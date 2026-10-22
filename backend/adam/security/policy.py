from dataclasses import dataclass
from typing import Literal

from adam.core.contracts import Contract
from adam.security.request import REMOTE_DEVICE

Mode = Literal["owner", "guest", "demo"]


@dataclass(frozen=True)
class Principal:
    person_id: str = "owner"
    mode: Mode = "owner"
    authenticated: bool = True
    trusted_device: bool = True
    elevated: bool = False
    profile_id: str = "local"


class ResourcePolicy(Contract):
    replication_policy: str = "local_only"
    sensitivity: str
    allowed_audiences: list[str]
    subjects: list[str]
    disclosure_owner: str
    source_actor: str
    profile: Mode = "owner"


class PolicyDecision(Contract):
    allowed: bool
    reason: str


def decide(principal: Principal, resource: ResourcePolicy) -> PolicyDecision:
    reason = "POLICY.ALLOWED"
    if REMOTE_DEVICE.get() and resource.replication_policy not in {
        "TRUSTED_DEVICES",
        "OWNER_DEVICES",
        "ALL_APPROVED",
    }:
        reason = "POLICY.CORE_ONLY"
    elif resource.sensitivity in {"SECRET", "SYSTEM_SECRET", "NEVER_LLM", "NEVER_LOG"}:
        reason = "POLICY.SECRET_NEVER_LLM"
    elif resource.sensitivity not in {"PUBLIC", "PERSONAL", "PRIVATE", "CONFIDENTIAL"}:
        reason = "POLICY.UNKNOWN_SENSITIVITY"
    elif principal.mode != resource.profile:
        reason = "POLICY.PROFILE_MISMATCH"
    elif principal.person_id not in resource.allowed_audiences:
        reason = "POLICY.AUDIENCE_DENIED"
    elif resource.disclosure_owner != principal.person_id and resource.sensitivity != "PUBLIC":
        reason = "POLICY.DISCLOSURE_OWNER_DENIED"
    elif (
        any(subject != principal.person_id for subject in resource.subjects)
        and resource.sensitivity != "PUBLIC"
    ):
        reason = "POLICY.SUBJECT_RESTRICTED"
    elif principal.mode == "owner" and not (principal.authenticated and principal.trusted_device):
        reason = "POLICY.AUTHENTICATION_REQUIRED"
    elif principal.mode == "guest" and resource.sensitivity != "PUBLIC":
        reason = "POLICY.GUEST_PUBLIC_ONLY"
    return PolicyDecision(allowed=reason == "POLICY.ALLOWED", reason=reason)
