from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agentmesh.models import SkillDefinition, SkillSourceScope, now_utc
from agentmesh.skill_runtime.discovery import SkillDiagnostic, SkillRoot, discover_skills
from agentmesh.store import SQLiteStore, store

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
BUILTIN_SKILLS_DIR = ROOT_DIR / "agentmesh" / "builtin_skills"


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
                    current[name] = existing
                    continue
            skill.updated_at = now_utc()
            current[name] = self.repository.save_skill_definition(skill)
        for stored in self.repository.skill_definitions:
            if stored.source_path.startswith("learned://") and stored.enabled and stored.name not in current:
                current[stored.name] = stored
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
        configured = os.getenv("AGENTMESH_WIKI_ROOT", "").strip()
        return bool(configured and Path(configured).expanduser().is_dir())

    def list_for_agent(self, agent_id: str) -> list[tuple[SkillDefinition, bool]]:
        self._ensure_loaded()
        agent = self.repository.get_agent(agent_id)
        agent_owner_user_id = agent.owner_user_id if agent is not None else next(
            (user.id for user in self.repository.users if user.personal_agent_id == agent_id),
            None,
        )
        bindings = {binding.skill_id: binding for binding in self.repository.list_agent_skill_bindings(agent_id)}
        result: list[tuple[SkillDefinition, bool]] = []
        for skill in self._skills.values():
            owner_user_id = skill.metadata.get("owner_user_id")
            learned_scope = skill.metadata.get("learned_scope", "private")
            if owner_user_id and learned_scope == "private" and agent_owner_user_id != owner_user_id:
                continue
            binding = bindings.get(skill.id)
            effective_enabled = (
                skill.enabled
                and self._external_corpus_ready(skill)
                and (binding is None or binding.enabled)
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

    @staticmethod
    def to_chat_skill(skill: SkillDefinition, *, enabled: bool = True) -> dict[str, object]:
        aliases = [alias if alias.startswith("$") else f"${alias}" for alias in skill.aliases]
        usage_suffix = f" {skill.argument_hint}" if skill.argument_hint else " <input>"
        return {
            "id": skill.id,
            "command": skill.command,
            "title": skill.title,
            "description": skill.description,
            "usage": f"{skill.command}{usage_suffix}" if skill.requires_input else skill.command,
            "placeholder": skill.argument_hint or f"Enter input for {skill.title}",
            "aliases": aliases,
            "requires_input": skill.requires_input,
            "source": skill.source_scope.value,
            "version": skill.version,
            "activation_policy": skill.activation_policy.value,
            "enabled": enabled,
        }


_catalog_service = SkillCatalogService(store)


def catalog_service() -> SkillCatalogService:
    return _catalog_service


def ensure_skill_catalog(repository: SQLiteStore) -> list[SkillDefinition]:
    if repository is store:
        return _catalog_service.reload()
    return SkillCatalogService(repository).reload()
