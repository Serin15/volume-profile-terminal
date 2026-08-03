"""
Test de CORECTITUDINE pentru nivelurile SESIUNII PRECEDENTE (backtesting).

Blocheaza: yPOC/yVAH/yVAL/PDH/PDL ale zilei = valorile sesiunii precedente incarcate
independent; ordinea nivelurilor e coerenta; prima zi disponibila (fara precedent) = None.

Se sare daca lipsesc datele reale.
"""

import os
import pytest

from data.loader import PARQUET_DIR
from app.desktop.data_service import prior_session_levels, load_day

DAY = "glbx-mdp3-20260722.trades.parquet"       # sesiunea precedenta = 21 iul
PRIOR = "glbx-mdp3-20260721.trades.parquet"
FIRST = "glbx-mdp3-20260504.trades.parquet"     # prima zi (fara precedent in bloc)

pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.path.join(PARQUET_DIR, DAY)),
    reason="date reale lipsesc (data/parquet)",
)


def test_prior_levels_match_prior_day_load():
    p = prior_session_levels(DAY, mode="session", va_percent=0.70, row_size=2.0)
    assert p is not None
    d_prior = load_day(PRIOR, mode="session", interval="5min", row_size=2.0)
    assert abs(p["poc"] - d_prior.poc) < 1e-6
    assert abs(p["vah"] - d_prior.vah) < 1e-6
    assert abs(p["val"] - d_prior.val) < 1e-6
    assert abs(p["high"] - float(d_prior.high.max())) < 1e-6
    assert abs(p["low"] - float(d_prior.low.min())) < 1e-6


def test_prior_levels_ordered():
    p = prior_session_levels(DAY, mode="session", va_percent=0.70, row_size=2.0)
    assert p["low"] <= p["val"] <= p["poc"] <= p["vah"] <= p["high"]


@pytest.mark.skipif(not os.path.isfile(os.path.join(PARQUET_DIR, FIRST)),
                    reason="prima zi lipseste")
def test_first_day_has_no_prior():
    # 4 mai e prima zi din blocul mai; nu exista sesiune anterioara descarcata
    assert prior_session_levels(FIRST, mode="session") is None
