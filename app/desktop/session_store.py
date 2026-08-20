"""
SessionStore — cache partajat pentru date (Faza 0 din arhitectura de panouri)
-----------------------------------------------------------------------------
O SINGURA sursa de adevar pentru citirile scumpe (ticks/parquet) si pentru
calculele VP per zi / sesiune. Panourile secundare viitoare (Historical Profile
Panel etc.) vor citi de aici in loc sa reciteasca parquet-ul de N ori.

PRINCIPII (Faza 0 = aditiva, fara schimbare de comportament):
  - NU reimplementeaza nimic: doar apeleaza logica EXISTENTA din data_service
    (resolve_ticks / load_day / period_profiles) si memoizeaza rezultatul.
  - Apelurile trec prin modulul `data_service` (ds.load_day, ...), nu prin
    simboluri importate direct -> raman testabile prin monkeypatch si nu
    dubleaza nicio definitie.
  - Valorile intoarse sunt IDENTICE cu apelul direct (POC/VAH/VAL/HVN/LVN/total).
  - Store-ul e STATELESS fata de replay: nu cunoaste niciun cursor / epoca
    curenta. Serveste doar agregate pe intreaga sesiune -> nu poate introduce
    look-ahead prin el insusi. Taierea cauzala la cursor ramane treaba Replay-ului.
  - Chei de cache DETERMINISTE (aceiasi parametri -> aceeasi cheie).

Store-ul NU e inca folosit de UI in Faza 0 (Main Chart / Profile Only raman
neatinse). E fundatia peste care se construieste Faza 1.
"""

import os
from collections import OrderedDict

import app.desktop.data_service as ds

# Nume de sesiune "prietenoase" (limbajul panoului) -> unitatea interna folosita de
# data_service.period_profiles. Panoul va vorbi Full Day / Asia / London / New York;
# data_service vorbeste Zi / Asia / Londra / NY. Aici e singurul loc de traducere.
SESSION_UNITS = OrderedDict([
    ("Full Day", "Zi"),
    ("Asia", "Asia"),
    ("London", "Londra"),
    ("New York", "NY"),
])


def _sessions_signature(sessions):
    """Semnatura hashabila, determinista, a listei de definitii de sesiuni (sau None).
    `sessions` = lista de (nume, fus, (sh, sm), (eh, em)) — ca in SESSION_DEFS."""
    if sessions is None:
        return None
    sig = []
    for name, tz, start, stop in sessions:
        sig.append((str(name), str(tz), (int(start[0]), int(start[1])),
                    (int(stop[0]), int(stop[1]))))
    return tuple(sig)


