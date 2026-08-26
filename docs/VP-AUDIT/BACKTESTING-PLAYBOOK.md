# BACKTESTING PLAYBOOK — cum faci backtesting CORECT pe platforma ta

> Metodologia „ca la carte" pentru un trader discreționar de Volume Profile + order flow,
> potrivită pe tool-ul tău. Însoțește `REPLAY-STUDY-PROTOCOL.md` (mecanica studiului).
> Îl ții deschis lângă platformă când faci replay.

---

## 0. Ce înseamnă backtesting CORECT aici (citește o dată, e fundația)

Tool-ul tău e **context, nu semnale**. Deci backtesting-ul **NU** e „câți bani făceau semnalele"
(nu există) și **NU** e optimizare de parametri. Backtesting corect aici = **două lucruri**:

1. **Îți testezi strategia TA de price action** (funcționează la NY open?) — pe date reale, cu disciplină.
2. **Descoperi ce context de order flow îți ascute deciziile** — și ce e zgomot.

**REGULA #1 (fără ea, tot e minciună): FĂRĂ HINDSIGHT.**
Nu te uiți niciodată la ce a făcut prețul și *apoi* „interpretezi". Rulezi în **replay, bară cu
bară**, și **te angajezi ÎNAINTE** să vezi viitorul (commit-before-reveal). Creierul rationalizează
orice — replay-ul cauzal e făcut special ca să te oprească.

---

## 1. Ordinea corectă de citire: LOCAȚIE → CONTEXT → TRIGGER (top-down)

Ăsta e „ca la carte". **Niciodată invers.**

1. **LOCAȚIE** (Volume Profile) — *unde suntem față de valoare?* Prima întrebare, mereu.
2. **CONTEXT** (order flow) — *ce face flow-ul AICI, la nivelul ăsta?* Order flow contează **DOAR
   la un nivel**. În mijlocul nicăieri = zgomot.
3. **TRIGGER** (price action-ul TĂU) — tool-ul nu-ți dă intrarea. Setup-ul tău declanșează;
   tool-ul ți-a spus DACĂ locația + contextul îl susțin.
4. **MANAGEMENT** — invalidarea = un nivel; ținta = următorul nivel/POC/margine VA.

> Regula de aur: „Asta face order flow-ul aici. **TU** decizi dacă setup-ul tău merită."

---

## 2. Pregătirea HĂRȚII (înainte să pornești replay-ul)

Backtesting corect începe **înainte** de prima bară. Marchezi structura — treaba de bază a Volume Profile:

- **Ieri** (toggle „Ieri"): yPOC, yVAH, yVAL, PDH/PDL. **Esențiale la NY open** (deschidem unde față de ieri?).
- **Composite 15D**: bias-ul / valoarea pe termen mediu. **NU 90D** (stricat peste rollover — vezi §8).
- **Overnight / sesiuni** (Profile Only + „Sesiuni"): high/low Globex, unde s-a construit valoarea în Asia/Londra.
- **HVN** (magneți, S/R) și **LVN** (goluri: tranzit rapid SAU respingere).
- Notează: **prețul e ABOVE / INSIDE / BELOW value?** Aproape de un nivel cheie sau în no-man's-land?

Asta e HARTA. Fără hartă, order flow-ul nu înseamnă nimic.

---

## 3. Fiecare tool: ce-ți spune și CÂND îl folosești (corect)

| Tool | Ce-ți spune | Când / cum îl folosești corect |
|------|-------------|-------------------------------|
| **Value Area location** (above/inside/below) | balanță vs dezechilibru | **PRIMA** întrebare. Inside = rotație (fade marginile spre POC). Above/Below = trend/dezechilibru (cauți continuare sau accept/reject) |
| **POC** | prețul „corect", magnet | ținta rotațiilor; unde tinde să revină |
| **VAH / VAL** | marginile valorii (70%) | fade la margini în balanță; breakout/acceptance în afară |
| **HVN** | volum mare = S/R, congestie | prețul încetinește; nu-l tranzita ușor |
| **LVN** | gol de volum | breakout prin LVN = rapid; respingere la LVN = reversal |
| **Ieri** (yPOC/yVAH/yVAL/PDH/PDL) | referințele de ieri | **NY open**: unde deschidem vs valoarea de ieri (open-drive / open-reject) |
| **Composite 15D** | bias termen mediu | contextul mare. NU 90D |
| **Profile Only / Sesiuni** | ce s-a construit peste noapte | valoarea pre-NY (Asia/Londra), high/low overnight |
| **Developing POC/VA** | cum MIGREAZĂ valoarea în sesiune | confirmă acceptarea/direcția intraday |
| **Delta / CVD** | presiunea agresivă netă | confirmă sau **divergează** față de preț |
| **CVD divergence** | preț face extremă, flow-ul nu | context de reversal **la un nivel** |
| **Absorption** | agresiune absorbită la extremă | nivel ține → context de reversal |
| **Exhaustion** | climax la o extremă nouă | trend obosit → posibil reversal |
| **Price progress** (efort vs rezultat) | agresiune fără progres = cineva apără | la nivel: cine câștigă lupta |
| **Footprint** | buy/sell per nivel + imbalances | citirea fină exact la nivelul cheie (zoom in) |
| **Tape speed** | participarea (activitatea) | HIGH = eveniment/interes; LOW = fără convingere |
| **Big trades** | print-uri mari | cine intră agresiv, unde |
| **Panoul Context** | rezumatul order flow la bară | citirea rapidă — **citește componentele + `reasons`, NU culoarea** (§8) |
| **Unelte desen (Long/Short, măsură)** | marchezi trade-ul ipotetic | entry/stop/target + R:R, ca să vezi dacă „ar fi mers" |

---

## 4. Rutina per sesiune (pas cu pas)

1. **Alege sesiunea** (din setul recomandat în protocol — trend întâi, range la final).
2. **Pregătește harta** (§2) — ÎNAINTE de replay.
3. **Replay bară cu bară** (sau în bucăți). La fiecare **punct de decizie** (prețul ajunge la un
   nivel SAU setup-ul tău se declanșează) → **PAUZĂ**.
4. **COMMIT (înainte de reveal):** scrii — locația (vs value/nivel), ce zice contextul, **iei sau
   sari trade-ul?**, direcția așteptată, încrederea 1-3. Marchezi trade-ul ipotetic cu unealta Long/Short.
5. **Avansează**, vezi ce s-a întâmplat. Notează rezultatul (cât în favoare / cât împotrivă = MFE/MAE)
   + **te-a ajutat contextul, sau te-a încurcat?**
6. **La final de sesiune:** numeri (luate/sărite, câștig/pierdere ipotetic), o propoziție de reflecție.

---

## 5. Ce notezi (jurnalul — fără el nu e backtesting)

O linie per decizie (ține-l în Excel sau în logul din protocol):

| Sesiune | Ora | Locație (vs value/nivel) | Context (order flow) | Setup-ul meu | Decizie (iau/sar) | Rezultat (MFE/MAE/net) | Regim (trend/range) | Context: ajutat/neutru/încurcat |
|---|---|---|---|---|---|---|---|---|

**Notează și trade-urile SĂRITE** — un proces bun sare trade-urile proaste. Aia e jumătate din edge.

---

## 6. Disciplina statistică (ca să nu te păcălești)

- **O sesiune nu dovedește nimic.** Ai nevoie de **multe** instanțe ale fiecărui tip de setup.
- **Separă pe REGIM** (trend vs range). Un setup care merge în range moare în trend, și invers.
- **NU tuna pragurile pe un exemplu** izolat („dacă schimb aici, semnalul apare") = curve-fitting = te minți.
- **Confluență, nu o componentă.** Din validarea ta: o singură absorbție/divergență ≈ 50% (șansă).
  Edge-ul apare la **suprapunere**: locație bună + mai multe semne de context în aceeași direcție.
- **Fii cinstit cu execuția.** Replay-ul e idealizat (fără spread real, fill perfect, fără emoție).
  Scade din așteptări.

---

## 7. Greșeli de evitat (checklist „ca la carte")

- ❌ **Hindsight** (te uiți la ce a făcut prețul, apoi „știai"). → commit-before-reveal.
- ❌ **Tool ca semnal** (verde = buy). → e context; verde ≠ long.
- ❌ **Tranzacționezi în mijlocul valorii / departe de niveluri.** → order flow contează DOAR la nivel.
- ❌ **O singură componentă** ca semnal. → confluență.
- ❌ **Ignori timeframe-ul mare** (composite/valoarea de ieri). → top-down, mereu.
- ❌ **Curve-fitting** pe praguri ca să apară semnale. → nu atinge pragurile în timpul studiului.
- ❌ **Concluzii pe eșantion mic.** → zeci de instanțe, nu 3.
- ❌ **90D composite** peste rollover (rupt). → folosește 15D.

---

## 8. De reținut despre TOOL (limitări care contează la backtest)

- **„SUPPORTIVE" (overall) e VERDE și când contextul e coerent-BEARISH** → verde ≠ bullish.
  Citește `reasons` („2 bearish"), nu culoarea.
- **Composite 90D** e incomplet peste rollover (NQM6→NQU6). Folosește **15D**.
- **Granița sesiunii (22:00 UTC)** e corectă doar pe datele tale de vară; nu adăuga date de iarnă
  până nu se rezolvă task-ul DST.
- **Absorption/exhaustion se aprind des** (~30/zi) → contează **CONFIRMED + la un nivel**, nu fiecare flag.
- **Replay = idealizat.** Bun pentru citit structură + flow, dar nu simulează execuția ta reală.

---

## 9. Planul de START (concret)

**Săptămâna 1 — DOAR CITEȘTE (fără trade-uri).** 3-4 sesiuni. Pregătești harta, rulezi replay,
și la fiecare nivel scrii ce VEZI (locație + context). Scop: înveți limbajul, îți calibrezi ochiul.
Nu marchezi trade-uri încă.

**Săptămâna 2 — ADAUGĂ setup-ul tău.** commit-before-reveal, marchezi trade-uri ipotetice (Long/Short),
completezi jurnalul. Începi să separi pe regim.

**Săptămâna 3+ — AGREGĂ.** Ce setup + ce context = edge-ul tău? În ce regim? Ce componente te-au
ajutat des (keep) vs neutru (ignoră) vs încurcat (investighează). Abia ACUM știi ce merită.

> Ține minte scopul real: nu „să găsești un semnal magic", ci **să-ți antrenezi citirea** și să afli
> ce context are valoare — înainte de date live la NY open.
