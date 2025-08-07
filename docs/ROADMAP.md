# Roadmap · Resumidor (EPUB → MD; futuro PDF/DOCX)

Este documento recoge objetivos y mejoras pendientes para el proyecto de resúmenes automáticos de libros. Se actualiza de forma continua conforme avanza el desarrollo.

---

## Funcionalidades ya implementadas

- **Skip de capítulos ya escritos**: no volver a anexar si existe `## Título` en el `.md` (flag `--skip-existing`).
- **Flags de depuración/alcance**:
  - `--only-first` (procesa solo el primer EPUB del directorio),
  - `--only-chapter N` (procesa un capítulo concreto),
  - `--only-metarresumen <ruta.md>` (rehace solo el metarresumen).
- **Medición y trazas**:
  - Tiempo por bloque (_map_), fusión y metarresumen; log de duración.
  - Pie de auditoría opcional en el `.md` (modelo, `num_ctx`, `num_predict`, `temperature`, fecha/hora).
- **Escritura atómica**:
  - Escribir en archivo temporal (`*.tmp`) + `rename()` para mayor robustez en FS sincronizados (p. ej., Nextcloud).
- **Parámetros por fase**:
  - Separar `MAP_NUM_PREDICT` y `FUSE_NUM_PREDICT` (y valor específico para metarresumen).

---

## Funcionalidades pendientes

- **Extractor PDF**:
  - `pypdf` + _outlines_ (bookmarks) como TOC cuando existan.
  - Heurística para detección de índice no estructurado (por palabras clave, número de capítulos, distribución, etc.).
  - Corrección automática de títulos fragmentados mediante modelo LLM (detección de palabras concatenadas o separadas por letras).
  - _Fallback_ por grupos de páginas (p. ej., 8–12) con fusión.
  - (Más adelante) OCR selectivo si el texto es escaso.
- **Extractor DOCX**:
  - `python-docx`; segmentación por encabezados `Heading 1/2` y _fallback_ por tamaño.
- **Paquetización**:
  - `pyproject.toml`, entrypoint CLI (`resumidor`), `scripts/` como _shim_ para compatibilidad.
  - Publicación como paquete editable para desarrollo.
- **Configuración**:
  - Soporte de `config.toml`/`.env` además de variables de entorno.
- **Evaluación de calidad**:
  - Banco de casos (capítulo → resumen de referencia),
  - métricas ligeras (longitud, densidad informativa, detección de muletillas).
- **Rendimiento y robustez**:
  - Caché de sub-resúmenes por bloque (evitar recomputo en reintentos),
  - reanudación tras fallo a mitad de libro (archivo de estado por EPUB),
  - control de concurrencia por libro (1 libro a la vez; capítulos secuenciales).
- **Salida opcional**:
  - Front‑matter YAML (metadatos del libro) en el `.md`.
  - Exportación alternativa a `.json` (estructura: capítulos + metarresumen).

---

## “Quizá / Más adelante”

- **OCR completo** (Tesseract) para PDFs escaneados (nuevo extractor `pdf_ocr_extractor.py`).
- **Soporte multi‑modelo**:
  - Perfiles por tamaño de capítulo (4B/8B/14B dinámico) y _auto‑switch_.
- **Multi‑idioma**:
  - Detección de idioma y ajuste de _prompts_ (ES/EN).
- **Integraciones**:
  - Pipeline batch + _watch_ de directorios; colas.
  - Publicación automática (commit en repo, subida a Nextcloud).
- **Tests**:
  - Unit tests de extractores y normalización de párrafos,
  - pruebas de escritura (atómico, verificación, concurrencia).
- **DX (Developer Experience)**:
  - `Makefile`/scripts de _setup_,
  - linters/formatters (`ruff`, `black`),
  - CI mínima (lint + _smoke tests_ en un capítulo de ejemplo).

---

## Notas de diseño

- Mantener un **solo repositorio** con arquitectura modular por _extractor_ (EPUB/PDF/DOCX) y una capa común de _summarizer_ (Ollama) y escritura.
- Reutilizar el pipeline **map → reduce → metarresumen** para todos los formatos.
- Estilo coherente (prosa, tercera persona, sin listas, sin `<think>`), normalización de párrafos en la fusión.

---

## Tareas operativas del repositorio

- Elegir **nombre del proyecto** y licencia (p. ej., MIT).
- Añadir `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` e _issue/PR templates_.
- Abrir _issues_ correspondientes a cada punto de este roadmap y etiquetar por prioridad.
