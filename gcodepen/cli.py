"""CLI: python -m gcodepen text "Olá" --font futural --size 8 --zmin -1 --zmax 3 -o out.gcode"""
from __future__ import annotations

import argparse
import sys

from .fonts import load_font
from .gcode import GcodeOptions, generate
from .layout import LayoutOptions, layout_text


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="gcodepen", description="Texto -> G-code para plotter de caneta (GRBL)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("text", help="gera G-code a partir de texto")
    t.add_argument("text", nargs="?", help="texto (ou use --file / stdin)")
    t.add_argument("--file", help="ler texto de arquivo")
    t.add_argument("--pdf", help="ler texto de um PDF")
    t.add_argument("--page", type=int, default=1, help="página do PDF (1 = primeira)")
    t.add_argument("--font", default="futural", help="nome Hershey (ex.: futural, scripts) ou caminho .ttf/.otf")
    t.add_argument("--size", type=float, default=8.0, help="altura da maiúscula em mm")
    t.add_argument("--line-spacing", type=float, default=1.0)
    t.add_argument("--letter-spacing", type=float, default=0.0)
    t.add_argument("--align", choices=["left", "center", "right"], default="left")
    t.add_argument("--width", type=float, default=None, help="largura da área em mm (padrão: automática pelo curso)")
    t.add_argument("--margin", type=float, default=0.0)
    t.add_argument("--travel-x", type=float, default=200.0, help="curso máx. de X em mm ($130); define a quebra de linha")
    t.add_argument("--travel-y", type=float, default=200.0, help="curso máx. de Y em mm ($131)")
    t.add_argument("--quadrant", type=int, choices=[1, 2, 3, 4], default=4,
                   help="quadrante do espaço de trabalho (4 = X+ e Y−, padrão)")
    t.add_argument("--rotate", type=float, default=0.0, help="gira a folha (graus, anti-horário)")
    t.add_argument("--pen", choices=["z", "servo"], default="z", help="caneta pelo eixo Z ou servo no PWM do spindle (M3 S)")
    t.add_argument("--pen-up", type=float, default=700.0, help="servo: S com a caneta levantada")
    t.add_argument("--pen-down", type=float, default=300.0, help="servo: S com a caneta no papel")
    t.add_argument("--pen-dwell", type=float, default=0.25, help="servo: espera em s após cada troca")
    t.add_argument("--zmin", type=float, default=-1.0, help="Z com a caneta no papel (escreve)")
    t.add_argument("--zmax", type=float, default=3.0, help="Z com a caneta levantada")
    t.add_argument("--feed", type=float, default=400.0, help="avanço de escrita mm/min")
    t.add_argument("--zfeed", type=float, default=100.0, help="avanço ao descer a caneta mm/min")
    t.add_argument("--travel-feed", type=float, default=None, help="usa G1 com este F p/ deslocar levantado (padrão: G0)")
    t.add_argument("--zero", action="store_true", help="emite G92 X0 Y0 no início")
    t.add_argument("--no-optimize", action="store_true")
    t.add_argument("-o", "--output", help="arquivo de saída (padrão: stdout)")

    sub.add_parser("serve", help="inicia a interface web").add_argument("--port", type=int, default=8000)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "serve":
        from .server import serve
        serve(port=args.port)
        return 0

    if args.pdf:
        from .pdfio import extract_pages
        pages = extract_pages(open(args.pdf, "rb").read())
        if not 1 <= args.page <= len(pages):
            raise SystemExit(f"PDF tem {len(pages)} página(s)")
        text = pages[args.page - 1]
    elif args.file:
        text = open(args.file, encoding="utf-8").read()
    elif args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read()

    font = load_font(args.font)
    strokes = layout_text(text, font, LayoutOptions(
        size=args.size, line_spacing=args.line_spacing, letter_spacing=args.letter_spacing,
        align=args.align, max_width=args.width, margin=args.margin,
        travel=(args.travel_x, args.travel_y), rotation=args.rotate, quadrant=args.quadrant))
    res = generate(strokes, GcodeOptions(
        zmin=args.zmin, zmax=args.zmax, feed_xy=args.feed, feed_z=args.zfeed,
        travel_feed=args.travel_feed, zero=args.zero, optimize=not args.no_optimize,
        max_travel=(args.travel_x, args.travel_y, GcodeOptions.max_travel[2]), quadrant=args.quadrant,
        pen=args.pen, pen_up=args.pen_up, pen_down=args.pen_down, pen_dwell=args.pen_dwell))
    for w in res.warnings:
        print(f"aviso: {w}", file=sys.stderr)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(res.gcode)
        print(f"{args.output}: {res.stats}", file=sys.stderr)
    else:
        sys.stdout.write(res.gcode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
