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
- Pruebas: `pip install -r requirements.txt && python -m pytest -q`.
- Los workflows de `.github/workflows/` actualizan los datos solos (diésel cada día, carbón y escoria cada lunes).

## Decisiones del proyecto (contexto de lo avanzado)

- **Diésel:** solo Diésel B5 S-50 y B5 S-50 UV de las listas Automotriz de Petroperú (Addendum N.° 1),
  todas las plantas, desde 2023. Si un día no hay lista nueva, rige la última registrada.
- **Promedio ponderado mensual (Conchán):** se calcula el día 1 de cada mes para el mes cerrado y se
  envía por correo con un Excel con fórmulas (`reportes/promedio-ponderado-conchan-AAAA-MM.xlsx`).
- **Carbón y escoria:** solo precio **FOB** y **CFR Muelle Conchán** (FOB + flete marítimo). No se
  calcula el costo puesto en planta. Datos públicos (FRED/IMF, Banco Mundial, BCRP, UN Comtrade) desde
  2018; poder calorífico de referencia 6,000 kcal/kg. Sin referencia de presupuesto por defecto.
- **Conveniencia de compra:** índice 0-100 (40% posición en 36 meses, 30% frente al promedio de
  12 meses, 30% cambio esperado por la simulación); desde 65 es "Compra conveniente" y se avisa.
- **Avisos por correo** (cuenta Gmail del proyecto a `AVISO_CORREOS`, secretos `AVISO_*` en GitHub):
  cambio de precio del diésel, promedio ponderado mensual y alertas nuevas de carbón y escoria.
  No hay reporte diario sin cambios ni WhatsApp.
- **Horarios:** diésel a las 08:00 y 12:30 (hora de Lima), con tareas programadas que lanzan el
  workflow; carbón y escoria cada lunes.
- **Tablero:** en español, identidad UNACEM (rojo #E60000, tipografías Barlow), modo claro y oscuro,
  pestañas Precios Petroperú, Referencia Osinergmin, Precios carbones internacionales y Escoria
  japonesa; botón "Preguntar en Claude" abajo a la derecha.
- **Sin IA de pago:** no hay agente por API; las consultas se hacen en Claude Code con la cuenta de cada persona.

