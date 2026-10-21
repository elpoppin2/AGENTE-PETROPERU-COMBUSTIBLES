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
    ("DIESEL B5 UV\nS-50", "DIESEL_B5_S50_UV"),
    ("DIESEL B5\nS-50", "DIESEL_B5_S50"),
    ("Diésel B5 S-50 Industrial", None),
    ("DIESEL B5 UV", None),
    ("DIESEL B5 S-50\nG. E.", None),
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
    assert dia2["DIESEL_B5_S50"]["precio"] == "14.6000"
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


def test_nombre_partido_en_varias_celdas_como_en_pdf():
    import agente_petroperu as a
    filas = [["Producto", "", "Callao", "Talara"],
             ["Diesel B5", "S-50", "14.6000", "14.82"],
             ["Diesel B5", "S-50 UV", "14.75", "14.95"],
             ["Diesel B5", "S-50 Industrial", "14.10", "14.20"]]
    res = {(p.combustible, p.ubicacion): p.precio for p in a.precios_de_tabla(filas, "f", "General")}
    assert res == {("DIESEL_B5_S50", "Callao"): 14.60, ("DIESEL_B5_S50", "Talara"): 14.82,
                   ("DIESEL_B5_S50_UV", "Callao"): 14.75, ("DIESEL_B5_S50_UV", "Talara"): 14.95}


def test_lista_real_de_petroperu(agente, servidor):
    """Página con el formato real y el PDF real del 13-Oct-2026 (Addendum N° 1)."""
    precios, paginas = agente.recorrer([servidor + "plantas.html"], agente.nueva_sesion())
    assert paginas[-1].endswith("/lista_2026-10-13.pdf")  # la más reciente de "Automotriz"
    tabla = {(p.combustible, p.ubicacion): p.precio for p in precios}
    assert len(tabla) == 32  # 16 plantas x 2 diésel
    assert tabla[("DIESEL_B5_S50_UV", "CALLAO")] == 22.9038
    assert tabla[("DIESEL_B5_S50", "CALLAO")] == 24.4732
    assert tabla[("DIESEL_B5_S50_UV", "TALARA")] == 23.0218
    assert tabla[("DIESEL_B5_S50", "PTO. MALDONADO")] == 23.9483
    assert {p.vigencia for p in precios} == {"2026-10-13"}


def test_pdf_real_anterior_y_cambio_de_precio(agente):
    leer = lambda f: agente.extraer_pdf((FIXTURES / f).read_bytes(), f, "General")
    agente.registrar(leer("lista_2026-10-06.pdf"), "2026-10-07")
    agente.registrar([], "2026-10-08")  # sin novedades: se usa el último precio
    filas = {(f["combustible"], f["ubicacion"]): f for f in agente.registrar(leer("lista_2026-10-13.pdf"), "2026-10-13")}
    assert len(filas) == 32
    assert {f["fecha_precio"] for f in filas.values()} == {"2026-10-13"}
    with agente.HISTORIAL.open() as f:
        dia8 = [r for r in csv.DictReader(f) if r["fecha_consulta"] == "2026-10-08"]
    assert dia8 and {r["estado"] for r in dia8} == {"ultimo_registrado"}
    assert {r["fecha_precio"] for r in dia8} == {"2026-10-06"}


def test_historico_desde_fecha(agente, servidor, monkeypatch):
    monkeypatch.setattr(agente, "URLS_INICIO", [servidor + "plantas.html"])
    monkeypatch.setattr(agente.time, "sleep", lambda s: None)
    precios = agente.historico("2026-10-01", agente.nueva_sesion())
    assert len(precios) == 64  # 2 listas automotrices x 16 plantas x 2 diésel
    assert agente.guardar_listas(precios) == 64
    assert agente.guardar_listas(precios[:5]) == 0  # no duplica al repetir
    with agente.LISTAS.open() as f:
        filas = list(csv.DictReader(f))
    assert {f["vigencia"] for f in filas} == {"2026-10-06", "2026-10-13"}
    assert len(agente.historico("2026-10-10", agente.nueva_sesion())) == 32


