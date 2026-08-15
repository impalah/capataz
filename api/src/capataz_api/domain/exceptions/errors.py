from dataclasses import dataclass


class DomainError(Exception):
    """A safe, expected domain error suitable for a problem response."""


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class AuthorizationError(DomainError):
    pass


@dataclass(frozen=True)
class FieldError:
    """A single field-level validation failure, with a best-effort source line."""

    path: str
    message: str
    line: int | None = None


class ValidationError(DomainError):
    def __init__(self, message: str, field_errors: tuple[FieldError, ...] = ()) -> None:
        super().__init__(message)
        self.field_errors = field_errors


class ExternalServiceError(DomainError):
    pass


class ConfigurationError(DomainError):
    """Deployment/configuration is invalid (e.g. a required secret is missing or empty).

    Distinct from ExternalServiceError, which represents a transient upstream failure (Portainer
    down, etc.) rather than a misconfigured deployment — see CR-040 in docs/code-review-2026-08.md.
    """
