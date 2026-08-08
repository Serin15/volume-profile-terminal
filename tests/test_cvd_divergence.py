"""
P4.4 — teste pentru CVD DIVERGENCE (structural, cauzal) din ContextEngine.

Deterministe, sintetice. Construim serii de high/low/cvd cu swing-uri STRUCTURALE clare
(brate L=R=3) si verificam divergentele + tranzitia FORMING -> CONFIRMED (swing-ul recent
nu se confirma pana nu trec R bare) + no-look-ahead + determinism.
"""

import os
import numpy as np
import pytest

from core import (Snapshot, ContextEngine, snapshot_from_daydata,
                  analyze_cvd_divergence, CvdDivergenceContext, CVD_DIVERGENCE_STATES)
from app.desktop.data_service import DayData


def _snap(high, low, cvd, close=None, tick=0.25, base=1_800_000_000):
    high = np.asarray(high, float); low = np.asarray(low, float); cvd = np.asarray(cvd, float)
    n = len(high)
    close = (high + low) / 2.0 if close is None else np.asarray(close, float)
    t = np.arange(n, dtype=float) * 60 + base
    return Snapshot(now_epoch=int(t[-1]) if n else 0, bar_seconds=60, t=t, open=close.copy(),
                    high=high, low=low, close=close, volume=np.zeros(n) + 10.0, cvd=cvd,
                    poc=0.0, vah=0.0, val=0.0, footprint={}, row_size=1.0, symbol="T", tick_size=tick)


def _make_day(high, low, cvd):
    high = np.asarray(high, float); low = np.asarray(low, float); cvd = np.asarray(cvd, float)
    n = len(high); close = (high + low) / 2.0
    t = np.arange(n, dtype=float) * 60 + 1_800_000_000
    dev = np.full(n, 100.0)
    return DayData(symbol="T", n_ticks=n, t=t, open=close.copy(), high=high, low=low, close=close,
                   volume=np.zeros(n) + 10.0, vwap=close.copy(), cvd=cvd,
                   last_price=float(close[-1]) if n else 0.0, bar_seconds=60,
                   bin_price=np.array([100.0]), bin_buy=np.array([1.0]), bin_sell=np.array([1.0]),
                   row_size=1.0, poc=999.0, vah=1005.0, val=995.0, footprint={},
                   dev_poc=dev, dev_vah=dev + 5, dev_val=dev - 5)


# --- scenarii: swing highs la k=4 si k=10 (al doilea mai sus), swing lows analog ---
_HIGH = [10, 11, 12, 13, 20, 14, 13, 12, 13, 15, 24, 17, 16, 15, 14, 13]
_LOW_FLAT = [h - 2 for h in _HIGH]
_CVD_BEAR = [0, 20, 40, 60, 100, 90, 85, 80, 85, 92, 70, 65, 60, 58, 56, 54]   # cvd LOWER la al 2-lea high
_CVD_NODIV = [0, 20, 40, 60, 100, 90, 95, 100, 110, 120, 130, 125, 120, 118, 116, 114]  # cvd HIGHER

_LOW = [20, 19, 18, 17, 10, 16, 17, 18, 17, 15, 6, 13, 14, 15, 16, 17]         # swing lows k=4,10 (lower low)
_HIGH_FLAT = [l + 2 for l in _LOW]
_CVD_BULL = [0, -20, -40, -60, -100, -90, -85, -80, -85, -92, -70, -65, -60, -58, -56, -54]  # cvd HIGHER la al 2-lea low


def test_bearish_divergence():
    d = analyze_cvd_divergence(_snap(_HIGH, _LOW_FLAT, _CVD_BEAR))
    assert d.state == "BEARISH_DIVERGENCE"
    assert d.status == "CONFIRMED"
    assert d.price_swing_direction == "HIGHER_HIGH"
    assert d.cvd_swing_direction == "LOWER"


def test_bullish_divergence():
    d = analyze_cvd_divergence(_snap(_HIGH_FLAT, _LOW, _CVD_BULL))
    assert d.state == "BULLISH_DIVERGENCE"
    assert d.status == "CONFIRMED"
    assert d.price_swing_direction == "LOWER_LOW"
    assert d.cvd_swing_direction == "HIGHER"


def test_no_divergence_when_cvd_confirms():
    d = analyze_cvd_divergence(_snap(_HIGH, _LOW_FLAT, _CVD_NODIV))
    assert d.state == "NO_DIVERGENCE"
    assert d.price_swing_direction == "HIGHER_HIGH"


def test_insufficient_evidence_few_bars():
    d = analyze_cvd_divergence(_snap([10, 11, 12, 13, 12], [8, 9, 10, 11, 10], [0, 10, 20, 30, 20]))
    assert d.state == "INSUFFICIENT_EVIDENCE"


def test_weak_noisy_divergence_is_not_flagged():
    """Higher high dar gap CVD sub pragul adaptiv (zgomot mare) -> NO_DIVERGENCE."""
    noisy = [0, 50, 0, 60, 100, 40, 90, 30, 80, 20, 99, 40, 80, 30, 70, 20]  # std mare -> cvd_min mare
    d = analyze_cvd_divergence(_snap(_HIGH, _LOW_FLAT, noisy))
    assert d.state == "NO_DIVERGENCE"        # dc = 99-100 = -1, sub pragul adaptiv


