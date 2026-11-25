# Sourcing Internacional Combustibles y Materia Prima

Proyecto de UNACEM que sigue los precios de los combustibles y materias primas que se compran.
Tiene tres módulos y un solo tablero web:

| Módulo | Qué sigue | Frecuencia | Código |
|---|---|---|---|
| **Diésel** | Precios de lista de Petroperú (B5 S-50 y B5 S-50 UV) y precios de referencia de Osinergmin | Diario (08:00 y 12:30 de Lima) | `agente_petroperu.py` |
| **Precios carbones internacionales** | Índices internacionales del carbón (Newcastle, API4, API2), precio FOB Colombia y CFR Muelle Conchán, con alertas por correo | Semanal (lunes) | [`carbon/`](carbon/README.md) |
| **Petróleo Brent** | Brent spot (US$/barril, US$/galón y S/ por galón) y diésel ULSD de la Costa del Golfo de EE.UU., comparados con la referencia de Osinergmin y la lista de Petroperú en Conchán | Diario (con el diésel; la EIA publica con 2 a 5 días hábiles de rezago) | `brent.py` |
| **Escoria japonesa** | Escoria granulada de alto horno (GBFS) de Japón: precio FOB Japón y CFR Muelle Conchán, comparados con el comercio exterior Japón→Perú, con alertas por correo | Semanal (lunes) | [`carbon/`](carbon/README.md) |

- **Tablero:** https://elpoppin2.github.io/AGENTE-PETROPERU-COMBUSTIBLES/ (pestañas *Precios Petroperú*,
  *Referencia Osinergmin*, *Precios carbones internacionales*, *Escoria japonesa* y *Petróleo Brent*).
