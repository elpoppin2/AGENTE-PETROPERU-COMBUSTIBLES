import csv
import functools
import http.server
import importlib
import threading
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def agente(tmp_path, monkeypatch):
    monkeypatch.setenv("PETROPERU_DATOS", str(tmp_path))
    import agente_petroperu
    return importlib.reload(agente_petroperu)


@pytest.fixture
def servidor():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/"
    httpd.shutdown()


def recorrer_local(agente, url, monkeypatch):
    monkeypatch.setattr(agente, "DOMINIOS_PERMITIDOS", ("127.0.0.1",))
    monkeypatch.setattr(agente, "enlace_relevante", lambda u, t: "precio" in t.lower())
    return agente.recorrer([url + "index.html"], agente.nueva_sesion())


def test_entra_a_cada_lista_y_filtra_automotores(agente, servidor, monkeypatch):
    precios, paginas = recorrer_local(agente, servidor, monkeypatch)
    assert len(paginas) == 3  # índice + 2 listas, sin redes sociales ni contacto
    tabla = {(p.combustible, p.ubicacion): p.precio for p in precios}
    assert tabla[("GASOHOL_90", "Callao")] == 15.43
    assert tabla[("DIESEL_B5_S50", "Conchán")] == 14.77
    assert tabla[("GASOLINA_PREMIUM", "Piura")] == 15.90
    assert tabla[("GLP_AUTOMOTRIZ", "Talara")] == 2.15
    assert not any(p.precio in (14.10, 9.80) for p in precios)  # industrial y turbo excluidos
    assert len(precios) == 12


def test_usa_ultimo_precio_si_no_hay_actualizacion(agente):
    P = agente.Precio
    agente.registrar([P("GASOHOL_90", "Callao", 15.43, "x"), P("GASOHOL_95", "Callao", 15.71, "x")], "2026-10-14")
    # Día 2: la web no responde -> se arrastran ambos precios.
    dia2 = {f["combustible"]: f for f in agente.registrar([], "2026-10-15")}
    assert dia2["GASOHOL_90"]["estado"] == "ultimo_registrado"
    assert dia2["GASOHOL_90"]["precio"] == "15.43"
    assert dia2["GASOHOL_90"]["fecha_precio"] == "2026-10-14"
    # Día 3: sólo cambia el 90; el 95 sigue igual.
    dia3 = {f["combustible"]: f for f in agente.registrar(
        [P("GASOHOL_90", "Callao", 15.20, "x"), P("GASOHOL_95", "Callao", 15.71, "x")], "2026-10-16")}
    assert (dia3["GASOHOL_90"]["estado"], dia3["GASOHOL_90"]["fecha_precio"]) == ("actualizado", "2026-10-16")
    assert (dia3["GASOHOL_95"]["estado"], dia3["GASOHOL_95"]["fecha_precio"]) == ("sin_cambio", "2026-10-14")
    # Repetir el mismo día no duplica filas.
    agente.registrar([P("GASOHOL_90", "Callao", 15.20, "x")], "2026-10-16")
    with agente.HISTORIAL.open() as f:
        filas = list(csv.DictReader(f))
    assert len(filas) == 6


def test_respaldo_de_texto_y_pdf_style():
    import agente_petroperu as a
    texto = "Gasohol 97 Plus .......... S/ 16,02\nDiesel B5 S-50 UV  14.80 Soles/Gal\nAsfalto 3.20"
    res = {p.combustible: p.precio for p in a.precios_de_texto(texto, "f", "General")}
    assert res == {"GASOHOL_97": 16.02, "DIESEL_B5_S50": 14.80}
