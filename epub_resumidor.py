#!/usr/bin/env python3
import os, re, time, requests, sys, json
from pathlib import Path
from typing import List, Tuple
from ebooklib import epub
from bs4 import BeautifulSoup
import html2text

# --- Config por variables de entorno ---
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
NUM_CTX = int(os.environ.get("NUM_CTX", "32768"))
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.1"))
NUM_PREDICT = int(os.environ.get("NUM_PREDICT", "2048"))

# Flags de depuración/seguimiento (pueden sobreescribirse por CLI)
_DEF_TRUE = {"1","true","yes","on","y"}
_DEF_FALSE = {"0","false","no","off","n"}

def _env_flag(name: str, default: bool=False) -> bool:
    v = str(os.environ.get(name, "")).strip().lower()
    if not v:
        return default
    if v in _DEF_TRUE: return True
    if v in _DEF_FALSE: return False
    return default

VERBOSE = _env_flag("VERBOSE", True)   # imprime progreso por defecto
STREAM = _env_flag("STREAM", True)      # streaming de tokens (activado por defecto)
STREAM_MAP = _env_flag("STREAM_MAP", True)    # streaming para bloques (map)
STREAM_FUSE = _env_flag("STREAM_FUSE", True)  # streaming para fusión (reduce)

def log(msg: str):
    if VERBOSE:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# Timeouts y control de troceo (ajustables por entorno)
CONNECT_TIMEOUT = float(os.environ.get("CONNECT_TIMEOUT", "10"))  # seg. para conectar
_READ_TO = os.environ.get("READ_TIMEOUT", "").strip()
READ_TIMEOUT = None if _READ_TO == "" else float(_READ_TO)          # None = sin límite (stream)
CHUNK_FRACTION = float(os.environ.get("CHUNK_FRACTION", "0.5"))    # fracción de NUM_CTX para cada bloque
OVERLAP_TOKENS = int(os.environ.get("OVERLAP_TOKENS", "200"))      # solape entre bloques

NON_CONTENT_TITLES = {
    # EN
    "cover","title","title page","copyright","acknowledgments","contents",
    "table of contents","index","dedication","preface","front matter",
    "foreword","about the author","bibliography","glossary","colophon","legal",
    # ES
    "cubierta","portada","créditos","agradecimientos","índice","tabla de contenido",
    "dedicatoria","prefacio","prólogo","epílogo","sobre el autor","acerca del autor",
    "biografía","bibliografía","glosario","colofón","licencia","nota del autor",
    "nota de la autora","nota del editor","nota de la editorial"
}

HREF_SKIP_REGEX = re.compile(
    r'(?:^|/)(?:toc\.(?:ncx|x?html?)|nav\.(?:x?html?)|'
    r'title|cover|copyright|acknowledg|front|colophon|'
    r'about|dedic|preface|foreword|prolog|epilog|gloss|biblio|legal)'
    r'|(?:^|/)index\.(?:x?html?)$',
    re.IGNORECASE,
)

def is_non_content_href(href: str) -> bool:
    h = (href or "").lower()
    return bool(HREF_SKIP_REGEX.search(h))

def is_content_title(title: str) -> bool:
    t = re.sub(r"\s+"," ", title or "").strip().lower()
    return bool(t) and all(k not in t for k in NON_CONTENT_TITLES)

def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script","style","nav","header","footer"]):
        tag.decompose()
    text_maker = html2text.HTML2Text()
    text_maker.ignore_links = False
    text_maker.body_width = 0
    md = text_maker.handle(str(soup))
    return re.sub(r"\n{3,}", "\n\n", md).strip()

def flatten_toc(toc) -> List[Tuple[str,str]]:
    out = []
    def walk(items):
        for it in items:
            if isinstance(it, epub.Link):
                out.append((it.title or "", it.href or ""))
            elif isinstance(it, tuple) and len(it) >= 2:
                node, children = it[0], it[1]
                if isinstance(node, epub.Link):
                    out.append((node.title or "", node.href or ""))
                if children: walk(children)
    walk(toc)
    # quita duplicados preservando orden
    seen, filtered = set(), []
    for t,h in out:
        key = (t.strip(), h.strip())
        if key not in seen:
            seen.add(key); filtered.append(key)
    return filtered

