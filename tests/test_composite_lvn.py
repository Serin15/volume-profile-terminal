"""
Teste pentru cele doua functii adaugate cu workflow-ul "pro":
  1. LVN pe TOT profilul (lvn_within_hvn=False) - vai inclusiv spre margini.
  2. Composite pe fereastra FIXA de N zile (_last_n_days_block).

Ambele sunt sintetice / pe structuri in-memory -> nu depind de date reale.
"""

from core import VolumeProfileEngine
from app.desktop.data_service import (_last_n_days_block, session_profiles,
                                      SESSION_DEFS)


# Profil bimodal: doua varfuri clare (100 si 110), vale la mijloc (~105),
# si cozi sparse la margini (95 si 115) = zonele de discount/premium.
_BIMODAL = {
    95: 5, 96: 10, 97: 20, 98: 40, 99: 70, 100: 100, 101: 70, 102: 40,
    103: 20, 104: 15, 105: 12, 106: 15, 107: 20, 108: 40, 109: 70,
    110: 100, 111: 70, 112: 40, 113: 20, 114: 10, 115: 5,
}


def _bimodal_engine():
    engine = VolumeProfileEngine(tick_size=1.0)
    for price, vol in _BIMODAL.items():
        engine.add_tick(price, vol)
    return engine


def test_lvn_full_is_superset_of_restricted():
    """Modul 'tot profilul' include tot ce da modul restrans (restrictia doar filtreaza)."""
    engine = _bimodal_engine()
    _, lvn_restr = engine.compute_hvn_lvn_peaks(lvn_within_hvn=True)
    _, lvn_full = engine.compute_hvn_lvn_peaks(lvn_within_hvn=False)
    assert set(lvn_restr).issubset(set(lvn_full))


def test_lvn_full_includes_edges_outside_hvn():
    """Cu lvn_within_hvn=False apar vai si IN AFARA intervalului HVN (spre margini)."""
    engine = _bimodal_engine()
    hvn, _ = engine.compute_hvn_lvn_peaks()
    _, lvn_full = engine.compute_hvn_lvn_peaks(lvn_within_hvn=False)
    lo, hi = min(hvn), max(hvn)
    assert any(p < lo or p > hi for p in lvn_full), \
        f"modul full ar trebui sa prinda vai la margini; lvn={lvn_full}, HVN=[{lo},{hi}]"


def test_lvn_restricted_stays_between_hvn():
    """Modul restrans (implicit) NU iese din intervalul HVN - comportament neschimbat."""
    engine = _bimodal_engine()
    hvn, lvn = engine.compute_hvn_lvn_peaks()          # implicit lvn_within_hvn=True
    lo, hi = min(hvn), max(hvn)
    assert all(lo <= p <= hi for p in lvn)


# ---------- Composite pe fereastra fixa de N zile ----------

_AVAILABLE = {
    "20260101": "a.parquet",
    "20260102": "b.parquet",
    "20260103": "c.parquet",
    "20260110": "d.parquet",
    "20260116": "e.parquet",
}


def test_last_n_days_window_15():
    """Ultimele 15 zile pana la 15 ian -> [01..15]; 16 ian e in afara ferestrei."""
    block = _last_n_days_block("20260115", _AVAILABLE, 15)
    assert block == ["a.parquet", "b.parquet", "c.parquet", "d.parquet"]


def test_last_n_days_window_small():
    """Fereastra de 2 zile pana la 03 ian -> doar [02, 03]."""
    block = _last_n_days_block("20260103", _AVAILABLE, 2)
    assert block == ["b.parquet", "c.parquet"]


def test_last_n_days_order_chronological():
    """Fisierele vin in ordine cronologica (composite corect indiferent de dict order)."""
    block = _last_n_days_block("20260116", _AVAILABLE, 90)
    assert block == ["a.parquet", "b.parquet", "c.parquet", "d.parquet", "e.parquet"]


def test_last_n_days_empty_date():
    """Fara data -> lista goala (nu arunca)."""
    assert _last_n_days_block(None, _AVAILABLE, 15) == []


# ---------- Profile per-sesiune (Asia / Londra / NY) ----------

def test_session_defs_shape():
    """Ambele moduri au exact Asia/Londra/NY, fiecare cu fus + start/stop."""
    for mode in ("real", "ro"):
        names = [s[0] for s in SESSION_DEFS[mode]]
        assert names == ["Asia", "Londra", "NY"]
        for name, tz, start, end in SESSION_DEFS[mode]:
            assert isinstance(tz, str) and "/" in tz
            assert len(start) == 2 and len(end) == 2


def test_session_defs_ny_rth_real():
    """In modul 'real', NY e ancorat pe New_York la RTH (09:30-16:00)."""
    ny = [s for s in SESSION_DEFS["real"] if s[0] == "NY"][0]
    _, tz, start, end = ny
    assert tz == "America/New_York"
    assert start == (9, 30) and end == (16, 0)


def test_session_profiles_no_date_graceful():
    """Fisier fara data in nume -> dict gol, nu arunca."""
    assert session_profiles("garbage.txt", SESSION_DEFS["real"]) == {}
