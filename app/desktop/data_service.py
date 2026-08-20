"""
Serviciu de date pentru aplicatia desktop.
Pod intre loader/engine (Python pur) si GUI. NU stie nimic despre Qt.

load_day() -> DayData: lumanari OHLC + profil split buy/sell + POC/VA/HVN/LVN.
"""

import os
import glob
import math
import datetime
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field
from collections import defaultdict

import numpy as np

from core import VolumeProfileEngine, DeltaEngine
from data import load_ticks, load_many
from data.loader import PARQUET_DIR, RAW_DIR

TICK_SIZE = 0.25

INTERVAL_SECONDS = {"1min": 60, "5min": 300, "15min": 900, "30min": 1800,
                    "1h": 3600, "2h": 7200, "4h": 14400, "1D": 86400}


@dataclass
class DayData:
    symbol: str
    n_ticks: int
    # Lumanari
    t: np.ndarray            # epoch secunde (UTC)
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    vwap: np.ndarray
    cvd: np.ndarray            # Cumulative Delta per lumanare (developing)
    last_price: float
    bar_seconds: int
    # Profil (grupat pe row_size)
    bin_price: np.ndarray
    bin_buy: np.ndarray
    bin_sell: np.ndarray
    row_size: float
    # Niveluri cheie
    poc: float
    vah: float
    val: float
    hvn: list = field(default_factory=list)
    lvn: list = field(default_factory=list)
    # Rezumat
    total_volume: float = 0.0
    cum_delta: float = 0.0
    buy_total: float = 0.0
    sell_total: float = 0.0
    mode: str = "session"
    incomplete: bool = False
    # Footprint: {candle_epoch_sec: {pret: [buy, sell]}}
    footprint: dict = field(default_factory=dict)
    big_trades: list = field(default_factory=list)   # (epoca, pret, marime, side)
    absorption: list = field(default_factory=list)   # (epoca, pret, kind) kind: "bull"/"bear"
    exhaustion: list = field(default_factory=list)   # (epoca, pret, kind, vol, delta) kind: "top"/"bot"
    level_reactions: list = field(default_factory=list)  # (epoca, pret, kind, lvl): Acc/Rej la nivel developing
    # Developing POC / Value Area: valoarea per lumanare, cumulativ de la inceputul sesiunii
    dev_poc: np.ndarray = field(default_factory=lambda: np.zeros(0))
    dev_vah: np.ndarray = field(default_factory=lambda: np.zeros(0))
    dev_val: np.ndarray = field(default_factory=lambda: np.zeros(0))
    # Speed of tape: trade-uri (print-uri) pe secunda per lumanare (viteza tape-ului)
    tps: np.ndarray = field(default_factory=lambda: np.zeros(0))


def _date_of(name):
    base = os.path.basename(name)
    for part in base.replace(".", "-").split("-"):
        if len(part) == 8 and part.isdigit():
            return part
    return None


def _available_by_date():
    files = glob.glob(os.path.join(PARQUET_DIR, "*.parquet")) or \
        glob.glob(os.path.join(RAW_DIR, "*.csv"))
    out = {}
    for f in files:
        d = _date_of(f)
        if d:
            out[d] = os.path.basename(f)
    return out


def _top_nodes(hvn, lvn, profile, max_hvn=5, max_lvn=3):
    """
    Pastreaza doar nodurile SEMNIFICATIVE, nu toate maximele/minimele locale:
      - HVN: cele cu volumul cel mai mare (varfuri reale, nu bump-uri mici)
      - LVN: vaile cele mai adanci (volum cel mai mic), din intervalul HVN
    Astfel raman cateva linii relevante, nu zeci.
    """
    def vol(p):
        return profile.get(round(p, 8), 0.0)

    hvn_top = sorted(sorted(hvn, key=vol, reverse=True)[:max_hvn])
    lvn_top = sorted(sorted(lvn, key=vol)[:max_lvn])
    return hvn_top, lvn_top


def _contiguous_block(date, available):
    """
    Lista fisierelor din blocul de zile CONSECUTIVE care contine `date`
    (ex. pentru 07 iul -> [06,07,08,09,10] daca sunt descarcate).
    """
    dates = sorted(available.keys())
    if date not in available:
        return [available[d] for d in dates]  # fallback: tot
    to_d = lambda s: datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    block = [date]
    # extindem inainte
    i = dates.index(date)
    j = i - 1
    while j >= 0 and (to_d(block[0]) - to_d(dates[j])).days == 1:
        block.insert(0, dates[j]); j -= 1
    # extindem dupa
    j = i + 1
    while j < len(dates) and (to_d(dates[j]) - to_d(block[-1])).days == 1:
        block.append(dates[j]); j += 1
    return [available[d] for d in block]


def _get_ticks(filename, mode, available=None):
    """
    mode 'utc'     -> ziua calendaristica UTC (00:00-24:00) din fisierul dat.
    mode 'session' -> sesiunea futures reala (22:00 UTC ziua precedenta ->
                      22:00 UTC ziua curenta), combinand fisierul zilei precedente.
    Intoarce (SessionTicks, is_incomplete).
    """
    if mode != "session":
        return load_ticks(filename), False

    date = _date_of(filename)
    if not date:
        return load_ticks(filename), False

    available = available if available is not None else _available_by_date()
    d = datetime.date(int(date[:4]), int(date[4:6]), int(date[6:8]))
    prev = (d - datetime.timedelta(days=1)).strftime("%Y%m%d")
    prev_file = available.get(prev)

    paths = ([prev_file] if prev_file else []) + [available.get(date, filename)]
    combined = load_many(paths)
    key = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    sessions = combined.by_session()
    if key in sessions:
        # Incompleta daca lipseste fisierul zilei precedente (coada 22:00-24:00)
        return sessions[key], (prev_file is None)
    return load_ticks(filename), True


