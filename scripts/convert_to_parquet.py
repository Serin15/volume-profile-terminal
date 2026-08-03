"""
Conversie CSV -> Parquet (rulare O SINGURA DATA, sau cand adaugi date noi).

De ce: fisierele CSV Databento sunt ~40-50 MB fiecare si se parseaza lent.
Parquet e columnar, comprimat si tipizat -> incarcare de ordine de marime mai
rapida si fisiere mult mai mici. Loader-ul (data/loader.py) citeste automat
Parquet cand exista, deci dupa conversie totul devine mai rapid, transparent.

Citeste tot din data/raw/*.csv si scrie in data/parquet/*.parquet
(schema normalizata: ts, price, size, side, symbol - TOATE simbolurile pastrate).

Foloseste:
    python scripts/convert_to_parquet.py            # converteste tot ce e in data/raw
    python scripts/convert_to_parquet.py fisier.csv  # doar un fisier anume
"""

import os
import sys
import glob
import time

from data.loader import read_file, RAW_DIR, PARQUET_DIR


def convert_one(csv_path: str) -> str:
    name = os.path.basename(csv_path)
    stem = name[:-4] if name.endswith(".csv") else name
    out_path = os.path.join(PARQUET_DIR, stem + ".parquet")

    t0 = time.time()
    df = read_file(csv_path)  # normalizat, toate simbolurile
    df.to_parquet(out_path, index=False, compression="snappy")
    dt = time.time() - t0

    csv_mb = os.path.getsize(csv_path) / 1e6
    pq_mb = os.path.getsize(out_path) / 1e6
    print(f"  {name:40} {csv_mb:6.1f} MB CSV -> {pq_mb:6.1f} MB Parquet  "
          f"({len(df):>8} randuri, {dt:.1f}s)")
    return out_path


def main():
    os.makedirs(PARQUET_DIR, exist_ok=True)

    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        files = sorted(glob.glob(os.path.join(RAW_DIR, "*.csv")))

    if not files:
        print(f"Niciun CSV gasit in {RAW_DIR}")
        sys.exit(1)

    print(f"Convertesc {len(files)} fisier(e) -> {PARQUET_DIR}\n")
    for f in files:
        convert_one(f)
    print("\nGata. Loader-ul va citi automat Parquet de acum.")


if __name__ == "__main__":
    main()
