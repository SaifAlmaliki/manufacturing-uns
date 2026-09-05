import React, { useMemo, useState } from 'react';
import type { GraphqlConnectivityTag } from '../../services/graphql/types';
import {
  booleanTransitions,
  numericTableRows,
  type Sample,
} from '../../lib/condition-monitoring/series';
import { ConsoleCard } from '../ui/console-ui';
import { SignalChart } from './SignalChart';

function clock(t: number): string {
  return new Date(t).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export const SignalCard: React.FC<{
  tag: GraphqlConnectivityTag;
  samples: Sample[];
  latest: Sample | undefined;
}> = ({ tag, samples, latest }) => {
  const [mode, setMode] = useState<'graph' | 'table'>('graph');
  const isBoolean = samples.some((s) => s.boolean) || latest?.boolean === true;
  const transitions = useMemo(() => booleanTransitions(samples), [samples]);
  const rows = useMemo(() => numericTableRows(samples), [samples]);

  return (
    <ConsoleCard padding="sm" className="flex min-h-[11rem] flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-white">{tag.displayName}</p>
          <p className="break-all font-mono text-[11px] text-zinc-500">{tag.mqttTopic}</p>
        </div>
        <div className="text-right">
          <p className="text-sm tabular-nums text-emerald-400">
            {latest ? String(latest.v) : '—'}
          </p>
          <p className="text-[11px] text-zinc-500">{latest?.quality ?? '—'}</p>
        </div>
      </div>
      <div className="flex gap-1">
        <button
          type="button"
          className={`rounded px-2 py-0.5 text-[11px] ${mode === 'graph' ? 'bg-zinc-800 text-white' : 'text-zinc-500'}`}
          onClick={() => setMode('graph')}
        >
          Graph
        </button>
        <button
          type="button"
          className={`rounded px-2 py-0.5 text-[11px] ${mode === 'table' ? 'bg-zinc-800 text-white' : 'text-zinc-500'}`}
          onClick={() => setMode('table')}
        >
          Table
        </button>
      </div>
      {mode === 'graph' ? (
        <SignalChart samples={samples} mode={isBoolean ? 'step' : 'line'} />
      ) : isBoolean ? (
        <table className="w-full text-left text-[11px] text-zinc-300">
          <tbody>
            {transitions.map((row) => (
              <tr key={row.t}>
                <td className="py-0.5 tabular-nums text-zinc-500">{clock(row.t)}</td>
                <td>
                  {row.from} → {row.to}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <table className="w-full text-left text-[11px] text-zinc-300">
          <tbody>
            {rows.map((row) => (
              <tr key={row.t}>
                <td className="py-0.5 tabular-nums text-zinc-500">{clock(row.t)}</td>
                <td className="tabular-nums">{row.v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </ConsoleCard>
  );
};
