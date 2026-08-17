import { useCallback, useMemo, useState } from "react";

import { api } from "../../api";
import { Loading, Notice, StatusBadge } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { formText, message } from "../../shared/utilities";

interface Obligation {
  id: string;
  root_reservation_id: string;
  current_reservation_id: string;
  counterparty_person_id: string;
  counterparty_name: string;
  currency: string;
  original_total: string;
  adjusted_total: string;
  applied_total: string;
  balance: string;
  derived_status: string;
  reservation_status: string;
  financial_review_required: boolean;
  schedule_configured: boolean;
  schedule: {
    due_key: string;
    amount: string;
    currency: string;
    due_on: string;
    revision: number;
  }[];
}

interface Payment {
  id: string;
  counterparty_person_id: string;
  root_reservation_id: string | null;
  amount: string;
  currency: string;
  reported_at: string;
  method: string;
  reference: string;
  provenance: string;
  evidence_level: string;
  possible_duplicate: boolean;
  unapplied_amount: string;
}

interface Statement extends Obligation {
  payments: Payment[];
  applications: {
    id: string;
    payment_id: string;
    obligation_id: string;
    due_key: string | null;
    amount: string;
    currency: string;
    applied_at: string;
    restored_by_refunds: string;
    reversed: boolean;
  }[];
  adjustments: {
    id: string;
    direction: string;
    amount: string;
    currency: string;
    reason: string;
  }[];
  refunds: {
    id: string;
    payment_id: string;
    amount: string;
    currency: string;
    reason: string;
  }[];
  reversals: { id: string; target_kind: string; target_id: string; amount: string }[];
  receipts: {
    id: string;
    visible_number: string;
    payment_id: string;
    document_artifact_id: string | null;
  }[];
}

interface AgingEntry {
  obligation_id: string;
  bucket: string;
  open_amount: string;
  currency: string;
  days_overdue: number | null;
}

const bucketLabels: Record<string, string> = {
  current: "Vigente / no vencido",
  "1_30": "1–30 días",
  "31_60": "31–60 días",
  "61_90": "61–90 días",
  over_90: "Más de 90 días",
  unscheduled: "Sin vencimiento configurado",
};

const paymentMethods = [
  ["cash", "Efectivo"],
  ["bank_transfer", "Transferencia bancaria"],
  ["card_external", "Tarjeta externa"],
  ["check", "Cheque"],
  ["other", "Otro medio externo"],
];

function money(value: string | number, currency: string) {
  return new Intl.NumberFormat("es-EC", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(Number(value));
}

function command(path: string, body: object) {
  return api(path, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(body),
  });
}

