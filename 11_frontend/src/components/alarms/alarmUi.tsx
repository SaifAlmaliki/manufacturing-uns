import React from 'react';
import { ActiveAlarm, AlarmSeverity } from '../../types/alarm';
import { ConsoleCard } from '../ui/console-ui';

export function getSeverityBadge(sev: AlarmSeverity) {
  switch (sev) {
    case 'CRITICAL':
      return 'bg-rose-500/20 text-rose-300 border-rose-500/50';
    case 'HIGH':
      return 'bg-amber-500/20 text-amber-300 border-amber-500/50';
    case 'WARNING':
      return 'bg-yellow-500/20 text-yellow-300 border-yellow-500/50';
    case 'INFO':
      return 'bg-sky-500/20 text-sky-300 border-sky-500/50';
  }
}

export function getStatusBadge(status: ActiveAlarm['status']) {
  switch (status) {
    case 'ACTIVE_UNACK':
      return 'bg-rose-950/60 text-rose-400 border-rose-700/60 animate-pulse';
    case 'ACTIVE_ACK':
      return 'bg-amber-950/60 text-amber-400 border-amber-700/60';
    case 'CLEARED_UNACK':
      return 'bg-sky-950/60 text-sky-400 border-sky-700/60';
    case 'RESOLVED':
      return 'bg-emerald-950/60 text-emerald-400 border-emerald-700/60';
  }
}

export function AlarmPanel({
  icon,
  title,
  description,
  variant = 'default',
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  variant?: 'default' | 'offline' | 'success';
}) {
  const variantClass =
    variant === 'offline'
      ? 'border-rose-500/30 bg-rose-500/5'
      : variant === 'success'
        ? 'border-emerald-500/20 bg-emerald-500/5'
        : '';

  return (
    <ConsoleCard
      padding="lg"
      className={`flex min-h-[min(420px,calc(100dvh-12rem))] w-full flex-col items-center justify-center gap-3 text-center ${variantClass}`}
    >
      {icon}
      <div className="max-w-2xl space-y-2">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <p className="text-sm text-zinc-400 text-pretty">{description}</p>
      </div>
    </ConsoleCard>
  );
}

export type AlarmOutletContext = {
  onOpenCreateRule: () => void;
  onOpenEditRule: (rule: import('../../types/alarm').AlertRule) => void;
  onAcknowledge: (alarm: import('../../types/alarm').ActiveAlarm) => void;
  onResolve: (alarm: import('../../types/alarm').ActiveAlarm) => void;
};
