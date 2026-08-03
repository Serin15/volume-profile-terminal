"""Teste pentru DeltaEngine (buy/sell/delta per nivel + cumulative delta)."""

from core import DeltaEngine


def test_delta_basic():
    ticks = [
        (100.0, 10, "B"),  # buy
        (100.0, 4, "A"),   # sell
        (101.0, 6, "B"),   # buy
        (101.0, 6, "A"),   # sell
        (102.0, 5, "N"),   # necunoscut -> ignorat la delta
    ]
    engine = DeltaEngine(tick_size=0.25)
    engine.add_ticks_bulk(ticks)
    r = engine.result()

    assert r.total_buy_volume == 16
    assert r.total_sell_volume == 10
    assert r.cumulative_delta == 6
    assert r.delta_per_level[100.0] == 6      # 10 buy - 4 sell
    assert r.delta_per_level[101.0] == 0      # 6 buy - 6 sell
    # tick-ul 'N' de la 102 nu apare in dictionarele de delta
    assert 102.0 not in r.delta_per_level


def test_side_normalization():
    """side poate veni cu spatii sau litere mici; trebuie normalizat."""
    engine = DeltaEngine(tick_size=0.25)
    engine.add_tick(100.0, 5, " b ")
    engine.add_tick(100.0, 3, "a")
    r = engine.result()
    assert r.total_buy_volume == 5
    assert r.total_sell_volume == 3
    assert r.cumulative_delta == 2
