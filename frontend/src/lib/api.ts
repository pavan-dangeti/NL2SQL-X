import type { ChartType, Dataset, HistoryItem, Meta, Pin, QueryResult, Stage, Table } from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const CLIENT_KEY = "nl2sql.client";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get retriable(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }
}

let memoryClient: string | null = null;

export function clientId(): string {
  try {
    const existing = localStorage.getItem(CLIENT_KEY);
    if (existing && /^[A-Za-z0-9_-]{8,64}$/.test(existing)) return existing;
    const fresh = crypto.randomUUID();
    localStorage.setItem(CLIENT_KEY, fresh);
    return fresh;
  } catch {
    memoryClient ??= crypto.randomUUID();
    return memoryClient;
  }
}

export function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

function failure(status: number, body: unknown): ApiError {
  const detail = (body ?? {}) as { detail?: unknown; code?: string };
  const message =
    typeof detail.detail === "string"
      ? detail.detail
      : status >= 500
        ? "The server had a problem. Please try again."
        : `Request failed (${status}).`;
  return new ApiError(message, status, detail.code ?? null);
}

async function send(path: string, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-Client-Id", clientId());
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  try {
    return await fetch(`${BASE}${path}`, { ...init, headers });
  } catch (err) {
    if (isAbort(err)) throw err;
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0, "network");
  }
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await send(path, init);
  if (response.status === 204) return undefined as T;
  const body = await readJson(response);
  if (!response.ok) throw failure(response.status, body);
  return body as T;
}

export function parseEvents(buffer: string): { events: { event: string; data: string }[]; rest: string } {
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  const events = [];
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}

export interface Previous {
  question: string;
  sql: string;
}

async function ask(
  question: string,
  datasetId: string,
  previous: Previous | null,
  onStage: (stage: Stage) => void,
  signal?: AbortSignal,
): Promise<QueryResult> {
  const response = await send("/api/v1/query", {
    method: "POST",
    headers: { Accept: "text/event-stream" },
    body: JSON.stringify({ question, dataset_id: datasetId, previous }),
    signal,
  });
  const type = response.headers.get("content-type") ?? "";
  if (!type.includes("text/event-stream") || !response.body) {
    const body = await readJson(response);
    if (!response.ok) throw failure(response.status, body);
    return body as QueryResult;
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseEvents(buffer + value);
    buffer = parsed.rest;
    for (const { event, data } of parsed.events) {
      const payload = JSON.parse(data);
      if (event === "stage") onStage(payload.stage as Stage);
      else if (event === "result") return payload as QueryResult;
      else if (event === "error") throw failure(payload.status ?? 500, payload);
    }
  }
  throw new ApiError("The connection closed before the answer arrived. Please try again.", 0, "network");
}

const q = encodeURIComponent;

export const api = {
  meta: () => request<Meta>("/api/v1/meta"),
  datasets: () => request<Dataset[]>("/api/v1/datasets"),
  schema: (id: string) => request<{ tables: Table[] }>(`/api/v1/datasets/${q(id)}/schema`),
  suggestions: (id: string) => request<string[]>(`/api/v1/datasets/${q(id)}/suggestions`),
  preview: (id: string, table: string, signal?: AbortSignal) =>
    request<QueryResult>(`/api/v1/datasets/${q(id)}/tables/${q(table)}/preview?limit=50`, { signal }),
  history: (id: string) => request<HistoryItem[]>(`/api/v1/history?dataset_id=${q(id)}`),
  clearHistory: (id: string) => request<void>(`/api/v1/history?dataset_id=${q(id)}`, { method: "DELETE" }),
  ask,
  runSql: (sql: string, datasetId: string, signal?: AbortSignal) =>
    request<QueryResult>("/api/v1/sql", { method: "POST", body: JSON.stringify({ sql, dataset_id: datasetId }), signal }),
  upload: (name: string, files: File[]) => {
    const form = new FormData();
    form.append("name", name);
    for (const f of files) form.append("files", f);
    return request<Dataset>("/api/v1/datasets", { method: "POST", body: form });
  },
  deleteDataset: (id: string) => request<void>(`/api/v1/datasets/${q(id)}`, { method: "DELETE" }),
  pins: (datasetId: string) => request<Pin[]>(`/api/v1/pins?dataset_id=${q(datasetId)}`),
  pin: (body: { dataset_id: string; title: string; question: string; sql: string; chart_type: ChartType }) =>
    request<Pin>("/api/v1/pins", { method: "POST", body: JSON.stringify(body) }),
  runPin: (id: string, signal?: AbortSignal) =>
    request<{ pin: Pin; result: QueryResult }>(`/api/v1/pins/${q(id)}/run`, { method: "POST", signal }),
  renamePin: (id: string, title: string) =>
    request<void>(`/api/v1/pins/${q(id)}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  unpin: (id: string) => request<void>(`/api/v1/pins/${q(id)}`, { method: "DELETE" }),
};
