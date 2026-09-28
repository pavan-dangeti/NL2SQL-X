import { useEffect, useRef, useState, useSyncExternalStore } from "react";

type View = "ask" | "dashboard";

function readView(): View {
  return window.location.hash === "#/dashboard" ? "dashboard" : "ask";
}

function subscribe(callback: () => void) {
  window.addEventListener("hashchange", callback);
  return () => window.removeEventListener("hashchange", callback);
}

export function useView(): [View, (view: View) => void] {
  const view = useSyncExternalStore(subscribe, readView, () => "ask" as View);
  const go = (next: View) => {
    const hash = next === "dashboard" ? "#/dashboard" : "#/";
    if (window.location.hash !== hash) window.location.hash = hash;
  };
  return [view, go];
}

export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable);
}

export function useHotkeys(handler: (e: KeyboardEvent) => void): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const listener = (e: KeyboardEvent) => ref.current(e);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
}

export function useElapsed(): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = performance.now();
    const timer = window.setInterval(() => setElapsed(performance.now() - started), 100);
    return () => window.clearInterval(timer);
  }, []);
  return elapsed;
}
