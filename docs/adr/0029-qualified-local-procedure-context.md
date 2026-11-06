# Reviewed procedures are scoped reference context

Status: accepted for bounded local procedure selection, 2026-10-05.

## Decision

ProcedureContextSelectionV1 is a typed selection in the existing Memory context
bundle and Run snapshot, not another durable entity or executable Skill. Its
goal comes from the persisted current Run. Selection freezes the Memory
version/hash, reviewed payload and current capability hash. Existing capture
derives human confirmation, successful Run, Review and sealed Artifact references
on the server. Shared procedures still require independent Memory Review.

Automatic local project context examines at most eight current, scoped records
whose literal goal appears in the request and chooses one verified procedure.
There is no inferred semantic match. Explicit SDK memory_search can inspect a
known Memory ID using procedure_query, mutually exclusive with fact_query.
Ordinary summary retrieval still excludes structured payloads.

The verifier checks current owner/project/Agent binding and Memory lifecycle,
accepted Review versions/hashes and sealed Artifacts. Supported machine
preconditions are project_member and task_bound; other text remains unknown and
withholds the steps. Required tool names or IDs resolve to one enabled granted
definition, match the required implementation version, and match a registered,
locally verifiable implementation/schema (state, Memory/document search or risk
review). External data/research Providers and unknown/MCP implementations are
withheld pending a verifiable adapter contract; a configured tool is not proof
of actual Provider availability. Environment versions come from the running
Python, AgentMesh and openai-agents installations. Arbitrary environment claims
cannot be supplied by a model. Empty version maps assert no version constraint;
they do not prove an enterprise environment or grant a tool.

Only a qualified complete procedure enters context. Unknown conditions, missing
grants, changed tools/environments and unavailable evidence return bounded
diagnostics. Unsafe instructions are quarantined. Full steps and evidence count
against the rendering budget; they are dropped together when oversized. A tiny
budget may also drop the diagnostic without turning that into Memory use.

Current capability and evidence are checked on local snapshot recovery, each
actual model handoff and inside the receipt write transaction. Receipts identify
the exact delivered Memory version. The text remains untrusted reference data;
it does not authorize or automatically invoke the suggested steps. Existing tool
grants, approvals and outcome validation remain independent.

SDK history distinguishes procedure delivery from fact-only delivery of a mixed
payload. Procedure dependencies repeat applicability checks even with Memory
off. A fact query does not acquire a procedure dependency just because its
Memory also contains steps. Absent new lineage fields retain old checkpoint
bytes. Forgetting redacts withheld procedure selections as well as delivered
hits; the migrated database barrier rejects late restoration after reopen.
Remote Runner procedure context is withheld until its delivery contract exists.

The Task Review capture form explicitly opts into recording a method and asks
for goals, steps, verification conditions, optional additional conditions and
selected current tool versions. Success/approval evidence is not client input.
Existing Knowledge rendering exposes the recorded conditions and references.

## Verification boundary

Deterministic tests exercise actual accepted Task Review capture, independent
team Memory Review, automatic local selection, typed SDK tool output, current
grants, budget drops, receipt transaction races, mixed fact/procedure isolation,
Session lineage and forgetting/reopen. These are contracts, not semantic
entailment or a measured reduction in repeated model mistakes.

Full verification is recorded separately in
docs/verification/2026-10-05-procedure-context-regression.json.

The selector provides one bounded literal-match procedure, not a general
semantic ContextAssembler or ranked multi-procedure optimizer. Freeform
condition confirmation, explicit reviewed Skill packaging/activation, complete
candidate status UI, four-baseline 120/24-case evaluation, retrieval capacity,
real enterprise environment verification and remote parity remain separate work.