def read_epub_chapter_md(book: epub.EpubBook, href: str) -> str:
    base = (href or '').split('#', 1)[0]
    item = book.get_item_with_href(base)
    if not item:
        base_norm = (base or '').lstrip('./')
        for it in book.get_items():
            if getattr(it, 'href', '').lstrip('./') == base_norm:
                item = it
                break
    if not item:
        return ""
    content = item.get_content().decode("utf-8", errors="ignore")
    return html_to_markdown(content)

def ensure_md(path_md: Path):
    if not path_md.exists():
        path_md.write_text("# Resumen general\n\n# Resumen por capítulos\n", encoding="utf-8")

def append_chapter_summary(path_md: Path, title: str, summary: str):
    md = path_md.read_text(encoding="utf-8")
    block = f"\n\n## {title}\n\n{summary.strip()}\n"
    data = md + block
    # Escritura segura (flush + fsync) para FS de red/sincronizados
    try:
        with open(path_md, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        log(f"[warn] error escribiendo el .md: {e}")
        # Intento de respaldo sin fsync
        path_md.write_text(data, encoding="utf-8")
    # Verificación rápida
    try:
        new_md = path_md.read_text(encoding="utf-8")
        if f"## {title}" not in new_md:
            log(f"[warn] no se encontró el encabezado del capítulo recién añadido: {title}")
    except Exception as e:
        log(f"[warn] verificación de escritura falló: {e}")

def extract_chapter_summaries_section(path_md: Path) -> str:
    md = path_md.read_text(encoding="utf-8")
    m = re.search(r"# Resumen por capítulos\s*(.*)$", md, flags=re.S)
    return (m.group(1) if m else "").strip()

def write_general_summary(path_md: Path, general: str):
    md = path_md.read_text(encoding="utf-8")
    # reemplaza bloque tras "# Resumen general" sin tocar lo demás
    new_block = f"# Resumen general\n\n{general.strip()}\n\n"
    if "# Resumen general" in md:
        md = re.sub(r"# Resumen general\s*(?:\n+[^#].*?)?(?=\n#|\Z)",
                    new_block, md, flags=re.S)
    else:
        md = new_block + md
    path_md.write_text(md, encoding="utf-8")

# --- Sanitización de bloques de pensamiento oculto ---

def _strip_think(text: str) -> str:
    # Elimina cualquier bloque <think>…</think> que algún modelo pudiera devolver
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.IGNORECASE).strip()

# --- Normalización de párrafos en salidas largas ---
def _normalize_paragraphs(text: str, min_per: int = 3, max_per: int = 5) -> str:
    """Si llega como un solo bloque, agrupa por 3–5 frases y separa con salto de párrafo (línea en blanco)."""
    t = (text or "").strip()
    if not t:
        return t
    # si ya hay párrafos, respétalos
    if "\n\n" in t:
        return t
    # separar por finales de frase (., !, ?, …), conservando signos
    sents = re.split(r"(?<=[\.!?…])\s+", t)
    sents = [s.strip() for s in sents if s and s.strip()]
    if not sents:
        return t
    paras, cur = [], []
    for s in sents:
        cur.append(s)
        if len(cur) >= max_per:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        # si el último párrafo quedó muy corto y hay párrafos previos, reequilibrar
        if len(cur) < min_per and paras:
            paras[-1] = paras[-1] + " " + " ".join(cur)
        else:
            paras.append(" ".join(cur))
    return "\n\n".join(paras)

