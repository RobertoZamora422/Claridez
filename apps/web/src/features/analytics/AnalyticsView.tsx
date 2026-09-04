import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { api, ApiError } from "../../api";
import { Loading, Notice } from "../../shared/components";
import { formatDate, message } from "../../shared/utilities";
import { MetricCard } from "./MetricCard";
import { buildSelection, previousRange, reportTemporal, type TemporalSelection } from "./temporal";
import type {
  Catalog,
  Execution,
  ExportJob,
  HistoryPage,
  MetricContract,
  MetricSelection,
  QueryResult,
  SavedReport,
} from "./types";
import "./analytics.css";

const PROFILE_LABEL: Record<string, string> = {
  owner: "Propietario",
  administrator: "Administrador",
  commercial: "Comercial",
  operations: "Operaciones",
  finance: "Finanzas",
};
const JOB_LABEL = {
  queued: "En cola",
  running: "Generando",
  retry: "Reintento programado",
  completed: "Disponible",
  terminal: "Falló definitivamente",
};
type HistoryCollection = "reports" | "revisions" | "executions" | "exports";
function emptyPage<T>(): HistoryPage<T> {
  return { results: [], next_cursor: null };
}
interface MetricOptions {
  dimensions: string[];
  filters: Record<string, string>;
}

function defaults(metric: MetricContract): MetricOptions {
  return { dimensions: metric.required_dimensions, filters: {} };
}

