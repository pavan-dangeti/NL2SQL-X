import {
  CircleAlert,
  Command as CommandIcon,
  Database,
  Keyboard,
  LayoutDashboard,
  MessageSquareText,
  Moon,
  Plus,
  RefreshCw,
  Sparkles,
  Sun,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CommandPalette, ShortcutsDialog, type Command } from "./components/CommandPalette";
import { Composer, type ComposerHandle } from "./components/Composer";
import { Dashboard } from "./components/Dashboard";
import { Progress } from "./components/Progress";
import { ResultView } from "./components/ResultView";
import { HistoryPanel, SchemaPanel } from "./components/Sidebar";
import { useToast } from "./components/Toaster";
import { UploadDialog } from "./components/UploadDialog";
import { preloadChart } from "./components/Visual";
import { api, ApiError, isAbort, type Previous } from "./lib/api";
import { isTyping, useHotkeys, useView } from "./lib/hooks";
import { load, save } from "./lib/storage";
import type { ChartType, Dataset, HistoryItem, Meta, Pin, QueryResult, Stage, Table } from "./lib/types";

const DATASET_KEY = "nl2sql.dataset";
const THEME_KEY = "nl2sql.theme";
const EDITED = "(edited SQL)";

type Failure = { message: string; retry: (() => void) | null };
type Dialog = "palette" | "shortcuts" | "upload" | null;

function initialLink(): { question: string | null; dataset: string | null } {
  const params = new URLSearchParams(window.location.search);
  return { question: params.get("q"), dataset: params.get("d") };
}

