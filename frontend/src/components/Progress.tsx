import { Check, Loader2 } from "lucide-react";
import { useElapsed } from "../lib/hooks";
import type { Stage } from "../lib/types";

const STEPS: { label: string; stages: Stage[] }[] = [
  { label: "Reading schema", stages: ["schema"] },
  { label: "Writing SQL", stages: ["generating", "repairing"] },
  { label: "Safety check", stages: ["validating"] },
  { label: "Running query", stages: ["running"] },
];

export function Progress({ stage }: { stage: Stage | null }) {
  const elapsed = useElapsed();
  const finished = stage === "cache" || stage === "done";
  const active = finished ? STEPS.length : Math.max(0, STEPS.findIndex((s) => stage && s.stages.includes(stage)));

  return (
    <section className="card p-5" role="status" aria-live="polite" data-testid="progress">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{stage === "repairing" ? "Fixing the first draft…" : finished ? "Almost there…" : "Working on it…"}</span>
        <span className="font-mono text-xs text-ink-3 tabular-nums">{(elapsed / 1000).toFixed(1)} s</span>
      </div>
      <ol className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {STEPS.map((step, i) => {
          const done = i < active;
          const current = i === active && !finished;
          return (
            <li key={step.label} className="flex items-center gap-2 text-xs">
              <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${done ? "border-ok bg-ok/15 text-ok" : current ? "border-accent text-accent" : "border-line text-ink-3"}`}>
                {done ? <Check className="h-3.5 w-3.5" /> : current ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : i + 1}
              </span>
              <span className={done || current ? "text-ink" : "text-ink-3"}>{step.label}</span>
            </li>
          );
        })}
      </ol>
      <div className="mt-4 h-1 overflow-hidden rounded-full bg-panel-2">
        <div className="h-full rounded-full bg-gradient-to-r from-accent to-accent-2 transition-[width] duration-500" style={{ width: `${Math.max(8, (active / STEPS.length) * 100)}%` }} />
      </div>
    </section>
  );
}
