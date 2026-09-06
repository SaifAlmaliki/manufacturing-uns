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
  fromMs?: number;
  toMs?: number;
}> = ({ tag, samples, latest, fromMs, toMs }) => {
  const [mode, setMode] = useState<'graph' | 'table'>('graph');
  const inferredBoolean = samples.some((s) => s.boolean) || latest?.boolean === true;
  const isBoolean =
    tag.dataType === 'Boolean'
      ? true
      : tag.dataType === 'Double' || tag.dataType === 'Integer'
        ? false
        : inferredBoolean;
  const typeHint =
    tag.dataType || latest == null ? null : isBoolean ? 'BOOLEAN' : 'DOUBLE';
  const unit = tag.unitOfMeasure;
  const transitions = useMemo(() => booleanTransitions(samples), [samples]);
  const rows = useMemo(() => numericTableRows(samples), [samples]);

  return (
    <ConsoleCard padding="sm" className="flex h-[17rem] flex-col gap-2 overflow-hidden">
      <div className="flex shrink-0 items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">{tag.displayName}</p>
          {tag.assetDisplayName ? (
            <p className="truncate text-[11px] text-muted-foreground">{tag.assetDisplayName}</p>
          ) : null}
          <p className="break-all font-mono text-[11px] text-muted-foreground">{tag.mqttTopic}</p>
        </div>
        <div className="text-right">
          <p className="text-sm tabular-nums text-emerald-400">
            {latest ? String(latest.v) : '—'}
            {unit ? (
              <span className="ml-1 text-[10px] font-normal text-muted-foreground">{unit}</span>
            ) : null}
            {typeHint ? (
              <span className="ml-1 text-[10px] font-normal text-muted-foreground">{typeHint}</span>
            ) : null}
          </p>
          <p className="text-[11px] text-muted-foreground">{latest?.quality ?? '—'}</p>
        </div>
      </div>
      <div className="flex shrink-0 gap-1">
        <button
          type="button"
          className={`rounded px-2 py-0.5 text-[11px] ${mode === 'graph' ? 'bg-muted text-foreground' : 'text-muted-foreground'}`}
          onClick={() => setMode('graph')}
        >
          Graph
        </button>
        <button
          type="button"
          className={`rounded px-2 py-0.5 text-[11px] ${mode === 'table' ? 'bg-muted text-foreground' : 'text-muted-foreground'}`}
          onClick={() => setMode('table')}
        >
          Table
        </button>
      </div>
      <div data-testid="signal-card-body" className="min-h-0 flex-1 overflow-y-auto">
        {mode === 'graph' ? (
          <SignalChart samples={samples} mode={isBoolean ? 'step' : 'line'} fromMs={fromMs} toMs={toMs} />
        ) : isBoolean ? (
          <table className="w-full text-left text-[11px] text-foreground">
            <tbody>
              {transitions.map((row) => (
                <tr key={row.t}>
                  <td className="py-0.5 tabular-nums text-muted-foreground">{clock(row.t)}</td>
                  <td>
                    {row.from} → {row.to}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table className="w-full text-left text-[11px] text-foreground">
            <tbody>
              {rows.map((row) => (
                <tr key={row.t}>
                  <td className="py-0.5 tabular-nums text-muted-foreground">{clock(row.t)}</td>
                  <td className="tabular-nums">{row.v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </ConsoleCard>
  );
};