BIG_TRADE_MIN = 25   # prag "tranzactie mare" pe NQ (single print) - tunable


def _big_trades(df, bar_seconds, min_size=BIG_TRADE_MIN):
    """Tranzactiile individuale mari (>= min_size): (epoca_lumanare, pret, marime, side)."""
    sub = df[df["size"] >= min_size]
    if sub.empty:
        return []
    tsec = (sub["ts"].astype("int64") // 10**9).to_numpy()
    cep = (tsec // bar_seconds) * bar_seconds
    prices = sub["price"].to_numpy()
    sizes = sub["size"].to_numpy()
    sides = sub["side"].astype(str).to_numpy()
    return [(int(cep[i]), float(prices[i]), float(sizes[i]), sides[i])
            for i in range(len(sub))]


def _build_footprint(df, interval, row_size):
    """
    Footprint: pentru fiecare lumanare (bin de timp) si fiecare nivel de pret,
    volumul de cumparare agresiva (buy) si vanzare agresiva (sell).
    Returneaza {candle_epoch_sec: {pret: [buy, sell]}}.
    """
    fp = df[["ts", "price", "size", "side"]].copy()
    fp["candle"] = (fp["ts"].dt.floor(interval).astype("int64") // 10**9)
    fp["pbin"] = (fp["price"] / row_size).round().astype("int64")
    grouped = fp.groupby(["candle", "pbin", "side"], observed=True)["size"].sum()

    out = {}
    for (candle, pbin, side), vol in grouped.items():
        price = round(pbin * row_size, 4)
        cell = out.setdefault(int(candle), {}).setdefault(price, [0.0, 0.0])
        if side == "B":
            cell[0] += float(vol)
        elif side == "A":
            cell[1] += float(vol)
    return out


# --- Absorption (order flow) ---
# Volum agresiv MARE la extrema unei lumanari, dar pretul NU continua (respingere).
#   Bull absorption: la MINIM, vanzarea agresiva (sell) domina dar e ABSORBITA de
#     cumparatori pasivi -> pretul tine si inchide sus (wick de jos) -> SUPORT.
#   Bear absorption: la MAXIM, cumpararea agresiva (buy) domina dar e absorbita de
#     vanzatori pasivi -> pretul nu urca, inchide jos (wick de sus) -> REZISTENTA.
# Praguri reglate pentru NY OPEN (16:30 RO, volum mare) - filtreaza zgomotul deschiderii,
# prinde doar semnalele mari. Reglabile oricand din ⚙.
ABS_MIN_VOL = 70     # volum agresiv minim in zona extrema (NQ) - putin ridicat pt open
ABS_DOM = 1.8        # agresorul dominant >= ABS_DOM x cealalta parte (calitate: dezechilibru clar)
ABS_FRAC = 0.22      # zona extrema concentreaza >= 22% din volumul lumanarii
ABS_REJECT = 0.60    # inchidere la >= 60% din range fata de extrema (respingere curata)
ABS_ZONE = 2         # cate bin-uri de pret de la extrema formeaza "zona"

# Exhaustion (climax): extrema NOUA + volum climax + delta dominanta in directia trendului
EXH_WINDOW = 14      # cate lumanari inapoi pt extrema + mediana de volum
EXH_VOL_MULT = 2.0   # climax: volum >= EXH_VOL_MULT x mediana (ridicat pt volumul mare de la open)
EXH_DELTA_FRAC = 0.20  # delta in directia trendului >= 20% din volumul lumanarii


def _detector_defaults(bar_seconds):
    """Praguri absorption/exhaustion ADAPTATE la interval, ca detectorii sa prinda aceleasi
    evenimente REALE indiferent de timeframe (altfel pe 1min exhaustion trage ~35x/zi = tapet,
    pe 15min ~0). Fereastra exhaustion in TIMP (~30 min); granularitatea fina (1-2 min, scalping)
    cere prag de climax mai strict fiindca volumul de 1min e mai zgomotos. Validat pe date reale:
    1min -> ~5 exhaustion + ~3 absorption/sesiune (fata de ~35 + ~9 la pragurile fixe vechi).
    Mediu (5-15 min) = calibrarea validata initial (NESCHIMBAT). Returneaza (abs_kw, exh_kw)."""
    if bar_seconds <= 120:            # 1-2 min (scalping fin)
        win = max(3, int(round(1800 / bar_seconds)))     # ~30 min de lookback
        return ({"min_vol": 85, "frac": 0.30},
                {"window": win, "vol_mult": 3.5, "delta_frac": 0.25})
    if bar_seconds <= 900:            # 5-15 min (neschimbat)
        return ({"min_vol": ABS_MIN_VOL, "frac": ABS_FRAC},
                {"window": EXH_WINDOW, "vol_mult": EXH_VOL_MULT, "delta_frac": EXH_DELTA_FRAC})
    return ({"min_vol": 60, "frac": 0.20},                # coarse (>15 min)
            {"window": 10, "vol_mult": 1.8, "delta_frac": EXH_DELTA_FRAC})


def detect_absorption(footprint, t, high, low, close, row_size, exclude_last=False,
                      min_vol=ABS_MIN_VOL, dom=ABS_DOM, frac=ABS_FRAC,
                      reject=ABS_REJECT, zone=ABS_ZONE):
    """
    Detecteaza absorption pe lumanarile INCHISE. Pragurile sunt parametri (reglabile din UI).
    Returneaza [(candle_epoch, pret_extrema, kind, buy_vol, sell_vol)] cu kind "bull"/"bear".
    """
    out = []
    n = len(t)
    last = n - (1 if exclude_last else 0)
    for i in range(last):
        ep = int(round(t[i]))
        cells = footprint.get(ep)
        if not cells:
            continue
        h, l, c = float(high[i]), float(low[i]), float(close[i])
        rng = h - l
        if rng <= 0:
            continue
        v_total = sum(b + s for (b, s) in cells.values())
        if v_total <= 0:
            continue
        prices = sorted(cells.keys())
        low_zone = prices[:zone]        # cele mai joase niveluri
        high_zone = prices[-zone:]      # cele mai inalte niveluri
        buy_lo = sum(cells[p][0] for p in low_zone)
        sell_lo = sum(cells[p][1] for p in low_zone)
        buy_hi = sum(cells[p][0] for p in high_zone)
        sell_hi = sum(cells[p][1] for p in high_zone)

        # Bull: sell agresiv absorbit la minim + inchidere sus (respingere de jos)
        if (sell_lo >= min_vol and sell_lo >= dom * buy_lo
                and sell_lo >= frac * v_total
                and (c - l) / rng >= reject):
            out.append((ep, l, "bull", buy_lo, sell_lo))     # + volum buy/sell zona (pt tooltip)
        # Bear: buy agresiv absorbit la maxim + inchidere jos (respingere de sus)
        if (buy_hi >= min_vol and buy_hi >= dom * sell_hi
                and buy_hi >= frac * v_total
                and (h - c) / rng >= reject):
            out.append((ep, h, "bear", buy_hi, sell_hi))
    return out


def detect_exhaustion(footprint, t, high, low, close, volume, exclude_last=False,
                      window=EXH_WINDOW, vol_mult=EXH_VOL_MULT, delta_frac=EXH_DELTA_FRAC):
    """
    Exhaustion (climax): o lumanare face o EXTREMA NOUA pe fereastra, cu volum CLIMAX
    (>> mediana recenta) si delta puternica IN directia trendului (cumparatori la maxim
    nou / vanzatori la minim nou) -> ultimul impuls, potential reversal.
    (Diferit de absorption: acolo volumul e absorbit si pretul respinge; aici e un climax
    care duce pretul la o extrema noua.)
    Returneaza [(candle_epoch, pret_extrema, kind, volum, delta)] cu kind "top"/"bot".
    """
    out = []
    n = len(t)
    last = n - (1 if exclude_last else 0)
    hi = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    vol_arr = np.asarray(volume, dtype=float)
    for i in range(window, last):
        ep = int(round(t[i]))
        cells = footprint.get(ep)
        if not cells:
            continue
        vol = float(vol_arr[i])
        if vol <= 0:
            continue
        med = float(np.median(vol_arr[i - window:i]))
        if med <= 0 or vol < vol_mult * med:       # nu e climax de volum
            continue
        delta = sum(b - s for (b, s) in cells.values())
        new_high = hi[i] >= hi[i - window:i + 1].max() - 1e-9
        new_low = lo[i] <= lo[i - window:i + 1].min() + 1e-9
        if new_high and delta > 0 and delta >= delta_frac * vol:
            out.append((ep, float(hi[i]), "top", vol, delta))   # cumparatori epuizati la maxim
        elif new_low and delta < 0 and -delta >= delta_frac * vol:
            out.append((ep, float(lo[i]), "bot", vol, delta))   # vanzatori epuizati la minim
    return out


def detect_level_reactions(t, o, h, l, c, dev_poc, dev_vah, dev_val, row_size,
                           exclude_last=False, lookback=20, poke_ratio=0.35,
                           accept_ratio=0.5, min_sep=5):
    """Acceptance / Rejection la MARGINILE Value Area developing (VAH/VAL) - concept Market
    Profile: pretul ACCEPTA sau RESPINGE iesirea din valoare. CAUZAL (dev_* la bara i + OHLC
    <= i), per bara INCHISA, FILTRAT -> putine si notabile (nu tapet, NU la POC=magnet).
      Rejection = wick IESE din valoare (peste VAH / sub VAL) dar inchide INAPOI inauntru.
      Acceptance = inchide DECISIV in afara valorii (breakout care tine).
    Returneaza [(epoca, pret_nivel, kind, lvl)] cu kind in
    {rejection_up, rejection_down, acceptance_up, acceptance_down}."""
    out = []
    n = len(t)
    last = n - (1 if exclude_last else 0)
    rng_series = np.asarray(h, float) - np.asarray(l, float)
    last_emit = -999            # dedupe GLOBAL (nu per-tip) -> fara markere lipite
    for i in range(lookback, last):
        seg = rng_series[max(0, i - lookback):i]
        rng = float(np.median(seg)) if len(seg) else 0.0
        if rng <= 0:
            continue
        poke, acc, tol = poke_ratio * rng, accept_ratio * rng, 0.5 * row_size
        oi, hi, li, ci = float(o[i]), float(h[i]), float(l[i]), float(c[i])
        vah, val = float(dev_vah[i]), float(dev_val[i])
        cand = None
        if vah > 0 and hi > vah + poke and ci < vah - tol:            # respins la VAH (bearish)
            cand = (hi - vah, vah, "rejection_down", "vah")
        elif val > 0 and li < val - poke and ci > val + tol:          # respins la VAL (bullish)
            cand = (val - li, val, "rejection_up", "val")
        elif vah > 0 and oi <= vah + tol and ci > vah + acc:          # acceptat peste VAH (bullish)
            cand = (ci - vah, vah, "acceptance_up", "vah")
        elif val > 0 and oi >= val - tol and ci < val - acc:          # acceptat sub VAL (bearish)
            cand = (val - ci, val, "acceptance_down", "val")
        if cand is None:
            continue
        _, price, kind, lk = cand
        if i - last_emit < min_sep:
            continue
        last_emit = i
        out.append((int(round(t[i])), float(price), kind, lk))
    return out


def profile_from_footprint(footprint, epochs, row_size, va_percent=0.70,
                           lvn_full_profile=False):
    """
    Profil VP (POC/VA/HVN/LVN + split buy/sell) agregat DOAR pe lumanarile din `epochs`,
    reutilizand footprint-ul deja calculat. Folosit de modul VISIBLE RANGE (profil pe
    ce vezi pe ecran). Returneaza dict sau None daca nu e volum.

    lvn_full_profile: daca True, LVN-urile se detecteaza pe TOT profilul (inclusiv spre
        margini = discount/premium), nu doar vaile dintre HVN-uri.
    """
    buy_by, sell_by = {}, {}
    for ep in epochs:
        cells = footprint.get(int(ep))
        if not cells:
            continue
        for price, (b, s) in cells.items():
            buy_by[price] = buy_by.get(price, 0.0) + b
            sell_by[price] = sell_by.get(price, 0.0) + s
    prices = sorted(set(buy_by) | set(sell_by))
    if not prices:
        return None
    vp = VolumeProfileEngine(tick_size=row_size)
    for p in prices:
        tot = buy_by.get(p, 0.0) + sell_by.get(p, 0.0)
        if tot > 0:
            vp.add_tick(p, tot)
    vpr = vp.result(va_percent=va_percent)
    node_hvn, node_lvn = vp.compute_hvn_lvn_peaks(
        min_prominence_ratio=0.4, lvn_within_hvn=not lvn_full_profile)
    hvn, lvn = _top_nodes(node_hvn, node_lvn, vpr.profile,
                          max_lvn=6 if lvn_full_profile else 3)
    return dict(
        bin_price=np.array(prices, dtype=float),
        bin_buy=np.array([buy_by.get(p, 0.0) for p in prices]),
        bin_sell=np.array([sell_by.get(p, 0.0) for p in prices]),
        poc=vpr.poc or 0.0, vah=vpr.vah or 0.0, val=vpr.val or 0.0,
        hvn=hvn, lvn=lvn, total=vpr.total_volume)


def prior_session_levels(filename, mode="session", va_percent=0.70, row_size=2.0):
    """
    Nivelurile SESIUNII PRECEDENTE (pentru backtesting): yPOC / yVAH / yVAL +
    PDH / PDL (high/low sesiune) + close. Gaseste ultima sesiune disponibila
    inainte de ziua din `filename`. Varianta usoara (doar VP + high/low, fara
    footprint) ca sa nu incetineasca reload-ul. Intoarce dict sau None.
    """
    date = _date_of(filename)
    if not date:
        return None
    available = _available_by_date()
    d = datetime.date(int(date[:4]), int(date[4:6]), int(date[6:8]))
    prior_file, prior_date = None, None
    for back in range(1, 8):                     # cauta pana la 7 zile inapoi
        pdate = (d - datetime.timedelta(days=back)).strftime("%Y%m%d")
        if pdate in available:
            prior_file, prior_date = available[pdate], pdate
            break
    if prior_file is None:
        return None

    tk, _ = _get_ticks(prior_file, mode, available)
    if tk.df.empty:
        return None
    vp = VolumeProfileEngine(tick_size=row_size)
    vp.add_ticks_bulk(tk.price_volume())
    vpr = vp.result(va_percent=va_percent)
    prices = tk.df["price"]
    last = tk.df.sort_values("ts", kind="stable")["price"].iloc[-1]
    return {
        "poc": vpr.poc, "vah": vpr.vah, "val": vpr.val,
        "high": float(prices.max()), "low": float(prices.min()),
        "close": float(last),
        "date": f"{prior_date[6:8]}.{prior_date[4:6]}",
    }


# Definitii implicite de sesiuni pentru profile SEPARATE (Asia / Londra / NY).
#   'real' -> orele ancorate in fusul bursei (auto vara/iarna via zoneinfo).
#   'ro'   -> aceleasi ferestre, dar fixate ca ore Romania (fara ajustare DST).
# Format: (nume, fus, (ora_start, min_start), (ora_stop, min_stop)) - orele in `fus`.
SESSION_DEFS = {
    "real": [
        ("Asia",   "Asia/Tokyo",        (8, 0),  (16, 0)),
        ("Londra", "Europe/London",     (8, 0),  (16, 0)),
        ("NY",     "America/New_York",  (9, 30), (16, 0)),   # RTH / cash open
    ],
    "ro": [
        ("Asia",   "Europe/Bucharest",  (2, 0),  (10, 0)),
        ("Londra", "Europe/Bucharest",  (10, 0), (18, 0)),
        ("NY",     "Europe/Bucharest",  (16, 30), (23, 0)),
    ],
}


def session_window(date, session, sessions=None, mode="real"):
    """(start, end) epoci UTC pentru o SESIUNE (Asia/Londra/NY) pe o data data.

    Reutilizeaza SESSION_DEFS + ACEEASI ancorare zoneinfo ca period_profiles/
    session_profiles (auto vara/iarna). Intoarce None pentru 'Full Day'/'Zi'/'Toate'
    (fara fereastra = toata sesiunea). Accepta si numele prietenoase (New York/London).

    `date`: 'YYYYMMDD' sau nume de fisier (se extrage data). Folosit de sync-ul cauzal
    din Historical Profiles (Faza 2): fereastra sesiunii zilei de replay, ca sa taiem
    footprint-ul cauzal exact pe acea sesiune.
    """
    if session in (None, "Zi", "Full Day", "Toate", "Toate sesiunile"):
        return None
    d = _date_of(date) or (date if isinstance(date, str) and len(date) == 8 else None)
    if not d or len(d) != 8:
        return None
    y, mo, dd = int(d[:4]), int(d[4:6]), int(d[6:8])
    sessions = sessions or SESSION_DEFS.get(mode, SESSION_DEFS["real"])
    aliases = {"New York": "NY", "London": "Londra"}      # nume prietenos -> intern
    want = aliases.get(session, session)
    for name, tz, (sh, sm), (eh, em) in sessions:
        if name != want:
            continue
        z = ZoneInfo(tz)
        start = datetime.datetime(y, mo, dd, sh, sm, tzinfo=z).timestamp()
        end = datetime.datetime(y, mo, dd, eh, em, tzinfo=z).timestamp()
        if end <= start:
            end += 86400.0
        return (start, end)
    return None


def session_profiles(filename, sessions, mode="session",
                     va_percent=0.70, row_size=2.0, lvn_full_profile=False):
    """
    Volume Profile SEPARAT pe fiecare sesiune (Asia/Londra/NY) pentru ziua din `filename`.

    `sessions`: lista de (nume, fus, (sh, sm), (eh, em)) - orele in fusul `fus`.
        Fereastra fiecarei sesiuni se ancoreaza pe data zilei in fusul ei, apoi se
        converteste in UTC (zoneinfo -> corect si vara si iarna). Tick-urile din
        fereastra formeaza profilul acelei sesiuni.

    Returneaza {nume: {poc, vah, val, hvn, lvn, high, low, start, end, total}}
    (doar sesiunile care au volum). start/end = epoci UTC (secunde).
    """
    date = _date_of(filename)
    if not date:
        return {}
    tk, _ = _get_ticks(filename, mode)
    df = tk.df
    if df.empty:
        return {}
    tsec = (df["ts"].astype("int64") // 10**9).to_numpy()
    prices = df["price"].to_numpy()
    sizes = df["size"].to_numpy()
    y, mo, dd = int(date[:4]), int(date[4:6]), int(date[6:8])

    out = {}
    for name, tz, (sh, sm), (eh, em) in sessions:
        z = ZoneInfo(tz)
        start = datetime.datetime(y, mo, dd, sh, sm, tzinfo=z).timestamp()
        end = datetime.datetime(y, mo, dd, eh, em, tzinfo=z).timestamp()
        if end <= start:
            end += 86400.0   # sesiune care trece de miezul noptii in fusul ei
        mask = (tsec >= start) & (tsec < end)
        if not mask.any():
            continue
        sp = prices[mask]
        vp = VolumeProfileEngine(tick_size=row_size)
        vp.add_ticks_bulk(zip(sp.tolist(), sizes[mask].tolist()))
        vpr = vp.result(va_percent=va_percent)
        node_hvn, node_lvn = vp.compute_hvn_lvn_peaks(
            min_prominence_ratio=0.4, lvn_within_hvn=not lvn_full_profile)
        hvn, lvn = _top_nodes(node_hvn, node_lvn, vpr.profile,
                              max_lvn=6 if lvn_full_profile else 3)
        out[name] = {
            "poc": vpr.poc, "vah": vpr.vah, "val": vpr.val,
            "hvn": hvn, "lvn": lvn,
            "high": float(sp.max()), "low": float(sp.min()),
            "start": float(start), "end": float(end),
            "total": vpr.total_volume,
        }
    return out


def _last_n_days_block(date, available, n):
    """Fisierele pentru ultimele `n` zile calendaristice pana la `date` inclusiv
    (doar cele existente). Composite pe fereastra FIXA de N zile, spre deosebire de
    _contiguous_block care ia tot blocul de zile consecutive descarcate."""
    if not date:
        return []
    to_d = lambda s: datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    try:
        end = to_d(date)
    except (ValueError, TypeError):
        return []
    start = end - datetime.timedelta(days=n - 1)
    return [available[d] for d in sorted(available) if start <= to_d(d) <= end]


def resolve_ticks(filename, mode="session", span="day"):
    """Tick-urile (SessionTicks) folosite pentru o selectie - reutilizat si de Replay.

    span: 'day'  -> o sesiune;
          'week' -> tot blocul de zile consecutive descarcate;
          'Nd'   -> composite pe ultimele N zile calendaristice (ex. '15d', '90d').
    """
    if span == "week":
        date = _date_of(filename)
        available = _available_by_date()
        block = _contiguous_block(date, available) if date else [filename]
        return load_many(block), False
    if isinstance(span, str) and span.endswith("d") and span[:-1].isdigit():
        date = _date_of(filename)
        available = _available_by_date()
        block = _last_n_days_block(date, available, int(span[:-1])) if date else []
        return load_many(block or [filename]), False
    return _get_ticks(filename, mode)


def developing_levels(footprint, t, row_size, va_percent):
    """POC/VAH/VAL 'developing': valoarea cumulativa dupa fiecare lumanare (de la inceputul
    sesiunii). Foloseste ACELASI motor ca profilul final -> ultima valoare = POC/VA total.
    Pe lumanari fara volum se pastreaza ultima valoare (forward-fill)."""
    n = len(t)
    dp = np.zeros(n); dvah = np.zeros(n); dval = np.zeros(n)
    if n == 0:
        return dp, dvah, dval
    vp = VolumeProfileEngine(tick_size=row_size)
    last = (0.0, 0.0, 0.0)
    for i in range(n):
        cells = footprint.get(int(round(float(t[i]))), {})
        if cells:
            vp.add_ticks_bulk([(p, b + s) for p, (b, s) in cells.items()])
        r = vp.result(va_percent=va_percent)
        if r.poc is not None:
            last = (r.poc, r.vah, r.val)
        dp[i], dvah[i], dval[i] = last
    return dp, dvah, dval


def _vp_split_from_ticks(df, row_size, va_percent, lvn_full_profile):
    """VP structurat (bin-uri split buy/sell + POC/VA/HVN/LVN) dintr-un DataFrame de
    tick-uri [ts,price,size,side]. Aceeasi logica de bin-uri ca load_day (o singura
    definitie a profilului) - reutilizata de profile per-perioada (Profile Only)."""
    if df is None or df.empty:
        return None
    prices = df["price"].to_numpy()
    sizes = df["size"].to_numpy()
    sides = df["side"].astype(str).to_numpy()
    vp = VolumeProfileEngine(tick_size=row_size)
    vp.add_ticks_bulk(zip(prices.tolist(), sizes.tolist()))
    vpr = vp.result(va_percent=va_percent)
    if not vpr.profile:
        return None
    de = DeltaEngine(tick_size=row_size)
    de.add_ticks_bulk(zip(prices.tolist(), sizes.tolist(), sides.tolist()))
    der = de.result()
    bin_prices = sorted(vpr.profile.keys())
    bin_buy = np.empty(len(bin_prices)); bin_sell = np.empty(len(bin_prices))
    for i, p in enumerate(bin_prices):
        total = vpr.profile[p]
        b = der.buy_volume_per_level.get(p, 0.0)
        s = der.sell_volume_per_level.get(p, 0.0)
        bs = b + s
        if bs > 0:
            bin_buy[i] = total * b / bs
            bin_sell[i] = total * s / bs
        else:
            bin_buy[i] = bin_sell[i] = total / 2.0
    node_hvn, node_lvn = vp.compute_hvn_lvn_peaks(
        min_prominence_ratio=0.4, lvn_within_hvn=not lvn_full_profile)
    hvn, lvn = _top_nodes(node_hvn, node_lvn, vpr.profile,
                          max_lvn=6 if lvn_full_profile else 3)
    return dict(bin_price=np.array(bin_prices, dtype=float), bin_buy=bin_buy, bin_sell=bin_sell,
                poc=vpr.poc or 0.0, vah=vpr.vah or 0.0, val=vpr.val or 0.0,
                hvn=hvn, lvn=lvn, total=vpr.total_volume)


def period_profiles(filename, mode="session", span="day", unit="Zi", va_percent=0.70,
                    row_size=2.0, sessions=None, lvn_full_profile=False):
    """VP SEPARAT per PERIOADA (zi sau sesiune) de-a lungul span-ului -> modul 'Profile Only'.

    Fiecare intrare e un profil pozitionat pe axa timpului: {label, x0, x1 (epoci UTC),
    bin_price, bin_buy, bin_sell, poc, vah, val, hvn, lvn, total}.

    unit: 'Zi' (un profil per zi din span) sau 'Asia'/'Londra'/'NY' (acea sesiune per zi)
          sau 'Toate' (toate cele trei sesiuni per zi). Ferestrele de sesiune sunt ancorate
          pe fus orar (zoneinfo) EXACT ca session_profiles -> auto vara/iarna.
    span: reutilizeaza mecanismul existent ('day', 'week', 'Nd'). Aditiv: nu atinge load_day.
    """
    available = _available_by_date()
    date = _date_of(filename)
    if span == "week":
        files = _contiguous_block(date, available) if date else [filename]
    elif isinstance(span, str) and span.endswith("d") and span[:-1].isdigit():
        files = (_last_n_days_block(date, available, int(span[:-1])) if date else []) or [filename]
    else:
        files = [filename]

    sessions = sessions or SESSION_DEFS["real"]
    unit = unit or "Zi"
    want = None if unit in ("Toate", "Toate sesiunile") else unit
    out = []
    for f in files:
        try:
            tk, _ = _get_ticks(f, mode, available)
        except Exception:
            continue
        df = tk.df
        if df.empty:
            continue
        tsec = (df["ts"].astype("int64") // 10**9).to_numpy()
        if unit == "Zi":
            info = _vp_split_from_ticks(df, row_size, va_percent, lvn_full_profile)
            if info:
                fd = _date_of(f) or ""
                info.update(label=f"{fd[4:6]}-{fd[6:8]}" if len(fd) == 8 else fd,
                            x0=float(tsec.min()), x1=float(tsec.max()))
                out.append(info)
            continue
        fdate = _date_of(f)
        if not fdate:
            continue
        y, mo, dd = int(fdate[:4]), int(fdate[4:6]), int(fdate[6:8])
        for name, tz, (sh, sm), (eh, em) in sessions:
            if want is not None and name != want:
                continue
            z = ZoneInfo(tz)
            start = datetime.datetime(y, mo, dd, sh, sm, tzinfo=z).timestamp()
            end = datetime.datetime(y, mo, dd, eh, em, tzinfo=z).timestamp()
            if end <= start:
                end += 86400.0
            mask = (tsec >= start) & (tsec < end)
            if not mask.any():
                continue
            info = _vp_split_from_ticks(df[mask], row_size, va_percent, lvn_full_profile)
            if info:
                info.update(label=f"{fdate[4:6]}-{fdate[6:8]} {name}",
                            x0=float(start), x1=float(end))
                out.append(info)
    out.sort(key=lambda d: d["x0"])
    return out


def load_day(filename, va_percent=0.70, interval="5min", row_size=2.0,
             mode="session", span="day",
             big_trade_min=BIG_TRADE_MIN, abs_params=None, exh_params=None,
             lvn_full_profile=False) -> DayData:
    tk, incomplete = resolve_ticks(filename, mode, span)
    df = tk.df

    # --- Lumanari (resample pe interval) ---
    c = df.set_index("ts")
    ohlc = c["price"].resample(interval).ohlc()
    ohlc["volume"] = c["size"].resample(interval).sum()
    ohlc = ohlc.dropna(subset=["open"])  # scoate pauza de mentenanta (fara tick-uri)
    t = ohlc.index.astype("int64").to_numpy() / 1e9

    # VWAP developing (tipic (H+L+C)/3 ponderat cu volumul, cumulativ)
    o_ = ohlc["open"].to_numpy(); h_ = ohlc["high"].to_numpy()
    l_ = ohlc["low"].to_numpy(); c_ = ohlc["close"].to_numpy()
    v_ = ohlc["volume"].to_numpy()
    typ = (h_ + l_ + c_) / 3.0
    cum_v = np.cumsum(v_)
    vwap = np.cumsum(typ * v_) / np.where(cum_v == 0, np.nan, cum_v)

    # TOTUL la REZOLUTIA DE AFISARE (row_size): POC/VAH/VAL/HVN/LVN si barele
    # profilului se calculeaza pe ACEEASI grila -> ce vezi = ce se calculeaza.
    # (row_size=0.25 => valori precise la tick; mai mare => grupat mai gros.)
    vp = VolumeProfileEngine(tick_size=row_size)
    vp.add_ticks_bulk(tk.price_volume())
    vpr = vp.result(va_percent=va_percent)

    de = DeltaEngine(tick_size=row_size)
    de.add_ticks_bulk(tk.price_volume_side())
    der = de.result()

    # Barele = volumul TOTAL per nivel (deci POC = bara cea mai groasa, garantat),
    # colorate proportional buy (verde) / sell (mov).
    prices = sorted(vpr.profile.keys())
    bin_price = np.array(prices, dtype=float)
    bin_buy = np.empty(len(prices))
    bin_sell = np.empty(len(prices))
    for i, p in enumerate(prices):
        total = vpr.profile[p]
        b = der.buy_volume_per_level.get(p, 0.0)
        s = der.sell_volume_per_level.get(p, 0.0)
        bs = b + s
        if bs > 0:
            bin_buy[i] = total * b / bs
            bin_sell[i] = total * s / bs
        else:
            bin_buy[i] = bin_sell[i] = total / 2.0

    # HVN/LVN pe aceeasi grila, prag strict (nod clar peste/sub medie) + top-N.
    # lvn_full_profile -> LVN pe tot profilul (inclusiv spre margini = discount/premium).
    node_hvn, node_lvn = vp.compute_hvn_lvn_peaks(
        min_prominence_ratio=0.4, lvn_within_hvn=not lvn_full_profile)
    hvn_top, lvn_top = _top_nodes(node_hvn, node_lvn, vpr.profile,
                                  max_lvn=6 if lvn_full_profile else 3)

    # Footprint: buy/sell per (lumanare, nivel de pret) - pentru order flow detaliat
    footprint = _build_footprint(tk.df, interval, row_size)

    # CVD: Cumulative Delta developing (suma delta-urilor per lumanare, cronologic)
    pcd = {tt: sum(b - s for (b, s) in cells.values()) for tt, cells in footprint.items()}
    cvd = np.cumsum([pcd.get(int(round(tt)), 0.0) for tt in t]) if len(t) else np.zeros(0)

    big_trades = _big_trades(tk.df, INTERVAL_SECONDS[interval], min_size=big_trade_min)

    # Absorption/Exhaustion: praguri adaptate la INTERVAL (base) + override-uri din ⚙ (user).
    abs_base, exh_base = _detector_defaults(INTERVAL_SECONDS[interval])
    absorption = detect_absorption(footprint, t, h_, l_, c_, row_size,
                                   **{**abs_base, **(abs_params or {})})
    exhaustion = detect_exhaustion(footprint, t, h_, l_, c_, v_,
                                   **{**exh_base, **(exh_params or {})})

    # Developing POC/VA: trail-ul cumulativ per lumanare (ultima valoare = POC/VA total)
    dev_poc, dev_vah, dev_val = developing_levels(footprint, t, row_size, va_percent)

    # Acceptance / Rejection: reactii la nivelurile developing (VAH/VAL/POC), filtrate
    level_reactions = detect_level_reactions(t, o_, h_, l_, c_, dev_poc, dev_vah, dev_val, row_size)

    # Speed of tape: nr. de trade-uri (print-uri) pe secunda per lumanare. Independent de
    # volum - multe print-uri mici = tape rapid; putine mari = tape lent (blocuri).
    if len(t):
        cand = (tk.df["ts"].dt.floor(interval).astype("int64") // 10**9)
        counts = cand.value_counts()
        bar_sec = INTERVAL_SECONDS[interval]
        tps = np.array([float(counts.get(int(round(tt)), 0)) / bar_sec for tt in t])
    else:
        tps = np.zeros(0)

    return DayData(
        symbol=tk.symbol, n_ticks=len(tk),
        t=t, open=o_, high=h_, low=l_, close=c_, volume=v_,
        vwap=vwap, cvd=cvd, last_price=float(c_[-1]) if len(c_) else 0.0,
        bar_seconds=INTERVAL_SECONDS[interval],
        bin_price=bin_price, bin_buy=bin_buy, bin_sell=bin_sell, row_size=row_size,
        poc=vpr.poc, vah=vpr.vah, val=vpr.val, hvn=hvn_top, lvn=lvn_top,
        total_volume=vpr.total_volume, cum_delta=der.cumulative_delta,
        buy_total=der.total_buy_volume, sell_total=der.total_sell_volume,
        mode=mode, incomplete=incomplete, footprint=footprint, big_trades=big_trades,
        absorption=absorption, exhaustion=exhaustion, level_reactions=level_reactions,
        dev_poc=dev_poc, dev_vah=dev_vah, dev_val=dev_val, tps=tps,
    )


def build_reference_levels(filename, mode="session", va_percent=0.70, row_size=2.0,
                           sessions=None):
    """
    Niveluri de CONTEXT din sesiuni PRECEDENTE, ca list[ReferenceLevel] (core), pentru P2.
    Aditiv: nu modifica nimic din pipeline-ul existent, doar reuseste loaderele.

    - Sesiunea precedenta COMPLETA: POC/VAH/VAL + HVN/LVN + PDH/PDL (available_from=0 = istorie).
    - Sub-sesiunile de AZI (Asia/Londra/NY) daca `sessions` e dat (SESSION_DEFS[...]):
      fiecare nivel primeste available_from = inchiderea sesiunii lui. Gate-ul cauzal din
      analyze_session_context foloseste DOAR nivelurile cu available_from <= T -> Asia/Londra
      devin context abia dupa ce se inchid (fara look-ahead).
    """
    from core import ReferenceLevel
    out = []
    date = _date_of(filename)
    if not date:
        return out
    available = _available_by_date()
    d = datetime.date(int(date[:4]), int(date[4:6]), int(date[6:8]))

    prior_file = None
    for back in range(1, 8):
        pdate = (d - datetime.timedelta(days=back)).strftime("%Y%m%d")
        if pdate in available:
            prior_file = available[pdate]
            break
    if prior_file:
        tk, _ = _get_ticks(prior_file, mode, available)
        if not tk.df.empty:
            vp = VolumeProfileEngine(tick_size=row_size)
            vp.add_ticks_bulk(tk.price_volume())
            vpr = vp.result(va_percent=va_percent)
            hvn_nodes, lvn_nodes = vp.compute_nodes(min_prominence_ratio=0.4, lvn_mode="full")
            prices = tk.df["price"]
            for kind, val in (("poc", vpr.poc), ("vah", vpr.vah), ("val", vpr.val),
                              ("high", float(prices.max())), ("low", float(prices.min()))):
                if val is not None:
                    out.append(ReferenceLevel("prev", kind, float(val), 0))
            for nd in hvn_nodes[:5]:
                out.append(ReferenceLevel("prev", "hvn", float(nd.price), 0))
            for nd in lvn_nodes[:5]:
                out.append(ReferenceLevel("prev", "lvn", float(nd.price), 0))

    if sessions:
        sp = session_profiles(filename, sessions, mode=mode, va_percent=va_percent,
                              row_size=row_size)
        for name, info in sp.items():
            avail = int(round(info["end"]))
            for kind in ("poc", "vah", "val"):
                if info.get(kind) is not None:
                    out.append(ReferenceLevel(name.lower(), kind, float(info[kind]), avail))
            out.append(ReferenceLevel(name.lower(), "high", float(info["high"]), avail))
            out.append(ReferenceLevel(name.lower(), "low", float(info["low"]), avail))
            for p in info.get("hvn", []):
                out.append(ReferenceLevel(name.lower(), "hvn", float(p), avail))
            for p in info.get("lvn", []):
                out.append(ReferenceLevel(name.lower(), "lvn", float(p), avail))
    return out


def build_composite_levels(filename, spans=(15, 90), va_percent=0.70, row_size=2.0):
    """
    Niveluri COMPOSITE pe termen lung (15D/90D) ca list[ReferenceLevel] (core), pentru P3.
    Aditiv: reuseste _last_n_days_block + load_many, nu modifica nimic existent.

    Composite = ISTORIE: N zile care se termina IERI (exclud ziua curenta) -> pur cauzal,
    available_from=0. POC/VAH/VAL + HVN/LVN (noduri P1a) + high/low pe fereastra composite.
    Eticheta span = "15D"/"90D" (session in ReferenceLevel).
    """
    from core import ReferenceLevel
    out = []
    date = _date_of(filename)
    if not date:
        return out
    available = _available_by_date()
    d = datetime.date(int(date[:4]), int(date[4:6]), int(date[6:8]))
    prev_date = None
    for back in range(1, 8):
        pdate = (d - datetime.timedelta(days=back)).strftime("%Y%m%d")
        if pdate in available:
            prev_date = pdate
            break
    if prev_date is None:
        return out

    for n in spans:
        block = _last_n_days_block(prev_date, available, n)   # N zile pana IERI inclusiv
        if not block:
            continue
        tk = load_many(block)
        if tk.df.empty:
            continue
        vp = VolumeProfileEngine(tick_size=row_size)
        vp.add_ticks_bulk(tk.price_volume())
        vpr = vp.result(va_percent=va_percent)
        hvn_nodes, lvn_nodes = vp.compute_nodes(min_prominence_ratio=0.4, lvn_mode="full")
        prices = tk.df["price"]
        span = f"{n}D"
        for kind, val in (("poc", vpr.poc), ("vah", vpr.vah), ("val", vpr.val),
                          ("high", float(prices.max())), ("low", float(prices.min()))):
            if val is not None:
                out.append(ReferenceLevel(span, kind, float(val), 0))
        for nd in hvn_nodes[:6]:
            out.append(ReferenceLevel(span, "hvn", float(nd.price), 0))
        for nd in lvn_nodes[:6]:
            out.append(ReferenceLevel(span, "lvn", float(nd.price), 0))
    return out
