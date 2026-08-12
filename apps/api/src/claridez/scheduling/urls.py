from django.urls import path

from .views import (
    AvailabilityView,
    BlockCancelView,
    BlockListCreateView,
    BlockReleaseView,
    CalendarExportView,
    CalendarView,
    PolicyView,
    RescheduleView,
    ScheduleHistoryView,
    SchedulingCapabilitiesView,
)

app_name = "scheduling"

urlpatterns = [
    path("scheduling/capabilities/", SchedulingCapabilitiesView.as_view()),
    path("scheduling/calendar/", CalendarView.as_view()),
    path("scheduling/calendar.ics", CalendarExportView.as_view()),
    path("scheduling/availability/", AvailabilityView.as_view()),
    path("scheduling/spaces/<uuid:space_id>/policy/", PolicyView.as_view()),
    path("scheduling/blocks/", BlockListCreateView.as_view()),
    path("scheduling/blocks/<uuid:block_id>/release/", BlockReleaseView.as_view()),
    path("scheduling/blocks/<uuid:block_id>/cancel/", BlockCancelView.as_view()),
    path("reservations/<uuid:reservation_id>/reschedule/", RescheduleView.as_view()),
    path(
        "reservations/<uuid:reservation_id>/schedule-history/",
        ScheduleHistoryView.as_view(),
    ),
]
