import json

import pandas as pd
import pytest

import brent


def test_leer_fred_csv_ignora_faltantes():
    texto = "observation_date,DCOILBRENTEU\n2026-11-03,80.5\n2026-11-04,.\n2026-11-05,82\n"
    s = brent.leer_fred_csv(texto, "DCOILBRENTEU")
    assert list(s.index.strftime("%Y-%m-%d")) == ["2026-11-03", "2026-11-05"]
    assert s.iloc[-1] == 82


def test_leer_fred_csv_rechaza_respuesta_rara():
    with pytest.raises(ValueError):
        brent.leer_fred_csv("<html>error</html>", "DCOILBRENTEU")


def test_leer_bcrp_diario():
    texto = json.dumps({"periods": [{"name": "03.Nov.26", "values": ["3.40"]},
                                    {"name": "04.Nov.26", "values": ["n.d."]}]})
    s = brent.leer_bcrp_diario(texto)
    assert len(s) == 1 and s.iloc[0] == 3.40


def test_armar_galon_y_soles_con_tipo_de_cambio_anterior():
    idx = pd.to_datetime(["2026-11-06", "2026-11-09"])        # viernes y lunes
    series = {
        "brent_usd_bbl": pd.Series([84.0, 86.1], index=idx),
        "diesel_golfo_usd_gal": pd.Series([2.50, 2.60], index=idx),
        "fx_pen_usd": pd.Series([3.40], index=idx[:1]),       # el lunes aún no hay tipo de cambio
    }
    df = brent.armar(series)
    assert list(df.columns) == brent.COLUMNAS
    assert df.loc[0, "brent_usd_gal"] == pytest.approx(2.0)          # 84 / 42
    assert df.loc[0, "brent_pen_gal"] == pytest.approx(6.8)           # 2.0 × 3.40
    assert df.loc[1, "fx_pen_usd"] == pytest.approx(3.40)             # se arrastra el último
    assert df.loc[1, "diesel_golfo_pen_gal"] == pytest.approx(2.60 * 3.40)


def test_armar_conserva_lo_guardado_si_falla_una_fuente():
    anterior = pd.DataFrame({"fecha": ["2026-11-02"], "brent_usd_bbl": [80.0],
                             "diesel_golfo_usd_gal": [2.4], "fx_pen_usd": [3.5]})
    nuevo = {"brent_usd_bbl": pd.Series([81.0], index=pd.to_datetime(["2026-11-03"]))}
    df = brent.armar(nuevo, anterior)
    assert list(df["fecha"]) == ["2026-11-02", "2026-11-03"]
    assert df.loc[1, "fx_pen_usd"] == 3.5 and df.loc[0, "diesel_golfo_usd_gal"] == 2.4
