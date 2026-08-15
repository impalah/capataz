"""Identity adapters.

Both Cognito and generic OIDC authentication delegate to `auth-middleware`'s
(https://github.com/impalah/auth-middleware) `OidcProvider`: as of auth-middleware
0.6.0, there is no dedicated Cognito provider — a Cognito User Pool is just another
standards-compliant OIDC issuer (`https://cognito-idp.{region}.amazonaws.com/{user_pool_id}`).
`CognitoIdentityProvider` points `OidcProvider` at that issuer and passes it a
`CognitoGroupsProvider`, because Cognito's *access* tokens don't carry a `cognito:groups`
claim the way ID tokens do — `CognitoGroupsProvider` reads `cognito:groups` when present
and falls back to a single-scope heuristic otherwise. `OidcIdentityProvider` (any other
standards-compliant issuer: Authentik, Keycloak, Auth0, Okta, ...) instead discovers the
JWKS from the issuer's `.well-known/openid-configuration` document and reads groups from
a configured `groups_claim` directly off the access token. Both providers stay behind
this module's `IdentityProvider` implementations, so the rest of the application never
imports auth-middleware directly. The dev_mock mode is deliberately accepted only in
CAPATAZ_ENV=development.
"""

import asyncio

from auth_middleware.exceptions.invalid_token_exception import InvalidTokenException
from auth_middleware.jwt_bearer_manager import JWTBearerManager
from auth_middleware.providers.aws.cognito_groups_provider import CognitoGroupsProvider
from auth_middleware.providers.oidc.oidc_provider import OidcProvider
from auth_middleware.providers.oidc.oidc_provider_settings import OidcProviderSettings
from starlette.requests import Request

from capataz_api.application.ports import IdentityProvider
from capataz_api.domain.entities import Principal
from capataz_api.domain.exceptions import AuthorizationError


class DevMockIdentityProvider(IdentityProvider):
    async def authenticate(self, authorization: str | None, headers: dict[str, str]) -> Principal:
        # `authorization` is part of the IdentityProvider port signature (deps.py calls every
        # provider uniformly) but the dev mock only ever reads the X-Dev-* headers; the explicit
        # await is a real, if trivial, event-loop yield so this stays a genuine coroutine like
        # every other IdentityProvider implementation, rather than a function that merely looks
        # like one.
        await asyncio.sleep(0)
        user = headers.get("x-dev-user")
        groups = headers.get("x-dev-groups", "")
        if not user:
            raise AuthorizationError("X-Dev-User is required in development mock mode")
        return Principal(
            subject=user,
            email=f"{user}@dev.local",
            groups={item.strip() for item in groups.split(",") if item.strip()},
        )


_BEARER_TOKEN_REQUIRED = "Bearer token is required"


class _BearerJwtIdentityProvider(IdentityProvider):
    """Shared authenticate() flow for JWTProvider-backed adapters."""

    _provider: OidcProvider
    _bearer_manager: JWTBearerManager
    _invalid_token_message: str

    async def authenticate(self, authorization: str | None, headers: dict[str, str]) -> Principal:
        if not authorization:
            raise AuthorizationError(_BEARER_TOKEN_REQUIRED)
        request = Request({"type": "http", "headers": [(b"authorization", authorization.encode())]})
        try:
            credentials = await self._bearer_manager.get_credentials(request)
        except InvalidTokenException as exc:
            raise AuthorizationError(self._invalid_token_message) from exc
        if credentials is None:
            raise AuthorizationError(_BEARER_TOKEN_REQUIRED)
        user = await self._provider.create_user_from_token(credentials)
        return Principal(
            subject=user.id, email=user.email, name=user.name, groups=set(await user.groups)
        )


class CognitoIdentityProvider(_BearerJwtIdentityProvider):
    _invalid_token_message = "Invalid Cognito access token"

    def __init__(self, region: str, user_pool_id: str, audience: str) -> None:
        settings = OidcProviderSettings(
            issuer=f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}",
            audience=audience or None,
            # Cognito never sets 'preferred_username' (this library's default username_claim).
            # Without a fallback, auth-middleware's create_user_from_token() falls all the way
            # back to the app's client_id as the display name, which is worse than useless.
            # 'username' is the Cognito access-token claim; 'cognito:username' is its ID-token
            # counterpart, kept here in case a caller ever passes an ID token instead.
            username_claim_fallbacks=["username", "cognito:username"],
        )
        provider = OidcProvider(settings=settings, groups_provider=CognitoGroupsProvider())
        self._provider = provider
        self._bearer_manager = JWTBearerManager(auth_provider=provider, auto_error=False)


class OidcIdentityProvider(_BearerJwtIdentityProvider):
    _invalid_token_message = "Invalid OIDC access token"

    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_uri: str | None = None,
        groups_claim: str = "groups",
    ) -> None:
        settings = OidcProviderSettings(
            issuer=issuer,
            audience=audience or None,
            jwks_uri=jwks_uri or None,
            groups_claim=groups_claim or None,
        )
        provider = OidcProvider(settings=settings)
        self._provider = provider
        self._bearer_manager = JWTBearerManager(auth_provider=provider, auto_error=False)
