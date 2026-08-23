import { useCallback, useState } from "react";

import { api } from "../../api";
import { Loading, Notice } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { formText, message, toInputDate } from "../../shared/utilities";

interface MetricSet {
  recognized_revenue: string;
  direct_cost: string;
  variable_expense: string;
  recurring_expense: string;
  gross_margin: string;
  contribution_margin: string;
  operating_result: string;
  profitability_percentage: string | null;
  p10_cash: string;
  p11_cash: string;
  net_cash_flow: string;
}

interface Category {
  id: string;
  kind: "direct_cost" | "variable_expense" | "recurring_expense";
  name: string;
}

interface Period {
  id: string;
  label: string;
  starts_on: string;
  ends_on: string;
  currency: string;
  closed: boolean;
  closed_at: string | null;
}

interface EventResult {
  root_reservation_id: string;
  recognized_venue_id?: string | null;
  execution_started_at?: string | null;
  execution_completed_at?: string | null;
  baseline_plan_revision_id: string | null;
  baseline_planned_cost: string;
  cost_variance: string;
  metrics: MetricSet;
}

interface FinancialFact {
  id: string;
  root_reservation_id?: string;
  venue_id?: string;
  category_id?: string;
  direction?: string;
  source_kind?: string;
  source_id?: string;
  original_outflow_id?: string | null;
  amount: string;
  effective_amount: string;
  currency: string;
  economic_date: string;
  description?: string;
  reason?: string;
  allocations?: MoneyAttribution[];
  expense_attributions?: MoneyAttribution[];
  effective_expense_attributions?: MoneyAttribution[];
}

interface MoneyAttribution {
  scope: "business" | "venue" | "event";
  root_reservation_id: string | null;
  venue_id: string | null;
  amount: string;
}

interface Evidence {
  id: string;
  root_reservation_id: string;
  venue_id: string;
  category_id: string;
  amount: string;
  currency: string;
  economic_date: string;
  description: string;
  evidence_reference: string;
  decision: { id: string; decision: string } | null;
}

interface RecurringRule {
  id: string;
  category_id: string;
  name: string;
  amount: string;
  day_of_month: number;
  valid_from: string;
  valid_until: string | null;
  default_venue_id: string | null;
}

interface FinanceOverview {
  organization_id: string;
  currency: string;
  timezone: string;
  period: Period | null;
  ordinary: MetricSet;
  prior_period_adjustments: MetricSet;
  presented: MetricSet;
  events: EventResult[];
  categories: Category[];
  periods: Period[];
  direct_costs: FinancialFact[];
  cost_evidence: Evidence[];
  expenses: FinancialFact[];
  recurring_rules: RecurringRule[];
  cash_movements: FinancialFact[];
  recognition_adjustments: FinancialFact[];
}

interface EvidenceContext {
  categories: Category[];
  events: { root_reservation_id: string; reservation_id: string; venues: string[] }[];
}

const today = toInputDate(new Date());

function money(value: string, currency: string) {
  return new Intl.NumberFormat("es-EC", { style: "currency", currency }).format(Number(value));
}

function command(path: string, body: object = {}) {
  return api<{ id: string }>(path, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(body),
  });
}

function financeQuery(periodId: string, rootId: string, venueId: string) {
  const query = new URLSearchParams();
  if (periodId) query.set("period_id", periodId);
  if (rootId) query.set("root_reservation_id", rootId);
  if (venueId) query.set("venue_id", venueId);
  const value = query.toString();
  return value ? `?${value}` : "";
}

function attributionKey(attribution: MoneyAttribution, index: number) {
  return [
    attribution.scope,
    attribution.root_reservation_id ?? "no-root",
    attribution.venue_id ?? "no-venue",
    String(index),
  ].join("-");
}

function categoryOptions(categories: Category[], kind?: Category["kind"]) {
  return categories
    .filter((category) => kind === undefined || category.kind === kind)
    .map((category) => (
      <option key={category.id} value={category.id}>
        {category.name}
      </option>
    ));
}

