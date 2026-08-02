import { useCallback, useState, type SyntheticEvent } from "react";

import { api, type CatalogItem, type EventTypeDefinition } from "../../api";
import { Loading, Notice } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { formText, localToInstant, message } from "../../shared/utilities";

interface ComponentDraft {
  item_id: string;
  quantity: string;
}

export function CatalogView({
  organizationId,
  timeZone,
  canManage,
  canReadPrices,
  canManagePrices,
}: {
  organizationId: string;
  timeZone: string;
  canManage: boolean;
  canReadPrices: boolean;
  canManagePrices: boolean;
}) {
  const [eventTypes, setEventTypes] = useState<EventTypeDefinition[]>([]);
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [newKind, setNewKind] = useState<CatalogItem["kind"]>("service");
  const [newComponents, setNewComponents] = useState<ComponentDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [eventTypeBody, itemBody] = await Promise.all([
        api<{ event_types: EventTypeDefinition[] }>(
          `/api/v1/organizations/${organizationId}/event-types/`,
        ),
        api<{ items: CatalogItem[] }>(`/api/v1/organizations/${organizationId}/catalog/items/`),
      ]);
      setEventTypes(eventTypeBody.event_types);
      setItems(itemBody.items);
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
  const componentOptions = items.filter((item) => item.kind !== "package" && item.is_active);
  return (
    <section aria-labelledby="catalog-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Fuente comercial vigente</p>
          <h1 id="catalog-title">Catálogo, paquetes y precios</h1>
          <p className="muted">
            Las cotizaciones congelan la revisión, composición y precio aplicables; los cambios
            futuros no alteran su historia.
          </p>
        </div>
      </header>
      {error && <Notice>{error}</Notice>}
      <div className="section-heading">
        <div>
          <h2>Tipos de evento</h2>
          <p className="muted">Opciones disponibles al registrar una solicitud.</p>
        </div>
      </div>
      {canManage ? (
        <form
          className="panel compact-form"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void mutate(() =>
              api(`/api/v1/organizations/${organizationId}/event-types/`, {
                method: "POST",
                body: JSON.stringify({ name: formText(form, "name") }),
              }),
            );
            event.currentTarget.reset();
          }}
        >
          <label>
            Nuevo tipo de evento
            <input name="name" required />
          </label>
          <button className="button button--secondary" disabled={busy}>
            Añadir tipo
          </button>
        </form>
      ) : null}
      <div className="chip-grid">
        {eventTypes.map((eventType) => (
          <form
            key={eventType.id}
            className="catalog-chip"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              void mutate(() =>
                api(`/api/v1/organizations/${organizationId}/event-types/${eventType.id}/`, {
                  method: "PATCH",
                  body: JSON.stringify({
                    revision: eventType.revision,
                    name: formText(form, "name"),
                    is_active: form.get("is_active") === "on",
                  }),
                }),
              );
            }}
          >
            <input name="name" defaultValue={eventType.name} disabled={!canManage} required />
            {canManage ? (
              <>
                <label>
                  <input name="is_active" type="checkbox" defaultChecked={eventType.is_active} />
                  Activo
                </label>
                <button className="button button--ghost" disabled={busy}>
                  Guardar
                </button>
              </>
            ) : (
              <span className="status">{eventType.is_active ? "Activo" : "Inactivo"}</span>
            )}
          </form>
        ))}
      </div>
      <div className="section-heading">
        <div>
          <h2>Servicios, productos y paquetes</h2>
          <p className="muted">Identidades estables con revisiones append-only.</p>
        </div>
      </div>
      {canManage ? (
        <form
          className="panel form-stack"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void mutate(() =>
              api(`/api/v1/organizations/${organizationId}/catalog/items/`, {
                method: "POST",
                body: JSON.stringify({
                  kind: newKind,
                  name: formText(form, "name"),
                  description: formText(form, "description"),
                  unit_label: formText(form, "unit_label"),
                  components: newKind === "package" ? newComponents : [],
                }),
              }),
            );
            event.currentTarget.reset();
            setNewComponents([]);
          }}
        >
          <h3>Nuevo ítem</h3>
          <div className="form-grid">
            <label>
              Tipo
              <select
                value={newKind}
                onChange={(event) => {
                  setNewKind(event.target.value as CatalogItem["kind"]);
                  setNewComponents([]);
                }}
              >
                <option value="service">Servicio</option>
                <option value="product">Producto</option>
                <option value="package">Paquete</option>
              </select>
            </label>
            <label>
              Nombre
              <input name="name" required />
            </label>
            <label>
              Unidad
              <input name="unit_label" placeholder="evento, persona, unidad" required />
            </label>
            <label className="span-two">
              Descripción
              <textarea name="description" rows={2} />
            </label>
          </div>
          {newKind === "package" ? (
            <ComponentEditor
              value={newComponents}
              options={componentOptions}
              onChange={setNewComponents}
            />
          ) : null}
          <button
            className="button button--primary"
            disabled={busy || (newKind === "package" && newComponents.length === 0)}
          >
            Crear ítem
          </button>
        </form>
      ) : null}
      <div className="management-grid catalog-grid">
        {items.map((item) => (
          <CatalogCard
            key={`${item.id}-${String(item.revision)}`}
            organizationId={organizationId}
            timeZone={timeZone}
            item={item}
            options={componentOptions.filter((candidate) => candidate.id !== item.id)}
            canManage={canManage}
            canReadPrices={canReadPrices}
            canManagePrices={canManagePrices}
            busy={busy}
            mutate={mutate}
          />
        ))}
      </div>
    </section>
  );
}

