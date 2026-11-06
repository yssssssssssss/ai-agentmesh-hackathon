# AgentMesh Development Plan

## 1. Product Positioning

AgentMesh is a team agent platform with a chat-first user experience, personal digital avatars, controlled service agents, a shared blackboard for agent collaboration, and governed team memory.

The product is not a generic knowledge base, not a free-form multi-agent chat room, and not an approval console for agent chores.

The core user-facing promise is:

> Ask the team brain for help, let personal and service agents gather context, and turn useful work into private, project, or team memory without forcing users to manage agent internals.

## 2. Design Principles

- Chat is the main user entry point.
- The shared blackboard is an internal collaboration layer, not the primary human interface.
- Confirmations belong in Inbox or Memory workflows, not the main workspace.
- Personal activity is private by default.
- Shared memory is governed, sourced, permissioned, and reversible.
- Agent collaboration must be task-based and auditable, not free-form autonomous chatter.
- MVP must prove user value before platform breadth.

## 3. MVP Goal

Build a working vertical slice:

1. User chats with their personal Agent.
2. Natural chat stays private, while explicit `$` skills create tasks.
3. If memory is insufficient or a skill needs collaboration, the task creates an internal blackboard request.
4. A mock service Agent responds with evidence.
5. The result is returned to the user in chat.
6. The user's Agent records a daily activity log.
7. High-value outputs can become memory candidates.
8. Confirmation items go to Inbox or Memory Review, not the chat workspace.

## 4. MVP Non-goals

- No free-form agent-to-agent chat.
- No automatic sharing of private user activity.
- No full organization knowledge graph.
- No real crawler or search integration in the first vertical slice.
- No complex RBAC/ABAC engine in the first slice.
- No automatic external system write-back.
- No personality simulation for member avatars.
- No full document ingestion pipeline until chat/task loop works.

## 5. Recommended Initial Tech Stack

Frontend:

- Next.js
- React
- TypeScript
- CSS Modules or Tailwind, but keep visual system small

Backend:

- Python FastAPI
- Pydantic
- SQLAlchemy
- Simple background worker first, Celery/RQ later only if needed

Storage:

- PostgreSQL for app data
- SQLite acceptable only for a local prototype
- pgvector only after keyword retrieval is insufficient

Agent/runtime:

- Start with deterministic mock agents
- Add LLM calls behind a narrow Agent interface
- Avoid framework lock-in until the domain model is stable

## 6. Product Surface Architecture

### 6.1 Workspace

The main workspace is chat-first.

Primary functions:

- Ask team brain questions.
- Search team memory through natural language.
- Ask personal Agent to record, summarize, or organize work.
- Start tasks such as "generate Brief" or "find similar projects".
- Receive synthesized results with citations.

### 6.2 Inbox

Inbox holds work that needs human attention:

- High-impact memory confirmation.
- Risk approvals.
- Tool-call approval.
- External sharing approval.
- Conflicting or disputed memory review.

### 6.3 Memory Library

Memory Library manages long-lived knowledge:

- Personal memory.
- Project context.
- Team memory candidates.
- Accepted team memory.
- Deprecated or disputed memory.

### 6.4 Agent Activity Panel

Right-side activity panel shows:

- What my personal Agent did today.
- Which service agents it asked for help.
- What evidence came back.
- Which items were kept private, project-visible, or sent for review.

## 7. Backend Layer Architecture

### 7.1 API Layer

Responsibilities:

- Auth placeholder for MVP.
- Chat API.
- Task API.
- Inbox API.
- Memory API.
- Activity log API.

### 7.2 Personal Agent Layer

Responsibilities:

- Receive user chat input.
- Parse explicit `$` skill commands.
- Keep natural chat private and create tasks only for explicit skills.
- Decide whether to answer directly, search memory, or create a task.
- Maintain private user context.
- Produce daily personal activity summaries.

### 7.3 Task Router

Responsibilities:

- Create task records.
- Choose workflow type.
- Track task state.
- Write audit events.
- Route requests to mock or real service agents.

### 7.4 Blackboard Layer

Internal collaboration substrate.

Post types:

- request
- evidence
- risk
- digest
- decision
- correction
- memory_candidate

Rules:

- Humans do not need to read raw blackboard posts by default.
- Every post must have actor, source, scope, permission, status, and timestamp.
- Service agents communicate through blackboard posts, not private chat.

