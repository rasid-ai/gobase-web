from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Role


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["username"],
            password=attrs["password"],
        )
        # One message for both unknown user and wrong password: the login form
        # must not reveal which usernames exist.
        if user is None or not user.is_active:
            raise serializers.ValidationError("Incorrect username or password.")
        attrs["user"] = user
        return attrs


class AccessTokenSerializer(serializers.Serializer):
    """Login and refresh both return only the access token.

    The refresh token is never in a response body — it is set as an httpOnly
    cookie by the view.
    """

    access = serializers.CharField(read_only=True)


class MeSerializer(serializers.Serializer):
    username = serializers.CharField(read_only=True)
    role = serializers.ChoiceField(choices=Role.choices, read_only=True)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_current_password(self, value: str) -> str:
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value: str) -> str:
        try:
            validate_password(value, self.context["request"].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user
