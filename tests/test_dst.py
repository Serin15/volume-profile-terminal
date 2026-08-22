"""Teste DST pentru granita de sesiune (Pasul 1 din audit).

Bug reparat: granita sesiunii futures era hardcodata la 22:00 UTC (= 18:00 ET DOAR vara).
Acum e 18:00 America/New_York, DST-aware: vara 22:00 UTC, iarna 23:00 UTC.

Acopera: session_date_for (vara NESCHIMBAT / iarna corect), by_session pe o zi de iarna,
robustete la ts tz-naive (parquet), si ferestrele Asia/London/NY DST-aware (session_window).
Teste sintetice, nu depind de date reale (deterministe).
"""
import datetime as dt

import pandas as pd

import app.desktop.data_service as ds
from data import session_date_for, SESSION_TZ, SESSION_BOUNDARY_HOUR
from data.loader import SessionTicks


def _sd(iso):
    return session_date_for(pd.Timestamp(iso))


def _ticks(rows, tz_aware=True):
    stamps = [r[0] for r in rows]
    ts = pd.to_datetime(stamps, utc=True) if tz_aware else pd.to_datetime(stamps)
    df = pd.DataFrame({"ts": ts, "price": [r[1] for r in rows],
                       "size": [r[2] for r in rows], "side": [r[3] for r in rows]})
    return SessionTicks(df=df, symbol="NQ",
                        volume_per_symbol={"NQ": float(df["size"].sum())}, source="test")


def _utc_hm(epoch):
    d = dt.datetime.fromtimestamp(epoch, dt.timezone.utc)
    return (d.hour, d.minute)


# ================= session_date_for =================
def test_boundary_constants():
    assert (SESSION_TZ, SESSION_BOUNDARY_HOUR) == ("America/New_York", 18)


def test_summer_boundary_is_22utc():
    """Vara (EDT): 18:00 ET = 22:00 UTC -> comportamentul de dinainte, NESCHIMBAT."""
    assert _sd("2026-07-06T21:59:00Z") == "2026-07-06"   # 17:59 EDT
    assert _sd("2026-07-06T22:00:00Z") == "2026-07-07"   # 18:00 EDT -> sesiune noua
    assert _sd("2026-07-06T22:30:00Z") == "2026-07-07"


def test_winter_boundary_is_23utc():
    """Iarna (EST): 18:00 ET = 23:00 UTC. La 22:00-23:00 UTC suntem INCA in sesiunea veche."""
    assert _sd("2026-01-15T21:59:00Z") == "2026-01-15"   # 16:59 EST
    assert _sd("2026-01-15T22:00:00Z") == "2026-01-15"   # 17:00 EST — bug vechi: dadea 16
    assert _sd("2026-01-15T22:59:00Z") == "2026-01-15"   # 17:59 EST — bug vechi: dadea 16
    assert _sd("2026-01-15T23:00:00Z") == "2026-01-16"   # 18:00 EST -> sesiune noua
    assert _sd("2026-01-15T23:30:00Z") == "2026-01-16"


def test_same_utc_different_session_summer_vs_winter():
    """DOVADA DST: acelasi UTC (22:30) cade in sesiuni diferite vara vs iarna."""
    assert _sd("2026-07-06T22:30:00Z") == "2026-07-07"   # vara: dupa 18:00 ET
    assert _sd("2026-01-15T22:30:00Z") == "2026-01-15"   # iarna: inca inainte de 18:00 ET


# ================= by_session =================
def test_by_session_winter_day():
    st = _ticks([("2026-01-15T22:30:00Z", 100, 5, "B"),    # 17:30 EST -> sesiunea 15
                 ("2026-01-15T23:30:00Z", 101, 7, "A"),    # 18:30 EST -> sesiunea 16
                 ("2026-01-16T14:30:00Z", 102, 3, "B")])   # 09:30 EST (NY open) -> sesiunea 16
    sess = st.by_session()
    assert set(sess) == {"2026-01-15", "2026-01-16"}
    assert len(sess["2026-01-15"]) == 1
    assert len(sess["2026-01-16"]) == 2


def test_by_session_summer_day_unchanged():
    st = _ticks([("2026-07-06T21:59:00Z", 100, 5, "B"),    # 17:59 EDT -> 06
                 ("2026-07-06T22:30:00Z", 101, 7, "A"),    # 18:30 EDT -> 07
                 ("2026-07-06T23:00:00Z", 102, 3, "B")])   # 19:00 EDT -> 07
    sess = st.by_session()
    assert set(sess) == {"2026-07-06", "2026-07-07"}
    assert len(sess["2026-07-06"]) == 1
    assert len(sess["2026-07-07"]) == 2


def test_by_session_tz_naive_input_treated_as_utc():
    """ts tz-naive (cum poate veni din parquet) -> tratat ca UTC, fara crash, corect."""
    st = _ticks([("2026-01-15T22:30:00", 100, 5, "B"),
                 ("2026-01-15T23:30:00", 101, 7, "A")], tz_aware=False)
    assert st.df["ts"].dt.tz is None                      # chiar e tz-naive
    sess = st.by_session()
    assert set(sess) == {"2026-01-15", "2026-01-16"}


# ================= ferestre Asia / London / NY (session_window DST-aware) =================
def test_ny_window_dst_aware():
    """NY RTH 09:30-16:00 ET: iarna 14:30-21:00 UTC (EST), vara 13:30-20:00 UTC (EDT)."""
    s_w, e_w = ds.session_window("20260115", "New York")
    s_s, e_s = ds.session_window("20260715", "New York")
    assert _utc_hm(s_w) == (14, 30) and _utc_hm(e_w) == (21, 0)
    assert _utc_hm(s_s) == (13, 30) and _utc_hm(e_s) == (20, 0)
    assert s_w != s_s                                     # granita se muta cu DST


def test_london_window_dst_aware():
    """London 08:00-16:00: iarna 08:00-16:00 UTC (GMT), vara 07:00-15:00 UTC (BST)."""
    s_w, e_w = ds.session_window("20260115", "London")
    s_s, e_s = ds.session_window("20260715", "London")
    assert _utc_hm(s_w) == (8, 0) and _utc_hm(e_w) == (16, 0)
    assert _utc_hm(s_s) == (7, 0) and _utc_hm(e_s) == (15, 0)


def test_asia_window_no_dst():
    """Tokyo nu are DST: 08:00 JST = 23:00 UTC (ziua precedenta) tot anul."""
    s_w, _ = ds.session_window("20260115", "Asia")
    s_s, _ = ds.session_window("20260715", "Asia")
    assert _utc_hm(s_w) == (23, 0) and _utc_hm(s_s) == (23, 0)


def test_full_day_has_no_window():
    assert ds.session_window("20260115", "Full Day") is None
    assert ds.session_window("20260115", "Zi") is None
