from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from agentmesh.models import AgentToolGrant
from agentmesh.research_orchestration.v3.actor_adapters import (
    ActorAdapterError,
    ActorModelCallReceiptV3,
    AgentSdkSkillAdapterV3,
    ModelRuntimeIdentityV3,
    StructuredModelResponseV3,
    TavilyGatewayResponseV3,
    TavilyProviderIdentityV3,
    TavilyToolCallReceiptV3,
    TavilyToolGatewayAdapterV3,
    tool_operation_key_v3,
)
from agentmesh.research_orchestration.v3.adapter_registry import (
    COMPETITIVE_TEXT_ADAPTER_DECLARATIONS_V3,
)
from agentmesh.research_orchestration.v3.adapter_resources import CompetitiveTextResourceLoaderV3
from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_bytes, canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import load_competitive_text_catalog
from agentmesh.research_orchestration.v3.common import SealedArtifactRefV3, freeze_json_object
from agentmesh.research_orchestration.v3.execution import StepApprovalProofV3
from agentmesh.research_orchestration.v3.execution_plan import PlanStepV3
from agentmesh.research_orchestration.v3.planning.capabilities import _catalog_snapshot_documents
from agentmesh.research_orchestration.v3.ports import ActorExecutionRequestV3
from agentmesh.research_orchestration.v3.snapshots import (
    FrozenActorV3,
    FrozenDocumentV3,
    FrozenModelPolicyV3,
    ResearchControlSnapshotV3,
)
from agentmesh.tool_runtime.gateway import ToolRuntimeDescriptor
from agentmesh.tools import SYSTEM_TOOLS

NOW = datetime(2026, 8, 21, 1, 2, 3, tzinfo=UTC)
MODEL_POLICY = FrozenModelPolicyV3(
    requested_provider="openai_agents_sdk",
    requested_model="gpt-test",
    structured_output_mode="json_schema",
    adapter_compatibility_id="openai-agents-sdk.chat-completions.json-schema:v1",
)


def _schema_document(document_id: str, content: dict[str, object]) -> FrozenDocumentV3:
    return FrozenDocumentV3(
        document_id=document_id,
        kind="json_schema",
        media_type="application/json",
        content_hash=canonical_json_v3_sha256(content),
        size_bytes=len(canonical_json_v3_bytes(content)),
        content=content,
    )


def _snapshot(
    actor: FrozenActorV3,
    *,
    extra_documents: tuple[FrozenDocumentV3, ...] = (),
) -> ResearchControlSnapshotV3:
    catalog = load_competitive_text_catalog()
    documents = _catalog_snapshot_documents(catalog)
    for document in extra_documents:
        documents[document.document_id] = document
    return ResearchControlSnapshotV3(
        schema_version="research-control-snapshot-v3",
        catalog_id="competitive-text-v1",
        catalog_hash=catalog.catalog_hash,
        resolved_for_agent_id="agent_test",
        resolved_at=NOW,
        model_policy=MODEL_POLICY,
        actors=(actor,),
        documents=tuple(sorted(documents.values(), key=lambda item: item.document_id)),
    )


