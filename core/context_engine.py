"""
Order Flow Context Engine — FUNDATIE (P4-core)
==============================================

Stratul de analiza contextuala dintre datele/replay-ul CAUZAL si UI. Traduce ce s-a
intamplat in order flow in OBSERVATII individuale (NU semnale BUY/SELL, NU scor, NU
black-box). In P4-core exista DOAR scheletul + granita anti-look-ahead demonstrata;
componentele (Delta, Price Progress, Absorption/Exhaustion, CVD divergence, POC
migration, LVN interaction, Acceptance/Rejection, Tape) se adauga in fazele urmatoare.

Principiul central — NO LOOK-AHEAD (cauzalitate garantata prin CONSTRUCTIE):
    ContextEngine NU primeste ziua intreaga + un timestamp si "promite" ca nu se uita
    in viitor. Primeste un `Snapshot` care CONTINE FIZIC doar informatia disponibila la
    momentul T (bar index k) si NIMIC dupa. Snapshot-ul se construieste prin FELIERE
    (`snapshot_from_daydata(day, upto_index=k)`), care taie orice bar > k si foloseste
    valorile DEVELOPING (POC/VA cumulative pana la k) — NU POC-ul zilei intregi (care ar
    fi look-ahead). Astfel engine-ul nu are cum sa vada viitorul: nu-l primeste.

Layering: acest modul traieste in `core/` si depinde DOAR de numpy + core.vp_engine.
NU importa nimic din `app/` (data_service). `snapshot_from_daydata` accepta orice obiect
cu forma unui DayData (duck typing) -> core ramane independent de UI.
"""

from dataclasses import dataclass, field

import numpy as np

from core.vp_engine import VolumeProfileEngine


# ------------------------------------------------------------------ Snapshot
@dataclass(frozen=True)
class Snapshot:
    """
    Intrarea CAUZALA a ContextEngine: toata informatia disponibila la momentul T
    (bar index k) si nimic dupa. Imutabil (frozen) -> analiza e o functie pura de el.

    Toate array-urile au aceeasi lungime (k+1 bare, ultima = bara curenta la T).
    poc/vah/val sunt valorile DEVELOPING la T (cumulative pana la k), NU ale zilei
    intregi -> nu exista scurgere din viitor.
    """
    now_epoch: int          # T = epoca barei curente (t[-1])
    bar_seconds: int
    t: np.ndarray           # epoci bare [0..k]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    cvd: np.ndarray         # Cumulative Delta pana la fiecare bara (cauzal)
    poc: float              # developing POC la T (cauzal)
    vah: float
    val: float
    footprint: dict         # DOAR barele <= T: {epoca: {pret: [buy, sell]}}
    row_size: float
    symbol: str = ""
    tick_size: float = 0.25  # tick-ul instrumentului (NQ=0.25) - pt "ticks de progres"
    # Seria DEVELOPING POC (cumulativ pana la fiecare bara, cauzala) [0..k]. poc_series[-1]==poc.
    # Folosita de P4.5 (POC migration). NU e POC-ul zilei intregi.
    poc_series: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def __len__(self):
        return len(self.t)


def _levels_from_footprint(footprint, row_size, va_percent=0.70):
    """POC/VAH/VAL cauzale reconstruite din footprint-ul (deja feliat la <= T).
    Folosit doar ca fallback cand ziua nu are array-urile developing."""
    vp = VolumeProfileEngine(tick_size=row_size)
    for cells in footprint.values():
        for price, (buy, sell) in cells.items():
            total = buy + sell
            if total > 0:
                vp.add_tick(price, total)
    r = vp.result(va_percent=va_percent)
    return (r.poc or 0.0, r.vah or 0.0, r.val or 0.0)


def snapshot_from_daydata(day, upto_index=None, va_percent=0.70) -> Snapshot:
    """
    Construieste un Snapshot CAUZAL dintr-un DayData, pastrand DOAR barele [0..upto_index].

    Aici e granita anti-look-ahead: feliem array-urile la k, filtram footprint-ul la
    epocile <= T si luam POC/VA din valorile DEVELOPING (dev_poc[k] etc.) — cauzale —
    NU din day.poc (care e calculat pe ziua intreaga = viitor).

    `upto_index=None` -> foloseste toata ziua (util cand `day` e DEJA un snapshot de
    replay, adica deja taiat la bara curenta).
    `day` = orice obiect cu forma unui DayData (duck typing; nu importam clasa).
    """
    t_all = np.asarray(day.t)
    n = len(t_all)
    if n == 0:
        return Snapshot(now_epoch=0, bar_seconds=int(getattr(day, "bar_seconds", 0)),
                        t=np.zeros(0), open=np.zeros(0), high=np.zeros(0), low=np.zeros(0),
                        close=np.zeros(0), volume=np.zeros(0), cvd=np.zeros(0),
                        poc=0.0, vah=0.0, val=0.0, footprint={},
                        row_size=float(getattr(day, "row_size", 0.0)),
                        symbol=getattr(day, "symbol", ""),
                        tick_size=float(getattr(day, "tick_size", 0.25)))

    k = (n - 1) if upto_index is None else max(0, min(int(upto_index), n - 1))
    sl = slice(0, k + 1)

    t = np.array(t_all[sl], dtype=float)
    epochs = {int(round(e)) for e in t}
    footprint = {int(round(ep)): cells
                 for ep, cells in getattr(day, "footprint", {}).items()
                 if int(round(ep)) in epochs}

    # POC/VA CAUZALE la T: preferam array-urile developing (cumulative, deja cauzale);
    # fallback = reconstruite din footprint-ul feliat. NICIODATA day.poc (ziua intreaga).
    def dev_at(name):
        arr = np.asarray(getattr(day, name, []))
        return float(arr[k]) if len(arr) > k else None
    poc = dev_at("dev_poc")
    vah = dev_at("dev_vah")
    val = dev_at("dev_val")
    if poc is None or vah is None or val is None:
        poc, vah, val = _levels_from_footprint(footprint, float(day.row_size), va_percent)

    # Seria developing POC cauzala [0..k]. Fallback (dev_poc absent) = constanta = degenerat sigur.
    dp_arr = np.asarray(getattr(day, "dev_poc", []))
    poc_series = (np.array(dp_arr[:k + 1], dtype=float) if len(dp_arr) > k
                  else np.full(k + 1, float(poc)))

    def col(name):
        return np.array(np.asarray(getattr(day, name))[sl], dtype=float)

    return Snapshot(
        now_epoch=int(round(t[-1])), bar_seconds=int(day.bar_seconds),
        t=t, open=col("open"), high=col("high"), low=col("low"), close=col("close"),
        volume=col("volume"), cvd=col("cvd"),
        poc=float(poc), vah=float(vah), val=float(val),
        footprint=footprint, row_size=float(day.row_size),
        symbol=getattr(day, "symbol", ""),
        tick_size=float(getattr(day, "tick_size", 0.25)),
        poc_series=poc_series,
    )


