import React, { useMemo, useState } from 'react';
import { downsample, type Sample } from '../../lib/condition-monitoring/series';

const WIDTH = 320;
const HEIGHT = 132;
const PAD = 4;
const DISPLAY_PAD = { l: 36, r: 10, t: 12, b: 24 };

export type ChartPad = number | { l: number; r: number; t: number; b: number };

function resolvePad(pad: ChartPad = PAD): { l: number; r: number; t: number; b: number } {
  if (typeof pad === 'number') return { l: pad, r: pad, t: pad, b: pad };
  return pad;
}

export function formatChartTime(t: number): string {
  return new Date(t).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatChartValue(v: number): string {
  if (Number.isInteger(v)) return String(v);
  return String(Math.round(v * 1000) / 1000);
}

function hoverTitle(t: number, v: number): string {
  return `${formatChartTime(t)} ${formatChartValue(v)}`;
}

function chartPoints(
  samples: Sample[],
  width: number,
  height: number,
  fromMs?: number,
  toMs?: number,
  pad: ChartPad = PAD,
): { x: number; y: number; sample: Sample }[] {
  if (samples.length === 0) return [];
  const { l, r, t, b } = resolvePad(pad);
  const xs = samples.map((s) => s.t);
  const ys = samples.map((s) => s.v);
  const minX = fromMs ?? Math.min(...xs);
  const maxX = toMs ?? Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const x = (ts: number) => l + ((ts - minX) / spanX) * (width - l - r);
  const y = (v: number) => t + (1 - (v - minY) / spanY) * (height - t - b);
  return samples.map((sample) => ({ x: x(sample.t), y: y(sample.v), sample }));
}

export function nearestChartPoint(
  pts: { x: number; y: number; sample: Sample }[],
  x: number,
): { x: number; y: number; sample: Sample } | null {
  if (pts.length === 0) return null;
  return pts.reduce((best, p) => (Math.abs(p.x - x) < Math.abs(best.x - x) ? p : best));
}

export function chartPath(
  samples: Sample[],
  width: number,
  height: number,
  mode: 'line' | 'step',
  fromMs?: number,
  toMs?: number,
  pad: ChartPad = PAD,
): string {
  const pts = chartPoints(samples, width, height, fromMs, toMs, pad);
  if (pts.length === 0) return '';
  if (mode === 'step') {
    let d = `M${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`;
    for (let i = 1; i < pts.length; i += 1) {
      d += ` H${pts[i].x.toFixed(1)} V${pts[i].y.toFixed(1)}`;
    }
    return d;
  }
  return pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(' ');
}

export const SignalChart: React.FC<{
  samples: Sample[];
  mode: 'line' | 'step';
  fromMs?: number;
  toMs?: number;
}> = ({ samples, mode, fromMs, toMs }) => {
  const drawn = useMemo(() => downsample(samples), [samples]);
  const pts = useMemo(
    () => chartPoints(drawn, WIDTH, HEIGHT, fromMs, toMs, DISPLAY_PAD),
    [drawn, fromMs, toMs],
  );
  const [hover, setHover] = useState<(typeof pts)[number] | null>(null);

  if (drawn.length === 0) {
    return <p className="py-6 text-center text-xs text-muted-foreground">No historian points in range</p>;
  }

  const ys = drawn.map((s) => s.v);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const minX = fromMs ?? drawn[0].t;
  const maxX = toMs ?? drawn[drawn.length - 1].t;
  const d = chartPath(drawn, WIDTH, HEIGHT, mode, fromMs, toMs, DISPLAY_PAD);
  const { l, r, t, b } = DISPLAY_PAD;
  const plotBottom = HEIGHT - b;
  const plotRight = WIDTH - r;
  const midY = (minY + maxY) / 2;
  const midX = (minX + maxX) / 2;

  const onMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const x = ((event.clientX - rect.left) / rect.width) * WIDTH;
    setHover(nearestChartPoint(pts, x));
  };

  return (
    <div className="relative h-full min-h-[8rem] w-full">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-full w-full"
        role="img"
        aria-label="Signal trend"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <line x1={l} y1={t} x2={plotRight} y2={t} className="stroke-border" strokeWidth="1" />
        <line x1={l} y1={(t + plotBottom) / 2} x2={plotRight} y2={(t + plotBottom) / 2} className="stroke-border" strokeWidth="1" />
        <line x1={l} y1={plotBottom} x2={plotRight} y2={plotBottom} className="stroke-border" strokeWidth="1" />
        <line x1={l} y1={t} x2={l} y2={plotBottom} className="stroke-border" strokeWidth="1" />
        <text data-testid="chart-y-max" x={l - 4} y={t + 3} textAnchor="end" className="fill-muted-foreground" fontSize="8">
          {formatChartValue(maxY)}
        </text>
        {minY !== maxY ? (
          <text x={l - 4} y={(t + plotBottom) / 2 + 3} textAnchor="end" className="fill-muted-foreground" fontSize="8">
            {formatChartValue(midY)}
          </text>
        ) : null}
        <text data-testid="chart-y-min" x={l - 4} y={plotBottom + 3} textAnchor="end" className="fill-muted-foreground" fontSize="8">
          {formatChartValue(minY)}
        </text>
        <text data-testid="chart-x-start" x={l} y={HEIGHT - 6} textAnchor="start" className="fill-muted-foreground" fontSize="8">
          {formatChartTime(minX)}
        </text>
        {minX !== maxX ? (
          <text x={(l + plotRight) / 2} y={HEIGHT - 6} textAnchor="middle" className="fill-muted-foreground" fontSize="8">
            {formatChartTime(midX)}
          </text>
        ) : null}
        <text data-testid="chart-x-end" x={plotRight} y={HEIGHT - 6} textAnchor="end" className="fill-muted-foreground" fontSize="8">
          {formatChartTime(maxX)}
        </text>
        <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-[#FF7A00]" />
        {hover ? (
          <>
            <line
              x1={hover.x}
              y1={t}
              x2={hover.x}
              y2={plotBottom}
              className="stroke-[#FF7A00]/50"
              strokeWidth="1"
              strokeDasharray="2 2"
            />
            <circle cx={hover.x} cy={hover.y} r={3.5} fill="#FF7A00" />
          </>
        ) : null}
        {pts.map((p, i) => (
          <circle
            key={`${p.sample.t}-${i}`}
            cx={p.x}
            cy={p.y}
            r={8}
            fill="transparent"
            aria-label={hoverTitle(p.sample.t, p.sample.v)}
          >
            <title>{hoverTitle(p.sample.t, p.sample.v)}</title>
          </circle>
        ))}
      </svg>
      {hover ? (
        <div
          role="status"
          className="pointer-events-none absolute top-1 right-1 rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-foreground shadow-xs"
        >
          <span className="text-muted-foreground">{formatChartTime(hover.sample.t)}</span>
          <span className="ml-1.5 font-semibold text-[#FF7A00]">{formatChartValue(hover.sample.v)}</span>
        </div>
      ) : null}
    </div>
  );
};
