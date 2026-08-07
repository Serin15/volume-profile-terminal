"""
Volume Profile Engine
----------------------
Motor de calcul pentru Volume Profile, independent de UI si de sursa de date.
Primeste tick-uri (price, volume) si calculeaza POC, Value Area (VAH/VAL), HVN/LVN.

Principiu: engine-ul NU deseneaza nimic, doar returneaza date structurate.
Randarea (matplotlib/Plotly/Canvas mai tarziu) e complet separata.

Nota de implementare: intern, preturile sunt stocate ca tick_index (int),
nu ca float. Asta elimina erorile de rotunjire care pot aparea cu float-uri
ca si chei de dictionar (ex. 22341.25 calculat pe doua cai diferite putand
sa nu fie identic bit-cu-bit). La iesire (rezultate), tot se convertesc
inapoi in preturi reale (float), deci interfata externa ramane neschimbata.
"""

from dataclasses import dataclass
from collections import defaultdict


@dataclass
class VolumeProfileResult:
    profile: dict          # {price_level: volume} - preturi reale, nu tick_index
    poc: float              # Point of Control (nivelul cu volum maxim)
    vah: float              # Value Area High
    val: float              # Value Area Low
    total_volume: float
    hvn: list               # High Volume Nodes (metoda veche, percentile)
    lvn: list               # Low Volume Nodes (metoda veche, percentile)
    hvn_peaks: list          # High Volume Nodes (metoda noua, peak detection real)
    lvn_peaks: list          # Low Volume Nodes (metoda noua, peak detection real)


@dataclass
class VolumeNode:
    """
    Un nod STRUCTURAT din Volume Profile (HVN sau LVN), cu marginile zonei si o
    clasa de importanta. Spre deosebire de compute_hvn_lvn_peaks() care intoarce
    doar un pret reprezentativ, aici zona are latime -> util pentru interactiunea
    pretului cu LVN-ul (traverseaza toata zona? o respinge la margine?).

    kind:       "hvn" | "lvn"
    price:      pretul reprezentativ (varful/valea extrema a zonei)
    low, high:  marginile zonei (cel mai jos / cel mai sus nivel din grupul unit)
    width:      high - low (0 = nod pe un singur nivel)
    volume:     volumul la nivelul reprezentativ
    prominence: cat de mult iese in evidenta fata de media profilului (>=0).
                HVN: vol/medie - 1 ; LVN: 1 - vol/medie.
    tier:       "major" | "minor" (dupa pragul de prominenta) - noduri importante vs marunte.
    """
    kind: str
    price: float
    low: float
    high: float
    width: float
    volume: float
    prominence: float
    tier: str


# Moduri de detectie LVN (unde se raporteaza vaile de volum):
#   "full"         - pe TOT profilul (inclusiv spre margini). IMPLICIT pentru sistemul nou:
#                    ipoteza de testat = un LVN e o zona structurala de volum mic ORIUNDE,
#                    NU automat discount/premium.
#   "between_hvns" - doar in intervalul dintre cel mai jos si cel mai sus HVN (comportament vechi).
#   "value_area"   - doar in interiorul Value Area (VAL..VAH).
LVN_MODES = ("full", "between_hvns", "value_area")


