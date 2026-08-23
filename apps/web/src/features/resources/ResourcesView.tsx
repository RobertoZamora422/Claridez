import { useCallback, useState, type ReactNode, type SyntheticEvent } from "react";

import { api } from "../../api";
import { Loading, Notice, StatusBadge } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { message, toInputDate } from "../../shared/utilities";

interface Row {
  id?: string;
  [key: string]: unknown;
}

interface Availability extends Row {
  resource_id: string;
  name: string;
  nature: string;
  unit: string;
  declared_capacity: string | null;
  available: string | null;
  shortage: boolean;
}

interface ResourcesOverview {
  organization_id: string;
  capabilities: string[];
  availability: Availability[];
  resources: Row[];
  units: Row[];
  conversions: Row[];
  locations: Row[];
  balances: Row[];
  assets: Row[];
  movements: Row[];
  requirements: Row[];
  assignments: Row[];
  unavailability: Row[];
  maintenance: Row[];
  suppliers: Row[];
  purchases: Row[];
  receipts: Row[];
}

type Section = "availability" | "inventory" | "supply" | "events" | "maintenance";

const today = toInputDate(new Date());

function text(row: Row, key: string) {
  const value = row[key];
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return value.toString();
  return "—";
}

function nullable(value: unknown) {
  return value === "" || value === null || value === undefined ? null : value;
}

function CommandForm({
  title,
  children,
  submitLabel,
  onSubmit,
  busy,
}: {
  title: string;
  children: ReactNode;
  submitLabel: string;
  onSubmit: (event: SyntheticEvent<HTMLFormElement>) => void;
  busy: boolean;
}) {
  return (
    <form className="resource-command" onSubmit={onSubmit}>
      <h3>{title}</h3>
      <div className="form-grid">{children}</div>
      <button className="button button--primary" disabled={busy}>
        {busy ? "Guardando…" : submitLabel}
      </button>
    </form>
  );
}

function Cards({ rows, render }: { rows: Row[]; render: (row: Row) => ReactNode }) {
  if (rows.length === 0) return <p className="muted">Aún no hay registros en esta sección.</p>;
  return <div className="resource-card-grid">{rows.map(render)}</div>;
}

function payload(event: SyntheticEvent<HTMLFormElement>) {
  return Object.fromEntries(new FormData(event.currentTarget).entries());
}

