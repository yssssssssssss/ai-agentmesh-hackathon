from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from agentmesh.acquisition import AcquisitionResult
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.models import AgentRun, AgentRunStatus, Source
from agentmesh.research_orchestration.capabilities import (
    CapabilityResolutionError,
    CompetitiveCapabilityResolver,
)
from agentmesh.research_orchestration.compiler import (
    CompetitiveCapabilitySnapshot,
    CompetitivePlanCompiler,
    FrozenDocument,
    FrozenModelPolicy,
    FrozenResourceSnapshot,
    FrozenSkillActor,
    FrozenTextDocument,
    FrozenToolActor,
    PlanCompileError,
    recompute_plan_hash,
    validate_execution_plan_version,
)
from agentmesh.research_orchestration.contracts import (
    AmbiguityCode,
    ResearchAssumption,
    ResearchConstraint,
    SuccessCriterion,
    canonical_json_bytes,
    canonical_sha256,
)
from agentmesh.research_orchestration.planning import (
    CompetitiveRequirementPlanner,
    is_competitive_research_request,
    requirement_version_from_result,
)
from agentmesh.seed import PROJECT, USER, WORKSPACE, ensure_seed_data
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.gateway import ToolGateway
from agentmesh.tools import WEB_RESEARCH_OUTPUT_SCHEMA


def _frozen(content) -> FrozenDocument:  # noqa: ANN001
    return FrozenDocument(content=content, content_hash=canonical_sha256(content))


def _frozen_text(content: str) -> FrozenTextDocument:
    return FrozenTextDocument(content=content, content_hash=hashlib.sha256(content.encode()).hexdigest())


def _snapshot(*, now: datetime, **tool_updates) -> CompetitiveCapabilitySnapshot:  # noqa: ANN003
    skill_text = "---\nname: competitive-analysis\n---\nUse only supplied verified evidence.\n"
    skill_hash = hashlib.sha256(skill_text.encode()).hexdigest()
    profile_text = f'''skill_version: "1"
skill_content_hash: {skill_hash}
task_types: [competitive_research]
archetypes: [evidence_synthesis]
required_tools: [tool_web_research]
required_resources: [wiki.corpus]
input_schema_ref: input.schema.json
output_schema_ref: output.schema.json
produces_factual_claims: true
report_policy: default
planner_eligible: true
'''
    skill_root = Path(__file__).parents[1] / "agentmesh" / "builtin_skills" / "competitive-analysis"
    input_schema = json.loads((skill_root / "input.schema.json").read_text(encoding="utf-8"))
    output_schema = json.loads((skill_root / "output.schema.json").read_text(encoding="utf-8"))
    evidence_inputs_schema = input_schema["properties"]["evidence_inputs"]
    published_output_schema = {
        "type": "object",
        "required": ["evidence_inputs"],
        "properties": {"evidence_inputs": evidence_inputs_schema},
        "additionalProperties": False,
    }
    instructions = _frozen_text(skill_text)
    profile = _frozen_text(profile_text)
    skill = FrozenSkillActor(
        skill_id="skill_competitive",
        skill_name="competitive-analysis",
        skill_version="1",
        skill_content_hash=instructions.content_hash,
        profile_content_hash=profile.content_hash,
        enabled=True,
        binding_enabled=True,
        planner_eligible=True,
        task_types=["competitive_research"],
        archetypes=["evidence_synthesis"],
        required_tools=["tool_web_research"],
        required_resources=["wiki.corpus"],
        input_schema_ref="input.schema.json",
        output_schema_ref="output.schema.json",
        produces_factual_claims=True,
        report_policy="default",
        instructions=instructions,
        profile=profile,
        input_schema=_frozen(input_schema),
        output_schema=_frozen(output_schema),
    )
    tool_payload = {
        "tool_id": "tool_web_research",
        "tool_name": "web_research",
        "implementation_id": "agentmesh.web_research.tavily",
        "implementation_version": "1",
        "execution_mode": "real",
        "enabled": True,
        "granted": True,
        "grant_id": "grant_web",
        "granted_to_agent_id": "agent_research",
        "health_state": "healthy",
        "health_checked_at": now,
        "health_ttl_seconds": 60,
        "side_effect": "read",
        "idempotency_support": "none",
        "approval_required": True,
        "evidence_class": "provider_summary",
        "timeout_seconds": 45,
        "input_schema": _frozen(
            {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}
        ),
        "output_schema": _frozen(WEB_RESEARCH_OUTPUT_SCHEMA),
        "published_output_schema": _frozen(published_output_schema),
    }
    tool_payload.update(tool_updates)
    resource_manifest = {
        "files": [
            {
                "path": "methods/toolbox/analysis/competitive-analysis.md",
                "content_hash": "3" * 64,
                "size_bytes": 42,
            }
        ]
    }
    resource_document = _frozen(resource_manifest)
    return CompetitiveCapabilitySnapshot(
        resolved_for_agent_id="agent_research",
        resolved_at=now,
        model_policy=FrozenModelPolicy(
            requested_model_id="gpt-primary",
            structured_output_mode="json_schema",
            adapter_compatibility_id="openai-agents-sdk.chat-completions.json-schema:v1",
        ),
        skill=skill,
        tool=FrozenToolActor(**tool_payload),
        resource_snapshot=FrozenResourceSnapshot(
            artifact_id="artifact_resource_snapshot",
            content_hash=resource_document.content_hash,
            size_bytes=len(canonical_json_bytes(resource_manifest)),
            manifest=resource_document,
        ),
        deliverable_contract=_frozen(
            {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}}
        ),
        evidence_policy=_frozen({"version": "v1", "minimum_sources": 2}),
        review_rubric=_frozen({"version": "v1", "required_evidence_coverage": 1}),
    )


