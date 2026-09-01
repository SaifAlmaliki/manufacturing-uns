/**
 * The only place in the console that talks to 99_simulator's control API.
 *
 * Reads and writes both return SimulatorResult and never throw. The simulator is optional
 * infrastructure — a production install may not run one — so "not there" is a state to
 * render, not an exception to catch. A throwing client would need a try/catch in every
 * caller, and the one that got forgotten would blank the page.
 */

import type {
  PlantSnapshot,
  RunAction,
  SimulatorApiError,
  SimulatorConfig,
  SimulatorDeviceList,
  SimulatorDiagnostics,
  SimulatorHealth,
  SimulatorResult,
  SimulatorSignalList,
  SimulatorStatus,
} from '../../types/simulator'

/** Long enough for a loaded simulator, short enough that the console does not look hung. */
const REQUEST_TIMEOUT_MS = 5000

interface FieldErrorBody {
  detail?: { field?: string; message?: string } | Array<{ loc?: unknown[]; msg?: string }> | string
}

export class SimulatorClient {
  private baseUrl: string
  private token: string | null

  /**
   * Relative by default, so the same build works behind the Vite dev proxy and behind
   * nginx in the container without knowing which one it is behind.
   */
  constructor(baseUrl = '/simulator', token: string | null = null) {
    this.baseUrl = baseUrl.replace(/\/$/, '')
    this.token = token
  }

  public setToken(token: string | null) {
    this.token = token
  }

  /**
   * Pull the field name and the message out of whichever 422 body arrived.
   *
   * There are two, and both are real: the API raises `{detail: {field, message}}` for
   * rejections its own validation found, and FastAPI raises pydantic's array form before
   * the handler ever runs. Handling only the first would show "Unprocessable Entity" for
   * exactly the mistakes a form is meant to explain.
   */
  private parseError(status: number, body: FieldErrorBody | null): SimulatorApiError {
    const detail = body?.detail

    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      return {
        kind: 'http',
        status,
        field: detail.field,
        message: detail.message || `Request refused with ${status}`,
      }
    }

    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0]
      const loc = Array.isArray(first.loc) ? first.loc : []
      return {
        kind: 'http',
        status,
        field: loc.length > 0 ? String(loc[loc.length - 1]) : undefined,
        message: first.msg || `Request refused with ${status}`,
      }
    }

    if (typeof detail === 'string') {
      return { kind: 'http', status, message: detail }
    }

    return { kind: 'http', status, message: `Request refused with ${status}` }
  }

  private async request<T>(
    path: string,
    method: 'GET' | 'POST' | 'PUT' = 'GET',
    body?: unknown,
  ): Promise<SimulatorResult<T>> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
    }
    if (this.token) {
      headers['X-Simulator-Token'] = this.token
    }

    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      })

      if (!response.ok) {
        // A 404 for a device is an error body; a 404 from a proxy with no upstream is
        // HTML. Failing to parse must not become a thrown SyntaxError.
        let parsed: FieldErrorBody | null = null
        try {
          parsed = (await response.json()) as FieldErrorBody
        } catch {
          parsed = null
        }
        return { ok: false, error: this.parseError(response.status, parsed) }
      }

      return { ok: true, data: (await response.json()) as T }
    } catch {
      // Refused, DNS failure, timeout, or a body that was not JSON. From the console's
      // point of view these are one condition: there is no simulator answering here.
      return {
        ok: false,
        error: { kind: 'offline', message: 'No simulator is answering on /simulator' },
      }
    }
  }

  public getHealth(): Promise<SimulatorResult<SimulatorHealth>> {
    return this.request<SimulatorHealth>('/health')
  }

  public getStatus(): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>('/status')
  }

  public getConfig(): Promise<SimulatorResult<SimulatorConfig>> {
    return this.request<SimulatorConfig>('/config')
  }

  public getPlant(): Promise<SimulatorResult<PlantSnapshot>> {
    return this.request<PlantSnapshot>('/plant')
  }

  public getDevices(): Promise<SimulatorResult<SimulatorDeviceList>> {
    return this.request<SimulatorDeviceList>('/devices')
  }

  public getSignals(deviceId: string): Promise<SimulatorResult<SimulatorSignalList>> {
    return this.request<SimulatorSignalList>(`/devices/${encodeURIComponent(deviceId)}/signals`)
  }

  public getDiagnostics(): Promise<SimulatorResult<SimulatorDiagnostics>> {
    return this.request<SimulatorDiagnostics>('/diagnostics')
  }

  /**
   * Every write returns the full status body, so a caller never has to guess what the
   * simulator now looks like or fire a follow-up GET to find out.
   */
  public run(action: RunAction): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>('/run', 'POST', { action })
  }

  /**
   * The body key is `profile`, not `name` — Task 7's `ProfileRequest` forbids extra fields,
   * so `{name}` would come back as a 422 about an unexpected key rather than switching
   * anything.
   */
  public setProfile(profile: string, seed?: number): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>(
      '/profile',
      'PUT',
      seed === undefined ? { profile } : { profile, seed },
    )
  }

  public setTiers(intervals: Record<string, number>): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>('/tiers', 'PUT', intervals)
  }

  public setFamilies(flags: Record<string, boolean>): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>('/families', 'PUT', flags)
  }

  public setDeviceEnabled(deviceId: string, enabled: boolean): Promise<SimulatorResult<SimulatorStatus>> {
    return this.request<SimulatorStatus>(
      `/devices/${encodeURIComponent(deviceId)}`,
      'PUT',
      { enabled },
    )
  }
}

export const simulatorClient = new SimulatorClient()

/**
 * Hand the browser the token, if this deployment configured one.
 *
 * Without this line a configured `simulator.api.token` locks the console out of its own
 * simulator: Task 6 answers 401 to every request that arrives without the header, and
 * nothing else in the console ever calls `setToken`. Vite inlines `import.meta.env` at
 * build time, exactly as `VITE_GRAPHQL_URL` is already used in `src/config/`, so an
 * unset variable leaves the token null and the unauthenticated default keeps working.
 *
 * A token that reaches the browser is readable in the bundle. That is understood and
 * accepted: spec §10 scopes this token to keeping other containers on the compose
 * network from driving the simulator, not to keeping it from the operator who is
 * already logged into the console.
 */
simulatorClient.setToken(import.meta.env.VITE_SIMULATOR_TOKEN ?? null)
