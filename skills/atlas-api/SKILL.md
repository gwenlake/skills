---
name: atlas-api
description: Call the Gwenlake Atlas API — the REST API, the `gwenlake` Python library and the `gwenlake` command line — to work with the resources of an Atlas project. Covers authentication, projects, datasets and files, SQL, data branches, mediasets, connections and syncs, transforms, builds, lineage and schedules, repositories, inference (chat, embeddings, rerank), agents and their sessions, skills and MCP tools. Use this skill whenever the user wants to read, query, load, export or update data in Gwenlake Atlas (or "Atlas", "Gwenlake"), run or follow a build, schedule a refresh, call a model served by Gwenlake, talk to an Atlas agent from code, script the platform with `curl`, Python or the CLI, or debug an Atlas API error (401, 403, 409, 422) — even when they only name a dataset handle like `project.dataset` or an id like `res.dataset.…`. For building an Atlas application (`app.yaml`) use the `atlas-applications` skill, and for designing an ontology the `atlas-ontologies` skill.
compatibility: Needs network access to an Atlas endpoint and an API key (GWENLAKE_API_KEY or ~/.gwenlake/credentials). The bundled script needs Python 3.9+, standard library only; the `gwenlake` library needs Python 3.11+.
---

# The Gwenlake Atlas API

Gwenlake Atlas is a data and AI platform. Everything on it is a **resource** of a catalog — a dataset, a connection, a transform, an agent — with a typed id, living in a **project**, which lives in an **organization**. One HTTP API serves all of it, inference included.

This skill tells you how to reach that API and how its conventions work, then gives the recipes for the common jobs. The detail of each resource family is in `references/`; read the one the task needs.

## Three ways in

| Way | Use it when |
| --- | --- |
| **`scripts/atlas_api.py`** (bundled, standard library) | you have a shell and want one call, a SQL result or an upload without installing anything |
| **`gwenlake` Python library and CLI** (`pip install -U gwenlake`) | you are writing Python, exporting large results, following builds, or writing transforms |
| **Plain HTTP** (`curl`, any client) | another language, a backend, or a route the library does not wrap |

All three resolve the same credentials and talk to the same routes. Prefer the library or the CLI when they cover the job — they page, retry and wait for you — and fall back to HTTP for the rest.

```bash
python scripts/atlas_api.py whoami                                 # the user and the endpoint in use
python scripts/atlas_api.py call GET /filesystem/projects          # any route: call METHOD PATH [-q k=v] [-d JSON|@file] [-o file]
python scripts/atlas_api.py resolve <project>.<dataset>            # a handle → the dataset id
python scripts/atlas_api.py sql "SELECT * FROM '<project>.<dataset>' LIMIT 5"
python scripts/atlas_api.py upload <project>.<dataset> rows.parquet --mode SNAPSHOT
```

## Endpoint and authentication

- **Base URL**: `https://atlas.gwenlake.com/api/v1`. A tenant is `https://<tenant>.gwenlakeatlas.com/api/v1`; a platform on its own host serves the API under `/api/v1` (a gateway in front of it may serve `/v1`). The base URL carries the version; paths do not: `/datasets`, `/sql/statements`.
- **Authentication**: `Authorization: Bearer <token>` on every request — an API key (`sk-…`) or an OAuth2 access token.
- **Where the token comes from**, in order: an explicit key (`--api-key`, `api_key=`), a named profile (`--profile`, `profile=`, `GWENLAKE_PROFILE`), the `GWENLAKE_API_KEY` environment variable, the `default` profile of `~/.gwenlake/credentials`. The endpoint: `--base-url` / `base_url=`, `GWENLAKE_BASE_URL`, the profile's `base_url` (a URL) or `hostname` (a tenant's name), else the default.

```ini
# ~/.gwenlake/credentials — one section per profile
[default]
token = sk-...

[acme]
token = sk-...
hostname = acme
```

**An API key is confined to the project it was created in** and acts as its creator there, possibly narrowed to a list of scopes. So one machine often holds several profiles, one per project: when a project or a dataset "does not exist", you are probably using the wrong profile. `whoami`, then `GET /filesystem/projects`, tell you what the current credentials reach. Ask the user which profile to use rather than guessing; never print, log or commit a key.