def test_canonical_json_is_unicode_and_key_order_stable_and_rejects_floats() -> None:
    decomposed = "e\u0301"
    composed = "é"

    assert canonical_json_bytes({"b": decomposed, "a": 1}) == canonical_json_bytes({"a": 1, "b": composed})
    assert canonical_sha256({"b": decomposed, "a": 1}) == canonical_sha256({"a": 1, "b": composed})
    with pytest.raises(TypeError):
        canonical_json_bytes({"cost": 0.1})


def test_clear_competitive_request_creates_requirement_without_clarification() -> None:
    result = asyncio.run(
        CompetitiveRequirementPlanner().plan(
            "对比三款面向企业产品团队的 AI 研究助手，重点分析证据可追溯、任务恢复和协作能力，给出适用场景与局限。",
            model=None,
        )
    )

    assert not result.blocking
    assert result.requirement.competitor_scope is not None
    assert result.requirement.clarification_questions == []
    assert result.requirement.task_type == "competitive_research"
    assert result.problem_contract.success_criterion_ids == [
        "sc_evidence_comparison",
        "sc_scenarios",
        "sc_recommendations",
    ]
    assert all(
        not question.factual or question.evidence_requirement is not None
        for question in result.problem_contract.questions
    )


def test_missing_competitor_scope_blocks_once_and_answer_creates_new_version() -> None:
    planner = CompetitiveRequirementPlanner()
    first = asyncio.run(planner.plan("帮我做竞品分析", model=None))
    first_version = requirement_version_from_result("run_1", 1, first)

    answered = asyncio.run(
        planner.plan(
            "帮我做竞品分析",
            clarification_answers={"clarify_competitor_scope": "选择三款面向企业产品团队的 AI 研究助手"},
            model=None,
        )
    )
    second_version = requirement_version_from_result("run_1", 2, answered)

    assert first.blocking
    assert first.requirement.ambiguities[0].code == AmbiguityCode.MISSING_COMPETITOR_SCOPE
    assert len(first.requirement.clarification_questions) == 1
    assert not answered.blocking
    assert answered.requirement.competitor_scope == "三款面向企业产品团队的 AI 研究助手"
    assert first_version.version == 1
    assert second_version.version == 2
    assert first_version.content_hash != second_version.content_hash
    assert first_version.payload["requirement"]["competitor_scope"] is None


def test_natural_and_explicit_routing_share_competitive_boundary() -> None:
    assert is_competitive_research_request("对比淘宝和拼多多的协作能力并分析差异")
    assert is_competitive_research_request("淘宝、拼多多和京东的购物车体验、会员体系与履约能力分别如何？")
    assert is_competitive_research_request("任意参数", explicit_skill_name="$competitive-analysis")
    assert not is_competitive_research_request("用尼尔森原则检查竞品页面的可用性问题")
    assert not is_competitive_research_request("生成一份访谈提纲")