def _request(
    snapshot: ResearchControlSnapshotV3,
    actor: FrozenActorV3,
    *,
    resolved_input: dict[str, object],
    requires_approval: bool,
) -> ActorExecutionRequestV3:
    step_values = {
        "step_number": 1,
        "name": "Adapter contract",
        "actor_type": actor.actor_type,
        "actor_id": actor.actor_id,
        "question_ids": ("question_1",),
        "depends_on": (),
        "input": resolved_input,
        "input_bindings": (),
        "expected_outputs": ({"pointer": "/results", "description": "Result"},),
        "acceptance_criteria": ("Return a structured result.",),
        "required": True,
        "requires_approval": requires_approval,
        "approval_role": "owner" if requires_approval else None,
        "timeout_seconds": 30,
        "max_sends": 1,
        "invocation_semantics": {
            "tool": "tool_read",
            "skill": "skill_once",
            "llm": "llm_once",
            "reviewer": "reviewer_once",
        }[actor.actor_type],
        "actor_snapshot_hash": canonical_json_v3_sha256(actor),
        "input_schema_hash": next(
            item.content_hash
            for item in snapshot.documents
            if item.document_id == actor.input_schema_document_id
        ),
        "output_schema_hash": next(
            item.content_hash
            for item in snapshot.documents
            if item.document_id == actor.output_schema_document_id
        ),
    }
    step_values["contract_hash"] = canonical_json_v3_sha256(step_values)
    step = PlanStepV3.model_validate(step_values)
    snapshot_hash = canonical_json_v3_sha256(snapshot)
    return ActorExecutionRequestV3(
        run_id="run_test",
        plan_version_id="plan_test",
        attempt_id="attempt_test",
        control_snapshot_artifact=SealedArtifactRefV3(
            artifact_id=f"artifact_snapshot_{snapshot_hash[:24]}",
            kind="research_control_snapshot",
            schema_version="research-control-snapshot-v3",
            content_hash=snapshot_hash,
        ),
        step=step,
        resolved_input=resolved_input,
    )


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Settlement:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def settle_actor_result(self, *, request, receipt, content, schema_version):
        self.calls.append(
            {
                "request": request,
                "receipt": receipt,
                "content": content,
                "schema_version": schema_version,
            }
        )
        digest = canonical_json_v3_sha256(content)
        return SealedArtifactRefV3(
            artifact_id=f"artifact_result_{digest[:24]}",
            kind="actor_result",
            schema_version=schema_version,
            content_hash=digest,
        )


class _ApprovalReader:
    def __init__(self, available: bool) -> None:
        self.available = available

    def read_step_approval(self, request: ActorExecutionRequestV3):
        if not self.available:
            return None
        return StepApprovalProofV3(
            run_id=request.run_id,
            plan_version_id=request.plan_version_id,
            attempt_id=request.attempt_id,
            step_number=request.step.step_number,
            role="owner",
            decision="approved",
            receipt_id="approval_receipt_test",
        )


class _Gateway:
    def __init__(self, *, missing_receipt: bool = False) -> None:
        self.missing_receipt = missing_receipt
        self.calls: list[dict[str, object]] = []
        self.definition = next(item for item in SYSTEM_TOOLS if item.id == "tool_web_research")
        self.grant = AgentToolGrant(
            id="grant_test",
            agent_id="agent_test",
            tool_id="tool_web_research",
            granted_by="owner_test",
        )

    def get_tool_definition(self, tool_id: str):
        return self.definition if tool_id == self.definition.id else None

    def list_agent_tool_grants(self, agent_id: str):
        return (self.grant,) if agent_id == self.grant.agent_id else ()

    def describe(self, gateway_name: str):
        if gateway_name != "web_research":
            return None
        return ToolRuntimeDescriptor(
            implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
            implementation_version="1",
            execution_mode="real",
            health_state="healthy",
            health_checked_at=NOW,
        )

    def provider_identity(self, gateway_name: str):
        if gateway_name != "web_research":
            return None
        return TavilyProviderIdentityV3(provider="tavily", mode="real")

    async def invoke(self, *, request, arguments, operation_key, approval_proof):
        self.calls.append(
            {
                "request": request,
                "arguments": arguments,
                "operation_key": operation_key,
                "approval_proof": approval_proof,
            }
        )
        payload = freeze_json_object(
            {
                "answer": None,
                "response_time": 1,
                "results": [
                    {
                        "title": "Alpha token=title-secret",
                        "url": "https://user:password@example.test/alpha?api_key=url-secret",
                        "snippet": "Bearer snippet-secret; password=body-secret",
                        "score": 1,
                        "published_date": None,
                    }
                ],
            }
        )
        receipt = None
        if not self.missing_receipt:
            receipt = TavilyToolCallReceiptV3(
                id="tool_receipt_test",
                operation_key=operation_key,
                provider="tavily",
                gateway_name="web_research",
                implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
                implementation_version="1",
                execution_mode="real",
                provider_request_id="provider_request_test",
                result_count=1,
            )
        return TavilyGatewayResponseV3(payload=payload, receipt=receipt)


