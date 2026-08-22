"""Teste pentru loader-ul unic (alegere simbol, side, granita de sesiune)."""

import pandas as pd

from data import load_ticks, session_date_for, SESSION_TZ, SESSION_BOUNDARY_HOUR


CSV_CONTENT = """ts_recv,price,size,side,symbol
2026-07-06T21:59:00.000000000Z,100.00,10,B,NQU6
2026-07-06T22:30:00.000000000Z,101.00,5,A,NQU6
2026-07-06T23:00:00.000000000Z,102.00,7,B,NQU6
2026-07-06T20:00:00.000000000Z,50.00,2,B,NQZ6
"""


def _write_csv(tmp_path):
    p = tmp_path / "mini.csv"
    p.write_text(CSV_CONTENT, encoding="utf-8")
    return str(p)


def test_symbol_auto_selection(tmp_path):
    """Trebuie ales simbolul cu volumul cel mai mare (NQU6: 22 vs NQZ6: 2)."""
    st = load_ticks(_write_csv(tmp_path))
    assert st.symbol == "NQU6"
    assert len(st) == 3
    assert st.volume_per_symbol["NQU6"] == 22
    assert st.volume_per_symbol["NQZ6"] == 2


def test_side_preserved(tmp_path):
    st = load_ticks(_write_csv(tmp_path))
    sides = set(st.df["side"].tolist())
    assert sides == {"A", "B"}


def test_price_volume_side_shape(tmp_path):
    st = load_ticks(_write_csv(tmp_path))
    pvs = st.price_volume_side()
    assert len(pvs) == 3
    assert all(len(t) == 3 for t in pvs)


def test_session_boundary(tmp_path):
    """
    Tick la 21:59 UTC -> sesiunea zilei 06; tick la 22:30 si 23:00 -> sesiunea 07.
    """
    st = load_ticks(_write_csv(tmp_path))
    sessions = st.by_session()
    assert set(sessions.keys()) == {"2026-07-06", "2026-07-07"}
    assert len(sessions["2026-07-06"]) == 1  # doar 21:59
    assert len(sessions["2026-07-07"]) == 2  # 22:30 + 23:00


def test_session_date_for_rule_summer_unchanged():
    """Vara (EDT): granita 18:00 ET = 22:00 UTC -> comportamentul de dinainte, NESCHIMBAT."""
    assert (SESSION_TZ, SESSION_BOUNDARY_HOUR) == ("America/New_York", 18)
    before = pd.Timestamp("2026-07-06T21:59:00Z")   # 17:59 EDT -> sesiunea 06
    after = pd.Timestamp("2026-07-06T22:30:00Z")    # 18:30 EDT -> sesiunea 07
    assert session_date_for(before) == "2026-07-06"
    assert session_date_for(after) == "2026-07-07"
