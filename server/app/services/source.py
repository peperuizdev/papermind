import logging
import re
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

_FULL = re.compile(r'^FAM\s+(\d+)\.pdf$', re.IGNORECASE)
_SHORT = re.compile(r'^FAM\s+(\d+)\s+-\s+.+\.pdf$', re.IGNORECASE)


def list_pdfs() -> list[dict]:
    docs_path = Path(settings.docs_path)
    log.info("Scanning PDFs in %s", docs_path.resolve())

    # Primera pasada: parsear todos los archivos
    raw = []
    for pdf in sorted(docs_path.glob("*.pdf")):
        meta = _parse_filename(pdf)
        if meta:
            raw.append({"path": pdf, **meta})
        else:
            log.warning("Skipping unrecognized filename: %s", pdf.name)

    # Cruzar IDs para enlace bidireccional: solo enlaza si el par existe en el directorio
    full_ids  = {d["study_id"] for d in raw if d["doc_type"] == "full"}
    short_ids = {d["study_id"] for d in raw if d["doc_type"] == "short"}

    results = []
    for d in raw:
        if d["doc_type"] == "full":
            related = d["study_id"] if d["study_id"] in short_ids else None
        else:
            related = d["study_id"] if d["study_id"] in full_ids else None
        results.append({**d, "related_study_id": related})

    log.info("Found %d PDFs (%d full, %d short)",
             len(results),
             sum(1 for d in results if d["doc_type"] == "full"),
             sum(1 for d in results if d["doc_type"] == "short"))
    return results


def _parse_filename(path: Path) -> dict | None:
    name = path.name

    if m := _FULL.match(name):
        num = m.group(1)
        return {
            "study_id": f"FAM-{num}",
            "doc_type": "full",
            "related_study_id": None,
        }

    if m := _SHORT.match(name):
        num = m.group(1)
        return {
            "study_id": f"FAM-{num}",
            "doc_type": "short",
            "related_study_id": f"FAM-{num}",
        }

    return None
