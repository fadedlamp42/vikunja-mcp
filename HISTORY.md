# history

## 2026-03-05 - origin story and implementation notes

### why this repo exists

we started with `@democratize-technology/vikunja-mcp` and hit repeated runtime failures:

- package/env mismatch (`VIKUNJA_URL` in examples, actual package expected `VIKUNJA_API_BASE`)
- one package variant (`@democratize-technology/vikunja-mcp`) threw tool/schema errors during `tools/list`
- the other (`vikunja-mcp`) initialized but failed inconsistently on task endpoints in real usage

result: not reliable enough for production mcp usage.

### research findings (via exa)

#### python mcp "standard approach"

- official docs and sdk examples consistently recommend the python sdk (`mcp`) with `FastMCP` for most servers, using stdio transport for local client integration.
- low-level `Server` is still part of the official sdk and is valid when we need custom request/tool wiring.
- logging guidance is explicit: never write protocol logs to stdout for stdio servers; use stderr.

primary references:

- https://modelcontextprotocol.io/docs/develop/build-server
- https://github.com/modelcontextprotocol/python-sdk
- https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/servers/simple-tool/mcp_simple_tool/server.py

#### vikunja api docs and auth model

- vikunja serves generated docs at `/api/v1/docs`
- raw swagger spec is at `/api/v1/docs.json`
- recommended auth is bearer api token in `Authorization: Bearer <token>`

primary reference:

- https://vikunja.io/docs/api-documentation/

#### vikunja filtering semantics

- filter queries are sql-like and support `&&`, `||`, grouping, and date math (`now/d`, `+1w`, etc.)
- label filtering via api requires numeric label ids

primary reference:

- https://vikunja.io/docs/filters/

### api surface snapshot used for implementation

- source swagger: `https://try.vikunja.io/api/v1/docs.json`
- swagger version: `2.0`
- paths: `108`
- operations (path+method): `148`

### architecture decision

we intentionally use the official low-level `mcp.server.Server` instead of `FastMCP.from_openapi` because vikunja currently publishes swagger 2.0 with many `in: body`/`in: formData` parameters, and the openapi provider path in `fastmcp` expects openapi3-compatible parameter shapes.

in practice, `FastMCP.from_openapi` raised large validation failures against vikunja's swagger2 document.

### implementation strategy

- parse vikunja swagger2 directly
- generate one mcp tool per operation for broad coverage
- generate tool input schemas from swagger parameters
- route each tool call to the corresponding vikunja endpoint with token auth
- add helper tools:
  - `vikunja_list_operations`
  - `vikunja_reload_openapi`

### distribution model

- package build works via `poetry build`
- installation target is local `uvx --from /Users/regular/knowledge/personal/repositories/vikunja-mcp prism-vikunja-mcp`
- no package-registry publishing path is maintained for this project

### schema hardening and commit gate

- fixed swagger conversion so all array schemas include `items` (prevents mcp client error: `array schema missing items`)
- added `prism-vikunja-validate-schemas` command to validate every generated operation schema from swagger
- wired validation into `.pre-commit-config.yaml` so schema regressions block commits
