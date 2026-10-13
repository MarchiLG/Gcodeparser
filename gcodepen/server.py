"""Servidor HTTP local (stdlib) com API JSON + interface em web/."""
from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .fonts import HERSHEY_DEFAULT, hershey_names, load_font, system_fonts
from .gcode import GcodeOptions, generate
from .grbl import Grbl, GrblError, list_ports
from .layout import LayoutOptions, layout_text
from .voice import AIError

_log: list = []      # (seq, tipo, texto) — console serial incremental
_seq = [0]
_log_lock = threading.Lock()


def _on_line(kind: str, text: str):
    with _log_lock:
        _seq[0] += 1
        _log.append((_seq[0], kind, text))
        del _log[:-500]


grbl = Grbl(on_line=_on_line)
ALLOWED_HOSTS: set[str] = set()

WEB = Path(__file__).resolve().parent.parent / "web"
_font_cache: dict[str, object] = {}


def _font(spec: str):
    if spec not in _font_cache:
        _font_cache[spec] = load_font(spec)
    return _font_cache[spec]


def _num(d: dict, key: str, default, lo=None, hi=None):
    v = d.get(key, default)
    if v is None or v == "":
        return default
    v = float(v)
    if lo is not None and v < lo or hi is not None and v > hi:
        raise ValueError(f"'{key}' fora do intervalo permitido")
    return v


def _gcode_opts(req: dict) -> GcodeOptions:
    return GcodeOptions(
        zmin=_num(req, "zmin", -1.0), zmax=_num(req, "zmax", 3.0),
        feed_xy=_num(req, "feed", 400.0, 1, 100000), feed_z=_num(req, "zfeed", 100.0, 1, 100000),
        travel_feed=_num(req, "travel_feed", None, 1, 100000),
        zero=bool(req.get("zero")), optimize=bool(req.get("optimize", True)),
    )


def build_job(req: dict):
    """Converte o JSON da UI em (strokes, GcodeResult)."""
    text = str(req.get("text", ""))
    if len(text) > 200_000:
        raise ValueError("Texto muito grande")
    spec = req.get("font") or HERSHEY_DEFAULT
    if spec.startswith("sys:"):
        spec = system_fonts().get(spec[4:], "")
        if not spec:
            raise ValueError("Fonte do sistema não encontrada")
    font = _font(spec)
    lopts = LayoutOptions(
        size=_num(req, "size", 8.0, 0.5, 500),
        line_spacing=_num(req, "line_spacing", 1.0, 0.3, 10),
        letter_spacing=_num(req, "letter_spacing", 0.0, -0.5, 5),
        align=req.get("align", "left") if req.get("align") in ("left", "center", "right") else "left",
        max_width=_num(req, "width", None, 1, 5000),
        margin=_num(req, "margin", 0.0, 0, 1000),
    )
    gopts = _gcode_opts(req)
    strokes = layout_text(text, font, lopts)
    return generate(strokes, gopts)


