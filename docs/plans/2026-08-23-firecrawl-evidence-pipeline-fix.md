# Firecrawl Evidence Pipeline Remediation Plan

- Status: implemented in working tree; awaiting review/commit
- Date: 2026-08-23
- Owners: AgentMesh backend and research-workbench maintainers
- Scope: research-v2 Web evidence acquisition, evidence materialization, deterministic review, and blocked-result presentation
- Primary regression case: `run_248e21325869`
- Verified replacement regression run: `run_c174f55a38fd` (`review=pass`, six Evidence items, final Report present)

## 1. Problem statement

The latest WorkBuddy versus TRAE Work research run executed Tavily discovery, Firecrawl scraping, the `competitive-analysis` Skill, claim-ledger generation, and deterministic review. It still ended as `failed/deterministic_review_blocked`, with no Report artifact, empty `AgentRun.output_text`, and no final Assistant message.

The failure is not a missing Provider call or an exhausted model budget. The run recorded three successfully scraped URLs and an 18,060-token Skill model call. The failure comes from the representation and coverage of evidence:

1. Three fetched pages were flattened into one `content` string and then materialized as one `EvidenceSource`.
2. Firecrawl excerpts were cut from the beginning of each page, so navigation and page chrome consumed much of the 1,200-character budget.
3. Per-page truncation was lost before Evidence materialization; the stored Evidence reported `quote_truncated=false`.
4. The fixed research-v2 plan made one broad Web request, so it did not collect question-specific evidence for traceability, recovery, and collaboration.
5. The Skill emitted only inference Claims for `q_scenarios`, while the frozen problem contract treated it as a required factual question.
6. One Claim had `conflict_status=possible` with `confidence=medium`, violating the deterministic confidence cap.
7. A blocked Review produced no Report and no explanatory Assistant message.

## 2. Goals

1. Preserve one independently addressable Evidence item per fetched source.
2. Select query-relevant passages instead of truncating the start of the page.
3. Preserve retrieval time, content Provider, content hash, and truncation state per source.
4. Acquire evidence against each required factual question, within a bounded call and credit budget.
5. Keep deterministic Review fail-closed; never manufacture evidence to make a report pass.
6. Repair deterministic structural mistakes once when no new evidence is required.
7. Produce a useful blocked-result summary when final Review still fails.
8. Preserve access control, Tool approval, Artifact lineage, idempotency, and historical read compatibility.

## 3. Non-goals

- Do not replace Tavily with Firecrawl Search in this change.
- Do not use the Firecrawl Agent endpoint.
- Do not disable or weaken deterministic Review.
- Do not permit unlimited query fan-out, crawling, retries, or page extraction.
- Do not enable authenticated-page crawling or browser-session reuse.
- Do not change research-v3 frozen catalog semantics in this work.
- Do not migrate or rewrite completed historical Artifact rows.
- Do not expose Provider keys, response bodies, internal URLs, or full prompts in logs or API projections.

## 4. Chosen architecture

```text
Research requirement and problem contract
                 |
                 v
Question-scoped query bundle (maximum 4 queries)
                 |
                 v
Tavily discovery and URL normalization
                 |
                 v
Source ranking and deduplication
                 |
                 v
Firecrawl REST /v2/scrape (maximum 6 pages)
                 |
                 v
Per-source relevant excerpt + truncation metadata
                 |
                 v
Web Tool Result v2
                 |
                 v
One EvidenceSource per source URL
                 |
                 v
Competitive-analysis Skill
                 |
                 v
Claim normalization and deterministic Review
        |                         |
      pass                      block
        |                         |
Final Report              Blocked Research Summary
```

Tavily remains the search/discovery Adapter. Firecrawl remains a content-fetch Adapter. The seam exposed to Research remains the governed `web_research` Tool.

## 5. Contract changes

### 5.1 Acquisition source evidence

Add a structured acquisition record associated with a persisted `Source`:

| Field | Constraint | Meaning |
| --- | --- | --- |
| `source_id` | non-empty; must match a returned `Source.id` | Stable source identity |
| `content_provider` | `firecrawl` or the actual content Provider | Fetch provenance |
| `excerpt` | 1-8,192 UTF-8 bytes | Model-visible evidence text |
| `retrieved_at` | timezone-aware timestamp | Retrieval time |
| `content_hash` | SHA-256 | Exact excerpt integrity |
| `truncated` | boolean | Whether content was shortened before Evidence materialization |
| `risk_flags` | bounded unique list | Prompt injection, truncation, or extraction warnings |

`AcquisitionResult` retains `content`, `sources`, `permission`, and `metadata` for compatibility and adds a bounded `source_evidence` list.

### 5.2 Web Tool output v2

Introduce `web-research-output-v2` with these standard top-level fields:

