# MIGRARE PE PC NOU — Volume Profile Terminal

> Ghid complet ca să muți TOT proiectul pe un PC nou. Scris 2026-08-26.
> Repo privat: `github.com/Serin15/volume-profile-terminal`.

---

## Ce călătorește CU git (nu trebuie copiat manual)

- **Tot codul** (`core/`, `app/`, `data/loader.py`, `scripts/`, `tests/`).
- **Datele** `data/parquet/` (~219 MB, 75+ sesiuni NQ) — versionate intenționat.
- **Docs** `docs/` (VP-AUDIT complet: audit, protocoale de studiu, manual, handoff-uri).
- `requirements.txt` (inclusiv **tzdata** — obligatoriu pe Windows pt fusuri/DST/RTH).

## Ce NU e în git (copiază manual DOAR dacă vrei)

- **`.venv/`** — NU se copiază (e specific mașinii). Se recreează pe PC nou (vezi mai jos).
- **Memoria Claude Code** (opțional): `C:\Users\<tu>\.claude\projects\D--Volume-Profile\` —
  conține notițele mele persistente. Copiaz-o dacă vrei să continui cu Claude pe PC nou cu
  același context. Nefuncțională dacă proiectul stă la altă cale decât `D:\Volume Profile`.
- Build-uri PyInstaller (`build/`, `dist/`, `*.spec`) — regenerabile, ignorate de git.

---

## METODA A — prin GitHub (recomandat)

Munca a fost **pushed pe GitHub** (branch `feat/panels-arch`). Pe PC-ul nou:

```bash
# 1. Clonează (aduce cod + date + docs)
git clone https://github.com/Serin15/volume-profile-terminal.git "D:\Volume Profile"
cd "D:\Volume Profile"
git checkout feat/panels-arch

# 2. Creează venv + instalează dependințele
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 3. Rulează
.venv\Scripts\python.exe run_desktop.py
```

## METODA B — offline, prin fișierul .bundle (fără GitHub/auth)

Dacă preferi să nu depinzi de GitHub: pe Desktop e `volume-profile-FULL.bundle` (un
singur fișier cu TOT istoricul + toate branch-urile + date). Copiază-l pe stick, apoi pe PC nou:

```bash
git clone "volume-profile-FULL.bundle" "D:\Volume Profile"
cd "D:\Volume Profile"
git checkout feat/panels-arch
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python.exe run_desktop.py
```

---

## Cerințe PC nou

- **Python 3.12+** (dezvoltat pe 3.14.4). `git`. Windows (dezvoltat pe Win10).
- Spațiu: ~250 MB repo + ~300 MB venv.
- Prima pornire încarcă ultima zi (~5 sec, ~260 MB RAM).

## Verificare că merge (pe PC nou)

```bash
.venv\Scripts\python.exe -m pytest -q          # trebuie: 345 passed (~20 min, date reale)
.venv\Scripts\python.exe scripts/verify_detectors.py 20260817 --interval 1min   # harness detectori
```

---

## STAREA CURENTĂ (2026-08-26) — de unde continui

**Git:** `main` = înghețat (neatins). **`feat/panels-arch`** = branch ACTIV cu toată munca.
Ultim commit: `0c2fa5d` (verificare detectori + recalibrare exhaustion + filtru RTH).

**Făcut recent (sesiunea de audit detectori order flow):**
- Detectorii de markere (Big/Absorption/Exhaustion/Acc-Rej) **verificați corecți** pe date reale
  (`scripts/verify_detectors.py` = invarianți + jurnal cu outcome). NU erau stricați.
- **Exhaustion recalibrat pe 1min**: prag absolut `min_vol=400` + `vol_mult` 3.5→2.0 (se aprindea
  0 pe RTH, tot overnight, ~jumătate zgomot; acum ~5/zi, inclusiv climax-uri RTH reale).
- Fix: big trades cu `side='N'` (agresor necunoscut) excluse.
- Filtru nou **"Doar RTH"** în bara ORDER FLOW (markerele doar în sesiunea NY).
- Suită completă: **345 passed**.

**Deschis / next (în ordine):**
1. 🔴 **Bug hover** pe mașina lui Ali ("nu apare nimic la hover pe markere"). Cod verificat corect
   (6 teste trec) → e environmental. Diagnostic: mișcă mouse-ul — se mișcă crucea? NU = sigMouseMoved
   nu ajunge (Qt/platformă). DA = ar trebui să meargă (markerele-s OFF by default, bifează layerul).
2. 🎯 **Replay study pe markere** — `docs/VP-AUDIT/MARKER-STUDY-PROTOCOL.md` + `marker-study-log.csv`.
   Follow-through slab (40-46%) = context, nu semnal; ce ajută cu adevărat se decide pe date reale.
3. Acc/Rej — corect dar overnight-heavy (VA developing subțire noaptea); de judecat în replay study.
4. Composite 90D — decide rework/remove (din audit).

**Regula de aur:** tool de CONTEXT, zero BUY/SELL/scoring/ML. Nimic pe `main` până nu ești mulțumit.
Fiecare fază = commit separat + suită verde + STOP pentru aprobare.
