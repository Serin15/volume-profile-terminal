"""
P4.1 — teste pentru componenta DELTA (analyze_delta) din ContextEngine.

Deterministe, sintetice (nu depind de date reale). Controlam exact secventa de delta
setand cvd = cumsum(deltas) intr-un Snapshot minimal, apoi verificam clasificarea.

Acopera cele 10 categorii cerute: delta pozitiv/negativ, flip, agresiune de cumparare/
vanzare crescatoare, decelerare, zgomot/neutral, conditii de margine, no-look-ahead,
determinism. Plus: praguri adaptive/configurabile si "nu e pozitiv=BUY".
"""

import numpy as np

from core import (Snapshot, analyze_delta, ContextEngine, DeltaContext,
                  DELTA_STATES, snapshot_from_daydata)
from app.desktop.data_service import DayData


def _snap(deltas):
    """Snapshot minimal cu o secventa de delta data (cvd = cumsum)."""
    deltas = np.asarray(deltas, dtype=float)
    n = len(deltas)
    cvd = np.cumsum(deltas) if n else np.zeros(0)
    t = np.arange(n, dtype=float) * 60.0 + 1_800_000_000
    z = np.zeros(n)
    return Snapshot(now_epoch=int(t[-1]) if n else 0, bar_seconds=60,
                    t=t, open=z.copy(), high=z.copy(), low=z.copy(), close=z.copy(),
                    volume=z.copy(), cvd=cvd, poc=0.0, vah=0.0, val=0.0,
                    footprint={}, row_size=2.0, symbol="TEST")


def _state(deltas, cfg=None):
    return analyze_delta(_snap(deltas), cfg).sequence_state


# ---------------------------------------------------------------- 1-2. semn simplu
def test_positive_delta_is_buying_not_generic_buy():
    dc = analyze_delta(_snap([100.0]))
    assert dc.delta_direction == "POSITIVE"
    assert dc.sequence_state.startswith("BUYING")


def test_negative_delta_is_selling():
    dc = analyze_delta(_snap([-100.0]))
    assert dc.delta_direction == "NEGATIVE"
    assert dc.sequence_state.startswith("SELLING")


# ---------------------------------------------------------------- 3. flip
def test_delta_flip_detected():
    assert _state([-100.0, -80.0, 120.0]) == "DELTA_FLIP"
    assert _state([90.0, 70.0, -110.0]) == "DELTA_FLIP"


def test_flip_is_not_reported_as_plain_buy():
    """Un flip de la vanzare la cumparare NU e clasificat 'BUYING_...', ci DELTA_FLIP."""
    dc = analyze_delta(_snap([-100.0, -80.0, 120.0]))
    assert dc.delta_direction == "POSITIVE"          # delta curent e pozitiv
    assert dc.sequence_state == "DELTA_FLIP"          # dar starea = flip, nu "buy"


# ---------------------------------------------------------------- 4-5. agresiune crescatoare
def test_increasing_buying_aggression_accelerates():
    assert _state([40.0, 80.0, 160.0]) == "BUYING_ACCELERATION"


def test_increasing_selling_aggression_accelerates():
    assert _state([-40.0, -80.0, -160.0]) == "SELLING_ACCELERATION"


# ---------------------------------------------------------------- 6. decelerare
def test_selling_deceleration():
    assert _state([-200.0, -140.0, -90.0]) == "SELLING_DECELERATION"


def test_buying_deceleration():
    assert _state([200.0, 140.0, 90.0]) == "BUYING_DECELERATION"


# ---------------------------------------------------------------- 7. zgomot / neutral
def test_small_current_delta_after_activity_is_neutral():
    assert _state([60.0, -55.0, 58.0, 5.0]) == "NEUTRAL"


def test_all_zero_delta_is_neutral():
    assert _state([0.0, 0.0, 0.0]) == "NEUTRAL"


# ---------------------------------------------------------------- 8. margini
def test_empty_snapshot_delta_is_safe_neutral():
    dc = analyze_delta(_snap([]))
    assert dc.sequence_state == "NEUTRAL"
    assert dc.current_delta == 0.0
    assert dc.previous_delta is None
    assert dc.delta_change is None
    assert dc.recent_sequence == []


