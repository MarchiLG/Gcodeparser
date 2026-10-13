import re

import pytest

from gcodepen.fonts import load_font
from gcodepen.gcode import GcodeOptions, generate
from gcodepen.layout import LayoutOptions, layout_text


def make(text="Olá, Mundo!", **kw):
    strokes = layout_text(text, load_font("futural"), LayoutOptions(**kw))
    return generate(strokes, GcodeOptions(zmin=-1.5, zmax=2.5))


def z_values(gcode):
    return [float(m) for m in re.findall(r"Z(-?[\d.]+)", gcode)]


def test_z_only_between_min_and_max():
    zs = z_values(make().gcode)
    assert zs and set(zs) == {-1.5, 2.5}


def test_starts_and_ends_pen_up():
    lines = [l for l in make().gcode.splitlines() if l and not l.startswith(";")]
    zl = [l for l in lines if "Z" in l]
    assert zl[0].startswith("G0 Z2.5") and zl[-1].startswith("G0 Z2.5")
    assert lines[-1] == "G0 X0 Y0"


def test_no_forbidden_commands():
    g = make().gcode
    assert "$" not in g.replace("; ", "")  # nenhuma config GRBL
    assert not re.search(r"\bM0?[345]\b", g)
    assert all(re.match(r"^(G0|G1|G17|G21|G90|G94|G92|;)", l) for l in g.splitlines() if l)


def test_writing_moves_only_with_pen_down():
    pen_down = False
    for l in make().gcode.splitlines():
        if l.startswith("G1 Z"):
            pen_down = True
        elif l.startswith("G0 Z"):
            pen_down = False
        elif l.startswith("G0 X"):
            assert not pen_down
        elif l.startswith("G1 X"):
            assert pen_down


def test_invalid_z():
    with pytest.raises(ValueError):
        generate([[(0, 0), (1, 1)]], GcodeOptions(zmin=2, zmax=1))


def test_bbox_warning_when_beyond_travel():
    res = make("x" * 80, size=10)
    assert any("curso" in w for w in res.warnings)


def test_empty_text():
    res = make("")
    assert res.stats["strokes"] == 0 and res.warnings


def test_wrapping_respects_width():
    res = make("palavra " * 30, size=5, max_width=60)
    xmax = res.stats["bbox"][2]
    assert xmax <= 60 + 1e-6
    assert res.stats["bbox"][3] > 10  # várias linhas


def test_accents_add_strokes():
    n_a = len(layout_text("a", load_font("futural")))
    n_acc = len(layout_text("á", load_font("futural")))
    assert n_acc > n_a


def test_ttf_font():
    from gcodepen.fonts import system_fonts
    for path in system_fonts().values():
        try:
            font = load_font(path)
        except ValueError:
            continue
        strokes = layout_text("Ola", font)
        assert strokes
        return
    pytest.skip("sem TTF utilizável")
