import json

import pytest

from gcodepen import voice
from gcodepen.voice import AIError, fit_strokes, parse_strokes


def test_parse_strokes_clamps_and_normalizes():
    raw = 'texto ```json\n{"strokes": [[[0,0],[1000,500]], [[2000,-5],[10,10]], [[1,1]]]}\n```'
    st = parse_strokes(raw)
    assert len(st) == 2  # stroke de 1 ponto descartado
    assert st[0] == [(0.0, 0.0), (1.0, 0.5)]
    assert st[1][0] == (1.0, 0.0)  # clamp


@pytest.mark.parametrize("raw", ["sem json", '{"strokes": []}', '{"x": 1}', '{"strokes": [[["a","b"],[1,2]]]}'])
def test_parse_strokes_invalid(raw):
    with pytest.raises(AIError):
        parse_strokes(raw)


def test_fit_strokes():
    out = fit_strokes([[(0.2, 0.2), (0.6, 0.4)]], 100, margin=5)
    xs = [p[0] for p in out[0]]
    ys = [p[1] for p in out[0]]
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((5, 105, 5, 55))


def test_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert not voice.enabled()
    with pytest.raises(AIError):
        voice.transcribe(b"x")


def test_transcribe_and_draw_request_shape(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    seen = {}

    class R:
        def __init__(self, text): self.text = text
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, *a): return json.dumps({"candidates": [{"content": {"parts": [{"text": self.text}]}}]}).encode()

    def fake_urlopen(req, timeout=0):
        seen["url"], seen["key"], seen["body"] = req.full_url, req.headers.get("X-goog-api-key"), json.loads(req.data)
        return R(seen.get("reply", "olá mundo"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert voice.transcribe(b"RIFF....") == "olá mundo"
    assert seen["key"] == "k" and "key=" not in seen["url"]
    assert seen["body"]["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "audio/wav"
    seen["reply"] = '{"strokes": [[[0,0],[1000,1000]]]}'
    assert voice.draw("linha") == [[(0.0, 0.0), (1.0, 1.0)]]
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_pdf_extract(tmp_path):
    from gcodepen.pdfio import extract_pages
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 << /Type /Font "
            b"/Subtype /Type1 /BaseFont /Helvetica >> >> >> /Contents 4 0 R >>"]
    stream = b"BT /F1 12 Tf 20 200 Td (Ola PDF) Tj ET"
    objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    assert extract_pages(out) == ["Ola PDF"]
    with pytest.raises(Exception):
        extract_pages(b"not a pdf")
