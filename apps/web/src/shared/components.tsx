import type { ReactNode } from "react";

const STATUS_LABELS: Record<string, string> = {
  new: "Nueva",
  quoted: "Cotizada",
  accepted: "Aceptada",
  confirmed: "Confirmada",
  closed_lost: "Oportunidad perdida",
  cancelled: "Cancelada",
  provisional: "Reserva provisional",
  expired: "Vencida",
  draft: "Borrador",
  issued: "Emitida",
  superseded: "Sustituida",
  withdrawn: "Retirada",
  active: "Activo",
  released: "Liberado",
  rescheduled: "Reprogramada",
};

export function StatusBadge({ value }: { value: string }) {
  return <span className={`status status--${value}`}>{STATUS_LABELS[value] ?? value}</span>;
}

export function Notice({
  children,
  tone = "error",
}: {
  children: ReactNode;
  tone?: "error" | "info";
}) {
  return (
    <div className={`notice notice--${tone}`} role={tone === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Loading({ label = "Cargando información…" }: { label?: string }) {
  return (
    <p className="loading" role="status">
      {label}
    </p>
  );
}
