from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agents.models.interface import Model

from scripts import agent_sdk_smoke as smoke


class OpenAIChatCompletionsModel(Model):
    async def get_response(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("network model must not run in this test")

    async def stream_response(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("network model must not run in this test")
        yield  # pragma: no cover


def _result(output: object) -> SimpleNamespace:
    return SimpleNamespace(
        final_output=output,
        context_wrapper=SimpleNamespace(usage=SimpleNamespace(requests=1, total_tokens=10)),
    )


class _StreamResult:
    def __init__(self, *, synthesis: bool):
        self.is_complete = synthesis
        self.final_output = (
            smoke.ProbeSynthesis(summary="Combined result", node_ids=["research", "evidence"])
            if synthesis
            else None
        )
        self.context_wrapper = SimpleNamespace(usage=SimpleNamespace(requests=1, total_tokens=10))
        self._synthesis = synthesis

    def cancel(self) -> None:
        self.is_complete = True

    async def stream_events(self):  # noqa: ANN201
        if self._synthesis:
            yield SimpleNamespace(type="raw_response_event")
            yield SimpleNamespace(type="run_item_stream_event", name="tool_called")


def test_model_smoke_checks_all_required_sdk_capabilities_without_network(monkeypatch) -> None:
    async def fake_run(agent, _input, **_kwargs):  # noqa: ANN001, ANN202
        if agent.name.endswith("Intent"):
            return _result(smoke.ProbeIntent(goal="Validate checkout", deliverables=["research_plan"]))
        if agent.name.endswith("Plan"):
            return _result(
                smoke.ProbePlan(
                    nodes=[
                        smoke.ProbePlanNode(node_id="research", skill_name="research", depends_on=[]),
                        smoke.ProbePlanNode(
                            node_id="synthesis",
                            skill_name="synthesis",
                            depends_on=["research"],
                        ),
                    ]
                )
            )
        node_id = agent.name.rsplit(" ", 1)[-1]
        return _result(smoke.ProbeNodeResult(node_id=node_id, summary=f"{node_id} complete"))

    def fake_run_streamed(agent, _input, **_kwargs):  # noqa: ANN001, ANN202
        if agent.name.endswith("Synthesis"):
            assert agent.model_settings.tool_choice == "required"
        return _StreamResult(synthesis=agent.name.endswith("Synthesis"))

    monkeypatch.setattr(smoke.Runner, "run", fake_run)
    monkeypatch.setattr(smoke.Runner, "run_streamed", fake_run_streamed)
    selected = smoke.SelectedSDKModel(
        model=OpenAIChatCompletionsModel(),
        requested_model="alpha",
        actual_model="alpha-model",
    )

    payload = asyncio.run(smoke.run_model_smoke(selected))

    assert payload["passed"] is True
    assert payload["requests"] == 5
    assert payload["total_tokens"] == 50
    assert payload["requested_provider"] == "openai_agents_sdk"
    assert payload["actual_provider"] == "OpenAIChatCompletionsModel"
    assert payload["checks"] == {
        "structured_intent": True,
        "structured_plan": True,
        "parallel_node_results": True,
        "structured_synthesis": True,
        "streaming": True,
        "tool_call": True,
        "usage": True,
        "cancellation": True,
        "provider_provenance": True,
    }


def test_default_mode_keeps_single_model_output_and_does_not_print_secrets(monkeypatch, capsys) -> None:
    selected = smoke.SelectedSDKModel(
        model=OpenAIChatCompletionsModel(),
        requested_model="default",
        actual_model="default-model",
    )
    requested: list[str] = []

    class FakeFactory:
        def __init__(self, _repository):  # noqa: ANN001
            pass

        def for_model_id(self, model_id: str):  # noqa: ANN201
            requested.append(model_id)
            return selected

    async def fake_smoke(_selected):  # noqa: ANN001, ANN202
        return {
            "configured": True,
            "requested_model": "default",
            "actual_model": "default-model",
            "checks": {"streaming": True},
            "passed": True,
        }

    monkeypatch.setattr(smoke, "AgentMeshModelFactory", FakeFactory)
    monkeypatch.setattr(smoke, "run_model_smoke", fake_smoke)
    monkeypatch.setattr(smoke, "configure_agentmesh_tracing", lambda _repository: None)
    monkeypatch.setenv("AI_API_KEY", "secret-must-not-appear")

    exit_code = asyncio.run(smoke.main([]))
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == smoke.EXIT_OK
    assert requested == ["default"]
    assert payload["requested_model"] == "default"
    assert "models" not in payload
    assert "secret-must-not-appear" not in output


def test_all_configured_runs_each_compatible_model_and_fails_as_a_group(monkeypatch, capsys) -> None:
    monkeypatch.setenv("AGENTMESH_MODELS", "alpha,beta,alpha,missing,responses")
    for model_id in ("ALPHA", "BETA", "RESPONSES"):
        monkeypatch.setenv(f"AGENTMESH_MODEL_{model_id}_BASE_URL", "https://models.example/v1")
        monkeypatch.setenv(f"AGENTMESH_MODEL_{model_id}_API_KEY", f"secret-{model_id}")
        monkeypatch.setenv(f"AGENTMESH_MODEL_{model_id}_MODEL", f"model-{model_id}")
    monkeypatch.setenv("AGENTMESH_MODEL_RESPONSES_API_STYLE", "responses")
    requested: list[str] = []

    class FakeFactory:
        def __init__(self, _repository):  # noqa: ANN001
            pass

        def for_model_id(self, model_id: str):  # noqa: ANN201
            requested.append(model_id)
            return smoke.SelectedSDKModel(
                model=OpenAIChatCompletionsModel(),
                requested_model=model_id,
                actual_model=f"actual-{model_id}",
            )

    async def fake_smoke(selected):  # noqa: ANN001, ANN202
        if selected.requested_model == "beta":
            raise RuntimeError("secret-BETA-must-not-appear")
        return {
            "configured": True,
            "requested_model": selected.requested_model,
            "actual_model": selected.actual_model,
            "checks": {},
            "passed": True,
        }

    monkeypatch.setattr(smoke, "AgentMeshModelFactory", FakeFactory)
    monkeypatch.setattr(smoke, "run_model_smoke", fake_smoke)
    monkeypatch.setattr(smoke, "configure_agentmesh_tracing", lambda _repository: None)

    exit_code = asyncio.run(smoke.main(["--all-configured"]))
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == smoke.EXIT_FAILED
    assert requested == ["alpha", "beta"]
    assert [item["requested_model"] for item in payload["models"]] == ["alpha", "beta"]
    assert payload["models"][1]["error_code"] == "RuntimeError"
    assert payload["passed"] is False
    assert payload["skipped"] == [
        {"model_id": "missing", "reason": "not_configured"},
        {"model_id": "responses", "reason": "sdk_incompatible"},
    ]
    assert "secret-ALPHA" not in output
    assert "secret-BETA" not in output


def test_unconfigured_default_model_has_explicit_exit_code(monkeypatch, capsys) -> None:
    class FakeFactory:
        def __init__(self, _repository):  # noqa: ANN001
            pass

        @staticmethod
        def for_model_id(_model_id: str):
            return None

    monkeypatch.setattr(smoke, "AgentMeshModelFactory", FakeFactory)
    monkeypatch.setattr(smoke, "configure_agentmesh_tracing", lambda _repository: None)

    exit_code = asyncio.run(smoke.main([]))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == smoke.EXIT_NOT_CONFIGURED
    assert payload == {"configured": False, "reason": "model_not_configured"}