- `title`
- `content`
- `sources`
- `source_evidence`
- `permission`
- `metadata`

The v2 writer always emits `source_evidence`; the validator accepts its absence only so historical v1 payloads can still be verified through the dual-read path.

Rules:

- Every `source_evidence.source_id` must resolve to exactly one `sources[].id`.
- Every `sources[].id` may appear at most once in `source_evidence`.
- The excerpt hash must match the excerpt.
- The count of Provider calls, successful scrapes, and fallback snippets must be present as secret-safe numeric strings in metadata.
- `content` remains a bounded human-readable summary; it is not the canonical evidence body.

Publish new Tool-result artifacts as `web-research-output-v2`. Keep `tool_web_research.implementation_version=1` during Phase 1 because research-v3's frozen Tavily adapter is explicitly out of scope and currently pins that runtime identity. The payload extension is additive at the Gateway seam, while Artifact readers dispatch on the persisted Tool-result schema version. Revisit the Tool implementation-version bump together with the research-v3 catalog migration rather than creating cross-generation descriptor drift here.

### 5.3 Evidence materialization

For v2 Tool results, create one `EvidenceSource` per `source_evidence` entry. Each Evidence contains one matching `ProviderSourceRef` and points to its own excerpt through a JSON pointer.

Historical v1 Tool results continue through the existing aggregate materialization path. No historical data is rewritten.

### 5.4 Truncation semantics

A source is marked truncated when either:

- the fetched Firecrawl body exceeds the raw input cap, or
- the selected relevant passages exceed the Evidence excerpt cap.

The flag propagates to `EvidenceRiskFlag.TRUNCATED` and the Evidence Manifest. Aggregate-level truncation must not overwrite or hide source-level truncation.

## 6. Relevant-passage extraction

Firecrawl continues to request `markdown` with `onlyMainContent=true`. The Adapter must not take the first N characters directly.

The deterministic selector will:

1. Normalize line endings and remove repeated blank lines.
2. Split Markdown by headings and paragraphs.
3. Remove duplicate blocks and obvious navigation/login/footer blocks.
4. Score each block using product names, query terms, and analysis-dimension terms.
5. Preserve source order among equally scored blocks.
6. Select the highest-scoring blocks until the per-source byte budget is reached.
7. Record whether any original content was omitted.

Limits:

- Raw Firecrawl body accepted per page: 128 KiB.
- Evidence excerpt per source: 4 KiB by default, maximum 8 KiB.
- Firecrawl pages per run: 6 maximum.
- Model-visible evidence across all sources: 24 KiB maximum.
- Empty or boilerplate-only extraction falls back to the Tavily snippet and records `content_extraction_empty`.

No additional LLM call is used for passage selection.

## 7. Question-scoped discovery

The research-v2 compiler continues to expose one governed Web Tool step, avoiding a state-machine rewrite. That Tool input gains a bounded `question_queries` list generated deterministically from the frozen requirement:

- one base comparison query;
- one traceability query;
- one recovery query;
- one collaboration query.

Rules:

- At most four Tavily searches.
- At most five results per query.
- Canonical URL deduplication before scraping.
- At most six Firecrawl scrapes total.
- Prefer official product documentation, help centers, release notes, and policy pages.
- Third-party comparisons may supplement but not replace first-party evidence when first-party material is available.
- Each result records which question IDs it was collected for.

The single AgentMesh Tool Invocation remains the authorization and idempotency unit. Its result records bounded child-call receipts containing Provider name, operation kind, request digest, status category, latency, and result count. Secrets and raw request bodies are excluded.

## 8. Skill and Claim rules

The `competitive-analysis` Skill continues to receive only verified Evidence IDs and source excerpts.

For every required factual question:

- emit at least one Fact Claim supported by the required number of independent sources; or
- emit an explicit evidence Gap and leave the question unsatisfied.

Scenarios and recommendations use the chain:

```text
Fact -> Inference -> Recommendation
```

A recommendation cannot serve as evidence for a factual question.

Before Review, deterministically cap confidence:

- `possible` or `conflicting` conflict state implies `low` confidence;
- Provider-summary-backed claims cannot exceed `medium` confidence.

This normalization cannot add Claims, source IDs, or evidence.

## 9. Review and repair behavior

Classify Review failures into two groups.

### Structural failures

- `conflict_confidence_cap`
- incorrect Claim type or coverage labels
- missing or invalid parent Claim linkage

Perform at most one repair model call. The repair call receives the failed check codes, current normalized Claims, and the same Evidence set. It cannot invoke tools or add sources.

### Evidence failures

- `evidence_policy`
- insufficient sources
- insufficient independent sources
- required factual question without evidence

Perform at most one supplemental acquisition pass when the per-run query and page budgets have remaining capacity. The pass targets only uncovered question IDs. Re-run analysis and Review once.

