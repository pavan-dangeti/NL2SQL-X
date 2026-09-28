import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { memo, useDeferredValue, useMemo, useState } from "react";
import { formatCell, humanize, sortRows } from "../lib/format";
import type { Cell } from "../lib/types";

interface Props {
  columns: string[];
  rows: Cell[][];
  compact?: boolean;
}

export const DataTable = memo(function DataTable({ columns, rows, compact = false }: Props) {
  const pageSize = compact ? 8 : 50;
  const [sort, setSort] = useState<{ index: number; direction: "asc" | "desc" } | null>(null);
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState("");
  const query = useDeferredValue(filter.trim().toLowerCase());

  const numeric = useMemo(
    () => columns.map((_, i) => rows.some((r) => typeof r[i] === "number") && rows.every((r) => r[i] === null || typeof r[i] === "number")),
    [columns, rows],
  );
  const filtered = useMemo(
    () => (query ? rows.filter((r) => r.some((c) => c !== null && String(c).toLowerCase().includes(query))) : rows),
    [rows, query],
  );
  const sorted = useMemo(() => (sort ? sortRows(filtered, sort.index, sort.direction) : filtered), [filtered, sort]);
  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const current = Math.min(page, pages - 1);
  const visible = sorted.slice(current * pageSize, (current + 1) * pageSize);

  const toggle = (index: number) => {
    setPage(0);
    setSort((s) =>
      s?.index !== index ? { index, direction: numeric[index] ? "desc" : "asc" } : s.direction === "asc" ? { index, direction: "desc" } : null,
    );
  };

  if (!rows.length) {
    return <p className="py-10 text-center text-sm text-ink-3">The query ran successfully but returned no rows.</p>;
  }

  return (
    <div>
      {!compact && rows.length > 10 && (
        <label className="mb-3 flex max-w-xs items-center gap-2 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm focus-within:border-accent">
          <Search className="h-4 w-4 text-ink-3" aria-hidden />
          <input
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setPage(0);
            }}
            placeholder="Filter rows…"
            className="w-full bg-transparent outline-none placeholder:text-ink-3"
            aria-label="Filter rows"
            data-testid="table-filter"
          />
        </label>
      )}
      <div className={`scroll-thin overflow-auto rounded-lg border border-line ${compact ? "max-h-[260px]" : "max-h-[520px]"}`}>
        <table className="w-full border-collapse text-sm" data-testid="results-table">
          <thead className="sticky top-0 z-10 bg-panel-2">
            <tr>
              {columns.map((col, i) => {
                const active = sort?.index === i;
                const Icon = !active ? ArrowUpDown : sort.direction === "asc" ? ArrowUp : ArrowDown;
                return (
                  <th key={col} scope="col" aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"} className={`border-b border-line px-3 py-2 font-medium ${numeric[i] ? "text-right" : "text-left"}`}>
                    <button type="button" onClick={() => toggle(i)} className={`inline-flex items-center gap-1 whitespace-nowrap ${active ? "text-ink" : "text-ink-2 hover:text-ink"}`}>
                      {humanize(col)}
                      <Icon className={`h-3 w-3 ${active ? "text-accent" : "opacity-40"}`} aria-hidden />
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, r) => (
              <tr key={current * pageSize + r} className="odd:bg-panel even:bg-panel-2/40 hover:bg-panel-2">
                {row.map((cell, c) => (
                  <td
                    key={c}
                    className={`max-w-[360px] truncate border-b border-line/60 px-3 py-1.5 ${numeric[c] ? "text-right font-mono tabular-nums" : ""} ${cell === null ? "text-ink-3" : ""}`}
                    title={cell === null ? "NULL" : String(cell)}
                  >
                    {formatCell(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!visible.length && <p className="py-8 text-center text-sm text-ink-3">No rows match “{filter}”.</p>}
      </div>
      {pages > 1 && (
        <div className="mt-3 flex items-center justify-between text-xs text-ink-2">
          <span data-testid="table-range">
            Rows {current * pageSize + 1}–{Math.min((current + 1) * pageSize, sorted.length)} of {sorted.length.toLocaleString()}
          </span>
          <div className="flex items-center gap-1">
            <button type="button" className="btn-ghost px-2" disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Previous page">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="tabular-nums">
              {current + 1} / {pages}
            </span>
            <button type="button" className="btn-ghost px-2" disabled={current >= pages - 1} onClick={() => setPage(current + 1)} aria-label="Next page" data-testid="next-page">
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
});
