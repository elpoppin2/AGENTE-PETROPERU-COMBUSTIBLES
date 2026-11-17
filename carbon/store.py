"""Almacén de series en un CSV largo (fecha, serie, valor, unidad, fuente).

Formato simple y legible en diffs de git: cada corrida del bot hace upsert por
(fecha, serie), de modo que las revisiones de las fuentes sobrescriben el dato
anterior y el historial queda versionado en el repositorio.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

COLUMNS = ["fecha", "serie", "valor", "unidad", "fuente", "actualizado"]


def load(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, parse_dates=["fecha"])
    return df[COLUMNS]


def upsert(path: Path, new: pd.DataFrame) -> pd.DataFrame:
    """Inserta/actualiza observaciones y guarda. Devuelve el histórico completo."""
    old = load(path)
    if new.empty:
        return old
    new = new.copy()
    new["fecha"] = pd.to_datetime(new["fecha"]).dt.to_period("M").dt.to_timestamp()
    new["actualizado"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new = new.dropna(subset=["valor"])[COLUMNS]
    frames = [df for df in (old, new) if not df.empty]
    merged = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["fecha", "serie"], keep="last")
        .sort_values(["serie", "fecha"])
        .reset_index(drop=True)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path, index=False, date_format="%Y-%m-%d", float_format="%.4f")
    return merged


def wide(hist: pd.DataFrame) -> pd.DataFrame:
    """Pivot mensual: índice = fecha, columnas = series."""
    if hist.empty:
        return pd.DataFrame()
    out = hist.pivot_table(index="fecha", columns="serie", values="valor", aggfunc="last")
    out.index = pd.DatetimeIndex(out.index)
    return out.sort_index()
