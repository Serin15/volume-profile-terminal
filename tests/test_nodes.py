"""
Test de CORECTITUDINE pentru HVN/LVN pe DATE REALE.

Blocheaza definitia: fiecare HVN trebuie sa fie un nivel cu volum PESTE medie
(varf real), fiecare LVN un nivel cu volum SUB medie (vale reala). Ruleaza pe
profilul la aceeasi rezolutie de afisare pe care o foloseste aplicatia.

Daca fisierul de date real lipseste, testul se sare (nu esueaza).
"""

import os
import pytest

from data.loader import PARQUET_DIR
from core import VolumeProfileEngine
from app.desktop.data_service import load_day, _get_ticks

DATA_FILE = "glbx-mdp3-20260722.trades.parquet"
ROW = 2.0

pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.path.join(PARQUET_DIR, DATA_FILE)),
    reason="date reale lipsesc (data/parquet)",
)


def _mean_and_profile():
    """Profil la rezolutia de afisare + volumul mediu pe nivel (referinta independenta)."""
    tk, _ = _get_ticks(DATA_FILE, "session")
    e = VolumeProfileEngine(tick_size=ROW)
    e.add_ticks_bulk(tk.price_volume())
    prof = {round(p, 2): v for p, v in e.result().profile.items()}
    mean = sum(prof.values()) / len(prof)
    return mean, prof


def test_hvn_are_peaks_above_mean():
    d = load_day(DATA_FILE, mode="session", row_size=ROW)
    mean, prof = _mean_and_profile()
    assert d.hvn, "ar trebui sa existe cel putin un HVN pe aceasta zi"
    for h in d.hvn:
        vol = prof.get(round(h, 2), 0)
        assert vol > mean, f"HVN {h} are volum {vol:.0f} <= media {mean:.0f} (nu e varf)"


def test_lvn_are_valleys_below_mean():
    d = load_day(DATA_FILE, mode="session", row_size=ROW)
    mean, prof = _mean_and_profile()
    for l in d.lvn:
        vol = prof.get(round(l, 2), 0)
        assert vol < mean, f"LVN {l} are volum {vol:.0f} >= media {mean:.0f} (nu e vale)"


def test_node_counts_bounded():
    d = load_day(DATA_FILE, mode="session", row_size=ROW)
    assert len(d.hvn) <= 5, "prea multe HVN"
    assert len(d.lvn) <= 3, "prea multe LVN"


def test_poc_is_the_highest_volume_level():
    """POC = nivelul cu volumul maxim, la ACEEASI rezolutie de afisare (independent)."""
    d = load_day(DATA_FILE, mode="session", row_size=ROW)
    _, prof = _mean_and_profile()
    max_price = max(prof.items(), key=lambda kv: kv[1])[0]
    assert abs(d.poc - max_price) < 1e-6, f"POC {d.poc} != nivelul de volum maxim {max_price}"


def test_poc_is_the_tallest_displayed_bar():
    """POC trebuie sa cada pe cea mai groasa bara AFISATA (ce vezi = ce se calculeaza)."""
    d = load_day(DATA_FILE, mode="session", row_size=ROW)
    totals = d.bin_buy + d.bin_sell
    tallest_price = d.bin_price[totals.argmax()]
    assert abs(d.poc - tallest_price) < 1e-6, \
        f"POC {d.poc} nu e pe cea mai groasa bara {tallest_price}"
