from __future__ import annotations
import sys
from pathlib import Path

from .config import log
from .epub_extractor import EpubExtractor
from .summarizer import Summarizer

def process_epub(epub_path:Path):
    log(f"Procesando: {epub_path.name}")
    out_md = epub_path.with_name(epub_path.stem+"-RESUMEN.md")
    extractor = EpubExtractor(epub_path)
    Summarizer(extractor, out_md).run()

def main():
    if len(sys.argv)<2:
        print("Uso: python -m epub_resumidor.cli <directorio_con_epub>")
        sys.exit(1)
    base = Path(sys.argv[1]).expanduser()
    if not base.is_dir():
        print("No es un directorio:", base); sys.exit(1)
    epubs = sorted(p for p in base.iterdir() if p.suffix.lower()==".epub")
    log(f"Encontrados {len(epubs)} EPUB")
    if not epubs:
        print("No hay EPUB en el directorio."); return
    for p in epubs:
        process_epub(p)

if __name__=="__main__":
    main()