/**
 * The shapes 99_simulator's control API returns. Mirrors the response bodies in
 * docs/superpowers/specs/2026-08-31-simulator-console-and-control-api-design.md section 5.
 *
 * Field names are the API's, snake_case included. Renaming them to camelCase here would
 * add a mapping layer whose only job is to hide where the data came from, and every
 * mismatch would surface as `undefined` in the UI instead of a compile error.
 */

export type RunState = 'stopped' | 'starting' | 'running' | 'paused'

export type RunAction = 'start' | 'pause' | 'resume' | 'stop'

export interface SimulatorHealth {
  status: string
  uptime_s: number
  git_hash: string
  version: string
}

export interface SimulatorStatus {
  run_state: RunState
  profile: string
  seed: number
  device_count: number
  signal_count: number
  uptime_s: number
  broker_connected: boolean
  msg_per_sec: Record<string, number>
  published_total: number
  failed_total: number
  /** True when the running plant no longer matches the profile files on disk. */
  overrides_active: boolean
  tiers: Record<string, number>
  families: Record<string, boolean>
  per_tier: Record<string, number>
  tick_count: number
  /** Only present on the body returned by PUT /simulator/profile. */
  counters_reset?: boolean
}

/**
 * One resolved ISA-95 location. Flat, not a tree: the API returns the rows the profile
 * expanded to, and the console groups them for display. A nested shape would have to be
 * built somewhere, and building it in Python would mean testing it twice.
 */
export interface SimulatorHierarchyRow {
  enterprise: string
  site: string
  area: string
  line: string
  cell: string
  kind: string
  nameplate_tph: number
}

export interface SimulatorDeviceTarget {
  site: string
  area: string
  line: string
  cell: string
  kind: string
}

export interface SimulatorDeviceConfig {
  id: string
  equipment: string
  family: string
  tier: string
  enabled: boolean
  topic_prefix: string
  signal_count: number
  /** Site-relative line paths this device supplies, e.g. `Production/Line1`. */
  serves: string[]
  target: SimulatorDeviceTarget
}

export interface SimulatorConfig {
  profile: string
  available_profiles: string[]
  seed: number
  tier_scale: number
  tiers: Record<string, number>
  families: Record<string, boolean>
  sites: string[]
  max_cells_per_line: number
  hierarchy: SimulatorHierarchyRow[]
  devices: SimulatorDeviceConfig[]
}

export interface PlantTankState {
  level_pct: number
  volume_m3: number
  capacity_m3: number
}

export interface PlantSnapshot {
  enterprise: string
  site: string
  mode: string
  filter_mode: string
  duty_raw_pump: string
  lead_dist_pump: string
  tanks: Record<string, PlantTankState>
  flows_m3h: Record<string, number>
  pressures_barg: Record<string, number>
}

export interface SimulatorDevice {
  id: string
  equipment: string
  topic_prefix: string
  tier: string
  family: string
  enabled: boolean
  connected: boolean
  /** Unix seconds, or null before the first publish. */
  last_publish_ts: number | null
  publish_ok: number
  publish_fail: number
  last_error: string | null
  signal_count: number
}

export interface SimulatorDeviceList {
  devices: SimulatorDevice[]
}

export interface SimulatorSignal {
  name: string
  shape: string
  /** The Unit of Measure. Named `unit` because that is the API's field name. */
  unit: string
  precision: number
  /** `[low, high]`, or null when the signal is unbounded. */
  range: [number, number] | null
  limits: Record<string, number>
  params: Record<string, unknown>
  tier: string
  param_type: string
  value: number | boolean | string | null
  /** `Normal` | `Warning` | `Alarm`, from the signal's own limit check. */
  status: string
  last_publish_ts: number | null
  /** The full ISA-95 topic this signal publishes on. Built by the API, not the browser. */
  topic: string
}

export interface SimulatorSignalList {
  device_id: string
  signals: SimulatorSignal[]
}

/** What the profile expanded to, and what it could not resolve. */
export interface SimulatorLoadReport {
  devices: number
  signals: number
  per_family: Record<string, number>
  per_tier: Record<string, number>
  serves_links: number
  unmatched_templates: string[]
  warnings: string[]
}

export interface SimulatorDeviceHealth {
  device_id: string
  client_id: string
  connected: boolean
  publish_ok: number
  publish_fail: number
  reconnects: number
  last_error: string | null
  last_publish_ts: number | null
}

export interface SimulatorDiagnostics {
  report: SimulatorLoadReport
  failing_devices: SimulatorDeviceHealth[]
  sample_topics: string[]
}

/**
 * `offline` means the request never reached the simulator; `http` means it answered and
 * refused. The console says very different things for the two, so they stay distinct:
 * "no simulator here" is a normal deployment, "your profile name is wrong" is a mistake.
 */
export interface SimulatorApiError {
  kind: 'offline' | 'http'
  status?: number
  /** Set when the API named the field it rejected. */
  field?: string
  message: string
}

export type SimulatorResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: SimulatorApiError }

export function isSimulatorFailure<T>(
  result: SimulatorResult<T>,
): result is { ok: false; error: SimulatorApiError } {
  return result.ok === false
}
