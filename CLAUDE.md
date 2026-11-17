# Sourcing Internacional Combustibles y Materia Prima (UNACEM)

Proyecto que registra precios de compra: diésel en Perú (Petroperú y Osinergmin), carbón
bituminoso de Colombia y escoria granulada de Japón. Tablero: https://elpoppin2.github.io/AGENTE-PETROPERU-COMBUSTIBLES/

## Cómo trabajar con quien pregunta

- Responde en español, claro y directo, con las cifras y su unidad.
- Si la persona solo hace una consulta, **no modifiques archivos ni hagas commit o push**. Cambia el
  proyecto únicamente cuando lo pida de forma explícita.
- No inventes cifras: calcula con Python (pandas) sobre los archivos y di qué archivo y qué cálculo usaste.
  Distingue los datos observados de las estimaciones del modelo y de la simulación (que no es un pronóstico).
- **El repositorio es público.** Nunca subas datos internos de la empresa (cotizaciones, ofertas de
  proveedores, presupuestos, contratos). Si alguien los comparte para un cálculo, úsalos solo en la
  conversación.

## Datos

| Archivo | Contenido | Unidad |
|---|---|---|
| `data/listas.csv` | Listas de Petroperú desde 2023: `vigencia`, `combustible` (DIESEL_B5_S50, DIESEL_B5_S50_UV), `ubicacion` (planta), `precio`, `fuente` | S/ por galón, con impuestos |
| `data/historial.csv` | Precio vigente de cada día y planta | S/ por galón |
| `data/osinergmin.csv` | Referencia semanal de Osinergmin por planta: `b5_bajo_azufre`, `b5_alto_azufre`, `componente_logistico` | S/ por galón, sin impuestos ni margen |
| `reportes/carbon/modelo_mensual.csv` | Desde 2018. Carbón: `carbon_col_fob`, `carbon_flete`, `carbon_cfr` (= FOB + flete, Muelle Conchán). Escoria: `escoria_fob`, `escoria_flete`, `escoria_cfr`. Índices: `carbon_newcastle_fob`, `carbon_api4_fob_rb`, `carbon_api2_cif_ara`; `brent`, `fx_pen_usd` | US$ por tonelada |
| `reportes/carbon/simulacion.csv` | Simulación a 12 meses (p10 a p90) de FOB, flete y CFR | US$ por tonelada |
| `reportes/carbon/resumen.json` | Alertas vigentes e índice de conveniencia de compra por material | |
| `reportes/promedio-*.md`, `reportes/promedio-ponderado-*.xlsx` | Promedios ponderados mensuales del diésel en Conchán | S/ por galón |

- Un precio de lista rige desde su `vigencia` hasta la lista siguiente. El **promedio ponderado mensual**
  pesa cada precio por los días que estuvo vigente; si no hubo lista el día 1, rige la última anterior
  (`agente_petroperu.py --promedio AAAA-MM`).
- Las columnas `*_fuente` del modelo dicen de dónde salió cada FOB; `nowcast_*` y `ultimo_dato` son estimaciones.

## Código

- `agente_petroperu.py`: diésel (lectura de Petroperú y Osinergmin, Excel, avisos por correo, promedio ponderado).
- `carbon/`: carbón y escoria (fuentes públicas, modelo FOB/CFR, alertas, `simulacion.py`).
- `index.html`: tablero (GitHub Pages). Librerías en `assets/vendor/` (se reconstruyen con `herramientas/librerias`).
- `agente/`: agente de consultas por issues (Claude Managed Agents).
- Pruebas: `pip install -r requirements.txt && python -m pytest -q`.
- Los workflows de `.github/workflows/` actualizan los datos solos (diésel cada día, carbón y escoria cada lunes).
