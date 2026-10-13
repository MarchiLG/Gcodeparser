"""Fontes -> glifos como polilinhas.

Convenção de unidades de um glifo: y para cima, linha de base em y=0 e
altura das maiúsculas = 1.0. O layout multiplica tudo por `size` (mm).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

Point = tuple[float, float]
Stroke = list[Point]

HERSHEY_DEFAULT = "futural"

# Sinais diacríticos desenhados à mão (usados nas fontes Hershey, que são só ASCII).
# Coordenadas em unidades de altura de maiúscula, relativas ao centro do glifo base.
_MARKS: dict[str, list[Stroke]] = {
    "́": [[(-0.10, 0.0), (0.10, 0.18)]],                                   # agudo
    "̀": [[(0.10, 0.0), (-0.10, 0.18)]],                                   # grave
    "̂": [[(-0.12, 0.0), (0.0, 0.16), (0.12, 0.0)]],                       # circunflexo
    "̃": [[(-0.14, 0.0), (-0.07, 0.10), (0.0, 0.04), (0.07, 0.14), (0.14, 0.06)]],  # til
    "̈": [[(-0.08, 0.10), (-0.08, 0.11)], [(0.08, 0.10), (0.08, 0.11)]],   # trema
    "̧": [[(0.0, 0.0), (0.03, -0.06), (-0.05, -0.12)]],                    # cedilha
}


@dataclass
class Glyph:
    strokes: list[Stroke]
    advance: float
    top: float = 1.0  # topo do glifo (p/ posicionar sinais acima)


class Font:
    name: str
    line_height: float = 1.6  # distância entre linhas de base, em alturas de maiúscula

    def glyph(self, ch: str) -> Glyph:  # pragma: no cover - interface
        raise NotImplementedError

    def has(self, ch: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def space_advance(self) -> float:
        return self.glyph(" ").advance


class HersheyFont(Font):
    def __init__(self, name: str = HERSHEY_DEFAULT):
        from HersheyFonts import HersheyFonts

        hf = HersheyFonts()
        hf.load_default_font(name)
        self.name = name
        self._glyphs = hf.all_glyphs
        ro = hf.render_options
        self._base = float(ro["base_line"])
        self._cap = float(ro["base_line"] - ro["cap_line"]) or 21.0
        self._cache: dict[str, Glyph] = {}
        self.line_height = 1.6

    def has(self, ch: str) -> bool:
        return ch in self._glyphs

    def glyph(self, ch: str) -> Glyph:
        if ch in self._cache:
            return self._cache[ch]
        g = self._glyphs.get(ch)
        if g is None:
            g = self._glyphs.get("?")
        strokes: list[Stroke] = []
        if g is not None:
            for st in g.strokes:
                strokes.append([((x - g.left_offset) / self._cap, (self._base - y) / self._cap) for x, y in st])
            adv = g.char_width / self._cap
        else:
            adv = 0.6
        out = Glyph(strokes, adv)
        self._cache[ch] = out
        return out


class TTFFont(Font):
    """Contornos de TTF/OTF achatados em polilinhas (letras 'ocas')."""

    def __init__(self, path: str, tolerance: float = 0.02):
        from fontTools.ttLib import TTFont

        self._tt = TTFont(path, fontNumber=0, lazy=True)
        self.name = Path(path).stem
        try:
            self._gs = self._tt.getGlyphSet()
        except Exception as e:  # fontes bitmap/emoji não têm contornos
            raise ValueError(f"Fonte '{Path(path).name}' sem contornos vetoriais: {e}") from e
        self._cmap = self._tt.getBestCmap() or {}
        self._upm = float(self._tt["head"].unitsPerEm)
        cap = getattr(self._tt["OS/2"], "sCapHeight", 0) if "OS/2" in self._tt else 0
        self._cap = float(cap or 0.7 * self._upm)
        self._tol = tolerance
        self._cache: dict[str, Glyph] = {}
        self.line_height = 1.7

    def has(self, ch: str) -> bool:
        return ord(ch) in self._cmap

    def glyph(self, ch: str) -> Glyph:
        if ch in self._cache:
            return self._cache[ch]
        from fontTools.pens.basePen import BasePen

        name = self._cmap.get(ord(ch)) or self._cmap.get(ord("?"))
        tol = self._tol * self._cap
        cap = self._cap

        class _Flatten(BasePen):
            def __init__(self, gs):
                super().__init__(gs)
                self.contours: list[Stroke] = []
                self._cur: Stroke = []

            def _moveTo(self, p):
                self._cur = [(p[0] / cap, p[1] / cap)]

            def _lineTo(self, p):
                self._cur.append((p[0] / cap, p[1] / cap))

            def _curveToOne(self, p1, p2, p3):
                p0 = self._getCurrentPoint()
                # nº de segmentos pela flecha estimada do polígono de controle
                d = max(abs(p0[0] - 2 * p1[0] + p2[0]), abs(p0[1] - 2 * p1[1] + p2[1]),
                        abs(p1[0] - 2 * p2[0] + p3[0]), abs(p1[1] - 2 * p2[1] + p3[1]))
                n = max(2, min(32, int((d / max(tol, 1e-6)) ** 0.5 * 0.75) + 1))
                for i in range(1, n + 1):
                    t = i / n
                    mt = 1 - t
                    x = mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0]
                    y = mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1]
                    self._cur.append((x / cap, y / cap))

            def _closePath(self):
                if len(self._cur) > 1:
                    if self._cur[0] != self._cur[-1]:
                        self._cur.append(self._cur[0])
                    self.contours.append(self._cur)
                self._cur = []

            def _endPath(self):
                if len(self._cur) > 1:
                    self.contours.append(self._cur)
                self._cur = []

        if name is None:
            out = Glyph([], 0.6)
        else:
            pen = _Flatten(self._gs)
            self._gs[name].draw(pen)
            out = Glyph(pen.contours, self._gs[name].width / cap)
        self._cache[ch] = out
        return out


class AccentedFont(Font):
    """Envolve uma fonte e compõe letras acentuadas (NFD) quando ela não as tem."""

    def __init__(self, inner: Font):
        self._inner = inner
        self.name = inner.name
        self.line_height = inner.line_height

    def has(self, ch: str) -> bool:
        return self._inner.has(ch)

    def glyph(self, ch: str) -> Glyph:
        if self._inner.has(ch) or len(ch) != 1:
            return self._inner.glyph(ch)
        decomp = unicodedata.normalize("NFD", ch)
        if len(decomp) >= 2 and self._inner.has(decomp[0]):
            base = self._inner.glyph(decomp[0])
            strokes = [list(s) for s in base.strokes]
            cx = base.advance / 2
            upper = decomp[0].isupper() or decomp[0] in "bdfhklt"
            top = 1.0 if upper else 0.62
            for mark in decomp[1:]:
                for st in _MARKS.get(mark, []):
                    dy = top + 0.06 if mark != "̧" else 0.0
                    strokes.append([(cx + x, dy + y) for x, y in st])
            return Glyph(strokes, base.advance)
        return self._inner.glyph(ch)


def hershey_names() -> list[str]:
    from HersheyFonts import HersheyFonts

    skip = {"astrology", "japanese", "markers", "music", "meteorology", "symbolic",
            "mathlow", "mathupp", "greek", "greekc", "greeks", "cyrilc_1", "cyrillic"}
    return [n for n in HersheyFonts().default_font_names if n not in skip]


def system_fonts() -> dict[str, str]:
    """Descobre TTF/OTF instalados (via fc-list, se existir). nome -> caminho."""
    import shutil
    import subprocess

    found: dict[str, str] = {}
    if shutil.which("fc-list"):
        try:
            out = subprocess.run(["fc-list", ":", "file", "family"], capture_output=True, text=True, timeout=10).stdout
        except Exception:
            out = ""
        for line in out.splitlines():
            path, _, fam = line.partition(":")
            path = path.strip()
            if not path.lower().endswith((".ttf", ".otf")) or "%" in path:
                continue
            fam = fam.replace("family=", "").split(",")[0].strip() or Path(path).stem
            found.setdefault(f"{fam} ({Path(path).stem})", path)
    return dict(sorted(found.items()))


def load_font(spec: str) -> Font:
    """`spec` = nome Hershey (ex.: 'futural') ou caminho para .ttf/.otf."""
    p = Path(spec)
    if spec.lower().endswith((".ttf", ".otf", ".ttc")) or p.is_file():
        return AccentedFont(TTFFont(str(p)))
    return AccentedFont(HersheyFont(spec))
