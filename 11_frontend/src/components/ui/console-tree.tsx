import React from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

/** Shared plant-tree chrome used by condition monitoring and the hierarchy editor. */
export function ConsoleTreeNode({
  level,
  name,
  expandable,
  expanded,
  selected,
  onToggle,
  onRowClick,
  collapsePlaceholder,
  children,
  branch,
}: {
  level: number;
  name: string;
  expandable: boolean;
  expanded: boolean;
  selected?: boolean;
  onToggle?: () => void;
  onRowClick?: () => void;
  collapsePlaceholder?: React.ReactNode;
  children: React.ReactNode;
  branch?: React.ReactNode;
}) {
  return (
    <div className="select-none">
      <div
        style={{ paddingLeft: `${level * 14 + 8}px` }}
        onClick={onRowClick}
        className={`group flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors ${
          onRowClick ? 'cursor-pointer' : ''
        } ${
          selected
            ? 'bg-[#FF7A00]/15 text-[#FF7A00]'
            : 'text-foreground hover:bg-muted hover:text-foreground'
        }`}
      >
        {expandable ? (
          <button
            type="button"
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${name}`}
            aria-expanded={expanded}
            onClick={(event) => {
              event.stopPropagation();
              onToggle?.();
            }}
            className="rounded p-0.5 text-muted-foreground hover:text-[#FF7A00]"
          >
            {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          </button>
        ) : (
          (collapsePlaceholder ?? <span className="inline-block w-[18px] shrink-0" aria-hidden="true" />)
        )}
        {children}
      </div>
      {expandable && expanded && branch ? (
        <div className="ml-3 border-l border-border">{branch}</div>
      ) : null}
    </div>
  );
}
