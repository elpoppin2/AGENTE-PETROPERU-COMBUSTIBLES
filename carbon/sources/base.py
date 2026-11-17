from __future__ import annotations

import logging

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

OUT_COLUMNS = ["fecha", "serie", "valor", "unidad", "fuente"]
USER_AGENT = "sourcing-internacional-unacem/0.1 (+https://github.com)"


def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = USER_AGENT
    return s


def frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=OUT_COLUMNS)
    return pd.DataFrame(rows)[OUT_COLUMNS]


def monthly_mean(df: pd.DataFrame, serie: str, unidad: str, fuente: str) -> pd.DataFrame:
    """Convierte una serie diaria/irregular (fecha, valor) en promedio mensual."""
    if df.empty:
        return frame([])
    m = df.set_index("fecha")["valor"].resample("MS").mean().dropna()
    return frame(
        [{"fecha": d, "serie": serie, "valor": v, "unidad": unidad, "fuente": fuente} for d, v in m.items()]
    )