export function AnalyticsView({
  organizationId,
  catalog,
}: {
  organizationId: string;
  catalog: Catalog;
}) {
  const base = `/api/v1/organizations/${organizationId}/analytics`;
  const [temporal, setTemporal] = useState<TemporalSelection>(() => ({
    timezone: catalog.timezone,
    ...previousRange("month", catalog.server_now, catalog.timezone),
    asOf: catalog.server_now,
    periodId: catalog.periods[0]?.id ?? "",
  }));
  const [selected, setSelected] = useState(() =>
    catalog.preset.filter(
      (id) =>
        catalog.periods.length > 0 ||
        catalog.metrics.find((m) => m.metric_id === id)?.temporal_mode !== "FP",
    ),
  );
  const [options, setOptions] = useState<Record<string, MetricOptions>>({});
  const [result, setResult] = useState<QueryResult | null>(null);
  const [execution, setExecution] = useState<Execution | null>(null);
  const [reports, setReports] = useState<SavedReport[]>([]);
  const [history, setHistory] = useState<Execution[]>([]);
  const [exports, setExports] = useState<ExportJob[]>([]);
  const [report, setReport] = useState<SavedReport | null>(null);
  const [useStoredSelection, setUseStoredSelection] = useState(false);
  const [preserveReportTimes, setPreserveReportTimes] = useState(false);
  const [revisions, setRevisions] = useState<SavedReport[]>([]);
  const [revisionReportId, setRevisionReportId] = useState<string | null>(null);
  const [nextPages, setNextPages] = useState<Partial<Record<HistoryCollection, string | null>>>({});
  const [title, setTitle] = useState("");
  const [visibility, setVisibility] = useState<"private" | "organization">("private");
  const [format, setFormat] = useState<ExportJob["format"]>("csv");
  const [pending, setPending] = useState(
    catalog.preset.some((id) =>
      catalog.metrics.some(
        (m) => m.metric_id === id && (m.temporal_mode !== "FP" || catalog.periods.length > 0),
      ),
    )
      ? "Consultando dashboard…"
      : "",
  );
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const focusTarget = useRef<HTMLHeadingElement>(null);
  const sequence = useRef(0);
  const stableKeys = useRef(new Map<string, string>());
  const can = (name: string) => catalog.capabilities.includes(`analytics:${name}`);
  const activeModes = catalog.metrics
    .filter((m) => selected.includes(m.metric_id))
    .map((m) => m.temporal_mode);
  const needsCommonRange =
    !preserveReportTimes && activeModes.some((mode) => ["F", "SI", "C"].includes(mode));
  const needsCommonCutoff = !preserveReportTimes && activeModes.some((mode) => mode !== "F");

  function idempotency(kind: string, payload: object) {
    const identity = `${kind}:${JSON.stringify(payload)}`;
    const found = stableKeys.current.get(identity);
    if (found) return found;
    const key = crypto.randomUUID();
    stableKeys.current.set(identity, key);
    return key;
  }
  function querySelection(): MetricSelection[] {
    if (report && useStoredSelection) return report.selection;
    if (selected.length === 0) throw new Error("Seleccione al menos una métrica.");
    return selected.map((id) => {
      const metric = catalog.metrics.find((row) => row.metric_id === id);
      if (!metric) throw new Error("Esta métrica ya no está disponible para su perfil.");
      const option = options[id] ?? defaults(metric);
      const stored = preserveReportTimes && report?.selection.find((row) => row.metric_id === id);
      if (stored)
        return {
          ...stored,
          dimensions: [
            ...new Set([
              ...option.dimensions,
              ...metric.required_dimensions.filter((key) => !option.filters[key]),
            ]),
          ],
          filters: Object.fromEntries(
            Object.entries(option.filters).filter(([, value]) => value !== ""),
          ),
        };
      return buildSelection(metric, temporal, option.dimensions, option.filters);
    });
  }
  function detach() {
    setUseStoredSelection(false);
    setResult(null);
    setExecution(null);
    setNotice("");
  }
  function changeTime(patch: Partial<TemporalSelection>) {
    detach();
    setPreserveReportTimes(false);
    setTemporal((current) => ({ ...current, ...patch }));
    if (report)
      setNotice(
        "Las fechas comunes se aplicarán a todas las métricas de la nueva selección. La revisión guardada no cambia.",
      );
  }
  async function task(label: string, action: () => Promise<void>) {
    const current = ++sequence.current;
    setPending(label);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (caught) {
      setError(message(caught));
      if (caught instanceof ApiError && [401, 403, 404].includes(caught.status)) {
        setResult(null);
        setExecution(null);
        setReports([]);
        setHistory([]);
        setExports([]);
        setRevisions([]);
        setNextPages({});
        setRevisionReportId(null);
      }
    } finally {
      if (sequence.current === current) setPending("");
    }
  }
  async function refreshHistory() {
    const [r, e, j] = await Promise.all([
      can("execute_report")
        ? api<HistoryPage<SavedReport>>(`${base}/reports/`)
        : Promise.resolve(emptyPage<SavedReport>()),
      can("execute_report")
        ? api<HistoryPage<Execution>>(`${base}/executions/`)
        : Promise.resolve(emptyPage<Execution>()),
      can("create_export")
        ? api<HistoryPage<ExportJob>>(`${base}/exports/`)
        : Promise.resolve(emptyPage<ExportJob>()),
    ]);
    setReports(r.results);
    setHistory(e.results);
    setExports(j.results);
    setNextPages((current) => ({
      ...current,
      reports: r.next_cursor,
      executions: e.next_cursor,
      exports: j.next_cursor,
    }));
  }
  async function moreHistory<T>(
    collection: HistoryCollection,
    setRows: Dispatch<SetStateAction<T[]>>,
  ) {
    const cursor = nextPages[collection];
    if (!cursor) return;
    const path =
      collection === "revisions" ? `reports/${revisionReportId ?? ""}/revisions` : collection;
    const result = await api<HistoryPage<T>>(
      `${base}/${path}/?cursor=${encodeURIComponent(cursor)}`,
    );
    setRows((current) => [...current, ...result.results]);
    setNextPages((current) => ({ ...current, [collection]: result.next_cursor }));
    setNotice("Página autorizada cargada. El cursor no concede permisos adicionales.");
  }
  useEffect(() => {
    let live = true;
    const metrics = catalog.preset.flatMap((id) => {
      const definition = catalog.metrics.find((m) => m.metric_id === id);
      if (!definition || (definition.temporal_mode === "FP" && !catalog.periods.length)) return [];
      const time = {
        timezone: catalog.timezone,
        ...previousRange("month", catalog.server_now, catalog.timezone),
        asOf: catalog.server_now,
        periodId: catalog.periods[0]?.id ?? "",
      };
      return [buildSelection(definition, time, definition.required_dimensions, {})];
    });
    if (metrics.length) {
      void api<QueryResult>(`${base}/dashboards/query/`, {
        method: "POST",
        body: JSON.stringify({ timezone: catalog.timezone, metrics }),
      })
        .then((body) => {
          if (live) setResult(body);
        })
        .catch((caught: unknown) => {
          if (live) setError(message(caught));
        })
        .finally(() => {
          if (live) setPending("");
        });
    }
    return () => {
      live = false;
    };
  }, [base, catalog]);

  async function query() {
    const metrics = querySelection();
    const body = await api<QueryResult>(`${base}/dashboards/query/`, {
      method: "POST",
      body: JSON.stringify({
        timezone: useStoredSelection && report ? report.timezone : temporal.timezone,
        metrics,
      }),
    });
    setResult(body);
    setExecution(null);
    focusTarget.current?.focus();
  }
  async function execute(revision?: SavedReport) {
    const chosen = revision ?? (useStoredSelection ? report : null);
    const payload = chosen
      ? { report_revision_id: chosen.revision_id }
      : { timezone: temporal.timezone, metrics: querySelection() };
    const row = await api<Execution>(`${base}/executions/`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotency("execute", payload) },
      body: JSON.stringify(payload),
    });
    setExecution(row);
    setResult(row.result ?? null);
    stableKeys.current.delete(`execute:${JSON.stringify(payload)}`);
    setNotice(
      "Ejecución congelada. Las exportaciones usarán este resultado, no un dashboard posterior.",
    );
    await refreshHistory();
    focusTarget.current?.focus();
  }
  async function save(revise: boolean) {
    if (!title.trim()) throw new Error("Escriba un nombre para el reporte.");
    const payload = {
      title,
      visibility,
      timezone: useStoredSelection && report ? report.timezone : temporal.timezone,
      metrics: querySelection(),
      ...(revise && report ? { expected_revision: report.revision } : {}),
    };
    const path = revise && report ? `${base}/reports/${report.id}/revisions/` : `${base}/reports/`;
    const saved = await api<SavedReport>(path, { method: "POST", body: JSON.stringify(payload) });
    setReport(saved);
    setUseStoredSelection(true);
    setPreserveReportTimes(true);
    setTemporal(reportTemporal(saved.selection, saved.timezone));
    setNotice(`Definición guardada · revisión ${String(saved.revision)}. No es un snapshot.`);
    await refreshHistory();
  }
  function loadReport(row: SavedReport) {
    setReport(row);
    setUseStoredSelection(true);
    setPreserveReportTimes(true);
    setTemporal(reportTemporal(row.selection, row.timezone));
    setTitle(row.title);
    setVisibility(row.visibility);
    setSelected(row.selection.map((s) => s.metric_id));
    setOptions(
      Object.fromEntries(
        row.selection.map((s) => [s.metric_id, { dimensions: s.dimensions, filters: s.filters }]),
      ),
    );
    setResult(null);
    setExecution(null);
    setNotice(
      "Revisión cargada con sus parámetros exactos. Puede ejecutarla o crear una nueva revisión.",
    );
  }
  async function download(job: ExportJob) {
    const response = await fetch(`${base}/exports/${job.id}/download/`, {
      credentials: "same-origin",
      headers: { Accept: "application/octet-stream" },
    });
    if (!response.ok) throw new Error("La descarga no está disponible o su autorización cambió.");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `reporte-${job.id}.${job.format}`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 1000);
    setNotice("Descarga autorizada nuevamente por el servidor.");
  }

  return (
    <section
      className="analytics-page"
      aria-label="Analítica y reportes"
      aria-busy={Boolean(pending)}
    >
      <header className="analytics-header">
        <div>
          <p className="analytics-eyebrow">
            CENTRO DE CONTROL · {PROFILE_LABEL[catalog.profile] ?? catalog.profile}
          </p>
          <h1>Analítica y reportes</h1>
          <p>
            Hechos, estados y periodos con su cobertura visible. Sin mezclar monedas ni unidades.
          </p>
        </div>
        <span className="analytics-catalog-tag">
          {catalog.catalog_version} · {String(catalog.metrics.length)} métricas autorizadas
        </span>
      </header>
      {error && <Notice>{error}</Notice>}
      {notice && <Notice tone="info">{notice}</Notice>}
      <form
        className="analytics-controls"
        onSubmit={(event) => {
          event.preventDefault();
          void task("Consultando…", query);
        }}
      >
        <fieldset disabled={Boolean(pending)}>
          <legend>Selección temporal</legend>
          <div className="button-row">
            {(["day", "week", "month"] as const).map((kind) => (
              <button
                type="button"
                className="button button--ghost"
                key={kind}
                onClick={() => {
                  changeTime(previousRange(kind, catalog.server_now, temporal.timezone));
                }}
              >
                {{ day: "Día anterior", week: "Semana ISO anterior", month: "Mes anterior" }[kind]}
              </button>
            ))}
          </div>
          <div className="analytics-form-grid">
            <label>
              Inicio incluido
              <input
                type="date"
                value={temporal.start}
                onChange={(e) => {
                  changeTime({ start: e.target.value });
                }}
                required={needsCommonRange}
              />
            </label>
            <label>
              Fin excluido
              <input
                type="date"
                value={temporal.end}
                onChange={(e) => {
                  changeTime({ end: e.target.value });
                }}
                required={needsCommonRange}
              />
            </label>
            <label>
              Zona IANA
              <input
                value={temporal.timezone}
                onChange={(e) => {
                  changeTime({ timezone: e.target.value });
                }}
                required
              />
            </label>
            <label>
              Estado observado al corte (ISO con offset)
              <input
                value={temporal.asOf}
                onChange={(e) => {
                  changeTime({ asOf: e.target.value });
                }}
                placeholder="2026-09-01T00:00:00-05:00"
                required={needsCommonCutoff}
              />
            </label>
            {catalog.periods.length > 0 && (
              <label>
                Periodo de Finance
                <select
                  value={temporal.periodId}
                  onChange={(e) => {
                    changeTime({ periodId: e.target.value });
                  }}
                >
                  {catalog.periods.map((period) => (
                    <option key={period.id} value={period.id}>
                      {period.starts_on} → {period.ends_on} · {period.currency} ·{" "}
                      {period.closed ? "cerrado" : "abierto / provisional"}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <p className="analytics-muted">
            F usa solo el intervalo; S usa el estado al corte; SI combina ambos; C observa la
            cohorte después de su fin. FP usa el periodo Finance completo. El límite de conocimiento
            lo captura el servidor.
          </p>
          {report && (
            <details className="analytics-warning">
              <summary>Parámetros guardados · revisión {String(report.revision)}</summary>
              <p>
                {preserveReportTimes
                  ? "Se conservan los instantes exactos por métrica al cambiar filtros o dimensiones. Los campos comunes vacíos indican parámetros diferentes o rangos que no empiezan a medianoche."
                  : "La nueva selección usa las fechas comunes. La revisión anterior permanece intacta."}
              </p>
              <ul>
                {report.selection.map((row) => (
                  <li key={row.metric_id}>
                    {catalog.metrics.find((m) => m.metric_id === row.metric_id)?.label ??
                      row.metric_id}
                    : {row.period_start ?? "sin inicio"} → {row.period_end ?? "sin fin"}; corte{" "}
                    {row.as_of_at ?? "no aplica"}; periodo{" "}
                    {row.operational_period_id ?? "no aplica"} · {report.timezone}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </fieldset>
        <details className="analytics-selector">
          <summary>Métricas y dimensiones · {String(selected.length)} seleccionadas</summary>
          <fieldset disabled={Boolean(pending)}>
            <legend>Solo contratos permitidos por sus fuentes</legend>
            <div className="analytics-metric-options">
              {catalog.metrics.map((metric) => {
                const enabled = selected.includes(metric.metric_id);
                const value = options[metric.metric_id] ?? defaults(metric);
                function changeOption(next: MetricOptions) {
                  detach();
                  setOptions((current) => ({ ...current, [metric.metric_id]: next }));
                }
                return (
                  <div className="analytics-option" key={metric.metric_id}>
                    <label className="analytics-check">
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={(e) => {
                          detach();
                          setSelected((current) =>
                            e.target.checked
                              ? [...current, metric.metric_id]
                              : current.filter((id) => id !== metric.metric_id),
                          );
                        }}
                      />
                      {metric.label}{" "}
                      <small>
                        {metric.temporal_mode} · {metric.unit}
                      </small>
                    </label>
                    {enabled && (
                      <details>
                        <summary>Dimensiones y filtros de {metric.label}</summary>
                        {metric.dimensions.map((dimension) => (
                          <div className="analytics-dimension" key={dimension}>
                            <label className="analytics-check">
                              <input
                                type="checkbox"
                                checked={value.dimensions.includes(dimension)}
                                onChange={(e) => {
                                  changeOption({
                                    ...value,
                                    dimensions: e.target.checked
                                      ? [...value.dimensions, dimension]
                                      : value.dimensions.filter((v) => v !== dimension),
                                  });
                                }}
                              />
                              Agrupar por {dimension}
                              {metric.required_dimensions.includes(dimension)
                                ? " (partición obligatoria)"
                                : ""}
                            </label>
                            <label>
                              Filtro {dimension}
                              {dimension === "time_bucket" ? (
                                <select
                                  value={value.filters[dimension] ?? ""}
                                  onChange={(e) => {
                                    changeOption({
                                      ...value,
                                      filters: { ...value.filters, [dimension]: e.target.value },
                                    });
                                  }}
                                >
                                  <option value="">Mes (predeterminado)</option>
                                  <option value="day">Día civil</option>
                                  <option value="week">Semana ISO</option>
                                  <option value="month">Mes</option>
                                </select>
                              ) : (
                                <input
                                  maxLength={80}
                                  value={value.filters[dimension] ?? ""}
                                  placeholder={
                                    dimension.endsWith("_id")
                                      ? "UUID; vacío = todos los autorizados"
                                      : "Vacío = todas las particiones autorizadas"
                                  }
                                  onChange={(e) => {
                                    changeOption({
                                      ...value,
                                      filters: { ...value.filters, [dimension]: e.target.value },
                                    });
                                  }}
                                />
                              )}
                            </label>
                          </div>
                        ))}
                        <p>{metric.coverage_rule}</p>
                      </details>
                    )}
                  </div>
                );
              })}
            </div>
          </fieldset>
        </details>
        <div className="button-row">
          <button className="button button--primary" disabled={Boolean(pending)}>
            Consultar dashboard
          </button>
          {can("execute_report") && (
            <button
              type="button"
              className="button button--ghost"
              disabled={Boolean(pending)}
              onClick={() => {
                void task("Congelando ejecución…", () => execute());
              }}
            >
              Ejecutar y congelar
            </button>
          )}
        </div>
      </form>
      <h2 tabIndex={-1} ref={focusTarget}>
        Resultados
      </h2>
      {pending && <Loading label={pending} />}
      {!result && !pending && <p>No hay una consulta visible. Seleccione métricas y consulte.</p>}
      {result && (
        <>
          <p className="analytics-muted">
            Conocimiento hasta {formatDate(result.knowledge_cutoff_at, result.timezone)} · zona{" "}
            {result.timezone} ·{" "}
            {execution ? `Ejecución ${execution.id}` : "Consulta interactiva, no persistida"}
          </p>
          <div className="analytics-result-grid">
            {result.metrics.map((metric) => {
              const definition = catalog.metrics.find((row) => row.metric_id === metric.metric_id);
              const selection = result.selection.find((row) => row.metric_id === metric.metric_id);
              return definition && selection ? (
                <MetricCard
                  key={metric.metric_id}
                  metric={metric}
                  definition={definition}
                  selection={selection}
                />
              ) : null;
            })}
          </div>
          <details>
            <summary>Parámetros y hash del catálogo</summary>
            <code>{result.catalog_hash}</code>
            <pre>{JSON.stringify(result.selection, null, 2)}</pre>
          </details>
        </>
      )}
      <section className="analytics-management" aria-labelledby="analytics-reports-heading">
        <h2 id="analytics-reports-heading">Reportes guardados</h2>
        <p>
          Una definición conserva la selección. Cada edición crea una revisión; ejecutar congela el
          resultado.
        </p>
        {can("manage_own_report") && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void task("Guardando definición…", () => save(false));
            }}
          >
            <fieldset disabled={Boolean(pending)}>
              <legend>
                {report ? `Definición · revisión ${String(report.revision)}` : "Guardar selección"}
              </legend>
              <div className="analytics-form-grid">
                <label>
                  Nombre del reporte
                  <input
                    maxLength={120}
                    required
                    value={title}
                    onChange={(e) => {
                      setTitle(e.target.value);
                    }}
                  />
                </label>
                <label>
                  Visibilidad
                  <select
                    value={visibility}
                    onChange={(e) => {
                      setVisibility(e.target.value as "private" | "organization");
                    }}
                  >
                    <option value="private">Privado</option>
                    {can("manage_shared_report") && (
                      <option value="organization">Organización</option>
                    )}
                  </select>
                </label>
              </div>
              <p className="analytics-muted">
                Compartir nunca concede acceso a una fuente. No incluya datos personales en el
                nombre.
              </p>
              <div className="button-row">
                <button className="button button--ghost">Guardar como nuevo reporte</button>
                {report && (report.visibility === "private" || can("manage_shared_report")) && (
                  <button
                    type="button"
                    className="button button--ghost"
                    onClick={() => {
                      void task("Creando revisión…", () => save(true));
                    }}
                  >
                    Crear nueva revisión
                  </button>
                )}
              </div>
            </fieldset>
          </form>
        )}
        <button
          className="button button--ghost"
          disabled={Boolean(pending)}
          onClick={() => {
            void task("Cargando historial autorizado…", refreshHistory);
          }}
        >
          Actualizar reportes e historial
        </button>
        <ul className="analytics-history">
          {reports.map((row) => (
            <li key={row.id}>
              <strong>{row.title}</strong>
              <span>
                Revisión {String(row.revision)} ·{" "}
                {row.visibility === "private" ? "Privado" : "Organización"}
              </span>
              <div className="button-row">
                <button
                  disabled={Boolean(pending)}
                  onClick={() => {
                    loadReport(row);
                  }}
                >
                  Cargar {row.title}
                </button>
                <button
                  disabled={Boolean(pending)}
                  onClick={() => {
                    void task("Cargando revisiones…", async () => {
                      const list = await api<HistoryPage<SavedReport>>(
                        `${base}/reports/${row.id}/revisions/`,
                      );
                      setRevisions(list.results);
                      setRevisionReportId(row.id);
                      setNextPages((current) => ({ ...current, revisions: list.next_cursor }));
                    });
                  }}
                >
                  Revisiones
                </button>
                {(row.visibility === "private" || can("manage_shared_report")) && (
                  <button
                    disabled={Boolean(pending)}
                    onClick={() => {
                      void task("Archivando definición…", async () => {
                        await api(`${base}/reports/${row.id}/archive/`, {
                          method: "POST",
                          body: JSON.stringify({ archived: true, expected_revision: row.revision }),
                        });
                        await refreshHistory();
                        setNotice("Reporte archivado; sus revisiones y ejecuciones se conservan.");
                      });
                    }}
                  >
                    Archivar
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
        {nextPages.reports && (
          <button
            disabled={Boolean(pending)}
            onClick={() => {
              void task("Cargando más reportes…", () => moreHistory("reports", setReports));
            }}
          >
            Cargar más reportes
          </button>
        )}
        {(revisions.length > 0 || nextPages.revisions) && (
          <div>
            <h3>Revisiones autorizadas</h3>
            {revisions.map((row) => (
              <button
                key={row.revision_id}
                disabled={Boolean(pending)}
                onClick={() => {
                  loadReport(row);
                }}
              >
                Cargar revisión {String(row.revision)} de {row.title}
              </button>
            ))}
            {nextPages.revisions && (
              <button
                disabled={Boolean(pending)}
                onClick={() => {
                  void task("Cargando más revisiones…", () =>
                    moreHistory("revisions", setRevisions),
                  );
                }}
              >
                Cargar más revisiones
              </button>
            )}
          </div>
        )}
      </section>
      <section className="analytics-management" aria-labelledby="analytics-exports-heading">
        <h2 id="analytics-exports-heading">Ejecuciones y exportaciones</h2>
        <p>
          Sin datos personales nominales. CSV tabular, XLSX tipado y PDF de presentación. Hasta
          25.000 filas / 20 MiB; el resultado interactivo está acotado a 2.000 filas / 512 KiB.
        </p>
        {execution && can("create_export") && (
          <div className="analytics-export-create">
            <p>
              Ejecución seleccionada: <code>{execution.id}</code> · {String(execution.row_count)}{" "}
              filas
            </p>
            <label>
              Formato de exportación
              <select
                value={format}
                onChange={(e) => {
                  setFormat(e.target.value as ExportJob["format"]);
                }}
              >
                <option value="csv">CSV · tabla</option>
                <option value="xlsx">XLSX · hojas tipadas</option>
                <option value="pdf">PDF · presentación (máx. 1.000 filas)</option>
              </select>
            </label>
            <button
              className="button button--primary"
              disabled={Boolean(pending)}
              onClick={() => {
                void task("Creando exportación…", async () => {
                  const payload = { execution_id: execution.id, format };
                  await api<ExportJob>(`${base}/exports/`, {
                    method: "POST",
                    headers: { "Idempotency-Key": idempotency("export", payload) },
                    body: JSON.stringify(payload),
                  });
                  await refreshHistory();
                  setNotice(
                    "Exportación en cola. Actualice el historial para consultar su estado.",
                  );
                });
              }}
            >
              Crear exportación de esta ejecución
            </button>
          </div>
        )}
        {!execution && (
          <p>Ejecute una selección o abra una ejecución del historial para exportar.</p>
        )}
        <h3>Mis últimas ejecuciones autorizadas</h3>
        <ul className="analytics-history">
          {history.map((row) => (
            <li key={row.id}>
              <span>
                {formatDate(row.executed_at, row.timezone)} · {String(row.row_count)} filas
              </span>
              <code>{row.id}</code>
              <button
                disabled={Boolean(pending)}
                onClick={() => {
                  void task("Reconstruyendo ejecución…", async () => {
                    const body = await api<Execution>(`${base}/executions/${row.id}/`);
                    setExecution(body);
                    setResult(body.result ?? null);
                    focusTarget.current?.focus();
                  });
                }}
              >
                Abrir ejecución {row.id.slice(0, 8)}
              </button>
            </li>
          ))}
        </ul>
        {nextPages.executions && (
          <button
            disabled={Boolean(pending)}
            onClick={() => {
              void task("Cargando más ejecuciones…", () => moreHistory("executions", setHistory));
            }}
          >
            Cargar más ejecuciones
          </button>
        )}
        <h3>Mis últimas exportaciones autorizadas</h3>
        <ul className="analytics-history">
          {exports.map((job) => (
            <li key={job.id}>
              <strong>
                {job.format.toUpperCase()} · {JOB_LABEL[job.state]}
              </strong>
              <code>{job.id}</code>
              <span>Intentos: {String(job.attempt_count)}</span>
              {job.error_code && <span role="status">Código: {job.error_code}</span>}
              {job.next_attempt_at && (
                <span>Reintento: {formatDate(job.next_attempt_at, temporal.timezone)}</span>
              )}
              {job.state === "completed" && can("download_export") && (
                <button
                  disabled={Boolean(pending)}
                  onClick={() => {
                    void task("Reautorizando descarga…", () => download(job));
                  }}
                >
                  Descargar {job.format.toUpperCase()}
                </button>
              )}
            </li>
          ))}
        </ul>
        {nextPages.exports && (
          <button
            disabled={Boolean(pending)}
            onClick={() => {
              void task("Cargando más exportaciones…", () => moreHistory("exports", setExports));
            }}
          >
            Cargar más exportaciones
          </button>
        )}
        <p className="analytics-muted">
          Páginas de hasta 50 registros y 512 KiB. Puede cargar páginas anteriores; cada lectura y
          descarga revalida el acceso.
        </p>
      </section>
    </section>
  );
}
