# PaperMind — Asistente RAG para investigación cosmética

Herramienta de consulta inteligente que permite al equipo de R&D de Famousplace Cosmetics interrogar en lenguaje natural el corpus de estudios científicos internos, obteniendo respuestas sintetizadas con trazabilidad directa a los documentos originales.

---

## Historias de usuario

**H1 — Investigadora de ingredientes**
> Como investigadora de R&D, quiero preguntar qué estudios tenemos sobre un ingrediente activo concreto y recibir un resumen de los hallazgos más relevantes, para no tener que revisar manualmente decenas de PDFs cuando empieza un proyecto de formulación.

**H2 — Formuladora senior**
> Como formuladora, quiero obtener un resumen de las conclusiones de todos los estudios sobre un ingrediente en una aplicación específica (por ejemplo, ácido hialurónico en pintalabios), para identificar rápidamente qué funciona, qué no y qué queda sin resolver.

**H3 — Directora de innovación**
> Como directora de innovación, quiero poder hacer preguntas de síntesis transversal ("¿coinciden estos estudios en algún punto?") en una conversación continua, para detectar patrones comunes entre líneas de investigación sin necesidad de cruzar documentos a mano.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FLUJO DE CONSULTA                            │
│                                                                     │
│  [Usuario]                                                          │
│     │  pregunta en lenguaje natural                                 │
│     ▼                                                               │
│  [React Chat UI]  ──POST /webhook/papermind-chat──►  [n8n Webhook]  │
│     ◄── typewriter effect ─────────────────────────      │          │
│                                                    [AI Agent]       │
│                                               Gemini 2.5 Flash      │
│                                                    │                │
│                              ┌─────────────────────┤               │
│                              │                     │               │
│                    tool: Buscar             tool: Obtener           │
│                    en estudios              estudio                 │
│                              │                     │               │
│                              ▼                     ▼               │
│                     [FastAPI /api/search]  [FastAPI /api/study]     │
│                              │                                      │
│                    ┌─────────┴──────────┐                           │
│                    │                    │                           │
│              [OpenAI]            [Qdrant]  ◄──► [Cohere Rerank]     │
│           text-embedding      vector store     multilingual v3.0    │
│             -3-large                                                │
│                                                                     │
│  [PostgreSQL] ◄──► [AI Agent]  (memoria de conversación)           │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      FLUJO DE INGESTA                               │
│                                                                     │
│  Opción A — Lote local                                              │
│  POST /api/ingest  ──►  PDFs en DOCS_PATH  ──►  pipeline           │
│                                                                     │
│  Opción B — Google Drive (automático)                               │
│  [Google Drive]  ──trigger n8n──►  descarga PDF                     │
│                               ──►  POST /api/ingest/file            │
│                                    (con drive_link en metadata)     │
│                                                                     │
│  Pipeline común:                                                    │
│  PDF  ──►  Triage (native/OCR)  ──►  Extracción de texto           │
│        ──►  Chunking IMRaD       ──►  Embedding OpenAI              │
│        ──►  Upsert Qdrant        ──►  (idempotente por UUID5)       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## El proceso RAG explicado

### 1 · Ingesta

Antes de poder responder preguntas, los documentos se procesan y almacenan en la base de datos vectorial.

**Triage del PDF**
Cada PDF pasa por un clasificador que determina si tiene texto extraíble (`native`) o si es un documento vectorizado sin capa de texto (`ocr`). Los PDFs nativos se procesan con `pdfplumber`, que extrae texto preservando la estructura espacial de columnas. Los vectorizados se envían a Gemini Flash, que los lee visualmente y devuelve el texto en orden lógico.

**Chunking por secciones IMRaD**
El texto extraído no se trocea por tamaño fijo sino por estructura científica: Abstract, Introduction, Methods, Results, Discussion y Conclusion. Cada sección se convierte en uno o varios chunks con solapamiento de 300 caracteres entre chunks de la misma sección cuando el texto es largo. Esto garantiza que las preguntas sobre metodología recuperen chunks de Methods, y las preguntas sobre resultados recuperen chunks de Results — no mezclas aleatorias.

El corpus incluye dos tipos de documento para cada estudio: el artículo completo (`full`) y un abstract extendido (`short`). Ambos se indexan por separado, lo que permite búsquedas en profundidad o en amplitud según la necesidad.

**Metadatos por chunk**
Cada chunk almacena en su payload: `study_id`, `title`, `section`, `doc_type`, `keywords`, `drive_link` y un `chunk_file_id` UUID5 determinista. El UUID5 hace que re-ingestar el mismo documento sea idempotente: los chunks se actualizan en Qdrant sin crear duplicados.