class Handler(BaseHTTPRequestHandler):
    server_version = "GCodePen/0.1"

    def log_message(self, fmt, *args):  # silencioso
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 50_000_000:
            raise ValueError("Corpo da requisição muito grande")
        return json.loads(self.rfile.read(n) or b"{}")

    def _host_ok(self) -> bool:
        """Bloqueia DNS-rebinding e POSTs de outras origens (o servidor move uma máquina!)."""
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin.split("://", 1)[-1] in ALLOWED_HOSTS

    def do_GET(self):
        if not self._host_ok():
            return self._json({"error": "host não permitido"}, 403)
        path = self.path.split("?", 1)[0]
        if path == "/api/ai/status":
            from . import voice
            return self._json({"enabled": voice.enabled()})
        if path == "/api/serial/ports":
            return self._json({"ports": list_ports()})
        if path == "/api/serial/status":
            return self._serial_status()
        if path == "/api/fonts":
            return self._json({"hershey": hershey_names(), "default": HERSHEY_DEFAULT,
                               "system": list(system_fonts().keys())})
        rel = "index.html" if path == "/" else path.lstrip("/")
        f = (WEB / rel).resolve()
        if WEB not in f.parents or not f.is_file():
            self.send_error(404)
            return
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(f.name)[0] or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serial_status(self):
        since = 0
        if "since=" in self.path:
            try:
                since = int(self.path.split("since=", 1)[1].split("&")[0])
            except ValueError:
                pass
        if grbl.connected:
            try:
                grbl.query_status()
            except GrblError:
                pass
        with _log_lock:
            log = [e for e in _log if e[0] > since]
        return self._json({"connected": grbl.connected, "banner": grbl.banner, "status": grbl.status,
                           "progress": grbl.progress(), "log": log, "seq": _seq[0],
                           "settings": grbl.settings})

    def _serial_post(self, path: str, req: dict):
        act = path.rsplit("/", 1)[1]
        if act == "connect":
            grbl.connect(str(req["device"]), int(req.get("baud", 115200)))
        elif act == "disconnect":
            grbl.disconnect()
        elif act == "stream":
            gcode = req.get("gcode") or build_job(req).gcode
            grbl.start_stream(gcode)
        elif act == "pause":
            grbl.hold()
        elif act == "resume":
            grbl.resume()
        elif act == "stop":
            grbl.stop()
        elif act == "jog":
            grbl.jog(float(req.get("x", 0)), float(req.get("y", 0)), float(req.get("z", 0)),
                     float(req.get("feed", 500)))
        elif act == "jogcancel":
            grbl.jog_cancel()
        elif act == "home":
            grbl.send_line("$H", wait=60)
        elif act == "unlock":
            grbl.send_line("$X")
        elif act == "zero":   # define o zero de trabalho (não altera $$): eixos em req["axes"], ex. "XY"
            axes = "".join(a for a in str(req.get("axes", "XY")).upper() if a in "XYZ")
            if axes:
                grbl.send_line("G92 " + " ".join(f"{a}0" for a in axes))
        elif act == "send":   # linha avulsa, ex.: "G0 Z3"
            line = str(req.get("line", "")).strip()
            if not line or len(line) > 80 or "\n" in line:
                raise ValueError("linha inválida")
            grbl.send_line(line)
        else:
            raise KeyError(act)
        return {"ok": True}

    def do_POST(self):
        if not self._host_ok():
            return self._json({"error": "host não permitido"}, 403)
        path = self.path.split("?", 1)[0]
        try:
            req = self._body()
            if path == "/api/transcribe":
                import base64

                from . import voice
                text = voice.transcribe(base64.b64decode(req["data"]), req.get("mime", "audio/wav"))
                return self._json({"text": text})
            if path == "/api/draw":
                from . import voice
                strokes = voice.fit_strokes(voice.draw(str(req["prompt"])), _num(req, "draw_size", 80, 5, 500),
                                            _num(req, "margin", 0.0, 0, 1000))
                res = generate(strokes, _gcode_opts(req))
                return self._json({"gcode": res.gcode, "strokes": res.strokes,
                                   "stats": res.stats, "warnings": res.warnings})
            if path == "/api/pdf":
                import base64

                from .pdfio import extract_pages
                pages = extract_pages(base64.b64decode(req["data"]))
                return self._json({"pages": pages})
            if path.startswith("/api/serial/"):
                return self._json(self._serial_post(path, req))
            if path == "/api/generate":
                res = build_job(req)
                return self._json({"gcode": res.gcode, "strokes": res.strokes,
                                   "stats": res.stats, "warnings": res.warnings})
            return self._json({"error": "rota inexistente"}, 404)
        except AIError as e:
            return self._json({"error": str(e)}, 502)
        except GrblError as e:
            return self._json({"error": str(e)}, 409)
        except (ValueError, KeyError, TypeError, OSError) as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"erro interno: {e}"}, 500)


def serve(host: str = "127.0.0.1", port: int = 8000):
    ALLOWED_HOSTS.update({f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"})
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"GCodePen em http://{host}:{port}  (Ctrl+C para sair)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        grbl.disconnect()


if __name__ == "__main__":
    serve()