export function ReceivablesView({
  organizationId,
  capabilities,
}: {
  organizationId: string;
  capabilities: Set<string>;
}) {
  const [obligations, setObligations] = useState<Obligation[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [aging, setAging] = useState<AgingEntry[]>([]);
  const [selectedObligationId, setSelectedObligationId] = useState("");
  const [selectedPaymentId, setSelectedPaymentId] = useState("");
  const [statement, setStatement] = useState<Statement | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [portfolio, paymentBody, agingBody] = await Promise.all([
        api<{ obligations: Obligation[] }>(
          `/api/v1/organizations/${organizationId}/receivables/portfolio/`,
        ),
        api<{ payments: Payment[] }>(
          `/api/v1/organizations/${organizationId}/receivables/payments/`,
        ),
        api<{ entries: AgingEntry[] }>(
          `/api/v1/organizations/${organizationId}/receivables/aging/`,
        ),
      ]);
      setObligations(portfolio.obligations);
      setPayments(paymentBody.payments);
      setAging(agingBody.entries);
      setSelectedObligationId((current) =>
        current.length > 0 ? current : (portfolio.obligations[0]?.id ?? ""),
      );
      setSelectedPaymentId((current) =>
        current.length > 0 ? current : (paymentBody.payments[0]?.id ?? ""),
      );
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  const loadStatement = useCallback(async () => {
    if (!selectedObligationId) {
      setStatement(null);
      return;
    }
    try {
      setStatement(
        await api<Statement>(
          `/api/v1/organizations/${organizationId}/receivables/obligations/${selectedObligationId}/statement/`,
        ),
      );
    } catch (caught) {
      setError(message(caught));
    }
  }, [organizationId, selectedObligationId]);

  useInitialLoad(load);
  useInitialLoad(loadStatement);

  const selected = obligations.find((item) => item.id === selectedObligationId) ?? null;
  const selectedPayment = payments.find((item) => item.id === selectedPaymentId) ?? null;
  const totals = useMemo(
    () =>
      obligations.reduce(
        (result, item) => ({
          due: result.due + Number(item.adjusted_total),
          applied: result.applied + Number(item.applied_total),
          balance: result.balance + Number(item.balance),
        }),
        { due: 0, applied: 0, balance: 0 },
      ),
    [obligations],
  );

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      await load();
      await loadStatement();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading label="Reconstruyendo cartera…" />;
  return (
    <section className="receivables-page" aria-labelledby="receivables-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Control de cobros</p>
          <h1 id="receivables-title">Cartera y pagos recibidos</h1>
          <p className="muted">Movimientos externos declarados; Claridez no custodia fondos.</p>
        </div>
        <button className="button button--secondary" onClick={() => void load()} disabled={busy}>
          Actualizar
        </button>
      </header>
      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice>{notice}</Notice> : null}

      <div className="receivables-metrics" aria-label="Resumen de cartera">
        <article>
          <span>Total ajustado</span>
          <strong>{money(totals.due, obligations[0]?.currency ?? "USD")}</strong>
        </article>
        <article>
          <span>Aplicado</span>
          <strong>{money(totals.applied, obligations[0]?.currency ?? "USD")}</strong>
        </article>
        <article>
          <span>Saldo pendiente</span>
          <strong>{money(totals.balance, obligations[0]?.currency ?? "USD")}</strong>
        </article>
        <article>
          <span>Sin aplicar</span>
          <strong>
            {money(
              payments.reduce((sum, item) => sum + Number(item.unapplied_amount), 0),
              payments[0]?.currency ?? "USD",
            )}
          </strong>
        </article>
      </div>

      <section className="panel" aria-labelledby="aging-title">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Antigüedad</p>
            <h2 id="aging-title">Saldo por vencimiento explícito</h2>
          </div>
        </div>
        <div className="aging-grid">
          {Object.entries(bucketLabels).map(([key, label]) => {
            const rows = aging.filter((item) => item.bucket === key);
            return (
              <article key={key}>
                <span>{label}</span>
                <strong>
                  {money(
                    rows.reduce((sum, item) => sum + Number(item.open_amount), 0),
                    rows[0]?.currency ?? "USD",
                  )}
                </strong>
                <small>{rows.length} vencimiento(s)</small>
              </article>
            );
          })}
        </div>
      </section>

      <div className="receivables-layout">
        <section className="panel obligation-list" aria-labelledby="obligations-title">
          <h2 id="obligations-title">Obligaciones</h2>
          {obligations.length === 0 ? (
            <p className="muted">Todavía no existen raíces confirmadas con obligación.</p>
          ) : (
            obligations.map((item) => (
              <button
                key={item.id}
                aria-pressed={selectedObligationId === item.id}
                onClick={() => {
                  setSelectedObligationId(item.id);
                }}
              >
                <span>
                  <strong>{item.counterparty_name}</strong>
                  <small>{item.schedule_configured ? "Con vencimientos" : "Sin vencimiento"}</small>
                </span>
                <span>
                  <strong>{money(item.balance, item.currency)}</strong>
                  <StatusBadge value={item.derived_status} />
                </span>
              </button>
            ))
          )}
        </section>

        <section className="panel receivable-detail" aria-labelledby="obligation-detail-title">
          <h2 id="obligation-detail-title">Detalle y estado de cuenta</h2>
          {!selected || !statement ? (
            <p className="muted">Selecciona una obligación.</p>
          ) : (
            <>
              {statement.financial_review_required ? (
                <Notice>
                  La reserva está cancelada. Requiere revisión financiera; no se aplicó ninguna
                  consecuencia monetaria automática.
                </Notice>
              ) : null}
              <dl className="details">
                <div>
                  <dt>Original</dt>
                  <dd>{money(statement.original_total, statement.currency)}</dd>
                </div>
                <div>
                  <dt>Aplicado neto</dt>
                  <dd>{money(statement.applied_total, statement.currency)}</dd>
                </div>
                <div>
                  <dt>Saldo</dt>
                  <dd>{money(statement.balance, statement.currency)}</dd>
                </div>
                <div>
                  <dt>Calendario</dt>
                  <dd>{statement.schedule_configured ? "Configurado" : "Sin vencimiento"}</dd>
                </div>
              </dl>
              <div className="movement-table" role="region" aria-label="Movimientos" tabIndex={0}>
                <table>
                  <thead>
                    <tr>
                      <th>Hecho</th>
                      <th>Referencia</th>
                      <th>Importe</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Obligación original</td>
                      <td>Confirmación de raíz</td>
                      <td>{money(statement.original_total, statement.currency)}</td>
                    </tr>
                    {statement.applications.map((item) => (
                      <tr key={item.id}>
                        <td>{item.reversed ? "Aplicación reversada" : "Aplicación"}</td>
                        <td>{item.id}</td>
                        <td>{money(item.amount, item.currency)}</td>
                      </tr>
                    ))}
                    {statement.adjustments.map((item) => (
                      <tr key={item.id}>
                        <td>Ajuste · {item.direction}</td>
                        <td>{item.reason}</td>
                        <td>{money(item.amount, item.currency)}</td>
                      </tr>
                    ))}
                    {statement.refunds.map((item) => (
                      <tr key={item.id}>
                        <td>Devolución externa</td>
                        <td>{item.reason}</td>
                        <td>{money(item.amount, item.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {statement.receipts.length ? (
                <div className="receipt-list">
                  <h3>Recibos — no factura</h3>
                  {statement.receipts.map((receipt) => (
                    <a
                      key={receipt.id}
                      className="button button--secondary"
                      href={`/api/v1/organizations/${organizationId}/receivables/receipts/${receipt.id}/pdf/`}
                    >
                      Descargar {receipt.visible_number}
                    </a>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </section>
      </div>

      <div className="financial-actions">
        {capabilities.has("receivables:record_payment") && selected ? (
          <form
            className="panel command-box"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              void run(
                () =>
                  command(`/api/v1/organizations/${organizationId}/receivables/payments/`, {
                    counterparty_person_id: selected.counterparty_person_id,
                    root_reservation_id: selected.root_reservation_id,
                    amount: formText(form, "amount"),
                    currency: selected.currency,
                    reported_at: new Date(formText(form, "reported_at")).toISOString(),
                    method: formText(form, "method"),
                    reference: formText(form, "reference"),
                    observation: formText(form, "observation"),
                    evidence_level: "internal_report",
                    duplicate_review_note: formText(form, "duplicate_review_note"),
                  }),
                "Pago recibido registrado. El dinero todavía puede estar sin aplicar.",
              );
            }}
          >
            <h2>Registrar pago externo</h2>
            <label>
              Importe {selected.currency}
              <input name="amount" type="number" min="0.01" step="0.01" required />
            </label>
            <label>
              Fecha y hora reportada
              <input name="reported_at" type="datetime-local" required />
            </label>
            <label>
              Método
              <select name="method">
                {paymentMethods.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Referencia
              <input name="reference" />
            </label>
            <label>
              Observación
              <textarea name="observation" rows={2} />
            </label>
            <label>
              Nota de revisión de posible duplicado
              <input name="duplicate_review_note" />
            </label>
            <button className="button button--primary" disabled={busy}>
              Registrar pago
            </button>
          </form>
        ) : null}

        {capabilities.has("receivables:apply_payment") && selected ? (
          <form
            className="panel command-box"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const paymentId = formText(form, "payment_id");
              void run(
                () =>
                  command(
                    `/api/v1/organizations/${organizationId}/receivables/payments/${paymentId}/applications/`,
                    {
                      obligation_id: selected.id,
                      due_key: formText(form, "due_key") || null,
                      amount: formText(form, "amount"),
                    },
                  ),
                "Pago aplicado al saldo seleccionado.",
              );
            }}
          >
            <h2>Aplicar pago</h2>
            <label>
              Pago con importe disponible
              <select
                name="payment_id"
                value={selectedPaymentId}
                onChange={(event) => {
                  setSelectedPaymentId(event.target.value);
                }}
                required
              >
                <option value="">Selecciona un pago</option>
                {payments
                  .filter((item) => Number(item.unapplied_amount) > 0)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {money(item.unapplied_amount, item.currency)} sin aplicar · {item.reference}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Vencimiento opcional
              <select name="due_key">
                <option value="">Sin asignar a vencimiento</option>
                {selected.schedule.map((due) => (
                  <option key={due.due_key} value={due.due_key}>
                    {due.due_on} · {money(due.amount, due.currency)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Importe
              <input name="amount" type="number" min="0.01" step="0.01" required />
            </label>
            <button className="button button--primary" disabled={busy || !selectedPaymentId}>
              Aplicar
            </button>
          </form>
        ) : null}

        {capabilities.has("receivables:manage_schedule") && selected ? (
          <form
            className="panel command-box"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const dues = formText(form, "dues")
                .split("\n")
                .map((line) => line.trim())
                .filter(Boolean)
                .map((line) => {
                  const [due_on, amount] = line.split(",").map((value) => value.trim());
                  return { due_on, amount };
                });
              void run(
                () =>
                  command(
                    `/api/v1/organizations/${organizationId}/receivables/obligations/${selected.id}/schedule/`,
                    { dues, provenance: "manual", reason: formText(form, "reason") },
                  ),
                "Nueva revisión de calendario publicada sin borrar la anterior.",
              );
            }}
          >
            <h2>Revisar calendario operativo</h2>
            <p className="muted">Una línea por vencimiento: AAAA-MM-DD, importe.</p>
            <label>
              Vencimientos
              <textarea name="dues" rows={4} placeholder="2026-09-15, 800.00" />
            </label>
            <label>
              Razón obligatoria
              <input name="reason" required />
            </label>
            <button className="button button--primary" disabled={busy}>
              Publicar revisión
            </button>
          </form>
        ) : null}

        {capabilities.has("receivables:record_adjustment") && selected ? (
          <form
            className="panel command-box"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              void run(
                () =>
                  command(
                    `/api/v1/organizations/${organizationId}/receivables/obligations/${selected.id}/adjustments/`,
                    {
                      direction: formText(form, "direction"),
                      amount: formText(form, "amount"),
                      currency: selected.currency,
                      reason: formText(form, "reason"),
                    },
                  ),
                "Ajuste append-only registrado.",
              );
            }}
          >
            <h2>Registrar ajuste</h2>
            <label>
              Dirección
              <select name="direction">
                <option value="increase">Aumenta obligación</option>
                <option value="decrease">Disminuye obligación</option>
              </select>
            </label>
            <label>
              Importe
              <input name="amount" type="number" min="0.01" step="0.01" required />
            </label>
            <label>
              Razón obligatoria
              <input name="reason" required />
            </label>
            <button className="button button--primary" disabled={busy}>
              Registrar ajuste
            </button>
          </form>
        ) : null}

        {capabilities.has("receivables:reverse_movement") && statement ? (
          <form
            className="panel command-box"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const [kind, id] = formText(form, "movement").split(":");
              if (!kind || !id) {
                setError("Selecciona un movimiento válido.");
                return;
              }
              void run(
                () =>
                  command(
                    `/api/v1/organizations/${organizationId}/receivables/movements/${kind}/${id}/reverse/`,
                    { reason: formText(form, "reason") },
                  ),
                "Reverso completo registrado; el hecho original permanece.",
              );
            }}
          >
            <h2>Reversar movimiento</h2>
            <label>
              Movimiento
              <select name="movement" required>
                <option value="">Selecciona un movimiento</option>
                {statement.applications
                  .filter((item) => !item.reversed)
                  .map((item) => (
                    <option key={item.id} value={`application:${item.id}`}>
                      Aplicación · {money(item.amount, item.currency)}
                    </option>
                  ))}
                {statement.adjustments.map((item) => (
                  <option key={item.id} value={`adjustment:${item.id}`}>
                    Ajuste · {money(item.amount, item.currency)}
                  </option>
                ))}
                {statement.refunds.map((item) => (
                  <option key={item.id} value={`refund:${item.id}`}>
                    Devolución · {money(item.amount, item.currency)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Razón obligatoria
              <input name="reason" required />
            </label>
            <button className="button button--danger" disabled={busy}>
              Registrar reverso completo
            </button>
          </form>
        ) : null}

        {capabilities.has("receivables:record_refund") && selectedPayment && statement ? (
          <form
            className="panel command-box"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const applicationId = formText(form, "application_id");
              const allocationAmount = formText(form, "allocation_amount");
              void run(
                () =>
                  command(
                    `/api/v1/organizations/${organizationId}/receivables/payments/${selectedPayment.id}/refunds/`,
                    {
                      obligation_id: applicationId ? selected?.id : null,
                      amount: formText(form, "amount"),
                      currency: selectedPayment.currency,
                      refunded_at: new Date(formText(form, "refunded_at")).toISOString(),
                      method: formText(form, "method"),
                      reference: formText(form, "reference"),
                      reason: formText(form, "reason"),
                      allocations: applicationId
                        ? [{ application_id: applicationId, amount: allocationAmount }]
                        : [],
                    },
                  ),
                "Devolución externa registrada; Claridez no ejecutó el reembolso.",
              );
            }}
          >
            <h2>Registrar devolución externa</h2>
            <label>
              Pago de origen
              <select
                value={selectedPaymentId}
                onChange={(event) => {
                  setSelectedPaymentId(event.target.value);
                }}
              >
                {payments.map((item) => (
                  <option key={item.id} value={item.id}>
                    {money(item.amount, item.currency)} · {item.reference || item.method}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Importe total devuelto
              <input name="amount" type="number" min="0.01" step="0.01" required />
            </label>
            <label>
              Aplicación que reabre saldo (opcional)
              <select name="application_id">
                <option value="">Devuelve dinero sin aplicar</option>
                {statement.applications
                  .filter((item) => item.payment_id === selectedPayment.id && !item.reversed)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {money(item.amount, item.currency)}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Importe que reabre esa aplicación
              <input name="allocation_amount" type="number" min="0.01" step="0.01" />
            </label>
            <label>
              Fecha y hora de devolución
              <input name="refunded_at" type="datetime-local" required />
            </label>
            <label>
              Método
              <select name="method">
                {paymentMethods.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Referencia
              <input name="reference" />
            </label>
            <label>
              Razón obligatoria
              <input name="reason" required />
            </label>
            <button className="button button--danger" disabled={busy}>
              Registrar devolución
            </button>
          </form>
        ) : null}

        {capabilities.has("receivables:issue_receipt") && selectedPayment ? (
          <form
            className="panel command-box"
            onSubmit={(event) => {
              event.preventDefault();
              void run(
                () =>
                  command(
                    `/api/v1/organizations/${organizationId}/receivables/payments/${selectedPayment.id}/receipts/`,
                    {},
                  ),
                "Recibo lógico emitido; su PDF se genera como artefacto no fiscal.",
              );
            }}
          >
            <h2>Emitir recibo</h2>
            <p>
              Snapshot inmutable del pago y sus aplicaciones. <strong>No es factura.</strong>
            </p>
            <button className="button button--primary" disabled={busy}>
              Emitir para el pago seleccionado
            </button>
          </form>
        ) : null}

        {capabilities.has("receivables:record_payment") && selectedPayment ? (
          <form
            className="panel command-box"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              void run(
                () =>
                  api(
                    `/api/v1/organizations/${organizationId}/receivables/payments/${selectedPayment.id}/evidence/`,
                    { method: "POST", body: form },
                  ),
                "Comprobante enviado a cuarentena. No valida el pago.",
              );
            }}
          >
            <h2>Adjuntar comprobante privado</h2>
            <label>
              PDF, JPG o PNG
              <input
                name="file"
                type="file"
                accept="application/pdf,image/jpeg,image/png"
                required
              />
            </label>
            <button className="button button--secondary" disabled={busy}>
              Enviar a análisis
            </button>
          </form>
        ) : null}
      </div>
    </section>
  );
}