def _tool_context(*, approval: bool = True, missing_receipt: bool = False):
    actor = FrozenActorV3(
        actor_type="tool",
        actor_id="tavily-web-search",
        implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
        implementation_version="1",
        execution_mode="real",
        enabled=True,
        eligible=True,
        tier="core",
        approval_role="owner",
        required_tool_ids=(),
        optional_tool_ids=(),
        input_schema_document_id="source-tavily-input-schema",
        output_schema_document_id="source-tavily-output-schema",
    )
    snapshot = _snapshot(actor)
    request = _request(
        snapshot,
        actor,
        resolved_input={"query": "Alpha comparison", "max_results": 5},
        requires_approval=True,
    )
    gateway = _Gateway(missing_receipt=missing_receipt)
    settlement = _Settlement()
    adapter = TavilyToolGatewayAdapterV3(
        snapshot=snapshot,
        frozen_actor=actor,
        gateway=gateway,
        approvals=_ApprovalReader(approval),
        settlement=settlement,
        clock=_Clock(),
    )
    return adapter, request, gateway, settlement


def test_tavily_adapter_requires_explicit_approval_before_provider_call() -> None:
    adapter, request, gateway, settlement = _tool_context(approval=False)

    with pytest.raises(ActorAdapterError, match="tool_approval_proof_missing"):
        asyncio.run(adapter.execute(request))

    assert gateway.calls == []
    assert settlement.calls == []


def test_tavily_adapter_requires_receipt_and_operation_key() -> None:
    adapter, request, gateway, settlement = _tool_context(missing_receipt=True)

    with pytest.raises(ActorAdapterError, match="tool_call_receipt_missing"):
        asyncio.run(adapter.execute(request))

    assert gateway.calls[0]["operation_key"] == tool_operation_key_v3(request)
    assert settlement.calls == []


def test_tavily_adapter_redacts_and_normalizes_only_public_sources() -> None:
    adapter, request, gateway, settlement = _tool_context()

    result = asyncio.run(adapter.execute(request))

    assert result.receipt_id == "tool_receipt_test"
    persisted = settlement.calls[0]["content"]
    encoded = str(persisted)
    assert "title-secret" not in encoded
    assert "url-secret" not in encoded
    assert "snippet-secret" not in encoded
    assert "body-secret" not in encoded
    source = persisted["output"]["results"][0]
    assert source["url"] == "https://example.test/alpha"
    assert source["registrable_domain"] == "example.test"
    assert source["redaction"] == "masked"
    assert persisted["redacted_output_hash"] == canonical_json_v3_sha256(persisted["output"])
    assert gateway.calls[0]["approval_proof"].receipt_id == "approval_receipt_test"


class _ModelPort:
    def __init__(self, *, drift: bool = False, missing_receipt: bool = False) -> None:
        self.drift = drift
        self.missing_receipt = missing_receipt
        self.calls = []
        self.output = freeze_json_object(
            {
                "version": "skill-output-v2",
                "status": "succeeded",
                "summary": "Organized public evidence.",
                "findings": [],
                "assumptions": [],
                "limitations": ["Public sources only."],
                "recommendations": ["Verify material differences."],
                "payload": {"comparison": "Alpha"},
            }
        )

    def describe(self, policy: FrozenModelPolicyV3):
        return ModelRuntimeIdentityV3(
            requested_provider=policy.requested_provider,
            requested_model="drifted-model" if self.drift else policy.requested_model,
            actual_provider="FakeAgentSdkModel",
            actual_model="gpt-test-actual",
            structured_output_mode=policy.structured_output_mode,
            adapter_compatibility_id=policy.adapter_compatibility_id,
        )

    async def invoke(self, request):
        self.calls.append(request)
        if self.missing_receipt:
            return StructuredModelResponseV3(payload=self.output, receipt=None)
        return StructuredModelResponseV3(
            payload=self.output,
            receipt=ActorModelCallReceiptV3(
                id="model_receipt_test",
                call_key=request.call_key,
                actor_type=request.actor_type,
                actor_id=request.actor_id,
                requested_provider=request.model_policy.requested_provider,
                requested_model=request.model_policy.requested_model,
                actual_provider="FakeAgentSdkModel",
                actual_model="gpt-test-actual",
                model_policy_hash=request.model_policy_hash,
                instruction_hash=request.instruction_hash,
                prompt_hash=request.prompt_hash,
                rubric_hash=request.rubric_hash,
                input_hash=canonical_json_v3_sha256(request.resolved_input),
                output_hash=canonical_json_v3_sha256(self.output),
                provider_receipt_id="provider_model_request_test",
                usage={"requests": 1},
            ),
        )