def test_reporte_de_cambio_entre_dos_listas(agente, monkeypatch, tmp_path):
    monkeypatch.setattr(agente, "DIR_REPORTES", tmp_path / "reportes")
    leer = lambda f: agente.extraer_pdf((FIXTURES / f).read_bytes(), f, "General")
    for f, v in (("lista_2026-10-06.pdf", "2026-10-06"), ("lista_2026-10-13.pdf", "2026-10-13")):
        precios = leer(f)
        for p in precios:
            p.vigencia = v
        agente.guardar_listas(precios)
    assert agente.reporte_cambio("2026-10-06") is None  # no hay lista anterior
    titulo, cuerpo, mensaje = agente.reporte_cambio("2026-10-13")
    assert "13 oct. 2026" in titulo and "Callao ▲ +0.45" in titulo
    assert "| Callao | 22.9038 | ▲ +0.4484 | 24.4732 | ▲ +0.4484 |" in cuerpo
    assert "6 oct. 2026" in cuerpo and "cc @" in cuerpo
    ruta = agente.escribir_reporte("2026-10-13")
    assert ruta.name == "2026-10-13.md" and ruta.read_text().startswith("# Cambio de precios")
    assert "Callao: B5 S-50 UV S/ 22.90 (▲ +0.45)" in mensaje and len(mensaje) < 600
    html = agente.markdown_a_html(cuerpo)
    assert "<table" in html and "#b54708" in html and "<script" not in html


def test_enviar_avisos_por_correo_y_whatsapp(agente, monkeypatch):
    import smtplib
    P = agente.Precio
    for v, precio in (("2026-10-06", 20.0), ("2026-10-13", 20.5)):
        agente.guardar_listas([P("DIESEL_B5_S50_UV", "CALLAO", precio, "x", v), P("DIESEL_B5_S50", "CALLAO", precio + 1, "x", v)])
    enviados, urls = [], []

    class SMTPFalso:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, u, c): assert (u, c) == ("bot@gmail.com", "clave")
        def send_message(self, m): enviados.append(m)

    class Resp:
        def raise_for_status(self): pass

    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTPFalso)
    monkeypatch.setattr(agente.requests, "get", lambda url, timeout: urls.append(url) or Resp())
    monkeypatch.setattr(agente.time, "sleep", lambda s: None)
    monkeypatch.setenv("AVISO_CORREO_USUARIO", "bot@gmail.com")
    monkeypatch.setenv("AVISO_CORREO_CLAVE", "clave")
    monkeypatch.setenv("AVISO_CORREOS", "a@x.pe, b@x.pe")
    monkeypatch.setenv("AVISO_WHATSAPP", "+51999000111:123, +51999000222:456")
    assert agente.enviar_avisos("2026-10-13", "https://github.com/x/issues/1")
    assert len(enviados) == 1 and enviados[0]["To"] == "a@x.pe, b@x.pe"
    assert "13 oct. 2026" in enviados[0]["Subject"]
    assert len(urls) == 2 and "phone=%2B51999000111" in urls[0] and "apikey=123" in urls[0]


def test_excel_con_todo_el_historico(agente):
    from openpyxl import load_workbook
    P = agente.Precio
    agente.guardar_listas([P("DIESEL_B5_S50_UV", "CALLAO", 20.0, "a.pdf", "2026-10-06"),
                           P("DIESEL_B5_S50", "CALLAO", 21.0, "a.pdf", "2026-10-06"),
                           P("DIESEL_B5_S50_UV", "CALLAO", 20.5, "b.pdf", "2026-10-13"),
                           P("DIESEL_B5_S50", "TALARA", 21.7, "b.pdf", "2026-10-13")])
    wb = load_workbook(agente.generar_excel())
    assert wb.sheetnames[:4] == ["Precios vigentes", "Histórico B5 S-50 UV", "Histórico B5 S-50", "Datos"]
    assert [c.value for c in wb["Precios vigentes"][5]][:2] == ["Callao", 20.5]
    assert wb["Histórico B5 S-50 UV"]["B2"].value == 20.5 and wb["Histórico B5 S-50 UV"]["B3"].value == 20.0
    assert wb["Datos"].max_row == 5