# ------------------------------------------------------------------ ContextResult
@dataclass
class ContextResult:
    """
    Rezultatul analizei contextuale la momentul T. In P4-core contine doar valori de
    FUNDATIE, trivial cauzale (derivate strict din snapshot). Blocurile de componente
    (delta, price_progress, absorption, exhaustion, cvd_divergence, poc_migration,
    node_interaction, accept_reject, tape) se vor pune in `components` in fazele urmatoare.

    `overall` va deveni SUPPORTIVE / NEUTRAL / CONTRADICTING derivat prin REGULI
    transparente din componente — niciodata un scor sau un procent. Acum e "NEUTRAL"
    (nu exista inca componente).
    """
    now_epoch: int          # T
    n_bars: int             # cate bare erau disponibile la T (cauzal)
    last_price: float       # close la T
    poc: float              # developing POC la T (cauzal)
    cvd: float              # Cumulative Delta la T
    overall: str = "NEUTRAL"
    components: dict = field(default_factory=dict)


# ================================================================== P4.1 — DELTA
# Praguri IMPLICITE (adaptive, NU absolute). Toate sunt raportate la o SCALA calculata
# din delta recenta (mediana |delta| pe fereastra) -> se adapteaza la activitatea zilei,
# nu la un numar fix de contracte. Configurabile prin ContextEngine(config={"delta": {...}}).
DELTA_DEFAULTS = {
    "lookback": 7,           # cate bare inapoi formeaza secventa recenta + scala
    "neutral_ratio": 0.5,    # |delta| < neutral_ratio * scala -> flow neglijabil (NEUTRAL)
    "aggression_ratio": 1.2,  # |delta| >= aggression_ratio * scala -> nivel de "agresiune"
    "accel_tol": 0.15,       # toleranta la variatia de magnitudine (accelerare/decelerare)
}


@dataclass
class DeltaContext:
    """
    Interpretarea Delta la momentul T - OBSERVATII, nu semnal. Expune componentele
    individual (userul le vede pe fiecare), NU "pozitiv=BUY". Clasificarea se bazeaza pe
    EVOLUTIA delta (directie + magnitudine + variatie), cu praguri adaptive la scala recenta.
    """
    current_delta: float            # delta barei curente (la T)
    previous_delta: float           # delta barei anterioare (None daca nu exista)
    delta_change: float             # current - previous (None daca nu exista precedenta)
    delta_direction: str            # POSITIVE | NEGATIVE | FLAT
    momentum: str                   # BUYING | SELLING | NEUTRAL (directia neta recenta)
    acceleration: str               # ACCELERATING | DECELERATING | STEADY (magnitudine vs precedenta)
    recent_sequence: list           # ultimele `lookback` delta (cronologic)
    scale: float                    # scala adaptiva (mediana |delta| recent) - expusa pt transparenta
    sequence_state: str             # vezi DELTA_STATES


# Starile posibile ale secventei de delta (descriptive, simetrice):
DELTA_STATES = (
    "NEUTRAL", "DELTA_FLIP",
    "BUYING_AGGRESSION", "BUYING_ACCELERATION", "BUYING_DECELERATION",
    "SELLING_AGGRESSION", "SELLING_ACCELERATION", "SELLING_DECELERATION",
)


def _classify_delta_state(cur, prev, neutral, acceleration, side):
    """Regula de clasificare (pura). Ordine: neutral -> flip -> accel/decel -> agresiune sustinuta."""
    if cur == 0.0 or abs(cur) < neutral:
        return "NEUTRAL"
    # DELTA_FLIP: semnul curent difera de al barei anterioare (ambele non-neglijabile)
    if prev is not None and prev != 0.0 and (cur > 0) != (prev > 0):
        return "DELTA_FLIP"
    if acceleration == "ACCELERATING":
        return f"{side}_ACCELERATION"
    if acceleration == "DECELERATING":
        return f"{side}_DECELERATION"
    return f"{side}_AGGRESSION"          # sustinut (magnitudine ~constanta)


def analyze_delta(snapshot: Snapshot, cfg=None) -> DeltaContext:
    """
    Componenta Delta - functie PURA, DETERMINISTA, CAUZALA de Snapshot.
    Delta per bara = diferenta CVD-ului (cvd e cauzal, feliat la <= T). Nu foloseste
    pretul, nu stie de Price Action, nu emite BUY/SELL.
    """
    c = {**DELTA_DEFAULTS, **(cfg or {})}
    cvd = np.asarray(snapshot.cvd, dtype=float)
    deltas = np.diff(cvd, prepend=0.0) if len(cvd) else np.zeros(0)
    n = len(deltas)
    if n == 0:
        return DeltaContext(0.0, None, None, "FLAT", "NEUTRAL", "STEADY", [], 0.0, "NEUTRAL")

    cur = float(deltas[-1])
    prev = float(deltas[-2]) if n >= 2 else None
    recent = deltas[-int(c["lookback"]):]
    scale = float(np.median(np.abs(recent)))
    if scale <= 0.0:
        scale = max(abs(cur), 1e-9)      # degenerat (delta recent ~0) -> evita impartirea la 0
    neutral = c["neutral_ratio"] * scale

    direction = "POSITIVE" if cur > 0 else "NEGATIVE" if cur < 0 else "FLAT"

    rmean = float(np.mean(recent))
    momentum = "NEUTRAL" if abs(rmean) < neutral else ("BUYING" if rmean > 0 else "SELLING")

    if prev is None:
        acceleration = "STEADY"
    else:
        ap, ac, tol = abs(prev), abs(cur), c["accel_tol"]
        if ac > ap * (1 + tol):
            acceleration = "ACCELERATING"
        elif ac < ap * (1 - tol):
            acceleration = "DECELERATING"
        else:
            acceleration = "STEADY"

    side = "BUYING" if cur > 0 else "SELLING"
    state = _classify_delta_state(cur, prev, neutral, acceleration, side)

    return DeltaContext(
        current_delta=cur,
        previous_delta=prev,
        delta_change=(cur - prev) if prev is not None else None,
        delta_direction=direction,
        momentum=momentum,
        acceleration=acceleration,
        recent_sequence=[float(x) for x in recent],
        scale=scale,
        sequence_state=state,
    )


# ================================================================== P4.2 — PRICE PROGRESS
# Efort (agresiune delta) vs rezultat (progres de pret in ticks), pe o fereastra scurta.
# Pragurile "mare/mic" sunt ADAPTIVE: se compara efortul/rezultatul CURENT cu scala
# tipica din ferestrele TRECUTE (nu se suprapun cu fereastra curenta) -> nimic absolut.
PRICE_PROGRESS_DEFAULTS = {
    "window": 3,             # cate bare formeaza "miscarea" curenta (efort + rezultat)
    "scale_lookback": 20,    # cate ferestre trecute intra in scala adaptiva (mediana)
    "high_ratio": 1.3,       # >= high_ratio * scala -> MARE (HIGH)
    "low_ratio": 0.6,        # <= low_ratio  * scala -> MIC (LOW); intre -> MEDIUM
}

# Starile (relatia efort vs rezultat). NU spun bullish/bearish - doar agresiune vs progres.
PRICE_PROGRESS_STATES = (
    "AGGRESSION_WITH_PROGRESS",      # efort mare -> progres mare (agresiunea "livreaza")
    "AGGRESSION_WITHOUT_PROGRESS",   # efort mare -> progres mic (agresiune neproductiva)
    "PROGRESS_WITHOUT_AGGRESSION",   # efort mic -> progres mare (pret se misca usor)
    "QUIET",                         # efort mic -> progres mic
    "NEUTRAL",                       # combinatii de mijloc (nici clar mare, nici clar mic)
    "INSUFFICIENT_EVIDENCE",         # prea putine bare pentru o scala adaptiva
)


