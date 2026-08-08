"""
P4.2 — teste pentru componenta PRICE PROGRESS (efort vs rezultat) din ContextEngine.

Deterministe, sintetice. Construim un fundal UNIFORM (delta constant/bara, close liniar)
-> scala adaptiva a efortului si a rezultatului sunt constante cunoscute; apoi setam
fereastra CURENTA ca sa cadem in fiecare din cele 5 cazuri.

Fundal implicit: bg_delta=20 -> agg_scale = |3*20| = 60; bg_slope=1 -> progress_scale = 3.
Praguri: high_ratio=1.3 (>=78 / >=3.9 = HIGH), low_ratio=0.6 (<=36 / <=1.8 = LOW).
"""

import numpy as np

from core import (Snapshot, analyze_price_progress, ContextEngine, PriceProgressContext,
                  PRICE_PROGRESS_STATES, snapshot_from_daydata)
from app.desktop.data_service import DayData

W = 3


def _snap_pp(cur_deltas, cur_price_change, bg_delta=20.0, bg_slope=1.0, n_bg=9,
             tick=0.25, base=1_800_000_000):
    """Snapshot cu fundal uniform + o fereastra curenta controlata (ultimele W bare)."""
    deltas = [float(bg_delta)] * n_bg + [float(x) for x in cur_deltas]
    n = len(deltas)
    close = [1000.0 + i * bg_slope for i in range(n_bg)]
    anchor = close[-1]                                   # close[n_bg-1] = close[n-W-1]
    for j in range(W):                                   # barele curente: liniar pana la +cur_price_change
        close.append(anchor + cur_price_change * (j + 1) / W)
    close = np.asarray(close, dtype=float)
    cvd = np.cumsum(deltas)
    t = np.arange(n, dtype=float) * 60.0 + base
    z = np.zeros(n)
    return Snapshot(now_epoch=int(t[-1]), bar_seconds=60, t=t, open=close.copy(),
                    high=close.copy(), low=close.copy(), close=close, volume=z + 10.0,
                    cvd=cvd, poc=0.0, vah=0.0, val=0.0, footprint={}, row_size=2.0,
                    symbol="T", tick_size=tick)


def _state(cur_deltas, cur_price_change, cfg=None, **kw):
    return analyze_price_progress(_snap_pp(cur_deltas, cur_price_change, **kw), cfg).state


# ---------------------------------------------------------------- cele 5 cazuri
def test_high_aggression_high_progress():
    assert _state([-60, -60, -60], -12.0) == "AGGRESSION_WITH_PROGRESS"


def test_high_aggression_low_progress():
    # efort mare (180), progres mic (1 tick-punct) -> agresiune neproductiva
    assert _state([-60, -60, -60], -1.0) == "AGGRESSION_WITHOUT_PROGRESS"


def test_low_aggression_high_progress():
    assert _state([8, 8, 8], 12.0) == "PROGRESS_WITHOUT_AGGRESSION"


def test_low_aggression_low_progress():
    assert _state([8, 8, 8], 1.0) == "QUIET"


def test_medium_is_neutral():
    # efort = scala (60), progres = scala (3) -> ambele MEDIUM -> NEUTRAL
    assert _state([20, 20, 20], 3.0) == "NEUTRAL"


def test_insufficient_evidence_when_too_few_bars():
    deltas = [10.0, 20.0, 30.0, 40.0]          # n=4 < 2*W+1=7
    close = np.array([1000.0, 1001.0, 1002.0, 1003.0])
    snap = Snapshot(now_epoch=1, bar_seconds=60, t=np.arange(4.0), open=close.copy(),
                    high=close.copy(), low=close.copy(), close=close, volume=np.zeros(4),
                    cvd=np.cumsum(deltas), poc=0.0, vah=0.0, val=0.0, footprint={},
                    row_size=2.0, symbol="T")
    assert analyze_price_progress(snap).state == "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------- efort vs rezultat, nu "confirmare"
def test_delta_and_price_opposed_is_not_confirmation():
    """Delta POZITIVA + pret in SCADERE: agresiune mare, dar NU o clasificam bullish/bearish;
    doar magnitudinea (efort vs progres) + alinierea directiei ca observatie separata."""
    pp = analyze_price_progress(_snap_pp([60, 60, 60], -12.0))
    assert pp.direction_alignment == "OPPOSED"
    assert pp.state in PRICE_PROGRESS_STATES
    assert "BULLISH" not in pp.state and "BEARISH" not in pp.state


