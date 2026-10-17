"""Controle direto da GRBL 1.1 via serial (sem UGS).

Streaming com *character counting*: nunca deixa mais de 127 bytes pendentes
no buffer RX da placa; cada `ok`/`error:N` libera o comprimento da linha
mais antiga. Comandos de tempo real (`?`, `!`, `~`, 0x18, jog cancel) são
enviados fora da fila.
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections import deque
from typing import Callable

RX_BUFFER = 127  # bytes úteis do buffer serial da GRBL (128 - 1)
BAUD = 115200

# Jog contínuo (botão preso): comandos `$J=` curtos, mantidos ~JOG_LOOKAHEAD s à frente do movimento.
JOG_SEG_SECONDS = 0.15   # movimento coberto por comando
JOG_LOOKAHEAD = 0.35     # quanto movimento fica enfileirado na placa (limita a "inércia" ao soltar)
JOG_KEEPALIVE = 0.7      # sem keep-alive do cliente por esse tempo => cancela sozinho

_STATUS_RE = re.compile(r"<([A-Za-z]+)(?::\d+)?\|(.*?)>")


def list_ports() -> list[dict]:
    from serial.tools import list_ports as lp
    # esconde as /dev/ttyS* "fantasma" (hwid n/a); portas USB têm hwid real
    return [{"device": p.device, "description": p.description}
            for p in lp.comports() if p.hwid and p.hwid != "n/a"]


def parse_status(line: str) -> dict | None:
    """'<Idle|MPos:0.000,0.000,0.000|FS:0,0>' -> {'state','mpos','wpos',...}"""
    m = _STATUS_RE.match(line.strip())
    if not m:
        return None
    out: dict = {"state": m.group(1)}
    for field in m.group(2).split("|"):
        k, _, v = field.partition(":")
        if k in ("MPos", "WPos", "WCO"):
            try:
                out[k.lower()] = [float(x) for x in v.split(",")]
            except ValueError:
                pass
        elif k in ("FS", "Bf", "Ov"):
            out[k.lower()] = [float(x) for x in v.split(",") if x]
    return out


def clean_gcode(text: str) -> list[str]:
    """Remove comentários e linhas vazias; mantém `$` (comandos do sistema)."""
    out = []
    for raw in text.splitlines():
        line = re.sub(r"\(.*?\)", "", raw.split(";", 1)[0]).strip()
        if line:
            out.append(line)
    return out


class GrblError(Exception):
    pass


class Grbl:
    def __init__(self, port=None, on_line: Callable[[str, str], None] | None = None):
        """`port` já aberto (objeto estilo pyserial) — usado em testes; senão use connect()."""
        self._ser = port
        self._on_line = on_line or (lambda kind, text: None)
        self._lock = threading.RLock()
        self._reader: threading.Thread | None = None
        self._streamer: threading.Thread | None = None
        self._stop_reader = threading.Event()
        self.status: dict = {}
        self.settings: dict[str, float] = {}
        self.banner = ""
        self.log: deque = deque(maxlen=500)
        # estado do streaming
        self._pending: deque[int] = deque()   # tamanhos das linhas aguardando ok
        self._queue: list[str] = []
        self.total = 0
        self.sent = 0
        self.acked = 0
        self.errors: list[str] = []
        self.paused = False
        self.running = False
        self._abort = False
        self._cond = threading.Condition(self._lock)
        self._sync_waiters: list[threading.Event] = []
        # jog contínuo
        self._jog_lock = threading.Lock()
        self._jog_thread: threading.Thread | None = None
        self._jog_halt = threading.Event()
        self._jog_key: tuple | None = None
        self._jog_deadline = 0.0

    # ---------------- conexão ----------------
    def connect(self, device: str, baud: int = BAUD, timeout: float = 4.0):
        import serial
        self.disconnect()
        self._ser = serial.Serial(device, baud, timeout=0.1, write_timeout=2)
        self._start_reader()
        self.soft_reset()
        t0 = time.time()
        while time.time() - t0 < timeout and not self.banner:
            time.sleep(0.05)
        if not self.banner:
            raise GrblError("Sem resposta da GRBL (banner 'Grbl 1.1…' não recebido). Verifique porta/baud.")
        self.refresh_settings()

    def attach(self):
        """Usa a porta passada no construtor (testes)."""
        self._start_reader()

    def disconnect(self):
        self._jog_halt.set()
        self._abort = True
        self._stop_reader.set()
        with self._cond:
            self._cond.notify_all()
        for t in (self._streamer, self._reader):
            if t and t.is_alive() and t is not threading.current_thread():
                t.join(timeout=1)
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        self.running = False
        self.banner = ""

    @property
    def connected(self) -> bool:
        return self._ser is not None

    def _start_reader(self):
        self._stop_reader.clear()
        self._abort = False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # ---------------- leitura ----------------
    def _emit(self, kind: str, text: str):
        self.log.append((kind, text))
        self._on_line(kind, text)

    def _read_loop(self):
        buf = b""
        while not self._stop_reader.is_set() and self._ser:
            try:
                chunk = self._ser.read(256)
            except Exception as e:  # porta removida
                self._emit("err", f"serial: {e}")
                break
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("ascii", "replace").strip()
                if line:
                    self._handle_line(line)

    def _handle_line(self, line: str):
        if line == "ok" or line.startswith("error:"):
            with self._cond:
                if self._pending:
                    self._pending.popleft()
                self.acked += 1
                if line != "ok":
                    self.errors.append(f"linha {self.acked}: {line}")
                    self._emit("err", line)
                else:
                    self._emit("rx", line)
                self._cond.notify_all()
            return
        st = parse_status(line)
        if st:
            if "wco" in st:
                self._wco = st["wco"]
            elif "mpos" in st and getattr(self, "_wco", None):
                st["wpos"] = [m - o for m, o in zip(st["mpos"], self._wco)]
            elif "wpos" in st and getattr(self, "_wco", None):
                st["mpos"] = [w + o for w, o in zip(st["wpos"], self._wco)]
            self.status = {**self.status, **st}
            return
        if line.startswith("Grbl "):
            self.banner = line
            with self._cond:  # reset da placa: descarta o que estava em voo
                self._pending.clear()
            self._emit("rx", line)
            return
        m = re.match(r"\$(\d+)=([-\d.]+)", line)
        if m:
            self.settings[m.group(1)] = float(m.group(2))
        if line.startswith("ALARM:"):
            self._emit("err", line)
            return
        self._emit("rx", line)

    # ---------------- escrita ----------------
    def _write(self, data: bytes):
        if not self._ser:
            raise GrblError("Não conectado")
        with self._lock:
            self._ser.write(data)

    def realtime(self, ch: bytes):
        self._write(ch)

    def query_status(self):
        self.realtime(b"?")

    def soft_reset(self):
        self.realtime(b"\x18")

    def hold(self):
        self.realtime(b"!")
        self.paused = True

    def resume(self):
        self.realtime(b"~")
        self.paused = False
        with self._cond:
            self._cond.notify_all()

    def stop(self):
        """Aborta: para o stream, hold + soft reset. A caneta fica onde estiver — suba o Z depois."""
        self._abort = True
        self._jog_halt.set()
        try:
            self.realtime(b"!")
            time.sleep(0.1)
            self.realtime(b"\x18")
        finally:
            with self._cond:
                self._pending.clear()
                self._cond.notify_all()
            self.paused = False

    def send_line(self, line: str, wait: float = 5.0) -> list[str]:
        """Envia uma linha avulsa (jog, $H, $X, G92…) e espera o ok/error. Não use durante stream."""
        if self.running:
            raise GrblError("Há um job em execução")
        if self.jogging:
            raise GrblError("Jog contínuo em andamento")
        before = len(self.log)
        n = len(line) + 1
        with self._cond:
            self._pending.append(n)
            target = self.acked + 1
        self._write(line.encode("ascii") + b"\n")
        self._emit("tx", line)
        t0 = time.time()
        with self._cond:
            while self.acked < target and time.time() - t0 < wait:
                self._cond.wait(0.1)
            if self.acked < target:
                raise GrblError(f"Timeout aguardando ok para '{line}'")
        return [t for _, t in list(self.log)[before:]]

    def refresh_settings(self):
        self.settings.clear()
        try:
            self.send_line("$$")
        except GrblError:
            pass

    def jog(self, x=0.0, y=0.0, z=0.0, feed=500.0):
        axes = " ".join(f"{a}{v:g}" for a, v in (("X", x), ("Y", y), ("Z", z)) if v)
        if not axes:
            return
        self.send_line(f"$J=G91 G21 {axes} F{feed:g}")

    def jog_cancel(self):
        self.realtime(b"\x85")

    @property
    def jogging(self) -> bool:
        t = self._jog_thread
        return bool(t and t.is_alive())

    def jog_hold(self, x: float = 0, y: float = 0, z: float = 0, feed: float = 500.0):
        """Jog contínuo na direção (x, y, z) enquanto o cliente renovar a chamada (keep-alive).

        Envia vários `$J=` curtos em segundo plano e, ao parar (jog_stop, falta de keep-alive
        ou erro da GRBL), manda o jog-cancel em tempo real (0x85): a placa freia e descarta o
        que ainda estava enfileirado. Chamar de novo com a mesma direção só renova o prazo."""
        if self.running:
            raise GrblError("Há um job em execução")
        mag = math.sqrt(x * x + y * y + z * z)
        if not mag:
            return
        key = (round(x / mag, 6), round(y / mag, 6), round(z / mag, 6), float(feed))
        with self._jog_lock:
            self._jog_deadline = time.monotonic() + JOG_KEEPALIVE
            if self.jogging and self._jog_key == key:
                return
        self.jog_stop()   # direção/avanço mudou (ou nada ativo)
        if not self.connected:
            raise GrblError("Não conectado")
        with self._jog_lock:
            self._jog_key = key
            self._jog_halt = threading.Event()
            self._jog_thread = threading.Thread(target=self._jog_loop, args=(self._jog_halt, key), daemon=True)
            self._jog_thread.start()

    def jog_stop(self):
        with self._jog_lock:
            t, halt = self._jog_thread, self._jog_halt
        halt.set()
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1)

    def _jog_loop(self, halt: threading.Event, key: tuple):
        dx, dy, dz, feed = key
        seg = max(feed / 60.0 * JOG_SEG_SECONDS, 0.01)
        axes = " ".join(f"{a}{v * seg:.4f}" for a, v in (("X", dx), ("Y", dy), ("Z", dz)) if v)
        line = f"$J=G91 G21 {axes} F{feed:g}"
        n = len(line) + 1
        errors0, sent, t_end = len(self.errors), 0, time.monotonic()
        try:
            while not halt.is_set() and self._ser and time.monotonic() < self._jog_deadline:
                if len(self.errors) > errors0:   # ex.: error:15 (limite), error:9 (alarme) — não inundar
                    break
                if t_end - time.monotonic() > JOG_LOOKAHEAD:
                    halt.wait(0.02)
                    continue
                with self._cond:
                    if sum(self._pending) + n > RX_BUFFER:
                        self._cond.wait(0.02)
                        continue
                    self._pending.append(n)
                self._write(line.encode("ascii") + b"\n")
                sent += 1
                t_end = max(t_end, time.monotonic()) + JOG_SEG_SECONDS
        except GrblError as e:
            self._emit("err", str(e))
        finally:
            if sent and self._ser:
                try:
                    self.jog_cancel()
                except GrblError:
                    pass

    # ---------------- streaming ----------------
    def start_stream(self, gcode: str):
        if self.running:
            raise GrblError("Já existe um job em execução")
        lines = clean_gcode(gcode)
        for ln in lines:
            if len(ln) > 80:
                raise GrblError(f"Linha longa demais para a GRBL (>80): {ln[:40]}…")
        self._queue = lines
        self.total, self.sent, self.acked = len(lines), 0, 0
        self.errors = []
        self._abort = False
        self.running = True
        self._streamer = threading.Thread(target=self._stream_loop, daemon=True)
        self._streamer.start()

    def _stream_loop(self):
        try:
            for line in self._queue:
                n = len(line) + 1
                with self._cond:
                    while not self._abort and (self.paused or sum(self._pending) + n > RX_BUFFER):
                        self._cond.wait(0.1)
                    if self._abort:
                        return
                    self._pending.append(n)
                self._write(line.encode("ascii") + b"\n")
                self._emit("tx", line)
                self.sent += 1
            with self._cond:  # espera o último ok
                while not self._abort and self._pending:
                    self._cond.wait(0.1)
        except GrblError as e:
            self._emit("err", str(e))
        finally:
            self.running = False

    def progress(self) -> dict:
        return {"total": self.total, "sent": self.sent, "acked": self.acked,
                "running": self.running, "paused": self.paused, "errors": self.errors[-5:]}
