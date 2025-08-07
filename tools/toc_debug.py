#!/usr/bin/env python3
import sys, re
from pathlib import Path
from ebooklib import epub
from epub_resumidor.utils import flatten_toc

# Copiamos las mismas reglas del script actual
NON_CONTENT_TITLES = {
    "cover","title","title page","copyright","acknowledgments","contents",
    "table of contents","index","dedication","preface","front matter",
    "foreword","about the author","bibliography","glossary","colophon","legal",
    "cubierta","portada","créditos","agradecimientos","índice","tabla de contenido",
    "dedicatoria","prefacio","prólogo","epílogo","sobre el autor","acerca del autor",
    "biografía","bibliografía","glosario","colofón","licencia","nota del autor",
    "nota de la autora","nota del editor","nota de la editorial"
}
HREF_SKIP_PATTERNS = (
    "cover","title","toc","nav","copyright","acknowledg","front",
    "colophon","index","about","dedic","preface","foreword","prolog",
    "epilog","gloss","biblio","legal"
)
def is_non_content_href(href: str) -> bool:
    h = (href or "").lower()
    return any(key in h for key in HREF_SKIP_PATTERNS)

def is_content_title(title: str) -> bool:
    import re
    t = re.sub(r"\s+"," ", title or "").strip().lower()
    return bool(t) and all(k not in t for k in NON_CONTENT_TITLES)


def main(path):
    book = epub.read_epub(path)
    pairs = flatten_toc(book.toc)
    print(f"TOC entradas: {len(pairs)}\n")
    print("Primeras 10 entradas (titulo → href):")
    for i,(t,h) in enumerate(pairs[:10],1):
        print(f"{i:>2}. {t!r} -> {h!r}")
    print("\nDiagnóstico por entrada (por qué se filtra o no):")
    kept=0; dropped=0
    for t,h in pairs:
        reasons=[]
        if not h: reasons.append("href vacío")
        if not is_content_title(t): reasons.append("titulo no-sustantivo")
        if is_non_content_href(h): reasons.append("href no-sustantivo (coincide patrón)")
        if reasons:
            dropped+=1
            print(f"X  DESCARTADO: {t!r} -> {h!r} :: {', '.join(reasons)}")
        else:
            kept+=1
            # prueba de resolución: ancla y tamaño de contenido
            base = h.split('#',1)[0]
            item = book.get_item_with_href(base)
            size = len(item.get_content()) if item else 0
            print(f"✓  MANTENIDO:  {t!r} -> {h!r}  | base={base!r}  | item={'OK' if item else 'NONE'} size={size}")
    print(f"\nResumen: mantenidos={kept}, descartados={dropped}")

if __name__ == "__main__":
    p = sys.argv[1]
    main(p)