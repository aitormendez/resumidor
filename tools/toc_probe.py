#!/usr/bin/env python3
"""
Probe tool to debug EPUB TOC entries and the content each entry points to.
It prints, for every TOC item, its (title, href), the base file and fragment
(anchor), whether the EPUB item resolves, and the size/hash of the extracted
content (HTML→Markdown). It also compares two href filters: the OLD one that
blacklists any href containing 'index', and the NEW regex-based filter that
only skips pure index.html/xhtml, toc/nav/cover/credits, etc.

Usage:
  python toc_probe.py \
    "/path/to/book.epub" [--max 40] [--no-md-normalize]

Interpretation tips:
- If many entries share the same BASE and produce the same MD hash, your
  pipeline that ignores the fragment ("#...") is feeding the same section to
  the summarizer for multiple chapters.
- If OLD_SKIP=True but NEW_SKIP=False for many entries like 'index_split_001',
  the old filter was over-aggressive.
"""

import sys, re, hashlib, argparse
from pathlib import Path

try:
    from ebooklib import epub
except Exception as e:
    print("[ERR] ebooklib no está instalado:", e, file=sys.stderr)
    sys.exit(1)

try:
    import html2text as _h2t
    _H2T = _h2t.HTML2Text()
    _H2T.body_width = 0
    _H2T.ignore_links = False
    _H2T.ignore_images = False
except Exception:
    _H2T = None

# --- OLD filter (problematic: excludes any href containing 'index')
OLD_HREF_SKIP_PATTERNS = (
    "cover","title","toc","nav","copyright","acknowledg","front",
    "colophon","index","about","dedic","preface","foreword","prolog",
    "epilog","gloss","biblio","legal"
)

def old_is_non_content_href(href: str) -> bool:
    h = (href or "").lower()
    return any(key in h for key in OLD_HREF_SKIP_PATTERNS)

# --- NEW regex-based filter (keeps index_split_*.xhtml but skips pure index.html)
NEW_HREF_SKIP_REGEX = re.compile(
    r'(?:^|/)(?:toc\.(?:ncx|x?html?)|nav\.(?:x?html?)|'
    r'title|cover|copyright|acknowledg|front|colophon|'
    r'about|dedic|preface|foreword|prolog|epilog|gloss|biblio|legal)'
    r'|(?:^|/)index\.(?:x?html?)$',
    re.IGNORECASE,
)

def new_is_non_content_href(href: str) -> bool:
    return bool(NEW_HREF_SKIP_REGEX.search((href or '').lower()))

NON_CONTENT_TITLES = {
    "cover","title","title page","copyright","acknowledgments","contents",
    "table of contents","index","dedication","preface","front matter",
    "foreword","about the author","bibliography","glossary","colophon","legal",
    "cubierta","portada","créditos","agradecimientos","índice","tabla de contenido",
    "dedicatoria","prefacio","prólogo","epílogo","sobre el autor","acerca del autor",
    "biografía","bibliografía","glosario","colofón","licencia","nota del autor",
    "nota de la autora","nota del editor","nota de la editorial"
}

def is_content_title(title: str) -> bool:
    t = re.sub(r"\s+"," ", title or "").strip().lower()
    return bool(t) and all(k not in t for k in NON_CONTENT_TITLES)

# --- TOC flatten ---

def flatten_toc(toc):
    out = []
    def walk(items):
        for it in items:
            if isinstance(it, epub.Link):
                out.append((it.title or "", it.href or ""))
            elif isinstance(it, tuple) and len(it) >= 2:
                node, childs = it[0], it[1]
                if isinstance(node, epub.Link):
                    out.append((node.title or "", node.href or ""))
                if childs:
                    walk(childs)
    walk(toc)
    # dedup by (title, href)
    seen, filt = set(), []
    for t, h in out:
        key = (t.strip(), h.strip())
        if key not in seen:
            seen.add(key); filt.append(key)
    return filt

# --- content extraction ---

