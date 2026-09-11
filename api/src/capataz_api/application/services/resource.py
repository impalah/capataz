"""Application-layer use cases for resources: encrypted files/secrets uploaded to Capataz.

The plaintext only ever exists transiently inside these methods: it is encrypted before it
reaches the repository, and neither responses nor audit records ever carry it.
"""

from pydantic import ValidationError as PydanticValidationError

from capataz_api.application.policies import build_audit_event, describe_error
from capataz_api.application.ports import ResourceCipher, ServiceRepository
from capataz_api.domain.entities import Principal, Resource
from capataz_api.domain.exceptions import ConflictError, NotFoundError, ValidationError
from capataz_api.domain.specs import MAX_RESOURCE_BYTES, ResourceSpec, connector_resource_refs


class ResourceApplicationService:
    def __init__(self, repo: ServiceRepository, cipher: ResourceCipher) -> None:
        self._repo = repo
        self._cipher = cipher

    async def list_resources(self) -> list[Resource]:
        return await self._repo.list_resources()

    async def get_resource(self, resource_id: str) -> Resource:
        resource = await self._repo.get_resource(resource_id)
        if resource is None:
            raise NotFoundError("Resource not found")
        return resource

    async def create_resource(
        self,
        *,
        resource_id: str,
        resource_type: str,
        description: str | None,
        content: bytes,
        principal: Principal,
        request_id: str | None,
    ) -> Resource:
        meta = self._meta(resource_id, resource_type, description)
        self._check_content(content)
        if await self._repo.get_resource(meta.id):
            raise ConflictError("Resource id already exists")
        result = await self._repo.upsert_resource(self._encrypted(meta.id, meta, content))
        await self._repo.append_audit(
            build_audit_event(
                principal,
                "resource.create",
                meta.id,
                request_id,
                metadata={"type": meta.type.value, "size": len(content)},
            )
        )
        return result

    async def replace_resource(
        self,
        resource_id: str,
        *,
        content: bytes,
        description: str | None,
        principal: Principal,
        request_id: str | None,
    ) -> Resource:
        existing = await self.get_resource(resource_id)
        meta = self._meta(
            existing.id,
            existing.type.value,
            description if description is not None else existing.description,
        )
        self._check_content(content)
        result = await self._repo.upsert_resource(self._encrypted(existing.id, meta, content))
        await self._repo.append_audit(
            build_audit_event(
                principal,
                "resource.update",
                resource_id,
                request_id,
                metadata={"size": len(content)},
            )
        )
        return result

    async def delete_resource(
        self, resource_id: str, *, principal: Principal, request_id: str | None
    ) -> None:
        await self.get_resource(resource_id)
        users = [
            f"connector {connector.id} ({field_name})"
            for connector in await self._repo.list_connectors()
            for field_name, (referenced, _type) in connector_resource_refs(connector.spec).items()
            if referenced == resource_id
        ]
        if users:
            raise ConflictError(f"Resource {resource_id!r} is still used by: {', '.join(users)}")
        await self._repo.delete_resource(resource_id)
        await self._repo.append_audit(
            build_audit_event(principal, "resource.delete", resource_id, request_id)
        )

    def _encrypted(self, resource_id: str, meta: ResourceSpec, content: bytes) -> Resource:
        return Resource(
            id=resource_id,
            type=meta.type,
            ciphertext=self._cipher.encrypt(content),
            fingerprint=self._cipher.fingerprint(content),
            size=len(content),
            description=meta.description,
            source={"upload": True},
        )

    @staticmethod
    def _meta(resource_id: str, resource_type: str, description: str | None) -> ResourceSpec:
        try:
            return ResourceSpec.model_validate(
                {"id": resource_id, "type": resource_type, "description": description}
            )
        except PydanticValidationError as exc:
            raise ValidationError(f"Invalid resource: {describe_error(exc)}") from None

    @staticmethod
    def _check_content(content: bytes) -> None:
        if not content:
            raise ValidationError("Resource content is empty")
        if len(content) > MAX_RESOURCE_BYTES:
            raise ValidationError(f"Resource content exceeds {MAX_RESOURCE_BYTES} bytes")
