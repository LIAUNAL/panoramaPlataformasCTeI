# Fuentes y servidores MCP para el estudio de base tecnológica CTeI

Inventario de lo que ya usan los proyectos del laboratorio y de las fuentes que sirven para buscar plataformas, software, patentes y artículos sobre plataformas de ciencia, tecnología e innovación (CTeI) en Bogotá, Colombia, América Latina y el resto del mundo. Corte: 1 de noviembre de 2026. Lo marcado «sin verificar» no se comprobó en la documentación oficial.

## 1. Lo que ya usamos

| Proyecto | Servidores MCP y API | Para qué |
|---|---|---|
| PaperSmith (`papersmith-ai`) | `banco-lia` en `.mcp.json`; llamadas directas a OpenAlex, Crossref, arXiv, Semantic Scholar y NCBI desde sus scripts | Descubrir y resolver referencias, elegir revista |
| Morfeo (`RedaccionPropuestas`) | `openalex` (`@cyanheads/openalex-mcp-server`), `semanticscholar`, `crossref`, `pubmed`, `arxiv`, `consensus`, `context7`, `banco-lia` | Bibliografía de propuestas; Consensus filtra por cuartil |
| Banco LIA (`bancoProyectosPapersLIA`) | Su propio MCP `banco-lia` sobre SQLite FTS5; enriquecimiento con OpenAlex, Crossref y Semantic Scholar | Insumo de redacción de artículos y propuestas |

Ninguno de los tres usa fuentes de patentes, datos abiertos de CTeI ni directorios de software o plataformas. Esa es la parte nueva de este estudio.

## 2. Fuentes candidatas

