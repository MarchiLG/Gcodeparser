import threading
import time

from gcodepen.grbl import RX_BUFFER, Grbl, clean_gcode, parse_status


class FakeGrbl:
    """Porta serial falsa: consome linhas em ritmo lento e responde ok/error,
    verificando que o buffer RX nunca estoura."""

    def __init__(self, error_on=None, delay=0.002):
        self.rx = bytearray()      # bytes ainda "no buffer" da placa
        self.out = bytearray()     # bytes que a placa "enviou" ao PC
        self.max_buffer = 0
        self.lines = []
        self.realtime = []
        self.error_on = error_on
        self.delay = delay
        self._lock = threading.Lock()
        self._closed = False
        threading.Thread(target=self._run, daemon=True).start()

    def write(self, data):
        with self._lock:
            for b in data:
                if b in (ord("?"), ord("!"), ord("~"), 0x18, 0x85):
                    self.realtime.append(b)
                    if b == ord("?"):
                        self.out += b"<Idle|MPos:1.000,2.000,3.000|FS:0,0>\r\n"
                else:
                    self.rx.append(b)
            self.max_buffer = max(self.max_buffer, len(self.rx))

    def read(self, n):
        time.sleep(0.005)
        with self._lock:
            d, self.out = bytes(self.out[:n]), self.out[n:]
        return d

    def close(self):
        self._closed = True

    def _run(self):
        while not self._closed:
            time.sleep(self.delay)
            with self._lock:
                if b"\n" in self.rx:
                    i = self.rx.index(b"\n")
                    line = bytes(self.rx[:i]).decode()
                    del self.rx[: i + 1]
                    self.lines.append(line)
                    self.out += (b"error:20\r\n" if line == self.error_on else b"ok\r\n")


def make(**kw):
    fake = FakeGrbl(**kw)
    g = Grbl(port=fake)
    g.attach()
    return fake, g


def wait(cond, t=5):
    t0 = time.time()
    while not cond() and time.time() - t0 < t:
        time.sleep(0.01)
    assert cond()


def test_stream_respects_rx_buffer():
    fake, g = make()
    gcode = "\n".join(f"G1 X{i}.123 Y{i}.456 F400" for i in range(200))
    g.start_stream(gcode)
    wait(lambda: not g.running)
    assert fake.max_buffer <= RX_BUFFER
    assert len(fake.lines) == 200 and g.acked == 200
    g.disconnect()


def test_error_is_recorded_and_stream_continues():
    fake, g = make(error_on="G1 X5")
    g.start_stream("G1 X1\nG1 X5\nG1 X9")
    wait(lambda: not g.running)
    assert g.acked == 3 and len(g.errors) == 1 and "error:20" in g.errors[0]
    g.disconnect()


def test_pause_resume_stop():
    fake, g = make(delay=0.01)
    g.start_stream("\n".join(f"G1 X{i}" for i in range(300)))
    time.sleep(0.1)
    g.hold()
    sent = g.sent
    time.sleep(0.4)
    assert g.sent <= sent + 25  # só o que já cabia no buffer
    g.resume()
    g.stop()
    wait(lambda: not g.running)
    assert ord("!") in fake.realtime and 0x18 in fake.realtime
    g.disconnect()


def test_status_parse_and_wpos():
    s = parse_status("<Idle|MPos:1.000,2.000,3.000|FS:0,0>")
    assert s["state"] == "Idle" and s["mpos"] == [1.0, 2.0, 3.0]
    assert parse_status("<Run|WPos:0.0,0.0,-1.0>")["wpos"][2] == -1.0
    assert parse_status("ok") is None


def test_clean_gcode_strips_comments():
    assert clean_gcode("G21 ; mm\n\n(x) G90\n; só comentário\n") == ["G21", "G90"]


def test_send_line_and_jog():
    fake, g = make()
    g.jog(x=1, z=-0.5, feed=300)
    assert fake.lines[-1] == "$J=G91 G21 X1 Z-0.5 F300"
    g.disconnect()


def test_jog_hold_streams_many_commands_then_cancels():
    fake, g = make()
    g.jog_hold(1, 0, 0, 600)
    for _ in range(3):                 # keep-alive com a mesma direção não reinicia a thread
        time.sleep(0.3)
        g.jog_hold(1, 0, 0, 600)
    n = len([l for l in fake.lines if l.startswith("$J=")])
    assert n >= 4, fake.lines          # vários comandos, não um só
    assert all(l == "$J=G91 G21 X1.5000 F600" for l in fake.lines if l.startswith("$J="))
    assert 0x85 not in fake.realtime
    g.jog_stop()
    assert 0x85 in fake.realtime and not g.jogging
    sent = len(fake.lines)
    time.sleep(0.3)
    assert len(fake.lines) == sent     # nada mais é enviado depois de soltar
    g.disconnect()


def test_jog_hold_stops_without_keepalive():
    fake, g = make()
    g.jog_hold(0, -1, 0, 300)
    wait(lambda: not g.jogging, t=3)   # expira sozinho (cliente sumiu)
    assert 0x85 in fake.realtime
    g.disconnect()


def test_jog_hold_throttles_to_lookahead():
    fake, g = make()
    g.jog_hold(1, 1, 0, 600)
    time.sleep(0.5)
    n = len([l for l in fake.lines if l.startswith("$J=")])
    assert n <= 6                      # ~0.5 s / 0.15 s + lookahead, não centenas
    g.jog_stop()
    g.disconnect()


def test_send_line_refused_while_jog_hold():
    import pytest
    from gcodepen.grbl import GrblError
    fake, g = make()
    g.jog_hold(1, 0, 0, 600)
    with pytest.raises(GrblError):
        g.send_line("G0 X0")
    g.jog_stop()
    g.disconnect()
