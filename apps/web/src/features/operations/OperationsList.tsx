import type { OperationEvent } from "../../api";
import { Loading, Notice } from "../../shared/components";
import { STATUS_LABELS } from "./constants";
import { localDate } from "./operationHelpers";

export function OperationsList({
  events,
  statusFilter,
  attentionFilter,
  loading,
  error,
  onStatusFilter,
  onAttentionFilter,
  onSelect,
}: {
  events: OperationEvent[];
  statusFilter: string;
  attentionFilter: string;
  loading: boolean;
  error: string;
  onStatusFilter: (value: string) => void;
  onAttentionFilter: (value: string) => void;
  onSelect: (reservationId: string) => void;
}) {
  return (
    <section aria-labelledby="operations-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Centro operativo</p>
          <h1 id="operations-title">Próximos eventos</h1>
          <p>Lo pendiente, bloqueado y listo para ejecutar.</p>
        </div>
      </header>
      <div className="operation-filters" aria-label="Filtros operativos">
        <label>
          Estado
          <select
            value={statusFilter}
            onChange={(event) => {
              onStatusFilter(event.target.value);
            }}
          >
            <option value="">Activos</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Atención
          <select
            value={attentionFilter}
            onChange={(event) => {
              onAttentionFilter(event.target.value);
            }}
          >
            <option value="">Toda</option>
            <option value="overdue">Atrasada</option>
            <option value="upcoming">Próxima</option>
            <option value="blocked">Con bloqueos</option>
            <option value="ready">Lista</option>
            <option value="unassigned">Sin responsable</option>
          </select>
        </label>
      </div>
      {error ? <Notice>{error}</Notice> : null}
      {loading ? (
        <Loading label="Cargando eventos operativos…" />
      ) : events.length === 0 ? (
        <div className="empty-state">
          <h2>No hay eventos confirmados en este periodo</h2>
          <p>Prueba cambiando los filtros de la bandeja.</p>
        </div>
      ) : (
        <ul className="operation-event-list">
          {events.map((event) => (
            <li key={event.reservation_id}>
              <button
                onClick={() => {
                  onSelect(event.reservation_id);
                }}
              >
                <span>
                  <strong>{event.event.event_type}</strong>
                  <small>
                    {event.event.venue.name} · {event.event.space.name} ·{" "}
                    {event.contact.display_name} ·{" "}
                    {localDate(event.event.starts_at, event.event.timezone)}
                  </small>
                </span>
                <span>
                  <span className={`status status--${event.preparation.status}`}>
                    {STATUS_LABELS[event.preparation.status]}
                  </span>
                  <small>
                    {event.preparation.attention.pending_count} pendientes ·{" "}
                    {event.preparation.attention.blocked_count} bloqueos
                  </small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
