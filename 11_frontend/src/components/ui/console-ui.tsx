import React from 'react';
import { NavLink } from 'react-router-dom';
import { Search } from 'lucide-react';
import { cn } from '../../lib/utils';

/** Shared console tokens — surfaces follow theme; orange brand stays fixed. */
export const consoleTokens = {
  page: 'bg-background text-foreground',
  card: 'rounded-md border border-border bg-surface',
  cardMuted: 'rounded-md border border-border bg-muted/40',
  input:
    'w-full rounded-md border border-border bg-background px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:border-[#FF7A00]/50 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/30',
  /** Compact native select — no py-2.5, or the selected value clips inside h-7. */
  select:
    'h-7 w-full min-w-0 rounded-md border border-border bg-background px-1.5 py-0 text-[11px] leading-tight text-foreground focus:border-[#FF7A00]/50 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/30 disabled:cursor-not-allowed disabled:opacity-50',
  label: 'text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground',
  tabActive: 'bg-[#FF7A00] text-[#140800]',
  tabInactive: 'text-muted-foreground hover:bg-muted hover:text-foreground',
  btnPrimary:
    'inline-flex items-center gap-1.5 rounded-md bg-[#FF7A00] px-4 py-2 text-sm font-semibold text-[#140800] transition-colors hover:bg-[#e66e00] disabled:opacity-50',
  btnSecondary:
    'inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted',
  btnGhost:
    'inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
  accent: '#FF7A00',
  inputOrange:
    'w-full rounded-md border border-border bg-background px-3 py-2.5 text-sm text-[#FF7A00] placeholder:text-muted-foreground focus:border-[#FF7A00]/50 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/30',
  pane: 'flex flex-col h-full bg-surface text-foreground',
  paneHeader: 'shrink-0 border-b border-border p-3',
} as const;

export function QualityLamp({ status }: { status: string }) {
  const tone = status === 'Good' ? 'good' : status === 'Bad' ? 'bad' : 'unknown';
  return (
    <span className={`quality-lamp quality-lamp-${tone}`}>
      <span className="quality-lamp-dot" />
      {status}
    </span>
  );
}

export function ConsoleDialog({
  children,
  onClose,
  ariaLabel,
  className = '',
  overlayClassName = '',
}: {
  children: React.ReactNode;
  onClose: () => void;
  ariaLabel: string;
  className?: string;
  overlayClassName?: string;
}) {
  return (
    <div className={`instrument-overlay ${overlayClassName}`} onClick={onClose}>
      <div
        role="dialog"
        aria-label={ariaLabel}
        className={`instrument-panel instrument-grain ${className}`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

interface PageShellProps {
  children: React.ReactNode;
  scroll?: boolean;
  id?: string;
  className?: string;
}

export const PageShell: React.FC<PageShellProps> = ({ children, scroll = true, id, className = '' }) => (
  <div
    id={id}
    className={`flex-1 ${scroll ? 'overflow-y-auto' : 'overflow-hidden flex flex-col'} ${consoleTokens.page} ${className}`}
  >
    {children}
  </div>
);

interface PageContentProps {
  children: React.ReactNode;
  className?: string;
  /** Drop the 1400px cap — use on data-heavy pages like alarms and historian. */
  fullWidth?: boolean;
}

export const PageContent: React.FC<PageContentProps> = ({ children, className = '', fullWidth = false }) => (
  <div
    className={`space-y-3 p-3 md:p-4 lg:px-6 ${fullWidth ? 'w-full max-w-none' : 'mx-auto max-w-[1400px]'} ${className}`}
  >
    {children}
  </div>
);

interface ConsoleCardProps {
  children: React.ReactNode;
  className?: string;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  id?: string;
}

export const ConsoleCard: React.FC<ConsoleCardProps> = ({ children, className = '', padding = 'md', id }) => {
  const pad = padding === 'none' ? '' : padding === 'sm' ? 'p-3' : padding === 'lg' ? 'p-6' : 'p-5';
  return <div id={id} className={`${consoleTokens.card} ${pad} ${className}`}>{children}</div>;
};

interface PageStatProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  iconBg?: string;
  valueClassName?: string;
  compact?: boolean;
}

export const PageStat: React.FC<PageStatProps> = ({
  label,
  value,
  icon,
  iconBg = 'bg-[#FF7A00]/15',
  valueClassName = 'text-foreground',
  compact = false,
}) => {
  if (compact) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-2.5 py-1.5">
        <div className={`flex size-7 shrink-0 items-center justify-center rounded-md ${iconBg}`}>{icon}</div>
        <div className="min-w-0">
          <div className="text-[10px] leading-none text-muted-foreground">{label}</div>
          <div className={`text-sm font-semibold tabular-nums leading-tight ${valueClassName}`}>{value}</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`${consoleTokens.card} flex items-center justify-between p-4`}>
      <div>
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className={`mt-1 text-xl font-semibold tabular-nums ${valueClassName}`}>{value}</div>
      </div>
      <div className={`flex size-10 items-center justify-center rounded-md ${iconBg}`}>{icon}</div>
    </div>
  );
};

interface SegmentTab {
  id: string;
  label: string;
  icon?: React.FC<{ className?: string }>;
  badge?: string | number;
  /** When set, tab navigates via router instead of onChange. */
  href?: string;
}

interface SegmentTabsProps {
  tabs: SegmentTab[];
  active: string;
  onChange?: (id: string) => void;
  className?: string;
}