export default function App() {
  const link = useRef(initialLink());
  const [view, go] = useView();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState(link.current.dataset ?? load(DATASET_KEY) ?? "ecommerce");
  const [tables, setTables] = useState<Table[] | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [pins, setPins] = useState<Pin[] | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [resultKey, setResultKey] = useState(0);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<Stage | null>(null);
  const [followUp, setFollowUp] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const [bootError, setBootError] = useState<string | null>(null);
  const composer = useRef<ComposerHandle>(null);
  const inflight = useRef<AbortController | null>(null);
  const pendingKey = useRef<string | null>(null);
  const notify = useToast();

  const active = datasets.find((d) => d.id === datasetId);
  const wantsFocus = useRef(false);

  const focusComposer = useCallback(() => {
    if (composer.current) composer.current.focus();
    else wantsFocus.current = true;
    go("ask");
  }, [go]);

  useEffect(() => {
    if (view === "ask" && wantsFocus.current && composer.current) {
      wantsFocus.current = false;
      composer.current.focus();
    }
  }, [view]);

  const loadDatasets = useCallback(async () => {
    const list = await api.datasets();
    setDatasets(list);
    return list;
  }, []);

  const boot = useCallback(async () => {
    setBootError(null);
    try {
      const [m, list] = await Promise.all([api.meta(), loadDatasets()]);
      setMeta(m);
      setDatasetId((id) => (list.some((d) => d.id === id) ? id : "ecommerce"));
    } catch (err) {
      setBootError(err instanceof ApiError ? err.message : "Could not load the app.");
    }
  }, [loadDatasets]);

  useEffect(() => {
    void boot();
    const timer = window.setTimeout(preloadChart, 1200);
    return () => window.clearTimeout(timer);
  }, [boot]);

  const loadPins = useCallback(() => {
    api.pins(datasetId).then(setPins, () => setPins([]));
  }, [datasetId]);

  useEffect(() => {
    if (!datasets.some((d) => d.id === datasetId)) return;
    save(DATASET_KEY, datasetId);
    let cancelled = false;
    setTables(null);
    setSuggestions([]);
    setHistory([]);
    setPins(null);
    Promise.allSettled([api.schema(datasetId), api.suggestions(datasetId), api.history(datasetId), api.pins(datasetId)]).then(
      ([s, g, h, p]) => {
        if (cancelled) return;
        setTables(s.status === "fulfilled" ? s.value.tables : []);
        if (g.status === "fulfilled") setSuggestions(g.value);
        if (h.status === "fulfilled") setHistory(h.value);
        setPins(p.status === "fulfilled" ? p.value : []);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [datasetId, datasets]);

  const refreshHistory = useCallback(() => {
    api.history(datasetId).then(setHistory, () => undefined);
  }, [datasetId]);

  const run = useCallback(
    async (task: (signal: AbortSignal) => Promise<QueryResult>, retry: () => void) => {
      inflight.current?.abort();
      const controller = new AbortController();
      inflight.current = controller;
      setBusy(true);
      setStage(null);
      setFailure(null);
      go("ask");
      try {
        const next = await task(controller.signal);
        if (inflight.current !== controller) return;
        setResult(next);
        setResultKey((k) => k + 1);
        setFollowUp(false);
      } catch (err) {
        if (isAbort(err) || inflight.current !== controller) return;
        const apiError = err instanceof ApiError ? err : null;
        setFailure({ message: apiError?.message ?? "Something went wrong.", retry: !apiError || apiError.retriable ? retry : null });
      } finally {
        if (inflight.current === controller) {
          inflight.current = null;
          setBusy(false);
          setStage(null);
          refreshHistory();
        }
      }
    },
    [go, refreshHistory],
  );

  const ask = useCallback(
    (question: string) => {
      const previous: Previous | null = followUp && result ? { question: result.question, sql: result.sql } : null;
      void run((signal) => api.ask(question, datasetId, previous, setStage, signal), () => ask(question));
    },
    [datasetId, followUp, result, run],
  );

  const runSql = useCallback((sql: string) => void run((signal) => api.runSql(sql, datasetId, signal), () => runSql(sql)), [datasetId, run]);

  const preview = useCallback(
    (table: string) => void run((signal) => api.preview(datasetId, table, signal), () => preview(table)),
    [datasetId, run],
  );

  useEffect(() => {
    const question = link.current.question;
    if (!question || !active) return;
    if (pendingKey.current === question) return;
    pendingKey.current = question;
    window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    composer.current?.set(question);
    ask(question);
  }, [active, ask]);

  const cancel = useCallback(() => {
    inflight.current?.abort();
    inflight.current = null;
    setBusy(false);
    setStage(null);
  }, []);

  const switchDataset = useCallback(
    (id: string) => {
      cancel();
      setResult(null);
      setFailure(null);
      setDatasetId(id);
    },
    [cancel],
  );

  const removeDataset = async () => {
    if (!active || active.builtin || !window.confirm(`Delete “${active.name}”? Its history and pins are removed too.`)) return;
    try {
      await api.deleteDataset(active.id);
      await loadDatasets();
      switchDataset("ecommerce");
      notify(`Deleted ${active.name}.`);
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Could not delete the dataset.", "error");
    }
  };

  const toggleTheme = useCallback(() => {
    setDark((current) => {
      const next = !current;
      document.documentElement.classList.toggle("dark", next);
      save(THEME_KEY, next ? "dark" : "light");
      return next;
    });
  }, []);

  const pinResult = async (type: ChartType) => {
    if (!result) return;
    try {
      await api.pin({ dataset_id: datasetId, title: result.question === EDITED ? "Custom SQL" : result.question, question: result.question, sql: result.sql, chart_type: type });
      loadPins();
      notify("Pinned to the dashboard.");
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Could not pin this result.", "error");
    }
  };

  const share = async () => {
    if (!result) return;
    const url = new URL(window.location.origin + window.location.pathname);
    url.searchParams.set("q", result.question);
    if (datasetId !== "ecommerce") url.searchParams.set("d", datasetId);
    try {
      await navigator.clipboard.writeText(url.toString());
      notify("Link copied. It re-runs this question when opened.");
    } catch {
      notify("Could not copy the link.", "error");
    }
  };

  const clearHistory = useCallback(() => {
    api.clearHistory(datasetId).then(
      () => {
        setHistory([]);
        notify("History cleared.");
      },
      () => notify("Could not clear history.", "error"),
    );
  }, [datasetId, notify]);

  const chord = useRef<number>(0);
  useHotkeys((e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "k") {
      e.preventDefault();
      setDialog((d) => (d === "palette" ? null : "palette"));
      return;
    }
    if (e.key === "Escape") {
      if (dialog === "palette" || dialog === "shortcuts") setDialog(null);
      else if (busy) cancel();
      return;
    }
    if (dialog || isTyping(e.target) || mod || e.altKey) return;
    if (e.key === "/") {
      e.preventDefault();
      focusComposer();
    } else if (e.key === "?") {
      setDialog("shortcuts");
    } else if (e.key.toLowerCase() === "g") {
      chord.current = Date.now();
    } else if (Date.now() - chord.current < 1000) {
      if (e.key.toLowerCase() === "d") go("dashboard");
      if (e.key.toLowerCase() === "a") go("ask");
      chord.current = 0;
    }
  });

  const commands = useMemo<Command[]>(() => {
    const icon = "h-4 w-4";
    return [
      { id: "ask", group: "Navigate", label: "Ask a question", icon: <MessageSquareText className={icon} />, hint: "G A", run: focusComposer },
      { id: "dash", group: "Navigate", label: "Open dashboard", icon: <LayoutDashboard className={icon} />, hint: "G D", run: () => go("dashboard") },
      ...suggestions.map((s, i) => ({ id: `s${i}`, group: "Suggested questions", label: s, icon: <Sparkles className={icon} />, run: () => { composer.current?.set(s); ask(s); } })),
      ...datasets.filter((d) => d.id !== datasetId).map((d) => ({ id: `d-${d.id}`, group: "Switch dataset", label: d.name, icon: <Database className={icon} />, run: () => switchDataset(d.id) })),
      { id: "upload", group: "Actions", label: "Upload CSV files", icon: <Plus className={icon} />, run: () => setDialog("upload") },
      { id: "theme", group: "Actions", label: dark ? "Switch to light theme" : "Switch to dark theme", icon: dark ? <Sun className={icon} /> : <Moon className={icon} />, run: toggleTheme },
      { id: "clear", group: "Actions", label: "Clear history for this dataset", icon: <Trash2 className={icon} />, run: clearHistory },
      { id: "keys", group: "Help", label: "Keyboard shortcuts", icon: <Keyboard className={icon} />, hint: "?", run: () => setDialog("shortcuts") },
    ];
  }, [ask, clearHistory, dark, datasetId, datasets, focusComposer, go, suggestions, switchDataset, toggleTheme]);

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] items-center gap-2 px-4 py-2.5 sm:gap-3">
          <a href="#/" className="flex items-center gap-2.5" aria-label="NL2SQL-X home">
            <img src="/favicon.svg" alt="" className="h-8 w-8" />
            <span className="hidden leading-tight sm:block">
              <span className="block text-[15px] font-semibold tracking-tight">
                NL2SQL<span className="text-accent">-X</span>
              </span>
              <span className="block text-xs text-ink-3">Ask your data in plain English</span>
            </span>
          </a>
          <nav className="ml-2 flex rounded-lg bg-panel-2 p-1 text-sm" aria-label="Views">
            {(["ask", "dashboard"] as const).map((v) => (
              <a
                key={v}
                href={v === "ask" ? "#/" : "#/dashboard"}
                aria-current={view === v ? "page" : undefined}
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium ${view === v ? "bg-panel text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}
                data-testid={`nav-${v}`}
              >
                {v === "ask" ? <MessageSquareText className="h-4 w-4" /> : <LayoutDashboard className="h-4 w-4" />}
                <span className="hidden md:inline">{v === "ask" ? "Ask" : "Dashboard"}</span>
                {v === "dashboard" && !!pins?.length && <span className="rounded-full bg-accent/15 px-1.5 text-[10px] text-accent">{pins.length}</span>}
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
            {meta?.demo_mode && (
              <span className="hidden rounded-full border border-warn/40 bg-warn/10 px-2.5 py-0.5 text-xs text-warn lg:inline" title="No Gemini API key is configured. Only the suggested questions are answered.">
                Demo mode
              </span>
            )}
            <label className="flex items-center gap-2 text-sm">
              <Database className="hidden h-4 w-4 text-ink-3 sm:block" aria-hidden />
              <select value={datasetId} onChange={(e) => switchDataset(e.target.value)} className="max-w-[140px] rounded-lg border border-line bg-panel px-2 py-1.5 sm:max-w-[220px]" aria-label="Dataset" data-testid="dataset-select">
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
            {active && !active.builtin && (
              <button type="button" className="btn-ghost px-2" onClick={removeDataset} aria-label="Delete dataset" title="Delete dataset" data-testid="delete-dataset">
                <Trash2 className="h-4 w-4" />
              </button>
            )}
            <button type="button" className="btn-ghost border border-line" onClick={() => setDialog("upload")} data-testid="open-upload">
              <Plus className="h-4 w-4" /> <span className="hidden sm:inline">Upload</span>
            </button>
            <button type="button" className="btn-ghost hidden border border-line px-2 md:inline-flex" onClick={() => setDialog("palette")} aria-label="Command palette" title="Command palette (⌘K)" data-testid="open-palette">
              <CommandIcon className="h-4 w-4" />
              <kbd className="text-[10px] text-ink-3">K</kbd>
            </button>
            <button type="button" className="btn-ghost px-2" onClick={toggleTheme} aria-label="Toggle theme" data-testid="theme-toggle">
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
          </div>
        </div>
      </header>

      {bootError ? (
        <main className="mx-auto mt-24 max-w-md px-4 text-center" data-testid="boot-error">
          <CircleAlert className="mx-auto h-10 w-10 text-bad" />
          <p className="mt-3 text-ink-2">{bootError}</p>
          <button type="button" className="btn-primary mt-4" onClick={boot}>
            <RefreshCw className="h-4 w-4" /> Try again
          </button>
        </main>
      ) : (
        <div className="mx-auto grid w-full max-w-[1500px] flex-1 grid-cols-1 gap-4 px-4 py-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="order-2 grid gap-4 lg:sticky lg:top-[68px] lg:order-1 lg:h-[calc(100vh-84px)] lg:grid-rows-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <SchemaPanel tables={tables} loading={!tables} onPick={(name) => composer.current?.insert(name)} onPreview={preview} />
            <HistoryPanel items={history} busy={busy} onRerun={(h) => (h.question === EDITED && h.sql ? runSql(h.sql) : ask(h.question))} onClear={clearHistory} />
          </aside>

          <main className="order-1 min-w-0 space-y-4 lg:order-2">
            {view === "dashboard" ? (
              <Dashboard
                pins={pins}
                datasetName={active?.name ?? "this dataset"}
                onChanged={loadPins}
                onAsk={focusComposer}
              />
            ) : (
              <>
                <Composer
                  ref={composer}
                  busy={busy}
                  suggestions={result ? suggestions.slice(0, 4) : suggestions}
                  canFollowUp={!!result && result.question !== EDITED}
                  followUp={followUp}
                  onFollowUpChange={setFollowUp}
                  onAsk={ask}
                  onCancel={cancel}
                />

                {failure && (
                  <div className="card flex items-start gap-3 border-bad/40 bg-bad/5 p-4" role="alert" data-testid="error">
                    <CircleAlert className="mt-0.5 h-5 w-5 shrink-0 text-bad" />
                    <p className="flex-1 text-sm">{failure.message}</p>
                    {failure.retry && (
                      <button type="button" className="btn-ghost border border-line" onClick={failure.retry} data-testid="retry">
                        <RefreshCw className="h-4 w-4" /> Retry
                      </button>
                    )}
                  </div>
                )}

                {busy && <Progress stage={stage} />}
                {result && !busy && (
                  <ResultView key={resultKey} result={result} busy={busy} canShare={!result.question.startsWith("(") && !result.question.startsWith("Preview of")} onRunSql={runSql} onPin={pinResult} onShare={share} />
                )}
                {!result && !busy && !failure && (
                  <section className="card overflow-hidden" data-testid="welcome">
                    <div className="bg-gradient-to-br from-accent/10 via-transparent to-accent-2/10 px-6 py-12 text-center">
                      <h2 className="text-2xl font-semibold tracking-tight">Ask anything about {active?.name ?? "your data"}</h2>
                      <p className="mx-auto mt-2 max-w-2xl text-sm text-ink-2">
                        NL2SQL-X writes the SQL, proves it is a single read-only query, runs it with a time limit and picks the right chart. Pin answers to a live dashboard, share them as links, or upload CSVs to query your own data.
                      </p>
                      <div className="mt-5 flex flex-wrap justify-center gap-2 text-xs text-ink-3">
                        <span><kbd className="rounded border border-line bg-panel px-1.5 font-mono">/</kbd> type a question</span>
                        <span>·</span>
                        <span><kbd className="rounded border border-line bg-panel px-1.5 font-mono">⌘K</kbd> commands</span>
                        <span>·</span>
                        <span><kbd className="rounded border border-line bg-panel px-1.5 font-mono">?</kbd> shortcuts</span>
                      </div>
                    </div>
                  </section>
                )}
              </>
            )}
          </main>
        </div>
      )}

      <footer className="border-t border-line py-3 text-center text-xs text-ink-3">
        NL2SQL-X {meta ? `v${meta.version} · ${meta.demo_mode ? "demo mode" : meta.llm}` : ""}
      </footer>

      {dialog === "upload" && meta && (
        <UploadDialog
          maxMb={meta.max_upload_mb}
          onClose={() => setDialog(null)}
          onUploaded={async (dataset) => {
            setDialog(null);
            await loadDatasets();
            switchDataset(dataset.id);
            notify(`${dataset.name} is ready: ${dataset.row_count.toLocaleString()} rows in ${dataset.tables.length} ${dataset.tables.length === 1 ? "table" : "tables"}.`);
          }}
        />
      )}
      {dialog === "palette" && <CommandPalette commands={commands} onClose={() => setDialog(null)} />}
      {dialog === "shortcuts" && <ShortcutsDialog onClose={() => setDialog(null)} />}
    </div>
  );
}
