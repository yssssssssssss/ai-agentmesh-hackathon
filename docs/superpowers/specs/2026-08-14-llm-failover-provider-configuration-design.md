# LLM Failover and Provider Configuration Design

Date: 2026-08-14
Status: Implemented and locally verified

## Goal

Configure the internal LLM gateway and embedding endpoint without committing credentials, and add automatic LLM failover from the primary model to a named fallback model. Every completed turn must record which model was requested, which model actually answered, and why failover occurred.

## Non-goals

- No gateway-side routing changes.
- No fallback for Embedding, Web Research, Data API, or O2.
- No retry loop across multiple fallback models.
- No secret values in Git, logs, audit metadata, health responses, tests, or documentation.
- No streaming response support in this change. The current client continues to request a non-streaming chat-completions response.

## Configuration Contract

The local ignored `.env` will define two named LLM models and one embedding model:

```dotenv
AGENTMESH_MODEL_DEFAULT=primary
AGENTMESH_MODELS=primary,fallback

AGENTMESH_MODEL_PRIMARY_BASE_URL=http://<internal-gateway>/v1
AGENTMESH_MODEL_PRIMARY_API_KEY=<local-secret>
AGENTMESH_MODEL_PRIMARY_MODEL=<primary-model-name>
AGENTMESH_MODEL_PRIMARY_LABEL=Primary LLM
AGENTMESH_MODEL_PRIMARY_API_STYLE=chat_completions

AGENTMESH_MODEL_FALLBACK_BASE_URL=http://<internal-gateway>/v1
AGENTMESH_MODEL_FALLBACK_API_KEY=<local-secret>
AGENTMESH_MODEL_FALLBACK_MODEL=<fallback-model-name>
AGENTMESH_MODEL_FALLBACK_LABEL=Fallback LLM
AGENTMESH_MODEL_FALLBACK_API_STYLE=chat_completions

AGENTMESH_LLM_FALLBACK_MODEL_ID=fallback

AGENTMESH_EMBEDDING_ENABLED=true
AGENTMESH_EMBEDDING_API_URL=http://<internal-gateway>/v1/embeddings
AGENTMESH_EMBEDDING_API_KEY=<local-secret>
AGENTMESH_EMBEDDING_MODEL=<embedding-model-name>
```

`.env.example` will document the variable names with placeholders only. The real key remains in `.env`, which is ignored by Git. Since the key was shared in chat, it should be rotated after validation.

## LLM Routing Architecture

Add a `FailoverChatLLM` wrapper implementing the existing `ChatLLM` protocol. `chat_llm_client()` resolves the Agent-selected model as the requested model, resolves `AGENTMESH_LLM_FALLBACK_MODEL_ID`, and returns:

- the selected `LLMClient` directly when no fallback is configured;
- the selected `LLMClient` directly when the selected model is already the fallback model;
- otherwise, a request-scoped `FailoverChatLLM(primary, fallback)`.

Explicitly injected test clients bypass environment failover. This keeps unit tests deterministic and prevents production configuration from changing dependency-injected behavior.

The wrapper is request-scoped. It must not keep shared mutable model-selection state across concurrent requests.

The wrapper first calls the requested model. It calls the fallback model only when the primary raises one of these stable failures:

- `timeout`
- `request_error`
- `http_status`
- `invalid_response`
- an empty response

It does not fail over on `auth_error`. Both configured models use the same credential, so a second request would hide a configuration failure rather than improve availability.

There is one fallback attempt and no loop. If fallback also fails, the caller receives a redacted `LLMRequestError` whose stable reason is `primary_<reason>_fallback_<reason>`. It contains neither provider response bodies nor credentials.

## Provenance

Extend `ChatWorkflowTrace` with:

- `requested_model: str | None`
- `actual_model: str | None`

Extend `SynthesisResult` with the same model fields. On primary success, both fields contain the selected model. On fallback success, `requested_model` contains the primary model and `actual_model` contains the fallback model. Persist the primary stable failure category as `ChatWorkflowTrace.model_fallback_reason`; keep `fallback_reason` reserved for Provider or local fallback so both causes can coexist.

The existing requested/actual provider fields remain separate. Acquisition provider provenance must not be overwritten by LLM model provenance.

The model fields describe the model that generated the final assistant answer. Intent-classifier attempts are internal routing details and must not overwrite final answer provenance.

Workspace renders requested model, actual model, mode, latency, and fallback reason. The fields are persisted with the assistant message and remain visible after reload.

## Model Registry Behavior

Both named models appear in the existing model registry. Admin can still select either model explicitly for an Agent. If the fallback model is selected explicitly, it is treated as the requested model and is not wrapped with itself.

The global fallback setting applies to chat classification, synthesis, Brief generation, and market LLM calls because those paths already resolve clients through `chat_llm_client()`.

## Embedding Behavior

Embedding uses the full embeddings endpoint URL and the existing Bearer-token JSON contract. Startup validation still requires explicit opt-in plus URL and key. Vector dimensions remain the current fixed project contract unless the real response proves a different dimension and tests are updated deliberately.

## Health and Smoke Tests

`provider_smoke.py --llm` will probe the primary and fallback models directly, not through automatic failover, so one healthy model cannot mask the other. Output remains redacted and includes model ID, ready state, real/fallback mode, latency, and stable error category.

`provider_smoke.py --embedding` validates that the embedding endpoint returns a non-empty numeric vector. It never prints the vector or key.

## Tests

Backend tests must cover:

1. Primary success does not call fallback.
2. Timeout, request error, non-auth HTTP failure, invalid response, and empty response call fallback exactly once.
3. Authentication failure does not call fallback.
4. Fallback failure surfaces both redacted stable failure categories.
5. Explicit selection of the fallback model does not wrap itself.
6. Requested and actual model fields survive message persistence and thread reload.
7. Concurrent requests do not leak actual-model state.
8. Provider smoke probes both models independently.
9. Embedding smoke uses the configured endpoint and produces no secret output.

Frontend tests and Playwright must verify primary and fallback provenance labels and refresh persistence.

## Rollout and Verification

1. Commit code, tests, `.env.example`, and generated OpenAPI types without secrets.
2. Write the approved values to local ignored `.env`.
3. Run focused backend and frontend tests.
4. Probe the primary LLM, fallback LLM, and embedding endpoint.
5. Run the full backend, Ruff, React build, and Playwright gates.
6. Rotate the shared credential and update only the local `.env` after rotation.

## Acceptance Criteria

- Primary LLM requests succeed against the internal gateway.
- A controlled primary failure produces one successful fallback response.
- The UI and persisted trace show different requested and actual models for the fallback case.
- Authentication failures remain explicit and do not trigger fallback.
- Embedding returns a real non-empty vector.
- No credential is tracked or printed.
- All focused and full regression gates pass.

## Verification Evidence

- Primary model generated a real application response and persisted identical requested/actual model fields across thread reload.
- A controlled primary timeout selected the fallback exactly once and persisted `model_fallback_reason=timeout`.
- Real smoke reported Embedding, primary LLM, and fallback LLM as configured, ready, and real without printing credentials or response bodies.
- Full gates passed: 523 pytest, Ruff, 7 Vitest, production build, and 24 Playwright tests.