Code that the platform runs (a transform build, a training) needs no key: the build's identity is injected. Keep scripts free of credentials.

## Conventions that hold everywhere

**Ids and handles.** Every resource has two names:

- an **id**, typed and permanent: `res.project.…`, `res.dataset.…`, `res.mediaset.…`, `res.connection.…`, `res.repository.…`, `res.transform.…`, `res.sync.…`, `res.schedule.…`, `res.agent.…`, `res.application.…`, `res.sql-query.…` (and `build.…`; an agent session is `conv_…`). **Routes take ids.**
- a **slug** (lowercase letters, digits, hyphens, underscores; also returned as `alias`, its former name). The **handle** of a resource is `<project_slug>.<slug>`: `sales.orders`. **SQL, transform bindings and the CLI take handles.**

To go from a handle to an id: `atlas_api.py resolve`, `client.resolve("p.ds")`, or list `GET /datasets?project_id=` and match the `slug`.

**Listings** answer `{"object": "list", "data": [...]}` and usually take `?project_id=` (or `?organization_id=`). A few orchestration routes answer a bare array (`GET /orchestration/builds`): handle both. Single objects come back as they are. The Python resources unwrap `data` for you.

**Errors** answer `{"detail": ...}` — a text, or for a `422` the list of faulty fields.

| Status | Meaning |
| --- | --- |
| `400` | well formed but cannot be honoured: an unknown branch, a reference across projects, a write mode the dataset's kind refuses, a statement that is not a single `SELECT` |
| `401` | missing, invalid or revoked token — or a token for another endpoint |
| `402` | the organization's plan does not include the feature, or its inference budget is spent (`insufficient_quota`) |
| `403` | no permission on the resource (`Missing scope 'datasets:read' on …`) or the operation does not apply. **An id that does not exist usually answers `403`, not `404`** |
| `404` | no such resource, or no such route at this endpoint |
| `409` | conflict with the resource's state: a taken slug, a second producer for a dataset, a build of the same function already running |
| `422` | the body or the parameters are invalid |
| `502` / `503` / `504` | a system behind the platform answered badly, could not queue the work, or was too slow: retry later |

**Permissions.** A role (Viewer reads, Editor creates and runs, Admin manages members, keys and connections) is a set of scopes written `<resource>:<action>`: `datasets:read`, `sql:read`, `transforms:run`. The `403` names the missing scope. See `references/platform.md`.

**Branches.** A tabular dataset can carry data branches; the trunk is `main`. Most data routes take `?branch=`, and SQL takes `'p.ds:branch'`. An unknown branch is a `400`, never a silent fall back.

**What is public.** The API reference documents inference, projects, datasets, files, SQL and connections. The other routes in this skill (agents, skills, tools, ontologies, syncs, schedules, orchestration, applications…) are the ones the Atlas interface uses; they are served at the same endpoint and documented in the guides, but they evolve faster. When a route answers `404` or a body is refused, trust the platform's answer over this file and check the guide (links at the end).

## Recipes

### Find your way

```bash
python scripts/atlas_api.py call GET /filesystem/projects                     # projects: slug, id
python scripts/atlas_api.py call GET /datasets -q project_id=res.project.…    # datasets: slug, id, type
python scripts/atlas_api.py call GET /datasets/res.dataset.…/summary          # rows, size, last modification
python scripts/atlas_api.py call GET /filesystem/search -q q=orders -q project_id=res.project.…
```

```python
from gwenlake import Gwenlake

client = Gwenlake()                       # or Gwenlake(profile="acme")
for p in client.projects.list():
    print(p["slug"], p["id"])
for d in client.datasets.list(project_id="res.project.…"):
    print(d["slug"], d["id"], d.get("type"))
```

A dataset's `type` decides how it is read: `iceberg` (a table: SQL), `files` (arbitrary files: the files routes; SQL only if it holds Parquet), `vector` (embeddings: search, no SQL).

### Query data with SQL