class VolumeProfileEngine:
    """
    Engine de Volume Profile pe baza de tick-uri.

    tick_size: marimea bin-ului de pret (ex. 0.25 pentru NQ).
               Toate preturile sunt "bucketed" la cel mai apropiat multiplu de tick_size.

    Intern, engine-ul lucreaza cu tick_index (int) = round(price / tick_size),
    nu cu pretul float direct. Asta e mai rapid, foloseste mai putina memorie,
    si evita problemele de rotunjire ale float-urilor ca si chei de dictionar.
    """

    def __init__(self, tick_size: float = 0.25):
        self.tick_size = tick_size
        self.profile = defaultdict(float)   # {tick_index: volum}
        self.total_volume = 0.0

    def _to_tick_index(self, price: float) -> int:
        """Converteste un pret real in tick_index (intreg)."""
        return round(price / self.tick_size)

    def _to_price(self, tick_index: int) -> float:
        """Converteste un tick_index inapoi in pret real."""
        return round(tick_index * self.tick_size, 8)

    def add_tick(self, price: float, volume: float):
        """Adauga un singur tick in profil. Update incremental, O(1)."""
        idx = self._to_tick_index(price)
        self.profile[idx] += volume
        self.total_volume += volume

    def add_ticks_bulk(self, ticks):
        """
        ticks: iterabil de tuple (price, volume).
        Util pentru incarcare initiala din istoric (CSV/DataFrame).
        """
        for price, volume in ticks:
            self.add_tick(price, volume)

    def compute_poc(self) -> float:
        """Point of Control = nivelul de pret cu cel mai mare volum acumulat."""
        if not self.profile:
            return None
        poc_idx = max(self.profile.items(), key=lambda kv: kv[1])[0]
        return self._to_price(poc_idx)

    def compute_value_area(self, va_percent: float = 0.70):
        """
        Algoritmul corect de Value Area (cum face Sierra Chart):
        1. Pornesti din POC.
        2. Te uiti la nivelul de deasupra si la nivelul de dedesubt.
        3. Adaugi in Value Area pe cel cu volum mai mare dintre cele doua.
        4. Repeti pana acumulezi va_percent din volumul total.

        Returneaza (vah, val) ca preturi reale.
        """
        if not self.profile:
            return None, None

        sorted_idx = sorted(self.profile.keys())
        poc_idx = max(self.profile.items(), key=lambda kv: kv[1])[0]
        poc_pos = sorted_idx.index(poc_idx)

        target_volume = self.total_volume * va_percent
        accumulated = self.profile[poc_idx]

        low_pos = poc_pos
        high_pos = poc_pos

        while accumulated < target_volume:
            next_high_pos = high_pos + 1
            next_low_pos = low_pos - 1

            vol_high = (
                self.profile[sorted_idx[next_high_pos]]
                if next_high_pos < len(sorted_idx)
                else -1
            )
            vol_low = (
                self.profile[sorted_idx[next_low_pos]]
                if next_low_pos >= 0
                else -1
            )

            if vol_high == -1 and vol_low == -1:
                break

            if vol_high >= vol_low:
                accumulated += vol_high
                high_pos = next_high_pos
            else:
                accumulated += vol_low
                low_pos = next_low_pos

        val = self._to_price(sorted_idx[low_pos])
        vah = self._to_price(sorted_idx[high_pos])
        return vah, val

    def compute_hvn_lvn(self, hvn_percentile: float = 0.85, lvn_percentile: float = 0.15):
        """
        HVN (High Volume Nodes): niveluri cu volum peste percentila hvn_percentile.
        LVN (Low Volume Nodes): niveluri cu volum sub percentila lvn_percentile.
        Metoda simpla, bazata pe percentile ale distributiei de volum.

        NOTA: aceasta e metoda "naiva" (procente), pastrata pentru compatibilitate.
        Pentru detectie corecta de zone (asa cum fac Sierra/ATAS), foloseste
        compute_hvn_lvn_peaks() - cauta maxime/minime LOCALE, nu doar praguri globale.
        """
        if not self.profile:
            return [], []

        volumes = sorted(self.profile.values())
        n = len(volumes)
        hvn_threshold = volumes[int(n * hvn_percentile)]
        lvn_threshold = volumes[int(n * lvn_percentile)]

        hvn = [self._to_price(idx) for idx, vol in self.profile.items() if vol >= hvn_threshold]
        lvn = [self._to_price(idx) for idx, vol in self.profile.items() if vol <= lvn_threshold]

        return sorted(hvn), sorted(lvn)

    def compute_hvn_lvn_peaks(self, window: int = None, min_prominence_ratio: float = 0.15,
                               window_ratio: float = 0.03, merge_gap_ticks: int = 4,
                               lvn_within_hvn: bool = True):
        """
        Detectie REALA de HVN/LVN prin maxime/minime LOCALE (peak detection),
        nu praguri globale de percentile. Asta e cum functioneaza Sierra/ATAS/Bookmap.

        Cum functioneaza:
        1. Pentru fiecare nivel de pret, verificam daca volumul lui e cel mai mare
           (sau cel mai mic) dintr-o FEREASTRA de niveluri in jurul lui.
        2. Filtram "varfurile" nesemnificative: un candidat trebuie sa aiba un
           volum cu cel putin min_prominence_ratio diferit de media profilului.
        3. GRUPAM candidatii apropiati (in cadrul a merge_gap_ticks unul de altul)
           intr-o singura "zona", raportand punctul cu volumul extrem din grup -
           altfel o zona plata (multe niveluri egale la coada distributiei) ar
           aparea ca zeci de "varfuri" separate, cand e de fapt o singura zona.

        window: numar fix de niveluri in fiecare directie. Daca None (implicit),
                se calculeaza automat ca window_ratio din numarul total de niveluri.
        window_ratio: procent din latimea profilului folosit ca fereastra (implicit 3%).
        min_prominence_ratio: cat de mult peste/sub medie trebuie sa fie un varf/vale
                ca sa fie considerat semnificativ (0.15 = cel putin 15% peste medie).
        merge_gap_ticks: cate niveluri de tick_size pot fi intre doi candidati ca sa
                fie considerati parte din aceeasi zona (nu doua zone separate).
        lvn_within_hvn: daca True (implicit), LVN-urile se raporteaza DOAR in
                intervalul de pret dintre cel mai jos si cel mai sus HVN. Motiv:
                un LVN real e o VALE intre zone de volum mare, nu marginea sparsa
                a distributiei (unde volumul e ~zero si fiecare nivel pare trivial
                un "minim local" - sursa de zgomot confirmata pe date reale).

        Returneaza (hvn_zones, lvn_zones) - liste de preturi (un pret reprezentativ
        per zona detectata), sortate.
        """
        if not self.profile:
            return [], []

        hvn_candidates, lvn_candidates, _ = self._node_candidates(
            window, min_prominence_ratio, window_ratio)

        def zones(candidates, pick_max):
            out = []
            for group in self._merge_groups(candidates, merge_gap_ticks):
                best_idx, _ = (max if pick_max else min)(group, key=lambda c: c[1])
                out.append(self._to_price(best_idx))
            return sorted(out)

        hvn_zones = zones(hvn_candidates, True)
        lvn_zones = zones(lvn_candidates, False)

        # LVN-urile reale sunt vai INTRE zone de volum mare, nu marginile sparse
        # ale distributiei. Le restrangem la intervalul acoperit de HVN-uri.
        if lvn_within_hvn and hvn_zones:
            lo, hi = hvn_zones[0], hvn_zones[-1]
            lvn_zones = [p for p in lvn_zones if lo <= p <= hi]

        return hvn_zones, lvn_zones

    def _node_candidates(self, window, min_prominence_ratio, window_ratio):
        """Candidatii HVN/LVN (varfuri/vai locale peste/sub pragul de prominenta) +
        media profilului. Logica PARTAJATA de compute_hvn_lvn_peaks si compute_nodes,
        ca sa existe o singura definitie a ce e un varf/vale (fara divergenta)."""
        sorted_idx = sorted(self.profile.keys())
        volumes = [self.profile[idx] for idx in sorted_idx]
        n = len(volumes)
        if n == 0:
            return [], [], 0.0
        if window is None:
            window = max(3, int(n * window_ratio))
        mean_volume = sum(volumes) / n
        hvn_min_volume = mean_volume * (1 + min_prominence_ratio)
        lvn_max_volume = mean_volume * (1 - min_prominence_ratio)
        hvn_candidates, lvn_candidates = [], []
        for i in range(n):
            lo = max(0, i - window)
            hi = min(n, i + window + 1)
            local_window = volumes[lo:hi]
            if volumes[i] == max(local_window) and volumes[i] >= hvn_min_volume:
                hvn_candidates.append((sorted_idx[i], volumes[i]))
            elif volumes[i] == min(local_window) and volumes[i] <= lvn_max_volume:
                lvn_candidates.append((sorted_idx[i], volumes[i]))
        return hvn_candidates, lvn_candidates, mean_volume

    @staticmethod
    def _merge_groups(candidates, merge_gap_ticks):
        """Grupeaza candidatii aflati la <= merge_gap_ticks unul de altul intr-o singura
        zona. Returneaza lista de grupuri, fiecare = lista de (tick_index, volum)."""
        if not candidates:
            return []
        candidates = sorted(candidates, key=lambda c: c[0])
        groups = []
        current = [candidates[0]]
        for idx, vol in candidates[1:]:
            if idx - current[-1][0] <= merge_gap_ticks:
                current.append((idx, vol))
            else:
                groups.append(current)
                current = [(idx, vol)]
        groups.append(current)
        return groups

    def compute_nodes(self, window: int = None, min_prominence_ratio: float = 0.15,
                      window_ratio: float = 0.03, merge_gap_ticks: int = 4,
                      lvn_mode: str = "full", va_percent: float = 0.70,
                      major_prominence_ratio: float = 0.6):
        """
        Detectie STRUCTURATA de noduri: intoarce (hvn_nodes, lvn_nodes) ca liste de
        VolumeNode cu margini (low/high), latime, prominenta si clasa (major/minor).
        Foloseste ACEIASI candidati + merge ca compute_hvn_lvn_peaks (o singura sursa
        de adevar), dar raporteaza zona intreaga, nu doar pretul reprezentativ.

        lvn_mode (unde se raporteaza vaile de volum):
            "full"         - tot profilul (IMPLICIT; ipoteza de testat, vezi LVN_MODES),
            "between_hvns" - doar intre cel mai jos si cel mai sus HVN (comportamentul vechi),
            "value_area"   - doar in interiorul Value Area (VAL..VAH).
            Un mod necunoscut e tratat permisiv ca "full".
        major_prominence_ratio: prag de prominenta peste care un nod e "major" (altfel "minor").
        """
        if not self.profile:
            return [], []
        hvn_candidates, lvn_candidates, mean_volume = self._node_candidates(
            window, min_prominence_ratio, window_ratio)

        def build(candidates, kind, pick_max):
            nodes = []
            for group in self._merge_groups(candidates, merge_gap_ticks):
                best_idx, best_vol = (max if pick_max else min)(group, key=lambda c: c[1])
                low = self._to_price(min(c[0] for c in group))
                high = self._to_price(max(c[0] for c in group))
                price = self._to_price(best_idx)
                if mean_volume > 0:
                    prom = (best_vol / mean_volume - 1.0) if pick_max \
                        else (1.0 - best_vol / mean_volume)
                else:
                    prom = 0.0
                prom = max(0.0, prom)
                tier = "major" if prom >= major_prominence_ratio else "minor"
                nodes.append(VolumeNode(kind=kind, price=price, low=low, high=high,
                                        width=round(high - low, 8), volume=best_vol,
                                        prominence=prom, tier=tier))
            nodes.sort(key=lambda z: z.price)
            return nodes

        hvn_nodes = build(hvn_candidates, "hvn", True)
        lvn_nodes = build(lvn_candidates, "lvn", False)

        if lvn_mode == "between_hvns" and hvn_nodes:
            lo, hi = hvn_nodes[0].price, hvn_nodes[-1].price
            lvn_nodes = [z for z in lvn_nodes if lo <= z.price <= hi]
        elif lvn_mode == "value_area":
            vah, val = self.compute_value_area(va_percent)
            if val is not None and vah is not None:
                lvn_nodes = [z for z in lvn_nodes if val <= z.price <= vah]
        # "full" (sau mod necunoscut) -> fara restrictie

        return hvn_nodes, lvn_nodes

    def result(self, va_percent: float = 0.70) -> VolumeProfileResult:
        """Returneaza rezultatul complet, structurat, gata de trimis catre orice UI."""
        poc = self.compute_poc()
        vah, val = self.compute_value_area(va_percent)
        hvn, lvn = self.compute_hvn_lvn()
        hvn_peaks, lvn_peaks = self.compute_hvn_lvn_peaks()

        # Convertim profilul intern (tick_index -> volum) in preturi reale (price -> volum)
        profile_real = {self._to_price(idx): vol for idx, vol in self.profile.items()}

        return VolumeProfileResult(
            profile=profile_real,
            poc=poc,
            vah=vah,
            val=val,
            total_volume=self.total_volume,
            hvn=hvn,
            lvn=lvn,
            hvn_peaks=hvn_peaks,
            lvn_peaks=lvn_peaks,
        )