@dataclass
class PriceProgressContext:
    """
    Relatia dintre AGRESIUNEA delta (efort) si PROGRESUL de pret (rezultat) pe fereastra
    curenta - OBSERVATIE, nu semnal. "Delta negativa + pret in scadere" NU e tratata
    automat ca 'bearish confirmation': masuram cat efort a produs cat progres.
    """
    window: int                     # bare folosite
    delta_sum: float                # agresiune neta pe fereastra (cu semn)
    aggression: float               # |delta_sum| = efort
    price_change: float             # close[T] - close[T-window] (cu semn, puncte)
    progress_ticks: float           # price_change / tick_size
    efficiency: float               # |price_change| / aggression (puncte per unitate de delta)
    aggression_level: str           # HIGH | MEDIUM | LOW (fata de scala adaptiva)
    progress_level: str             # HIGH | MEDIUM | LOW
    direction_alignment: str        # ALIGNED | OPPOSED | FLAT (semnul delta vs semnul pretului)
    agg_scale: float                # scala adaptiva a efortului (mediana ferestre trecute)
    progress_scale: float           # scala adaptiva a rezultatului
    state: str                      # vezi PRICE_PROGRESS_STATES


def _level(value, scale, high_ratio, low_ratio):
    """Clasifica o marime fata de o scala adaptiva: HIGH / LOW / MEDIUM."""
    if scale <= 0:
        return "MEDIUM"
    if value >= high_ratio * scale:
        return "HIGH"
    if value <= low_ratio * scale:
        return "LOW"
    return "MEDIUM"


def analyze_price_progress(snapshot: Snapshot, cfg=None) -> PriceProgressContext:
    """
    Componenta Price Progress - functie PURA, DETERMINISTA, CAUZALA de Snapshot.
    Efort = |suma delta pe fereastra|; rezultat = |variatia de pret pe fereastra|.
    Scala adaptiva = mediana ferestrelor TRECUTE (care NU se suprapun cu cea curenta).
    """
    c = {**PRICE_PROGRESS_DEFAULTS, **(cfg or {})}
    w = int(c["window"])
    close = np.asarray(snapshot.close, dtype=float)
    cvd = np.asarray(snapshot.cvd, dtype=float)
    n = len(close)
    tick = snapshot.tick_size or 0.25

    deltas = np.diff(cvd, prepend=0.0) if len(cvd) else np.zeros(0)

    def _insufficient():
        return PriceProgressContext(
            window=w, delta_sum=0.0, aggression=0.0, price_change=0.0, progress_ticks=0.0,
            efficiency=0.0, aggression_level="MEDIUM", progress_level="MEDIUM",
            direction_alignment="FLAT", agg_scale=0.0, progress_scale=0.0,
            state="INSUFFICIENT_EVIDENCE")

    # Avem nevoie de: o fereastra curenta [n-w .. n-1] SI cel putin o fereastra trecuta
    # care nu se suprapune cu ea. Rezultatul foloseste close[j-w] -> j >= w; ferestrele
    # trecute se termina la j <= n-1-w (fara suprapunere) -> e nevoie de n >= 2*w+1.
    if w < 1 or n < 2 * w + 1:
        return _insufficient()

    # Fereastra curenta (la T)
    delta_sum = float(np.sum(deltas[n - w:]))
    aggression = abs(delta_sum)
    price_change = float(close[-1] - close[n - w - 1])
    progress = abs(price_change)

    # Scala adaptiva din ferestrele TRECUTE: cele care se termina la j in [w .. n-1-w]
    # (j >= w -> close[j-w] valid; j <= n-1-w -> nu contin nicio bara din fereastra curenta).
    past_eff, past_res = [], []
    for j in range(w, n - w):
        past_eff.append(abs(float(np.sum(deltas[j - w + 1:j + 1]))))
        past_res.append(abs(float(close[j] - close[j - w])))
    if not past_eff:
        return _insufficient()
    lb = int(c["scale_lookback"])
    agg_scale = float(np.median(past_eff[-lb:]))
    progress_scale = float(np.median(past_res[-lb:]))

    agg_level = _level(aggression, agg_scale, c["high_ratio"], c["low_ratio"])
    prog_level = _level(progress, progress_scale, c["high_ratio"], c["low_ratio"])

    if price_change == 0.0 or delta_sum == 0.0:
        alignment = "FLAT"
    elif (delta_sum > 0) == (price_change > 0):
        alignment = "ALIGNED"
    else:
        alignment = "OPPOSED"

    efficiency = (progress / aggression) if aggression > 0 else 0.0

    # Stare = combinatia efort x rezultat (doar cand ambele sunt clar mari/mici)
    if agg_level == "HIGH" and prog_level == "HIGH":
        state = "AGGRESSION_WITH_PROGRESS"
    elif agg_level == "HIGH" and prog_level == "LOW":
        state = "AGGRESSION_WITHOUT_PROGRESS"
    elif agg_level == "LOW" and prog_level == "HIGH":
        state = "PROGRESS_WITHOUT_AGGRESSION"
    elif agg_level == "LOW" and prog_level == "LOW":
        state = "QUIET"
    else:
        state = "NEUTRAL"

    return PriceProgressContext(
        window=w, delta_sum=delta_sum, aggression=aggression, price_change=price_change,
        progress_ticks=price_change / tick, efficiency=efficiency,
        aggression_level=agg_level, progress_level=prog_level,
        direction_alignment=alignment, agg_scale=agg_scale, progress_scale=progress_scale,
        state=state)


# ================================================================== P4.3 — ABSORPTION / EXHAUSTION
# Transforma markerele in STARI contextuale cauzale, cu confirmation window
# (FORMING -> CONFIRMED/FADED) si reactie ulterioara masurata DOAR din bare <= T.
# Praguri adaptive (raportate la volumul si range-ul recent), nu valori fixe.
#
# IMPORTANT: absorption are conditii PROPRII (dominanta agresorului in zona extrema +
# respingere in bara), NU e acelasi lucru cu "aggression without progress" din P4.2.

ABSORPTION_DEFAULTS = {
    "zone": 2,               # cate nivele de la extrema formeaza "zona"
    "dom": 1.8,              # agresorul dominant >= dom x cealalta parte, in zona
    "frac": 0.22,            # zona concentreaza >= frac din volumul barei
    "reject": 0.55,          # respingere: inchidere la >= reject din range fata de extrema
    "min_vol_ratio": 0.25,   # agresiune zona >= ratio x mediana volum recent (ADAPTIV)
    "vol_lookback": 20,      # bare pt mediana de volum/range
    "confirmation_window": 3,  # bare de asteptat pt confirmare (reactie)
    "reaction_ratio": 0.5,   # reactie >= ratio x mediana range recent (ticks) -> CONFIRMED
    "scan_lookback": 15,     # cat de departe inapoi caut cel mai RECENT candidat
}

ABSORPTION_STATES = (
    "NONE",
    "BULL_ABSORPTION_FORMING", "BULL_ABSORPTION_CONFIRMED", "BULL_ABSORPTION_FADED",
    "BEAR_ABSORPTION_FORMING", "BEAR_ABSORPTION_CONFIRMED", "BEAR_ABSORPTION_FADED",
)

EXHAUSTION_DEFAULTS = {
    "window": 14,            # fereastra pt extrema noua + mediana de volum
    "vol_mult": 2.0,         # climax: volum >= vol_mult x mediana
    "delta_frac": 0.20,      # delta in directia trendului >= frac din volum
    "confirmation_window": 3,
    "reaction_ratio": 0.5,
    "vol_lookback": 20,
    "scan_lookback": 15,
}

