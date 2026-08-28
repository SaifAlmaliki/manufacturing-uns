import { useLocation } from 'react-router-dom'
import { Group, Panel, Separator } from 'react-resizable-panels'
import { useUnsState } from '../../app/UnsProvider'
import { ExplorePanel } from '../explore/ExplorePanel'
import { FeedPanel } from '../feed/FeedPanel'
import { PayloadPanel } from '../payload/PayloadPanel'
import { TreePanel } from '../tree/TreePanel'
import { ConsoleHeader } from './ConsoleHeader'

export function AppShell() {
  const state = useUnsState()
  const explore = useLocation().pathname.startsWith('/explore')

  return (
    <div className="flex h-full flex-col bg-console-bg text-console-text">
      <ConsoleHeader />
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
