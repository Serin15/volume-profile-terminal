"""
Loader unic de date
--------------------
Inlocuieste cele 4 functii de incarcare duplicate din scripturile vechi
(load_databento_csv, visualize_profile, multi_day_analysis, session_reanalysis).

O SINGURA sursa de adevar pentru:
  - citirea unui fisier Databento (schema Trades, CME GLBX.MDP3)
  - alegerea automata a simbolului activ (volumul cel mai mare)
  - accesul la side (agresor) si timestamp
  - granita CORECTA de sesiune futures (18:00 ET, DST-aware: 22:00 UTC vara / 23:00 iarna)
  - citirea din Parquet cand exista (mult mai rapid decat CSV)

Coloane asteptate in CSV Databento (Trades, cu "Include symbol field"):
    ts_recv, ts_event, rtype, publisher_id, instrument_id, action, side,
    price, size, symbol, sequence, flags, ts_in_delta, depth

Principiu: loader-ul NU calculeaza nimic (fara POC/delta) - doar aduce date
curate, structurate. Calculul e treaba engine-urilor din core/.
"""

import os
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

# Granita sesiunii de trading futures CME (NQ): 18:00 America/New_York (= 17:00 CT).
# DST-AWARE: convertim tick-ul in ET si comparam ora LOCALA (18:00), NU o ora UTC fixa.
# Astfel granita e corecta si vara (18:00 EDT = 22:00 UTC) si iarna (18:00 EST = 23:00 UTC).
SESSION_TZ = "America/New_York"
SESSION_BOUNDARY_HOUR = 18

# Coloanele CSV brut Databento de care avem nevoie (ignoram restul).
_CSV_COLS = ["ts_recv", "price", "size", "side", "symbol"]
# Coloanele schemei NORMALIZATE (folosite in Parquet si intern).
_NORM_COLS = ["ts", "price", "size", "side", "symbol"]

_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(_DATA_DIR, "raw")
PARQUET_DIR = os.path.join(_DATA_DIR, "parquet")


@dataclass
class SessionTicks:
    """
    Tick-uri incarcate pentru UN simbol, gata de bagat in engine-uri.

    df: DataFrame cu coloanele [ts (datetime64 UTC), price, size, side].
    symbol: simbolul ales (ex. 'NQU6').
    volume_per_symbol: dict {simbol: volum total} - util ca sa vezi ce contracte
                       erau in fisier si de ce s-a ales acesta.
    source: calea din care s-a incarcat (csv sau parquet).
    """
    df: pd.DataFrame
    symbol: str
    volume_per_symbol: dict
    source: str

    def __len__(self):
        return len(self.df)

    def price_volume(self):
        """Lista de (price, size) - pentru VolumeProfileEngine.add_ticks_bulk."""
        return list(zip(self.df["price"].to_numpy(), self.df["size"].to_numpy()))

    def price_volume_side(self):
        """Lista de (price, size, side) - pentru DeltaEngine.add_ticks_bulk."""
        return list(zip(
            self.df["price"].to_numpy(),
            self.df["size"].to_numpy(),
            self.df["side"].to_numpy(),
        ))

    def ohlc(self):
        """(open, high, low, close, volum) din tick-uri, in ordine cronologica."""
        prices = self.df["price"]
        return (
            float(prices.iloc[0]),
            float(prices.max()),
            float(prices.min()),
            float(prices.iloc[-1]),
            float(self.df["size"].sum()),
        )

    def by_session(self):
        """
        Grupeaza tick-urile pe SESIUNE reala futures (granita la 18:00 ET, DST-aware),
        nu pe ziua calendaristica UTC bruta.

        Returneaza dict {session_date (str 'YYYY-MM-DD'): SessionTicks}.
        Primele/ultimele sesiuni pot fi incomplete daca fisierele nu acopera
        marginile intervalului - vezi nota din handoff.
        """
        df = self.df.copy()
        # Regula DST-AWARE: convertim in ET; daca ora LOCALA >= 18:00, tick-ul apartine
        # sesiunii zilei urmatoare. Corect si vara (18:00 EDT=22:00 UTC) si iarna
        # (18:00 EST=23:00 UTC). ts poate fi tz-naive (parquet) -> il tratam ca UTC.
        ts = df["ts"]
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize("UTC")
        et = ts.dt.tz_convert(SESSION_TZ)
        shifted = et + pd.to_timedelta((et.dt.hour >= SESSION_BOUNDARY_HOUR).astype(int), unit="D")
        df["session"] = shifted.dt.date.astype(str)

        out = {}
        for sess, group in df.groupby("session"):
            out[sess] = SessionTicks(
                df=group.drop(columns="session").reset_index(drop=True),
                symbol=self.symbol,
                volume_per_symbol={self.symbol: float(group["size"].sum())},
                source=f"{self.source} [sesiune {sess}]",
            )
        return out


def session_date_for(ts) -> str:
    """
    Sesiunea de trading din care face parte un timestamp (nu ziua calendaristica).
    ts: pandas.Timestamp sau datetime (UTC; tz-naive e tratat ca UTC).
    Granita la 18:00 ET, DST-aware (vara 22:00 UTC / iarna 23:00 UTC).
    """
    ts = pd.Timestamp(ts)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    et = ts.tz_convert(SESSION_TZ)
    if et.hour >= SESSION_BOUNDARY_HOUR:
        return (et + timedelta(days=1)).date().isoformat()
    return et.date().isoformat()


