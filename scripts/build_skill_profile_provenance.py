#!/usr/bin/env python3
"""Build Profile provenance v2 from externally verified PR review evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentmesh.canonical_json import strict_json_loads
from agentmesh.models import SkillSourceScope
from agentmesh.skill_runtime.parser import parse_skill_file
from agentmesh.skill_runtime.profiles import load_capability_profile_record, profile_path
from agentmesh.skill_runtime.trust import ProfileReviewProofV2, SkillProfileProvenanceV2

_GITHUB_HANDLE = re.compile(r"^@[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?$")


class _ReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_name: str = Field(min_length=1, max_length=64)
    author: str = Field(min_length=1, max_length=120)
    reviewers: tuple[str, ...] = Field(min_length=1, max_length=2)
    reviewed_head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    reviewed_tree_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    reviewed_blob_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _ReviewEvidenceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^profile-review-evidence-v1$")
    repository: str = Field(min_length=1, max_length=240)
    release_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    reviewed_tree_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    profiles: tuple[_ReviewEvidence, ...] = Field(min_length=1, max_length=1000)


class ProvenanceBuildError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _codeowner_handles(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ProvenanceBuildError("codeowners_unavailable") from error
    handles = {
        token
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
        for token in line.split()[1:]
        if _GITHUB_HANDLE.fullmatch(token)
    }
    if not handles:
        raise ProvenanceBuildError("codeowners_empty")
    return handles


def build_profile_provenance(
    *,
    builtin_root: Path,
    evidence_path: Path,
    codeowners_path: Path,
    expected_profile_count: int,
) -> SkillProfileProvenanceV2:
    try:
        evidence = _ReviewEvidenceDocument.model_validate(
            strict_json_loads(evidence_path.read_bytes())
        )
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise ProvenanceBuildError("review_evidence_invalid") from error
    evidence_by_name: dict[str, _ReviewEvidence] = {}
    for item in evidence.profiles:
        if item.skill_name in evidence_by_name:
            raise ProvenanceBuildError(f"review_evidence_duplicate:{item.skill_name}")
        evidence_by_name[item.skill_name] = item
    codeowners = _codeowner_handles(codeowners_path)
    proofs: list[ProfileReviewProofV2] = []
    skills = []
    for skill_path in sorted(builtin_root.glob("*/SKILL.md")):
        parsed = parse_skill_file(skill_path, source_scope=SkillSourceScope.BUILTIN)
        if parsed.skill is None:
            raise ProvenanceBuildError(f"skill_invalid:{skill_path.parent.name}")
        skills.append(parsed.skill)
    if len(skills) != expected_profile_count or len({skill.name for skill in skills}) != expected_profile_count:
        raise ProvenanceBuildError("skill_inventory_drift")
    if set(evidence_by_name) != {skill.name for skill in skills}:
        raise ProvenanceBuildError("review_evidence_coverage_mismatch")

    for skill in skills:
        loaded = load_capability_profile_record(skill)
        profile = loaded.profile
        if loaded.review_state != "approved" or not loaded.declared_planner_eligible:
            raise ProvenanceBuildError(f"profile_not_approved:{skill.name}")
        item = evidence_by_name[skill.name]
        reviewers = tuple(dict.fromkeys(item.reviewers))
        enhanced = bool(
            profile.required_tools
            or profile.risk_level == "high"
            or profile.side_effect.value in {"local_write", "external_write"}
        )
        required_reviewers = 2 if enhanced else 1
        if (
            item.reviewed_tree_sha != evidence.reviewed_tree_sha
            or item.author in reviewers
            or len(reviewers) < required_reviewers
            or any(reviewer not in codeowners for reviewer in reviewers)
        ):
            raise ProvenanceBuildError(f"profile_review_invalid:{skill.name}")
        sidecar = profile_path(skill)
        profile_sha = _sha256(sidecar)
        if item.reviewed_blob_sha256 != profile_sha:
            raise ProvenanceBuildError(f"reviewed_profile_blob_mismatch:{skill.name}")
        proofs.append(
            ProfileReviewProofV2(
                skill_name=skill.name,
                profile_path=sidecar.relative_to(builtin_root.parent).as_posix(),
                profile_sha256=profile_sha,
                profile_version=profile.profile_version,
                profile_content_hash=profile.profile_content_hash,
                skill_content_hash=skill.content_hash,
                reviewed_head_sha=item.reviewed_head_sha,
                reviewed_tree_sha=item.reviewed_tree_sha,
                reviewed_blob_sha256=item.reviewed_blob_sha256,
                author=item.author,
                reviewers=reviewers,
                review_policy="double" if enhanced else "single",
            )
        )
    return SkillProfileProvenanceV2(
        schema_version="wiki-skill-profile-provenance-v2",
        repository=evidence.repository,
        release_commit=evidence.release_commit,
        reviewed_tree_sha=evidence.reviewed_tree_sha,
        profiles=tuple(proofs),
    )


def _json_bytes(value: BaseModel) -> bytes:
    return (
        json.dumps(value.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builtin-root", type=Path, required=True)
    parser.add_argument("--review-evidence", type=Path, required=True)
    parser.add_argument("--codeowners", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-profile-count", type=int, default=84)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    provenance = build_profile_provenance(
        builtin_root=args.builtin_root.resolve(),
        evidence_path=args.review_evidence.resolve(),
        codeowners_path=args.codeowners.resolve(),
        expected_profile_count=args.expected_profile_count,
    )
    content = _json_bytes(provenance)
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != content:
            print("skill Profile provenance is stale")
            return 1
        print("skill Profile provenance is current")
        return 0
    if args.output.exists() and args.output.read_bytes() != content:
        raise ProvenanceBuildError("profile_provenance_overwrite_forbidden")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists():
        args.output.write_bytes(content)
    print(f"built {len(provenance.profiles)} Profile review proofs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
