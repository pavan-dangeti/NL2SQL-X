import { Check, CircleAlert, LayoutDashboard, Pencil, RefreshCw, Trash2, X } from "lucide-react";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, isAbort } from "../lib/api";
import { formatMs, relativeTime } from "../lib/format";
import type { Pin, QueryResult } from "../lib/types";
import { useToast } from "./Toaster";
import { Visual } from "./Visual";

interface Props {
  pins: Pin[] | null;
  datasetName: string;
  onChanged: () => void;
  onAsk: () => void;
}

export function Dashboard({ pins, datasetName, onChanged, onAsk }: Props) {
  const [generation, setGeneration] = useState(0);

  if (pins === null) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="card h-[340px] animate-pulse" />
        ))}
      </div>
    );
  }

  if (!pins.length) {
    return (
      <section className="card px-6 py-16 text-center" data-testid="dashboard-empty">
        <LayoutDashboard className="mx-auto h-10 w-10 text-accent" />
        <h2 className="mt-3 text-lg font-semibold">Your {datasetName} dashboard is empty</h2>
        <p className="mx-auto mt-1 max-w-md text-sm text-ink-2">Ask a question and press Pin on any result. Pinned queries re-run against live data every time you open this page.</p>
        <button type="button" className="btn-primary mt-5" onClick={onAsk}>
          Ask a question
        </button>
      </section>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Dashboard</h2>
          <p className="text-sm text-ink-2">
            {pins.length} pinned {pins.length === 1 ? "query" : "queries"} on {datasetName}
          </p>
        </div>
        <button type="button" className="btn-ghost border border-line" onClick={() => setGeneration((g) => g + 1)} data-testid="refresh-all">
          <RefreshCw className="h-4 w-4" /> Refresh all
        </button>
      </div>
      <div className="grid gap-4 xl:grid-cols-2" data-testid="dashboard">
        {pins.map((pin) => (
          <PinCard key={pin.id} pin={pin} generation={generation} onChanged={onChanged} />
        ))}
      </div>
    </div>
  );
}

const PinCard = memo(function PinCard({ pin, generation, onChanged }: { pin: Pin; generation: number; onChanged: () => void }) {
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(pin.title);
  const [refreshed, setRefreshed] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const notify = useToast();

  const load = useCallback(async () => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setLoading(true);
    setError(null);
    try {
      const { result: next } = await api.runPin(pin.id, current.signal);
      setResult(next);
      setRefreshed(new Date().toISOString());
    } catch (err) {
      if (!isAbort(err)) setError(err instanceof ApiError ? err.message : "Could not refresh this pin.");
    } finally {
      if (controller.current === current) setLoading(false);
    }
  }, [pin.id]);

  useEffect(() => {
    void load();
    return () => controller.current?.abort();
  }, [load, generation]);

  const rename = async () => {
    const next = title.trim();
    if (!next || next === pin.title) {
      setEditing(false);
      setTitle(pin.title);
      return;
    }
    try {
      await api.renamePin(pin.id, next);
      setEditing(false);
      onChanged();
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Rename failed.", "error");
    }
  };

  const remove = async () => {
    try {
      await api.unpin(pin.id);
      notify("Removed from dashboard.");
      onChanged();
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Could not remove the pin.", "error");
    }
  };

  return (
    <article className="card flex min-w-0 flex-col" data-testid="pin-card">
      <header className="flex items-start gap-2 border-b border-line px-4 py-3">
        <div className="min-w-0 flex-1">
          {editing ? (
            <form
              className="flex items-center gap-1"
              onSubmit={(e) => {
                e.preventDefault();
                void rename();
              }}
            >
              <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} className="w-full rounded-md border border-line bg-panel px-2 py-1 text-sm outline-none focus:border-accent" aria-label="Pin title" />
              <button type="submit" className="btn-ghost px-1.5" aria-label="Save title">
                <Check className="h-4 w-4 text-ok" />
              </button>
              <button
                type="button"
                className="btn-ghost px-1.5"
                aria-label="Cancel rename"
                onClick={() => {
                  setEditing(false);
                  setTitle(pin.title);
                }}
              >
                <X className="h-4 w-4" />
              </button>
            </form>
          ) : (
            <h3 className="truncate text-sm font-semibold" title={pin.question}>
              {pin.title}
            </h3>
          )}
          <p className="mt-0.5 text-xs text-ink-3">
            {loading ? "Refreshing…" : result ? `${result.row_count.toLocaleString()} rows · ${formatMs(result.timings.total_ms)} · updated ${relativeTime(refreshed ?? "")}` : "Not loaded"}
          </p>
        </div>
        {!editing && (
          <div className="flex shrink-0 items-center">
            <button type="button" className="btn-ghost px-1.5" onClick={() => void load()} disabled={loading} aria-label="Refresh pin">
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>
            <button type="button" className="btn-ghost px-1.5" onClick={() => setEditing(true)} aria-label="Rename pin">
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button type="button" className="btn-ghost px-1.5 hover:text-bad" onClick={() => void remove()} aria-label="Remove pin" data-testid="unpin">
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </header>
      <div className="flex-1 p-4">
        {error ? (
          <div className="flex items-start gap-2 text-sm text-bad">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" /> {error}
          </div>
        ) : result ? (
          <Visual result={result} type={pin.chart_type} measures={pin.chart_type === "metric" ? result.chart.y : result.chart.y.slice(0, 1)} height={260} compact />
        ) : (
          <div className="h-[260px] animate-pulse rounded-lg bg-panel-2" />
        )}
      </div>
    </article>
  );
});
