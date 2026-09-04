import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../../api";
import { AnalyticsView } from "./AnalyticsView";
import { MetricCard } from "./MetricCard";
import { buildSelection, civilMidnight, previousRange, reportTemporal } from "./temporal";
import type {
  Catalog,
  MetricContract,
  MetricResult,
  MetricSelection,
  QueryResult,
  SavedReport,
} from "./types";

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  api: vi.fn(),
}));
const metric: MetricContract = {
  metric_id: "request_created_count",
  metric_version: 1,
  owner: "commercial",
  label: "Solicitudes creadas",
  formula: "count distinct",
  grain: "event_request",
  dimensions: ["time_bucket", "origin"],
  required_dimensions: [],
  temporal_mode: "F",
  unit: "count",
  scale: 0,
  coverage_rule: "historia autoritativa",
};

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== "string") throw new Error("Expected JSON request body");
  return JSON.parse(body) as unknown;
}
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
  ].map((v) => `analytics:${v}`),
  metrics: [metric],
  preset: [metric.metric_id],
  timezone: "America/Guayaquil",
  currency: "USD",
  server_now: "2026-09-04T12:00:00Z",
  periods: [],
};
const selection: MetricSelection = {
  metric_id: metric.metric_id,
  metric_version: 1,
  dimensions: [],
  filters: {},
  period_start: "2026-08-01T05:00:00Z",
  period_end: "2026-09-01T05:00:00Z",
  as_of_at: null,
  operational_period_id: null,
};
const metricResult: MetricResult = {
  metric_id: metric.metric_id,
  metric_version: 1,
  unit: "count",
  coverage: "complete",
  coverage_from: null,
  coverage_reason: null,
  provisional: false,
  exclusions: [],
  points: [{ dimensions: {}, value: 2, status: "value", sample_size: null, eligible_count: null }],
};
const result: QueryResult = {
  catalog_hash: catalog.catalog_hash,
  catalog_version: catalog.catalog_version,
  timezone: catalog.timezone,
  executed_at: catalog.server_now,
  knowledge_cutoff_at: catalog.server_now,
  selection: [selection],
  metrics: [metricResult],
};
const saved: SavedReport = {
  id: "report-1",
  revision_id: "revision-1",
  revision: 1,
  title: "Embudo mensual",
  visibility: "private",
  timezone: catalog.timezone,
  selection: [selection],
  archived: false,
  owner_membership_id: "membership-1",
};

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((path, init) => {
    if (path.endsWith("/dashboards/query/")) return Promise.resolve(result);
    if (path.endsWith("/reports/") && init?.method === "POST") return Promise.resolve(saved);
    if (path.endsWith("/reports/")) return Promise.resolve({ results: [saved], next_cursor: null });
    if (path.endsWith("/executions/") && init?.method === "POST")
      return Promise.resolve({
        id: "execution-1",
        report_revision_id: null,
        executed_at: catalog.server_now,
        knowledge_cutoff_at: catalog.server_now,
        result_sha256: "b".repeat(64),
        row_count: 1,
        timezone: catalog.timezone,
        result,
      });
    if (path.endsWith("/executions/")) return Promise.resolve({ results: [], next_cursor: null });
    if (path.endsWith("/exports/")) return Promise.resolve({ results: [], next_cursor: null });
    return Promise.reject(new Error(`Unexpected test route: ${path}`));
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Temporal P15", () => {
  it("muestra fechas comunes sin redondear rangos arbitrarios guardados", () => {
    expect(reportTemporal([selection], catalog.timezone).start).toBe("2026-08-01");
    const arbitrary = { ...selection, period_start: "2026-08-01T11:43:18Z" };
    expect(reportTemporal([arbitrary], catalog.timezone).start).toBe("");
    expect(reportTemporal([selection, arbitrary], catalog.timezone).start).toBe("");
  });
  it("convierte días civiles DST de 23 y 25 horas con bordes exclusivos", () => {
    const hours = (a: string, b: string) =>
      (Date.parse(civilMidnight(b, "America/New_York")) -
        Date.parse(civilMidnight(a, "America/New_York"))) /
      3600000;
    expect(hours("2026-03-08", "2026-03-09")).toBe(23);
    expect(hours("2026-11-01", "2026-11-02")).toBe(25);
    expect(civilMidnight("2026-09-04", "America/Guayaquil")).toBe("2026-09-04T05:00:00.000Z");
  });
  it("no normaliza silenciosamente una medianoche inexistente ni fechas inválidas", () => {
    expect(() => civilMidnight("2011-12-30", "Pacific/Apia")).toThrow("ambigua o inexistente");
    expect(() => civilMidnight("2026-02-30", "UTC")).toThrow("fecha válida");
    expect(() => civilMidnight("2026-02-01", "Unknown/Zone")).toThrow();
  });
  it("mes civil y semana ISO no equivalen a cantidades fijas de segundos", () => {
    expect(previousRange("month", "2024-03-04T12:00:00Z", "UTC")).toEqual({
      start: "2024-02-01",
      end: "2024-03-01",
    });
    expect(previousRange("week", "2026-09-04T12:00:00Z", "UTC")).toEqual({
      start: "2026-08-24",
      end: "2026-08-31",
    });
  });
  it("F omite as_of, S no envía rango, C valida el orden y FP exige periodo", () => {
    const time = {
      timezone: "UTC",
      start: "2026-08-01",
      end: "2026-09-01",
      asOf: catalog.server_now,
      periodId: "",
    };
    expect(buildSelection(metric, time, [], {}).as_of_at).toBeNull();
    expect(buildSelection({ ...metric, temporal_mode: "S" }, time, [], {}).period_start).toBeNull();
    expect(() =>
      buildSelection(
        { ...metric, temporal_mode: "C" },
        { ...time, asOf: "2026-08-30T12:00:00Z" },
        [],
        {},
      ),
    ).toThrow("cohorte");
    expect(() => buildSelection({ ...metric, temporal_mode: "FP" }, time, [], {})).toThrow(
      "Finance",
    );
    expect(() =>
      buildSelection(
        { ...metric, temporal_mode: "S" },
        { ...time, asOf: "2026-09-04T12:00:00" },
        [],
        {},
      ),
    ).toThrow("offset");
  });
});

