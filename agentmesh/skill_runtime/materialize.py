from __future__ import annotations

import hashlib
import json

from agentmesh.models import LearnedSkill, SkillActivationPolicy, SkillDefinition, SkillSourceScope
from agentmesh.store import SQLiteStore


def materialize_learned_skill(repository: SQLiteStore, learned: LearnedSkill) -> SkillDefinition:
    name = f"learned-{learned.id.rsplit('_', 1)[-1]}"[:64].rstrip("-")
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(learned.steps, 1)) or "1. Follow the validated workflow."
    validation = "\n".join(f"- {rule}" for rule in learned.validation_rules) or "- Return a source-bound result."
    instructions = f"""# {learned.title}

## Trigger

{learned.trigger_pattern}

## Steps

{steps}

## Validation

{validation}
"""
    digest = hashlib.sha256(instructions.encode("utf-8")).hexdigest()
    existing = next(
        (
            skill
            for skill in repository.skill_definitions
            if skill.metadata.get("learned_skill_id") == learned.id
        ),
        None,
    )
    definition = SkillDefinition(
        id=existing.id if existing else f"skilldef_learned_{learned.id.rsplit('_', 1)[-1]}",
        name=name,
        title=learned.title[:160],
        description=f"Learned workflow for: {learned.trigger_pattern}"[:1024],
        instructions=instructions,
        source_path=f"learned://{learned.id}/SKILL.md",
        source_scope=SkillSourceScope.WORKSPACE,
        content_hash=digest,
        version=str(learned.version),
        metadata={
            "learned_skill_id": learned.id,
            "owner_user_id": learned.user_id or "",
            "learned_scope": learned.scope.value,
            "source_workflow_ids": json.dumps(learned.source_workflow_ids),
        },
        activation_policy=SkillActivationPolicy.EXPLICIT_ONLY,
        created_at=existing.created_at if existing else learned.created_at,
    )
    return repository.save_skill_definition(definition)
