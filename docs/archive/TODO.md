# AgentMesh TODO

## Current Direction

Build a chat-first team agent platform:

- User-facing entry: chat with personal Agent and team brain.
- Internal collaboration: task router plus shared blackboard.
- Long-term asset: governed personal, project, and team memory.
- Human review: moved to Inbox and Memory Review, not the main workspace.

Reference plan: `DEVELOPMENT_PLAN.md`.

## Ground Rules

- [ ] Do not implement free-form agent-to-agent chat.
- [ ] Do not auto-share private user activity.
- [ ] Do not make the blackboard the primary human interface.
- [ ] Do not auto-accept team memory.
- [ ] Keep the first release focused on one vertical slice.
- [x] Every shared artifact must have actor, source, scope, permission, status, and timestamp.
- [x] Keep the real acquisition Agent as an interface boundary; implementation will be provided by an external project.

## Milestone 0: Product Baseline

- [x] Review original PRD documents.
- [x] Decide chat-first workspace direction.
- [x] Decide blackboard is internal collaboration infrastructure.
- [x] Create static `app.html`.
- [x] Add personal Agent daily activity panel to the app shell.
- [x] Add external Agent collaboration log panel to the app shell.
- [x] Move confirmation-heavy workflows conceptually to Inbox and Memory Review.
- [x] Create `DEVELOPMENT_PLAN.md`.
- [x] Define final MVP success metrics.
- [x] Define sample project dataset for testing.

## Milestone 1: Project Scaffold

- [x] Decide package manager and repo layout.
- [x] Create frontend app scaffold.
- [x] Create backend app scaffold.
- [x] Add root README with local run instructions.
- [x] Add environment variable template.
- [x] Add lint/format configuration.
- [x] Add basic test runner.
- [x] Add local development script.
- [x] Create isolated `.venv` for stable pytest execution.

## Milestone 2: Core Domain Model

- [x] Define `Workspace` model.
- [x] Define `Project` model.
- [x] Define `User` model.
- [x] Define `Agent` model.
- [x] Define `ChatThread` model.
- [x] Define `ChatMessage` model.
- [x] Define `Task` model.
- [x] Define `BlackboardPost` model.
- [x] Define `ActivityLog` model.
- [x] Define `MemoryItem` model.
- [x] Define `InboxItem` model.
- [x] Define `Source` model.
- [x] Define `AuditEvent` model.
- [x] Add model-level permission scope fields.
- [x] Add model-level status fields.
- [x] Add created/updated timestamps for all persisted entities.
- [x] Add SQLite-backed persistence store.

## Milestone 3: Core Backend APIs

- [x] Implement health check API.
- [x] Implement workspace/project seed data.
- [x] Implement chat thread creation API.
- [x] Implement chat message creation API.
- [x] Implement task creation API.
- [x] Implement blackboard post creation API.
- [x] Implement activity log creation/list API.
- [x] Implement inbox item list/update API.
- [x] Implement memory item list/create API.
- [x] Implement layered user memory list/create and short/mid/long-term rollup APIs.
- [x] Implement source attachment model/API.
- [x] Add basic API tests.
- [x] Verify records survive service restart through SQLite.

## Milestone 4: Personal Agent MVP

- [x] Implement personal Agent interface.
- [x] Implement explicit `$` chat skill registry.
- [x] Route explicit skills:
  - [x] `$memory.search`
  - [x] `$brief.create`
  - [x] `$note.save`
  - [x] `$research.request`
  - [x] `$data.query`
  - [x] `$risk.review`
  - [x] `$memory.propose`
  - [x] `$system.info`
- [x] Keep natural language input as private general chat unless the user invokes a skill.
- [x] Ensure user input defaults to private scope.
- [x] Create ActivityLog for user-agent interactions.
- [x] Add tests for default private behavior.

## Milestone 5: Task Router And Blackboard Loop

- [x] Implement task state machine:
  - [x] created
  - [-] planning
  - [x] running
  - [x] waiting_external_agent
  - [-] synthesizing
  - [x] completed
  - [x] failed
- [x] Implement task-to-blackboard request creation.
- [x] Define blackboard post types:
  - [x] request
  - [x] evidence
  - [x] risk
  - [x] digest
  - [x] decision
  - [x] correction
  - [x] memory_candidate
- [x] Link evidence posts back to request posts.
- [x] Preserve completed task steps on failure.
- [x] Add audit events for task and blackboard actions.

## Milestone 6: Mock Service Agents

- [x] Implement `mock_research_agent`.
- [x] Implement `mock_data_agent`.
- [x] Implement `risk_agent`.
- [x] Let mock agents read blackboard requests.
- [x] Let service agents publish evidence/risk posts.
- [x] Return synthesized results to chat.
- [x] Add tests for request -> evidence -> chat loop.

