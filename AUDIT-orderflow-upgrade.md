# PHASE 0 — AUDIT: Order Flow Analysis & Execution Context upgrade

> Audit-only report (no code changed during the audit). Scope: upgrade the existing NQ
> Order Flow terminal into a professional Order Flow analysis + execution-context tool
> that works alongside a discretionary Price Action strategy. This is an **upgrade**, not
> a rebuild. Date: 2026-08-07.

---

## 1. Current architecture (relevant layers)

The codebase already follows the target layering (data → engines → orchestration → UI):

```
data/loader.py              raw ticks, symbol pick, session boundary (22:00 UTC), load_many
      ↓
core/vp_engine.py           VolumeProfileEngine  (POC, VA, HVN/LVN peaks)   [computes, no draw]
core/delta_engine.py        DeltaEngine          (buy/sell per level, CVD)  [computes, no draw]
      ↓
app/desktop/data_service.py load_day() → DayData  (OHLC, VWAP, footprint, absorption,
                            exhaustion, developing POC/VA, tps, session_profiles,
                            prior_session_levels, composite via resolve_ticks)
      ↓
app/desktop/replay.py       Replay._snapshot()   (tick-by-tick, causal, checkpoints)
      ↓
app/desktop/charts.py       pure render items    |  main.py → UI, toggles, ⚙, hover
```

**Key finding:** there is no dedicated analysis/context layer. `data_service.py` mixes
data-shaping with signal detection. That is the seam where the new **Order Flow Context
Engine** attaches — between `data_service`/`replay` and the UI. Nothing needs to be torn down.

## 2. Feature-by-feature audit

| Subsystem | Current (file:func) | Reusable | Gap |
|---|---|---|---|
| Volume Profile | vp_engine `VolumeProfileEngine`; POC `compute_poc`; VA `compute_value_area` (Sierra) | yes | POC tie-break undefined (insertion order) |
| POC/VAH/VAL | `result()`; drawn as pill lines | yes | Acceptance/Rejection state missing |
| HVN/LVN | `compute_hvn_lvn_peaks` (local peaks), capped `_top_nodes` (5 HVN / 3 LVN) | engine yes, caps no | edges/width/tiers missing; full-profile off by default |
| Delta | delta_engine per-level + `cumulative_delta`; per-candle `ΔV` | raw yes | no sequence/momentum/change/accel |
| CVD | `d.cvd` cumsum; panel | yes | no slope/momentum/divergence |
| Absorption | `detect_absorption` (sell absorbed at low + close-up rejection) | good base | no price-progress ticks, no subsequent reaction, not stateful |
| Exhaustion | `detect_exhaustion` (new extreme + volume climax + trend delta) | yes | markers only; feed states |
| VWAP | developing + Anchored VWAP | yes | stays contextual (ok) |
| Developing POC/VA | `developing_levels()` cumulative, replay-safe | yes | migration state (UP/DOWN/SIDEWAYS) not classified |
| Session profiles | `session_profiles()` Asia/London/NY, `SESSION_DEFS` real(DST)/ro, editable ⚙ | strong | today only; no previous; HVN/LVN capped; one global toggle |
| Prior levels | `prior_session_levels()` yPOC/yVAH/yVAL/PDH/PDL | partial | not per intraday session; no HVN/LVN |
| Composite | `resolve_ticks` 15d/90d → `load_many` → one VP engine on all ticks | yes (already correct) | no context panel; no price-location state |
| Replay | `Replay._snapshot` bars[0..cc]; `exclude_last`; checkpoints | causal, strong | route context through snapshot, not full-day arrays |
| Tape | `tps` prints/sec per candle | yes | no contracts/sec, no acceleration, no tape+delta+progress |

## 3. LVN/HVN algorithm (answers to spec PART 14)

1. **Detection:** local peak detection (`compute_hvn_lvn_peaks`, vp_engine.py:155) — local max/min in an adaptive window + prominence vs profile mean.
2. **Restricted to Value Area?** **No.** By default restricted to the **inter-HVN range** (`lvn_within_hvn=True`). A full-profile toggle already exists (`lvn_full_profile`), off by default.
3. **Threshold (production):** `min_prominence_ratio=0.4` → HVN ≥ mean×1.4, LVN ≤ mean×0.6; window = 3% of profile width (min 3).
4. **Adaptive?** Yes — relative to profile mean + width (not fixed `volume<X`).
5. **Grouping:** `merge_gap_ticks=4` groups neighbours → one representative (extreme).
6. **LVN width:** not determined (single representative price). **Gap.**
7. **Significance vs noise:** prominence ratio + `_top_nodes` top-N cap (hides real nodes; analysis wants all + tiers).

## 4. Databento data for Tape Speed (answers to spec PART 23)

Schema = **Trades** (each row = a trade print; `ts_recv` ns, `price`, `size` contracts, `side` A/B/N).
Reliable: **trades/sec** (churn proxy), **contracts/sec = volume/sec** (throughput), **delta/sec**,
**acceleration** (change over recent bars). Not available (no MBP/MBO): order-count/sec, queue,
iceberg. Never label these "orders/sec".

## 5. Missing functionality

