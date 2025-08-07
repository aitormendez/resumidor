from __future__ import annotations
import sys
from pathlib import Path

from .config import log
from .epub_extractor import EpubExtractor
from .summarizer import Summarizer

from .pdf_extractor import PdfExtractor

def process_path(path: Path):
    """Crear el extractor adecuado (.epub o .pdf) y lanzar el resumidor."""
    if path.suffix.lower() == ".epub":
        extractor = EpubExtractor(path)
    elif path.suffix.lower() == ".pdf":
        extractor = PdfExtractor(path)
    else:
        return
    out_md = path.with_name(path.stem + "-RESUMEN.md")
    Summarizer(extractor, out_md).run()


def main():
    if len(sys.argv) < 2:
        print("Uso: python -m epub_resumidor.cli <directorio_con_epub_o_pdf>")
        sys.exit(1)

    base = Path(sys.argv[1]).expanduser()
    if not base.is_dir():
        print("No es un directorio:", base)
        sys.exit(1)

    files = sorted(
        p for p in base.iterdir() if p.suffix.lower() in {".epub", ".pdf"}
    )

    num_epub = sum(1 for p in files if p.suffix.lower() == ".epub")
    num_pdf = sum(1 for p in files if p.suffix.lower() == ".pdf")
    log(f"Encontrados {num_epub} EPUB y {num_pdf} PDF")

    if not files:
        print("No hay EPUB ni PDF en el directorio.")
        return

    for p in files:
        process_path(p)

if __name__=="__main__":
    main()