"""Teste pentru modul 'Profile Only': data_service.period_profiles + render item.

period_profiles = VP separat per PERIOADA (zi / sesiune) de-a lungul span-ului, fiecare
pozitionat pe axa timpului ([x0,x1]). Reutilizeaza engine-urile VP/Delta + ferestrele de
sesiune existente -> testam structura + invariantii, nu re-testam engine-urile.

Date reale (skip daca lipsesc). E VP ISTORIC (fara cauzalitate/look-ahead de verificat).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # pt render item (QGraphicsObject)

import glob
import numpy as np
import pytest

from data.loader import PARQUET_DIR
from app.desktop.data_service import period_profiles, SESSION_DEFS

_HAVE = bool(glob.glob(os.path.join(PARQUET_DIR, "*.parquet")))
pytestmark = pytest.mark.skipif(not _HAVE, reason="date reale lipsesc (data/parquet)")

DAY = "glbx-mdp3-20260804.trades"
ROW = 2.0


def _valid_profile(p):
    assert p["x0"] < p["x1"], "perioada trebuie sa aiba latime pe axa timpului"
    bp, bb, bs = p["bin_price"], p["bin_buy"], p["bin_sell"]
    assert len(bp) == len(bb) == len(bs) and len(bp) > 0
    assert p["val"] <= p["poc"] + 1e-9 <= p["vah"] + 1e-9, "VAL <= POC <= VAH"
    # split-ul pastreaza volumul total al profilului
    assert abs((bb.sum() + bs.sum()) - p["total"]) < max(1.0, p["total"] * 1e-6)
    assert bb.min() >= -1e-9 and bs.min() >= -1e-9


def test_day_unit_single_profile():
    profs = period_profiles(DAY, mode="session", span="day", unit="Zi", row_size=ROW)
    assert len(profs) == 1
    _valid_profile(profs[0])


def test_ny_session_profile():
    profs = period_profiles(DAY, mode="session", span="day", unit="NY", row_size=ROW,
                            sessions=SESSION_DEFS["real"])
    assert len(profs) == 1                       # o singura sesiune NY intr-o zi
    p = profs[0]
    _valid_profile(p)
    assert "NY" in p["label"]
    # fereastra NY (RTH, ~6.5h) e mai ingusta decat ziua intreaga
    assert (p["x1"] - p["x0"]) <= 8 * 3600


def test_all_sessions_three_profiles():
    profs = period_profiles(DAY, mode="session", span="day", unit="Toate sesiunile",
                            row_size=ROW, sessions=SESSION_DEFS["real"])
    assert 1 <= len(profs) <= 3
    labels = " ".join(p["label"] for p in profs)
    assert "NY" in labels
    for p in profs:
        _valid_profile(p)
    # profilele sunt sortate crescator pe timp
    assert all(profs[i]["x0"] <= profs[i + 1]["x0"] for i in range(len(profs) - 1))


def test_week_unit_multiple_days():
    profs = period_profiles(DAY, mode="session", span="week", unit="Zi", row_size=ROW)
    assert len(profs) >= 2                        # un bloc de zile consecutive
    for p in profs:
        _valid_profile(p)
    assert all(profs[i]["x1"] <= profs[i + 1]["x0"] + 1 for i in range(len(profs) - 1))


def test_deterministic():
    a = period_profiles(DAY, mode="session", span="day", unit="Zi", row_size=ROW)
    b = period_profiles(DAY, mode="session", span="day", unit="Zi", row_size=ROW)
    assert [round(p["poc"], 6) for p in a] == [round(p["poc"], 6) for p in b]


def test_render_item_headless():
    """PeriodProfilesItem accepta datele + expune bounds valide (fara paint live)."""
    from pyqtgraph.Qt import QtWidgets
    from app.desktop.charts import PeriodProfilesItem
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    profs = period_profiles(DAY, mode="session", span="day", unit="Zi", row_size=ROW)
    item = PeriodProfilesItem()
    item.set_data(profs, ROW)
    b = item.data_bounds()
    assert b is not None
    xmin, xmax, pmin, pmax = b
    assert xmin < xmax and pmin < pmax
    assert not item.boundingRect().isNull()
    # gol = fara crash, bounds nule
    item.set_data([], ROW)
    assert item.data_bounds() is None