def test_single_bar_has_no_previous():
    dc = analyze_delta(_snap([120.0]))
    assert dc.previous_delta is None
    assert dc.delta_change is None
    assert dc.acceleration == "STEADY"


def test_state_always_in_known_set():
    for seq in ([100.0], [-100.0], [-100.0, -80.0, 120.0], [40.0, 80.0, 160.0],
                [-200.0, -140.0, -90.0], [60.0, -55.0, 58.0, 5.0], [0.0, 0.0], []):
        assert analyze_delta(_snap(seq)).sequence_state in DELTA_STATES


def test_delta_change_and_direction_values():
    dc = analyze_delta(_snap([50.0, 130.0]))
    assert dc.current_delta == 130.0
    assert dc.previous_delta == 50.0
    assert dc.delta_change == 80.0


# ---------------------------------------------------------------- praguri adaptive/config
def test_thresholds_are_adaptive_to_scale():
    """Aceeasi FORMA (x10) da aceeasi stare -> pragurile-s relative la scala, nu absolute."""
    assert _state([40.0, 80.0, 160.0]) == _state([400.0, 800.0, 1600.0])


def test_config_override_changes_neutral_band():
    """neutral_ratio urias -> chiar si o delta clara devine NEUTRAL (prag configurabil)."""
    assert _state([40.0, 80.0, 160.0], {"neutral_ratio": 100.0}) == "NEUTRAL"


# ---------------------------------------------------------------- 9-10. no-look-ahead + determinism
def _make_day(deltas, bar=60, base=1_800_000_000):
    deltas = np.asarray(deltas, dtype=float)
    n = len(deltas)
    t = np.arange(n, dtype=float) * bar + base
    cvd = np.cumsum(deltas) if n else np.zeros(0)
    close = np.arange(n, dtype=float) + 100.0
    vol = np.zeros(n) + 10.0
    fp = {int(round(t[i])): {100.0: [float(max(deltas[i], 0.0) + 1.0),
                                     float(max(-deltas[i], 0.0) + 1.0)]} for i in range(n)}
    dev = np.full(n, 100.0)
    return DayData(symbol="T", n_ticks=n, t=t, open=close.copy(), high=close.copy(),
                   low=close.copy(), close=close, volume=vol, vwap=close.copy(),
                   cvd=cvd, last_price=float(close[-1]) if n else 0.0, bar_seconds=bar,
                   bin_price=np.array([100.0]), bin_buy=np.array([1.0]),
                   bin_sell=np.array([1.0]), row_size=2.0,
                   poc=999.0, vah=1005.0, val=995.0, footprint=fp,
                   dev_poc=dev, dev_vah=dev + 5, dev_val=dev - 5)


def test_delta_no_look_ahead():
    """Delta la T=3 e IDENTIC fie ca ziua continua (8 bare) fie ca s-a terminat la T (4 bare)."""
    full = _make_day([1.0, -2.0, 3.0, -4.0, 5.0, -6.0, 7.0, -8.0])
    ended = _make_day([1.0, -2.0, 3.0, -4.0])
    a = analyze_delta(snapshot_from_daydata(full, upto_index=3))
    b = analyze_delta(snapshot_from_daydata(ended, upto_index=3))
    assert a == b
    # barele viitoare nu au schimbat secventa vazuta la T
    assert a.recent_sequence == [1.0, -2.0, 3.0, -4.0]


def test_delta_causal_progression():
    day = _make_day([10.0, -20.0, 30.0, -40.0, 50.0])
    for k in range(len(day.t)):
        dc = analyze_delta(snapshot_from_daydata(day, upto_index=k))
        assert dc.recent_sequence == [10.0, -20.0, 30.0, -40.0, 50.0][:k + 1]


def test_delta_determinism():
    snap = snapshot_from_daydata(_make_day([10.0, 20.0, 30.0, 40.0]), upto_index=3)
    assert analyze_delta(snap) == analyze_delta(snap)


def test_engine_populates_delta_component():
    snap = snapshot_from_daydata(_make_day([10.0, 20.0, 30.0]), upto_index=2)
    res = ContextEngine().analyze(snap)
    assert "delta" in res.components
    assert isinstance(res.components["delta"], DeltaContext)
    # determinism prin engine
    assert ContextEngine().analyze(snap).components["delta"] == res.components["delta"]
