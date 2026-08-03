# Volume Profile Terminal — NQ

Terminal desktop de **Volume Profile & Order Flow** pentru E-mini Nasdaq-100 (NQ),
scris în Python (PySide6 + pyqtgraph), pe date reale Databento. Uz personal pentru
**backtesting** și **învățat order flow**, cu drum spre date live pentru tranzacționare
la deschiderea NY (16:30 RO / 09:30 ET).

Regula de aur a arhitecturii: **motoarele de calcul sunt separate de UI**. `core/`
calculează (NU desenează) → `data/` (loader unic + Parquet) → `app/desktop/` (interfața).

---

## Ce face (toate instrumentele)

### Volume Profile
- **POC / VAH / VAL** — Point of Control + Value Area (70%, algoritm de expansiune din POC).
- **HVN / LVN** — noduri de volum mare (suport/rezistență) și mici (goluri de tranzit), peak detection real.
- **5 moduri de perioadă** (panou ⚙): Sesiune (22:00→22:00 UTC) · Zi UTC · Composite (săptămână) ·
  Visible (recalculat pe ce vezi) · Custom range (tragi zona).
- **Profil overlay** suprapus peste preț (stil DeepCharts), 2 moduri: *Simplu* (o culoare, VA evidențiată,
  POC accentuat) sau *Buy/Sell* (split verde/mov per nivel).
- **VA box de ieri + POC ray** proiectat spre dreapta (repere la NY open).

### Order Flow
- **Delta per nivel** — buy − sell (agresor) la fiecare preț.
- **CVD (Cumulative Delta)** — panou jos, presiunea netă agresivă de-a lungul sesiunii (linie continuă,
  umplere verde/mov pe semn), cu toggle.
- **Footprint** — fiecare lumânare spartă pe niveluri de preț cu `sell × buy`; **bare interne bid/ask**
  (stil Quantower) la zoom; **imbalance** diagonal (metoda ATAS, ⚙ reglabil); **3 moduri**: Bid×Ask / Volume / Delta.