EXHAUSTION_STATES = (
    "NONE",
    "TOP_EXHAUSTION_FORMING", "TOP_EXHAUSTION_CONFIRMED", "TOP_EXHAUSTION_FADED",
    "BOT_EXHAUSTION_FORMING", "BOT_EXHAUSTION_CONFIRMED", "BOT_EXHAUSTION_FADED",
)


@dataclass
class AbsorptionContext:
    detected: bool
    kind: str                       # "bull" | "bear" | None
    price: float                    # nivelul extrem absorbit
    bar_epoch: int
    bars_since: int                 # cate bare au trecut de la candidat pana la T
    aggression: float               # volumul agresiv absorbit in zona
    within_bar_rejection: float     # respingerea in bara (0..1)
    status: str                     # NONE | FORMING | CONFIRMED | FADED
    subsequent_reaction_ticks: float  # reactie cauzala (None pana la confirmare)
    confirmation_window: int
    state: str                      # vezi ABSORPTION_STATES


@dataclass
class ExhaustionContext:
    detected: bool
    kind: str                       # "top" | "bot" | None
    price: float
    bar_epoch: int
    bars_since: int
    climax_volume: float
    delta: float
    status: str                     # NONE | FORMING | CONFIRMED | FADED
    subsequent_reaction_ticks: float
    confirmation_window: int
    state: str                      # vezi EXHAUSTION_STATES


def _median_recent(values, upto_exclusive, lookback):
    """Mediana valorilor din [upto-lookback .. upto), robust; 0.0 daca gol."""
    lo = max(0, upto_exclusive - lookback)
    seg = values[lo:upto_exclusive]
    return float(np.median(seg)) if len(seg) else 0.0


def _absorption_candidate(cells, h, l, cl, v_total, c, min_vol):
    """Conditiile PROPRII de absorptie pe o bara inchisa. Returneaza (kind, price, aggression, rejection) sau None."""
    rng = h - l
    if rng <= 0 or v_total <= 0 or not cells:
        return None
    prices = sorted(cells.keys())
    zn = int(c["zone"])
    low_zone, high_zone = prices[:zn], prices[-zn:]
    buy_lo = sum(cells[p][0] for p in low_zone); sell_lo = sum(cells[p][1] for p in low_zone)
    buy_hi = sum(cells[p][0] for p in high_zone); sell_hi = sum(cells[p][1] for p in high_zone)
    # Bull: vanzare agresiva la MINIM, absorbita + inchidere sus (respingere de jos)
    if (sell_lo >= min_vol and sell_lo >= c["dom"] * buy_lo
            and sell_lo >= c["frac"] * v_total and (cl - l) / rng >= c["reject"]):
        return ("bull", l, sell_lo, (cl - l) / rng)
    # Bear: cumparare agresiva la MAXIM, absorbita + inchidere jos (respingere de sus)
    if (buy_hi >= min_vol and buy_hi >= c["dom"] * sell_hi
            and buy_hi >= c["frac"] * v_total and (h - cl) / rng >= c["reject"]):
        return ("bear", h, buy_hi, (h - cl) / rng)
    return None


def analyze_absorption(snapshot: Snapshot, cfg=None) -> AbsorptionContext:
    """Componenta Absorption - pura, determinista, cauzala. Cel mai RECENT candidat +
    statusul lui (FORMING pana trece confirmation_window; apoi CONFIRMED/FADED dupa reactia
    masurata DOAR din bare <= T). Fara look-ahead: reactia se citeste doar cand a elapsat."""
    c = {**ABSORPTION_DEFAULTS, **(cfg or {})}
    n = len(snapshot)
    none = AbsorptionContext(False, None, 0.0, 0, 0, 0.0, 0.0, "NONE", None,
                             int(c["confirmation_window"]), "NONE")
    if n < 3:
        return none
    high, low, close = snapshot.high, snapshot.low, snapshot.close
    vol, fp, tick = snapshot.volume, snapshot.footprint, (snapshot.tick_size or 0.25)
    t = snapshot.t
    last = n - 1                                  # bara curenta (o excludem din candidati)
    min_vol = c["min_vol_ratio"] * _median_recent(vol, last, int(c["vol_lookback"]))
    med_range = _median_recent(high - low, last, int(c["vol_lookback"]))
    reaction_min = c["reaction_ratio"] * (med_range / tick)
    w = int(c["confirmation_window"])

    lo_scan = max(0, last - int(c["scan_lookback"]))
    for k in range(last - 1, lo_scan - 1, -1):    # bare INCHISE, cel mai recent intai
        cells = fp.get(int(round(t[k])))
        cand = _absorption_candidate(cells, float(high[k]), float(low[k]), float(close[k]),
                                     float(vol[k]), c, min_vol)
        if cand is None:
            continue
        kind, price, aggression, rejection = cand
        bars_since = last - k
        if bars_since < w:                        # inca nu a trecut fereastra -> PENDING
            status, reaction = "FORMING", None
        else:
            seg = slice(k + 1, k + 1 + w)
            if kind == "bull":
                broke = float(np.min(low[seg])) < price - 1e-9
                reaction = (float(close[k + w]) - price) / tick
            else:
                broke = float(np.max(high[seg])) > price + 1e-9
                reaction = (price - float(close[k + w])) / tick
            status = "CONFIRMED" if (not broke and reaction >= reaction_min) else "FADED"
        state = f"{kind.upper()}_ABSORPTION_{status}"
        return AbsorptionContext(True, kind, float(price), int(round(t[k])), bars_since,
                                 float(aggression), float(rejection), status, reaction, w, state)
    return none


def _exhaustion_candidate(snapshot, k, c, med_vol):
    """Conditiile de exhaustion (climax + extrema noua + delta in trend) pe bara k."""
    win = int(c["window"])
    if k < win:
        return None
    high, low, vol, cvd = snapshot.high, snapshot.low, snapshot.volume, snapshot.cvd
    v = float(vol[k])
    if v <= 0 or med_vol <= 0 or v < c["vol_mult"] * med_vol:
        return None
    delta = float(cvd[k] - cvd[k - 1])
    new_high = high[k] >= float(np.max(high[k - win:k + 1])) - 1e-9
    new_low = low[k] <= float(np.min(low[k - win:k + 1])) + 1e-9
    if new_high and delta > 0 and delta >= c["delta_frac"] * v:
        return ("top", float(high[k]), v, delta)
    if new_low and delta < 0 and -delta >= c["delta_frac"] * v:
        return ("bot", float(low[k]), v, delta)
    return None


