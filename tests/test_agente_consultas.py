"""El agente de consultas: arma la sesión, niega permisos y devuelve el último mensaje."""
import importlib.util
import json
import sys
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _cargar(monkeypatch, eventos, enviados, creadas):
    class Bloque:
        def __init__(self, t): self.type, self.text = "text", t

    class Evento:
        def __init__(self, tipo, **kw): self.type = tipo; self.__dict__.update(kw)

    class Stream:
        def __enter__(self): return iter([Evento(t, **kw) for t, kw in eventos])
        def __exit__(self, *a): pass

    class Eventos:
        def stream(self, session_id): return Stream()
        def send(self, session_id, events): enviados.extend(events)

    class Sesiones:
        events = Eventos()
        def create(self, **kw):
            creadas.append(kw)
            return types.SimpleNamespace(id="sesn_1")

    falso = types.SimpleNamespace(Anthropic=lambda: types.SimpleNamespace(beta=types.SimpleNamespace(sessions=Sesiones())))
    monkeypatch.setitem(sys.modules, "anthropic", falso)
    spec = importlib.util.spec_from_file_location("consultar", RAIZ / "agente" / "consultar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, Bloque, Evento


def test_consulta_devuelve_el_ultimo_mensaje(monkeypatch, tmp_path):
    enviados, creadas = [], []
    eventos = []
    mod, Bloque, Evento = _cargar(monkeypatch, eventos, enviados, creadas)
    eventos += [
        ("agent.message", {"content": [Bloque("Voy a revisar los datos.")]}),
        ("agent.tool_use", {"id": "sevt_9", "evaluated_permission": "ask"}),
        ("agent.message", {"content": [Bloque("El promedio fue S/ 24.62.")]}),
        ("session.status_idle", {"stop_reason": types.SimpleNamespace(type="end_turn")}),
    ]
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps({"agent_id": "agent_1", "agent_version": 2, "environment_id": "env_1"}))
    monkeypatch.setattr(mod, "AQUI", tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert mod.responder("¿Promedio?") == "El promedio fue S/ 24.62."
    s = creadas[0]
    assert s["agent"] == {"type": "agent", "id": "agent_1", "version": 2} and s["budget"]["max_list_cost"]["currency"] == "USD"
    assert s["resources"][0]["type"] == "github_repository"
    assert enviados[0]["type"] == "user.message"
    assert {"type": "user.tool_confirmation", "tool_use_id": "sevt_9", "result": "deny"} in enviados


def test_consulta_avisa_si_llega_al_tope(monkeypatch, tmp_path):
    enviados, creadas, eventos = [], [], []
    mod, Bloque, Evento = _cargar(monkeypatch, eventos, enviados, creadas)
    eventos += [("agent.message", {"content": [Bloque("Parcial")]}),
                ("session.status_idle", {"stop_reason": types.SimpleNamespace(type="budget_reached")})]
    (tmp_path / "ids.json").write_text(json.dumps({"agent_id": "a", "agent_version": 1, "environment_id": "e"}))
    monkeypatch.setattr(mod, "AQUI", tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert "tope de gasto" in mod.responder("x")