def get_item_html(book: epub.EpubBook, href: str):
    base = (href or '').split('#', 1)[0]
    item = book.get_item_with_href(base)
    if not item:
        base_norm = base.lstrip('./')
        for it in book.get_items():
            if getattr(it, 'href', '').lstrip('./') == base_norm:
                item = it; break
    if not item:
        return base, '', None, b''
    try:
        raw = item.get_content()
    except Exception:
        raw = b''
    return base, '', item, raw


def html_to_md(html_bytes: bytes) -> str:
    if not html_bytes:
        return ""
    html = html_bytes.decode('utf-8', errors='ignore')
    if _H2T is None:
        return re.sub(r"\s+", " ", html).strip()  # crude fallback
    return _H2T.handle(html)


def md_hash(text: str, normalize: bool=True) -> str:
    if normalize:
        text = re.sub(r"\s+", " ", (text or "").strip())
    return hashlib.md5(text.encode('utf-8')).hexdigest()

# --- main ---

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('epub_path', help='Ruta al archivo .epub')
    ap.add_argument('--max', type=int, default=9999, help='Limitar número de entradas mostradas')
    ap.add_argument('--no-md-normalize', action='store_true', help='No normalizar espacios antes del hash')
    args = ap.parse_args()

    p = Path(args.epub_path)
    if not p.is_file():
        print(f"[ERR] No existe archivo: {p}")
        sys.exit(2)

    try:
        book = epub.read_epub(str(p))
    except Exception as e:
        print(f"[ERR] No se pudo leer EPUB: {e}")
        sys.exit(3)

    pairs = flatten_toc(book.toc)

    print(f"TOC entradas: {len(pairs)}  (mostrando hasta {args.max})\n")
    print(f"{'#':>3}  {'OLD_SKIP':<8} {'NEW_SKIP':<8} {'TIT_OK':<6}  {'base==prev?':<11}  {'MD_DUP_BASE?':<12}  title → href")
    print('-'*120)

    base_first_hash = {}
    prev_base = None
    shown = 0
    for idx, (title, href) in enumerate(pairs, 1):
        if shown >= args.max:
            break
        old_skip = old_is_non_content_href(href)
        new_skip = new_is_non_content_href(href)
        tit_ok = is_content_title(title)

        base = (href or '').split('#', 1)[0]
        frag = (href.split('#',1)[1] if '#' in (href or '') else '')
        base_eq_prev = (base == prev_base)
        prev_base = base

        base, _frag_unused, item, html_bytes = get_item_html(book, href)
        html_len = len(html_bytes)
        md = html_to_md(html_bytes)
        md_len = len(md)
        h = md_hash(md, normalize=not args.no_md_normalize) if md_len else ''

        md_dup_base = ''
        if base and h:
            if base not in base_first_hash:
                base_first_hash[base] = h
            else:
                md_dup_base = 'YES' if base_first_hash[base] == h else 'NO'

        title_disp = (title or '').strip().replace('\n',' ')
        if len(title_disp) > 60:
            title_disp = title_disp[:57] + '…'
        href_disp = (href or '').strip()
        if len(href_disp) > 80:
            href_disp = '…' + href_disp[-79:]

        print(f"{idx:>3}  {str(old_skip):<8} {str(new_skip):<8} {str(tit_ok):<6}  {str(base_eq_prev):<11}  {md_dup_base or '-':<12}  {title_disp!r} -> {href_disp!r}  | html={html_len} md={md_len} hash={h[:8] if h else ''}")
        shown += 1

    print('\nResumen:')
    print(f"  Bases únicas en TOC: {len(set((h or '').split('#',1)[0] for _,h in pairs))}")
    print(f"  Entradas marcadas OLD_SKIP=True: {sum(1 for _,h in pairs if old_is_non_content_href(h))}")
    print(f"  Entradas marcadas NEW_SKIP=True: {sum(1 for _,h in pairs if new_is_non_content_href(h))}")

if __name__ == '__main__':
    main()