function ComponentEditor({
  value,
  options,
  onChange,
}: {
  value: ComponentDraft[];
  options: CatalogItem[];
  onChange: (value: ComponentDraft[]) => void;
}) {
  return (
    <div className="component-editor">
      <div className="line-header">
        <h3>Composición explícita</h3>
        <button
          type="button"
          className="button button--ghost"
          disabled={options.length === 0}
          onClick={() => {
            const available = options.find(
              (option) => !value.some((component) => component.item_id === option.id),
            );
            if (available) onChange([...value, { item_id: available.id, quantity: "1.000" }]);
          }}
        >
          Añadir componente
        </button>
      </div>
      {value.map((component, index) => (
        <div className="component-row" key={`${component.item_id}-${String(index)}`}>
          <select
            aria-label={`Componente ${String(index + 1)}`}
            value={component.item_id}
            onChange={(event) => {
              onChange(
                value.map((candidate, position) =>
                  position === index ? { ...candidate, item_id: event.target.value } : candidate,
                ),
              );
            }}
          >
            {options.map((option) => (
              <option
                key={option.id}
                value={option.id}
                disabled={value.some(
                  (candidate, position) => position !== index && candidate.item_id === option.id,
                )}
              >
                {option.name}
              </option>
            ))}
          </select>
          <input
            aria-label={`Cantidad del componente ${String(index + 1)}`}
            type="number"
            min="0.001"
            step="0.001"
            value={component.quantity}
            onChange={(event) => {
              onChange(
                value.map((candidate, position) =>
                  position === index ? { ...candidate, quantity: event.target.value } : candidate,
                ),
              );
            }}
          />
          <button
            type="button"
            className="icon-button"
            aria-label={`Quitar componente ${String(index + 1)}`}
            onClick={() => {
              onChange(value.filter((_, position) => position !== index));
            }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function CatalogCard({
  organizationId,
  timeZone,
  item,
  options,
  canManage,
  canReadPrices,
  canManagePrices,
  busy,
  mutate,
}: {
  organizationId: string;
  timeZone: string;
  item: CatalogItem;
  options: CatalogItem[];
  canManage: boolean;
  canReadPrices: boolean;
  canManagePrices: boolean;
  busy: boolean;
  mutate: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  const [components, setComponents] = useState<ComponentDraft[]>(
    item.components.map((component) => ({
      item_id: component.item_id,
      quantity: component.quantity,
    })),
  );
  return (
    <article className="panel management-card">
      <div className="management-card__title">
        <div>
          <span className="status">{item.kind}</span>
          <h3>{item.name}</h3>
        </div>
        {canReadPrices ? (
          <strong>
            {item.current_price ? `$${item.current_price.amount}` : "Sin precio vigente"}
          </strong>
        ) : null}
      </div>
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void mutate(() =>
            api(`/api/v1/organizations/${organizationId}/catalog/items/${item.id}/`, {
              method: "PATCH",
              body: JSON.stringify({
                revision: item.revision,
                name: formText(form, "name"),
                description: formText(form, "description"),
                unit_label: formText(form, "unit_label"),
                is_active: form.get("is_active") === "on",
                components: item.kind === "package" ? components : [],
              }),
            }),
          );
        }}
      >
        <label>
          Nombre
          <input name="name" defaultValue={item.name} disabled={!canManage} required />
        </label>
        <label>
          Unidad
          <input name="unit_label" defaultValue={item.unit_label} disabled={!canManage} required />
        </label>
        <label>
          Descripción
          <textarea
            name="description"
            defaultValue={item.description ?? ""}
            disabled={!canManage}
            rows={2}
          />
        </label>
        {item.kind === "package" && canManage ? (
          <ComponentEditor value={components} options={options} onChange={setComponents} />
        ) : item.components.length > 0 ? (
          <p className="muted">
            Incluye: {item.components.map((component) => component.name).join(", ")}
          </p>
        ) : null}
        {canManage ? (
          <div className="check-row">
            <label>
              <input name="is_active" type="checkbox" defaultChecked={item.is_active} /> Activo
            </label>
            <button className="button button--ghost" disabled={busy}>
              Guardar revisión
            </button>
          </div>
        ) : null}
      </form>
      {canManagePrices ? (
        <PriceForm
          busy={busy}
          timeZone={timeZone}
          onSubmit={(amount, validFrom, validUntil) =>
            mutate(() =>
              api(`/api/v1/organizations/${organizationId}/catalog/items/${item.id}/prices/`, {
                method: "POST",
                body: JSON.stringify({
                  amount,
                  valid_from: localToInstant(validFrom, timeZone),
                  valid_until: validUntil ? localToInstant(validUntil, timeZone) : null,
                }),
              }),
            )
          }
        />
      ) : null}
      {canReadPrices && item.prices && item.prices.length > 0 ? (
        <details>
          <summary>Historial de precios ({item.prices.length})</summary>
          <ul className="price-history">
            {item.prices.map((price) => (
              <li key={price.id}>
                v{price.revision} · ${price.amount} ·{" "}
                {new Date(price.valid_from).toLocaleDateString()}
                {price.valid_until
                  ? ` a ${new Date(price.valid_until).toLocaleDateString()}`
                  : " en adelante"}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </article>
  );
}

function PriceForm({
  busy,
  timeZone,
  onSubmit,
}: {
  busy: boolean;
  timeZone: string;
  onSubmit: (amount: string, validFrom: string, validUntil: string) => Promise<void>;
}) {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return (
    <form
      className="price-form"
      onSubmit={(event: SyntheticEvent<HTMLFormElement>) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void onSubmit(
          formText(form, "amount"),
          formText(form, "valid_from"),
          formText(form, "valid_until"),
        );
      }}
    >
      <h3>Nuevo precio · {timeZone}</h3>
      <label>
        USD
        <input name="amount" type="number" min="0" step="0.01" required />
      </label>
      <label>
        Vigente desde
        <input
          name="valid_from"
          type="datetime-local"
          defaultValue={now.toISOString().slice(0, 16)}
          required
        />
      </label>
      <label>
        Hasta (opcional)
        <input name="valid_until" type="datetime-local" />
      </label>
      <button className="button button--secondary" disabled={busy}>
        Registrar precio
      </button>
    </form>
  );
}
