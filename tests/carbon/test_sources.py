import io
import json
from pathlib import Path

import pandas as pd
import pytest

from carbon.sources import bcrp, comtrade, fred, investing, manual, worldbank

FIX = Path(__file__).parent / "fixtures"


def test_fred_parses_and_skips_missing():
    df = fred.parse_csv((FIX / "fred_PCOALAUUSDM.csv").read_text(), "PCOALAUUSDM", "carbon_newcastle_fob", "USD/t")
    assert list(df["valor"]) == [118.2, 121.4]
    assert set(df["serie"]) == {"carbon_newcastle_fob"}


def test_fred_rejects_html_response():
    with pytest.raises(ValueError):
        fred.parse_csv("<html>blocked</html>", "PCOALAUUSDM", "carbon_newcastle_fob", "USD/t")


def test_fred_api_json():
    payload = {"observations": [{"date": "2026-08-01", "value": "121.4"}, {"date": "2026-09-01", "value": "."}]}
    df = fred.parse_api_json(payload, "PCOALAUUSDM", "carbon_newcastle_fob", "USD/t")
    assert list(df["valor"]) == [121.4]


def test_fred_legacy_date_header():
    df = fred.parse_csv("DATE,EXJPUS\n2026-01-01,150.5\n", "EXJPUS", "fx_jpy_usd", "JPY por USD")
    assert df["valor"].iloc[0] == 150.5


def test_bcrp_daily_to_monthly_mean():
    df = bcrp.parse_json((FIX / "bcrp_PD04638PD.json").read_text(), "fx_pen_usd", "PEN por USD", "PD04638PD")
    sep = df[df["fecha"] == pd.Timestamp("2026-09-01")]["valor"].iloc[0]
    assert sep == pytest.approx((3.512 + 3.518) / 2)
    assert len(df) == 2


@pytest.mark.parametrize("name,expected", [
    ("02.Ene.24", pd.Timestamp("2024-01-02")),
    ("15.Set.26", pd.Timestamp("2026-09-15")),
    ("Ago.2025", pd.Timestamp("2025-08-01")),
    ("basura", None),
])
def test_bcrp_period_names(name, expected):
    assert bcrp.parse_period(name) == expected


def test_comtrade_unit_values_and_volume():
    records = json.loads((FIX / "comtrade_pe_imp_coal.json").read_text())["data"]
    df = comtrade.parse_records(records, "pe_imp_carbon_col_cif", "M")
    uv = df[df["serie"] == "pe_imp_carbon_col_cif_usd_t"].set_index("fecha")["valor"]
    vol = df[df["serie"] == "pe_imp_carbon_col_cif_vol_t"].set_index("fecha")["valor"]
    assert uv[pd.Timestamp("2025-06-01")] == pytest.approx(140.0)
    assert uv[pd.Timestamp("2025-08-01")] == pytest.approx(145.0)      # peso tomado de qty (kg)
    assert pd.Timestamp("2025-07-01") not in uv.index                  # sin peso -> descartado
    assert vol[pd.Timestamp("2025-06-01")] == pytest.approx(60000)


def test_comtrade_prefers_totals_over_breakdown():
    base = {"period": "202601", "netWgt": 1_000_000, "fobvalue": 30_000, "qtyUnitCode": 8}
    records = [
        {**base, "customsCode": "C00", "motCode": 0, "partner2Code": 0},
        {**base, "customsCode": "C01", "motCode": 2100, "partner2Code": 0},
    ]
    df = comtrade.parse_records(records, "co_exp_carbon_pe_fob", "X")
    assert df[df["serie"] == "co_exp_carbon_pe_fob_vol_t"]["valor"].iloc[0] == pytest.approx(1000)


def _pink_sheet_bytes() -> bytes:
    rows = [
        ["World Bank Commodity Price Data (The Pink Sheet)", None, None, None],
        [None, None, None, None],
        ["Monthly Prices", None, None, None],
        [None, None, None, None],
        [None, "Crude oil, Brent", "Coal, Australian", "Coal, South African **"],
        [None, "($/bbl)", "($/mt)", "($/mt)"],
        [None, "CRUDE_BRENT", "COAL_AUS", "COAL_SAFRICA"],
        ["2018M12", 57.0, 100.0, 90.0],
        ["2026M08", 70.5, 121.0, 95.0],
        ["2026M09", 72.1, "…", 97.0],
    ]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, sheet_name="Monthly Prices", header=False, index=False)
    return buf.getvalue()