def test_compiler_freezes_one_tool_to_skill_plan_with_reproducible_hash() -> None:
    now = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    result = asyncio.run(
        CompetitiveRequirementPlanner().plan("对比淘宝与拼多多的企业协作能力、场景和局限", model=None)
    )
    requirement = requirement_version_from_result("run_1", 1, result)
    plan = CompetitivePlanCompiler().compile(requirement, _snapshot(now=now), plan_version=1, now=now)

    assert plan.plan_hash == recompute_plan_hash(plan)
    assert plan.payload["recommended"] is True
    assert [(step["actor_type"], step["actor_id"]) for step in plan.payload["steps"]] == [
        ("tool", "tool_web_research"),
        ("skill", "skill_competitive"),
    ]
    assert plan.payload["steps"][1]["depends_on"] == [1]
    assert plan.payload["steps"][1]["input_bindings"] == [
        {"source_step": 1, "source_pointer": "/evidence_inputs", "target_pointer": "/evidence_inputs"}
    ]
    assert "淘宝与拼多多" in plan.payload["steps"][0]["initial_input"]["query"]
    question_queries = plan.payload["steps"][0]["initial_input"]["question_queries"]
    assert 1 <= len(question_queries) <= 4
    assert all(item["question_ids"] for item in question_queries)
    assert any("q_scenarios" in item["question_ids"] for item in question_queries)
    validate_execution_plan_version(plan)
    assert {"review", "report"}.isdisjoint(step["actor_type"] for step in plan.payload["steps"])


@pytest.mark.parametrize(
    ("tool_updates", "expected_code"),
    [
        ({"execution_mode": "fake"}, "tool_not_real"),
        ({"granted": False}, "tool_not_authorized"),
        ({"health_state": "unavailable"}, "tool_unhealthy"),
        ({"health_checked_at": datetime(2026, 8, 19, 9, 58, tzinfo=UTC)}, "tool_health_stale"),
        ({"health_checked_at": datetime(2026, 8, 19, 10, 1, tzinfo=UTC)}, "tool_health_from_future"),
    ],
)
def test_compiler_fails_closed_for_ineligible_tool(tool_updates, expected_code) -> None:  # noqa: ANN001
    now = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    result = asyncio.run(
        CompetitiveRequirementPlanner().plan("对比淘宝与拼多多的企业协作能力、场景和局限", model=None)
    )
    requirement = requirement_version_from_result("run_1", 1, result)

    with pytest.raises(PlanCompileError) as captured:
        CompetitivePlanCompiler().compile(
            requirement,
            _snapshot(now=now, **tool_updates),
            plan_version=1,
            now=now,
        )

    assert expected_code in captured.value.codes


def test_compiler_rejects_blocked_or_tampered_requirement() -> None:
    now = datetime.now(UTC)
    blocked = asyncio.run(CompetitiveRequirementPlanner().plan("帮我做竞品分析", model=None))
    requirement = requirement_version_from_result("run_1", 1, blocked)

    with pytest.raises(PlanCompileError) as blocked_error:
        CompetitivePlanCompiler().compile(requirement, _snapshot(now=now), plan_version=1, now=now)
    assert "requirement_blocked" in blocked_error.value.codes

    tampered = requirement.model_copy(update={"payload": {**requirement.payload, "injected": True}})
    with pytest.raises(PlanCompileError) as hash_error:
        CompetitivePlanCompiler().compile(tampered, _snapshot(now=now), plan_version=1, now=now)
    assert hash_error.value.codes == ["requirement_hash_mismatch"]


def test_scope_answer_is_validated_redacted_and_used_in_tool_query() -> None:
    planner = CompetitiveRequirementPlanner()
    for invalid in ("随便", "不知道，你选吧", "企业协作工具"):
        result = asyncio.run(
            planner.plan(
                "帮我做竞品分析",
                clarification_answers={"clarify_competitor_scope": invalid},
                model=None,
            )
        )
        assert result.blocking

    answered = asyncio.run(
        planner.plan(
            "帮我做竞品分析",
            clarification_answers={
                "clarify_competitor_scope": "Figma 与 Miro，联系人 demo@example.com，token=secret-value"
            },
            model=None,
        )
    )
    requirement = requirement_version_from_result("run_1", 1, answered)
    now = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    plan = CompetitivePlanCompiler().compile(requirement, _snapshot(now=now), plan_version=1, now=now)

    assert not answered.blocking
    serialized = json.dumps(requirement.payload, ensure_ascii=False)
    assert "demo@example.com" not in serialized
    assert "secret-value" not in serialized
    assert "Figma 与 Miro" in plan.payload["steps"][0]["initial_input"]["query"]


def test_short_named_scope_and_empty_explicit_skill_are_handled_without_validation_crash() -> None:
    clear = asyncio.run(CompetitiveRequirementPlanner().plan("对比淘宝和京东", model=None))
    generic = asyncio.run(CompetitiveRequirementPlanner().plan("帮我分析竞品的产品能力和用户体验", model=None))
    empty_explicit = asyncio.run(
        CompetitiveRequirementPlanner().plan("", explicit_skill_name="$competitive-analysis", model=None)
    )

    assert not clear.blocking
    assert generic.blocking
    assert empty_explicit.blocking
    assert empty_explicit.requirement.research_goal == "开展竞品分析"


