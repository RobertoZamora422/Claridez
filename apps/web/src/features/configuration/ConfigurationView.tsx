import { useCallback, useState } from "react";

import { api, type Space, type Venue } from "../../api";
import { Loading, Notice } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { formText, message } from "../../shared/utilities";

interface BusinessConfiguration {
  organization_id: string;
  name: string;
  currency: "USD";
  timezone: string;
}

export function ConfigurationView({
  organizationId,
  canManage,
  onOrganizationRenamed,
}: {
  organizationId: string;
  canManage: boolean;
  onOrganizationRenamed: (name: string) => void;
}) {
  const [configuration, setConfiguration] = useState<BusinessConfiguration | null>(null);
  const [venues, setVenues] = useState<Venue[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [configurationBody, venueBody] = await Promise.all([
        api<BusinessConfiguration>(`/api/v1/organizations/${organizationId}/configuration/`),
        api<{ venues: Venue[] }>(`/api/v1/organizations/${organizationId}/venues/`),
      ]);
      setConfiguration(configurationBody);
      setVenues(venueBody.venues);
      setError("");
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);
  useInitialLoad(load);

  async function mutate(operation: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await operation();
      await load();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading />;
  return (
    <section aria-labelledby="configuration-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Administración funcional</p>
          <h1 id="configuration-title">Configuración del negocio</h1>
          <p className="muted">
            Nombre, moneda, zona horaria, sedes y espacios reservables. Las membresías y la
            seguridad sensible no se administran aquí.
          </p>
        </div>
      </header>
      {error && <Notice>{error}</Notice>}
      {configuration ? (
        <form
          className="panel form-stack"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const name = formText(form, "name");
            void mutate(async () => {
              await api(`/api/v1/organizations/${organizationId}/configuration/`, {
                method: "PATCH",
                body: JSON.stringify({
                  name,
                  currency: "USD",
                  timezone: formText(form, "timezone"),
                }),
              });
              onOrganizationRenamed(name);
            });
          }}
        >
          <h2>Datos funcionales</h2>
          <div className="form-grid">
            <label>
              Nombre del negocio
              <input name="name" defaultValue={configuration.name} disabled={!canManage} required />
            </label>
            <label>
              Moneda
              <input value="USD" disabled />
            </label>
            <label>
              Zona horaria IANA
              <input
                name="timezone"
                defaultValue={configuration.timezone}
                disabled={!canManage}
                required
              />
            </label>
          </div>
          {canManage ? (
            <button className="button button--primary" disabled={busy}>
              Guardar configuración
            </button>
          ) : null}
        </form>
      ) : null}
      <div className="section-heading">
        <div>
          <p className="eyebrow">Capacidad reservable</p>
          <h2>Sedes y espacios</h2>
        </div>
      </div>
      {canManage ? (
        <form
          className="panel compact-form"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void mutate(() =>
              api(`/api/v1/organizations/${organizationId}/venues/`, {
                method: "POST",
                body: JSON.stringify({
                  name: formText(form, "name"),
                  location_reference: formText(form, "location_reference"),
                }),
              }),
            );
            event.currentTarget.reset();
          }}
        >
          <label>
            Nueva sede
            <input name="name" required />
          </label>
          <label>
            Referencia de ubicación
            <input name="location_reference" />
          </label>
          <button className="button button--secondary" disabled={busy}>
            Añadir sede
          </button>
        </form>
      ) : null}
      <div className="management-grid">
        {venues.map((venue) => (
          <VenueCard
            key={venue.id}
            organizationId={organizationId}
            venue={venue}
            canManage={canManage}
            busy={busy}
            mutate={mutate}
          />
        ))}
      </div>
    </section>
  );
}

function VenueCard({
  organizationId,
  venue,
  canManage,
  busy,
  mutate,
}: {
  organizationId: string;
  venue: Venue;
  canManage: boolean;
  busy: boolean;
  mutate: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  return (
    <article className="panel management-card">
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void mutate(() =>
            api(`/api/v1/organizations/${organizationId}/venues/${venue.id}/`, {
              method: "PATCH",
              body: JSON.stringify({
                revision: venue.revision,
                name: formText(form, "name"),
                location_reference: formText(form, "location_reference"),
                is_primary: form.get("is_primary") === "on",
                is_active: form.get("is_active") === "on",
              }),
            }),
          );
        }}
      >
        <div className="management-card__title">
          <h3>{venue.name}</h3>
          {venue.is_primary ? <span className="status status--ready">Principal</span> : null}
        </div>
        <label>
          Nombre
          <input name="name" defaultValue={venue.name} disabled={!canManage} required />
        </label>
        <label>
          Ubicación
          <input
            name="location_reference"
            defaultValue={venue.location_reference ?? ""}
            disabled={!canManage}
          />
        </label>
        {canManage ? (
          <div className="check-row">
            <label>
              <input name="is_primary" type="checkbox" defaultChecked={venue.is_primary} />
              Principal
            </label>
            <label>
              <input name="is_active" type="checkbox" defaultChecked={venue.is_active} /> Activa
            </label>
            <button className="button button--ghost" disabled={busy}>
              Guardar sede
            </button>
          </div>
        ) : null}
      </form>
      <div className="space-list">
        {venue.spaces.map((space) => (
          <SpaceRow
            key={space.id}
            organizationId={organizationId}
            space={space}
            canManage={canManage}
            busy={busy}
            mutate={mutate}
          />
        ))}
      </div>
      {canManage ? (
        <form
          className="compact-form"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void mutate(() =>
              api(`/api/v1/organizations/${organizationId}/venues/${venue.id}/spaces/`, {
                method: "POST",
                body: JSON.stringify({ name: formText(form, "name") }),
              }),
            );
            event.currentTarget.reset();
          }}
        >
          <label>
            Nuevo espacio
            <input name="name" required />
          </label>
          <button className="button button--secondary" disabled={busy || !venue.is_active}>
            Añadir
          </button>
        </form>
      ) : null}
    </article>
  );
}

function SpaceRow({
  organizationId,
  space,
  canManage,
  busy,
  mutate,
}: {
  organizationId: string;
  space: Space;
  canManage: boolean;
  busy: boolean;
  mutate: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  return (
    <form
      className="space-row"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void mutate(() =>
          api(`/api/v1/organizations/${organizationId}/spaces/${space.id}/`, {
            method: "PATCH",
            body: JSON.stringify({
              revision: space.revision,
              name: formText(form, "name"),
              is_primary: form.get("is_primary") === "on",
              is_active: form.get("is_active") === "on",
            }),
          }),
        );
      }}
    >
      <label>
        Espacio
        <input name="name" defaultValue={space.name} disabled={!canManage} required />
      </label>
      {canManage ? (
        <>
          <label>
            <input name="is_primary" type="checkbox" defaultChecked={space.is_primary} /> Principal
          </label>
          <label>
            <input name="is_active" type="checkbox" defaultChecked={space.is_active} /> Activo
          </label>
          <button className="button button--ghost" disabled={busy}>
            Guardar
          </button>
        </>
      ) : (
        <span className="muted">{space.is_active ? "Activo" : "Inactivo"}</span>
      )}
    </form>
  );
}
