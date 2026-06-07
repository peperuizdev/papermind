import logging
import re
import uuid

log = logging.getLogger(__name__)

# Mapeo de cabeceras detectadas a secciones IMRaD estándar (None = descartar)
_SECTION_MAP: dict[str, str | None] = {
    "abstract": "abstract",
    "introduction": "introduction",
    "background": "introduction",
    "materials and methods": "methods",
    "materials & methods": "methods",
    "material and methods": "methods",
    "material & methods": "methods",
    "material and method": "methods",
    "material & method": "methods",
    "methods and materials": "methods",
    "methods": "methods",
    "method": "methods",       # variante singular (e.g. "3. Method")
    "methodology": "methods",
    "experimental": "methods",
    "results and discussion": "results",
    "results": "results",
    "result": "results",       # variante singular (e.g. "Result" en 3.3.3)
    "discussion and conclusions": "discussion",
    "discussion": "discussion",
    "conclusions": "conclusion",
    "conclusion": "conclusion",
    "summary": "conclusion",
    # Variantes clínicas y cosméticas frecuentes → Methods
    "subjects": "methods",
    "volunteers": "methods",
    "participants": "methods",
    "population": "methods",
    "study design": "methods",
    "study population": "methods",
    "clinical study": "methods",
    "clinical trial": "methods",
    "study protocol": "methods",
    "formulation": "methods",
    "characterization": "results",
    "in vitro": "results",
    "in vivo": "results",
    "clinical results": "results",
    "efficacy": "results",
    # Secciones a descartar (ruido para retrieval)
    "references": None,
    "bibliography": None,
    "acknowledgments": None,
    "acknowledgements": None,
    "appendix": None,
    "supplementary": None,
}

