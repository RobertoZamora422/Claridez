import { useCallback, useState } from "react";

import { api, type EventRequest } from "../../api";
import { Loading, Notice, StatusBadge } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { formatDate, message } from "../../shared/utilities";
import { NewRequestForm } from "./NewRequestForm";
import { RequestDetail } from "./RequestDetail";

interface RequestListProps {
  organizationId: string;
  timeZone: string;
  canManage: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

export function RequestsView(props: RequestListProps & { capabilities: Set<string> }) {
  const { organizationId, timeZone, canManage, selectedId, onSelect, capabilities } = props;
  const [requests, setRequests] = useState<EventRequest[]>([]);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const body = await api<{ event_requests: EventRequest[] }>(
        `/api/v1/organizations/${organizationId}/event-requests/`,
      );
      setRequests(body.event_requests);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);
  useInitialLoad(load);
  if (selectedId)
    return (
      <RequestDetail
        organizationId={organizationId}
        requestId={selectedId}
        timeZone={timeZone}
        capabilities={capabilities}
        onBack={() => {
          onSelect(null);
          void load();
        }}
      />
    );
  if (creating)
    return (
      <NewRequestForm
        organizationId={organizationId}
        timeZone={timeZone}
        onCancel={() => {
          setCreating(false);
        }}
        onCreated={(created) => {
          setCreating(false);
          onSelect(created.id);
        }}
      />
    );
  return (
    <section aria-labelledby="requests-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Seguimiento comercial</p>
          <h1 id="requests-title">Solicitudes</h1>
          <p className="muted">De la primera conversación a una fecha confirmada.</p>
        </div>
        {canManage && (
          <button
            className="button button--primary"
            onClick={() => {
              setCreating(true);
            }}
          >
            Nueva solicitud
          </button>
        )}
      </header>
      {error && <Notice>{error}</Notice>}
      {loading ? (
        <Loading />
      ) : requests.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">
            ＋
          </div>
          <h2>Aún no hay solicitudes</h2>
          <p>Registra el primer interesado para comenzar el flujo comercial.</p>
          {canManage && (
            <button
              className="button button--primary"
              onClick={() => {
                setCreating(true);
              }}
            >
              Crear solicitud
            </button>
          )}
        </div>
      ) : (
        <div className="request-list">
          {requests.map((request) => (
            <button
              key={request.id}
              className="request-card"
              onClick={() => {
                onSelect(request.id);
              }}
            >
              <span>
                <strong>{request.event_type}</strong>
                <small>{request.person.full_name ?? "Contacto restringido"}</small>
              </span>
              <span>
                <small>{formatDate(request.starts_at, timeZone)}</small>
                <StatusBadge value={request.status} />
              </span>
              <span aria-hidden="true">→</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
