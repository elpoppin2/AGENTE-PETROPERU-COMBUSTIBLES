import pandas as pd
import pytest

from carbon import analytics, report, store


def test_ratios_calibrated_from_trade_data(synthetic_wide, cfg):
    res = analytics.compute(synthetic_wide, cfg)
    assert res.meta["ratio_api2_calibrado"] and res.meta["ratio_newcastle_calibrado"]
    assert res.meta["ratio_colombia_api2"] == pytest.approx(0.85)
    # meses sin Comtrade se estiman con el índice preferido (API2) x ratio
    last = res.monthly.iloc[-1]
    assert last["carbon_col_fob_fuente"] == "nowcast_api2"
    assert last["carbon_col_fob"] == pytest.approx(last["carbon_api2_cif_ara"] * 0.85)


def test_falls_back_to_newcastle_without_api2(synthetic_wide, cfg):
    w = synthetic_wide.drop(columns="carbon_api2_cif_ara")
    res = analytics.compute(w, cfg)
    last = res.monthly.iloc[-1]
    assert last["carbon_col_fob_fuente"] == "nowcast_newcastle"
    assert last["carbon_col_fob"] == pytest.approx(last["carbon_newcastle_fob"] * res.meta["ratio_colombia_newcastle"])
    assert not res.meta["ratio_api2_calibrado"]


def test_api2_extends_beyond_newcastle(synthetic_wide, cfg):
    """Investing (API2) suele estar al día cuando FRED aún no publica el mes."""
    w = synthetic_wide.copy()
    w.loc[pd.Timestamp("2026-10-01"), "carbon_api2_cif_ara"] = 120.0
    m = analytics.compute(w, cfg).monthly
    assert m.index.max() == pd.Timestamp("2026-10-01")
    assert m.iloc[-1]["carbon_col_fob"] == pytest.approx(120 * 0.85)


def test_cfr_es_fob_mas_flete(synthetic_wide, cfg):
    r = analytics.compute(synthetic_wide, cfg).monthly.iloc[-1]
    assert r["carbon_cfr"] == pytest.approx(r["carbon_col_fob"] + r["carbon_flete"])
    assert r["carbon_cfr_pen"] == pytest.approx(r["carbon_cfr"] * r["fx_pen_usd"])
    assert "carbon_landed" not in r.index      # no se calcula el puesto en planta

def test_freight_calibrated_to_implied(synthetic_wide, cfg):
    res = analytics.compute(synthetic_wide, cfg)
    m = res.monthly.iloc[:-4]
    assert (m["carbon_flete"] / 26).median() == pytest.approx(1.0, rel=0.02)
    assert res.monthly.iloc[0]["share_colombia_import_pe"] == pytest.approx(0.75)


def test_spec_adjustment(synthetic_wide, cfg):
    cfg["carbon"]["poder_calorifico_spec_kcal_kg"] = 6300
    r = analytics.compute(synthetic_wide, cfg).monthly.iloc[-1]
    assert r["carbon_col_fob"] == pytest.approx(r["carbon_api2_cif_ara"] * 0.85 * 6300 / 6000)


def test_manual_quotes_override(synthetic_wide, cfg):
    w = synthetic_wide.copy()
    w.loc[w.index[-1], "manual_carbon_fob"] = 99.0
    w.loc[w.index[-1], "manual_flete_carbon"] = 30.0
    r = analytics.compute(w, cfg).monthly.iloc[-1]
    assert r["carbon_col_fob"] == pytest.approx(99.0)
    assert r["carbon_flete"] == pytest.approx(30.0)
    assert r["carbon_col_fob_fuente"] == "manual_carbon_fob"


def test_alerts_on_jump_and_budget(synthetic_wide, cfg):
    w = synthetic_wide.copy()
    w.loc[w.index[-1], "carbon_api2_cif_ara"] *= 1.5
    cfg["carbon"]["presupuesto_cfr_usd_t"] = 100
    alerts = analytics.compute(w, cfg).alerts
    assert any("API2" in a and "m/m" in a for a in alerts)
    assert any("supera la referencia" in a for a in alerts)


def test_empty_history(cfg):
    res = analytics.compute(pd.DataFrame(), cfg)
    assert res.monthly.empty and res.alerts


def test_store_roundtrip_and_report(tmp_path, synthetic_wide, cfg):
    long = synthetic_wide.stack().dropna().rename("valor").reset_index()
    long.columns = ["fecha", "serie", "valor"]
    long["unidad"], long["fuente"] = "x", "test"
    path = tmp_path / "series.csv"
    store.upsert(path, long)
    # una revisión del mismo mes sobrescribe sin duplicar
    rev = long.iloc[[0]].assign(valor=1.0)
    hist = store.upsert(path, rev)
    assert len(hist) == len(long)
    w = store.wide(hist)
    assert w.iloc[0][long.iloc[0]["serie"]] == 1.0

    res = analytics.compute(store.wide(store.load(path)), cfg)
    files = report.charts(res, tmp_path / "graficos")
    md = report.render(res, cfg, "comentario de prueba", files)
    assert "CFR Conchán" in md and "puesto en planta" not in md.lower() and "indices.png" in files
    assert "comentario de prueba" in md and "Escoria FOB Japón" in md


