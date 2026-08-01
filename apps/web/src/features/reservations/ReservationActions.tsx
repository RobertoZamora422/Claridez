import { useState } from "react";

import { api, type Reservation } from "../../api";
import { Notice, StatusBadge } from "../../shared/components";
import { formText, message } from "../../shared/utilities";

export function ReservationActions({
  organizationId,
  reservation,
  capabilities,
  onChanged,
}: {
  organizationId: string;
  reservation: Reservation;
  capabilities: Set<string>;
  onChanged: () => Promise<void>;
}) {
  const [kind, setKind] = useState<"external_deposit" | "waiver">("external_deposit");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run(operation: () => Promise<unknown>) {
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
  return (
    <section className="panel" aria-labelledby="reservation-title">
      <header className="panel-header">
        <div>
          <p className="eyebrow">Control de agenda</p>
          <h2 id="reservation-title">Reserva</h2>
        </div>
        <StatusBadge value={reservation.status} />
      </header>
      {error && <Notice>{error}</Notice>}
      {reservation.status === "provisional" && capabilities.has("reservation:confirm") && (
        <form
          className="command-box"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void run(() =>
              api(
                `/api/v1/organizations/${organizationId}/reservations/${reservation.id}/confirm/`,
                {
                  method: "POST",
                  body: JSON.stringify(
                    kind === "external_deposit"
                      ? {
                          kind,
                          recognized_amount: formText(form, "recognized_amount"),
                          reported_at: new Date(formText(form, "reported_at")).toISOString(),
                          reference: formText(form, "reference"),
                        }
                      : { kind, waiver_reason: formText(form, "waiver_reason") },
                  ),
                },
              ),
            );
          }}
        >
          <h3>Confirmar reserva</h3>
          <p>Claridez registra una constancia operativa; no procesa el pago.</p>
          {capabilities.has("reservation:waive_deposit") && (
            <div className="segmented">
              <button
                type="button"
                aria-pressed={kind === "external_deposit"}
                onClick={() => {
                  setKind("external_deposit");
                }}
              >
                Anticipo externo
              </button>
              <button
                type="button"
                aria-pressed={kind === "waiver"}
                onClick={() => {
                  setKind("waiver");
                }}
              >
                Excepción
              </button>
            </div>
          )}
          {kind === "external_deposit" ? (
            <div className="form-grid">
              <label>
                Monto reconocido USD
                <input name="recognized_amount" type="number" min="0.01" step="0.01" required />
              </label>
              <label>
                Fecha y hora informada
                <input name="reported_at" type="datetime-local" required />
              </label>
              <label className="span-two">
                Referencia o nota
                <input name="reference" required />
              </label>
            </div>
          ) : (
            <label>
              Razón de la excepción
              <textarea name="waiver_reason" required rows={3} />
            </label>
          )}
          <button className="button button--primary" disabled={busy}>
            Confirmar reserva
          </button>
        </form>
      )}
      {reservation.confirmed_at && (
        <div className="evidence">
          <h3>
            {reservation.confirmation_kind === "waiver"
              ? "Excepción autorizada"
              : "Anticipo reconocido externamente"}
          </h3>
          {reservation.recognized_deposit_amount && (
            <p>
              <strong>${reservation.recognized_deposit_amount} USD</strong> · No procesado por
              Claridez
            </p>
          )}
          <p>{reservation.deposit_reference ?? reservation.waiver_reason}</p>
        </div>
      )}
      {["provisional", "confirmed"].includes(reservation.status) &&
        capabilities.has("reservation:cancel") && (
          <form
            className="danger-zone"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              void run(() =>
                api(
                  `/api/v1/organizations/${organizationId}/reservations/${reservation.id}/cancel/`,
                  { method: "POST", body: JSON.stringify({ reason: formText(form, "reason") }) },
                ),
              );
            }}
          >
            <label>
              Razón de cancelación
              <input name="reason" required />
            </label>
            <button className="button button--danger" disabled={busy}>
              Cancelar reserva
            </button>
          </form>
        )}
    </section>
  );
}
