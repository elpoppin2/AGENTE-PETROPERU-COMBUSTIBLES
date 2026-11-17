"""CLI del monitor de carbón importado.

    python -m carbon update     # descarga fuentes públicas + manuales y actualiza el histórico
    python -m carbon report     # calcula ratios y genera el reporte
    python -m carbon all        # update + report + notificación
    python -m carbon enviar     # envía por correo el aviso de alertas nuevas (reportes/carbon/aviso.md)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import date

import pandas as pd

from . import analytics, notify, report, store
from .config import HIST_PATH, MANUAL_DIR, REPORTS_DIR, ROOT, load_config
from .sources import bcrp, comtrade, fred, investing, manual, worldbank

log = logging.getLogger("carbon")
STATUS_PATH = REPORTS_DIR / "estado_fuentes.json"
AVISO_PATH = REPORTS_DIR / "aviso.md"                     # último aviso de alertas nuevas
ENVIADAS_PATH = REPORTS_DIR / "alertas_enviadas.json"     # alertas ya avisadas (sin cifras)
URL_TABLERO = "https://elpoppin2.github.io/AGENTE-PETROPERU-COMBUSTIBLES/"
URL_REPO = "https://github.com/elpoppin2/AGENTE-PETROPERU-COMBUSTIBLES"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "setiembre", "octubre", "noviembre", "diciembre"]


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
        ("comtrade", lambda: comtrade.fetch(f.get("comtrade_meses", 24), anual_desde=int(start[:4]),
                                            estado=HIST_PATH.parent / "comtrade_consultas.json")),
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
    if f.get("manual", True):
        # data/carbon/manual es la fuente completa de las series manual_*: se reemplazan enteras,
        # así una cotización que se borra del CSV también sale del histórico.
        store.quitar_series(HIST_PATH, "manual_")
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
    if not res.simulacion.empty:
        res.simulacion.to_csv(REPORTS_DIR / "simulacion.csv", index=False, date_format="%Y-%m", float_format="%.4f")
    # Resumen para el tablero web (index.html): alertas y supuestos del último reporte.
    (REPORTS_DIR / "resumen.json").write_text(json.dumps({
        "actualizado": date.today().isoformat(),
        "ultimo_mes": res.meta.get("ultimo_mes"),
        "fuente_carbon_fob": res.meta.get("fuente_carbon_fob"),
        "alertas": res.meta.get("alertas", {}).get("carbon", res.alerts),
        "referencia_cfr_usd_t": cfg["carbon"].get("presupuesto_cfr_usd_t"),
        "kcal_spec": cfg["carbon"].get("poder_calorifico_spec_kcal_kg"),
        "puerto": cfg["destino"].get("puerto"),
        "conveniencia": res.meta.get("conveniencia", {}).get("carbon"),
        "escoria": {
            "fuente_fob": res.meta.get("fuente_escoria_fob"),
            "alertas": res.meta.get("alertas", {}).get("escoria", []),
            "referencia_cfr_usd_t": cfg.get("escoria", {}).get("presupuesto_cfr_usd_t"),
            "conveniencia": res.meta.get("conveniencia", {}).get("escoria"),
        },
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log.info("Reporte generado: %s (%d alertas)", REPORTS_DIR / "ultimo_reporte.md", len(res.alerts))
    return res


def _clave(alerta: str) -> str:
    """La alerta sin cifras: la misma alerta con otro valor no se vuelve a avisar."""
    return re.sub(r"[-+]?\d[\d.,]*", "#", alerta)


def _mes(fecha) -> str:
    return f"{MESES[fecha.month - 1]} {fecha.year}"


def aviso_alertas(res: analytics.Result) -> str | None:
    """Arma el aviso (Markdown) si hay alertas que no se habían avisado antes.

    Guarda las alertas vigentes en alertas_enviadas.json; una alerta que desaparece
    y vuelve a salir se avisa de nuevo.
    """
    previas = set(json.loads(ENVIADAS_PATH.read_text(encoding="utf-8"))) if ENVIADAS_PATH.exists() else set()
    actuales = {_clave(a): a for a in res.alerts}
    ENVIADAS_PATH.write_text(json.dumps(sorted(actuales), ensure_ascii=False, indent=1), encoding="utf-8")
    nuevas = [a for k, a in actuales.items() if k not in previas]
    if not nuevas or res.monthly.empty:
        return None
    last = res.monthly.iloc[-1]
    mes = _mes(res.monthly.index[-1])
    v = lambda c: last.get(c)
    por_material = res.meta.get("alertas") or {"carbon": res.alerts}
    materiales = {
        "carbon": ("Carbón bituminoso de Colombia", [("Precio FOB Colombia (material)", "carbon_col_fob"),
                   ("Flete marítimo", "carbon_flete"), ("**CFR Conchán**", "carbon_cfr")]),
        "escoria": ("Escoria granulada de Japón", [("Precio FOB Japón (material)", "escoria_fob"),
                    ("Flete marítimo", "escoria_flete"), ("**CFR Conchán**", "escoria_cfr")]),
    }
    cuerpo = [f"## Alertas de carbón y escoria, {mes}"]
    for clave, (nombre, filas) in materiales.items():
        lista = por_material.get(clave, [])
        nuevas_m = [a for a in lista if a in nuevas]
        if not nuevas_m:
            continue
        cuerpo += ["", f"### {nombre}", "", "**Nuevas:**", *[f"- {a}" for a in nuevas_m]]
        siguen = [a for a in lista if a not in nuevas_m]
        if siguen:
            cuerpo += ["", "**Siguen vigentes:**", *[f"- {a}" for a in siguen]]
        cuerpo += ["", f"Precio, {mes} (US$/t):", "", "| Concepto | US$/t |", "|---|---:|"]
        for etiqueta, col in filas:
            if v(col) is not None and pd.notna(v(col)):
                cifra = f"{v(col):,.2f}"
                cuerpo.append(f"| {etiqueta} | {'**' + cifra + '**' if etiqueta.startswith('**') else cifra} |")
        if clave == "carbon":
            indices = []
            for etiqueta, col in [("Newcastle FOB (Australia)", "carbon_newcastle_fob"), ("API4 FOB Richards Bay", "carbon_api4_fob_rb"),
                                  ("API2 CIF Rotterdam", "carbon_api2_cif_ara")]:
                s_ = res.monthly[col].dropna() if col in res.monthly else pd.Series(dtype=float)
                if not s_.empty:
                    indices.append(f"- {etiqueta}: US$ {s_.iloc[-1]:,.2f} ({_mes(s_.index[-1])})")
            if indices:
                cuerpo += ["", "Índices internacionales (último dato):", *indices]
    cuerpo += ["", f"[Ver el tablero]({URL_TABLERO}) · [Reporte completo]({URL_REPO}/blob/main/reportes/carbon/ultimo_reporte.md)"]
    afectados = [materiales[k][0].split(" de ")[0].lower() for k in materiales if any(a in nuevas for a in por_material.get(k, []))]
    titulo = f"Alertas de {' y '.join(afectados)}, {mes}: {len(nuevas)} {'nueva' if len(nuevas) == 1 else 'nuevas'}"
    AVISO_PATH.write_text(f"# {titulo}\n\n" + "\n".join(cuerpo) + "\n", encoding="utf-8")
    salida = os.environ.get("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a", encoding="utf-8") as f:
            f.write(f"aviso={AVISO_PATH}\ntitulo={titulo}\n")
    log.info("Aviso de %d alertas nuevas: %s", len(nuevas), AVISO_PATH)
    return titulo


def enviar_aviso(enlace: str | None = None) -> bool:
    """Envía reportes/carbon/aviso.md por correo (mismos destinatarios que los avisos del diésel)."""
    from agente_petroperu import enviar
    titulo, cuerpo = AVISO_PATH.read_text(encoding="utf-8").split("\n", 1)
    cuerpo = cuerpo.strip()
    if enlace:
        cuerpo += f"\n\n[Ver el aviso en GitHub]({enlace})"
    return enviar(titulo.lstrip("# ").strip(), cuerpo, titulo.lstrip("# ").strip())


def main() -> None:
    p = argparse.ArgumentParser(prog="carbon", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("comando", choices=["update", "report", "all", "enviar"])
    p.add_argument("--enlace", default=None, help="con enviar: enlace al aviso en GitHub")
    p.add_argument("--config", default=None, help="ruta alternativa a config.yaml")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config) if args.config else load_config()

    if args.comando == "enviar":
        raise SystemExit(0 if enviar_aviso(args.enlace) else 1)
    if args.comando in ("update", "all"):
        update(cfg)
    if args.comando in ("report", "all"):
        res = build_report(cfg)
        if args.comando == "all":
            aviso_alertas(res)
            notify.telegram(res, cfg, os.environ.get("REPORT_URL"))


if __name__ == "__main__":
    main()