## Milestone 7: Human-facing Frontend MVP

- [ ] Convert `app.html` into real frontend components.
- [ ] Implement app shell and left navigation.
- [x] Implement chat workspace.
- [x] Implement visually distinct composer.
- [x] Implement icon-only send button.
- [x] Implement quick action buttons:
  - [x] generate Brief
  - [x] ask service Agent
  - [x] record today's work
  - [x] create memory candidate
- [x] Implement right-side personal Agent activity panel.
- [x] Implement right-side external Agent collaboration panel.
- [x] Implement Inbox preview link.
- [x] Implement Memory Review preview link.
- [x] Connect quick actions to real chat API.
- [x] Render returned Inbox/Memory items in the workspace preview.
- [x] Add responsive layout checks.

## Milestone 8: Inbox And Memory Review

- [x] Implement Inbox page.
- [x] Move high-impact confirmations into Inbox.
- [x] Implement Memory Review page.
- [x] Create memory candidate from chat result.
- [x] Add memory scopes:
  - [x] private
  - [x] project
  - [x] team_candidate
  - [x] team_accepted
- [x] Add memory states:
  - [x] draft
  - [x] proposed
  - [x] accepted
  - [x] disputed
  - [x] deprecated
  - [x] expired
- [x] Add accept/edit/dispute/deprecate actions.
- [x] Add source display for memory candidates.

## Milestone 9: Retrieval Foundation

- [x] Add keyword search over chat messages.
- [x] Add keyword search over activity logs.
- [x] Add keyword search over blackboard evidence.
- [x] Add keyword search over memory items.
- [x] Add permission-aware filtering.
- [x] Add project/workspace filters.
- [x] Add source-aware result display.
- [x] Evaluate whether pgvector is needed.

## Milestone 10: Real Integrations

- [x] Add OpenAI-compatible LLM synthesis integration.
- [x] Define real acquisition Agent request/response interface.
- [x] Wire `mock_research_agent` behind the real acquisition Agent interface.
- [x] Add external acquisition connector placeholder.
- [x] Defer crawler/search implementation to the external project.
- [x] Add document ingestion.
- [x] Add basic file parsing.
- [x] Add data source connector placeholder.
- [x] Add high-risk tool call approval.
- [x] Add prompt injection guard for external content.

## Milestone 11: Evaluation

- [x] Build sample project dataset.
- [x] Test "find similar project" flow.
- [x] Test "generate Brief" flow.
- [x] Test "record today's work" flow.
- [x] Measure answer citation coverage.
- [x] Measure time-to-useful-answer.
- [x] Measure memory candidate acceptance rate.
- [x] Measure user correction rate.

## First Implementation Slice

Build this first, end to end:

- [x] Scaffold frontend and backend.
- [x] User sends one chat message.
- [x] Backend stores `ChatMessage`.
- [x] Personal Agent parses explicit `$` skill commands.
- [x] Backend creates `Task`.
- [x] Task creates internal `BlackboardPost` request.
- [x] `mock_research_agent` creates `BlackboardPost` evidence.
- [x] Backend returns cited chat response.
- [x] Backend writes `ActivityLog`.
- [x] Frontend shows response and right-side activity update.
- [x] Add tests for the full slice.

## Definition Of Done For MVP

- [x] A user can ask the team brain for similar project experience.
- [x] The answer includes at least one source.
- [x] The system records what the personal Agent did today.
- [x] The system records what external Agent was asked to do.
- [x] Confirmation-heavy items appear outside the main chat workspace.
- [x] Private user input is not shared by default.
- [x] All task and agent actions are auditable.

## Completed In Current Real-Data Slice

