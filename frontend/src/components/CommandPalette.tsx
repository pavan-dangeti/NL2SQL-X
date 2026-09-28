import { CornerDownLeft, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export interface Command {
  id: string;
  label: string;
  group: string;
  icon: ReactNode;
  hint?: string;
  run: () => void;
}

export function CommandPalette({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const list = useRef<HTMLUListElement>(null);

  const matches = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return commands.filter((c) => words.every((w) => `${c.group} ${c.label}`.toLowerCase().includes(w)));
  }, [commands, query]);

  useEffect(() => setIndex(0), [query]);

  useEffect(() => {
    list.current?.querySelector(`[data-index="${index}"]`)?.scrollIntoView({ block: "nearest" });
  }, [index]);

  const choose = (command: Command | undefined) => {
    if (!command) return;
    onClose();
    command.run();
  };

  let lastGroup = "";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[12vh] backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label="Command palette" className="card w-full max-w-xl overflow-hidden shadow-2xl" data-testid="palette">
        <label className="flex items-center gap-3 border-b border-line px-4 py-3">
          <Search className="h-4 w-4 text-ink-3" aria-hidden />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setIndex((i) => Math.min(i + 1, matches.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setIndex((i) => Math.max(i - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                choose(matches[index]);
              } else if (e.key === "Escape") {
                onClose();
              }
            }}
            placeholder="Type a command or search…"
            className="w-full bg-transparent text-sm outline-none placeholder:text-ink-3"
            aria-label="Search commands"
            data-testid="palette-input"
          />
          <kbd className="rounded border border-line px-1.5 text-[10px] text-ink-3">ESC</kbd>
        </label>
        <ul ref={list} className="scroll-thin max-h-[50vh] overflow-y-auto p-2" role="listbox">
          {matches.length === 0 && <li className="px-3 py-6 text-center text-sm text-ink-3">No commands match.</li>}
          {matches.map((c, i) => {
            const header = c.group !== lastGroup;
            lastGroup = c.group;
            return (
              <li key={c.id}>
                {header && <div className="label px-3 pb-1 pt-2">{c.group}</div>}
                <button
                  type="button"
                  role="option"
                  aria-selected={i === index}
                  data-index={i}
                  onMouseEnter={() => setIndex(i)}
                  onClick={() => choose(c)}
                  className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm ${i === index ? "bg-panel-2 text-ink" : "text-ink-2"}`}
                >
                  <span className="text-ink-3">{c.icon}</span>
                  <span className="flex-1 truncate">{c.label}</span>
                  {c.hint && <kbd className="rounded border border-line px-1.5 text-[10px] text-ink-3">{c.hint}</kbd>}
                  {i === index && <CornerDownLeft className="h-3.5 w-3.5 text-ink-3" />}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

const SHORTCUTS: [string, string][] = [
  ["⌘ / Ctrl K", "Open the command palette"],
  ["/", "Focus the question box"],
  ["Enter", "Ask the question"],
  ["Shift Enter", "New line in the question"],
  ["⌘ / Ctrl Enter", "Run edited SQL"],
  ["Esc", "Stop a running question or close a dialog"],
  ["G then D", "Go to the dashboard"],
  ["G then A", "Go back to asking"],
  ["?", "Show this list"],
];

export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" className="card w-full max-w-md p-5 shadow-2xl" data-testid="shortcuts">
        <h2 className="text-base font-semibold">Keyboard shortcuts</h2>
        <dl className="mt-3 divide-y divide-line text-sm">
          {SHORTCUTS.map(([keys, action]) => (
            <div key={keys} className="flex items-center justify-between py-2">
              <dt className="text-ink-2">{action}</dt>
              <dd>
                <kbd className="rounded border border-line bg-panel-2 px-2 py-0.5 font-mono text-xs">{keys}</kbd>
              </dd>
            </div>
          ))}
        </dl>
        <div className="mt-4 text-right">
          <button type="button" className="btn-primary" onClick={onClose} autoFocus>
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}
