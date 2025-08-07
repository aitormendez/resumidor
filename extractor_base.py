"""
extractor_base.py – clase base reutilizable para todos los extractores
(EPUB, PDF, DOCX…). Centraliza la lógica que se repite:
  • Conversión a Markdown
  • Filtro de secciones demasiado cortas
  • Fallback de “libro completo”
Cada extractor concreto solo implementa dos métodos:
  _iter_raw_sections()  -> Iterable[(title, raw_html_or_text, header_level)]
  _fallback_full_text() -> str   (texto/HTML de todo el libro)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Tuple

from .utils import html_to_markdown


class ExtractorBase(ABC):
    """Clase base con la lógica común de extracción."""

    MIN_WORDS = 60  # descartar secciones demasiado cortas

    # ---- Métodos que debe implementar cada subclase -----------------

    @abstractmethod
    def _iter_raw_sections(self) -> Iterable[Tuple[str, str, int]]:
        """Devuelve tuplas (title, raw_html_or_text, header_level)."""
        ...

    @abstractmethod
    def _fallback_full_text(self) -> str:
        """Devuelve el texto o HTML completo del libro (sin separar en capítulos)."""
        ...

    # -----------------------------------------------------------------

    def sections(self) -> Iterable[Tuple[str, str, int]]:
        """
        Implementación común: itera capítulos, filtra los demasiado cortos
        y aplica fallback si no queda nada.
        Devuelve tuplas (title, markdown, header_level).
        """
        yielded = False

        for title, raw, level in self._iter_raw_sections():
            md = (
                html_to_markdown(raw)
                if "<" in raw[:200] and "</" in raw
                else raw.strip()
            )
            if len(md.split()) >= self.MIN_WORDS:
                yielded = True
                yield title, md, level

        if not yielded:
            full = self._fallback_full_text().strip()
            if full:
                md = (
                    html_to_markdown(full)
                    if "<" in full[:200] and "</" in full
                    else full
                )
                if md:
                    yield "Libro completo", md, 2