def _skill_context(*, drift: bool = False, missing_receipt: bool = False):
    input_schema = _schema_document(
        "adapter-web-research-input-schema",
        {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "additionalProperties": False,
            "required": ["evidence", "research_goal"],
            "properties": {
                "evidence": {"type": "array"},
                "research_goal": {"type": "string", "minLength": 1},
            },
        },
    )
    actor = FrozenActorV3(
        actor_type="skill",
        actor_id="competitive-web-research",
        implementation_id=(
            "agentmesh.research_orchestration.v3.actor_adapters.AgentSdkSkillAdapterV3"
        ),
        implementation_version="1",
        execution_mode="model",
        enabled=True,
        eligible=True,
        required_tool_ids=("tavily-web-search",),
        optional_tool_ids=(),
        instruction_document_id="competitive-web-research-instructions",
        input_schema_document_id=input_schema.document_id,
        output_schema_document_id="source-skill-result-envelope-schema",
    )
    snapshot = _snapshot(actor, extra_documents=(input_schema,))
    request = _request(
        snapshot,
        actor,
        resolved_input={"evidence": [], "research_goal": "Compare Alpha"},
        requires_approval=False,
    )
    model = _ModelPort(drift=drift, missing_receipt=missing_receipt)
    settlement = _Settlement()
    adapter = AgentSdkSkillAdapterV3(
        snapshot=snapshot,
        frozen_actor=actor,
        model=model,
        settlement=settlement,
        resources=CompetitiveTextResourceLoaderV3(),
    )
    return adapter, request, model, settlement, actor


def test_skill_adapter_rejects_model_drift_before_call() -> None:
    adapter, request, model, settlement, _actor = _skill_context(drift=True)

    with pytest.raises(ActorAdapterError, match="model_policy_drifted"):
        asyncio.run(adapter.execute(request))

    assert model.calls == []
    assert settlement.calls == []


def test_skill_adapter_rejects_missing_model_call_receipt() -> None:
    adapter, request, model, settlement, _actor = _skill_context(missing_receipt=True)

    with pytest.raises(ActorAdapterError, match="model_call_receipt_missing"):
        asyncio.run(adapter.execute(request))

    assert len(model.calls) == 1
    assert settlement.calls == []


def test_skill_adapter_has_no_hidden_tool_access_despite_frozen_requirement() -> None:
    adapter, request, model, settlement, actor = _skill_context()

    result = asyncio.run(adapter.execute(request))

    assert actor.required_tool_ids == ("tavily-web-search",)
    assert model.calls[0].tool_names == ()
    assert model.calls[0].resources == ()
    assert result.receipt_id == "model_receipt_test"
    assert settlement.calls[0]["content"]["output"]["payload"] == {"comparison": "Alpha"}


def test_adapter_declaration_rejects_frozen_implementation_identity_drift() -> None:
    declaration = next(
        item
        for item in COMPETITIVE_TEXT_ADAPTER_DECLARATIONS_V3
        if (item.actor_type, item.actor_id) == ("skill", "competitive-web-research")
    )
    _adapter, _request_value, _model, _settlement, actor = _skill_context()
    drifted = actor.model_copy(update={"implementation_version": "0"})

    with pytest.raises(ValueError, match="does not match"):
        declaration.registration(drifted, _adapter)

    assert declaration.result_identity.implementation_id == declaration.implementation_id
    assert declaration.result_identity.execution_mode == declaration.execution_mode
    assert not hasattr(declaration.result_identity, "implementation_version")
