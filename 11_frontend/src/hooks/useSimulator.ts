/**
 * Live simulator state for every panel under /simulator.
 *
 * Polls GET /status and GET /plant every two seconds. The MQTT self-telemetry carries a
 * status too, but polling is what the rendered numbers come from: a request returns the
 * state as of now and fails visibly when there is nothing to ask, while a retained MQTT
 * message from a process that died an hour ago looks exactly like a current one. The
 * subscription is here for what polling cannot give — the event feed, and the retained
 * Last Will that distinguishes "gone" from "slow".
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { platformConfig } from '../lib/platform/config'
import { simulatorClient } from '../services/simulator/client'
import { unsGraphQLClient } from '../services/graphql/client'
import type {
  PlantSnapshot,
  RunAction,
  SimulatorApiError,
  SimulatorConfig,
  SimulatorDevice,
  SimulatorDiagnostics,
  SimulatorResult,
  SimulatorSignal,
  SimulatorStatus,
} from '../types/simulator'
import type { MqttMessage } from '../types/uns'

const POLL_INTERVAL_MS = 2000

/** Enough to show a trend without turning the diagnostics page into a memory leak. */
const TELEMETRY_BUFFER = 100

export interface SimulatorTelemetryEvent {
  topic: string
  /** Whatever the broker sent, unnarrowed. The feed renders it; it does not interpret it. */
  payload: MqttMessage['payload']
  receivedAt: string
}

export function useSimulator() {
  const [status, setStatus] = useState<SimulatorStatus | null>(null)
  const [plant, setPlant] = useState<PlantSnapshot | null>(null)
  const [config, setConfig] = useState<SimulatorConfig | null>(null)
  const [devices, setDevices] = useState<SimulatorDevice[]>([])
  const [diagnostics, setDiagnostics] = useState<SimulatorDiagnostics | null>(null)
  const [telemetry, setTelemetry] = useState<SimulatorTelemetryEvent[]>([])
  const [offline, setOffline] = useState(false)
  const [lastError, setLastError] = useState<SimulatorApiError | null>(null)
  const [busy, setBusy] = useState(false)

  // A ref, not state: the poller reads it and must not be restarted when it changes.
  const busyRef = useRef(false)

  const refreshStatus = useCallback(async () => {
    const result = await simulatorClient.getStatus()
    if (result.ok) {
      setStatus(result.data)
      setOffline(false)
      return
    }
    if (result.error.kind === 'offline') {
      setOffline(true)
      // The last known status is deliberately kept on screen. Blanking it would lose the
      // reason the simulator stopped, which is the one thing worth reading afterwards.
      return
    }
    setLastError(result.error)
  }, [])

  const refreshPlant = useCallback(async () => {
    const result = await simulatorClient.getPlant()
    if (result.ok) {
      setPlant(result.data)
    }
  }, [])

  const refreshConfig = useCallback(async () => {
    const result = await simulatorClient.getConfig()
    if (result.ok) {
      setConfig(result.data)
    } else if (result.error.kind !== 'offline') {
      setLastError(result.error)
    }
  }, [])

  const refreshDevices = useCallback(async () => {
    const result = await simulatorClient.getDevices()
    if (result.ok) {
      setDevices(result.data.devices)
    } else if (result.error.kind !== 'offline') {
      setLastError(result.error)
    }
  }, [])

  const refreshDiagnostics = useCallback(async () => {
    const result = await simulatorClient.getDiagnostics()
    if (result.ok) {
      setDiagnostics(result.data)
    } else if (result.error.kind !== 'offline') {
      setLastError(result.error)
    }
  }, [])

  const signals = useCallback(async (deviceId: string): Promise<SimulatorSignal[]> => {
    const result = await simulatorClient.getSignals(deviceId)
    return result.ok ? result.data.signals : []
  }, [])

  // Poll status and plant together. Two requests rather than one wider endpoint, because
  // the plant snapshot is the only body whose size grows with the profile.
  useEffect(() => {
    let cancelled = false

    const tick = async () => {
      // Skipped while a write is in flight: a poll that lands between the write and its
      // effect would paint the old run state over the new one, and the button would look
      // like it did nothing.
      if (cancelled || busyRef.current) {
        return
      }
      await Promise.all([refreshStatus(), refreshPlant()])
    }

    void tick()
    const timer = window.setInterval(() => void tick(), POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [refreshStatus, refreshPlant])

  // Load once. Configuration and inventory change only when a write changes them, and the
  // write handlers below refresh them explicitly.
  useEffect(() => {
    void refreshConfig()
    void refreshDevices()
  }, [refreshConfig, refreshDevices])

  // The Platform Observability feed. Subscribed through the existing GraphQL MQTT
  // subscription, so the console needs no second transport and no broker credentials.
  useEffect(() => {
    const prefix = `uns/platform/simulator/${platformConfig.instanceName}/#`
    return unsGraphQLClient.subscribeMqttMessages([prefix], (message) => {
      setTelemetry((previous) =>
        [
          {
            topic: message.topic,
            payload: message.payload,
            receivedAt: new Date().toISOString(),
          },
          ...previous,
        ].slice(0, TELEMETRY_BUFFER),
      )
    })
  }, [])

  /**
   * Run one write, then refresh from the write's own response.
   *
   * Every write returns the status body, so there is no window in which the screen shows
   * a state the simulator has already left.
   */
  const write = useCallback(
    async (action: () => Promise<SimulatorResult<SimulatorStatus>>, reloadConfig = false) => {
      setBusy(true)
      busyRef.current = true
      setLastError(null)
      try {
        const result = await action()
        if (result.ok) {
          setStatus(result.data)
          setOffline(false)
          if (reloadConfig) {
            await Promise.all([refreshConfig(), refreshDevices()])
          }
          return true
        }
        setLastError(result.error)
        setOffline(result.error.kind === 'offline')
        return false
      } finally {
        busyRef.current = false
        setBusy(false)
      }
    },
    [refreshConfig, refreshDevices],
  )

  const run = useCallback((action: RunAction) => write(() => simulatorClient.run(action)), [write])

  // A profile switch replaces every device, so the inventory and the hierarchy are stale
  // the moment it returns.
  const setProfile = useCallback(
    (name: string, seed?: number) => write(() => simulatorClient.setProfile(name, seed), true),
    [write],
  )

  const setTiers = useCallback(
    (intervals: Record<string, number>) => write(() => simulatorClient.setTiers(intervals)),
    [write],
  )

  const setFamilies = useCallback(
    (flags: Record<string, boolean>) => write(() => simulatorClient.setFamilies(flags), true),
    [write],
  )

  const setDeviceEnabled = useCallback(
    (deviceId: string, enabled: boolean) =>
      write(() => simulatorClient.setDeviceEnabled(deviceId, enabled), true),
    [write],
  )

  return {
    status,
    plant,
    config,
    devices,
    diagnostics,
    telemetry,
    offline,
    lastError,
    busy,
    refreshStatus,
    refreshPlant,
    refreshConfig,
    refreshDevices,
    refreshDiagnostics,
    signals,
    run,
    setProfile,
    setTiers,
    setFamilies,
    setDeviceEnabled,
  }
}
