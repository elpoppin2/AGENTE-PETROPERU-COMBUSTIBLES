"""Petróleo Brent y diésel internacional, precio spot diario (pestaña "Petróleo Brent").

Descarga de FRED (datos de la EIA de EE.UU.) el Brent spot en dólares por barril y el
diésel de ultra bajo azufre de la Costa del Golfo de EE.UU. (la referencia de importación
del diésel en Perú) en dólares por galón, y del BCRP el tipo de cambio interbancario.
Con ellos escribe data/brent.csv con el precio por barril, por galón (1 barril = 42 galones)
y en soles por galón, desde 2018.

Uso: python brent.py            (actualiza data/brent.csv)
Si una fuente falla, se conservan los datos que ya había.
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from carbon.sources.base import session
from carbon.sources.bcrp import URL as URL_BCRP, parse_period

log = logging.getLogger("brent")

RAIZ = Path(__file__).resolve().parent
ARCHIVO = RAIZ / "data" / "brent.csv"
INICIO = "2018-01-01"
GALONES_POR_BARRIL = 42

URL_FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"
API_FRED = "https://api.stlouisfed.org/fred/series/observations"
FRED = {
    "DCOILBRENTEU": "brent_usd_bbl",           # Brent Europa, spot diario (EIA), US$ por barril
    "DDFUELUSGULF": "diesel_golfo_usd_gal",    # Diésel ULSD Costa del Golfo, spot diario (EIA), US$ por galón
}
BCRP_FX = "PD04638PD"                          # tipo de cambio interbancario, venta (diario)

COLUMNAS = ["fecha", "brent_usd_bbl", "brent_usd_gal", "diesel_golfo_usd_gal", "fx_pen_usd",
            "brent_pen_gal", "diesel_golfo_pen_gal"]


def leer_fred_csv(texto: str, fred_id: str) -> pd.Series:
    """CSV de fredgraph -> serie diaria (los faltantes vienen como ".")."""
    if fred_id not in texto.split("\n", 1)[0]:
        raise ValueError(f"respuesta inesperada de FRED: {texto[:120]!r}")
    df = pd.read_csv(io.StringIO(texto))
    s = pd.Series(pd.to_numeric(df[fred_id], errors="coerce").to_numpy(), index=pd.to_datetime(df.iloc[:, 0]))
    return s.dropna().sort_index()


def leer_fred_json(payload: dict) -> pd.Series:
    obs = payload.get("observations", [])
    s = pd.Series([pd.to_numeric(o.get("value"), errors="coerce") for o in obs],
                  index=pd.to_datetime([o.get("date") for o in obs]), dtype=float)
    return s.dropna().sort_index()


def leer_bcrp_diario(texto: str) -> pd.Series:
    """JSON de la API del BCRP -> serie diaria del tipo de cambio."""
    payload = json.loads(texto.strip().lstrip("﻿"))
    filas = {}
    for p in payload.get("periods", []):
        fecha = parse_period(p.get("name", ""))
        valor = pd.to_numeric((p.get("values") or [None])[0], errors="coerce")
        if fecha is not None and pd.notna(valor):
            filas[fecha] = float(valor)
    return pd.Series(filas, dtype=float).sort_index()


def descargar() -> dict[str, pd.Series]:
    s, clave, out = session(), os.environ.get("FRED_API_KEY"), {}
    for fred_id, col in FRED.items():
        try:
            if clave:
                r = s.get(API_FRED, params={"series_id": fred_id, "api_key": clave, "file_type": "json",
                                            "observation_start": INICIO}, timeout=60)
                r.raise_for_status()
                out[col] = leer_fred_json(r.json())
            else:
                r = s.get(URL_FRED, params={"id": fred_id, "cosd": INICIO}, timeout=60)
                r.raise_for_status()
                out[col] = leer_fred_csv(r.text, fred_id)
            log.info("FRED %s: %d días, último %s", fred_id, len(out[col]), out[col].index[-1].date())
        except Exception as e:  # una serie caída no tumba las demás
            log.warning("FRED %s falló: %s", fred_id, e)
    try:
        r = s.get(URL_BCRP.format(code=BCRP_FX, start="2018-1-1", end=date.today().isoformat()), timeout=60)
        r.raise_for_status()
        out["fx_pen_usd"] = leer_bcrp_diario(r.text)
        log.info("BCRP %s: %d días", BCRP_FX, len(out["fx_pen_usd"]))
    except Exception as e:
        log.warning("BCRP %s falló: %s", BCRP_FX, e)
    return out


def armar(series: dict[str, pd.Series], anterior: pd.DataFrame | None = None) -> pd.DataFrame:
    """Une las series nuevas con las ya guardadas y calcula el galón en dólares y en soles."""
    base = (anterior.set_index("fecha")[["brent_usd_bbl", "diesel_golfo_usd_gal", "fx_pen_usd"]]
            if anterior is not None and not anterior.empty else pd.DataFrame(columns=["brent_usd_bbl", "diesel_golfo_usd_gal", "fx_pen_usd"]))
    base.index = pd.to_datetime(base.index)
    for col, s in series.items():
        if s is not None and len(s):
            base = base.reindex(base.index.union(s.index))
            base.loc[s.index, col] = s.to_numpy()   # lo nuevo reemplaza a lo guardado
    df = base.sort_index().apply(pd.to_numeric, errors="coerce")
    df = df[df.index >= INICIO]
    # El tipo de cambio de un día sin publicación es el del último día hábil anterior.
    df["fx_pen_usd"] = df["fx_pen_usd"].ffill()
    df = df.dropna(subset=["brent_usd_bbl", "diesel_golfo_usd_gal"], how="all")
    df["brent_usd_gal"] = df["brent_usd_bbl"] / GALONES_POR_BARRIL
    df["brent_pen_gal"] = df["brent_usd_gal"] * df["fx_pen_usd"]
    df["diesel_golfo_pen_gal"] = df["diesel_golfo_usd_gal"] * df["fx_pen_usd"]
    df = df.reset_index(names="fecha")
    df["fecha"] = df["fecha"].dt.strftime("%Y-%m-%d")
    return df[COLUMNAS]


def actualizar(archivo: Path = ARCHIVO) -> pd.DataFrame:
    anterior = pd.read_csv(archivo) if archivo.exists() else None
    series = descargar()
    if not series and anterior is not None:
        log.warning("Sin datos nuevos: se conserva %s", archivo.name)
        return anterior
    df = armar(series, anterior)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    df.round({"brent_usd_bbl": 2, "brent_usd_gal": 4, "diesel_golfo_usd_gal": 4, "fx_pen_usd": 4,
              "brent_pen_gal": 4, "diesel_golfo_pen_gal": 4}).to_csv(archivo, index=False)
    ult = df.dropna(subset=["brent_usd_bbl"]).iloc[-1] if df["brent_usd_bbl"].notna().any() else None
    if ult is not None:
        log.info("Brent %s: US$ %.2f/barril = US$ %.4f/galón = S/ %.4f/galón",
                 ult.fecha, ult.brent_usd_bbl, ult.brent_usd_gal, ult.brent_pen_gal)
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    actualizar()
    sys.exit(0)