def test_reporte_diario_con_y_sin_cambios(agente, monkeypatch):
    from datetime import datetime
    P = agente.Precio
    agente.guardar_listas([P("DIESEL_B5_S50_UV", "CALLAO", 20.0, "a", "2026-10-13"), P("DIESEL_B5_S50", "CALLAO", 21.0, "a", "2026-10-13")])
    agente.guardar_listas([P("DIESEL_B5_S50_UV", "CALLAO", 20.4, "b", "2026-10-17"), P("DIESEL_B5_S50", "CALLAO", 21.4, "b", "2026-10-17")])
    enviados = []
    monkeypatch.setattr(agente, "enviar", lambda t, c, m, copia_remitente=False: enviados.append((t, c, m, copia_remitente)) or True)

    class Reloj(datetime):
        actual = datetime(2026, 10, 19, 6, 30)
        @classmethod
        def now(cls, tz=None): return cls.actual.replace(tzinfo=tz)
    monkeypatch.setattr(agente, "datetime", Reloj)

    assert agente.enviar_reporte_diario() is None          # antes de las 07:00 no sale
    Reloj.actual = datetime(2026, 10, 19, 7, 57)
    assert agente.enviar_reporte_diario() is True           # primer envío del día
    titulo, cuerpo, mensaje, copia = enviados[-1]
    assert "19 oct. 2026: sin cambios" in titulo and copia
    assert "Sigue vigente la lista del 17 oct. 2026 (publicada hace 2 días)" in cuerpo
    assert "| Callao | 20.4000 | ▲ +0.4000 |" in cuerpo
    assert agente.enviar_reporte_diario() is None           # no se repite el mismo día

    agente.guardar_listas([P("DIESEL_B5_S50_UV", "CALLAO", 20.1, "c", "2026-10-20"), P("DIESEL_B5_S50", "CALLAO", 21.1, "c", "2026-10-20")])
    Reloj.actual = datetime(2026, 10, 20, 8, 0)
    assert agente.enviar_reporte_diario() is True
    assert "lista nueva" in enviados[-1][0] and "Hay lista nueva" in enviados[-1][1]
    assert agente.enviar_reporte_diario(forzar=True) is True  # para pruebas manuales
    Reloj.actual = datetime(2026, 10, 21, 6, 0)
    assert agente.enviar_reporte_diario(forzar=True) is True
    Reloj.actual = datetime(2026, 10, 21, 7, 57)
    assert agente.enviar_reporte_diario() is True           # la prueba no consumió el envío del día


def test_osinergmin_lectura_y_comparacion(agente, monkeypatch):
    from openpyxl import load_workbook
    contenido = (FIXTURES / "osinergmin_2026-10-19.pdf").read_bytes()
    filas = agente.extraer_osinergmin(contenido, "ref.pdf")
    tabla = {r["planta"]: r for r in filas}
    assert len(filas) == 18 and {r["fecha"] for r in filas} == {"2026-10-19"}
    assert tabla["CALLAO"]["b5_bajo_azufre"] == 17.14 and tabla["CALLAO"]["componente_logistico"] == 0.0
    assert tabla["CUSCO"]["b5_bajo_azufre"] == 17.99 and tabla["PTO. MALDONADO"]["b5_alto_azufre"] == 17.96
    assert agente.guardar_osinergmin(filas) == 18 and agente.guardar_osinergmin(filas) == 0

    # Petroperú sin impuestos: 24.8272 / 1.18 - 1.49 = 19.55
    assert round(agente.sin_impuestos(24.8272), 4) == 19.55
    P = agente.Precio
    agente.guardar_listas([P("DIESEL_B5_S50", "CALLAO", 24.8272, "a", "2026-10-17"),
                           P("DIESEL_B5_S50_UV", "CALLAO", 23.2578, "a", "2026-10-17"),
                           P("DIESEL_B5_S50", "PTO. MALDONADO", 23.9483, "a", "2026-10-17")])
    c = load_workbook(agente.generar_excel())["Comparación"]
    filas_c = {c.cell(row=i, column=1).value: [c.cell(row=i, column=j).value for j in range(2, 9)] for i in range(5, c.max_row + 1)}
    assert filas_c["Callao"][:3] == [17.14, 19.55, 2.41]
    assert "Amazonía" in filas_c["Pto. Maldonado"][1]


def test_actualizar_osinergmin_busca_cada_semana(agente, monkeypatch):
    contenido = (FIXTURES / "osinergmin_2026-10-19.pdf").read_bytes()
    pedidas = []

    class Resp:
        def __init__(self, ok): self.status_code, self.content = (200, contenido) if ok else (404, b"no")

    class Sesion:
        def get(self, url, timeout): pedidas.append(url); return Resp(url.endswith("19102026.pdf"))

    monkeypatch.setattr(agente.time, "sleep", lambda s: None)
    monkeypatch.setattr(agente, "OSINERGMIN_DESDE", "2026-10-12")
    assert agente.actualizar_osinergmin(Sesion(), hasta="2026-10-21") == 18
    assert any(u.endswith("12102026.pdf") for u in pedidas) and pedidas[-1].endswith("19102026.pdf")
    pedidas.clear()
    assert agente.actualizar_osinergmin(Sesion(), hasta="2026-10-21") == 0  # ya estaba
    assert not any(u.endswith("19102026.pdf") for u in pedidas)
