"""FRED (Federal Reserve Bank of St. Louis).

Sin clave usa la descarga CSV pública; con FRED_API_KEY (gratis en
fredaccount.stlouisfed.org) usa la API oficial, más estable desde servidores.
"""
from __future__ import annotations

import io
import logging
import os

import pandas as pd

from .base import frame, monthly_mean, session

log = logging.getLogger(__name__)

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
API_URL = "https://api.stlouisfed.org/fred/series/observations"

# id FRED -> (serie interna, unidad)
SERIES = {
    "PCOALAUUSDM": ("carbon_newcastle_fob", "USD/t"),       # IMF: Australia thermal coal, FOB Newcastle
    "MCOILBRENTEU": ("brent", "USD/bbl"),                   # Brent Europa, promedio mensual
    "COLCCUSMA02STM": ("fx_cop_usd", "COP por USD"),        # OCDE: peso colombiano por dólar
}


def parse_csv(text: str, fred_id: str, serie: str, unidad: str) -> pd.DataFrame:
    if fred_id not in text.split("\n", 1)[0]:
        raise ValueError(f"respuesta inesperada: {text[:120]!r}")
    df = pd.read_csv(io.StringIO(text))
    date_col = df.columns[0]            # "observation_date" (actual) o "DATE" (antiguo)
    df = df.rename(columns={date_col: "fecha", fred_id: "valor"})
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")   # FRED usa "." para faltantes
    return monthly_mean(df.dropna(), serie, unidad, f"FRED {fred_id}")


def parse_api_json(payload: dict, fred_id: str, serie: str, unidad: str) -> pd.DataFrame:
    df = pd.DataFrame(payload.get("observations", []), columns=["date", "value"])
    df = pd.DataFrame({"fecha": pd.to_datetime(df["date"]),
                       "valor": pd.to_numeric(df["value"], errors="coerce")})
    return monthly_mean(df.dropna(), serie, unidad, f"FRED {fred_id}")


def fetch(start: str) -> pd.DataFrame:
    s = session()
    key = os.environ.get("FRED_API_KEY")
    out = []
    for fred_id, (serie, unidad) in SERIES.items():
        try:
            if key:
                r = s.get(API_URL, params={"series_id": fred_id, "api_key": key, "file_type": "json",
                                           "observation_start": f"{start}-01"}, timeout=60)
                r.raise_for_status()
                out.append(parse_api_json(r.json(), fred_id, serie, unidad))
                continue
            r = s.get(URL, params={"id": fred_id, "cosd": f"{start}-01"}, timeout=60)
            r.raise_for_status()
            out.append(parse_csv(r.text, fred_id, serie, unidad))
        except Exception as e:  # una serie caída no debe tumbar el resto
            log.warning("FRED %s falló: %s", fred_id, e)
    return pd.concat(out, ignore_index=True) if out else frame([])