def approx_token_count(s: str) -> int:
    return max(1, len(s)//4)  # aprox 1 token ≈ 4 chars

def chunk_text(md: str, max_tokens: int, overlap_tokens: int = 300) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", md) if p.strip()]
    chunks, cur, cur_tokens = [], [], 0
    for p in paras:
        t = approx_token_count(p)
        if cur_tokens + t > max_tokens and cur:
            chunks.append("\n\n".join(cur))
            # solape desde el final
            ov, tokens = [], 0
            for para in reversed(cur):
                tokens += approx_token_count(para)
                ov.append(para)
                if tokens >= overlap_tokens: break
            cur = list(reversed(ov)); cur_tokens = sum(approx_token_count(x) for x in cur)
        cur.append(p); cur_tokens += t
    if cur: chunks.append("\n\n".join(cur))
    return chunks

def ollama_chat(prompt: str, *, stream: bool=None, tag: str="") -> str:
    """Llama a Ollama. Si stream=True, imprime tokens en tiempo real (si VERBOSE)."""
    if stream is None:
        stream = STREAM
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system",
             "content": ("Resume en prosa clara, directa y fiel. SIN listas ni viñetas. "
                         "No inventes datos. No uses primera persona. No simules ser el autor ni el narrador; "
                         "escribe en tercera persona neutra. Evita muletillas como «El autor explica…/El texto dice…». "
                         "No incluyas secciones de pensamiento ni etiquetas como <think>…</think> en la respuesta.")},
            {"role": "user", "content": prompt}
        ],
        "options": {"num_ctx": NUM_CTX, "temperature": TEMPERATURE, "num_predict": NUM_PREDICT},
        "stream": bool(stream)
    }
    if not stream:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=600)
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", "").strip()
    # Streaming (tolerante a fallos)
    log(f"[stream] inicio {tag or 'respuesta del modelo'}")
    full = ""
    try:
        with requests.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True,
                           timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except Exception:
                    continue
                if isinstance(chunk, dict):
                    msg = chunk.get("message", {})
                    tok = msg.get("content", "")
                    if tok:
                        full += tok
                        if VERBOSE:
                            print(tok, end="", flush=True)
                    if chunk.get("done"):
                        break
    except KeyboardInterrupt:
        log("[stream] interrumpido por el usuario; se usará lo acumulado")
    except requests.exceptions.Timeout:
        log("[stream] timeout de lectura; se usará lo acumulado")
    except requests.exceptions.RequestException as e:
        log(f"[stream] error de red: {e}; se usará lo acumulado")
    finally:
        if VERBOSE:
            print()
    full = full.strip()
    if full:
        return full
    # Fallback sin streaming si no acumulamos nada
    log("[stream] sin contenido acumulado; reintentando sin streaming…")
    r2 = requests.post(f"{OLLAMA_URL}/api/chat", json={**payload, "stream": False}, timeout=600)
    r2.raise_for_status()
    data2 = r2.json()
    return data2.get("message", {}).get("content", "").strip()

def summarize_chapter(title: str, chapter_md: str) -> str:
    max_for_text = int(NUM_CTX * CHUNK_FRACTION)  # ej.: 0.5 por defecto
    chunks = chunk_text(chapter_md, max_tokens=max_for_text, overlap_tokens=OVERLAP_TOKENS)
    partials = []
    for i, ck in enumerate(chunks, 1):
        prompt = (
        f"Resume en prosa y en español el siguiente contenido del capítulo «{title}». "
        f"Evita fórmulas como «El autor explica/afirma…», «El texto dice…» y no uses primera persona. "
        f"Escribe directamente las ideas en tercera persona, sin listas. No incluyas etiquetas <think>.\n\n"
        f"--- CONTENIDO ({i}/{len(chunks)}) ---\n{ck}\n"
        )
        log(f"  · map {i}/{len(chunks)} ({approx_token_count(ck)} tokens aprox; max_bloque={max_for_text})")
        partials.append(_strip_think(ollama_chat(prompt, stream=STREAM_MAP, tag=f"capítulo {title} · bloque {i}/{len(chunks)}")))
        time.sleep(0.3)
    if len(partials) == 1:
        log("  · fusión innecesaria (1 bloque)")
        return partials[0]
    fusion_prompt = ("Fusiona en un único resumen en prosa los sub-resúmenes de un mismo capítulo, "
                     "eliminando redundancias y manteniendo la coherencia. Escribe en 2–6 párrafos, "
                     "separando ideas mayores con salto de párrafo. Evita fórmulas tipo «El autor… / El texto…» "
                     "y escribe directamente las ideas, en voz activa y sin listas. No incluyas etiquetas <think>.\n\n"
                     + "\n\n---\n".join(partials))
    log("  · fusionando sub-resúmenes")
    return _normalize_paragraphs(_strip_think(ollama_chat(fusion_prompt, stream=STREAM_FUSE, tag=f"capítulo {title} · fusión")))

