import type { OperationEvent, PreparationItem } from "../../api";

export const STATUS_LABELS: Record<OperationEvent["preparation"]["status"], string> = {
  preparing: "En preparación",
  ready: "Listo",
  in_progress: "En ejecución",
  completed: "Completado",
  cancelled: "Cancelado",
  rescheduled: "Reprogramado",
};

export const ITEM_STATUS_LABELS: Record<PreparationItem["status"], string> = {
  pending: "Pendiente",
  in_progress: "En curso",
  blocked: "Bloqueado",
  completed: "Completado",
  not_applicable: "No aplica",
};

export const SECTION_LABELS: Record<PreparationItem["section"], string> = {
  definitions: "Definiciones",
  setup: "Preparación",
  final_review: "Revisión final",
};
