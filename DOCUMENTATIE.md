# Volume Profile Terminal — Documentație completă

Tool propriu de analiză avansată de piață (Volume Profile + Order Flow/Delta) pentru
futures **NQ** (E-mini Nasdaq-100), cu date reale de la **Databento**. Aplicație
**desktop nativă** (Python), gândită pentru uz personal la tranzacționare, cu look
în stil DeepCharts/ATAS.

> **Principiul de bază:** motorul de calcul e complet separat de interfață.
> Engine-urile calculează și returnează date structurate; ele **nu desenează nimic**.
> Orice interfață (desktop, web, viitor) se construiește peste același „creier".

---

## 1. Structura proiectului

```
Volume Profile/
├── core/                       # CREIERUL - motoare de calcul (fără UI, fără date)
│   ├── vp_engine.py            #   Volume Profile: POC, VAH/VAL, HVN/LVN
│   └── delta_engine.py         #   Delta / Order Flow: buy/sell/delta per nivel
│
├── data/                       # STRAT DE DATE
│   ├── loader.py               #   Loader UNIC: CSV/Parquet, simbol activ, sesiune
│   ├── raw/                    #   CSV-uri brute Databento (10 zile) + metadate
│   └── parquet/                #   CSV-urile convertite (14x mai mici, rapide)
│
├── app/                        # INTERFETE
│   ├── desktop/                #   Terminal desktop (PySide6 + pyqtgraph) - PRINCIPALUL
│   │   ├── data_service.py     #     Pod loader+engine -> date gata de desenat
│   │   ├── charts.py           #     Lumânări + profil overlay (desen pyqtgraph)
│   │   ├── replay.py           #     Replay tick-by-tick + seek/checkpoints (backtesting)
│   │   ├── drawings.py         #     Unelte de desen (nivel/trend/rect/fib/măsură)
│   │   ├── theme.py            #     Paletă dark (stil DeepCharts)
│   │   └── main.py             #     Fereastra: controale, grafic, crosshair
│   └── streamlit_app.py        #   Prototip web (Streamlit + Plotly) - secundar
│
├── scripts/                    # UNELTE CLI (analiză în terminal)
│   ├── convert_to_parquet.py   #   CSV -> Parquet (rulează o dată)
│   ├── load_databento_csv.py   #   VP pentru o zi
│   ├── delta_analysis.py       #   VP + Delta pentru o zi
│   ├── multi_day_analysis.py   #   OHLC + VP/zi + composite pe o săptămână
│   ├── session_reanalysis.py   #   VP pe sesiuni futures reale (22:00 UTC)
│   ├── live_simulator.py       #   Developing profile (evoluție oră cu oră)
│   └── verify_ohlc.py          #   Verificare independentă OHLC vs sursă externă
│
├── tests/                      # TESTE AUTOMATE (pytest) - 53 teste
│   ├── test_vp_engine.py       #   POC / Value Area / HVN-LVN peaks
│   ├── test_delta_engine.py    #   buy/sell/delta + normalizare side
│   ├── test_loader.py          #   simbol activ, side, granița sesiune
│   ├── test_nodes.py           #   HVN/LVN corecte pe DATE REALE + POC aliniat
│   ├── test_footprint.py       #   footprint = totaluri reale + celulă vs tick-uri
│   ├── test_replay_seek.py     #   seek/backtesting: checkpoints corecte, fără drift
│   ├── test_absorption.py      #   absorption sintetic determinist (fără fals-pozitive)
│   ├── test_vwap_bigtrades.py  #   VWAP + Big Trades pe date reale
│   ├── test_replay_determinism.py  # replay determinist indiferent de viteză
│   └── test_integration.py     #   fereastra reală: matrice combinații + invarianți
│
├── run_desktop.py              # Lansator aplicație desktop
├── pyproject.toml              # Config pachet + pytest
├── requirements.txt            # Dependințe
├── README.md                   # Ghid scurt de setup
└── DOCUMENTATIE.md             # Acest document
```

---

## 2. Ce calculează (concepte)

