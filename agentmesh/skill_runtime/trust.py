from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentmesh.canonical_json import strict_json_loads
from agentmesh.models import SkillDefinition
from agentmesh.skill_runtime.profiles import LoadedCapabilityProfile, profile_path

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
_MAX_TRUST_FILE_BYTES = 512 * 1024


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProfileReviewProofV2(_StrictFrozenModel):
    skill_name: str = Field(min_length=1, max_length=64)
    profile_path: str = Field(min_length=1, max_length=500)
    profile_sha256: str = Field(pattern=_SHA256_PATTERN)
    profile_version: str = Field(min_length=1, max_length=40)
    profile_content_hash: str = Field(pattern=_SHA256_PATTERN)
    skill_content_hash: str = Field(pattern=_SHA256_PATTERN)
    reviewed_head_sha: str = Field(pattern=_GIT_SHA_PATTERN)
    reviewed_tree_sha: str = Field(pattern=_GIT_SHA_PATTERN)
    reviewed_blob_sha256: str = Field(pattern=_SHA256_PATTERN)
    author: str = Field(min_length=1, max_length=120)
    reviewers: tuple[str, ...] = Field(min_length=1, max_length=2)
    review_policy: Literal["single", "double"]


class SkillProfileProvenanceV2(_StrictFrozenModel):
    schema_version: Literal["wiki-skill-profile-provenance-v2"]
    repository: str = Field(min_length=1, max_length=240)
    release_commit: str = Field(pattern=_GIT_SHA_PATTERN)
    reviewed_tree_sha: str = Field(pattern=_GIT_SHA_PATTERN)
    profiles: tuple[ProfileReviewProofV2, ...] = Field(min_length=1, max_length=1000)


class VerifiedBuildMarkerV1(_StrictFrozenModel):
    schema_version: Literal["agentmesh-verified-build-marker-v1"]
    release_id: str = Field(pattern=_SHA256_PATTERN)
    wheel_digest: str = Field(pattern=_SHA256_PATTERN)
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    repository: str = Field(min_length=1, max_length=240)
    workflow: str = Field(min_length=1, max_length=240)
    ref: str = Field(min_length=1, max_length=240)
    commit: str = Field(pattern=_GIT_SHA_PATTERN)
    attestation_identity: str = Field(min_length=1, max_length=500)
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class ProfileTrustVerifier:
    package_root: Path
    marker: VerifiedBuildMarkerV1 | None
    manifest: SkillProfileProvenanceV2 | None
    entries: dict[str, ProfileReviewProofV2]
    diagnostic: str | None

    @property
    def available(self) -> bool:
        return self.marker is not None and self.manifest is not None and self.diagnostic is None

    def __call__(self, skill: SkillDefinition, loaded: LoadedCapabilityProfile) -> bool:
        if not self.available or loaded.review_state != "approved" or not loaded.declared_planner_eligible:
            return False
        entry = self.entries.get(skill.name)
        if entry is None:
            return False
        profile = loaded.profile
        enhanced_review = bool(
            profile.required_tools
            or profile.risk_level == "high"
            or profile.side_effect.value in {"local_write", "external_write"}
        )
        required_reviewers = 2 if enhanced_review else 1
        reviewers = tuple(dict.fromkeys(entry.reviewers))
        if (
            entry.review_policy != ("double" if enhanced_review else "single")
            or len(reviewers) < required_reviewers
            or any(not reviewer.strip() for reviewer in reviewers)
            or entry.author in reviewers
            or entry.reviewed_blob_sha256 != entry.profile_sha256
            or entry.reviewed_tree_sha != self.manifest.reviewed_tree_sha
            or entry.profile_version != profile.profile_version
            or entry.profile_content_hash != profile.profile_content_hash
            or entry.skill_content_hash != skill.content_hash
        ):
            return False
        try:
            relative = PurePosixPath(entry.profile_path)
            if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
                return False
            candidate_path = self.package_root.joinpath(*relative.parts)
            current = self.package_root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    return False
            expected_path = candidate_path.resolve(strict=True)
            package_root = self.package_root.resolve(strict=True)
            actual_path = profile_path(skill).resolve(strict=True)
            if (
                not expected_path.is_relative_to(package_root)
                or expected_path != actual_path
                or not expected_path.is_file()
            ):
                return False
            return hashlib.sha256(expected_path.read_bytes()).hexdigest() == entry.profile_sha256
        except OSError:
            return False

    @classmethod
    def load(
        cls,
        *,
        package_root: Path,
        manifest_path: Path,
        marker_path: Path,
        expected_release_id: str,
        expected_repository: str,
        expected_profile_count: int = 84,
    ) -> ProfileTrustVerifier:
        try:
            manifest_bytes = _read_bounded(manifest_path)
            marker_bytes = _read_bounded(marker_path)
            manifest = SkillProfileProvenanceV2.model_validate(strict_json_loads(manifest_bytes))
            marker = VerifiedBuildMarkerV1.model_validate(strict_json_loads(marker_bytes))
        except (OSError, UnicodeError, ValueError, ValidationError):
            return cls(package_root, None, None, {}, "skill_profile_trust_unavailable")
        if (
            marker.release_id != expected_release_id
            or marker.wheel_digest != expected_release_id
            or marker.manifest_sha256 != hashlib.sha256(manifest_bytes).hexdigest()
            or marker.repository != expected_repository
            or manifest.repository != expected_repository
            or marker.commit != manifest.release_commit
            or marker.ref != "refs/heads/main"
            or not marker.workflow
            or not marker.attestation_identity
        ):
            return cls(package_root, None, None, {}, "skill_profile_trust_unavailable")
        entries: dict[str, ProfileReviewProofV2] = {}
        for entry in manifest.profiles:
            if entry.skill_name in entries:
                return cls(package_root, None, None, {}, "skill_profile_trust_unavailable")
            entries[entry.skill_name] = entry
        if len(entries) != expected_profile_count:
            return cls(package_root, None, None, {}, "skill_profile_trust_unavailable")
        return cls(package_root, marker, manifest, entries, None)


def _read_bounded(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("trust_file_invalid")
    data = path.read_bytes()
    if len(data) > _MAX_TRUST_FILE_BYTES:
        raise ValueError("trust_file_too_large")
    return data


@lru_cache(maxsize=1)
def runtime_profile_trust_verifier() -> ProfileTrustVerifier:
    package_root = Path(__file__).resolve().parents[1]
    release_root = package_root.parent
    release_id = release_root.name if re.fullmatch(_SHA256_PATTERN, release_root.name) else ""
    return ProfileTrustVerifier.load(
        package_root=package_root,
        manifest_path=package_root / "builtin_skills" / "wiki-skill-provenance.json",
        marker_path=release_root / "verified-build-marker.json",
        expected_release_id=release_id,
        expected_repository="yssssssssssss/ai-agentmesh-hackathon",
    )
