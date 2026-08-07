"""
P1a - Noduri STRUCTURATE de Volume Profile (compute_nodes).

Verifica: margini (low/high) + latime, clasa major/minor, cele 3 moduri de LVN
(full / between_hvns / value_area), si COMPATIBILITATEA cu compute_hvn_lvn_peaks
(aceleasi preturi -> nu am schimbat detectia veche, doar am adaugat structura).

Totul sintetic / in-memory -> nu depinde de date reale.
"""

from core import VolumeProfileEngine, VolumeNode


# Profil bimodal: doua varfuri (100, 110), vale la mijloc (~105), cozi sparse la
# margini (95, 115) = vai IN AFARA intervalului HVN (discount/premium).
_BIMODAL = {
    95: 5, 96: 10, 97: 20, 98: 40, 99: 70, 100: 100, 101: 70, 102: 40,
    103: 20, 104: 15, 105: 12, 106: 15, 107: 20, 108: 40, 109: 70,
    110: 100, 111: 70, 112: 40, 113: 20, 114: 10, 115: 5,
}

# Profil cu o vale LATA si plata intre doua varfuri -> zona LVN cu latime > 0.
_WIDE_VALLEY = {0: 100, 1: 60, 2: 10, 3: 10, 4: 10, 5: 60, 6: 100}


def _engine(profile, tick_size=1.0):
    e = VolumeProfileEngine(tick_size=tick_size)
    for price, vol in profile.items():
        e.add_tick(price, vol)
    return e


# ---------- structura de baza ----------

def test_nodes_are_volume_node_instances_with_valid_edges():
    hvn, lvn = _engine(_BIMODAL).compute_nodes()
    assert hvn and lvn
    for node in hvn + lvn:
        assert isinstance(node, VolumeNode)
        assert node.kind in ("hvn", "lvn")
        assert node.low <= node.price <= node.high        # reprezentantul e in zona
        assert node.width == round(node.high - node.low, 8)
        assert node.width >= 0.0
        assert node.prominence >= 0.0
        assert node.tier in ("major", "minor")


def test_hvn_and_lvn_kinds_are_correct():
    hvn, lvn = _engine(_BIMODAL).compute_nodes()
    assert all(n.kind == "hvn" for n in hvn)
    assert all(n.kind == "lvn" for n in lvn)


def test_merged_lvn_zone_has_width():
    """Vale plata pe mai multe niveluri adiacente -> UN nod cu latime, nu trei noduri."""
    _, lvn = _engine(_WIDE_VALLEY).compute_nodes()
    assert len(lvn) == 1, f"vale continua = o singura zona, nu {len(lvn)}"
    z = lvn[0]
    assert z.high > z.low and z.width > 0, "zona ar trebui sa aiba latime"
    assert z.low <= 2 and z.high >= 4                      # acopera nivelurile 2..4


# ---------- moduri LVN ----------

def test_lvn_full_is_default_and_includes_edges():
    """IMPLICIT = full: prinde vaile de la margini (in afara intervalului HVN)."""
    e = _engine(_BIMODAL)
    hvn, lvn_full = e.compute_nodes()                      # lvn_mode="full" implicit
    lo, hi = hvn[0].price, hvn[-1].price
    assert any(z.price < lo or z.price > hi for z in lvn_full), \
        "modul full ar trebui sa prinda vai in afara intervalului HVN"


def test_lvn_between_hvns_stays_inside_hvn_range():
    e = _engine(_BIMODAL)
    hvn, lvn = e.compute_nodes(lvn_mode="between_hvns")
    lo, hi = hvn[0].price, hvn[-1].price
    assert all(lo <= z.price <= hi for z in lvn)


def test_lvn_between_is_subset_of_full():
    e = _engine(_BIMODAL)
    _, lvn_full = e.compute_nodes(lvn_mode="full")
    _, lvn_btw = e.compute_nodes(lvn_mode="between_hvns")
    assert {z.price for z in lvn_btw}.issubset({z.price for z in lvn_full})


def test_lvn_value_area_restricts_to_va():
    e = _engine(_BIMODAL)
    vah, val = e.compute_value_area(0.70)
    _, lvn_va = e.compute_nodes(lvn_mode="value_area", va_percent=0.70)
    assert all(val <= z.price <= vah for z in lvn_va)


def test_unknown_lvn_mode_behaves_like_full():
    e = _engine(_BIMODAL)
    _, lvn_full = e.compute_nodes(lvn_mode="full")
    _, lvn_unknown = e.compute_nodes(lvn_mode="tralala")
    assert {z.price for z in lvn_unknown} == {z.price for z in lvn_full}


# ---------- tier major / minor ----------

def test_tier_threshold_splits_major_and_minor():
    """Prag 0.7: valea de mijloc (prominenta ~0.68) = minor; valea de la margine (~0.87) = major."""
    _, lvn = _engine(_BIMODAL).compute_nodes(major_prominence_ratio=0.7)
    by_price = {round(z.price): z for z in lvn}
    assert by_price[105].tier == "minor"
    assert by_price[95].tier == "major"


def test_deep_nodes_are_major_by_default():
    hvn, lvn = _engine(_BIMODAL).compute_nodes()           # prag implicit 0.6
    # Varfurile clare (100/110) si valea adanca (~105) ies mult in evidenta -> major.
    assert all(n.tier == "major" for n in hvn)


# ---------- compatibilitate cu compute_hvn_lvn_peaks (detectia veche neschimbata) ----------

def test_compute_nodes_prices_match_legacy_peaks():
    """Preturile din compute_nodes = exact cele din compute_hvn_lvn_peaks (aceiasi candidati)."""
    e = _engine(_BIMODAL)
    # full <-> lvn_within_hvn=False ; between_hvns <-> lvn_within_hvn=True
    hvn_peaks, lvn_peaks_full = e.compute_hvn_lvn_peaks(lvn_within_hvn=False)
    _, lvn_peaks_btw = e.compute_hvn_lvn_peaks(lvn_within_hvn=True)
    hvn_nodes, lvn_nodes_full = e.compute_nodes(lvn_mode="full")
    _, lvn_nodes_btw = e.compute_nodes(lvn_mode="between_hvns")
    assert [n.price for n in hvn_nodes] == hvn_peaks
    assert [n.price for n in lvn_nodes_full] == lvn_peaks_full
    assert [n.price for n in lvn_nodes_btw] == lvn_peaks_btw


def test_empty_engine_returns_empty_nodes():
    assert VolumeProfileEngine(tick_size=0.25).compute_nodes() == ([], [])