1. Order Flow Context Engine (whole execution-context layer).
2. Delta sequence classification + momentum/acceleration + change-vs-previous.
3. Price-progress-vs-delta as a dedicated adaptive metric (prior art: Bar Info "Efficiency").
4. Absorption enrichment (price progress ticks + subsequent reaction, stateful).
5. CVD divergence on structural swings + slope/momentum.
6. POC migration state UP/DOWN/SIDEWAYS.
7. Full-profile LVN default + LVN width/edges + HVN tiers (drop engine top-N cap).
8. LVN interaction states (rejection/acceptance/fast traversal/test).
9. Acceptance/Rejection engine around POC/VAH/VAL/VWAP/HVN/LVN/prior/composite.
10. Previous-session profiles (prev NY/London/Asia) with full HVN/LVN + last-N + per-level toggles.
11. Composite context panel + price-location state.
12. Tape contracts/sec + acceleration + tape+delta+progress readout.
13. Execution Context UI panel (compact, component-exposed, no score).

## 6. Proposed architecture

One new pure layer + extensions to two existing layers.

```
data → core engines → data_service/replay (snapshot ≤ T)
                          ↓
   core/context_engine.py  (NEW — pure, causal, deterministic)
     input : causal snapshot (bars/ticks ≤ T) + config
     output: ContextResult:
             DeltaBlock, CvdBlock, ProgressBlock, Absorption/ExhaustionState,
             PocMigration, NodeInteraction, AcceptRejectState, TapeBlock,
             overall ∈ {SUPPORTIVE, NEUTRAL, CONTRADICTING}  (transparent rules, NO score)
                          ↓
   UI (main.py): compact Execution Context panel + toggles (reads ContextResult, never recomputes)
```

- `core/vp_engine.py` — structured nodes (kind, price, low, high, width, volume, prominence, tier),
  full-profile default; keep old API for back-compat.
- `data_service.py` — `previous_session_profiles()`, return full node lists, `price_location_vs_value()`,
  contracts/sec; keep `load_day` intact.
- `replay.py` — call context engine per `_snapshot`; keep `exclude_last`.
- UI — Execution Context is text → docked QWidget panel + per-session/per-level visibility controls.

**Price Action stays separate:** the tool never assumes IFVG/CISD. Click a bar / drop an execution
marker → "Order Flow around this price/time was…", never "IFVG confirmed".

## 7. Files to change / create

**Change:** core/vp_engine.py · app/desktop/data_service.py · app/desktop/replay.py ·
app/desktop/main.py · app/desktop/theme.py.
**New:** core/context_engine.py (ContextResult + ContextEngine) · tests: test_context_engine,
test_lookahead (critical), test_price_progress, test_cvd_divergence, test_lvn_interaction,
test_acceptance_rejection, test_session_prev, test_tape_speed.

## 8. Look-ahead prevention (spec PART 27 — non-negotiable)

- Single invariant: `ContextEngine` is a pure function of bars/ticks with timestamp ≤ T; fed only
  the truncated snapshot arrays — cannot see the future.
- States needing "subsequent reaction" (acceptance/rejection, LVN interaction, absorption
  follow-through): computed for reference bar k, emitted **CONFIRMED only when T−k ≥
  confirmation_window**; otherwise **FORMING/PENDING**.
- Dedicated `test_lookahead`: engine at each T over data truncated to T must equal slicing a full-day
  run for bars ≤ T; a rejection at k must be absent at k and present only at k+window.
- Existing `detect_absorption`/`detect_exhaustion` already use `exclude_last` + backward windows.

## 9. Testing strategy

After each phase: full pytest (currently 78 green), deterministic synthetic fixtures + verify against
raw ticks, replay determinism (speed 3 vs 350), no-look-ahead invariant, session boundaries + DST
unchanged, each new metric with a hand-computed golden case.

## 10. Implementation order (approved)

1. **P1a** — structured VP nodes (edges/width/tiers) + full-profile LVN with 3 modes (Full default /
   Between HVNs / Value Area).
2. **P4-core** — context_engine skeleton + ContextResult + look-ahead harness & test.
3. **P4** — Delta → Price Progress → Absorption/Exhaustion enrichment → CVD divergence → POC migration.
4. **P1b** — LVN interaction + Acceptance/Rejection (confirmation-window pattern).
5. **P5** — Tape (contracts/s + acceleration + combined).
6. **P2 + P3** — Session context (previous sessions, toggles) + Composite context.
7. **P6** — Execution Context UI (last).

## 11. August 3 golden test case (spec PART 26)

08/03 data is already imported (NQU6, 374,996 ticks, verified, on git). Usable as the golden replay
test: replay to 16:32 shows the delta flip forming with no look-ahead; the Execution Context panel
describes delta/CVD/absorption/exhaustion/POC/progress around the BUY without naming the IFVG and
without future data. The provided sequence (−466,−42,+154,…) is per-minute → reproduce with
Interval = 1min.

## Strict non-goals

No BUY/SELL signals, no confidence %, no confluence score, no automated strategy/execution/journal,
no black-box prediction. This is an analysis tool that exposes individual observations.
