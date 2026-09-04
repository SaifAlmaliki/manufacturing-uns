# Simulated water treatment plant

The simulator publishes one hydraulic train at Acme Water, Site 1. Five areas on
one line (`Train1`): RawWater → Treatment → Filtration → Storage → Distribution.
Nineteen tags. The plant runs itself — MQTT is publish-only.

This file is the process narrative for operators and engineers. Device YAML lives
in `conf/simulator/`. How to run the simulator is in [README.md](README.md).

Topic shape:

`AcmeWater/Site1/<Area>/Train1/<Tag>/WTP_<Template>/<ParamType>/<Signal>`

Cell is the tag once. Equipment is the class. Do not repeat the tag as `T101/T101`.

## Five areas

**Raw water.** Inlet valve V101 and one of three duty pumps (P101–P103) fill
raw-water tank T101 (250 m³). FT101 measures outlet to treatment; PT101 is
inlet/tank pressure.

**Treatment.** Basin B101 (40 m³, 3.0 m side water depth) takes FT101 flow.
DP101 runs while the basin has outlet flow. AIT101 is a slow pH walk, not a
chemistry model.

**Filtration.** One filter F101 (8 m³ hold-up, full when in service), isolated by
V201 and V202. Forward flow to storage only when both valves are open and the
filter is in service. During backwash those valves close and the filter is out of
service.

**Storage.** Clearwell T201 (400 m³) receives filtrate.

**Distribution.** Lead VFD P201 (lag P202) and discharge valve V301 send water
out. FT201 and PT201 are the distribution meter and pressure.

Vessels start at 50 % so the plant produces data immediately, not after a
fill-from-empty.

| Vessel | Capacity | Initial level |
|---|---|---|
| T101 | 250 m³ | 50 % |
| B101 | 40 m³ | 50 % (PV metres = LevelPct × 3.0 m side water depth) |
| F101 | 8 m³ hold-up | full when in service |
| T201 | 400 m³ | 50 % |

| Stream | Nameplate |
|---|---|
| One raw-water pump (P101–P103) | 80 m³/h |
| Inlet with V101 open and one pump running | 80 m³/h |
| Distribution target (sequencer `Speed.SP`) | 70 m³/h |
| One distribution VFD at 100 % | 80 m³/h |

## Tags

Nineteen devices. B101's mixer is not a tag. F101 is one filter, not SF301/SF302.
No PID devices; distribution flow is the VFD `Speed.SP` the sequencer writes.

| Area | Cell (tag) | Equipment | Signals |
|---|---|---|---|
| RawWater | V101 | WTP_Valve | CmdOpen, CmdClose, OpenFB, CloseFB, Position, CycleCount |
| RawWater | P101, P102, P103 | WTP_MotorDOL | CmdStart, CmdStop, ResetFault, Running, Fault, RuntimeH, StartCount, Auto |
| RawWater | T101 | WTP_Level | PV (%), Capacity_m3, Volume_m3 |
| RawWater | FT101 | WTP_Flowmeter | PV (m³/h), Totalizer, Reset (constant false) |
| RawWater | PT101 | WTP_Pressure | PV (barg) |
| Treatment | B101 | WTP_Basin | PV (m), LevelPct |
| Treatment | DP101 | WTP_MotorDOL | same as P101 |
| Treatment | AIT101 | WTP_Analyzer | PV (pH) |
| Filtration | V201, V202 | WTP_Valve | same as V101 |
| Filtration | F101 | WTP_Filter | FilterRun, Backwash, InService |
| Storage | T201 | WTP_Level | same as T101 |
| Distribution | P201, P202 | WTP_VFD | RunCmd, Speed.SP, Speed.PV, ResetFault, Running, Fault, RuntimeH, StartCount |
| Distribution | FT201 | WTP_Flowmeter | same as FT101 |
| Distribution | PT201 | WTP_Pressure | PV |
| Distribution | V301 | WTP_Valve | same as V101 |

WTP_Level limits on `PV` (%): HH 95, H 85, L 20, LL 10, matching the template sheet.
WTP_Basin `PV` is level in metres; `LevelPct` is 0–100.

`param_type`:

- Analog PVs (`PV`, `Volume_m3`, `LevelPct`, `Totalizer`, `Speed.PV`, `Position`, `RuntimeH`, …): `ProcessValue`
- Sequencer mirrors (`CmdOpen`, `CmdClose`, `CmdStart`, `CmdStop`, `RunCmd`, `ResetFault`, `Auto`, `Reset`, `Speed.SP`): `Setpoint`
- Discrete status (`OpenFB`, `CloseFB`, `Running`, `Fault`, `FilterRun`, `Backwash`, `InService`): `Status`

Boolean values publish as JSON booleans. Dimensionless flags use `unit: "1"`.
There is no separate `EngUnits` signal; the payload `unit` field is the Unit of Measure.

Cadence:

| Tier | Interval | What |
|---|---|---|
| process | 5 s | PV, Position, Speed.PV, LevelPct, Volume_m3 |
| status | 30 s | Running, OpenFB, FilterRun, InService, command mirrors, Auto |
| meter | 900 s | Totalizer, RuntimeH, CycleCount, StartCount, Capacity_m3 |
| event | on change | Fault, Backwash |