- **Repositorio:** https://github.com/elpoppin2/AGENTE-PETROPERU-COMBUSTIBLES
- **Preguntar en Claude:** botón flotante abajo a la derecha del tablero. Explica cómo abrir
  Claude Code con este repositorio para hacer consultas sobre los datos. Ver [Preguntar en Claude](#preguntar-en-claude).
- **Interfaz del tablero:** usa librerías de código abierto de GitHub, empaquetadas en
  `assets/vendor/` (sin depender de servidores externos): [Motion](https://github.com/motiondivision/motion)
  para las animaciones, [Tom Select](https://github.com/orchidjs/tom-select) para el selector de planta
  con búsqueda, [Tippy.js](https://github.com/atomiks/tippyjs) para el menú de descargas y las ayudas, y
  [NumberFlow](https://github.com/barvian/number-flow) para las cifras que ruedan. Para actualizarlas:
  `cd herramientas/librerias && npm ci && npm run construir`. Licencias en `assets/vendor/LICENCIAS.txt`.
- **Pruebas de todo el proyecto:** `pip install -r requirements.txt && python -m pytest -q`

El módulo de carbón viene del repositorio `PRECIOS-COMBUSTIBLES-CARB-N-IMPORTADO---COLOMBIA`; su
documentación completa está en [`carbon/README.md`](carbon/README.md) y su workflow en
[`.github/workflows/carbon.yml`](.github/workflows/carbon.yml).

---

## Módulo diésel: agente de precios de Petroperú

Agente que **todos los días** entra a
[Listas de precios en nuestras plantas de ventas](https://www.petroperu.com.pe/productos/lista-de-precios-en-nuestras-plantas/),
abre la lista **Automotriz** más reciente (PDF) y guarda, por cada planta de venta, el precio del
**Diésel B5 S-50** y del **Diésel B5 S-50 UV (uso vehicular)**. Si ese día Petroperú no publicó cambios —o la web
no responde— se registra **el último precio conocido**.

## Combustibles que registra

| Clave | Producto |
|---|---|
| `DIESEL_B5_S50` | Diésel B5 S-50 |
| `DIESEL_B5_S50_UV` | Diésel B5 S-50 UV (uso vehicular) |

Los precios salen del **Addendum N° 1** de cada lista (soles por galón, con
impuestos, sin descuentos ni FISE). No se registran el "DIESEL B5 UV" ni el
"DIESEL B5" sin S-50 de la primera página, ni los precios "G. E." (generadoras
eléctricas) del Addendum N° 2.

Reconoce variantes de escritura como `Diesel B5-S50`, `DB5 S-50`,
`Diesel B5-S50UV` o `Diésel B5 S-50 (Uso Vehicular)`. Todo lo demás
(gasoholes, gasolinas, GLP, Turbo, Diésel B5 S-50 Industrial, Diésel B5 sin
S-50) se ignora. Para cambiar la selección, edita la lista `COMBUSTIBLES` en
`agente_petroperu.py`.

## Resultados

| Archivo | Contenido |
|---|---|
| `data/historial.csv` | Una fila por día, combustible y ubicación/planta |
| `data/precios_actuales.json` | Foto de los precios del último día consultado |
| `data/listas.csv` | Un precio por lista publicada por Petroperú (desde 2023); alimenta el tablero |
| `data/precios-diesel-petroperu.xlsx` | Excel con todo el histórico (precios vigentes, histórico por planta y datos); se descarga desde el tablero |

Columna `estado`:

- `actualizado` – precio nuevo publicado por Petroperú ese día.
- `sin_cambio` – Petroperú publica el mismo precio que el día anterior.
- `ultimo_registrado` – no se pudo obtener ese día; se usa el último precio guardado.

`fecha_precio` es la fecha de vigencia de la lista de Petroperú de la que sale el precio.

## Reporte diario por correo (desactivado)

El agente puede enviar un reporte todos los días aunque no haya cambios
(`python agente_petroperu.py --reporte-diario`), pero por ahora solo se envía
correo cuando Petroperú publica una lista nueva. Para activarlo, se agrega ese
paso al workflow `precios-diarios.yml`.

## Avisos de cambio de precio

Cuando Petroperú publica una lista nueva, el agente guarda un reporte en
`reportes/AAAA-MM-DD.md` (precio de cada planta, variación frente a la lista
anterior) y lo publica como *Issue* con la etiqueta **cambio de precio**.
GitHub lo envía por correo y a la app de GitHub. Para probarlo: *Actions →
Precios diarios Petroperú → Run workflow* marcando "Enviar otra vez el aviso".

### Enviar el aviso a otros correos y a WhatsApp

El aviso también puede llegar por correo a cualquier persona y por WhatsApp.
Se configura en GitHub, en *Settings → Secrets and variables → Actions →
New repository secret* (los secrets no se ven en el repositorio, que es público):

| Secret | Valor |
|---|---|
| `AVISO_CORREO_USUARIO` | Cuenta de Gmail que envía, p. ej. `avisos.precios@gmail.com` |
| `AVISO_CORREO_CLAVE` | Contraseña de aplicación de esa cuenta (Cuenta de Google → Seguridad → Verificación en 2 pasos → Contraseñas de aplicaciones) |
| `AVISO_CORREOS` | Destinatarios separados por comas |
| `AVISO_WHATSAPP` | `telefono:apikey` de [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/), separados por comas, p. ej. `+51999888777:123456` |

Para obtener su `apikey`, cada persona agrega el número de CallMeBot a sus
contactos y le envía por WhatsApp el mensaje *I allow callmebot to send me messages*.

## Promedio ponderado mensual (día 1 de cada mes)

El día 1 de cada mes, después de leer los precios, el agente calcula el promedio
ponderado del mes que cerró en la planta Conchán, para el Diésel B5 S-50 y el B5 S-50 UV:

- Cada precio pondera por los días que estuvo vigente en el mes.
- Si no hubo lista el día 1, ese primer tramo usa la última lista registrada antes.

Deja `reportes/promedio-AAAA-MM.md` y un Excel con fórmulas
(`reportes/promedio-ponderado-conchan-AAAA-MM.xlsx`, acumulado desde agosto de 2026).
Avisa con un issue de GitHub (etiqueta "promedio mensual") y por correo a `AVISO_CORREOS`,
con el Excel adjunto. Si la ejecución del día 1 falla, el aviso sale en la siguiente.

Para probarlo: *Actions → Precios diarios Petroperú → Run workflow* y marca
"Enviar otra vez el promedio ponderado". A mano: `python agente_petroperu.py --promedio 2026-10`
(prepara el reporte) y `--enviar-promedio 2026-10` (lo envía).
La planta se cambia con la variable `PETROPERU_PLANTA_PROMEDIO`.

## Petróleo Brent y diésel internacional

`brent.py` (paso del workflow diario) descarga de FRED los precios spot diarios de la EIA del
**Brent** (`DCOILBRENTEU`, US$ por barril) y del **diésel de ultra bajo azufre de la Costa del Golfo
de EE.UU.** (`DDFUELUSGULF`, US$ por galón), y del BCRP el tipo de cambio interbancario venta
(`PD04638PD`). Escribe `data/brent.csv` desde 2018 con el Brent por barril y por galón
(1 barril = 42 galones) y ambos en soles por galón. Si una fuente falla, se conservan los datos
guardados. Con `FRED_API_KEY` usa la API oficial de FRED; sin ella, la descarga CSV pública.

La pestaña "Petróleo Brent" muestra la última cotización, la evolución diaria, la cadena
**crudo → diésel Golfo → referencia Osinergmin (Callao) → lista Petroperú (Conchán)** en soles por
galón y los promedios mensuales.

## Precios de referencia de Osinergmin

El agente también descarga cada semana el PDF de **precios de referencia** de
Osinergmin (`PrecioReferenciaDDMMAAAA.pdf`, publicado los lunes) y guarda en
`data/osinergmin.csv` el precio de referencia del Diésel B5 bajo y alto azufre
de cada planta o terminal (18 puntos del Perú), en soles por galón sin impuestos
ni margen comercial, desde enero de 2023. En cada ejecución revisa todas las
semanas y solo descarga las que falten.

El tablero los muestra en la pestaña "Referencia Osinergmin" (precio vigente por
planta, evolución semanal y publicaciones) y el Excel en las hojas
"Osinergmin B5 bajo azufre" y "Osinergmin B5 alto azufre". Cinco publicaciones
de 2023 y 2024 son imágenes escaneadas sin texto y no tienen datos.

El buscador Facilito (precios de cada grifo) está protegido con reCAPTCHA y no
publica datos abiertos, por eso no se usa.

## Tablero

`index.html` es un tablero con gráficos que lee `data/listas.csv`. Publicado con
GitHub Pages en https://elpoppin2.github.io/AGENTE-PETROPERU-COMBUSTIBLES/ y se
actualiza solo cada vez que el agente guarda una lista nueva.

Para cargar listas antiguas: *Actions → Cargar histórico Petroperú → Run workflow*
(o `python agente_petroperu.py --historico 2023-01-01`).

### Mapa por departamento

En ambas pestañas, el mapa del Perú colorea cada departamento según el precio vigente
de sus plantas (B5 S-50 en Petroperú, B5 bajo azufre en Osinergmin; promedio si tiene
más de una planta). Al pasar el mouse muestra el último precio y su variación; al hacer
clic abre los datos de esa planta. Los departamentos sin planta van en gris.

Los contornos están en `assets/peru-departamentos.json`, generado con
`python herramientas/mapa_peru.py` a partir de
[juaneladio/peru-geojson](https://github.com/juaneladio/peru-geojson) (Mozilla Public
License 2.0). Las ubicaciones de las plantas están en ese mismo script.

## Uso local

```bash
pip install -r requirements.txt
python agente_petroperu.py --descubrir   # primera vez: ver qué páginas y precios encuentra
python agente_petroperu.py               # ejecución normal (guarda en data/)
```

Variables opcionales: `PETROPERU_URLS` (URLs de inicio separadas por coma),
`PETROPERU_DATOS` (carpeta de datos), `PETROPERU_MAX_PAGINAS`.

## Ejecución diaria automática

**Opción A – GitHub Actions (recomendada):** sube esta carpeta a un repositorio
de GitHub. El flujo `.github/workflows/precios-diarios.yml` se ejecuta todos los
días a las 08:00 y a las 12:30 (hora de Lima) y guarda el historial en el mismo repositorio.
También puedes lanzarlo a mano en *Actions → Precios diarios Petroperú → Run workflow*.

**Opción B – Tu computadora:**

- Linux/Mac (`crontab -e`):
  `7 8 * * * cd /ruta/agente-petroperu && python3 agente_petroperu.py >> agente.log 2>&1`
- Windows (Programador de tareas):
  `schtasks /create /tn "Precios Petroperu" /sc daily /st 08:07 /tr "python C:\ruta\agente-petroperu\agente_petroperu.py"`

## Pruebas

```bash
pip install pytest && python -m pytest -q tests
```

## Preguntar en Claude

Las consultas sobre los datos se hacen con **Claude Code**, con la cuenta de Claude de cada persona
(sin costo adicional al plan de Claude ni clave de API). El equipo usa el repositorio en **solo
lectura**: no necesita ser colaborador, y solo el dueño (`elpoppin2`) cambia el proyecto.

1. Abrir https://claude.ai/code e iniciar una sesión (si lo pide, conectar GitHub en https://claude.ai/connect-github).
2. Escribir en el primer mensaje: *"Usa el repositorio público github.com/elpoppin2/AGENTE-PETROPERU-COMBUSTIBLES (lee su CLAUDE.md) y respóndeme: "* seguido de la pregunta. El botón **Preguntar en Claude**
   del tablero (abajo a la derecha) copia este mensaje con un toque.
3. Claude descarga el repositorio público en modo lectura y responde con los datos actualizados.

`CLAUDE.md` le explica a Claude los datos, las unidades, las decisiones del proyecto y que no debe
cambiar nada si solo le preguntan. Un agente de consultas pagado por API (respuestas en issues) se
probó y se retiró; está en el historial de git si se quiere reactivar.
