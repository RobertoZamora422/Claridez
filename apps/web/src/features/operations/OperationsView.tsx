import { OperationDetail } from "./OperationDetail";
import { OperationsList } from "./OperationsList";
import { useOperationsController } from "./useOperationsController";

export function OperationsView({
  organizationId,
  canManage,
  canExecute,
}: {
  organizationId: string;
  canManage: boolean;
  canExecute: boolean;
}) {
  const controller = useOperationsController({ organizationId, canManage });

  if (controller.selectedId && controller.detail) {
    const reservationId = controller.detail.reservation_id;
    return (
      <OperationDetail
        detail={controller.detail}
        base={controller.base}
        assignees={controller.assignees}
        canManage={canManage}
        canExecute={canExecute}
        notice={controller.notice}
        error={controller.error}
        onBack={controller.closeDetail}
        onAssign={controller.assign}
        onCommand={controller.command}
        onReload={() => controller.loadDetail(reservationId)}
        onReplace={controller.replaceDetail}
        onItemUpdated={controller.applyItemUpdate}
      />
    );
  }

  return (
    <OperationsList
      events={controller.events}
      statusFilter={controller.statusFilter}
      attentionFilter={controller.attentionFilter}
      loading={controller.loading}
      error={controller.error}
      onStatusFilter={controller.setStatusFilter}
      onAttentionFilter={controller.setAttentionFilter}
      onSelect={controller.selectEvent}
    />
  );
}
