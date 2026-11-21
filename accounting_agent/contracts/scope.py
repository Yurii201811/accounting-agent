"""Authenticated tenant and legal-entity scope contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._wire import (
    parse_json_object,
    parse_enum,
    require_identifier,
    require_wire_array,
    require_wire_object,
    require_wire_version,
)


class AuthenticationStrength(str, Enum):
    SINGLE_FACTOR = "single_factor"
    MULTI_FACTOR = "multi_factor"
    PHISHING_RESISTANT = "phishing_resistant"
    HIGH_ASSURANCE = "high_assurance"
    SERVICE_CREDENTIAL = "service_credential"


class MembershipRole(str, Enum):
    TENANT_ADMIN = "tenant_admin"
    PREPARER = "preparer"
    REVIEWER = "reviewer"
    CONTROLLER = "controller"
    AUDITOR = "auditor"
    CONNECTOR_ADMIN = "connector_admin"
    ARCHIVE_ADMIN = "archive_admin"
    SECURITY_ADMIN = "security_admin"
    SERVICE_WORKER = "service_worker"


_TENANT_CONTEXT_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "actor_id",
        "roles",
        "authentication_strength",
        "request_id",
    }
)


@dataclass(frozen=True)
class TenantContext:
    """Exact authenticated scope; callers cannot substitute request-body authority."""

    tenant_id: str
    client_id: str
    legal_entity_id: str
    actor_id: str
    roles: tuple[MembershipRole, ...]
    authentication_strength: AuthenticationStrength
    request_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "client_id",
            "legal_entity_id",
            "actor_id",
            "request_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        if not isinstance(self.roles, tuple):
            raise ValueError("roles must be a tuple")
        if not self.roles:
            raise ValueError("roles must not be empty")
        parsed_roles: list[MembershipRole] = []
        for role in self.roles:
            try:
                parsed_roles.append(MembershipRole(role))
            except (TypeError, ValueError) as error:
                raise ValueError("unknown membership role") from error
        if len(set(parsed_roles)) != len(parsed_roles):
            raise ValueError("roles must not contain duplicates")
        if MembershipRole.SERVICE_WORKER in parsed_roles and len(parsed_roles) != 1:
            raise ValueError("service_worker role must be exclusive")
        authentication_strength = parse_enum(
            self.authentication_strength,
            AuthenticationStrength,
            "authentication_strength",
        )
        if (
            MembershipRole.SERVICE_WORKER in parsed_roles
            and authentication_strength is not AuthenticationStrength.SERVICE_CREDENTIAL
        ):
            raise ValueError("service_worker requires service_credential authentication")
        if (
            authentication_strength is AuthenticationStrength.SERVICE_CREDENTIAL
            and MembershipRole.SERVICE_WORKER not in parsed_roles
        ):
            raise ValueError("service_credential requires service_worker role")
        object.__setattr__(self, "roles", tuple(sorted(parsed_roles, key=lambda role: role.value)))
        object.__setattr__(self, "authentication_strength", authentication_strength)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "actor_id": self.actor_id,
            "roles": [role.value for role in self.roles],
            "authentication_strength": self.authentication_strength.value,
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> TenantContext:
        payload = require_wire_object(
            value,
            contract_name="TenantContext",
            expected_fields=_TENANT_CONTEXT_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        roles = require_wire_array(payload["roles"], "roles")
        return cls(
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            actor_id=payload["actor_id"],
            roles=tuple(roles),
            authentication_strength=payload["authentication_strength"],
            request_id=payload["request_id"],
        )

    @classmethod
    def from_json(cls, value: object) -> TenantContext:
        return cls.from_dict(parse_json_object(value, "TenantContext"))
