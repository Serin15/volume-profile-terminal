"""
Test de INTEGRARE (offscreen): construieste fereastra reala si parcurge combinatii
de setari (interval x rezolutie x mod x tip x span), plus intra in replay si navigheaza.

Scop: sa prindem crash-uri sau invarianti incalcati pe FLUXUL COMPLET (GUI -> data_service
-> engine -> render), asa cum ruleaza pe sistemul real. Verifica pe fiecare combinatie:
  - Value Area contine POC (VAL <= POC <= VAH);
  - POC in intervalul de pret afisat;
  - CVD se termina la Cumulative Delta;
  - suma celulelor footprint = totalurile de delta;
  - markerele de absorption au pret valid si tip valid.

Se sare daca lipsesc datele reale.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import glob
import numpy as np
import pytest

from data.loader import PARQUET_DIR
from app.desktop.data_service import BIG_TRADE_MIN

pytestmark = pytest.mark.skipif(
    not glob.glob(os.path.join(PARQUET_DIR, "*.parquet")),
    reason="date reale lipsesc (data/parquet)",
)


@pytest.fixture(scope="module")
def win():
    from pyqtgraph.Qt import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from app.desktop.main import MainWindow
    w = MainWindow()
    yield w


def _check_invariants(d):
    assert len(d.t) > 0
    # Value Area contine POC
    assert d.val <= d.poc <= d.vah, f"VA nu contine POC: {d.val} {d.poc} {d.vah}"
    # POC in intervalul de pret afisat (± un bin)
    assert d.low.min() - d.row_size <= d.poc <= d.high.max() + d.row_size
    # CVD se termina la Cumulative Delta
    assert abs(float(d.cvd[-1]) - d.cum_delta) < 1.0, f"CVD {d.cvd[-1]} != cumΔ {d.cum_delta}"
    # Suma celulelor footprint = totaluri delta engine
    fp_buy = sum(b for cells in d.footprint.values() for (b, s) in cells.values())
    fp_sell = sum(s for cells in d.footprint.values() for (b, s) in cells.values())
    assert abs(fp_buy - d.buy_total) < 1e-5
    assert abs(fp_sell - d.sell_total) < 1e-5
    # Absorption: tip valid + pret in interval (tuple imbogatit: ep,price,kind,buy,sell)
    for entry in d.absorption:
        ep, price, kind = entry[:3]
        assert kind in ("bull", "bear")
        assert d.low.min() - 1e-6 <= price <= d.high.max() + 1e-6
    # Big trades: peste prag
    for bt in d.big_trades:
        assert bt[2] >= BIG_TRADE_MIN


@pytest.mark.parametrize("interval", ["1min", "5min", "1h"])
@pytest.mark.parametrize("res", ["0.25", "2.0"])
@pytest.mark.parametrize("mode", ["Sesiune", "Zi UTC"])
def test_matrix_combos(win, interval, res, mode):
    win.cbo_interval.setCurrentText(interval)
    win.cbo_res.setCurrentText(res)
    win.cbo_period.setCurrentText(mode)
    win.cbo_type.setCurrentText("Profil")
    win._reload()
    _check_invariants(win._data)
    # comuta pe Footprint (doar re-render, aceleasi date)
    win.cbo_type.setCurrentText("Footprint")
    win._reload()
    _check_invariants(win._data)


def test_week_composite(win):
    win.cbo_interval.setCurrentText("15min")
    win.cbo_res.setCurrentText("2.0")
    win.cbo_period.setCurrentText("Composite (saptamana)")
    win._reload()
    _check_invariants(win._data)
    win.cbo_period.setCurrentText("Sesiune")
    win._reload()


def test_visible_range_profile(win):
    win.cbo_interval.setCurrentText("5min")
    win.cbo_res.setCurrentText("2.0")
    win.cbo_period.setCurrentText("Visible (ce vezi)")
    win._reload()
    _check_invariants(win._data)   # datele de baza raman valide
    win.cbo_period.setCurrentText("Custom range (trage)")
    win._reload()
    assert win.custom_region.isVisible()
    _check_invariants(win._data)
    win.cbo_period.setCurrentText("Sesiune")
    win._reload()
    assert not win.custom_region.isVisible()


def test_replay_navigation_no_crash(win):
    win.cbo_interval.setCurrentText("5min")
    win.cbo_res.setCurrentText("2.0")
    win.cbo_period.setCurrentText("Sesiune")
    win._reload()
    win.btn_replay.setChecked(True)
    for _ in range(30):
        win._replay_tick()
    _check_invariants(win._data)
    n = win._replay.n_candles
    win._seek_to(n // 2); _check_invariants(win._data)
    win._step_bars(+1); _check_invariants(win._data)
    win._step_bars(-1); _check_invariants(win._data)
    win._seek_to(0); _check_invariants(win._data)
    win._seek_to(10 ** 9); _check_invariants(win._data)
    win.btn_replay.setChecked(False)   # iesire din replay


def test_drawings_no_crash(win):
    dm = win.draw_mgr
    dm.set_tool("hline"); dm.add_point(0, float(win._data.poc))
    dm.set_tool("trend"); dm.add_point(float(win._data.t[0]), float(win._data.low.min()))
    dm.add_point(float(win._data.t[-1]), float(win._data.high.max()))
    dm.set_tool("rect"); dm.add_point(float(win._data.t[0]), float(win._data.val))
    dm.add_point(float(win._data.t[-1]), float(win._data.vah))
    assert len(dm.items) == 3
    dm.undo(); assert len(dm.items) == 2
    dm.clear(); assert len(dm.items) == 0
