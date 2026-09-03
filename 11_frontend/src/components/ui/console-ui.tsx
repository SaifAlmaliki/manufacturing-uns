import React from 'react';

/** FlowBoard-style design tokens for console pages */
export const consoleTokens = {
  page: 'bg-[#0a0a0b] text-zinc-100',
  card: 'rounded-2xl border border-zinc-800 bg-[#111114]',
  cardMuted: 'rounded-2xl border border-zinc-800/60 bg-zinc-900/40',
  input:
    'w-full rounded-xl border border-zinc-800 bg-zinc-900/80 px-3 py-2.5 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-[#FF7A00]/50 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/30',
  label: 'text-xs font-medium text-zinc-500',
  tabActive: 'bg-[#FF7A00] text-white',
  tabInactive: 'text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200',
  btnPrimary:
    'inline-flex items-center gap-1.5 rounded-xl bg-[#FF7A00] px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#e66e00] disabled:opacity-50',
  btnSecondary:
    'inline-flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-2 text-sm font-medium text-zinc-300 transition-colors hover:border-zinc-700 hover:text-white',
  btnGhost:
    'inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium text-zinc-400 transition-colors hover:bg-zinc-800/60 hover:text-zinc-100',
  accent: '#FF7A00',
  /** Dark inputs with orange text — simulator & technical panels */
  inputOrange:
    'w-full rounded-xl border border-zinc-800 bg-zinc-900/80 px-3 py-2.5 text-sm text-[#FF7A00] placeholder:text-zinc-600 focus:border-[#FF7A00]/50 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/30',
  pane: 'flex flex-col h-full bg-[#111114] text-zinc-100',
  paneHeader: 'shrink-0 border-b border-zinc-800 p-3',
} as const;

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
}

export const PageContent: React.FC<PageContentProps> = ({ children, className = '' }) => (
  <div className={`mx-auto max-w-[1400px] space-y-4 p-4 md:p-6 ${className}`}>{children}</div>
);

interface ConsoleCardProps {
  children: React.ReactNode;
  className?: string;
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

export const ConsoleCard: React.FC<ConsoleCardProps> = ({ children, className = '', padding = 'md' }) => {
  const pad = padding === 'none' ? '' : padding === 'sm' ? 'p-3' : padding === 'lg' ? 'p-6' : 'p-5';
  return <div className={`${consoleTokens.card} ${pad} ${className}`}>{children}</div>;
};

interface PageStatProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  iconBg?: string;
  valueClassName?: string;
}

export const PageStat: React.FC<PageStatProps> = ({ label, value, icon, iconBg = 'bg-[#FF7A00]/15', valueClassName = 'text-white' }) => (
  <div className={`${consoleTokens.card} flex items-center justify-between p-4`}>
    <div>
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${valueClassName}`}>{value}</div>
    </div>
    <div className={`flex size-10 items-center justify-center rounded-xl ${iconBg}`}>{icon}</div>
  </div>
);

interface SegmentTab {
  id: string;
  label: string;
  icon?: React.FC<{ className?: string }>;
  badge?: string | number;
}

interface SegmentTabsProps {
  tabs: SegmentTab[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}

export const SegmentTabs: React.FC<SegmentTabsProps> = ({ tabs, active, onChange, className = '' }) => (
  <div className={`flex flex-wrap gap-1 rounded-xl border border-zinc-800 bg-zinc-900/60 p-1 ${className}`}>
    {tabs.map((tab) => {
      const Icon = tab.icon;
      const isActive = tab.id === active;
      return (
        <button
          key={tab.id}
          type="button"
          id={`subtab-${tab.id}`}
          onClick={() => onChange(tab.id)}
          className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
            isActive ? consoleTokens.tabActive : consoleTokens.tabInactive
          }`}
        >
          {Icon && <Icon className="size-4" />}
          <span>{tab.label}</span>
          {tab.badge !== undefined && (
            <span
              className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold tabular-nums ${
                isActive ? 'bg-white/20 text-white' : 'bg-zinc-800 text-zinc-400'
              }`}
            >
              {tab.badge}
            </span>
          )}
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
      {icon && <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[#FF7A00]/15">{icon}</div>}
      <div>
        <h2 className="text-base font-semibold text-white">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-zinc-500">{description}</p>}
      </div>
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </ConsoleCard>
);

export const ConsoleInput: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({ className = '', ...props }) => (
  <input className={`${consoleTokens.input} ${className}`} {...props} />
);

export const ConsoleSelect: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = ({ className = '', ...props }) => (
  <select className={`${consoleTokens.input} ${className}`} {...props} />
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
