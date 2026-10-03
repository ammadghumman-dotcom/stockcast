"use client";

import { Area, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type ChartPoint = { date: string; actual?: number; p10?: number; p50?: number; p90?: number; band?: [number, number]; event?: string | null };

export function ForecastChart({ data, asOf }: { data: ChartPoint[]; asOf?: string | null }) {
  if (!data.length) return null;
  return (
    <div className="h-72 w-full" data-testid="forecast-chart">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} minTickGap={32} fontSize={11} />
          <YAxis fontSize={11} width={40} />
          <Tooltip
            formatter={(v: number | [number, number], name: string) =>
              Array.isArray(v) ? [`${v[0].toFixed(1)} – ${v[1].toFixed(1)}`, "p10–p90"] : [Number(v).toFixed(1), name]
            }
            labelFormatter={(l, payload) => {
              const ev = (payload?.[0]?.payload as ChartPoint | undefined)?.event;
              return ev ? `${l} · ${ev}` : String(l);
            }}
          />
          <Area type="monotone" dataKey="band" stroke="none" fill="#2563eb" fillOpacity={0.15} isAnimationActive={false} />
          <Line type="monotone" dataKey="actual" stroke="#525252" dot={false} strokeWidth={1.25} isAnimationActive={false} name="actual" />
          <Line type="monotone" dataKey="p50" stroke="#2563eb" dot={false} strokeWidth={2} isAnimationActive={false} name="forecast" />
          {asOf ? <ReferenceLine x={asOf} stroke="#a3a3a3" strokeDasharray="4 4" label={{ value: "today", fontSize: 10, fill: "#a3a3a3", position: "insideTopRight" }} /> : null}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
