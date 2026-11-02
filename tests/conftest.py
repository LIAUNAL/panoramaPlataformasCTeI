"""Fixtures: a throwaway landscape root (data/vocabulario.json + synthetic fichas) under pytest's tmp dir.

The tests never read the real fichas/, which other writers fill in parallel.
"""
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

FICHAS = {
    "CT101-plataforma-bogota.md": """---
id: CT101
titulo: "Plataforma Distrital de Innovación"
tipo: plataforma
alcance: bogota
pais: "Colombia"
operador: "Secretaría Distrital"
anio: 2021
temas: [F01, F03]
actores: [universidad, empresa, emprendedor]
servicios: [directorio-actores, emparejamiento-oferta-demanda, convocatorias]
interacciones: [emparejamiento, postulacion]
evidencia: ["https://example.org/plataforma-distrital"]
consultado: 2026-11-01
relacionados: [{id: CT102, tipo: similar-a}]
---

# Plataforma Distrital de Innovación

## Descripción
Directorio de actores de innovación de la ciudad con emparejamiento entre oferta y demanda tecnológica.

## Actores que atiende
Universidades, empresas y emprendedores.

## Servicios
Directorio, emparejamiento y convocatorias.

## Interacciones entre actores
Emparejamiento y postulación.

## Modelo de operación
Pública, operada por la Secretaría.

## Tecnología
No publicada.

## Ideas para plataformas CTeI como Hēma
Emparejamiento automático entre retos empresariales y grupos de investigación.

## Evidencia
- https://example.org/plataforma-distrital (consultado 2026-11-01)
""",
    "CT102-red-nacional.md": """---
id: CT102
titulo: "Red Nacional de Laboratorios"
tipo: plataforma
alcance: nacional
pais: "Colombia"
operador: "Ministerio de Ciencia"
anio: 2019
temas: [F07, F01]
actores: [universidad, centro-investigacion, empresa]
servicios: [acceso-laboratorios, reserva-equipos, directorio-actores]
interacciones: [contratacion-servicios]
evidencia: ["https://example.org/red-laboratorios"]
consultado: 2026-11-01
relacionados: []
---

# Red Nacional de Laboratorios

## Descripción
Catálogo nacional de laboratorios con reserva de equipos para investigación y empresas.

## Ideas para plataformas CTeI como Hēma
Reserva de equipos compartidos entre universidades.

## Evidencia
- https://example.org/red-laboratorios
""",
    "CT301-cris-internacional.md": """---
id: CT301
titulo: "Sistema CRIS de código abierto"
tipo: software
alcance: internacional
pais: "Países Bajos"
operador: "Consorcio europeo"
anio: 2015
temas: [F13, F09]
actores: [investigador, universidad, gestor-programa]
servicios: [perfil-investigador, gestion-proyectos, seguimiento-informes]
interacciones: [reporte-indicadores, seguimiento-hitos]
evidencia: ["https://example.org/cris", "doi:10.1234/cris.2015"]
consultado: 2026-11-01
relacionados: [{id: CT501, tipo: estudiado-en}]
---

# Sistema CRIS de código abierto

## Descripción
Software de gestión de la investigación basado en el estándar CERIF, con perfiles y seguimiento de proyectos.

## Tecnología
Java, estándar CERIF, API abierta.

## Evidencia
- https://example.org/cris
""",
    "CT501-articulo-latam.md": """---
id: CT501
titulo: "Evaluación de plataformas de innovación en América Latina"
tipo: articulo
alcance: latam
pais: "Chile"
operador: "Revista de Política Científica"
anio: 2023
temas: [F08, F13]
actores: [gobierno-nacional, agencia-financiadora, investigador]
servicios: [observatorio-indicadores, datos-abiertos]
interacciones: [reporte-indicadores, intercambio-datos]
evidencia: ["doi:10.5555/latam.2023.01"]
consultado: 2026-11-01
relacionados: []
---

# Evaluación de plataformas de innovación en América Latina

## Descripción
Artículo que compara observatorios de ciencia y sistemas CRIS de la región y sus indicadores.

## Evidencia
- doi:10.5555/latam.2023.01
""",
}

REFERENCE = """---
id: CT000
titulo: "Referencia de prueba"
tipo: plataforma
alcance: bogota
temas: [F01]
actores: [universidad, empresa, "Centro de Investigación"]
servicios: [directorio-actores, convocatorias, servicio-propio]
interacciones: [postulacion]
evidencia: ["https://example.org/ref"]
consultado: 2026-11-01
---

# Referencia de prueba
"""


def write_ficha(root: Path, name: str, text: str) -> Path:
    path = root / "fichas" / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path):
    """A landscape root with the real vocabulary and three synthetic fichas (CT501 is added by tests)."""
    base = tmp_path / "repo"
    (base / "data").mkdir(parents=True)
    (base / "fichas").mkdir()
    shutil.copyfile(REPO / "data" / "vocabulario.json", base / "data" / "vocabulario.json")
    shutil.copyfile(REPO / "fichas" / "_plantilla.md", base / "fichas" / "_plantilla.md")
    for name in ("CT101-plataforma-bogota.md", "CT102-red-nacional.md", "CT301-cris-internacional.md"):
        write_ficha(base, name, FICHAS[name])
    return base


@pytest.fixture
def full_root(root):
    write_ficha(root, "CT501-articulo-latam.md", FICHAS["CT501-articulo-latam.md"])
    return root


@pytest.fixture
def built(full_root):
    """full_root after a build without the static site."""
    import build_landscape
    build_landscape.build(full_root, site=False)
    return full_root


@pytest.fixture
def landscape(built):
    import landscape_db
    return landscape_db.Landscape(built / "data" / "landscape.json", built / "data" / "landscape.db")


@pytest.fixture
def outside_reference(tmp_path):
    """A private reference ficha outside the repository root."""
    private = tmp_path / "private"
    private.mkdir()
    path = private / "CT000-hema.md"
    path.write_text(REFERENCE, encoding="utf-8")
    return path