def analyze_exhaustion(snapshot: Snapshot, cfg=None) -> ExhaustionContext:
    """Componenta Exhaustion - pura, determinista, cauzala. SEPARATA de absorption: aici
    e climax de volum/agresiune la o extrema NOUA, urmat (posibil) de deteriorarea progresului.
    Status FORMING -> CONFIRMED/FADED dupa reactia cauzala (fara look-ahead)."""
    c = {**EXHAUSTION_DEFAULTS, **(cfg or {})}
    n = len(snapshot)
    none = ExhaustionContext(False, None, 0.0, 0, 0, 0.0, 0.0, "NONE", None,
                             int(c["confirmation_window"]), "NONE")
    if n < int(c["window"]) + 2:
        return none
    high, low, close, vol, t = (snapshot.high, snapshot.low, snapshot.close,
                                snapshot.volume, snapshot.t)
    tick = snapshot.tick_size or 0.25
    last = n - 1
    med_range = _median_recent(high - low, last, int(c["vol_lookback"]))
    reaction_min = c["reaction_ratio"] * (med_range / tick)
    w = int(c["confirmation_window"])

    lo_scan = max(int(c["window"]), last - int(c["scan_lookback"]))
    for k in range(last - 1, lo_scan - 1, -1):
        med_vol = _median_recent(vol, k, int(c["window"]))
        cand = _exhaustion_candidate(snapshot, k, c, med_vol)
        if cand is None:
            continue
        kind, price, climax_vol, delta = cand
        bars_since = last - k
        if bars_since < w:
            status, reaction = "FORMING", None
        else:
            seg = slice(k + 1, k + 1 + w)
            if kind == "top":                     # cumparatori epuizati la maxim -> asteptam reversal jos
                broke = float(np.max(high[seg])) > price + 1e-9
                reaction = (price - float(close[k + w])) / tick
            else:
                broke = float(np.min(low[seg])) < price - 1e-9
                reaction = (float(close[k + w]) - price) / tick
            status = "CONFIRMED" if (not broke and reaction >= reaction_min) else "FADED"
        state = f"{kind.upper()}_EXHAUSTION_{status}"
        return ExhaustionContext(True, kind, float(price), int(round(t[k])), bars_since,
                                 float(climax_vol), float(delta), status, reaction, w, state)
    return none


# ================================================================== P4.4 — CVD DIVERGENCE
# STRUCTURAL: compara evolutia pretului intre swing-uri confirmate cu evolutia CVD.
# Swing-urile se confirma cauzal (au nevoie de `right` bare in dreapta) -> daca un swing
# nou nu poate fi confirmat inca, statusul e FORMING (tentativ), nu CONFIRMED.
# Praguri adaptive: gap-ul de pret vs range-ul recent, gap-ul de CVD vs imprastierea CVD.
# NU e semnal: divergenta NU inseamna reversal garantat - e doar o OBSERVATIE de context.
CVD_DIVERGENCE_DEFAULTS = {
    "left": 3, "right": 3,           # bratele swing-ului (structural, nu 2 bare consecutive)
    "scale_lookback": 30,            # bare pt scalele adaptive
    "price_ratio": 0.5,              # gap pret >= price_ratio * mediana range recent
    "cvd_ratio": 0.3,                # gap CVD  >= cvd_ratio  * imprastiere CVD recenta (std)
    "slope_window": 5,               # bare pt panta CVD
    "momentum_deadband_ratio": 0.15,  # banda moarta pt momentum FLAT (fata de imprastierea CVD)
}

CVD_DIVERGENCE_STATES = (
    "BULLISH_DIVERGENCE", "BEARISH_DIVERGENCE", "NO_DIVERGENCE", "INSUFFICIENT_EVIDENCE",
)


@dataclass
class CvdDivergenceContext:
    cvd_value: float
    cvd_slope: float                 # variatie CVD / bara pe slope_window
    cvd_momentum: str                # RISING | FALLING | FLAT
    state: str                       # vezi CVD_DIVERGENCE_STATES
    status: str                      # CONFIRMED | FORMING | NONE
    price_swing_direction: str       # HIGHER_HIGH | LOWER_HIGH | LOWER_LOW | HIGHER_LOW | EQUAL_* | NONE
    cvd_swing_direction: str         # HIGHER | LOWER | EQUAL | NONE
    strength: float                  # magnitudinea nepotrivirii (in "imprastieri CVD") - NU scor de trading
    confirmation_window: int
    ref1_epoch: int
    ref1_price: float
    ref1_cvd: float
    ref2_epoch: int
    ref2_price: float
    ref2_cvd: float


def _swings(arr, L, R, last, kind):
    """Swing-uri CONFIRMATE (cu L bare mai jos/sus la stanga si R la dreapta). Cauzal:
    doar cele care au deja R bare la dreapta (k+R <= last)."""
    out = []
    for k in range(L, last - R + 1):
        left, right = arr[k - L:k], arr[k + 1:k + R + 1]
        if kind == "high" and arr[k] > left.max() and arr[k] > right.max():
            out.append(k)
        elif kind == "low" and arr[k] < left.min() and arr[k] < right.min():
            out.append(k)
    return out


def _pending_swing(arr, L, R, last, kind):
    """Cel mai RECENT extrem local NECONFIRMAT (in ultimele R bare): are L bare la stanga
    dominate, dar inca nu are R bare la dreapta -> potential swing (FORMING)."""
    lo = max(L, last - R + 1)
    for k in range(last, lo - 1, -1):
        left, right = arr[k - L:k], arr[k + 1:last + 1]
        if kind == "high" and arr[k] > left.max() and (len(right) == 0 or arr[k] >= right.max()):
            return k
        if kind == "low" and arr[k] < left.min() and (len(right) == 0 or arr[k] <= right.min()):
            return k
    return None


def _eval_divergence(kind, s1, s2, price_min, cvd_min, cvd_spread):
    """Evalueaza o pereche de swing-uri (s = (k, price, cvd, epoch)). Returneaza
    (state|None, price_dir, cvd_dir, strength)."""
    dp, dc = s2[1] - s1[1], s2[2] - s1[2]
    cvd_dir = "HIGHER" if dc > cvd_min else "LOWER" if dc < -cvd_min else "EQUAL"
    strength = abs(dc) / cvd_spread if cvd_spread > 0 else 0.0
    if kind == "high":
        pdir = "HIGHER_HIGH" if dp > price_min else "LOWER_HIGH" if dp < -price_min else "EQUAL_HIGH"
        state = "BEARISH_DIVERGENCE" if (pdir == "HIGHER_HIGH" and cvd_dir == "LOWER") else None
    else:
        pdir = "LOWER_LOW" if dp < -price_min else "HIGHER_LOW" if dp > price_min else "EQUAL_LOW"
        state = "BULLISH_DIVERGENCE" if (pdir == "LOWER_LOW" and cvd_dir == "HIGHER") else None
    return state, pdir, cvd_dir, strength


