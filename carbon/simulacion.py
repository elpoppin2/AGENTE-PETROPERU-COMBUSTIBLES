"""Simulación de precios a 12 meses y conveniencia de compra (carbón y escoria).

Simulación: cada componente del CFR (FOB y flete) sigue un proceso autorregresivo
en logaritmos, ln p_t = c + φ·ln p_{t-1} + ε, ajustado con la historia mensual desde
2018. Los choques de FOB y flete se simulan correlacionados (como en la historia) y
el CFR de cada camino es FOB + flete. Se reportan los percentiles 10, 25, 50, 75 y 90
de 5,000 caminos. Es una simulación estadística del comportamiento pasado, no un
pronóstico de mercado: no anticipa eventos que la historia no contiene.

Conveniencia de compra (índice 0-100, más alto = más conveniente comprar ahora):
  40% posición del CFR actual en los últimos 36 meses (más barato = mejor)
  30% CFR actual frente a su promedio de 12 meses (por debajo = mejor)
  30% cambio esperado a 12 meses según la simulación (si se espera que suba = mejor comprar ya)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MATERIALES = {
    "carbon": {"fob": "carbon_col_fob", "flete": "carbon_flete", "cfr": "carbon_cfr", "nombre": "carbón"},
    "escoria": {"fob": "escoria_fob", "flete": "escoria_flete", "cfr": "escoria_cfr", "nombre": "escoria"},
}
HORIZONTE = 12
CAMINOS = 5000
SEMILLA = 2026            # misma semilla: misma simulación con los mismos datos
PERCENTILES = (10, 25, 50, 75, 90)
UMBRAL_CONVENIENTE = 65
UMBRAL_ESPERAR = 35


def _ar1(x: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Ajusta ln p_t = c + φ·ln p_{t-1} + ε. φ se acota a [0, 0.995] para que el proceso sea estable."""
    y, x0 = x[1:], x[:-1]
    phi = float(np.clip(np.polyfit(x0, y, 1)[0], 0.0, 0.995)) if np.ptp(x0) > 0 else 0.995
    c = float(np.mean(y - phi * x0))
    return c, phi, y - (c + phi * x0)


def simular(m: pd.DataFrame, material: str, meses: int = HORIZONTE, caminos: int = CAMINOS,
            desde: str = "2018-01") -> pd.DataFrame:
    """Percentiles mensuales de FOB, flete y CFR para los próximos `meses`."""
    cfg = MATERIALES[material]
    if cfg["fob"] not in m or cfg["flete"] not in m:
        return pd.DataFrame()
    datos = m[[cfg["fob"], cfg["flete"]]].loc[desde:].apply(pd.to_numeric, errors="coerce").dropna()
    if len(datos) < 24:
        return pd.DataFrame()
    logs = np.log(datos.clip(lower=0.01).to_numpy())
    ajustes = [_ar1(logs[:, k]) for k in range(2)]
    c = np.array([a[0] for a in ajustes])
    phi = np.array([a[1] for a in ajustes])
    cov = np.cov(np.column_stack([a[2] for a in ajustes]).T) + np.eye(2) * 1e-10
    L = np.linalg.cholesky(cov)
    rng = np.random.default_rng(SEMILLA)
    x = np.tile(logs[-1], (caminos, 1))
    tray = np.empty((caminos, meses, 2))
    for t in range(meses):
        x = c + phi * x + rng.standard_normal((caminos, 2)) @ L.T
        tray[:, t, :] = x
    fob, flete = np.exp(tray[..., 0]), np.exp(tray[..., 1])
    fechas = pd.date_range(datos.index[-1] + pd.offsets.MonthBegin(1), periods=meses, freq="MS")
    filas = []
    for serie, arr in (("fob", fob), ("flete", flete), ("cfr", fob + flete)):
        q = np.percentile(arr, PERCENTILES, axis=0)
        for t, fecha in enumerate(fechas):
            filas.append({"material": material, "serie": serie, "fecha": fecha,
                          **{f"p{p}": float(q[i, t]) for i, p in enumerate(PERCENTILES)}})
    return pd.DataFrame(filas)


def simular_todo(m: pd.DataFrame) -> pd.DataFrame:
    partes = [simular(m, mat) for mat in MATERIALES]
    partes = [p for p in partes if not p.empty]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def conveniencia(m: pd.DataFrame, sim: pd.DataFrame, material: str) -> dict | None:
    """Índice de conveniencia de compra del CFR Conchán y los ratios que lo componen."""
    cfg = MATERIALES[material]
    s = pd.to_numeric(m.get(cfg["cfr"]), errors="coerce").dropna() if cfg["cfr"] in m else pd.Series(dtype=float)
    if len(s) < 12:
        return None
    actual = float(s.iloc[-1])
    ventana = s.tail(36)
    percentil = float((ventana < actual).mean() * 100)
    prom12 = float(s.tail(12).mean())
    desvio = (actual / prom12 - 1) * 100
    futuro = sim[(sim["material"] == material) & (sim["serie"] == "cfr")] if not sim.empty else sim
    esperado = float((futuro.iloc[-1]["p50"] / actual - 1) * 100) if len(futuro) else 0.0
    s_pos = 100 - percentil
    s_prom = float(np.clip(50 - 5 * desvio, 0, 100))
    s_fut = float(np.clip(50 + 5 * esperado, 0, 100))
    indice = 0.4 * s_pos + 0.3 * s_prom + 0.3 * s_fut
    etiqueta = ("Compra conveniente" if indice >= UMBRAL_CONVENIENTE
                else "Conviene esperar" if indice < UMBRAL_ESPERAR else "Neutral")
    flete = pd.to_numeric(m.get(cfg["flete"]), errors="coerce").dropna()
    share = (flete / s).dropna()
    return {
        "material": material, "mes": s.index[-1].strftime("%Y-%m"), "cfr": actual,
        "indice": round(indice, 1), "etiqueta": etiqueta,
        "percentil_36m": round(percentil, 1), "promedio_12m": prom12, "frente_promedio_12m_pct": round(desvio, 2),
        "cambio_esperado_12m_pct": round(esperado, 2),
        "cfr_12m_p10": float(futuro.iloc[-1]["p10"]) if len(futuro) else None,
        "cfr_12m_p50": float(futuro.iloc[-1]["p50"]) if len(futuro) else None,
        "cfr_12m_p90": float(futuro.iloc[-1]["p90"]) if len(futuro) else None,
        "flete_en_cfr_pct": round(float(share.iloc[-1] * 100), 1) if len(share) else None,
        "flete_en_cfr_mediana_36m_pct": round(float(share.tail(36).median() * 100), 1) if len(share) else None,
        "componentes": {"posicion_36m": round(s_pos, 1), "frente_promedio": round(s_prom, 1), "simulacion": round(s_fut, 1)},
    }


def alerta_conveniencia(c: dict | None) -> list[str]:
    """Aviso cuando la compra es conveniente."""
    if not c or c["etiqueta"] != "Compra conveniente":
        return []
    nombre = MATERIALES[c["material"]]["nombre"]
    return [f"🟢 Compra conveniente de {nombre}: CFR Conchán {c['cfr']:,.2f} USD/t "
            f"(índice {c['indice']:.0f}/100; percentil {c['percentil_36m']:.0f} de 36 meses, "
            f"{c['frente_promedio_12m_pct']:+.1f}% frente al promedio de 12 meses; "
            f"la simulación prevé {c['cambio_esperado_12m_pct']:+.1f}% a 12 meses)"]
