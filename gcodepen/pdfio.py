"""PDF -> texto por página (pypdf). Imagens, tabelas e fórmulas não são desenhadas."""
from __future__ import annotations

import io
import re


def extract_pages(data: bytes, max_pages: int = 500) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ValueError("PDF protegido por senha")
        except Exception as e:
            raise ValueError("PDF protegido por senha") from e
    pages = []
    for page in reader.pages[:max_pages]:
        txt = page.extract_text() or ""
        txt = txt.replace("­", "").replace(" ", " ")
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        pages.append(txt)
    return pages
