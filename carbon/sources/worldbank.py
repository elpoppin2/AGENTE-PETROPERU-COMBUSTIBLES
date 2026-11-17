"""Banco Mundial — Pink Sheet (Commodity Markets), libro mensual histórico.

La URL del Excel cambia cada mes, así que se descubre desde la página de
Commodity Markets y, si falla, se prueba una lista de URLs conocidas.
"""
from __future__ import annotations

import io
import logging
import re

import pandas as pd

from .base import frame, session

log = logging.getLogger(__name__)

PAGE = "https://www.worldbank.org/en/research/commodity-markets"
FALLBACK_URLS = [
    "https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx",
]
LINK_RE = re.compile(r'href="([^"]*CMO-Historical-Data-Monthly\.xlsx)"', re.IGNORECASE)
DATE_RE = re.compile(r"^(\d{4})M(\d{2})$")

# prefijo de columna en el Pink Sheet -> (serie interna, unidad)
COLUMNS = {
    "coal, australian": ("carbon_bm_australia_fob", "USD/t"),
    "coal, south african": ("carbon_bm_sudafrica_fob", "USD/t"),
    "coal, colombian": ("carbon_bm_colombia_fob", "USD/t"),   # discontinuada en algunas ediciones
    "crude oil, brent": ("brent_bm", "USD/bbl"),
}


def discover_url(s) -> list[str]:
    urls = []
    try:
        html = s.get(PAGE, timeout=60).text
        urls += [u if u.startswith("http") else "https://www.worldbank.org" + u for u in LINK_RE.findall(html)]
    except Exception as e:
        log.warning("No se pudo leer la página de Commodity Markets: %s", e)
    return urls + FALLBACK_URLS


def parse_xlsx(content: bytes, start: str) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(content), sheet_name="Monthly Prices", header=None)
    header_row = next(
        i for i in range(min(len(raw), 15))
        if any(str(v).strip().lower().startswith("coal") for v in raw.iloc[i].values)
    )
    headers = [str(v).strip().lower() for v in raw.iloc[header_row].values]
    col_map = {}
    for idx, h in enumerate(headers):
        for prefix, target in COLUMNS.items():
            if h.startswith(prefix):
                col_map[idx] = target
    start_ts = pd.Timestamp(f"{start}-01")
    rows = []
    for _, row in raw.iloc[header_row + 1:].iterrows():
        m = DATE_RE.match(str(row.iloc[0]).strip())
        if not m:
            continue
        fecha = pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=1)
        if fecha < start_ts:
            continue
        for idx, (serie, unidad) in col_map.items():
            valor = pd.to_numeric(row.iloc[idx], errors="coerce")
            if pd.notna(valor):
                rows.append({"fecha": fecha, "serie": serie, "valor": float(valor),
                             "unidad": unidad, "fuente": "Banco Mundial Pink Sheet"})
    return frame(rows)


def fetch(start: str) -> pd.DataFrame:
    s = session()
    for url in discover_url(s):
        try:
            r = s.get(url, timeout=120)
            r.raise_for_status()
            return parse_xlsx(r.content, start)
        except Exception as e:
            log.warning("Pink Sheet %s falló: %s", url, e)
    return frame([])
