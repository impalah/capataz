import pytest
from auth_middleware.exceptions.invalid_token_exception import InvalidTokenException
from auth_middleware.types.user import User as AuthMiddlewareUser

from capataz_api.adapters.inbound.auth import (
    CognitoIdentityProvider,
    DevMockIdentityProvider,
    OidcIdentityProvider,
)
from capataz_api.domain.exceptions import AuthorizationError


@pytest.mark.asyncio
async def test_dev_mock_requires_user_header() -> None:
    provider = DevMockIdentityProvider()
    with pytest.raises(AuthorizationError, match="X-Dev-User"):
        await provider.authenticate(None, {})


@pytest.mark.asyncio
async def test_dev_mock_parses_comma_separated_groups() -> None:
    provider = DevMockIdentityProvider()
    principal = await provider.authenticate(
        None, {"x-dev-user": "ana", "x-dev-groups": "capataz-admin, capataz-operator"}
    )
    assert principal.subject == "ana"
    assert principal.email == "ana@dev.local"
    assert principal.groups == {"capataz-admin", "capataz-operator"}


@pytest.mark.asyncio
async def test_cognito_provider_requires_bearer_token() -> None:
    provider = CognitoIdentityProvider(
        region="eu-west-1", user_pool_id="eu-west-1_test", audience="client-id"
    )
    with pytest.raises(AuthorizationError, match="Bearer token is required"):
        await provider.authenticate(None, {})


@pytest.mark.asyncio
async def test_cognito_provider_maps_authenticated_user_to_principal(monkeypatch) -> None:
    provider = CognitoIdentityProvider(
        region="eu-west-1", user_pool_id="eu-west-1_test", audience="client-id"
    )

    async def fake_get_credentials(request):
        return object()

    async def fake_create_user_from_token(token):
        return AuthMiddlewareUser(
            id="cognito-sub-123",
            email="operator@example.com",
            groups=["capataz-operator"],
        )

    monkeypatch.setattr(provider._bearer_manager, "get_credentials", fake_get_credentials)
    monkeypatch.setattr(provider._provider, "create_user_from_token", fake_create_user_from_token)

    principal = await provider.authenticate("Bearer some-token", {})

    assert principal.subject == "cognito-sub-123"
    assert principal.email == "operator@example.com"
    assert principal.groups == {"capataz-operator"}


@pytest.mark.asyncio
async def test_cognito_provider_wraps_invalid_token(monkeypatch) -> None:
    provider = CognitoIdentityProvider(
        region="eu-west-1", user_pool_id="eu-west-1_test", audience="client-id"
    )

    async def fake_get_credentials(request):
        raise InvalidTokenException(status_code=401, detail="bad signature")

    monkeypatch.setattr(provider._bearer_manager, "get_credentials", fake_get_credentials)

    with pytest.raises(AuthorizationError, match="Invalid Cognito access token"):
        await provider.authenticate("Bearer some-token", {})


@pytest.mark.asyncio
async def test_cognito_provider_rejects_missing_credentials(monkeypatch) -> None:
    provider = CognitoIdentityProvider(
        region="eu-west-1", user_pool_id="eu-west-1_test", audience="client-id"
    )

    async def fake_get_credentials(request):
        return None

    monkeypatch.setattr(provider._bearer_manager, "get_credentials", fake_get_credentials)

    with pytest.raises(AuthorizationError, match="Bearer token is required"):
        await provider.authenticate("Bearer some-token", {})


@pytest.mark.asyncio
async def test_oidc_provider_requires_bearer_token() -> None:
    provider = OidcIdentityProvider(
        issuer="https://idp.home.arpa/application/o/capataz/", audience="capataz-client"
    )
    with pytest.raises(AuthorizationError, match="Bearer token is required"):
        await provider.authenticate(None, {})


@pytest.mark.asyncio
async def test_oidc_provider_maps_authenticated_user_to_principal(monkeypatch) -> None:
    provider = OidcIdentityProvider(
        issuer="https://idp.home.arpa/application/o/capataz/", audience="capataz-client"
    )

    async def fake_get_credentials(request):
        return object()

    async def fake_create_user_from_token(token):
        return AuthMiddlewareUser(
            id="oidc-sub-123",
            email="operator@example.com",
            groups=["capataz-operator"],
        )

    monkeypatch.setattr(provider._bearer_manager, "get_credentials", fake_get_credentials)
    monkeypatch.setattr(provider._provider, "create_user_from_token", fake_create_user_from_token)

    principal = await provider.authenticate("Bearer some-token", {})

    assert principal.subject == "oidc-sub-123"
    assert principal.email == "operator@example.com"
    assert principal.groups == {"capataz-operator"}


@pytest.mark.asyncio
async def test_oidc_provider_wraps_invalid_token(monkeypatch) -> None:
    provider = OidcIdentityProvider(
        issuer="https://idp.home.arpa/application/o/capataz/", audience="capataz-client"
    )

    async def fake_get_credentials(request):
        raise InvalidTokenException(status_code=401, detail="bad signature")

    monkeypatch.setattr(provider._bearer_manager, "get_credentials", fake_get_credentials)

    with pytest.raises(AuthorizationError, match="Invalid OIDC access token"):
        await provider.authenticate("Bearer some-token", {})


@pytest.mark.asyncio
async def test_oidc_provider_rejects_missing_credentials(monkeypatch) -> None:
    provider = OidcIdentityProvider(
        issuer="https://idp.home.arpa/application/o/capataz/", audience="capataz-client"
    )

    async def fake_get_credentials(request):
        return None

    monkeypatch.setattr(provider._bearer_manager, "get_credentials", fake_get_credentials)

    with pytest.raises(AuthorizationError, match="Bearer token is required"):
        await provider.authenticate("Bearer some-token", {})
