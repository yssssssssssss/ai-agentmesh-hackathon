from __future__ import annotations

import asyncio

import pytest
from agents import Agent, ModelSettings, RunConfig, Runner, function_tool
from agents.models.interface import ModelTracing
from agents.testing import ScriptedModel, assistant_message, function_call

from agentmesh.memory_context.request_budget import (
    ContextRequestBudgetV1,
    ContextRequestError,
    RequestBudgetModel,
    measure_model_request,
)


def test_complete_request_counts_instructions_input_schema_and_utf8():
    @function_tool
    def lookup(value: str) -> str:
        """Read a project record using its exact identifier."""
        return value

    measured = measure_model_request(
        system_instructions='回答项目问题', input=[{'role': 'user', 'content': '查负责人'}],
        tools=[lookup], handoffs=[], output_schema=None, model_settings=ModelSettings(max_tokens=123),
        model_id='enterprise-model', budget=ContextRequestBudgetV1(),
    )
    assert measured.model_id == 'enterprise-model'
    assert measured.estimation_method == 'utf8_conservative'
    assert measured.estimated_input_tokens > measured.total_chars
    assert measured.output_token_cap == 123
    without_tool = measure_model_request(
        system_instructions='回答项目问题', input=[{'role': 'user', 'content': '查负责人'}],
        tools=[], handoffs=[], output_schema=None, model_settings=ModelSettings(max_tokens=123),
        model_id='enterprise-model', budget=ContextRequestBudgetV1(),
    )
    assert measured.estimated_input_tokens > without_tool.estimated_input_tokens


@pytest.mark.parametrize('large_part', ['instructions', 'input', 'schema'])
def test_oversized_complete_request_never_calls_model(large_part):
    @function_tool
    def lookup(value: str) -> str:
        return value

    if large_part == 'schema':
        lookup.description = '字段说明' * 4000
    model = ScriptedModel([[assistant_message('unreachable')]])
    measured = []
    handoffs = []
    guarded = RequestBudgetModel(model, model_id='test', budget=ContextRequestBudgetV1(max_tokens=8000),
                                 on_measure=measured.append, on_handoff=lambda: handoffs.append(True))
    agent = Agent(name='bounded', model=guarded, tools=[lookup],
                  instructions='规则' * 4000 if large_part == 'instructions' else 'Use project evidence.')
    with pytest.raises(ContextRequestError, match='context_request_budget_exceeded'):
        asyncio.run(Runner.run(agent, '问题' * 4000 if large_part == 'input' else 'Question',
                               run_config=RunConfig(tracing_disabled=True)))
    assert not model.calls
    assert len(measured) == 1 and measured[0].decision == 'withheld'
    assert handoffs == []


def test_tool_result_is_counted_on_each_model_turn():
    @function_tool
    def lookup() -> str:
        return '项目证据' * 4000

    model = ScriptedModel([[function_call('lookup', {}, call_id='lookup-1')], [assistant_message('unreachable')]])
    measured = []
    guarded = RequestBudgetModel(model, model_id='test', budget=ContextRequestBudgetV1(max_tokens=12000),
                                 on_measure=measured.append)
    agent = Agent(name='bounded', instructions='Read evidence.', model=guarded, tools=[lookup])
    with pytest.raises(ContextRequestError, match='context_request_budget_exceeded'):
        asyncio.run(Runner.run(agent, 'Read', run_config=RunConfig(tracing_disabled=True)))
    assert len(model.calls) == 1
    assert [item.decision for item in measured] == ['allowed', 'withheld']


def test_bounded_request_clamps_output_and_calls_handoff_before_model():
    model = ScriptedModel([[assistant_message('bounded answer')]])
    seen = []
    guarded = RequestBudgetModel(model, model_id='test', on_handoff=lambda: seen.append(len(model.calls)))
    agent = Agent(name='bounded', instructions='Answer.', model=guarded)
    answer = asyncio.run(Runner.run(agent, 'Question', run_config=RunConfig(tracing_disabled=True)))
    assert answer.final_output == 'bounded answer'
    assert seen == [0]
    assert model.first_call.model_settings.max_tokens == 8192


def test_hidden_provider_context_cannot_bypass_local_budget():
    model = ScriptedModel([[assistant_message('unreachable')]])
    guarded = RequestBudgetModel(model, model_id='test')
    with pytest.raises(ContextRequestError, match='context_request_hidden_state'):
        asyncio.run(guarded.get_response(
            None, 'Question', ModelSettings(), [], None, [], ModelTracing.DISABLED,
            previous_response_id='previous-hidden-response', conversation_id=None, prompt=None,
        ))
    assert not model.calls
