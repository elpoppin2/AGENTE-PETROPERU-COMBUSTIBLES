"""Reporte Markdown + gráficos PNG (se renderiza directo en GitHub)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .analytics import KEY_SERIES, RATIOS, Result  # noqa: E402

FUENTES_LEGIBLES = {
    "manual_carbon_fob": "cotización propia",
    "co_exp_carbon_pe_fob_usd_t": "Comtrade: export. Colombia→Perú (FOB)",
    "co_exp_carbon_mundo_fob_usd_t": "Comtrade: export. Colombia→mundo (FOB)",
    "carbon_bm_colombia_fob": "Banco Mundial: Coal, Colombian",
    "nowcast_api2": "estimado: API2 × ratio Colombia/API2",
    "nowcast_newcastle": "estimado: Newcastle × ratio Colombia/Newcastle",
}
THREE_DECIMALS = ("ratio", "paridad", "flete_share", "fx_pen", "carbon_vs", "share")


def _fmt(v, nd=2, pct=False):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%" if pct else f"{v:,.{nd}f}"


def _table(ind: pd.DataFrame, series: dict) -> str:
    sub = ind[ind["serie"].isin(series)]
    if sub.empty:
        return "_Sin datos._\n"
    lines = ["| Indicador | Mes | Último | m/m | a/a | Prom. 3m | Prom. 12m | Rango 24m | z 24m |",
             "|---|---|---:|---:|---:|---:|---:|---|---:|"]
    for _, r in sub.iterrows():
        nd = 3 if r["serie"].startswith(THREE_DECIMALS) else 2
        lines.append(
            f"| {r['descripcion']} | {r['mes']} | **{_fmt(r['ultimo'], nd)}** | {_fmt(r['var_mensual_pct'], pct=True)} "
            f"| {_fmt(r['var_anual_pct'], pct=True)} | {_fmt(r['prom_3m'], nd)} | {_fmt(r['prom_12m'], nd)} "
            f"| {_fmt(r['min_24m'], nd)} – {_fmt(r['max_24m'], nd)} | {_fmt(r['zscore_24m'], 1)} |"
        )
    return "\n".join(lines) + "\n"


def charts(res: Result, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    m = res.monthly.tail(36)
    if m.empty:
        return []
    specs = [
        ("indices.png", "Índices internacionales de carbón (USD/t)",
         {"carbon_api2_cif_ara": "API2 CIF Rotterdam", "carbon_newcastle_fob": "Newcastle FOB",
          "carbon_api4_fob_rb": "API4 FOB Richards Bay", "carbon_col_fob": "Colombia FOB (spec)"}),
        ("carbon.png", "Carbón colombiano → Conchán (USD/t)",
         {"carbon_col_fob": "Colombia FOB (spec)", "carbon_cif": "CIF Conchán", "carbon_landed": "Puesto en planta",
          "carbon_cif_comtrade": "CIF Comtrade Perú (Colombia)", "pe_imp_carbon_mundo_cif": "CIF Comtrade Perú (todo origen)"}),
        ("flete.png", "Flete estimado Colombia→Conchán (USD/t) y Brent (USD/bbl)",
         {"carbon_flete": "Flete", "brent": "Brent"}),
        ("ratios.png", "Ratios Colombia FOB / índice",
         {"ratio_col_api2": "Colombia/API2", "ratio_col_newcastle": "Colombia/Newcastle",
          "paridad_carbon_brent": "Carbón/Brent (energía)"}),
    ]
    files = []
    for fname, title, cols in specs:
        fig, ax = plt.subplots(figsize=(9, 4))
        plotted = False
        for col, label in cols.items():
            if col in m.columns and m[col].notna().any():
                s = m[col].dropna()
                style = "o" if "comtrade" in col or col.startswith("pe_imp") else "-"
                ax.plot(s.index, s.values, style, label=label, markersize=3, linewidth=1.8)
                plotted = True
        if not plotted:
            plt.close(fig)
            continue
        ax.set_title(title, fontsize=11, loc="left")
        ax.grid(alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(fontsize=8, frameon=False, ncol=3)
        fig.tight_layout()
        fig.savefig(out_dir / fname, dpi=120)
        plt.close(fig)
        files.append(fname)
    return files


def _status_section(status: list[dict]) -> str:
    lines = ["## Estado de las fuentes (última descarga)\n", "| Fuente | Observaciones | Estado |", "|---|---:|---|"]
    for s in status:
        if s["avisos"]:
            state = "⚠ " + "<br>".join(a.replace("|", "/")[:220] for a in s["avisos"][:3])
        else:
            state = "✅ OK" if s["observaciones"] else "— sin archivos"
        lines.append(f"| {s['fuente']} | {s['observaciones']} | {state} |")
    return "\n".join(lines) + "\n"


def render(res: Result, cfg: dict, commentary: str | None, chart_files: list[str],
           status: list[dict] | None = None) -> str:
    today = date.today().isoformat()
    meta = res.meta
    out = ["# Monitor de carbón importado — Puerto Conchán\n",
           f"_Actualizado: {today} · Último mes con índice de referencia: {meta.get('ultimo_mes', '—')}_\n"]

    out.append("## Alertas\n")
    out.append("\n".join(f"- {a}" for a in res.alerts) + "\n" if res.alerts else "Sin alertas.\n")

    if commentary:
        out.append("## Análisis del agente\n")
        out.append(commentary.strip() + "\n")

    if res.monthly.empty:
        return "\n".join(out)

    last = res.monthly.iloc[-1]
    ccfg = cfg["carbon"]
    out.append("## Carbón Colombia puesto en planta\n")
    out.append("| Concepto | Valor |\n|---|---:|")
    for label, col, nd in [
        ("FOB Colombia, spec contrato (USD/t)", "carbon_col_fob", 2),
        ("Flete Colombia→Conchán (USD/t)", "carbon_flete", 2),
        ("CIF Conchán (USD/t)", "carbon_cif", 2),
        ("Puesto en planta (USD/t)", "carbon_landed", 2),
        ("Puesto en planta (PEN/t)", "carbon_landed_pen", 2),
        ("Puesto en planta (USD/GJ)", "carbon_usd_gj", 2),
        ("Puesto en planta (USD/Gcal)", "carbon_usd_gcal", 2),
        ("IGV a pagar en aduana, crédito fiscal (USD/t)", "carbon_igv_caja_usd_t", 2),
        ("Costo anual estimado (MUSD)", "carbon_impacto_anual_musd", 1),
    ]:
        out.append(f"| {label} | {_fmt(last.get(col), nd)} |")
    out.append(f"| Presupuesto puesto en planta (USD/t) | {_fmt(ccfg['presupuesto_landed_usd_t'])} |")
    fuente = meta.get("fuente_carbon_fob")
    out.append(f"| Fuente del FOB | {FUENTES_LEGIBLES.get(fuente, fuente)} |\n")

    def calib(flag):
        return "calibrado con Comtrade" if flag else "valor por defecto"

    out.append(f"Spec {ccfg['poder_calorifico_spec_kcal_kg']} kcal/kg NAR. "
               f"Ratio Colombia/API2: {meta['ratio_colombia_api2']:.3f} ({calib(meta['ratio_api2_calibrado'])}); "
               f"Colombia/Newcastle: {meta['ratio_colombia_newcastle']:.3f} ({calib(meta['ratio_newcastle_calibrado'])}). "
               f"Factor de calibración del flete: {meta['factor_flete']:.2f}.\n")

    out.append("## Precios y costos\n")
    out.append(_table(res.indicators, KEY_SERIES))
    out.append("## Ratios\n")
    out.append(_table(res.indicators, RATIOS))

    if chart_files:
        out.append("## Gráficos (últimos 36 meses)\n")
        out += [f"![{f}](graficos/{f})\n" for f in chart_files]

    if status:
        out.append(_status_section(status))
    out.append("## Frescura de datos por serie\n")
    out.append("| Serie | Último mes |\n|---|---|")
    out += [f"| `{k}` | {v} |" for k, v in sorted(meta.get("ultimo_dato_por_serie", {}).items())]
    out.append("\n---\n_Fuentes: FRED/IMF, Banco Mundial (Pink Sheet), BCRP, UN Comtrade, CSV de Investing.com "
               "y cotizaciones propias. Los valores modelados son estimaciones; ver README para la metodología._\n")
    return "\n".join(out)
