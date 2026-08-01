import { useMemo, useState, type SyntheticEvent } from "react";

import { api, type EventRequest, type Quotation, type QuotationLine } from "../../api";
import { Notice, StatusBadge } from "../../shared/components";
import { formText, message } from "../../shared/utilities";

export function QuoteEditor({
  organizationId,
  request,
  quotation,
  canManage,
  onChanged,
}: {
  organizationId: string;
  request: EventRequest;
  quotation: Quotation | null;
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const latest = quotation?.versions.at(-1) ?? null;
  const [lines, setLines] = useState<QuotationLine[]>(
    latest?.lines ?? [
      {
        description: "",
        unit_label: "evento",
        quantity: "1.000",
        unit_price: "0.00",
        discount_amount: "0.00",
      },
    ],
  );
  const defaultValidity = useMemo(() => {
    const date = new Date();
    date.setDate(date.getDate() + 3);
    return date.toISOString().slice(0, 16);
  }, []);
  async function action(operation: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await operation();
      await onChanged();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }
  async function createQuote() {
    await action(() =>
      api(`/api/v1/organizations/${organizationId}/event-requests/${request.id}/quotations/`, {
        method: "POST",
        body: JSON.stringify({ valid_until: new Date(defaultValidity).toISOString() }),
      }),
    );
  }
  async function createVersion() {
    if (!quotation) return;
    await action(() =>
      api(`/api/v1/organizations/${organizationId}/quotations/${quotation.id}/versions/`, {
        method: "POST",
        body: JSON.stringify({ valid_until: new Date(defaultValidity).toISOString() }),
      }),
    );
  }
  async function save(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!quotation || !latest) return;
    const form = new FormData(event.currentTarget);
    await action(() =>
      api(
        `/api/v1/organizations/${organizationId}/quotations/${quotation.id}/versions/${String(latest.version)}/`,
        {
          method: "PUT",
          body: JSON.stringify({
            revision: latest.revision,
            valid_until: new Date(formText(form, "valid_until")).toISOString(),
            notes: formText(form, "notes"),
            lines,
          }),
        },
      ),
    );
  }
  function updateLine(index: number, field: keyof QuotationLine, value: string) {
    setLines((current) =>
      current.map((line, position) => (position === index ? { ...line, [field]: value } : line)),
    );
  }

  if (!quotation)
    return (
      <section className="panel">
        <h2>Cotización</h2>
        <p className="muted">Prepara una propuesta con precios y vigencia.</p>
        {error && <Notice>{error}</Notice>}
        {canManage && (
          <button
            className="button button--primary"
            disabled={busy}
            onClick={() => void createQuote()}
          >
            Crear cotización
          </button>
        )}
      </section>
    );
  return (
    <section className="panel" aria-labelledby="quote-title">
      <header className="panel-header">
        <div>
          <p className="eyebrow">{quotation.visible_number}</p>
          <h2 id="quote-title">Cotización · versión {latest?.version}</h2>
        </div>
        {latest && <StatusBadge value={latest.status} />}
      </header>
      {error && <Notice>{error}</Notice>}
      {latest?.stored_status === "draft" && canManage ? (
        <form className="form-stack" onSubmit={(event) => void save(event)}>
          <div className="form-grid">
            <label>
              Vigencia
              <input
                name="valid_until"
                type="datetime-local"
                defaultValue={latest.valid_until.slice(0, 16)}
                required
              />
            </label>
            <label className="span-two">
              Notas
              <textarea name="notes" defaultValue={latest.notes} rows={2} />
            </label>
          </div>
          <div className="line-list">
            <div className="line-header">
              <h3>Líneas</h3>
              <button
                type="button"
                className="button button--ghost"
                onClick={() => {
                  setLines((current) => [
                    ...current,
                    {
                      description: "",
                      unit_label: "unidad",
                      quantity: "1.000",
                      unit_price: "0.00",
                      discount_amount: "0.00",
                    },
                  ]);
                }}
              >
                Añadir línea
              </button>
            </div>
            {lines.map((line, index) => (
              <div className="quote-line" key={line.id ?? index}>
                <label>
                  Descripción
                  <input
                    required
                    value={line.description}
                    onChange={(event) => {
                      updateLine(index, "description", event.target.value);
                    }}
                  />
                </label>
                <label>
                  Cantidad
                  <input
                    type="number"
                    min="0.001"
                    step="0.001"
                    required
                    value={line.quantity}
                    onChange={(event) => {
                      updateLine(index, "quantity", event.target.value);
                    }}
                  />
                </label>
                <label>
                  Precio USD
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={line.unit_price}
                    onChange={(event) => {
                      updateLine(index, "unit_price", event.target.value);
                    }}
                  />
                </label>
                <label>
                  Descuento USD
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={line.discount_amount}
                    onChange={(event) => {
                      updateLine(index, "discount_amount", event.target.value);
                    }}
                  />
                </label>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`Eliminar línea ${String(index + 1)}`}
                  disabled={lines.length === 1}
                  onClick={() => {
                    setLines((current) => current.filter((_, position) => position !== index));
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          <div className="form-actions">
            <button className="button button--secondary" disabled={busy}>
              Guardar borrador
            </button>
            <button
              type="button"
              className="button button--primary"
              disabled={busy || latest.lines.length === 0}
              onClick={() =>
                void action(() =>
                  api(
                    `/api/v1/organizations/${organizationId}/quotations/${quotation.id}/versions/${String(latest.version)}/issue/`,
                    { method: "POST", body: "{}" },
                  ),
                )
              }
            >
              Emitir cotización
            </button>
          </div>
        </form>
      ) : (
        latest && (
          <div>
            <div className="money-summary">
              <div>
                <span>Subtotal</span>
                <strong>${latest.subtotal}</strong>
              </div>
              <div>
                <span>Descuentos</span>
                <strong>− ${latest.discount_total}</strong>
              </div>
              <div className="money-total">
                <span>Total</span>
                <strong>${latest.total} USD</strong>
              </div>
            </div>
            {canManage &&
              (request.status === "new" || request.status === "quoted") &&
              latest.status !== "draft" && (
                <button
                  className="button button--secondary"
                  disabled={busy}
                  onClick={() => {
                    void createVersion();
                  }}
                >
                  Crear nueva versión
                </button>
              )}
            {latest.status === "issued" && canManage && (
              <AcceptanceForm
                busy={busy}
                onAccept={(channel, note) =>
                  action(() =>
                    api(
                      `/api/v1/organizations/${organizationId}/quotations/${quotation.id}/versions/${String(latest.version)}/accept/`,
                      { method: "POST", body: JSON.stringify({ channel, note }) },
                    ),
                  )
                }
              />
            )}
          </div>
        )
      )}
    </section>
  );
}

function AcceptanceForm({
  busy,
  onAccept,
}: {
  busy: boolean;
  onAccept: (channel: string, note: string) => Promise<void>;
}) {
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void onAccept(formText(form, "channel"), formText(form, "note"));
      }}
    >
      <h3>Registrar aceptación</h3>
      <p>Esta acción crea una reserva provisional por 48 horas.</p>
      <div className="form-grid">
        <label>
          Canal
          <select name="channel" defaultValue="whatsapp">
            <option value="whatsapp">WhatsApp</option>
            <option value="phone_call">Llamada</option>
            <option value="email">Correo</option>
            <option value="in_person">Presencial</option>
            <option value="other">Otro</option>
          </select>
        </label>
        <label>
          Nota
          <input name="note" />
        </label>
      </div>
      <button className="button button--primary" disabled={busy}>
        Aceptar y bloquear fecha
      </button>
    </form>
  );
}
