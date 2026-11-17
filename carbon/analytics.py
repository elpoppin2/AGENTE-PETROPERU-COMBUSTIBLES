"""Modelo de costo puesto en Conchán del carbón colombiano, ratios e indicadores.

Carbón Colombia FOB (de mayor a menor prioridad):
  1. Cotización propia FOB (data/carbon/manual)
  2. Valor unitario FOB de exportaciones de Colombia a Perú / al mundo (Comtrade)
  3. Pink Sheet "Coal, Colombian" (si el Banco Mundial la publica)
  4. Nowcast: índice x ratio Colombia/índice calibrado. El índice es API2
     (Investing) si está disponible y es el preferido; si no, Newcastle.
Flete
  1. Cotización propia
  2. Modelo flete_base x (Brent / Brent_base)^elasticidad, recalibrado con el
     flete implícito CIF Perú - FOB Colombia de Comtrade
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

KCAL_TO_GJ = 4.1868e-6          # GJ por kcal
GJ_PER_BBL = 6.12               # contenido energético aproximado de un barril de Brent

KEY_SERIES = {
    "carbon_api2_cif_ara": "API2 CIF Rotterdam (USD/t)",
    "carbon_newcastle_fob": "Newcastle FOB (USD/t)",
    "carbon_api4_fob_rb": "API4 FOB Richards Bay (USD/t)",
    "carbon_col_fob": "Colombia FOB, spec contrato (USD/t)",
    "carbon_flete": "Flete Colombia→Conchán (USD/t)",
    "carbon_cif": "CIF Conchán (USD/t)",
    "carbon_landed": "Puesto en planta (USD/t)",
    "carbon_landed_pen": "Puesto en planta (PEN/t)",
    "carbon_usd_gj": "Puesto en planta (USD/GJ)",
    "carbon_cif_comtrade": "CIF Perú desde Colombia — Comtrade (USD/t)",
    "pe_imp_carbon_mundo_cif": "CIF Perú desde todo origen — Comtrade (USD/t)",
    "brent": "Brent (USD/bbl)",
    "fx_pen_usd": "Tipo de cambio (PEN/USD)",
    "fx_cop_usd": "Tipo de cambio (COP/USD)",
}

RATIOS = {
    "ratio_col_api2": "Colombia FOB / API2",
    "ratio_col_newcastle": "Colombia FOB / Newcastle",
    "spread_api2_newcastle": "API2 − Newcastle (USD/t, Atlántico vs Pacífico)",
    "paridad_carbon_brent": "Carbón vs Brent (USD/GJ ÷ USD/GJ)",
    "flete_share_carbon": "Flete / CIF",
    "carbon_vs_cif_comtrade": "CIF modelo / CIF Comtrade Perú",
    "share_colombia_import_pe": "Participación de Colombia en importaciones de Perú (t)",
}


@dataclass
class Result:
    monthly: pd.DataFrame
    indicators: pd.DataFrame
    alerts: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def _col(w: pd.DataFrame, name: str) -> pd.Series:
    return w[name] if name in w.columns else pd.Series(np.nan, index=w.index, dtype=float)


def _first(w: pd.DataFrame, names: list[str]) -> tuple[pd.Series, pd.Series]:
    """Combina series por prioridad. Devuelve (valor, nombre de la fuente usada)."""
    value = pd.Series(np.nan, index=w.index, dtype=float)
    source = pd.Series(None, index=w.index, dtype=object)
    for n in names:
        s = _col(w, n)
        fill = value.isna() & s.notna()
        value[fill] = s[fill]
        source[fill] = n
    return value, source


def _recent_median(s: pd.Series, n: int = 12) -> float | None:
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    return float(s.tail(n).median()) if not s.empty else None


def _freight(brent: pd.Series, fcfg: dict, implied: pd.Series, manual: pd.Series) -> tuple[pd.Series, float]:
    model = fcfg["base_usd_t"] * (brent / fcfg["brent_base_usd_bbl"]) ** fcfg["elasticidad_bunker"]
    model = model.fillna(fcfg["base_usd_t"])
    implied = implied.where((implied > 3) & (implied < 150))     # descarta valores absurdos
    scale = _recent_median(implied / model) or 1.0
    scale = float(np.clip(scale, 0.5, 2.0))
    return manual.combine_first(model * scale), scale


def compute(w: pd.DataFrame, cfg: dict) -> Result:
    if w.empty:
        return Result(pd.DataFrame(), pd.DataFrame(), ["Sin datos todavía: ejecuta `python -m carbon update`."])

    w = w.sort_index()
    dcfg, ccfg = cfg["destino"], cfg["carbon"]
    m = pd.DataFrame(index=w.index)

    # --- Índices de mercado y tipos de cambio ------------------------------------
    # FRED/IMF es el promedio oficial; los futuros de Investing cubren los meses recientes.
    m["carbon_newcastle_fob"], _ = _first(w, ["carbon_newcastle_fob", "carbon_bm_australia_fob",
                                              "carbon_newcastle_futuro"])
    m["carbon_api2_cif_ara"] = _col(w, "carbon_api2_cif_ara")
    m["carbon_api4_fob_rb"], _ = _first(w, ["carbon_api4_fob_rb", "carbon_bm_sudafrica_fob"])
    m["brent"], _ = _first(w, ["brent", "brent_bm"])
    m["brent"] = m["brent"].ffill()
    for fx in ("fx_pen_usd", "fx_cop_usd"):
        m[fx] = _col(w, fx).ffill()

    # --- FOB Colombia -------------------------------------------------------------
    trade_fob, _ = _first(w, ["co_exp_carbon_pe_fob_usd_t", "co_exp_carbon_mundo_fob_usd_t",
                              "carbon_bm_colombia_fob"])
    ratio_nc = _recent_median(trade_fob / m["carbon_newcastle_fob"]) or ccfg["ratio_colombia_newcastle_default"]
    ratio_api2 = _recent_median(trade_fob / m["carbon_api2_cif_ara"]) or ccfg["ratio_colombia_api2_default"]
    now_api2 = m["carbon_api2_cif_ara"] * ratio_api2
    now_nc = m["carbon_newcastle_fob"] * ratio_nc
    if ccfg.get("benchmark_preferido", "api2") == "api2":
        nowcast = now_api2.combine_first(now_nc)
        now_src = np.where(now_api2.notna(), "nowcast_api2", np.where(now_nc.notna(), "nowcast_newcastle", None))
    else:
        nowcast = now_nc.combine_first(now_api2)
        now_src = np.where(now_nc.notna(), "nowcast_newcastle", np.where(now_api2.notna(), "nowcast_api2", None))

    observed, src = _first(w, ["manual_carbon_fob", "co_exp_carbon_pe_fob_usd_t",
                               "co_exp_carbon_mundo_fob_usd_t", "carbon_bm_colombia_fob"])
    fob_ref = observed.combine_first(nowcast)
    cv_adj = ccfg["poder_calorifico_spec_kcal_kg"] / ccfg["poder_calorifico_ref_kcal_kg"]
    m["carbon_col_fob"] = fob_ref * cv_adj
    m["carbon_col_fob_fuente"] = src.where(observed.notna(), now_src)
    m["ratio_col_api2"] = fob_ref / m["carbon_api2_cif_ara"]
    m["ratio_col_newcastle"] = fob_ref / m["carbon_newcastle_fob"]
    m["spread_api2_newcastle"] = m["carbon_api2_cif_ara"] - m["carbon_newcastle_fob"]

    # --- Flete, CIF y puesto en planta ----------------------------------------------
    implied = _col(w, "pe_imp_carbon_col_cif_usd_t") - _col(w, "co_exp_carbon_pe_fob_usd_t")
    m["carbon_flete"], scale = _freight(m["brent"], ccfg["flete"], implied, _col(w, "manual_flete_carbon"))
    cif_model = (m["carbon_col_fob"] + m["carbon_flete"]) * (1 + dcfg["seguro_pct"] / 100)
    m["carbon_cif"] = _col(w, "manual_carbon_cif").combine_first(cif_model)
    port = sum(dcfg["costos_portuarios_usd_t"].values())
    m["carbon_landed"] = m["carbon_cif"] * (1 + ccfg["arancel_pct"] / 100 + dcfg["agente_aduanas_pct"] / 100) + port
    m["carbon_landed_pen"] = m["carbon_landed"] * m["fx_pen_usd"]
    m["carbon_igv_caja_usd_t"] = m["carbon_cif"] * (1 + ccfg["arancel_pct"] / 100) * dcfg["igv_pct"] / 100

    gj_per_t = ccfg["poder_calorifico_spec_kcal_kg"] * 1000 * KCAL_TO_GJ
    m["carbon_usd_gj"] = m["carbon_landed"] / gj_per_t
    m["carbon_usd_gcal"] = m["carbon_landed"] / (ccfg["poder_calorifico_spec_kcal_kg"] / 1000)
    m["paridad_carbon_brent"] = (m["carbon_col_fob"] / gj_per_t) / (m["brent"] / GJ_PER_BBL)
    m["flete_share_carbon"] = m["carbon_flete"] / m["carbon_cif"]
    m["carbon_impacto_anual_musd"] = m["carbon_landed"] * ccfg["consumo_anual_t"] / 1e6

    # --- Mercado peruano de carbón importado (Comtrade) ------------------------------
    m["carbon_cif_comtrade"] = _col(w, "pe_imp_carbon_col_cif_usd_t")
    m["carbon_vs_cif_comtrade"] = m["carbon_cif"] / m["carbon_cif_comtrade"]
    m["pe_imp_carbon_mundo_cif"] = _col(w, "pe_imp_carbon_mundo_cif_usd_t")
    m["pe_imp_carbon_col_vol_t"] = _col(w, "pe_imp_carbon_col_cif_vol_t")
    m["pe_imp_carbon_mundo_vol_t"] = _col(w, "pe_imp_carbon_mundo_cif_vol_t")
    m["share_colombia_import_pe"] = m["pe_imp_carbon_col_vol_t"] / m["pe_imp_carbon_mundo_vol_t"]

    # Recorta meses finales sin ningún índice de referencia (aún no publicados)
    has_index = m[["carbon_newcastle_fob", "carbon_api2_cif_ara"]].notna().any(axis=1)
    if has_index.any():
        m = m.loc[:has_index[has_index].index.max()]

    indicators = build_indicators(m)
    meta = {
        "ratio_colombia_api2": ratio_api2,
        "ratio_colombia_newcastle": ratio_nc,
        "ratio_api2_calibrado": bool((trade_fob * m["carbon_api2_cif_ara"].reindex(trade_fob.index)).notna().any()),
        "ratio_newcastle_calibrado": bool((trade_fob * m["carbon_newcastle_fob"].reindex(trade_fob.index)).notna().any()),
        "factor_flete": scale,
        "ultimo_mes": m.index.max().strftime("%Y-%m") if not m.empty else None,
        "fuente_carbon_fob": m["carbon_col_fob_fuente"].iloc[-1] if not m.empty else None,
        "ultimo_dato_por_serie": {c: w[c].last_valid_index().strftime("%Y-%m")
                                  for c in w.columns if w[c].notna().any()},
    }
    return Result(m, indicators, build_alerts(m, indicators, cfg), meta)


def build_indicators(m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col, label in {**KEY_SERIES, **RATIOS}.items():
        if col not in m.columns:
            continue
        s = pd.to_numeric(m[col], errors="coerce").dropna()
        if s.empty:
            continue
        last, date = s.iloc[-1], s.index[-1]

        def pct(periods: int) -> float | None:
            if col.startswith("spread"):       # un diferencial puede cruzar cero: el % no tiene sentido
                return None
            ref = s.shift(periods).iloc[-1] if len(s) > periods else np.nan
            return float((last / ref - 1) * 100) if pd.notna(ref) and ref else None

        tail = s.tail(24)
        z = float((last - tail.mean()) / tail.std()) if len(tail) >= 6 and tail.std() > 0 else None
        rows.append({
            "serie": col, "descripcion": label, "mes": date.strftime("%Y-%m"), "ultimo": float(last),
            "var_mensual_pct": pct(1), "var_anual_pct": pct(12),
            "prom_3m": float(s.tail(3).mean()), "prom_12m": float(s.tail(12).mean()),
            "min_24m": float(tail.min()), "max_24m": float(tail.max()), "zscore_24m": z,
        })
    return pd.DataFrame(rows)


def build_alerts(m: pd.DataFrame, ind: pd.DataFrame, cfg: dict) -> list[str]:
    acfg = cfg["alertas"]
    alerts = []
    watched = ["carbon_api2_cif_ara", "carbon_newcastle_fob", "carbon_col_fob", "carbon_landed",
               "carbon_flete", "fx_pen_usd", "brent"]
    for _, r in ind[ind["serie"].isin(watched)].iterrows():
        if r["var_mensual_pct"] is not None and abs(r["var_mensual_pct"]) >= acfg["variacion_mensual_pct"]:
            arrow = "▲" if r["var_mensual_pct"] > 0 else "▼"
            alerts.append(f"{arrow} {r['descripcion']}: {r['var_mensual_pct']:+.1f}% m/m ({r['ultimo']:,.2f}, {r['mes']})")
        if r["zscore_24m"] is not None and abs(r["zscore_24m"]) >= acfg["zscore"]:
            alerts.append(f"⚠ {r['descripcion']} fuera de rango histórico: z={r['zscore_24m']:+.1f} vs 24 meses")
    budget = cfg["carbon"]["presupuesto_landed_usd_t"]
    s = m["carbon_landed"].dropna()
    if budget and not s.empty:
        limit = budget * (1 + acfg["margen_presupuesto_pct"] / 100)
        if s.iloc[-1] > limit:
            alerts.append(f"💰 Carbón puesto en planta {s.iloc[-1]:,.1f} USD/t supera el presupuesto de "
                          f"{budget:,.1f} USD/t ({(s.iloc[-1] / budget - 1) * 100:+.1f}%)")
    return alerts
