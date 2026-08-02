import type { OperationEvent, PreparationItem } from "../../api";

export function localDate(value: string, timeZone: string) {
  return new Intl.DateTimeFormat("es-EC", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(new Date(value));
}

export function reorderTargets(items: PreparationItem[], item: PreparationItem) {
  const sectionItems = items.filter((entry) => entry.section === item.section);
  const sectionIndex = sectionItems.findIndex((entry) => entry.id === item.id);
  const up = sectionIndex > 0 ? sectionItems[sectionIndex - 1]?.id : undefined;
  if (sectionIndex < 0 || sectionIndex >= sectionItems.length - 1) return { up, down: undefined };
  const nextId = sectionItems[sectionIndex + 1]?.id;
  const nextIndex = items.findIndex((entry) => entry.id === nextId);
  return { up, down: items[nextIndex + 1]?.id ?? null };
}

export function readinessBlockers(event: OperationEvent) {
  const items = event.preparation.items ?? [];
  const blockers: { message: string; itemId?: string }[] = [];
  if (!event.preparation.responsible)
    blockers.push({ message: "Asigna un responsable principal." });
  const baseline = items.filter((item) => item.baseline_key !== null);
  if (baseline.length !== 7)
    blockers.push({ message: "La baseline operativa no contiene sus siete verificaciones." });
  const pendingRequired = items.find(
    (item) => item.is_required && !["completed", "not_applicable"].includes(item.status),
  );
  if (pendingRequired)
    blockers.push({
      message: "Resuelve todas las verificaciones obligatorias.",
      itemId: pendingRequired.id,
    });
  const blocked = items.find((item) => item.status === "blocked");
  if (blocked) blockers.push({ message: "Resuelve los bloqueos.", itemId: blocked.id });
  const finalReview = items.find((item) => item.baseline_key === "final_readiness_review");
  if (finalReview?.status !== "completed")
    blockers.push({
      message: "Completa la revisión final.",
      ...(finalReview ? { itemId: finalReview.id } : {}),
    });
  return blockers;
}
