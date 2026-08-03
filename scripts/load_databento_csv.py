"""
Volume Profile pentru O zi (un fisier Databento).

Acum foloseste loader-ul unic (data/loader.py) - alege automat contractul activ
si citeste Parquet daca exista (mult mai rapid decat CSV brut).

Foloseste:
    python scripts/load_databento_csv.py glbx-mdp3-20260706.trades.csv
    (merge si cu nume scurt: 'glbx-mdp3-20260706.trades' - se rezolva singur)
"""

import sys

from core import VolumeProfileEngine
from data import load_ticks


def main():
    if len(sys.argv) < 2:
        print("Foloseste: python scripts/load_databento_csv.py nume_fisier.csv")
        sys.exit(1)

    filepath = sys.argv[1]
    print(f"Incarc {filepath}...")

    st = load_ticks(filepath)

    print("\n=== Simboluri gasite in fisier (volum total) ===")
    for sym, vol in sorted(st.volume_per_symbol.items(), key=lambda kv: -kv[1]):
        marker = "  <- folosit pentru VP" if sym == st.symbol else ""
        print(f"{sym:>10} : {vol:>12.0f}{marker}")

    print(f"\nNumar tick-uri pentru {st.symbol}: {len(st)}  (sursa: {st.source})")

    engine = VolumeProfileEngine(tick_size=0.25)
    engine.add_ticks_bulk(st.price_volume())
    result = engine.result(va_percent=0.70)

    print(f"\n=== Volume Profile pentru {st.symbol} ===")
    print(f"Volum total: {result.total_volume:.0f}")
    print(f"POC:         {result.poc}")
    print(f"VAH:         {result.vah}")
    print(f"VAL:         {result.val}")
    print(f"HVN peaks:   {sorted(result.hvn_peaks, reverse=True)[:8]}")
    print(f"LVN peaks:   {sorted(result.lvn_peaks)[:8]}")

    print("\n=== Top 10 niveluri dupa volum ===")
    top10 = sorted(result.profile.items(), key=lambda kv: -kv[1])[:10]
    for price, vol in top10:
        marker = ""
        if price == result.poc:
            marker = "  <- POC"
        elif price == result.vah:
            marker = "  <- VAH"
        elif price == result.val:
            marker = "  <- VAL"
        print(f"{price:>10.2f} : {vol:>10.0f}{marker}")


if __name__ == "__main__":
    main()
