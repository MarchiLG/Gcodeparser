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
    assert res.stats["bbox"][1] < -10  # várias linhas, descendo em Y− (4º quadrante)


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


# ---------------- quadrante / rotação / quebra pelo curso ----------------
def bbox_of(text="Olá, Mundo! " * 6, **kw):
    strokes = layout_text(text, load_font("futural"), LayoutOptions(**kw))
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    return min(xs), min(ys), max(xs), max(ys)


@pytest.mark.parametrize("q,sx,sy", [(1, 1, 1), (2, -1, 1), (3, -1, -1), (4, 1, -1)])
def test_quadrant_signs(q, sx, sy):
    x0, y0, x1, y1 = bbox_of(quadrant=q, travel=(200, 200))
    assert (x0 >= -1e-9 and x1 > 0) if sx > 0 else (x1 <= 1e-9 and x0 < 0)
    assert (y0 >= -1e-9 and y1 > 0) if sy > 0 else (y1 <= 1e-9 and y0 < 0)


def test_default_is_fourth_quadrant_and_text_starts_at_origin():
    x0, y0, x1, y1 = bbox_of("Hi", travel=(200, 200), margin=5)
    assert x0 >= 5 - 1e-9 and y1 == pytest.approx(-5)   # canto sup. esquerdo a 5 mm da origem


def test_wrap_follows_travel_x():
    x0, y0, x1, y1 = bbox_of(size=6, travel=(100, 300))
    assert x1 <= 100 + 1e-6 and y0 < -12   # quebrou em várias linhas


def test_wrap_changes_with_font_size():
    small = bbox_of(size=4, travel=(100, 500))
    big = bbox_of(size=10, travel=(100, 500))
    assert big[1] < small[1] < 0   # fonte maior => mais linhas


def test_rotation_90_wraps_against_travel_y():
    x0, y0, x1, y1 = bbox_of(size=6, travel=(300, 100), rotation=90)
    assert y1 - y0 <= 100 + 1e-6 and x1 - x0 > 12   # texto corre ao longo de Y


def test_rotation_diagonal_fits_travel():
    x0, y0, x1, y1 = bbox_of(size=6, travel=(120, 150), rotation=30)
    assert x1 - x0 <= 120 + 1e-6 and y1 - y0 <= 150 + 1e-6


def test_explicit_width_overrides_travel():
    x0, y0, x1, y1 = bbox_of(size=6, travel=(500, 500), max_width=60)
    assert x1 <= 60 + 1e-6


def test_bbox_warning_is_quadrant_aware():
    strokes = [[(0, 0), (-10, 5)]]
    assert generate(strokes, GcodeOptions(quadrant=3)).warnings   # Y>0 fora do 3º
    assert not generate([[(0, 0), (-10, -5)]], GcodeOptions(quadrant=3)).warnings
    assert not generate([[(0, 0), (10, -5)]], GcodeOptions(quadrant=4)).warnings


# ---------------- caneta por servo (PWM do spindle) ----------------
def servo(**kw):
    strokes = layout_text("Oi", load_font("futural"), LayoutOptions())
    return generate(strokes, GcodeOptions(pen="servo", pen_up=800, pen_down=250, pen_dwell=0.3, **kw))


def test_servo_uses_spindle_not_z():
    g = servo().gcode
    assert "Z" not in "".join(l.split(";")[0] for l in g.splitlines())
    ms = [l for l in g.splitlines() if l.startswith("M")]
    assert set(ms) == {"M3 S800", "M3 S250"} and ms[0] == "M3 S800" and ms[-1] == "M3 S800"
    assert not any(l.startswith("M5") for l in g.splitlines())


def test_servo_dwells_after_every_pen_change():
    lines = [l for l in servo().gcode.splitlines() if l and not l.startswith(";")]
    for i, l in enumerate(lines):
        if l.startswith("M3"):
            assert lines[i + 1] == "G4 P0.3"


def test_servo_writing_only_with_pen_down():
    down = False
    for l in servo().gcode.splitlines():
        if l == "M3 S250":
            down = True
        elif l == "M3 S800":
            down = False
        elif l.startswith("G0 X"):
            assert not down
        elif l.startswith("G1 X"):
            assert down


def test_servo_ignores_z_validation_and_validates_s():
    generate([[(0, 0), (1, 1)]], GcodeOptions(pen="servo", zmin=5, zmax=1))   # Z irrelevante
    with pytest.raises(ValueError):
        generate([[(0, 0), (1, 1)]], GcodeOptions(pen="servo", pen_up=-1))
    with pytest.raises(ValueError):
        generate([[(0, 0), (1, 1)]], GcodeOptions(pen="laser"))


def test_servo_s_above_spindle_max_warns():
    assert any("$30" in w for w in servo(spindle_max=500).warnings)