One profile `wtp`, `tier_scale: 1.0`.

## Coupling

Levels, flows, and pressures follow actuator state. Tank balance is
`dV/dt = Qin − Qout` with first-order lags on flow (τ = 5 s). Tanks clamp 0–100 %.

- **V101.** Inlet to T101 is 80 m³/h if V101 is open and at least one of P101–P103
  is running and not faulted; otherwise 0. If T101 is at 100 %, inlet is 0 (level
  interlock). Close V101 and T101 stops filling.
- **Pumps.** One raw-water pump nameplate is 80 m³/h. Distribution target is
  70 m³/h (`Speed.SP` 87.5 on an 80 m³/h VFD). Speed.PV lags Speed.SP (τ = 8 s).
  FT201 is the sum of running VFD contributions when V301 is open. Stop both VFDs
  or close V301 and FT201 and PT201 fall toward residual.
- **Backwash.** Every 1800 s of Running, F101 enters Backwash for 45 s. V201/V202
  close, F101 forward flow is 0, B101 outlet is 0, and FT101 (T101 outlet) is 0 so
  B101 cannot overflow. T201 is not filled from F101.
- **LL.** T101 outlet (FT101) flows only while T101 is above LL (10 %) and the
  downstream path can take water (treatment not blocked). Pulling a tank below LL
  stops the outlet pump path that would empty it.

**Pressures.** PT101 is static head from T101 level plus a pump term if a raw pump
runs; 0.2 barg residual if idle. PT201 is T201 head plus a distribution pump term;
falls toward residual when both VFDs are stopped or V301 is closed.

**Quality.** AIT101 pH is an Ornstein–Uhlenbeck walk, mean 7.2, σ 0.08, τ 600 s,
range 6.5–8.5. While DP101 is running the mean is 7.2; while it is off the mean
drifts toward 7.6 over the same τ. No other chemistry.

## Sequencer

Mode starts at `Running` (the train is already live). The sequencer issues
commands; signals only read them.

- **Valves in Running:** V101, V201, V202, V301 open (Position 100, OpenFB true).
- **Raw pumps:** exactly one duty among P101–P103; others stopped. Rotate duty
  every 900 s in order P101 → P102 → P103 → P101. `Auto` is always true.
- **Distribution:** P201 is lead at Speed.SP = 87.5 (70 m³/h of 80 m³/h
  nameplate). P202 is lag: stopped, Speed.SP = 0, unless the lead is faulted —
  then P202 takes SP 87.5.
- **Backwash:** every 1800 s of Running, enter Backwash for 45 s. F101 Backwash
  true, InService false, V201/V202 close, T201 is not filled from F101. Then
  return to Running.
- **Faults:** each running motor/VFD has probability 1/3600 per tick of latching
  `Fault` (about once an hour). The sequencer stops that machine and starts the
  standby (next raw pump in the rotation order, or the lag VFD). `Fault` stays
  true for 120 s, then clears. `ResetFault` is true for 30 s at the moment of
  clear (one status period, not a 1 s pulse).
- **Interlocks:** do not run a pump against a closed discharge (V301 closed ⇒
  VFDs stop; V101 closed ⇒ raw pumps stop). Do not start a pump that is faulted.

Command mirrors always equal the last sequencer action (`CmdStart` true while the
sequencer wants the motor running, even if `Fault` has already dropped `Running`).

## Example topics

One per template class.

```
AcmeWater/Site1/RawWater/Train1/V101/WTP_Valve/Status/OpenFB
AcmeWater/Site1/RawWater/Train1/P101/WTP_MotorDOL/Status/Running
AcmeWater/Site1/Distribution/Train1/P201/WTP_VFD/ProcessValue/Speed.PV
AcmeWater/Site1/RawWater/Train1/T101/WTP_Level/ProcessValue/PV
AcmeWater/Site1/Treatment/Train1/B101/WTP_Basin/ProcessValue/LevelPct
AcmeWater/Site1/RawWater/Train1/FT101/WTP_Flowmeter/ProcessValue/PV
AcmeWater/Site1/RawWater/Train1/PT101/WTP_Pressure/ProcessValue/PV
AcmeWater/Site1/Treatment/Train1/AIT101/WTP_Analyzer/ProcessValue/PV
AcmeWater/Site1/Filtration/Train1/F101/WTP_Filter/Status/InService
```

## Not modelled

- **Chemistry.** AIT101 is a slow quality signal. There is no coagulation,
  residual chlorine, turbidity, or other water-chemistry solver.
- **Commands.** `CmdOpen` / `CmdStart` / `Speed.SP` / `Reset` are published
  mirrors. They do not accept MQTT or API writes.
- **Second filter.** F101 is one filter. SF301/SF302 and other poster-only
  instances are not simulated.
- **PID.** No PID201 or other loop controllers. Distribution flow is the VFD
  `Speed.SP` the sequencer writes.

Also absent: B101's mixer as a tag, T401, and a hydraulics solver beyond the
tank balance above.