export function FinanceView({
  organizationId,
  capabilities,
}: {
  organizationId: string;
  capabilities: Set<string>;
}) {
  const canRead = capabilities.has("finance:read");
  const [overview, setOverview] = useState<FinanceOverview | null>(null);
  const [evidenceContext, setEvidenceContext] = useState<EvidenceContext | null>(null);
  const [periodId, setPeriodId] = useState("");
  const [rootId, setRootId] = useState("");
  const [venueId, setVenueId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [finance, context] = await Promise.all([
        canRead
          ? api<FinanceOverview>(
              `/api/v1/organizations/${organizationId}/finance/overview/${financeQuery(periodId, rootId, venueId)}`,
            )
          : Promise.resolve(null),
        capabilities.has("finance:submit_evidence")
          ? api<EvidenceContext>(
              `/api/v1/organizations/${organizationId}/finance/evidence-context/`,
            )
          : Promise.resolve(null),
      ]);
      setOverview(finance);
      setEvidenceContext(context);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [canRead, capabilities, organizationId, periodId, rootId, venueId]);

  useInitialLoad(load);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      await load();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  const categories = overview?.categories ?? evidenceContext?.categories ?? [];
  const eventOptions =
    evidenceContext?.events ??
    overview?.events.map((event) => ({
      root_reservation_id: event.root_reservation_id,
      reservation_id: event.root_reservation_id,
      venues: event.recognized_venue_id ? [event.recognized_venue_id] : [],
    })) ??
    [];

  if (loading) return <Loading label="Reconstruyendo control financiero…" />;
  return (
    <section className="finance-page" aria-labelledby="finance-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Control financiero operativo</p>
          <h1 id="finance-title">Costos, gastos, flujo y rentabilidad</h1>
          <p className="muted">
            Caja, cartera e ingreso permanecen separados. Claridez no lleva contabilidad formal.
          </p>
        </div>
        <div className="finance-header-actions">
          {canRead ? (
            <a
              className="button button--secondary"
              href={`/api/v1/organizations/${organizationId}/finance/export/${financeQuery(periodId, rootId, venueId)}`}
            >
              Exportar CSV
            </a>
          ) : null}
          <button className="button button--secondary" onClick={() => void load()} disabled={busy}>
            Actualizar
          </button>
        </div>
      </header>
      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="info">{notice}</Notice> : null}

      {overview ? (
        <>
          <div className="finance-filter">
            <label>
              Periodo de presentación
              <select
                value={periodId}
                onChange={(event) => {
                  setPeriodId(event.target.value);
                }}
              >
                <option value="">Vida completa de los eventos</option>
                {overview.periods.map((period) => (
                  <option key={period.id} value={period.id}>
                    {period.label}
                    {period.closed ? " · cerrado" : " · abierto"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Raíz estable
              <input
                value={rootId}
                onChange={(event) => {
                  setRootId(event.target.value.trim());
                }}
                placeholder="UUID opcional"
              />
            </label>
            <label>
              Sede histórica
              <input
                value={venueId}
                onChange={(event) => {
                  setVenueId(event.target.value.trim());
                }}
                placeholder="UUID opcional"
              />
            </label>
            <button className="button button--secondary" onClick={() => void load()}>
              Aplicar
            </button>
          </div>
          <div className="finance-metrics" aria-label="Resultados financieros operativos">
            {[
              ["Ingreso reconocido", overview.presented.recognized_revenue],
              ["Margen bruto", overview.presented.gross_margin],
              ["Resultado operativo", overview.presented.operating_result],
              ["Flujo neto", overview.presented.net_cash_flow],
            ].map(([label, value]) => (
              <article key={label}>
                <span>{label}</span>
                <strong>{money(value ?? "0.00", overview.currency)}</strong>
              </article>
            ))}
          </div>
          <div className="finance-split">
            <article className="panel">
              <h2>Operación ordinaria</h2>
              <dl className="finance-breakdown">
                <div>
                  <dt>Costo directo</dt>
                  <dd>{money(overview.ordinary.direct_cost, overview.currency)}</dd>
                </div>
                <div>
                  <dt>Gasto variable</dt>
                  <dd>{money(overview.ordinary.variable_expense, overview.currency)}</dd>
                </div>
                <div>
                  <dt>Gasto recurrente</dt>
                  <dd>{money(overview.ordinary.recurring_expense, overview.currency)}</dd>
                </div>
                <div>
                  <dt>Caja P10</dt>
                  <dd>{money(overview.ordinary.p10_cash, overview.currency)}</dd>
                </div>
                <div>
                  <dt>Caja P11</dt>
                  <dd>{money(overview.ordinary.p11_cash, overview.currency)}</dd>
                </div>
              </dl>
            </article>
            <article className="panel">
              <h2>Ajustes de periodos anteriores</h2>
              <p className="muted">Se muestran aparte; no reescriben el cierre histórico.</p>
              <dl className="finance-breakdown">
                <div>
                  <dt>Ingreso</dt>
                  <dd>
                    {money(overview.prior_period_adjustments.recognized_revenue, overview.currency)}
                  </dd>
                </div>
                <div>
                  <dt>Costos y gastos</dt>
                  <dd>{money(overview.prior_period_adjustments.direct_cost, overview.currency)}</dd>
                </div>
                <div>
                  <dt>Flujo</dt>
                  <dd>
                    {money(overview.prior_period_adjustments.net_cash_flow, overview.currency)}
                  </dd>
                </div>
              </dl>
            </article>
          </div>
          <article className="panel">
            <div className="panel-header">
              <div>
                <h2>Rentabilidad por evento</h2>
                <p className="muted">Raíz estable y sede histórica del hecho.</p>
              </div>
            </div>
            <div className="movement-table">
              <table>
                <thead>
                  <tr>
                    <th>Raíz</th>
                    <th>Sede ingreso</th>
                    <th>Baseline</th>
                    <th>Variación</th>
                    <th>Resultado</th>
                    <th>Rentabilidad</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.events.map((event) => (
                    <tr key={event.root_reservation_id}>
                      <td>
                        <code>{event.root_reservation_id}</code>
                      </td>
                      <td>
                        <code>{event.recognized_venue_id ?? "—"}</code>
                      </td>
                      <td>{money(event.baseline_planned_cost, overview.currency)}</td>
                      <td>{money(event.cost_variance, overview.currency)}</td>
                      <td>{money(event.metrics.operating_result, overview.currency)}</td>
                      <td>
                        {event.metrics.profitability_percentage === null
                          ? "—"
                          : `${event.metrics.profitability_percentage}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
        </>
      ) : null}

      {capabilities.has("finance:submit_evidence") ? (
        <form
          className="command-box"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void run(
              () =>
                command(`/api/v1/organizations/${organizationId}/finance/cost-evidence/`, {
                  root_reservation_id: formText(form, "root"),
                  venue_id: formText(form, "venue"),
                  category_id: formText(form, "category"),
                  amount: formText(form, "amount"),
                  currency: "USD",
                  economic_date: formText(form, "date"),
                  description: formText(form, "description"),
                  evidence_reference: formText(form, "evidence"),
                }),
              "Evidencia enviada a Finanzas.",
            );
          }}
        >
          <h2>Enviar evidencia de costo</h2>
          <div className="form-grid">
            <label>
              Raíz del evento
              <select name="root" required>
                {eventOptions.map((item) => (
                  <option key={item.root_reservation_id}>{item.root_reservation_id}</option>
                ))}
              </select>
            </label>
            <label>
              Sede histórica
              <input name="venue" required />
            </label>
            <label>
              Categoría
              <select name="category" required>
                {categoryOptions(categories, "direct_cost")}
              </select>
            </label>
            <label>
              Importe USD
              <input name="amount" inputMode="decimal" required />
            </label>
            <label>
              Fecha económica
              <input name="date" type="date" defaultValue={today} required />
            </label>
            <label>
              Referencia
              <input name="evidence" required />
            </label>
            <label className="span-two">
              Descripción
              <input name="description" required />
            </label>
          </div>
          <button className="button" disabled={busy}>
            Enviar evidencia
          </button>
        </form>
      ) : null}

      {overview ? (
        <div className="finance-actions">
          {capabilities.has("finance:manage_categories") ? (
            <CategoryForm organizationId={organizationId} busy={busy} run={run} />
          ) : null}
          {capabilities.has("finance:close_period") ? (
            <PeriodForm organizationId={organizationId} busy={busy} run={run} />
          ) : null}
          {capabilities.has("finance:plan_costs") ? (
            <PlanForm
              organizationId={organizationId}
              categories={categories}
              events={eventOptions}
              busy={busy}
              run={run}
            />
          ) : null}
          {capabilities.has("finance:record_actuals") ? (
            <ActualForm
              organizationId={organizationId}
              categories={categories}
              events={eventOptions}
              busy={busy}
              run={run}
            />
          ) : null}
          {capabilities.has("finance:allocate_expenses") ? (
            <ExpenseForm
              organizationId={organizationId}
              categories={categories}
              busy={busy}
              run={run}
            />
          ) : null}
          {capabilities.has("finance:manage_recurring") ? (
            <RecurringForm
              organizationId={organizationId}
              categories={categories}
              rules={overview.recurring_rules}
              busy={busy}
              run={run}
            />
          ) : null}
          {capabilities.has("finance:manage_budgets") ? (
            <BudgetForm
              organizationId={organizationId}
              categories={categories}
              periods={overview.periods}
              busy={busy}
              run={run}
            />
          ) : null}
          {capabilities.has("finance:record_cash") ? (
            <CashForm
              organizationId={organizationId}
              costs={overview.direct_costs}
              expenses={overview.expenses}
              movements={overview.cash_movements}
              busy={busy}
              run={run}
            />
          ) : null}
          {capabilities.has("finance:adjust_recognition") ? (
            <RecognitionForm
              organizationId={organizationId}
              events={eventOptions}
              busy={busy}
              run={run}
            />
          ) : null}
          {[
            "finance:record_actuals",
            "finance:allocate_expenses",
            "finance:record_cash",
            "finance:adjust_recognition",
          ].some((capability) => capabilities.has(capability)) ? (
            <CorrectionsForm
              organizationId={organizationId}
              capabilities={capabilities}
              costs={overview.direct_costs}
              expenses={overview.expenses}
              movements={overview.cash_movements}
              recognition={overview.recognition_adjustments}
              busy={busy}
              run={run}
            />
          ) : null}
          {capabilities.has("finance:record_actuals") ? (
            <EvidenceDecisions
              organizationId={organizationId}
              evidence={overview.cost_evidence}
              busy={busy}
              run={run}
            />
          ) : null}
          {capabilities.has("finance:close_period") ? (
            <ClosePeriods
              organizationId={organizationId}
              periods={overview.periods}
              busy={busy}
              run={run}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

type Runner = (action: () => Promise<unknown>, success: string) => Promise<void>;

function CategoryForm({
  organizationId,
  busy,
  run,
}: {
  organizationId: string;
  busy: boolean;
  run: Runner;
}) {
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void run(
          () =>
            command(`/api/v1/organizations/${organizationId}/finance/categories/`, {
              kind: formText(form, "kind"),
              name: formText(form, "name"),
            }),
          "Categoría creada.",
        );
      }}
    >
      <h2>Nueva categoría</h2>
      <label>
        Tipo
        <select name="kind">
          <option value="direct_cost">Costo directo</option>
          <option value="variable_expense">Gasto variable</option>
          <option value="recurring_expense">Gasto recurrente</option>
        </select>
      </label>
      <label>
        Nombre
        <input name="name" required />
      </label>
      <button className="button" disabled={busy}>
        Crear categoría
      </button>
    </form>
  );
}

function PeriodForm({
  organizationId,
  busy,
  run,
}: {
  organizationId: string;
  busy: boolean;
  run: Runner;
}) {
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void run(
          () =>
            command(`/api/v1/organizations/${organizationId}/finance/periods/`, {
              starts_on: formText(form, "starts"),
              ends_on: formText(form, "ends"),
              label: formText(form, "label"),
            }),
          "Periodo creado.",
        );
      }}
    >
      <h2>Nuevo periodo mensual</h2>
      <label>
        Etiqueta
        <input name="label" required />
      </label>
      <label>
        Inicio
        <input name="starts" type="date" required />
      </label>
      <label>
        Fin exclusivo
        <input name="ends" type="date" required />
      </label>
      <button className="button" disabled={busy}>
        Crear periodo
      </button>
    </form>
  );
}

function PlanForm({
  organizationId,
  categories,
  events,
  busy,
  run,
}: {
  organizationId: string;
  categories: Category[];
  events: EvidenceContext["events"];
  busy: boolean;
  run: Runner;
}) {
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void run(
          () =>
            command(`/api/v1/organizations/${organizationId}/finance/direct-cost-plans/`, {
              root_reservation_id: formText(form, "root"),
              venue_id: formText(form, "venue"),
              currency: "USD",
              reason: formText(form, "reason"),
              lines: [
                {
                  category_id: formText(form, "category"),
                  description: formText(form, "description"),
                  amount: formText(form, "amount"),
                },
              ],
            }),
          "Revisión planificada publicada.",
        );
      }}
    >
      <h2>Publicar costo planificado</h2>
      <label>
        Raíz
        <select name="root">
          {events.map((item) => (
            <option key={item.root_reservation_id}>{item.root_reservation_id}</option>
          ))}
        </select>
      </label>
      <label>
        Sede histórica
        <input name="venue" required />
      </label>
      <label>
        Categoría<select name="category">{categoryOptions(categories, "direct_cost")}</select>
      </label>
      <label>
        Descripción
        <input name="description" required />
      </label>
      <label>
        Importe USD
        <input name="amount" required />
      </label>
      <label>
        Razón
        <input name="reason" required />
      </label>
      <button className="button" disabled={busy}>
        Publicar revisión
      </button>
    </form>
  );
}

function ActualForm({
  organizationId,
  categories,
  events,
  busy,
  run,
}: {
  organizationId: string;
  categories: Category[];
  events: EvidenceContext["events"];
  busy: boolean;
  run: Runner;
}) {
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void run(
          () =>
            command(`/api/v1/organizations/${organizationId}/finance/direct-costs/`, {
              root_reservation_id: formText(form, "root"),
              venue_id: formText(form, "venue"),
              category_id: formText(form, "category"),
              amount: formText(form, "amount"),
              currency: "USD",
              economic_date: formText(form, "date"),
              description: formText(form, "description"),
              evidence_reference: formText(form, "evidence"),
            }),
          "Costo real registrado.",
        );
      }}
    >
      <h2>Registrar costo directo real</h2>
      <label>
        Raíz
        <select name="root">
          {events.map((item) => (
            <option key={item.root_reservation_id}>{item.root_reservation_id}</option>
          ))}
        </select>
      </label>
      <label>
        Sede histórica
        <input name="venue" required />
      </label>
      <label>
        Categoría<select name="category">{categoryOptions(categories, "direct_cost")}</select>
      </label>
      <label>
        Importe USD
        <input name="amount" required />
      </label>
      <label>
        Fecha económica
        <input name="date" type="date" defaultValue={today} required />
      </label>
      <label>
        Descripción
        <input name="description" required />
      </label>
      <label>
        Referencia
        <input name="evidence" required />
      </label>
      <button className="button" disabled={busy}>
        Registrar costo
      </button>
    </form>
  );
}

function ExpenseForm({
  organizationId,
  categories,
  busy,
  run,
}: {
  organizationId: string;
  categories: Category[];
  busy: boolean;
  run: Runner;
}) {
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const amount = formText(form, "amount");
        const scope = formText(form, "scope");
        void run(
          () =>
            command(`/api/v1/organizations/${organizationId}/finance/expenses/`, {
              category_id: formText(form, "category"),
              expense_type: formText(form, "type"),
              amount,
              currency: "USD",
              economic_date: formText(form, "date"),
              description: formText(form, "description"),
              evidence_reference: formText(form, "evidence"),
              allocations: [
                {
                  scope,
                  root_reservation_id: scope === "event" ? formText(form, "root") : null,
                  venue_id: scope === "business" ? null : formText(form, "venue"),
                  amount,
                },
              ],
            }),
          "Gasto real registrado.",
        );
      }}
    >
      <h2>Registrar gasto real</h2>
      <label>
        Tipo
        <select name="type">
          <option value="variable">Variable</option>
          <option value="recurring">Recurrente manual</option>
        </select>
      </label>
      <label>
        Categoría<select name="category">{categoryOptions(categories)}</select>
      </label>
      <label>
        Importe USD
        <input name="amount" required />
      </label>
      <label>
        Fecha económica
        <input name="date" type="date" defaultValue={today} required />
      </label>
      <label>
        Asignación
        <select name="scope">
          <option value="business">Negocio</option>
          <option value="venue">Sede</option>
          <option value="event">Evento</option>
        </select>
      </label>
      <label>
        Raíz, si evento
        <input name="root" />
      </label>
      <label>
        Sede, si aplica
        <input name="venue" />
      </label>
      <label>
        Descripción
        <input name="description" required />
      </label>
      <label>
        Referencia
        <input name="evidence" required />
      </label>
      <button className="button" disabled={busy}>
        Registrar gasto
      </button>
    </form>
  );
}

function RecurringForm({
  organizationId,
  categories,
  rules,
  busy,
  run,
}: {
  organizationId: string;
  categories: Category[];
  rules: RecurringRule[];
  busy: boolean;
  run: Runner;
}) {
  return (
    <div className="command-box">
      <h2>Gastos recurrentes</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void run(
            () =>
              command(`/api/v1/organizations/${organizationId}/finance/recurring-rules/`, {
                category_id: formText(form, "category"),
                name: formText(form, "name"),
                amount: formText(form, "amount"),
                currency: "USD",
                day_of_month: Number(formText(form, "day")),
                valid_from: formText(form, "from"),
                valid_until: formText(form, "until") || null,
                default_venue_id: formText(form, "venue") || null,
              }),
            "Regla recurrente creada.",
          );
        }}
      >
        <label>
          Categoría
          <select name="category">{categoryOptions(categories, "recurring_expense")}</select>
        </label>
        <label>
          Nombre
          <input name="name" required />
        </label>
        <label>
          Importe USD
          <input name="amount" required />
        </label>
        <label>
          Día 1–28
          <input name="day" type="number" min="1" max="28" required />
        </label>
        <label>
          Vigente desde
          <input name="from" type="date" required />
        </label>
        <label>
          Vigente hasta
          <input name="until" type="date" />
        </label>
        <label>
          Sede por defecto
          <input name="venue" />
        </label>
        <button className="button" disabled={busy}>
          Crear regla
        </button>
      </form>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const rule = formText(form, "rule");
          void run(
            () =>
              command(
                `/api/v1/organizations/${organizationId}/finance/recurring-rules/${rule}/occurrences/`,
                {
                  economic_date: formText(form, "date"),
                  evidence_reference: formText(form, "evidence"),
                },
              ),
            "Ocurrencia recurrente materializada.",
          );
        }}
      >
        <label>
          Regla
          <select name="rule">
            {rules.map((rule) => (
              <option key={rule.id} value={rule.id}>
                {rule.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Fecha económica
          <input name="date" type="date" defaultValue={today} required />
        </label>
        <label>
          Referencia
          <input name="evidence" required />
        </label>
        <button className="button button--secondary" disabled={busy}>
          Materializar ocurrencia
        </button>
      </form>
    </div>
  );
}

function BudgetForm({
  organizationId,
  categories,
  periods,
  busy,
  run,
}: {
  organizationId: string;
  categories: Category[];
  periods: Period[];
  busy: boolean;
  run: Runner;
}) {
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void run(
          () =>
            command(`/api/v1/organizations/${organizationId}/finance/budgets/`, {
              period_id: formText(form, "period"),
              venue_id: formText(form, "venue") || null,
              currency: "USD",
              reason: formText(form, "reason"),
              lines: [
                { category_id: formText(form, "category"), amount: formText(form, "amount") },
              ],
            }),
          "Revisión presupuestaria publicada.",
        );
      }}
    >
      <h2>Publicar presupuesto</h2>
      <label>
        Periodo
        <select name="period">
          {periods
            .filter((period) => !period.closed)
            .map((period) => (
              <option key={period.id} value={period.id}>
                {period.label}
              </option>
            ))}
        </select>
      </label>
      <label>
        Sede opcional
        <input name="venue" />
      </label>
      <label>
        Categoría<select name="category">{categoryOptions(categories)}</select>
      </label>
      <label>
        Importe USD
        <input name="amount" required />
      </label>
      <label>
        Razón
        <input name="reason" required />
      </label>
      <button className="button" disabled={busy}>
        Publicar presupuesto
      </button>
    </form>
  );
}

function CashForm({
  organizationId,
  costs,
  expenses,
  movements,
  busy,
  run,
}: {
  organizationId: string;
  costs: FinancialFact[];
  expenses: FinancialFact[];
  movements: FinancialFact[];
  busy: boolean;
  run: Runner;
}) {
  const sourceOptions = [
    ...costs.map((item) => ({
      value: `outflow:direct_cost:${item.id}:`,
      label: `Salida · costo · ${item.description ?? item.id} · ${item.effective_amount}`,
    })),
    ...expenses.map((item) => ({
      value: `outflow:expense:${item.id}:`,
      label: `Salida · gasto · ${item.description ?? item.id} · ${item.effective_amount}`,
    })),
    ...movements
      .filter((item) => item.direction === "outflow")
      .map((item) => ({
        value: `recovery:${item.source_kind ?? ""}:${item.source_id ?? ""}:${item.id}`,
        label: `Recuperación · salida ${item.id} · ${item.effective_amount}`,
      })),
  ];
  const [selectedSource, setSelectedSource] = useState(sourceOptions[0]?.value ?? "");
  const [selectedDirection, selectedKind, selectedSourceId, selectedOutflowId] =
    selectedSource.split(":");
  const attributionTargets =
    selectedKind !== "expense"
      ? []
      : selectedDirection === "outflow"
        ? (expenses.find((item) => item.id === selectedSourceId)?.allocations ?? [])
        : (movements.find((item) => item.id === selectedOutflowId)
            ?.effective_expense_attributions ?? []);
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const [direction = "", sourceKind = "", sourceId = "", originalOutflowId = ""] = formText(
          form,
          "source",
        ).split(":");
        const expenseAttributions = attributionTargets.flatMap((attribution, index) => {
          const attributed = formText(form, "attribution-" + String(index));
          return attributed === "" ? [] : [{ ...attribution, amount: attributed }];
        });
        void run(
          () =>
            command(`/api/v1/organizations/${organizationId}/finance/cash-movements/`, {
              direction,
              source_kind: sourceKind,
              source_id: sourceId,
              original_outflow_id: originalOutflowId === "" ? null : originalOutflowId,
              amount: formText(form, "amount"),
              expense_attributions: expenseAttributions,
              economic_date: formText(form, "date"),
              reason: formText(form, "reason"),
              evidence_reference: formText(form, "evidence"),
            }),
          "Salida P11 registrada.",
        );
      }}
    >
      <h2>Registrar caja P11</h2>
      <label>
        Origen exacto
        <select
          name="source"
          value={selectedSource}
          onChange={(event) => {
            setSelectedSource(event.target.value);
          }}
        >
          {sourceOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {attributionTargets.length ? (
        <fieldset>
          <legend>Atribución monetaria explícita</legend>
          <p className="muted">Distribuye el importe sin prorrateos automáticos.</p>
          {attributionTargets.map((attribution, index) => (
            <label key={attributionKey(attribution, index)}>
              {attribution.scope} · {attribution.root_reservation_id ?? "sin raíz"} ·{" "}
              {attribution.venue_id ?? "sin sede"} · disponible {attribution.amount}
              <input name={"attribution-" + String(index)} inputMode="decimal" placeholder="0.00" />
            </label>
          ))}
        </fieldset>
      ) : null}
      <label>
        Importe USD
        <input name="amount" required />
      </label>
      <label>
        Fecha económica
        <input name="date" type="date" defaultValue={today} required />
      </label>
      <label>
        Razón
        <input name="reason" required />
      </label>
      <label>
        Referencia
        <input name="evidence" required />
      </label>
      <button className="button" disabled={busy}>
        Registrar movimiento
      </button>
    </form>
  );
}

function CorrectionsForm({
  organizationId,
  capabilities,
  costs,
  expenses,
  movements,
  recognition,
  busy,
  run,
}: {
  organizationId: string;
  capabilities: Set<string>;
  costs: FinancialFact[];
  expenses: FinancialFact[];
  movements: FinancialFact[];
  recognition: FinancialFact[];
  busy: boolean;
  run: Runner;
}) {
  const targets = [
    ...(capabilities.has("finance:record_actuals")
      ? costs.map((item) => ({
          kind: "cost",
          item,
          label: `Costo · ${item.description ?? item.id}`,
        }))
      : []),
    ...(capabilities.has("finance:allocate_expenses")
      ? expenses.map((item) => ({
          kind: "expense",
          item,
          label: `Gasto · ${item.description ?? item.id}`,
        }))
      : []),
    ...(capabilities.has("finance:record_cash")
      ? movements.map((item) => ({
          kind: "cash",
          item,
          label: `Caja · ${item.reason ?? item.id}`,
        }))
      : []),
    ...(capabilities.has("finance:adjust_recognition")
      ? recognition.map((item) => ({
          kind: "recognition",
          item,
          label: `Reconocimiento · ${item.reason ?? item.id}`,
        }))
      : []),
  ];
  const [selectedTargetValue, setSelectedTargetValue] = useState(
    targets[0] ? `${targets[0].kind}:${targets[0].item.id}` : "",
  );
  const [selectedTargetKind, selectedTargetId] = selectedTargetValue.split(":");
  const selectedTarget = targets.find(
    ({ kind, item }) => kind === selectedTargetKind && item.id === selectedTargetId,
  );
  const correctionAttributions =
    selectedTargetKind === "cash" && selectedTarget?.item.source_kind === "expense"
      ? (selectedTarget.item.effective_expense_attributions ?? [])
      : [];
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const [kind = "", id = ""] = formText(form, "target").split(":");
        const root = formText(form, "root");
        const venue = formText(form, "venue");
        const common = {
          direction: formText(form, "direction"),
          amount: formText(form, "amount"),
          economic_date: formText(form, "date"),
          reason: formText(form, "reason"),
        };
        const expenseAttributions = correctionAttributions.flatMap((attribution, index) => {
          const attributed = formText(form, "correction-attribution-" + String(index));
          return attributed === "" ? [] : [{ ...attribution, amount: attributed }];
        });
        const path =
          kind === "cost"
            ? `direct-costs/${id}/corrections/`
            : kind === "expense"
              ? `expenses/${id}/corrections/`
              : kind === "cash"
                ? `cash-movements/${id}/corrections/`
                : `recognition-adjustments/${id}/corrections/`;
        const body =
          kind === "cost"
            ? { ...common, evidence_reference: formText(form, "evidence") }
            : kind === "expense"
              ? {
                  ...common,
                  evidence_reference: formText(form, "evidence"),
                  scope: formText(form, "scope"),
                  root_reservation_id: root === "" ? null : root,
                  venue_id: venue === "" ? null : venue,
                }
              : kind === "cash"
                ? { ...common, expense_attributions: expenseAttributions }
                : common;
        void run(
          () => command(`/api/v1/organizations/${organizationId}/finance/${path}`, body),
          "Corrección tipada registrada.",
        );
      }}
    >
      <h2>Registrar corrección tipada</h2>
      <label>
        Hecho exacto
        <select
          name="target"
          required
          value={selectedTargetValue}
          onChange={(event) => {
            setSelectedTargetValue(event.target.value);
          }}
        >
          {targets.map(({ kind, item, label }) => (
            <option key={`${kind}-${item.id}`} value={`${kind}:${item.id}`}>
              {label} · {item.effective_amount}
            </option>
          ))}
        </select>
      </label>
      {correctionAttributions.length ? (
        <fieldset>
          <legend>Atribución monetaria de la corrección</legend>
          <p className="muted">Corrige únicamente porciones del movimiento original.</p>
          {correctionAttributions.map((attribution, index) => (
            <label key={attributionKey(attribution, index)}>
              {attribution.scope} · {attribution.root_reservation_id ?? "sin raíz"} ·{" "}
              {attribution.venue_id ?? "sin sede"} · vigente {attribution.amount}
              <input
                name={"correction-attribution-" + String(index)}
                inputMode="decimal"
                placeholder="0.00"
              />
            </label>
          ))}
        </fieldset>
      ) : null}
      <label>
        Dirección
        <select name="direction">
          <option value="increase">Aumenta</option>
          <option value="decrease">Disminuye</option>
        </select>
      </label>
      <label>
        Importe USD
        <input name="amount" required />
      </label>
      <label>
        Fecha económica
        <input name="date" type="date" defaultValue={today} required />
      </label>
      <label>
        Asignación, si corrige gasto
        <select name="scope">
          <option value="business">Negocio</option>
          <option value="venue">Sede</option>
          <option value="event">Evento</option>
        </select>
      </label>
      <label>
        Raíz, si evento
        <input name="root" />
      </label>
      <label>
        Sede, si aplica
        <input name="venue" />
      </label>
      <label>
        Razón
        <input name="reason" required />
      </label>
      <label>
        Evidencia, si costo o gasto
        <input name="evidence" />
      </label>
      <button className="button" disabled={busy || targets.length === 0}>
        Registrar corrección
      </button>
    </form>
  );
}

function RecognitionForm({
  organizationId,
  events,
  busy,
  run,
}: {
  organizationId: string;
  events: EvidenceContext["events"];
  busy: boolean;
  run: Runner;
}) {
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void run(
          () =>
            command(`/api/v1/organizations/${organizationId}/finance/recognition-adjustments/`, {
              root_reservation_id: formText(form, "root"),
              direction: formText(form, "direction"),
              amount: formText(form, "amount"),
              currency: "USD",
              economic_date: formText(form, "date"),
              reason_code: formText(form, "code"),
              reason: formText(form, "reason"),
              evidence_reference: formText(form, "evidence"),
            }),
          "Ajuste de reconocimiento registrado.",
        );
      }}
    >
      <h2>Ajustar ingreso reconocido</h2>
      <p className="muted">Solo medición, omisión o duplicidad; no consecuencias de cancelación.</p>
      <label>
        Raíz completada
        <select name="root">
          {events.map((item) => (
            <option key={item.root_reservation_id}>{item.root_reservation_id}</option>
          ))}
        </select>
      </label>
      <label>
        Dirección
        <select name="direction">
          <option value="increase">Aumenta</option>
          <option value="decrease">Disminuye</option>
        </select>
      </label>
      <label>
        Importe USD
        <input name="amount" required />
      </label>
      <label>
        Fecha económica
        <input name="date" type="date" defaultValue={today} required />
      </label>
      <label>
        Tipo de corrección
        <select name="code">
          <option value="measurement_correction">Medición</option>
          <option value="omission_correction">Omisión</option>
          <option value="duplicate_correction">Duplicidad</option>
        </select>
      </label>
      <label>
        Razón
        <input name="reason" required />
      </label>
      <label>
        Referencia
        <input name="evidence" required />
      </label>
      <button className="button" disabled={busy}>
        Registrar ajuste
      </button>
    </form>
  );
}

function EvidenceDecisions({
  organizationId,
  evidence,
  busy,
  run,
}: {
  organizationId: string;
  evidence: Evidence[];
  busy: boolean;
  run: Runner;
}) {
  const pending = evidence.filter((item) => item.decision === null);
  return (
    <article className="command-box">
      <h2>Evidencia pendiente</h2>
      {pending.length === 0 ? (
        <p className="muted">No hay evidencia pendiente.</p>
      ) : (
        pending.map((item) => (
          <div className="finance-decision" key={item.id}>
            <span>
              {item.description} · {item.amount} {item.currency}
            </span>
            <button
              className="button"
              disabled={busy}
              onClick={() =>
                void run(
                  () =>
                    command(
                      `/api/v1/organizations/${organizationId}/finance/cost-evidence/${item.id}/decision/`,
                      { decision: "approved", reason: "Evidencia financiera revisada" },
                    ),
                  "Evidencia aprobada y costo materializado.",
                )
              }
            >
              Aprobar
            </button>
            <button
              className="button button--secondary"
              disabled={busy}
              onClick={() =>
                void run(
                  () =>
                    command(
                      `/api/v1/organizations/${organizationId}/finance/cost-evidence/${item.id}/decision/`,
                      { decision: "rejected", reason: "Evidencia financiera rechazada" },
                    ),
                  "Evidencia rechazada.",
                )
              }
            >
              Rechazar
            </button>
          </div>
        ))
      )}
    </article>
  );
}

function ClosePeriods({
  organizationId,
  periods,
  busy,
  run,
}: {
  organizationId: string;
  periods: Period[];
  busy: boolean;
  run: Runner;
}) {
  return (
    <article className="command-box">
      <h2>Cierres operativos</h2>
      {periods
        .filter((period) => !period.closed)
        .map((period) => (
          <div className="finance-decision" key={period.id}>
            <span>{period.label}</span>
            <button
              className="button"
              disabled={busy}
              onClick={() =>
                void run(
                  () =>
                    command(
                      `/api/v1/organizations/${organizationId}/finance/periods/${period.id}/close/`,
                    ),
                  "Periodo cerrado con snapshot inmutable.",
                )
              }
            >
              Cerrar periodo
            </button>
          </div>
        ))}
    </article>
  );
}