### Volume Profile (`core/vp_engine.py`)
- **POC (Point of Control)** — nivelul de preț cu cel mai mare volum tranzacționat.
- **Value Area (VAH/VAL)** — zona unde s-au făcut 70% din tranzacții, calculată prin
  **expansiune din POC** (algoritmul corect, ca Sierra Chart — nu procent simplu):
  pornești din POC, adaugi mereu nivelul vecin cu volum mai mare, până acumulezi 70%.
- **HVN (High Volume Node)** — noduri de volum **mare** = suport/rezistență puternice,
  „magneți" de preț (prețul stagnează acolo).
- **LVN (Low Volume Node)** — noduri de volum **mic** = zone de tranzit rapid / respingere
  (prețul trece repede prin ele).
- HVN/LVN prin **peak detection real** (maxime/minime locale), nu praguri globale;
  cu prag de semnificație și grupare, ca să iasă doar nodurile reale.

**Notă tehnică internă:** profilul folosește `tick_index` (int) ca și cheie, nu prețul
float — elimină erorile de rotunjire. La ieșire se convertește înapoi în prețuri reale.

### Delta / Order Flow (`core/delta_engine.py`)
Folosește câmpul `side` din schema Trades Databento (deja clasificat de ei):
- `'B'` (Bid) = **buy aggressor** (cumpărare agresivă)
- `'A'` (Ask) = **sell aggressor** (vânzare agresivă)

Calculează per nivel: volum buy, volum sell, delta (buy − sell). Plus **Cumulative
Delta** (suma pe toată sesiunea) — arată cine a dominat.

### VWAP
Preț mediu ponderat cu volumul, **developing** (cumulativ pe parcursul sesiunii),
calculat din lumânări: `cumsum((H+L+C)/3 × vol) / cumsum(vol)`.

### Sesiunea futures reală
Ziua de tranzacționare CME nu e ziua calendaristică UTC. Sesiunea începe la **18:00 ET
= 22:00 UTC** (vara/EDT) și ține până a doua zi la 22:00 UTC. Regula: dacă ora UTC ≥ 22,
tick-ul aparține sesiunii zilei următoare. (Verificat cu surse externe.)

---

## 3. Aplicația desktop — funcționalități

Layout **stil DeepCharts 1:1**: un singur grafic, profilul **suprapus translucid** peste
lumânări, ancorat pe stânga, care se re-ancorează și re-scalează la pan/zoom.

**Layout:** bara de sus = *ce date afișezi* (grupat: Ziua · Tip/Perioadă/Vedere ·
Interval/VA%/Rezoluție/Fus · Straturi). Bara de jos = *playback & backtesting* (Replay + nav).

**Controale (bara de sus):**
| Control | Ce face |
|---|---|
| **Ziua** | Alege ziua de tranzacționare (etichetată bearish/range-bound) |
| **Tip** | `Profil` (lumânări + VP overlay) sau `Footprint` (celule bid/ask per lumânare) |
| **Perioada** | `1 zi` (o sesiune) sau `Săptămână` (composite pe blocul de zile) |
| **Vedere** | `Sesiune` (22:00→22:00 UTC) sau `Zi UTC` (00:00–24:00) |
| **Interval** | Lumânări: 1min / 5min / 15min / 30min / 1h / 2h / 4h / 1D |
| **VA %** | Procentul Value Area (implicit 70%) |
| **Rezoluție** | Granularitatea profilului — **controlează tot calculul** (vezi mai jos) |
| **HVN/LVN** | Afișează/ascunde liniile de noduri |
| **Big Trades** | Afișează/ascunde bulele tranzacțiilor mari |
| **Absorption** | Afișează/ascunde markerele de absorbție (triunghiuri la extreme) |
| **Replay** | Intră în modul replay (redă sesiunea din start) |
| **▶ / ⏸** | Play / Pauză replay (sau tasta **spațiu**) |
| **Viteza** | lent / 1x / 2x / 5x / 10x (tick-uri pe cadru la replay) |

**Bara de backtesting (jos, activă în replay):** ⏮ start · **◀ Bar / Bar ▶** (pas ±1 lumânare,
sau săgețile ← →) · **scrubber** (tragi oriunde în sesiune, înainte și înapoi) · ⏭ final ·
**Sari la HH:MM** (sări la minutul exact în fusul afișat). Poziția curentă (oră + bar N/total)
e afișată lângă scrubber. Seek-ul e instant chiar și pe sesiuni de sute de mii de tick-uri
(checkpoints interne). La orice navigare manuală, redarea automată se oprește (pas cu pas).

