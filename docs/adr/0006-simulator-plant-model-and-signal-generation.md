---
status: accepted
---

# Simulator plant model and signal generation

The simulator published two PLC templates of Gaussian noise per production cell. It now
publishes about 55 devices and 430 signals across six families — energy, water, utilities,
asset health, production and safety — and every value is computed from one shared plant
state rather than drawn independently.

Independent noise is enough to prove a mapper writes what it receives, and that is all the
old simulator was for. It is not enough to develop against. A console showing site kW, a
cooling tower supply temperature and a line's PackML state side by side is showing three
unrelated random walks, so nothing built on top can be checked: an OEE calculation cannot be
wrong, a correlation cannot be missing, an alarm cannot be spurious, because there is no
underlying fact for any of them to disagree with. Every consumer in this platform — the
graphdb mapper's node model, the historian's Metric extraction, the frontend's Process
Visualization, the Alert Rules of ADR 0005 — is developed against this data.

So the simulator gained a model of the plant: a PackML state machine per production line
taking only legal transitions, ambient conditions per site, and a `PlantContext` that every
device reads. A compressor's load follows the air demand of the lines it serves. A cooling
tower's approach temperature is set by the wet bulb the weather station publishes. Values
move together because they are computed from the same state, which is what makes them worth
developing against.

## Considered Options

**More templates of the same kind** was rejected. Reaching 400 signals by adding 400 more
independent generators multiplies the output and adds nothing: the failure is that the values
are unrelated, and more unrelated values is more of the failure.

**Replaying a recorded plant dataset** was rejected. It would be the most realistic option
and the least usable one: a fixed recording cannot be started, stopped, held or reconfigured,
it cannot exercise a state the recording never entered, and the recording itself would be
plant data with all the handling that implies.

**A physics solver** was rejected as the wrong tool. Mass and energy balances would buy
accuracy nobody consuming this data can use, at the cost of a component whose behaviour is
harder to predict than the platform it exists to test. First-order lags and algebraic
relations between named signals are enough for every correlation the platform needs to show.

**One topic per signal** was retained rather than bundling signals into nested payloads.
Bundling would cut the message count several-fold, which is tempting given that the volume
constraint is real. It was rejected because the Metric Key in `CONTEXT.md` is the topic
segments below the Asset plus the dotted path within the payload, so bundling changes the
shape of every Metric Key in the platform — a data-model change, made to relieve a load
problem that a profile already solves.

## Consequences

Volume is now a real constraint, and it lands on Neo4j rather than Timescale: the graphdb
mapper performs `MERGE` work per topic level on every message, while the historian appends.
`full` is roughly 120 msg/s of eight-level topics. So `small` — one site, three families, all
cadences scaled by six, about 2 msg/s — is the shipped default, `full` is opt-in through
`simulator.simulation.profile`, and `test_volume.py` asserts the default stays small.

Configuration moved out of `conf/settings.yaml` into `conf/simulator/*.yaml`, read directly
rather than through Dynaconf, because `uns_config.get_settings()` hardcodes its settings
files for all nine modules and widening it for one would change config loading platform-wide.
The `simulator.plc` and `simulator.equipment.mixer_tank` keys stay supported by the loader but
are no longer declared in the shipped file, because `create_plc`'s two branches are mutually
exclusive and leaving either key in place would have the legacy generator publishing on top of
the new devices — the same topics twice from `plc:`, or eight undeclared `MixerTank`s from the
fallback. The two PLC templates are declared in `conf/simulator/production.yaml` instead, with
their equipment names, base values, variations and Units of Measure unchanged, so the topics
and payloads they produced before are the topics and payloads they produce now.

`derived` signals introduced an expression language, which is a cost. It is bounded by being
a whitelisted AST walk over arithmetic, comparisons, `ctx.*` and seven named functions, with
every rejection raised when the file loads and naming the offending construct. There is no
`eval` anywhere in it.
