---
status: accepted
---

# OEE is computed from shift history, not streamed

Date: 2026-09-01

## Status

Accepted

## Context

The platform needed the memo's pilot success criterion: an OEE number per line that
production can act on.

The obvious shape is a stream processor. Machine state and counters already arrive on MQTT;
a subscriber could keep a running Availability, Performance and Quality per line and
publish them continuously, and the console would show a live gauge.

Three things make that the wrong shape here.

**Availability has no live value.** It is Run Time over *Loading Time*, and Loading Time is
the shift's scheduled time less its planned stops. Mid-shift, the denominator is not known:
a changeover scheduled for the last hour has not happened yet. A live gauge would either
divide by elapsed time — a different quantity that drifts toward the real one and looks
wrong all shift — or by planned time, and read 40% at 08:00 on every shift ever run.

**A stopped machine has to be asked why.** Auto-classification from a state code gets some
of the way, and the rest is a person saying "that was the gearbox". That answer arrives
minutes or hours after the stop, and `is_planned` on the reason moves the interval between
Unplanned Down and excluded time — so it changes Availability. A number that is final the
instant the shift ends is a number that cannot absorb the correction.

**Late data is normal.** An edge connector reconnects and flushes an hour of buffered
samples. Stream state has already moved past them.

## Decision

OEE is computed **after** a shift closes, from the historised `uns_metrics` rows, by a
scheduler that runs a pass every few minutes.

- A shift becomes eligible `settle_minutes` after its end, so in-flight messages have
  landed.
- Each computation records an **input fingerprint** (a row count and a max timestamp) over
  its window. For `late_window_hours` after the shift ends, a pass that finds a changed
  fingerprint recomputes and writes a new **revision**; the previous numbers move to
  `oee.shift_result_revision`. Identical fingerprint, no write.
- Correcting a downtime reason enqueues that shift in `oee.recompute_request`, which the
  same pass drains.
- A manually assigned reason (`reason_source = 'manual'`) is never overwritten by the
  engine. Recomputation reads the corrected reason and produces a different, better number.
- Results are published once per revision to `<asset path>/KPI/ShiftOee`, which is a KPI
  topic and not a measurement. Nothing subscribes to it in order to compute anything else.

Every formula lives in one pure module (`oee_calc.py`) that takes a `ShiftInputs` and
returns a `ShiftMetrics`. Nothing else does arithmetic. The dashboard reads
`oee.shift_result`; it does not re-derive OEE from samples, because a second implementation
of the formula is free to disagree with the first.

Undefined is represented as null, never zero. A shift with no Loading Time did not achieve
0% — `status` says `NO_LOADING_TIME` and the ratios are null, so a plant holiday does not
appear on the trend as a catastrophe.

## Consequences

**Good.** The number is explainable: every result has its stops, its per-product counts and
its ideal cycle times stored beside it. Recomputation is safe by construction — the same
inputs produce the same fingerprint and therefore no write — so the CLI, the queue and the
scheduler can all ask for the same range without racing. Corrections are first-class rather
than an audit-trail afterthought. The engine is a batch reader, so it can be stopped for an
hour and catch up.

**Bad.** OEE is late by `settle_minutes` plus up to one scan interval — around twenty
minutes with the defaults — and there is no live gauge to put on a wall display. A shift's
number can change after an operator sees it, which needs explaining once to every plant that
adopts it; `revision` and `oee.shift_result_revision` are what make that explanation
possible. Backfill on an empty results table walks back `backfill_days`, which on a large
history is the slowest thing the module ever does, so it is bounded and logged.

**Neutral.** Nothing here prevents adding a live *rate* signal later — units per hour is
well defined mid-shift and needs no Loading Time. That would be a new topic beside
`KPI/ShiftOee`, not a change to it.
