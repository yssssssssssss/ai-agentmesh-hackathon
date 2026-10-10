---
status: accepted
---

# Treat user-managed Zero MCP as a governed read-only gateway

AgentMesh connects to a locally managed Zero MCP server through the existing MCP runtime instead of reimplementing Zero APIs or granting imported Skills host-level `Bash`, `Read`, `Write`, or `Edit` access. Versioned requirement aliases translate imported `mcp__zero-design__*` names to the remote MCP names, while one ungranted-by-default `zero_design_read` ToolDefinition remains the authorization and audit boundary.

## Consequences

- A configured gateway exposes only the remote tools requested by the active Skill, not the server's complete tool catalog.
- Aliased names are presented to the model and translated back only at the governed MCP call boundary, preserving imported Skill contracts and durable call identity.
- The read-only configuration accepts a remote tool only when its MCP annotation reports `readOnlyHint=true`.
- `use_design_script`, `use_design_html`, image export, plugin invocation, and Knowledge mutations remain excluded.
- Users must start Zero MCP locally, configure `AGENTMESH_MCP_CONFIG`, and explicitly grant `tool_zero_design_read` to an Agent.
- DeepSearch continues to reject MCP tools.
- Imported host-tool requirements such as `Bash`, `Read`, `Write`, and `Edit` remain separate gaps until removed or mapped to sandboxed adapters.
