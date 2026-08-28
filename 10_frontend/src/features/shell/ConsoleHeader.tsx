import { NavLink } from 'react-router-dom'
import { connectionChip, connectionLabel } from '../../app/connection'
import { useUnsState } from '../../app/UnsProvider'
import { platformConfig } from '../../lib/platform/config'

export function ConsoleHeader() {
  const state = useUnsState()
  const chip = connectionChip(state.httpOk, state.wsOk)
  return (
    <header className="flex items-center justify-between border-b border-console-border px-4 py-2">
      <div className="flex items-center gap-6">
        <div>
          <h1 className="text-base font-semibold">{platformConfig.displayName}</h1>
          <p className="text-xs text-console-muted">
            {platformConfig.organizationName} · {platformConfig.instanceName}
          </p>
        </div>
        <nav className="flex gap-2">
          <NavLink
            to="/"
            className={({ isActive }) =>
              `rounded px-2 py-1 text-sm ${isActive ? 'bg-console-panel text-console-accent' : 'text-console-muted hover:text-console-text'}`
            }
          >
            Home
          </NavLink>
          <NavLink
            to="/explore"
            className={({ isActive }) =>
              `rounded px-2 py-1 text-sm ${isActive ? 'bg-console-panel text-console-accent' : 'text-console-muted hover:text-console-text'}`
            }
          >
            Explore
          </NavLink>
        </nav>
      </div>
      <span
        className={`rounded px-2 py-0.5 text-xs ${
          chip === 'live'
            ? 'bg-console-accent/20 text-console-accent'
            : chip === 'degraded'
              ? 'bg-console-warn/20 text-console-warn'
              : 'bg-console-danger/20 text-console-danger'
        }`}
      >
        {connectionLabel(chip, state.httpOk, state.wsOk)}
      </span>
    </header>
  )
}
