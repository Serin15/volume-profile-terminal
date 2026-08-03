"""Developing POC/VA: corectitudine pe date reale.

Blocheaza: (1) valoarea developing finala = POC/VA total (cumulativ = complet);
(2) lungimea = nr. de lumanari; (3) ordine VAL <= POC <= VAH pe tot trail-ul.
Se sare daca fisierul real lipseste.
"""
import os
import numpy as np
import pytest

from data.loader import PARQUET_DIR
from app.desktop.data_service import load_day, developing_levels

DATA_FILE = "glbx-mdp3-20260722.trades.parquet"
ROW = 2.0
INTERVAL = "5min"

pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.path.join(PARQUET_DIR, DATA_FILE)),
    reason="date reale lipsesc (data/parquet)",
)


def test_developing_final_equals_total():
    """Ultima valoare developing = POC/VAH/VAL al profilului complet."""
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=ROW)
    assert len(d.dev_poc) == len(d.t) == len(d.dev_vah) == len(d.dev_val)
    assert abs(d.dev_poc[-1] - d.poc) < 1e-6
    assert abs(d.dev_vah[-1] - d.vah) < 1e-6
    assert abs(d.dev_val[-1] - d.val) < 1e-6


def test_developing_order_invariant():
    """VAL <= POC <= VAH la fiecare pas al trail-ului."""
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=ROW)
    assert np.all(d.dev_val <= d.dev_poc + 1e-9)
    assert np.all(d.dev_poc <= d.dev_vah + 1e-9)


def test_developing_matches_helper():
    """developing_levels reprodus direct din footprint = campul din DayData."""
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=ROW)
    dp, dvah, dval = developing_levels(d.footprint, d.t, ROW, 0.70)
    assert np.allclose(dp, d.dev_poc)
    assert np.allclose(dvah, d.dev_vah)
    assert np.allclose(dval, d.dev_val)


def test_developing_migrates():
    """Trail-ul chiar se dezvolta (POC-ul nu e constant pe toata sesiunea)."""
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=ROW)
    assert len(np.unique(d.dev_poc)) > 1
