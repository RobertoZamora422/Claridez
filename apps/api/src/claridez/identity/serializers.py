"""Contratos JSON de autenticación."""

from rest_framework import serializers

from .models import User


class AuthUserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ("id", "email", "display_name", "status", "email_verified_at")
        read_only_fields = fields


class UserResponseSerializer(serializers.Serializer[dict[str, object]]):
    user = AuthUserSerializer(read_only=True)


class StatusResponseSerializer(serializers.Serializer[dict[str, str]]):
    status = serializers.CharField(read_only=True)


class CsrfResponseSerializer(serializers.Serializer[dict[str, str]]):
    csrf_token = serializers.CharField(read_only=True)


class ErrorDetailSerializer(serializers.Serializer[dict[str, str]]):
    code = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)


class ErrorResponseSerializer(serializers.Serializer[dict[str, object]]):
    error = ErrorDetailSerializer(read_only=True)


class LoginSerializer(serializers.Serializer[dict[str, str]]):
    email = serializers.CharField(max_length=254, trim_whitespace=False)
    password = serializers.CharField(max_length=512, trim_whitespace=False, write_only=True)


class PasswordChangeSerializer(serializers.Serializer[dict[str, str]]):
    current_password = serializers.CharField(max_length=512, trim_whitespace=False, write_only=True)
    new_password = serializers.CharField(max_length=512, trim_whitespace=False, write_only=True)
    new_password_confirmation = serializers.CharField(
        max_length=512,
        trim_whitespace=False,
        write_only=True,
    )

    def validate(self, attrs: dict[str, str]) -> dict[str, str]:
        if attrs["new_password"] != attrs["new_password_confirmation"]:
            raise serializers.ValidationError("Las contraseñas no coinciden.")
        return attrs


class EmailRequestSerializer(serializers.Serializer[dict[str, str]]):
    email = serializers.CharField(max_length=254, trim_whitespace=False)


class TokenConfirmationSerializer(serializers.Serializer[dict[str, str]]):
    uid = serializers.CharField(max_length=128)
    token = serializers.CharField(max_length=256)


class PasswordResetConfirmationSerializer(TokenConfirmationSerializer):
    new_password = serializers.CharField(max_length=512, trim_whitespace=False, write_only=True)
    new_password_confirmation = serializers.CharField(
        max_length=512,
        trim_whitespace=False,
        write_only=True,
    )

    def validate(self, attrs: dict[str, str]) -> dict[str, str]:
        if attrs["new_password"] != attrs["new_password_confirmation"]:
            raise serializers.ValidationError("Las contraseñas no coinciden.")
        return attrs
