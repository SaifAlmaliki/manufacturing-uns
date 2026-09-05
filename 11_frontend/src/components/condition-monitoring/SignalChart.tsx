import React, { useMemo } from 'react';
import { downsample, type Sample } from '../../lib/condition-monitoring/series';

const WIDTH = 320;
const HEIGHT = 96;
const PAD = 4;

function chartPoints(
  samples: Sample[],
  width: number,
  height: number,
  fromMs?: number,
  toMs?: number,
): { x: number; y: number; sample: Sample }[] {
  if (samples.length === 0) return [];
  const xs = samples.map((s) => s.t);
  const ys = samples.map((s) => s.v);
  const minX = fromMs ?? Math.min(...xs);
  const maxX = toMs ?? Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const x = (t: number) => PAD + ((t - minX) / spanX) * (width - PAD * 2);
  const y = (v: number) => HEIGHT - PAD - ((v - minY) / spanY) * (height - PAD * 2);
  return samples.map((sample) => ({ x: x(sample.t), y: y(sample.v), sample }));
}

export function chartPath(
  samples: Sample[],
  width: number,
  height: number,
  mode: 'line' | 'step',
  fromMs?: number,
  toMs?: number,
): string {
  const pts = chartPoints(samples, width, height, fromMs, toMs);
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

function hoverTitle(t: number, v: number): string {
  const time = new Date(t).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  return `${time} ${v}`;
}

export const SignalChart: React.FC<{
  samples: Sample[];
  mode: 'line' | 'step';
  fromMs?: number;
  toMs?: number;
}> = ({ samples, mode, fromMs, toMs }) => {
  const drawn = useMemo(() => downsample(samples), [samples]);
  const pts = useMemo(
    () => chartPoints(drawn, WIDTH, HEIGHT, fromMs, toMs),
    [drawn, fromMs, toMs],
  );
  if (drawn.length === 0) {
    return <p className="py-6 text-center text-xs text-zinc-500">No historian points in range</p>;
  }
  const d = chartPath(drawn, WIDTH, HEIGHT, mode, fromMs, toMs);
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-24 w-full" role="img" aria-label="Signal trend">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-[#FF7A00]" />
      {pts.map((p, i) => (
        <circle
          key={`${p.sample.t}-${i}`}
          cx={p.x}
          cy={p.y}
          r={6}
          fill="transparent"
          title={hoverTitle(p.sample.t, p.sample.v)}
        />
      ))}
    </svg>
  );
};
