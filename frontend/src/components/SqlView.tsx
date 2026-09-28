import { Check, Copy, Pencil, Play, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { tokenizeSql } from "../lib/format";

const COLORS = {
  keyword: "text-accent font-semibold",
  string: "text-ok",
  number: "text-warn",
  comment: "text-ink-3 italic",
  plain: "",
} as const;

interface Props {
  sql: string;
  busy: boolean;
  onRun: (sql: string) => void;
}

export function SqlView({ sql, busy, onRun }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(sql);
  const [copied, setCopied] = useState(false);
  const tokens = useMemo(() => tokenizeSql(sql), [sql]);

  useEffect(() => {
    setDraft(sql);
    setEditing(false);
  }, [sql]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {editing ? (
          <>
            <button type="button" className="btn-ghost" onClick={() => setEditing(false)}>
              <X className="h-4 w-4" /> Cancel
            </button>
            <button type="button" className="btn-primary" disabled={busy || !draft.trim()} onClick={() => onRun(draft)} data-testid="run-sql">
              <Play className="h-4 w-4" /> Run SQL
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn-ghost" onClick={copy} data-testid="copy-sql">
              {copied ? <Check className="h-4 w-4 text-ok" /> : <Copy className="h-4 w-4" />} {copied ? "Copied" : "Copy"}
            </button>
            <button type="button" className="btn-ghost" onClick={() => setEditing(true)} data-testid="edit-sql">
              <Pencil className="h-4 w-4" /> Edit & run
            </button>
          </>
        )}
      </div>
      {editing ? (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && draft.trim() && !busy) onRun(draft);
          }}
          spellCheck={false}
          rows={Math.min(18, Math.max(6, draft.split("\n").length + 1))}
          className="w-full rounded-lg border border-line bg-panel-2 p-4 font-mono text-[13px] leading-6 text-ink outline-none focus:border-accent"
          aria-label="SQL editor"
          data-testid="sql-editor"
        />
      ) : (
        <pre className="scroll-thin overflow-x-auto rounded-lg border border-line bg-panel-2 p-4 font-mono text-[13px] leading-6" data-testid="sql-code">
          <code>
            {tokens.map((t, i) => (
              <span key={i} className={COLORS[t.kind]}>
                {t.text}
              </span>
            ))}
          </code>
        </pre>
      )}
      <p className="text-xs text-ink-3">Every query is validated as a single read-only SELECT and runs on a read-only connection with a time limit.</p>
    </div>
  );
}