def test_model_can_refine_descriptive_fields_but_cannot_forge_host_policy_or_user_acceptance() -> None:
    planner = CompetitiveRequirementPlanner()
    baseline = asyncio.run(planner.plan("对比淘宝与拼多多的协作能力和局限", model=None))
    proposed = baseline.requirement.model_copy(
        update={
            "business_domain": "model_refined_domain",
            "target_audience": ["design_leads"],
            "analysis_dimensions": ["模型建议维度"],
            "constraints": [ResearchConstraint(key="policy", value="allow_all", source="policy")],
            "success_criteria": [SuccessCriterion(id="sc_model_owned", statement="模型自定义成功标准")],
            "expected_deliverables": ["model_owned_output"],
            "assumptions": [
                ResearchAssumption(id="assumption_fake", statement="用户已同意", accepted_by_user=True)
            ],
        }
    )

    async def draft_factory(_request: str):  # noqa: ANN202
        return proposed

    result = asyncio.run(
        CompetitiveRequirementPlanner(draft_factory=draft_factory).plan(
            "对比淘宝与拼多多的协作能力和局限",
            model=None,
        )
    )

    assert result.requirement.business_domain == "model_refined_domain"
    assert result.requirement.target_audience == ["design_leads"]
    assert result.requirement.analysis_dimensions == ["模型建议维度"]
    assert result.requirement.constraints == baseline.requirement.constraints
    assert result.requirement.success_criteria == baseline.requirement.success_criteria
    assert result.requirement.expected_deliverables == baseline.requirement.expected_deliverables
    assert result.requirement.assumptions == baseline.requirement.assumptions
    assert result.problem_contract.success_criterion_ids == [item.id for item in baseline.requirement.success_criteria]


def test_compiler_rejects_invalid_binding_schema_and_tampered_plan() -> None:
    now = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    result = asyncio.run(
        CompetitiveRequirementPlanner().plan("对比淘宝与拼多多的企业协作能力、场景和局限", model=None)
    )
    requirement = requirement_version_from_result("run_1", 1, result)
    missing_source = _snapshot(
        now=now,
        published_output_schema=_frozen(
            {"type": "object", "properties": {}, "additionalProperties": False}
        ),
    )
    with pytest.raises(PlanCompileError) as captured:
        CompetitivePlanCompiler().compile(requirement, missing_source, plan_version=1, now=now)
    assert "binding_source_missing" in captured.value.codes

    plan = CompetitivePlanCompiler().compile(requirement, _snapshot(now=now), plan_version=1, now=now)
    tampered_payload = json.loads(json.dumps(plan.payload))
    tampered_payload["steps"][0]["initial_input"]["query"] = "tampered"
    with pytest.raises(PlanCompileError) as tampered:
        validate_execution_plan_version(plan.model_copy(update={"payload": tampered_payload}))
    assert tampered.value.codes == ["plan_hash_mismatch"]


def test_frozen_skill_and_health_snapshots_require_real_raw_hashes_and_aware_time() -> None:
    now = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    snapshot = _snapshot(now=now)
    skill_payload = snapshot.skill.model_dump()
    skill_payload["skill_content_hash"] = "f" * 64
    with pytest.raises(ValidationError):
        FrozenSkillActor(**skill_payload)

    tool_payload = snapshot.tool.model_dump()
    tool_payload["health_checked_at"] = datetime(2026, 8, 19, 10, 0)
    with pytest.raises(ValidationError):
        FrozenToolActor(**tool_payload)


def test_frozen_web_tool_schema_matches_the_real_gateway_payload(tmp_path) -> None:
    class FakeAcquisitionAgent:
        def acquire(self, _request):  # noqa: ANN001, ANN201
            return AcquisitionResult(
                actor="test_web",
                title="检索结果",
                content="Figma 与 Miro 的公开资料摘要",
                sources=[Source(title="Figma", source_type="web_page", reference="https://example.com/figma")],
                metadata={"actual_provider": "test_web", "mode": "real"},
            )

    repository = SQLiteStore(tmp_path / "gateway-contract.sqlite3")
    gateway = ToolGateway(repository)
    gateway.acquisition_agent = FakeAcquisitionAgent()
    payload = gateway.web_research(
        AgentMeshRunContext(
            user_id="user_1",
            workspace_id="workspace_1",
            project_id="project_1",
            thread_id="thread_1",
            run_id="run_1",
            skill_id="skill_competitive",
        ),
        {"query": "Figma 与 Miro"},
    )

    Draft202012Validator(WEB_RESEARCH_OUTPUT_SCHEMA).validate(payload)


