export type TemporalMode = "F" | "S" | "SI" | "C" | "FP";
export interface HistoryPage<T> {
  results: T[];
  next_cursor: string | null;
}
export interface MetricContract {
  metric_id: string;
  metric_version: number;
  owner: string;
  label: string;
  formula: string;
  grain: string;
  dimensions: string[];
  required_dimensions: string[];
  temporal_mode: TemporalMode;
  unit: string;
  scale: number;
  coverage_rule: string;
}
export interface MetricSelection {
  metric_id: string;
  metric_version: number;
  dimensions: string[];
  filters: Record<string, string>;
  period_start: string | null;
  period_end: string | null;
  as_of_at: string | null;
  operational_period_id: string | null;
}
export interface Period {
  id: string;
  starts_on: string;
  ends_on: string;
  currency: string;
  closed: boolean;
}
export interface Catalog {
  catalog_version: string;
  catalog_hash: string;
  profile: string;
  capabilities: string[];
  metrics: MetricContract[];
  preset: string[];
  timezone: string;
  currency: string;
  server_now: string;
  periods: Period[];
}
export interface MetricPoint {
  dimensions: Record<string, string>;
  value: string | number | null;
  status: "value" | "not_applicable" | "not_calculable";
  sample_size: number | null;
  eligible_count: number | null;
}
export interface MetricResult {
  metric_id: string;
  metric_version: number;
  unit: string;
  coverage: "complete" | "partial" | "unavailable";
  coverage_from: string | null;
  coverage_reason: string | null;
  provisional: boolean;
  exclusions: string[];
  points: MetricPoint[];
}
export interface QueryResult {
  catalog_hash: string;
  catalog_version: string;
  timezone: string;
  executed_at: string;
  knowledge_cutoff_at: string;
  selection: MetricSelection[];
  metrics: MetricResult[];
}
export interface SavedReport {
  id: string;
  revision_id: string;
  revision: number;
  title: string;
  visibility: "private" | "organization";
  timezone: string;
  selection: MetricSelection[];
  archived: boolean;
  owner_membership_id: string;
}
export interface Execution {
  id: string;
  report_revision_id: string | null;
  executed_at: string;
  knowledge_cutoff_at: string;
  result_sha256: string;
  row_count: number;
  timezone: string;
  result?: QueryResult;
}
export interface ExportJob {
  id: string;
  execution_id: string;
  format: "csv" | "xlsx" | "pdf";
  state: "queued" | "running" | "retry" | "completed" | "terminal";
  attempt_count: number;
  error_code: string | null;
  created_at: string;
  next_attempt_at: string | null;
}