- [x] Real cookie-session auth with seeded user, lead, and admin accounts.
- [x] Admin user lifecycle API for creating and disabling local users.
- [x] New local users automatically receive a personal Agent and password credential.
- [x] Role checks for personal Agent edits, public Agent management, and team-memory acceptance.
- [x] Personal Agent configuration API and UI for name, description, capabilities, tools, and model preference.
- [x] Backend tool registry with explicit per-Agent grants.
- [x] Backend model registry with server-side API keys and UI model switching.
- [x] OpenAI-compatible LLM call path when a configured model is selected.
- [x] FastAPI application split into route modules under `agentmesh/routes`.
- [x] Split service Agents and LLM synthesis helpers out of `agentmesh/agents.py`.
- [x] Split `PersonalAgent.handle_chat` intent branches into stateful workflow helpers.
- [x] SQLite-backed persistence for users, sessions, agents, tools, models, chat, tasks, blackboard, memory, inbox, activity, sources, and documents.
- [x] Inbox action queue semantics with active filtering, resolved status, snooze TTL, and expired snoozes returning to the active queue.
- [x] Unified audit timeline API and UI for user, Agent, BBS, Inbox, and handoff events already recorded as `AuditEvent`.
- [x] Agent roster derives runtime status/current task from BBS task cards and execution locks, and the Agent/BBS pages display it.
- [x] Real `.txt`, `.md`, and `.markdown` upload API and composer upload entry.
- [x] Workspace and project list/detail/create APIs backed by SQLite persistence.
- [x] Blackboard/BBS list with pagination, agent actor display, read markers, replies, structured handoff UI/API, manual posts, and queued auto-post drain API.
- [x] Data Agent connector registry with a working `local_metrics` connector and query API.
- [x] Research Agent Web provider boundary for `opencli`, `agent-browser`, or explicit mock mode.
- [x] Oxygen-CLI internal provider boundary with status API, admin tool sync, read-only research/data adapters, and UI status panel.
- [x] Oxygen command contracts for `metasearch`, `o2-kb`, `oxygen-comment`, and `bdp-copilot` are represented in the adapter and covered by tests.
- [x] Admin UI for assigning synced Oxygen tools to public Agents.
- [x] Risk Agent deterministic rule engine for prompt-injection and high-risk tool-call review.
- [x] Persisted Risk Agent policy rules with admin create/update APIs.
- [x] Risk policy management UI on the Members page.
- [x] Dark chat UI, fixed bottom composer, scrollable conversation area, right-side collapsible floating panels, Agent page, BBS page, and user page.

## Still Mock Or Placeholder By Design

- [ ] Default research evidence still uses `MockAcquisitionAgent` unless `AGENTMESH_WEB_PROVIDER` is configured.
- [x] Oxygen-backed research/data calls require the relevant internal CLI runtime, tokens, initialization, and browser bridge state; AgentMesh now has adapters but cannot replace those prerequisites.
- [x] `risk_agent` review post content is produced by a policy-backed deterministic reviewer.
- [x] `local_metrics` is a sample connector, not a production BI/database connector.
- [x] Workspace/project records are persisted in SQLite, with seed records only used as startup defaults.
- [x] File parsing supports UTF-8 plain text, Markdown, PDF, Word `.docx`, slide `.pptx`, and image OCR connector paths, with uploaded document search, background parsing for large files, and short-term document-summary memory. OCR requires a configured `tesseract` command.
- [x] User system supports local seeded users plus admin-created local users.
- [x] User system has an OAuth adapter framework; real SSO provider configuration and organization provisioning still need enterprise inputs.
- [x] Permission model has role checks, scopes, team membership, core user/team/admin visibility filtering, and persisted role-action policy overrides for MVP-sensitive actions.
- [x] Public Agents are backend-registered and managed by admin APIs; there is no user-facing public-Agent builder.
- [x] Agent-initiated background posting is prepared through a queued BBS auto-post API, manual drain endpoint, and env-gated worker.

## Next Engineering Backlog

- [x] Replace static workspace/project API responses with persisted records in the current SQLite store.
- [x] Add a migration path from the current records store to dedicated relational tables if production schema stabilizes.
- [ ] Move `PersonalAgent` workflow helpers into a dedicated workflow module if orchestration keeps growing.
- [x] Add a production-facing read-only HTTP data connector; first real business data source still needs company API URL, auth, and response contract.
- [x] Add production Oxygen CLI contracts for the first approved internal research/data CLIs.
- [x] Add admin-facing setup checks for missing `JD_METASEARCH_ACCESS_TOKEN`, `o2-kb init`, Browser Bridge extension state, and `bdp-copilot` auth/runtime readiness.
- [x] Add a real Web provider adapter once the exact `agent-browser` or `opencli` command contract is fixed.
- [x] Replace `MockRiskAgent` with a policy-backed risk reviewer that uses rule packs, source policy, and human approval signals.
- [x] Add persisted risk policy tables for allow/deny lists and human approval outcomes.
- [x] Add document parser connectors for Word, images, and slide decks.
- [x] Add an env-gated long-running worker for automatic BBS post draining.
- [x] Add scheduled Agent task definitions beyond auto-post draining.
- [x] Add full local user lifecycle: create user, deactivate user, password rotation/reset, and organization/team membership management.
- [x] Add local user creation and disable flow.
- [x] Add password rotation/reset APIs and Members page controls.
- [x] Add organization/team membership management.
- [x] Add persisted permission policy rules for role-level allow/deny overrides on MVP-sensitive actions.
