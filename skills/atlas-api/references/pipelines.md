# Pipelines: transforms, builds, lineage, schedules, repositories

Paths are relative to the base URL. `$A` stands for `python scripts/atlas_api.py`.

## Contents

- [How a pipeline exists](#how-a-pipeline-exists)
- [Transforms](#transforms)
- [Builds](#builds)
- [Lineage and propagation](#lineage-and-propagation)
- [Schedules](#schedules)
- [Testing a change on a branch](#testing-a-change-on-a-branch)
- [Repositories and the git routes](#repositories-and-the-git-routes)
- [Writing a Python transform](#writing-a-python-transform)

## How a pipeline exists

There is no pipeline object. Every **producer** of a dataset declares what it reads, and the platform derives the graph:

```
connection -> sync      -> dataset
connection -> transform -> dataset
datasets   -> train     -> model -> transform -> dataset
```

Producers are of four kinds: a **Python transform** (a decorated function in a git repository the platform scans), a **SQL transform** (a stored query, see `data.md`), a **ready-made transform** (OCR, chunking, embedding: parameters, no code), and a **sync** (a pull from a connection, see `data.md`). All of them run in a **build**. An output can never be an input of the same transform.

## Transforms

| Request | Does |
| --- | --- |
| `GET /transforms` (`?project_id=`) | lists: `type` (`python`, `sql`…), `output`, `inputs`, `config`, `last_execution` |
| `GET /transforms/{id}` | one transform |
| `POST /transforms` | creates one (a SQL transform: `{name, project_id, type: "sql", output, config: {query_id}}`) |
| `POST /transforms/{id}/execute` | runs this one producer, without its dependencies |

A Python transform's `config` names its `repository_id`, `entrypoint` and `function`; it is registered by a scan of the repository, not created by hand. Settings a transform can carry without a commit: `parameters` (handed to the code as `TRANSFORM_PARAMETERS`), `packages`, `requirements`, `python`.

Library: `client.transforms` (`list`, `get`, `set_parameters`, `execute`, `functions`). CLI: `gwenlake transforms list --project <slug>`, `get`, `set-parameters res.transform.… chunk_size=512`, `execute`, `functions`.

## Builds

A build targets one dataset, model or mediaset. The platform walks the graph upstream, orders the producers, creates one build per node and runs the chain. **Every upstream node with a producer is built again**, whether its inputs changed or not; a producer that fails stops the chain and cancels what was waiting.

| Request | Does |
| --- | --- |
| `POST /orchestration/builds/plan` — `{"target_id": "res.dataset.…"}` | what a build would run, nothing started: `steps` in order, each with `target_id`, `transform_id`, `outputs`, `depends_on`, and the data `branch`. Refused (`403`, `400`, `409`) exactly where the build would be |
| `POST /orchestration/builds` — same body | starts it: a batch with a `group_id` and the `builds`, each with `id`, `target_id`, `status`, `depends_on` |
| `GET /orchestration/builds` (`?target_id=`, `?limit=`) | builds, newest first — **a bare array, not a list envelope** |
| `GET /orchestration/builds/{id}` | one build: `status`, `triggered_by`, `started_at`, `finished_at`, `error_message` |
| `GET /orchestration/builds/{id}/logs` (`?tail=`, `?since=`) | its log; `since=` takes the `next` of a previous answer, to read only the new lines |
| `POST /orchestration/builds/{id}/cancel` | stops it |

Body options: `target_only` builds the target alone, without its upstream chain; `branch` writes on a data branch. Statuses: `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `CANCELLED`. Build ids look like `build.58d2bddbad62`.

A `409` such as `Build build.… is already RUNNING for the function … and rewrites …` means the same function is being built: wait for that build (or cancel it) rather than starting another.

```python
dataset = client.resolve("sales.customers")
for step in client.builds.plan(dataset)["steps"]:            # nothing started
    print(step["target_id"], step["depends_on"])
batch = client.builds.run_and_wait(dataset)                  # raises when the chain fails
print(client.builds.logs(batch["builds"][-1]["id"], tail=50)["logs"])
```

```bash
gwenlake builds run <project>.<dataset> --dry-run          # the plan
gwenlake builds run <project>.<dataset> --wait             # each step as it settles; exit 1 on failure
gwenlake builds run <project>.<dataset> --target-only --branch experiment --follow
gwenlake builds list --project <slug> --status failed --since 1d
gwenlake builds logs build.… --follow
gwenlake builds retry build.… --wait                       # the same target again, on its data branch
gwenlake builds cancel build.… --batch                     # the rest of its batch too
```

Over plain HTTP, poll `GET /orchestration/builds/{id}` every few seconds until the status settles; on `FAILED`, read `error_message` and the end of the log.

Logs are kept seven days, then archived. A build that stops reporting for ten minutes is marked failed.

## Lineage and propagation

| Request | Does |
| --- | --- |
| `GET /orchestration/lineage/{id}?direction=upstream\|downstream` | the graph around a resource: `root_id`, `nodes` (ids), `edges` (`source_id`, `target_id`, `transform_id`) |
| `POST /orchestration/lineage/{id}/propagate` | rebuilds everything **downstream** of a dataset (not the dataset itself). Answers a `task_id` at once |
| `GET /orchestration/tasks/{id}` | the task: `result.build_ids` once the builds are created, or `noop` when nothing downstream has a producer |

```python
task = client.lineage.propagate(dataset, branch="main")
print(client.builds.wait_task(task["task_id"])["result"])    # {"status": "dispatched", "build_ids": [...]}
```

CLI: `gwenlake lineage <project>.<dataset> --direction upstream`, `gwenlake builds propagate <project>.<dataset> --wait`.

## Schedules

A schedule runs an action on a cron expression.

```json
POST /schedules
{
  "name": "Nightly refresh",
  "project_id": "res.project.…",
  "trigger": {"type": "time", "cron": "0 6 * * *", "time_zone": "Europe/Paris"},
  "action": {"type": "build", "target_ids": ["res.dataset.…"]},
  "enabled": true
}
```

- **Trigger**: a cron of five or six fields; `time_zone` is an IANA name, `UTC` by default. A schedule in `Europe/Paris` fires at the local time through daylight-saving changes.
- **Action**: `build` (each of `target_ids`, dependencies included — a dataset, a model, or a mediaset, which runs its sync); `maintenance` (expires the snapshots older than `older_than_days` of each target: a dataset, a project or an organization); `flow` (each of `flow_ids`). One bad target never stops the others.

| Request | Does |
| --- | --- |
| `GET /schedules?project_id=`, `GET /schedules/{id}` | lists; one with its `last_execution` |
| `PATCH /schedules/{id}` | changes the trigger, the action or `enabled` |
| `POST /schedules/{id}/trigger` | fires it now |
| `DELETE /schedules/{id}` | removes it |

A schedule's builds run with the platform's own trust, not a user's credential, and appear in the targets' history with `triggered_by: SCHEDULE`.

```python
from gwenlake.schedules import build_action, time_trigger

client.schedules.create({"name": "Nightly refresh", "project_id": "res.project.…",
                         "trigger": time_trigger("0 6 * * *", "Europe/Paris"),
                         "action": build_action("res.dataset.…"), "enabled": True})
client.schedules.enable("res.schedule.…", False)
client.schedules.trigger("res.schedule.…")
```

CLI: `gwenlake schedules create --project <slug> --name "Nightly refresh" --cron "0 6 * * *" --time-zone Europe/Paris --target <project>.<dataset>`, `update res.schedule.… --cron "*/15 * * * *"`, `trigger`, `list`, `delete`.

## Testing a change on a branch

A build with a `branch` writes its outputs on that data branch, reads its tabular inputs on it when they have it (the trunk otherwise), and checks out the **git branch of the same name** when the repository has one. Prefer specific names (`experiment-q3`) over `dev`.

| Request | Does |
| --- | --- |
| `POST /orchestration/branches` — `{"root_id": "res.dataset.…", "name": "experiment-q3", "build": true}` | forks the branch on every tabular dataset of the root's lineage, upstream and downstream, and optionally builds it there |
| `POST /orchestration/branches/merge` — `{"root_id", "name", "delete_branch": true}` | promotes every dataset of the lineage to the trunk |
| `DELETE /orchestration/branches/{name}?root_id=` | drops the branch without promoting it |
| `POST /datasets/{id}/branches/{name}/promote` | promotes a single dataset's branch |

Check the result on the branch with SQL (`'p.ds:experiment-q3'`) before merging. A build on a branch whose output is a file dataset is refused: a file dataset has one version.

## Repositories and the git routes

A repository is a git remote declared in a project: the code of the transforms and trainings, `.sql` files, `*.agent.md` files, model artifacts.

```json
POST /repositories
{"name": "Sales pipelines", "slug": "sales-pipelines", "project_id": "res.project.…",
 "configuration": {"type": "git", "provider": "gitlab", "url": "https://gitlab.example.com/data/sales-pipelines.git",
                   "default_branch": "main", "credentials": {"token": "glpat-…"}}}
```

The token is write-only: a read returns the configuration without it. `PUT /repositories/{id}/credentials` rotates it, `PATCH` changes the rest, `DELETE` removes the repository but not the transforms scanned from it. A repository without a token uses the organization's git credential when the URL is on its git host.

**A scan** registers what the repository declares, in its project:

| File | Declares |
| --- | --- |
| `*.py` with `@transform_df`, `@transform`, `@train` | a Python transform or a training, with its inputs, outputs, models and connections |
| `*.sql` with `-- @output:` headers | a stored query and the SQL transform wired to it |
| `*.agent.md` | an agent |

A scan runs when the repository is saved, after each successful build, and on demand: `POST /orchestration/repositories/{id}/scan-lineage?ref=`, `client.repositories.scan_lineage(id, wait=True)["result"]` (`transforms_found`, `edges_created`, `edges_removed`, `warnings`), `gwenlake repositories scan res.repository.… --wait`. A scan of the default branch is authoritative: it removes the transforms whose declaration is gone. After changing a transform's inputs or outputs in code, scan before building.

The git routes read and change a repository through the platform, without a clone:

| Request | Does |
| --- | --- |
| `GET /git/{id}/branches` | the branches |
| `GET /git/{id}/tree?ref=&path=` | the entries of a directory at a ref |
| `GET /git/{id}/file?path=&ref=` | one file |
| `POST /git/{id}/commit` | a commit of one or several files: `[{path, operation, content}]`, binaries in base64 |
| `POST /git/{id}/branches`, `DELETE /git/{id}/branches/{name}` | creates or deletes a branch |
| `POST /git/{id}/import` | copies one file of the repository into a dataset |

CLI: `gwenlake repositories list --project <slug>`, `get`, `scan`, `tree`.

## Writing a Python transform

Transforms are written with the `gwenlake.transforms` decorators; bindings name resources by handle.

```python
from gwenlake.transforms import transform_df, Input, Output

@transform_df(
    flights=Input("flights.flight-data"),
    delayed=Output("flights.delayed"),
)
def keep_delayed(flights):                     # a pandas.DataFrame in, a DataFrame out
    return flights[flights["arr_delay"] > 15]
```

- `transform_df` loads each input whole and replaces the output's content with what the function returns.
- `transform` hands `TransformInput`/`TransformOutput` objects for explicit IO: `dataframe()`, `iter_dataframes()` (chunks), `to_parquet()`, `write_dataframes()`, and `.filesystem()` (`ls`, `open`, `read`, `write`, `delete`) for raw files. `columns=` on a binding is the cheapest way to read less.
- Other bindings: `Model("crm.churn")`, `Connection("ops.drop-folder")` (a read-only filesystem over a connection).
- `@incremental`, stacked above, makes writes add to the output and gives inputs a `dataframe("added")` (the rows appended since the last successful run); bump `semantic_version` to start over.
- Call the decorated function with a client to run it from your machine (`keep_delayed(client)`); in a repository the platform builds, a module holding several transforms ends with `run(client, ...)` so a build runs only the one it targets.

Inside a build the library needs no key, carries the build's data branch, and the entrypoint runs with `uv run` from the repository root (its `pyproject.toml` and `uv.lock`, or PEP 723 inline metadata). The full guide — files, several outputs, incremental runs, trainings on the GPU pool, MLflow — is at https://docs.gwenlake.com/atlas/guides/transforms and the pages next to it; read it before writing anything beyond the simple form above.
