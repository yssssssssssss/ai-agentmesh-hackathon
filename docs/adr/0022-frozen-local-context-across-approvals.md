# Frozen local context across approvals

Status: accepted for the local ContextSnapshot slice, 2026-10-04.

## Decision

Keep automatic context as a private, versioned execution payload of the existing
Run. `RunContextSnapshotV1` freezes its input hash, Run/owner/workspace/project/
thread/Task identities, writer generation, plan version and node identity,
Skill version/hash, exact Memory bundle, core-preference version, additional
instructions and complete-request budget. Its canonical hash determines its ID.
SDK RunState contains only the snapshot ID alongside existing execution IDs.
No second Memory authority or execution queue is introduced.

Local direct and Standard-node execution stage snapshots in inject mode before
the SDK runs. Preparation reserves citations but records no Memory use. On each
actual model request, the existing request guard admits the complete budget,
loads and validates the snapshot, verifies the frozen input and instructions,
then commits exact Memory-version receipts through the existing Store barrier.
This establishes local model handoff, not a successful Provider response.

## Recovery and current authority

Approval recovery rebuilds the Agent and obtains the SDK context through its
documented deserializer. Application validation runs outside that callback:
the SDK redacts callback exceptions, while our public failures use static safe
codes. Before claiming or approving calls, the Runtime checks restored execution
identities, the frozen input and the server snapshot. Source/version/lifecycle,
origin lineage, core-preference version, current user/project access, context
mode, Skill identity and plan version are rechecked. Recovered Agents receive
the frozen additional instructions; current tool policy and resource manifests
are rebuilt from server authority. Checks repeat at subsequent model handoffs.

Staging freezes the Skill object that actually built the Agent and the plan
version that built the node input. A concurrent replacement cannot pair a newer
stored identity with older instructions. Skill disablement and current per-agent
binding revocation are also checked before handoff.

This works across a new Runtime instance and across partial approvals. Existing
SDK states without snapshot IDs retain compatibility; their restored execution
identities are still checked. DeepSearch keeps its existing frozen plan and
evidence boundaries and does not acquire automatic private-memory injection.

## Withdrawal and persistence

Snapshots live in a private records collection outside public Memory search and
API payloads. Run lookup has a partial expression index. Their immutable payload
hash is checked when loaded, and SQL triggers reject replacing a prepared
payload. The only content-changing transition is redaction to withdrawn.

Owned forgetting or source withdrawal invalidates snapshots whose frozen Memory
references are provably affected. In the same transaction it clears the bundle,
query, core preferences and additional instructions, retaining IDs and hashes
as barriers. A withdrawn snapshot cannot be restored or rewritten. Tombstone
triggers also reject late reconstruction from forgotten Memory. Reopening the
database preserves these barriers. Audit/Run events contain only IDs, hashes,
counts, mode and safe error codes, never the private instructions.

## Scope and remaining work

This completes the frozen automatic-context recovery slice for local direct and
Standard execution. It does not complete structured fact/procedure selection,
candidate decision projections, aliases, procedure reuse or the 120/24 memory
evaluations. Complete Session ownership, deduplication and source archives,
remote Runner delivery acknowledgements, lease fencing, non-streamed request
admission and full cumulative cost accounting remain subsequent work.

Already delivered Session/output retention is a separate policy. This change
cannot retract material already received by a user or Provider, and does not
claim remote or real-Provider verification.

Verification: `docs/verification/2026-10-04-local-context-snapshot-regression.json`.
