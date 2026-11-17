# The applications API

For a backend or an agent that talks to Atlas over HTTP rather than through `scripts/atlas_app.py`. The format of the file itself is in `SKILL.md`.

## Contents

- [Basics](#basics)
- [Routes](#routes)
- [Validate](#validate)
- [Create](#create)
- [Save a revision](#save-a-revision)
- [Read an application](#read-an-application)
- [The normalized form (`spec`)](#the-normalized-form-spec)
- [Read a source](#read-a-source)
- [Status codes](#status-codes)
- [A Python client](#a-python-client)
- [Finding ids and data](#finding-ids-and-data)

## Basics

- **Base URL**: `https://atlas.gwenlake.com/api/v1`. A tenant is `https://<tenant>.gwenlakeatlas.com/api/v1`; a platform on its own host serves the API under `/api/v1` (a gateway in front of it may serve `/v1`).
- **Authentication**: `Authorization: Bearer <token>` — an API key (`sk-…`) or an OAuth2 access token. An API key is created in a project, acts as its creator and **never reaches outside its project**: it cannot create an app in another project nor name a dataset of another project as a source.
- **The application text is raw YAML**: `Content-Type: application/yaml` (`application/x-yaml`, `text/yaml` and `text/x-yaml` are accepted). Any other content type on a YAML route is a `415`. The body is UTF-8, 256 KiB at most (`413` beyond).
- **Listings** answer `{"object": "list", "data": [...]}`. Errors answer `{"detail": ...}`.
- **Scopes**: `applications:read` to read (the app, its YAML, its revisions, its sources), `applications:write` to create and save. Viewer role reads; Editor role writes.
- **Branches**: the file is stored per data branch. Every route takes `?branch=` (`main` by default); a branch without a copy of its own reads `main`'s.

The `gwenlake` Python library has `client.applications` (`list`, `get`, `create`, `update`, `delete`) but it sends JSON only: it lists, reads and deletes applications, it cannot send an `app.yaml`. Use plain HTTP for the YAML routes.

## Routes

| Request | Does |
| --- | --- |
| `GET /applications?project_id=` (or `?organization_id=`) | the applications you can read |
| `POST /applications/validate` — YAML body | validates, saves nothing; always `200` |
| `POST /applications?project_id=` — YAML body | creates a declarative application; `201` |
| `PUT /applications/{id}` — YAML body | saves a new revision |
| `GET /applications/{id}` | the application, with `spec`, `version`, `warnings` |
| `GET /applications/{id}` with `Accept: application/yaml` | the YAML source |
| `GET /applications/{id}/versions` | the revisions, newest first (`?limit=`, 50 by default, 500 at most) |
| `PATCH /applications/{id}` — JSON body | updates the row's fields (name, description); not the YAML |
| `DELETE /applications/{id}` | deletes the application; `204` |
| `POST /applications/{id}/sources/{source}/read` — JSON body | reads a source |
| `GET /applications/{id}/sources/{source}/columns` | the columns of a source, `{name, type}` |

Ids are typed strings: `res.application.…`, `res.project.…`.

## Validate

```bash
curl -X POST "$BASE/applications/validate?project_id=$PROJECT_ID" \
  -H "Authorization: Bearer $GWENLAKE_API_KEY" \
  -H "Content-Type: application/yaml" \
  --data-binary @app.yaml
```

`--data-binary`, not `-d`: `-d` strips newlines and the YAML arrives broken.

- Without `project_id` nor `application_id`, only the format and the SQL are checked. With `?project_id=` (or `?application_id=`, for an existing app), the datasets named by the sources are also checked: each must exist in that organization and be readable by you.
- The answer is always `200`; an invalid document is a result, not a failed request:

```json
{
  "object": "application.validation",
  "valid": false,
  "spec": null,
  "errors": [
    { "path": "widgets.filtre.props.bind", "message": "`bind` must be `state.<id>` with a declared state variable (got `state.secteur`).", "line": 37, "column": 7 },
    { "path": "layout.row[0].column.rows[2].tableau", "message": "No widget `tableau` is declared under `widgets`.", "line": 29, "column": 13 }
  ],
  "warnings": []
}
```

- `path` names the element in the source document: keys joined by dots, list positions in brackets. It is empty for the document itself (a YAML syntax error, a duplicate key).
- `spec` is the normalized form when `valid` is true. `warnings` are only reported for a valid document: a widget declared but not placed, a source nothing reads, a state variable nothing uses.
- This validation **does not check widget types nor their props** (other than `source`, `bind` and `${state.x}`): the interface owns the list of widgets. Check them against the widget table yourself.

## Create

```bash
curl -X POST "$BASE/applications?project_id=$PROJECT_ID" \
  -H "Authorization: Bearer $GWENLAKE_API_KEY" \
  -H "Content-Type: application/yaml" \
  --data-binary @app.yaml
```

- `project_id` is required. The application is named after `metadata.title`, its slug is `metadata.name`, and the YAML is its first revision.
- `201` with the application (same shape as [Read an application](#read-an-application)).
- `422` when the definition is invalid — nothing is created:

```json
{
  "detail": "The app definition is invalid (2 errors) — nothing was saved.",
  "errors": [ { "path": "...", "message": "...", "line": 12, "column": 5 } ]
}
```

- `409` when the slug is already taken in the project.

A JSON body on the same route creates an application from a **template** (`{name, project_id, template, configuration}`): the older, hand-coded kind. Do not use it for a new application.

## Save a revision

```bash
curl -X PUT "$BASE/applications/$APP_ID?base_version=$VERSION" \
  -H "Authorization: Bearer $GWENLAKE_API_KEY" \
  -H "Content-Type: application/yaml" \
  --data-binary @app.yaml
```

- The text is stored as sent, comments included. Saving the same text twice adds no revision.
- `?base_version=` is the revision your edit started from (the `version` of the application you read, or the `x-gwenlake-version` header of its YAML). A save over a newer revision is refused with `409`: read again, merge, save. Leave it out to overwrite.
- A save on `main` keeps the application's name and slug equal to `metadata.title` and `metadata.name`: changing them renames the application (`409` if the new slug is taken).
- `422` with `errors` when invalid, `400` on a template application.

Restoring an old revision is saving its text again: `GET /applications/{id}?version=<id>` with `Accept: application/yaml`, then `PUT`.

## Read an application

```bash
curl "$BASE/applications/$APP_ID" -H "Authorization: Bearer $GWENLAKE_API_KEY"
```

```json
{
  "object": "application",
  "id": "res.application.…",
  "name": "Suivi du portefeuille crédit",
  "slug": "suivi-portefeuille",
  "project_id": "res.project.…",
  "spec": { "apiVersion": "atlas/v1", "kind": "App", "metadata": {}, "sources": {}, "state": {}, "layout": {}, "widgets": {} },
  "warnings": [],
  "errors": [],
  "version": "…",
  "storage": { "path": "…", "version": "…" }
}
```

- `?version=` reads an older revision, `?branch=` another data branch.
- A **template** application answers without `spec`, `version` nor `storage`, and carries `template`. That is how to tell the two kinds apart; a template application cannot take a YAML.
- With `Accept: application/yaml` the answer is the YAML source, and the `x-gwenlake-version` header names the revision.

## The normalized form (`spec`)

`spec` is the YAML with every shortcut expanded and every default explicit; it is what the interface renders. Read it to check how the platform understood a layout.

- `layout`: a container is `{"kind": "row" | "column", "size", "children": [...]}`, a widget `{"kind": "widget", "id", "size"}`, a size `{"unit": "weight", "value": 2}`, `{"unit": "px", "value": 360}` or `{"unit": "auto"}`. Every node has a size but the root.
- `sources`: `{"kind": "dataset", "dataset": "<project>/<dataset>"}` or `{"kind": "query", "sources": [...], "state": [...]}` — the sources and variables the query cites. **The SQL is not part of it**; it is only in the YAML source.
- `state`: every variable has a `default`, possibly `null`.
- `widgets`: every widget has `props`, possibly empty, copied as written, expressions included.
- `theme`: copied as written, and only when the document sets one.

## Read a source

What a widget does, and the way to check that an application returns data. The source is the one the **saved** definition declares: the body only carries structured options.

```bash
curl -X POST "$BASE/applications/$APP_ID/sources/expositions/read" \
  -H "Authorization: Bearer $GWENLAKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"filter": {"region": "Bretagne", "secteur": ["agri", "peche"]}, "aggregate": "sum(montant)", "group_by": "secteur"}'
```

| Option | Meaning |
| --- | --- |
| `state` | the values of the state variables a `query` source cites, `{"region": "Bretagne"}`; a variable left out takes its default |
| `filter` | field → value: a single value is an equality, a list a membership, `null` no condition |
| `aggregate` | `sum`, `avg`, `min`, `max` or `count` of a field, as `sum(montant)`; `count(*)` counts rows |
| `group_by` | with `aggregate`: one row per value of this field, `{<field>, value}` |
| `distinct` | the distinct non-null values of a field, sorted |
| `sort` | `[{"field": "...", "direction": "asc" \| "desc"}]`; a grouped read sorts on the group field or `value` |
| `columns` | for a page of rows: the fields to return, 1 to 8 of them, instead of all |
| `limit`, `offset` | a page of rows; 100 by default, 1000 at most — 100 000 at most for a read that names its `columns` |

Four modes: `distinct` → the distinct values; `aggregate` alone → one row `{"value": …}`; `aggregate` + `group_by` → one row per group; neither → a page of rows with their `total`. `distinct` cannot be combined with `aggregate` or `group_by`; `group_by` needs an `aggregate`; `columns` applies to a page of rows only.

```json
{
  "object": "list",
  "data": [ { "secteur": "agri", "value": 1250000.0 } ],
  "columns": [ { "name": "secteur", "type": "VARCHAR" }, { "name": "value", "type": "DOUBLE" } ],
  "total": null,
  "limit": 1000,
  "offset": 0,
  "truncated": false
}
```

The read runs with the caller's rights: the caller needs `datasets:read` and `sql:read` on every dataset behind the source, and gets a `403` otherwise. Datasets are read at their head on `main`.

`GET /applications/{id}/sources/{source}/columns` answers the columns of a source, `{"object": "list", "data": [{"name", "type"}]}` — the way to check the names a widget may use once the app is saved.

## Status codes

| Status | Meaning |
| --- | --- |
| `200` / `201` | done. `POST /applications/validate` answers `200` even for an invalid document: read `valid` |
| `400` | the application is rendered by a template; a read option is malformed; the body is not UTF-8 |
| `401` | the token is missing, revoked or for another endpoint |
| `402` | the organization's plan does not include the feature |
| `403` | the role or the key lacks the scope; a dataset behind a source cannot be read by the caller |
| `404` | no such application, or no such source in it |
| `409` | the slug is taken; a newer revision exists (`base_version`); the stored definition is no longer valid (save it again) |
| `413` | the document is larger than 256 KiB |
| `415` | a YAML route received another content type |
| `422` | the definition is invalid: `detail` and `errors` |
| `502` | the organization's storage refused the write; nothing was saved |

## A Python client

A minimal client for a backend, with `httpx` (the same requests work with any HTTP library):

```python
import os
import httpx

BASE = os.environ.get("GWENLAKE_BASE_URL", "https://atlas.gwenlake.com/api/v1")
YAML = {"Content-Type": "application/yaml"}


class InvalidApp(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(f"{e['path'] or '(document)'}: {e['message']}" for e in errors))


class AtlasApps:
    def __init__(self, api_key: str | None = None, base_url: str = BASE):
        self.http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key or os.environ['GWENLAKE_API_KEY']}"},
            timeout=120,
        )

    def validate(self, text: str, project_id: str | None = None) -> dict:
        """{valid, spec, errors, warnings}; nothing is saved."""
        params = {"project_id": project_id} if project_id else {}
        r = self.http.post("/applications/validate", params=params, content=text.encode(), headers=YAML)
        r.raise_for_status()
        return r.json()

    def create(self, text: str, project_id: str) -> dict:
        r = self.http.post("/applications", params={"project_id": project_id}, content=text.encode(), headers=YAML)
        return self._saved(r)

    def save(self, application_id: str, text: str, base_version: str | None = None) -> dict:
        params = {"base_version": base_version} if base_version else {}
        r = self.http.put(f"/applications/{application_id}", params=params, content=text.encode(), headers=YAML)
        return self._saved(r)

    def source(self, application_id: str) -> tuple[str, str]:
        """(the YAML source, its revision)."""
        r = self.http.get(f"/applications/{application_id}", headers={"Accept": "application/yaml"})
        r.raise_for_status()
        return r.text, r.headers.get("x-gwenlake-version", "")

    def read(self, application_id: str, source: str, **options) -> dict:
        r = self.http.post(f"/applications/{application_id}/sources/{source}/read", json=options)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _saved(r: httpx.Response) -> dict:
        if r.status_code == 422:
            raise InvalidApp(r.json().get("errors", []))
        r.raise_for_status()
        return r.json()
```

```python
apps = AtlasApps()
text = open("app.yaml", encoding="utf-8").read()

check = apps.validate(text, project_id="res.project.…")
if not check["valid"]:
    raise InvalidApp(check["errors"])

app = apps.create(text, project_id="res.project.…")
print(app["id"], apps.read(app["id"], "expositions", aggregate="count(*)")["data"])
```

When a backend generates the YAML (from a model, from a form), always validate before creating, hand the `errors` back to whatever produced the text, and loop until `valid` — each error says what to correct. Build the YAML as text or with a YAML library that quotes strings holding `${...}` and `#`.

## Finding ids and data

| Need | Request |
| --- | --- |
| the projects, with `id` and `slug` | `GET /filesystem/projects` |
| the datasets of a project, with `slug` | `GET /datasets?project_id=` |
| the columns of a dataset | `POST /sql/statements` with `{"statement": "SELECT * FROM '<project>.<dataset>' LIMIT 5", "format": "json"}` — in SQL a dataset is `'<project>.<dataset>'`, quoted, with a dot; in an app source it is `<project>/<dataset>`, with a slash |
| the agents of a project, with `slug` | `GET /agents?project_id=` |
| the models, for a `chat` widget | `GET /models` |

With the command line: `gwenlake projects list`, `gwenlake datasets list --project <slug>`, `gwenlake sql "SELECT * FROM '<project>.<dataset>' LIMIT 5"`.