function segmentTabClass(isActive: boolean) {
  return `flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
    isActive ? consoleTokens.tabActive : consoleTokens.tabInactive
  }`;
}

export const SegmentTabs: React.FC<SegmentTabsProps> = ({ tabs, active, onChange, className = '' }) => (
  <div className={`flex flex-wrap gap-1 rounded-md border border-border bg-muted/60 p-1 ${className}`}>
    {tabs.map((tab) => {
      const Icon = tab.icon;
      const badge =
        tab.badge !== undefined ? (
          <span
            className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold tabular-nums ${
              tab.id === active ? 'bg-black/15 text-[#140800]' : 'bg-background text-muted-foreground'
            }`}
          >
            {tab.badge}
          </span>
        ) : null;

      if (tab.href) {
        return (
          <NavLink
            key={tab.id}
            to={tab.href}
            id={`subtab-${tab.id}`}
            className={({ isActive }) => segmentTabClass(isActive)}
          >
            {Icon && <Icon className="size-4" />}
            <span>{tab.label}</span>
            {badge}
          </NavLink>
        );
      }

      return (
        <button
          key={tab.id}
          type="button"
          id={`subtab-${tab.id}`}
          onClick={() => onChange?.(tab.id)}
          className={segmentTabClass(tab.id === active)}
        >
          {Icon && <Icon className="size-4" />}
          <span>{tab.label}</span>
          {badge}
        </button>
      );
    })}
  </div>
);

interface PageToolbarProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
}

export const PageToolbar: React.FC<PageToolbarProps> = ({ title, description, icon, actions }) => (
  <ConsoleCard className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
    <div className="flex items-start gap-3">
      {icon && <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-[#FF7A00]/15">{icon}</div>}
      <div>
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
      </div>
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </ConsoleCard>
);

export const ConsoleInput: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({ className = '', ...props }) => (
  <input className={`${consoleTokens.input} ${className}`} {...props} />
);

export const ConsoleSelect: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = ({ className = '', ...props }) => (
  <select className={`${consoleTokens.select} ${className}`} {...props} />
);

export const BtnPrimary: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement>> = ({
  className = '',
  children,
  ...props
}) => (
  <button type="button" className={`${consoleTokens.btnPrimary} ${className}`} {...props}>
    {children}
  </button>
);

export const BtnSecondary: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement>> = ({
  className = '',
  children,
  ...props
}) => (
  <button type="button" className={`${consoleTokens.btnSecondary} ${className}`} {...props}>
    {children}
  </button>
);

export const BtnGhost: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement>> = ({
  className = '',
  children,
  ...props
}) => (
  <button type="button" className={`${consoleTokens.btnGhost} ${className}`} {...props}>
    {children}
  </button>
);

/** One horizontal row: compact KPI chips on the left, page actions on the right. */
export const CompactKpiRow: React.FC<{
  children: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}> = ({ children, actions, className = '' }) => (
  <div className={`flex flex-wrap items-center justify-between gap-2 ${className}`}>
    <div className="flex flex-wrap items-center gap-2">{children}</div>
    {actions ? <div className="flex flex-wrap items-center gap-1.5">{actions}</div> : null}
  </div>
);

export type FilterToolbarTab = { id: string; label: string; href?: string };

export type FilterToolbarSelect = {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  'aria-label'?: string;
};

/**
 * Single-row filter bar: optional tabs, search, selects, and trailing actions.
 * Do not wrap tabs and search in separate cards — they belong in this one bar.
 */
export const FilterToolbar: React.FC<{
  tabs?: { items: FilterToolbarTab[]; active: string; onChange?: (id: string) => void };
  search?: { value: string; onChange: (value: string) => void; placeholder?: string };
  selects?: FilterToolbarSelect[];
  trailing?: React.ReactNode;
  className?: string;
}> = ({ tabs, search, selects, trailing, className = '' }) => (
  <div
    className={cn(
      'flex flex-nowrap items-center gap-1 overflow-x-auto rounded-md border border-border bg-muted/60 p-1',
      className,
    )}
  >
    {tabs?.items.map((tab) => {
      const tabClass = `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
        tabs.active === tab.id ? consoleTokens.tabActive : consoleTokens.tabInactive
      }`;
      if (tab.href) {
        return (
          <NavLink key={tab.id} to={tab.href} className={tabClass}>
            {tab.label}
          </NavLink>
        );
      }
      return (
        <button
          key={tab.id}
          type="button"
          onClick={() => tabs.onChange?.(tab.id)}
          className={tabClass}
        >
          {tab.label}
        </button>
      );
    })}
    {(tabs?.items.length ?? 0) > 0 && (search || selects?.length || trailing) ? (
      <div className="mx-0.5 hidden h-7 w-px shrink-0 bg-border sm:block" aria-hidden />
    ) : null}
    {search ? (
      <div className="relative min-w-[8rem] w-40 shrink px-0.5">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          type="search"
          value={search.value}
          onChange={(e) => search.onChange(e.target.value)}
          placeholder={search.placeholder ?? 'Search…'}
          className="w-full rounded-lg border-0 bg-background py-1.5 pl-7 pr-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/40"
        />
      </div>
    ) : null}
    {selects?.map((select, index) => (
      <select
        key={select['aria-label'] ?? `filter-select-${index}`}
        value={select.value}
        onChange={(e) => select.onChange(e.target.value)}
        aria-label={select['aria-label']}
        className="shrink-0 rounded-lg border-0 bg-background px-1.5 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/40"
      >
        {select.options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    ))}
    {trailing}
  </div>
);
