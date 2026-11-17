# AI: models, agents, skills, MCP tools, ontologies, telemetry

Paths are relative to the base URL. `$A` stands for `python scripts/atlas_api.py`.

## Contents

- [Models](#models)
- [Chat completions](#chat-completions)
- [Embeddings](#embeddings)
- [Rerank](#rerank)
- [Agents](#agents)
- [Agent sessions](#agent-sessions)
- [Skills](#skills)
- [MCP servers (tools)](#mcp-servers-tools)
- [Ontologies](#ontologies)
- [Telemetry](#telemetry)

## Models

`GET /models` lists the inference models the caller may use. Each has an `id` — the `model` of the other inference routes — and a `kind`: `chat`, `embeddings` or `rerank`, plus `owned_by`, `pricing`, `context_window`.

```bash
$A call GET /models
gwenlake models list
```

The catalog depends on the organization and evolves. Ids are frequently prefixed by a provider (`mistral/mistral-large-4`, `intfloat/e5-base-v2`, `BAAI/bge-reranker-v2-m3`): **list, then copy an id of the right kind**. Examples in the documentation use ids (`llama-3.1-8b`, `e5-base-v2`) that may not exist where you are.

These models are separate from the **ML models of the catalog** (`res.model.…`), which a `@train` function produces and a transform loads (`gwenlake models ml`, `client.ml_models`).

A model call refused with `402` and `insufficient_quota` means the organization's monthly inference budget is spent.

## Chat completions

`POST /chat/completions` is OpenAI-compatible; the body is relayed as it is.

```bash
$A call POST /chat/completions -d '{
  "model": "mistral/mistral-large-4",
  "messages": [{"role": "system", "content": "You answer in one sentence."},
               {"role": "user", "content": "Describe Argentina."}]}'
```

```python
response = client.chat.create(model="mistral/mistral-large-4", messages=messages)     # temperature defaults to 0
print(response["choices"][0]["message"]["content"])

for chunk in client.chat.create(model=…, messages=messages, stream=True):           # server-sent event lines
    print(chunk)

client.chat.create(model=…, messages=…, response_format={"type": "json_object"})    # or a JSON schema
```

Any OpenAI-compatible client works by setting its `base_url` to the Atlas base URL and its `api_key` to the Gwenlake key. With `"stream": true` the answer is the SSE frames of the model.

## Embeddings

`POST /embeddings` — `{"model": "<an embeddings model>", "input": "a text" | ["texts", …]}` — answers `{"object": "list", "data": [{"object": "embedding", "index", "embedding": [...]}], "usage"}`.

```python
response = client.embeddings.create(input=texts, model="intfloat/e5-base-v2")   # batches of 100 for you
for item in response.data:
    print(item.index, len(item.embedding))
print(response.usage.total_tokens)
```

`index` follows the order of the input. To search a vector dataset, do not embed yourself: `POST /datasets/{id}/search` embeds the query with the dataset's own model (`data.md`).

## Rerank

`POST /rerank` scores documents against a query — the second stage after a vector search.

```json
{"model": "BAAI/bge-reranker-v2-m3", "query": "What is the refund policy?",
 "input": ["Shipping takes 3 days.", "Refunds are accepted within 30 days."], "top_n": 1}
```

The documents travel as `input` (strings); `top_n` keeps the best ones, all when omitted. The answer is `{"object": "list", "data": [{"index": 1, "relevance_score": 0.17}]}`, by decreasing relevance, `index` being the position in `input`.

The library has no rerank resource; use its transport:

```python
from gwenlake.client import RequestOptions

r = client._client.send(RequestOptions(method="POST", url="/rerank", json_data={...}))
r.raise_for_status()
```

## Agents

An agent is an LLM agent hosted by the platform: a model, instructions, tools, and the data of its project within reach. It is defined by one file, `agent.md` — YAML frontmatter, then the instructions in Markdown:

```markdown
---
name: Ops assistant
model: mistral/mistral-large-4
tools:
  - web-search
skills:
  - pdf
resources:
  - ref: ops.tickets
  - ref: ops.runbooks
    tools: [search]
mcp:
  - ref: ops.jira
---

You help the operations team answer questions about open tickets and the
runbooks. Query the data before answering; cite the ticket id you relied on.
```

| Key | Meaning |
| --- | --- |
| `name` | the agent's name |
| `model` | an inference model id of kind `chat` |
| `tools` | built-in tools: `web-search`, `web-reader`, `wikipedia`, `duckduckgo`, `yahoo-finance`, and the platform's own build tools |
| `skills` | skills the agent may load: a built-in one by name, or a skill of the project by slug or id |
| `resources` | datasets, ontologies and mediasets of the project, by handle; `tools:` narrows a binding to some capabilities |
| `mcp` | remote MCP servers: a tool resource of the project (`ref`/`id`), or an inline `{url, headers, …}` |

Each bound resource becomes tools named `<slug>__<capability>`:

| Resource | Capabilities |
| --- | --- |
| tabular dataset | `query` (SQL on that dataset), `schema`, `summary` |
| vector dataset | `search`, `summary` |
| ontology | `model`, `list_objects`, `get_object`, `list_links`, `list_linked_objects` |
| mediaset | `list_files`, `summary`, `presigned_url` |

A tool runs with the **caller's** rights: an agent never reads more than its user may.

| Request | Does |
| --- | --- |
| `GET /agents` (`?project_id=`), `GET /agents/{id}` | lists, reads one |
| `POST /agents` | creates one, with the structured fields or the raw `definition` text (the whole `agent.md`) and a `project_id` |
| `GET /agents/tools` | what an agent can name: `builtin` tools, `platform` tools, the library of `skills`, and the capabilities of each resource kind |
| `GET /agents/{id}/tools` | the tools resolved for this agent (MCP tools excepted: they exist for the run) |
| `POST /agents/{id}/tools/{name}/invoke` | calls one tool by hand |

A file named `*.agent.md` in a repository the platform scans becomes an agent of the repository's project, versioned with the code — the preferred way for an agent that lives with its pipeline.

## Agent sessions

A conversation is a **session**: the history is kept server-side, only the new input travels, and a session is private to whoever opened it.

```bash
# open a session with a first message
$A call POST /agents/res.agent.…/sessions -d '{"input": "Which tickets are older than a week?"}' --timeout 300
# continue it
$A call POST /agents/res.agent.…/sessions/<session_id> -d '{"input": "And of those, which mention billing?"}'
```

The body takes `input`, `stream`, and per-turn overrides `model`, `temperature`, `timeout`. The reply is an `agent.message` with the `session_id` (`conv_…` — copy it from the answer, do not build it), the `content`, the `thinking` when the model exposes it, the tool calls it made and the token `usage`.

| Request | Does |
| --- | --- |
| `GET /agents/{id}/sessions` | your sessions |
| `GET` / `DELETE /agents/{id}/sessions/{session_id}` | reads or drops one |

With `"stream": true` the reply is server-sent events, one JSON frame per line, ended by `data: [DONE]`: answer frames carry `content`, reasoning frames `event: "thinking"`, and each tool call a `tool_started` then a `tool_completed` frame with the tool's name, arguments and result.

A turn that reaches an MCP server which cannot be reached fails with a `502` naming it.

**Klara** is the built-in assistant, at `POST /klara` with no setup: a build assistant that creates projects, datasets, ontologies and pipeline code when asked. Each turn names where to work (`organization_id`, `project_id`).

## Skills

A skill is one Markdown file, `SKILL.md`, in the Agent Skills convention: instructions an agent loads when a task calls for them. On Atlas it is a resource of a project, versioned like a query.

| Frontmatter key | Meaning |
| --- | --- |
| `name` | the skill's name, what an agent definition refers to |
| `description` | when to load it: the agent reads every description and picks from them |
| `license`, `compatibility` | informative |
| `allowed-tools` | the tools the skill expects, space-separated (`allowed_tools` over the API) |
| `metadata` | free key-value pairs |

| Request | Does |
| --- | --- |
| `POST /skills` | creates one in a project, from the text (`{name, project_id, definition}` — `definition` is the whole file) or the structured fields (`name`, `description`, `instructions`…) |
| `GET /skills?project_id=`, `GET /skills/{id}` | lists, reads one |
| `PATCH /skills/{id}`, `DELETE /skills/{id}`, `POST /skills/{id}/restore` | updates, deletes, restores |
| `GET /skills/{id}/versions` | the history |

```bash
jq -n --arg project "$PROJECT_ID" --rawfile definition SKILL.md \
  '{name: "quarterly-report", project_id: $project, definition: $definition}' > body.json
$A call POST /skills -d @body.json
```

A project skill is the `SKILL.md` file alone — no `references/` or `scripts/` beside it. The resource's `name` and `description` are the file's: renaming the resource rewrites the frontmatter. `?branch=` addresses a data branch's copy.

An agent names the skills it may load under `skills:`, built-in by name, project skills by slug or id; a project skill named like a built-in one replaces it for that agent. The built-in library is listed by `GET /agents/tools`, under `skills` (`pdf`, `docx`, `xlsx`, `pptx` and others): list it rather than assuming a name.

## MCP servers (tools)

A remote MCP server is declared once per project as a **tool** resource, with its credential encrypted and never shown again.

```json
POST /tools
{"name": "Jira", "slug": "jira", "project_id": "res.project.…",
 "configuration": {"type": "mcp", "url": "https://mcp.example.com/jira/sse", "auth": "headers",
                   "credentials": {"headers": {"Authorization": "Bearer …"}}}}
```

| Field | Meaning |
| --- | --- |
| `url` | the server's endpoint, `http` or `https` |
| `transport` | `sse`, the only one accepted |
| `timeout`, `sse_read_timeout` | seconds |
| `auth` | `headers` (static headers) or `client_credentials` (an OAuth2 client, with `token_url` and `scope`) |
| `credentials` | `{headers}` or `{client_id, client_secret}`; write-only |

`GET /tools?project_id=` lists them; a read returns the configuration with `has_credentials: true`. `PATCH /tools/{id}` deep-merges the configuration (changing the URL keeps the headers; rotating a token is one `PATCH`). **`POST /tools/{id}/test`** reaches the server with the stored credential and answers its tool list: test a declaration before an agent depends on it.

An agent names the server under `mcp:` by `ref`. The inline form (`url`, `headers`) works but leaves the headers in clear in `agent.md` and every version of it: prefer the resource. Only remote servers are accepted; an entry naming a local `command` is refused.

## Ontologies

An ontology describes a domain as object types, link types and action types, and may bind each object type to the dataset holding its instances. It is declarative: no lineage, no builds. **To design, generate or fix one, use the `atlas-ontologies` skill**: the format has traps (the three collections are lists, not the maps the public guide shows; bindings are not validated when saved) that it covers in full.

```json
POST /ontologies
{
  "name": "Sales", "project_id": "res.project.…", "api_name": "sales", "version": "1",
  "object_types": [
    {"api_name": "customer", "display_name": "Customer", "primary_key": "customer_id",
     "properties": {"customer_id": {"data_type": "string", "required": true}, "name": {"data_type": "string"}},
     "dataset_id": "res.dataset.…"}
  ],
  "link_types": [
    {"api_name": "places", "source_object_type": "customer", "target_object_type": "order",
     "cardinality": "ONE_TO_MANY", "foreign_key_property": "customer_id"}
  ]
}
```

- `data_type`: `string`, `integer`, `long`, `short`, `byte`, `double`, `float`, `decimal`, `boolean`, `date`, `timestamp`.
- `cardinality`: `ONE_TO_ONE`, `ONE_TO_MANY`, `MANY_TO_MANY`. A link is backed by a foreign key on the **target** (`foreign_key_property`, holding the source's primary key) or by an edge dataset (`dataset_id` with `source_key`/`target_key`).
- Identifiers match `[A-Za-z_][A-Za-z0-9_]*`. A property name is the bound dataset's column name; only declared properties are ever read.

| Request | Does |
| --- | --- |
| `GET /ontologies` (`?project_id=`) | summaries: identity, `api_name`, `version`, `is_standard` — including the twenty standard ontologies the platform ships (`general`, `business`, `finance`, `maritime`, …), global and read-only |
| `GET /ontologies/{id}` | the whole specification |
| `PATCH /ontologies/{id}` | a collection given replaces the stored one wholesale |
| `DELETE /ontologies/{id}` | deletes it |
| `GET /ontologies/{id}/objects/{object_type}?limit=&offset=` | the instances, as a JSON-LD `@graph` |
| `GET /ontologies/{id}/objects/{object_type}/{pk}` | one node |
| `GET /ontologies/{id}/objects/{object_type}/{pk}/links/{link_type}` | the objects linked to that node |
| `GET /ontologies/{id}/links/{link_type}` | the edges, as `source`/`target` references |

Instances are served as `application/ld+json`; the caller must be able to read both the ontology and the dataset. An ontology bound to an agent is queried first, before the datasets behind it.

## Telemetry

Every turn of an agent runs under an OpenTelemetry trace filed under the agent's project: an `AGENT` span per turn, an `LLM` span per model call (model, tokens, latency), a `TOOL` span per tool call (name, arguments, result). Traces are browsed from the Atlas interface; reading them back over the API is not offered.

An application of your own files its traces under a project with the standard OTLP-over-HTTP exporter, authenticated by **an API key created in that project** (an OAuth2 session carries no project and is refused):

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://atlas.gwenlake.com/api/v1/traces
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer $GWENLAKE_API_KEY"
export OTEL_SERVICE_NAME=order-scoring
```

Set `user.id` on spans to name the person a trace is about, and keep the standard attribute names (`gen_ai.*` for model calls). Tool results appear in traces as the agent saw them: bind agents to the data they need and no more.
