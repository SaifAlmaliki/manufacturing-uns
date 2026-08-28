import type { ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { Group, Panel, Separator } from 'react-resizable-panels'
import { connectionChip, connectionLabel } from '../../app/connection'
import { useUnsState } from '../../app/UnsProvider'
import { ExplorePanel } from '../explore/ExplorePanel'
import { FeedPanel } from '../feed/FeedPanel'
import { PayloadPanel } from '../payload/PayloadPanel'
import { TreePanel } from '../tree/TreePanel'

function NavItem({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `rounded px-2 py-1 text-sm ${isActive ? 'bg-console-panel text-console-accent' : 'text-console-muted hover:text-console-text'}`
      }
    >
      {children}
    </NavLink>
  )
}

export function AppShell() {
  const state = useUnsState()
  const chip = connectionChip(state.httpOk, state.wsOk)
  const explore = useLocation().pathname.startsWith('/explore')

  return (
    <div className="flex h-full flex-col bg-console-bg text-console-text">
      <header className="flex items-center justify-between border-b border-console-border px-4 py-2">
        <div className="flex items-center gap-6">
          <h1 className="text-base font-semibold">Unified Namespace</h1>
          <nav className="flex gap-2">
            <NavItem to="/">Home</NavItem>
            <NavItem to="/explore">Explore</NavItem>
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
      {state.treeBanner ? (
        <div className="border-b border-console-danger/40 bg-console-danger/10 px-4 py-2 text-sm">
          {state.treeBanner}
        </div>
      ) : null}
      <Group orientation="horizontal" className="min-h-0 flex-1">
        <Panel id="tree" defaultSize="22" minSize="12" className="min-h-0">
          <TreePanel />
        </Panel>
        <Separator className="w-1 bg-console-border" />
        <Panel id="payload" defaultSize="40" minSize="20" className="min-h-0">
          <PayloadPanel />
        </Panel>
        <Separator className="w-1 bg-console-border" />
        <Panel id="context" defaultSize="38" minSize="20" className="min-h-0">
          {explore ? <ExplorePanel /> : <FeedPanel />}
        </Panel>
      </Group>
    </div>
  )
}