def test_efficiency_effort_vs_result():
    """Efort mic cu progres mare = eficienta mare; efort mare cu progres mic = eficienta mica."""
    low_eff = analyze_price_progress(_snap_pp([-60, -60, -60], -1.0))   # 1/180
    high_eff = analyze_price_progress(_snap_pp([8, 8, 8], 12.0))        # 12/24
    assert high_eff.efficiency > low_eff.efficiency


# ---------------------------------------------------------------- praguri adaptive + config
def test_thresholds_adaptive_to_scale():
    """Aceeasi forma x10 (efort si progres) -> aceeasi stare (praguri relative, nu absolute)."""
    base = _state([-60, -60, -60], -12.0)
    scaled = _state([-600, -600, -600], -120.0, bg_delta=200.0, bg_slope=10.0)
    assert base == scaled == "AGGRESSION_WITH_PROGRESS"


def test_config_override_changes_levels():
    """high_ratio urias -> nimic nu mai e HIGH -> cazul 'mare/mare' devine NEUTRAL."""
    assert _state([-60, -60, -60], -12.0, cfg={"high_ratio": 100.0}) == "NEUTRAL"


def test_state_always_in_known_set():
    for cd, pc in ([-60, -60, -60], -12.0), ([8, 8, 8], 1.0), ([20, 20, 20], 3.0):
        assert analyze_price_progress(_snap_pp(cd, pc)).state in PRICE_PROGRESS_STATES


# ---------------------------------------------------------------- no-look-ahead + determinism
def _make_day_pp(deltas, closes, bar=60, base=1_800_000_000):
    deltas = np.asarray(deltas, dtype=float)
    closes = np.asarray(closes, dtype=float)
    n = len(deltas)
    t = np.arange(n, dtype=float) * bar + base
    cvd = np.cumsum(deltas) if n else np.zeros(0)
    fp = {int(round(t[i])): {100.0: [float(max(deltas[i], 0.0) + 1.0),
                                     float(max(-deltas[i], 0.0) + 1.0)]} for i in range(n)}
    dev = np.full(n, 100.0)
    return DayData(symbol="T", n_ticks=n, t=t, open=closes.copy(), high=closes.copy(),
                   low=closes.copy(), close=closes, volume=np.zeros(n) + 10.0,
                   vwap=closes.copy(), cvd=cvd, last_price=float(closes[-1]) if n else 0.0,
                   bar_seconds=bar, bin_price=np.array([100.0]), bin_buy=np.array([1.0]),
                   bin_sell=np.array([1.0]), row_size=2.0, poc=999.0, vah=1005.0, val=995.0,
                   footprint=fp, dev_poc=dev, dev_vah=dev + 5, dev_val=dev - 5)


def test_price_progress_no_look_ahead():
    deltas = [10.0, -20.0, 30.0, -40.0, 50.0, -60.0, 70.0, -80.0]
    closes = [1000.0 + i for i in range(8)]
    full = _make_day_pp(deltas, closes)
    ended = _make_day_pp(deltas[:6], closes[:6])
    a = analyze_price_progress(snapshot_from_daydata(full, upto_index=5))
    b = analyze_price_progress(snapshot_from_daydata(ended, upto_index=5))
    assert a == b


def test_price_progress_determinism():
    day = _make_day_pp([10, 20, 30, 10, 20, 30, 10, 20],
                       [1000.0 + i for i in range(8)])
    snap = snapshot_from_daydata(day, upto_index=7)
    assert analyze_price_progress(snap) == analyze_price_progress(snap)


def test_engine_populates_price_progress_and_keeps_delta():
    day = _make_day_pp([10, 20, 30, 10, 20, 30, 10, 20],
                       [1000.0 + i for i in range(8)])
    res = ContextEngine().analyze(snapshot_from_daydata(day, upto_index=7))
    assert "price_progress" in res.components
    assert isinstance(res.components["price_progress"], PriceProgressContext)
    assert "delta" in res.components            # P4.1 ramane (aditiv, compatibil)
    assert ContextEngine().analyze(snapshot_from_daydata(day, upto_index=7)) == res