# Regex para detectar cabeceras de sección (con o sin numeración, con o sin dos puntos)
_HEADER_RE = re.compile(
    r"^\s*(?:\d+[\.\s]*)?\s*"
    r"(Abstract|Introduction|Background|"
    r"Materials?\s+(?:and|&)\s+Methods?|Methods?\s+(?:and|&)\s+Materials?|"
    r"Methods?|Methodology|Experimental(?:\s+Section)?|"
    r"Results?(?:\s+and\s+Discussion)?|"
    r"Discussion(?:\s+(?:and\s+)?(?:Conclusions?|Results?))?|"
    r"Conclusions?|Summary|"
    r"Subjects?|Volunteers?|Participants?|Population|"
    r"Study\s+(?:Design|Population|Protocol)|"
    r"Clinical\s+(?:Study|Trial|Results?|Test)|"
    r"Formulation|Characterization|"
    r"In\s+[Vv]itro|In\s+[Vv]ivo|Efficacy|"
    r"References?|Bibliography|Acknowledgm?ents?|Appendix|Supplementary)"
    r"\s*[:\.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Regex para extraer keywords — para antes de sección IMRaD o línea en blanco
_KEYWORDS_RE = re.compile(
    r"(?:keywords?|key\s+words?)\s*:?\s*\n?\s*(.+?)"
    r"(?=\n\s*\n"
    r"|\n\s*(?:abstract|introduction|background|material|method|result|discussion|conclusion|reference|acknowledgment)\b"
    r"|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# Regex para detectar fin del título (autores, afiliaciones, emails)
# Cabeceras de congreso/journal que aparecen como header de página (no son el título)
_CONF_HEADER_RE = re.compile(
    r"^\d+(?:st|nd|rd|th)\s+"                              # "34rd ..."
    r"|(?:Congress|Symposium|Conference|Workshop).*\d{4}"  # "Congress ... 2024"
    r"|\d{4}.*(?:Congress|Symposium|Conference|Workshop)",  # "2024 ... Congress"
    re.IGNORECASE,
)

# Detectores de fin de título: email, teléfono, afiliaciones, listas de autores
_TITLE_END_RE = re.compile(
    r"@|Tel:|E-mail:|http"
    r"|\+\d{1,3}[-\s]\d"                          # teléfono con prefijo: "+81-6..."
    r"|^\s*\d+\s*[A-Z]"                           # afiliación numerada: "1Mageline..."
    r"|^\s*[A-Z][a-z]+,\s*[A-Z][a-z]"            # autor occidental: "Apellido, Nombre"
    r"|\d+\s*[;,]\s*[A-Z]"                       # autor IFSCC: "Wang Zheng1; Ling..."
    r"|\d+\s*;"                                   # superíndice: "Zheng1;"
    r"|[A-Z][a-z]+\s+[A-Z][a-z]+[\s\*]*;"        # autor sin dígito: "Wang Hua;"
    r"|\d+\s*\*"                                  # corresponding author: "Wilson1*"
    r"|(?:[A-Z][a-z]+\s+[A-Z][a-z]+,\s*){2,}"   # lista de autores: "Joaquim Lima, Pascal Arnaud, ..."
    r"|[A-Za-z][a-z]+[¹²³⁴⁵⁶⁷⁸⁹⁰]",            # superíndice unicode: "Batisti¹"
    re.MULTILINE,
)

_MAX_CHUNK_CHARS = 6000   # ~1500 tokens, margen seguro para text-embedding-3-large
_OVERLAP_CHARS   = 300    # solapamiento entre sub-chunks de secciones largas


def chunk_document(text: str, file_meta: dict) -> list[dict]:
    """Divide un documento en chunks IMRaD con metadatos completos."""
    study_id = file_meta["study_id"]
    doc_type  = file_meta["doc_type"]

    # Documentos cortos (abstracts OCR): un único chunk sin división IMRaD
    if doc_type == "short":
        keywords = _extract_keywords(text)
        title    = _extract_title(text)
        log.info("[%s] short doc → 1 chunk | title: %s | keywords: %s", study_id, title[:60], keywords)
        file_meta = {**file_meta, "title": title, "keywords": keywords}
        return _make_chunks(text, "abstract", file_meta, keywords)

    # Extraer keywords y título antes de chunking
    keywords = _extract_keywords(text)
    title    = _extract_title(text)
    log.info("[%s] title: %s", study_id, title[:60])
    log.info("[%s] keywords: %s", study_id, keywords)

    # Enriquecer metadatos con título y keywords extraídos
    file_meta = {**file_meta, "title": title, "keywords": keywords}

    # Quitar lista de referencias aunque no tenga cabecera explícita
    text = _strip_implicit_references(text)

    sections = _split_imrad(text)
    chunks = []
    for section_name, section_text in sections.items():
        if not section_text.strip():
            continue
        section_chunks = _make_chunks(section_text, section_name, file_meta, keywords)
        chunks.extend(section_chunks)
        log.info("  [%s] %-20s → %d chunk(s)", study_id, section_name, len(section_chunks))

    log.info("[%s] total chunks: %d", study_id, len(chunks))
    return chunks


def _split_imrad(text: str) -> dict[str, str]:
    """Divide el texto en secciones según cabeceras IMRaD detectadas."""
    matches = list(_HEADER_RE.finditer(text))
    if not matches:
        log.warning("No IMRaD headers found, treating entire text as body")
        return {"body": text}

    sections: dict[str, str] = {}

    # Texto antes del primer header → metadatos del paper (título + autores), no se indexa
    for i, match in enumerate(matches):
        header_raw  = match.group(1).strip()
        section_key = _normalize_header(header_raw)
        if section_key is None:
            # Sección descartada (References, Acknowledgments, etc.)
            continue

        start = match.end()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        if not content:
            continue

        # Concatenar si la misma sección aparece más de una vez
        if section_key in sections:
            sections[section_key] += "\n\n" + content
        else:
            sections[section_key] = content

    return sections


def _normalize_header(raw: str) -> str | None:
    """Mapea una cabecera detectada a su clave IMRaD estándar."""
    key = raw.lower().strip().rstrip(":")
    # Búsqueda exacta primero
    if key in _SECTION_MAP:
        return _SECTION_MAP[key]
    # Búsqueda por prefijo para variantes no previstas
    for map_key, map_val in _SECTION_MAP.items():
        if key.startswith(map_key):
            return map_val
    return "body"


def _make_chunks(
    text: str, section: str, file_meta: dict, keywords: list[str]
) -> list[dict]:
    """Crea uno o más chunks del texto de una sección, con solapamiento si es necesario."""
    if len(text) <= _MAX_CHUNK_CHARS:
        return [_build_chunk(text, section, file_meta, 0)]

    # Sección larga: dividir en sub-chunks con solapamiento en límite de palabra
    chunks = []
    pos, idx = 0, 0
    while pos < len(text):
        end = _word_boundary(text, min(pos + _MAX_CHUNK_CHARS, len(text)))
        sub = text[pos:end]
        chunks.append(_build_chunk(sub, section, file_meta, idx))
        pos = _word_boundary(text, pos + _MAX_CHUNK_CHARS - _OVERLAP_CHARS)
        idx += 1
    return chunks


def _word_boundary(text: str, pos: int) -> int:
    """Avanza hasta el siguiente espacio o salto de línea para no cortar palabras."""
    if pos >= len(text):
        return len(text)
    while pos < len(text) and text[pos] not in (" ", "\n"):
        pos += 1
    return pos


def _build_chunk(text: str, section: str, file_meta: dict, idx: int) -> dict:
    """Construye el dict final de un chunk con metadatos completos."""
    # UUID5 determinista: misma entrada → mismo ID → permite upsert idempotente
    chunk_id = str(uuid.uuid5(
        uuid.NAMESPACE_DNS,
        f"{file_meta['study_id']}_{file_meta['doc_type']}_{section}_{idx}",
    ))

    return {
        "text": text,
        "metadata": {
            "study_id":        file_meta["study_id"],
            "doc_type":        file_meta["doc_type"],
            "related_study_id": file_meta.get("related_study_id"),
            "section":         section,
            "tipo":            "text",
            "title":           file_meta.get("title", ""),
            "keywords":        file_meta.get("keywords", []),
            "drive_link":      file_meta.get("drive_link"),
            "chunk_file_id":   chunk_id,
        },
    }


def _extract_keywords(text: str) -> list[str]:
    """Extrae las keywords del paper."""
    m = _KEYWORDS_RE.search(text)
    if not m:
        return []
    raw = m.group(1).strip()
    # Separar por punto y coma, coma o salto de línea
    parts = re.split(r"[;,\n]+", raw)
    # Descartar fragmentos largos (texto capturado por error) y limpiar puntuación final
    keywords = [
        p.strip().rstrip(".,;:")
        for p in parts
        if p.strip() and len(p.strip()) <= 60
    ]
    log.debug("  Keywords found: %s", keywords)
    return keywords


# Patrón de referencia bibliográfica numerada (e.g. "1. Author" o "1 Author")
_REF_LINE_RE = re.compile(r"^\s*\d+[\.\)]\s+[A-Z]", re.MULTILINE)


def _strip_implicit_references(text: str) -> str:
    """Elimina lista de referencias al final del texto aunque no tenga cabecera explícita."""
    # Buscar solo en el último tercio del documento para evitar falsos positivos
    cutoff = len(text) * 2 // 3
    tail = text[cutoff:]
    matches = list(_REF_LINE_RE.finditer(tail))
    if len(matches) >= 3:
        # Primera referencia numerada en el último tercio → cortar ahí
        first_ref_pos = cutoff + matches[0].start()
        log.debug("  Implicit references detected at char %d, stripping", first_ref_pos)
        return text[:first_ref_pos].strip()
    return text


def _extract_title(text: str) -> str:
    """Extrae el título del paper (líneas iniciales antes de autores/afiliaciones)."""
    lines = text.split("\n")
    title_lines: list[str] = []
    collecting = False

    for line in lines[:25]:
        stripped = line.strip()
        if not stripped:
            if title_lines:
                break  # primera línea en blanco tras título = fin
            continue
        if _TITLE_END_RE.search(stripped):
            break  # línea de autor/afiliación/email

        # Saltar cabeceras de congreso/journal antes de encontrar el título real
        if not collecting and _CONF_HEADER_RE.search(stripped):
            continue

        collecting = True
        title_lines.append(stripped)
        if len(title_lines) >= 5:
            break

    return " ".join(title_lines)