If Review still blocks, terminate without a formal Report.

## 10. Blocked-result contract

A failed deterministic Review must still produce a user-readable `Blocked Research Summary` containing:

1. Explicit statement that no approved final report was produced.
2. Verified facts that remain usable.
3. Clearly labelled inferences.
4. Failed Review check codes.
5. Evidence gaps by required question.
6. Retrieved source links.
7. Concrete next evidence-gathering actions.

Persistence behavior:

- `run.status=failed`
- `run.error_code=deterministic_review_blocked`
- `run.output_text` contains the blocked summary
- one private Assistant message is projected idempotently
- `report_id` remains absent
- `deliverable_id`, `review_id`, Evidence, and Claim Ledger remain inspectable

The UI labels this output “未通过审核的研究草稿”; it must never display it as a final Report.

## 11. Implementation phases

### Phase 1 — Per-source Evidence fidelity

Files:

- `agentmesh/acquisition.py`
- `agentmesh/web_research.py`
- `agentmesh/tool_runtime/gateway.py`
- `agentmesh/tools.py`
- `agentmesh/research_orchestration/evidence.py`
- `agentmesh/research_orchestration/artifacts.py`
- `tests/test_web_research.py`
- `tests/test_research_orchestration_evidence.py`
- `tests/test_research_orchestration_artifacts.py`

Work:

- Add structured per-source acquisition evidence.
- Add deterministic relevant-passage extraction.
- Publish Web Tool output v2.
- Materialize one EvidenceSource per URL.
- Preserve source-level truncation and risk flags.
- Keep v1 Artifact reads compatible.

Independent exit criteria:

- Three scraped URLs create three independently verifiable Evidence artifacts.
- Every quote resolves to its exact Tool-result JSON pointer.
- A truncated page carries the truncated flag and corresponding gap.
- Existing v1 fixture reads remain unchanged.

### Phase 2 — Question-scoped retrieval

Files:

- `agentmesh/research_orchestration/planning.py`
- `agentmesh/research_orchestration/compiler.py`
- `agentmesh/research_orchestration/contracts.py`
- `agentmesh/web_research.py`
- `agentmesh/tool_runtime/gateway.py`
- `tests/test_research_orchestration_planning.py`
- `tests/test_research_orchestration_execution.py`
- `tests/test_web_research.py`

Work:

- Generate the four-query bounded query bundle.
- Associate results and Evidence with question IDs.
- Rank official and primary sources ahead of derivative comparisons.
- Deduplicate canonical URLs.
- Record child Provider-call receipts and cost counters.
- Enforce query and scrape budgets.

Independent exit criteria:

- Every query is associated with at least one frozen question ID.
- No run exceeds four searches or six scrapes.
- Duplicate URLs are fetched once.
- Missing evidence remains an explicit Gap rather than an invented Claim.

### Phase 3 — Review repair and blocked-result UX

Files:

- `agentmesh/research_orchestration/actors.py`
- `agentmesh/research_orchestration/delivery.py`
- `agentmesh/research_orchestration/execution.py`
- `agentmesh/research_orchestration/workflow.py`
- `agentmesh/research_orchestration/api.py`
- `agentmesh/agent_runtime/service.py`
- `agentmesh-demo/src/components/workspace/ResearchResults.tsx`
- `tests/test_research_orchestration_delivery.py`
- `tests/test_research_orchestration_workflow.py`
- `tests/test_research_orchestration_routes.py`
- `agentmesh-demo/src/components/workspace/ResearchExecution.test.tsx`

Work:

- Normalize conflict confidence before Review.
- Add one bounded structural repair attempt.
- Add one bounded supplemental-evidence attempt.
- Persist and project Blocked Research Summary.
- Clearly distinguish blocked drafts from final Reports in the UI.

Independent exit criteria:

- Structural Claim errors are repaired without adding evidence.
- Evidence failures trigger at most one bounded acquisition pass.
- A persistent block produces no Report but always produces a readable Assistant message.
- Repeated delivery/retry commands remain idempotent.

## 12. Test matrix

### Unit tests

- Firecrawl 200, malformed JSON, empty Markdown, timeout, 401/403, 402, 408, 429, and 5xx.
- Public URL acceptance and localhost/private-IP rejection.
- Relevant passage selection rejects navigation-heavy leading text.
- Per-source content hash and JSON pointer validation.
- Source-level truncation propagation.
- URL canonicalization and deduplication.
- Conflict confidence normalization.
- No secret or Provider response-body leakage.

### Integration tests

