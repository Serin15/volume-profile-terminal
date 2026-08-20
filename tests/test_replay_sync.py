"""Teste Faza 2 — sync cauzal Historical Profiles ↔ replay.

Acopera cele 10 cerinte: determinism, seek fwd/back, no-look-ahead, taiere exacta la
cursor, zile istorice complete, sync ON/OFF, mai multe profile simultan, Main Chart
neafectat, SessionStore folosit, performanta (fara recalcul inutil).

Adevarul de referinta e Replay._snapshot() (single source of truth pentru timp) +
data_service.profile_from_footprint — panoul NU trebuie sa devieze de la ele.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import glob

import pytest

from data.loader import PARQUET_DIR
import app.desktop.data_service as ds
from app.desktop.session_store import SessionStore
from app.desktop.historical_panel import HistoricalProfilePanel, ProfileCard

_HAVE = bool(glob.glob(os.path.join(PARQUET_DIR, "*.parquet")))
pytestmark = pytest.mark.skipif(not _HAVE, reason="date reale lipsesc (data/parquet)")

ROW = 2.0
REPLAY_DAY = "20260804"
HIST_DAY = "20260803"


@pytest.fixture(scope="module")
def qapp():
    from pyqtgraph.Qt import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _day_items():
    from app.desktop.main import discover_files, nice_label
    return [(nice_label(f), f) for f in discover_files()]


def _find(ymd):
    for _, f in _day_items():
        if ymd in str(f):
            return f
    return None


def _replay(filename):
    from app.desktop.replay import Replay
    full = ds.load_day(filename, row_size=ROW)
    tk, _ = ds.resolve_ticks(filename, "session", "day")
    return Replay(full, tk.df, va_percent=0.70, row_size=ROW), full


def _mid_session_index(full, window):
    s, e = window
    idxs = [i for i, ep in enumerate(full.t) if s <= ep < e]
    return idxs[len(idxs) // 2] if idxs else len(full.t) // 2


def _causal_total(snapshot, window):
    used = [int(ep) for ep in snapshot.footprint if window[0] <= ep < window[1]]
    prof = ds.profile_from_footprint(snapshot.footprint, used, ROW, 0.70)
    return (prof["total"] if prof else 0.0), used


def _make_card(store, default_file, session="New York"):
    return ProfileCard(store, _day_items(), default_file=default_file,
                       default_session=session, row_size=ROW)


def _configure(card, ymd, session="New York"):
    """Selecteaza data + sesiunea prin combo si reimprospateaza (ca in fluxul real:
    set_day_items pastreaza selectia cu semnale blocate, iar refresh-ul vine dupa)."""
    for i in range(card.cbo_date.count()):
        if ymd in str(card.cbo_date.itemData(i)):
            card.cbo_date.setCurrentIndex(i)
            break
    card.cbo_session.setCurrentText(session)
    card.refresh()


# ---------- 1. determinism ----------
def test_causal_determinism(qapp):
    f = _find(REPLAY_DAY)
    win = ds.session_window(f, "New York")
    r1, full = _replay(f)
    j = _mid_session_index(full, win)
    snap_a = r1.seek_candle(j)
    r2, _ = _replay(f)
    snap_b = r2.seek_candle(j)
    ta, _ = _causal_total(snap_a, win)
    tb, _ = _causal_total(snap_b, win)
    assert ta == tb and ta > 0                     # acelasi cursor -> acelasi VP cauzal


# ---------- 2. seek inainte/inapoi ----------
def test_seek_back_and_forth(qapp):
    f = _find(REPLAY_DAY)
    win = ds.session_window(f, "New York")
    r, full = _replay(f)
    j = _mid_session_index(full, win)
    t_j, _ = _causal_total(r.seek_candle(j), win)
    _causal_total(r.seek_candle(min(j + 25, full.t.size - 1)), win)   # avanseaza
    t_back, _ = _causal_total(r.seek_candle(j), win)                  # inapoi
    assert t_back == t_j                            # seek inapoi = identic (determinist)


# ---------- 3. no-look-ahead ----------
def test_no_lookahead_causal(qapp):
    f = _find(REPLAY_DAY)
    win = ds.session_window(f, "New York")
    r, full = _replay(f)
    j = _mid_session_index(full, win)
    snap = r.seek_candle(j)
    cursor_ep = int(snap.t[-1])
    t1, used = _causal_total(snap, win)
    assert used and all(ep <= cursor_ep for ep in used)   # nicio epoca dupa cursor
    snap2 = r.seek_candle(min(j + 20, full.t.size - 1))
    t2, _ = _causal_total(snap2, win)
    assert t2 >= t1                                 # creste cauzal cand avansezi cursorul


# ---------- 4. taiere EXACTA la cursor + match cu engine ----------
def test_current_day_truncated_at_cursor(qapp):
    f = _find(REPLAY_DAY)
    win = ds.session_window(f, "New York")
    r, full = _replay(f)
    j = _mid_session_index(full, win)
    snap = r.seek_candle(j)
    card = _make_card(SessionStore(), f, "New York")
    card.set_replay_context(f, snap, True)
    card.refresh()
    live = card.view._profile
    truth_total, _ = _causal_total(snap, win)
    assert live["total"] == truth_total            # cardul == recalcul independent din snapshot
    complete = ds.period_profiles(f, unit="NY", span="day", row_size=ROW)[0]
    assert 0 < live["total"] < complete["total"]   # taiat: mai putin decat sesiunea completa


# ---------- 5. zilele istorice raman complete ----------
def test_historical_day_stays_complete(qapp):
    f_replay, f_hist = _find(REPLAY_DAY), _find(HIST_DAY)
    win = ds.session_window(f_replay, "New York")
    r, full = _replay(f_replay)
    snap = r.seek_candle(_mid_session_index(full, win))
    store = SessionStore()
    panel = HistoricalProfilePanel(store, _day_items(), row_size=ROW)
    panel.chk_sync.setChecked(True)
    card = panel.cards()[0]
    _configure(card, HIST_DAY, "New York")
    panel.set_replay_state(f_replay, snap)          # replay pe 04.08, dar cardul e pe 03.08
    complete_hist = ds.period_profiles(f_hist, unit="NY", span="day", row_size=ROW)[0]
    assert not card.is_live()
    assert card.view._profile["total"] == complete_hist["total"]


# ---------- 6. sync ON/OFF ----------
def test_sync_on_off(qapp):
    f = _find(REPLAY_DAY)
    win = ds.session_window(f, "New York")
    r, full = _replay(f)
    snap = r.seek_candle(_mid_session_index(full, win))
    panel = HistoricalProfilePanel(SessionStore(), _day_items(), row_size=ROW)
    card = panel.cards()[0]
    _configure(card, REPLAY_DAY, "New York")
    complete = ds.period_profiles(f, unit="NY", span="day", row_size=ROW)[0]["total"]
    # sync OFF (implicit) -> complet
    panel.set_replay_state(f, snap)
    assert card.view._profile["total"] == complete
    # sync ON -> taiat
    panel.chk_sync.setChecked(True)
    assert card.view._profile["total"] < complete


# ---------- 7. mai multe profile simultan ----------
def test_multiple_profiles_coexist_synced(qapp):
    f_replay, f_hist = _find(REPLAY_DAY), _find(HIST_DAY)
    win = ds.session_window(f_replay, "New York")
    r, full = _replay(f_replay)
    snap = r.seek_candle(_mid_session_index(full, win))
    panel = HistoricalProfilePanel(SessionStore(), _day_items(), row_size=ROW)
    panel.chk_sync.setChecked(True)
    c1 = panel.cards()[0]; _configure(c1, REPLAY_DAY, "New York")
    c2 = panel.add_card(); _configure(c2, HIST_DAY, "New York")
    panel.set_replay_state(f_replay, snap)
    comp04 = ds.period_profiles(f_replay, unit="NY", span="day", row_size=ROW)[0]["total"]
    comp03 = ds.period_profiles(f_hist, unit="NY", span="day", row_size=ROW)[0]["total"]
    assert c1.view._profile["total"] < comp04            # ziua de replay: taiat
    assert c2.view._profile["total"] == comp03           # ziua istorica: complet


# ---------- 8. Main Chart neafectat ----------
def test_main_chart_unaffected_by_sync(qapp):
    from app.desktop.main import MainWindow
    w = MainWindow()
    for i in range(w.cbo_day.count()):
        if REPLAY_DAY in str(w.cbo_day.itemData(i)):
            w.cbo_day.setCurrentIndex(i); break
    w.hist_dock.chk_sync.setChecked(True)
    w.btn_replay.setChecked(True)               # intra in replay
    w._seek_to(w._replay.n_candles // 2)
    assert w.period_profiles_item.isVisible() is False   # niciun overlay istoric pe Main Chart
    assert w.candles.isVisible()
    assert [w.cbo_type.itemText(i) for i in range(w.cbo_type.count())] == ["Profil", "Footprint"]
    w.btn_replay.setChecked(False)              # curata starea


# ---------- 9. SessionStore folosit (istoric) ----------
def test_sessionstore_used_for_historical(qapp, monkeypatch):
    f_replay, f_hist = _find(REPLAY_DAY), _find(HIST_DAY)
    win = ds.session_window(f_replay, "New York")
    r, full = _replay(f_replay)
    snap = r.seek_candle(_mid_session_index(full, win))
    store = SessionStore()
    calls = {"n": 0}
    real = store.get_session_profile
    monkeypatch.setattr(store, "get_session_profile",
                        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(*a, **k))[1])
    panel = HistoricalProfilePanel(store, _day_items(), row_size=ROW)
    panel.chk_sync.setChecked(True)
    card = panel.cards()[0]
    calls["n"] = 0                               # ignoram apelurile de la init
    _configure(card, HIST_DAY, "New York")       # card istoric -> refresh -> store
    panel.set_replay_state(f_replay, snap)
    assert calls["n"] >= 1                       # cardul istoric trece prin SessionStore


# ---------- 10. performanta ----------
def test_throttle_no_recompute_same_cursor(qapp, monkeypatch):
    f = _find(REPLAY_DAY)
    win = ds.session_window(f, "New York")
    r, full = _replay(f)
    snap = r.seek_candle(_mid_session_index(full, win))
    panel = HistoricalProfilePanel(SessionStore(), _day_items(), row_size=ROW)
    panel.chk_sync.setChecked(True)
    card = panel.cards()[0]
    card.set_day_items(_day_items(), select=f); card.cbo_session.setCurrentText("New York")
    calls = {"n": 0}
    real = ds.profile_from_footprint
    monkeypatch.setattr(ds, "profile_from_footprint",
                        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(*a, **k))[1])
    panel.set_replay_state(f, snap)              # calcul o data
    n1 = calls["n"]
    assert n1 >= 1
    panel.set_replay_state(f, snap)              # ACELASI cursor -> throttle, fara recalcul
    assert calls["n"] == n1


def test_historical_card_not_recomputed_on_cursor_move(qapp):
    f_replay, f_hist = _find(REPLAY_DAY), _find(HIST_DAY)
    win = ds.session_window(f_replay, "New York")
    r, full = _replay(f_replay)
    ja = _mid_session_index(full, win)
    panel = HistoricalProfilePanel(SessionStore(), _day_items(), row_size=ROW)
    panel.chk_sync.setChecked(True)
    card = panel.cards()[0]; _configure(card, HIST_DAY, "New York")
    panel.set_replay_state(f_replay, r.seek_candle(ja))
    hist_total = card.view._profile["total"]
    panel.set_replay_state(f_replay, r.seek_candle(min(ja + 20, full.t.size - 1)))  # cursor mutat
    complete_hist = ds.period_profiles(f_hist, unit="NY", span="day", row_size=ROW)[0]["total"]
    assert card.view._profile["total"] == hist_total == complete_hist   # istoric = neschimbat, complet