def test_adaptive_scaling_same_result_x10():
    base = analyze_cvd_divergence(_snap(_HIGH, _LOW_FLAT, _CVD_BEAR)).state
    scaled = analyze_cvd_divergence(_snap([h * 10 for h in _HIGH], [l * 10 for l in _LOW_FLAT],
                                          [c * 10 for c in _CVD_BEAR])).state
    assert base == scaled == "BEARISH_DIVERGENCE"


def test_structural_not_consecutive_bars():
    """Zigzag pe fiecare bara (fara swing-uri structurale) -> nu declara divergenta confirmata."""
    hi = [10, 12] * 8
    lo = [8, 10] * 8
    cv = list(range(16))
    d = analyze_cvd_divergence(_snap(hi, lo, cv))
    assert d.state in ("NO_DIVERGENCE", "INSUFFICIENT_EVIDENCE")
    assert not (d.state.endswith("DIVERGENCE") and d.status == "CONFIRMED"
                and d.state != "NO_DIVERGENCE")


def test_forming_before_confirmation_then_confirmed():
    """Al doilea swing high (k=10) e PENDING pana trec R=3 bare -> FORMING; apoi CONFIRMED."""
    forming = analyze_cvd_divergence(_snap(_HIGH[:12], _LOW_FLAT[:12], _CVD_BEAR[:12]))  # last=11
    assert forming.state == "BEARISH_DIVERGENCE"
    assert forming.status == "FORMING"
    confirmed = analyze_cvd_divergence(_snap(_HIGH[:14], _LOW_FLAT[:14], _CVD_BEAR[:14]))  # last=13
    assert confirmed.state == "BEARISH_DIVERGENCE"
    assert confirmed.status == "CONFIRMED"


def test_slope_and_momentum_present():
    d = analyze_cvd_divergence(_snap(_HIGH, _LOW_FLAT, _CVD_BEAR))
    assert d.cvd_momentum in ("RISING", "FALLING", "FLAT")
    assert isinstance(d.cvd_slope, float)
    assert d.cvd_value == float(_CVD_BEAR[-1])


def test_reference_swings_reported():
    d = analyze_cvd_divergence(_snap(_HIGH, _LOW_FLAT, _CVD_BEAR))
    assert d.ref1_price == 20.0 and d.ref2_price == 24.0     # cele doua swing highs
    assert d.ref1_cvd == 100.0 and d.ref2_cvd == 70.0
    assert d.ref2_epoch > d.ref1_epoch


def test_state_always_in_known_set():
    for hi, lo, cv in ((_HIGH, _LOW_FLAT, _CVD_BEAR), (_HIGH_FLAT, _LOW, _CVD_BULL),
                       (_HIGH, _LOW_FLAT, _CVD_NODIV), ([10, 11, 12], [8, 9, 10], [0, 1, 2])):
        assert analyze_cvd_divergence(_snap(hi, lo, cv)).state in CVD_DIVERGENCE_STATES


# --- no-look-ahead + determinism ---
def test_no_look_ahead():
    full = _make_day(_HIGH, _LOW_FLAT, _CVD_BEAR)
    ended = _make_day(_HIGH[:12], _LOW_FLAT[:12], _CVD_BEAR[:12])
    a = analyze_cvd_divergence(snapshot_from_daydata(full, upto_index=11))
    b = analyze_cvd_divergence(snapshot_from_daydata(ended, upto_index=11))
    assert a == b
    assert a.status == "FORMING"                              # la T=11 al 2-lea swing e pending
    assert analyze_cvd_divergence(snapshot_from_daydata(full, upto_index=13)).status == "CONFIRMED"


def test_determinism():
    snap = snapshot_from_daydata(_make_day(_HIGH, _LOW_FLAT, _CVD_BEAR), upto_index=15)
    assert analyze_cvd_divergence(snap) == analyze_cvd_divergence(snap)


def test_engine_keeps_all_five_components():
    res = ContextEngine().analyze(snapshot_from_daydata(_make_day(_HIGH, _LOW_FLAT, _CVD_BEAR), 15))
    for name in ("delta", "price_progress", "absorption", "exhaustion", "cvd_divergence"):
        assert name in res.components
    assert isinstance(res.components["cvd_divergence"], CvdDivergenceContext)


# --- date reale (skippable) ---
from data.loader import PARQUET_DIR
_REAL = "glbx-mdp3-20260804.trades.parquet"


@pytest.mark.skipif(not os.path.isfile(os.path.join(PARQUET_DIR, _REAL)),
                    reason="date reale lipsesc")
def test_cvd_divergence_runs_on_real_data():
    from app.desktop.data_service import load_day
    day = load_day(_REAL, mode="session", interval="5min", row_size=2.0)
    eng = ContextEngine()
    seen = set()
    for i in range(len(day.t)):
        d = eng.analyze(snapshot_from_daydata(day, upto_index=i)).components["cvd_divergence"]
        assert d.state in CVD_DIVERGENCE_STATES
        seen.add(d.state)
    # pe o sesiune intreaga ar trebui sa apara si divergente (nu doar NO/INSUFFICIENT)
    assert {"BULLISH_DIVERGENCE", "BEARISH_DIVERGENCE"} & seen
