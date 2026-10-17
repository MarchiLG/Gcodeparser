"""Strokes (mm) -> G-code GRBL para plotter de caneta.

Caneta controlada de duas formas (`GcodeOptions.pen`):
  * "z"     — eixo Z: Z mínimo = caneta escrevendo, Z máximo = levantada;
  * "servo" — servo no PWM do spindle: `M3 S<valor>` (+ `G4` p/ o servo chegar).
Só usa parâmetros padrão do GRBL: nenhum `$xx=`; G21 G90 G17 G94, G0/G1 em X/Y(/Z),
e M3/G4 apenas no modo servo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .fonts import Point, Stroke
from .layout import QUADRANT_SIGNS

# Padrões de fábrica do GRBL 1.1 ($$): máx. de avanço e curso por eixo.
GRBL_DEFAULTS = {
    "max_rate": (500.0, 500.0, 500.0),   # $110-$112 mm/min
    "max_travel": (200.0, 200.0, 200.0),  # $130-$132 mm
    "spindle_max": 1000.0,                # $30
}


@dataclass
class GcodeOptions:
    zmin: float = -1.0            # Z com a caneta no papel (escreve)
    zmax: float = 3.0             # Z com a caneta levantada (não escreve)
    feed_xy: float = 400.0        # G1 em X/Y (mm/min)
    feed_z: float = 100.0         # G1 descendo a caneta (mm/min)
    travel_feed: float | None = None  # deslocamento levantado; None = usa G0 (rápido)
    zero: bool = False            # emite G92 X0 Y0 no início
    optimize: bool = True         # reordena strokes (vizinho mais próximo)
    max_travel: tuple[float, float, float] = GRBL_DEFAULTS["max_travel"]
    max_rate: tuple[float, float, float] = GRBL_DEFAULTS["max_rate"]
    decimals: int = 3
    quadrant: int = 4             # região do curso que o desenho deve ocupar (1..4)
    pen: str = "z"                # "z" = caneta no eixo Z | "servo" = servo no PWM do spindle
    pen_up: float = 700.0         # servo: S com a caneta levantada
    pen_down: float = 300.0       # servo: S com a caneta no papel
    pen_dwell: float = 0.25       # servo: espera (s) após cada troca, p/ o servo chegar
    spindle_max: float = GRBL_DEFAULTS["spindle_max"]  # $30


@dataclass
class GcodeResult:
    gcode: str
    strokes: list[Stroke]          # na ordem final de execução
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def validate(opts: GcodeOptions) -> None:
    if opts.pen not in ("z", "servo"):
        raise ValueError("pen deve ser 'z' ou 'servo'")
    if opts.quadrant not in (1, 2, 3, 4):
        raise ValueError("quadrante deve ser 1, 2, 3 ou 4")
    if opts.pen == "z" and not opts.zmin < opts.zmax:
        raise ValueError(f"Z mín ({opts.zmin}) precisa ser menor que Z máx ({opts.zmax})")
    if opts.pen == "servo":
        if not (0 <= opts.pen_up <= 100000 and 0 <= opts.pen_down <= 100000):
            raise ValueError("S do servo fora de 0..100000")
        if not 0 <= opts.pen_dwell <= 10:
            raise ValueError("Espera do servo fora de 0..10 s")
    if opts.feed_xy <= 0 or opts.feed_z <= 0:
        raise ValueError("Avanços precisam ser positivos")


def order_strokes(strokes: list[Stroke], start: tuple[float, float] = (0.0, 0.0)) -> list[Stroke]:
    """Vizinho mais próximo, podendo inverter cada stroke. O(n²) — ok p/ milhares de strokes."""
    remaining = [list(s) for s in strokes if len(s) >= 2]
    out: list[Stroke] = []
    cx, cy = start
    while remaining:
        best_i, best_d, best_rev = 0, math.inf, False
        for i, s in enumerate(remaining):
            d0 = (s[0][0] - cx) ** 2 + (s[0][1] - cy) ** 2
            d1 = (s[-1][0] - cx) ** 2 + (s[-1][1] - cy) ** 2
            if d0 < best_d:
                best_i, best_d, best_rev = i, d0, False
            if d1 < best_d:
                best_i, best_d, best_rev = i, d1, True
        s = remaining.pop(best_i)
        if best_rev:
            s.reverse()
        out.append(s)
        cx, cy = s[-1]
    return out


def generate(strokes: list[Stroke], opts: GcodeOptions | None = None) -> GcodeResult:
    opts = opts or GcodeOptions()
    validate(opts)
    strokes = [s for s in strokes if len(s) >= 2]
    if opts.optimize:
        strokes = order_strokes(strokes)

    def f(v: float) -> str:
        t = f"{v:.{opts.decimals}f}"
        t = t.rstrip("0").rstrip(".") if "." in t else t
        return "0" if t in ("-0", "") else t

    def xy(p: Point) -> str:
        return f"X{f(p[0])} Y{f(p[1])}"

    servo = opts.pen == "servo"
    sx, sy = QUADRANT_SIGNS[opts.quadrant]
    warnings: list[str] = []
    if strokes:
        xs = [p[0] for s in strokes for p in s]
        ys = [p[1] for s in strokes for p in s]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        tol = 1e-6
        lo_x, hi_x = (0.0, opts.max_travel[0]) if sx > 0 else (-opts.max_travel[0], 0.0)
        lo_y, hi_y = (0.0, opts.max_travel[1]) if sy > 0 else (-opts.max_travel[1], 0.0)
        if bbox[0] < lo_x - tol or bbox[2] > hi_x + tol or bbox[1] < lo_y - tol or bbox[3] > hi_y + tol:
            warnings.append(
                f"Desenho ocupa X {bbox[0]:.1f}..{bbox[2]:.1f} / Y {bbox[1]:.1f}..{bbox[3]:.1f} mm; "
                f"o curso configurado é {opts.max_travel[0]:g} x {opts.max_travel[1]:g} mm "
                f"({opts.quadrant}º quadrante: X {lo_x:g}..{hi_x:g} / Y {lo_y:g}..{hi_y:g})."
            )
    else:
        bbox = (0.0, 0.0, 0.0, 0.0)
        warnings.append("Nada para desenhar (texto vazio ou sem glifos).")
    if opts.feed_xy > opts.max_rate[0]:
        warnings.append(f"Avanço {opts.feed_xy:g} acima do $110 padrão ({opts.max_rate[0]:g}); o GRBL limita sozinho.")
    if servo:
        if opts.pen_up == opts.pen_down:
            warnings.append("S com a caneta levantada e no papel são iguais: o servo não vai se mover.")
        if max(opts.pen_up, opts.pen_down) > opts.spindle_max:
            warnings.append(f"S acima do $30 ({opts.spindle_max:g}); o GRBL limita ao máximo.")
    elif abs(opts.zmax - opts.zmin) > opts.max_travel[2]:
        warnings.append("Curso Z maior que $132 padrão.")

    def pen_up() -> list[str]:
        if servo:
            return [f"M3 S{f(opts.pen_up)}"] + ([f"G4 P{f(opts.pen_dwell)}"] if opts.pen_dwell else [])
        return [f"G0 Z{f(opts.zmax)}"]

    def pen_down() -> list[str]:
        if servo:
            return [f"M3 S{f(opts.pen_down)}"] + ([f"G4 P{f(opts.pen_dwell)}"] if opts.pen_dwell else [])
        return [f"G1 Z{f(opts.zmin)} F{f(opts.feed_z)}"]

    lines = [
        "; GCodePen — caneta: servo S{} escreve / S{} levantada".format(f(opts.pen_down), f(opts.pen_up))
        if servo else
        "; GCodePen — caneta: Z{} escreve / Z{} levantada".format(f(opts.zmin), f(opts.zmax)),
        f"; {opts.quadrant}º quadrante",
        "G21 ; mm",
        "G90 ; absoluto",
        "G17",
        "G94 ; avanço em mm/min",
    ]
    if opts.zero:
        lines.append("G92 X0 Y0 ; posição atual = origem")
    lines += pen_up()

    pos = (0.0, 0.0)
    draw_len = travel_len = 0.0
    lifts = 0
    tf = f" F{f(opts.travel_feed)}" if opts.travel_feed else ""
    travel_cmd = "G1" if opts.travel_feed else "G0"
    for s in strokes:
        travel_len += math.dist(pos, s[0])
        lines.append(f"{travel_cmd} {xy(s[0])}{tf}")
        lines += pen_down()
        first = True
        for a, b in zip(s, s[1:]):
            draw_len += math.dist(a, b)
            lines.append(f"G1 {xy(b)} F{f(opts.feed_xy)}" if first else f"G1 {xy(b)}")
            first = False
        lines += pen_up()
        lifts += 1
        pos = s[-1]
    travel_len += math.dist(pos, (0.0, 0.0))
    lines.append(f"{travel_cmd} X0 Y0{tf}")
    lines.append("; fim" + (" (servo fica levantado; sem M5 p/ não soltar o servo)" if servo else ""))

    rapid = opts.max_rate[0]
    pen_time = lifts * (2 * opts.pen_dwell if servo else abs(opts.zmax - opts.zmin) / opts.feed_z * 60)
    seconds = (draw_len / opts.feed_xy + (travel_len / (opts.travel_feed or rapid))) * 60 + pen_time
    stats = {
        "strokes": len(strokes),
        "lines": len(lines),
        "draw_mm": round(draw_len, 1),
        "travel_mm": round(travel_len, 1),
        "est_seconds": round(seconds),
        "bbox": [round(v, 2) for v in bbox],
    }
    return GcodeResult("\n".join(lines) + "\n", strokes, warnings, stats)
