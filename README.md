# synthetic-ds

CLI local para generar datasets sintéticos desde PDFs con múltiples proveedores OpenAI-compatible.

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