import {
  AreaChart as AreaIcon,
  BarChart3,
  Code2,
  Download,
  FileJson,
  Gauge,
  ImageDown,
  LineChart as LineIcon,
  Link2,
  PieChart as PieIcon,
  Pin,
  Sparkles,
  Table2,
  TrendingUp,
  TriangleAlert,
  Wrench,
  Zap,
} from "lucide-react";
import { useRef, useState } from "react";
import { chartToPng, downloadBlob, slug } from "../lib/exportChart";
import { formatMs, humanize, toCsv } from "../lib/format";
import type { ChartType, QueryResult } from "../lib/types";
import { SqlView } from "./SqlView";
import { useToast } from "./Toaster";
import { plotOptions, Visual } from "./Visual";

type ViewId = ChartType | "sql";

const VIEW_META: Record<ViewId, { label: string; icon: typeof Table2 }> = {
  bar: { label: "Bar", icon: BarChart3 },
  line: { label: "Line", icon: LineIcon },
  area: { label: "Area", icon: AreaIcon },
  pie: { label: "Pie", icon: PieIcon },
  metric: { label: "Summary", icon: Gauge },
  table: { label: "Table", icon: Table2 },
  sql: { label: "SQL", icon: Code2 },
};

interface Props {
  result: QueryResult;
  busy: boolean;
  canShare: boolean;
  onRunSql: (sql: string) => void;
  onPin: (type: ChartType) => Promise<void>;
  onShare: () => void;
}

export function ResultView({ result, busy, canShare, onRunSql, onPin, onShare }: Props) {
  const options = plotOptions(result);
  const [view, setView] = useState<ViewId>(options.includes(result.chart.type) ? result.chart.type : options[0]);
  const [measures, setMeasures] = useState<string[]>(result.chart.y.slice(0, 1));
  const [pinning, setPinning] = useState(false);
  const chartBox = useRef<HTMLDivElement>(null);
  const notify = useToast();
  const title = slug(result.question);
  const plotted = view !== "sql" && view !== "table" && view !== "metric";

  const toggleMeasure = (m: string) =>
    setMeasures((current) => (current.includes(m) ? (current.length > 1 ? current.filter((x) => x !== m) : current) : [...current, m]));

  const exportPng = async () => {
    if (chartBox.current && (await chartToPng(chartBox.current, `${title}.png`))) notify("Chart saved as PNG.");
    else notify("Could not export this chart.", "error");
  };

  const pin = async () => {
    setPinning(true);
    try {
      await onPin(view === "sql" ? result.chart.type : view);
    } finally {
      setPinning(false);
    }
  };

  return (
    <section className="card overflow-hidden" data-testid="result">
      <header className="border-b border-line px-5 py-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold leading-snug" data-testid="result-title">
              {result.question}
            </h2>
            {result.explanation && (
              <p className="mt-1.5 flex gap-1.5 text-sm text-ink-2" data-testid="explanation">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
                {result.explanation}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1">
            <button type="button" className="btn-ghost border border-line" onClick={pin} disabled={pinning || busy} data-testid="pin">
              <Pin className="h-4 w-4" /> Pin
            </button>
            {canShare && (
              <button type="button" className="btn-ghost px-2" onClick={onShare} title="Copy link" aria-label="Copy link" data-testid="share">
                <Link2 className="h-4 w-4" />
              </button>
            )}
            <button
              type="button"
              className="btn-ghost px-2"
              onClick={() => downloadBlob(new Blob([toCsv(result.columns, result.rows)], { type: "text/csv;charset=utf-8" }), `${title}.csv`)}
              disabled={!result.rows.length}
              title="Download CSV"
              aria-label="Download CSV"
              data-testid="export-csv"
            >
              <Download className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="btn-ghost px-2"
              onClick={() =>
                downloadBlob(
                  new Blob([JSON.stringify(result.rows.map((r) => Object.fromEntries(result.columns.map((c, i) => [c, r[i]]))), null, 2)], { type: "application/json" }),
                  `${title}.json`,
                )
              }
              disabled={!result.rows.length}
              title="Download JSON"
              aria-label="Download JSON"
              data-testid="export-json"
            >
              <FileJson className="h-4 w-4" />
            </button>
            {plotted && (
              <button type="button" className="btn-ghost px-2" onClick={exportPng} title="Download chart as PNG" aria-label="Download chart as PNG" data-testid="export-png">
                <ImageDown className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-2" data-testid="result-stats">
          <span className="rounded-md bg-panel-2 px-2 py-0.5">
            {result.row_count.toLocaleString()} {result.row_count === 1 ? "row" : "rows"}
          </span>
          <span className="rounded-md bg-panel-2 px-2 py-0.5" title={`AI ${formatMs(result.timings.llm_ms)} · database ${formatMs(result.timings.db_ms)}`}>
            {formatMs(result.timings.total_ms)}
          </span>
          {result.cached && (
            <span className="inline-flex items-center gap-1 rounded-md bg-accent/10 px-2 py-0.5 text-accent">
              <Zap className="h-3 w-3" /> cached
            </span>
          )}
          {result.repaired && (
            <span className="inline-flex items-center gap-1 rounded-md bg-warn/10 px-2 py-0.5 text-warn" title="The first SQL draft failed and was corrected automatically">
              <Wrench className="h-3 w-3" /> self-corrected
            </span>
          )}
          {result.truncated && (
            <span className="inline-flex items-center gap-1 rounded-md bg-warn/10 px-2 py-0.5 text-warn">
              <TriangleAlert className="h-3 w-3" /> first {result.row_count.toLocaleString()} rows shown
            </span>
          )}
        </div>
      </header>

      {result.insights.length > 0 && (
        <ul className="grid gap-2 border-b border-line bg-panel-2/40 px-5 py-3 text-sm md:grid-cols-3" data-testid="insights">
          {result.insights.map((text) => (
            <li key={text} className="flex gap-2 text-ink-2">
              <TrendingUp className="mt-0.5 h-4 w-4 shrink-0 text-accent-2" aria-hidden />
              <span>{text}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div role="tablist" aria-label="Result view" className="flex flex-wrap gap-1 rounded-lg bg-panel-2 p-1">
          {[...options, "sql" as const].map((id) => {
            const { label, icon: Icon } = VIEW_META[id];
            return (
              <button
                key={id}
                role="tab"
                type="button"
                aria-selected={view === id}
                onClick={() => setView(id)}
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${view === id ? "bg-panel text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}
                data-testid={`view-${id}`}
              >
                <Icon className="h-3.5 w-3.5" /> {label}
              </button>
            );
          })}
        </div>
        {plotted && view !== "pie" && result.chart.y.length > 1 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs" data-testid="measures">
            {result.chart.y.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => toggleMeasure(m)}
                aria-pressed={measures.includes(m)}
                className={`rounded-full border px-2.5 py-0.5 ${measures.includes(m) ? "border-accent bg-accent/10 text-ink" : "border-line text-ink-3 hover:text-ink"}`}
              >
                {humanize(m)}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="p-5" ref={chartBox}>
        {view === "sql" ? <SqlView sql={result.sql_pretty} busy={busy} onRun={onRunSql} /> : <Visual result={result} type={view} measures={view === "metric" ? result.chart.y : measures} />}
      </div>
    </section>
  );
}
