import React, { useState, useMemo } from 'react';
import { TrendingUp } from 'lucide-react';
import { HistoricEvent } from '../../types/uns';

interface HistorianTrendChartProps {
  events: HistoricEvent[];
  selectedTopic: string;
}

export const HistorianTrendChart: React.FC<HistorianTrendChartProps> = ({ events, selectedTopic }) => {
  // Extract all numeric fields from payloads
  const numericKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const ev of events) {
      if (typeof ev.payload === 'object' && ev.payload !== null) {
        for (const [k, v] of Object.entries(ev.payload)) {
          if (typeof v === 'number' || (!isNaN(Number(v)) && typeof v !== 'boolean')) {
            keys.add(k);
          }
        }
      }
    }
    return Array.from(keys);
  }, [events]);

  const [activeMetrics, setActiveMetrics] = useState<string[]>([]);
  const [hoveredPoint, setHoveredPoint] = useState<{
    time: string;
    values: Record<string, number>;
    x: number;
    y: number;
  } | null>(null);

  // Initialize active metrics when keys change
  React.useEffect(() => {
    if (numericKeys.length > 0 && activeMetrics.length === 0) {
      setActiveMetrics(numericKeys.slice(0, 3)); // pick first 3 by default
    }
  }, [numericKeys, activeMetrics.length]);

  const toggleMetric = (key: string) => {
    if (activeMetrics.includes(key)) {
      if (activeMetrics.length > 1) {
        setActiveMetrics(activeMetrics.filter((k) => k !== key));
      }
    } else {
      setActiveMetrics([...activeMetrics, key]);
    }
  };

  // Color palette for metrics in High Density theme
  const colors = [
    { stroke: '#FFC107', bg: 'bg-[#FFC107]', text: 'text-[#FFC107]' }, // Amber
    { stroke: '#10B981', bg: 'bg-[#10B981]', text: 'text-[#10B981]' }, // Emerald
    { stroke: '#38BDF8', bg: 'bg-[#38BDF8]', text: 'text-[#38BDF8]' }, // Cyan
    { stroke: '#A855F7', bg: 'bg-[#A855F7]', text: 'text-[#A855F7]' }, // Purple
    { stroke: '#F43F5E', bg: 'bg-[#F43F5E]', text: 'text-[#F43F5E]' }, // Rose
    { stroke: '#3B82F6', bg: 'bg-[#3B82F6]', text: 'text-[#3B82F6]' }, // Blue
  ];

  // Parse time series points
  const parsedData = useMemo(() => {
    if (events.length === 0) return [];

    return events.map((ev) => {
      const vals: Record<string, number> = {};
      if (typeof ev.payload === 'object' && ev.payload !== null) {
        for (const k of numericKeys) {
          const raw = (ev.payload as Record<string, unknown>)[k];
          if (typeof raw === 'number') vals[k] = raw;
          else if (!isNaN(Number(raw))) vals[k] = Number(raw);
        }
      }
      return {
        timestamp: ev.timestamp,
        timeMs: new Date(ev.timestamp).getTime(),
        values: vals,
      };
    });
  }, [events, numericKeys]);

  // Compute scale boundaries
  const chartBounds = useMemo(() => {
    if (parsedData.length === 0 || activeMetrics.length === 0) {
      return { minVal: 0, maxVal: 100, minTime: 0, maxTime: 1 };
    }

    let minVal = Infinity;
    let maxVal = -Infinity;

    for (const d of parsedData) {
      for (const m of activeMetrics) {
        const v = d.values[m];
        if (v !== undefined) {
          if (v < minVal) minVal = v;
          if (v > maxVal) maxVal = v;
        }
      }
    }

    if (minVal === Infinity) {
      minVal = 0;
      maxVal = 100;
    }
    if (minVal === maxVal) {
      minVal -= 5;
      maxVal += 5;
    }

    // Add 8% padding
    const padding = (maxVal - minVal) * 0.08 || 1;
    minVal -= padding;
    maxVal += padding;

    const minTime = parsedData[0].timeMs;
    const maxTime = parsedData[parsedData.length - 1].timeMs || minTime + 1;

    return { minVal, maxVal, minTime, maxTime };
  }, [parsedData, activeMetrics]);

  // SVG dimensions
  const svgWidth = 800;
  const svgHeight = 220;
  const margin = { top: 15, right: 20, bottom: 25, left: 50 };
  const innerWidth = svgWidth - margin.left - margin.right;
  const innerHeight = svgHeight - margin.top - margin.bottom;

  // Coordinate mappers
  const getX = (timeMs: number) => {
    const span = chartBounds.maxTime - chartBounds.minTime || 1;
    return margin.left + ((timeMs - chartBounds.minTime) / span) * innerWidth;
  };

  const getY = (val: number) => {
    const span = chartBounds.maxVal - chartBounds.minVal || 1;
    return margin.top + innerHeight - ((val - chartBounds.minVal) / span) * innerHeight;
  };

  // Build SVG Path strings for active metrics
  const metricPaths = useMemo(() => {
    return activeMetrics.map((m, idx) => {
      const color = colors[idx % colors.length];
      const validPoints: { x: number; y: number }[] = [];

      for (const d of parsedData) {
        const v = d.values[m];
        if (v !== undefined) {
          validPoints.push({ x: getX(d.timeMs), y: getY(v) });
        }
      }

      if (validPoints.length === 0) return { key: m, path: '', color, points: [] };

      const path = validPoints.reduce((acc, pt, i) => {
        return i === 0 ? `M ${pt.x},${pt.y}` : `${acc} L ${pt.x},${pt.y}`;
      }, '');

      return { key: m, path, color, points: validPoints };
    });
  }, [parsedData, activeMetrics, chartBounds]);

  if (events.length === 0) {
    return null;
  }

  if (numericKeys.length === 0) {
    return (
      <div className="p-4 bg-[#111114] border border-[#1E293B] rounded-lg text-center text-xs text-[#64748B] font-mono">
        No numeric fields found in loaded historian payloads to trend.
      </div>
    );
  }

  return (
    <div id="historian-trend-chart-panel" className="bg-[#111114] border border-[#1E293B] rounded-lg overflow-hidden p-4 space-y-3">
      {/* Header & Metric Toggles */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-[#1E293B]">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-[#FFC107]" />
          <span className="text-xs font-bold text-[#F8FAFC] font-mono uppercase tracking-wider">
            Numeric Telemetry Trend
          </span>
          <span className="text-[10px] text-[#64748B] font-mono">({parsedData.length} samples)</span>
        </div>

        {/* Metric Selector Chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          {numericKeys.map((key, idx) => {
            const isActive = activeMetrics.includes(key);
            const activeIdx = activeMetrics.indexOf(key);
            const color = activeIdx !== -1 ? colors[activeIdx % colors.length] : null;

            return (
              <button
                key={key}
                onClick={() => toggleMetric(key)}
                className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-all cursor-pointer ${
                  isActive
                    ? 'bg-[#1E293B] border border-[#334155] text-[#F8FAFC] shadow-sm font-semibold'
                    : 'bg-[#0B0B0C] text-[#64748B] hover:text-[#94A3B8] border border-[#1E293B]'
                }`}
              >
                {color && <span className={`w-2 h-2 rounded-full ${color.bg}`} />}
                <span>{key}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* SVG Multi-Line Chart Canvas */}
      <div className="relative w-full overflow-hidden bg-[#0B0B0C] border border-[#1E293B] rounded p-1">
        <svg
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          className="w-full h-48 select-none"
          onMouseLeave={() => setHoveredPoint(null)}
        >
          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((pct, i) => {
            const y = margin.top + innerHeight * pct;
            const val = chartBounds.maxVal - pct * (chartBounds.maxVal - chartBounds.minVal);
            return (
              <g key={i}>
                <line
                  x1={margin.left}
                  y1={y}
                  x2={margin.left + innerWidth}
                  y2={y}
                  stroke="#1E293B"
                  strokeDasharray="3 3"
                />
                <text x={margin.left - 8} y={y + 3} textAnchor="end" fill="#64748B" fontSize="9" fontFamily="monospace">
                  {val.toFixed(1)}
                </text>
              </g>
            );
          })}

          {/* Time axis labels */}
          <text x={margin.left} y={svgHeight - 6} textAnchor="start" fill="#64748B" fontSize="9" fontFamily="monospace">
            {new Date(chartBounds.minTime).toLocaleTimeString()}
          </text>
          <text
            x={margin.left + innerWidth}
            y={svgHeight - 6}
            textAnchor="end"
            fill="#64748B"
            fontSize="9"
            fontFamily="monospace"
          >
            {new Date(chartBounds.maxTime).toLocaleTimeString()}
          </text>

          {/* Lines */}
          {metricPaths.map((mp) => (
            <path
              key={mp.key}
              d={mp.path}
              fill="none"
              stroke={mp.color.stroke}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}

          {/* Interactive cursor & dots */}
          {metricPaths.map((mp) =>
            mp.points.map((pt, pIdx) => (
              <circle
                key={`${mp.key}-${pIdx}`}
                cx={pt.x}
                cy={pt.y}
                r="3"
                fill={mp.color.stroke}
                className="opacity-40 hover:opacity-100 transition-opacity cursor-pointer"
                onMouseEnter={() => {
                  setHoveredPoint({
                    time: parsedData[pIdx].timestamp,
                    values: parsedData[pIdx].values,
                    x: pt.x,
                    y: pt.y,
                  });
                }}
              />
            ))
          )}
        </svg>

        {/* Hover Tooltip Box */}
        {hoveredPoint && (
          <div
            className="absolute z-20 pointer-events-none bg-[#111114] border border-[#FFC107]/50 rounded px-2.5 py-1.5 shadow-xl font-mono text-[10px] space-y-1"
            style={{
              left: `${Math.min(hoveredPoint.x, svgWidth - 160)}px`,
              top: `${Math.max(10, hoveredPoint.y - 60)}px`,
            }}
          >
            <div className="text-[#64748B] text-[9px]">
              {new Date(hoveredPoint.time).toLocaleTimeString()}
            </div>
            {Object.entries(hoveredPoint.values).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-3">
                <span className="text-[#94A3B8]">{k}:</span>
                <span className="text-[#FFC107] font-bold">{v}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Metrics Summary Stats Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
        {activeMetrics.map((m, idx) => {
          const vals = parsedData.map((d) => d.values[m]).filter((v) => v !== undefined) as number[];
          if (vals.length === 0) return null;
          const min = Math.min(...vals);
          const max = Math.max(...vals);
          const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
          const color = colors[idx % colors.length];

          return (
            <div key={m} className="p-2 rounded bg-[#0B0B0C] border border-[#1E293B] font-mono text-[10px]">
              <div className={`font-semibold truncate flex items-center gap-1 ${color.text}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${color.bg}`} />
                <span>{m}</span>
              </div>
              <div className="flex items-center justify-between text-[#64748B] text-[9px] mt-1">
                <span>Min: <b className="text-[#F8FAFC]">{min.toFixed(1)}</b></span>
                <span>Avg: <b className="text-[#F8FAFC]">{avg.toFixed(1)}</b></span>
                <span>Max: <b className="text-[#F8FAFC]">{max.toFixed(1)}</b></span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
