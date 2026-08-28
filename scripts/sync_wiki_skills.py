#!/usr/bin/env python3
"""Vendor the audited 2C-DesignWiki Skill inventory into AgentMesh.

The Wiki is input data. This script parses its frontmatter but never executes any
instruction contained in a Skill. Ten hand-maintained pilot packages are kept
verbatim; the remaining definitions are normalized into flat builtin packages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WIKI_ROOT = REPOSITORY_ROOT / "2C-DesignWiki"
DEFAULT_BUILTIN_ROOT = REPOSITORY_ROOT / "agentmesh" / "builtin_skills"
MANIFEST_FILENAME = "wiki-skill-provenance.json"

EXPECTED_SOURCE_FILE_COUNT = 86
EXPECTED_CANONICAL_SKILL_COUNT = 84
_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_IGNORED_DIRECTORIES = {".git", "node_modules", "__pycache__"}
_VALID_STAGES = frozenset({"pre_design", "during_design", "post_design"})
_ROUTING_SUMMARY_LIMIT = 100

# Primary lifecycle stage for every audited Wiki Skill. This is deliberately
# exhaustive: adding or removing a canonical Skill must update this map.
SKILL_STAGES: dict[str, str] = {
    "accessibility-review": "post_design",
    "ai-decision-lab": "post_design",
    "analyze-satisfaction": "post_design",
    "build-experience-metrics": "post_design",
    "case-register": "post_design",
    "code-open-feedback": "post_design",
    "coding-repo-sync": "post_design",
    "competitive-analysis": "pre_design",
    "component-properties-admission": "post_design",
    "conversion-funnel-analysis": "post_design",
    "design-abtest-analysis": "post_design",
    "design-advisor": "pre_design",
    "design-cleanup": "post_design",
    "design-md-to-portal": "post_design",
    "design-md-to-relay": "during_design",
    "design-md-to-spec-page": "post_design",
    "design-reasoning-input": "post_design",
    "design-review": "post_design",
    "dwiki": "post_design",
    "feature-adoption-analysis": "post_design",
    "feedback-insight": "post_design",
    "field-design-build": "during_design",
    "filter-tabs-design-skill": "during_design",
    "generate-interview-guide": "pre_design",
    "generate-persona": "pre_design",
    "generate-research-plan": "pre_design",
    "generate-survey": "during_design",
    "generate-usability-test": "during_design",
    "git-workflow": "post_design",
    "industry-market-analysis": "pre_design",
    "instance-manage": "post_design",
    "instance-suggest": "post_design",
    "issue-prioritization": "post_design",
    "jd-app-journey-map": "pre_design",
    "jd-field-ppt-skill": "post_design",
    "jobs-to-be-done": "pre_design",
    "journey-map": "pre_design",
    "joyspace-docs": "post_design",
    "knowledge-preview": "post_design",
    "knowledge-update": "post_design",
    "leader-report": "post_design",
    "lieflat-charts": "post_design",
    "livestream-cover-generator": "during_design",
    "mega-subsidy-design-skill": "during_design",
    "motion-handoff-export": "post_design",
    "navbar-generation": "during_design",
    "nested-structure-generation-skill": "during_design",
    "platform-transaction-address": "during_design",
    "platform-transaction-cart": "during_design",
    "platform-transaction-cashier": "during_design",
    "platform-transaction-settlement": "during_design",
    "platform-transaction-shared-foundation": "during_design",
    "platform-transaction-success-page": "during_design",
    "plugin-api-key-ai": "during_design",
    "popup-design-skill": "during_design",
    "prd-design-brief": "pre_design",
    "prd-feasibility": "pre_design",
    "prelaunch-usability-review": "post_design",
    "prototype-generation": "during_design",
    "qiangdan-hall-generator": "during_design",
    "query-experiment-conclusions": "pre_design",
    "register-experiment": "post_design",
    "relay-component-set-architect": "during_design",
    "relay-component-variant-generator": "during_design",
    "relay-demo-from-md": "during_design",
    "relay-spec-longpage": "post_design",
    "relay-theme-replace": "during_design",
    "relay-to-component-pipeline": "during_design",
    "relay-to-design-md": "post_design",
    "research-screenshot-analyzer": "pre_design",
    "ruler-annotation": "post_design",
    "run-heuristic-evaluation": "post_design",
    "search": "pre_design",
    "senior-adaptation-tool": "during_design",
    "structure-interview-transcript": "pre_design",
    "synthesize-qualitative-insights": "pre_design",
    "usability-review": "post_design",
    "welcome": "pre_design",
    "zero-banner-update": "during_design",
    "zero-id-to-md": "post_design",
    "zero-md-to-page": "post_design",
    "zero-spec-to-md": "post_design",
    "zero-superbrand-banner-audit": "post_design",
    "zero-to-joyspace": "post_design",
}

# Short, user-language descriptions for Skills whose source summaries overlap
# heavily with neighboring workflows. All other imported Skills receive a
# bounded summary derived from their source description.
SKILL_ROUTING_SUMMARIES: dict[str, str] = {
    "design-review": "检查页面或设计稿的问题并给出修改建议，适合通用设计评审与方案走查。",
    "generate-persona": "把访谈、调研数据和用户洞察归纳为用户画像、人物角色或 persona。",
    "journey-map": "基于研究材料生成用户旅程图或体验地图，展示阶段、触点、情绪、痛点与机会。",
    "prototype-generation": "把 PRD、截图或口头需求快速生成可点击、可编辑的高保真页面原型或样稿。",
    "research-screenshot-analyzer": "采集并分析用研或竞品截图，输出截图视觉分析；不处理访谈材料，不生成正式用研结论。",
    "structure-interview-transcript": "整理单场用户访谈逐字稿或录音转写，生成结构化访谈小结；不做多场研究综合。",
    "synthesize-qualitative-insights": "生成用户研究报告或用研报告：把多场访谈、逐字稿等定性材料归纳为主题、结论与洞察。",
    "usability-review": "检查页面、原型或产品流程的可用性问题，给出体验诊断与优化建议。",
}

PRESERVED_BUILTIN_NAMES = frozenset(
    {
        "build-experience-metrics",
        "competitive-analysis",
        "generate-interview-guide",
        "generate-research-plan",
        "generate-survey",
        "generate-usability-test",
        "issue-prioritization",
        "jobs-to-be-done",
        "prd-feasibility",
        "query-experiment-conclusions",
    }
)


@dataclass(frozen=True, slots=True)
class Adapter:
    name: str
    description: str


ADAPTERS: dict[str, Adapter] = {
    "jd-design-system-md-v16/horizontal/user-research/skills/AI-Decision-Lab/SKILL.md": Adapter(
        name="ai-decision-lab",
        description=(
            "AI Decision Lab 用于把设计截图转化为结构化评审结论，支持单稿、多稿和多页面流程评审。"
        ),
    ),
    "jd-design-system-md-v16/product-architecture/platform-transaction/_共享底座/SKILL.md": Adapter(
        name="platform-transaction-shared-foundation",
        description="平台交易设计部共享底座索引，按业务线、场域和阶段路由设计任务。",
    ),
    "jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/地址/SKILL.md": Adapter(
        name="platform-transaction-address",
        description="平台交易设计部地址场域入口，按输入校验和四步方法路由地址设计任务。",
    ),
    "jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/成功页/SKILL.md": Adapter(
        name="platform-transaction-success-page",
        description="平台交易设计部成功页场域入口，按输入校验和四步方法路由成功页设计任务。",
    ),
    "jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/收银台/SKILL.md": Adapter(
        name="platform-transaction-cashier",
        description="平台交易设计部收银台场域入口，按输入校验和四步方法路由收银台设计任务。",
    ),
    "jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/结算/SKILL.md": Adapter(
        name="platform-transaction-settlement",
        description="平台交易设计部结算场域入口，按输入校验和四步方法路由结算设计任务。",
    ),
    "jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/购物车/SKILL.md": Adapter(
        name="platform-transaction-cart",
        description="平台交易设计部购物车场域入口，按输入校验和四步方法路由购物车设计任务。",
    ),
}

EXPECTED_DUPLICATES: dict[str, tuple[str, tuple[str, ...]]] = {
    "4405264795472393813077b0451a2ae99a8b62be11f0027c143dc5ebc867c587": (
        "jd-design-system-md-v16/product-architecture/plus-and-new-channel/_skills/zero-id-to-md/SKILL.md",
        (
            "jd-design-system-md-v16/product-architecture/plus-and-new-channel/_foundation/components/zero-id-to-md/SKILL.md",
            "jd-design-system-md-v16/product-architecture/plus-and-new-channel/_skills/zero-id-to-md/SKILL.md",
        ),
    ),
    "dc9aad37b98bfc97df4d555121482c5f281e3fd651a8e946992d1bd0e44a98b2": (
        "tools/dwiki/SKILL.md",
        (
            "tools/dwiki/SKILL.md",
            "tools/dwiki/o2-registry/SKILL.md",
        ),
    ),
}


class SyncError(RuntimeError):
    """The source inventory or vendored snapshot violated its contract."""


@dataclass(frozen=True, slots=True)
class SourceSkill:
    path: Path
    relative_path: str
    source_sha256: str
    frontmatter: dict[str, Any] | None
    body: str

    @property
    def declared_name(self) -> str | None:
        if self.frontmatter is None:
            return None
        value = self.frontmatter.get("name")
        return str(value).strip() if value is not None else None


@dataclass(frozen=True, slots=True)
class CanonicalSkill:
    name: str
    source: SourceSkill
    adapter: Adapter | None

    @property
    def destination_relative_path(self) -> str:
        return f"{self.name}/SKILL.md"


@dataclass(frozen=True, slots=True)
class SyncPlan:
    source_file_count: int
    skills: tuple[CanonicalSkill, ...]
    duplicate_groups: dict[str, tuple[SourceSkill, ...]]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _skill_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        names[:] = sorted(
            name
            for name in names
            if name not in _IGNORED_DIRECTORIES and not (base / name).is_symlink()
        )
        if "SKILL.md" in files:
            candidate = base / "SKILL.md"
            if not candidate.is_symlink():
                paths.append(candidate)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def _split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() != "---":
            continue
        try:
            loaded = yaml.safe_load("".join(lines[1:index]))
        except yaml.YAMLError as error:
            raise SyncError("invalid source frontmatter") from error
        if not isinstance(loaded, dict):
            raise SyncError("source frontmatter must be a mapping")
        return {str(key): value for key, value in loaded.items()}, "".join(lines[index + 1 :])
    raise SyncError("unterminated source frontmatter")


def _load_source(path: Path, wiki_root: Path) -> SourceSkill:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        frontmatter, body = _split_frontmatter(text)
    except (OSError, UnicodeError, SyncError) as error:
        relative = path.relative_to(wiki_root).as_posix()
        raise SyncError(f"cannot parse {relative}: {error}") from error
    return SourceSkill(
        path=path,
        relative_path=path.relative_to(wiki_root).as_posix(),
        source_sha256=_sha256(raw),
        frontmatter=frontmatter,
        body=body,
    )


def _selection_key(source: SourceSkill) -> tuple[bool, int, str]:
    name_matches_directory = source.declared_name is not None and source.path.parent.name == source.declared_name
    depth = len(Path(source.relative_path).parts)
    return not name_matches_directory, depth, source.relative_path


def _validate_duplicate_groups(groups: dict[str, list[SourceSkill]]) -> None:
    actual = {
        digest: tuple(sorted(item.relative_path for item in sources))
        for digest, sources in groups.items()
        if len(sources) > 1
    }
    expected = {digest: tuple(sorted(paths)) for digest, (_, paths) in EXPECTED_DUPLICATES.items()}
    if actual != expected:
        raise SyncError(f"source duplicate groups changed: expected={expected!r}, actual={actual!r}")


def build_sync_plan(wiki_root: Path = DEFAULT_WIKI_ROOT) -> SyncPlan:
    wiki_root = wiki_root.resolve(strict=True)
    paths = _skill_paths(wiki_root)
    if len(paths) != EXPECTED_SOURCE_FILE_COUNT:
        raise SyncError(f"expected {EXPECTED_SOURCE_FILE_COUNT} source files, found {len(paths)}")

    groups: dict[str, list[SourceSkill]] = {}
    for path in paths:
        source = _load_source(path, wiki_root)
        groups.setdefault(source.source_sha256, []).append(source)
    _validate_duplicate_groups(groups)
    if len(groups) != EXPECTED_CANONICAL_SKILL_COUNT:
        raise SyncError(f"expected {EXPECTED_CANONICAL_SKILL_COUNT} unique source files, found {len(groups)}")

    canonical: list[CanonicalSkill] = []
    for digest, sources in groups.items():
        source = min(sources, key=_selection_key)
        expected_duplicate = EXPECTED_DUPLICATES.get(digest)
        if expected_duplicate is not None:
            expected_path = expected_duplicate[0]
            if source.relative_path != expected_path:
                raise SyncError(
                    f"duplicate canonical selection changed for {digest}: "
                    f"expected={expected_path}, actual={source.relative_path}"
                )
        adapter = ADAPTERS.get(source.relative_path)
        name = adapter.name if adapter is not None else source.declared_name
        if not name or not _NAME_PATTERN.fullmatch(name) or len(name) > 64:
            raise SyncError(f"source requires an explicit adapter: {source.relative_path}")
        canonical.append(CanonicalSkill(name=name, source=source, adapter=adapter))

    canonical.sort(key=lambda item: item.name)
    names = [item.name for item in canonical]
    if len(set(names)) != EXPECTED_CANONICAL_SKILL_COUNT:
        duplicates = sorted(name for name in set(names) if names.count(name) > 1)
        raise SyncError(f"canonical names are not unique: {duplicates}")
    if set(SKILL_STAGES) != set(names):
        raise SyncError(
            "stage mapping does not match canonical Skills: "
            f"missing={sorted(set(names) - set(SKILL_STAGES))}, "
            f"unexpected={sorted(set(SKILL_STAGES) - set(names))}"
        )
    invalid_stages = {name: stage for name, stage in SKILL_STAGES.items() if stage not in _VALID_STAGES}
    if invalid_stages:
        raise SyncError(f"stage mapping contains invalid values: {invalid_stages}")
    used_adapters = {item.source.relative_path for item in canonical if item.adapter is not None}
    if used_adapters != set(ADAPTERS):
        raise SyncError(f"adapter coverage changed: {sorted(set(ADAPTERS) ^ used_adapters)}")
    if not set(names) >= PRESERVED_BUILTIN_NAMES:
        raise SyncError("one or more preserved pilot Skills disappeared from the Wiki inventory")
    invalid_routing_summaries = set(SKILL_ROUTING_SUMMARIES) - (set(names) - PRESERVED_BUILTIN_NAMES)
    if invalid_routing_summaries:
        raise SyncError(f"routing summaries must target generated Skills: {sorted(invalid_routing_summaries)}")
    return SyncPlan(
        source_file_count=len(paths),
        skills=tuple(canonical),
        duplicate_groups={digest: tuple(sorted(items, key=lambda item: item.relative_path)) for digest, items in groups.items() if len(items) > 1},
    )


def _normalized_frontmatter(skill: CanonicalSkill) -> dict[str, Any]:
    if skill.source.frontmatter is None:
        if skill.adapter is None:
            raise SyncError(f"missing adapter for {skill.source.relative_path}")
        frontmatter: dict[str, Any] = {
            "name": skill.name,
            "description": skill.adapter.description,
        }
    else:
        frontmatter = dict(skill.source.frontmatter)
        frontmatter["name"] = skill.name
        if skill.adapter is not None:
            frontmatter["description"] = skill.adapter.description

    raw_metadata = frontmatter.get("metadata")
    if raw_metadata is None:
        metadata: dict[str, Any] = {}
    elif isinstance(raw_metadata, dict):
        metadata = dict(raw_metadata)
    else:
        raise SyncError(f"metadata is not a mapping: {skill.source.relative_path}")

    top_level_version = frontmatter.pop("version", None)
    if top_level_version is not None and "version" not in metadata:
        metadata["version"] = str(top_level_version)
    metadata.setdefault("author", "2C-DesignWiki")
    metadata["source"] = f"2C-DesignWiki/{skill.source.relative_path}"
    metadata["agentmesh-wiki-import"] = "true"
    metadata["agentmesh-stage"] = SKILL_STAGES[skill.name]
    metadata["agentmesh-activation"] = "explicit_only"
    source_summary = metadata.get("short-description") or frontmatter.get("description", "")
    summary = SKILL_ROUTING_SUMMARIES.get(skill.name, str(source_summary))
    summary = " ".join(summary.split())
    if len(summary) > _ROUTING_SUMMARY_LIMIT:
        summary = summary[: _ROUTING_SUMMARY_LIMIT - 1].rstrip("，。；：、 ") + "…"
    metadata["short-description"] = summary
    frontmatter["metadata"] = metadata
    # Imported Wiki content is data, not authorization to enter model-driven planning.
    frontmatter["disable-model-invocation"] = True
    return frontmatter


def render_skill(skill: CanonicalSkill) -> bytes:
    frontmatter = yaml.safe_dump(
        _normalized_frontmatter(skill),
        allow_unicode=True,
        sort_keys=False,
        width=120,
    ).rstrip("\n")
    return f"---\n{frontmatter}\n---\n{skill.source.body}".encode()


def _destination_hash(skill: CanonicalSkill, builtin_root: Path) -> str:
    destination = builtin_root / skill.destination_relative_path
    if skill.name in PRESERVED_BUILTIN_NAMES:
        if not destination.is_file():
            raise SyncError(f"preserved builtin is missing: {destination}")
        return _sha256(destination.read_bytes())
    return _sha256(render_skill(skill))


def build_manifest(plan: SyncPlan, builtin_root: Path = DEFAULT_BUILTIN_ROOT) -> dict[str, Any]:
    duplicate_groups = []
    for digest, sources in sorted(plan.duplicate_groups.items()):
        canonical_source = EXPECTED_DUPLICATES[digest][0]
        duplicate_groups.append(
            {
                "source_sha256": digest,
                "canonical_source": f"2C-DesignWiki/{canonical_source}",
                "sources": [f"2C-DesignWiki/{item.relative_path}" for item in sources],
            }
        )
    skills = []
    for skill in plan.skills:
        mode = "preserved" if skill.name in PRESERVED_BUILTIN_NAMES else "generated"
        skills.append(
            {
                "name": skill.name,
                "source": f"2C-DesignWiki/{skill.source.relative_path}",
                "source_sha256": skill.source.source_sha256,
                "destination": f"agentmesh/builtin_skills/{skill.destination_relative_path}",
                "builtin_sha256": _destination_hash(skill, builtin_root),
                "mode": mode,
                "adapter": skill.adapter is not None,
                "stage": SKILL_STAGES[skill.name],
            }
        )
    return {
        "schema_version": 1,
        "source_root": "2C-DesignWiki",
        "source_file_count": plan.source_file_count,
        "unique_source_count": len(plan.skills),
        "preserved_builtin_count": len(PRESERVED_BUILTIN_NAMES),
        "generated_builtin_count": len(plan.skills) - len(PRESERVED_BUILTIN_NAMES),
        "stage_counts": {
            stage: sum(SKILL_STAGES[skill.name] == stage for skill in plan.skills)
            for stage in sorted(_VALID_STAGES)
        },
        "duplicate_groups": duplicate_groups,
        "skills": skills,
    }


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _builtin_skill_paths(builtin_root: Path) -> set[str]:
    return {path.relative_to(builtin_root).as_posix() for path in _skill_paths(builtin_root)}


def check_sync(plan: SyncPlan, builtin_root: Path = DEFAULT_BUILTIN_ROOT) -> list[str]:
    expected_paths = {skill.destination_relative_path for skill in plan.skills}
    problems: list[str] = []
    actual_paths = _builtin_skill_paths(builtin_root)
    if actual_paths != expected_paths:
        problems.append(
            f"builtin inventory mismatch: missing={sorted(expected_paths - actual_paths)}, "
            f"unexpected={sorted(actual_paths - expected_paths)}"
        )
    for skill in plan.skills:
        destination = builtin_root / skill.destination_relative_path
        if not destination.is_file():
            continue
        if skill.name in PRESERVED_BUILTIN_NAMES:
            frontmatter, body = _split_frontmatter(destination.read_text(encoding="utf-8"))
            if body != skill.source.body:
                problems.append(f"preserved builtin body differs from Wiki source: {skill.name}")
            if not isinstance(frontmatter, dict) or str(frontmatter.get("name", "")).strip() != skill.name:
                problems.append(f"preserved builtin name differs from canonical name: {skill.name}")
            metadata = frontmatter.get("metadata") if isinstance(frontmatter, dict) else None
            expected_source = f"2C-DesignWiki/{skill.source.relative_path}"
            if not isinstance(metadata, dict) or str(metadata.get("source", "")).strip() != expected_source:
                problems.append(f"preserved builtin source differs from canonical source: {skill.name}")
            skill_version = str(metadata.get("version", "1")) if isinstance(metadata, dict) else "1"
            profile_path = destination.parent / "agents" / "agentmesh.yaml"
            if not profile_path.is_file():
                problems.append(f"preserved builtin profile is missing: {skill.name}")
            else:
                try:
                    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, yaml.YAMLError):
                    profile = None
                if not isinstance(profile, dict) or profile.get("primary_stage") != SKILL_STAGES[skill.name]:
                    problems.append(f"preserved builtin stage differs from stage mapping: {skill.name}")
                if not isinstance(profile, dict) or profile.get("planner_eligible") is not True:
                    problems.append(f"preserved builtin planner eligibility is disabled: {skill.name}")
                if not isinstance(profile, dict) or profile.get("skill_version") != skill_version:
                    problems.append(f"preserved builtin profile version differs from Skill metadata: {skill.name}")
                if not isinstance(profile, dict) or profile.get("skill_content_hash") != _destination_hash(
                    skill,
                    builtin_root,
                ):
                    problems.append(f"preserved builtin profile hash is stale: {skill.name}")
            continue
        expected = render_skill(skill)
        if destination.read_bytes() != expected:
            problems.append(f"generated builtin is stale: {skill.name}")

    manifest_path = builtin_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        problems.append(f"provenance manifest is missing: {manifest_path}")
    else:
        expected_manifest = _manifest_bytes(build_manifest(plan, builtin_root))
        if manifest_path.read_bytes() != expected_manifest:
            problems.append(f"provenance manifest is stale: {manifest_path}")
    return problems


def sync(plan: SyncPlan, builtin_root: Path = DEFAULT_BUILTIN_ROOT) -> None:
    builtin_root.mkdir(parents=True, exist_ok=True)
    expected_paths = {skill.destination_relative_path for skill in plan.skills}
    unexpected = _builtin_skill_paths(builtin_root) - expected_paths
    if unexpected:
        raise SyncError(f"refusing to delete unexpected builtin Skills: {sorted(unexpected)}")

    for skill in plan.skills:
        if skill.name in PRESERVED_BUILTIN_NAMES:
            destination = builtin_root / skill.destination_relative_path
            if not destination.is_file():
                raise SyncError(f"preserved builtin is missing: {destination}")
            continue
        destination = builtin_root / skill.destination_relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(render_skill(skill))

    manifest = build_manifest(plan, builtin_root)
    (builtin_root / MANIFEST_FILENAME).write_bytes(_manifest_bytes(manifest))


def generate_profile_stubs(
    plan: SyncPlan,
    builtin_root: Path = DEFAULT_BUILTIN_ROOT,
) -> list[Path]:
    """Create identity-only draft sidecars without guessing capability or safety fields."""

    created: list[Path] = []
    for skill in plan.skills:
        destination = builtin_root / skill.destination_relative_path
        if not destination.is_file():
            raise SyncError(f"cannot create Profile stub before Skill sync: {skill.name}")
        sidecar = destination.parent / "agents" / "agentmesh.yaml"
        if sidecar.exists():
            continue
        frontmatter, _body = _split_frontmatter(destination.read_text(encoding="utf-8"))
        metadata = frontmatter.get("metadata") if isinstance(frontmatter, dict) else None
        if not isinstance(metadata, dict):
            raise SyncError(f"generated Skill metadata is missing: {skill.name}")
        description = " ".join(
            str(metadata.get("short-description") or frontmatter.get("description") or "").split()
        )
        payload = {
            "skill_id": "auto",
            "skill_version": str(metadata.get("version", "1")),
            "skill_content_hash": _sha256(destination.read_bytes()),
            "profile_version": "1",
            "display_description": description[:_ROUTING_SUMMARY_LIMIT],
            "primary_stage": SKILL_STAGES[skill.name],
            "review_state": "draft",
            "planner_eligible": False,
        }
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "# Draft scaffold. Add reviewed capability, input/output, Tool, resource, risk, and side-effect fields.\n"
            + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120)
        )
        try:
            with sidecar.open("x", encoding="utf-8") as stream:
                stream.write(content)
        except FileExistsError:
            continue
        created.append(sidecar)
    return created


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the vendored snapshot without writing files")
    parser.add_argument(
        "--generate-profile-stubs",
        action="store_true",
        help="Create identity-only draft Profile sidecars when absent; never overwrite existing files",
    )
    parser.add_argument("--wiki-root", type=Path, default=DEFAULT_WIKI_ROOT)
    parser.add_argument("--builtin-root", type=Path, default=DEFAULT_BUILTIN_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.check and args.generate_profile_stubs:
        print("wiki Skill sync failed: --check and --generate-profile-stubs are mutually exclusive", file=sys.stderr)
        return 2
    try:
        plan = build_sync_plan(args.wiki_root)
        if args.check:
            problems = check_sync(plan, args.builtin_root)
            if problems:
                for problem in problems:
                    print(problem, file=sys.stderr)
                return 1
        else:
            sync(plan, args.builtin_root)
            created_stubs = (
                generate_profile_stubs(plan, args.builtin_root)
                if args.generate_profile_stubs
                else []
            )
            problems = check_sync(plan, args.builtin_root)
            if problems:
                raise SyncError("; ".join(problems))
    except (OSError, SyncError) as error:
        print(f"wiki Skill sync failed: {error}", file=sys.stderr)
        return 1
    print(
        f"Wiki Skill snapshot is current: {len(plan.skills)} total, "
        f"{len(PRESERVED_BUILTIN_NAMES)} preserved, "
        f"{len(plan.skills) - len(PRESERVED_BUILTIN_NAMES)} generated"
        + (
            f", {len(created_stubs)} Profile stubs created"
            if not args.check and args.generate_profile_stubs
            else ""
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
