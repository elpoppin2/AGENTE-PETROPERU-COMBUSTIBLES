# Agente de precios de diésel – Petroperú

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
