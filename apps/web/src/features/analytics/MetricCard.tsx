import { useId } from "react";

import type { MetricContract, MetricPoint, MetricResult, MetricSelection } from "./types";

const STATES = {
  value: "Disponible",
  not_applicable: "No aplica",
  not_calculable: "No calculable",
};
const COVERAGE = {
  complete: "Cobertura completa",
  partial: "Cobertura parcial",
  unavailable: "No disponible",
};
const UNITS: Record<string, string> = {
  count: "conteo",
  seconds: "segundos",
  minutes: "minutos",
  percentage_points: "%",
  quantity: "cantidad",
};

function exactValue(value: string | number | null): string {
  if (value === null) return "—";
  // Formato textual: jamás convertir un Decimal monetario en un double ni recalcularlo.
  const [whole = "", fraction] = String(value).split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".")}${fraction !== undefined ? `,${fraction}` : ""}`;
}

function unitLabel(metric: MetricResult, point: MetricPoint, selection: MetricSelection): string {
  if (metric.unit === "money")
    return point.dimensions.currency ?? selection.filters.currency ?? "moneda no informada";
  if (metric.unit === "quantity")
    return `unidad ${point.dimensions.unit_id ?? selection.filters.unit_id ?? "no informada"}`;
  return UNITS[metric.unit] ?? metric.unit;
}

export function MetricCard({
  metric,
  definition,
  selection,
}: {
  metric: MetricResult;
  definition: MetricContract;
  selection: MetricSelection;
}) {
  const heading = useId();
  const points = metric.points;
  // Cada barra es un valor ya calculado por el backend. Escala por partición, nunca agrega.
  const partition = (p: MetricPoint) =>
    [
      p.dimensions.currency ?? selection.filters.currency,
      p.dimensions.resource_id ?? selection.filters.resource_id,
      p.dimensions.unit_id ?? selection.filters.unit_id,
    ].join(":");
  const maxima = new Map<string, number>();
  for (const point of points) {
    const value = Math.abs(Number(point.value));
    if (point.value !== null && Number.isFinite(value))
      maxima.set(partition(point), Math.max(maxima.get(partition(point)) ?? 0, value));
  }
  return (
    <article className="analytics-card" aria-labelledby={heading}>
      <div className="analytics-card-heading">
        <h3 id={heading}>{definition.label}</h3>
        <span className={`analytics-coverage analytics-coverage--${metric.coverage}`}>
          {COVERAGE[metric.coverage]}
        </span>
      </div>
      {metric.provisional && <p className="analytics-warning">Provisional · periodo abierto</p>}
      {points.length === 1 && points[0] && (
        <p className="analytics-kpi">
          {exactValue(points[0].value)} <small>{unitLabel(metric, points[0], selection)}</small>
        </p>
      )}
      {points.length === 0 && (
        <p>
          {metric.coverage === "complete"
            ? "Sin grupos para esta selección."
            : "No hay evidencia suficiente para esta selección."}
        </p>
      )}
      {metric.coverage_reason && (
        <p className="analytics-warning">
          Motivo: <code>{metric.coverage_reason}</code>
        </p>
      )}
      {metric.coverage_from && (
        <p className="analytics-muted">Evidencia desde {metric.coverage_from}</p>
      )}
      {points.length > 1 && (
        <figure className="analytics-chart" aria-label={`Gráfico de ${definition.label}`}>
          <figcaption>
            Valores por grupo · escala independiente por moneda, recurso y unidad. Tabla completa
            debajo.
          </figcaption>
          <div aria-hidden="true">
            {points.slice(0, 12).map((point, index) => {
              const value = Number(point.value);
              const max = maxima.get(partition(point)) ?? 0;
              const width =
                point.value !== null && max > 0 && Number.isFinite(value)
                  ? (Math.abs(value) / max) * 100
                  : 0;
              return (
                <div className="analytics-bar-row" key={index}>
                  <span>{Object.values(point.dimensions).join(" · ") || "Total"}</span>
                  <div className="analytics-bar-track">
                    <span
                      className={
                        value < 0 ? "analytics-bar analytics-bar--negative" : "analytics-bar"
                      }
                      style={{ width: `${String(width)}%` }}
                    />
                  </div>
                  <span>
                    {exactValue(point.value)} {unitLabel(metric, point, selection)}
                  </span>
                </div>
              );
            })}
          </div>
          {points.length > 12 && (
            <p>El gráfico muestra los primeros 12 grupos; la tabla conserva todos.</p>
          )}
        </figure>
      )}
      {points.length > 0 && (
        <div
          className="analytics-table-wrap"
          tabIndex={0}
          role="region"
          aria-label={`Tabla de ${definition.label}`}
        >
          <table>
            <caption>
              {definition.label} · valores entregados por {definition.owner}
            </caption>
            <thead>
              <tr>
                <th scope="col">Grupo</th>
                <th scope="col">Valor</th>
                <th scope="col">Unidad / moneda</th>
                <th scope="col">Estado</th>
                <th scope="col">Muestra / elegibles</th>
              </tr>
            </thead>
            <tbody>
              {points.map((point, index) => (
                <tr key={index}>
                  <th scope="row">
                    {Object.entries(point.dimensions)
                      .map(([key, value]) => `${key}: ${value}`)
                      .join(" · ") || "Total"}
                  </th>
                  <td>{exactValue(point.value)}</td>
                  <td>{unitLabel(metric, point, selection)}</td>
                  <td>{STATES[point.status]}</td>
                  <td>
                    {point.sample_size === null ? "—" : exactValue(point.sample_size)} /{" "}
                    {point.eligible_count === null ? "—" : exactValue(point.eligible_count)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details>
        <summary>Contrato y procedencia</summary>
        <p>
          <code>
            {definition.metric_id}@{String(definition.metric_version)}
          </code>
        </p>
        <p>{definition.formula}</p>
        <p>
          Grano: {definition.grain} · modo {definition.temporal_mode}
        </p>
        <p>{definition.coverage_rule}</p>
        {metric.exclusions.length > 0 && <p>Exclusiones: {metric.exclusions.join("; ")}</p>}
      </details>
    </article>
  );
}
