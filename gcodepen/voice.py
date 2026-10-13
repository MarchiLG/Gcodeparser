"""Gemini (REST, sem SDK): áudio -> texto e prompt -> desenho (polilinhas).

Chave em GEMINI_API_KEY (só no servidor); modelo em GEMINI_MODEL
(padrão: alias `gemini-flash-latest`).
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request

from .fonts import Stroke

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class AIError(Exception):
    pass


def enabled() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _call(parts: list[dict], json_mode: bool = False, timeout: float = 60.0) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise AIError("Defina a variável de ambiente GEMINI_API_KEY e reinicie o servidor.")
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    body = {"contents": [{"parts": parts}]}
    if json_mode:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise AIError(f"Gemini HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise AIError(f"Falha de rede ao chamar o Gemini: {e}") from e
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
    except (KeyError, IndexError) as e:
        raise AIError(f"Resposta inesperada do Gemini: {str(data)[:200]}") from e


def transcribe(audio: bytes, mime: str = "audio/wav", lang: str = "português do Brasil") -> str:
    prompt = (f"Transcreva fielmente o áudio em {lang}. Responda SOMENTE com o texto falado, "
              "com pontuação normal, sem comentários, aspas ou marcações de tempo. "
              "Se não houver fala, responda com texto vazio.")
    return _call([{"text": prompt},
                  {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}}])


DRAW_PROMPT = """Você desenha para um plotter de caneta. Desenhe: "{prompt}".
Responda SOMENTE com JSON no formato {{"strokes": [[[x, y], [x, y], ...], ...]}}.
Regras: cada stroke é uma polilinha contínua traçada sem levantar a caneta; coordenadas inteiras de 0 a 1000,
origem no canto INFERIOR esquerdo (y cresce para cima); estilo de linha simples (contorno, sem preenchimento);
use curvas aproximadas por muitos pontos curtos; no máximo 60 strokes e 800 pontos no total; ocupe bem o quadrado."""


def parse_strokes(raw: str) -> list[Stroke]:
    """Valida o JSON do modelo -> strokes normalizados em 0..1 (y para cima)."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise AIError("O modelo não devolveu JSON.")
    try:
        data = json.loads(m.group(0))
        out: list[Stroke] = []
        total = 0
        for st in data["strokes"]:
            pts = [(min(max(float(x), 0.0), 1000.0) / 1000.0, min(max(float(y), 0.0), 1000.0) / 1000.0)
                   for x, y in st]
            if len(pts) >= 2:
                out.append(pts)
                total += len(pts)
            if total > 5000:
                break
    except (ValueError, KeyError, TypeError) as e:
        raise AIError(f"JSON de desenho inválido: {e}") from e
    if not out:
        raise AIError("O modelo não devolveu nenhum traço.")
    return out


def draw(prompt: str) -> list[Stroke]:
    return parse_strokes(_call([{"text": DRAW_PROMPT.format(prompt=prompt.replace('"', "'")[:500])}], json_mode=True))


def fit_strokes(strokes: list[Stroke], size_mm: float, margin: float = 0.0) -> list[Stroke]:
    """Escala (mantendo proporção) p/ que a maior dimensão = size_mm; canto inferior esquerdo em (margin, margin)."""
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    k = size_mm / (max(w, h) or 1.0)
    return [[((x - min(xs)) * k + margin, (y - min(ys)) * k + margin) for x, y in s] for s in strokes]
