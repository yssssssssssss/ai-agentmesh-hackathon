# Zero MCP read-only discovery and integration verification

Date: 2026-09-11

## Live discovery

A user-managed local Zero MCP service was discovered at `http://127.0.0.1:27618/mcp` and probed without reading design content or invoking write tools.

- MCP protocol: `2025-03-26`
- Server: `zero-design` `1.0.0`
- ZeroAgent: `1.0.21`
- Tools returned: 37
- Read-only tools: 27
- Non-read-only tools: 10
- Resources returned: 23
- Tool inventory SHA-256: `ef7ccaf540afffc6bce2a0626e58740ca5be72160cbe551c307806c0facfd2b0`
- Resource inventory SHA-256: `a7154f0c829aa4df61453c6824df182d0e7e0bea59b25938735507dfc04f0877`

All eight Zero-specific requirements declared by the 15 affected imported Skills were present. The read-only release maps six of them; `use_design_script` and `export_image` remain disabled.

A live AgentMesh wrapper smoke connected through `AgentMeshMCPFactory` and listed only `mcp__zero-design__get_design_metadata` for a Skill requesting that single alias. No design data or write Tool was invoked.

## Automated verification

- `pytest tests/test_mcp_runtime.py tests/test_universal_skill_search.py -q`: `64 passed`.
- Full backend suite with frontend routes excluded: `1869 passed, 6 skipped`.
- `ruff check .`: passed.
- MCP requirement aliases must target allowlisted remote tools and be unique.
- A Skill receives only its requested alias subset.
- The read-only gateway rejects remote tools unless Zero reports `readOnlyHint=true`.
- Catalog readiness recognizes configured aliases.
- The gateway is seeded but is not granted automatically.
- `design-review` no longer reports Zero MCP aliases as missing when configured; its unrelated `Bash`, `Edit`, `Read`, and `Write` requirements remain visible.
- Existing project, grant, capacity, output quarantine, and DeepSearch fail-closed tests remain in force.

This is integration evidence, not independent Profile approval or production authorization.
