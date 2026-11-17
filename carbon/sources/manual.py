"""Cotizaciones propias de carbón (proveedores, brokers, Argus/Platts) cargadas a mano.

data/carbon/manual/cotizaciones.csv
    fecha,material,base,precio_usd_t,poder_calorifico_kcal_kg,proveedor,comentario
    2026-10-15,carbon,FOB,118.5,6000,Proveedor X,Puerto Nuevo
data/carbon/manual/fletes.csv
    fecha,material,flete_usd_t,tipo_buque,fuente,comentario
    2026-10-10,carbon,25,Supramax,Broker Y,Puerto Nuevo-Conchán

Las cotizaciones FOB de carbón se normalizan al poder calorífico de referencia del
índice para que sean comparables con Newcastle. Las CFR y CIF son precios entregados
en Conchán (incluyen flete) y se usan tal cual.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .base import frame, monthly_mean

log = logging.getLogger(__name__)


def fetch(manual_dir: Path, cfg: dict) -> pd.DataFrame:
    out = []
    cv_ref = cfg["carbon"]["poder_calorifico_ref_kcal_kg"]

    q_path = manual_dir / "cotizaciones.csv"
    if q_path.exists():
        q = pd.read_csv(q_path, parse_dates=["fecha"])
        q["material"] = q["material"].str.strip().str.lower()
        q["base"] = q["base"].str.strip().str.upper()
        q["valor"] = pd.to_numeric(q["precio_usd_t"], errors="coerce").astype(float)  # precios enteros: se normalizan a decimales
        is_coal = (q["material"] == "carbon") & (q["base"] == "FOB")
        cv = pd.to_numeric(q.get("poder_calorifico_kcal_kg"), errors="coerce").fillna(cv_ref)
        q.loc[is_coal, "valor"] = q.loc[is_coal, "valor"] * cv_ref / cv[is_coal]
        for (mat, base), g in q.dropna(subset=["valor"]).groupby(["material", "base"]):
            out.append(monthly_mean(g[["fecha", "valor"]], f"manual_{mat}_{base.lower()}",
                                    "USD/t", "Cotización propia"))

    f_path = manual_dir / "fletes.csv"
    if f_path.exists():
        f = pd.read_csv(f_path, parse_dates=["fecha"])
        f["material"] = f["material"].str.strip().str.lower()
        f["valor"] = pd.to_numeric(f["flete_usd_t"], errors="coerce")
        for mat, g in f.dropna(subset=["valor"]).groupby("material"):
            out.append(monthly_mean(g[["fecha", "valor"]], f"manual_flete_{mat}", "USD/t", "Cotización propia"))

    return pd.concat(out, ignore_index=True) if out else frame([])
