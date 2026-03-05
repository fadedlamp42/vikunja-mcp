`ses_3440e116effe7kLNrWzcn5JrI2`

# prism-vikunja-mcp

python-native mcp server for vikunja with broad swagger-derived coverage.

## why this exists

the existing npm package (`@democratize-technology/vikunja-mcp`) had multiple runtime issues in real use:

- wrong env var contract vs published examples (`VIKUNJA_API_BASE` vs `VIKUNJA_URL`)
- schema/transport failures in tool listing on one package variant
- endpoint behavior mismatches for task listing on another package variant

this server avoids that fragile stack and reads vikunja's own swagger (`/api/v1/docs.json`) to build tools directly.

## what it exposes

- one mcp tool per vikunja swagger operation (auto-generated)
- `vikunja_list_operations` for discovery and filtering
- `vikunja_reload_openapi` to refresh the operation list at runtime

## configuration

required:

- `VIKUNJA_API_BASE` (example: `https://vikunja.example.com` or `https://vikunja.example.com/api/v1`)
- `VIKUNJA_API_TOKEN`

optional:

- `VIKUNJA_OPENAPI_URL` (default derives from `VIKUNJA_API_BASE`)
- `VIKUNJA_VERIFY_TLS` (`true` by default)
- `VIKUNJA_CA_BUNDLE` (path to custom ca bundle)
- `VIKUNJA_REQUEST_TIMEOUT_SECONDS` (default `30`)

## local development

```bash
poetry install
poetry run prism-vikunja-mcp
```

## pre-commit validation

this repo uses `ruff` + `pre-commit`, plus a schema validation hook that checks every generated tool schema from vikunja swagger.

```bash
poetry run pre-commit install
poetry run pre-commit run --all-files
```

the validation hook runs:

```bash
poetry run prism-vikunja-validate-schemas
```

you can point validation to a different instance:

```bash
VIKUNJA_VALIDATION_OPENAPI_URL="http://vikunja.prism-dynamics.org/api/v1/docs.json" poetry run prism-vikunja-validate-schemas
```

## quick mcp client config (local)

```json
{
  "vikunja": {
    "type": "stdio",
    "command": "poetry",
    "args": [
      "run",
      "prism-vikunja-mcp"
    ],
    "env": {
      "VIKUNJA_API_BASE": "https://vikunja.example.com",
      "VIKUNJA_API_TOKEN": "tk_your_token_here"
    }
  }
}
```
