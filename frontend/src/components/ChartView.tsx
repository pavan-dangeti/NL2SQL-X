import { useId, useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell as PieCell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatCompact, humanize } from "../lib/format";
import type { Cell } from "../lib/types";

const PALETTE = ["#6366f1", "#06b6d4", "#f59e0b", "#10b981", "#ec4899", "#8b5cf6", "#ef4444", "#84cc16"];

export type PlotType = "line" | "area" | "bar" | "pie";

interface Props {
  type: PlotType;
  x: string;
  measures: string[];
  columns: string[];
  rows: Cell[][];
  height?: number;
  compact?: boolean;
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

const axis = { stroke: "var(--ink-3)", fontSize: 12, tickLine: false, axisLine: false } as const;
const tooltip = {
  contentStyle: {
    background: "var(--panel)",
    border: "1px solid var(--line)",
    borderRadius: 10,
    fontSize: 12,
    color: "var(--ink)",
    boxShadow: "0 8px 24px rgb(0 0 0 / 0.18)",
  },
  labelStyle: { color: "var(--ink-2)", marginBottom: 4 },
  formatter: (v: unknown) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(v)),
};

export default function ChartView({ type, x, measures, columns, rows, height = 380, compact = false }: Props) {
  const data = useMemo(() => {
    const xi = columns.indexOf(x);
    return rows.map((row) => {
      const point: Record<string, Cell> = {};
      columns.forEach((c, i) => {
        point[c] = row[i];
      });
      point[x] = row[xi] === null ? "(empty)" : row[xi];
      return point;
    });
  }, [columns, rows, x]);

  const longLabels = type === "bar" && data.some((d) => String(d[x]).length > 14);
  const legend = measures.length > 1 && !compact;
  const margin = { top: 8, right: 12, left: 0, bottom: 0 };
  const yAxis = <YAxis {...axis} tickFormatter={formatCompact} width={52} />;
  const grid = <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" vertical={false} />;
  const keyed = (i: number) => PALETTE[i % PALETTE.length];
  const gradient = `g${useId().replace(/[^a-zA-Z0-9]/g, "")}`;

  return (
    <div style={{ height }} className="w-full" data-testid={`chart-${type}`}>
      <ResponsiveContainer width="100%" height="100%">
        {type === "line" ? (
          <LineChart data={data} margin={margin}>
            {grid}
            <XAxis dataKey={x} {...axis} minTickGap={24} />
            {yAxis}
            <Tooltip {...tooltip} />
            {legend && <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />}
            {measures.map((m, i) => (
              <Line key={m} type="monotone" dataKey={m} name={humanize(m)} stroke={keyed(i)} strokeWidth={2.5} dot={!compact && data.length <= 31} activeDot={{ r: 5 }} isAnimationActive={!compact} />
            ))}
          </LineChart>
        ) : type === "area" ? (
          <AreaChart data={data} margin={margin}>
            <defs>
              {measures.map((m, i) => (
                <linearGradient key={m} id={`${gradient}-${i}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={keyed(i)} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={keyed(i)} stopOpacity={0.02} />
                </linearGradient>
              ))}
            </defs>
            {grid}
            <XAxis dataKey={x} {...axis} minTickGap={24} />
            {yAxis}
            <Tooltip {...tooltip} />
            {legend && <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />}
            {measures.map((m, i) => (
              <Area key={m} type="monotone" dataKey={m} name={humanize(m)} stroke={keyed(i)} strokeWidth={2.5} fill={`url(#${gradient}-${i})`} isAnimationActive={!compact} />
            ))}
          </AreaChart>
        ) : type === "bar" ? (
          <BarChart data={data} layout={longLabels ? "vertical" : "horizontal"} margin={margin}>
            <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" horizontal={!longLabels} vertical={longLabels} />
            {longLabels ? (
              <>
                <XAxis type="number" {...axis} tickFormatter={formatCompact} />
                <YAxis type="category" dataKey={x} {...axis} width={compact ? 130 : 180} interval={0} tickFormatter={(v: string) => truncate(String(v), compact ? 18 : 26)} />
              </>
            ) : (
              <>
                <XAxis dataKey={x} {...axis} interval="preserveStartEnd" />
                {yAxis}
              </>
            )}
            <Tooltip {...tooltip} cursor={{ fill: "var(--panel-2)" }} />
            {legend && <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />}
            {measures.map((m, i) => (
              <Bar key={m} dataKey={m} name={humanize(m)} fill={keyed(i)} radius={longLabels ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={44} isAnimationActive={!compact} />
            ))}
          </BarChart>
        ) : (
          <PieChart>
            <Tooltip {...tooltip} />
            <Legend verticalAlign="bottom" iconType="circle" wrapperStyle={{ fontSize: compact ? 11 : 12 }} />
            <Pie data={data} dataKey={measures[0]} nameKey={x} innerRadius="55%" outerRadius="80%" paddingAngle={2} stroke="var(--panel)" isAnimationActive={!compact}>
              {data.map((_, i) => (
                <PieCell key={i} fill={keyed(i)} />
              ))}
            </Pie>
          </PieChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
