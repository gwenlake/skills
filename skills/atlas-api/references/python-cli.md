# The `gwenlake` Python library and command line

## Contents

- [Install](#install)
- [The client](#the-client)
- [Resources](#resources)
- [Errors](#errors)
- [Async](#async)
- [A route the library does not wrap](#a-route-the-library-does-not-wrap)
- [The command line](#the-command-line)

## Install

```bash
pip install -U gwenlake        # or: uv add gwenlake — Python 3.11 or later
```

Installing the library adds the `gwenlake` command, its alias `gwl`, and `gwenlake-train`.

Check the version (`gwenlake --version`). Since **0.30** the default endpoint is `https://atlas.gwenlake.com/api/v1`; an older library defaults to `https://api.gwenlake.com/v1` and misses resources — upgrade it, or name the endpoint (`base_url="atlas"`, `--base-url atlas`). Since 0.20 every route of the catalog has a method.

## The client

```python
from gwenlake import Gwenlake

client = Gwenlake(
    api_key=None,          # else a profile, GWENLAKE_API_KEY, the default profile
    credentials=None,      # Credentials(client_id=…, client_secret=…) for an OAuth2 client
    profile=None,          # a section of ~/.gwenlake/credentials
    base_url=None,         # "atlas" (default), a tenant's name ("acme"), a host or a URL
    timeout=60,            # seconds; connect timeout is 5 s
    max_retries=2,         # 5xx are retried with an exponential backoff
)
```

With no usable credentials the constructor raises a `GwenlakeException`. Inside a build the client needs no argument: the platform injects the build's identity.

| Variable | Meaning |
| --- | --- |
| `GWENLAKE_API_KEY` | the API key |
| `GWENLAKE_BASE_URL` | the endpoint: a tenant's name, a host or a URL |
| `GWENLAKE_PROFILE` | the credentials profile the command line uses |

A `.env` file in the working directory is loaded by the command line and the training module.

## Resources

Methods take and return plain dicts; listings come back already unwrapped (a list, not the `{"object": "list"}` envelope).

| Attribute | Covers |
| --- | --- |
| `client.projects` | `list`, `get`, `create`, `update`, `delete`, `datasets` |
| `client.filesystem` | folders, search, move / rename / restore of any resource |
| `client.datasets` | `list`, `get`, `create`, `update`, `delete`, `summary`, `empty`, `delete_rows`, branches, `maintenance`, vector `search` |
| `client.files` | `list`, `upload`, `download`, `presigned_url`, `delete` — all take the dataset id and `branch=` |
| `client.statements` | ad hoc SQL: `create`, `read_all`, `iter_arrow`, `to_dataframe`, `to_file` |
| `client.queries` | stored SQL queries and their versions |
| `client.transforms` | producers: `list`, `get`, `set_parameters`, `execute`, `functions` |
| `client.builds` | `run`, `plan`, `wait`, `run_and_wait`, `logs`, `cancel`, `wait_task` |
| `client.schedules` | `list`, `create`, `update`, `enable`, `trigger`, `delete` |
| `client.lineage` | the graph, `propagate`, branches of a lineage |
| `client.repositories` | repositories, `scan_lineage`, the git routes |
| `client.connections` | `list`, `get`, `list_files`, `iter_files`, `download`, `query`, `test` |
| `client.ml_models` | the catalog's ML models and their artifacts |
| `client.mediasets`, `client.syncs`, `client.flows` | mediasets, syncs, flows |
| `client.agents`, `client.skills`, `client.tools`, `client.ontologies`, `client.applications` | agents and what they use |
| `client.organizations`, `client.users`, `client.api_keys` | the organization, you, the API keys |
| `client.models`, `client.chat`, `client.embeddings` | inference |

`client.resolve("<project>.<dataset>")` turns a handle into a dataset id — the bridge between what SQL takes and what the resources take.

```python
dataset_id = client.resolve("sales.orders")
print(client.datasets.summary(dataset_id))
df = client.statements.to_dataframe("SELECT * FROM 'sales.customers'")
client.files.upload(dataset_id, "rows.parquet", mode="SNAPSHOT")
```

Before relying on a method this table does not spell out, check it exists in the installed version: `python -c "from gwenlake import Gwenlake; help(Gwenlake().builds)"`.

## Errors

- `gwenlake.exceptions.GwenlakeException`: what the library detects itself — no credentials, a handle that resolves to nothing.
- `httpx.HTTPStatusError`: the API answered an error status. Every resource calls `raise_for_status()`, so a `403` or `404` surfaces as this exception with the response attached.

```python
import httpx
from gwenlake.exceptions import GwenlakeException

try:
    rows = client.statements.create(statement="SELECT * FROM 'p.files'")
except GwenlakeException as e:
    print("library:", e)
except httpx.HTTPStatusError as e:
    print(e.response.status_code, e.response.json().get("detail"))
```

Always print `detail`: it names the missing scope, the faulty field or the conflicting build.

## Async

`AsyncGwenlake` takes the same arguments and has the same resources, awaited.

```python
import asyncio
from gwenlake import AsyncGwenlake

async def main():
    client = AsyncGwenlake()
    projects, datasets = await asyncio.gather(client.projects.list(), client.datasets.list())
    stream = await client.chat.create(model="…", messages=[…], stream=True)
    async for chunk in stream:
        print(chunk)

asyncio.run(main())
```

The transforms and training layers are synchronous: run them with `asyncio.to_thread` from an async program.

## A route the library does not wrap

Use the client's transport, which carries the credentials and the endpoint:

```python
from gwenlake.client import RequestOptions

response = client._client.send(RequestOptions(method="POST", url="/rerank", json_data={...}))
response.raise_for_status()
print(response.json())
```

## The command line

```
gwenlake [--profile NAME] [--api-key KEY] [--base-url URL] [--json] <resource> <command> [arguments]
```

Listings print as a table; **`--json` prints what the API answered**, ready for `jq` — use it whenever you parse the output. `gwenlake <resource> --help` lists a resource's commands. The global options are also accepted after the command.

**Names**: a dataset is `<project>.<dataset>` (slugs) or an id; a project is a slug or an id; builds, schedules, transforms, repositories and queries are named by id (their `list` shows the ids).

| Resource | Commands |
| --- | --- |
| `me` | who the credentials belong to |
| `projects` | `list`, `get`, `create`, `delete` |
| `datasets` | `list`, `get`, `summary`, `create`, `update`, `delete`, `empty`, `delete-rows`, `branches`, `export` |
| `files` | `list`, `upload` (`--mode APPEND\|SNAPSHOT\|UPSERT`, `--path`, `--branch`), `download`, `delete` |
| `sql` | run a statement; `--limit`, `--out file` (`.parquet`, `.csv`, `.json`, `.jsonl`), `-o - --format …` for stdout, `--file` |
| `builds` | `run` (`--target-only`, `--branch`, `--wait`, `--follow`, `--dry-run`), `retry`, `propagate`, `list` (`--target`, `--project`, `--status`, `--trigger`, `--since`, `--limit`), `get`, `logs` (`--tail`, `--follow`), `wait`, `cancel` (`--batch`) |
| `schedules` | `list`, `get`, `create`, `update`, `delete`, `trigger` |
| `transforms` | `list`, `get`, `set-parameters`, `execute`, `functions` |
| `repositories` | `list`, `get`, `scan`, `tree` |
| `queries` | `list`, `get`, `execute` |
| `lineage` | the graph around a dataset, a project or any resource id |
| `connections` | `list`, `get`, `files` |
| `search` | resources by name, optionally of one type |
| `models` | `list` (inference models), `ml` (the catalog's ML models) |
| `organizations` | `list`, `members` |
| `api-keys` | `list`, `create`, `delete` |
| `config` | `path`, `list`, `set-profile`, `remove-profile`, `endpoints` |

```bash
gwenlake me
gwenlake datasets list --project sales
gwenlake datasets summary sales.orders
gwenlake sql "SELECT region, count(*) FROM 'sales.order_lines' GROUP BY 1"
gwenlake sql "SELECT * FROM 'sales.customers'" --out customers.parquet
gwenlake datasets export sales.orders --out orders.csv --where "region = 'west'"
gwenlake builds run sales.customers --wait
gwenlake schedules list --project sales
```

**Destructive commands (`delete`, `empty`) ask for confirmation**; `--yes` skips it in a script — pass it only when the user asked for the deletion. `builds run`, `retry` and `propagate` with `--wait` or `--follow`, `builds wait` and `builds logs --follow` exit with status 1 when a build failed or was cancelled.

Profiles:

```bash
gwenlake config list                                         # the profiles, secrets masked
gwenlake config set-profile default --token sk-...
gwenlake config set-profile acme --token sk-... --hostname acme
gwenlake config set-profile elsewhere --token sk-... --base-url https://atlas.acme.example/api/v1
gwenlake config endpoints                                    # the endpoint in use
```

`gwenlake config list` is the safe way to see which profiles exist: never `cat` the credentials file.