def _resolve_path(path_or_name: str):
    """
    Rezolva o cale sau un nume scurt catre fisierul real.
    Cauta, in ordine: calea data direct -> data/parquet/ -> data/raw/.
    Prefera Parquet daca exista un echivalent (mult mai rapid).
    Returneaza (path, is_parquet).
    """
    # 1. Calea exista exact asa cum a fost data
    if os.path.isfile(path_or_name):
        return path_or_name, path_or_name.endswith(".parquet")

    name = os.path.basename(path_or_name)
    stem_csv = name[:-4] if name.endswith(".csv") else name
    parquet_name = (stem_csv + ".parquet") if not name.endswith(".parquet") else name

    # 2. Varianta Parquet (preferata)
    pq = os.path.join(PARQUET_DIR, parquet_name)
    if os.path.isfile(pq):
        return pq, True

    # 3. CSV brut in data/raw/
    csv_name = name if name.endswith(".csv") else (stem_csv + ".csv")
    raw = os.path.join(RAW_DIR, csv_name)
    if os.path.isfile(raw):
        return raw, False

    raise FileNotFoundError(
        f"Nu am gasit '{path_or_name}'. Cautat ca atare, in {PARQUET_DIR} si {RAW_DIR}."
    )


def _read_raw(path: str, is_parquet: bool) -> pd.DataFrame:
    """
    Citeste fisierul intr-un DataFrame NORMALIZAT [ts, price, size, side, symbol].
    Parquet: deja normalizat (scris de convert_to_parquet.py), se citeste direct.
    CSV: schema bruta Databento (ts_recv, ...), se parseaza si se normalizeaza.
    """
    if is_parquet:
        df = pd.read_parquet(path, columns=_NORM_COLS)
    else:
        df = pd.read_csv(
            path,
            usecols=lambda c: c in _CSV_COLS,
            dtype={"side": "string", "symbol": "string"},
        )
        # Timestamp brut -> datetime UTC (ISO 8601 cu nanosecunde, sufix Z)
        if "ts_recv" in df.columns:
            df["ts"] = pd.to_datetime(df["ts_recv"], utc=True, format="ISO8601")
        else:
            df["ts"] = pd.NaT

    missing = {"price", "size"} - set(df.columns)
    if missing:
        raise ValueError(f"Fisierul {path} nu are coloanele necesare: {missing}")

    # Normalizare tipuri (idempotent - sigur si pe parquet deja curat)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["size"] = pd.to_numeric(df["size"], errors="coerce")
    df = df.dropna(subset=["price", "size"])

    if "side" not in df.columns:
        df["side"] = "N"
    df["side"] = df["side"].fillna("N").astype(str)

    if "symbol" not in df.columns:
        df["symbol"] = "UNKNOWN"
    df["symbol"] = df["symbol"].fillna("UNKNOWN").astype(str)

    return df[_NORM_COLS]


def read_file(path_or_name: str) -> pd.DataFrame:
    """
    Rezolva calea si citeste fisierul intr-un DataFrame normalizat cu TOATE
    simbolurile (fara filtrare). Folosit de load_ticks/load_many si de scriptul
    de conversie Parquet. Coloane: [ts, price, size, side, symbol].
    """
    path, is_parquet = _resolve_path(path_or_name)
    return _read_raw(path, is_parquet)


def load_ticks(path_or_name: str, symbol: str = None) -> SessionTicks:
    """
    Incarca tick-urile dintr-un fisier, filtrate pe UN singur simbol.

    path_or_name: cale completa, sau nume scurt (ex. 'glbx-mdp3-20260706.trades.csv'
                  sau chiar 'glbx-mdp3-20260706.trades') - se rezolva automat in
                  data/parquet/ (preferat) sau data/raw/.
    symbol: daca None, se alege automat simbolul cu volumul cel mai mare
            (contractul activ, ex. NQU6).
    """
    path, is_parquet = _resolve_path(path_or_name)
    df = _read_raw(path, is_parquet)

    volume_per_symbol = df.groupby("symbol")["size"].sum().to_dict()
    if not volume_per_symbol:
        raise ValueError(f"Niciun rand valid in {path}.")

    if symbol is None:
        symbol = max(volume_per_symbol.items(), key=lambda kv: kv[1])[0]

    sub = df[df["symbol"] == symbol].copy()
    sub = sub.sort_values("ts", kind="stable").reset_index(drop=True)
    sub = sub[["ts", "price", "size", "side"]]

    return SessionTicks(
        df=sub,
        symbol=symbol,
        volume_per_symbol={k: float(v) for k, v in volume_per_symbol.items()},
        source=path,
    )


def load_many(paths, symbol: str = None) -> SessionTicks:
    """
    Incarca si concateneaza mai multe fisiere intr-un singur SessionTicks,
    pentru simbolul cu volumul cel mai mare GLOBAL (pe toate fisierele).
    Util pentru analiza multi-day / composite / pe sesiuni reale.
    """
    frames = []
    global_volume = {}
    sources = []

    for p in paths:
        path, is_parquet = _resolve_path(p)
        df = _read_raw(path, is_parquet)
        for sym, vol in df.groupby("symbol")["size"].sum().items():
            global_volume[sym] = global_volume.get(sym, 0.0) + float(vol)
        frames.append(df)
        sources.append(path)

    if not frames:
        raise ValueError("Niciun fisier de incarcat.")

    if symbol is None:
        symbol = max(global_volume.items(), key=lambda kv: kv[1])[0]

    combined = pd.concat(frames, ignore_index=True)
    sub = combined[combined["symbol"] == symbol].copy()
    sub = sub.sort_values("ts", kind="stable").reset_index(drop=True)
    sub = sub[["ts", "price", "size", "side"]]

    return SessionTicks(
        df=sub,
        symbol=symbol,
        volume_per_symbol=global_volume,
        source=f"{len(sources)} fisiere",
    )
