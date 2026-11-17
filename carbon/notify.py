"""Notificación opcional por Telegram (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)."""
from __future__ import annotations

import logging
import os

import pandas as pd

from .analytics import Result
from .sources.base import session

log = logging.getLogger(__name__)


def summary_text(res: Result, report_url: str | None = None) -> str:
    lines = [f"📊 Monitor carbón Conchán — datos a {res.meta.get('ultimo_mes', '—')}"]
    if not res.monthly.empty:
        last = res.monthly.iloc[-1]
        for label, col in [("Carbón puesto en planta", "carbon_landed"),
                           ("Colombia FOB", "carbon_col_fob"),
                           ("API2 CIF ARA", "carbon_api2_cif_ara"),
                           ("Newcastle FOB", "carbon_newcastle_fob")]:
            v = last.get(col)
            if v is not None and pd.notna(v):
                lines.append(f"• {label}: {v:,.1f} USD/t")
    lines += ["", "Alertas:"] + [f"• {a}" for a in res.alerts] if res.alerts else ["Sin alertas."]
    if report_url:
        lines.append(f"\nReporte: {report_url}")
    return "\n".join(lines)


def telegram(res: Result, cfg: dict, report_url: str | None = None) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not cfg.get("notificaciones", {}).get("telegram") or not token or not chat:
        return
    try:
        r = session().post(f"https://api.telegram.org/bot{token}/sendMessage",
                           json={"chat_id": chat, "text": summary_text(res, report_url)[:4000]}, timeout=30)
        r.raise_for_status()
    except Exception as e:
        log.warning("No se pudo enviar el mensaje de Telegram: %s", e)
