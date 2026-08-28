from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agentmesh.models import (
    SkillCapabilityProfile,
    SkillDefinition,
    SkillLifecycleStage,
    SkillSourceScope,
    SkillStatus,
    now_utc,
)
from agentmesh.skill_runtime.discovery import SkillDiagnostic, SkillRoot, discover_skills
from agentmesh.skill_runtime.profiles import (
    ProfileError,
    legacy_capability_profiles,
    load_capability_profile_record,
    profile_matches_skill,
    profile_path,
)
from agentmesh.skill_runtime.resources import skill_wiki_corpus_ready
from agentmesh.store import SQLiteStore, store

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
BUILTIN_SKILLS_DIR = ROOT_DIR / "agentmesh" / "builtin_skills"
_SKILL_DISPLAY_DESCRIPTION_LIMIT = 100


def _display_description(skill: SkillDefinition, profile: SkillCapabilityProfile | None) -> str:
    description = (profile.display_description if profile is not None else None) or skill.description
    description = " ".join(description.split())
    if len(description) <= _SKILL_DISPLAY_DESCRIPTION_LIMIT:
        return description
    return description[: _SKILL_DISPLAY_DESCRIPTION_LIMIT - 1].rstrip("，。；：、 ") + "…"


def _metadata_primary_stage(skill: SkillDefinition) -> SkillLifecycleStage | None:
    raw_stage = skill.metadata.get("agentmesh-stage", "").strip()
    try:
        return SkillLifecycleStage(raw_stage)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ResolvedSkill:
    definition: SkillDefinition
    command: str
    argument: str


