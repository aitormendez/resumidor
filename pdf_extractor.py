"""
pdf_extractor.py – Extrae capítulos y subcapítulos de un PDF.

Flujo:
1. Si el outline (bookmarks) es fiable ⇒ usa nivel‑1 como capítulos y
   subnivel‑1 como subcapítulos sustanciales.
2. Si el outline es poco fiable o inexistente ⇒ heurística tipográfica:
   detecta cabeceras grandes, centradas y en mayúsculas / Title Case.
3. Si aun así no hay secciones, se resume el libro completo.

Devuelve secciones como (title, markdown/text, level) para que
ExtractorBase las formatee.
"""

from __future__ import annotations

from typing import Iterable, Tuple, List, Any

from pathlib import Path
import statistics
import re

import pypdf
from pypdf.generic import Destination as PdfDestination
import pdfplumber

from .extractor_base import ExtractorBase
from .utils import html_to_markdown  # reuse if HTML snippets appear


# --------------------------------------------------------------------------- #
# Configurables
# --------------------------------------------------------------------------- #
MIN_PAGES_SUB = 3
MIN_WORDS_SUB = 800
MIN_RATIO_SUB = 0.25  # % del capítulo

# --------------------------------------------------------------------------- #
# Outline fiabilidad
# --------------------------------------------------------------------------- #
def _outline_is_reliable(chapters: list[tuple[PdfDestination, int]], total_pages: int) -> bool:
    num_ch = len(chapters)
    if total_pages == 0 or num_ch < 3:
        return False

    page_idxs = [idx for _, idx in chapters]
    coverage = len(set(page_idxs)) / total_pages

    titles = [getattr(dest, "title", "").strip().lower() for dest, _ in chapters]
    diversity = len(set(titles)) / len(titles)

    bad_kw = {"cover", "copyright", "index"}
    keywords_ok = not any(any(b in t for b in bad_kw) for t in titles[:3])

    cap_rx = re.compile(r"(cap[ií]tulo|chapter|\d+|[ivxlcdm]+\.)", re.I)
    numeric_ratio = sum(1 for t in titles if cap_rx.search(t)) / num_ch

    sizes = [b - a for a, b in zip(page_idxs, page_idxs[1:])] or [0]
    min_distance = min(sizes)

    score = sum(
        [
            coverage >= 0.6,
            diversity >= 0.4,
            keywords_ok,
            numeric_ratio >= 0.3,
            min_distance >= 3,
        ]
    )

    reliable = score >= 4
    print(
        f"[DEBUG] TOC check → chapters={num_ch}, coverage={coverage:.2f}, "
        f"diversity={diversity:.2f}, keywords_ok={keywords_ok}, "
        f"numeric_ratio={numeric_ratio:.2f}, min_dist={min_distance}, "
        f"score={score}, reliable={reliable}"
    )
    return reliable


