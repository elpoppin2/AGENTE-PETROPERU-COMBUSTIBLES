# Monitor de carbón importado — Puerto Conchán

Bot/agente que sigue cada semana la evolución del precio del **carbón térmico
colombiano** (HS 2701.12) importado por **Puerto Conchán (Lima, Perú)**, un insumo
crítico de la operación.

Combina **información pública gratuita**, los **CSV que descargues de Investing.com**
y tus **cotizaciones propias**. Con eso arma el **costo puesto en planta**
(FOB → flete → CIF → planta, en USD, PEN y USD/GJ), calcula **ratios** de
seguimiento y dispara **alertas**. Si configuras una API key de Claude, un
**agente analista** redacta el comentario de mercado con noticias públicas recientes.

Es parte del proyecto **Sourcing Internacional Combustibles y Materia Prima** ([README principal](../README.md)).

👉 Reporte vigente: [`reportes/carbon/ultimo_reporte.md`](../reportes/carbon/ultimo_reporte.md) · Tablero: pestaña *Carbón importado*

---

## Fuentes

| Fuente | Qué aporta | Frecuencia / rezago |
|---|---|---|
| **Investing.com** (CSV manual) | Futuros API2 CIF Rotterdam, Newcastle, API4 Richards Bay | Diario → promedio mensual; al día |
| **FRED / IMF** (`PCOALAUUSDM`, `MCOILBRENTEU`, `COLCCUSMA02STM`) | Newcastle FOB (promedio mensual oficial), Brent (proxy de bunker), USD/COP | Mensual, ~1 mes |
| **Banco Mundial – Pink Sheet** | Carbón Australia, Sudáfrica (y Colombia si se publica), Brent | Mensual, ~1 mes |
| **BCRP** (`PD04638PD`) | Tipo de cambio interbancario PEN/USD | Diario → promedio mensual |
| **UN Comtrade** | Precios reales por tonelada: CIF de Perú (carbón de Colombia y de todo origen), FOB de Colombia (a Perú y al mundo), volúmenes | Mensual, 2–4 meses |
| **Tus cotizaciones** (`data/carbon/manual/*.csv`) | Precios de proveedores/brokers/Argus/Platts y fletes cotizados | Cuando las cargues |

> No existe una fuente pública gratuita y en tiempo real del FOB Colombia. Por eso el
> modelo **calibra ratios** con los datos de comercio exterior (reales pero con
> retraso) y los aplica a los índices que sí están al día (API2 de Investing, Newcastle).

### Cargar datos de Investing.com

Investing no tiene API pública y sus términos prohíben la extracción automática, así que
el bot **no** entra a la web: solo lee los CSV que tú descargas.

1. En Investing, abre el futuro (p. ej. *Rotterdam Coal Futures* / API2) → **Datos
   históricos** → elige el rango → **Descargar**. Necesitas una cuenta gratuita.
2. Guarda el archivo en `data/carbon/manual/investing/`. El nombre debe contener una palabra
   clave: `api2` o `rotterdam`, `newcastle`, `api4` o `richards`. Es lo que
   descarga Investing por defecto (p. ej. *Rotterdam Coal Futures Historical Data.csv*).
3. Haz push. El workflow se dispara solo y regenera el reporte.

Se aceptan los formatos del sitio en inglés (`10/21/2026`, `1,234.50`) y en español
(`21.10.2026`, `1.234,50`). Puedes reemplazar el archivo por uno más largo cuando quieras;
el histórico se actualiza por mes sin duplicar.

## Metodología

**Carbón Colombia FOB** (en orden de prioridad)
1. Tu cotización FOB (normalizada a la kcal de referencia).
2. Precio FOB por tonelada de las exportaciones Colombia→Perú (o →mundo) en Comtrade.
3. Pink Sheet “Coal, Colombian”, si existe.
4. **Nowcast**: `índice × ratio Colombia/índice`. El índice es **API2** (el carbón
   colombiano es del Atlántico) o Newcastle si no hay API2. El ratio es la mediana
   de los últimos 12 meses donde hay dato de Comtrade y del índice; si no hay, se usa
   el valor por defecto de la config.

Se ajusta a la especificación del contrato: `FOB_spec = FOB_ref × kcal_spec / kcal_ref`.

**Flete Colombia→Conchán** (vía Canal de Panamá):
`flete_base × (Brent / Brent_base)^elasticidad`, recalibrado con el flete implícito de
Comtrade (`CIF Perú − FOB Colombia` del mismo flujo). Tu cotización de flete siempre
tiene prioridad.