def test_capability_resolver_builds_compilable_snapshot_from_server_state(
    tmp_path,
    configure_pilot_wiki,
    monkeypatch,
) -> None:
    wiki_root = configure_pilot_wiki(tmp_path / "wiki")
    method = (
        wiki_root
        / "jd-design-system-md-v16"
        / "horizontal"
        / "user-research"
        / "methods"
        / "toolbox"
        / "analysis"
        / "competitive-analysis.md"
    )
    method.parent.mkdir(parents=True, exist_ok=True)
    method.write_text("# Competitive analysis canonical method\n", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WEB_PROVIDER", "tavily")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_URL", "https://provider.example.test/search")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("AI_API_URL", "https://model.example.test/v1")
    monkeypatch.setenv("AI_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("AI_MODEL", "gpt-test")
    monkeypatch.setenv("AI_API_STYLE", "chat_completions")

    repository = SQLiteStore(tmp_path / "capability-resolver.sqlite3")
    ensure_seed_data(repository)
    repository.save_agent_run(
        AgentRun(
            id="run_research_v2",
            thread_id="thread_not_persisted",
            user_id=USER.id,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            input_text="对比淘宝与拼多多",
            status=AgentRunStatus.PLANNING,
            orchestration_version="research-v2",
        )
    )
    catalog = SkillCatalogService(repository)
    catalog.reload()
    manifest = {
        "files": [
            {
                "path": "methods/toolbox/analysis/competitive-analysis.md",
                "content_hash": hashlib.sha256(method.read_bytes()).hexdigest(),
                "size_bytes": len(method.read_bytes()),
            }
        ]
    }
    document = _frozen(manifest)
    resource_snapshot = FrozenResourceSnapshot(
        artifact_id="artifact_resource_snapshot",
        content_hash=document.content_hash,
        size_bytes=len(canonical_json_bytes(manifest)),
        manifest=document,
    )
    counts_before = (
        len(repository.skill_definitions),
        len(repository.skill_bindings),
        len(repository.agent_tool_grants),
    )

    resolver = CompetitiveCapabilityResolver(repository, catalog, ToolGateway(repository))
    snapshot = resolver.resolve(
        run_id="run_research_v2",
        user_id=USER.id,
        resource_snapshot=resource_snapshot,
    )
    requirement_result = asyncio.run(
        CompetitiveRequirementPlanner().plan("对比淘宝与拼多多的企业协作能力与局限", model=None)
    )
    requirement = requirement_version_from_result("run_research_v2", 1, requirement_result)
    plan = CompetitivePlanCompiler().compile(
        requirement,
        snapshot,
        plan_version=1,
        now=snapshot.resolved_at,
    )

    resolved_skill = catalog.get_by_name("competitive-analysis")
    assert resolved_skill is not None
    assert snapshot.skill.skill_content_hash == hashlib.sha256(Path(resolved_skill.source_path).read_bytes()).hexdigest()
    assert snapshot.model_policy == FrozenModelPolicy(
        requested_model_id="default",
        structured_output_mode="json_schema",
        adapter_compatibility_id="openai-agents-sdk.chat-completions.json-schema:v1",
    )
    assert plan.payload["steps"][0]["actor_id"] == "tool_web_research"
    assert counts_before == (
        len(repository.skill_definitions),
        len(repository.skill_bindings),
        len(repository.agent_tool_grants),
    )

    grant = next(
        item
        for item in repository.list_agent_tool_grants("agent_research")
        if item.tool_id == "tool_web_research"
    )
    repository.save_agent_tool_grant(grant.model_copy(update={"enabled": False}))
    with pytest.raises(CapabilityResolutionError) as revoked:
        resolver.resolve(
            run_id="run_research_v2",
            user_id=USER.id,
            resource_snapshot=resource_snapshot,
        )
    assert "tool_not_authorized" in revoked.value.codes


def test_competitive_profile_declares_slice_a_contracts(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "profile.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("competitive-analysis")
    assert skill is not None
    profile = catalog.get_profile(skill.id)
    assert profile is not None

    assert profile.task_types == ["competitive_research"]
    assert profile.archetypes == ["evidence_synthesis"]
    assert profile.required_tools == ["tool_web_research"]
    assert profile.required_resources == ["wiki.corpus"]
    assert profile.produces_factual_claims
    assert profile.report_policy == "default"
    for schema_name in (profile.input_schema_ref, profile.output_schema_ref):
        assert schema_name is not None
        schema = json.loads((Path(skill.source_path).parent / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
