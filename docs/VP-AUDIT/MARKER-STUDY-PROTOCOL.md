# MARKER STUDY PROTOCOL — Order Flow Markers (Big / Absorption / Exhaustion / Acc-Rej)

**Scop:** să afli, cinstit, **care dintre markerele de order flow de pe chart chiar te ajută** să
tranzacționezi mai bine — și care sunt tapet. Complementar cu `REPLAY-STUDY-PROTOCOL.md` (ăla e
pentru panoul **Context**; ăsta e pentru **markerele** din bara ORDER FLOW).

**Ce s-a schimbat (Aug 2026, sesiunea de audit detectori):**
- Detectorii sunt **verificați corecți** (fac provabil ce spun — vezi `scripts/verify_detectors.py`).
- **Exhaustion recalibrat pe 1min**: prag absolut `min_vol=400` + `vol_mult` 3.5→2.0. Înainte: 0
  detecții pe sesiunea NY, toate overnight (multe = zgomot). Acum: ~5/zi, inclusiv climax-uri RTH reale.
- **Filtru nou „Doar RTH"** în bara ORDER FLOW: arată markerele DOAR în sesiunea ta (09:30-16:00 ET).

**Durată realistă:** ~20-30 min/sesiune × ~8-10 sesiuni. 2-3 pe zi, nu mai mult (oboseala strică observația).

---

## REGULA DE AUR (fără ea, studiul nu valorează nimic)

> **COMMIT ÎNAINTE DE REVEAL.**
> Când apare un marker: **pauză**, scrii ce te aștepți să urmeze (+ încredere), și ABIA APOI avansezi.

Replay-ul e cauzal exact ca să te forțeze să te angajezi înainte să vezi viitorul. Dacă te uiți întâi
la ce a făcut prețul, o să raționalizezi orice și o să crezi că markerul e genial.

---

## AVANTAJ NOU: „cheia de răspuns" înainte de studiu

Înainte să studiezi o zi în replay, rulează harness-ul pe ea:

```
.venv\Scripts\python.exe scripts/verify_detectors.py 20260817 --interval 1min --bars 10
```

Îți dă, pentru ziua aia: **fiecare** marker (oră RO, preț, numerele care l-au declanșat), în ce
sesiune (RTH/overnight) și **ce a făcut prețul după** (follow-through în direcția așteptată). Asta e
referința obiectivă. **NU te uita la ea înainte de commit** — o folosești DUPĂ, ca să compari
citirea ta live cu ce s-a întâmplat de fapt, și ca să numeri obiectiv per tip de marker.

---

## SETUP (o dată)

```
cd "D:\Volume Profile"
.venv\Scripts\python.exe run_desktop.py
```

- **Rezoluție:** `1min` (timeframe-ul tău de scalping; acolo se aplică recalibrarea).
- **View / straturi:** bifează **Big Trades, Absorption, Exhaustion, Acc/Rej** în bara ORDER FLOW.
  Bifează și **„Doar RTH"** ca să vezi numai markerele din sesiunea ta (mai puțin zgomot overnight).
- **Footprint** ON dacă vrei să vezi buy/sell per nivel când inspectezi un marker. `row_size`=2.0, VA=70%.
- **Hover pe marker** → cardul cu detalii (tip, volum, delta, preț). Dacă nu apare cardul: vezi
  diagnosticul de hover (mișcă mouse-ul — se mișcă crucea? dacă nu, e problemă de platformă).

---

## CE E UN „MOMENT NOTABIL"

Pune pauză și logează DOAR când:
- **Apare un marker** (triunghi Absorption / romb Exhaustion / inel Acc-Rej / bulă Big Trade),
  **mai ales la un nivel** (POC / VAH / VAL / nivel de ieri / HVN-LVN).
- Un **cluster** de markere (ex. mai multe big trades pe aceeași parte + absorption).

Țintă: **~5-10 momente/sesiune**. Ignoră markerele izolate în mijloc de range fără context.

---

## BUCLA LA FIECARE MARKER (30 secunde)

1. **Pauză** la bara markerului. Notează: ora (RO), tipul (big/abs/exh/react) + kind (bull/bear/top/
   bot/rej-up…), prețul, **la ce nivel** a apărut.
2. **Hover** pe marker → citește numerele (volum, delta, buy/sell). Are sens povestea? (ex. absorption
   bull = sell mare la minim, absorbit, close sus).
3. **COMMIT (înainte de reveal):** ce aștepți? **U** (sus) / **D** (jos) / **R** (rotație) / **?** +
   **încredere 1-3**. Markerul ăsta ți-ar schimba/confirma un trade? (`Sharper` / `No-change` / `Misled`).
4. **Avansează** ~5 bare (≈5 min), apoi ~10 bare (≈10 min). Notează: net ticks + cât s-a dus în
   favoarea/împotriva ta (MFE/MAE, la ochi).
5. **Verdict:** `Helped` / `Neutral` / `Misled`.

Completează în `marker-study-log.csv` (o linie/marker).

---

## SESIUNI RECOMANDATE (regimuri diferite, date recente cu markere)

| # | Sesiune | Regim (de verificat) |
|---|---------|----------------------|
| 1 | `2026-08-17` | activă, are toate tipurile (referință: harness deja rulat) |
| 2 | `2026-08-18` | zi separată, multe acc/rej |
| 3 | `2026-08-19` | overnight activ |
| 4 | `2026-08-20` | — |
| 5 | `2026-08-21` | — |
| 6 | `2026-08-04` | TREND ↑ amplu |
| 7 | `2026-07-30` | TREND ↑ curat |
| 8 | `2026-07-28` | RANGE pur (testul greu) |

Rulează harness-ul pe fiecare înainte, ca să ai referința.

---

## LA FINALUL CELOR ~8-10 SESIUNI — CONCLUZIA (aici e câștigul)

Agregă din log, **per tip de marker**, câte Helped / Neutral / Misled:

| Tipar | Decizie |
|-------|---------|
| Majoritar **Helped**, rar Misled | **KEEP + trust** — chiar te ajută |
| Majoritar **Neutral** | **HIDE/deprioritizează** — nu adaugă la ce vezi oricum |
| Des **Misled** | **INVESTIGATE** — recalibrăm sau scoatem |

Întrebări meta (răspunde explicit):
- **Care marker s-a dovedit cel mai util?** Care e tapet?
- **Exhaustion** (după recalibrare) — pe RTH îți zice ceva util, sau tot rar/irelevant? (era 0 pe RTH)
- **Acc/Rej** — reacțiile la VAH/VAL te ajută, sau prea multe/prea slabe? (bănuială: VA developing
  subțire = reacții slabe; „Doar RTH" ajută?)
- **Absorption** — la niveluri chiar prinde respingeri reale?
- **Big Trades** — bulele mari coincid cu momente de decizie, sau sunt doar zgomot de lichiditate?

**Output final:** listă scurtă `keep / hide / investigate` per marker. Aia decide cum curățăm UI-ul și
ce (dacă ceva) merită recalibrat mai departe — din datele tale, nu din presupuneri.

---

*Însoțit de `marker-study-log.csv` (log de completat, o linie per marker).*
