import { lazy, Suspense } from "react";
import { formatCell, humanize } from "../lib/format";
import type { ChartType, QueryResult } from "../lib/types";
import type { PlotType } from "./ChartView";
import { DataTable } from "./DataTable";

const loadChart = () => import("./ChartView");
const ChartView = lazy(loadChart);

export function preloadChart(): void {
  void loadChart();
}

const PLOT_TYPES: PlotType[] = ["line", "area", "bar", "pie"];

export function plotOptions(result: QueryResult): ChartType[] {
  const { chart } = result;
  if (chart.type === "metric") return ["metric", "table"];
  if (!chart.x || !chart.y.length || result.rows.length < 2) return ["table"];
  const options: ChartType[] = ["bar", "line", "area"];
  if (result.rows.length <= 12) options.push("pie");
  return [...options, "table"];
}

interface Props {
  result: QueryResult;
  type: ChartType;
  measures: string[];
  height?: number;
  compact?: boolean;
}

export function Visual({ result, type, measures, height = 380, compact = false }: Props) {
  if (type === "metric" && result.rows.length) {
    return (
      <div className={`grid gap-3 ${compact ? "grid-cols-1" : "sm:grid-cols-2 lg:grid-cols-4"}`} data-testid="metric">
        {(measures.length ? measures : result.columns).map((y) => (
          <div key={y} className="rounded-xl border border-line bg-panel-2 p-5">
            <div className="label">{humanize(y)}</div>
            <div className={`mt-2 font-semibold tabular-nums tracking-tight ${compact ? "text-2xl" : "text-4xl"}`}>{formatCell(result.rows[0][result.columns.indexOf(y)])}</div>
          </div>
        ))}
      </div>
    );
  }
  if (PLOT_TYPES.includes(type as PlotType) && result.chart.x && measures.length) {
    return (
      <Suspense fallback={<div style={{ height }} className="animate-pulse rounded-lg bg-panel-2" />}>
        <ChartView
          type={type as PlotType}
          x={result.chart.x}
          measures={type === "pie" ? measures.slice(0, 1) : measures}
          columns={result.columns}
          rows={result.rows}
          height={height}
          compact={compact}
        />
      </Suspense>
    );
  }
  return <DataTable columns={result.columns} rows={result.rows} compact={compact} />;
}
