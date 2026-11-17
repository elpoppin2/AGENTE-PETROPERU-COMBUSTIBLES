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


def test_landed_cost_build_up(synthetic_wide, cfg):
    r = analytics.compute(synthetic_wide, cfg).monthly.iloc[-1]
    d = cfg["destino"]
    cif = (r["carbon_col_fob"] + r["carbon_flete"]) * (1 + d["seguro_pct"] / 100)
    assert r["carbon_cif"] == pytest.approx(cif)
    port = sum(d["costos_portuarios_usd_t"].values())
    assert r["carbon_landed"] == pytest.approx(cif * (1 + d["agente_aduanas_pct"] / 100) + port)
    assert r["carbon_landed_pen"] == pytest.approx(r["carbon_landed"] * r["fx_pen_usd"])
    assert r["carbon_usd_gj"] == pytest.approx(r["carbon_landed"] / (6000 * 4.1868e-3))


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
    cfg["carbon"]["presupuesto_landed_usd_t"] = 100
    alerts = analytics.compute(w, cfg).alerts
    assert any("API2" in a and "m/m" in a for a in alerts)
    assert any("supera el presupuesto" in a for a in alerts)


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
    assert "puesto en planta" in md and "indices.png" in files
    assert "comentario de prueba" in md and "escoria" not in md.lower()