1. Three independent high-quality sources produce three Evidence IDs and a passing Review.
2. Three URLs with no factual scenario evidence remain blocked.
3. One Firecrawl failure falls back to Tavily for that source and records degradation.
4. All Firecrawl calls fail; the run produces a blocked summary rather than an empty result.
5. Prompt-injection text is marked and excluded from trusted synthesis.
6. Tool approval rejection results in zero Provider calls.
7. Retrying a settled invocation does not duplicate external calls.
8. Historical v1 Tool and Evidence artifacts remain readable.

### Regression fixture

Use the exact WorkBuddy versus TRAE Work request that produced `run_248e21325869`.

Pass conditions:

- each fetched page has an independent Evidence ID;
- `q_evidence_comparison` and `q_scenarios` have traceable factual support or explicit gaps;
- `possible/conflicting` Claims never exceed low confidence;
- a passing Review creates a Report and non-empty `run.output_text`;
- a blocked Review creates a non-empty blocked summary and no Report.

### Verification commands

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
npm --prefix agentmesh-demo test -- --run
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
.venv/bin/python scripts/provider_smoke.py --web
```

Real Provider smoke tests must use an isolated database and approved secrets.

## 13. Deployment and compatibility

1. Rotate the Firecrawl key previously exposed in screenshots/chat.
2. Deploy readers that understand both v1 and v2 Tool-result artifacts before enabling v2 writes.
3. Confirm there are no non-terminal research-v2 runs before deploying the additive Gateway payload.
4. Deploy the new Tool-result writer and run deterministic tests.
5. Run Tavily and Firecrawl smoke tests against an isolated database.
6. Run the WorkBuddy/TRAE regression case.
7. Enable production traffic only after Review behavior and blocked-result projection pass.

Rollback:

- Set `AGENTMESH_FIRECRAWL_ENABLED=false` to return to Tavily-only acquisition.
- Keep v1 Artifact readers in place.
- Do not roll back persisted writer-generation metadata.
- Do not resume an in-flight Plan across a Tool implementation-version change.

## 14. Operational limits

Default per research run:

- Tavily searches: maximum 4
- Firecrawl pages: maximum 6
- Firecrawl concurrency: maximum 3
- supplemental evidence rounds: maximum 1
- structural repair calls: maximum 1
- total Research deadline: existing 300 seconds

At 10x load, Playwright/Firecrawl concurrency is expected to become the first bottleneck. Requests must queue within the parent deadline or fail with a stable timeout; they must not create unbounded background work.

## 15. Credentials and external dependencies

- `AGENTMESH_TAVILY_API_KEY`: Web discovery.
- `AGENTMESH_FIRECRAWL_API_KEY`: Cloud page extraction; optional only for a trusted self-hosted endpoint.
- configured Agent model credentials: Skill analysis, synthesis, and repair.
- `AGENTMESH_FIRECRAWL_API_URL`: Cloud `/v2/scrape` or trusted self-hosted equivalent.

All credentials remain server-side and must not appear in Git, API responses, screenshots, fixtures, Artifact content, or telemetry.

## 16. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Public evidence does not exist | Keep fail-closed; return blocked summary and request product testing or user-provided material |
| Firecrawl outage | Preserve Tavily snippets, mark degradation, and avoid claiming full-page evidence |
| Cost expansion | Hard caps on queries/pages/repair rounds and per-run usage metadata |
| Prompt injection in fetched pages | Scan each excerpt independently; quarantine flagged evidence |
| Schema drift | Version Tool output, dual-read v1/v2, drain old active plans before writer switch |
| Large model context | Relevant excerpts only; bounded per-source and total byte budgets |
| Duplicate claims from duplicate pages | Canonical URL and content-hash deduplication |
| Review repair invents facts | Repair call has no tools and cannot introduce new Evidence IDs |

## 17. Acceptance criteria

A run is successful only when:

- all required factual questions have the required independent source coverage;
- every factual Claim cites existing Evidence IDs;
- every Evidence ID resolves to an exact source excerpt and URL;
- all conflict-confidence rules pass;
- deterministic Review passes;
- a Report artifact exists;
- `AgentRun.output_text` and the final Assistant message are non-empty.

A blocked run is acceptable only when:

- no final Report exists;
- the Review artifact names every failed check;
- a blocked summary is stored and displayed;
- verified facts, inferences, sources, and gaps remain inspectable;
- no unsupported factual conclusion is presented as final.

## 18. Effort estimate

- Phase 1: 3-5 engineering days
- Phase 2: 3-5 engineering days
- Phase 3: 2-4 engineering days
- Real-provider verification and release checks: 2-3 engineering days
- Total: approximately 10-17 engineering days, depending on schema-compatibility and live-source behavior

## 19. Fragile assumption

This plan assumes public, independently verifiable material exists for the requested product capabilities. If that assumption fails, the correct product behavior is a detailed blocked summary and a request for first-party material or controlled product testing—not a fabricated passing report.
