"""
Delta Engine
------------
Motor de calcul pentru Delta (Order Flow), independent de UI si de sursa de date.
Foloseste campul `side` din schema Trades (Databento): fiecare tick e deja
clasificat ca cumparare agresiva (buyer-initiated) sau vanzare agresiva
(seller-initiated), conform tick-rule/NBBO facut de Databento.

Conventie Databento pentru campul side:
    'A' (Ask) = sell aggressor -> tranzactia s-a executat la ask, agresor = vanzator
    'B' (Bid) = buy aggressor  -> tranzactia s-a executat la bid, agresor = cumparator
    'N' (None) = agresor necunoscut/nespecificat

Delta la un nivel de pret = volum_cumparare - volum_vanzare.
Delta pozitiv = cumparatorii au dominat la acel nivel.
Delta negativ = vanzatorii au dominat la acel nivel.

Cumulative Delta = suma delta-urilor tuturor tick-urilor, in ordine cronologica -
arata daca, per total, a dominat cumpararea sau vanzarea intr-o sesiune.
"""

from dataclasses import dataclass
from collections import defaultdict


@dataclass
class DeltaResult:
    delta_per_level: dict     # {price: delta (buy_volume - sell_volume)}
    buy_volume_per_level: dict
    sell_volume_per_level: dict
    cumulative_delta: float   # delta total pe toata perioada procesata
    total_buy_volume: float
    total_sell_volume: float


class DeltaEngine:
    """
    Engine de Delta pe baza de tick-uri clasificate (price, volume, side).

    tick_size: aceeasi conventie ca la VolumeProfileEngine.
    """

    def __init__(self, tick_size: float = 0.25):
        self.tick_size = tick_size
        self.buy_volume = defaultdict(float)   # {tick_index: volum cumparare agresiva}
        self.sell_volume = defaultdict(float)  # {tick_index: volum vanzare agresiva}
        self.cumulative_delta = 0.0
        self.total_buy_volume = 0.0
        self.total_sell_volume = 0.0

    def _to_tick_index(self, price: float) -> int:
        return round(price / self.tick_size)

    def _to_price(self, tick_index: int) -> float:
        return round(tick_index * self.tick_size, 8)

    def add_tick(self, price: float, volume: float, side: str):
        """
        Adauga un tick clasificat. side: 'A' (sell aggressor), 'B' (buy aggressor),
        sau altceva/None (necunoscut, ignorat la delta, dar nu la volumul brut).
        """
        idx = self._to_tick_index(price)
        side_normalizat = (side or "").strip().upper()[:1]

        if side_normalizat == "B":  # buy aggressor
            self.buy_volume[idx] += volume
            self.cumulative_delta += volume
            self.total_buy_volume += volume
        elif side_normalizat == "A":  # sell aggressor
            self.sell_volume[idx] += volume
            self.cumulative_delta -= volume
            self.total_sell_volume += volume
        # daca side e 'N' sau necunoscut, nu contribuie la delta (dar tot conteaza
        # in Volume Profile-ul calculat separat de VolumeProfileEngine)

    def add_ticks_bulk(self, ticks):
        """ticks: iterabil de tuple (price, volume, side)."""
        for price, volume, side in ticks:
            self.add_tick(price, volume, side)

    def result(self) -> DeltaResult:
        """Returneaza rezultatul complet, structurat."""
        all_idx = set(self.buy_volume.keys()) | set(self.sell_volume.keys())

        delta_per_level = {}
        buy_per_level = {}
        sell_per_level = {}

        for idx in all_idx:
            price = self._to_price(idx)
            buy = self.buy_volume.get(idx, 0.0)
            sell = self.sell_volume.get(idx, 0.0)
            delta_per_level[price] = buy - sell
            buy_per_level[price] = buy
            sell_per_level[price] = sell

        return DeltaResult(
            delta_per_level=delta_per_level,
            buy_volume_per_level=buy_per_level,
            sell_volume_per_level=sell_per_level,
            cumulative_delta=self.cumulative_delta,
            total_buy_volume=self.total_buy_volume,
            total_sell_volume=self.total_sell_volume,
        )