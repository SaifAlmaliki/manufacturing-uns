/**
 * What the simulator is set to do, and the four things that can be changed (spec 7.2):
 * the profile, the tier intervals, the sensor families, and whether a device publishes.
 *
 * Interval fields are local state until Apply. Sending a PUT per keystroke would
 * reschedule every publish task on the way from "3" to "30" and the plant would stutter
 * while somebody typed.
 */

import React, { useEffect, useState } from 'react'
import { Check, Layers, Lock, Save } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import type { SimulatorState } from './SimulatorStatusPanel'
import { TIER_LABELS } from './SimulatorStatusPanel'
import { BtnPrimary, ConsoleCard } from '../ui/console-ui'

export const SimulatorConfigPanel: React.FC<{ simulator: SimulatorState }> = ({ simulator }) => {
  const { hasPermission } = useAuth()
  const canControl = hasPermission('simulator_control')
  const { config, status, devices, busy, offline, setProfile, setTiers, setFamilies, setDeviceEnabled } =
    simulator

  const [profileDraft, setProfileDraft] = useState('')
  const [seedDraft, setSeedDraft] = useState('')
  const [tierDrafts, setTierDrafts] = useState<Record<string, string>>({})

  // Reseed the drafts whenever the server's own view changes — after a profile switch, the
  // tier map is a different map. Keyed on the values themselves rather than a mount, so a
  // switch made in another browser tab does not leave stale numbers in these boxes.
  useEffect(() => {
    if (!config) {
      return
    }
    setProfileDraft(config.profile)
    setSeedDraft(String(config.seed))
    setTierDrafts(
      Object.fromEntries(Object.entries(config.tiers).map(([tier, seconds]) => [tier, String(seconds)])),
    )
  }, [config])

  const disabled = !canControl || busy || offline

  const applyTiers = () => {
    const intervals: Record<string, number> = {}
    for (const [tier, raw] of Object.entries(tierDrafts)) {
      const parsed = Number(raw)
      // Only what actually changed, and only what is a number. The API rejects negatives
      // itself; sending NaN would get a pydantic error naming a field the operator did not
      // touch, which is a worse message than silently skipping it.
      if (Number.isFinite(parsed) && parsed !== config?.tiers[tier]) {
        intervals[tier] = parsed
      }
    }
    if (Object.keys(intervals).length > 0) {
      void setTiers(intervals)
    }
  }

  const applyProfile = () => {
    const seed = seedDraft.trim() === '' ? undefined : Number(seedDraft)
    void setProfile(profileDraft, Number.isFinite(seed) ? seed : undefined)
  }

  return (
    <div className="flex flex-col gap-3">
      {!canControl && (
        <span className="inline-flex w-fit items-center gap-1 rounded border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-[9px] text-zinc-400">
          <Lock className="size-3 text-rose-400" />
          Read-Only Mode
        </span>
      )}

      <ConsoleCard padding="sm" className="space-y-2">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">Profile &amp; seed</div>
        {/* Said once, here: switching profiles rebuilds the plant and resets the counters. */}
        <div className="font-mono text-[10px] text-zinc-500">
          Switching the profile replaces every device and resets the published and failed counters.
          A refused switch leaves the running simulator untouched.
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[180px]">
            <label className="mb-1 block text-[10px] text-zinc-500" htmlFor="simulator-profile">
              PROFILE:
            </label>
            <select
              id="simulator-profile"
              disabled={disabled}
              value={profileDraft}
              onChange={(event) => setProfileDraft(event.target.value)}
              className="w-full rounded-xl border border-zinc-800 bg-zinc-900/80 px-2.5 py-1.5 text-sm text-[#FF7A00] focus:border-[#FF7A00]/50 focus:outline-none disabled:opacity-50"
            >
              {(config?.available_profiles ?? []).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <div className="w-28">
            <label className="mb-1 block text-[10px] text-zinc-500" htmlFor="simulator-seed">
              SEED:
            </label>
            <input
              id="simulator-seed"
              type="number"
              disabled={disabled}
              value={seedDraft}
              onChange={(event) => setSeedDraft(event.target.value)}
              className="w-full rounded-xl border border-zinc-800 bg-zinc-900/80 px-2.5 py-1.5 text-sm text-[#FF7A00] focus:border-[#FF7A00]/50 focus:outline-none disabled:opacity-50"
            />
          </div>
          <BtnPrimary
            id="simulator-apply-profile"
            disabled={disabled || profileDraft === ''}
            onClick={applyProfile}
            className="px-2.5 py-1.5 text-xs"
          >
            <Save className="size-3.5" />
            Apply profile
          </BtnPrimary>
        </div>
      </ConsoleCard>

      <ConsoleCard padding="sm" className="space-y-2">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">
          Cadence tiers — seconds between publishes
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
          {Object.keys(tierDrafts).map((tier) => (
            <div key={tier}>
              <label className="mb-1 block text-[10px] text-zinc-500" htmlFor={`simulator-tier-${tier}`}>
                {(TIER_LABELS[tier] ?? tier).toUpperCase()}:
              </label>
              <input
                id={`simulator-tier-${tier}`}
                type="number"
                min={0}
                step="0.1"
                disabled={disabled}
                value={tierDrafts[tier]}
                onChange={(event) =>
                  setTierDrafts((previous) => ({ ...previous, [tier]: event.target.value }))
                }
                className="w-full rounded-xl border border-zinc-800 bg-zinc-900/80 px-2.5 py-1.5 text-sm text-[#FF7A00] focus:border-[#FF7A00]/50 focus:outline-none disabled:opacity-50"
              />
            </div>
          ))}
        </div>
        <BtnPrimary id="simulator-apply-tiers" disabled={disabled} onClick={applyTiers} className="px-2.5 py-1.5 text-xs">
          <Check className="size-3.5" />
          Apply intervals
        </BtnPrimary>
      </ConsoleCard>

      <ConsoleCard padding="sm" className="space-y-2">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">Sensor families</div>
        <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
          {Object.entries(status?.families ?? config?.families ?? {}).map(([family, enabled]) => (
            <label
              key={family}
              className="flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-[11px] text-[#FF7A00]"
            >
              <input
                type="checkbox"
                disabled={disabled}
                checked={enabled}
                onChange={(event) => void setFamilies({ [family]: event.target.checked })}
                className="accent-[#FFC107]"
              />
              <span>{family}</span>
            </label>
          ))}
        </div>
      </ConsoleCard>

      <ConsoleCard padding="none" className="overflow-hidden">
        <div className="flex items-center gap-1.5 border-b border-zinc-800 px-3 py-2 text-[10px] uppercase tracking-wider text-zinc-500">
          <Layers className="size-3.5" />
          <span>Devices ({devices.length})</span>
        </div>
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-[9px] uppercase text-zinc-500">
              <tr className="border-b border-zinc-800">
                <th className="px-3 py-1.5 text-left">Device</th>
                <th className="px-3 py-1.5 text-left">Equipment</th>
                <th className="px-3 py-1.5 text-left">Family</th>
                <th className="px-3 py-1.5 text-left">Tier</th>
                <th className="px-3 py-1.5 text-right">Signals</th>
                <th className="px-3 py-1.5 text-right">Published</th>
                <th className="px-3 py-1.5 text-right">Enabled</th>
              </tr>
            </thead>
            <tbody className="text-[#FF7A00]">
              {devices.map((device) => (
                <tr key={device.id} className="border-b border-zinc-800/60">
                  <td className="px-3 py-1.5" title={device.topic_prefix}>{device.id}</td>
                  <td className="px-3 py-1.5 text-zinc-400">{device.equipment}</td>
                  <td className="px-3 py-1.5 text-zinc-400">{device.family}</td>
                  <td className="px-3 py-1.5 text-zinc-400">
                    {TIER_LABELS[device.tier] ?? device.tier}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{device.signal_count}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{device.publish_ok.toLocaleString()}</td>
                  <td className="px-3 py-1.5 text-right">
                    <input
                      type="checkbox"
                      aria-label={`Enable ${device.id}`}
                      disabled={disabled}
                      checked={device.enabled}
                      onChange={(event) => void setDeviceEnabled(device.id, event.target.checked)}
                      className="accent-[#FF7A00]"
                    />
                  </td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-4 text-center text-zinc-500">
                    No devices. Start the simulator, or check that a profile is loaded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </ConsoleCard>
    </div>
  )
}
