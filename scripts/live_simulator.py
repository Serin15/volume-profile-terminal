"""
Live Simulator - reda date istorice ca un flux "live", aratand cum evolueaza
POC/VAH/VAL ora cu ora (Developing Profile). Checkpoint la schimbarea orei.

Foloseste:
    python scripts/live_simulator.py glbx-mdp3-20260723.trades.csv
"""

import sys

from core import VolumeProfileEngine
from data import load_ticks


def main():
    if len(sys.argv) < 2:
        print("Foloseste: python scripts/live_simulator.py nume_fisier.csv")
        sys.exit(1)

    filepath = sys.argv[1]
    print(f"Incarc {filepath} (ordine cronologica)...\n")

    st = load_ticks(filepath)  # loader-ul intoarce deja tick-urile sortate pe ts
    print(f"Simbol: {st.symbol}  |  Tick-uri totale: {len(st)}\n")
    print("=== Developing Profile - evolutia POC/VAH/VAL ora cu ora ===\n")
    print(f"{'Ora (UTC)':<16} | {'Tick-uri':>10} | {'Volum':>10} | {'POC':>10} | {'VAH':>10} | {'VAL':>10}")
    print("-" * 90)

    engine = VolumeProfileEngine(tick_size=0.25)
    current_hour = None
    tick_count = 0

    df = st.df
    hours = df["ts"].dt.strftime("%Y-%m-%dT%H").to_numpy()
    prices = df["price"].to_numpy()
    sizes = df["size"].to_numpy()

    for i in range(len(df)):
        engine.add_tick(prices[i], sizes[i])
        tick_count += 1
        hour = hours[i]
        if hour != current_hour:
            if current_hour is not None:
                r = engine.result(va_percent=0.70)
                print(f"{current_hour:<16} | {tick_count:>10} | {r.total_volume:>10.0f} | "
                      f"{r.poc:>10.2f} | {r.vah:>10.2f} | {r.val:>10.2f}")
            current_hour = hour

    r = engine.result(va_percent=0.70)
    print(f"{current_hour:<16} | {tick_count:>10} | {r.total_volume:>10.0f} | "
          f"{r.poc:>10.2f} | {r.vah:>10.2f} | {r.val:>10.2f}")

    print("\n=== Rezultat FINAL ===")
    print(f"POC: {r.poc}  |  VAH: {r.vah}  |  VAL: {r.val}")


if __name__ == "__main__":
    main()