def summarize_book_from_chapter_summaries(summaries_md: str) -> str:
    prompt = ("A partir de los resúmenes por capítulo siguientes, escribe un ‘Resumen general’ del libro "
              "en 1–3 párrafos, en prosa clara y fiel (sin listas). Evita expresiones como «El autor…», "
              "«El libro dice…»; presenta directamente las ideas y conclusiones en tercera persona. "
              "No incluyas etiquetas <think>.\n\n" + summaries_md)
    return _normalize_paragraphs(_strip_think(ollama_chat(prompt)))

def process_epub(epub_path: Path):
    print(f"Procesando: {epub_path.name}")
    md_path = epub_path.with_name(epub_path.stem + "-RESUMEN.md")
    log(f"Libro: {epub_path.name}")
    log(f"Modelo={MODEL} | num_ctx={NUM_CTX} | num_predict={NUM_PREDICT} | temp={TEMPERATURE}")
    ensure_md(md_path)

    book = epub.read_epub(str(epub_path))
    toc_pairs = flatten_toc(book.toc)

    chapters = []
    for title, href in toc_pairs:
        if not href:
            continue
        if not is_content_title(title) or is_non_content_href(href):
            # Ej.: “Cubierta”, “Índice”, nav.xhtml, toc.ncx…
            continue
        chapters.append((title.strip() or "Capítulo", href))

    log(f"Capítulos tras filtrado: {len(chapters)}")

    if not chapters:
        print("TOC sin capítulos sustantivos; se omite.")
        return

    for idx, (title, href) in enumerate(chapters, 1):
        log(f"Capítulo {idx}/{len(chapters)}: {title}")
        chapter_md = read_epub_chapter_md(book, href)
        log("  · extrayendo y limpiando Markdown")
        if not chapter_md.strip():
            log(f"  · omitido: sin texto ({href})")
            continue
        # Heurísticas de “texto suficiente”: omite capítulos vacíos, muy cortos o solo con imágenes
        words = re.findall(r"\w+", chapter_md, flags=re.UNICODE)
        if len(words) < 60:  # umbral conservador; ajusta según prefieras
            log(f"  · omitido: <60 palabras ({len(words)}) ({href})")
            continue
        if re.fullmatch(r"(?:!\[.*?\]\(.*?\)\s*){1,}$", chapter_md.strip()):
            # capítulo compuesto solo por imágenes en Markdown
            log(f"  · omitido: solo imágenes ({href})")
            continue
        log(f"  · resumiendo (≈{approx_token_count(chapter_md)} tokens de entrada)")
        summary = summarize_chapter(title, chapter_md)
        append_chapter_summary(md_path, title, summary)
        log("  · añadido al .md")
        time.sleep(0.05)

    summaries_section = extract_chapter_summaries_section(md_path)
    if summaries_section:
        log("Metarresumen: generando a partir de ‘Resumen por capítulos’")
        general = summarize_book_from_chapter_summaries(summaries_section)
        write_general_summary(md_path, general)
        log(f"Metarresumen escrito en {md_path.name}")
    else:
        print("No se encontró ‘Resumen por capítulos’; metarresumen omitido.")

def main(directory: str):
    base = Path(directory)
    assert base.is_dir(), f"No es un directorio: {directory}"
    epubs = [p for p in sorted(base.iterdir()) if p.suffix.lower() == ".epub"]
    log(f"Encontrados {len(epubs)} EPUB en: {directory}")
    if not epubs:
        print("No hay EPUB en el directorio.")
        return
    for p in epubs:
        process_epub(p)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", help="Ruta al directorio con .epub")
    args = parser.parse_args()
    main(args.directory)