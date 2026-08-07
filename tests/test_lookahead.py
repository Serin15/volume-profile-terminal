"""
P4-core — teste ANTI-LOOK-AHEAD pentru ContextEngine.

Demonstreaza granita de cauzalitate PRIN CONSTRUCTIE:
  - Snapshot-ul e feliat fizic la T (nu contine bare > T).
  - POC/VA din snapshot = valorile developing (cauzale), NU day.poc (ziua intreaga).
  - Rezultatul engine-ului la T e IDENTIC fie ca ziua "continua" dupa T, fie ca s-ar
    fi terminat la T -> barele viitoare nu se scurg in rezultat.
  - Determinism: acelasi snapshot -> acelasi ContextResult.
  - Progresie de tip replay: la fiecare pas se folosesc doar barele <= T.

Testele sintetice nu depind de date reale (rapide, deterministe). Testul pe replay real
se sare daca lipsesc datele.
"""

import os

import numpy as np
import pytest

from core import ContextEngine, ContextResult, Snapshot, snapshot_from_daydata
from app.desktop.data_service import DayData


# ---------------------------------------------------------------- fixtura sintetica
def _make_day(n=8, bar=300, base=1_800_000_000):
    """
    DayData deterministic, mic. IMPORTANT pentru test: valorile developing (dev_poc[k]
    = 200+k) sunt DISTINCTE per bara, iar day.poc (ziua intreaga) e 999 = evident diferit.
    Astfel, daca engine-ul ar folosi din greseala day.poc, s-ar vedea imediat.
    """
    t = np.array([base + i * bar for i in range(n)], dtype=float)
    close = np.array([100.0 + i for i in range(n)], dtype=float)
    open_ = close - 0.5
    high = close + 1.0
    low = close - 1.0
    volume = np.array([10.0 + i for i in range(n)], dtype=float)
    vwap = close.copy()
    per_delta = np.array([((-1) ** i) * (i + 1) for i in range(n)], dtype=float)
    cvd = np.cumsum(per_delta) if n else np.zeros(0)
    dev_poc = np.array([200.0 + i for i in range(n)], dtype=float)   # cauzal, distinct/bara
    dev_vah = dev_poc + 5.0
    dev_val = dev_poc - 5.0
    row = 2.0
    footprint = {}
    for i in range(n):
        ep = int(round(t[i]))
        buy = max(per_delta[i], 0.0) + 5.0
        sell = max(-per_delta[i], 0.0) + 5.0
        price = round(round(close[i] / row) * row, 4)
        footprint[ep] = {price: [float(buy), float(sell)]}
    return DayData(
        symbol="TEST", n_ticks=int(volume.sum()),
        t=t, open=open_, high=high, low=low, close=close, volume=volume,
        vwap=vwap, cvd=cvd, last_price=float(close[-1]) if n else 0.0, bar_seconds=bar,
        bin_price=np.array([200.0]), bin_buy=np.array([1.0]), bin_sell=np.array([1.0]),
        row_size=row,
        poc=999.0, vah=1005.0, val=995.0,          # FULL-DAY (look-ahead) - nu trebuie folosite
        footprint=footprint, dev_poc=dev_poc, dev_vah=dev_vah, dev_val=dev_val,
    )


# ---------------------------------------------------------------- felierea fizica
def test_snapshot_is_physically_truncated_at_T():
    day = _make_day(8)
    snap = snapshot_from_daydata(day, upto_index=3)
    assert len(snap) == 4
    assert snap.now_epoch == int(day.t[3])
    assert snap.t.max() == day.t[3]
    assert snap.close[-1] == day.close[3]
    # footprint-ul NU contine nicio bara din viitor
    assert all(ep <= snap.now_epoch for ep in snap.footprint)


def test_snapshot_uses_causal_developing_poc_not_full_day():
    day = _make_day(8)
    snap = snapshot_from_daydata(day, upto_index=3)
    assert snap.poc == day.dev_poc[3]      # 203 = developing la T
    assert snap.poc != day.poc             # NU 999 (ziua intreaga)


def test_snapshot_arrays_all_truncated_to_k_plus_one():
    snap = snapshot_from_daydata(_make_day(8), upto_index=3)
    for name in ("t", "open", "high", "low", "close", "volume", "cvd"):
        assert len(getattr(snap, name)) == 4, f"{name} nu e feliat la T"


