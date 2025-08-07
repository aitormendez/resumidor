from __future__ import annotations
from pathlib import Path
from typing import Iterable, Tuple, List, Any

import pypdf
from pypdf.generic import Destination as PdfDestination  # clase real de destino

import pdfplumber

from .extractor_base import ExtractorBase

# ---------- umbrales para decidir si un subcapítulo se resume aparte ----------
MIN_PAGES_SUB   = 3
MIN_WORDS_SUB   = 800
MIN_RATIO_SUB   = 0.25          # (% del capítulo)


class PdfExtractor(ExtractorBase):
    """
    Estrategia progresiva:
      1. Outline nivel 1 = capítulos principales.
      2. Outline nivel 2 = subcapítulos.
         • Se resumen aparte solo si cumplen umbrales (páginas, palabras o ratio).
      3. Si el outline no es fiable, _sections se dejará vacía
         y el resumidor caerá en el fallback libro completo
         (estrategias tipográficas/regex se añadirán después).
    """

    def __init__(self, pdf_path: Path, pages_per_section: int = 10):
        self.path = pdf_path
        self.reader = pypdf.PdfReader(str(pdf_path))

        # ------------- obtener outline ---------------------------------
        outline = getattr(self.reader, "outline", None)
        # _chapters -> List[Tuple[PdfDestination, int]]  (dest, page_idx)
        self._chapters: List[Tuple[PdfDestination, int]] = []
        # _sub_map  -> Dict[int, List[Tuple[PdfDestination, int]]]
        #              key = root page_idx  (hashable), value = list of (dest, page_idx)
        self._sub_map: dict[int, List[Tuple[PdfDestination, int]]] = {}

        def _walk(nodes: Any, depth: int = 0, current_root: int | None = None):
            for node in nodes:
                if isinstance(node, PdfDestination):
                    page_idx = self.reader.get_destination_page_number(node)
                    if depth == 0:
                        self._chapters.append((node, page_idx))
                        current_root = page_idx   # use page index as key
                    elif depth == 1 and current_root is not None:
                        self._sub_map.setdefault(current_root, []).append((node, page_idx))
                elif isinstance(node, list):
                    _walk(node, depth + 1, current_root)

        if outline:
            _walk(outline)

        # ------------- construir secciones -----------------------------
        self._sections: List[Tuple[str, List[int], int]] = []
        total_pages = len(self.reader.pages)

        if self._chapters:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for idx, (chap_dest, chap_start) in enumerate(self._chapters):
                    chap_end = (
                        self._chapters[idx + 1][1]
                        if idx + 1 < len(self._chapters)
                        else total_pages
                    )
                    chap_pages = list(range(chap_start, chap_end))

                    # evaluar subcapítulos
                    subs = self._sub_map.get(chap_start, [])
                    substantial_subs: List[Tuple[str, List[int]]] = []

                    for s_idx, (sub_dest, sub_start) in enumerate(subs):
                        sub_end = (
                            subs[s_idx + 1][1]
                            if s_idx + 1 < len(subs)
                            else chap_end
                        )
                        sub_pages = list(range(sub_start, sub_end))

                        # señales
                        page_count = len(sub_pages)
                        text_sub = "\n".join(pdf.pages[i].extract_text() or "" for i in sub_pages)
                        words_sub = len(text_sub.split())
                        ratio = page_count / len(chap_pages) if chap_pages else 0

                        if (
                            page_count >= MIN_PAGES_SUB
                            or words_sub >= MIN_WORDS_SUB
                            or ratio >= MIN_RATIO_SUB
                        ):
                            title = getattr(sub_dest, "title", "") or f"Subsección {len(substantial_subs)+1}"
                            substantial_subs.append((title, sub_pages))

                    if substantial_subs:
                        chap_title = getattr(chap_dest, "title", "") or f"Capítulo {idx+1}"
                        self._sections.append((chap_title, chap_pages, 2))
                        for title, pages in substantial_subs:
                            self._sections.append((title, pages, 3))
                    else:
                        chap_title = getattr(chap_dest, "title", "") or f"Capítulo {idx+1}"
                        self._sections.append((chap_title, chap_pages, 2))

        # ---------------- fallback libro completo ----------------------
        with pdfplumber.open(str(pdf_path)) as pdf:
            self._full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    # -------- métodos requeridos por ExtractorBase --------------------

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