def test_cotizacion_cfr_despues_del_ultimo_indice(synthetic_wide, cfg):
    """Cotización (7,000 kcal): FOB 120 + flete 30 = CFR 150, en un mes sin índice publicado."""
    from carbon.sources import manual
    import tempfile
    from pathlib import Path
    cfg["carbon"]["poder_calorifico_spec_kcal_kg"] = 7000
    with tempfile.TemporaryDirectory() as d:
        Path(d, "cotizaciones.csv").write_text(
            "fecha,material,base,precio_usd_t,poder_calorifico_kcal_kg,proveedor,comentario\n"
            "2026-11-04,carbon,FOB,120,7000,Proveedor,\n2026-11-04,carbon,CFR,150,7000,Proveedor,\n")
        Path(d, "fletes.csv").write_text("fecha,material,flete_usd_t,tipo_buque,fuente,comentario\n2026-11-04,carbon,30,Handysize,Broker,\n")
        q = manual.fetch(Path(d), cfg)
    assert q.set_index("serie")["valor"]["manual_carbon_cfr"] == 150   # el CFR no se normaliza por kcal
    w = synthetic_wide.copy()
    mes = w.index[-1] + pd.offsets.MonthBegin(1)                       # después del último índice
    for _, f in q.iterrows():
        w.loc[mes, f["serie"]] = f["valor"]
    r = analytics.compute(w.sort_index(), cfg).monthly.iloc[-1]
    assert r.name == mes                                               # el mes cotizado no se recorta
    assert r["carbon_col_fob"] == pytest.approx(120.0)
    assert r["carbon_flete"] == pytest.approx(30.0)
    assert r["carbon_cfr"] == pytest.approx(150.0)

def test_aviso_solo_con_alertas_nuevas(synthetic_wide, cfg, tmp_path, monkeypatch):
    import carbon.__main__ as cli
    monkeypatch.setattr(cli, "AVISO_PATH", tmp_path / "aviso.md")
    monkeypatch.setattr(cli, "ENVIADAS_PATH", tmp_path / "enviadas.json")
    cfg["carbon"]["presupuesto_cfr_usd_t"] = 100
    res = analytics.compute(synthetic_wide, cfg)
    assert any("supera la referencia" in a for a in res.alerts)
    titulo = cli.aviso_alertas(res)
    assert titulo and "nueva" in titulo
    texto = (tmp_path / "aviso.md").read_text(encoding="utf-8")
    assert "**CFR Conchán**" in texto and "Flete marítimo" in texto and "planta" not in texto
    # La misma alerta con otra cifra no se vuelve a avisar
    res.alerts = [a.replace("1", "2") for a in res.alerts]
    assert cli.aviso_alertas(res) is None


def test_escoria_fob_mas_flete_con_datos_anuales(synthetic_wide, cfg):
    """La escoria usa el FOB de Japón (mensual, si no anual, si no el último dato) + flete = CFR."""
    w = synthetic_wide.copy()
    anio = w.index[-12].year
    w.loc[pd.Timestamp(f"{anio}-01-01"), "jp_exp_escoria_pe_fob_anual_usd_t"] = 6.6       # dato anual
    w.loc[w.index[-2], "jp_exp_escoria_pe_fob_usd_t"] = 9.0                               # dato mensual
    w = w.sort_index()
    m = analytics.compute(w, cfg).monthly
    assert m.loc[pd.Timestamp(f"{anio}-03-01"), "escoria_fob"] == pytest.approx(6.6)       # el anual cubre todo el año
    assert m.iloc[-2]["escoria_fob"] == pytest.approx(9.0)
    assert m.iloc[-1]["escoria_fob"] == pytest.approx(9.0)                                  # se arrastra el último dato
    assert m.iloc[-1]["escoria_fob_fuente"] == "ultimo_dato"
    r = m.iloc[-1]
    assert r["escoria_cfr"] == pytest.approx(r["escoria_fob"] + r["escoria_flete"])


def test_alertas_separadas_por_material(synthetic_wide, cfg):
    cfg["escoria"]["presupuesto_cfr_usd_t"] = 10
    res = analytics.compute(synthetic_wide, cfg)
    assert any("Escoria CFR Conchán" in a for a in res.meta["alertas"]["escoria"])
    assert not any("Escoria" in a for a in res.meta["alertas"]["carbon"])


def test_ratio_calibrado_con_exportaciones_a_peru(synthetic_wide, cfg):
    """Con datos Colombia→Perú, el ratio sale de ellos y el comercio con el mundo no se usa."""
    w = synthetic_wide.copy()
    w["co_exp_carbon_mundo_fob_usd_t"] = w["carbon_api2_cif_ara"] * 0.60      # más barato: no debe usarse
    cfg["carbon"]["poder_calorifico_spec_kcal_kg"] = 7000
    cfg["carbon"]["poder_calorifico_comercio_pe_kcal_kg"] = 7000              # el comercio ya está a 7,000
    res = analytics.compute(w, cfg)
    r = res.monthly.iloc[-1]
    assert res.meta["calibracion_ratio"] == "colombia_peru"
    assert r["carbon_col_fob"] == pytest.approx(r["carbon_api2_cif_ara"] * 0.85)  # sin escalar: misma base
    cfg["carbon"]["poder_calorifico_comercio_pe_kcal_kg"] = 6000              # si el comercio estuviera a 6,000
    r2 = analytics.compute(w, cfg).monthly.iloc[-1]
    assert r2["carbon_col_fob"] == pytest.approx(r["carbon_col_fob"] * 7000 / 6000)


def test_cfr_comparable_con_atenuantes(synthetic_wide, cfg):
    cfg["carbon"]["atenuantes"] = {"granulometria_usd_t": 4.5, "calidad_usd_t": 1.5, "plazo_pago_dias": 60, "tasa_anual_pct": 8.0}
    r = analytics.compute(synthetic_wide, cfg).monthly.iloc[-1]
    base = r["carbon_cfr"] + 6.0
    assert r["carbon_costo_credito"] == pytest.approx(base * 0.08 * 60 / 365)
    assert r["carbon_cfr_comparable"] == pytest.approx(base + r["carbon_costo_credito"])
