export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

let csrfToken: string | null = null;

async function csrf(): Promise<string> {
  if (csrfToken !== null) return csrfToken;
  const response = await fetch("/api/v1/auth/csrf/", { credentials: "same-origin" });
  if (!response.ok)
    throw new ApiError("csrf_failed", "No se pudo iniciar una sesión segura.", response.status);
  const body = (await response.json()) as { csrf_token: string };
  csrfToken = body.csrf_token;
  return csrfToken;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRFToken", await csrf());
  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  const body = (await response.json().catch(() => null)) as {
    error?: { code?: string; message?: string };
  } | null;
  if (!response.ok) {
    throw new ApiError(
      body?.error?.code ?? "request_failed",
      body?.error?.message ?? "No fue posible completar la operación.",
      response.status,
    );
  }
  return body as T;
}

export async function externalApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  const body = (await response.json().catch(() => null)) as {
    error?: { code?: string; message?: string };
  } | null;
  if (!response.ok) {
    throw new ApiError(
      body?.error?.code ?? "external_access_failed",
      body?.error?.message ?? "El acceso documental no está disponible.",
      response.status,
    );
  }
  return body as T;
}

export async function login(email: string, password: string): Promise<User> {
  const response = await api<{ user: User }>("/api/v1/auth/login/", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  csrfToken = null;
  return response.user;
}

export async function logout(): Promise<void> {
  await api("/api/v1/auth/logout/", { method: "POST" });
  csrfToken = null;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
}

export interface Person {
  id: string;
  canonical_id?: string;
  requested_id?: string;
  full_name?: string;
  phone_e164?: string;
  email?: string | null;
  origin?: string;
  commercial_type: "lead" | "client";
  revision: number;
  aliases?: { id: string; kind: "phone" | "email"; value: string; source_person_id: string }[];
}

export interface CrmPerson {
  id: string;
  full_name: string;
  phone_e164: string;
  email: string | null;
  revision: number;
  has_interest_history: boolean;
  is_client: boolean;
  aliases?: { kind: "phone" | "email"; value: string; source_person_id: string }[];
}

export interface CrmTask {
  id: string;
  person_id: string;
  event_request_id: string | null;
  title: string;
  due_at: string;
  next_contact_at: string | null;
  action_at: string;
  status: "open" | "completed" | "cancelled";
  responsible_membership_id: string;
  completed_at: string | null;
  cancellation_reason: string | null;
  cancellation_reason_unavailable: boolean;
  revision: number;
  overdue: boolean;
  requires_schedule_review: boolean;
  last_schedule_event: {
    id: string;
    kind: string;
    occurred_at: string;
    root_id: string;
    reservation_id: string;
  } | null;
  history?: {
    id: string;
    kind: string;
    revision: number;
    status: string;
    reason: string | null;
    reason_unavailable: boolean;
    created_at: string;
  }[];
}

export interface CrmInteraction {
  id: string;
  person_id: string;
  event_request_id: string | null;
  channel: string;
  direction: "inbound" | "outbound";
  occurred_at: string;
  responsible_membership_id: string;
  summary: string;
  correction_of_id: string | null;
  created_at: string;
}

export interface CrmHistoryEntry {
  id: string;
  kind: string;
  status: string;
  request_revision: number;
  occurred_at: string | null;
  provenance: "cutover_snapshot" | "database";
  reason: string | null;
  recorded_at: string;
}

export interface CrmOpportunity {
  id: string;
  person: CrmPerson;
  event_type: string;
  starts_at: string;
  ends_at: string;
  status: EventRequest["status"];
  result: "open" | "won" | "lost";
  origin: string;
  origin_detail: string | null;
  responsible_membership_id: string;
  closed_reason: string | null;
  revision: number;
  next_action: CrmTask | null;
  updated_at: string;
  general_need?: string;
  notes?: string;
  estimated_guests?: number;
  venue?: { id: string; name: string };
  space?: { id: string; name: string };
  history?: CrmHistoryEntry[];
}

export interface CrmIndicators {
  opportunities: number;
  open: number;
  won: number;
  lost: number;
  without_next_action: number;
  overdue_tasks: number;
}

export interface ConsentEvent {
  id: string;
  person_id: string;
  purpose: string;
  channel: string;
  event_type: string;
  decision: "granted" | "revoked";
  source: string;
  occurred_at: string;
  evidence_reference: string;
  corrects_id: string | null;
  created_at: string;
}

export interface CrmPersonOverview {
  person: CrmPerson;
  opportunities: CrmOpportunity[];
  interactions: CrmInteraction[];
  tasks: CrmTask[];
  consent: {
    effective: { purpose: string; channel: string; decision: string; event_id: string }[];
    events: ConsentEvent[];
  };
  timeline: {
    type: "opportunity" | "interaction" | "task" | "schedule";
    at: string;
    data: unknown;
  }[];
}

export interface Reservation {
  id: string;
  space_id: string;
  root_id?: string;
  predecessor_id?: string | null;
  revision?: number;
  status: "provisional" | "confirmed" | "expired" | "cancelled" | "rescheduled";
  starts_at: string;
  ends_at: string;
  event_timezone: string;
  hold_expires_at: string;
  confirmation_kind: "external_deposit" | "waiver" | null;
  recognized_deposit_amount: string | null;
  deposit_reported_at: string | null;
  deposit_reference: string | null;
  confirmed_at: string | null;
  waiver_reason: string | null;
  waiver_authorized_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  event_request_id?: string;
  event_type?: string;
}

export interface CalendarEntry {
  id: string;
  type: "reservation" | "hold" | "block";
  status: string;
  revision: number;
  root_id?: string;
  space_id: string;
  space_name: string;
  venue_id: string;
  venue_name: string;
  starts_at: string;
  ends_at: string;
  event_timezone: string;
  reason?: string;
  setup_minutes?: number;
  teardown_minutes?: number;
  buffer_before_minutes?: number;
  buffer_after_minutes?: number;
  is_blocking: boolean;
}

export interface CalendarPayload {
  view: "day" | "week" | "month";
  anchor_date: string;
  timezone: string;
  from: string;
  to: string;
  entries: CalendarEntry[];
}

export interface EventRequest {
  id: string;
  person: Person;
  event_type_id: string;
  event_type: string;
  venue: { id: string; name: string };
  space: { id: string; name: string };
  starts_at: string;
  ends_at: string;
  event_timezone: string;
  estimated_guests: number;
  general_need: string;
  notes: string;
  origin: string;
  status: "new" | "quoted" | "accepted" | "confirmed" | "closed_lost" | "cancelled";
  revision: number;
  quotation_id: string | null;
  reservation: Reservation | null;
}

export interface QuotationLine {
  id?: string;
  source?: "ad_hoc" | "catalog";
  catalog_item_id?: string | null;
  catalog_item_revision_id?: string | null;
  catalog_price_id?: string | null;
  package_components?: CatalogComponent[];
  position?: number;
  description: string;
  unit_label: string | null;
  quantity: string;
  unit_price: string;
  discount_amount: string;
  line_subtotal?: string;
  line_total?: string;
}

export interface QuotationVersion {
  id: string;
  version: number;
  revision: number;
  status: string;
  stored_status: string;
  valid_until: string;
  currency: "USD";
  subtotal: string;
  discount_total: string;
  total: string;
  notes: string;
  lines: QuotationLine[];
  reservation_id: string | null;
}

export interface Quotation {
  id: string;
  event_request_id: string;
  visible_number: string;
  versions: QuotationVersion[];
}

export interface Availability {
  space: { id: string; name: string; venue_id: string; venue_name: string };
  from: string;
  to: string;
  available: boolean;
  blocks: Reservation[];
}

export interface Space {
  id: string;
  venue_id: string;
  name: string;
  is_primary: boolean;
  is_active: boolean;
  revision: number;
}

export interface Venue {
  id: string;
  name: string;
  location_reference: string | null;
  is_primary: boolean;
  is_active: boolean;
  revision: number;
  spaces: Space[];
}

export interface EventTypeDefinition {
  id: string;
  name: string;
  is_active: boolean;
  revision: number;
}

export interface CatalogComponent {
  item_id: string;
  revision_id: string;
  revision: number;
  kind: "service" | "product";
  name: string;
  unit_label: string;
  quantity: string;
}

export interface CatalogPrice {
  id: string;
  amount: string;
  currency: "USD";
  valid_from: string;
  valid_until: string | null;
  revision: number;
}

export interface CatalogItem {
  id: string;
  kind: "service" | "product" | "package";
  name: string;
  description: string | null;
  unit_label: string;
  is_active: boolean;
  revision: number;
  revision_id: string;
  components: CatalogComponent[];
  current_price?: CatalogPrice | null;
  prices?: CatalogPrice[];
}

export type OperationStatus =
  "preparing" | "ready" | "in_progress" | "completed" | "cancelled" | "rescheduled";

export interface OperationMembership {
  membership_id: string;
  display_name: string;
  role: string;
  available: boolean;
}

export interface OperationAssignee {
  membership_id: string;
  display_name: string;
  role: string;
}

export interface HistoricalOperationActor {
  membership_id: string;
  display_name: string;
  available: boolean;
}

export interface PreparationItem {
  id: string;
  client_request_id: string;
  baseline_key: string | null;
  section: "definitions" | "setup" | "final_review";
  position: number;
  title: string;
  is_required: boolean;
  responsible: OperationMembership | null;
  due_on: string | null;
  status: "pending" | "in_progress" | "blocked" | "completed" | "not_applicable";
  notes: string;
  status_note: string;
  revision: number;
  resolved_at?: string;
  resolved_by?: HistoricalOperationActor;
}

export interface OperationEvent {
  reservation_id: string;
  event: {
    event_type_id: string;
    event_type: string;
    venue: { id: string; name: string };
    space: { id: string; name: string };
    starts_at: string;
    ends_at: string;
    timezone: string;
    estimated_guests: number;
    general_need: string;
  };
  contact: { display_name: string; phone_e164?: string };
  preparation: {
    status: OperationStatus;
    revision: number;
    responsible: OperationMembership | null;
    operational_notes?: string;
    baseline_version: string;
    ready_at: string | null;
    ready_by: HistoricalOperationActor | null;
    started_at: string | null;
    started_by: HistoricalOperationActor | null;
    completed_at: string | null;
    completed_by: HistoricalOperationActor | null;
    attention: {
      pending_count: number;
      overdue_count: number;
      blocked_count: number;
      is_overdue: boolean;
      is_upcoming: boolean;
      is_ready: boolean;
      has_blockers: boolean;
      responsible_unavailable: boolean;
    };
    items?: PreparationItem[];
  };
}
