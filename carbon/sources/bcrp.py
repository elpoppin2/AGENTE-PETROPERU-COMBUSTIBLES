"""BCRP (Banco Central de Reserva del Perú) — API de series estadísticas."""
from __future__ import annotations

import json
import logging
from datetime import date

import pandas as pd

from .base import frame, monthly_mean, session

log = logging.getLogger(__name__)

URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{code}/json/{start}/{end}"

# código BCRP -> (serie interna, unidad)
SERIES = {
    "PD04638PD": ("fx_pen_usd", "PEN por USD"),   # Tipo de cambio interbancario - venta (diario)
}

MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
         "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}


def parse_period(name: str) -> pd.Timestamp | None:
    """'02.Ene.24' (diario) o 'Ene.2024' (mensual)."""
    parts = name.strip().split(".")
    try:
        if len(parts) == 3:
            d, m, y = parts
            year = int(y) + (2000 if len(y) == 2 else 0)
            return pd.Timestamp(year=year, month=MESES[m.lower()[:3]], day=int(d))
        if len(parts) == 2:
            m, y = parts
            return pd.Timestamp(year=int(y), month=MESES[m.lower()[:3]], day=1)
    except (KeyError, ValueError):
        return None
    return None


def parse_json(text: str, serie: str, unidad: str, code: str) -> pd.DataFrame:
    payload = json.loads(text.strip().lstrip("﻿"))
    rows = []
    for p in payload.get("periods", []):
        fecha = parse_period(p.get("name", ""))
        valor = pd.to_numeric((p.get("values") or [None])[0], errors="coerce")  # "n.d." -> NaN
        if fecha is not None and pd.notna(valor):
            rows.append({"fecha": fecha, "valor": float(valor)})
    df = pd.DataFrame(rows, columns=["fecha", "valor"])
    return monthly_mean(df, serie, unidad, f"BCRP {code}")


def fetch(start: str) -> pd.DataFrame:
    s = session()
    y, m = (int(x) for x in start.split("-"))
    out = []
    for code, (serie, unidad) in SERIES.items():
        try:
            r = s.get(URL.format(code=code, start=f"{y}-{m}-1", end=date.today().isoformat()), timeout=60)
            r.raise_for_status()
            out.append(parse_json(r.text, serie, unidad, code))
        except Exception as e:
            log.warning("BCRP %s falló: %s", code, e)
    return pd.concat(out, ignore_index=True) if out else frame([])
