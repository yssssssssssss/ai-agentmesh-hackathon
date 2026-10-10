# Confirmed project terminology retains original fact evidence

Status: accepted for local fact queries, 2026-10-05.

## Decision

Store a bounded ProjectTermAliasesV1 inside the existing Project aggregate. A
current member with manage_team_memory permission confirms the complete mapping
with an expected version and a durable command ID. The transaction rechecks the
actor, project and permission policy. Exact command replay survives database
reopen; stale edits and changed command payloads fail. Ordinary Project saves
retain the governed vocabulary rather than overwriting it from a stale object.
Audit contains counts, versions and hashes, without the alias names.

Aliases use exact NFC/casefold/whitespace normalization inside one project.
Self-maps, ambiguous normalized names, chains, cycles, invalid scoped IDs and
invisible control characters are rejected. The dictionary holds at most 200
pairs. Project, Task and User IDs retain their existing identities; this does not
infer merges from similar names or connect different projects.

New confirmed term facts use the canonical subject ID. Queries also select
historical assertions stored under the confirmed aliases and group conflicts by
the canonical subject. Existing Memory versions, fact subject IDs, evidence
hashes and valid-time intervals remain unchanged. Historical queries use the
currently confirmed vocabulary; this does not provide historical vocabulary
versions or infer semantic equivalence from a model.

Fact results freeze vocabulary version and confirmation identity. Local approval
recovery, actual model handoff and the receipt write transaction repeat the
query; a changed dictionary cannot reuse the old selection. SDK Sessions retain
the vocabulary version of exact archived term-query output and reject its stale
reuse, including with Memory off. The rendered model diagnostic keeps the
canonical ID and matched count rather than rendering all 200 aliases.

The Knowledge page reads the selected project and current account, shows the
real dictionary, and offers an explicit edit/confirmation flow. A version
conflict disables stale saving and requires reloading. Network retries retain
the command ID until the submitted mapping changes. Current server permissions
remain authoritative even when the browser capability cache is stale.

## Verification boundary

The real local API browser regression covers confirmation, concurrent editing,
reload/persistence and ordinary-member read access. Deterministic backend tests
cover source preservation, merged conflicts, current scopes/permissions,
durable replay, bounded diagnostics and changes before receipt commit.
Full verification is recorded separately in
docs/verification/2026-10-05-project-terminology-regression.json.

Procedure applicability, complete context assembly, remote Runner delivery,
memory quality evaluation and real enterprise Provider smoke remain separate
work; this dictionary does not complete phases 3 or 4.
