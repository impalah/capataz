from capataz_api.domain.entities import Principal
from capataz_api.domain.exceptions import AuthorizationError
from capataz_api.domain.value_objects import RiskLevel

ROLE_VIEWER = "capataz-viewer"
ROLE_OPERATOR = "capataz-operator"
ROLE_ADMIN = "capataz-admin"


def has_role(principal: Principal, required: str) -> bool:
    groups = principal.groups
    if required == ROLE_VIEWER:
        return bool(groups & {ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN})
    if required == ROLE_OPERATOR:
        return bool(groups & {ROLE_OPERATOR, ROLE_ADMIN})
    return ROLE_ADMIN in groups


def require_role(principal: Principal, required: str) -> None:
    if not has_role(principal, required):
        raise AuthorizationError("Insufficient role for this operation")


def authorize_action(
    principal: Principal, risk: RiskLevel, confirmation: bool, reason: str | None
) -> None:
    if risk == RiskLevel.READ:
        require_role(principal, ROLE_OPERATOR)
    elif risk == RiskLevel.OPERATE:
        require_role(principal, ROLE_OPERATOR)
    else:
        require_role(principal, ROLE_ADMIN)
        if not confirmation or not reason or not reason.strip():
            raise AuthorizationError("Critical action requires explicit confirmation and a reason")
