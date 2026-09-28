import type { Cell } from "./types";

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const full = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

export function formatCell(value: Cell): string {
  if (value === null) return "—";
  if (typeof value === "number") return Number.isInteger(value) && Math.abs(value) < 10000 ? String(value) : full.format(value);
  return value;
}

export function formatCompact(value: number): string {
  return Math.abs(value) >= 10000 ? compact.format(value) : full.format(value);
}

export function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function humanize(column: string): string {
  const text = column.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const seconds = Math.round((now.getTime() - then.getTime()) / 1000);
  if (Number.isNaN(seconds)) return "";
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function csvEscape(value: Cell): string {
  if (value === null) return "";
  let text = String(value);
  if (/^[=+\-@\t\r]/.test(text) && typeof value === "string") text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(columns: string[], rows: Cell[][]): string {
  return [columns, ...rows].map((row) => row.map(csvEscape).join(",")).join("\r\n");
}

function compareCells(a: Cell, b: Cell): number {
  if (a === b) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

export function sortRows(rows: Cell[][], index: number, direction: "asc" | "desc"): Cell[][] {
  const sign = direction === "asc" ? 1 : -1;
  return rows
    .map((row, i) => [row, i] as const)
    .sort((a, b) => {
      const x = a[0][index];
      const y = b[0][index];
      if (x === null || y === null) return x === y ? a[1] - b[1] : x === null ? 1 : -1;
      return sign * compareCells(x, y) || a[1] - b[1];
    })
    .map(([row]) => row);
}

const KEYWORDS = new Set(
  (
    "select from where join left right inner outer full cross on and or not in is null as group by order having " +
    "limit offset union all distinct case when then else end with asc desc between like exists count sum avg min " +
    "max round date strftime cast coalesce ifnull substr lower upper julianday over partition recursive"
  ).split(" "),
);

type Token = { text: string; kind: "keyword" | "string" | "number" | "comment" | "plain" };

export function tokenizeSql(sql: string): Token[] {
  const tokens: Token[] = [];
  const pattern = /(--[^\n]*)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+|[^\sA-Za-z0-9_']+|')/g;
  for (const m of sql.matchAll(pattern)) {
    if (m[1]) tokens.push({ text: m[1], kind: "comment" });
    else if (m[2]) tokens.push({ text: m[2], kind: "string" });
    else if (m[3]) tokens.push({ text: m[3], kind: "number" });
    else if (m[4]) tokens.push({ text: m[4], kind: KEYWORDS.has(m[4].toLowerCase()) ? "keyword" : "plain" });
    else tokens.push({ text: m[0], kind: "plain" });
  }
  return tokens;
}
