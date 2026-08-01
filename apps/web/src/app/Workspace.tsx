import { useEffect, useState } from "react";

import { api, logout, type Organization, type User } from "../api";
import { BrandLogo } from "../Brand";
import { AgendaView } from "../features/agenda/AgendaView";
import { RequestsView } from "../features/requests/RequestsView";
import { Notice } from "../shared/components";
import { message } from "../shared/utilities";

type Page = "agenda" | "requests";

export function Workspace({
  user,
  organization,
  organizations,
  onSwitch,
  onSignedOut,
}: {
  user: User;
  organization: Organization;
  organizations: Organization[];
  onSwitch: () => void;
  onSignedOut: () => void;
}) {
  const [page, setPage] = useState<Page>("agenda");
  const [selectedRequest, setSelectedRequest] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState(new Set<string>());
  const [timeZone, setTimeZone] = useState("America/Guayaquil");
  const [error, setError] = useState("");
  useEffect(() => {
    void Promise.all([
      api<{ capabilities: string[] }>(
        `/api/v1/organizations/${organization.id}/commercial/capabilities/`,
      ),
      api<{ settings: { timezone: string } }>(`/api/v1/organizations/${organization.id}/settings/`),
    ])
      .then(([capabilityBody, settingsBody]) => {
        setCapabilities(new Set(capabilityBody.capabilities));
        setTimeZone(settingsBody.settings.timezone);
      })
      .catch((caught: unknown) => {
        setError(message(caught));
      });
  }, [organization.id]);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <BrandLogo theme="light" />
          <button className="tenant-switch" onClick={onSwitch} disabled={organizations.length < 2}>
            <span>{organization.name}</span>
            <small>
              {organizations.length > 1 ? "Cambiar organización" : "Organización activa"}
            </small>
          </button>
          <nav aria-label="Navegación principal">
            <button
              aria-current={page === "agenda" ? "page" : undefined}
              onClick={() => {
                setPage("agenda");
                setSelectedRequest(null);
              }}
            >
              <span aria-hidden="true">▦</span>Agenda
            </button>
            <button
              aria-current={page === "requests" ? "page" : undefined}
              onClick={() => {
                setPage("requests");
              }}
            >
              <span aria-hidden="true">◎</span>Solicitudes
            </button>
          </nav>
        </div>
        <div className="profile">
          <span className="profile-avatar">
            {(user.display_name || user.email).slice(0, 1).toUpperCase()}
          </span>
          <span>
            <strong>{user.display_name || user.email}</strong>
            <small>{user.email}</small>
          </span>
          <button aria-label="Cerrar sesión" onClick={() => void logout().then(onSignedOut)}>
            ↗
          </button>
        </div>
      </aside>
      <header className="mobile-header">
        <BrandLogo />
        <button className="button button--ghost" onClick={onSwitch}>
          {organization.name}
        </button>
      </header>
      <nav className="mobile-nav" aria-label="Navegación móvil">
        <button
          aria-current={page === "agenda" ? "page" : undefined}
          onClick={() => {
            setPage("agenda");
            setSelectedRequest(null);
          }}
        >
          Agenda
        </button>
        <button
          aria-current={page === "requests" ? "page" : undefined}
          onClick={() => {
            setPage("requests");
          }}
        >
          Solicitudes
        </button>
      </nav>
      <main className="workspace">
        {error && <Notice>{error}</Notice>}
        {page === "agenda" ? (
          <AgendaView organizationId={organization.id} timeZone={timeZone} />
        ) : (
          <RequestsView
            organizationId={organization.id}
            timeZone={timeZone}
            canManage={capabilities.has("sales:manage")}
            selectedId={selectedRequest}
            onSelect={setSelectedRequest}
            capabilities={capabilities}
          />
        )}
      </main>
    </div>
  );
}
