"""epub_extractor.py – extrae capítulos sustantivos de un EPUB
y los devuelve como Markdown. Porta la lógica del script original.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Tuple

from bs4 import BeautifulSoup
from bs4.element import Tag
from ebooklib import epub

# Algunas versiones antiguas no exponen ITEM_DOCUMENT; 9 es su valor interno.
try:
    from ebooklib import ITEM_DOCUMENT
except ImportError:
    ITEM_DOCUMENT = 9  # type: ignore

from .utils import html_to_markdown, flatten_toc, split_href

# ---------- filtros -------------------------------------------------------------

_NON_CONTENT_TITLES = {
    "cover",
    "title",
    "title page",
    "copyright",
    "acknowledgments",
    "contents",
    "table of contents",
    "index",
    "dedication",
    "preface",
    "front matter",
    "foreword",
    "about the author",
    "bibliography",
    "glossary",
    "colophon",
    "legal",
    # ES
    "cubierta",
    "portada",
    "créditos",
    "agradecimientos",
    "índice",
    "tabla de contenido",
    "dedicatoria",
    "prefacio",
    "prólogo",
    "epílogo",
    "sobre el autor",
    "acerca del autor",
    "biografía",
    "bibliografía",
    "glosario",
    "colofón",
    "licencia",
    "nota del autor",
    "nota de la autora",
    "nota del editor",
    "nota de la editorial",
}

_HREF_SKIP = re.compile(
    r'(?:^|/)(?:toc\.(?:ncx|x?html?)|nav\.(?:x?html?)|'
    r'title|cover|copyright|acknowledg|front|colophon|'
    r'about|dedic|preface|foreword|prolog|epilog|gloss|biblio|legal)'
    r'|(?:^|/)index\.(?:x?html?)$',
    re.I,
)


def _content_title(title: str) -> bool:
    t = re.sub(r"\s+", " ", title or "").strip().lower()
    return bool(t) and all(k not in t for k in _NON_CONTENT_TITLES)


def _skip_href(href: str) -> bool:
    return bool(_HREF_SKIP.search((href or "").lower()))


# ---------- helpers internos ----------------------------------------------------


def _item_by_base(book: epub.EpubBook, base: str):
    item = book.get_item_with_href(base)
    if item:
        return item
    target = (base or "").lstrip("./")
    for it in book.get_items():
        if getattr(it, "href", "").lstrip("./") == target:
            return it
    return None


def _section_md(book: epub.EpubBook, base: str, frag: str, nxt: str | None) -> str:
    item = _item_by_base(book, base)
    if not item:
        return ""
    soup = BeautifulSoup(item.get_content().decode("utf-8", "ignore"), "html.parser")
    for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    start = soup.find(id=frag) or soup.find(attrs={"name": frag}) if frag else None
    if not start:
        return html_to_markdown(str(soup))

    pieces = [str(start)]
    for node in start.next_elements:
        if isinstance(node, Tag):
            nid = node.get("id") or node.get("name")
            if nxt and nid == nxt:
                break
        pieces.append(str(node))
    return html_to_markdown("".join(pieces))


# ---------- clase extractor -----------------------------------------------------


class EpubExtractor:
    """
    Provee `.sections() -> Iterable[(title, markdown)]`
    """

    def __init__(self, path: Path):
        self.path = path
        self.book = epub.read_epub(str(path))

        # --- construir lista de capítulos ------------------------------
        raw: list[Tuple[str, str, str]] = []
        for title, href in flatten_toc(self.book.toc):
            if not href:
                continue
            if not _content_title(title) or _skip_href(href):
                continue
            base, frag = split_href(href)
            raw.append((title.strip() or "Capítulo", base, frag))

        self.chapters: list[Tuple[str, str, str, str | None]] = []
        for i, (title, base, frag) in enumerate(raw):
            nxt = None
            for _, b2, f2 in raw[i + 1 :]:
                if b2 == base:
                    nxt = f2 or None
                    break
            self.chapters.append((title, base, frag, nxt))

        # Fallback: todo el libro si no hay capítulos sustantivos
        if not self.chapters:
            parts: list[str] = [
                it.get_content().decode("utf-8", "ignore")
                for it in self.book.get_items_of_type(ITEM_DOCUMENT)
            ]

            # Algunos EPUB antiguos no etiquetan ITEM_DOCUMENT; recorrer la spine
            if not parts:
                for idref, _ in self.book.spine:
                    it = self.book.get_item_with_id(idref)
                    if not it:
                        continue
                    # aceptar cualquier html/xhtml
                    if (
                        it.get_type() == ITEM_DOCUMENT
                        or getattr(it, "media_type", "").lower().find("html") != -1
                    ):
                        parts.append(it.get_content().decode("utf-8", "ignore"))

            self._full_md = html_to_markdown("\n".join(parts))

    # ------------------------------------------------------------------ #

    def sections(self) -> Iterable[Tuple[str, str]]:
        if self.chapters:
            for title, base, frag, nxt in self.chapters:
                md = _section_md(self.book, base, frag, nxt)
                if len(md.split()) < 60:
                    continue
                yield title, md
        else:
            md = getattr(self, "_full_md", "").strip()
            if md:
                yield "Libro completo", md