def analyze_cvd_divergence(snapshot: Snapshot, cfg=None) -> CvdDivergenceContext:
    """Componenta CVD Divergence - pura, determinista, cauzala. Compara swing-uri
    STRUCTURALE de pret cu CVD. FORMING cand swing-ul recent nu e inca confirmabil cauzal."""
    c = {**CVD_DIVERGENCE_DEFAULTS, **(cfg or {})}
    n = len(snapshot)
    high, low, cvd, t = snapshot.high, snapshot.low, snapshot.cvd, snapshot.t
    L, R = int(c["left"]), int(c["right"])
    cvd_now = float(cvd[-1]) if n else 0.0

    def result(state, status="NONE", pdir="NONE", cdir="NONE", strength=0.0,
               s1=None, s2=None, slope=0.0, momentum="FLAT"):
        r1 = s1 or (0, 0.0, 0.0, 0)
        r2 = s2 or (0, 0.0, 0.0, 0)
        return CvdDivergenceContext(
            cvd_value=cvd_now, cvd_slope=slope, cvd_momentum=momentum, state=state,
            status=status, price_swing_direction=pdir, cvd_swing_direction=cdir,
            strength=float(strength), confirmation_window=R,
            ref1_epoch=int(r1[3]), ref1_price=float(r1[1]), ref1_cvd=float(r1[2]),
            ref2_epoch=int(r2[3]), ref2_price=float(r2[1]), ref2_cvd=float(r2[2]))

    if n < L + R + 2:
        return result("INSUFFICIENT_EVIDENCE")
    last = n - 1

    # panta + momentum CVD (adaptive deadband)
    sw = min(int(c["slope_window"]), last)
    change = float(cvd[-1] - cvd[-1 - sw]) if sw > 0 else 0.0
    slope = change / sw if sw > 0 else 0.0
    seg = cvd[max(0, last - int(c["scale_lookback"])):last + 1]
    cvd_spread = float(np.std(seg)) if len(seg) > 1 else 0.0
    band = c["momentum_deadband_ratio"] * cvd_spread
    momentum = "RISING" if change > band else "FALLING" if change < -band else "FLAT"

    # scale adaptive
    ranges = (high - low)[max(0, last - int(c["scale_lookback"])):last + 1]
    price_min = c["price_ratio"] * float(np.median(ranges)) if len(ranges) else 0.0
    cvd_min = c["cvd_ratio"] * cvd_spread

    hi_idx = _swings(high, L, R, last, "high")
    lo_idx = _swings(low, L, R, last, "low")
    p_hi = _pending_swing(high, L, R, last, "high")
    p_lo = _pending_swing(low, L, R, last, "low")

    def pt(k, arr):
        return (k, float(arr[k]), float(cvd[k]), int(round(t[k])))

    # perechi candidate: (second_k, is_forming, kind, s1, s2)
    pairs = []
    if len(hi_idx) >= 2:
        pairs.append((hi_idx[-1], False, "high", pt(hi_idx[-2], high), pt(hi_idx[-1], high)))
    if len(lo_idx) >= 2:
        pairs.append((lo_idx[-1], False, "low", pt(lo_idx[-2], low), pt(lo_idx[-1], low)))
    if p_hi is not None and len(hi_idx) >= 1 and p_hi > hi_idx[-1]:
        pairs.append((p_hi, True, "high", pt(hi_idx[-1], high), pt(p_hi, high)))
    if p_lo is not None and len(lo_idx) >= 1 and p_lo > lo_idx[-1]:
        pairs.append((p_lo, True, "low", pt(lo_idx[-1], low), pt(p_lo, low)))

    diverging, no_div = [], None
    for second_k, forming, kind, s1, s2 in pairs:
        state, pdir, cdir, strength = _eval_divergence(kind, s1, s2, price_min, cvd_min, cvd_spread)
        if state is not None:
            diverging.append((second_k, forming, state, pdir, cdir, strength, s1, s2))
        elif not forming and (no_div is None or second_k > no_div[0]):
            no_div = (second_k, pdir, cdir, s1, s2)

    if diverging:
        second_k, forming, state, pdir, cdir, strength, s1, s2 = max(diverging, key=lambda x: x[0])
        return result(state, "FORMING" if forming else "CONFIRMED", pdir, cdir, strength,
                      s1, s2, slope, momentum)

    has_confirmed_pair = len(hi_idx) >= 2 or len(lo_idx) >= 2
    if has_confirmed_pair:
        pdir, cdir = (no_div[1], no_div[2]) if no_div else ("NONE", "NONE")
        s1, s2 = (no_div[3], no_div[4]) if no_div else (None, None)
        return result("NO_DIVERGENCE", "CONFIRMED", pdir, cdir, 0.0, s1, s2, slope, momentum)
    return result("INSUFFICIENT_EVIDENCE", "NONE", "NONE", "NONE", 0.0, None, None, slope, momentum)


# ================================================================== P4.5 — POC MIGRATION
# Directia + comportamentul POC-ului DEVELOPING in timp (nu doar pozitia curenta).
# Cauzal: foloseste exclusiv seria developing POC pana la T (Snapshot.poc_series),
# NICIODATA POC-ul zilei intregi. Praguri adaptive raportate la deplasarea recenta a POC.
# NU e semnal: POC rising NU inseamna bullish automat - e context.
POC_MIGRATION_DEFAULTS = {
    "window": 10,                # bare pe care se masoara migratia
    "scale_lookback": 30,        # bare pt scala adaptiva a deplasarii POC
    "min_bars": 6,               # sub atat -> INSUFFICIENT_EVIDENCE
    "dir_ratio": 0.35,           # |net| >= dir_ratio * (deplasare tipica * window) -> directional
    "strong_consistency": 0.6,   # consistenta >= atat -> migratie STRONG (altfel WEAK)
}

POC_MIGRATION_STATES = ("POC_RISING", "POC_FALLING", "POC_SIDEWAYS", "INSUFFICIENT_EVIDENCE")


@dataclass
class PocMigrationContext:
    state: str                   # vezi POC_MIGRATION_STATES
    direction: str               # RISING | FALLING | SIDEWAYS | NONE
    migration_strength: str      # STRONG | WEAK | NONE
    net_ticks: float             # deplasarea neta a POC pe fereastra (cu semn, in ticks)
    speed_ticks_per_bar: float   # viteza medie (ticks/bara)
    consistency: float           # |net| / drum_total (0..1): 1 = monoton, ~0 = oscilant
    window: int
    poc_current: float
    poc_reference: float         # POC la inceputul ferestrei
    adaptive_scale: float        # referinta de semnificatie (deplasare tipica * window)


def analyze_poc_migration(snapshot: Snapshot, cfg=None) -> PocMigrationContext:
    """Componenta POC Migration - pura, determinista, cauzala. Directie + magnitudine +
    viteza + consistenta ale POC-ului developing. Praguri adaptive la deplasarea recenta."""
    c = {**POC_MIGRATION_DEFAULTS, **(cfg or {})}
    poc = np.asarray(snapshot.poc_series, dtype=float)
    tick = snapshot.tick_size or 0.25
    n = len(poc)
    W = int(c["window"])

    def none(state):
        cur = float(poc[-1]) if n else 0.0
        direction = "SIDEWAYS" if state == "POC_SIDEWAYS" else "NONE"
        return PocMigrationContext(state=state, direction=direction, migration_strength="NONE",
                                   net_ticks=0.0, speed_ticks_per_bar=0.0, consistency=0.0,
                                   window=W, poc_current=cur, poc_reference=cur, adaptive_scale=0.0)

    if n < max(int(c["min_bars"]), 2):
        return none("INSUFFICIENT_EVIDENCE")

    w = min(W, n - 1)
    seg = poc[-(w + 1):]
    dpoc = np.diff(seg)
    net = float(seg[-1] - seg[0])
    total_path = float(np.sum(np.abs(dpoc)))

    # Scala adaptiva: deplasarea per-bara TIPICA a POC recent (medie ca sa nu fie 0 cand POC e "lipicios")
    disp = np.abs(np.diff(poc[-(int(c["scale_lookback"]) + 1):]))
    bar_disp = float(np.mean(disp)) if len(disp) else 0.0
    adaptive_scale = bar_disp * w

    net_ticks = net / tick
    speed = abs(net) / w / tick
    consistency = abs(net) / total_path if total_path > 0 else 0.0

    if bar_disp <= 0 or abs(net) < c["dir_ratio"] * adaptive_scale:
        direction, strength = "SIDEWAYS", "NONE"
    else:
        direction = "RISING" if net > 0 else "FALLING"
        strength = "STRONG" if consistency >= c["strong_consistency"] else "WEAK"

    return PocMigrationContext(
        state="POC_" + direction, direction=direction, migration_strength=strength,
        net_ticks=net_ticks, speed_ticks_per_bar=speed, consistency=consistency, window=w,
        poc_current=float(seg[-1]), poc_reference=float(seg[0]), adaptive_scale=adaptive_scale)


