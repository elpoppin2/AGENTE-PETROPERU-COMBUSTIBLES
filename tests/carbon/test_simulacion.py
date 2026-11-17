import numpy as np
import pandas as pd
import pytest

from carbon import analytics, simulacion, store


def _mensual(valores, inicio="2019-01-01"):
    return pd.Series(valores, index=pd.date_range(inicio, periods=len(valores), freq="MS"), dtype=float)


def _modelo(cfr_fob, flete):
    m = pd.DataFrame({"carbon_col_fob": cfr_fob, "carbon_flete": flete})
    m["carbon_cfr"] = m["carbon_col_fob"] + m["carbon_flete"]
    return m


def test_simulacion_percentiles_ordenados_y_reproducibles():
    t = np.arange(60)
    m = _modelo(_mensual(110 + 15 * np.sin(t / 5)), _mensual(28 + 3 * np.cos(t / 7)))
    sim = simulacion.simular(m, "carbon")
    assert set(sim["serie"]) == {"fob", "flete", "cfr"} and len(sim) == 3 * simulacion.HORIZONTE
    assert (sim["p10"] <= sim["p50"]).all() and (sim["p50"] <= sim["p90"]).all()
    assert sim["fecha"].min() == pd.Timestamp("2024-01-01")              # mes siguiente al último dato
    pd.testing.assert_frame_equal(sim, simulacion.simular(m, "carbon"))   # misma semilla, mismo resultado


def test_conveniencia_compra_barata_y_cara():
    t = np.arange(60)
    base = 120 + 20 * np.sin(t / 4)
    barato = _modelo(_mensual(np.append(base, 85.0)), _mensual(np.full(61, 25.0)))
    caro = _modelo(_mensual(np.append(base, 160.0)), _mensual(np.full(61, 25.0)))
    for m, esperado in ((barato, "Compra conveniente"), (caro, "Conviene esperar")):
        c = simulacion.conveniencia(m, simulacion.simular(m, "carbon"), "carbon")
        assert c["etiqueta"] == esperado, c
    c = simulacion.conveniencia(barato, simulacion.simular(barato, "carbon"), "carbon")
    assert c["percentil_36m"] == 0 and c["frente_promedio_12m_pct"] < 0
    aviso = simulacion.alerta_conveniencia(c)
    assert len(aviso) == 1 and aviso[0].startswith("🟢 Compra conveniente de carbón")
    assert simulacion.alerta_conveniencia(simulacion.conveniencia(caro, simulacion.simular(caro, "carbon"), "carbon")) == []


def test_compute_incluye_simulacion_y_conveniencia(synthetic_wide, cfg):
    res = analytics.compute(synthetic_wide, cfg)
    assert {"carbon", "escoria"} <= set(res.simulacion["material"])
    assert res.meta["conveniencia"]["carbon"]["etiqueta"] in ("Compra conveniente", "Neutral", "Conviene esperar")


def test_quitar_series_manuales(tmp_path):
    path = tmp_path / "series.csv"
    df = pd.DataFrame({"fecha": pd.to_datetime(["2026-10-01", "2026-10-01"]), "serie": ["brent", "manual_carbon_fob"],
                       "valor": [80.0, 120.0], "unidad": "x", "fuente": "y"})
    store.upsert(path, df)
    store.quitar_series(path, "manual_")
    assert list(store.load(path)["serie"]) == ["brent"]
