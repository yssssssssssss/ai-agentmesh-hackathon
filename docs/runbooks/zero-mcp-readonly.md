# Zero MCP read-only integration

AgentMesh can connect to a user-managed local Zero MCP server through its governed MCP runtime. The bundled example exposes only verified read-only Relay capabilities; it does not enable design writes.

## Configure

1. Start Zero and enable its local MCP service.
2. Point AgentMesh at the example configuration:

```bash
export AGENTMESH_MCP_CONFIG=config/zero-mcp.readonly.example.json
```

3. Restart AgentMesh so `tool_zero_design_read` is seeded.
4. Explicitly grant `tool_zero_design_read` to the intended personal Agent through the existing Agent Tool API or admin UI.

The example targets `http://127.0.0.1:27618/mcp`. Change the local URL if the installed Zero version uses another endpoint.

## Exposed capabilities

The read-only gateway maps imported Skill requirements to these remote tools:

- `resources_list`
- `resources_read`
- `get_design_metadata`
- `get_design_context`
- `get_screenshot`
- `get_variables`

A Skill receives only the remote tools named by its requirement aliases. Granting the gateway does not expose every tool published by Zero MCP.

The following capabilities are deliberately excluded from this configuration:

- `use_design_script`
- `use_design_html`
- `export_image`
- plugin invocation
- Knowledge creation, upload, or deletion

DeepSearch continues to reject MCP tools. This integration is for Standard Skill execution only.

## Security behavior

- The gateway is not granted to Agents automatically.
- Remote tools are exposed only when Zero marks them with `readOnlyHint=true`.
- MCP calls require the existing AgentMesh approval boundary.
- Project access and Tool Grant are rechecked before provider invocation.
- Arguments containing credentials are withheld.
- Unsafe outputs are withheld and audited.
- Oversized outputs are stored as scoped Artifacts.
- Public alias names are translated to remote Zero tool names only at the governed MCP boundary.

Imported `Bash`, `Read`, `Write`, `Edit`, `Glob`, and `Grep` requirements are not satisfied by this integration. Skills that still require them remain `tool_limited` until those declarations are removed or mapped to separate sandboxed adapters.
