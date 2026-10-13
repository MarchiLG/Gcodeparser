"""Texto -> strokes em mm.

Sistema de coordenadas de saída: X para a direita, Y para cima, tudo >= 0
(o bloco de texto é transladado para ficar com o canto inferior esquerdo em
(margin, margin)). A primeira linha fica no topo do bloco.
"""
from __future__ import annotations

from dataclasses import dataclass

from .fonts import Font, Stroke


@dataclass
class LayoutOptions:
    size: float = 8.0            # altura da maiúscula, mm
    line_spacing: float = 1.0    # multiplicador sobre o line_height da fonte
    letter_spacing: float = 0.0  # extra entre letras, em alturas de maiúscula
    align: str = "left"          # left | center | right
    max_width: float | None = None  # largura da área p/ quebra de linha, mm (None = sem quebra)
    margin: float = 0.0          # deslocamento X/Y do bloco, mm
    tab_size: int = 4


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


def layout_text(text: str, font: Font, opts: LayoutOptions | None = None) -> list[Stroke]:
    opts = opts or LayoutOptions()
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
        return []
    min_y = min(p[1] for st in strokes for p in st)
    dx, dy = opts.margin, opts.margin - min_y
    return [[(px + dx, py + dy) for px, py in st] for st in strokes]
