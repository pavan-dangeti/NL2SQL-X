import { ChevronRight, CircleAlert, Database, Eye, History, Key, Link2, RotateCcw, Search, Trash2 } from "lucide-react";
import { memo, useMemo, useState } from "react";
import { relativeTime } from "../lib/format";
import type { HistoryItem, Table } from "../lib/types";

export const SchemaPanel = memo(function SchemaPanel({
  tables,
  loading,
  onPick,
  onPreview,
}: {
  tables: Table[] | null;
  loading: boolean;
  onPick: (text: string) => void;
  onPreview: (table: string) => void;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});

  return (
    <section className="card flex min-h-0 flex-col" aria-label="Schema">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <Database className="h-4 w-4 text-accent-2" />
        <h2 className="label">Schema</h2>
        {tables && <span className="ml-auto text-xs text-ink-3">{tables.length} tables</span>}
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-2" data-testid="schema">
        {loading && !tables && Array.from({ length: 4 }, (_, i) => <div key={i} className="m-2 h-6 animate-pulse rounded bg-panel-2" />)}
        {tables?.map((t) => (
          <div key={t.name}>
            <div className="group flex items-center rounded-md hover:bg-panel-2">
              <button
                type="button"
                onClick={() => setOpen((o) => ({ ...o, [t.name]: !o[t.name] }))}
                aria-expanded={!!open[t.name]}
                className="flex min-w-0 flex-1 items-center gap-1.5 px-2 py-1.5 text-left text-sm"
                data-testid={`table-${t.name}`}
              >
                <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-ink-3 transition-transform ${open[t.name] ? "rotate-90" : ""}`} />
                <span className="truncate font-mono font-medium">{t.name}</span>
                <span className="ml-auto text-xs text-ink-3 tabular-nums">{t.row_count.toLocaleString()}</span>
              </button>
              <button
                type="button"
                onClick={() => onPreview(t.name)}
                className="mr-1 rounded p-1 text-ink-3 hover:text-accent focus:opacity-100 lg:opacity-0 lg:group-hover:opacity-100"
                aria-label={`Preview ${t.name}`}
                title="Preview rows"
                data-testid={`preview-${t.name}`}
              >
                <Eye className="h-3.5 w-3.5" />
              </button>
            </div>
            {open[t.name] && (
              <ul className="mb-1 ml-5 border-l border-line pl-2">
                {t.columns.map((c) => {
                  const fk = t.foreign_keys.find((f) => f.column === c.name);
                  const hint = c.values ? c.values.join(", ") : c.min !== null ? `${c.min} … ${c.max}` : "";
                  return (
                    <li key={c.name}>
                      <button
                        type="button"
                        onClick={() => onPick(c.name)}
                        title={hint || `Insert ${c.name}`}
                        className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-xs hover:bg-panel-2"
                      >
                        {c.primary_key ? <Key className="h-3 w-3 text-warn" /> : fk ? <Link2 className="h-3 w-3 text-accent-2" /> : <span className="w-3" />}
                        <span className="font-mono text-ink">{c.name}</span>
                        <span className="ml-auto font-mono text-[10px] text-ink-3">{c.type || "ANY"}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        ))}
      </div>
    </section>
  );
});

export const HistoryPanel = memo(function HistoryPanel({
  items,
  busy,
  onRerun,
  onClear,
}: {
  items: HistoryItem[];
  busy: boolean;
  onRerun: (item: HistoryItem) => void;
  onClear: () => void;
}) {
  const [search, setSearch] = useState("");
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? items.filter((h) => h.question.toLowerCase().includes(q) || h.sql?.toLowerCase().includes(q)) : items;
  }, [items, search]);

  return (
    <section className="card flex min-h-0 flex-col" aria-label="History">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <History className="h-4 w-4 text-accent-2" />
        <h2 className="label">History</h2>
        {items.length > 0 && (
          <button type="button" onClick={onClear} className="ml-auto text-ink-3 hover:text-bad" aria-label="Clear history" data-testid="clear-history">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {items.length > 5 && (
        <label className="mx-2 mt-2 flex items-center gap-2 rounded-md border border-line px-2 py-1 text-xs focus-within:border-accent">
          <Search className="h-3.5 w-3.5 text-ink-3" aria-hidden />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search history" className="w-full bg-transparent outline-none placeholder:text-ink-3" aria-label="Search history" />
        </label>
      )}
      <ul className="scroll-thin min-h-0 flex-1 space-y-1 overflow-y-auto p-2" data-testid="history">
        {items.length === 0 && <li className="px-2 py-6 text-center text-xs text-ink-3">Questions you ask will appear here.</li>}
        {items.length > 0 && shown.length === 0 && <li className="px-2 py-4 text-center text-xs text-ink-3">No matches.</li>}
        {shown.map((h) => (
          <li key={h.id}>
            <button
              type="button"
              disabled={busy}
              onClick={() => onRerun(h)}
              className="group w-full rounded-md px-2 py-1.5 text-left hover:bg-panel-2 disabled:opacity-60"
              title={h.error ?? h.sql ?? ""}
            >
              <div className="flex items-start gap-1.5">
                {h.status === "error" ? <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-bad" /> : <RotateCcw className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-3 group-hover:text-accent" />}
                <span className="line-clamp-2 text-sm">{h.question}</span>
              </div>
              <div className="mt-0.5 pl-5 text-[11px] text-ink-3">
                {h.status === "ok" ? `${h.row_count ?? 0} rows` : "failed"} · {relativeTime(h.created_at)}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
});
