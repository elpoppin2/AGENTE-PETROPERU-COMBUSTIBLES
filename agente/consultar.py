"""Responde una consulta con el agente de Claude Managed Agents y deja la respuesta en un archivo.

    PREGUNTA="¿Cuál fue el promedio del B5 S-50 en Conchán en octubre?" python agente/consultar.py respuesta.md

Cada consulta abre una sesión con el repositorio montado en /workspace/repo y un tope de gasto
(TOPE_USD). Si el agente pide permiso para una acción, se le niega: nadie está mirando la sesión.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import anthropic

AQUI = Path(__file__).resolve().parent
REPO_URL = "https://github.com/elpoppin2/AGENTE-PETROPERU-COMBUSTIBLES"
TOPE_USD = "100"            # centavos de dólar: "100" = US$ 1.00 por consulta como máximo
LIMITE_S = 12 * 60          # tiempo máximo de espera por la respuesta


def responder(pregunta: str) -> str:
    ids = json.loads((AQUI / "ids.json").read_text(encoding="utf-8"))
    client = anthropic.Anthropic()
    sesion = client.beta.sessions.create(
        agent={"type": "agent", "id": ids["agent_id"], "version": ids["agent_version"]},
        environment_id=ids["environment_id"],
        title=pregunta[:80],
        budget={"type": "limit", "max_list_cost": {"amount": TOPE_USD, "currency": "USD"}},
        resources=[{
            "type": "github_repository", "url": REPO_URL, "mount_path": "/workspace/repo",
            "authorization_token": os.environ["GITHUB_TOKEN"], "checkout": {"type": "branch", "name": "main"},
        }],
    )
    print("Sesión:", sesion.id, file=sys.stderr)
    mensajes: list[str] = []
    motivo = None
    limite = time.monotonic() + LIMITE_S
    with client.beta.sessions.events.stream(session_id=sesion.id) as stream:
        client.beta.sessions.events.send(session_id=sesion.id, events=[
            {"type": "user.message", "content": [{"type": "text", "text": pregunta}]},
        ])
        for evento in stream:
            if evento.type == "agent.message":
                texto = "".join(b.text for b in evento.content if b.type == "text").strip()
                if texto:
                    mensajes.append(texto)
            elif evento.type in ("agent.tool_use", "agent.mcp_tool_use") and getattr(evento, "evaluated_permission", None) == "ask":
                client.beta.sessions.events.send(session_id=sesion.id, events=[
                    {"type": "user.tool_confirmation", "tool_use_id": evento.id, "result": "deny"},
                ])
            elif evento.type == "session.status_idle":
                if evento.stop_reason.type != "requires_action":
                    motivo = evento.stop_reason.type
                    break
            elif evento.type == "session.status_terminated":
                motivo = "terminated"
                break
            if time.monotonic() > limite:
                client.beta.sessions.events.send(session_id=sesion.id, events=[{"type": "user.interrupt"}])
                motivo = "tiempo"
                break
    if motivo == "budget_reached":
        aviso = f"\n\n_La consulta llegó al tope de gasto (US$ {int(TOPE_USD) / 100:.2f}); la respuesta puede estar incompleta._"
    elif motivo == "tiempo":
        aviso = "\n\n_La consulta superó el tiempo máximo de espera; la respuesta puede estar incompleta._"
    else:
        aviso = ""
    if not mensajes:
        return "No pude obtener una respuesta del agente. Intenta reformular la consulta." + aviso
    return mensajes[-1] + aviso


def main() -> int:
    pregunta = os.environ.get("PREGUNTA", "").strip()
    if not pregunta:
        print("Falta la pregunta (variable PREGUNTA).", file=sys.stderr)
        return 1
    respuesta = responder(pregunta)
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if destino:
        destino.write_text(respuesta + "\n", encoding="utf-8")
    print(respuesta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
