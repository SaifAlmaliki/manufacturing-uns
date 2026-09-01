## The plant model

The simulator is not a set of independent random generators. One `PlantClock` ticks every
second and drives a `PlantContext`: per site, ambient temperature, humidity, wet bulb, wind
and barometric pressure, plus the shift and the electricity tariff period; per production
line, a PackML state machine that only ever takes legal transitions, and the production
rate, throughput, heat load and air demand that follow from it.

Devices read that context. A compressor's load follows the air demand of the lines it
`serves`; a boiler's steam flow follows their heat load, but through a first-order lag, so
it trails a line stop by minutes while the compressors react in seconds. The cooling tower
sizes its approach temperature against the wet bulb the weather station publishes — the same
number, not a second model of it — so a warm humid stretch shows up as a hotter tower supply
**and** a higher chiller kW.

That is the point of the whole design: values that move together for a reason, so a consumer
built against this data behaves like one built against a plant.

### Profiles

`conf/simulator/plant.yaml` declares the whole plant; a profile narrows it. Select one with
`simulator.simulation.profile` in `conf/settings.yaml`.

| Profile | Sites | Families | Devices | Rate |
|---|---|---|---|---|
| `small` (default) | Dormagen, first cell per line | energy, water, production | 11 | ~2 msg/s |
| `full` | Dormagen, Krefeld | all six | 55 | ~120 msg/s |

`small` is the default because the graphdb mapper performs `MERGE` work once per topic level
on **every** message, and eight-level topics at `full` rate are a heavy sustained write load
on Neo4j. The historian only appends, so it is not the constraint. `test/test_volume.py`
enforces the default: a family added to the wrong profile fails a test rather than a mapper.

A profile also carries `tier_scale`, which multiplies every cadence interval — `small` uses
6.0, so its 5 s process tier publishes every 30 s.

### Cadence tiers

Every signal belongs to a tier, and the tier decides how often it publishes. Intervals are
configurable under `simulator.simulation.tiers`.

| Tier | Interval | What is on it |
|---|---|---|
| `fast` | 1 s | vibration, motor current |
| `process` | 5 s | temperatures, pressures, flows, levels, analysers |
| `energy` | 15 s | power, power factor, per-phase voltage and current |
| `status` | 30 s | PackML state, equipment status, SIS status |
| `meter` | 900 s | cumulative kWh, m³, Nm³ and tonne registers |
| `lab` | 1800 s | LIMS sample results |
| `event` | on change | alarms, trips, detector faults |

Evaluation and publishing are separate. Every signal is evaluated on every one-second tick
regardless of tier, so a 15-minute meter register has integrated all 900 seconds rather than
sampling 900 seconds apart. The tier controls publishing only.

### Signal shapes

| Shape | Behaviour | Key parameters |
|---|---|---|
| `noise` (default) | Gaussian around `base_value` | `base_value`, `variation` |
| `constant` | A fixed value | `value` |
| `ou_walk` | Mean-reverting random walk; drifts and returns | `mean`, `sigma`, `tau` |
| `diurnal` | Sine over `period_s`, plus optional noise | `mean`, `amplitude`, `period_s`, `phase_s` |
| `sawtooth` | Fills to `high`, drains to `low`, independent rates | `low`, `high`, `fill_rate`, `drain_rate` |
| `counter` | Monotonic register; `rate` is an expression in units per second | `rate`, `initial`, `rollover` |
| `window_agg` | Rolling min/max/mean of a **sibling** over `window_s` | `source`, `window_s`, `agg` |
| `derived` | An expression over siblings and `ctx` | `expr`, `params` |
| `stepped` | A discrete: mirrored from a `ctx` path, or drawn from `choices` | `source`, `choices`, `map`, `weights`, `dwell_s` |
| `bernoulli_event` | With probability `p` per tick, emit one of `choices` | `p`, `choices` |

`derived` and `counter.rate` take arithmetic over sibling signal names, keys of the signal's
own `params`, and `ctx.*`. Permitted calls are `min`, `max`, `abs`, `round`, `clamp`, `sqrt`
and `exp`. It is a whitelisted AST walk, never `eval`: attribute access off anything but
`ctx`, subscripts, lambdas, comprehensions and imports are all rejected when the file loads,
and a reference cycle between `derived` signals is rejected the same way.

`unit` is required on every signal. A dimensionless ratio declares `unit: "1"` rather than
omitting the key, so an omission is always a mistake and never a choice.

### Adding a device

1. Pick the family file in `conf/simulator/` — or add a family name to `FAMILIES` in
   `profiles.py` and create the file.
2. Add an entry under `devices:` with `id`, `equipment`, a `target`, a `tier`, and `signals`.
   An absent `target` means every cell in a `kind: production` area.
3. If it should follow production, give it `serves: [Site/Area/Line, ...]` and read
   `ctx.served_*` in its expressions. `served_throughput_tph`, `served_heat_load` and
   `served_air_demand` are **sums** over the served lines, so divide by a `served_lines`
   parameter if the device should behave the same at a one-line site as at a two-line one.
4. Update `EXPECTED_SIGNAL_COUNT` and `EXPECTED_DEVICE_COUNT` in `test/test_conf_files.py`.
   Those tables are per template, so the suite's totals are derived from them rather than
   asserted, and a device that fails to resolve names itself in the failure.