| Fuente | Cubre | Acceso | ¿Hay MCP? | Uso en el estudio |
|---|---|---|---|---|
| OpenAlex | Artículos, autores, instituciones, financiadores | Gratuito; llave gratuita para paginar más allá de la primera página ([límites](https://help.openalex.org/how-to-use-the-api/rate-limits-and-authentication)) | Sí, `@cyanheads/openalex-mcp-server` | Artículos de los cuatro alcances |
| Crossref | Metadatos de DOI | Gratuito | Sí, `@botanicastudios/crossref-mcp` | Verificar DOI |
| Semantic Scholar | Artículos y citas | Gratuito con límites compartidos ([API](https://www.semanticscholar.org/product/api)) | Sí, `@xbghc/semanticscholar-mcp` | Artículos |
| arXiv, Consensus | Preprints; artículos con cuartil | arXiv gratuito; Consensus con cuenta | Sí | Complemento |
| SciELO, Redalyc, LA Referencia | Revistas y repositorios latinoamericanos | Gratuito por OAI-PMH (sin verificar) | No encontrado | Artículos de la región; casi todo ya está en OpenAlex |
| Lens.org | Artículos y patentes en un mismo corpus | Token con registro y atribución obligatoria ([docs](https://docs.api.lens.org/)) | No | Siguiente fase |
| EPO OPS y Espacenet | Familias de patentes, estado legal; incluye LATIPAT | Gratuito con registro hasta 4 GB por semana ([uso justo](https://www.epo.org/en/service-support/ordering/fair-use)) | A través de `patent-client-agents` | Patentes, en especial latinoamericanas |
| Google Patents | Patentes de todo el mundo | Web gratuita; BigQuery con 1 TB mensual gratuito | Sí, `patent-client-agents` ([repo](https://github.com/parkerhancock/patent-client-agents)) | Patentes |
| USPTO | Patentes de Estados Unidos | PPUBS sin llave; ODP con llave | Sí, `patent-mcp-server` ([repo](https://github.com/riemannzeta/patent_mcp_server)) | Patentes de Estados Unidos |
| WIPO PATENTSCOPE | Solicitudes PCT y colecciones nacionales | Web gratuita; API de pago ([datos](https://www.wipo.int/patentscope/en/data/)) | No | Consulta manual |
| SIC Colombia (SIPI) | Solicitudes colombianas | Consulta web, sin API abierta | No | Patentes colombianas, a mano o por LATIPAT |
| Minciencias en datos.gov.co | Grupos, investigadores y producción (ScienTI) | API Socrata gratuita ([datos abiertos](https://www.minciencias.gov.co/ciudadano/datosabiertos)) | No | Actores y capacidades en Colombia |
| OECD STIP Compass | Más de 7.900 iniciativas de política de CTeI | Descargas gratuitas ([portal](https://stip.oecd.org)) | No | Instrumentos y plataformas públicas |
| CORDIS | Proyectos financiados por la Unión Europea | Archivos masivos sin llave; API con registro ([API](https://cordis.europa.eu/about/dataextractions-api)) | No | Proyectos de plataformas y software |
| euroCRIS DRIS | Cerca de 1.500 instalaciones de sistemas CRIS | Consulta web; API sin documentar (sin verificar) | No | Software de gestión de la investigación |
| GitHub | Software abierto (DSpace-CRIS, VIVO) | API de búsqueda | Sí, `github/github-mcp-server` | Software |
| Crunchbase, Dealroom | Empresas y financiación | Licencia de pago | No revisado | Solo en el lado privado si la licencia no permite publicar |
| Exa, Tavily, Firecrawl, Brave | Web abierta | Niveles gratuitos limitados | Sí | Sitios oficiales de plataformas |

## 3. Recomendación

**Ahora, sin llaves de pago:** OpenAlex, Crossref y Semantic Scholar con los mismos MCP de Morfeo; `patent-client-agents` con Google Patents, más un registro gratuito en EPO OPS para LATIPAT; consulta web de la SIC; búsqueda web y lectura de los sitios oficiales para plataformas; descargas directas de datos.gov.co, STIP Compass y CORDIS; GitHub para software abierto; `banco-lia` para las capacidades del propio laboratorio.

**Después, con llaves:** Lens.org para enlazar patentes y artículos (con su atribución en este sitio), CORE, USPTO ODP, la API de CORDIS y una cuenta de Exa o Tavily para búsquedas web más intensas.

**Qué integra `ctei-landscape` y qué no:** el MCP del panorama solo indexa y consulta las fichas, como el banco LIA. El descubrimiento queda en los MCP externos configurados para el agente `aracne-ctei-scout`, que cambian rápido y manejan sus propias llaves. No vale la pena construir ahora servidores propios para Lens, DRIS o STIP, porque sus API están restringidas o sin documentar.

## 4. Lo que usó la primera campaña

La campaña del 1 de noviembre de 2026 produjo 102 fichas en cuatro corridas, registradas en `data/runs.jsonl`:

| Corrida | Fichas | Fuentes usadas |
|---|---|---|
| Bogotá y Colombia | 20 (CT100–CT119) | Sitios oficiales (Minciencias, iNNpulsa, Alcaldía de Bogotá, ATENEA, Ruta N, SENA, SIC, OCyT) y sus informes en PDF |
| América Latina | 20 (CT200–CT219) | Sitios oficiales de agencias y consejos de siete países y tres redes regionales |
| Internacional | 28 (CT300–CT327) | Sitios oficiales y documentación de la Unión Europea, Reino Unido, Estados Unidos, euroCRIS y proveedores de software |
| Patentes y artículos | 34 (CT400–CT414 y CT500–CT518) | Google Patents (consulta y páginas públicas), OpenAlex, Crossref y Semantic Scholar |

Quedaron pendientes las patentes colombianas y latinoamericanas (LATIPAT, SIC), los datos de Minciencias en datos.gov.co y STIP Compass. Varios portales latinoamericanos cargan su contenido con JavaScript y no se pudieron leer de forma automática (Sucupira, Portal Timbó). Google Patents bloqueó las consultas automáticas después de unas pocas solicitudes.
