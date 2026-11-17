"""CLI del monitor de carbón importado.

    python -m carbon update     # descarga fuentes públicas + manuales y actualiza el histórico
    python -m carbon report     # calcula ratios y genera el reporte
    python -m carbon all        # update + report + notificación
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date

import pandas as pd

from . import analytics, notify, report, store
from .config import HIST_PATH, MANUAL_DIR, REPORTS_DIR, ROOT, load_config
from .sources import bcrp, comtrade, fred, investing, manual, worldbank

log = logging.getLogger("carbon")
STATUS_PATH = REPORTS_DIR / "estado_fuentes.json"


class _WarningCollector(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def update(cfg: dict) -> pd.DataFrame:
    f = cfg["fuentes"]
    start = f["inicio"]
    steps = [
        ("fred", lambda: fred.fetch(start)),
        ("banco_mundial", lambda: worldbank.fetch(start)),
        ("bcrp", lambda: bcrp.fetch(start)),
        ("comtrade", lambda: comtrade.fetch(f.get("comtrade_meses", 24))),
        ("investing", lambda: investing.fetch(ROOT / cfg["investing"]["carpeta"], cfg["investing"]["series"])),
        ("manual", lambda: manual.fetch(MANUAL_DIR, cfg)),
    ]
    frames, status = [], []
    for name, fn in steps:
        if not f.get(name, True):
            continue
        collector = _WarningCollector()
        log.addHandler(collector)
        try:
            df = fn()
        finally:
            log.removeHandler(collector)
        log.info("%-14s %5d observaciones", name, len(df))
        status.append({"fuente": name, "observaciones": len(df),
                       "series": sorted(df["serie"].unique().tolist()), "avisos": collector.messages[:8]})
        frames.append(df)
    REPORTS_DIR.mkdir(exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    new = pd.concat([d for d in frames if not d.empty], ignore_index=True) if any(
        not d.empty for d in frames) else pd.DataFrame(columns=store.COLUMNS)
    return store.upsert(HIST_PATH, new)


def build_report(cfg: dict) -> analytics.Result:
    res = analytics.compute(store.wide(store.load(HIST_PATH)), cfg)
    files = report.charts(res, REPORTS_DIR / "graficos")
    status = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else None
    md = report.render(res, cfg, None, files, status)
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "ultimo_reporte.md").write_text(md, encoding="utf-8")
    (REPORTS_DIR / "historial").mkdir(exist_ok=True)
    (REPORTS_DIR / "historial" / f"{date.today().isoformat()}.md").write_text(
        md.replace("](graficos/", "](../graficos/"), encoding="utf-8")
    if not res.monthly.empty:
        res.monthly.to_csv(REPORTS_DIR / "modelo_mensual.csv", date_format="%Y-%m", float_format="%.4f")
        res.indicators.to_csv(REPORTS_DIR / "indicadores.csv", index=False, float_format="%.4f")
    # Resumen para el tablero web (index.html): alertas y supuestos del último reporte.
    (REPORTS_DIR / "resumen.json").write_text(json.dumps({
        "actualizado": date.today().isoformat(),
        "ultimo_mes": res.meta.get("ultimo_mes"),
        "fuente_carbon_fob": res.meta.get("fuente_carbon_fob"),
        "alertas": res.alerts,
        "presupuesto_landed_usd_t": cfg["carbon"].get("presupuesto_landed_usd_t"),
        "kcal_spec": cfg["carbon"].get("poder_calorifico_spec_kcal_kg"),
        "puerto": cfg["destino"].get("puerto"),
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log.info("Reporte generado: %s (%d alertas)", REPORTS_DIR / "ultimo_reporte.md", len(res.alerts))
    return res


def main() -> None:
    p = argparse.ArgumentParser(prog="carbon", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("comando", choices=["update", "report", "all"])
    p.add_argument("--config", default=None, help="ruta alternativa a config.yaml")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config) if args.config else load_config()

    if args.comando in ("update", "all"):
        update(cfg)
    if args.comando in ("report", "all"):
        res = build_report(cfg)
        if args.comando == "all":
            notify.telegram(res, cfg, os.environ.get("REPORT_URL"))


if __name__ == "__main__":
    main()
