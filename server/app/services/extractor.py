import logging
import re
from pathlib import Path

import pdfplumber
from google import genai
from google.genai import types

from app.config import settings

log = logging.getLogger(__name__)

# Patrones para limpiar el texto extraído
_MULTI_BLANK = re.compile(r'\n{3,}')
_MULTI_SPACE = re.compile(r'[ \t]{2,}')


def extract_native(path: Path) -> str:
    """Extract full text from a native (text-based) PDF using pdfplumber."""
    log.info("Extracting native text: %s", path.name)
    pages_text = []

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            # Extraemos por palabras para evitar fusión de términos en PDFs de dos columnas
            words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
            if not words:
                log.debug("  Page %d empty, skipping", i + 1)
                continue
            text = _words_to_text(words)
            text = _clean(text)
            if text:
                pages_text.append(text)

    full_text = "\n\n".join(pages_text)
    log.info("  Extracted %d chars from %d pages", len(full_text), len(pages_text))
    return full_text


def _words_to_text(words: list[dict]) -> str:
    """Reconstruct text from word bounding boxes, preserving line breaks."""
    if not words:
        return ""
    lines = []
    current_line = [words[0]["text"]]
    prev_bottom = words[0]["bottom"]

    for w in words[1:]:
        # Nueva línea si la palabra empieza por debajo del baseline anterior
        if w["top"] > prev_bottom + 2:
            lines.append(" ".join(current_line))
            current_line = [w["text"]]
        else:
            current_line.append(w["text"])
        prev_bottom = w["bottom"]

    lines.append(" ".join(current_line))
    return "\n".join(lines)


def _clean(text: str) -> str:
    # Colapsar espacios múltiples y saltos de línea excesivos
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


_OCR_PROMPT = (
    "Extract all the text from this scientific document exactly as it appears. "
    "Preserve section headers and paragraph breaks. "
    "If there are multiple columns, read them in logical order (left to right, top to bottom). "
    "Return only the extracted text, no commentary, no markdown formatting."
)


def extract_ocr(path: Path) -> str:
    """Extract text from a vectorized PDF via Gemini Flash OCR."""
    log.info("Extracting OCR text: %s", path.name)

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.ocr_model,
        contents=[
            types.Part.from_bytes(data=path.read_bytes(), mime_type="application/pdf"),
            _OCR_PROMPT,
        ],
    )

    text = _clean(response.text.strip())
    log.info("  OCR extracted %d chars", len(text))
    return text
