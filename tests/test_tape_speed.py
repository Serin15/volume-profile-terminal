"""
P5 — teste pentru TAPE SPEED (ritmul executiei din schema Trades).

Deterministe, sintetice. Controlam volumul (contracts/sec = volum/bar_seconds), delta si
tps. Verificam nivelul de viteza (adaptiv), accelerarea, si SEPARAREA vitezei de directie.
bar_seconds=60 => contracts/sec = volum/60. Fundal 600 -> 10/s -> scala 10.
"""

import os
import numpy as np
import pytest

from core import (Snapshot, ContextEngine, snapshot_from_daydata,
                  analyze_tape_speed, TapeSpeedContext, TAPE_SPEED_STATES)
from app.desktop.data_service import DayData

BS = 60


def _snap(volumes, deltas=None, tps=None, tick=0.25, base=1_800_000_000):
    n = len(volumes)
    vol = np.asarray(volumes, dtype=float)
    deltas = [10.0] * n if deltas is None else deltas
    cvd = np.cumsum(deltas) if n else np.zeros(0)
    tps_arr = np.asarray([5.0] * n if tps is None else tps, dtype=float)
    t = np.arange(n, dtype=float) * BS + base
    c = 100.0 + np.arange(n, dtype=float)
    return Snapshot(now_epoch=int(t[-1]) if n else 0, bar_seconds=BS, t=t, open=c.copy(),
                    high=c + 1, low=c - 1, close=c, volume=vol, cvd=cvd, poc=0.0, vah=0.0,
                    val=0.0, footprint={}, row_size=2.0, symbol="T", tick_size=tick,
                    tps=tps_arr)


def test_high_speed():
    d = analyze_tape_speed(_snap([600.0] * 9 + [2000.0]))
    assert d.speed_level == "HIGH" and d.state == "HIGH"
    assert d.acceleration == "ACCELERATING"


def test_low_speed():
    assert analyze_tape_speed(_snap([600.0] * 9 + [200.0])).speed_level == "LOW"


def test_normal_speed():
    assert analyze_tape_speed(_snap([600.0] * 9 + [700.0])).speed_level == "NORMAL"


def test_contracts_and_trades_and_delta_per_sec():
    d = analyze_tape_speed(_snap([600.0] * 9 + [1200.0],
                                 deltas=[10.0] * 9 + [120.0],
                                 tps=[5.0] * 9 + [8.0]))
    assert d.contracts_per_sec == 1200.0 / BS      # 20
    assert d.trades_per_sec == 8.0
    assert d.delta_per_sec == 120.0 / BS           # 2.0


def test_speed_independent_of_delta_direction():
    """Aceeasi viteza, delta opusa -> ACELASI speed_level (viteza != directie)."""
    up = analyze_tape_speed(_snap([600.0] * 9 + [2000.0], deltas=[10.0] * 10))
    down = analyze_tape_speed(_snap([600.0] * 9 + [2000.0], deltas=[-10.0] * 10))
    assert up.speed_level == down.speed_level == "HIGH"
    assert up.delta_per_sec > 0 and down.delta_per_sec < 0    # directia difera, expusa separat


def test_adaptive_scaling_x10():
    base = analyze_tape_speed(_snap([600.0] * 9 + [2000.0]))
    big = analyze_tape_speed(_snap([6000.0] * 9 + [20000.0]))
    assert base.speed_level == big.speed_level == "HIGH"


def test_insufficient_evidence():
    assert analyze_tape_speed(_snap([600.0, 700.0, 800.0])).speed_level == "INSUFFICIENT_EVIDENCE"


def test_missing_tps_still_reports_contracts_speed():
    """Fara tps (trades/sec=0) tot clasificam viteza pe contracts/sec."""
    snap = _snap([600.0] * 9 + [2000.0])
    snap = Snapshot(**{**snap.__dict__, "tps": np.zeros(0)})
    d = analyze_tape_speed(snap)
    assert d.trades_per_sec == 0.0 and d.speed_level == "HIGH"


def test_state_always_in_known_set():
    for v in ([600.0] * 9 + [2000.0], [600.0] * 9 + [200.0], [600.0] * 9 + [700.0], [1.0, 2.0]):
        assert analyze_tape_speed(_snap(v)).speed_level in TAPE_SPEED_STATES


# --- no-look-ahead + determinism ---
def _make_day(volumes, deltas=None, tps=None):
    n = len(volumes)
    vol = np.asarray(volumes, dtype=float)
    deltas = [10.0] * n if deltas is None else deltas
    cvd = np.cumsum(deltas)
    tps_arr = np.asarray([5.0] * n if tps is None else tps, dtype=float)
    t = np.arange(n, dtype=float) * BS + 1_800_000_000
    c = 100.0 + np.arange(n, dtype=float)
    dev = np.full(n, 100.0)
    return DayData(symbol="T", n_ticks=n, t=t, open=c.copy(), high=c + 1, low=c - 1, close=c,
                   volume=vol, vwap=c.copy(), cvd=cvd, last_price=float(c[-1]), bar_seconds=BS,
                   bin_price=np.array([100.0]), bin_buy=np.array([1.0]), bin_sell=np.array([1.0]),
                   row_size=2.0, poc=999.0, vah=1005.0, val=995.0, footprint={},
                   dev_poc=dev, dev_vah=dev + 5, dev_val=dev - 5, tps=tps_arr)


def test_tape_speed_no_look_ahead():
    vols = [600.0] * 9 + [2000.0, 300.0, 300.0]
    full = _make_day(vols)
    ended = _make_day(vols[:10])
    a = analyze_tape_speed(snapshot_from_daydata(full, upto_index=9))
    b = analyze_tape_speed(snapshot_from_daydata(ended, upto_index=9))
    assert a == b and a.speed_level == "HIGH"     # barele viitoare (mici) nu schimba viteza la T=9


def test_tape_speed_determinism():
    snap = snapshot_from_daydata(_make_day([600.0] * 9 + [2000.0]), upto_index=9)
    assert analyze_tape_speed(snap) == analyze_tape_speed(snap)


def test_engine_keeps_all_nine_components():
    res = ContextEngine().analyze(snapshot_from_daydata(_make_day([600.0] * 9 + [2000.0]), 9))
    for name in ("delta", "price_progress", "absorption", "exhaustion", "cvd_divergence",
                 "poc_migration", "lvn_interaction", "acceptance_rejection", "tape_speed"):
        assert name in res.components
    assert isinstance(res.components["tape_speed"], TapeSpeedContext)


# --- date reale (skippable) ---
from data.loader import PARQUET_DIR
_REAL = "glbx-mdp3-20260804.trades.parquet"


@pytest.mark.skipif(not os.path.isfile(os.path.join(PARQUET_DIR, _REAL)),
                    reason="date reale lipsesc")
def test_tape_speed_runs_on_real_data():
    from app.desktop.data_service import load_day
    day = load_day(_REAL, mode="session", interval="1min", row_size=2.0)
    eng = ContextEngine()
    seen = set()
    for i in range(0, len(day.t), 5):
        d = eng.analyze(snapshot_from_daydata(day, upto_index=i)).components["tape_speed"]
        assert d.speed_level in TAPE_SPEED_STATES
        assert d.contracts_per_sec >= 0 and d.trades_per_sec >= 0
        seen.add(d.speed_level)
    assert {"HIGH", "LOW"} & seen                  # apar si perioade rapide si lente
