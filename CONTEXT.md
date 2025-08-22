# `epub_resumidor` — Resúmenes de libros EPUB a Markdown con Ollama

Genera **resúmenes por capítulos** y un **metarresumen** de libros en formato **EPUB** (y estructura compatible para PDF en el futuro), escribiendo el resultado en un archivo `-RESUMEN.md` junto al libro original.

> Estado: usado en producción local (macOS). Probado con **Ollama** y modelos `qwen3:14b` y `llama3.1:8b`.

---

## ¿Qué hace el script?

1. **Busca** todos los `.epub` en un directorio.
2. **Crea** `<título>-RESUMEN.md` con:

   ```md
   # Resumen general

   # Resumen por capítulos
   ```

3. **Lee el TOC** (tabla de contenidos) del EPUB.
4. **Filtra** entradas no sustantivas (portada, índice, créditos, etc.) y capítulos sin texto útil.
5. Para cada capítulo **extrae el texto** (Markdown), lo **trocea** si es largo (_map_), genera **sub‑resúmenes**, y luego **fusiona** en un **resumen de capítulo** (_reduce_).
6. **Anexa** cada resumen de capítulo al `.md` bajo `# Resumen por capítulos`.
7. Al final, con los resúmenes por capítulo, compone un **“Resumen general”** (1–3 párrafos) y lo inserta bajo `# Resumen general`.

**Estilo**: prosa clara en **tercera persona**, sin listas, sin muletillas tipo “El autor…/El texto…”, y se eliminan bloques ocultos `<think>…</think>` si un modelo los emite.

---

## Requisitos

- **Ollama** en ejecución (`ollama serve` o app abierta)
- Python 3.11+ (recomendado) con:
  - `requests`
  - `ebooklib`
  - `beautifulsoup4`
  - `html2text`

### Instalación de dependencias (pyenv/virtualenv opcional)

```bash
# crear y asociar entorno (ejemplo con pyenv)
pyenv virtualenv 3.11.6 epub_resumidor_env
cd "/Volumes/D/Documentos D/mcp-servers/clients/epub_resumidor"
pyenv local epub_resumidor_env

# instalar librerías
pip install -U pip wheel
pip install requests ebooklib beautifulsoup4 html2text
```

---

## Cómo se usa

Sitúate en el directorio **padre** que contiene la carpeta `resumidor` (por ejemplo, `clients/`), y ejecuta:

```bash
python -m resumidor.cli "/ruta/al/directorio_con_epub_o_pdf"
```

El script procesará **todos** los `.epub` y `.pdf` del directorio indicado.

**Salida**: para cada libro, se escribirá `NombreDelLibro-RESUMEN.md` en el mismo directorio del archivo original.

> El script usa **fsync** y verificación tras la escritura para mayor fiabilidad en FS sincronizados (p. ej., Nextcloud).

---

## Parámetros por defecto

Estos valores están “hard‑coded” como predeterminados, pero **pueden modificarse via variables de entorno** sin editar el script:

```bash
# por defecto internamente
OLLAMA_MODEL="qwen3:14b"
NUM_CTX=32768
NUM_PREDICT=2048
TEMPERATURE=0.1
# streaming visible en consola
STREAM=1        # habilita stream de tokens
STREAM_MAP=1    # stream durante el 'map' (bloques)
STREAM_FUSE=1   # stream durante la fusión
VERBOSE=1       # logs de progreso
```

Puedes sobreescribir **en la llamada**:

```bash
OLLAMA_MODEL="llama3.1:8b" NUM_CTX=65536 NUM_PREDICT=1536 TEMPERATURE=0.2 \
STREAM=1 STREAM_MAP=0 STREAM_FUSE=1 VERBOSE=1 \
python epub_resumidor.py "/ruta/epubs"
```

---

## Otros ajustes útiles (entorno)

**Troceo y solape**

```bash
CHUNK_FRACTION=0.5     # % del contexto para el texto de cada bloque (por defecto 0.5)
OVERLAP_TOKENS=200     # solape entre bloques
```

