"""
P1b — teste pentru LEVEL INTERACTION (LVN interaction + Acceptance/Rejection).

Deterministe, sintetice. Testam profund motorul GENERIC analyze_level_interaction (unde
sta logica) pe o zona fixa [100,104], apoi LVN interaction (nodul din P1a) si acceptance/
rejection pe niveluri punctuale. Praguri adaptive, confirmation window, no-look-ahead.
"""

import os
import numpy as np
import pytest

from core import (Snapshot, ContextEngine, snapshot_from_daydata,
                  analyze_level_interaction, analyze_lvn_interaction,
                  analyze_acceptance_rejection, InteractionContext, INTERACTION_STATES)
from app.desktop.data_service import DayData

ZLO, ZHI = 100.0, 104.0


def _snap(bars, poc=0.0, vah=0.0, val=0.0, footprint=None, tick=0.25, row=1.0, base=1_800_000_000):
    """bars = list de (h, l, c). cvd = cumsum(+10) (delta constant), volum 10."""
    n = len(bars)
    h = np.array([b[0] for b in bars], float); l = np.array([b[1] for b in bars], float)
    c = np.array([b[2] for b in bars], float)
    t = np.arange(n, dtype=float) * 60 + base
    cvd = np.cumsum(np.full(n, 10.0))
    fp = footprint or {}
    return Snapshot(now_epoch=int(t[-1]) if n else 0, bar_seconds=60, t=t, open=c.copy(),
                    high=h, low=l, close=c, volume=np.zeros(n) + 10.0, cvd=cvd,
                    poc=poc, vah=vah, val=val, footprint=fp, row_size=row, symbol="T", tick_size=tick)


ABOVE = (111.0, 109.0, 110.0)


def _rejection_bars(n_after=5):
    bars = [ABOVE] * 5 + [(110.0, 101.0, 108.0)]              # bar5 dip in zona + inchidere sus
    ups = [(109, 107, 108), (111, 109, 110), (113, 111, 112), (115, 113, 114), (117, 115, 116)]
    return bars + [tuple(map(float, u)) for u in ups[:n_after]]


def test_rejection_confirmed():
    d = analyze_level_interaction(_snap(_rejection_bars(5)), ZLO, ZHI, "lvn", "major")
    assert d.state == "REJECTION" and d.status == "CONFIRMED"
    assert d.approach_direction == "FROM_ABOVE" and d.exit_direction == "BACK"
    assert d.node_tier == "major"


def test_rejection_forming_before_window():
    d = analyze_level_interaction(_snap(_rejection_bars(2)), ZLO, ZHI, "lvn", "")   # doar 2 bare dupa
    assert d.state == "REJECTION" and d.status == "FORMING"


def test_acceptance_confirmed():
    bars = [ABOVE] * 5 + [(103.0, 101.0, 102.0)] * 5         # dwelling in zona
    d = analyze_level_interaction(_snap(bars), ZLO, ZHI, "lvn", "")
    assert d.state == "ACCEPTANCE" and d.status == "CONFIRMED"
    assert d.exit_direction == "INSIDE" and d.bars_inside == 5


def test_test_state_when_just_entered():
    bars = [ABOVE] * 5 + [(103.0, 101.0, 102.0)] * 2         # doar 2 bare in zona
    d = analyze_level_interaction(_snap(bars), ZLO, ZHI, "lvn", "")
    assert d.state == "TEST" and d.status == "FORMING"


def test_fast_traversal():
    bars = [ABOVE] * 5 + [(110.0, 98.0, 98.0)] + [(99.0, 97.0, 98.0)] * 4   # strabate zona intr-o bara
    d = analyze_level_interaction(_snap(bars), ZLO, ZHI, "lvn", "")
    assert d.state == "FAST_TRAVERSAL"
    assert d.exit_direction == "THROUGH" and d.bars_inside == 1


def test_failed_rejection():
    bars = ([ABOVE] * 4 + [(110.0, 101.0, 108.0)]            # respingere initiala
            + [(112.0, 110.0, 111.0), (113.0, 111.0, 112.0)]  # pleaca sus (miscare de respingere)
            + [(103.0, 101.0, 102.0)] * 5)                    # revine si accepta
    d = analyze_level_interaction(_snap(bars), ZLO, ZHI, "lvn", "")
    assert d.state == "FAILED_REJECTION"