describe("Analítica P15", () => {
  it("carga otra página con su cursor sin sustituir la primera", async () => {
    vi.mocked(api).mockImplementation((path) => {
      if (path.includes("/reports/?cursor="))
        return Promise.resolve({
          results: [{ ...saved, id: "report-2", title: "Reporte anterior" }],
          next_cursor: null,
        });
      if (path.endsWith("/reports/"))
        return Promise.resolve({ results: [saved], next_cursor: "signed cursor" });
      if (path.endsWith("/dashboards/query/")) return Promise.resolve(result);
      return Promise.resolve({ results: [], next_cursor: null });
    });
    render(<AnalyticsView organizationId="tenant-a" catalog={catalog} />);
    await screen.findByText("Consulta interactiva, no persistida", { exact: false });
    fireEvent.click(screen.getByRole("button", { name: "Actualizar reportes e historial" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cargar más reportes" }));
    expect(await screen.findByRole("button", { name: "Cargar Reporte anterior" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Cargar Embudo mensual" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Cargar más reportes" })).not.toBeInTheDocument();
    expect(
      vi.mocked(api).mock.calls.some(([path]) => path.includes("cursor=signed%20cursor")),
    ).toBe(true);
  });
  it("editar un filtro conserva los instantes exactos de una revisión cargada", async () => {
    const exact = {
      ...selection,
      period_start: "2026-06-11T11:43:18Z",
      period_end: "2026-07-18T20:17:22Z",
    };
    vi.mocked(api).mockImplementation((path) =>
      Promise.resolve(
        path.endsWith("/reports/")
          ? { results: [{ ...saved, selection: [exact] }], next_cursor: null }
          : path.endsWith("/dashboards/query/")
            ? result
            : { results: [], next_cursor: null },
      ),
    );
    render(<AnalyticsView organizationId="tenant-a" catalog={catalog} />);
    await screen.findByText("Consulta interactiva, no persistida", { exact: false });
    fireEvent.click(screen.getByRole("button", { name: "Actualizar reportes e historial" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cargar Embudo mensual" }));
    fireEvent.click(screen.getByText(/Métricas y dimensiones ·/));
    fireEvent.click(screen.getByText("Dimensiones y filtros de Solicitudes creadas"));
    fireEvent.change(screen.getByRole("textbox", { name: "Filtro origin" }), {
      target: { value: "referral" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Consultar dashboard" }));
    await waitFor(() => {
      expect(
        vi.mocked(api).mock.calls.filter(([path]) => path.endsWith("/dashboards/query/")),
      ).toHaveLength(2);
    });
    const calls = vi.mocked(api).mock.calls.filter(([path]) => path.endsWith("/dashboards/query/"));
    expect(parseBody(calls[1]?.[1]?.body)).toEqual({
      timezone: catalog.timezone,
      metrics: [{ ...exact, filters: { origin: "referral" } }],
    });
  });
  it("consulta por perfil sin persistir ejecución ni aceptar cutoff del cliente", async () => {
    render(<AnalyticsView organizationId="tenant-a" catalog={catalog} />);
    expect(
      await screen.findByText("Consulta interactiva, no persistida", { exact: false }),
    ).toBeVisible();
    expect(screen.getByText("CENTRO DE CONTROL · Comercial")).toBeVisible();
    expect(api).toHaveBeenCalledTimes(1);
    const call = vi.mocked(api).mock.calls[0];
    const body = parseBody(call?.[1]?.body) as {
      metrics: MetricSelection[];
      knowledge_cutoff_at?: string;
    };
    expect(body.metrics[0]?.as_of_at).toBeNull();
    expect(body.knowledge_cutoff_at).toBeUndefined();
    expect(screen.queryByRole("option", { name: "Organización" })).not.toBeInTheDocument();
  });
  it("solo ofrece las métricas y dimensiones del catálogo autorizado", async () => {
    render(<AnalyticsView organizationId="tenant-a" catalog={catalog} />);
    await screen.findByText("Consulta interactiva, no persistida", { exact: false });
    fireEvent.click(screen.getByText("Métricas y dimensiones · 1 seleccionadas"));
    expect(screen.getByRole("checkbox", { name: /Solicitudes creadas/ })).toBeChecked();
    expect(screen.queryByText("Rentabilidad")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Filtro email")).not.toBeInTheDocument();
  });
  it("congela explícitamente y crea exports por execution_id con Idempotency-Key", async () => {
    render(<AnalyticsView organizationId="tenant-a" catalog={catalog} />);
    await screen.findByText("Consulta interactiva, no persistida", { exact: false });
    fireEvent.click(screen.getByRole("button", { name: "Ejecutar y congelar" }));
    expect(
      await screen.findByRole("button", { name: "Crear exportación de esta ejecución" }),
    ).toBeVisible();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Crear exportación de esta ejecución" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Crear exportación de esta ejecución" }));
    await waitFor(() => {
      expect(
        vi
          .mocked(api)
          .mock.calls.some(([path, init]) => path.endsWith("/exports/") && init?.method === "POST"),
      ).toBe(true);
    });
    const call = vi
      .mocked(api)
      .mock.calls.find(([path, init]) => path.endsWith("/exports/") && init?.method === "POST");
    expect(parseBody(call?.[1]?.body)).toEqual({
      execution_id: "execution-1",
      format: "csv",
    });
    expect(new Headers(call?.[1]?.headers).get("Idempotency-Key")).toMatch(/^[a-f0-9-]{36}$/);
  });
  it("carga una revisión y la ejecuta sin reemplazar sus parámetros", async () => {
    render(<AnalyticsView organizationId="tenant-a" catalog={catalog} />);
    await screen.findByText("Consulta interactiva, no persistida", { exact: false });
    fireEvent.click(screen.getByRole("button", { name: "Actualizar reportes e historial" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cargar Embudo mensual" }));
    fireEvent.click(screen.getByRole("button", { name: "Ejecutar y congelar" }));
    await waitFor(() => {
      expect(
        vi
          .mocked(api)
          .mock.calls.some(
            ([path, init]) => path.endsWith("/executions/") && init?.method === "POST",
          ),
      ).toBe(true);
    });
    const call = vi
      .mocked(api)
      .mock.calls.find(([path, init]) => path.endsWith("/executions/") && init?.method === "POST");
    expect(parseBody(call?.[1]?.body)).toEqual({ report_revision_id: "revision-1" });
  });
  it("muestra loading y limpia resultados al perder autorización", async () => {
    render(<AnalyticsView organizationId="tenant-a" catalog={catalog} />);
    expect(screen.getByRole("status")).toHaveTextContent("Consultando dashboard");
    await screen.findByText("Consulta interactiva, no persistida", { exact: false });
    vi.mocked(api).mockRejectedValueOnce(new ApiError("forbidden", "Acceso revocado", 403));
    fireEvent.click(screen.getByRole("button", { name: "Consultar dashboard" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Acceso revocado");
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });
  it("mantiene filtros de partición obligatorios sin agregación implícita", () => {
    const contract = { ...metric, required_dimensions: ["currency"], dimensions: ["currency"] };
    const time = {
      timezone: "UTC",
      start: "2026-08-01",
      end: "2026-09-01",
      asOf: catalog.server_now,
      periodId: "",
    };
    expect(buildSelection(contract, time, [], {}).dimensions).toEqual(["currency"]);
    expect(buildSelection(contract, time, [], { currency: "USD" }).dimensions).toEqual([]);
  });
  it("cada gráfico tiene tabla y conserva Decimal exacto, cobertura y estados no numéricos", () => {
    const money = {
      ...metricResult,
      unit: "money",
      coverage: "partial" as const,
      coverage_reason: "missing_history",
      provisional: true,
      points: [
        {
          dimensions: { currency: "USD" },
          value: "9999999999999999.99",
          status: "value" as const,
          sample_size: null,
          eligible_count: null,
        },
        {
          dimensions: { currency: "EUR" },
          value: null,
          status: "not_calculable" as const,
          sample_size: null,
          eligible_count: null,
        },
        {
          dimensions: { currency: "GBP" },
          value: null,
          status: "not_applicable" as const,
          sample_size: null,
          eligible_count: null,
        },
      ],
    };
    render(<MetricCard metric={money} definition={metric} selection={selection} />);
    expect(screen.getByRole("figure", { name: "Gráfico de Solicitudes creadas" })).toBeVisible();
    const table = screen.getByRole("table");
    expect(within(table).getByText("9.999.999.999.999.999,99")).toBeVisible();
    expect(within(table).getByText("No calculable")).toBeVisible();
    expect(within(table).getByText("No aplica")).toBeVisible();
    expect(screen.getByText("Cobertura parcial")).toBeVisible();
    expect(screen.getByText("Provisional · periodo abierto")).toBeVisible();
  });
  it("unavailable y empty nunca se presentan como cero calculado", () => {
    render(
      <MetricCard
        metric={{
          ...metricResult,
          points: [],
          coverage: "unavailable",
          coverage_reason: "no_evidence",
        }}
        definition={metric}
        selection={selection}
      />,
    );
    expect(screen.getByText("No disponible")).toBeVisible();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});