**Embedding**
Cada chunk se embede con `text-embedding-3-large` de OpenAI (3072 dimensiones, COSINE distance). El embedding del título y keywords del paper se concatena implícitamente al texto del chunk antes de embeder, lo que mejora la recuperación por nombre de estudio o ingrediente.

### 2 · Búsqueda semántica + reranking

Cuando el usuario hace una pregunta, el AI Agent invoca la herramienta **Buscar en estudios**.

**Búsqueda vectorial densa**
La consulta se embede con el mismo modelo. Se recuperan `top_k × 3` candidatos de Qdrant (por defecto 24) con filtros opcionales de metadata: `doc_type`, `sections`, `study_id` o `keywords`. Recuperar más candidatos de los necesarios aumenta el recall antes de que el reranker decida.

**Reranking con Cohere**
Los candidatos se reordenan por relevancia semántica real usando `rerank-multilingual-v3.0`. El reranker evalúa la relación entre la consulta y el texto completo del chunk, no solo la similitud vectorial. Esto corrige los casos en que la búsqueda densa recupera chunks temáticamente cercanos pero contextualmente irrelevantes.

**Etiqueta de relevancia**
El score numérico del reranker (0–1) se convierte en una etiqueta semántica antes de enviarse al modelo: `alta` (≥ 0.50), `media` (≥ 0.20), `baja` (< 0.20). El LLM recibe contexto cualitativo, no un número que pudiera repetir al usuario o malinterpretar.

### 3 · Síntesis con el AI Agent

El AI Agent de n8n (Gemini 2.5 Flash) recibe los chunks recuperados y genera una respuesta en español. Tiene acceso a dos herramientas:

- **Buscar en estudios**: búsqueda semántica con filtros. Es la herramienta de primer recurso para cualquier consulta temática.
- **Obtener estudio**: recupera todos los chunks de un estudio concreto ordenados por sección IMRaD. Se usa cuando el usuario pide detalle sobre un estudio específico o cuando la búsqueda general no es suficiente.

La memoria de conversación se persiste en PostgreSQL. Cada sesión mantiene su historial independiente, lo que permite preguntas de seguimiento como "¿y esos estudios coinciden en algo?" sin perder el contexto anterior.

### 4 · Integración con Google Drive

Un segundo workflow de n8n monitoriza una carpeta de Google Drive. Cuando se sube un nuevo PDF con el naming convention esperado (`FAM 123.pdf` para artículo completo, `FAM 123 - titulo.pdf` para abstract), el workflow lo descarga y llama a `/api/ingest/file` pasando el contenido del PDF y el enlace de Drive. El backend procesa el documento a través del pipeline completo y almacena el `drive_link` en el payload de cada chunk. Desde ese momento, cualquier respuesta del agente que cite ese estudio puede incluir el enlace directo al documento original en Drive.

---

## Decisiones de diseño

### 1 · Chunking semántico por secciones IMRaD

**Decisión**: dividir los papers por sección científica en lugar de por ventana de tokens.

**Por qué**: los papers científicos tienen estructura predecible. Una pregunta sobre eficacia clínica debe recuperar "Results" y "Discussion", no el abstract ni la metodología. El chunking por tamaño fijo corta secciones a la mitad y mezcla contenido heterogéneo. El chunking IMRaD produce chunks coherentes y mejora la precisión del retrieval.

**Cómo**: se detectan cabeceras con regex que cubren más de 30 variantes reales de naming en papers cosméticos ("In vitro", "Clinical Study", "Volunteers", "Formulation", etc.) y se mapean a las 6 categorías canónicas.

### 2 · Búsqueda densa + Cohere multilingual reranker

**Decisión**: dos etapas — búsqueda vectorial para recall alto + reranker para precisión.

**Por qué**: la búsqueda vectorial sola no discrimina bien entre chunks del mismo dominio temático. El reranker multilingual resuelve además la asimetría lingüística: el corpus está en inglés pero los usuarios consultan en español. El modelo de Cohere fue entrenado para cross-lingual retrieval, por lo que la similitud semántica se calcula correctamente sin traducción previa.

### 3 · Relevancia como etiqueta, no como número

**Decisión**: convertir el score del reranker a `alta/media/baja` antes de enviarlo al LLM.

**Por qué**: durante las pruebas se observó que los modelos — tanto Claude Haiku como Gemini — tendían a incluir el score numérico en las respuestas al usuario ("con una relevancia de 0.73..."). El equipo de R&D no necesita ni entiende ese valor. Con etiquetas semánticas el modelo razona cualitativamente sobre la relevancia sin exponer artefactos internos del pipeline.

### 4 · Elección del LLM: de Claude Haiku a Gemini 2.5 Flash