**Tiempos** (solo para streaming)

```bash
CONNECT_TIMEOUT=10     # seg. para conectar
READ_TIMEOUT=          # vacío => sin límite; o p. ej. 180 (3 min)
```

---

## Ejemplos

### 1) Calidad (Qwen 14B, 32k, stream completo)

```bash
STREAM=1 STREAM_MAP=1 STREAM_FUSE=1 VERBOSE=1 \
OLLAMA_MODEL="qwen3:14b" NUM_CTX=32768 NUM_PREDICT=2048 TEMPERATURE=0.1 \
python epub_resumidor.py "/Volumes/E/Nextcloud/Materiales espirituales/Reveladores/Dios"
```

### 2) Rápido (Llama 3.1 8B, salida moderada)

```bash
STREAM=1 STREAM_MAP=0 STREAM_FUSE=1 VERBOSE=1 \
OLLAMA_MODEL="llama3.1:8b" NUM_CTX=32768 NUM_PREDICT=1024 TEMPERATURE=0.2 \
python epub_resumidor.py "/ruta/epubs"
```

### 3) Capítulos muy largos (más contexto, menos solape)

```bash
STREAM=1 OLLAMA_MODEL="qwen3:14b" NUM_CTX=65536 NUM_PREDICT=2048 \
CHUNK_FRACTION=0.45 OVERLAP_TOKENS=150 \
python epub_resumidor.py "/ruta/epubs"
```

---

## Cómo funciona (detalle)

- **TOC y filtrado**: Se aplanan las entradas del TOC (`ebooklib.epub`) y se filtran títulos/hrefs no sustantivos (EN/ES) y capítulos **sin texto útil** (heurística: `< 60` palabras o solo imágenes).
- **Map**: el capítulo se divide por párrafos en bloques de ~`NUM_CTX * CHUNK_FRACTION` con `OVERLAP_TOKENS` de solape. Cada bloque se resume con Ollama.
- **Reduce**: se fusionan los sub‑resúmenes en **2–5 párrafos**; si llegase un bloque único, se normaliza a párrafos respetando finales de frase.
- **Metarresumen**: se genera a partir de los resúmenes por capítulo (1–3 párrafos), con las mismas restricciones de estilo.
- **Estilo**: tercera persona, prosa directa, sin listas; eliminación de `<think>` si apareciera.

---

## Modelos recomendados

- **Qwen3 14B** (`qwen3:14b`): mejor calidad/fluidez en resúmenes largos (más lento y memoria > 8B).
- **Llama 3.1 8B** (`llama3.1:8b`): buen equilibrio rapidez/calidad.
- **Modelos 3–4B**: útiles para pruebas rápidas o hardware limitado; calidad inferior.

> **Consejo**: si el capítulo _cabe_ en 32k, prioriza `NUM_CTX=32768`. Sube a 64k solo si es imprescindible; el coste de KV‑cache crece y la latencia también.

---

## Solución de problemas

- **No aparece el capítulo en el `.md`**: el script re‑lee tras escribir y advierte con `[warn]` si no encuentra el encabezado recién añadido; revisa permisos, espacio y sincronización del FS.
- **Se ve binario “PK…”**: indica lectura directa del `.epub` como zip; este script usa `ebooklib` y no debe ocurrir.
- **Va lento**: revisa `NUM_PREDICT`, reduce `CHUNK_FRACTION` (0.45/0.4), baja solape, o usa un modelo más pequeño. Cierra apps que consumen RAM.
- **Stream se corta**: establece `READ_TIMEOUT` (p. ej., 180–600), o desactiva `STREAM_MAP=0` para bloques largos.

---

## Notas y límites

- Pensado para **EPUB**. Adaptar a **PDF** requiere otra ruta de extracción (p. ej., `pypdf`) y heurísticas por páginas.
- El script **no** reescribe capítulos ya escritos (todavía). Si relanzas, se anexarán de nuevo. (Se puede añadir _skip por encabezado_ si lo necesitas).

---

## Licencia

Uso personal/privado.