def test_insufficient_evidence_no_touch():
    bars = [ABOVE] * 8                                        # nu atinge niciodata zona
    d = analyze_level_interaction(_snap(bars), ZLO, ZHI, "lvn", "")
    assert d.detected is False and d.state == "INSUFFICIENT_EVIDENCE"


def test_insufficient_when_too_few_bars():
    d = analyze_level_interaction(_snap([ABOVE, (103, 101, 102)]), ZLO, ZHI, "lvn", "")
    assert d.state == "INSUFFICIENT_EVIDENCE"


def test_penetration_and_time_inside():
    bars = [ABOVE] * 5 + [(103.0, 101.0, 102.0)] * 5
    d = analyze_level_interaction(_snap(bars), ZLO, ZHI, "lvn", "")
    assert d.penetration_ticks == (104.0 - 101.0) / 0.25     # zhi - seg_low
    assert d.bars_inside == 5 and d.time_inside_sec == 5 * 60
    assert d.entry_price == 102.0


def test_adaptive_thresholds_scale_x10():
    def scaled(bars):
        return [(h * 10, l * 10, c * 10) for (h, l, c) in bars]
    base = analyze_level_interaction(_snap(_rejection_bars(5)), ZLO, ZHI, "lvn", "").state
    big = analyze_level_interaction(_snap(scaled(_rejection_bars(5))), ZLO * 10, ZHI * 10, "lvn", "").state
    assert base == big == "REJECTION"


def test_state_always_in_known_set():
    for bars in (_rejection_bars(5), [ABOVE] * 5 + [(103, 101, 102)] * 5,
                 [ABOVE] * 8, [ABOVE] * 5 + [(110, 98, 98)] + [(99, 97, 98)] * 4):
        assert analyze_level_interaction(_snap([tuple(map(float, b)) for b in bars]),
                                         ZLO, ZHI, "lvn", "").state in INTERACTION_STATES


# --- no-look-ahead + determinism (motor generic) ---
def _make_day(bars):
    n = len(bars)
    h = np.array([b[0] for b in bars], float); l = np.array([b[1] for b in bars], float)
    c = np.array([b[2] for b in bars], float)
    t = np.arange(n, dtype=float) * 60 + 1_800_000_000
    dev = np.full(n, 102.0)
    return DayData(symbol="T", n_ticks=n, t=t, open=c.copy(), high=h, low=l, close=c,
                   volume=np.zeros(n) + 10.0, vwap=c.copy(), cvd=np.cumsum(np.full(n, 10.0)),
                   last_price=float(c[-1]), bar_seconds=60, bin_price=np.array([100.0]),
                   bin_buy=np.array([1.0]), bin_sell=np.array([1.0]), row_size=1.0,
                   poc=102.0, vah=108.0, val=96.0, footprint={},
                   dev_poc=dev, dev_vah=dev + 6, dev_val=dev - 6)


def test_no_look_ahead_and_confirmation_window():
    full = _make_day(_rejection_bars(5))          # 11 bare, respingere confirmata la final
    ended = _make_day(_rejection_bars(5)[:8])     # ziua s-ar termina la bar7
    a = analyze_level_interaction(snapshot_from_daydata(full, upto_index=7), ZLO, ZHI, "lvn", "")
    b = analyze_level_interaction(snapshot_from_daydata(ended, upto_index=7), ZLO, ZHI, "lvn", "")
    assert a == b and a.status == "FORMING"       # barele viitoare nu confirma respingerea la T=7
    conf = analyze_level_interaction(snapshot_from_daydata(full, upto_index=10), ZLO, ZHI, "lvn", "")
    assert conf.status == "CONFIRMED"


def test_determinism():
    snap = snapshot_from_daydata(_make_day(_rejection_bars(5)), upto_index=10)
    assert analyze_level_interaction(snap, ZLO, ZHI, "lvn", "") == \
        analyze_level_interaction(snap, ZLO, ZHI, "lvn", "")


