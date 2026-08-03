"""
Analiza multi-day: mai multe fisiere (o saptamana) deodata.
  1. OHLC + verificare de continuitate intre zile
  2. Volume Profile per zi
  3. Composite Profile (toata perioada combinata)

Foloseste:
    python scripts/multi_day_analysis.py glbx-mdp3-20260706.trades.csv glbx-mdp3-20260707.trades.csv ...
"""

import sys

from core import VolumeProfileEngine
from data import load_ticks, load_many


def main():
    if len(sys.argv) < 2:
        print("Foloseste: python scripts/multi_day_analysis.py fisier1 fisier2 ...")
        sys.exit(1)

    filepaths = sys.argv[1:]
    print(f"Procesez {len(filepaths)} fisiere...\n")

    zile = []
    for filepath in filepaths:
        st = load_ticks(filepath)
        o, h, l, c, vol = st.ohlc()
        zile.append({"file": filepath, "st": st, "o": o, "h": h, "l": l, "c": c, "vol": vol})
        print(f"{filepath:45} | {st.symbol:>8} | O:{o:>9.2f} H:{h:>9.2f} "
              f"L:{l:>9.2f} C:{c:>9.2f} | Vol:{vol:>10.0f}")

    print("\n=== Verificare continuitate (close ziua N vs open ziua N+1) ===")
    prag = 50.0
    for i in range(len(zile) - 1):
        diff = abs(zile[i + 1]["o"] - zile[i]["c"])
        status = "OK" if diff < prag else "ATENTIE - diferenta mare"
        print(f"{zile[i]['file']:38} -> diff: {diff:>7.2f} | {status}")

    print("\n=== Volume Profile per zi ===")
    for zi in zile:
        engine = VolumeProfileEngine(tick_size=0.25)
        engine.add_ticks_bulk(zi["st"].price_volume())
        r = engine.result(va_percent=0.70)
        print(f"{zi['file']:45} | POC: {r.poc:>9.2f} | VAH: {r.vah:>9.2f} | VAL: {r.val:>9.2f}")

    print("\n=== Composite Profile (toate zilele combinate) ===")
    combined = load_many(filepaths)
    engine = VolumeProfileEngine(tick_size=0.25)
    engine.add_ticks_bulk(combined.price_volume())
    r = engine.result(va_percent=0.70)
    print(f"Simbol: {combined.symbol}  |  Volum total: {r.total_volume:.0f}")
    print(f"POC composite:  {r.poc}")
    print(f"VAH composite:  {r.vah}")
    print(f"VAL composite:  {r.val}")
    print(f"HVN peaks:      {sorted(r.hvn_peaks, reverse=True)[:8]}")
    print(f"LVN peaks:      {sorted(r.lvn_peaks)[:8]}")


if __name__ == "__main__":
    main()