- **VWAP** developing + **Anchored VWAP** (unealta „aV": click = ancoră, ex. NY open; VWAP + benzi std-dev).
- **Developing POC/VA** — trailul migrării valorii în timp (se dezvoltă în replay).
- **Grid de statistici jos** — ΣV / ΔV / Δ% per lumânare, colorat heatmap (numere la zoom).

### Semnale
- **Big Trades** — bule la tranzacțiile mari (participare instituțională), hover cu detalii, zone S/R (⚙ prag).
- **Absorption** — agresiune absorbită la extreme (efort fără rezultat), markere galbene + hover (⚙ praguri).
- **Exhaustion** — climax de volum+delta la extreme noi (epuizare), romburi coral + hover (⚙ praguri).
- Praguri Absorption/Exhaustion reglate pentru **NY open** (volum mare) — filtrează zgomotul deschiderii.

### Context & backtesting
- **Nivelurile de ieri** — yPOC / yVAH / yVAL + PDH / PDL (amber).
- **Session shading (RTH)** — overnight umbrit, sesiunea NY iese în evidență (DST-corect).
- **Compare** — suprapune profilul + nivelurile altei sesiuni (albastru, ancorat dreapta).
- **Replay tick-by-tick** — redă sesiunea; scrubber, step ±1 bar, jump la HH:MM, seek rapid prin checkpoints.
- **Unelte de desen** — nivel / trend / dreptunghi / fib / măsură + **Long/Short** (Entry/Stop/Target → R:R + $),
  magnet cu Ctrl.
- **Smart Layers (Auto)** — LOD pe zoom: graficul își ascunde/arată detaliile automat.
- **Hover pe linii** — treci cu mouse-ul peste orice nivel → nume + preț.
- **Fus orar** corect cu zoneinfo (România implicit; ora vară/iarnă automat).

---

## Setup (mașină nouă)

```bash
cd "D:\Volume Profile"
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -e .        # face import-urile core/data/app sa mearga peste tot
```

Sau, mai simplu, rulează `setup.bat` (o singură dată).

## Rulare

Aplicația desktop:

```bash
cd "D:\Volume Profile"
.venv\Scripts\python run_desktop.py
```

Sau dublu-click pe `start.bat` (sau shortcut-ul de pe Desktop).

## Adăugare zile noi de date

Datele nu sunt în repo (regenerabile din Databento). Pui CSV-ul în `data/raw/`, apoi:

```bash
.venv\Scripts\python scripts\convert_to_parquet.py fisier.csv
```

Databento: schema **Trades** ($28/GB), Encoding=CSV, Compression=None, Price=Decimal, Symbol=Include.
Câmpul `side`: A = sell aggressor, B = buy aggressor.

## Teste

```bash
.venv\Scripts\python -m pytest -q      # 68 teste
```

Motoarele sunt verificate independent (POC/VA/HVN/LVN, delta/CVD, footprint, absorption,
exhaustion, developing, anchored VWAP, replay determinism, integrare UI).

---

## Structura proiectului

```
Volume Profile/
├── core/                       # Motoare de calcul (NU deseneaza)
│   ├── vp_engine.py            #   Volume Profile: POC, VAH/VAL, HVN/LVN
│   └── delta_engine.py         #   Delta / Order Flow
├── data/
│   ├── loader.py               #   Loader unic (CSV/Parquet, sesiune, simbol activ)
│   ├── raw/                    #   CSV-uri brute Databento  (ignorat de git)
│   └── parquet/                #   CSV convertit, 14x mai mic (ignorat de git)
├── app/desktop/                # Aplicatia desktop (PySide6 + pyqtgraph)
│   ├── main.py                 #   Fereastra principala + toate tool-urile UI
│   ├── charts.py               #   Item-uri desenate manual (lumanari, profil, footprint, grid)
│   ├── data_service.py         #   Punte core -> UI (load_day, footprint, semnale)
│   ├── replay.py               #   Replay tick-by-tick + checkpoints
│   ├── drawings.py             #   Unelte de desen (backtesting)
│   └── theme.py                #   Tema dark + culori
├── scripts/                    # CLI de analiza (VP/Delta/multi-day/visualize)
├── tests/                      # pytest (68 teste)
├── run_desktop.py              # Launcher desktop
├── start.bat / setup.bat       # Pornire / instalare rapida
├── pyproject.toml              # Pachet + pytest
└── requirements.txt            # Dependinte

Documentatie detaliata: DOCUMENTATIE.md, PACHET-COMPLET.md, INSPIRATIE-platforme.md
```

## Setări tehnice de reținut

- **tick_size** = 0.25 (NQ/MNQ)
- **Value Area** = 70% (expansiune din POC)
- **Sesiune futures** = 22:00 → 22:00 UTC (Globex)
- **RTH (NY)** = 09:30–16:00 ET = 16:30–23:00 RO
- **Contract activ**: NQU6 (ales automat după volum)
- Tot calculul (POC/VA/HVN/LVN + barele profilului) se face la **rezoluția de afișare** (row_size) —
  „ce vezi = ce se calculează".

## Stadiu & roadmap

Terminalul e complet și funcțional pentru **backtesting + învățat order flow** (68 teste trec).

- [x] Motoare de calcul + loader + Parquet + teste
- [x] Terminal desktop complet (VP, footprint, order flow, semnale, replay, desen)
- [x] Instrumente pro: Anchored VWAP, Developing POC/VA, Exhaustion, grid stats, Compare
- [ ] **Date LIVE** (Databento Standard ~$199/lună) — pasul spre tranzacționare reală
- [ ] DOM ladder (MBP-10) + Liquidity Heatmap Bookmap (MBO) — cer date noi
- [ ] Datorie tehnică: lumânări randare incrementală (acum full-redraw ~33 FPS)
