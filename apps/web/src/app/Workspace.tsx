import { useEffect, useState } from "react";

import { api, logout, type Organization, type User } from "../api";
import { BrandLogo } from "../Brand";
import { AgendaView } from "../features/agenda/AgendaView";
import { CatalogView } from "../features/catalog/CatalogView";
import { ConfigurationView } from "../features/configuration/ConfigurationView";
import { CRMView } from "../features/crm/CRMView";
import { DocumentsView } from "../features/documents/DocumentsView";
import { FinanceView } from "../features/finance/FinanceView";
import { OperationsView } from "../features/operations/OperationsView";
import { ReceivablesView } from "../features/receivables/ReceivablesView";
import { ResourcesView } from "../features/resources/ResourcesView";
import { RequestsView } from "../features/requests/RequestsView";
import { Notice } from "../shared/components";
import { message } from "../shared/utilities";

type Page =
  | "agenda"
  | "crm"
  | "requests"
  | "operations"
  | "receivables"
  | "finance"
  | "resources"
  | "catalog"
  | "documents"
  | "configuration";

export function Workspace({
  user,
  organization,
  organizations,
  onSwitch,
  onOrganizationUpdated,
  onSignedOut,
}: {
  user: User;
  organization: Organization;
  organizations: Organization[];
  onSwitch: () => void;
  onOrganizationUpdated: (name: string) => void;
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
      api<{ capabilities: string[] }>(
        `/api/v1/organizations/${organization.id}/operations/capabilities/`,
      ),
      api<{ capabilities: string[] }>(
        `/api/v1/organizations/${organization.id}/configuration/capabilities/`,
      ),
      api<{ capabilities: string[] }>(`/api/v1/organizations/${organization.id}/crm/capabilities/`),
      api<{ capabilities: string[] }>(
        `/api/v1/organizations/${organization.id}/scheduling/capabilities/`,
      ),
      api<{ capabilities: string[] }>(
        `/api/v1/organizations/${organization.id}/documents/capabilities/`,
      ),
      api<{ capabilities: string[] }>(
        `/api/v1/organizations/${organization.id}/receivables/capabilities/`,
      ),
      api<{ capabilities: string[] }>(
        `/api/v1/organizations/${organization.id}/finance/capabilities/`,
      ),
      api<{ capabilities: string[] }>(
        `/api/v1/organizations/${organization.id}/resources/capabilities/`,
      ),
    ])
      .then(
        ([
          capabilityBody,
          settingsBody,
          operationsBody,
          configurationBody,
          crmBody,
          scheduleBody,
          documentsBody,
          receivablesBody,
          financeBody,
          resourcesBody,
        ]) => {
          setCapabilities(
            new Set([
              ...capabilityBody.capabilities,
              ...operationsBody.capabilities,
              ...configurationBody.capabilities,
              ...crmBody.capabilities,
              ...scheduleBody.capabilities,
              ...documentsBody.capabilities,
              ...receivablesBody.capabilities,
              ...financeBody.capabilities,
              ...resourcesBody.capabilities,
            ]),
          );
          setTimeZone(settingsBody.settings.timezone);
        },
      )
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
            {capabilities.has("sales:read") && capabilities.has("person:read") ? (
              <button
                aria-current={page === "crm" ? "page" : undefined}
                onClick={() => {
                  setPage("crm");
                  setSelectedRequest(null);
                }}
              >
                <span aria-hidden="true">◉</span>CRM
              </button>
            ) : null}
            {capabilities.has("operation:read") ? (
              <button
                aria-current={page === "operations" ? "page" : undefined}
                onClick={() => {
                  setPage("operations");
                  setSelectedRequest(null);
                }}
              >
                <span aria-hidden="true">✓</span>Operación
              </button>
            ) : null}
            {capabilities.has("receivables:read") ? (
              <button
                aria-current={page === "receivables" ? "page" : undefined}
                onClick={() => {
                  setPage("receivables");
                  setSelectedRequest(null);
                }}
              >
                <span aria-hidden="true">$</span>Cartera
              </button>
            ) : null}
            {capabilities.has("finance:read") || capabilities.has("finance:submit_evidence") ? (
              <button
                aria-current={page === "finance" ? "page" : undefined}
                onClick={() => {
                  setPage("finance");
                  setSelectedRequest(null);
                }}
              >
                <span aria-hidden="true">∑</span>Finanzas
              </button>
            ) : null}
            {capabilities.has("resource:read_availability") ? (
              <button
                aria-current={page === "resources" ? "page" : undefined}
                onClick={() => {
                  setPage("resources");
                  setSelectedRequest(null);
                }}
              >
                <span aria-hidden="true">▦</span>Recursos
              </button>
            ) : null}
            {capabilities.has("catalog:read") ? (
              <button
                aria-current={page === "catalog" ? "page" : undefined}
                onClick={() => {
                  setPage("catalog");
                  setSelectedRequest(null);
                }}
              >
                <span aria-hidden="true">◇</span>Catálogo
              </button>
            ) : null}
            {capabilities.has("contractual_record:read") ? (
              <button
                aria-current={page === "documents" ? "page" : undefined}
                onClick={() => {
                  setPage("documents");
                  setSelectedRequest(null);
                }}
              >
                <span aria-hidden="true">▤</span>Documentos
              </button>
            ) : null}
            {capabilities.has("business_configuration:manage") ? (
              <button
                aria-current={page === "configuration" ? "page" : undefined}
                onClick={() => {
                  setPage("configuration");
                  setSelectedRequest(null);
                }}
              >
                <span aria-hidden="true">⚙</span>Configuración
              </button>
            ) : null}
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
        {capabilities.has("sales:read") && capabilities.has("person:read") ? (
          <button
            aria-current={page === "crm" ? "page" : undefined}
            onClick={() => {
              setPage("crm");
              setSelectedRequest(null);
            }}
          >
            CRM
          </button>
        ) : null}
        {capabilities.has("operation:read") ? (
          <button
            aria-current={page === "operations" ? "page" : undefined}
            onClick={() => {
              setPage("operations");
              setSelectedRequest(null);
            }}
          >
            Operación
          </button>
        ) : null}
        {capabilities.has("receivables:read") ? (
          <button
            aria-current={page === "receivables" ? "page" : undefined}
            onClick={() => {
              setPage("receivables");
              setSelectedRequest(null);
            }}
          >
            Cartera
          </button>
        ) : null}
        {capabilities.has("finance:read") || capabilities.has("finance:submit_evidence") ? (
          <button
            aria-current={page === "finance" ? "page" : undefined}
            onClick={() => {
              setPage("finance");
              setSelectedRequest(null);
            }}
          >
            Finanzas
          </button>
        ) : null}
        {capabilities.has("resource:read_availability") ? (
          <button
            aria-current={page === "resources" ? "page" : undefined}
            onClick={() => {
              setPage("resources");
              setSelectedRequest(null);
            }}
          >
            Recursos
          </button>
        ) : null}
        {capabilities.has("catalog:read") ? (
          <button
            aria-current={page === "catalog" ? "page" : undefined}
            onClick={() => {
              setPage("catalog");
              setSelectedRequest(null);
            }}
          >
            Catálogo
          </button>
        ) : null}
        {capabilities.has("contractual_record:read") ? (
          <button
            aria-current={page === "documents" ? "page" : undefined}
            onClick={() => {
              setPage("documents");
              setSelectedRequest(null);
            }}
          >
            Documentos
          </button>
        ) : null}
        {capabilities.has("business_configuration:manage") ? (
          <button
            aria-current={page === "configuration" ? "page" : undefined}
            onClick={() => {
              setPage("configuration");
              setSelectedRequest(null);
            }}
          >
            Configuración
          </button>
        ) : null}
      </nav>
      <main className="workspace">
        {error && <Notice>{error}</Notice>}
        {page === "agenda" ? (
          <AgendaView
            organizationId={organization.id}
            timeZone={timeZone}
            capabilities={capabilities}
          />
        ) : page === "requests" ? (
          <RequestsView
            organizationId={organization.id}
            timeZone={timeZone}
            canManage={capabilities.has("sales:manage")}
            selectedId={selectedRequest}
            onSelect={setSelectedRequest}
            capabilities={capabilities}
          />
        ) : page === "crm" ? (
          <CRMView
            organizationId={organization.id}
            timeZone={timeZone}
            capabilities={capabilities}
          />
        ) : page === "operations" ? (
          <OperationsView
            organizationId={organization.id}
            canManage={capabilities.has("operation:manage")}
            canExecute={capabilities.has("operation:execute")}
          />
        ) : page === "receivables" ? (
          <ReceivablesView organizationId={organization.id} capabilities={capabilities} />
        ) : page === "finance" ? (
          <FinanceView organizationId={organization.id} capabilities={capabilities} />
        ) : page === "resources" ? (
          <ResourcesView organizationId={organization.id} capabilities={capabilities} />
        ) : page === "catalog" ? (
          <CatalogView
            organizationId={organization.id}
            timeZone={timeZone}
            canManage={capabilities.has("catalog:manage")}
            canReadPrices={capabilities.has("catalog_price:read")}
            canManagePrices={capabilities.has("catalog_price:manage")}
          />
        ) : page === "documents" ? (
          <DocumentsView organizationId={organization.id} capabilities={capabilities} />
        ) : (
          <ConfigurationView
            organizationId={organization.id}
            canManage={capabilities.has("business_configuration:manage")}
            onOrganizationRenamed={onOrganizationUpdated}
          />
        )}
      </main>
    </div>
  );
}
