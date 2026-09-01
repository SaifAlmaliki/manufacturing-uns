/**
 * What the simulator is set to do, and the four things that can be changed (spec 7.2):
 * the profile, the tier intervals, the sensor families, and whether a device publishes.
 *
 * Interval fields are local state until Apply. Sending a PUT per keystroke would
 * reschedule every publish task on the way from "3" to "30" and the plant would stutter
 * while somebody typed.
 */

import React, { useEffect, useState } from 'react'
import { Check, Layers, Lock, Save, Sliders } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import type { SimulatorState } from './SimulatorStatusPanel'
import { TIER_LABELS } from './SimulatorStatusPanel'

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
    <div className="p-3 md:p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs uppercase tracking-wider flex items-center gap-2">
          <Sliders className="w-4 h-4 text-amber-500 dark:text-[#FFC107]" />
          <span>Simulator Configuration</span>
        </h3>
        {!canControl && (
          <span className="px-2 py-0.5 rounded bg-[#1E293B] border border-[#334155] text-[#94A3B8] text-[9px] flex items-center gap-1">
            <Lock className="w-3 h-3 text-rose-400" />
            <span>Read-Only Mode</span>
          </span>
        )}
      </div>

      <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] space-y-2">
        <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider">
          Profile &amp; seed
        </div>
        {/* Said once, here: switching profiles rebuilds the plant and resets the counters. */}
        <div className="text-[10px] font-mono text-[#64748B] dark:text-[#94A3B8]">
          Switching the profile replaces every device and resets the published and failed counters.
          A refused switch leaves the running simulator untouched.
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[180px]">
            <label className="text-[#94A3B8] text-[10px] block mb-1" htmlFor="simulator-profile">
              PROFILE:
            </label>
            <select
              id="simulator-profile"
              disabled={disabled}
              value={profileDraft}
              onChange={(event) => setProfileDraft(event.target.value)}
              className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] rounded px-2.5 py-1.5 text-[#0F172A] dark:text-[#F8FAFC] text-[11px] font-mono focus:outline-none focus:border-[#FFC107] disabled:opacity-50"
            >
              {(config?.available_profiles ?? []).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <div className="w-28">
            <label className="text-[#94A3B8] text-[10px] block mb-1" htmlFor="simulator-seed">
              SEED:
            </label>
            <input
              id="simulator-seed"
              type="number"
              disabled={disabled}
              value={seedDraft}
              onChange={(event) => setSeedDraft(event.target.value)}
              className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] rounded px-2.5 py-1.5 text-[#0F172A] dark:text-[#F8FAFC] text-[11px] font-mono tabular-nums focus:outline-none focus:border-[#FFC107] disabled:opacity-50"
            />
          </div>
          <button
            id="simulator-apply-profile"
            disabled={disabled || profileDraft === ''}
            onClick={applyProfile}
            className="px-2.5 py-1.5 rounded border font-mono text-[10px] font-bold flex items-center gap-1.5 bg-amber-500 dark:bg-[#FFC107] border-amber-500 dark:border-[#FFC107] text-slate-950 dark:text-[#0B0B0C] hover:brightness-110 cursor-pointer disabled:bg-[#1E293B] disabled:border-[#334155] disabled:text-[#94A3B8] disabled:cursor-not-allowed"
          >
            <Save className="w-3 h-3" />
            <span>Apply profile</span>
          </button>
        </div>
      </div>

      <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] space-y-2">
        <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider">
          Cadence tiers — seconds between publishes
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
          {Object.keys(tierDrafts).map((tier) => (
            <div key={tier}>
              <label className="text-[#94A3B8] text-[10px] block mb-1" htmlFor={`simulator-tier-${tier}`}>
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
                className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] rounded px-2.5 py-1.5 text-[#0F172A] dark:text-[#F8FAFC] text-[11px] font-mono tabular-nums focus:outline-none focus:border-[#FFC107] disabled:opacity-50"
              />
            </div>
          ))}
        </div>
        <button
          id="simulator-apply-tiers"
          disabled={disabled}
          onClick={applyTiers}
          className="px-2.5 py-1.5 rounded border font-mono text-[10px] font-bold flex items-center gap-1.5 bg-amber-500 dark:bg-[#FFC107] border-amber-500 dark:border-[#FFC107] text-slate-950 dark:text-[#0B0B0C] hover:brightness-110 cursor-pointer disabled:bg-[#1E293B] disabled:border-[#334155] disabled:text-[#94A3B8] disabled:cursor-not-allowed"
        >
          <Check className="w-3 h-3" />
          <span>Apply intervals</span>
        </button>
      </div>

      <div className="p-3 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] space-y-2">
        <div className="text-[10px] text-[#64748B] uppercase font-mono tracking-wider">
          Sensor families
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-1.5">
          {Object.entries(status?.families ?? config?.families ?? {}).map(([family, enabled]) => (
            <label
              key={family}
              className="flex items-center gap-2 px-2 py-1.5 rounded bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] font-mono text-[11px] text-[#0F172A] dark:text-[#F8FAFC] cursor-pointer"
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
      </div>

      <div className="rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] overflow-hidden">
        <div className="px-3 py-2 text-[10px] text-[#64748B] uppercase font-mono tracking-wider border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center gap-1.5">
          <Layers className="w-3.5 h-3.5" />
          <span>Devices ({devices.length})</span>
        </div>
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-[#64748B] dark:text-[#94A3B8] text-[9px] uppercase">
              <tr className="border-b border-[#E2E8F0] dark:border-[#1E293B]">
                <th className="text-left px-3 py-1.5">Device</th>
                <th className="text-left px-3 py-1.5">Equipment</th>
                <th className="text-left px-3 py-1.5">Family</th>
                <th className="text-left px-3 py-1.5">Tier</th>
                <th className="text-right px-3 py-1.5">Signals</th>
                <th className="text-right px-3 py-1.5">Published</th>
                <th className="text-right px-3 py-1.5">Enabled</th>
              </tr>
            </thead>
            <tbody className="text-[#0F172A] dark:text-[#F8FAFC]">
              {devices.map((device) => (
                <tr key={device.id} className="border-b border-[#E2E8F0]/60 dark:border-[#1E293B]/60">
                  <td className="px-3 py-1.5" title={device.topic_prefix}>{device.id}</td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">{device.equipment}</td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">{device.family}</td>
                  <td className="px-3 py-1.5 text-[#64748B] dark:text-[#94A3B8]">
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
                      className="accent-[#FFC107]"
                    />
                  </td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-4 text-center text-[#64748B]">
                    No devices. Start the simulator, or check that a profile is loaded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
