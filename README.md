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

Columna `estado`:

- `actualizado` – precio nuevo publicado por Petroperú ese día.
- `sin_cambio` – Petroperú publica el mismo precio que el día anterior.
- `ultimo_registrado` – no se pudo obtener ese día; se usa el último precio guardado.

`fecha_precio` es la fecha de vigencia de la lista de Petroperú de la que sale el precio.

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
