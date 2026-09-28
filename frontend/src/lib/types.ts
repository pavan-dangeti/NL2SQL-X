export type Cell = string | number | null;

export type ChartType = "line" | "area" | "bar" | "pie" | "metric" | "table";

export type Stage = "schema" | "cache" | "generating" | "repairing" | "validating" | "running" | "done";

export interface ChartSpec {
  type: ChartType;
  x: string | null;
  y: string[];
}

export interface QueryResult {
  question: string;
  sql: string;
  sql_pretty: string;
  explanation: string | null;
  columns: string[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  chart: ChartSpec;
  insights: string[];
  timings: { llm_ms: number; db_ms: number; total_ms: number };
  model: string | null;
  repaired: boolean;
  cached: boolean;
  history_id: number | null;
}

export interface Dataset {
  id: string;
  name: string;
  tables: string[];
  row_count: number;
  size_bytes: number;
  created_at: string;
  builtin: boolean;
}

export interface Column {
  name: string;
  type: string;
  primary_key: boolean;
  nullable: boolean;
  values: string[] | null;
  min: string | number | null;
  max: string | number | null;
}

export interface Table {
  name: string;
  row_count: number;
  columns: Column[];
  foreign_keys: { column: string; references_table: string; references_column: string }[];
}

export interface HistoryItem {
  id: number;
  question: string;
  sql: string | null;
  row_count: number | null;
  status: "ok" | "error";
  error: string | null;
  duration_ms: number;
  created_at: string;
}

export interface Pin {
  id: string;
  dataset_id: string;
  title: string;
  question: string;
  sql: string;
  chart_type: ChartType;
  created_at: string;
}

export interface Meta {
  version: string;
  llm: string;
  demo_mode: boolean;
  max_result_rows: number;
  max_upload_mb: number;
  query_timeout_ms: number;
}