**Costo puesto en planta**
```
CIF     = (FOB + flete) × (1 + seguro%)
Landed  = CIF × (1 + arancel% + agente%) + descarga + almacenaje + transporte a planta
PEN/t   = Landed × TC BCRP
USD/GJ  = Landed / (kcal_spec × 4.1868e-3)
```
El IGV (18%) es crédito fiscal: se muestra como desembolso de caja, no como costo.

### Ratios que se monitorean

| Ratio | Para qué sirve |
|---|---|
| Colombia FOB / API2 | Descuento del carbón colombiano frente a su índice natural (Atlántico) |
| Colombia FOB / Newcastle | Competitividad frente al carbón del Pacífico (Australia/Indonesia) |
| API2 − Newcastle | Arbitraje Atlántico/Pacífico: si se abre, conviene comparar orígenes |
| Carbón vs Brent (USD/GJ) | Competitividad del carbón frente a combustibles líquidos |
| Flete / CIF | Exposición al mercado de fletes y al Canal de Panamá |
| CIF modelo / CIF Comtrade Perú | Control: el modelo frente a lo que realmente pagó el mercado peruano |
| Participación de Colombia en importaciones de Perú | Concentración de la oferta |

Para cada serie se calcula: último valor, variación mensual y anual, promedios 3m/12m,
rango y z-score de 24 meses.

### Alertas (config → `alertas`)
- Variación mensual mayor a `variacion_mensual_pct` (API2, Newcastle, FOB, flete, landed, TC, Brent).
- Valor fuera de rango histórico (|z| ≥ `zscore`).
- Costo puesto en planta por encima de `presupuesto_landed_usd_t`.

## Uso

```bash
pip install -r requirements.txt
python -m carbon update        # descarga datos → data/carbon/historico/series.csv
python -m carbon report        # calcula, grafica y escribe reportes/carbon/ultimo_reporte.md
python -m carbon all           # todo + notificación Telegram
python -m carbon report --sin-agente   # sin llamar a Claude
python -m pytest -q tests/carbon   # pruebas
```

### Cargar tus cotizaciones
Agrega filas a `data/carbon/manual/cotizaciones.csv` (bases FOB, CFR o CIF) y
`data/carbon/manual/fletes.csv`:

```csv
fecha,material,base,precio_usd_t,poder_calorifico_kcal_kg,proveedor,comentario
2026-10-15,carbon,FOB,118.5,6000,Proveedor X,Puerto Nuevo
```
```csv
fecha,material,flete_usd_t,tipo_buque,fuente,comentario
2026-10-10,carbon,25,Supramax,Broker Y,Puerto Nuevo-Conchán
```

### Ajustar supuestos
Todo está en [`carbon/config.yaml`](config.yaml): kcal de tu contrato, costos
portuarios en Conchán, flete base, consumo anual, presupuesto, índice preferido y
umbrales de alerta. Los valores marcados con **AJUSTAR** son supuestos iniciales.

## Automatización (GitHub Actions)

El workflow [`carbon.yml`](../.github/workflows/carbon.yml) corre **cada lunes
07:17 (Lima)**, al subir cotizaciones o CSV de Investing, y manualmente desde
*Actions → Run workflow*. Guarda el histórico y el reporte en el repositorio.

Secretos opcionales (*Settings → Secrets and variables → Actions*):

| Secreto | Uso |
|---|---|
| `ANTHROPIC_API_KEY` | Agente analista con Claude (comentario + búsqueda de noticias) |
| `FRED_API_KEY` | Clave gratuita de [fredaccount.stlouisfed.org](https://fredaccount.stlouisfed.org) si la descarga pública de FRED es bloqueada |
| `COMTRADE_API_KEY` | Clave gratuita de [comtradedeveloper.un.org](https://comtradedeveloper.un.org) para más cuota |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Resumen y alertas por Telegram |

Sin ningún secreto el bot funciona igual con las fuentes públicas.

## Estructura

```
carbon/config.yaml                 supuestos, umbrales y fuentes
carbon/sources/                    conectores: fred, worldbank, bcrp, comtrade, investing, manual
carbon/analytics.py                costo puesto en planta, ratios, indicadores y alertas
carbon/agent.py                    agente analista (Claude)
carbon/report.py                   reporte Markdown + gráficos
data/carbon/manual/                tus cotizaciones, fletes y CSV de Investing.com
data/carbon/historico/series.csv   histórico (generado)
reportes/carbon/                   reporte vigente, historial, CSV del modelo y resumen.json del tablero (generado)
```

## Ideas para extender
- SUNAT (ADUANET): DUAs de importación de carbón por Conchán (precio real por embarque).
- ANM Colombia: precio base de liquidación de regalías del carbón (trimestral).
- Índices de fletes (Baltic Supramax/Panamax) y bunker VLSFO Panamá si dispones de suscripción.
- Restricciones de calado del Canal de Panamá (ACP) como alerta de flete.
