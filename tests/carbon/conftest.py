import numpy as np
import pandas as pd
import pytest

from carbon.config import load_config


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def synthetic_wide():
    """Histórico sintético de 30 meses con la forma que produce store.wide()."""
    idx = pd.date_range("2024-04-01", periods=30, freq="MS")
    t = np.arange(len(idx))
    newc = 120 + 10 * np.sin(t / 4)
    api2 = 110 + 8 * np.sin(t / 3)
    w = pd.DataFrame({
        "carbon_newcastle_fob": newc,
        "carbon_api2_cif_ara": api2,
        "brent": 80 + 5 * np.cos(t / 5),
        "fx_pen_usd": 3.7 - 0.005 * t,
    }, index=idx)
    # Comtrade con rezago: sólo hasta 4 meses antes del final
    lag = slice(0, len(idx) - 4)
    w.loc[idx[lag], "co_exp_carbon_pe_fob_usd_t"] = api2[lag] * 0.85
    w.loc[idx[lag], "pe_imp_carbon_col_cif_usd_t"] = api2[lag] * 0.85 + 26
    w.loc[idx[lag], "pe_imp_carbon_col_cif_vol_t"] = 60000.0
    w.loc[idx[lag], "pe_imp_carbon_mundo_cif_vol_t"] = 80000.0
    w.loc[idx[lag], "pe_imp_carbon_mundo_cif_usd_t"] = api2[lag] * 0.85 + 30
    return w