```bash
curl https://atlas.gwenlake.com/api/v1/sql/statements \
  -H "Authorization: Bearer $GWENLAKE_API_KEY" -H "Content-Type: application/json" \
  -d '{"statement": "SELECT region, count(*) AS n FROM '"'"'sales.order_lines'"'"' GROUP BY 1", "format": "json"}'
```

- The engine is **DuckDB**; a statement is a **single `SELECT`**, read-only. It may join datasets of the same organization.
- A dataset is its handle **in single quotes**: `FROM 'project.dataset'`. On a branch: `'project.dataset:branch'`.
- **Pass `"format": "json"`** over HTTP: the default there is `pyarrow` (an Arrow IPC file, binary). `csv` is the third format. JSON answers `{"object": "list", "data": [rows], "truncated", "limit"}`.
- **A result without a `LIMIT` of its own is cut at 1000 rows** (`"limit"` in the body raises the cap). The cut is reported: `truncated: true` in the JSON, `X-Gwenlake-Truncated: true` as a header for every format. Never present a truncated result as the whole table: aggregate in SQL, or page with `LIMIT`/`OFFSET`.
- To read a table whole, let the library page it: `client.statements.to_dataframe(sql)`, `read_all(sql)` (Arrow), `to_file(sql, "out.parquet")` — or `gwenlake sql "…" --out out.parquet`.
- To learn a dataset's columns, run `SELECT * FROM '…' LIMIT 5`; a tabular dataset created with a declared schema also carries `columns` on `GET /datasets/{id}`.

### Create a dataset and load data

```bash
python scripts/atlas_api.py call POST /datasets -d '{
  "slug": "orders", "name": "Orders", "project_id": "res.project.…", "type": "iceberg",
  "columns": [{"name": "order_id", "type": "long", "required": true}, {"name": "amount", "type": "double"}],
  "keys": ["order_id"]}'
python scripts/atlas_api.py upload <project>.orders orders.csv                  # APPEND
python scripts/atlas_api.py upload <project>.orders orders.csv --mode UPDATE    # upsert on the keys
```

`type`, `columns` and `keys` are optional: a new dataset is tabular where the organization supports it, and the schema is inferred from the first upload. An upload is a multipart `POST /datasets/{id}/files` (field `file`). On a **tabular** dataset the file is parsed (Parquet, CSV, JSON, JSON Lines, Excel, Avro, ORC, Arrow…) and written into the table according to `?mode=`:

| `mode` | Effect |
| --- | --- |
| `APPEND` (default) | adds the rows |
| `SNAPSHOT` | **replaces every row** with the upload |
| `UPDATE` | upserts on the dataset's key columns (`?keys=a,b` names others) |
| `DELETE` | no file: removes the rows matching `?delete_filter=` (`country == 'FR'`) |

On a **file** dataset the file lands as it is, optionally under `/files/{subdirectory}`. Details, downloads, presigned URLs, branches, vector search: `references/data.md`.

### Run and follow a build

A dataset produced by a transform or a sync is rebuilt by a **build**, which first rebuilds everything upstream of it.

```bash
gwenlake builds run <project>.<dataset> --dry-run     # the plan: what would run, nothing started
gwenlake builds run <project>.<dataset> --wait        # run, print each step; exit status 1 on failure
gwenlake builds logs build.… --follow
```

Over HTTP: `POST /orchestration/builds/plan` then `POST /orchestration/builds` with `{"target_id": "res.dataset.…"}`; follow with `GET /orchestration/builds/{id}` until `status` is `SUCCESS`, `FAILED` or `CANCELLED`. A `409` means a build of the same function is already running — wait for it, do not start another. Schedules, propagation, branches, repositories and transforms: `references/pipelines.md`.

### Call a model

The inference routes follow the OpenAI conventions, so any OpenAI-compatible client works with the Atlas base URL.

```python
from openai import OpenAI

oai = OpenAI(base_url="https://atlas.gwenlake.com/api/v1", api_key="sk-...")
oai.chat.completions.create(model="mistral/mistral-large-4", messages=[{"role": "user", "content": "Hello"}])
```