# --- LVN interaction (nod real din footprint) ---
def _bimodal_day():
    """Footprint bimodal (varfuri 100/110, vale ~101-109 = LVN); pretul coboara prin vale."""
    heavy = [(100.0, {100.0: [50.0, 50.0]}), (110.0, {110.0: [50.0, 50.0]})] * 3   # 6 bare grele
    travel = [(109.0, {109.0: [2.0, 2.0]}), (107.0, {107.0: [2.0, 2.0]}),
              (106.0, {106.0: [2.0, 2.0]}), (105.0, {105.0: [2.0, 2.0]}),
              (103.0, {103.0: [2.0, 2.0]}), (101.0, {101.0: [2.0, 2.0]})]
    seq = heavy + travel
    n = len(seq)
    h = np.array([p + 0.5 for p, _ in seq]); l = np.array([p - 0.5 for p, _ in seq])
    c = np.array([p for p, _ in seq])
    t = np.arange(n, dtype=float) * 60 + 1_800_000_000
    fp = {int(round(t[i])): cells for i, (_, cells) in enumerate(seq)}
    dev = np.full(n, 100.0)
    return DayData(symbol="T", n_ticks=n, t=t, open=c.copy(), high=h, low=l, close=c,
                   volume=np.zeros(n) + 100.0, vwap=c.copy(), cvd=np.cumsum(np.full(n, 5.0)),
                   last_price=float(c[-1]), bar_seconds=60, bin_price=np.array([100.0]),
                   bin_buy=np.array([1.0]), bin_sell=np.array([1.0]), row_size=1.0,
                   poc=999.0, vah=1005.0, val=995.0, footprint=fp,
                   dev_poc=dev, dev_vah=dev + 5, dev_val=dev - 5)


def test_lvn_interaction_detects_and_delegates():
    snap = snapshot_from_daydata(_bimodal_day(), upto_index=11)
    d = analyze_lvn_interaction(snap)
    assert d.node_kind == "lvn"
    assert d.detected is True
    assert d.state in INTERACTION_STATES
    assert d.zone_low <= d.zone_high


def test_lvn_interaction_determinism():
    snap = snapshot_from_daydata(_bimodal_day(), upto_index=11)
    assert analyze_lvn_interaction(snap) == analyze_lvn_interaction(snap)


# --- acceptance/rejection pe nivel punctual (POC/VAH/VAL) ---
def test_acceptance_rejection_nearest_level():
    bars = [(111.0, 109.0, 110.0)] * 5 + [(103.0, 101.0, 102.0)] * 5
    d = analyze_acceptance_rejection(_snap(bars, poc=102.0, vah=108.0, val=96.0))
    assert d.node_kind == "poc"            # cel mai apropiat nivel de pretul curent (~102)
    assert d.state in INTERACTION_STATES
    assert d.detected is True


# --- compatibilitate: toate componentele coexista ---
def test_engine_keeps_all_components():
    res = ContextEngine().analyze(snapshot_from_daydata(_bimodal_day(), 11))
    for name in ("delta", "price_progress", "absorption", "exhaustion", "cvd_divergence",
                 "poc_migration", "lvn_interaction", "acceptance_rejection"):
        assert name in res.components
    assert isinstance(res.components["lvn_interaction"], InteractionContext)
    assert isinstance(res.components["acceptance_rejection"], InteractionContext)


# --- date reale (skippable) ---
from data.loader import PARQUET_DIR
_REAL = "glbx-mdp3-20260804.trades.parquet"


@pytest.mark.skipif(not os.path.isfile(os.path.join(PARQUET_DIR, _REAL)),
                    reason="date reale lipsesc")
def test_level_interaction_runs_on_real_data():
    from app.desktop.data_service import load_day
    day = load_day(_REAL, mode="session", interval="5min", row_size=2.0)
    eng = ContextEngine()
    lvn_seen, ar_seen = set(), set()
    for i in range(0, len(day.t), 3):        # esantion (VP-build/nod la fiecare pas -> pas de 3)
        comp = eng.analyze(snapshot_from_daydata(day, upto_index=i)).components
        assert comp["lvn_interaction"].state in INTERACTION_STATES
        assert comp["acceptance_rejection"].state in INTERACTION_STATES
        lvn_seen.add(comp["lvn_interaction"].state)
        ar_seen.add(comp["acceptance_rejection"].state)
    assert any(s != "INSUFFICIENT_EVIDENCE" for s in lvn_seen)
    assert any(s != "INSUFFICIENT_EVIDENCE" for s in ar_seen)
