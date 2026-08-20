"""Teste pentru SessionStore (Faza 0 — cache-ul partajat de date).

Acopera EXACT cerintele Fazei 0:
  - regresie: valorile VP (POC/VAH/VAL/HVN/LVN/total) IDENTICE inainte/dupa cache;
  - suport Full Day / Asia / London / New York;
  - chei de cache deterministe (hit/miss);
  - cache hit NU recalculeaza (deci nu reciteste parquet);
  - Replay-ul ramane NEATINS (determinism + seek identice cu/ fara store);
  - fara look-ahead: store-ul nu are niciun cuplaj cu cursorul de replay.

Date reale (skip daca lipsesc). Store-ul e agregat pe intreaga sesiune, deci NU e
un test de cauzalitate in sine — cauzalitatea ramane a Replay-ului (vezi
test_lookahead / test_replay_determinism).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import glob
import inspect

import numpy as np
import pytest

from data.loader import PARQUET_DIR
import app.desktop.data_service as ds
from app.desktop.session_store import SessionStore, SESSION_UNITS

_HAVE = bool(glob.glob(os.path.join(PARQUET_DIR, "*.parquet")))
pytestmark = pytest.mark.skipif(not _HAVE, reason="date reale lipsesc (data/parquet)")

DAY = "glbx-mdp3-20260804.trades"
ROW = 2.0


# ---------- 1. Regresie: valori identice inainte/dupa cache ----------
def test_get_day_matches_load_day():
    """DayData din store == DayData din data_service.load_day (bit-cu-bit pe cheie)."""
    store = SessionStore()
    direct = ds.load_day(DAY, row_size=ROW)
    cached = store.get_day(DAY, row_size=ROW)
    for attr in ("poc", "vah", "val", "total_volume", "cum_delta",
                 "buy_total", "sell_total"):
        assert getattr(direct, attr) == getattr(cached, attr), f"{attr} difera"
    assert list(direct.hvn) == list(cached.hvn)
    assert list(direct.lvn) == list(cached.lvn)
    np.testing.assert_array_equal(direct.bin_price, cached.bin_price)
    np.testing.assert_array_equal(direct.bin_buy, cached.bin_buy)
    np.testing.assert_array_equal(direct.bin_sell, cached.bin_sell)


def test_get_period_profiles_matches():
    """period_profiles din store == direct (POC/VA/total per profil)."""
    store = SessionStore()
    direct = ds.period_profiles(DAY, unit="Zi", row_size=ROW)
    cached = store.get_period_profiles(DAY, unit="Full Day", row_size=ROW)  # nume prietenos
    assert len(direct) == len(cached)
    for a, b in zip(direct, cached):
        assert a["poc"] == b["poc"] and a["vah"] == b["vah"] and a["val"] == b["val"]
        assert a["total"] == b["total"] and a["label"] == b["label"]


# ---------- 2. Suport Full Day / Asia / London / New York ----------
def test_session_units_supported():
    store = SessionStore()
    assert store.available_sessions() == ["Full Day", "Asia", "London", "New York"]
    for friendly in store.available_sessions():
        profs = store.get_session_profile(DAY, session=friendly, row_size=ROW)
        assert isinstance(profs, list)   # 0 sau 1 profil, fara crash
    # New York -> eticheta interna "NY"
    ny = store.get_session_profile(DAY, session="New York", row_size=ROW)
    assert ny and "NY" in ny[0]["label"]


def test_friendly_and_internal_units_share_cache():
    """'Full Day' si 'Zi' sunt aceeasi selectie -> a doua e HIT, nu recalcul."""
    store = SessionStore()
    store.get_period_profiles(DAY, unit="Full Day", row_size=ROW)
    m1 = store.misses
    store.get_period_profiles(DAY, unit="Zi", row_size=ROW)   # sinonim intern
    assert store.misses == m1 and store.hits >= 1


# ---------- 3. Chei deterministe + hit/miss ----------
def test_cache_hit_miss_counters():
    store = SessionStore()
    assert store.cache_info()["misses"] == 0
    store.get_day(DAY, row_size=ROW)
    assert (store.hits, store.misses) == (0, 1)     # prima = miss
    store.get_day(DAY, row_size=ROW)
    assert (store.hits, store.misses) == (1, 1)     # a doua = hit
    store.get_day(DAY, row_size=4.0)                # parametru diferit = alta cheie
    assert (store.hits, store.misses) == (1, 2)


def test_hit_returns_same_object():
    store = SessionStore()
    a = store.get_day(DAY, row_size=ROW)
    b = store.get_day(DAY, row_size=ROW)
    assert a is b                                   # hit = fix acelasi obiect


def test_cache_avoids_recompute(monkeypatch):
    """Un hit NU mai apeleaza load_day (deci nu reciteste parquet)."""
    store = SessionStore()
    calls = {"n": 0}
    real = ds.load_day

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(ds, "load_day", spy)
    first = store.get_day(DAY, row_size=ROW)
    second = store.get_day(DAY, row_size=ROW)
    assert calls["n"] == 1                          # calculat o singura data
    assert first is second


# ---------- 4. Replay-ul ramane NEATINS ----------
def _snapshot_at(full, df, candle):
    from app.desktop.replay import Replay
    r = Replay(full, df, va_percent=0.70, row_size=ROW)
    return r.seek_candle(candle)


def test_replay_identical_with_and_without_store():
    """Snapshot-ul de replay e IDENTIC fie ca ticks/day vin din store, fie direct.
    Dovada ca store-ul nu altereaza determinismul replay-ului."""
    # direct
    d_direct = ds.load_day(DAY, row_size=ROW)
    tk_direct, _ = ds.resolve_ticks(DAY, "session", "day")
    snap_direct = _snapshot_at(d_direct, tk_direct.df, 20)
    # prin store
    store = SessionStore()
    d_store = store.get_day(DAY, row_size=ROW)
    tk_store, _ = store.get_ticks(DAY, "session", "day")
    snap_store = _snapshot_at(d_store, tk_store.df, 20)

    assert snap_direct.poc == snap_store.poc
    assert snap_direct.vah == snap_store.vah
    assert snap_direct.val == snap_store.val
    np.testing.assert_array_equal(snap_direct.close, snap_store.close)
    np.testing.assert_array_equal(snap_direct.cvd, snap_store.cvd)
    assert snap_direct.n_ticks == snap_store.n_ticks


def test_store_ticks_match_direct():
    store = SessionStore()
    tk_s, inc_s = store.get_ticks(DAY, "session", "day")
    tk_d, inc_d = ds.resolve_ticks(DAY, "session", "day")
    assert inc_s == inc_d
    assert len(tk_s.df) == len(tk_d.df)
    np.testing.assert_array_equal(tk_s.df["price"].to_numpy(),
                                  tk_d.df["price"].to_numpy())


# ---------- 5. Fara look-ahead: store-ul nu stie de cursor ----------
def test_store_has_no_cursor_coupling():
    """Garda no-look-ahead: niciun API public al store-ului nu accepta cursor/epoca/
    timp curent. Store-ul serveste doar agregate pe intreaga sesiune -> nu poate
    scurge date viitoare. Taierea cauzala ramane la Replay (Faza 2)."""
    forbidden = ("cursor", "epoch", "now", "current", "until", "t_max", "bar_index")
    for name, method in inspect.getmembers(SessionStore, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        params = set(inspect.signature(method).parameters)
        leak = params & set(forbidden)
        assert not leak, f"{name} expune parametru de timp: {leak}"


def test_store_never_imports_replay_state():
    """Store-ul nu IMPORTA modulul replay si nu are simbolul Replay in namespace ->
    nicio cale structurala de look-ahead. (Verificam import-urile reale via AST, nu
    textul comentariilor — care POT mentiona 'cursor'/'Replay' explicand ca NU le foloseste.)"""
    import ast
    import app.desktop.session_store as ss
    assert not hasattr(ss, "Replay")
    tree = ast.parse(inspect.getsource(ss))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {n.name for n in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any("replay" in m.lower() for m in imported), imported


# ---------- 6. LRU ----------
def test_lru_eviction():
    store = SessionStore(maxsize=1)
    store.get_day(DAY, row_size=ROW)
    store.get_day(DAY, row_size=4.0)                # a doua evictioneaza prima
    assert store.cache_info()["day"] == 1
    store.get_day(DAY, row_size=ROW)                # reintroducem prima = miss (a fost evacuata)
    assert store.misses == 3


def test_clear_resets():
    store = SessionStore()
    store.get_day(DAY, row_size=ROW)
    store.clear()
    info = store.cache_info()
    assert info == {"hits": 0, "misses": 0, "ticks": 0, "day": 0, "period": 0}