export function ResourcesView({
  organizationId,
  capabilities,
}: {
  organizationId: string;
  capabilities: Set<string>;
}) {
  const [overview, setOverview] = useState<ResourcesOverview | null>(null);
  const [section, setSection] = useState<Section>("availability");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setOverview(
        await api<ResourcesOverview>(`/api/v1/organizations/${organizationId}/resources/overview/`),
      );
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);
  useInitialLoad(load);

  const command = useCallback(
    async (path: string, body: object, success: string) => {
      setBusy(true);
      setError("");
      setNotice("");
      try {
        await api(`/api/v1/organizations/${organizationId}/resources/${path}`, {
          method: "POST",
          headers: { "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify(body),
        });
        setNotice(success);
        await load();
      } catch (caught: unknown) {
        setError(message(caught));
      } finally {
        setBusy(false);
      }
    },
    [load, organizationId],
  );

  if (loading && overview === null) return <Loading label="Cargando proveedores y recursos…" />;

  const can = (value: string) => capabilities.has(value);
  const submit =
    (path: string, success: string, transform?: (body: Row) => object) =>
    (event: SyntheticEvent<HTMLFormElement>) => {
      event.preventDefault();
      const body = payload(event) as Row;
      void command(path, transform ? transform(body) : body, success);
    };
  const submitAt =
    (path: (body: Row) => string, success: string, transform?: (body: Row) => object) =>
    (event: SyntheticEvent<HTMLFormElement>) => {
      event.preventDefault();
      const body = payload(event) as Row;
      void command(path(body), transform ? transform(body) : body, success);
    };

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Recursos · P12</p>
          <h1>Proveedores, recursos e inventario</h1>
          <p>Control operativo de abastecimiento y capacidad, sin valoración contable.</p>
        </div>
        <button
          className="button button--ghost"
          onClick={() => {
            void load();
          }}
          disabled={loading}
        >
          Actualizar
        </button>
      </header>
      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="info">{notice}</Notice> : null}
      <nav className="resource-tabs" aria-label="Secciones de recursos">
        {(
          [
            ["availability", "Disponibilidad"],
            ["inventory", "Inventario"],
            ["supply", "Proveedores y compras"],
            ["events", "Eventos y asignación"],
            ["maintenance", "Mantenimiento"],
          ] as [Section, string][]
        ).map(([value, label]) => (
          <button
            key={value}
            aria-current={section === value ? "page" : undefined}
            onClick={() => {
              setSection(value);
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      {section === "availability" ? (
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>Disponibilidad operativa</h2>
              <p>Capacidad vigente por naturaleza de recurso.</p>
            </div>
          </div>
          <Cards
            rows={overview?.availability ?? []}
            render={(raw) => {
              const row = raw as Availability;
              return (
                <article
                  className={`resource-card ${row.shortage ? "resource-card--shortage" : ""}`}
                  key={row.resource_id}
                >
                  <div className="resource-card__heading">
                    <strong>{row.name}</strong>
                    {row.shortage ? <StatusBadge value="shortage" /> : null}
                  </div>
                  <small>{row.nature}</small>
                  <p className="resource-quantity">
                    {row.available ?? "Sin capacidad declarada"} {row.unit}
                  </p>
                  <span>Capacidad configurada: {row.declared_capacity ?? "no declarada"}</span>
                </article>
              );
            }}
          />
        </section>
      ) : null}

      {section === "inventory" ? (
        <>
          <section className="panel">
            <h2>Recursos, ubicaciones y existencias</h2>
            <Cards
              rows={overview?.resources ?? []}
              render={(row) => (
                <article className="resource-card" key={row.id}>
                  <strong>{text(row, "name")}</strong>
                  <span>{text(row, "nature")}</span>
                  <StatusBadge value={text(row, "is_active") === "true" ? "active" : "inactive"} />
                </article>
              )}
            />
            <div className="resource-ledger">
              <div>
                <h3>Saldos por ubicación</h3>
                <Cards
                  rows={overview?.balances ?? []}
                  render={(row) => (
                    <article className="resource-card" key={row.id}>
                      <code>{text(row, "resource_id")}</code>
                      <span>Ubicación {text(row, "location_id")}</span>
                      <strong>{text(row, "quantity")}</strong>
                    </article>
                  )}
                />
              </div>
              <div>
                <h3>Movimientos recientes</h3>
                <Cards
                  rows={overview?.movements ?? []}
                  render={(row) => (
                    <article className="resource-card" key={row.id}>
                      <div className="resource-card__heading">
                        <strong>{text(row, "kind")}</strong>
                        <span>{text(row, "quantity")}</span>
                      </div>
                      <span>{text(row, "reason")}</span>
                    </article>
                  )}
                />
              </div>
            </div>
          </section>
          {can("resource:manage") ? (
            <section className="panel resource-command-grid">
              <CommandForm
                title="Nueva unidad"
                submitLabel="Crear unidad"
                busy={busy}
                onSubmit={submit("units/create/", "Unidad creada.")}
              >
                <label>
                  Código
                  <input name="code" required />
                </label>
                <label>
                  Nombre
                  <input name="name" required />
                </label>
                <label>
                  Símbolo
                  <input name="symbol" required />
                </label>
                <label>
                  Dimensión
                  <select name="dimension">
                    <option value="count">Conteo</option>
                    <option value="mass">Masa</option>
                    <option value="volume">Volumen</option>
                    <option value="length">Longitud</option>
                    <option value="duration">Duración</option>
                  </select>
                </label>
              </CommandForm>
              <CommandForm
                title="Nueva conversión"
                submitLabel="Versionar conversión"
                busy={busy}
                onSubmit={submit("unit-conversions/create/", "Conversión versionada.", (body) => ({
                  ...body,
                  valid_until: nullable(body.valid_until),
                }))}
              >
                <label>
                  Unidad de origen
                  <select name="from_unit_id" required>
                    <option value="">Selecciona</option>
                    {overview?.units.map((unit) => (
                      <option key={unit.id} value={unit.id}>
                        {text(unit, "name")}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Unidad destino
                  <select name="to_unit_id" required>
                    <option value="">Selecciona</option>
                    {overview?.units.map((unit) => (
                      <option key={unit.id} value={unit.id}>
                        {text(unit, "name")}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Factor exacto
                  <input name="multiplier" inputMode="decimal" required />
                </label>
                <label>
                  Vigente desde
                  <input name="valid_from" type="date" defaultValue={today} required />
                </label>
                <label>
                  Vigente hasta
                  <input name="valid_until" type="date" />
                </label>
              </CommandForm>
              <CommandForm
                title="Nuevo recurso"
                submitLabel="Crear recurso"
                busy={busy}
                onSubmit={submit("items/create/", "Recurso creado.", (body) => ({
                  ...body,
                  declared_capacity: nullable(body.declared_capacity),
                }))}
              >
                <label>
                  Nombre
                  <input name="name" required />
                </label>
                <label>
                  Naturaleza
                  <select name="nature">
                    <option value="consumable">Consumible</option>
                    <option value="reusable_pool">Pool reutilizable</option>
                    <option value="serialized_asset">Activo serializado</option>
                    <option value="supplied_service">Servicio suministrado</option>
                  </select>
                </label>
                <label>
                  Unidad base
                  <select name="base_unit_id" required>
                    <option value="">Selecciona</option>
                    {overview?.units.map((unit) => (
                      <option key={unit.id} value={unit.id}>
                        {text(unit, "name")} ({text(unit, "symbol")})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Capacidad simultánea
                  <input name="declared_capacity" inputMode="decimal" />
                </label>
              </CommandForm>
              <CommandForm
                title="Estado de recurso"
                submitLabel="Aplicar estado"
                busy={busy}
                onSubmit={submitAt(
                  (body) => `items/${text(body, "resource_id")}/status/`,
                  "Estado del recurso actualizado.",
                  (body) => ({
                    active: body.active === "true",
                    reason: body.reason,
                  }),
                )}
              >
                <label>
                  Recurso
                  <input name="resource_id" required />
                </label>
                <label>
                  Estado
                  <select name="active">
                    <option value="true">Activo</option>
                    <option value="false">Inactivo</option>
                  </select>
                </label>
                <label className="span-two">
                  Razón de inactivación
                  <input name="reason" />
                </label>
              </CommandForm>
              <CommandForm
                title="Nueva ubicación"
                submitLabel="Crear ubicación"
                busy={busy}
                onSubmit={submit("locations/create/", "Ubicación creada.")}
              >
                <label>
                  ID de sede
                  <input name="venue_id" required />
                </label>
                <label>
                  Código
                  <input name="code" required />
                </label>
                <label>
                  Nombre
                  <input name="name" required />
                </label>
              </CommandForm>
            </section>
          ) : null}
          {can("inventory:record_movement") ? (
            <section className="panel resource-command-grid">
              <CommandForm
                title="Registrar movimiento"
                submitLabel="Confirmar movimiento"
                busy={busy}
                onSubmit={submit("movements/record/", "Movimiento registrado.", (body) => ({
                  ...body,
                  direction: nullable(body.direction),
                  other_location_id: nullable(body.other_location_id),
                  corrects_id: nullable(body.corrects_id),
                }))}
              >
                <label>
                  Recurso
                  <input name="resource_id" required />
                </label>
                <label>
                  Ubicación
                  <input name="location_id" required />
                </label>
                <label>
                  Tipo
                  <select name="kind">
                    <option value="entry">Entrada</option>
                    <option value="exit">Salida</option>
                    <option value="adjustment">Ajuste</option>
                    <option value="transfer">Traslado</option>
                    <option value="return">Devolución</option>
                    <option value="correction">Corrección</option>
                  </select>
                </label>
                <label>
                  Cantidad base
                  <input name="quantity" inputMode="decimal" required />
                </label>
                <label>
                  Dirección
                  <select name="direction">
                    <option value="">Automática</option>
                    <option value="increase">Aumenta</option>
                    <option value="decrease">Disminuye</option>
                  </select>
                </label>
                <label>
                  Otra ubicación
                  <input name="other_location_id" />
                </label>
                <label>
                  Corrige movimiento
                  <input name="corrects_id" />
                </label>
                <label className="span-two">
                  Razón
                  <input name="reason" required />
                </label>
              </CommandForm>
            </section>
          ) : null}
        </>
      ) : null}

      {section === "supply" ? (
        <>
          <section className="panel resource-ledger">
            <div>
              <h2>Proveedores</h2>
              <Cards
                rows={overview?.suppliers ?? []}
                render={(row) => (
                  <article className="resource-card" key={row.id}>
                    <strong>{text(row, "legal_name")}</strong>
                    <span>
                      {text(row, "tax_identifier") !== "—"
                        ? text(row, "tax_identifier")
                        : text(row, "internal_code")}
                    </span>
                    <StatusBadge value={text(row, "status")} />
                  </article>
                )}
              />
            </div>
            <div>
              <h2>Compras y recepciones</h2>
              <Cards
                rows={overview?.purchases ?? []}
                render={(row) => (
                  <article className="resource-card" key={row.id}>
                    <strong>{text(row, "reference")}</strong>
                    <span>Proveedor {text(row, "supplier_id")}</span>
                    <StatusBadge value={text(row, "status")} />
                  </article>
                )}
              />
            </div>
          </section>
          <section className="panel resource-command-grid">
            {can("supplier:manage_profile") ? (
              <CommandForm
                title="Nuevo proveedor"
                submitLabel="Crear proveedor"
                busy={busy}
                onSubmit={submit("suppliers/create/", "Proveedor creado.", (body) => ({
                  ...body,
                  tax_identifier: nullable(body.tax_identifier),
                  internal_code: nullable(body.internal_code),
                }))}
              >
                <label>
                  Razón social
                  <input name="legal_name" required />
                </label>
                <label>
                  Identificación fiscal
                  <input name="tax_identifier" />
                </label>
                <label>
                  Código interno
                  <input name="internal_code" />
                </label>
              </CommandForm>
            ) : null}
            {can("supplier:manage_profile") ? (
              <CommandForm
                title="Estado de proveedor"
                submitLabel="Aplicar estado"
                busy={busy}
                onSubmit={submitAt(
                  (body) => `suppliers/${text(body, "supplier_id")}/status/`,
                  "Estado del proveedor actualizado.",
                  (body) => ({ active: body.active === "true", reason: body.reason }),
                )}
              >
                <label>
                  Proveedor
                  <input name="supplier_id" required />
                </label>
                <label>
                  Estado
                  <select name="active">
                    <option value="true">Activo</option>
                    <option value="false">Inactivo</option>
                  </select>
                </label>
                <label className="span-two">
                  Razón
                  <input name="reason" />
                </label>
              </CommandForm>
            ) : null}
            {can("supplier:link_contact") ? (
              <CommandForm
                title="Vincular contacto existente"
                submitLabel="Vincular Person"
                busy={busy}
                onSubmit={submitAt(
                  (body) => `suppliers/${text(body, "supplier_id")}/contacts/link/`,
                  "Contacto canónico vinculado.",
                  (body) => ({
                    person_id: body.person_id,
                    responsibility: body.responsibility,
                    is_primary: body.is_primary === "true",
                    valid_from: body.valid_from,
                  }),
                )}
              >
                <label>
                  Proveedor
                  <input name="supplier_id" required />
                </label>
                <label>
                  Person canónica
                  <input name="person_id" required />
                </label>
                <label>
                  Responsabilidad
                  <input name="responsibility" required />
                </label>
                <label>
                  Vigente desde
                  <input name="valid_from" type="date" defaultValue={today} required />
                </label>
                <label>
                  Contacto principal
                  <select name="is_primary">
                    <option value="false">No</option>
                    <option value="true">Sí</option>
                  </select>
                </label>
              </CommandForm>
            ) : null}
            {can("supplier:manage_terms") ? (
              <CommandForm
                title="Nueva vigencia de términos"
                submitLabel="Versionar términos"
                busy={busy}
                onSubmit={submitAt(
                  (body) => `suppliers/${text(body, "supplier_id")}/terms/add/`,
                  "Términos versionados.",
                  (body) => ({
                    valid_from: body.valid_from,
                    valid_until: nullable(body.valid_until),
                    payment_terms: body.payment_terms,
                    lead_time_days: body.lead_time_days,
                    notes: body.notes,
                  }),
                )}
              >
                <label>
                  Proveedor
                  <input name="supplier_id" required />
                </label>
                <label>
                  Vigente desde
                  <input name="valid_from" type="date" defaultValue={today} required />
                </label>
                <label>
                  Vigente hasta
                  <input name="valid_until" type="date" />
                </label>
                <label>
                  Plazo de entrega (días)
                  <input name="lead_time_days" type="number" min="0" required />
                </label>
                <label className="span-two">
                  Términos de pago
                  <input name="payment_terms" required />
                </label>
                <label className="span-two">
                  Notas
                  <input name="notes" />
                </label>
              </CommandForm>
            ) : null}
            {can("supplier:manage_offering") ? (
              <CommandForm
                title="Oferta suministrada"
                submitLabel="Registrar oferta"
                busy={busy}
                onSubmit={submitAt(
                  (body) => `suppliers/${text(body, "supplier_id")}/offerings/add/`,
                  "Oferta suministrada registrada.",
                  (body) => ({
                    resource_id: body.resource_id,
                    supplier_reference: body.supplier_reference,
                    minimum_quantity: body.minimum_quantity,
                    valid_from: body.valid_from,
                    valid_until: nullable(body.valid_until),
                  }),
                )}
              >
                <label>
                  Proveedor
                  <input name="supplier_id" required />
                </label>
                <label>
                  Recurso
                  <input name="resource_id" required />
                </label>
                <label>
                  Referencia del proveedor
                  <input name="supplier_reference" />
                </label>
                <label>
                  Cantidad mínima base
                  <input name="minimum_quantity" required />
                </label>
                <label>
                  Vigente desde
                  <input name="valid_from" type="date" defaultValue={today} required />
                </label>
                <label>
                  Vigente hasta
                  <input name="valid_until" type="date" />
                </label>
              </CommandForm>
            ) : null}
            {can("purchase:manage") ? (
              <CommandForm
                title="Nueva compra"
                submitLabel="Crear compra"
                busy={busy}
                onSubmit={submit("purchases/create/", "Compra creada.", (body) => ({
                  supplier_id: body.supplier_id,
                  reference: body.reference,
                  ordered_on: nullable(body.ordered_on),
                  root_reservation_id: nullable(body.root_reservation_id),
                  venue_id: nullable(body.venue_id),
                  notes: body.notes ?? "",
                  lines: [
                    {
                      resource_id: body.resource_id,
                      quantity: body.quantity,
                      procurement_unit_amount: nullable(body.procurement_unit_amount),
                      procurement_currency: body.procurement_unit_amount ? "USD" : null,
                      description: body.description,
                    },
                  ],
                }))}
              >
                <label>
                  Proveedor
                  <input name="supplier_id" required />
                </label>
                <label>
                  Referencia
                  <input name="reference" required />
                </label>
                <label>
                  Fecha
                  <input name="ordered_on" type="date" defaultValue={today} />
                </label>
                <label>
                  Recurso
                  <input name="resource_id" required />
                </label>
                <label>
                  Cantidad
                  <input name="quantity" required />
                </label>
                <label>
                  Importe unitario esperado
                  <input name="procurement_unit_amount" inputMode="decimal" />
                </label>
                <label>
                  Raíz de evento
                  <input name="root_reservation_id" />
                </label>
                <label>
                  Sede histórica
                  <input name="venue_id" />
                </label>
                <label className="span-two">
                  Descripción
                  <input name="description" required />
                </label>
                <input type="hidden" name="notes" value="" />
              </CommandForm>
            ) : null}
            {can("purchase:receive") ? (
              <CommandForm
                title="Confirmar recepción"
                submitLabel="Confirmar recepción"
                busy={busy}
                onSubmit={submit(
                  "receipt-lines/confirm/",
                  "Recepción confirmada e inventario actualizado.",
                  (body) => ({
                    ...body,
                    destination_location_id: nullable(body.destination_location_id),
                    serial_numbers: (typeof body.serial_numbers === "string"
                      ? body.serial_numbers
                      : ""
                    )
                      .split(",")
                      .map((value) => value.trim())
                      .filter(Boolean),
                    notes: "",
                  }),
                )}
              >
                <label>
                  Línea de compra
                  <input name="purchase_line_id" required />
                </label>
                <label>
                  Referencia de recepción
                  <input name="receipt_reference" required />
                </label>
                <label>
                  Fecha
                  <input name="received_on" type="date" defaultValue={today} required />
                </label>
                <label>
                  Tipo
                  <select name="kind">
                    <option value="goods_received">Bien recibido</option>
                    <option value="service_fulfilled">Servicio cumplido</option>
                  </select>
                </label>
                <label>
                  Cantidad base
                  <input name="quantity" required />
                </label>
                <label>
                  Ubicación destino
                  <input name="destination_location_id" />
                </label>
                <label className="span-two">
                  Series separadas por coma
                  <input name="serial_numbers" />
                </label>
              </CommandForm>
            ) : null}
            {can("purchase:materialize_finance") &&
            (can("finance:record_actuals") || can("finance:allocate_expenses")) ? (
              <CommandForm
                title="Materializar hecho financiero"
                submitLabel="Registrar en Finanzas"
                busy={busy}
                onSubmit={submitAt(
                  (body) => `receipt-lines/${text(body, "receipt_line_id")}/materialize-finance/`,
                  "Procedencia de recepción materializada en Finanzas.",
                  (body) => ({
                    target_kind: body.target_kind,
                    category_id: body.category_id,
                    amount: body.amount,
                    currency: body.currency,
                    economic_date: body.economic_date,
                    description: body.description,
                    evidence_reference: body.evidence_reference,
                    root_reservation_id: nullable(body.root_reservation_id),
                    venue_id: nullable(body.venue_id),
                    expense_type:
                      body.target_kind === "expense_occurrence" ? body.expense_type : null,
                    allocations:
                      body.target_kind === "expense_occurrence"
                        ? [
                            {
                              scope: "business",
                              root_reservation_id: null,
                              venue_id: null,
                              amount: body.amount,
                            },
                          ]
                        : [],
                  }),
                )}
              >
                <label>
                  Línea recibida
                  <input name="receipt_line_id" required />
                </label>
                <label>
                  Destino
                  <select name="target_kind">
                    {can("finance:record_actuals") ? (
                      <option value="actual_direct_cost">Costo directo real</option>
                    ) : null}
                    {can("finance:allocate_expenses") ? (
                      <option value="expense_occurrence">Ocurrencia de gasto</option>
                    ) : null}
                  </select>
                </label>
                <label>
                  Categoría Finance
                  <input name="category_id" required />
                </label>
                <label>
                  Importe
                  <input name="amount" inputMode="decimal" required />
                </label>
                <label>
                  Moneda
                  <input name="currency" defaultValue="USD" required />
                </label>
                <label>
                  Fecha económica
                  <input name="economic_date" type="date" defaultValue={today} required />
                </label>
                <label>
                  Tipo de gasto
                  <select name="expense_type">
                    <option value="variable">Variable</option>
                    <option value="recurring">Recurrente</option>
                  </select>
                </label>
                <label>
                  Raíz de evento
                  <input name="root_reservation_id" />
                </label>
                <label>
                  Sede histórica
                  <input name="venue_id" />
                </label>
                <label className="span-two">
                  Descripción
                  <input name="description" required />
                </label>
                <label className="span-two">
                  Evidencia
                  <input name="evidence_reference" required />
                </label>
              </CommandForm>
            ) : null}
          </section>
        </>
      ) : null}

      {section === "events" ? (
        <>
          <section className="panel resource-ledger">
            <div>
              <h2>Requerimientos y faltantes</h2>
              <Cards
                rows={overview?.requirements ?? []}
                render={(row) => (
                  <article
                    className={`resource-card ${text(row, "status") === "shortage" ? "resource-card--shortage" : ""}`}
                    key={row.id}
                  >
                    <strong>
                      {text(row, "quantity")} · {text(row, "resource_id")}
                    </strong>
                    <StatusBadge value={text(row, "status")} />
                    <span>{text(row, "reason")}</span>
                  </article>
                )}
              />
            </div>
            <div>
              <h2>Asignaciones</h2>
              <Cards
                rows={overview?.assignments ?? []}
                render={(row) => (
                  <article className="resource-card" key={row.id}>
                    <strong>{text(row, "resource_id")}</strong>
                    <StatusBadge value={text(row, "status")} />
                    <span>Reserva {text(row, "reservation_id")}</span>
                  </article>
                )}
              />
            </div>
          </section>
          {can("resource:reserve") ? (
            <section className="panel resource-command-grid">
              <CommandForm
                title="Crear requerimiento"
                submitLabel="Registrar requerimiento"
                busy={busy}
                onSubmit={submit(
                  "requirements/create/",
                  "Requerimiento registrado; revisa si existe faltante.",
                )}
              >
                <label>
                  Reserva vigente
                  <input name="reservation_id" required />
                </label>
                <label>
                  Recurso
                  <input name="resource_id" required />
                </label>
                <label>
                  Cantidad
                  <input name="quantity" required />
                </label>
                <label>
                  Razón
                  <input name="reason" />
                </label>
              </CommandForm>
              <CommandForm
                title="Reservar o asignar"
                submitLabel="Reservar recurso"
                busy={busy}
                onSubmit={submit("assignments/reserve/", "Capacidad reservada.", (body) => ({
                  ...body,
                  source_location_id: nullable(body.source_location_id),
                  serialized_asset_id: nullable(body.serialized_asset_id),
                }))}
              >
                <label>
                  Requerimiento
                  <input name="requirement_id" required />
                </label>
                <label>
                  Ubicación origen
                  <input name="source_location_id" />
                </label>
                <label>
                  Activo serializado
                  <input name="serialized_asset_id" />
                </label>
              </CommandForm>
              <CommandForm
                title="Ejecutar asignación"
                submitLabel="Registrar hecho"
                busy={busy}
                onSubmit={submitAt(
                  (body) => `assignments/${text(body, "assignment_id")}/execute/`,
                  "Ejecución del recurso registrada.",
                  (body) => ({ action: body.action, notes: body.notes }),
                )}
              >
                <label>
                  Asignación
                  <input name="assignment_id" required />
                </label>
                <label>
                  Acción
                  <select name="action">
                    <option value="issue">Entregar o consumir</option>
                    <option value="fulfill">Cumplir servicio</option>
                    <option value="return">Devolver</option>
                  </select>
                </label>
                <label className="span-two">
                  Nota
                  <input name="notes" />
                </label>
              </CommandForm>
            </section>
          ) : null}
        </>
      ) : null}

      {section === "maintenance" ? (
        <>
          <section className="panel resource-ledger">
            <div>
              <h2>Indisponibilidades</h2>
              <Cards
                rows={overview?.unavailability ?? []}
                render={(row) => (
                  <article className="resource-card" key={row.id}>
                    <strong>{text(row, "reason")}</strong>
                    <StatusBadge
                      value={text(row, "is_active") === "true" ? "active" : "released"}
                    />
                    <span>
                      {text(row, "quantity")} · {text(row, "resource_id")}
                    </span>
                  </article>
                )}
              />
            </div>
            <div>
              <h2>Mantenimiento</h2>
              <Cards
                rows={overview?.maintenance ?? []}
                render={(row) => (
                  <article className="resource-card" key={row.id}>
                    <strong>{text(row, "description")}</strong>
                    <StatusBadge value={text(row, "status")} />
                  </article>
                )}
              />
            </div>
          </section>
          {can("resource:maintain") ? (
            <section className="panel resource-command-grid">
              <CommandForm
                title="Registrar indisponibilidad"
                submitLabel="Bloquear capacidad"
                busy={busy}
                onSubmit={submit(
                  "unavailability/record/",
                  "Indisponibilidad registrada.",
                  (body) => ({
                    ...body,
                    serialized_asset_id: nullable(body.serialized_asset_id),
                    location_id: nullable(body.location_id),
                    maintenance_description: nullable(body.maintenance_description),
                    corrects_id: nullable(body.corrects_id),
                  }),
                )}
              >
                <label>
                  Recurso
                  <input name="resource_id" required />
                </label>
                <label>
                  Activo serializado
                  <input name="serialized_asset_id" />
                </label>
                <label>
                  Ubicación
                  <input name="location_id" />
                </label>
                <label>
                  Cantidad
                  <input name="quantity" required />
                </label>
                <label>
                  Inicio
                  <input name="starts_at" type="datetime-local" required />
                </label>
                <label>
                  Fin
                  <input name="ends_at" type="datetime-local" required />
                </label>
                <label>
                  Razón
                  <input name="reason" required />
                </label>
                <label>
                  Trabajo de mantenimiento
                  <input name="maintenance_description" />
                </label>
                <label>
                  Corrige indisponibilidad
                  <input name="corrects_id" />
                </label>
              </CommandForm>
              <CommandForm
                title="Cerrar indisponibilidad"
                submitLabel="Restaurar disponibilidad"
                busy={busy}
                onSubmit={submitAt(
                  (body) => `unavailability/${text(body, "unavailability_id")}/close/`,
                  "Indisponibilidad cerrada mediante transición.",
                  () => ({}),
                )}
              >
                <label>
                  Indisponibilidad
                  <input name="unavailability_id" required />
                </label>
              </CommandForm>
            </section>
          ) : null}
        </>
      ) : null}
    </>
  );
}
