import { CornerDownLeft, CornerUpRight, Square, WandSparkles } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

export interface ComposerHandle {
  focus: () => void;
  set: (text: string) => void;
  insert: (text: string) => void;
}

interface Props {
  busy: boolean;
  suggestions: string[];
  canFollowUp: boolean;
  followUp: boolean;
  onFollowUpChange: (value: boolean) => void;
  onAsk: (question: string) => void;
  onCancel: () => void;
}

export const Composer = forwardRef<ComposerHandle, Props>(function Composer(
  { busy, suggestions, canFollowUp, followUp, onFollowUpChange, onAsk, onCancel },
  ref,
) {
  const [text, setText] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(ref, () => ({
    focus: () => input.current?.focus(),
    set: (value: string) => {
      setText(value);
      input.current?.focus();
    },
    insert: (value: string) => {
      const el = input.current;
      const start = el?.selectionStart ?? text.length;
      const end = el?.selectionEnd ?? text.length;
      const before = text.slice(0, start);
      const spaced = (before && !before.endsWith(" ") ? " " : "") + value + " ";
      setText(before + spaced + text.slice(end));
      requestAnimationFrame(() => {
        el?.focus();
        el?.setSelectionRange(start + spaced.length, start + spaced.length);
      });
    },
  }));

  useEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  const submit = (value = text) => {
    const q = value.trim();
    if (q && !busy) onAsk(q);
  };

  return (
    <section className="card p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="flex items-end gap-3"
      >
        <WandSparkles className="mb-2.5 h-5 w-5 shrink-0 text-accent" aria-hidden />
        <textarea
          ref={input}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          maxLength={500}
          placeholder={followUp ? "Refine the last result, e.g. “only for Europe”…" : "Ask a question about your data…"}
          className="min-h-[40px] flex-1 resize-none bg-transparent py-2 text-[15px] outline-none placeholder:text-ink-3"
          aria-label="Question"
          data-testid="question-input"
        />
        {busy ? (
          <button type="button" className="btn-ghost border border-line" onClick={onCancel} data-testid="cancel">
            <Square className="h-3.5 w-3.5" /> Stop
          </button>
        ) : (
          <button type="submit" className="btn-primary" disabled={!text.trim()} data-testid="ask">
            Ask <CornerDownLeft className="h-4 w-4" />
          </button>
        )}
      </form>
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
        {canFollowUp && (
          <label className="mr-1 inline-flex cursor-pointer items-center gap-1.5 text-xs text-ink-2">
            <input type="checkbox" checked={followUp} onChange={(e) => onFollowUpChange(e.target.checked)} className="accent-[var(--accent)]" data-testid="follow-up" />
            <CornerUpRight className="h-3.5 w-3.5" /> Follow-up on last result
          </label>
        )}
        {!busy &&
          suggestions.map((s) => (
            <button key={s} type="button" className="chip" onClick={() => {
                setText(s);
                submit(s);
              }} data-testid="suggestion">
              {s}
            </button>
          ))}
      </div>
    </section>
  );
});
