# Handoff — Volume Profile Terminal (NQ)

Lipește acest text la începutul unui chat nou ca să-l aduci la zi instant.

## Ce e
Terminal desktop de **order flow / Volume Profile pentru NQ** (E-mini Nasdaq-100),
Python (PySide6 + pyqtgraph), date reale Databento. Uz personal pentru backtesting +
învățat VP/order flow, apoi (viitor) date live pentru strategia mea de New York.

## Unde e
- Proiect: **`D:\Volume Profile\`** (cwd-ul Claude Code e `D:\New folder`, dar codul e în D:\Volume Profile)
- Rulare: `cd "D:\Volume Profile"; .venv\Scripts\python.exe run_desktop.py`
- Teste: `.venv\Scripts\python.exe -m pytest -q` (**68 passed**)
- Documente: `PACHET-COMPLET.md`, `DOCUMENTATIE.md`, `INSPIRATIE-platforme.md` (în D:\Volume Profile)

## Arhitectură (regula de aur)
Motorul de calcul e **separat** de UI. `core/` (vp_engine, delta_engine — calculează, NU
desenează) → `data/` (loader unic + Parquet) → `app/desktop/` (data_service, charts, replay,
drawings, main, theme). Instalat editabil (`pip install -e .`).

## Ce e construit (complet + testat)
- **Volume Profile**: POC, Value Area (VAH/VAL), HVN/LVN (peak detection real). 5 moduri de
  perioadă în panoul ⚙: Sesiune / Zi UTC / Composite / **Visible** (pe ce vezi) / **Custom range** (tragi zona).
- **Order flow**: Delta per nivel, CVD (panou colorat verde/mov), VWAP, Cumulative Delta.
- **Footprint**: celule bid/ask, numere sell×buy la zoom, delta/lumânare, imbalance diagonal (⚙ ratio).
- **Big Trades**: bule pe trepte de mărime, hover tooltip, zone S/R (⚙ prag).
- **Absorption**: markere galbene + halo, hover cu buy/sell/delta (⚙ praguri).
- **Nivelurile de ieri**: yPOC/yVAH/yVAL + PDH/PDL (amber).
- **Replay/backtesting**: tick-by-tick, scrubber, step ±1 bar, jump la HH:MM, intră pe pauză;
  seek rapid prin checkpoints.
- **Unelte de desen**: nivel/trend/dreptunghi/fib/măsură + **Long/Short** (Entry/Stop/Target → R:R + $),
  magnet cu Ctrl.
- **Smart Layers** (checkbox Auto): LOD pe zoom (graficul se curăță singur).
- **Structura DeepCharts**: fiecare tool are panoul lui ⚙ de settings (praguri reglabile din UI).
- **Fus orar** corect cu zoneinfo (România implicit; 16:30 RO = deschidere NY).
- **Performanță**: footprint cu viewport culling (rapid inclusiv la rezoluție fină).

## Adăugat recent (10 features noi din inspirație, toate cu toggle/⚙ + teste)
- **VA box de ieri** (zonă amber) + **POC ray** proiectat spre dreapta (toggle „Ieri").
- **Session shading**: overnight umbrit, RTH (16:30–23:00 RO = NY) iese în evidență (toggle „RTH").
- **Anchored VWAP**: unealta „aV" (1 click = ancoră, ex. NY open) → VWAP teal + benzi std-dev.
- **Developing POC/VA**: trail-ul migrării valorii, se dezvoltă în replay (toggle „Dev").
- **Footprint cu bare interne bid/ask** (stil Quantower) + **3 moduri**: Bid×Ask / Volume / Delta (⚙).
- **Exhaustion**: rombi coral la climax de volum+delta pe extreme noi (~5/zi, ⚙ praguri, hover).
- **Grid statistici jos**: ΣV / ΔV / Δ% per lumânare, heatmap + numere la zoom (toggle „Grid").
- **Bară de straturi jos** (stil DeepChart): toggle-urile mutate din topbar, grupate + ⚙.
- **Session Browser + Compare**: dropdown „Compară" → suprapune profilul + nivelurile altei sesiuni
  (albastru, ancorat pe dreapta).
- **Hover pe linii**: treci cu mouse-ul peste orice linie de nivel → nume + preț (HVN/LVN/POC/…).

## Date
- **17 zile** reale (contract NQU6, tick 0.25), 4 regimuri: bearish (20-24 iul),
  range (6-10 iul), bullish (4-8 mai), + 30-31 iul. Parquet în `data/parquet/`.
- Adăugare zile noi: pui CSV în `data/raw/`, apoi `python scripts/convert_to_parquet.py fisier.csv`.

## Ce a mai rămas (opțional)
- VP: grupare **Auto**, tipuri de date (Number of Trades etc.)
- Big Trades: prag **automat** (algoritm), tipuri de marker
- Fib/Măsură editabile prin drag, salvare desene pe disc
- Time & Sales (construit odată, scos — Ali nu-l vrea ca panou lateral)
- **Milestone mare: date LIVE** (Databento Standard ~$199/lună) — pasul spre uz în tranzacționare
- Milestone: **DOM ladder** (MBP-10) + **Liquidity Heatmap** Bookmap (MBO) — cer date noi
- Datorie tehnică: lumânările încă full-redraw (~33 FPS, ok)

## Notă de lucru
Prefer pas-cu-pas, în română, cu validare pe fiecare pas. Verificare vizuală prin capturi
offscreen (win.grab().save PNG). Cer mereu corectitudine verificată independent.
