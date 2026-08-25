from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from agentmesh.models import (
    SkillActivationPolicy,
    SkillDefinition,
    SkillMemoryWritePolicy,
    SkillSourceScope,
)

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RESERVED_COMMANDS = {
    "memory.search",
    "memory.personal",
    "memory.project",
    "memory.team",
    "brief.create",
    "note.save",
    "research.request",
    "data.query",
    "risk.review",
    "memory.propose",
    "system.info",
}
_KNOWN_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
    "disable-model-invocation",
    "aliases",
    "argument-hint",
    "requires-input",
}


@dataclass(slots=True)
class SkillDiagnostic:
    level: Literal["warning", "error"]
    code: str
    message: str
    path: str


@dataclass(slots=True)
class SkillParseResult:
    skill: SkillDefinition | None
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)


def _diagnostic(path: Path, level: Literal["warning", "error"], code: str, message: str) -> SkillDiagnostic:
    return SkillDiagnostic(level=level, code=code, message=message, path=str(path))


def _split_frontmatter(text: str) -> tuple[str, str] | None:
    normalized = text.lstrip("\ufeff")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :]).strip()
    return None


def _repair_description(frontmatter: str) -> str:
    """Repair the common cross-harness YAML error: an unquoted colon in description."""
    repaired: list[str] = []
    changed = False
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            value = line.partition(":")[2].strip()
            if value and ":" in value and not value.startswith(("'", '"', "|", ">")):
                repaired.extend(["description: >-", f"  {value}"])
                changed = True
                continue
        repaired.append(line)
    return "\n".join(repaired) if changed else frontmatter


