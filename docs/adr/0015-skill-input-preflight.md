---
status: accepted
---

# Gate Standard Skill execution on frozen user inputs

AgentMesh introduces Skill Input Preflight for new Standard v1 runs. A production Planner-eligible Skill must explicitly declare either `user_input_mode: prompt_only` or `user_input_mode: preflight`. A preflight Skill references a bounded `skill-user-input-v1` JSON Schema stored inside its Skill package. The server validates and hashes that contract when loading the Capability Profile; an invalid, missing, out-of-root, or unsupported contract makes the Skill unavailable.

After an explicit Skill or Standard Plan is selected and before any Skill node or Tool executes, the runtime compiles the selected contracts against the original request and Run-scoped input materials. Missing required fields place the top-level `AgentRun` in `waiting_input` with one durable `SkillInputRequestV1`. Text and uploaded Markdown/TXT/CSV remain private to that Run. Completion atomically freezes field bindings and advances to the existing Plan Approval state or execution state.

## Consequences

- `input_kinds` remains retrieval metadata and `input_schema_ref` remains an internal execution schema; neither is used as the user form contract.
- The client renders only the server-projected fields and submits values or Artifact IDs. It cannot add fields, relax validation, or claim that a field is satisfied.
- Input Request versions use compare-and-swap. `client_turn_id` plus a canonical payload hash makes identical retries idempotent and rejects conflicting reuse.
- Run Input Artifacts are separate from Documents, Memory, Evidence, and output Artifacts. Uploading one never creates Memory chunks or expands retrieval visibility.
- Every frozen binding identifies the Run/Plan node, field, value version, content hash, and contract hash. A node receives only its own bindings.
- `waiting_input` is an active, recoverable state. Refreshing, reading, or reconnecting SSE does not parse input or start execution. The existing one-active-Run-per-thread rule still applies.
- Input confirmation is not a new approval class. A single-Skill read/draft run continues immediately; a Plan that already requires approval presents one final combined confirmation.
- Text, UTF-8 Markdown/TXT, and CSV are the first supported adapters. Oversized normalized content fails with `input_content_too_large`; it is never silently truncated.
- URL snapshots and image inputs ship only behind their own ready adapters. Images are passed to a capable multimodal LLM and never use OCR or an OCR fallback.
- Existing DeepSearch Requirement and Evidence contracts are unchanged. Existing runs and stored artifacts are not migrated or reinterpreted.
