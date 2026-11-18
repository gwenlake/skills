---
name: atlas
description: "Work with Gwenlake Atlas through the Gwenlake MCP server: find a project, dataset, ontology, document store or agent, answer questions about data in SQL, traverse an ontology, search documents, check lineage and builds, and build a pipeline (dataset, SQL query or code, transform, build, schedule). Start here for anything on Atlas; ontologies and applications have their own skills. Use whenever the user asks about their Atlas or Gwenlake data, or wants something created or run on the platform."
---

# Gwenlake Atlas through the MCP server

Atlas is a data platform. An **organization** holds **projects**, and a project holds everything else: datasets, mediasets (documents), ontologies, agents, transforms, repositories, models, schedules. The tools of the `gwenlake` MCP server act as the signed-in user, so they see exactly what that account sees.

Three rules hold for every tool:

- **Everything is addressed by id.** A name is not an id. Turn a name into an id first, with `search_catalog` or a listing.
- **An empty result means "not visible to this user"**, not "does not exist". Say it that way.
- **Answer from the tools, not from memory.** The data belongs to this organization; what you know about a company or a metric does not replace reading it.

## Find things

| The user says | Call |
|---|---|
| a name in words ("the sales dataset") | `search_catalog(query)`, optionally with `resource_type` |
| an organization by name | `list_organizations`, then pass its id as `organization_id` |
| nothing about which project | `list_projects`, then `list_project_contents(project_id)` |
| an id of unknown type | `get_resource(resource_id)`; `resource_type` says which tool applies |

`search_catalog` matches one substring of the name, case-insensitively. If the full phrase returns nothing, retry with the distinctive word alone before concluding. Organizations never appear in `list_projects`.

## Answer a question about data

Choose the route in this order:

1. **An agent covers the domain** (`list_agents`, `get_agent`): ask it with `ask_agent`. It carries instructions and bindings its author wrote. Keep the `session_id` to follow up and send only the new question. Attribute the answer to the agent. Each call costs inference, so do not ask several agents the same question.
2. **An ontology covers it** (`list_ontologies`): read the model with `get_ontology`, then `list_ontology_objects`, `get_ontology_object`, `list_linked_objects`. Object and link types are addressed by their `api_name`, and an object by the value of its primary key. Traversal is forward only. Ontologies flagged `is_standard` are reference vocabularies with no data behind them.
3. **Otherwise, SQL**: `describe_dataset(dataset_id)`, then `query_dataset(statement)`.

For documents, `search_mediaset(mediaset_id, query)` is the only way into their contents. It is an embedding search: ask a question in natural language, not keywords. `score` is a distance, so lower is closer. Only mediasets whose `media_type` is `document` can be searched, and one that was never indexed answers with an error; indexing cannot be started from the MCP server.

### SQL rules

- The dialect is DuckDB, read-only.
- A dataset is written `<project alias>.<dataset alias>` in a `FROM` clause. That string is `sql_name` in the answer of `describe_dataset`. It is neither the id nor the display name.
- To read a data branch instead of the trunk, append it: `FROM sales.orders:experiment-q3`. An unknown branch is an error.
- Results are capped (200 rows by default). When an answer carries `truncated: true`, never total the rows shown: put the `COUNT`, `SUM` or `GROUP BY` in the statement.
- Aggregate, filter and join in the query. Do not pull rows back to reason over them.

## Where data comes from, and whether it is fresh

- `get_lineage(resource_id, direction)`: `upstream` (built from), `downstream` (feeds), `both`. Lineage never leaves a project.
- `list_builds(target_id, status)` says what ran; statuses are `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`.
- `get_build(build_id)` gives the error of a failed build. `get_build_logs(build_id)` gives the output of a training run while it runs.
- `list_transforms(output_id=…)` says what produces a resource. `list_schedules` says what runs on its own.

## Build something

These tools change shared state. **Describe the plan and get the user's agreement before the first call.** If a tool answers that it is disabled on this MCP server, writing is off for this deployment or this plan: it is not a missing permission, so do not look for another way in. Tell the user the action must be done from the Atlas interface or the API.

Each step needs the id returned by the previous one.

**A dataset produced by SQL**

1. `create_dataset(project_id, name)`. Leave `type` unset.
2. `create_sql_query(project_id, name, sql)`. Name the sources as `<project alias>.<dataset alias>`; the inputs are derived from them.
3. `create_transform(project_id, name, type="sql", output_id=<dataset id>, config={"query_id": <query id>})`.
4. `run_build(target_id=<dataset id>)`, then poll `get_build`. The call returns as soon as the work is queued.
5. `create_schedule(project_id, name, cron, target_id)` if it must repeat.

**A dataset produced by Python**

1. `create_dataset`.
2. `read_repository` to learn the conventions of the existing code, then `push_repository_files(repository_id, ref, message, files)`.
3. If the pushed code declares its own transform (a `@transform_df` function, or a `.sql` file with `-- @output` headers), the push registers it. Otherwise `create_transform(type="python", config={"repository_id": …, "entrypoint": "path/to/script.py"})`.
4. `run_build`.

**A trained model**: create the model first with `create_model(project_id, name, repository_id, path)`, in the same repository as the training code, then push the code whose `@train` names it. The other order registers nothing.

**An ontology**: `create_ontology` and `update_ontology`, after profiling the data in SQL. The `atlas-ontologies` skill holds the format and the method; load it first.

**An application** (a dashboard or a screen): one `app.yaml`, checked with `validate_application`, then published with `create_application` or `update_application`. The `atlas-applications` skill holds the format and the widgets; load it first.

**An agent**: `create_agent(project_id, name, instructions, resource_ids=[…])`, then try it with `ask_agent`. The bound resources must be in the same project. Check `tool_warnings` in `get_agent`.

### Traps

- **One producer per output.** A second transform on the same output is refused. Check with `list_transforms(output_id=…)`, and never create a transform by hand for code that already declares one.
- **Same project everywhere.** Transform, output, inputs and query must share a project.
- **`push_repository_files` writes whole files.** Read the current content first, or the rest of the file is lost. A file returned with `truncated: true` must not be rewritten from what was shown. The branch must already exist; prefer a working branch to the default one.
- **`run_build` overwrites the target** on the branch given, and `main` is what everyone reads. Use a named data branch for anything exploratory. By default it also rebuilds what is stale upstream; `target_only=true` builds the one node.
- **`update_ontology` replaces each collection it is given**, and `update_application` replaces the whole definition. Read the current version first and send it back complete.
- **A schedule keeps acting after the conversation.** `time_zone` is an IANA name such as `Europe/Paris`, not an offset.

## What the MCP server does not do

It does not upload data, index a mediaset, create connections or syncs, or delete anything. Those are done in the Atlas interface or with the API, documented at https://docs.gwenlake.com/atlas/.