**Bara de unelte de desen (verticală, stânga graficului):** cursor · **nivel orizontal** (1 click,
mobil) · **trendline** (2 clickuri, cu mânere) · **dreptunghi/zonă** (2 clickuri, translucid) ·
**fib retracement** (2 clickuri — swing) · **măsură** (2 clickuri: puncte / ticks / % / minute).
Preview live între clickuri; **Esc** anulează unealta, **Delete** = undo, plus butoane **↶ undo**
și **🗑 clear**. Desenele există pe durata sesiunii (nu se salvează pe disc).

**Elemente pe grafic:**
- Lumânări verde (urcare) / mov (coborâre) — paletă DeepCharts
- Profil overlay translucid: verde = buy agresiv, mov = sell agresiv, per nivel
- **POC** — linie magenta cu etichetă-pastilă pe axă
- **Value Area** — cutie portocalie translucidă + linii VAH/VAL punctate
- **VWAP** — curbă portocalie developing
- **CVD** — panou separat sub grafic: Cumulative Delta (linie albastră) developing în timp,
  aliniat cu prețul (vezi divergențe preț vs delta)
- **Footprint** (mod Tip): celule bid/ask colorate pe imbalance, numere „sell×buy" la zoom,
  + **rând de DELTA total per lumânare** (impuls) la bază: verde = cumpărare, mov = vânzare
  + **Imbalances** (contur luminos, metoda diagonală ATAS, prag 3:1): verde = buy imbalance,
    mov = sell imbalance; consecutive = stacked imbalance
- **HVN** — linii cyan cu etichetă „HVN <preț>"; **LVN** — linii gri cu „LVN <preț>"
- **Big Trades** — bule la tranzacțiile individuale mari (≥25 contracte pe NQ),
  mărimea = volumul, verde = cumpărare / mov = vânzare (buton on/off)
- **Absorption** — markere la extrema unei lumânări unde volum agresiv mare a fost **absorbit**
  iar prețul nu a continuat (respingere): triunghi **verde sub minim** = vânzare agresivă absorbită
  de cumpărători pasivi → suport (bull); triunghi **mov peste maxim** = cumpărare agresivă absorbită
  de vânzători pasivi → rezistență (bear). Detecție pe lumânări închise (praguri tunable în
  `data_service.py`: `ABS_MIN_VOL`, `ABS_DOM`, `ABS_FRAC`, `ABS_REJECT`, `ABS_ZONE`). Buton on/off.
- **Ultim preț** — linie punctată cu pastilă
- **Crosshair** — urmărește mouse-ul, afișează preț + oră UTC
- **Zoom pe scale** — trage de **scala de preț** (dreapta) ca să comprimi/extinzi vertical,
  sau de **scala de timp** (jos) ca să comprimi/extinzi orizontal (ca la TradingView); rotița
  = zoom pe ambele; dublu-click pe grafic revine la auto-range

**Carduri statistici:** Simbol, POC, VAH/VAL, Volum total, Cumulative Delta (colorat).

