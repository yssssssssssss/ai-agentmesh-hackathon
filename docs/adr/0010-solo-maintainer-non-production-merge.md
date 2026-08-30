---
status: accepted
---

# Allow CI-gated solo merges without production activation

AgentMesh is currently a single-maintainer Hackathon project, so an independent GitHub collaborator cannot approve the stacked implementation PRs. For repository integration only, the maintainer may merge a reviewed PR after every required CI check passes and the AI-assisted technical review reports no remaining P0, P1, or P2 findings. This exception does not count as independent human approval and does not satisfy any production release gate.

## Consequences

- Stacked PRs are merged in dependency order and retain their review and CI history.
- `main` continues to require pull requests, required CI, an up-to-date branch, conversation resolution, administrator enforcement, and protection from force-push or deletion.
- The solo exception removes required approving-review and CODEOWNER-review counts only for repository integration. CODEOWNERS remains as review routing metadata.
- Production `preview` and `execute` stay blocked. `AGENTMESH_SKILL_ORCHESTRATION` remains `off`; draft Profiles remain planner-ineligible.
- Real Profile approval, Provider acceptance, holdout, production soak, attestation, deployment, and rollback rehearsal still require external evidence and cannot be replaced by this ADR or AI review.
- If a second maintainer joins, required human approval and CODEOWNER enforcement must be restored before any production-release work continues.