# ---------------------------------------------------------------- nu se scurge viitorul
def test_engine_result_identical_whether_or_not_future_exists():
    """
    Miezul garantiei: rezultatul la T=3 e IDENTIC daca ziua are 8 bare (viitor prezent)
    sau doar 4 (s-ar fi terminat la T). Deci barele viitoare NU influenteaza rezultatul.
    """
    eng = ContextEngine()
    full = _make_day(8)                    # ziua "continua" dupa T
    ended_at_T = _make_day(4)              # ziua "s-a terminat" la T=3
    res_future = eng.analyze(snapshot_from_daydata(full, upto_index=3))
    res_ended = eng.analyze(snapshot_from_daydata(ended_at_T, upto_index=3))
    assert res_future == res_ended
    # si dovada ca a folosit POC-ul cauzal, nu pe cel al zilei intregi
    assert res_future.poc == full.dev_poc[3]
    assert res_future.poc != full.poc


def test_engine_receives_only_a_snapshot_no_day_handle():
    """Snapshot-ul nu poarta niciun camp catre ziua intreaga / viitor (granita structurala)."""
    snap = snapshot_from_daydata(_make_day(8), upto_index=3)
    assert isinstance(snap, Snapshot)
    for forbidden in ("full", "future", "day", "all_t"):
        assert not hasattr(snap, forbidden)


# ---------------------------------------------------------------- determinism
def test_determinism_same_snapshot_twice():
    snap = snapshot_from_daydata(_make_day(8), upto_index=5)
    eng = ContextEngine()
    assert eng.analyze(snap) == eng.analyze(snap)


def test_determinism_independent_identical_snapshots():
    day = _make_day(8)
    a = ContextEngine().analyze(snapshot_from_daydata(day, upto_index=5))
    b = ContextEngine().analyze(snapshot_from_daydata(day, upto_index=5))
    assert a == b
    assert isinstance(a, ContextResult)


# ---------------------------------------------------------------- progresie cauzala
def test_causal_progression_uses_only_bars_up_to_T():
    day = _make_day(8)
    eng = ContextEngine()
    for k in range(len(day.t)):
        snap = snapshot_from_daydata(day, upto_index=k)
        res = eng.analyze(snap)
        assert res.n_bars == k + 1
        assert res.now_epoch == int(day.t[k])
        assert snap.t.max() == day.t[k]
        assert all(ep <= day.t[k] for ep in snap.footprint)


def test_upto_none_uses_all_bars():
    """Cand `day` e deja un snapshot de replay (taiat), upto=None ia tot ce e in el."""
    day = _make_day(5)
    snap = snapshot_from_daydata(day, upto_index=None)
    assert len(snap) == 5
    assert snap.now_epoch == int(day.t[-1])


def test_empty_day_is_safe():
    day = _make_day(0)
    res = ContextEngine().analyze(snapshot_from_daydata(day))
    assert res.n_bars == 0


# ---------------------------------------------------------------- replay REAL (skippable)
from data.loader import PARQUET_DIR

_REAL = "glbx-mdp3-20260726.trades.parquet"


@pytest.mark.skipif(not os.path.isfile(os.path.join(PARQUET_DIR, _REAL)),
                    reason="date reale lipsesc (data/parquet)")
def test_replay_snapshot_is_causal_on_real_data():
    """Pe date reale: snapshot-ul de replay la T contine doar bare <= T, iar calea de
    replay si cea de feliere a zilei intregi dau ACELASI rezultat la acelasi T."""
    from app.desktop.data_service import load_day, resolve_ticks
    from app.desktop.replay import Replay

    day = load_day(_REAL, mode="session", interval="5min", row_size=2.0)
    if len(day.t) < 6:
        pytest.skip("prea putine bare in ziua de test")
    tk, _ = resolve_ticks(_REAL, "session", "day")
    rp = Replay(day, tk.df, va_percent=0.70, row_size=2.0)

    mid = len(day.t) // 2
    replay_dd = rp.seek_candle(mid)                 # DayData deja taiat la bara curenta
    snap = snapshot_from_daydata(replay_dd)          # upto=None -> tot ce e in snapshot
    res = ContextEngine().analyze(snap)

    now = snap.now_epoch
    assert snap.t.max() == now
    assert all(ep <= now for ep in snap.footprint)   # replay@T foloseste doar <= T
    assert res.n_bars == len(replay_dd.t)

    # calea "felierea zilei intregi la acelasi T" trebuie sa coincida
    j = int(np.argmin(np.abs(day.t - now)))
    res_full = ContextEngine().analyze(snapshot_from_daydata(day, upto_index=j))
    assert res_full.now_epoch == res.now_epoch
    assert res_full.n_bars == res.n_bars
    assert abs(res_full.last_price - res.last_price) < 1e-6
    assert abs(res_full.cvd - res.cvd) < 1e-6
