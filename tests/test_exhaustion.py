"""Exhaustion: detectie determinista pe date sintetice (fara UI, fara date reale).

Verifica: (1) climax + extrema noua + delta in directie -> semnal; (2) filtrele
(volum sub climax / delta gresita / fara extrema noua) NU produc semnal.
"""
import numpy as np

from app.desktop.data_service import detect_exhaustion

WIN = 5


def _series(n=12):
    t = np.arange(n, dtype=float) * 300.0 + 1_700_000_000
    return t


def test_exhaustion_top_fires():
    """Maxim nou + volum climax + delta puternic pozitiva -> 'top'."""
    n = 12; t = _series(n)
    high = 100.0 + np.arange(n) * 1.0          # fiecare lumanare = maxim nou
    low = high - 5.0
    close = high - 1.0
    volume = np.full(n, 100.0)
    volume[8] = 400.0                          # climax la 8 (>2x mediana 100)
    fp = {int(t[i]): {float(high[i]): [50.0, 50.0]} for i in range(n)}
    fp[int(t[8])] = {float(high[8]): [370.0, 30.0]}   # delta +340
    out = detect_exhaustion(fp, t, high, low, close, volume,
                            window=WIN, vol_mult=2.0, delta_frac=0.3)
    kinds = [(o[0], o[2]) for o in out]
    assert (int(t[8]), "top") in kinds
    assert len(out) == 1                       # nimic altceva nu declanseaza


def test_exhaustion_bot_fires():
    """Minim nou + volum climax + delta puternic negativa -> 'bot'."""
    n = 12; t = _series(n)
    low = 100.0 - np.arange(n) * 1.0           # fiecare lumanare = minim nou
    high = low + 5.0
    close = low + 1.0
    volume = np.full(n, 100.0)
    volume[8] = 400.0
    fp = {int(t[i]): {float(low[i]): [50.0, 50.0]} for i in range(n)}
    fp[int(t[8])] = {float(low[8]): [30.0, 370.0]}    # delta -340
    out = detect_exhaustion(fp, t, high, low, close, volume,
                            window=WIN, vol_mult=2.0, delta_frac=0.3)
    assert (int(t[8]), "bot") in [(o[0], o[2]) for o in out]


def test_exhaustion_needs_climax_volume():
    """Maxim nou + delta buna DAR volum normal -> fara semnal."""
    n = 12; t = _series(n)
    high = 100.0 + np.arange(n) * 1.0
    low = high - 5.0; close = high - 1.0
    volume = np.full(n, 100.0)                 # niciun climax
    fp = {int(t[i]): {float(high[i]): [80.0, 20.0]} for i in range(n)}  # delta pozitiva peste tot
    out = detect_exhaustion(fp, t, high, low, close, volume,
                            window=WIN, vol_mult=2.0, delta_frac=0.3)
    assert out == []


def test_exhaustion_needs_direction():
    """Climax + maxim nou DAR delta negativa (vanzare la maxim) -> nu e 'top'."""
    n = 12; t = _series(n)
    high = 100.0 + np.arange(n) * 1.0
    low = high - 5.0; close = high - 1.0
    volume = np.full(n, 100.0); volume[8] = 400.0
    fp = {int(t[i]): {float(high[i]): [50.0, 50.0]} for i in range(n)}
    fp[int(t[8])] = {float(high[8]): [30.0, 370.0]}   # delta -340 la maxim
    out = detect_exhaustion(fp, t, high, low, close, volume,
                            window=WIN, vol_mult=2.0, delta_frac=0.3)
    assert out == []


def test_exhaustion_exclude_last():
    """exclude_last nu analizeaza lumanarea in formare (ultima)."""
    n = 9; t = _series(n)
    high = 100.0 + np.arange(n) * 1.0
    low = high - 5.0; close = high - 1.0
    volume = np.full(n, 100.0); volume[8] = 400.0
    fp = {int(t[i]): {float(high[i]): [50.0, 50.0]} for i in range(n)}
    fp[int(t[8])] = {float(high[8]): [370.0, 30.0]}
    out = detect_exhaustion(fp, t, high, low, close, volume, exclude_last=True,
                            window=WIN, vol_mult=2.0, delta_frac=0.3)
    assert out == []                           # candela 8 e ultima -> exclusa
