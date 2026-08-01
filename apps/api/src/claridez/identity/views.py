"""Endpoints HTTP de autenticación local."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import signals as auth_signals
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token, rotate_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth_services import (
    InvalidCurrentPassword,
    InvalidOrExpiredToken,
    change_password,
    confirm_email_verification,
    confirm_password_reset,
    is_email_verification_eligible,
    is_login_eligible,
    is_password_reset_eligible,
)
from .emailing import send_email_verification, send_password_reset_email
from .errors import error_response
from .managers import canonicalize_email
from .models import User
from .serializers import (
    AuthUserSerializer,
    CsrfResponseSerializer,
    EmailRequestSerializer,
    ErrorResponseSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmationSerializer,
    StatusResponseSerializer,
    TokenConfirmationSerializer,
    UserResponseSerializer,
)
from .sessions import start_absolute_session

GENERIC_ACCEPTED = {"status": "accepted"}
GENERIC_OK = {"status": "ok"}


def _drf_error(code: str, message: str, *, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _invalid_credentials() -> Response:
    return _drf_error(
        "invalid_credentials",
        "No fue posible iniciar sesión con esas credenciales.",
        status=401,
    )


def _authentication_required() -> Response:
    return _drf_error(
        "authentication_required",
        "Se requiere una sesión válida.",
        status=401,
    )


def _authenticated_user(request: Request) -> User | None:
    user = request._request.user
    if isinstance(user, User) and user.is_authenticated:
        return user
    return None


def _canonical_email_from(serializer: EmailRequestSerializer) -> str | None:
    if not serializer.is_valid():
        return None
    try:
        return canonicalize_email(serializer.validated_data["email"])
    except ValueError:
        return None


def csrf_failure(request: HttpRequest, reason: str = "") -> JsonResponse:
    del request, reason
    return error_response(
        "csrf_failed",
        "La comprobación CSRF falló.",
        status=403,
    )


class CsrfView(APIView):
    authentication_classes: list[type[Any]] = []
    permission_classes: list[type[Any]] = []

    @extend_schema(responses={200: CsrfResponseSerializer}, tags=["Autenticación"])
    @method_decorator(ensure_csrf_cookie)
    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request._request)})


@method_decorator(csrf_protect, name="dispatch")
class CsrfProtectedAPIView(APIView):
    authentication_classes: list[type[Any]] = []
    permission_classes: list[type[Any]] = []


class LoginView(CsrfProtectedAPIView):
    @extend_schema(
        request=LoginSerializer,
        responses={
            200: UserResponseSerializer,
            401: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
        tags=["Autenticación"],
    )
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid_credentials()
        try:
            email = canonicalize_email(serializer.validated_data["email"])
        except ValueError:
            return _invalid_credentials()

        user = authenticate(
            request=request._request,
            email=email,
            password=serializer.validated_data["password"],
        )
        if not isinstance(user, User) or not is_login_eligible(user):
            if isinstance(user, User):
                auth_signals.user_login_failed.send(
                    sender=User,
                    credentials={"email": email},
                    request=request._request,
                )
            return _invalid_credentials()

        request._request.session.cycle_key()
        login(request._request, user)
        start_absolute_session(request._request)
        return Response({"user": AuthUserSerializer(user).data})


class LogoutView(CsrfProtectedAPIView):
    authentication_classes = [SessionAuthentication]

    @extend_schema(
        request=None,
        responses={200: StatusResponseSerializer},
        tags=["Autenticación"],
    )
    def post(self, request: Request) -> Response:
        logout(request._request)
        rotate_token(request._request)
        return Response(GENERIC_OK)


class MeView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    @extend_schema(
        responses={200: UserResponseSerializer, 401: ErrorResponseSerializer},
        tags=["Autenticación"],
    )
    def get(self, request: Request) -> Response:
        user = _authenticated_user(request)
        if user is None:
            return _authentication_required()
        return Response({"user": AuthUserSerializer(user).data})


class PasswordChangeView(CsrfProtectedAPIView):
    authentication_classes = [SessionAuthentication]

    @extend_schema(
        request=PasswordChangeSerializer,
        responses={
            200: StatusResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
        },
        tags=["Autenticación"],
    )
    def post(self, request: Request) -> Response:
        user = _authenticated_user(request)
        if user is None:
            return _authentication_required()
        serializer = PasswordChangeSerializer(data=request.data)
        if not serializer.is_valid():
            return _drf_error(
                "password_change_failed", "No fue posible cambiar la contraseña.", status=400
            )
        try:
            change_password(
                request=request._request,
                user_id=user.pk,
                current_password=serializer.validated_data["current_password"],
                new_password=serializer.validated_data["new_password"],
            )
        except (InvalidCurrentPassword, ValidationError):
            return _drf_error(
                "password_change_failed", "No fue posible cambiar la contraseña.", status=400
            )
        return Response(GENERIC_OK)


class PasswordResetRequestView(CsrfProtectedAPIView):
    @extend_schema(
        request=EmailRequestSerializer,
        responses={202: StatusResponseSerializer},
        tags=["Autenticación"],
    )
    def post(self, request: Request) -> Response:
        serializer = EmailRequestSerializer(data=request.data)
        email = _canonical_email_from(serializer)
        if email is not None:
            user = User.objects.filter(email=email).first()
            if user is not None and is_password_reset_eligible(user):
                send_password_reset_email(user)
        return Response(GENERIC_ACCEPTED, status=202)


class PasswordResetConfirmView(CsrfProtectedAPIView):
    @extend_schema(
        request=PasswordResetConfirmationSerializer,
        responses={200: StatusResponseSerializer, 400: ErrorResponseSerializer},
        tags=["Autenticación"],
    )
    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmationSerializer(data=request.data)
        if not serializer.is_valid():
            return _drf_error("invalid_or_expired_token", "El enlace no es válido.", status=400)
        try:
            confirm_password_reset(
                uid=serializer.validated_data["uid"],
                token=serializer.validated_data["token"],
                new_password=serializer.validated_data["new_password"],
            )
        except InvalidOrExpiredToken:
            return _drf_error("invalid_or_expired_token", "El enlace no es válido.", status=400)
        except ValidationError:
            return _drf_error("invalid_password", "La contraseña nueva no es válida.", status=400)
        return Response(GENERIC_OK)


class EmailVerificationRequestView(CsrfProtectedAPIView):
    @extend_schema(
        request=EmailRequestSerializer,
        responses={202: StatusResponseSerializer},
        tags=["Autenticación"],
    )
    def post(self, request: Request) -> Response:
        serializer = EmailRequestSerializer(data=request.data)
        email = _canonical_email_from(serializer)
        if email is not None:
            user = User.objects.filter(email=email).first()
            if user is not None and is_email_verification_eligible(user):
                send_email_verification(user)
        return Response(GENERIC_ACCEPTED, status=202)


class EmailVerificationConfirmView(CsrfProtectedAPIView):
    @extend_schema(
        request=TokenConfirmationSerializer,
        responses={200: StatusResponseSerializer, 400: ErrorResponseSerializer},
        tags=["Autenticación"],
    )
    def post(self, request: Request) -> Response:
        serializer = TokenConfirmationSerializer(data=request.data)
        if not serializer.is_valid():
            return _drf_error("invalid_or_expired_token", "El enlace no es válido.", status=400)
        try:
            confirm_email_verification(
                uid=serializer.validated_data["uid"],
                token=serializer.validated_data["token"],
            )
        except InvalidOrExpiredToken:
            return _drf_error("invalid_or_expired_token", "El enlace no es válido.", status=400)
        return Response(GENERIC_OK)
