import logging
from pathlib import Path

from pypdf import PdfReader

log = logging.getLogger(__name__)

_MIN_CHARS = 100


def classify(path: Path) -> str:
    """Devuelve 'native' si el PDF tiene texto extraíble, 'ocr' si no."""
    try:
        reader = PdfReader(str(path), strict=False)
        page = reader.pages[0]
        text = (page.extract_text() or "").strip()
        if len(text) >= _MIN_CHARS:
            log.debug("%s → native (%d chars)", path.name, len(text))
            return "native"
        log.debug("%s → ocr (%d chars extracted from page 1)", path.name, len(text))
        return "ocr"
    except Exception as e:
        log.warning("%s → ocr (read error: %s)", path.name, e)
        return "ocr"
