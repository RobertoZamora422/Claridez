import { useCallback, useState } from "react";

import {
  ApiError,
  api,
  type OperationAssignee,
  type OperationEvent,
  type PreparationItem,
} from "../../api";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { message } from "../../shared/utilities";
import { STATUS_LABELS } from "./constants";

export function useOperationsController({
  organizationId,
  canManage,
}: {
  organizationId: string;
  canManage: boolean;
}) {
  const base = `/api/v1/organizations/${organizationId}/operations/events`;
  const [events, setEvents] = useState<OperationEvent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<OperationEvent | null>(null);
  const [assignees, setAssignees] = useState<OperationAssignee[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [attentionFilter, setAttentionFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadList = useCallback(async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ page_size: "100" });
    if (statusFilter) params.append("status", statusFilter);
    if (attentionFilter) params.set("attention", attentionFilter);
    try {
      const body = await api<{ results: OperationEvent[] }>(`${base}/?${params}`);
      setEvents(body.results);
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [attentionFilter, base, statusFilter]);

  const loadDetail = useCallback(
    async (reservationId: string) => {
      setError("");
      try {
        const body = await api<OperationEvent>(`${base}/${reservationId}/`);
        setDetail(body);
      } catch (caught: unknown) {
        setError(message(caught));
      }
    },
    [base],
  );

  const loadAssignees = useCallback(async () => {
    if (!canManage) return;
    try {
      const body = await api<{ assignees: OperationAssignee[] }>(
        `/api/v1/organizations/${organizationId}/operations/assignees/`,
      );
      setAssignees(body.assignees);
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }, [canManage, organizationId]);

  useInitialLoad(loadList);
  useInitialLoad(loadAssignees);

  async function assign(membershipId: string) {
    if (!detail) return;
    try {
      const body = await api<OperationEvent>(`${base}/${detail.reservation_id}/assign/`, {
        method: "POST",
        body: JSON.stringify({
          revision: detail.preparation.revision,
          responsible_membership_id: membershipId,
        }),
      });
      setDetail(body);
      setNotice("Responsable actualizado.");
    } catch (caught: unknown) {
      setError(message(caught));
      if (caught instanceof ApiError && caught.status === 409)
        await loadDetail(detail.reservation_id);
    }
  }

  async function command(commandName: "ready" | "start" | "complete") {
    if (!detail) return;
    const labels = {
      ready: "declarar listo",
      start: "iniciar la ejecución",
      complete: "completar el evento",
    };
    if (!window.confirm(`¿Confirmas ${labels[commandName]}?`)) return;
    try {
      const body = await api<OperationEvent>(`${base}/${detail.reservation_id}/${commandName}/`, {
        method: "POST",
        body: JSON.stringify({ revision: detail.preparation.revision }),
      });
      setDetail(body);
      setNotice(`Estado actualizado: ${STATUS_LABELS[body.preparation.status]}.`);
      await loadList();
    } catch (caught: unknown) {
      setError(message(caught));
      if (caught instanceof ApiError && caught.status === 409)
        await loadDetail(detail.reservation_id);
    }
  }

  function applyItemUpdate(updated: PreparationItem, revision: number, preparationStatus?: string) {
    setDetail((current) =>
      current
        ? {
            ...current,
            preparation: {
              ...current.preparation,
              status: (preparationStatus ??
                current.preparation.status) as OperationEvent["preparation"]["status"],
              revision,
              items: (current.preparation.items ?? []).map((entry) =>
                entry.id === updated.id ? updated : entry,
              ),
            },
          }
        : current,
    );
    setNotice("Ítem actualizado.");
  }

  return {
    base,
    events,
    selectedId,
    detail,
    assignees,
    statusFilter,
    attentionFilter,
    loading,
    error,
    notice,
    setStatusFilter,
    setAttentionFilter,
    loadDetail,
    assign,
    command,
    applyItemUpdate,
    replaceDetail: (updated: OperationEvent, noticeText: string) => {
      setDetail(updated);
      setNotice(noticeText);
    },
    selectEvent: (reservationId: string) => {
      setSelectedId(reservationId);
      void loadDetail(reservationId);
    },
    closeDetail: () => {
      setSelectedId(null);
      setDetail(null);
    },
  };
}
