# ADR 0063: Shared Run context assembly and component budgeting

Status: Accepted, implemented 2026-10-07.

## Context

Local direct and Standard execution prepared core preferences and Memory separately. Runtime also owned the SQL/fact/procedure/ordinary-recall routing chain. Each Memory bundle had an 8000-character limit, but the preferences and surrounding instructions did not consume that limit. Final model requests already had an independent complete-request guard; they still need that guard after history, schemas and tool outputs are assembled.

## Decision

`MemoryContextService.assemble_for_run` owns preparation and routing. Its temporary `RunContextAssemblyV1` returns existing frozen preference/bundle components and the complete rendered additional context. It creates no second Memory authority, persistence identity or framework. Local direct and Standard consumers use this entry; the existing Runtime bundle adapter delegates to it.

Core preferences take precedence. Their full rendered policy/header/data consumes the selected budget first. Optional context uses the remaining space after its header. Default combined allowance remains 8000 characters and callers may tighten it through the existing Memory budget. Ordinary recall may shorten summaries while retaining complete title/citation/source metadata. Fact/procedure assertions retain their existing all-or-nothing behavior. If even a SQL budget diagnostic cannot fit, the component is dropped with a body-free event. If mandatory preference content cannot fit, preparation fails rather than silently truncating constraints. No delivery receipt is produced for a budget drop or preparation.

Routing remains authority-based: explicit current project/task state uses Task/Review SQL; supported entity/time questions use structured facts; exact qualified goals can use human-reviewed procedures; remaining questions use governed Memory retrieval. A SQL count query cannot fall back to a contradictory Memory narrative. Ordinary private chat keeps the owner's core preferences and does not automatically inject project Memory. Observe mode prepares diagnostics/metrics without context delivery or use receipts; off mode does neither.

SQL state queries can now also carry a currently qualified reviewed procedure for the same goal. The existing bundle keeps separate SQL and procedure fields; no second context store or authority is added. Preferences and complete SQL rendering retain priority. The method receives only remaining character allowance, including the separator, and remains all-or-nothing. Unsupported/oversized methods never replace SQL counts. Facts and procedures remain separate query authorities. Existing payloads without the combined fields preserve their canonical bytes.

Combined delivery validates both renderings and exact method evidence. Method receipt commit rechecks the SQL hash under the same BEGIN IMMEDIATE writer lock, before receipt/audit writes; the existing read-only state query runs before any Task writes in that transaction. State changes reject the receipt. SQL itself still produces no Memory-use receipt. Existing snapshot/approval/model guards recheck both selections.

Local direct instructions place the core preferences before recalled material. Standard nodes preserve their existing prompt placement and Runner envelope, but select components through the same shared allowance. DeepSearch keeps its separate context/budget contract. Recent complete Session units, current input, platform/Skill instructions, tools, schemas and tool outputs continue through the existing final request guard, which measures the actual complete SDK payload on every model request. This component allowance is not a replacement for the request/token budget.

Existing private snapshots freeze the prepared components and exact instructions. Current preferences, evidence, memory versions, execution identity and final budget are rechecked at model handoff. Actual delivery commits only the selected Memory versions; SQL state produces no Memory receipts. Existing snapshot/Source/Memory hash schemas are unchanged; new context instructions naturally produce new snapshot identities.

## Verification

A fresh Task created from a reviewed goal reaches the actual scripted SDK with current SQL and method context together, records only the method version and does not execute its steps automatically. Additional public checks cover state changes at receipt commit, SQL priority under a tightened shared budget and existing standalone SQL/procedure behavior. These checks establish workflow consistency, not real-model quality or adoption.

Five public assembly checks cover shared rendering, optional recall dropping before core constraints, natural-chat/observe boundaries, SQL-first routing and exact SDK handoff receipts. Selected existing direct Runtime checks cover preference modes/changes, SQL state, fact evidence changes and automatic reviewed procedure delivery. **18 passed / 24.32 seconds** across five files. A Standard downstream-node/source/synthesis case with injection enabled passed separately: **1 passed / 3.37 seconds**. Targeted Ruff and whitespace checks passed.

See `docs/verification/2026-10-07-shared-run-context-assembly.json`. No new frontend/API response was introduced, so no frontend rebuild or type regeneration was needed. Tests use temporary databases and scripted SDK models; no real model/Provider, full regression, dual-version or browser checks were repeated.

## Remaining scope

This completes the common local preparation entry and shared preference/material allowance. It does not finish the entire ContextAssembler: dynamic complete-request allocation/compaction, tokenizer-backed estimates where supported, remote Runner parity and full Session/Artifact lineage remain. Source freshness/remote ACL/deletion policies, actual model quality and team acceptance also remain in the complete plan. Existing reviewed procedure capture/selection is reused, not promoted into an executable Skill.
