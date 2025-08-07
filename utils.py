"""
utils.py – helpers compartidos por todo el paquete.
Esta lógica procede íntegra del script original epub_resumidor‑BAK.py
(únicamente se han movido funciones a un módulo independiente).
"""
from __future__ import annotations

import os
import re
import html2text
from pathlib import Path
from typing import List, Tuple

from bs4 import BeautifulSoup
from ebooklib import epub
from bs4.element import Tag

# ---------- conversión HTML → Markdown -----------------------------------------


def html_to_markdown(html: str) -> str:
    """Convierte HTML en Markdown conservando enlaces y saltos de párrafo."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    maker = html2text.HTML2Text()
    maker.ignore_links = False
    maker.body_width = 0  # no wrap
    md = maker.handle(str(soup))
    # colapsar saltos múltiples
    return re.sub(r"\n{3,}", "\n\n", md).strip()


# ---------- manejo de TOC -------------------------------------------------------


def flatten_toc(toc) -> List[Tuple[str, str]]:
    """
    EbookLib devuelve el TOC en forma de árbol con `epub.Link` y tuples
    (title, [children]). Esta función lo aplana en una lista (title, href)
    preservando el orden y sin duplicados.
    También soporta el caso en que `toc` sea un único `epub.Link`.
    """
    from ebooklib import epub

    # Garantizar que siempre iteramos sobre una lista
    if toc is None:
        nodes = []
    elif isinstance(toc, epub.Link):
        nodes = [toc]
    else:
        nodes = toc

    out: list[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()

    def walk(items):
        for node in items:
            if isinstance(node, epub.Link):
                item = (node.title or "", node.href or "")
                if item not in seen:
                    out.append(item)
                    seen.add(item)
            elif isinstance(node, tuple) and len(node) >= 2:
                walk(node[1])

    walk(nodes)
    return out


def split_href(href: str) -> Tuple[str, str]:
    """Devuelve (base_path, fragment_id) para un href tipo 'file.xhtml#frag'."""
    if "#" in (href or ""):
        return href.split("#", 1)
    return href or "", ""


# ---------- operaciones sobre el MD de salida -----------------------------------


def ensure_md(path: Path):
    if not path.exists():
        path.write_text("# Resumen general\n\n# Resumen por capítulos\n", encoding="utf-8")


def append_chapter_summary(path: Path, title: str, summary: str, level: int = 2):
    """
    Añade un bloque de resumen al Markdown.
    `level` indica la jerarquía de cabecera (2 = ##, 3 = ###, …).
    """
    md = path.read_text(encoding="utf-8")
    header = "#" * max(level, 2)  # nunca menos de ##
    block = f"\n\n{header} {title}\n\n{summary.strip()}\n"
    path.write_text(md + block, encoding="utf-8")


def extract_chapter_summaries_section(path: Path) -> str:
    md = path.read_text(encoding="utf-8")
    m = re.search(r"# Resumen por capítulos\s*(.*)$", md, flags=re.S)
    return (m.group(1) if m else "").strip()


def write_general_summary(path: Path, general: str):
    md = path.read_text(encoding="utf-8")
    new = f"# Resumen general\n\n{general.strip()}\n\n"
    if "# Resumen general" in md:
        md = re.sub(
            r"# Resumen general\s*(?:\n+[^#].*?)?(?=\n#|\Z)", new, md, flags=re.S
        )
    else:
        md = new + md
    path.write_text(md, encoding="utf-8")


# ---------- token heuristics & chunking -----------------------------------------


def approx_token_count(text: str) -> int:
    """Aproximación rápida: 1 token ≈ 4 caracteres ASCII."""
    return max(1, len(text) // 4)


def chunk_text(md: str, max_tokens: int, overlap_tokens: int = 300) -> List[str]:
    """
    Divide el Markdown en chunks que no excedan `max_tokens` (aprox.)
    Solapa `overlap_tokens` para dar contexto al modelo.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", md) if p.strip()]
    chunks, cur, cur_toks = [], [], 0
    for para in paragraphs:
        t = approx_token_count(para)
        if cur_toks + t > max_tokens and cur:
            chunks.append("\n\n".join(cur))
            # construir overlap
            ov, toks = [], 0
            for p in reversed(cur):
                toks += approx_token_count(p)
                ov.append(p)
                if toks >= overlap_tokens:
                    break
            cur = list(reversed(ov))
            cur_toks = sum(approx_token_count(x) for x in cur)
        cur.append(para)
        cur_toks += t
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


# ---------- limpieza/modelado del output ----------------------------------------


def strip_think(text: str) -> str:
    """Elimina etiquetas <think>…</think> que algunos modelos añaden."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()


def normalize_paragraphs(text: str, min_per: int = 3, max_per: int = 5) -> str:
    """
    Asegura párrafos de entre `min_per` y `max_per` frases cada uno.
    Si el texto ya tiene párrafos (doble salto), lo respeta.
    """
    t = (text or "").strip()
    if not t or "\n\n" in t:
        return t

    sentences = re.split(r"(?<=[\.!?…])\s+", t)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return t

    paragraphs, cur = [], []
    for s in sentences:
        cur.append(s)
        if len(cur) >= max_per:
            paragraphs.append(" ".join(cur))
            cur = []
    if cur:
        if len(cur) < min_per and paragraphs:
            paragraphs[-1] += " " + " ".join(cur)
        else:
            paragraphs.append(" ".join(cur))
    return "\n\n".join(paragraphs)
