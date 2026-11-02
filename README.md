# Panorama de plataformas CTeI

Estudio de referentes para plataformas de ciencia, tecnología e innovación (CTeI): plataformas en operación, software, patentes y artículos científicos de Bogotá, Colombia, América Latina y el resto del mundo. Sirve al levantamiento de requisitos de Hēma, la plataforma de articulación CTeI de la Agencia ATENEA, y de plataformas parecidas.

El repositorio tiene tres piezas: las fichas de los referentes, un tablero estático para GitHub Pages con constelación 3D y un [servidor MCP](#servidor-mcp) que el agente `aracne-ctei-scout` de Aracne consulta durante la fase de requisitos. Las fuentes y los servidores MCP usados en la búsqueda están en [`docs/fuentes-y-mcp.md`](docs/fuentes-y-mcp.md).

## Contenido

| Ruta | Qué contiene |
|------|--------------|
| `fichas/` | Una ficha `CT###.md` por referente, con front matter YAML y secciones fijas (plantilla en `fichas/_plantilla.md`): tipo, alcance, país, operador, año, temas, actores, servicios, interacciones, evidencia verificable y fecha de consulta |
| `data/vocabulario.json` | Vocabulario cerrado: temas F01 a F14, actores, servicios, interacciones, tipos, alcances y tipos de relación. Un término nuevo se propone; no se agrega en silencio |
| `data/landscape.json` | Fuente única generada desde las fichas: registros, clústeres, relaciones tipadas, top 5 por similitud y matriz de actores, servicios e interacciones |
| `data/cluster_names.json` | Nombres de los clústeres. El build escribe nombres provisionales («Por nombrar: …») que una persona reemplaza |
| `data/runs.jsonl` | Registro de corridas del agente, una línea JSON por corrida (formato abajo) |
| `docs/` | Sitio estático de GitHub Pages: `index.html`, `constelacion.html` (visor 3D) y `data/landscape.json` |
| `tools/` | Build, índice SQLite, servidor MCP, plantillas del tablero, pruebas visuales y el visor 3D en `tools/vendor/atlas3d/` |
| `tests/` | Pruebas con pytest sobre fichas sintéticas: validación, búsqueda, contrato del MCP y estabilidad de clústeres |
| `bin/panoramaCTeI` | Comando para ver el tablero, regenerar y servir el MCP desde un clon |

## Ver el tablero

En línea: <https://liaunal.github.io/panoramaPlataformasCTeI/>. GitHub Pages publica la carpeta `docs/` de la rama `main`, de modo que cada push que regenere `docs/` actualiza el sitio en uno o dos minutos.

En local:

```bash
panoramaCTeI ui              # http://localhost:8000, abre el navegador
panoramaCTeI ui 9000         # otro puerto
panoramaCTeI ui --no-open    # sin abrir el navegador
panoramaCTeI build           # valida fichas/ y regenera data/landscape.json y docs/
```

El comando se instala una vez con `ln -s "$PWD/bin/panoramaCTeI" ~/.local/bin/panoramaCTeI` (sirve cualquier carpeta del `PATH`). Sin el comando: `./tools/serve.sh [puerto]`. El servidor escucha solo en `127.0.0.1`.

El tablero tiene ocho vistas:

| Vista | Qué muestra |
|---|---|
| Constelación 3D | Cada referente es un sistema solar; sus planetas son alcance, tipo, temas, clúster, actores, interacciones y servicios. Un clic abre la ficha con las relaciones declaradas, el top 5 por similitud y la evidencia |
| Mapa por alcance | Cuatro columnas (Bogotá, Colombia, América Latina, Internacional) con el conteo por tipo y una tarjeta por referente, con filtro por tipo |
| Matriz | Mapa de calor de actores, servicios e interacciones por alcance, con la misma agregación de `actor_service_matrix`; cada celda lista las fichas que la respaldan |
| Clústeres e ideas | Grupos de referentes con sus etiquetas más frecuentes y las ideas para plataformas CTeI de sus fichas |
| Sistema temático | Funciones CTeI (F01 a F14) como planetas, con las fichas en órbita según tipo y clúster |
| Explorar | Buscador sin tildes con filtros por tipo, alcance, tema, clúster y año |
| Línea de tiempo | Referentes por año de lanzamiento, publicación o prioridad, apilados por alcance |
| Corridas del agente | Las corridas de `data/runs.jsonl`; un clic resalta en la constelación las fichas que consultó y exportó |

La constelación deja de dibujar cuando otra pestaña está a la vista y cambia a una vista 2D cuando el equipo no tiene GPU apropiada para WebGL (`constelacion.html?view=2d` la fuerza). No muestra nombres en reposo: el de un nodo aparece al pasar el cursor y el botón «nombres» muestra los de todos los soles. `constelacion.html?focus=CT101` abre con un referente seleccionado y `constelacion.html?highlight=CT101,CT102` resalta un grupo.

## Servidor MCP

El servidor MCP `ctei-landscape` (stdio) expone las fichas como insumo para requisitos. Busca sobre un índice SQLite FTS5 (BM25, sin tildes) que se regenera solo cuando cambia `data/landscape.json`; el índice no se versiona.

Se instala desde GitHub con [uv](https://docs.astral.sh/uv/), sin clonar el repositorio:

```bash
uvx --from git+https://github.com/LIAUNAL/panoramaPlataformasCTeI ctei-landscape-mcp
```

El paquete trae el servidor, `data/landscape.json` y las fichas, y deja el índice en `~/.cache/ctei-landscape/landscape.db`. Para tomar una versión nueva: `uvx --refresh --from git+https://github.com/LIAUNAL/panoramaPlataformasCTeI ctei-landscape-mcp`. Desde un clon, `panoramaCTeI mcp` sirve los datos del clon y guarda el índice en `data/landscape.db`.

Registro en un proyecto (`.mcp.json`):

```json
"ctei-landscape": {
  "type": "stdio",
  "command": "uvx",
  "args": ["--from", "git+https://github.com/LIAUNAL/panoramaPlataformasCTeI", "ctei-landscape-mcp"],
  "env": {"CTEI_REFERENCE_PATH": "${CTEI_REFERENCE_PATH:-}"}
}
```

| Herramienta | Para qué |
|---|---|
| `search_landscape(query, kind?, scope?, topic?, year_from?, match?, limit?)` | Búsqueda por texto con filtros por tipo (`kind`), alcance (`scope`), tema (`topic`) y año; `match` es `any` (alguna palabra) o `all` (todas) |
| `get_entry(entry_id)` | Registro completo y ficha Markdown con su evidencia y fecha de consulta |
| `related_entries(entry_id)` | Relaciones tipadas (`similar-a`, `implementa`, `estudiado-en`) en ambos sentidos, top 5 por similitud y resto del clúster |
| `actor_service_matrix(scope?, topic?)` | Actores, servicios e interacciones agregados, cada uno con las fichas que lo respaldan y su conteo por alcance |
| `coverage_gaps(reference_path?, reference_id="CT000")` | Lo que aparece en la matriz y no en una ficha de referencia: candidatos a requisito. Es una diferencia de conjuntos sobre etiquetas normalizadas, sin juicio del modelo |
| `taxonomy()` | Temas, tipos, alcances y clústeres con su número de fichas, más el vocabulario cerrado |
| `export_to_insumos(entry_ids, dest_dir)` | Copia las fichas y una matriz en Markdown a una carpeta que ya exista, por ejemplo `.aracne-sdlc-ai/bmad/planning-artifacts/inputs/` |

`coverage_gaps` lee la referencia de `reference_path` o de la variable `CTEI_REFERENCE_PATH`; si la variable está vacía, cuenta como no definida. Sin referencia, responde `available: false` con un mensaje que explica cómo pasarla. Con `reference_id="HEMA-publico"` usa la descripción pública `fichas/HEMA-publico.md` cuando existe.

El top 5 es similitud textual y de etiquetas calculada al generar el panorama, no un vínculo declarado: hay que confirmarlo antes de citarlo. Las relaciones tipadas sí vienen declaradas en las fichas.

## Publicación y confidencialidad

Este repositorio es público y contiene solo fichas de fuentes públicas. La ficha de referencia de Hēma (`CT000`), construida con las reuniones y actas del proyecto, y el análisis de brechas no se publican: viven en los repositorios privados del equipo y `coverage_gaps` los lee desde una ruta fuera de este repositorio. El build rechaza una ficha con id `CT000` dentro de `fichas/`, aun con `--lenient`.

## Regenerar

```bash
uv run python tools/build_landscape.py              # falla si alguna ficha no cumple el vocabulario
uv run python tools/build_landscape.py --lenient    # informa los problemas y construye con lo válido
uv run python tools/build_landscape.py --recluster  # reagrupa desde cero; luego revise data/cluster_names.json
```

La validación nombra el archivo y el campo de cada problema. Detecta etiquetas fuera del vocabulario, tipos o alcances desconocidos, evidencia que no es URL, DOI ni número de publicación de patente, fichas sin evidencia o sin fecha de consulta, ids duplicados y relaciones hacia fichas que no existen. Con `--lenient` se descartan los valores inválidos y quedan por fuera solo las fichas sin id válido, con id duplicado o con tipo o alcance desconocido. El build calcula todo y genera el sitio en memoria antes de escribir, así que un error deja intactos `data/landscape.json`, `data/cluster_names.json` y `docs/`.

Cada referente conserva su clúster de una campaña a la siguiente y los nuevos van al centroide más cercano, de modo que los nombres de `data/cluster_names.json` siguen apuntando a los mismos grupos. `--clusters K` fija el número de grupos de un agrupamiento nuevo.

### Registro de corridas

Cada corrida del agente agrega una línea a `data/runs.jsonl`:

```json
{"date": "2026-11-01T10:30:00-05:00", "query": "emparejamiento de oferta y demanda", "scope": "bogota", "fichas_consulted": ["CT101", "CT102"], "fichas_exported": ["CT101"]}
```

`scope` toma `bogota`, `nacional`, `latam`, `internacional` o `null`. El build omite con un aviso las líneas que no son un objeto JSON.

## Pruebas

```bash
uv run pytest -q
```

Las pruebas crean fichas sintéticas en una carpeta temporal y no dependen de las fichas reales. Con el tablero levantado, la prueba visual y funcional (Playwright con el Chrome del sistema en 1440×900, 1280×720 y 390×844) y la de memoria y CPU al alternar pestañas son:

```bash
uv run --no-project --with playwright --with pillow python tools/qa_dashboard.py http://localhost:8000/
uv run --no-project --with playwright python tools/qa_memory.py http://localhost:8000/ [vueltas]
```

La primera verifica que el grafo quede centrado, sin etiquetas ni tooltip en reposo, y que el panel muestre el top 5 sin traslapes. También revisa los controles, el buscador, los filtros, el mapa por alcance, la matriz, la vista de corridas y la ausencia de errores de JavaScript. La segunda falla si el heap, los nodos del DOM o los listeners siguen creciendo, si la constelación oculta usa más del 5 % de un núcleo o si la visible baja de 40 cuadros por segundo.

## Créditos

El visor 3D de `tools/vendor/atlas3d/` se distribuye bajo la licencia Apache 2.0 (copia en `tools/vendor/atlas3d/LICENSE`) y empaqueta three.js (MIT). La plantilla `tools/constellation_template.html` y los parches `VIEWER_PATCHES` de `tools/build_landscape.py` se aplican al generar el sitio. Los avisos de terceros se publican en `docs/THIRD_PARTY_NOTICES.md`.