# ================================================================== P1b — LEVEL INTERACTION (LVN + Acceptance/Rejection)
# Ce face pretul cand interactioneaza cu o ZONA (LVN/HVN) sau un NIVEL (POC/VAH/VAL).
# Foloseste zona reala a nodului (VolumeNode din P1a: low/high/tier), NU un singur pret.
# Praguri ADAPTIVE la range-ul recent + latimea zonei. Cauzal (doar Snapshot, <= T),
# cu confirmation window (FORMING -> CONFIRMED). Observatii de market behavior, NU semnale.
LEVEL_INTERACTION_DEFAULTS = {
    "scan_lookback": 20,         # cate bare inapoi caut episodul de interactiune
    "tol_ticks": 1.0,            # toleranta la marginile zonei pt "atingere" (ticks)
    "reaction_ratio": 0.6,       # miscare de respingere >= reaction_ratio * range recent (ticks)
    "accept_ratio": 1.5,         # bare in zona >= accept_ratio * timp_asteptat_traversare -> ACCEPTANCE
    "fast_ratio": 0.6,           # bare in zona <= fast_ratio * timp_asteptat -> FAST_TRAVERSAL
    "confirmation_window": 3,
    "min_bars": 5,
    "lvn_min_prominence": 0.4,   # prag prominenta pt nodurile LVN (ca in data_service)
    # latimea benzii pt niveluri PUNCTUALE (POC/VAH/VAL), specifica nivelului (× range recent):
    "point_band_ratio": {"poc": 0.5, "vah": 0.3, "val": 0.3, "default": 0.35},
}

INTERACTION_STATES = (
    "TEST", "REJECTION", "ACCEPTANCE", "FAST_TRAVERSAL", "FAILED_REJECTION", "INSUFFICIENT_EVIDENCE",
)


@dataclass
class InteractionContext:
    detected: bool
    node_kind: str                  # lvn | hvn | poc | vah | val | ...
    node_tier: str                  # major | minor | "" (niveluri punctuale)
    zone_low: float
    zone_high: float
    entry_price: float              # pretul la prima atingere
    penetration_ticks: float        # cat de adanc a intrat in zona (ticks)
    bars_inside: int
    time_inside_sec: float
    approach_direction: str         # FROM_ABOVE | FROM_BELOW | UNKNOWN
    exit_direction: str             # BACK | THROUGH | INSIDE | NONE
    delta_during: float             # delta acumulata in timpul interactiunii
    price_progress_ticks: float     # progres net de la intrare pana la T
    state: str                      # vezi INTERACTION_STATES
    status: str                     # NONE | FORMING | CONFIRMED
    confirmation_window: int


def _touch(high, low, i, zlo, zhi, tol):
    return high[i] >= zlo - tol and low[i] <= zhi + tol


def _find_runs(high, low, zlo, zhi, tol, lo_scan, last):
    """Rulele consecutive de bare care ating zona, in [lo_scan .. last]."""
    runs, i = [], lo_scan
    while i <= last:
        if _touch(high, low, i, zlo, zhi, tol):
            j = i
            while j + 1 <= last and _touch(high, low, j + 1, zlo, zhi, tol):
                j += 1
            runs.append((i, j)); i = j + 1
        else:
            i += 1
    return runs


def analyze_level_interaction(snapshot: Snapshot, zlo, zhi, kind, tier, cfg=None) -> InteractionContext:
    """Motor GENERIC de interactiune cu o zona/nivel [zlo, zhi]. Pur, cauzal, adaptiv.
    Reutilizat de LVN interaction si de acceptance/rejection pe niveluri punctuale."""
    c = {**LEVEL_INTERACTION_DEFAULTS, **(cfg or {})}
    n = len(snapshot)
    R = int(c["confirmation_window"])

    def none(state="INSUFFICIENT_EVIDENCE"):
        return InteractionContext(False, kind, tier, float(zlo), float(zhi), 0.0, 0.0, 0, 0.0,
                                  "UNKNOWN", "NONE", 0.0, 0.0, state, "NONE", R)

    if n < int(c["min_bars"]) or zhi < zlo:
        return none()
    high, low, close, cvd, t = (snapshot.high, snapshot.low, snapshot.close,
                                snapshot.cvd, snapshot.t)
    tick = snapshot.tick_size or 0.25
    last = n - 1
    tol = c["tol_ticks"] * tick
    lo_scan = max(0, last - int(c["scan_lookback"]))
    runs = _find_runs(high, low, zlo, zhi, tol, lo_scan, last)
    if not runs:
        return none()

    rs, re = runs[-1]
    deltas = np.diff(cvd, prepend=0.0)
    bar_range = float(np.median((high - low)[lo_scan:last + 1]))
    bar_range_ticks = max(bar_range / tick, 1e-9)
    zone_width_ticks = (zhi - zlo) / tick
    expected_cross = max(1.0, zone_width_ticks / bar_range_ticks)
    reaction_min = c["reaction_ratio"] * bar_range_ticks

    approach = "UNKNOWN"
    if rs - 1 >= 0:
        pc = close[rs - 1]
        approach = "FROM_ABOVE" if pc > zhi + tol else "FROM_BELOW" if pc < zlo - tol else "UNKNOWN"

    entry_price = float(close[rs])
    bars_inside = re - rs + 1
    seg_low, seg_high = float(np.min(low[rs:re + 1])), float(np.max(high[rs:re + 1]))
    if approach == "FROM_ABOVE":
        penetration = (zhi - seg_low) / tick
    elif approach == "FROM_BELOW":
        penetration = (seg_high - zlo) / tick
    else:
        penetration = (seg_high - seg_low) / tick
    delta_during = float(np.sum(deltas[rs:re + 1]))
    cur = float(close[last])
    price_progress = (cur - entry_price) / tick
    post = last - re
    still_inside = (re == last) or (zlo - tol <= cur <= zhi + tol)

    if still_inside:
        exit_dir = "INSIDE"
    elif approach == "FROM_ABOVE":
        exit_dir = "BACK" if cur > zhi else "THROUGH" if cur < zlo else "INSIDE"
    elif approach == "FROM_BELOW":
        exit_dir = "BACK" if cur < zlo else "THROUGH" if cur > zhi else "INSIDE"
    else:
        exit_dir = "THROUGH" if (cur > zhi or cur < zlo) else "INSIDE"

    if approach == "FROM_ABOVE":
        move_away = (cur - zhi) / tick
    elif approach == "FROM_BELOW":
        move_away = (zlo - cur) / tick
    else:
        move_away = abs(cur - (zlo + zhi) / 2.0) / tick

    # respingere anterioara reala: pretul a plecat din zona (>= reaction_min) intre doua atingeri
    prior_rejection = False
    if len(runs) >= 2:
        _, pre = runs[-2]
        gap = high[pre + 1:rs] if rs > pre + 1 else np.zeros(0)
        gap_lo = low[pre + 1:rs] if rs > pre + 1 else np.zeros(0)
        if len(gap):
            away = max(float(np.max(gap - zhi)) / tick, float(np.max(zlo - gap_lo)) / tick, 0.0)
            prior_rejection = away >= reaction_min

    # clasificare (transparenta, adaptiva)
    if still_inside:
        if bars_inside >= c["accept_ratio"] * expected_cross:
            state, status = "ACCEPTANCE", "CONFIRMED"
        else:
            state, status = "TEST", "FORMING"
    elif exit_dir == "BACK":
        if move_away >= reaction_min:
            state, status = "REJECTION", ("CONFIRMED" if post >= R else "FORMING")
        else:
            state, status = "TEST", "FORMING"
    elif exit_dir == "THROUGH":
        if bars_inside <= c["fast_ratio"] * expected_cross:
            state, status = "FAST_TRAVERSAL", ("CONFIRMED" if post >= R else "FORMING")
        else:
            state, status = "ACCEPTANCE", "CONFIRMED"
    else:
        state, status = "TEST", "FORMING"

    if prior_rejection and state == "ACCEPTANCE":     # respingere initiala invalidata de acceptare
        state = "FAILED_REJECTION"

    return InteractionContext(
        True, kind, tier, float(zlo), float(zhi), entry_price, penetration, bars_inside,
        bars_inside * snapshot.bar_seconds, approach, exit_dir, delta_during,
        price_progress, state, status, R)


