from __future__ import annotations

from typing import Any

from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from cryptovira.apps.accounts.api.serializers import (
    LogoutSerializer,
    RegisterSerializer,
    UserSerializer,
)
from cryptovira.apps.accounts.api.throttles import LoginRateThrottle, RegistrationRateThrottle
from cryptovira.apps.accounts.models import User


class RegisterView(generics.CreateAPIView[User]):
    """POST /api/v1/accounts/register/ — create an account and log the caller straight in.

    Returning access/refresh tokens from registration (rather than making the client immediately
    call the login endpoint with the password it just submitted) saves a redundant round trip and
    a redundant password transmission. The trade-off: registration and login now both need to be
    covered by security review as "produces a session", not just the login endpoint.
    """

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [RegistrationRateThrottle]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    """POST /api/v1/accounts/token/ — obtain an access/refresh pair.

    All the actual logic (checking the password, building the tokens) lives in simplejwt's
    `TokenObtainPairView`; the only reason to subclass at all is to attach the scoped throttle —
    `DEFAULT_THROTTLE_RATES["login"]` in settings.py, distinct from the general anon rate, since
    this is the endpoint a credential-stuffing script would actually hammer.
    """

    throttle_classes = [LoginRateThrottle]


class LogoutView(generics.GenericAPIView[Any]):
    # Parameterized [Any], not [User]: this view never looks up a model instance (no
    # get_object/get_queryset use) — it just validates a token payload and calls .blacklist().
    """POST /api/v1/accounts/logout/ — blacklist the refresh token so it can't be used again.

    This does not invalidate the caller's *current* access token (see the comment on
    LogoutSerializer for why that's not possible with stateless JWTs) — only future refreshes.
    A client that wants an immediate hard logout should also discard the access token locally;
    the server-side blacklist is what stops that refresh token being replayed later.
    """

    serializer_class = LogoutSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            token.blacklist()
        except TokenError as exc:
            # Already-blacklisted or malformed token: treat it the same as "already logged out"
            # rather than surfacing a 500 — the caller's desired end state (no valid session) is
            # already true.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(generics.RetrieveUpdateAPIView[User]):
    """GET/PATCH /api/v1/accounts/me/ — the caller's own profile, no id in the URL.

    `get_object` is overridden instead of relying on the default pk-lookup-from-URL behaviour:
    there is deliberately no `/accounts/users/<id>/` endpoint yet (that's a "look up any user"
    capability, a different permission problem), so this view can *only* ever return the
    authenticated caller's own record — the URL carries no id for a reason.
    """

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self) -> User:
        user = self.request.user
        # IsAuthenticated already excludes AnonymousUser; this narrows the type for mypy.
        assert isinstance(user, User)
        return user
