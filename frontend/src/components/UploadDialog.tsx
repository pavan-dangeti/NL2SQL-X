import { FileSpreadsheet, Loader2, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { formatBytes } from "../lib/format";
import type { Dataset } from "../lib/types";

interface Props {
  maxMb: number;
  onClose: () => void;
  onUploaded: (dataset: Dataset) => void;
}

export function UploadDialog({ maxMb, onClose, onUploaded }: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const total = files.reduce((n, f) => n + f.size, 0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const add = (list: FileList | null) => {
    if (!list) return;
    const picked = Array.from(list).filter((f) => /\.(csv|tsv|txt)$/i.test(f.name));
    setError(picked.length < list.length ? "Only .csv, .tsv and .txt files are supported." : null);
    setFiles((current) => [...current, ...picked].slice(0, 10));
    if (!name && picked[0]) setName(picked[0].name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "));
  };

  const submit = async () => {
    if (!files.length || total > maxMb * 1024 * 1024) return;
    setBusy(true);
    setError(null);
    try {
      onUploaded(await api.upload(name, files));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="upload-title" className="card w-full max-w-lg p-5 shadow-2xl">
        <div className="flex items-center justify-between">
          <h2 id="upload-title" className="text-base font-semibold">
            Query your own data
          </h2>
          <button type="button" className="btn-ghost px-2" onClick={onClose} disabled={busy} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-1 text-sm text-ink-2">Upload one or more CSV files. Each file becomes a table you can join. Uploads are private to this browser and expire after 7 days.</p>

        <button
          type="button"
          onClick={() => picker.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            add(e.dataTransfer.files);
          }}
          className={`mt-4 flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-sm transition-colors ${dragging ? "border-accent bg-accent/5" : "border-line hover:border-accent"}`}
        >
          <Upload className="h-6 w-6 text-accent" />
          <span>
            <span className="font-medium text-accent">Choose files</span> or drag them here
          </span>
          <span className="text-xs text-ink-3">CSV, TSV or TXT · up to {maxMb} MB in total</span>
        </button>
        <input ref={picker} type="file" accept=".csv,.tsv,.txt,text/csv" multiple hidden onChange={(e) => add(e.target.files)} data-testid="upload-input" />

        {files.length > 0 && (
          <ul className="mt-3 space-y-1">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex items-center gap-2 rounded-md bg-panel-2 px-3 py-1.5 text-sm">
                <FileSpreadsheet className="h-4 w-4 text-ok" />
                <span className="truncate">{f.name}</span>
                <span className="ml-auto text-xs text-ink-3">{formatBytes(f.size)}</span>
                <button type="button" className="text-ink-3 hover:text-bad" onClick={() => setFiles(files.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`}>
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <label className="mt-4 block text-sm">
          <span className="label">Dataset name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} className="mt-1 w-full rounded-lg border border-line bg-panel px-3 py-2 outline-none focus:border-accent" placeholder="e.g. Q3 sales" data-testid="dataset-name" />
        </label>

        {total > maxMb * 1024 * 1024 && <p className="mt-3 text-sm text-bad">The selected files are larger than {maxMb} MB.</p>}
        {error && (
          <p className="mt-3 text-sm text-bad" role="alert">
            {error}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={submit} disabled={busy || !files.length || total > maxMb * 1024 * 1024} data-testid="upload-submit">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Upload
          </button>
        </div>
      </div>
    </div>
  );
}
