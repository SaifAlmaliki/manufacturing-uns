import { Badge } from '../../components/ui/badge'
import { isFeedHighlight } from '../../lib/uns/topics'
import type { FeedItem } from './feed-buffer'

export function FeedRow({
  item,
  selectedNamespace,
  onClick,
}: {
  item: FeedItem
  selectedNamespace: string | null
  onClick: () => void
}) {
  const highlighted = isFeedHighlight(item.topic, selectedNamespace)
  return (
    <button
      type="button"
      data-testid="feed-row"
      data-highlighted={highlighted ? 'true' : 'false'}
      className={`block w-full border-b border-console-border px-3 py-2 text-left text-xs ${
        highlighted ? 'bg-console-accent/10' : ''
      }`}
      onClick={onClick}
    >
      <div className="flex justify-between gap-2 text-console-muted">
        <span className="truncate">{item.topic}</span>
        <span>{item.timestamp}</span>
      </div>
      {item.kind === 'sparkplug' ? <Badge>Sparkplug B (binary)</Badge> : null}
      {item.kind === 'invalid-json' ? <span className="text-console-danger">invalid JSON</span> : null}
      {item.kind === 'uns' ? (
        <pre className="mt-1 truncate text-console-text">{JSON.stringify(item.preview)}</pre>
      ) : null}
    </button>
  )
}