### Consistență totală „ce vezi = ce se calculează"
Slider-ul **Rezoluție** setează `tick_size`-ul motorului, deci **POC, VAH, VAL, HVN, LVN
și barele profilului se calculează pe ACEEAȘI grilă** pe care o vezi:
- **0.25** = valori precise la tick (POC-ul „adevărat")
- mai mare (1/2/5) = grupat mai gros (POC pe bara vizibilă cea mai groasă)

POC = garantat pe bara cea mai groasă afișată; HVN pe vârfuri; LVN pe văi. Fără decalaje.
Barele arată volumul **total** per nivel, colorate proporțional buy/sell.

---

## 4. Cum se rulează

**Setup (o singură dată):**
```powershell
cd "D:\Volume Profile"
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\pip install -e .
```

**Aplicația desktop:**
```powershell
.\.venv\Scripts\python.exe run_desktop.py
```

**Testele (verifică corectitudinea):**
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
→ trebuie să apară `53 passed`.

**Prototipul web (opțional):**
```powershell
.\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py
```

**Date noi:** pui CSV-urile în `data\raw\`, apoi:
```powershell
.\.venv\Scripts\python.exe scripts\convert_to_parquet.py
```

---

## 5. Setări tehnice de reținut

- **Instrument:** NQ (E-mini Nasdaq-100), contract activ **NQU6** (ales automat după volum)
- **Tick size real:** 0.25
- **Value Area:** 70% (expansiune din POC)
- **Sesiune futures:** 22:00 UTC → 22:00 UTC (18:00 ET, CME Globex, vara/EDT)
- **Databento:** schema **Trades** ($28/GB); setări descărcare: Encoding=CSV,
  Compression=None, Price format=Decimal, Symbol field=Include
- **Câmp `side`:** A = sell aggressor, B = buy aggressor, N = necunoscut
- **Date disponibile:** bearish (20-24 iul 2026), range-bound (6-10 iul 2026)

---

## 6. Ce s-a validat

- **POC/VAH/VAL** — verificate independent (pandas brut) la virgulă; algoritm VA corect
- **Delta** — buy/sell/cumulative verificate independent (ex. 6 iul: +458)
- **HVN/LVN** — verificate numeric (peste/sub medie) + vizual (mini-histograme) +
  aliniate la rezoluția de afișare; conforme definiției standard
- **Sesiune 22:00 UTC** — verificată (ex. sesiunea 21 iul = 20 iul 22:00 → 21 iul 21:00)
- **Reproductibilitate** — rezultatele se potrivesc între metode/scripturi diferite
- **Footprint** — suma celulelor = totalul real buy/sell; celulă verificată vs tick-uri brute
- **53 teste automate** trec (engine + loader + noduri + footprint + seek replay pe date reale)
- **Toate scripturile CLI** rulează fără eroare pe date reale

---

## 7. Roadmap

- [x] Fundație: structură, loader unic, Parquet, teste
- [x] Volume Profile complet: POC, VA, HVN/LVN (peak detection real)
- [x] Delta / Order Flow (buy/sell/cumulative)
- [x] Sesiune futures reală + composite multi-zi
- [x] Terminal desktop stil DeepCharts (overlay, VWAP, crosshair, HVN/LVN etichetate)
- [x] **Footprint** — celule bid/ask colorate pe imbalance + **numere „sell×buy" în
      celule** (apar automat la zoom, când celula e destul de mare); readout
      buy/sell/delta pe crosshair. Comutator Profil/Footprint.
- [x] **Replay tick-by-tick** — lumânarea curentă se formează tick cu tick (open fix,
      high/low se întind, close se mișcă); profilul/footprint/VWAP/delta se dezvoltă live;
      auto-follow (urmărește prețul), play/pauză/viteză
- [x] **Big Trades** (bule) + **imbalance markers** (footprint)
- [x] **Absorption** — markere la extreme respinse (volum agresiv absorbit, preț nu continuă)
- [x] **Backtesting Bloc 1 — control replay complet:** scrubber (tragi oriunde, înainte/înapoi),
      pas ±1 lumânare (butoane + săgeți), ⏮/⏭ (start/final), sari la minut exact (HH:MM),
      spațiu = play/pauză; seek rapid prin checkpoints (median ~25ms)
- [x] **Backtesting Bloc 2 — unelte de desen** (nivel orizontal, trendline, dreptunghi/zonă,
      fib retracement, măsură puncte/ticks/%/timp); undo/clear, Esc/Delete; pe durata sesiunii
- [ ] Exhaustion (detecție automată: climax de volum / delta la extrema trend-ului)
- [ ] Developing profile / profile pe sesiuni de-a lungul zilei
- [ ] **Date LIVE** (Databento Standard $199/lună, sau Tradovate/Rithmic) — profil în timp real
- [ ] Comercializare eventuală (auth, billing, multi-user)

---

## 8. Note

- Prototipul Streamlit (`app/streamlit_app.py`) a fost primul pas vizual; a fost înlocuit
  de terminalul desktop (mult mai potrivit pentru un tool live). Rămâne funcțional ca
  referință/analiză rapidă în browser.
- Nivel ATAS/Sierra pixel-cu-pixel complet (footprint fluid GPU, DOM) rămâne un proiect
  mare de viitor; valoarea actuală e în corectitudinea motorului + look-ul profesional.