**List the models first** (`GET /models`, `client.models.list()`): each carries an `id` and a `kind` (`chat`, `embeddings`, `rerank`), and the catalog differs from one organization to the next. Ids are often prefixed by their provider (`mistral/mistral-large-4`, `intfloat/e5-base-v2`, `BAAI/bge-reranker-v2-m3`) — never invent one. Chat, embeddings and rerank in detail: `references/ai.md`.

### Talk to an agent

```bash
python scripts/atlas_api.py call GET /agents -q project_id=res.project.…
python scripts/atlas_api.py call POST /agents/res.agent.…/sessions -d '{"input": "Which tickets are older than a week?"}'
python scripts/atlas_api.py call POST /agents/res.agent.…/sessions/<session_id> -d '{"input": "And of those?"}'
```

The first call opens a session and answers an `agent.message` with the `session_id` (`conv_…`) and the `content`; the second continues it, with that id in the path (the history is kept server-side). An agent turn can take a while: raise `--timeout`. Agents, skills, MCP tools, ontologies and telemetry: `references/ai.md`.

## Before a call that changes something

Reads are free; these are not. Say what you are about to do and get the user's go-ahead unless they already asked for exactly that:

- `DELETE` on any resource. Deleting a dataset also deletes the transform or sync that produced it.
- `POST /datasets/{id}/empty`, an upload with `mode=SNAPSHOT` or `mode=DELETE`: they remove rows.
- Renaming a slug (`PATCH` with `slug`, or with `name` alone, which regenerates the slug): every SQL statement and binding that names the handle breaks.
- Starting a build or triggering a schedule: it rewrites datasets and consumes compute. Use the plan (`--dry-run`) first.
- Promoting or merging a data branch into the trunk.
- Creating an API key (the plain key is shown once), changing members or connections.

To try something without touching the trunk, write on a data branch (`?branch=experiment`) and read it back with `'p.ds:experiment'`.

## Pitfalls

- **Handle or id?** `client.datasets.get("p.ds")` and `GET /datasets/p.ds` fail: routes take ids. SQL fails the other way round.
- **Wrong profile.** A `403` or an empty listing with a correct name is usually an API key of another project.
- **Old library, old endpoint.** Before `gwenlake` 0.30 the library and the CLI defaulted to `https://api.gwenlake.com/v1`. Check `gwenlake --version`; upgrade, or pass `--base-url atlas`.
- **`pyarrow` by default.** A SQL answer that looks like binary garbage over HTTP is Arrow: ask for `"format": "json"`.
- **1000 rows.** A count computed client-side on a truncated result is wrong. Count in SQL.
- **A file dataset of CSVs is not queryable** (`403 Cannot query this dataset`): SQL reads tables and Parquet. Upload into a tabular dataset instead.
- **`-d` with `curl` and a quoted handle**: the single quotes of `'p.ds'` end the shell string. Put the body in a file (`-d @body.json`) or use the bundled script.
- **Timeouts.** A scan of a large table or an agent turn can exceed a default timeout: `timeout=` on the client or the call, `--timeout` on the script.

## Bundled files

- `scripts/atlas_api.py` — `whoami`, `call`, `resolve`, `sql`, `upload`; resolves credentials like the `gwenlake` command.
- `references/data.md` — projects, datasets, files, SQL statements and stored queries, data branches, vector search, mediasets, connections, syncs.
- `references/pipelines.md` — transforms, builds, lineage, propagation, schedules, branches across a lineage, repositories and the git routes.
- `references/ai.md` — models, chat, embeddings, rerank; agents and sessions, skills, MCP tools, ontologies, telemetry.
- `references/platform.md` — organizations, members, roles and scopes, API keys, plans; the full list of route families.
- `references/python-cli.md` — the `gwenlake` Python client (sync and async), its resources, and the command line.

The public documentation is at https://docs.gwenlake.com/atlas/ (index for agents: https://docs.gwenlake.com/atlas/llms.txt; API reference: https://docs.gwenlake.com/atlas/api-reference/introduction). If something here disagrees with what the platform answers, the platform is right: follow its error message.
