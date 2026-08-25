import { AdvancedOperationPanel } from "./AdvancedOperationPanel";
import { OperationDetail } from "./OperationDetail";
import { OperationTemplatesPanel } from "./OperationTemplatesPanel";
import { OperationsList } from "./OperationsList";
import { useOperationsController } from "./useOperationsController";

export function OperationsView({
  organizationId,
  canManage,
  canExecute,
  canReadAdvanced = false,
  canManageTemplates = false,
  canManageIncidents = false,
  canAuthorizeChanges = false,
  canManageEvidence = false,
  canClose = false,
}: {
  organizationId: string;
  canManage: boolean;
  canExecute: boolean;
  canReadAdvanced?: boolean;
  canManageTemplates?: boolean;
  canManageIncidents?: boolean;
  canAuthorizeChanges?: boolean;
  canManageEvidence?: boolean;
  canClose?: boolean;
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
        advancedPanel={
          canReadAdvanced ? (
            <AdvancedOperationPanel
              organizationId={organizationId}
              detail={controller.detail}
              assignees={controller.assignees}
              canManage={canManage}
              canExecute={canExecute}
              canManageIncidents={canManageIncidents}
              canAuthorizeChanges={canAuthorizeChanges}
              canManageEvidence={canManageEvidence}
              canClose={canClose}
              onPreparationReload={() => controller.loadDetail(reservationId)}
            />
          ) : undefined
        }
      />
    );
  }

  return (
    <>
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
      {canReadAdvanced ? (
        <OperationTemplatesPanel organizationId={organizationId} canManage={canManageTemplates} />
      ) : null}
    </>
  );
}
