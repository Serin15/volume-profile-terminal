"""
Test de CORECTITUDINE pentru detectia de Absorption (date sintetice, deterministe).

Verifica LOGICA detectorului, independent de date reale:
  - bull absorption: vanzare agresiva mare la MINIM + inchidere sus -> semnal bull la low;
  - bear absorption: cumparare agresiva mare la MAXIM + inchidere jos -> semnal bear la high;
  - candela echilibrata / sub prag -> NICIUN semnal (fara fals-pozitive);
  - lumanarea in formare (exclude_last) nu produce semnal.
"""

import numpy as np

from app.desktop.data_service import (
    detect_absorption, ABS_MIN_VOL, ABS_DOM, ABS_FRAC, ABS_REJECT,
)


def _candle(cells):
    """footprint {epoch: {pret: [buy, sell]}} pentru o singura lumanare la epoch=0."""
    return {0: cells}


def test_bull_absorption_fires():
    # Minim 100-101 cu vanzare agresiva grea, inchidere sus (respingere de jos)
    cells = {100.0: [5.0, 120.0], 101.0: [5.0, 120.0],   # low zone: sell domina
             105.0: [30.0, 30.0], 109.0: [40.0, 20.0], 110.0: [20.0, 10.0]}
    t = np.array([0.0]); high = np.array([110.0]); low = np.array([100.0]); close = np.array([109.0])
    out = detect_absorption(_candle(cells), t, high, low, close, row_size=1.0)
    assert any(e[:3] == (0, 100.0, "bull") for e in out), out
    assert not any(e[2] == "bear" for e in out)
    e = next(e for e in out if e[2] == "bull")   # carry volum buy/sell zona (pt tooltip)
    assert e[3] == 10.0 and e[4] == 240.0, e


def test_bear_absorption_fires():
    # Maxim 109-110 cu cumparare agresiva grea, inchidere jos (respingere de sus)
    cells = {100.0: [10.0, 20.0], 101.0: [30.0, 30.0], 105.0: [30.0, 30.0],
             109.0: [120.0, 5.0], 110.0: [120.0, 5.0]}   # high zone: buy domina
    t = np.array([0.0]); high = np.array([110.0]); low = np.array([100.0]); close = np.array([101.0])
    out = detect_absorption(_candle(cells), t, high, low, close, row_size=1.0)
    assert any(e[:3] == (0, 110.0, "bear") for e in out), out
    assert not any(e[2] == "bull" for e in out)


def test_balanced_candle_no_signal():
    # Volume echilibrate, inchidere la mijloc -> niciun semnal
    cells = {100.0: [50.0, 50.0], 101.0: [50.0, 50.0], 105.0: [50.0, 50.0],
             109.0: [50.0, 50.0], 110.0: [50.0, 50.0]}
    t = np.array([0.0]); high = np.array([110.0]); low = np.array([100.0]); close = np.array([105.0])
    out = detect_absorption(_candle(cells), t, high, low, close, row_size=1.0)
    assert out == [], out


def test_below_min_volume_no_signal():
    # Aceeasi forma ca bull dar volum sub ABS_MIN_VOL -> nimic
    v = ABS_MIN_VOL * 0.3
    cells = {100.0: [1.0, v], 101.0: [1.0, v], 110.0: [5.0, 5.0]}
    t = np.array([0.0]); high = np.array([110.0]); low = np.array([100.0]); close = np.array([109.0])
    out = detect_absorption(_candle(cells), t, high, low, close, row_size=1.0)
    assert out == [], out


def test_no_rejection_no_signal():
    # Vanzare grea la minim DAR inchidere tot jos (fara respingere) -> nu e absorbtie
    cells = {100.0: [5.0, 200.0], 101.0: [5.0, 200.0], 110.0: [10.0, 10.0]}
    t = np.array([0.0]); high = np.array([110.0]); low = np.array([100.0]); close = np.array([100.5])
    out = detect_absorption(_candle(cells), t, high, low, close, row_size=1.0)
    assert out == [], out


def test_exclude_last_skips_forming_candle():
    cells = {100.0: [5.0, 120.0], 101.0: [5.0, 120.0], 110.0: [20.0, 10.0]}
    t = np.array([0.0]); high = np.array([110.0]); low = np.array([100.0]); close = np.array([109.0])
    out = detect_absorption(_candle(cells), t, high, low, close, row_size=1.0, exclude_last=True)
    assert out == [], out
