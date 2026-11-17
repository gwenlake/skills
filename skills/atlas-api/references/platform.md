# Platform: organizations, access, API keys, plans, route families

Paths are relative to the base URL. `$A` stands for `python scripts/atlas_api.py`.

## Contents

- [Who am I](#who-am-i)
- [Organizations](#organizations)
- [Roles and scopes](#roles-and-scopes)
- [API keys](#api-keys)
- [Plans and usage](#plans-and-usage)
- [Route families](#route-families)

## Who am I

`GET /users/me` answers the user the credentials belong to (`id`, `email`, `firstname`, `lastname`, `is_service_account`). `gwenlake me` and `$A whoami` do the same; the script also prints the endpoint in use. It is the first call to make when something answers `401` or `403`.

## Organizations

An organization is the company or team: it owns the members, the API keys, the storage where every dataset lands, and the projects. Reading it is open to its members; changing it is an admin's business.

| Request | Does |
| --- | --- |
| `GET /organizations`, `GET /organizations/{id}` | the organizations you belong to; one, with its `plan` and settings |
| `PATCH /organizations/{id}` | merges the `storage`, `git` and `iceberg` blocks field by field (a PATCH naming the bucket keeps the credentials) |
| `GET /organizations/{id}/members` | the members: name, email, role |
| `POST /organizations/{id}/members` | adds one, by `id` or `email`, with a `role` (`VIEWER` by default) |
| `PATCH /organizations/{id}/members` | changes a member's role |
| `DELETE /organizations/{id}/members/{user_id}` | removes one |
| `GET /organizations/{id}/api-keys` | the organization's API keys |
| `GET /organizations/{id}/llm-usage` | the month's inference spend against the budget |

Storage is an S3-compatible bucket or an SMB share (`storage.type`: `s3` or `smb`); `credentials` are write-only. On S3 the organization gets Iceberg tables with no setting; on SMB it opts in with an `iceberg` block, and without it datasets are file datasets. An SMB-backed organization has no presigned URLs. A `git` block gives the organization a git credential used for every repository on that host that has no token of its own.

Managing members takes the `members:manage` scope.

## Roles and scopes

Access is granted by membership: a role on an organization, a project or a single resource, and a role granted higher up covers everything below.

| Role | May |
| --- | --- |
| Viewer | read everything in scope: datasets, files, SQL, transforms, builds, connections, models, agents |
| Editor | the above, plus create and change projects, datasets, transforms, schedules, repositories, ontologies, agents and applications, and run transforms |
| Admin | the above, plus the organization's settings, its members, its API keys and its connections |

Every operation is gated on a **scope**, `<resource>:<action>`: `datasets:read`, `datasets:write`, `sql:read`, `transforms:run`, `connections:read`, `applications:write`, `projects:read`, `members:manage`, `apikeys:manage`… A role is a fixed set of scopes. A `403` names the one that is missing: `Missing scope 'datasets:read' on res.dataset.…`. The same message is answered for an id that does not exist, so check the id before concluding it is a rights problem.

Code run by the platform (a build) acts as the credential that triggered it, narrowed: it cannot manage members, keys, connections or the organization.

## API keys

An API key is **created in a project** and acts as the user who created it. Two bounds:

- it never reaches outside its project, whatever its creator's role elsewhere;
- it may carry `scopes`, a ceiling that only narrows: `["datasets:read", "sql:read"]` is a read-only key. A key never does more than its creator's role allows.

```bash
$A call POST /api-keys -d '{"name": "Nightly loader", "project_id": "res.project.…", "scopes": ["datasets:read", "datasets:write", "sql:read"]}'
```

The plain key is in the answer **once**; afterwards only `api_key_hint` is kept. Hand it to the user, do not write it to a file they did not ask for. `GET /api-keys` (`?project_id=`) lists keys with their `scopes` and `last_used_at`; `GET` / `DELETE /api-keys/{id}` read and revoke one. A revoked key answers `401`. CLI: `gwenlake api-keys list|create|delete`. (The guide writes this route `/apikeys`; if `/api-keys` answers `404` on your endpoint, try that spelling.)

An OAuth2 session — an interactive login or a client-credentials client (`Credentials(client_id=…, client_secret=…)`) — carries no project and no ceiling: it does what the user's roles allow. Use a client-credentials client for a service that must not hold a personal key.

## Plans and usage

An organization's `plan` is set by Gwenlake, never by a request. It bounds the number of projects, connections, datasets, agents, schedules and editors, and the monthly inference budget. A request refused by the plan alone answers **`402`**, not `403` — "not included" rather than "not allowed". Past the inference budget, model calls answer `402 insufficient_quota` until the month ends. `GET /users/me/plans` tells the plan of every organization the caller works in.

When you meet a `402`, tell the user it is a plan limit: retrying or changing credentials will not help.

## Route families

Where each family lives, and which reference details it.

| Family | Routes | Reference |
| --- | --- | --- |
| Identity | `/users/me`, `/users/me/plans` | this file |
| Organizations, members | `/organizations` | this file |
| API keys | `/api-keys` | this file |
| Projects, search | `/filesystem/projects`, `/filesystem/search` | `data.md` |
| Datasets, files, branches, vector search | `/datasets` | `data.md` |
| SQL | `/sql/statements`, `/sql/queries` | `data.md` |
| Mediasets | `/mediasets` | `data.md` |
| Connections, syncs | `/connections`, `/syncs` | `data.md` |
| Transforms | `/transforms` | `pipelines.md` |
| Builds, lineage, tasks, branches of a lineage | `/orchestration/…` | `pipelines.md` |
| Schedules | `/schedules` | `pipelines.md` |
| Repositories, git | `/repositories`, `/git/{id}/…` | `pipelines.md` |
| Inference | `/models`, `/chat/completions`, `/embeddings`, `/rerank` | `ai.md` |
| Agents, sessions, Klara | `/agents`, `/klara` | `ai.md` |
| Skills, MCP tools | `/skills`, `/tools` | `ai.md` |
| Ontologies | `/ontologies` | `ai.md`; the `atlas-ontologies` skill to build one |
| Traces (OTLP in) | `/traces` | `ai.md` |
| Applications | `/applications` | the `atlas-applications` skill |

The API reference at https://docs.gwenlake.com/atlas/api-reference/introduction documents, field by field, the families the public gateway exposes: inference, projects, datasets, files, SQL, connections. For the others, the guides under https://docs.gwenlake.com/atlas/guides/ are the source — and a `422` from the platform lists exactly which fields a body got wrong.
