"""Teste pentru VolumeProfileEngine (POC / Value Area / HVN-LVN peaks)."""

from core import VolumeProfileEngine


def test_poc_value_area_synthetic():
    """Profil sintetic cu varf clar la 101.00; VA se extinde din POC."""
    ticks = [
        (100.00, 10), (100.25, 25), (100.50, 60), (100.75, 120),
        (101.00, 200),  # POC
        (101.25, 150), (101.50, 90), (101.75, 40), (102.00, 15), (102.25, 5),
    ]
    engine = VolumeProfileEngine(tick_size=0.25)
    engine.add_ticks_bulk(ticks)
    r = engine.result(va_percent=0.70)

    assert r.total_volume == 715
    assert r.poc == 101.00
    # Expansiune din POC pana la 70% din 715 (=500.5): VAL=100.75, VAH=101.50
    assert r.val == 100.75
    assert r.vah == 101.50


def test_tick_index_no_float_key_errors():
    """Preturi care pot avea reprezentari float dubioase trebuie bucketate corect."""
    engine = VolumeProfileEngine(tick_size=0.25)
    for _ in range(3):
        engine.add_tick(28750.25, 1)
    r = engine.result()
    assert r.poc == 28750.25
    assert r.profile[28750.25] == 3


def test_hvn_peaks_bimodal():
    """Doua varfuri clare (100 si 110) trebuie detectate ca zone HVN distincte."""
    volumes = {
        95: 5, 96: 10, 97: 20, 98: 40, 99: 70, 100: 100, 101: 70, 102: 40,
        103: 20, 104: 15, 105: 12, 106: 15, 107: 20, 108: 40, 109: 70,
        110: 100, 111: 70, 112: 40, 113: 20, 114: 10, 115: 5,
    }
    engine = VolumeProfileEngine(tick_size=1.0)
    for price, vol in volumes.items():
        engine.add_tick(price, vol)

    hvn, lvn = engine.compute_hvn_lvn_peaks()
    assert 100.0 in hvn
    assert 110.0 in hvn
    # Nu trebuie sa returneze zeci de "varfuri" - doar cateva zone reale
    assert len(hvn) <= 4


def test_lvn_within_hvn_range():
    """LVN-urile nu trebuie sa apara in coada sparsa; doar intre HVN-uri."""
    volumes = {
        95: 5, 96: 10, 97: 20, 98: 40, 99: 70, 100: 100, 101: 70, 102: 40,
        103: 20, 104: 15, 105: 12, 106: 15, 107: 20, 108: 40, 109: 70,
        110: 100, 111: 70, 112: 40, 113: 20, 114: 10, 115: 5,
    }
    engine = VolumeProfileEngine(tick_size=1.0)
    for price, vol in volumes.items():
        engine.add_tick(price, vol)

    hvn, lvn = engine.compute_hvn_lvn_peaks()
    assert hvn, "trebuie sa existe HVN-uri"
    lo, hi = min(hvn), max(hvn)
    # Toate LVN-urile trebuie sa fie in intervalul acoperit de HVN-uri
    assert all(lo <= p <= hi for p in lvn), f"LVN in afara intervalului HVN: {lvn}"


def test_empty_engine():
    engine = VolumeProfileEngine(tick_size=0.25)
    assert engine.compute_poc() is None
    assert engine.compute_value_area() == (None, None)
