from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from agentmesh.models import SkillDefinition, SkillSourceScope
from agentmesh.skill_runtime.profiles import load_capability_profile_record
from agentmesh.skill_runtime.trust import ProfileTrustVerifier


def _fixture(
    tmp_path: Path,
    *,
    side_effect: str = "draft",
    required_tools: list[str] | None = None,
    author: str = "@author",
    reviewers: list[str] | None = None,
    review_policy: str = "single",
) -> tuple[SkillDefinition, Path, Path, Path, str]:
    package_root = tmp_path / ("a" * 64) / "agentmesh"
    skill_root = package_root / "builtin_skills" / "trusted-skill"
    profile_root = skill_root / "agents"
    profile_root.mkdir(parents=True)
    skill_path = skill_root / "SKILL.md"
    skill_path.write_text("# Trusted skill\n", encoding="utf-8")
    skill_hash = hashlib.sha256(skill_path.read_bytes()).hexdigest()
    skill = SkillDefinition(
        id="skill_trusted",
        name="trusted-skill",
        title="Trusted skill",
        description="Trusted capability",
        instructions="# Trusted skill",
        source_path=str(skill_path),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash=skill_hash,
        version="1",
    )
    profile_path = profile_root / "agentmesh.yaml"
    profile_path.write_text(
        yaml.safe_dump(
            {
                "skill_id": "auto",
                "skill_version": "1",
                "skill_content_hash": skill_hash,
                "profile_version": "1",
                "display_description": "Trusted capability",
                "primary_stage": "pre_design",
                "lifecycle_tags": ["pre_design"],
                "capability_type": "analysis",
                "input_kinds": ["request"],
                "output_kinds": ["analysis_result"],
                "examples": ["Analyze this request", "Review this request", "Assess this request"],
                "negative_examples": ["Write production data", "Book a flight"],
                "required_capabilities": [],
                "task_types": ["analysis"],
                "archetypes": ["analysis"],
                "required_tools": required_tools or [],
                "required_resources": [],
                "produces_factual_claims": False,
                "report_policy": "default",
                "cost_level": "low",
                "risk_level": "high" if side_effect != "draft" or required_tools else "low",
                "owner": "@owner",
                "review_state": "approved",
                "side_effect": side_effect,
                "planner_eligible": True,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    loaded = load_capability_profile_record(skill)
    release_id = "a" * 64
    commit = "b" * 40
    manifest_path = package_root / "builtin_skills" / "wiki-skill-profile-provenance.json"
    manifest = {
        "schema_version": "wiki-skill-profile-provenance-v2",
        "repository": "yssssssssssss/ai-agentmesh-hackathon",
        "release_commit": commit,
        "reviewed_tree_sha": "c" * 40,
        "profiles": [
            {
                "skill_name": skill.name,
                "profile_path": "builtin_skills/trusted-skill/agents/agentmesh.yaml",
                "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                "profile_version": loaded.profile.profile_version,
                "profile_content_hash": loaded.profile.profile_content_hash,
                "skill_content_hash": skill.content_hash,
                "reviewed_head_sha": "d" * 40,
                "reviewed_tree_sha": "c" * 40,
                "reviewed_blob_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                "author": author,
                "reviewers": reviewers or ["@reviewer"],
                "review_policy": review_policy,
            }
        ],
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    manifest_path.write_bytes(manifest_bytes)
    marker_path = package_root.parent / "verified-build-marker.json"
    marker_path.write_text(
        json.dumps(
            {
                "schema_version": "agentmesh-verified-build-marker-v1",
                "release_id": release_id,
                "wheel_digest": release_id,
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "repository": "yssssssssssss/ai-agentmesh-hackathon",
                "workflow": ".github/workflows/release.yml",
                "ref": "refs/heads/main",
                "commit": commit,
                "attestation_identity": "github://artifact-attestation/test",
                "verified_at": "2026-08-29T00:00:00Z",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return skill, package_root, manifest_path, marker_path, release_id


def test_profile_trust_requires_verified_release_and_reviewed_blob(tmp_path: Path) -> None:
    skill, package_root, manifest_path, marker_path, release_id = _fixture(tmp_path)
    loaded = load_capability_profile_record(skill)
    assert loaded.profile.planner_eligible is True

    verifier = ProfileTrustVerifier.load(
        package_root=package_root,
        manifest_path=manifest_path,
        marker_path=marker_path,
        expected_release_id=release_id,
        expected_repository="yssssssssssss/ai-agentmesh-hackathon",
        expected_profile_count=1,
    )

    assert verifier.available is True
    assert verifier(skill, loaded) is True

    profile_path = Path(skill.source_path).parent / "agents" / "agentmesh.yaml"
    profile_path.write_text(profile_path.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")
    assert verifier(skill, loaded) is False


def test_high_risk_profile_requires_two_independent_reviewers(tmp_path: Path) -> None:
    skill, package_root, manifest_path, marker_path, release_id = _fixture(
        tmp_path,
        side_effect="external_write",
        required_tools=["external_tool"],
        reviewers=["@reviewer"],
        review_policy="double",
    )
    loaded = load_capability_profile_record(skill)
    verifier = ProfileTrustVerifier.load(
        package_root=package_root,
        manifest_path=manifest_path,
        marker_path=marker_path,
        expected_release_id=release_id,
        expected_repository="yssssssssssss/ai-agentmesh-hackathon",
        expected_profile_count=1,
    )
    assert verifier(skill, loaded) is False

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["profiles"][0]["reviewers"] = ["@reviewer", "@second-reviewer"]
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    manifest_path.write_bytes(manifest_bytes)
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    marker_path.write_text(json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8")

    verifier = ProfileTrustVerifier.load(
        package_root=package_root,
        manifest_path=manifest_path,
        marker_path=marker_path,
        expected_release_id=release_id,
        expected_repository="yssssssssssss/ai-agentmesh-hackathon",
        expected_profile_count=1,
    )
    assert verifier(skill, loaded) is True


def test_profile_trust_fails_closed_for_self_review_or_marker_mismatch(tmp_path: Path) -> None:
    skill, package_root, manifest_path, marker_path, release_id = _fixture(
        tmp_path,
        author="@same",
        reviewers=["@same"],
    )
    loaded = load_capability_profile_record(skill)
    self_review = ProfileTrustVerifier.load(
        package_root=package_root,
        manifest_path=manifest_path,
        marker_path=marker_path,
        expected_release_id=release_id,
        expected_repository="yssssssssssss/ai-agentmesh-hackathon",
        expected_profile_count=1,
    )
    wrong_release = ProfileTrustVerifier.load(
        package_root=package_root,
        manifest_path=manifest_path,
        marker_path=marker_path,
        expected_release_id="f" * 64,
        expected_repository="yssssssssssss/ai-agentmesh-hackathon",
        expected_profile_count=1,
    )

    assert self_review.available is True
    assert self_review(skill, loaded) is False
    assert wrong_release.available is False
    assert wrong_release.diagnostic == "skill_profile_trust_unavailable"