def _load_frontmatter(path: Path, raw: str, diagnostics: list[SkillDiagnostic]) -> dict[str, Any] | None:
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        repaired = _repair_description(raw)
        if repaired == raw:
            diagnostics.append(_diagnostic(path, "error", "frontmatter_yaml_invalid", "SKILL.md frontmatter is invalid YAML"))
            return None
        try:
            loaded = yaml.safe_load(repaired)
        except yaml.YAMLError:
            diagnostics.append(_diagnostic(path, "error", "frontmatter_yaml_invalid", "SKILL.md frontmatter is invalid YAML"))
            return None
        diagnostics.append(
            _diagnostic(
                path,
                "warning",
                "frontmatter_yaml_repaired",
                "Repaired an unquoted colon in the description for cross-harness compatibility",
            )
        )
    if not isinstance(loaded, dict):
        diagnostics.append(_diagnostic(path, "error", "frontmatter_not_mapping", "SKILL.md frontmatter must be a mapping"))
        return None
    return {str(key): value for key, value in loaded.items()}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item for item in re.split(r"[\s,]+", value.strip()) if item]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _metadata(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _title(body: str, name: str) -> str:
    in_preamble = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "<!-- ABSOLUTE-PROHIBITIONS:START -->":
            in_preamble = True
            continue
        if stripped == "<!-- ABSOLUTE-PROHIBITIONS:END -->":
            in_preamble = False
            continue
        if in_preamble:
            continue
        if line.startswith("# "):
            candidate = line[2:].strip()
            if candidate:
                return candidate[:160]
    return name.replace("-", " ").title()


def parse_skill_file(path: Path, *, source_scope: SkillSourceScope) -> SkillParseResult:
    diagnostics: list[SkillDiagnostic] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        diagnostics.append(_diagnostic(path, "error", "skill_read_failed", f"Could not read SKILL.md: {type(error).__name__}"))
        return SkillParseResult(skill=None, diagnostics=diagnostics)

    split = _split_frontmatter(text)
    if split is None:
        diagnostics.append(_diagnostic(path, "error", "frontmatter_missing", "SKILL.md must start with YAML frontmatter"))
        return SkillParseResult(skill=None, diagnostics=diagnostics)
    raw_frontmatter, body = split
    frontmatter = _load_frontmatter(path, raw_frontmatter, diagnostics)
    if frontmatter is None:
        return SkillParseResult(skill=None, diagnostics=diagnostics)

    name = str(frontmatter.get("name") or "").strip()
    description = str(frontmatter.get("description") or "").strip()
    if not description:
        diagnostics.append(_diagnostic(path, "error", "description_missing", "Skill description is required"))
        return SkillParseResult(skill=None, diagnostics=diagnostics)
    if not name:
        diagnostics.append(_diagnostic(path, "error", "name_missing", "Skill name is required"))
        return SkillParseResult(skill=None, diagnostics=diagnostics)
    if not _NAME_RE.fullmatch(name) or len(name) > 64:
        diagnostics.append(_diagnostic(path, "error", "name_nonstandard", "Skill name is outside Agent Skills naming rules"))
        return SkillParseResult(skill=None, diagnostics=diagnostics)
    if path.parent.name != name:
        diagnostics.append(
            _diagnostic(path, "warning", "name_directory_mismatch", "Skill name differs from its parent directory")
        )
    if len(description) > 1024:
        diagnostics.append(_diagnostic(path, "warning", "description_too_long", "Skill description exceeds 1024 characters"))
        description = description[:1024]
    if not body:
        diagnostics.append(_diagnostic(path, "warning", "instructions_empty", "Skill instructions are empty"))

    metadata = _metadata(frontmatter.get("metadata"))
    activation = SkillActivationPolicy.EXPLICIT_ONLY
    if metadata.get("agentmesh-activation") == SkillActivationPolicy.MODEL_ALLOWED:
        activation = SkillActivationPolicy.MODEL_ALLOWED
    if bool(frontmatter.get("disable-model-invocation")):
        activation = SkillActivationPolicy.EXPLICIT_ONLY

    host_fields = {key: value for key, value in frontmatter.items() if key not in _KNOWN_FIELDS}
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    stable_id = hashlib.sha256(f"{source_scope.value}:{path.resolve()}:{name}".encode()).hexdigest()[:16]
    argument_hint = str(frontmatter.get("argument-hint") or "").strip() or None
    requires_input_raw = frontmatter.get("requires-input", True)

    aliases = _string_list(frontmatter.get("aliases"))
    invalid_aliases = [
        alias
        for alias in aliases
        if not _NAME_RE.fullmatch(alias.removeprefix("$"))
        or len(alias.removeprefix("$")) > 64
        or alias.removeprefix("$") in _RESERVED_COMMANDS
    ]
    if invalid_aliases:
        diagnostics.append(_diagnostic(path, "error", "alias_invalid", "Skill aliases must use non-reserved Agent Skills names"))
        return SkillParseResult(skill=None, diagnostics=diagnostics)
    compatibility = str(frontmatter.get("compatibility") or "").strip() or None
    if compatibility and len(compatibility) > 500:
        diagnostics.append(_diagnostic(path, "error", "compatibility_too_long", "Skill compatibility exceeds 500 characters"))
        return SkillParseResult(skill=None, diagnostics=diagnostics)

    try:
        skill = SkillDefinition(
            id=f"skilldef_{stable_id}",
            name=name,
            title=_title(body, name),
            description=description,
            instructions=body,
            source_path=str(path.resolve()),
            source_scope=source_scope,
            content_hash=content_hash,
            version=metadata.get("version", "1"),
            license=str(frontmatter.get("license") or "").strip() or None,
            compatibility=compatibility,
            metadata=metadata,
            host_fields=host_fields,
            requested_tools=_string_list(frontmatter.get("allowed-tools")),
            aliases=aliases,
            argument_hint=argument_hint,
            requires_input=bool(requires_input_raw),
            activation_policy=activation,
            memory_write_policy=SkillMemoryWritePolicy(
                metadata.get("agentmesh-memory-write", SkillMemoryWritePolicy.NONE.value)
            ) if metadata.get("agentmesh-memory-write", SkillMemoryWritePolicy.NONE.value) in {item.value for item in SkillMemoryWritePolicy}
            else SkillMemoryWritePolicy.NONE,
        )
    except (ValidationError, ValueError):
        diagnostics.append(_diagnostic(path, "error", "skill_model_invalid", "Skill metadata failed AgentMesh validation"))
        return SkillParseResult(skill=None, diagnostics=diagnostics)
    return SkillParseResult(skill=skill, diagnostics=diagnostics)
