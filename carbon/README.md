# Precios carbones internacionales — Puerto Conchán

Módulo que sigue cada semana la evolución del precio del **carbón térmico
colombiano** (HS 2701.12) importado por **Puerto Conchán (Lima, Perú)**, un insumo
crítico de la operación.

Combina **información pública gratuita**, los **CSV que descargues de Investing.com**
y tus **cotizaciones propias**. Con eso arma el **precio FOB** y el **Calibración del FOB:** el ratio Colombia/índice se calcula con las exportaciones de Colombia **a
Perú** (carbón de alto poder calorífico, que se asume a `poder_calorifico_comercio_pe_kcal_kg`), no con
el promedio de sus exportaciones al mundo, que es carbón más barato. Con menos de 3 datos de comercio
con Perú se usa el del mundo.

**CFR comparable con ofertas:** CFR + `atenuantes` de la configuración (granulometría fina, calidad
y costo financiero del plazo de pago). Sirve para comparar una oferta con el mercado.

**CFR Muelle Conchán**
(FOB + flete marítimo, en USD y PEN), calcula **ratios** de seguimiento y dispara **alertas**.
No calcula el costo puesto en planta.

Es parte del proyecto **Sourcing Internacional Combustibles y Materia Prima** ([README principal](../README.md)).

👉 Reporte vigente: [`reportes/carbon/ultimo_reporte.md`](../reportes/carbon/ultimo_reporte.md) · Tablero: pestaña *Precios carbones internacionales*

---

## Escoria granulada de Japón (GBFS)

El mismo monitor sigue la **escoria granulada de alto horno** (HS 261800) de Japón, con la misma
estructura que el carbón: **FOB Japón + flete = CFR Muelle Conchán** (pestaña *Escoria japonesa*).

- No hay índice público ni precio diario. El FOB es, en orden: la cotización cargada
  (`material = escoria` en `data/carbon/manual/cotizaciones.csv`), el valor unitario de las
  exportaciones de Japón a Perú en UN Comtrade (mensual; si falta, el anual) y, si no, el último dato.
- Si falta el dato mensual a Perú, el FOB se estima con lo que Japón exporta al mundo × la relación
  Perú/mundo (mediana), porque Japón vende más caro a Asia; el valor del mundo no se usa tal cual.
- El flete Japón→Conchán se estima con el Brent y se calibra con `CIF Perú − FOB Japón` (Comtrade) de
  los últimos `meses_calibracion` (36) meses.
- CFR comparable con ofertas = CFR + costo del crédito (`escoria.atenuantes`).
- Se compara con el CIF real de Perú desde Japón (Comtrade). Alerta si el CFR supera
  `escoria.presupuesto_cfr_usd_t` (opcional; vacía por defecto).

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

**CFR Muelle Conchán**
```
CFR     = FOB + flete marítimo      (una cotización CFR cargada tiene prioridad)
PEN/t   = CFR × TC BCRP
```

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
- Variación mensual mayor a `variacion_mensual_pct` (API2, Newcastle, FOB, flete, CFR, TC, Brent).
- Valor fuera de rango histórico (|z| ≥ `zscore`).
- CFR Conchán por encima de la referencia `presupuesto_cfr_usd_t` (opcional; vacía por defecto).

Cuando aparece una alerta que no se había avisado, el workflow abre un issue en GitHub
(etiqueta "alerta carbón") y envía un correo a los destinatarios de `AVISO_CORREOS` (los mismos
de los avisos del diésel), con el desglose del costo. La misma alerta con otra cifra no se
repite cada semana; si desaparece y vuelve, se avisa de nuevo. Prueba manual:
`python -m carbon enviar` envía el último `reportes/carbon/aviso.md`.

### Del FOB al CFR
`modelo_mensual.csv` separa cada mes el **precio FOB** (material) y el **flete marítimo**, que
suman el **CFR Muelle Conchán**. El tablero lo muestra en tabla y en columnas apiladas desde
enero de 2018.

### Frecuencia y rezago
El workflow corre cada lunes, pero las fuentes públicas son **mensuales**: FRED/FMI y el Banco
Mundial publican el promedio del mes con ~1 mes de rezago; UN Comtrade, con 2 a 4 meses. Por eso
el último mes con índice suele ser el anterior. Las cotizaciones propias (`data/carbon/manual/`)
se reflejan apenas se suben.

## Uso

```bash
pip install -r requirements.txt
python -m carbon update        # descarga datos → data/carbon/historico/series.csv
python -m carbon report        # calcula, grafica y escribe reportes/carbon/ultimo_reporte.md
python -m carbon all           # todo + notificación Telegram
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
Todo está en [`carbon/config.yaml`](config.yaml): kcal de tu contrato, flete base,
referencia CFR, índice preferido y umbrales de alerta. Los valores marcados con **AJUSTAR** son supuestos iniciales.

## Automatización (GitHub Actions)

El workflow [`carbon.yml`](../.github/workflows/carbon.yml) corre **cada lunes
07:17 (Lima)**, al subir cotizaciones o CSV de Investing, y manualmente desde
*Actions → Run workflow*. Guarda el histórico y el reporte en el repositorio.

Secretos opcionales (*Settings → Secrets and variables → Actions*):

| Secreto | Uso |
|---|---|
| `FRED_API_KEY` | Clave gratuita de [fredaccount.stlouisfed.org](https://fredaccount.stlouisfed.org) si la descarga pública de FRED es bloqueada |
| `COMTRADE_API_KEY` | Clave gratuita de [comtradedeveloper.un.org](https://comtradedeveloper.un.org) para más cuota |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Resumen y alertas por Telegram |

Sin ningún secreto el bot funciona igual con las fuentes públicas.

## Estructura

```
carbon/config.yaml                 supuestos, umbrales y fuentes
carbon/sources/                    conectores: fred, worldbank, bcrp, comtrade, investing, manual
carbon/analytics.py                FOB, flete y CFR Conchán, ratios, indicadores y alertas
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