# --------------------------------------------------------------------------- #
# Limpieza de cabeceras detectadas
# --------------------------------------------------------------------------- #
def _clean_title(t: str) -> str:
    t = re.sub(r"[·•\.]{2,}", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    tokens = t.split(" ")
    single_letters = sum(1 for tok in tokens if len(tok) == 1)
    if tokens and single_letters / len(tokens) >= 0.6:
        t = "".join(tokens)
        t = re.sub(r"(?<=[a-záéíóúñ])(?=[A-ZÁÉÍÓÚÜÑ])", " ", t)

    return t.title().strip()


# --------------------------------------------------------------------------- #
# Heurística tipográfica
# --------------------------------------------------------------------------- #
def _detect_by_fonts(pdf_path: Path, num_pages: int) -> list[tuple[str, list[int], int]]:
    candidates: list[tuple[int, str]] = []  # (page_idx, title)

    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            try:
                words = page.extract_words(keep_font=True, keep_size=True)
            except TypeError:
                words = [
                    {
                        "text": c.get("text", ""),
                        "size": c.get("size", 0),
                        "x0": c.get("x0", 0),
                        "x1": c.get("x1", 0),
                        "top": c.get("top", 0),
                    }
                    for c in page.chars
                    if "size" in c
                ]
            if not words:
                continue

            sizes = [w["size"] for w in words if isinstance(w["size"], (int, float))]
            if len(sizes) < 3:
                continue
            mu, sigma = statistics.mean(sizes), statistics.stdev(sizes)
            thresh = mu + 2 * sigma
            width = page.width

            # agrupar por línea aproximada
            lines: dict[int, list[dict]] = {}
            for w in words:
                top_band = int(w["top"] // 3)
                lines.setdefault(top_band, []).append(w)

            best_line = None
            best_size = 0
            for ws in lines.values():
                line_size = max(w["size"] for w in ws)
                if line_size >= thresh and line_size > best_size:
                    best_line = ws
                    best_size = line_size

            if best_line:
                x0 = min(w["x0"] for w in best_line)
                x1 = max(w["x1"] for w in best_line)
                if not (0.1 * width <= x0 <= x1 <= 0.9 * width):
                    continue

                raw_text = " ".join(
                    w["text"] for w in sorted(best_line, key=lambda d: d["x0"])
                ).strip()
                text = _clean_title(raw_text)

                # descartar palabras clave y páginas preliminares
                if i < 3 or re.search(r"\b(índice|contents?)\b", text, re.I):
                    continue

                if re.match(r"(cap[ií]tulo|chapter)\b", text, re.I) or text.istitle():
                    candidates.append((i, text))

    if len(candidates) < 2:
        return []

    sections: list[tuple[str, list[int], int]] = []
    for idx, (start, title) in enumerate(candidates):
        end = candidates[idx + 1][0] if idx + 1 < len(candidates) else num_pages
        pages_range = list(range(start, end))
        sections.append((title, pages_range, 2))
    return sections


# --------------------------------------------------------------------------- #
# PdfExtractor
# --------------------------------------------------------------------------- #
class PdfExtractor(ExtractorBase):
    def __init__(self, pdf_path: Path):
        self.path = pdf_path
        self.reader = pypdf.PdfReader(str(pdf_path))

        self._chapters: list[Tuple[PdfDestination, int]] = []
        self._sub_map: dict[int, list[Tuple[PdfDestination, int]]] = {}

        outline = getattr(self.reader, "outline", None)

        def _walk(nodes: Any, depth: int = 0, current_root: int | None = None):
            for node in nodes:
                if isinstance(node, PdfDestination):
                    page_idx = self.reader.get_destination_page_number(node)
                    if page_idx is None:
                        continue
                    if depth == 0:
                        self._chapters.append((node, page_idx))
                        current_root = page_idx
                    elif depth == 1 and current_root is not None:
                        self._sub_map.setdefault(current_root, []).append((node, page_idx))
                elif isinstance(node, list):
                    _walk(node, depth + 1, current_root)

        if outline:
            _walk(outline)

        # --------------------------------------------
        self._sections: list[tuple[str, list[int], int]] = []

        if self._chapters and _outline_is_reliable(self._chapters, len(self.reader.pages)):
            # Construir secciones a partir de capítulos fiables
            with pdfplumber.open(str(pdf_path)) as pdf:
                total = len(self.reader.pages)
                for idx, (chap_dest, chap_start) in enumerate(self._chapters):
                    chap_end = (
                        self._chapters[idx + 1][1] if idx + 1 < len(self._chapters) else total
                    )
                    chap_pages = list(range(chap_start, chap_end))

                    subs = self._sub_map.get(chap_start, [])
                    substantial_subs: list[tuple[str, list[int]]] = []
                    for s_idx, (sub_dest, sub_start) in enumerate(subs):
                        sub_end = (
                            subs[s_idx + 1][1] if s_idx + 1 < len(subs) else chap_end
                        )
                        sub_pages = list(range(sub_start, sub_end))

                        page_count = len(sub_pages)
                        with pdfplumber.open(str(pdf_path)) as pdf_tmp:
                            text_sub = "\n".join(
                                pdf_tmp.pages[i].extract_text() or "" for i in sub_pages
                            )
                        words_sub = len(text_sub.split())
                        ratio = page_count / len(chap_pages) if chap_pages else 0

                        if (
                            page_count >= MIN_PAGES_SUB
                            or words_sub >= MIN_WORDS_SUB
                            or ratio >= MIN_RATIO_SUB
                        ):
                            title = _clean_title(getattr(sub_dest, "title", "") or "")
                            substantial_subs.append((title, sub_pages))

                    chap_title = _clean_title(getattr(chap_dest, "title", "") or f"Capítulo {idx+1}")
                    self._sections.append((chap_title, chap_pages, 2))
                    for title, pgs in substantial_subs:
                        self._sections.append((title, pgs, 3))

        else:
            # Outline no fiable → heurística tipográfica
            self._sections = _detect_by_fonts(pdf_path, len(self.reader.pages))

        # Fallback texto completo
        with pdfplumber.open(str(pdf_path)) as pdf:
            self._full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    # -----------------------------------------------------------------
    # Métodos requeridos por ExtractorBase
    # -----------------------------------------------------------------
    def _iter_raw_sections(self) -> Iterable[Tuple[str, str, int]]:
        if not self._sections:
            return
        with pdfplumber.open(str(self.path)) as pdf:
            for title, pages, lvl in self._sections:
                text = "\n".join(pdf.pages[i].extract_text() or "" for i in pages)
                if text.strip():
                    yield title, text, lvl

    def _fallback_full_text(self) -> str:
        return self._full_text