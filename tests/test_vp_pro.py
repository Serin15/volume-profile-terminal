"""Teste Faza 3 — Professional Volume Profile (VolumeProfileView: TOTAL/SPLIT/DELTA + hover).

Cele 11 cerinte: buy/sell per nivel == engine, delta = buy-sell, POC/VAH/VAL neschimbate,
HVN/LVN neschimbate, moduri deterministe, hover corect, no-look-ahead cu replay, sync ON/OFF,
3 profile simultan, Main Chart neafectat, performanta (set_mode nu recalculeaza).

Reutilizeaza datele engine-ului (period_profiles/profile_from_footprint) — view-ul NU
calculeaza nimic, doar afiseaza.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import glob

import numpy as np
import pytest

from data.loader import PARQUET_DIR
import app.desktop.data_service as ds
from app.desktop.vp_view import VolumeProfileView
from app.desktop.session_store import SessionStore
from app.desktop.historical_panel import ProfileCard, HistoricalProfilePanel

_HAVE = bool(glob.glob(os.path.join(PARQUET_DIR, "*.parquet")))
pytestmark = pytest.mark.skipif(not _HAVE, reason="date reale lipsesc (data/parquet)")

DAY = "glbx-mdp3-20260804.trades"
ROW = 2.0


@pytest.fixture(scope="module")
def qapp():
    from pyqtgraph.Qt import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _profile():
    return ds.period_profiles(DAY, unit="NY", span="day", row_size=ROW)[0]


def _view(profile=None):
    v = VolumeProfileView()
    v.set_profile(profile if profile is not None else _profile(), row_size=ROW)
    return v


# ---------- 1. buy/sell per nivel == engine ----------
def test_buy_sell_per_level_matches_engine(qapp):
    p = _profile()
    v = _view(p)
    for i in range(0, len(p["bin_price"]), 7):     # esantion de niveluri
        price = float(p["bin_price"][i])
        info = v.level_at(price)
        assert info is not None
        assert info["buy"] == float(p["bin_buy"][i])
        assert info["sell"] == float(p["bin_sell"][i])
        assert info["total"] == float(p["bin_buy"][i] + p["bin_sell"][i])


# ---------- 2. delta per nivel = buy - sell ----------
def test_delta_per_level(qapp):
    p = _profile()
    v = _view(p)
    for i in range(0, len(p["bin_price"]), 11):
        info = v.level_at(float(p["bin_price"][i]))
        assert info["delta"] == info["buy"] - info["sell"]


# ---------- 3. POC/VAH/VAL neschimbate (inclusiv intre moduri) ----------
def test_poc_vah_val_unchanged_across_modes(qapp):
    p = _profile()
    v = _view(p)
    for m in ("total", "split", "delta"):
        v.set_mode(m)
        assert v.current_levels() == (p["poc"], p["vah"], p["val"])


# ---------- 4. HVN/LVN neschimbate ----------
def test_hvn_lvn_unchanged_across_modes(qapp):
    p = _profile()
    v = _view(p)
    expected = len(p["hvn"]) + len(p["lvn"])
    for m in ("total", "split", "delta"):
        v.set_mode(m)
        assert v.node_line_count() == expected
    assert v._profile["hvn"] == p["hvn"] and v._profile["lvn"] == p["lvn"]


# ---------- 5. moduri deterministe ----------
def test_modes_deterministic(qapp):
    p = _profile()
    v = _view(p)
    price = float(p["bin_price"][len(p["bin_price"]) // 2])
    snaps = {}
    for m in ("total", "split", "delta", "total"):
        v.set_mode(m)
        info = v.level_at(price)
        snaps.setdefault(m, []).append((info["total"], info["buy"], info["sell"], info["delta"]))
    assert snaps["total"][0] == snaps["total"][1]   # acelasi mod -> aceleasi valori
    # datele nivelului nu depind de mod (doar randarea difera)
    assert snaps["total"][0] == snaps["split"][0] == snaps["delta"][0]


# ---------- 6. hover returneaza valorile corecte ----------
def test_hover_values_and_tags(qapp):
    p = _profile()
    v = _view(p)
    # POC
    at_poc = v.level_at(p["poc"])
    assert at_poc["is_poc"] and at_poc["in_va"]
    # nivel din VA dar sub POC (VAL) -> in_va True, is_poc False (daca VAL != POC)
    at_val = v.level_at(p["val"])
    assert at_val["in_va"]
    # HVN / LVN
    if p["hvn"]:
        assert v.level_at(p["hvn"][0])["is_hvn"]
    if p["lvn"]:
        assert v.level_at(p["lvn"][0])["is_lvn"]
    # departe de orice nivel -> None
    assert v.level_at(float(p["bin_price"].max()) + 10 * ROW) is None


# ---------- 7. no-look-ahead cu replay (causal in view) ----------
def _replay(filename):
    from app.desktop.replay import Replay
    full = ds.load_day(filename, row_size=ROW)
    tk, _ = ds.resolve_ticks(filename, "session", "day")
    return Replay(full, tk.df, va_percent=0.70, row_size=ROW), full


def _causal_ny_profile(filename, snapshot):
    win = ds.session_window(filename, "New York")
    used = [int(ep) for ep in snapshot.footprint if win[0] <= ep < win[1]]
    return ds.profile_from_footprint(snapshot.footprint, used, ROW, 0.70), win


def test_no_lookahead_in_pro_view(qapp):
    r, full = _replay(DAY)
    win = ds.session_window(DAY, "New York")
    idxs = [i for i, ep in enumerate(full.t) if win[0] <= ep < win[1]]
    snap = r.seek_candle(idxs[len(idxs) // 2])
    causal, _ = _causal_ny_profile(DAY, snap)
    v = _view(causal)
    # suma nivelurilor din view == totalul cauzal (nimic viitor adaugat/lipsa)
    tot = sum(v.level_at(float(pr))["total"] for pr in causal["bin_price"])
    assert abs(tot - causal["total"]) < 1.0
    complete = ds.period_profiles(DAY, unit="NY", span="day", row_size=ROW)[0]
    assert 0 < causal["total"] < complete["total"]     # taiat la cursor


# ---------- 8. moduri functioneaza cu profil complet SI cauzal (sync ON/OFF) ----------
def test_modes_work_on_causal_and_complete(qapp):
    r, full = _replay(DAY)
    win = ds.session_window(DAY, "New York")
    idxs = [i for i, ep in enumerate(full.t) if win[0] <= ep < win[1]]
    causal, _ = _causal_ny_profile(DAY, r.seek_candle(idxs[len(idxs) // 2]))
    complete = ds.period_profiles(DAY, unit="NY", span="day", row_size=ROW)[0]
    for prof in (causal, complete):
        v = _view(prof)
        for m in ("total", "split", "delta"):
            v.set_mode(m)
            price = float(prof["bin_price"][len(prof["bin_price"]) // 2])
            assert v.level_at(price) is not None       # randeaza + hover valid in orice mod


# ---------- 9. 3 profile simultan, moduri independente ----------
def test_three_views_independent_modes(qapp):
    p = _profile()
    v1, v2, v3 = _view(p), _view(p), _view(p)
    v1.set_mode("total"); v2.set_mode("split"); v3.set_mode("delta")
    assert (v1.mode(), v2.mode(), v3.mode()) == ("total", "split", "delta")
    price = float(p["bin_price"][len(p["bin_price"]) // 2])
    # datele nivelului identice in toate (modul e doar vizual)
    a, b, c = v1.level_at(price), v2.level_at(price), v3.level_at(price)
    assert a["total"] == b["total"] == c["total"]
    assert a["buy"] == b["buy"] == c["buy"]


# ---------- 10. Main Chart neafectat de modurile VP ----------
def test_main_chart_unaffected_by_modes(qapp):
    from app.desktop.main import MainWindow
    w = MainWindow()
    data_before = w._data
    w.btn_profile_only.setChecked(True)
    card = w.hist_dock.cards()[0]
    for m in ("SPLIT", "DELTA", "TOTAL"):
        card._mode_btns[m].click()
    assert w.period_profiles_item.isVisible() is False
    assert w.candles.isVisible()
    assert [w.cbo_type.itemText(i) for i in range(w.cbo_type.count())] == ["Profil", "Footprint"]
    assert w._data is data_before                      # starea Main Chart neatinsa
    w.btn_profile_only.setChecked(False)


# ---------- 11. performanta: set_mode NU recalculeaza ----------
def test_set_mode_does_not_recompute(qapp, monkeypatch):
    p = _profile()
    v = _view(p)
    calls = {"pf": 0, "pp": 0}
    rp, rpp = ds.profile_from_footprint, ds.period_profiles
    monkeypatch.setattr(ds, "profile_from_footprint",
                        lambda *a, **k: (calls.__setitem__("pf", calls["pf"] + 1), rp(*a, **k))[1])
    monkeypatch.setattr(ds, "period_profiles",
                        lambda *a, **k: (calls.__setitem__("pp", calls["pp"] + 1), rpp(*a, **k))[1])
    for m in ("split", "delta", "total", "split", "delta"):
        v.set_mode(m)
    assert calls == {"pf": 0, "pp": 0}                 # doar re-desenare, zero recalcul


def test_card_mode_buttons_switch_view(qapp):
    card = ProfileCard(SessionStore(), [("04.08", DAY + ".parquet")],
                       default_file=DAY + ".parquet", default_session="New York", row_size=ROW)
    card._mode_btns["DELTA"].click()
    assert card.view.mode() == "delta"
    card._mode_btns["TOTAL"].click()
    assert card.view.mode() == "total"
