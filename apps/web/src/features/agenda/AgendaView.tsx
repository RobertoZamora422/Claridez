import { useCallback, useState } from "react";

import { api, type Availability } from "../../api";
import { Loading, Notice, StatusBadge } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { formatDate, localToInstant, message, toInputDate } from "../../shared/utilities";

export function AgendaView({
  organizationId,
  timeZone,
}: {
  organizationId: string;
  timeZone: string;
}) {
  const [startDate, setStartDate] = useState(toInputDate(new Date()));
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const from = localToInstant(`${startDate}T00:00`, timeZone);
      const toDate = new Date(from);
      toDate.setUTCDate(toDate.getUTCDate() + 7);
      const params = new URLSearchParams({ from, to: toDate.toISOString() });
      setAvailability(
        await api<Availability>(`/api/v1/organizations/${organizationId}/availability/?${params}`),
      );
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [organizationId, startDate, timeZone]);

  useInitialLoad(load);

  return (
    <section aria-labelledby="agenda-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Próximos 7 días</p>
          <h1 id="agenda-title">Agenda y disponibilidad</h1>
          <p className="muted">Horarios bloqueados en {timeZone}.</p>
        </div>
        <label className="date-control">
          Semana desde
          <input
            type="date"
            value={startDate}
            onChange={(event) => {
              setStartDate(event.target.value);
            }}
          />
        </label>
      </header>
      {error && <Notice>{error}</Notice>}
      {loading ? (
        <Loading />
      ) : availability?.blocks.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">
            ✓
          </div>
          <h2>Semana disponible</h2>
          <p>No hay reservas provisionales o confirmadas en este periodo.</p>
        </div>
      ) : (
        <div className="agenda-grid">
          {availability?.blocks.map((block) => (
            <article className="event-card" key={block.id}>
              <div>
                <p className="event-date">
                  {formatDate(block.starts_at, timeZone, {
                    weekday: "long",
                    day: "numeric",
                    month: "long",
                  })}
                </p>
                <h2>{block.event_type ?? "Evento reservado"}</h2>
              </div>
              <StatusBadge value={block.status} />
              <dl>
                <div>
                  <dt>Inicio</dt>
                  <dd>{formatDate(block.starts_at, timeZone)}</dd>
                </div>
                <div>
                  <dt>Fin</dt>
                  <dd>{formatDate(block.ends_at, timeZone)}</dd>
                </div>
                {block.status === "provisional" && (
                  <div>
                    <dt>Vence</dt>
                    <dd>{formatDate(block.hold_expires_at, timeZone)}</dd>
                  </div>
                )}
              </dl>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
