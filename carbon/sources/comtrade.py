"""UN Comtrade — valores unitarios de comercio exterior (USD/t) por flujo.

Se usan "espejos" del mismo flujo físico:
  * Perú importa carbón desde Colombia -> valor CIF Callao/Conchán
  * Colombia exporta carbón a Perú     -> valor FOB en origen
La diferencia CIF - FOB es el flete + seguro implícito de la ruta.

Sin clave se usa el endpoint público "preview" (un mes por consulta, más
lento pero suficiente); con COMTRADE_API_KEY (gratis en
comtradedeveloper.un.org) se usa el endpoint completo, 12 meses por consulta. Los datos llegan con 2-4 meses de rezago.
"""
from __future__ import annotations

import logging
import os
import time

import pandas as pd

from .base import frame, session

log = logging.getLogger(__name__)

PREVIEW_URL = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
DATA_URL = "https://comtradeapi.un.org/data/v1/get/C/M/HS"

PERU, COLOMBIA, WORLD = 604, 170, 0

# serie base -> parámetros. Para cada consulta se guardan dos series:
#   <serie>_usd_t  (valor unitario)  y  <serie>_vol_t  (toneladas)
QUERIES = {
    "pe_imp_carbon_col_cif": dict(reporter=PERU, partner=COLOMBIA, cmd="270112", flow="M"),
    "co_exp_carbon_pe_fob": dict(reporter=COLOMBIA, partner=PERU, cmd="270112", flow="X"),
    "co_exp_carbon_mundo_fob": dict(reporter=COLOMBIA, partner=WORLD, cmd="270112", flow="X"),
    "pe_imp_carbon_mundo_cif": dict(reporter=PERU, partner=WORLD, cmd="270112", flow="M"),
}


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def parse_records(records: list[dict], serie: str, flow: str) -> pd.DataFrame:
    """Agrega registros Comtrade por periodo -> valor unitario y volumen."""
    # Si vienen desagregados por aduana/modo de transporte, quedarse con totales.
    totals = [r for r in records
              if str(r.get("customsCode", "C00")) == "C00"
              and int(r.get("motCode", 0) or 0) == 0
              and int(r.get("partner2Code", 0) or 0) == 0]
    records = totals or records

    agg: dict[str, list[float]] = {}
    for r in records:
        value_keys = ("cifvalue", "primaryValue") if flow == "M" else ("fobvalue", "primaryValue")
        value = next((v for k in value_keys if (v := _num(r.get(k))) is not None), None)
        weight = _num(r.get("netWgt"))
        if weight is None and int(r.get("qtyUnitCode", -1) or -1) == 8:  # 8 = kg
            weight = _num(r.get("qty"))
        if value is None or weight is None:
            continue
        acc = agg.setdefault(str(r["period"]), [0.0, 0.0])
        acc[0] += value
        acc[1] += weight

    rows = []
    fuente = f"UN Comtrade ({'CIF' if flow == 'M' else 'FOB'})"
    for period, (value, kg) in sorted(agg.items()):
        fecha = pd.Timestamp(year=int(period[:4]), month=int(period[4:6]), day=1)
        tons = kg / 1000
        rows.append({"fecha": fecha, "serie": f"{serie}_usd_t", "valor": value / tons,
                     "unidad": "USD/t", "fuente": fuente})
        rows.append({"fecha": fecha, "serie": f"{serie}_vol_t", "valor": tons,
                     "unidad": "t", "fuente": fuente})
    return frame(rows)


def _periods(months: int) -> list[str]:
    end = pd.Timestamp.today().to_period("M") - 1
    return [str(p).replace("-", "") for p in pd.period_range(end=end, periods=months, freq="M")]


def fetch(months: int = 24) -> pd.DataFrame:
    s = session()
    key = os.environ.get("COMTRADE_API_KEY")
    url = DATA_URL if key else PREVIEW_URL
    if key:
        s.headers["Ocp-Apim-Subscription-Key"] = key
    periods = _periods(months)
    size = 12 if key else 1          # el endpoint público "preview" acepta sólo 1 periodo por consulta
    chunks = [periods[i:i + size] for i in range(0, len(periods), size)]
    out = []
    for serie, q in QUERIES.items():
        records: list[dict] = []
        r = None
        for chunk in chunks:
            params = {
                "reporterCode": q["reporter"], "partnerCode": q["partner"], "cmdCode": q["cmd"],
                "flowCode": q["flow"], "period": ",".join(chunk),
                "customsCode": "C00", "motCode": 0, "partner2Code": 0, "includeDesc": "false",
            }
            try:
                r = s.get(url, params=params, timeout=90)
                r.raise_for_status()
                payload = r.json()
                if not payload.get("data") and payload.get("error"):
                    log.warning("Comtrade %s %s: %s", serie, chunk[0], str(payload["error"])[:200])
                records += payload.get("data") or []
            except Exception as e:
                log.warning("Comtrade %s %s falló: %s", serie, chunk[0], e)
            time.sleep(1.5)   # respetar el límite de la API pública
        if not records:
            log.warning("Comtrade %s: sin registros (HTTP %s) %s", serie,
                        getattr(r, "status_code", "?"), getattr(r, "text", "")[:200].replace("\n", " "))
        out.append(parse_records(records, serie, q["flow"]))
    return pd.concat(out, ignore_index=True) if out else frame([])
