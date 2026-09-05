import { useEffect, useId, useRef, useState } from 'react';
import { Plus } from 'lucide-react';
import { BtnSecondary } from '../ui/console-ui';
import { AssetLevelIcon } from './AssetLevelIcon';
import {
  LEAF_TITLE,
  addDescription,
  levelDef,
  remainingChildren,
  type NodeLevel,
} from './hierarchyLevels';

export function NewAssetMenu({
  parentLevel,
  onPick,
}: {
  parentLevel: NodeLevel;
  onPick: (target: NodeLevel) => void;
}) {
  const items = remainingChildren(parentLevel);
  const disabled = items.length === 0;
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <BtnSecondary
        type="button"
        disabled={disabled}
        title={disabled ? LEAF_TITLE : undefined}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <Plus className="size-3.5" aria-hidden="true" />
        New
      </BtnSecondary>
      {open && !disabled ? (
        <ul
          id={menuId}
          role="menu"
          className="absolute right-0 z-20 mt-1 min-w-[18rem] rounded-md border border-zinc-800 bg-zinc-950 py-1 shadow-lg"
        >
          {items.map((target) => (
            <li key={target} role="none">
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm text-zinc-200 hover:bg-zinc-800/80"
                onClick={() => {
                  setOpen(false);
                  onPick(target);
                }}
              >
                <AssetLevelIcon level={target} className="mt-0.5 size-3.5 shrink-0 text-zinc-400" />
                <span>
                  <span className="font-medium text-zinc-100">{levelDef(target).label}</span>
                  <span className="mt-0.5 block text-[11px] leading-snug text-zinc-500">
                    {addDescription(parentLevel, target)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
