import { useCallback, useState } from "react";

import { api, type EventRequest, type Quotation, type Reservation } from "../../api";
import { QuoteEditor } from "../quotations/QuoteEditor";
import { ReservationActions } from "../reservations/ReservationActions";
import { Loading, Notice, StatusBadge } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { formText, formatDate, message } from "../../shared/utilities";

function CloseLostAction({
  organizationId,
  requestId,
  onChanged,
}: {
  organizationId: string;
  requestId: string;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <section className="panel">
      <h2>Cerrar oportunidad</h2>
      <p className="muted">Úsalo únicamente si la reserva nunca llegó a confirmarse.</p>
      {error && <Notice>{error}</Notice>}
      <form
        className="danger-zone"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError("");
          void api(`/api/v1/organizations/${organizationId}/event-requests/${requestId}/close/`, {
            method: "POST",
            body: JSON.stringify({ reason: formText(form, "reason") }),
          })
            .then(onChanged)
            .catch((caught: unknown) => {
              setError(message(caught));
            })
            .finally(() => {
              setBusy(false);
            });
        }}
      >
        <label>
          Razón de pérdida
          <input name="reason" required />
        </label>
        <button className="button button--danger" disabled={busy}>
          Marcar como oportunidad perdida
        </button>
      </form>
    </section>
  );
}

function ReservationDocumentStatus({
  organizationId,
  reservation,
}: {
  organizationId: string;
  reservation: Reservation;
}) {
  const [status, setStatus] = useState<{
    status: string;
    label?: string;
    instruments: { versions: { acceptance: object | null; state: string }[] }[];
    materiality?: { status: string; changes: string[] } | null;
  } | null>(null);
  const [error, setError] = useState("");
  const rootId = reservation.root_id ?? reservation.id;
  const load = useCallback(async () => {
    try {
      setStatus(
        await api(
          `/api/v1/organizations/${organizationId}/documents/records/?root_reservation_id=${encodeURIComponent(rootId)}`,
        ),
      );
    } catch (caught) {
      setError(message(caught));
    }
  }, [organizationId, rootId]);
  useInitialLoad(load);
  const issued = status?.instruments.flatMap((instrument) => instrument.versions) ?? [];
  return (
    <section className="panel" aria-labelledby="reservation-documents-title">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Expediente contractual</p>
          <h2 id="reservation-documents-title">Estado documental</h2>
        </div>
        {status ? <StatusBadge value={status.status} /> : null}
      </div>
      {error ? <Notice>{error}</Notice> : null}
      {!status ? (
        <Loading label="Consultando evidencia documental…" />
      ) : status.status === "no_contract_issued" ? (
        <p>sin contrato emitido</p>
      ) : (
        <dl className="details">
          <div>
            <dt>Instrumentos</dt>
            <dd>{status.instruments.length}</dd>
          </div>
          <div>
            <dt>Emisiones</dt>
            <dd>{issued.length}</dd>
          </div>
          <div>
            <dt>Aceptaciones</dt>
            <dd>{issued.filter((version) => version.acceptance !== null).length}</dd>
          </div>
          <div>
            <dt>Materialidad</dt>
            <dd>{status.materiality?.status ?? "sin emisión que comparar"}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}

export function RequestDetail({
  organizationId,
  requestId,
  timeZone,
  capabilities,
  onBack,
}: {
  organizationId: string;
  requestId: string;
  timeZone: string;
  capabilities: Set<string>;
  onBack: () => void;
}) {
  const [request, setRequest] = useState<EventRequest | null>(null);
  const [quotation, setQuotation] = useState<Quotation | null>(null);
  const [reservation, setReservation] = useState<Reservation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const current = await api<EventRequest>(
        `/api/v1/organizations/${organizationId}/event-requests/${requestId}/`,
      );
      setRequest(current);
      const quote = current.quotation_id
        ? await api<Quotation>(
            `/api/v1/organizations/${organizationId}/quotations/${current.quotation_id}/`,
          )
        : null;
      setQuotation(quote);
      const reservationId = [...(quote?.versions ?? [])]
        .reverse()
        .find((version) => version.reservation_id)?.reservation_id;
      setReservation(
        reservationId
          ? await api<Reservation>(
              `/api/v1/organizations/${organizationId}/reservations/${reservationId}/`,
            )
          : null,
      );
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [organizationId, requestId]);
  useInitialLoad(load);
  if (loading) return <Loading />;
  if (error || !request)
    return (
      <>
        <Notice>{error || "La solicitud no está disponible."}</Notice>
        <button className="button button--secondary" onClick={onBack}>
          Volver
        </button>
      </>
    );
  const latestQuote = quotation?.versions.at(-1);
  const quoteEditorKey = latestQuote
    ? `${latestQuote.id}:${String(latestQuote.version)}:${String(latestQuote.revision)}:${latestQuote.status}`
    : "no-quotation";
  return (
    <section>
      <button className="back-link" onClick={onBack}>
        ← Volver a solicitudes
      </button>
      <header className="page-header">
        <div>
          <p className="eyebrow">Detalle comercial</p>
          <h1>{request.event_type}</h1>
          <p className="muted">
            {request.person.full_name ?? "Contacto restringido"} ·{" "}
            {formatDate(request.starts_at, timeZone)}
          </p>
        </div>
        <StatusBadge value={request.status} />
      </header>
      <div className="detail-grid">
        <article className="panel">
          <h2>Solicitud</h2>
          <dl className="details">
            <div>
              <dt>Horario</dt>
              <dd>
                {formatDate(request.starts_at, timeZone)} — {formatDate(request.ends_at, timeZone)}
              </dd>
            </div>
            <div>
              <dt>Invitados</dt>
              <dd>{request.estimated_guests}</dd>
            </div>
            <div>
              <dt>Necesidad</dt>
              <dd>{request.general_need}</dd>
            </div>
            <div>
              <dt>Origen</dt>
              <dd>{request.origin}</dd>
            </div>
          </dl>
        </article>
        <article className="panel">
          <h2>Persona</h2>
          {request.person.full_name ? (
            <dl className="details">
              <div>
                <dt>Nombre</dt>
                <dd>{request.person.full_name}</dd>
              </div>
              <div>
                <dt>Teléfono</dt>
                <dd>{request.person.phone_e164}</dd>
              </div>
              <div>
                <dt>Tipo</dt>
                <dd>{request.person.commercial_type === "client" ? "Cliente" : "Interesado"}</dd>
              </div>
            </dl>
          ) : (
            <p className="muted">No tienes capacidad para consultar datos de contacto.</p>
          )}
        </article>
      </div>
      <QuoteEditor
        key={quoteEditorKey}
        organizationId={organizationId}
        request={request}
        quotation={quotation}
        canManage={capabilities.has("sales:manage")}
        onChanged={load}
      />
      {reservation && (
        <>
          <ReservationActions
            organizationId={organizationId}
            reservation={reservation}
            capabilities={capabilities}
            onChanged={load}
          />
          {capabilities.has("contractual_record:read") ? (
            <ReservationDocumentStatus organizationId={organizationId} reservation={reservation} />
          ) : null}
        </>
      )}
      {(request.status === "new" || request.status === "quoted") &&
        capabilities.has("sales:manage") && (
          <CloseLostAction
            organizationId={organizationId}
            requestId={request.id}
            onChanged={load}
          />
        )}
    </section>
  );
}
