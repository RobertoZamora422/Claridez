"""Rutas de autenticación HTTP de Claridez."""

from django.urls import path

from .views import (
    CsrfView,
    EmailVerificationConfirmView,
    EmailVerificationRequestView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
)

app_name = "identity"

urlpatterns = [
    path("csrf/", CsrfView.as_view(), name="csrf"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("password/change/", PasswordChangeView.as_view(), name="password-change"),
    path(
        "password/reset/request/",
        PasswordResetRequestView.as_view(),
        name="password-reset-request",
    ),
    path(
        "password/reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path(
        "email/verification/request/",
        EmailVerificationRequestView.as_view(),
        name="email-verification-request",
    ),
    path(
        "email/verification/confirm/",
        EmailVerificationConfirmView.as_view(),
        name="email-verification-confirm",
    ),
]