### 7.5 Service Agent Layer

MVP service agents:

- mock_research_agent
- mock_data_agent
- mock_risk_agent

Later service agents:

- search_agent
- crawler_agent
- document_agent
- asset_agent
- data_agent

### 7.6 Memory Layer

Memory scopes:

- private
- project
- team_candidate
- team_accepted

Memory states:

- draft
- proposed
- accepted
- disputed
- deprecated
- expired

## 8. Core Data Model

Minimal entities:

- Workspace
- Project
- User
- Agent
- ChatThread
- ChatMessage
- Task
- BlackboardPost
- ActivityLog
- MemoryItem
- InboxItem
- Source
- AuditEvent

Essential invariants:

- A shared item must have a permission scope.
- A team memory must have at least one source.
- A task must preserve completed steps even if later steps fail.
- A service agent cannot act outside the requesting user's effective permission.
- A private user message must not become team memory without explicit promotion.

## 9. MVP User Flow

### Flow A: Ask for similar project experience

1. User asks: "Have we done a similar 618 appliance homepage redesign?"
2. Personal Agent creates a task.
3. Task Router creates blackboard request.
4. mock_research_agent returns evidence.
5. Personal Agent summarizes evidence in chat.
6. Activity panel records "searched similar projects".
7. Optional memory candidate is sent to Memory Review.

### Flow B: Record today's work

1. User says: "Summarize today's discussion as private notes."
2. Personal Agent writes private ActivityLog.
3. User can later promote parts to project context.

### Flow C: Generate project Brief

1. User asks for a Brief.
2. Personal Agent retrieves project context and evidence.
3. Service agents fill missing context.
4. Brief result is shown in chat.
5. Sources are attached.
6. High-impact recommendations go to Inbox if confirmation is needed.

## 10. Verification Strategy

MVP acceptance:

- User can chat with personal Agent.
- Chat creates task records.
- Task can create internal blackboard request.
- Mock service agent can respond with evidence.
- Evidence returns to chat as a cited answer.
- Right-side activity panel updates.
- Memory candidate can be created but is not auto-accepted.
- Confirmation items appear in Inbox.
- Private messages remain private by default.

Engineering checks:

- Unit tests for permission/scope transitions.
- Unit tests for task state transitions.
- API tests for chat-to-task-to-evidence flow.
- UI smoke tests for chat input, quick actions, activity panel, and Inbox links.

## 11. Delivery Plan

### Milestone 0: Static Product Prototype

Status: done.

Deliverables:

- Static `app.html`.
- Chat-first workspace design.
- Personal Agent daily log panel.
- External Agent collaboration log panel.

### Milestone 1: Project Scaffold

Deliverables:

- Frontend app scaffold.
- Backend app scaffold.
- Shared domain glossary.
- Local dev instructions.

### Milestone 2: Core Domain API

Deliverables:

- Database schema.
- Chat thread/message API.
- Task API.
- Blackboard post API.
- Activity log API.
- Inbox item API.

### Milestone 3: Mock Agent Loop

Deliverables:

- Personal Agent explicit `$` skill router.
- Task Router.
- mock_research_agent.
- request -> evidence -> chat response loop.
- Audit events.

### Milestone 4: Human-facing UI

Deliverables:

- Chat workspace.
- Quick actions.
- Personal Agent daily activity panel.
- External Agent collaboration panel.
- Inbox preview.
- Memory review preview.

### Milestone 5: Memory Governance

Deliverables:

- Memory candidate creation.
- Memory scope/state transitions.
- Inbox review flow.
- Source and citation display.

### Milestone 6: Retrieval

Deliverables:

- Keyword search over project context, memory, and blackboard evidence.
- Permission-aware filtering.
- Relevance ranking.
- Evaluation dataset.

### Milestone 7: Real Service Integrations

Deliverables:

- Real search integration.
- Crawler allowlist.
- Document ingestion.
- Risk approval for high-risk tool calls.

## 12. First Implementation Slice

The first code slice should not build the whole platform.

Build only this:

1. Chat UI.
2. `POST /api/chat/messages`.
3. Personal Agent explicit `$` skill router.
4. Task record creation.
5. Internal blackboard request creation.
6. mock_research_agent evidence response.
7. Chat answer with citation.
8. Activity log update.

If this slice is not useful, the bigger platform will not save it.
