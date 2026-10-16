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


def test_entra_a_cada_lista_y_solo_registra_los_dos_diesel(agente, servidor, monkeypatch):
    precios, paginas = recorrer_local(agente, servidor, monkeypatch)
    assert len(paginas) == 3  # índice + 2 listas, sin redes sociales ni contacto
    tabla = {(p.combustible, p.ubicacion): p.precio for p in precios}
    assert tabla == {
        ("DIESEL_B5_S50", "Callao"): 14.60,
        ("DIESEL_B5_S50", "Conchán"): 14.62,
        ("DIESEL_B5_S50_UV", "Callao"): 14.75,
        ("DIESEL_B5_S50_UV", "Conchán"): 14.77,
        ("DIESEL_B5_S50", "Talara"): 14.65,
        ("DIESEL_B5_S50", "Piura"): 14.70,
        ("DIESEL_B5_S50_UV", "Talara"): 14.80,
        ("DIESEL_B5_S50_UV", "Piura"): 14.85,
    }  # gasoholes, gasolinas, GLP, Turbo, industrial y B5 sin S-50 quedan fuera


@pytest.mark.parametrize("texto, esperado", [
    ("Diésel B5 S-50", "DIESEL_B5_S50"),
    ("DIESEL B5-S50", "DIESEL_B5_S50"),
    ("DB5 S-50", "DIESEL_B5_S50"),
    ("Diésel B5 S-50 UV", "DIESEL_B5_S50_UV"),
    ("Diesel B5-S50UV", "DIESEL_B5_S50_UV"),
    ("Diesel B5 S-50 (Uso Vehicular)", "DIESEL_B5_S50_UV"),
    ("Diésel B5 S-50 Industrial", None),
    ("Diesel B5", None),
    ("Gasohol 90 Plus", None),
    ("GLP", None),
])
def test_identifica_solo_los_dos_diesel(texto, esperado):
    import agente_petroperu as a
    assert a.identificar_combustible(texto) == esperado


def test_usa_ultimo_precio_si_no_hay_actualizacion(agente):
    P = agente.Precio
    agente.registrar([P("DIESEL_B5_S50", "Callao", 14.60, "x"), P("DIESEL_B5_S50_UV", "Callao", 14.75, "x")], "2026-10-14")
    # Día 2: la web no responde -> se arrastran ambos precios.
    dia2 = {f["combustible"]: f for f in agente.registrar([], "2026-10-15")}
    assert dia2["DIESEL_B5_S50"]["estado"] == "ultimo_registrado"
    assert dia2["DIESEL_B5_S50"]["precio"] == "14.60"
    assert dia2["DIESEL_B5_S50"]["fecha_precio"] == "2026-10-14"
    # Día 3: sólo cambia el 90; el 95 sigue igual.
    dia3 = {f["combustible"]: f for f in agente.registrar(
        [P("DIESEL_B5_S50", "Callao", 14.40, "x"), P("DIESEL_B5_S50_UV", "Callao", 14.75, "x")], "2026-10-16")}
    assert (dia3["DIESEL_B5_S50"]["estado"], dia3["DIESEL_B5_S50"]["fecha_precio"]) == ("actualizado", "2026-10-16")
    assert (dia3["DIESEL_B5_S50_UV"]["estado"], dia3["DIESEL_B5_S50_UV"]["fecha_precio"]) == ("sin_cambio", "2026-10-14")
    # Repetir el mismo día no duplica filas.
    agente.registrar([P("DIESEL_B5_S50", "Callao", 14.40, "x")], "2026-10-16")
    with agente.HISTORIAL.open() as f:
        filas = list(csv.DictReader(f))
    assert len(filas) == 6


def test_respaldo_de_texto_y_pdf_style():
    import agente_petroperu as a
    texto = ("Gasohol 97 Plus .......... S/ 16,02\nDiesel B5 S-50 .......... S/ 14,60\n"
             "Diesel B5 S-50 UV  14.80 Soles/Gal\nAsfalto 3.20")
    res = {p.combustible: p.precio for p in a.precios_de_texto(texto, "f", "General")}
    assert res == {"DIESEL_B5_S50": 14.60, "DIESEL_B5_S50_UV": 14.80}
