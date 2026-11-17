"""Precio del carbón colombiano FOB y CFR Conchán (FOB + flete), ratios e indicadores.

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
    "carbon_cfr": "CFR Conchán (USD/t)",
    "carbon_cfr_pen": "CFR Conchán (PEN/t)",
    "carbon_cfr_comparable": "CFR comparable con ofertas, con atenuantes (USD/t)",
    "carbon_cif_comtrade": "CIF Perú desde Colombia — Comtrade (USD/t)",
    "pe_imp_carbon_mundo_cif": "CIF Perú desde todo origen — Comtrade (USD/t)",
    "escoria_fob": "Escoria FOB Japón (USD/t)",
    "escoria_flete": "Flete Japón→Conchán (USD/t)",
    "escoria_cfr": "Escoria CFR Conchán (USD/t)",
    "escoria_cfr_pen": "Escoria CFR Conchán (PEN/t)",
    "escoria_cif_comtrade": "Escoria CIF Perú desde Japón — Comtrade (USD/t)",
    "brent": "Brent (USD/bbl)",
    "fx_pen_usd": "Tipo de cambio (PEN/USD)",
    "fx_cop_usd": "Tipo de cambio (COP/USD)",
}

RATIOS = {
    "ratio_col_api2": "Colombia FOB / API2",
    "ratio_col_newcastle": "Colombia FOB / Newcastle",
    "spread_api2_newcastle": "API2 − Newcastle (USD/t, Atlántico vs Pacífico)",
    "paridad_carbon_brent": "Carbón vs Brent (USD/GJ ÷ USD/GJ)",
    "flete_share_carbon": "Flete / CFR",
    "carbon_vs_cif_comtrade": "CFR modelo / CIF Comtrade Perú",
    "share_colombia_import_pe": "Participación de Colombia en importaciones de Perú (t)",
    "flete_share_escoria": "Flete / CFR escoria",
    "escoria_vs_cif_comtrade": "Escoria CFR modelo / CIF Comtrade Perú",
}


def _anual(w: pd.DataFrame, name: str) -> pd.Series:
    """Una serie anual (dato el 1 de enero) repetida en los 12 meses de su año."""
    s = _col(w, name)
    return s.groupby(s.index.year).transform("max")


@dataclass
class Result:
    monthly: pd.DataFrame
    indicators: pd.DataFrame
    alerts: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    simulacion: pd.DataFrame = field(default_factory=pd.DataFrame)


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
    ccfg = cfg["carbon"]
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
    # El ratio Colombia/índice se calibra con lo que Colombia exporta a Perú (carbón de alto poder
    # calorífico, más caro que el promedio de sus exportaciones); se asume que ese carbón ya está
    # en `poder_calorifico_comercio_pe_kcal_kg`. Con menos de 3 datos se usa el comercio con el mundo,
    # en la base de los índices.
    cv_ref, cv_spec = ccfg["poder_calorifico_ref_kcal_kg"], ccfg["poder_calorifico_spec_kcal_kg"]
    pe_fob = _col(w, "co_exp_carbon_pe_fob_usd_t")
    if pe_fob.notna().sum() >= 3:
        trade_fob, cv_trade, calibracion = pe_fob, ccfg.get("poder_calorifico_comercio_pe_kcal_kg", cv_ref), "colombia_peru"
        fuentes_obs = ["co_exp_carbon_pe_fob_usd_t"]
    else:
        trade_fob, _ = _first(w, ["co_exp_carbon_pe_fob_usd_t", "co_exp_carbon_mundo_fob_usd_t", "carbon_bm_colombia_fob"])
        cv_trade, calibracion = cv_ref, "colombia_mundo"
        fuentes_obs = ["co_exp_carbon_pe_fob_usd_t", "co_exp_carbon_mundo_fob_usd_t", "carbon_bm_colombia_fob"]
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

    # Cada fuente se lleva al poder calorífico de las plantas: la cotización propia viene en la base de
    # los índices (manual.py la normaliza) y el comercio y el nowcast, en la base del comercio usado.
    manual = _col(w, "manual_carbon_fob") * cv_spec / cv_ref
    observed, src = _first(w, fuentes_obs)
    fob = manual.combine_first(observed * cv_spec / cv_trade).combine_first(nowcast * cv_spec / cv_trade)
    m["carbon_col_fob"] = fob
    m["carbon_col_fob_fuente"] = pd.Series(np.where(manual.notna(), "manual_carbon_fob", np.where(observed.notna(), src, now_src)), index=w.index)
    fob_ref = fob * cv_trade / cv_spec     # en la base del comercio, para los ratios
    m["ratio_col_api2"] = fob_ref / m["carbon_api2_cif_ara"]
    m["ratio_col_newcastle"] = fob_ref / m["carbon_newcastle_fob"]
    m["spread_api2_newcastle"] = m["carbon_api2_cif_ara"] - m["carbon_newcastle_fob"]

    # --- Flete y CFR Conchán (FOB + flete) ------------------------------------------
    implied = _col(w, "pe_imp_carbon_col_cif_usd_t") - _col(w, "co_exp_carbon_pe_fob_usd_t")
    m["carbon_flete"], scale = _freight(m["brent"], ccfg["flete"], implied, _col(w, "manual_flete_carbon"))
    # Una cotización CFR manda; una CIF se toma como CFR (el seguro es ~0.1%).
    m["carbon_cfr"] = (_col(w, "manual_carbon_cfr").combine_first(_col(w, "manual_carbon_cif"))
                       .combine_first(m["carbon_col_fob"] + m["carbon_flete"]))
    m["carbon_cfr_pen"] = m["carbon_cfr"] * m["fx_pen_usd"]
    # CFR comparable con ofertas: el CFR más los atenuantes que suelen traer las ofertas
    # (granulometría fina, calidad, costo del crédito del plazo de pago). Supuestos en config.
    at = ccfg.get("atenuantes") or {}
    m["carbon_prima_granulometria"] = float(at.get("granulometria_usd_t", 0))
    m["carbon_prima_calidad"] = float(at.get("calidad_usd_t", 0))
    base = m["carbon_cfr"] + m["carbon_prima_granulometria"] + m["carbon_prima_calidad"]
    m["carbon_costo_credito"] = base * float(at.get("tasa_anual_pct", 0)) / 100 * float(at.get("plazo_pago_dias", 0)) / 365
    m["carbon_cfr_comparable"] = base + m["carbon_costo_credito"]

    gj_per_t = ccfg["poder_calorifico_spec_kcal_kg"] * 1000 * KCAL_TO_GJ
    m["paridad_carbon_brent"] = (m["carbon_col_fob"] / gj_per_t) / (m["brent"] / GJ_PER_BBL)
    m["flete_share_carbon"] = m["carbon_flete"] / m["carbon_cfr"]

    # --- Mercado peruano de carbón importado (Comtrade) ------------------------------
    m["carbon_cif_comtrade"] = _col(w, "pe_imp_carbon_col_cif_usd_t")
    m["carbon_vs_cif_comtrade"] = m["carbon_cfr"] / m["carbon_cif_comtrade"]
    m["pe_imp_carbon_mundo_cif"] = _col(w, "pe_imp_carbon_mundo_cif_usd_t")
    m["pe_imp_carbon_col_vol_t"] = _col(w, "pe_imp_carbon_col_cif_vol_t")
    m["pe_imp_carbon_mundo_vol_t"] = _col(w, "pe_imp_carbon_mundo_cif_vol_t")
    m["share_colombia_import_pe"] = m["pe_imp_carbon_col_vol_t"] / m["pe_imp_carbon_mundo_vol_t"]

    # --- Escoria granulada de Japón (GBFS): FOB Japón + flete = CFR Conchán -------
    # No hay índice de mercado: el FOB es la cotización, o el valor unitario de las
    # exportaciones de Japón (Comtrade, mensual o anual); si falta, el último dato.
    ecfg = cfg.get("escoria")
    if ecfg:
        obs_e, src_e = _first(w, ["manual_escoria_fob", "jp_exp_escoria_pe_fob_usd_t", "jp_exp_escoria_mundo_fob_usd_t"])
        anual_fob = _anual(w, "jp_exp_escoria_pe_fob_anual_usd_t")
        fob_e = obs_e.combine_first(anual_fob)
        src_e = src_e.where(obs_e.notna(), np.where(anual_fob.notna(), "comtrade_anual", None))
        llevado = fob_e.ffill()
        src_e = src_e.where(fob_e.notna(), np.where(llevado.notna(), "ultimo_dato", "supuesto"))
        m["escoria_fob"] = llevado.fillna(ecfg["fob_default_usd_t"])
        m["escoria_fob_fuente"] = src_e
        cif_jp = _col(w, "pe_imp_escoria_jpn_cif_usd_t").combine_first(_anual(w, "pe_imp_escoria_jpn_cif_anual_usd_t"))
        fob_jp = _col(w, "jp_exp_escoria_pe_fob_usd_t").combine_first(anual_fob)
        m["escoria_flete"], scale_e = _freight(m["brent"], ecfg["flete"], cif_jp - fob_jp, _col(w, "manual_flete_escoria"))
        m["escoria_cfr"] = (_col(w, "manual_escoria_cfr").combine_first(_col(w, "manual_escoria_cif"))
                            .combine_first(m["escoria_fob"] + m["escoria_flete"]))
        m["escoria_cfr_pen"] = m["escoria_cfr"] * m["fx_pen_usd"]
        m["escoria_cif_comtrade"] = cif_jp
        m["flete_share_escoria"] = m["escoria_flete"] / m["escoria_cfr"]
        m["escoria_vs_cif_comtrade"] = m["escoria_cfr"] / cif_jp
        m["pe_imp_escoria_jpn_vol_t"] = _col(w, "pe_imp_escoria_jpn_cif_vol_t").combine_first(_anual(w, "pe_imp_escoria_jpn_cif_anual_vol_t"))

    # Recorta meses finales sin índice de referencia (aún no publicados), salvo que
    # haya una cotización propia de ese mes.
    cotizado = pd.concat([_col(w, c) for c in ("manual_carbon_fob", "manual_carbon_cfr", "manual_carbon_cif",
                                                "manual_escoria_fob", "manual_escoria_cfr", "manual_escoria_cif")], axis=1)
    has_index = m[["carbon_newcastle_fob", "carbon_api2_cif_ara"]].notna().any(axis=1) | cotizado.notna().any(axis=1)
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
        "calibracion_ratio": calibracion,
        "fuente_escoria_fob": m["escoria_fob_fuente"].iloc[-1] if ecfg and not m.empty else None,
        "ultimo_dato_por_serie": {c: w[c].last_valid_index().strftime("%Y-%m")
                                  for c in w.columns if w[c].notna().any()},
    }
    # Simulación a 12 meses y conveniencia de compra (ver simulacion.py)
    from . import simulacion
    sim = simulacion.simular_todo(m)
    conv = {mat: simulacion.conveniencia(m, sim, mat) for mat in simulacion.MATERIALES if f"{mat}_cfr" in m}
    meta["conveniencia"] = conv
    alertas = {"carbon": build_alerts(m, indicators, cfg) + simulacion.alerta_conveniencia(conv.get("carbon"))}
    if ecfg:
        alertas["escoria"] = build_alerts(m, indicators, cfg, "escoria") + simulacion.alerta_conveniencia(conv.get("escoria"))
    meta["alertas"] = alertas
    return Result(m, indicators, [a for lista in alertas.values() for a in lista], meta, sim)


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


def build_alerts(m: pd.DataFrame, ind: pd.DataFrame, cfg: dict, material: str = "carbon") -> list[str]:
    acfg = cfg["alertas"]
    alerts = []
    watched = (["escoria_fob", "escoria_flete", "escoria_cfr"] if material == "escoria" else
               ["carbon_api2_cif_ara", "carbon_newcastle_fob", "carbon_col_fob", "carbon_cfr",
                "carbon_flete", "fx_pen_usd", "brent"])
    for _, r in ind[ind["serie"].isin(watched)].iterrows():
        if r["var_mensual_pct"] is not None and abs(r["var_mensual_pct"]) >= acfg["variacion_mensual_pct"]:
            arrow = "▲" if r["var_mensual_pct"] > 0 else "▼"
            alerts.append(f"{arrow} {r['descripcion']}: {r['var_mensual_pct']:+.1f}% m/m ({r['ultimo']:,.2f}, {r['mes']})")
        if r["zscore_24m"] is not None and abs(r["zscore_24m"]) >= acfg["zscore"]:
            alerts.append(f"⚠ {r['descripcion']} fuera de rango histórico: z={r['zscore_24m']:+.1f} vs 24 meses")
    budget = cfg[material].get("presupuesto_cfr_usd_t")
    s = m[f"{material}_cfr"].dropna()
    if budget and not s.empty:
        limit = budget * (1 + acfg["margen_presupuesto_pct"] / 100)
        if s.iloc[-1] > limit:
            alerts.append(f"💰 {'Escoria' if material == 'escoria' else 'Carbón'} CFR Conchán {s.iloc[-1]:,.1f} USD/t supera la referencia de "
                          f"{budget:,.1f} USD/t ({(s.iloc[-1] / budget - 1) * 100:+.1f}%)")
    return alerts
