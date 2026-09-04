// Fixture local aislada. No se importa desde main.tsx ni forma parte del build de producto.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/inter/400.css";
import "@fontsource/inter/600.css";
import "@fontsource/plus-jakarta-sans/700.css";
import { AnalyticsView } from "../features/analytics/AnalyticsView";
import type { Catalog, MetricSelection } from "../features/analytics/types";
import "../styles.css";

if (!import.meta.env.DEV) throw new Error("La fixture visual no admite ejecución productiva.");
const catalog: Catalog = {
  catalog_version: "p15-v1",
  catalog_hash: "a".repeat(64),
  profile: "commercial",
  capabilities: [
    "read_dashboard",
    "execute_report",
    "manage_own_report",
    "create_export",
    "download_export",
  ].map((value) => `analytics:${value}`),
  timezone: "America/Guayaquil",
  currency: "USD",
  server_now: "2026-09-04T12:00:00Z",
  periods: [],
  preset: ["request_created_count", "accepted_quote_amount"],
  metrics: [
    {
      metric_id: "request_created_count",
      metric_version: 1,
      owner: "commercial",
      label: "Solicitudes creadas",
      formula: "Conteo de creaciones autoritativas",
      grain: "event_request",
      dimensions: ["time_bucket", "origin"],
      required_dimensions: [],
      temporal_mode: "F",
      unit: "count",
      scale: 0,
      coverage_rule: "Creaciones con evidencia histórica",
    },
    {
      metric_id: "accepted_quote_amount",
      metric_version: 1,
      owner: "commercial",
      label: "Importe de cotizaciones aceptadas",
      formula: "Total de versiones aceptadas por moneda",
      grain: "quotation_version",
      dimensions: ["currency"],
      required_dimensions: ["currency"],
      temporal_mode: "F",
      unit: "money",
      scale: 2,
      coverage_rule: "Aceptaciones con evidencia histórica",
    },
  ],
};

window.fetch = (input, init) => {
  const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const json = (value: unknown, status = 200) =>
    Promise.resolve(
      new Response(JSON.stringify(value), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
  if (path === "/api/v1/auth/csrf/") return json({ csrf_token: "synthetic-visual-only" });
  if (path.endsWith("/dashboards/query/")) {
    const body = JSON.parse(typeof init?.body === "string" ? init.body : "{}") as {
      metrics: MetricSelection[];
    };
    return json({
      catalog_hash: catalog.catalog_hash,
      catalog_version: catalog.catalog_version,
      timezone: catalog.timezone,
      executed_at: catalog.server_now,
      knowledge_cutoff_at: catalog.server_now,
      selection: body.metrics,
      metrics: body.metrics.map((metric) => ({
        metric_id: metric.metric_id,
        metric_version: 1,
        unit: metric.metric_id === "request_created_count" ? "count" : "money",
        coverage: metric.metric_id === "request_created_count" ? "complete" : "partial",
        coverage_from: null,
        coverage_reason:
          metric.metric_id === "request_created_count" ? null : "legacy_evidence_missing",
        provisional: false,
        exclusions: [],
        points:
          metric.metric_id === "request_created_count"
            ? [
                {
                  dimensions: {},
                  value: 42,
                  status: "value",
                  eligible_count: null,
                  sample_size: null,
                },
              ]
            : [
                {
                  dimensions: { currency: "USD" },
                  value: "25400.00",
                  status: "value",
                  eligible_count: null,
                  sample_size: null,
                },
                {
                  dimensions: { currency: "EUR" },
                  value: "3200.00",
                  status: "value",
                  eligible_count: null,
                  sample_size: null,
                },
              ],
      })),
    });
  }
  if (init?.method === "POST")
    return json({ error: { message: "Fixture visual: no persiste ni genera artefactos." } }, 409);
  return json({ results: [], next_cursor: null });
};

export function VisualFrame() {
  const [width, setWidth] = useState(320);
  return (
    <div style={{ padding: "1rem" }}>
      <h1>QA P15 · Datos sintéticos</h1>
      <p>No es evidencia de backend, p95 ni LCP productivo.</p>
      <label>
        Ancho de prueba
        <select
          value={width}
          onChange={(event) => {
            setWidth(Number(event.target.value));
          }}
        >
          <option value={320}>320 px</option>
          <option value={1280}>1280 px</option>
        </select>
      </label>
      <iframe
        title={`Analítica · ${String(width)} px`}
        src="/p15-visual.html?frame=1"
        style={{
          display: "block",
          width,
          height: 900,
          border: "1px solid #94a3b8",
          marginTop: "1rem",
        }}
      />
    </div>
  );
}
const root = document.getElementById("root");
if (!root) throw new Error("Missing visual fixture root");
createRoot(root).render(
  new URLSearchParams(location.search).has("frame") ? (
    <main style={{ padding: "12px" }}>
      <AnalyticsView organizationId="synthetic-tenant" catalog={catalog} />
    </main>
  ) : (
    <VisualFrame />
  ),
);
