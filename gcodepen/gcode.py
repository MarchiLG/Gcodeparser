"""Strokes (mm) -> G-code GRBL para plotter de caneta.

Convenção: Z mínimo = caneta escrevendo, Z máximo = caneta levantada.
Só usa parâmetros padrão do GRBL: nenhum `$xx=`, nenhum M3/M5; apenas
G21 G90 G17 G94 e G0/G1 em X/Y/Z.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .fonts import Point, Stroke

# Padrões de fábrica do GRBL 1.1 ($$): máx. de avanço e curso por eixo.
GRBL_DEFAULTS = {
    "max_rate": (500.0, 500.0, 500.0),   # $110-$112 mm/min
    "max_travel": (200.0, 200.0, 200.0),  # $130-$132 mm
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


@dataclass
class GcodeResult:
    gcode: str
    strokes: list[Stroke]          # na ordem final de execução
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def validate(opts: GcodeOptions) -> None:
    if not opts.zmin < opts.zmax:
        raise ValueError(f"Z mín ({opts.zmin}) precisa ser menor que Z máx ({opts.zmax})")
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

    warnings: list[str] = []
    if strokes:
        xs = [p[0] for s in strokes for p in s]
        ys = [p[1] for s in strokes for p in s]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        if bbox[2] > opts.max_travel[0] or bbox[3] > opts.max_travel[1] or bbox[0] < 0 or bbox[1] < 0:
            warnings.append(
                f"Desenho ocupa X {bbox[0]:.1f}..{bbox[2]:.1f} / Y {bbox[1]:.1f}..{bbox[3]:.1f} mm; "
                f"o curso padrão do GRBL ($130/$131) é {opts.max_travel[0]:g} x {opts.max_travel[1]:g} mm."
            )
    else:
        bbox = (0.0, 0.0, 0.0, 0.0)
        warnings.append("Nada para desenhar (texto vazio ou sem glifos).")
    if opts.feed_xy > opts.max_rate[0]:
        warnings.append(f"Avanço {opts.feed_xy:g} acima do $110 padrão ({opts.max_rate[0]:g}); o GRBL limita sozinho.")
    if abs(opts.zmax - opts.zmin) > opts.max_travel[2]:
        warnings.append("Curso Z maior que $132 padrão.")

    lines = [
        "; GCodePen — caneta: Z{} escreve / Z{} levantada".format(f(opts.zmin), f(opts.zmax)),
        "G21 ; mm",
        "G90 ; absoluto",
        "G17",
        "G94 ; avanço em mm/min",
    ]
    if opts.zero:
        lines.append("G92 X0 Y0 ; posição atual = origem")
    lines.append(f"G0 Z{f(opts.zmax)}")

    pos = (0.0, 0.0)
    draw_len = travel_len = 0.0
    lifts = 0
    tf = f" F{f(opts.travel_feed)}" if opts.travel_feed else ""
    travel_cmd = "G1" if opts.travel_feed else "G0"
    for s in strokes:
        travel_len += math.dist(pos, s[0])
        lines.append(f"{travel_cmd} {xy(s[0])}{tf}")
        lines.append(f"G1 Z{f(opts.zmin)} F{f(opts.feed_z)}")
        first = True
        for a, b in zip(s, s[1:]):
            draw_len += math.dist(a, b)
            lines.append(f"G1 {xy(b)} F{f(opts.feed_xy)}" if first else f"G1 {xy(b)}")
            first = False
        lines.append(f"G0 Z{f(opts.zmax)}")
        lifts += 1
        pos = s[-1]
    travel_len += math.dist(pos, (0.0, 0.0))
    lines.append(f"{travel_cmd} X0 Y0{tf}")
    lines.append("; fim")

    rapid = opts.max_rate[0]
    seconds = (draw_len / opts.feed_xy + (travel_len / (opts.travel_feed or rapid))
               + lifts * (abs(opts.zmax - opts.zmin) / opts.feed_z)) * 60
    stats = {
        "strokes": len(strokes),
        "lines": len(lines),
        "draw_mm": round(draw_len, 1),
        "travel_mm": round(travel_len, 1),
        "est_seconds": round(seconds),
        "bbox": [round(v, 2) for v in bbox],
    }
    return GcodeResult("\n".join(lines) + "\n", strokes, warnings, stats)
