"""Agente analista: Claude redacta el comentario de mercado a partir de los
indicadores calculados y, si está habilitado, busca noticias públicas recientes
(carbón colombiano, API2/Newcastle, Canal de Panamá, fletes) con la herramienta de
búsqueda web.
"""
from __future__ import annotations

import json
import logging
import os

import anthropic

from .analytics import Result

log = logging.getLogger(__name__)

SYSTEM = """Eres analista de abastecimiento de una empresa peruana que importa carbón
térmico de Colombia por el Puerto Conchán (Lima), un insumo crítico de su operación.
Recibes indicadores mensuales calculados por un modelo: índices internacionales (API2
CIF Rotterdam, Newcastle, API4), FOB Colombia estimado u observado, flete, CIF, costo
puesto en planta, tipos de cambio, ratios y datos de importación de Perú (Comtrade).

Escribe en español, para gerencia de compras, un comentario breve en Markdown con:
1. **Lectura del mes**: qué se movió y por qué (2-4 viñetas, con cifras).
2. **Drivers a vigilar**: factores de mercado públicos y recientes (p. ej. demanda de
   Europa y Asia, diferencial API2-Newcastle, producción, regalías y logística en
   Colombia, restricciones del Canal de Panamá, fletes Supramax/Panamax, bunker, peso
   colombiano, sol peruano). Si buscas en la web, cita la fuente con enlace.
3. **Recomendación**: acción concreta de compra/cobertura/negociación para las próximas
   4-8 semanas, con su justificación.

Reglas: distingue datos observados de estimaciones del modelo (los campos *_fuente lo
indican). No inventes cifras que no estén en los datos o en una fuente citada. Si un
dato está desactualizado o es dudoso, dilo. Máximo ~350 palabras. Sin preámbulo."""


def _payload(res: Result) -> str:
    ind = res.indicators.round(4).to_dict(orient="records")
    recent = res.monthly.tail(6).round(3).reset_index()
    recent["fecha"] = recent["fecha"].dt.strftime("%Y-%m")
    return json.dumps({
        "indicadores": ind,
        "ultimos_6_meses": recent.to_dict(orient="records"),
        "alertas": res.alerts,
        "meta": res.meta,
    }, ensure_ascii=False, default=str)


def commentary(res: Result, cfg: dict) -> str | None:
    acfg = cfg.get("agente", {})
    if not acfg.get("habilitado") or res.monthly.empty:
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        log.info("ANTHROPIC_API_KEY no definida: se omite el análisis del agente.")
        return None

    client = anthropic.Anthropic()
    tools = []
    if acfg.get("busqueda_web"):
        tools.append({"type": "web_search_20260209", "name": "web_search",
                      "max_uses": acfg.get("max_busquedas", 6)})
    messages = [{"role": "user", "content": "Datos del monitor (JSON):\n" + _payload(res)}]

    try:
        for _ in range(5):   # pause_turn: la búsqueda web puede pausar el turno; se reanuda
            with client.beta.messages.stream(
                model=acfg.get("modelo", "claude-opus-5-5"),
                max_tokens=32000,
                system=SYSTEM,
                messages=messages,
                tools=tools,
                thinking={"type": "adaptive"},
                output_config={"effort": acfg.get("esfuerzo", "high")},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",   # si el modelo declina, el servidor reintenta con otro
            ) as stream:
                msg = stream.get_final_message()
            if msg.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": msg.content})
                continue
            break
    except anthropic.AuthenticationError:
        log.error("ANTHROPIC_API_KEY inválida.")
        return None
    except anthropic.RateLimitError:
        log.warning("Límite de tasa de la API de Claude; se omite el análisis esta vez.")
        return None
    except anthropic.APIStatusError as e:
        log.warning("Error de la API de Claude (%s): %s", e.status_code, e.message)
        return None
    except anthropic.APIConnectionError:
        log.warning("Sin conexión con la API de Claude.")
        return None

    if msg.stop_reason == "refusal":
        log.warning("El modelo declinó generar el comentario.")
        return None
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    return text or None
