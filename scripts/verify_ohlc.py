"""
Verificare INDEPENDENTA a datelor: recalculeaza OHLC + volum direct din tick-uri,
fara engine-ul de VP, ca sa poti compara cu o sursa publica externa
(Yahoo Finance / Investing.com).

Foloseste:
    python scripts/verify_ohlc.py glbx-mdp3-20260723.trades.csv
"""

import sys

from data import load_ticks


def main():
    if len(sys.argv) < 2:
        print("Foloseste: python scripts/verify_ohlc.py nume_fisier.csv")
        sys.exit(1)

    filepath = sys.argv[1]
    st = load_ticks(filepath)
    o, h, l, c, vol = st.ohlc()

    first_ts = st.df["ts"].iloc[0]
    last_ts = st.df["ts"].iloc[-1]

    print(f"=== Verificare independenta pentru {st.symbol} ===")
    print(f"Fisier: {st.source}")
    print(f"Numar tick-uri: {len(st)}")
    print(f"Interval timestamp: {first_ts}  ->  {last_ts}\n")
    print(f"Open:  {o}")
    print(f"High:  {h}")
    print(f"Low:   {l}")
    print(f"Close: {c}")
    print(f"Volum total: {vol:.0f}\n")
    print("Compara High/Low/Volum cu o sursa publica (Yahoo Finance/Investing.com)")
    print("pentru contractul si ziua respectiva. Daca sunt apropiate, datele sunt corecte.")


if __name__ == "__main__":
    main()
