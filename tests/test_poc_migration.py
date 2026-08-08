"""
P4.5 — teste pentru POC MIGRATION (directia + comportamentul POC developing in timp).

Deterministe, sintetice. Controlam direct seria developing POC (Snapshot.poc_series).
Verificam directie / magnitudine (STRONG/WEAK) / viteza / consistenta + no-look-ahead.
"""

import os
import numpy as np
import pytest

from core import (Snapshot, ContextEngine, snapshot_from_daydata,
                  analyze_poc_migration, PocMigrationContext, POC_MIGRATION_STATES)
from app.desktop.data_service import DayData

# scenarii de serie developing POC
RISING = [100, 100, 102, 104, 106, 108, 110, 112, 114, 116, 118]     # monoton -> STRONG
FALLING = list(reversed(RISING))
SIDEWAYS = [100, 102, 100, 102, 100, 102, 100, 102, 100, 102, 100]   # oscilant, net 0
WEAK_RISE = [100, 105, 103, 108, 106, 111, 109, 114, 112, 117, 115]  # sus dar cu pullback-uri


def _snap(poc_series, tick=0.25, base=1_800_000_000):
    poc = np.asarray(poc_series, dtype=float)
    n = len(poc)
    t = np.arange(n, dtype=float) * 60 + base
    return Snapshot(now_epoch=int(t[-1]) if n else 0, bar_seconds=60, t=t, open=poc.copy(),
                    high=poc + 1, low=poc - 1, close=poc.copy(), volume=np.zeros(n) + 10.0,
                    cvd=np.zeros(n), poc=float(poc[-1]) if n else 0.0, vah=0.0, val=0.0,
                    footprint={}, row_size=2.0, symbol="T", tick_size=tick, poc_series=poc)


def _make_day(poc_series):
    poc = np.asarray(poc_series, dtype=float)
    n = len(poc)
    t = np.arange(n, dtype=float) * 60 + 1_800_000_000
    return DayData(symbol="T", n_ticks=n, t=t, open=poc.copy(), high=poc + 1, low=poc - 1,
                   close=poc.copy(), volume=np.zeros(n) + 10.0, vwap=poc.copy(), cvd=np.zeros(n),
                   last_price=float(poc[-1]) if n else 0.0, bar_seconds=60,
                   bin_price=np.array([100.0]), bin_buy=np.array([1.0]), bin_sell=np.array([1.0]),
                   row_size=2.0, poc=999.0, vah=1005.0, val=995.0, footprint={},
                   dev_poc=poc, dev_vah=poc + 5, dev_val=poc - 5)


def test_poc_rising_strong():
    m = analyze_poc_migration(_snap(RISING))
    assert m.state == "POC_RISING"
    assert m.direction == "RISING"
    assert m.migration_strength == "STRONG"
    assert m.net_ticks > 0
    assert m.consistency == 1.0


def test_poc_falling_strong():
    m = analyze_poc_migration(_snap(FALLING))
    assert m.state == "POC_FALLING"
    assert m.net_ticks < 0
    assert m.migration_strength == "STRONG"


def test_poc_sideways():
    m = analyze_poc_migration(_snap(SIDEWAYS))
    assert m.state == "POC_SIDEWAYS"
    assert m.direction == "SIDEWAYS"
    assert m.migration_strength == "NONE"


def test_poc_weak_migration():
    m = analyze_poc_migration(_snap(WEAK_RISE))
    assert m.state == "POC_RISING"
    assert m.migration_strength == "WEAK"       # directional dar consistenta scazuta
    assert 0.0 < m.consistency < 0.6


def test_noise_is_sideways():
    noise = [100, 103, 99, 102, 98, 101, 100, 102, 99, 101, 100]
    assert analyze_poc_migration(_snap(noise)).state == "POC_SIDEWAYS"


def test_insufficient_evidence():
    assert analyze_poc_migration(_snap([100, 101, 102])).state == "INSUFFICIENT_EVIDENCE"
    assert analyze_poc_migration(_snap([])).state == "INSUFFICIENT_EVIDENCE"


def test_adaptive_scaling_same_result_x10():
    base = analyze_poc_migration(_snap(RISING))
    scaled = analyze_poc_migration(_snap([100 + (x - 100) * 10 for x in RISING]))
    assert base.state == scaled.state == "POC_RISING"
    assert base.migration_strength == scaled.migration_strength == "STRONG"


def test_direction_magnitude_speed_consistency_exposed_separately():
    m = analyze_poc_migration(_snap(RISING))
    assert m.direction == "RISING"                       # directia
    assert abs(m.net_ticks) > 0                          # magnitudinea
    assert m.speed_ticks_per_bar > 0                     # viteza
    assert 0.0 <= m.consistency <= 1.0                   # consistenta
    assert m.poc_reference == 100.0 and m.poc_current == 118.0


def test_state_always_in_known_set():
    for s in (RISING, FALLING, SIDEWAYS, WEAK_RISE, [100, 101]):
        assert analyze_poc_migration(_snap(s)).state in POC_MIGRATION_STATES


# --- no-look-ahead + determinism ---
def test_poc_migration_no_look_ahead():
    rising16 = [100 + 2 * i for i in range(16)]
    full = _make_day(rising16)
    ended = _make_day(rising16[:13])
    a = analyze_poc_migration(snapshot_from_daydata(full, upto_index=12))
    b = analyze_poc_migration(snapshot_from_daydata(ended, upto_index=12))
    assert a == b
    assert a.state == "POC_RISING"


def test_poc_migration_uses_developing_not_full_day():
    """Foloseste seria developing (poc_series), NU day.poc (=999 in fixtura)."""
    snap = snapshot_from_daydata(_make_day(RISING), upto_index=len(RISING) - 1)
    m = analyze_poc_migration(snap)
    assert m.poc_current == 118.0                        # ultimul developing, nu 999


def test_determinism():
    snap = snapshot_from_daydata(_make_day(RISING), upto_index=len(RISING) - 1)
    assert analyze_poc_migration(snap) == analyze_poc_migration(snap)


def test_engine_keeps_all_six_components():
    res = ContextEngine().analyze(snapshot_from_daydata(_make_day(RISING), len(RISING) - 1))
    for name in ("delta", "price_progress", "absorption", "exhaustion",
                 "cvd_divergence", "poc_migration"):
        assert name in res.components
    assert isinstance(res.components["poc_migration"], PocMigrationContext)


# --- date reale (skippable) ---
from data.loader import PARQUET_DIR
_REAL = "glbx-mdp3-20260804.trades.parquet"


@pytest.mark.skipif(not os.path.isfile(os.path.join(PARQUET_DIR, _REAL)),
                    reason="date reale lipsesc")
def test_poc_migration_runs_on_real_data():
    from app.desktop.data_service import load_day
    day = load_day(_REAL, mode="session", interval="5min", row_size=2.0)
    eng = ContextEngine()
    seen = set()
    for i in range(len(day.t)):
        m = eng.analyze(snapshot_from_daydata(day, upto_index=i)).components["poc_migration"]
        assert m.state in POC_MIGRATION_STATES
        seen.add(m.state)
    assert {"POC_RISING", "POC_FALLING"} & seen          # POC-ul migreaza in ambele directii pe sesiune