class SessionStore:
    """
    Cache LRU pentru ticks + calcule VP per zi/sesiune, construit peste data_service.

    maxsize: numarul maxim de intrari pastrate per tip de cache (LRU: cea mai veche
             folosita iese prima). Suficient pentru zeci de zile fara sa umple memoria.
    """

    def __init__(self, maxsize=64):
        self.maxsize = int(maxsize)
        self._ticks = OrderedDict()    # (basename, mode, span) -> SessionTicks
        self._day = OrderedDict()      # cheie zi -> DayData
        self._period = OrderedDict()   # cheie perioada -> list[dict]
        self.hits = 0
        self.misses = 0

    # ---------- infrastructura de memoizare ----------
    def _memo(self, cache, key, compute):
        """Intoarce cache[key] daca exista (hit, fara recalcul), altfel calculeaza,
        stocheaza si evictioneaza LRU daca s-a depasit maxsize."""
        if key in cache:
            self.hits += 1
            cache.move_to_end(key)
            return cache[key]
        self.misses += 1
        value = compute()
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > self.maxsize:
            cache.popitem(last=False)   # scoate cea mai veche folosita
        return value

    # ---------- API public ----------
    def get_ticks(self, filename, mode="session", span="day"):
        """Tick-urile pentru o selectie, ca tuple (SessionTicks, incomplete) — exact
        ce intoarce data_service.resolve_ticks (folosit ca `tk, _ = get_ticks(...)`).
        Citirea parquet (scumpa) se face o singura data per cheie."""
        key = (os.path.basename(filename), mode, span)
        return self._memo(self._ticks, key,
                          lambda: ds.resolve_ticks(filename, mode, span))

    def get_day(self, filename, va_percent=0.70, interval="5min", row_size=2.0,
                mode="session", span="day", big_trade_min=ds.BIG_TRADE_MIN,
                abs_params=None, exh_params=None, lvn_full_profile=False):
        """DayData complet (identic cu data_service.load_day) — memoizat.

        NB: abs_params/exh_params (dict-uri mici de override) intra in cheie sortate
        stabil ca sa ramana deterministe."""
        key = (os.path.basename(filename), round(float(va_percent), 6), str(interval),
               round(float(row_size), 6), mode, span, int(big_trade_min),
               _params_sig(abs_params), _params_sig(exh_params), bool(lvn_full_profile))
        return self._memo(self._day, key, lambda: ds.load_day(
            filename, va_percent=va_percent, interval=interval, row_size=row_size,
            mode=mode, span=span, big_trade_min=big_trade_min,
            abs_params=abs_params, exh_params=exh_params,
            lvn_full_profile=lvn_full_profile))

    def get_period_profiles(self, filename, mode="session", span="day", unit="Full Day",
                            va_percent=0.70, row_size=2.0, sessions=None,
                            lvn_full_profile=False):
        """VP-uri per perioada (zi/sesiune) de-a lungul span-ului — identic cu
        data_service.period_profiles — memoizat.

        `unit` accepta atat numele prietenos (Full Day / Asia / London / New York)
        cat si unitatea interna (Zi / Asia / Londra / NY / Toate)."""
        unit_internal = SESSION_UNITS.get(unit, unit)
        key = (os.path.basename(filename), mode, span, unit_internal,
               round(float(va_percent), 6), round(float(row_size), 6),
               _sessions_signature(sessions), bool(lvn_full_profile))
        return self._memo(self._period, key, lambda: ds.period_profiles(
            filename, mode=mode, span=span, unit=unit_internal,
            va_percent=va_percent, row_size=row_size, sessions=sessions,
            lvn_full_profile=lvn_full_profile))

    def get_session_profile(self, filename, session="Full Day", mode="session",
                            va_percent=0.70, row_size=2.0, sessions=None,
                            lvn_full_profile=False):
        """Comoditate pentru un panou: profilul (0 sau 1) al UNEI sesiuni dintr-o zi.
        `session` in Full Day / Asia / London / New York. Intoarce lista (ca
        period_profiles) — goala daca sesiunea nu are volum in ziua respectiva."""
        return self.get_period_profiles(
            filename, mode=mode, span="day", unit=session, va_percent=va_percent,
            row_size=row_size, sessions=sessions, lvn_full_profile=lvn_full_profile)

    @staticmethod
    def available_sessions():
        """Numele de sesiune suportate, in ordinea de afisat in panou."""
        return list(SESSION_UNITS.keys())

    # ---------- utilitare ----------
    def clear(self):
        """Goleste tot cache-ul + reseteaza contoarele (util in teste / la schimbarea datelor)."""
        self._ticks.clear(); self._day.clear(); self._period.clear()
        self.hits = 0; self.misses = 0

    def cache_info(self):
        """Statistici de diagnostic (hit/miss + dimensiuni)."""
        return {
            "hits": self.hits, "misses": self.misses,
            "ticks": len(self._ticks), "day": len(self._day),
            "period": len(self._period),
        }


def _params_sig(params):
    """Semnatura hashabila determinista a unui dict de parametri (sau None)."""
    if not params:
        return None
    return tuple(sorted((str(k), v) for k, v in params.items()))
