from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from agentmesh.models import SkillDefinition, SkillSourceScope
from scripts.build_skill_profile_provenance import ProvenanceBuildError, build_profile_provenance


def _profile_fixture(tmp_path: Path, *, review_state: str = "approved") -> tuple[Path, Path, Path]:
    builtin_root = tmp_path / "agentmesh" / "builtin_skills"
    skill_root = builtin_root / "reviewed-skill"
    profile_root = skill_root / "agents"
    profile_root.mkdir(parents=True)
    skill_path = skill_root / "SKILL.md"
    skill_path.write_text(
        """---
name: reviewed-skill
description: Reviewed capability
metadata:
  version: "1"
---
# Reviewed Skill
""",
        encoding="utf-8",
    )
    skill = SkillDefinition(
        id="skill_reviewed",
        name="reviewed-skill",
        title="Reviewed Skill",
        description="Reviewed capability",
        instructions="# Reviewed Skill",
        source_path=str(skill_path),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash=hashlib.sha256(skill_path.read_bytes()).hexdigest(),
        version="1",
    )
    profile_path = profile_root / "agentmesh.yaml"
    profile_path.write_text(
        yaml.safe_dump(
            {
                "skill_id": "auto",
                "skill_version": "1",
                "skill_content_hash": skill.content_hash,
                "profile_version": "1",
                "display_description": "Reviewed capability",
                "primary_stage": "pre_design",
                "capability_type": "analysis",
                "input_kinds": ["request"],
                "output_kinds": ["analysis_result"],
                "examples": ["Analyze A", "Analyze B", "Analyze C"],
                "negative_examples": ["Write A", "Write B"],
                "required_tools": ["review_tool"],
                "owner": "@owner",
                "risk_level": "high",
                "side_effect": "external_write",
                "review_state": review_state,
                "planner_eligible": review_state == "approved",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "reviews.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "profile-review-evidence-v1",
                "repository": "owner/repository",
                "release_commit": "a" * 40,
                "reviewed_tree_sha": "b" * 40,
                "profiles": [
                    {
                        "skill_name": skill.name,
                        "author": "@author",
                        "reviewers": ["@reviewer", "@second-reviewer"],
                        "reviewed_head_sha": "c" * 40,
                        "reviewed_tree_sha": "b" * 40,
                        "reviewed_blob_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text("/agentmesh/builtin_skills/ @reviewer @second-reviewer\n", encoding="utf-8")
    return builtin_root, evidence_path, codeowners


def test_build_profile_provenance_requires_reviewed_exact_blobs(tmp_path: Path) -> None:
    builtin_root, evidence_path, codeowners = _profile_fixture(tmp_path)

    provenance = build_profile_provenance(
        builtin_root=builtin_root,
        evidence_path=evidence_path,
        codeowners_path=codeowners,
        expected_profile_count=1,
    )

    assert provenance.schema_version == "wiki-skill-profile-provenance-v2"
    assert provenance.repository == "owner/repository"
    assert provenance.profiles[0].review_policy == "double"
    assert provenance.profiles[0].reviewers == ("@reviewer", "@second-reviewer")


def test_build_profile_provenance_rejects_drafts_and_insufficient_reviews(tmp_path: Path) -> None:
    builtin_root, evidence_path, codeowners = _profile_fixture(tmp_path, review_state="draft")
    with pytest.raises(ProvenanceBuildError, match="profile_not_approved"):
        build_profile_provenance(
            builtin_root=builtin_root,
            evidence_path=evidence_path,
            codeowners_path=codeowners,
            expected_profile_count=1,
        )

    builtin_root, evidence_path, codeowners = _profile_fixture(tmp_path / "approved")
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["profiles"][0]["reviewers"] = ["@reviewer"]
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProvenanceBuildError, match="profile_review_invalid"):
        build_profile_provenance(
            builtin_root=builtin_root,
            evidence_path=evidence_path,
            codeowners_path=codeowners,
            expected_profile_count=1,
        )
