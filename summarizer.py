"""
summarizer.py – lógica map/reduce para resumir usando Ollama.
Transplantado casi literal desde epub_resumidor‑BAK.py.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable, Tuple, List

import requests
import re

from .config import (
    MODEL,
    OLLAMA_URL,
    NUM_CTX,
    NUM_PREDICT,
    TEMPERATURE,
    CHUNK_FRACTION,
    OVERLAP_TOKENS,
    STREAM,
    STREAM_MAP,
    STREAM_FUSE,
    log,
)
from .utils import (
    chunk_text,
    strip_think,
    normalize_paragraphs,
    ensure_md,
    append_chapter_summary,
    extract_chapter_summaries_section,
    write_general_summary,
)


# ---------- Helper para llamadas a Ollama ----------------------------------------


def _ollama_chat(prompt: str, *, stream: bool | None = None, tag: str = "") -> str:
    if stream is None:
        stream = STREAM

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Resume en prosa clara, directa y fiel. SIN listas ni viñetas.\n"
                    "No incluyas etiquetas <think>, ni markdown extra."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "options": {
            "num_ctx": NUM_CTX,
            "temperature": TEMPERATURE,
            "num_predict": NUM_PREDICT,
        },
        "stream": bool(stream),
    }

    if not stream:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=600)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()

    log(f"[stream] inicio {tag or 'respuesta'}")
    full = ""
    with requests.post(
        f"{OLLAMA_URL}/api/chat",
        json=payload,
        stream=True,
        timeout=(10, None),
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
               	chunk = json.loads(line)
            except Exception:
                continue
            tok = chunk.get("message", {}).get("content", "")
            if tok:
                full += tok
                if STREAM:
                    print(tok, end="", flush=True)
            if chunk.get("done"):
                break
    if STREAM:
        print()
    return full.strip()


def _fix_title_with_llm(bad_title: str) -> str:
    """
    Usa el modelo LLM para reinsertar espacios y capitalizar un título pegado.
    Se envía solo el título y se pide devolver la versión corregida.
    """
    prompt = (
        "Corrige el espaciado y las mayúsculas de esta frase para que quede "
        "como un título normal en español. Devuelve SOLO el título corregido:\n\n"
        f"{bad_title}"
    )
    fixed = _ollama_chat(prompt, stream=False)
    return fixed.strip() or bad_title


# ---------- Clase principal ------------------------------------------------------


class Summarizer:
    def __init__(self, extractor, out_md: Path):
        self.extractor = extractor
        self.out_md = out_md
        ensure_md(out_md)

    # ------------------ helpers internos ---------------------------- #

    def _summarize_chunk(self, title: str, md: str) -> str:
        max_for_text = int(NUM_CTX * CHUNK_FRACTION)
        chunks = chunk_text(md, max_tokens=max_for_text, overlap_tokens=OVERLAP_TOKENS)

        partials: List[str] = []
        for i, ck in enumerate(chunks, 1):
            prompt = (
                f"Resume en español el siguiente contenido del capítulo «{title}». "
                "Evita fórmulas tipo «El autor dice…». Sin listas.\n\n"
                f"--- CONTENIDO ({i}/{len(chunks)}) ---\n{ck}\n"
            )
            log(f"  · map {i}/{len(chunks)}")
            partials.append(
                strip_think(
                    _ollama_chat(
                        prompt, stream=STREAM_MAP, tag=f"{title} bloque {i}"
                    )
                )
            )
            time.sleep(0.3)

        if len(partials) == 1:
            return partials[0]

        fusion_prompt = (
            "Fusiona en un único resumen coherente los siguientes sub‑resúmenes. "
            "2‑6 párrafos como máximo.\n\n" + "\n\n---\n".join(partials)
        )
        log("  · fusionando sub-resúmenes")
        return normalize_paragraphs(
            strip_think(
                _ollama_chat(
                    fusion_prompt, stream=STREAM_FUSE, tag=f"{title} fusión"
                )
            )
        )

    def _summarize_book(self):
        section = extract_chapter_summaries_section(self.out_md)
        if not section:
            return
        prompt = (
            "A partir de los resúmenes por capítulo siguientes, escribe un "
            "Resumen general del libro en 1‑3 párrafos.\n\n" + section
        )
        general = normalize_paragraphs(strip_think(_ollama_chat(prompt)))
        write_general_summary(self.out_md, general)

    # ------------------ API pública ------------------------------- #

    def run(self):
        processed_any = False

        for idx, section in enumerate(self.extractor.sections(), 1):
            # Desempaquetar según extractor (EPUB devuelve 2 elementos, PDF 3)
            if len(section) == 3:
                title, md, level = section
            else:
                title, md = section
                level = 2  # nivel por defecto

            # Si parece un título pegado (≥15 letras seguidas sin espacio), corrígelo vía LLM
            # Dentro del bucle en summarizer.py
            if re.search(r"[A-Za-zÁÉÍÓÚÜÑ]{15,}", title):
                title = _fix_title_with_llm(title)
            # Elimina cualquier etiqueta <think> residual del título antes de log o escritura
            title = strip_think(title)

            processed_any = True
            log(f"Capítulo {idx}: {title}")
            summary = self._summarize_chunk(title, md)
            append_chapter_summary(self.out_md, title, summary, level=level)

        if not processed_any and hasattr(self.extractor, "_fallback_full_md"):
            md_full = getattr(self.extractor, "_fallback_full_md", "").strip()
            if md_full:
                log("No se detectaron capítulos; resumiendo libro completo.")
                summary = self._summarize_chunk("Libro completo", md_full)
                append_chapter_summary(self.out_md, "Libro completo", summary)
                processed_any = True

        if processed_any:
            self._summarize_book()
            log(f"Resumen completo en {self.out_md.name}")
        else:
            log("No se generó ningún resumen: el contenido era demasiado breve.")
