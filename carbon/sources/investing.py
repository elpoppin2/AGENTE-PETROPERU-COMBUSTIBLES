"""CSV de "Datos históricos" descargados manualmente desde Investing.com.

Investing no tiene API pública y sus términos prohíben la extracción
automatizada, así que el bot sólo lee los CSV que el usuario descarga y guarda
en data/carbon/manual/investing/. Acepta el formato del sitio en inglés
("Date","Price",... con 10/21/2026 y 1,234.50) y en español
("Fecha","Último",... con 21.10.2026 y 1.234,50).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .base import frame, monthly_mean

log = logging.getLogger(__name__)

PRICE_COLUMNS = ("price", "close", "último", "ultimo", "cierre")
SPANISH_HEADERS = ("fecha", "último", "ultimo", "apertura", "máximo", "mínimo")


def _number(text: str, decimal_comma: bool) -> float | None:
    s = str(text).strip().replace(" ", "")
    if decimal_comma:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_csv(path: Path, serie: str) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    cols = [c.strip().lower() for c in raw.columns]
    spanish = any(c in SPANISH_HEADERS for c in cols)
    price_idx = next((i for i, c in enumerate(cols) if c in PRICE_COLUMNS), 1)
    dates = raw.iloc[:, 0].str.strip()
    if dates.str.contains(r"^\d{1,2}\.\d{1,2}\.\d{4}$").all():
        fecha = pd.to_datetime(dates, format="%d.%m.%Y", errors="coerce")
    else:
        fecha = pd.to_datetime(dates, dayfirst=spanish, errors="coerce")
    df = pd.DataFrame({
        "fecha": fecha,
        "valor": [_number(v, spanish) for v in raw.iloc[:, price_idx]],
    }).dropna()
    return monthly_mean(df, serie, "USD/t", f"Investing.com ({path.name})")


def fetch(folder: Path, mapping: dict[str, str]) -> pd.DataFrame:
    if not folder.exists():
        return frame([])
    out = []
    for path in sorted(folder.glob("*.csv")):
        name = path.stem.lower()
        serie = next((s for key, s in mapping.items() if key in name), None)
        if serie is None:
            log.warning("Investing: no sé a qué serie corresponde %s (renómbralo con api2/newcastle/...)", path.name)
            continue
        try:
            out.append(parse_csv(path, serie))
        except Exception as e:
            log.warning("Investing: no se pudo leer %s: %s", path.name, e)
    return pd.concat(out, ignore_index=True) if out else frame([])
