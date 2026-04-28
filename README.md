# synthetic-ds

CLI local para generar datasets sintéticos desde PDFs con múltiples proveedores OpenAI-compatible.

Para automatización con agentes externos, ver [AGENTS.md](AGENTS.md).

## 🧠 Chunking Semántico Inteligente (Nuevo)

El sistema ahora incluye un **chunking semántico inteligente** que:

- **Detecta automáticamente** la estructura jerárquica del documento (capítulos, secciones, subsecciones)
- **Crea chunks de capítulos completos** (~8K-12K tokens) en lugar de cortar a mitades arbitrarias
- **Respeta la estructura del documento**: no corta párrafos ni ideas a la mitad
- **Para preguntas UNANSWERABLE**: el modelo tiene visibilidad del documento completo para validar que la respuesta realmente no existe
- **Mantiene continuidad** con overlap semántico inteligente entre chunks consecutivos

### Configuración de chunking

```yaml
# synthetic-ds.yaml
chunking:
  strategy: semantic          # "semantic" (recomendado) o "headings_first" (legacy)
  target_tokens: 8192         # Tamaño objetivo por chunk (~capítulo completo)
  overlap: 200                # Tokens de overlap entre chunks
  max_pages_per_chunk: 25     # Guardia para PDFs/libros muy grandes o con poco texto por página
```

### Comparación: Antes vs Ahora

| Característica | Antes | Ahora |
|---------------|-------|-------|
| Tamaño de chunks | 512 tokens (~1 página) | 8,192 tokens (~10-15 páginas) |
| Estrategia | Por cantidad de tokens fijos | Por estructura semántica |
| Detección de capítulos | Manual/secciones existentes | Automática con regex inteligente |
| Contexto UNANSWERABLE | Solo veía un fragmento | Ve el documento completo |
| Overlap | 50 tokens | 200 tokens con contexto previo |

## Flujo rápido

```bash
uv run synthetic-ds init --project-dir .
uv run synthetic-ds provider use fireworks
uv run synthetic-ds provider set-key fireworks
uv run synthetic-ds run ./pdfs --resource-profile low
```

## CLI para agentes

El CLI ya puede operarse sin UI ni prompts humanos, pensado para agentes como
OpenClawd/Hermes:

```bash
# Recomendado para agentes: usar env vars en vez de prompts/keychain
export FIREWORKS_API_KEY=...

# O guardar la key por stdin, sin interacción
printf '%s\n' "$FIREWORKS_API_KEY" | uv run synthetic-ds provider set-key fireworks --stdin

# Diagnóstico no interactivo antes de lanzar lotes largos
uv run synthetic-ds doctor --project-dir . --json

# Lanzar un job asíncrono y obtener JSON parseable
uv run synthetic-ds submit ./pdfs --project-dir . --json

# Exigir corpus de alta calidad para agentes/evaluación interna
uv run synthetic-ds submit ./pdfs \
  --project-dir . \
  --parser-mode fast \
  --agent \
  --allow-partial-export \
  --max-pdfs 10 \
  --max-pages-per-chunk 25 \
  --quality-preset strict \
  --min-groundedness-score 0.8 \
  --min-overall-score 0.8 \
  --json

# Ver estado / eventos / esperar finalización
uv run synthetic-ds status --job-id <job_id> --json
uv run synthetic-ds events --job-id <job_id> --json
uv run synthetic-ds wait --job-id <job_id> --json

# Ejecutar todo en foreground con resumen final en JSON
uv run synthetic-ds run ./pdfs --project-dir . --parser-mode fast --agent --json

# Resumir una corrida cortada y continuar desde el primer checkpoint faltante
uv run synthetic-ds run ./pdfs --project-dir . --resume --json

# Reconstruir solo eval cuando train ya quedó curado
uv run synthetic-ds run ./pdfs --project-dir . --from-phase judge_eval --only-eval --allow-partial-export --json
```

`submit` ahora crea el job y dispara un worker desacoplado del proceso CLI
actual, para que `status` / `events` / `wait` sigan funcionando aunque el
proceso que lanzó el comando ya haya terminado.

Comandos agent-friendly nuevos:

- `submit`: encola o lanza una corrida y devuelve `job_id`
- `jobs`: lista jobs conocidos
- `status`: devuelve el estado actual de un job
- `events`: devuelve el journal de eventos del job
- `wait`: bloquea hasta `completed` / `failed` / `cancelled`
- `doctor`: revisa dependencias, OCR, parser y provider key en JSON
- `--resume`: salta fases con checkpoint en `.work/checkpoints/`
- `--from-phase`: fuerza recomenzar desde una fase (`ingest`, `split`, `generate_train`, `judge_train`, `generate_eval`, `judge_eval`, `export`, `report`). También acepta alias `generate` y `judge`.
- `--only-train` / `--only-eval`: limita generación/curado a un split
- `--allow-partial-export`: exporta train aunque eval siga incompleto
- `--agent`: fuerza defaults conservadores para ejecución no interactiva

