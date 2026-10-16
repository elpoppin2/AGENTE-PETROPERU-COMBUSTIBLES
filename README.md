# Agente de precios de combustibles – Petroperú

Agente que **todos los días** entra a la página de precios de Petroperú, abre
cada lista de precios (páginas HTML o PDF) y guarda el precio de cada
combustible para automóviles. Si ese día Petroperú no publicó cambios —o la web
no responde— se registra **el último precio conocido**.

## Combustibles que registra

Gasohol 84/90/95/97, Gasohol/Gasolina Regular y Premium, Gasolina 84/90/95/97,
Diésel B5 S-50 (uso vehicular) y GLP automotriz. Se excluyen productos
industriales, marinos, de aviación (Turbo), residuales y asfaltos.

## Resultados

| Archivo | Contenido |
|---|---|
| `data/historial.csv` | Una fila por día, combustible y ubicación/planta |
| `data/precios_actuales.json` | Foto de los precios del último día consultado |

Columna `estado`:

- `actualizado` – precio nuevo publicado por Petroperú ese día.
- `sin_cambio` – Petroperú publica el mismo precio que el día anterior.
- `ultimo_registrado` – no se pudo obtener ese día; se usa el último precio guardado.

`fecha_precio` indica desde cuándo rige ese precio.

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
días a las 08:07 (hora de Lima) y guarda el historial en el mismo repositorio.
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