**Decisión**: usar Gemini 2.5 Flash como modelo de síntesis del agente.

**Por qué**: se probó inicialmente con Claude Haiku 4.5 por su rapidez y coste reducido. El problema fue que Haiku tiende a razonar en voz alta: añadía párrafos de reflexión sobre lo que iba a hacer, expresaba incertidumbre de forma prolija y generaba respuestas más largas de lo necesario para el caso de uso. Gemini 2.5 Flash produjo respuestas más directas y concisas manteniendo la misma calidad de síntesis, encajando mejor con el perfil de usuario (investigadoras con poco tiempo que buscan respuestas accionables, no razonamiento explícito).

### 5 · Ingesta idempotente por UUID5

**Decisión**: calcular el ID de cada chunk como UUID5 determinista basado en `study_id + doc_type + section + índice`.

**Por qué**: Qdrant soporta upsert por ID. Si se re-ingesta un documento (corrección de un PDF, actualización de metadata), los chunks existentes se actualizan sin acumular duplicados. El índice permanece limpio sin necesidad de borrar y recrear la colección.

### 6 · n8n como orquestador del agente

**Decisión**: implementar el AI Agent en n8n en lugar de código propio.

**Por qué**: n8n proporciona gestión de conversación, persistencia en PostgreSQL, ejecución de herramientas y conexión con modelos en un entorno visual configurable sin código adicional. El backend Python queda como API pura de retrieval, lo que mantiene una separación clara de responsabilidades: la lógica de búsqueda vive en FastAPI y la lógica de agente vive en n8n.

---

## Puesta en marcha

### Requisitos

- Python 3.12
- Node.js ≥ 18
- Docker (para Qdrant, n8n y PostgreSQL)
- API keys: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `COHERE_API_KEY`

### Infraestructura (Docker)

```bash
docker compose up -d
# Qdrant  → http://localhost:6333
# n8n     → http://localhost:5678
# PostgreSQL → localhost:5432
```

### Backend

```bash
cd server
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # rellenar con tus claves

uvicorn app.main:app --reload --reload-dir app
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

### Frontend

```bash
npm run dev          # desde la raíz del proyecto
# → http://localhost:5173
```

### Ingesta de documentos

Con el backend y Qdrant corriendo, ingestar todos los PDFs de `DOCS_PATH`:

```bash
curl -X POST http://localhost:8000/api/ingest
```

O ingestar un PDF individual (también lo usa el workflow de Drive):

```bash
curl -X POST http://localhost:8000/api/ingest/file \
  -F "file=@FAM\ 107.pdf" \
  -F "drive_link=https://drive.google.com/..."
```

### n8n

1. Acceder a `http://localhost:5678` y crear cuenta
2. Importar el workflow del agente (`PaperMind Agent`)
3. Importar el workflow de Google Drive (opcional)
4. Configurar las credenciales de Gemini, PostgreSQL y Google Drive en n8n
5. Activar los workflows

El webhook del agente escucha en `/webhook/papermind-chat` y espera `{ query, session_id }`.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| Frontend | React 18, TypeScript, Tailwind CSS, Vite 5 |
| Backend | Python 3.12, FastAPI, uvicorn |
| Orquestación del agente | n8n 2.20.0 (AI Agent V3) |
| LLM de síntesis | Gemini 2.5 Flash (via n8n) |
| Memoria de conversación | PostgreSQL (via n8n Postgres Memory) |
| Embeddings | OpenAI text-embedding-3-large (3072 dim) |
| Base de datos vectorial | Qdrant |
| Reranking | Cohere rerank-multilingual-v3.0 |
| Extracción PDF nativa | pdfplumber |
| OCR para PDFs vectorizados | Gemini Flash (google-genai) |
| Infraestructura | Docker Compose |

---

## Endpoints del backend

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/search` | Búsqueda semántica con reranking. Usado por el AI Agent. |
| `GET/POST` | `/api/study` | Recupera todos los chunks de un estudio por ID. |
| `POST` | `/api/ingest` | Ingesta por lote todos los PDFs en `DOCS_PATH`. |
| `POST` | `/api/ingest/file` | Ingesta un PDF individual (upload multipart). Usado por el workflow de Drive. |
| `GET` | `/api/ingest/triage` | Clasifica los PDFs como native u ocr sin ingestarlos. |
| `GET` | `/api/ingest/extract/{study_id}` | Previsualiza el texto extraído de un PDF (debug). |
| `GET` | `/api/ingest/chunks/{study_id}` | Previsualiza los chunks generados sin ingestarlos (debug). |
| `GET` | `/api/health` | Estado del servicio y conectividad con Qdrant. |