Para apuntar a un corpus más estricto, usá `--min-overall-score 0.8` y
`--min-groundedness-score 0.8`. Eso no entrena un modelo ni garantiza una
métrica externa de `0.8`; garantiza que el export solo incluya ejemplos que el
judge interno puntuó por encima de esos umbrales.

Para carpetas con muchos libros/PDFs, `--max-pdfs N` limita cuántos documentos
se toman de la carpeta ordenada. Para PDFs enormes, `--max-pages-per-chunk N`
evita chunks que abarquen demasiadas páginas aunque tengan pocos tokens.
Además, `parsing.docling_max_pages` y `parsing.docling_max_ram_mb` saltan a
PyMuPDF antes de intentar Docling cuando el libro es demasiado grande para el
entorno.

Para selección parcial de PDFs, un agente puede repetir `--include-file`:

```bash
uv run synthetic-ds submit ./pdfs \
  --include-file lote-01.pdf \
  --include-file lote-02.pdf \
  --json
```

## App visual local

```bash
# Una sola vez: compilar el frontend (React + Vite)
cd src/synthetic_ds/web/frontend
pnpm install
pnpm build
cd -

# Uso normal
uv run synthetic-ds init --project-dir .
uv run synthetic-ds provider use fireworks
uv run synthetic-ds provider set-key fireworks
uv run synthetic-ds app --project-dir .
```

La app abre una interfaz local para:

- elegir una carpeta con PDFs
- iniciar una corrida completa
- ver progreso en tiempo real vía Server-Sent Events
- revisar corridas anteriores
- explorar los ejemplos Q&A generados con filtros
- visualizar métricas (distribución de tipos, scores, aceptación)
- editar `synthetic-ds.yaml` desde un formulario o Monaco (YAML crudo)

Stack de la UI: FastAPI + React 18 + Vite + TypeScript + Tailwind + shadcn/ui,
servida como SPA estática desde el mismo binario. Dark mode por defecto,
toggle persistente a light.

### Desarrollo del frontend

```bash
# Terminal 1 — backend FastAPI
uv run synthetic-ds app --project-dir . --open-browser false

# Terminal 2 — Vite dev server con HMR
cd src/synthetic_ds/web/frontend
pnpm dev
# abrir http://127.0.0.1:5173
```

El dev server de Vite proxea automáticamente `/api/*` y `/open/*` a FastAPI
(puerto 8787).

La salida visible de cada corrida se guarda en:

```text
CARPETA_FUENTE/extraccion_dataset/
```

Los artefactos internos para resume/auditoría quedan ocultos en:

```text
CARPETA_FUENTE/extraccion_dataset/.work/
```

## Proveedores incluidos

- `fireworks` con `accounts/fireworks/routers/kimi-k2p5-turbo`
- `openai` con `gpt-4.1-mini`
- `zai` con `GLM-4.7`
- `groq` con `moonshotai/kimi-k2-instruct-0905`
- `openrouter` con `moonshotai/kimi-k2`
- `xai` con `grok-3-mini`

## Comandos útiles

```bash
uv run synthetic-ds provider list
uv run synthetic-ds provider use zai
uv run synthetic-ds provider test
uv run synthetic-ds ingest ./pdfs --recursive true
uv run synthetic-ds split
uv run synthetic-ds generate --split train --resource-profile low --generation-workers 2
uv run synthetic-ds curate --split train --resource-profile low --judge-workers 1
uv run synthetic-ds export
uv run synthetic-ds report
uv run synthetic-ds status
uv run synthetic-ds pause --job-id <id>
uv run synthetic-ds resume --job-id <id>
uv run synthetic-ds cancel --job-id <id>
uv run synthetic-ds verify --mode mock-full
uv run synthetic-ds verify --mode real-smoke
```

## Seguridad

`synthetic-ds provider set-key <provider>` guarda la clave en el keychain del sistema cuando hay un backend disponible. Si preferís no usar keychain, también podés exportar la variable de entorno indicada por `provider list`.

## Desarrollo

```bash
# Tests Python
uv run --extra dev pytest

# Build del frontend (antes de empaquetar la app)
cd src/synthetic_ds/web/frontend && pnpm install && pnpm build
```

## Arquitectura del Chunking Semántico

```
PDF (100 páginas)
    ↓
Detección automática de estructura:
  - Capítulo 1: págs 1-25
  - Capítulo 2: págs 26-50
  - etc.
    ↓
Chunks semánticos:
  - Chunk 1: Capítulo 1 completo (~8K tokens)
  - Chunk 2: Capítulo 2 completo (~8K tokens)
  - etc.
    ↓
Cada llamada al LLM recibe:
  - RESUMEN DEL DOCUMENTO
  - [Continuación del tema anterior]
  - CHUNK ACTUAL (capítulo/sección completa)
```

Para más detalles técnicos, ver `src/synthetic_ds/semantic_chunking.py`.
