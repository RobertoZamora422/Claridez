from django.urls import path

from .reminder_views import ReminderCancelView, ReminderRequestView

urlpatterns = [
    path("<uuid:organization_id>/reminders/", ReminderRequestView.as_view()),
    path(
        "<uuid:organization_id>/reminders/<uuid:intent_id>/cancel/",
        ReminderCancelView.as_view(),
    ),
]