def test_worldbank_pink_sheet_layout():
    df = worldbank.parse_xlsx(_pink_sheet_bytes(), "2019-01")
    aus = df[df["serie"] == "carbon_bm_australia_fob"]
    assert list(aus["valor"]) == [121.0]                       # 2018 filtrado, "…" ignorado
    assert set(df["serie"]) == {"brent_bm", "carbon_bm_australia_fob", "carbon_bm_sudafrica_fob"}


def test_manual_quotes_normalized_to_reference_cv(tmp_path, cfg):
    (tmp_path / "cotizaciones.csv").write_text(
        "fecha,material,base,precio_usd_t,poder_calorifico_kcal_kg,proveedor,comentario\n"
        "2026-10-05,carbon,FOB,126,6300,X,\n"
        "2026-10-20,Carbon,cif,150,,Y,\n"
    )
    (tmp_path / "fletes.csv").write_text(
        "fecha,material,flete_usd_t,tipo_buque,fuente,comentario\n2026-10-10,Carbon,25,Supramax,Z,\n"
    )
    df = manual.fetch(tmp_path, cfg).set_index("serie")["valor"]
    assert df["manual_carbon_fob"] == pytest.approx(120.0)     # 126 * 6000/6300
    assert df["manual_carbon_cif"] == 150
    assert df["manual_flete_carbon"] == 25


def test_investing_english_csv(tmp_path):
    path = tmp_path / "Rotterdam Coal Futures Historical Data.csv"
    path.write_text(
        '\ufeff"Date","Price","Open","High","Low","Vol.","Change %"\n'
        '"10/21/2026","1,104.50","110.00","112.00","109.00","","0.41%"\n'
        '"10/20/2026","110.00","109.00","111.00","108.00","","-0.5%"\n'
        '"09/30/2026","100.00","99.00","101.00","98.00","","1.0%"\n',
        encoding="utf-8",
    )
    df = investing.fetch(tmp_path, {"rotterdam": "carbon_api2_cif_ara"}).set_index("fecha")["valor"]
    assert df[pd.Timestamp("2026-10-01")] == pytest.approx((1104.5 + 110) / 2)
    assert df[pd.Timestamp("2026-09-01")] == pytest.approx(100)


def test_investing_spanish_csv(tmp_path):
    (tmp_path / "Futuros carbón API2 - Datos históricos.csv").write_text(
        '"Fecha","Último","Apertura","Máximo","Mínimo","Vol.","% var."\n'
        '"21.10.2026","1.104,50","110,00","112,00","109,00","","0,41%"\n'
        '"02.09.2026","98,25","99,00","101,00","98,00","","1,0%"\n',
        encoding="utf-8",
    )
    (tmp_path / "otra cosa.csv").write_text("Fecha,Último\n21.10.2026,1\n")   # sin palabra clave: se ignora
    df = investing.fetch(tmp_path, {"api2": "carbon_api2_cif_ara"})
    assert set(df["serie"]) == {"carbon_api2_cif_ara"}
    v = df.set_index("fecha")["valor"]
    assert v[pd.Timestamp("2026-10-01")] == pytest.approx(1104.5)
    assert v[pd.Timestamp("2026-09-01")] == pytest.approx(98.25)


def test_comtrade_periodo_anual():
    df = comtrade.parse_records([{"period": "2024", "fobvalue": 66000, "netWgt": 10_000_000}], "jp_exp_escoria_pe_fob_anual", "X")
    v = df.set_index("serie")
    assert v.loc["jp_exp_escoria_pe_fob_anual_usd_t", "fecha"] == pd.Timestamp("2024-01-01")
    assert v.loc["jp_exp_escoria_pe_fob_anual_usd_t", "valor"] == pytest.approx(6.6)


def test_comtrade_incremental(tmp_path, monkeypatch):
    """La segunda corrida solo pide los periodos recientes; los viejos ya consultados se saltan."""
    pedidos = []

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"data": []}

    class Sesion:
        headers = {}
        def get(self, url, params, timeout):
            pedidos.append((params["cmdCode"], params["period"]))
            return Resp()

    monkeypatch.setattr(comtrade, "session", lambda: Sesion())
    monkeypatch.setattr(comtrade.time, "sleep", lambda s: None)
    monkeypatch.delenv("COMTRADE_API_KEY", raising=False)
    estado = tmp_path / "consultas.json"
    comtrade.fetch(12, estado=estado)
    primera = len(pedidos)
    assert primera == 12 * len(comtrade.QUERIES)
    pedidos.clear()
    comtrade.fetch(12, estado=estado)
    assert len(pedidos) == comtrade.RECIENTES * len(comtrade.QUERIES)
