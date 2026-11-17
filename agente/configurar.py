"""Crea (la primera vez) o actualiza el agente de consultas en Claude Managed Agents.

Guarda los identificadores en agente/ids.json; consultar.py los lee en cada pregunta.
Se ejecuta desde Actions: "Configurar agente de consultas" (necesita ANTHROPIC_API_KEY).

    python agente/configurar.py
"""
from __future__ import annotations

import json
from pathlib import Path

import anthropic

AQUI = Path(__file__).resolve().parent
IDS = AQUI / "ids.json"

NOMBRE = "Consultas Sourcing Internacional"
MODELO = "claude-opus-5-5"
# Herramientas del contenedor (bash, archivos) para calcular sobre los CSV; sin internet.
HERRAMIENTAS = [{
    "type": "agent_toolset_20260401",
    "default_config": {"enabled": True, "permission_policy": {"type": "auto"}},
    "configs": [
        {"name": "web_fetch", "enabled": False},
        {"name": "web_search", "enabled": False},
    ],
}]


def main() -> None:
    client = anthropic.Anthropic()
    sistema = (AQUI / "instrucciones.md").read_text(encoding="utf-8")
    ids = json.loads(IDS.read_text(encoding="utf-8")) if IDS.exists() else {}

    if not ids.get("environment_id"):
        entorno = client.beta.environments.create(
            name="consultas-sourcing",
            # Sin acceso a internet salvo los registros de paquetes (para instalar pandas).
            config={"type": "cloud", "networking": {"type": "limited", "allow_package_managers": True}},
        )
        ids["environment_id"] = entorno.id
        print("Entorno creado:", entorno.id)

    if ids.get("agent_id"):
        agente = client.beta.agents.update(ids["agent_id"], name=NOMBRE, model=MODELO, system=sistema, tools=HERRAMIENTAS)
        print("Agente actualizado:", agente.id, "versión", agente.version)
    else:
        agente = client.beta.agents.create(name=NOMBRE, model=MODELO, system=sistema, tools=HERRAMIENTAS)
        print("Agente creado:", agente.id, "versión", agente.version)
    ids.update(agent_id=agente.id, agent_version=agente.version)
    IDS.write_text(json.dumps(ids, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
