"""Anchored VWAP: corectitudine + stabilitate numerica (staticmethod, fara UI)."""
import numpy as np
from types import SimpleNamespace

from app.desktop.main import MainWindow


def _make_d(n=30, base=27000.0):
    rng = np.random.default_rng(42)
    t = np.arange(n, dtype=float) * 300.0 + 1_700_000_000
    close = base + np.cumsum(rng.normal(0, 5, n))
    high = close + rng.uniform(1, 8, n)
    low = close - rng.uniform(1, 8, n)
    volume = rng.uniform(50, 500, n)
    return SimpleNamespace(t=t, high=high, low=low, close=close,
                           volume=volume, bar_seconds=300)


def test_avwap_anchor_invariants():
    """La ancora: aVWAP = pretul tipic al lumanarii, deviatia = 0 (numeric stabil)."""
    d = _make_d()
    k = 10
    t, avwap, std = MainWindow._compute_avwap(d, float(d.t[k]))
    tp0 = (d.high[k] + d.low[k] + d.close[k]) / 3.0
    assert len(t) == len(d.t) - k
    assert abs(avwap[0] - tp0) < 1e-9
    assert std[0] < 1e-6            # centrare -> fara anulare catastrofala


def test_avwap_final_equals_weighted_mean():
    """Valoarea finala = media pretului tipic ponderata cu volumul, de la ancora."""
    d = _make_d()
    k = 7
    _, avwap, _ = MainWindow._compute_avwap(d, float(d.t[k]))
    tp = (d.high[k:] + d.low[k:] + d.close[k:]) / 3.0
    v = d.volume[k:]
    manual = float((tp * v).sum() / v.sum())
    assert abs(avwap[-1] - manual) < 1e-6


def test_avwap_std_matches_weighted_variance():
    """Deviatia standard = radacina variantei ponderate (verificare independenta)."""
    d = _make_d()
    k = 0
    _, avwap, std = MainWindow._compute_avwap(d, float(d.t[k]))
    tp = (d.high + d.low + d.close) / 3.0
    v = d.volume
    for i in (5, 15, 29):
        w = v[: i + 1]
        x = tp[: i + 1]
        mean = (x * w).sum() / w.sum()
        var = (w * (x - mean) ** 2).sum() / w.sum()
        assert abs(avwap[i] - mean) < 1e-6
        assert abs(std[i] - np.sqrt(var)) < 1e-6


def test_avwap_std_nonneg():
    d = _make_d()
    _, _, std = MainWindow._compute_avwap(d, float(d.t[0]))
    assert np.all(std >= 0.0)


def test_avwap_anchor_clamped():
    """Ancora inaintea sesiunii -> incepe de la prima lumanare (idx 0)."""
    d = _make_d()
    t, avwap, _ = MainWindow._compute_avwap(d, float(d.t[0]) - 10_000)
    assert len(t) == len(d.t)
    tp0 = (d.high[0] + d.low[0] + d.close[0]) / 3.0
    assert abs(avwap[0] - tp0) < 1e-9