def _lvn_nodes_from_snapshot(snapshot, min_prominence):
    """Nodurile LVN calculate CAUZAL din footprint-ul <= T (P1a compute_nodes, full profile)."""
    if not snapshot.footprint:
        return []
    vp = VolumeProfileEngine(tick_size=snapshot.row_size or 0.25)
    for cells in snapshot.footprint.values():
        for price, (buy, sell) in cells.items():
            tot = buy + sell
            if tot > 0:
                vp.add_tick(price, tot)
    _, lvn_nodes = vp.compute_nodes(min_prominence_ratio=min_prominence, lvn_mode="full")
    return lvn_nodes


def analyze_lvn_interaction(snapshot: Snapshot, cfg=None) -> InteractionContext:
    """Interactiunea pretului cu LVN-ul cel mai RECENT atins (zona reala a nodului)."""
    c = {**LEVEL_INTERACTION_DEFAULTS, **(cfg or {})}
    nodes = _lvn_nodes_from_snapshot(snapshot, c["lvn_min_prominence"])
    n = len(snapshot)
    if not nodes or n < int(c["min_bars"]):
        return InteractionContext(False, "lvn", "", 0.0, 0.0, 0.0, 0.0, 0, 0.0, "UNKNOWN",
                                  "NONE", 0.0, 0.0, "INSUFFICIENT_EVIDENCE", "NONE",
                                  int(c["confirmation_window"]))
    high, low = snapshot.high, snapshot.low
    tick = snapshot.tick_size or 0.25
    tol = c["tol_ticks"] * tick
    last = n - 1
    lo_scan = max(0, last - int(c["scan_lookback"]))
    best, best_touch = None, -1
    for node in nodes:
        for i in range(last, lo_scan - 1, -1):        # ultima atingere a zonei nodului
            if _touch(high, low, i, node.low, node.high, tol):
                if i > best_touch:
                    best_touch, best = i, node
                break
    if best is None:
        return InteractionContext(False, "lvn", "", 0.0, 0.0, 0.0, 0.0, 0, 0.0, "UNKNOWN",
                                  "NONE", 0.0, 0.0, "INSUFFICIENT_EVIDENCE", "NONE",
                                  int(c["confirmation_window"]))
    return analyze_level_interaction(snapshot, best.low, best.high, "lvn", best.tier, cfg)


def analyze_acceptance_rejection(snapshot: Snapshot, cfg=None) -> InteractionContext:
    """Acelasi motor generic aplicat NIVELULUI cheie (POC/VAH/VAL) cel mai apropiat de pret.
    Banda e specifica nivelului (POC mai lata = magnet; VAH/VAL mai ingusta)."""
    c = {**LEVEL_INTERACTION_DEFAULTS, **(cfg or {})}
    n = len(snapshot)
    if n < int(c["min_bars"]):
        return InteractionContext(False, "level", "", 0.0, 0.0, 0.0, 0.0, 0, 0.0, "UNKNOWN",
                                  "NONE", 0.0, 0.0, "INSUFFICIENT_EVIDENCE", "NONE",
                                  int(c["confirmation_window"]))
    cur = float(snapshot.close[-1])
    tick = snapshot.tick_size or 0.25
    last = n - 1
    lo_scan = max(0, last - int(c["scan_lookback"]))
    bar_range = float(np.median((snapshot.high - snapshot.low)[lo_scan:last + 1]))
    candidates = [("poc", snapshot.poc), ("vah", snapshot.vah), ("val", snapshot.val)]
    candidates = [(k, v) for k, v in candidates if v and v > 0]
    if not candidates:
        return InteractionContext(False, "level", "", 0.0, 0.0, 0.0, 0.0, 0, 0.0, "UNKNOWN",
                                  "NONE", 0.0, 0.0, "INSUFFICIENT_EVIDENCE", "NONE",
                                  int(c["confirmation_window"]))
    kind, level = min(candidates, key=lambda kv: abs(kv[1] - cur))
    ratios = c["point_band_ratio"]
    band = ratios.get(kind, ratios["default"]) * bar_range
    band = max(band, c["tol_ticks"] * tick)
    return analyze_level_interaction(snapshot, level - band, level + band, kind, "", cfg)


# ------------------------------------------------------------------ ContextEngine
class ContextEngine:
    """
    Stratul de analiza: functie PURA si DETERMINISTA de un Snapshot cauzal.

    Nu detine niciun obiect de zi intreaga si nu poate privi in viitor — primeste doar
    Snapshot-ul, care contine fizic doar date <= T. `analyze()` nu muta nicio stare
    interna; acelasi Snapshot -> acelasi ContextResult, mereu.

    P4-core: calculeaza doar valori de fundatie (now_epoch, n_bars, last_price, poc
    cauzal, cvd). Componentele de order flow se adauga in fazele urmatoare, fiecare tot
    ca functie pura de Snapshot.
    """

    def __init__(self, config=None):
        # Config imutabila logic (parametri de praguri pt componentele viitoare).
        self.config = dict(config or {})

    def analyze(self, snapshot: Snapshot) -> ContextResult:
        """Snapshot cauzal -> ContextResult. Pura, determinista, fara look-ahead."""
        n = len(snapshot)
        # Componente de order flow (fiecare = functie pura de Snapshot).
        components = {
            "delta": analyze_delta(snapshot, self.config.get("delta")),
            "price_progress": analyze_price_progress(snapshot, self.config.get("price_progress")),
            "absorption": analyze_absorption(snapshot, self.config.get("absorption")),
            "exhaustion": analyze_exhaustion(snapshot, self.config.get("exhaustion")),
            "cvd_divergence": analyze_cvd_divergence(snapshot, self.config.get("cvd_divergence")),
            "poc_migration": analyze_poc_migration(snapshot, self.config.get("poc_migration")),
            "lvn_interaction": analyze_lvn_interaction(snapshot, self.config.get("level_interaction")),
            "acceptance_rejection": analyze_acceptance_rejection(snapshot, self.config.get("level_interaction")),
        }
        if n == 0:
            return ContextResult(now_epoch=int(snapshot.now_epoch), n_bars=0,
                                 last_price=0.0, poc=0.0, cvd=0.0, components=components)
        return ContextResult(
            now_epoch=int(snapshot.now_epoch),
            n_bars=n,
            last_price=float(snapshot.close[-1]),
            poc=float(snapshot.poc),
            cvd=float(snapshot.cvd[-1]),
            overall="NEUTRAL",
            components=components,
        )
