import { useCallback, useEffect, useState } from "react";

import { ApiError, api, type Organization, type User } from "./api";
import { Workspace } from "./app/Workspace";
import { LoginScreen } from "./features/authentication/LoginScreen";
import { ExternalDocumentView } from "./features/documents/ExternalDocumentView";
import { OrganizationPicker } from "./features/organizations/OrganizationPicker";
import { Loading, Notice } from "./shared/components";
import { message } from "./shared/utilities";
import "./styles.css";

export function App() {
  const isExternalExchange = window.location.pathname === "/documents/access";
  const externalToken = isExternalExchange
    ? decodeURIComponent(window.location.hash.replace(/^#/, "")) || null
    : null;
  const isExternalDocument =
    isExternalExchange || window.location.pathname === "/documents/external";
  const [user, setUser] = useState<User | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [loading, setLoading] = useState(!isExternalDocument);
  const [error, setError] = useState("");
  const loadOrganizations = useCallback(async () => {
    const [list, context] = await Promise.all([
      api<{ organizations: Organization[] }>("/api/v1/organizations/"),
      api<{ organization: Organization | null }>("/api/v1/organizations/context/"),
    ]);
    setOrganizations(list.organizations);
    setOrganization(context.organization);
  }, []);
  useEffect(() => {
    if (isExternalDocument) {
      return;
    }
    void api<{ user: User }>("/api/v1/auth/me/")
      .then(async (body) => {
        setUser(body.user);
        await loadOrganizations();
      })
      .catch((caught: unknown) => {
        if (!(caught instanceof ApiError) || caught.status !== 401) setError(message(caught));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [isExternalDocument, loadOrganizations]);
  async function selectOrganization(selected: Organization) {
    const body = await api<{ organization: Organization }>("/api/v1/organizations/context/", {
      method: "POST",
      body: JSON.stringify({ organization_id: selected.id }),
    });
    setOrganization(body.organization);
  }
  if (isExternalDocument) return <ExternalDocumentView token={externalToken} />;
  if (loading)
    return (
      <main className="center-layout">
        <Loading label="Preparando Claridez…" />
      </main>
    );
  if (!user)
    return (
      <LoginScreen
        onAuthenticated={(authenticated) => {
          setUser(authenticated);
          setLoading(true);
          void loadOrganizations()
            .catch((caught: unknown) => {
              setError(message(caught));
            })
            .finally(() => {
              setLoading(false);
            });
        }}
      />
    );
  if (error)
    return (
      <main className="center-layout">
        <Notice>{error}</Notice>
      </main>
    );
  if (!organization)
    return <OrganizationPicker organizations={organizations} onSelect={selectOrganization} />;
  return (
    <Workspace
      user={user}
      organization={organization}
      organizations={organizations}
      onSwitch={() => {
        setOrganization(null);
      }}
      onOrganizationUpdated={(name) => {
        setOrganization((current) => (current ? { ...current, name } : current));
        setOrganizations((current) =>
          current.map((item) => (item.id === organization.id ? { ...item, name } : item)),
        );
      }}
      onSignedOut={() => {
        setUser(null);
        setOrganization(null);
        setOrganizations([]);
      }}
    />
  );
}