class SkillCatalogService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository
        self._skills: dict[str, SkillDefinition] = {}
        self._diagnostics: list[SkillDiagnostic] = []

    @property
    def diagnostics(self) -> list[SkillDiagnostic]:
        return list(self._diagnostics)

    def _roots(self) -> list[SkillRoot]:
        roots: list[SkillRoot] = []
        if os.getenv("AGENTMESH_TRUST_PROJECT_SKILLS", "").strip().lower() in {"1", "true", "yes", "on"}:
            cwd = Path.cwd()
            for relative in (".agents/skills", ".pi/skills", ".claude/skills", ".codex/skills"):
                roots.append(SkillRoot(cwd / relative, SkillSourceScope.PROJECT))
        raw_paths = os.getenv("AGENTMESH_SKILL_PATHS", "")
        for raw_path in raw_paths.split(","):
            if raw_path.strip():
                roots.append(SkillRoot(Path(raw_path.strip()).expanduser(), SkillSourceScope.WORKSPACE))
        for package in self.repository.skill_packages:
            if package.status == "active":
                roots.append(SkillRoot(Path(package.root_path), SkillSourceScope.WORKSPACE))
        roots.append(SkillRoot(BUILTIN_SKILLS_DIR, SkillSourceScope.BUILTIN))
        return roots

    def reload(self) -> list[SkillDefinition]:
        discovered = discover_skills(self._roots())
        self._diagnostics = discovered.diagnostics
        current: dict[str, SkillDefinition] = {}
        for name, skill in discovered.skills.items():
            existing = self.repository.get_skill_definition(skill.id)
            if existing is not None:
                skill.created_at = existing.created_at
                if existing.content_hash == skill.content_hash and existing.enabled == skill.enabled:
                    skill.updated_at = existing.updated_at
                    current[name] = self.repository.save_skill_definition(skill, defer_vector=True)
                    continue
            skill.updated_at = now_utc()
            current[name] = self.repository.save_skill_definition(skill, defer_vector=True)
        for stored in self.repository.skill_definitions:
            if stored.source_path.startswith("learned://") and stored.enabled and stored.name not in current:
                current[stored.name] = stored
        active_profile_ids: set[str] = set()
        for skill in current.values():
            if not profile_path(skill).is_file():
                self.repository.delete_skill_capability_profile(skill.id)
                continue
            try:
                loaded_profile = load_capability_profile_record(skill)
                profile = loaded_profile.profile
            except ProfileError as error:
                self.repository.delete_skill_capability_profile(skill.id)
                self._diagnostics.append(
                    SkillDiagnostic(
                        level="error",
                        code=str(error),
                        message=f"Skill capability profile is not usable: {error}",
                        path=str(profile_path(skill)),
                    )
                )
                continue
            self.repository.save_skill_capability_profile(
                profile,
                defer_vector=True,
                index_vector=loaded_profile.review_state != "draft",
            )
            active_profile_ids.add(profile.id)
        for profile in legacy_capability_profiles():
            self.repository.save_skill_capability_profile(profile, defer_vector=True)
            active_profile_ids.add(profile.id)
        for profile in self.repository.skill_capability_profiles:
            if profile.id not in active_profile_ids:
                self.repository.delete_skill_capability_profile(profile.id)
        self.repository.start_skill_vector_indexing()
        self._skills = current
        return self.list_enabled()

    def _ensure_loaded(self) -> None:
        if not self._skills:
            self.reload()

    @staticmethod
    def _external_corpus_ready(skill: SkillDefinition) -> bool:
        source = skill.metadata.get("source", "")
        if skill.source_scope != SkillSourceScope.BUILTIN or not source.startswith("2C-DesignWiki/"):
            return True
        return skill_wiki_corpus_ready(skill)

    def is_runtime_enabled(self, skill: SkillDefinition, *, binding_enabled: bool = True) -> bool:
        return skill.enabled and self._external_corpus_ready(skill) and binding_enabled

    def list_for_agent(self, agent_id: str) -> list[tuple[SkillDefinition, bool]]:
        self._ensure_loaded()
        agent = self.repository.get_agent(agent_id)
        agent_owner_user_id = agent.owner_user_id if agent is not None else next(
            (user.id for user in self.repository.users if user.personal_agent_id == agent_id),
            None,
        )
        agent_owner = self.repository.get_user(agent_owner_user_id) if agent_owner_user_id is not None else None
        bindings = {binding.skill_id: binding for binding in self.repository.list_agent_skill_bindings(agent_id)}
        learned_skills = {skill.id: skill for skill in self.repository.learned_skills}
        result: list[tuple[SkillDefinition, bool]] = []
        for skill in self._skills.values():
            owner_user_id = skill.metadata.get("owner_user_id")
            learned_scope = skill.metadata.get("learned_scope", "private")
            learned_skill_id = skill.metadata.get("learned_skill_id")
            if learned_skill_id is not None or skill.source_path.startswith("learned://"):
                learned = learned_skills.get(learned_skill_id or "")
                if (
                    learned is None
                    or learned.status != SkillStatus.ACTIVE
                    or agent_owner is None
                    or not self.repository.learned_skill_visible_to_user(
                        learned,
                        agent_owner.id,
                        project_id=agent_owner.default_project_id,
                    )
                ):
                    continue
            elif owner_user_id and learned_scope == "private" and agent_owner_user_id != owner_user_id:
                continue
            binding = bindings.get(skill.id)
            effective_enabled = self.is_runtime_enabled(
                skill,
                binding_enabled=binding is None or binding.enabled,
            )
            if binding is not None and binding.aliases:
                skill = skill.model_copy(update={"aliases": sorted(set([*skill.aliases, *binding.aliases]))})
            result.append((skill, effective_enabled))
        return sorted(result, key=lambda item: item[0].name)

    def list_enabled(self, agent_id: str | None = None) -> list[SkillDefinition]:
        if agent_id is None:
            self._ensure_loaded()
            return sorted(
                (skill for skill in self._skills.values() if skill.enabled and self._external_corpus_ready(skill)),
                key=lambda item: item.name,
            )
        return [skill for skill, enabled in self.list_for_agent(agent_id) if enabled]

    def get_by_name(self, name: str, agent_id: str | None = None) -> SkillDefinition | None:
        normalized = name.removeprefix("$").strip()
        for skill in self.list_enabled(agent_id):
            aliases = {alias.removeprefix("$") for alias in skill.aliases}
            if skill.name == normalized or normalized in aliases:
                return skill
        return None

    def resolve_command(self, content: str, agent_id: str | None = None) -> ResolvedSkill | None:
        text = content.strip()
        if not text.startswith("$"):
            return None
        command, _, argument = text.partition(" ")
        skill = self.get_by_name(command, agent_id)
        if skill is None:
            return None
        return ResolvedSkill(definition=skill, command=command, argument=argument.strip())

    def get_profile(self, skill_id: str):  # noqa: ANN201
        return self.repository.get_skill_capability_profile(skill_id)

    def supported_tool_names(self) -> set[str]:
        """Return tool names backed by a configured AgentMesh runtime adapter."""
        from agentmesh.tool_runtime.gateway import BUILTIN_TOOL_NAMES
        from agentmesh.tool_runtime.mcp import load_mcp_config

        definitions = {tool.id: tool for tool in self.repository.tool_definitions if tool.enabled}
        names = {tool.name for tool in definitions.values() if tool.name in BUILTIN_TOOL_NAMES}
        try:
            mcp_config = load_mcp_config()
        except (OSError, ValueError):
            return names
        names.update(
            definition.name
            for server in mcp_config.servers
            if (definition := definitions.get(server.tool_id)) is not None
        )
        return names

    def to_chat_skill(
        self,
        skill: SkillDefinition,
        *,
        enabled: bool = True,
        binding_enabled: bool = True,
        supported_tool_names: set[str] | None = None,
    ) -> dict[str, object]:
        aliases = [alias if alias.startswith("$") else f"${alias}" for alias in skill.aliases]
        usage_suffix = f" {skill.argument_hint}" if skill.argument_hint else " <input>"
        stored_profile = self.get_profile(skill.id)
        profile = (
            stored_profile
            if stored_profile is not None and stored_profile.planner_eligible
            else None
        )
        profile_current = profile_matches_skill(profile, skill) if profile is not None else False
        runtime_ready = self.is_runtime_enabled(skill)
        primary_stage = profile.primary_stage if profile is not None else _metadata_primary_stage(skill)
        supported_tools = supported_tool_names if supported_tool_names is not None else self.supported_tool_names()
        missing_tools = sorted(set(skill.requested_tools) - supported_tools)
        execution_readiness = "unavailable" if not runtime_ready else "tool_limited" if missing_tools else "complete"
        payload: dict[str, object] = {
            "id": skill.id,
            "command": skill.command,
            "title": skill.title,
            "description": _display_description(skill, profile),
            "usage": f"{skill.command}{usage_suffix}" if skill.requires_input else skill.command,
            "placeholder": skill.argument_hint or f"Enter input for {skill.title}",
            "aliases": aliases,
            "requires_input": skill.requires_input,
            "source": skill.source_scope.value,
            "version": skill.version,
            "activation_policy": skill.activation_policy.value,
            "enabled": enabled,
            "binding_enabled": binding_enabled,
            "planner_eligible": bool(
                profile
                and profile.planner_eligible
                and profile_current
                and runtime_ready
                and enabled
                and not missing_tools
            ),
            "readiness": "ready" if runtime_ready else "unavailable",
            "execution_readiness": execution_readiness,
            "missing_tools": missing_tools,
        }
        if primary_stage is not None:
            payload["primary_stage"] = primary_stage.value
        if profile is not None:
            payload.update(
                {
                    "capability_type": profile.capability_type.value,
                    "input_kinds": profile.input_kinds,
                    "output_kinds": profile.output_kinds,
                    "side_effect": profile.side_effect.value,
                }
            )
        return payload


_catalog_service = SkillCatalogService(store)


def catalog_service() -> SkillCatalogService:
    return _catalog_service


def ensure_skill_catalog(repository: SQLiteStore) -> list[SkillDefinition]:
    if repository is store:
        return _catalog_service.reload()
    return SkillCatalogService(repository).reload()
