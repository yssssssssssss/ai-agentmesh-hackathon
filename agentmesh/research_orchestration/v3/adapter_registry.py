from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from agentmesh.research_orchestration.v3.common import ActorType
from agentmesh.research_orchestration.v3.execution import (
    ActorAdapterRegistrationV3,
    ActorExecutionAdapter,
)
from agentmesh.research_orchestration.v3.snapshots import FrozenActorV3, ResearchControlSnapshotV3


@dataclass(frozen=True, slots=True)
class ActorResultImplementationIdentityV3:
    """The implementation identity representable by ActorExecutionResultV3.

    Implementation version remains a registry/frozen-snapshot check. The result
    contract intentionally carries only implementation ID plus execution mode.
    """

    implementation_id: str
    execution_mode: Literal["real", "model", "deterministic"]


@dataclass(frozen=True, slots=True)
class CompetitiveTextAdapterDeclarationV3:
    actor_type: ActorType
    actor_id: str
    implementation_id: str
    implementation_version: str
    execution_mode: Literal["real", "model", "deterministic"]

    @property
    def result_identity(self) -> ActorResultImplementationIdentityV3:
        return ActorResultImplementationIdentityV3(
            implementation_id=self.implementation_id,
            execution_mode=self.execution_mode,
        )

    def registration(
        self,
        frozen_actor: FrozenActorV3,
        adapter: ActorExecutionAdapter,
    ) -> ActorAdapterRegistrationV3:
        if (
            frozen_actor.actor_type,
            frozen_actor.actor_id,
            frozen_actor.implementation_id,
            frozen_actor.implementation_version,
            frozen_actor.execution_mode,
        ) != (
            self.actor_type,
            self.actor_id,
            self.implementation_id,
            self.implementation_version,
            self.execution_mode,
        ):
            raise ValueError("adapter declaration does not match the FrozenActorV3 identity")
        return ActorAdapterRegistrationV3(
            actor_type=self.actor_type,
            actor_id=self.actor_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            execution_mode=self.execution_mode,
            adapter=adapter,
        )


COMPETITIVE_TEXT_ADAPTER_DECLARATIONS_V3 = (
    CompetitiveTextAdapterDeclarationV3(
        actor_type="llm",
        actor_id="competitive-text-synthesis-v1",
        implementation_id=(
            "agentmesh.research_orchestration.v3.actor_adapters.LlmSynthesisAdapterV3"
        ),
        implementation_version="1",
        execution_mode="model",
    ),
    CompetitiveTextAdapterDeclarationV3(
        actor_type="reviewer",
        actor_id="competitive-text-quality-reviewer-v1",
        implementation_id=(
            "agentmesh.research_orchestration.v3.actor_adapters.ReviewerAdapterV3"
        ),
        implementation_version="1",
        execution_mode="model",
    ),
    CompetitiveTextAdapterDeclarationV3(
        actor_type="skill",
        actor_id="competitive-analysis",
        implementation_id=(
            "agentmesh.research_orchestration.v3.actor_adapters.AgentSdkSkillAdapterV3"
        ),
        implementation_version="1",
        execution_mode="model",
    ),
    CompetitiveTextAdapterDeclarationV3(
        actor_type="skill",
        actor_id="competitive-web-research",
        implementation_id=(
            "agentmesh.research_orchestration.v3.actor_adapters.AgentSdkSkillAdapterV3"
        ),
        implementation_version="1",
        execution_mode="model",
    ),
    CompetitiveTextAdapterDeclarationV3(
        actor_type="tool",
        actor_id="tavily-web-search",
        implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
        implementation_version="1",
        execution_mode="real",
    ),
)


def competitive_text_adapter_registrations_v3(
    *,
    snapshot: ResearchControlSnapshotV3,
    adapters: Mapping[tuple[str, str], ActorExecutionAdapter],
) -> tuple[ActorAdapterRegistrationV3, ...]:
    """Bind the complete locked declaration set to one sealed control snapshot.

    This declaration helper is not called by any production composition root.
    """

    declarations = {
        (item.actor_type, item.actor_id): item
        for item in COMPETITIVE_TEXT_ADAPTER_DECLARATIONS_V3
    }
    frozen = {(item.actor_type, item.actor_id): item for item in snapshot.actors}
    if set(frozen) != set(declarations) or set(adapters) != set(declarations):
        raise ValueError("Competitive Text adapter registry must exactly cover the frozen Actor set")
    return tuple(
        declarations[key].registration(frozen[key], adapters[key])
        for key in sorted(declarations)
    )
