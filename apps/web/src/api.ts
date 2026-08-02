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
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
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
  full_name?: string;
  phone_e164?: string;
  email?: string | null;
  origin?: string;
  commercial_type: "lead" | "client";
  revision: number;
}

export interface Reservation {
  id: string;
  status: "provisional" | "confirmed" | "expired" | "cancelled";
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

export interface EventRequest {
  id: string;
  person: Person;
  event_type: string;
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
  from: string;
  to: string;
  available: boolean;
  blocks: Reservation[];
}

export type OperationStatus = "preparing" | "ready" | "in_progress" | "completed" | "cancelled";

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
    event_type: string;
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
    operational_notes: string;
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
