from __future__ import annotations
from typing import Iterable, Tuple, Protocol

class BaseExtractor(Protocol):
    """
    Protocolo común: cada extractor produce pares (title, markdown_text).
    """
    def sections(self) -> Iterable[Tuple[str, str]]:   # noqa: D401
        ...