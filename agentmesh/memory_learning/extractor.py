from __future__ import annotations

from agents import Agent, ModelRetrySettings, ModelSettings, RunConfig, Runner

from agentmesh.agent_runtime.model_factory import AgentMeshModelFactory
from agentmesh.memory_learning.contracts import EXTRACTION_INSTRUCTIONS, ExtractionResultV1, extraction_input
from agentmesh.memory_learning.service import MemoryLearningError
from agentmesh.models import DocumentRecord, User
from agentmesh.store import SQLiteStore


class SDKDocumentExtractor:
    def __init__(self, store: SQLiteStore):
        self.factory = AgentMeshModelFactory(store)

    async def extract(self, document: DocumentRecord, actor: User, *, max_output_tokens: int) -> tuple[ExtractionResultV1, int]:
        selected = self.factory.for_user(actor, timeout_seconds=85, max_retries=0)
        if selected is None:
            raise MemoryLearningError('model_unavailable')
        try:
            agent = Agent(name='Private document fact extraction', model=selected.model,
                          instructions=EXTRACTION_INSTRUCTIONS, output_type=ExtractionResultV1,
                          model_settings=ModelSettings(max_tokens=max_output_tokens,
                                                       retry=ModelRetrySettings(max_retries=0)))
            result = await Runner.run(agent, input=extraction_input(document), max_turns=1,
                                      run_config=RunConfig(tracing_disabled=True, trace_include_sensitive_data=False))
            if not result.raw_responses or any(response.usage.total_tokens <= 0 for response in result.raw_responses):
                raise MemoryLearningError('memory_learning_usage_unavailable')
            usage = sum(response.usage.total_tokens for response in result.raw_responses)
            return ExtractionResultV1.model_validate(result.final_output), usage
        finally:
            if selected.client is not None:
                await selected.client.close()
