"""Texto -> strokes em mm.

Sistema de coordenadas de saída: eixos da máquina visto de cima (X para a direita,
Y para cima). O bloco de texto é montado "em pé" (primeira linha no topo), girado
por `rotation` e então transladado para dentro do `quadrant` escolhido, com o canto
mais próximo da origem a `margin` mm dela:

    2º (X−, Y+) | 1º (X+, Y+)
    ------------+------------
    3º (X−, Y−) | 4º (X+, Y−)   <- padrão: CNC em 4º quadrante, texto cresce para X+ e Y−
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .fonts import Font, Stroke

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1

QUADRANT_SIGNS = {1: (1, 1), 2: (-1, 1), 3: (-1, -1), 4: (1, -1)}


@dataclass
class LayoutOptions:
    size: float = 8.0            # altura da maiúscula, mm
    line_spacing: float = 1.0    # multiplicador sobre o line_height da fonte
    letter_spacing: float = 0.0  # extra entre letras, em alturas de maiúscula
    align: str = "left"          # left | center | right
    max_width: float | None = None  # largura da área p/ quebra de linha, mm (None = automática pelo `travel`)
    margin: float = 0.0          # distância do bloco à origem (e à borda oposta do curso), mm
    tab_size: int = 4
    travel: tuple[float, float] | None = None  # curso máx (X, Y) em mm; define a quebra automática
    rotation: float = 0.0        # graus, anti-horário visto de cima
    quadrant: int = 4            # 1..4 (ver docstring)


def _line_width(font: Font, line: str, ls: float) -> float:
    """Largura em unidades de maiúscula (sem o espaçamento após a última letra)."""
    if not line:
        return 0.0
    return sum(font.glyph(c).advance + ls for c in line) - ls


def wrap_text(font: Font, text: str, opts: LayoutOptions) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " " * opts.tab_size)
    lines: list[str] = []
    for para in text.split("\n"):
        if opts.max_width is None:
            lines.append(para)
            continue
        limit = opts.max_width / opts.size
        cur = ""
        for word in para.split(" "):
            cand = word if not cur else cur + " " + word
            if cur and _line_width(font, cand, opts.letter_spacing) > limit:
                lines.append(cur)
                cur = word
            else:
                cur = cand
            # palavra maior que a linha inteira: quebra por caractere
            while _line_width(font, cur, opts.letter_spacing) > limit and len(cur) > 1:
                k = len(cur) - 1
                while k > 1 and _line_width(font, cur[:k], opts.letter_spacing) > limit:
                    k -= 1
                lines.append(cur[:k])
                cur = cur[k:]
        lines.append(cur)
    return lines


def layout_block(text: str, font: Font, opts: LayoutOptions) -> tuple[list[Stroke], Rect]:
    """Texto em pé, sem rotação: x >= 0 para a direita, y para cima (1ª linha em y≈0, as demais abaixo).
    Devolve também o retângulo do bloco (largura da área × extensão vertical dos traços)."""
    lines = wrap_text(font, text, opts)
    ls = opts.letter_spacing
    widths = [_line_width(font, ln, ls) for ln in lines]
    block = (opts.max_width / opts.size) if opts.max_width else max(widths, default=0.0)
    step = font.line_height * opts.line_spacing

    strokes: list[Stroke] = []
    for i, ln in enumerate(lines):
        if opts.align == "center":
            x = (block - widths[i]) / 2
        elif opts.align == "right":
            x = block - widths[i]
        else:
            x = 0.0
        y = -i * step
        for ch in ln:
            g = font.glyph(ch)
            for st in g.strokes:
                if len(st) >= 2:
                    strokes.append([((x + px) * opts.size, (y + py) * opts.size) for px, py in st])
            x += g.advance + ls

    if not strokes:
        return [], (0.0, 0.0, 0.0, 0.0)
    ys = [p[1] for st in strokes for p in st]
    return strokes, (0.0, min(ys), block * opts.size, max(ys))


def _rotated_limit(h: float, c: float, s: float, ux: float, uy: float) -> float:
    """Maior largura W do bloco (altura h) cujo retângulo girado cabe em ux × uy."""
    lims = []
    if c > 1e-9:
        lims.append((ux - h * s) / c)
    if s > 1e-9:
        lims.append((uy - h * c) / s)
    return min(lims)


def auto_width(text: str, font: Font, opts: LayoutOptions) -> float | None:
    """Largura de quebra (ao longo do texto) para o bloco girado caber no curso X × Y."""
    if opts.travel is None:
        return None
    ux = opts.travel[0] - 2 * opts.margin
    uy = opts.travel[1] - 2 * opts.margin
    th = math.radians(opts.rotation)
    c, s = round(abs(math.cos(th)), 9), round(abs(math.sin(th)), 9)
    floor = opts.size  # nunca menor que ~1 glifo
    w = max(_rotated_limit(0.0, c, s, ux, uy), floor)
    if c > 1e-9 and s > 1e-9:  # diagonal: a altura do bloco também consome largura; itera até estabilizar
        for _ in range(8):
            _, (_, y0, _, y1) = layout_block(text, font, replace(opts, max_width=w))
            nw = max(_rotated_limit(y1 - y0, c, s, ux, uy), floor)
            if nw >= w - 1e-6:
                break
            w = nw
    return w


def bounds(strokes: list[Stroke]) -> Rect:
    xs = [p[0] for st in strokes for p in st]
    ys = [p[1] for st in strokes for p in st]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)


def place(strokes: list[Stroke], rect: Rect, rotation: float = 0.0, quadrant: int = 4,
          margin: float = 0.0) -> list[Stroke]:
    """Gira (graus, anti-horário, em torno da origem) e translada para o quadrante,
    de modo que o retângulo `rect` (já girado) encoste a `margin` mm da origem."""
    if quadrant not in QUADRANT_SIGNS:
        raise ValueError("quadrante deve ser 1, 2, 3 ou 4")
    th = math.radians(rotation)
    c, s = math.cos(th), math.sin(th)

    def rot(p):
        return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)

    x0, y0, x1, y1 = rect
    corners = [rot(p) for p in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    rx0, rx1 = min(p[0] for p in corners), max(p[0] for p in corners)
    ry0, ry1 = min(p[1] for p in corners), max(p[1] for p in corners)
    sx, sy = QUADRANT_SIGNS[quadrant]
    dx = margin - rx0 if sx > 0 else -margin - rx1
    dy = margin - ry0 if sy > 0 else -margin - ry1
    out = []
    for st in strokes:
        pts = [rot(p) for p in st]
        out.append([(px + dx, py + dy) for px, py in pts])
    return out


def layout_text(text: str, font: Font, opts: LayoutOptions | None = None) -> list[Stroke]:
    opts = opts or LayoutOptions()
    if opts.max_width is None:
        w = auto_width(text, font, opts)
        if w is not None:
            opts = replace(opts, max_width=w)
    strokes, rect = layout_block(text, font, opts)
    if not strokes:
        return []
    return place(strokes, rect, opts.rotation, opts.quadrant, opts.margin)
