import type { MetricContract, MetricSelection } from "./types";

export interface TemporalSelection {
  timezone: string;
  start: string;
  end: string;
  asOf: string;
  periodId: string;
}

export function civilDate(instant: string, timezone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(instant));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year ?? ""}-${values.month ?? ""}-${values.day ?? ""}`;
}

function calendarDate(value: string): Date {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("Indique una fecha válida.");
  const result = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(result.valueOf()) || result.toISOString().slice(0, 10) !== value)
    throw new Error("Indique una fecha válida.");
  return result;
}

export function civilMidnight(date: string, timezone: string): string {
  const wall = calendarDate(date).valueOf();
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const renderWall = (instant: number) => {
    const p = Object.fromEntries(
      formatter.formatToParts(new Date(instant)).map((v) => [v.type, v.value]),
    );
    return Date.UTC(
      Number(p.year),
      Number(p.month) - 1,
      Number(p.day),
      Number(p.hour),
      Number(p.minute),
      Number(p.second),
    );
  };
  // Offset a ambos lados de una transición; se valida por round-trip, no se asumen días de 24 h.
  const offsets = new Set(
    [-36, 0, 36].map((h) => renderWall(wall + h * 3600000) - (wall + h * 3600000)),
  );
  const candidates = [...offsets]
    .map((offset) => wall - offset)
    .filter((v) => renderWall(v) === wall);
  if (candidates.length !== 1)
    throw new Error(
      "La medianoche es ambigua o inexistente en esta zona. Elija otro borde de fecha.",
    );
  return new Date(candidates[0] ?? NaN).toISOString();
}

export function previousRange(kind: "day" | "week" | "month", now: string, timezone: string) {
  const end = calendarDate(civilDate(now, timezone));
  if (kind === "week") end.setUTCDate(end.getUTCDate() - ((end.getUTCDay() + 6) % 7));
  if (kind === "month") end.setUTCDate(1);
  const start = new Date(end);
  if (kind === "month") start.setUTCMonth(start.getUTCMonth() - 1);
  else start.setUTCDate(start.getUTCDate() - (kind === "week" ? 7 : 1));
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

export function reportTemporal(selection: MetricSelection[], timezone: string): TemporalSelection {
  const common = (key: "period_start" | "period_end" | "as_of_at" | "operational_period_id") => {
    const values = [...new Set(selection.map((row) => row[key]).filter((value) => value !== null))];
    return values.length === 1 ? (values[0] ?? "") : "";
  };
  const date = (key: "period_start" | "period_end") => {
    const instant = common(key);
    if (!instant) return "";
    const civil = civilDate(instant, timezone);
    // No redondear un rango arbitrario guardado hasta la medianoche del día.
    return Date.parse(civilMidnight(civil, timezone)) === Date.parse(instant) ? civil : "";
  };
  return {
    timezone,
    start: date("period_start"),
    end: date("period_end"),
    asOf: common("as_of_at"),
    periodId: common("operational_period_id"),
  };
}

export function buildSelection(
  metric: MetricContract,
  temporal: TemporalSelection,
  dimensions: string[],
  filters: Record<string, string>,
): MetricSelection {
  const mode = metric.temporal_mode;
  const needsRange = mode === "F" || mode === "SI" || mode === "C";
  const start = needsRange ? civilMidnight(temporal.start, temporal.timezone) : null;
  const end = needsRange ? civilMidnight(temporal.end, temporal.timezone) : null;
  if (start !== null && end !== null && start >= end)
    throw new Error("El inicio debe ser anterior al fin exclusivo.");
  const asOf = mode === "F" ? null : temporal.asOf;
  if (asOf !== null && (!/(Z|[+-]\d{2}:\d{2})$/.test(asOf) || Number.isNaN(Date.parse(asOf))))
    throw new Error("El estado al corte requiere un instante ISO con offset o Z.");
  if (mode === "C" && end !== null && Date.parse(end) > Date.parse(asOf ?? ""))
    throw new Error("La cohorte debe terminar antes o en el instante de observación.");
  if (mode === "FP" && !temporal.periodId) throw new Error("Seleccione un periodo de Finance.");
  return {
    metric_id: metric.metric_id,
    metric_version: metric.metric_version,
    dimensions: [
      ...new Set([...dimensions, ...metric.required_dimensions.filter((key) => !filters[key])]),
    ],
    filters: Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== "")),
    period_start: start,
    period_end: end,
    as_of_at: asOf,
    operational_period_id: mode === "FP" ? temporal.periodId : null,
  };
}
