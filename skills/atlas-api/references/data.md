# Data: projects, datasets, files, SQL, mediasets, connections, syncs

Paths are relative to the base URL (`https://atlas.gwenlake.com/api/v1`). Every request carries `Authorization: Bearer <token>`. `$A` below stands for `python scripts/atlas_api.py`.

## Contents

- [Projects](#projects)
- [Datasets](#datasets)
- [Files and uploads](#files-and-uploads)
- [SQL statements](#sql-statements)
- [Stored queries and SQL transforms](#stored-queries-and-sql-transforms)
- [Data branches](#data-branches)
- [Vector datasets and search](#vector-datasets-and-search)
- [Mediasets](#mediasets)
- [Connections](#connections)
- [Syncs](#syncs)

## Projects

A project groups the resources of a use case. Its slug prefixes the handle of everything it holds, so choose a short, stable one.

| Request | Does |
| --- | --- |
| `GET /filesystem/projects` (`?organization_id=`) | the projects you can reach: `id`, `slug`, `name`, `organization_id` |
| `POST /filesystem/projects` — `{slug, name, organization_id}` | creates one |
| `GET` / `PATCH` / `DELETE /filesystem/projects/{id}` | reads, updates, deletes one |
| `GET /filesystem/projects/{id}/datasets` | its datasets |
| `GET /filesystem/projects/{id}/connections` | its connections |
| `GET /filesystem/search?q=&project_id=&type=` | resources by name |

Library: `client.projects.list()`, `.get(id)`, `.create({...})`, `.update(id, {...})`, `.delete(id)`, `.datasets(id)`. CLI: `gwenlake projects list`, `gwenlake search orders --project <slug> --type dataset`.

## Datasets

| `type` | Holds | Read with |
| --- | --- | --- |
| `iceberg` | a table (Apache Iceberg), with a history of snapshots and data branches | SQL |
| `files` | arbitrary files: Parquet parts, CSV, Excel exports, model outputs | the files routes; SQL only over the Parquet it holds |
| `vector` | embeddings, one row per chunk with its text and metadata | `POST /datasets/{id}/search` |

`iceberg` is the default where the organization supports it, `files` otherwise. The kind cannot change to or from `vector` after creation. Documents, images, audio and video belong in a [mediaset](#mediasets).

| Request | Does |
| --- | --- |
| `GET /datasets` (`?project_id=`, `?organization_id=`) | lists datasets |
| `POST /datasets` | creates one, empty |
| `GET /datasets/{id}` | one dataset: `id`, `name`, `slug`, `description`, `type`, `project_id`, `organization_id`, `created_at`, `updated_at`, and for a table its declared `columns` and `keys` |
| `PATCH /datasets/{id}` | changes name, slug, description, columns, keys |
| `GET /datasets/{id}/summary` | `num_rows`, `size_bytes`, `last_modified` (a table); `num_files` too (files); `dimensions` and `model` (vector). `null` when nothing was written yet |
| `GET /datasets/{id}/branches` | its data branches, `{"object": "list", "data": ["main", …]}` |
| `POST /datasets/{id}/empty` (`?branch=`) | removes every row or file, keeps the dataset (and a table's history) |
| `DELETE /datasets/{id}` | deletes the dataset **and the transform or sync that produced it** |

Create:

```json
{
  "slug": "orders",
  "name": "Orders",
  "project_id": "res.project.…",
  "type": "iceberg",
  "columns": [
    {"name": "order_id", "type": "long", "required": true},
    {"name": "placed_at", "type": "timestamp"},
    {"name": "amount", "type": "double"}
  ],
  "keys": ["order_id"]
}
```

Only `name` (or `slug`) and `project_id` are needed. Without `columns` the schema is inferred from the first upload. `keys` are the columns an `UPDATE` upserts on; they must never be null.

Renaming: a `PATCH` with `name` and no `slug` **regenerates the slug from the name**; a `PATCH` with `slug` alone changes it alone. The slug is in every SQL statement and binding that reads the dataset — change it knowingly, and give both when you rename.

Library: `client.datasets.list(project_id=…)`, `.get(id)`, `.create({...})`, `.update(id, {...})`, `.summary(id)`, `.empty(id, branch=…)`, `.delete(id)`, `.delete_rows(id, "source_file = 'x.csv'")`, `.maintenance(id, older_than_days=7)`. CLI: `gwenlake datasets list --project <slug>`, `summary`, `create`, `update`, `empty`, `delete`, `delete-rows`, `branches`, `export`.

## Files and uploads

Every route takes the dataset id and `?branch=`.

| Request | Does |
| --- | --- |
| `GET /datasets/{id}/files` (`?path=`) | the files of a directory: `filename`, `path`, `file_size`, `last_modified` |
| `POST /datasets/{id}/files` | uploads one file (multipart, field `file`) at the root |
| `POST /datasets/{id}/files/{path}` | the same, under a subdirectory |
| `GET /datasets/{id}/files/{filepath}` | downloads a file (bytes) |
| `GET /datasets/{id}/files/{filepath}/presigned-url?expires_in=` | `{"url": …}`: a link a third party downloads from without a key, one hour by default. Not available on an SMB-backed organization |
| `DELETE /datasets/{id}/files/{filepath}` | removes a file |

```bash
curl -X POST "$BASE/datasets/res.dataset.…/files?mode=SNAPSHOT" \
  -H "Authorization: Bearer $GWENLAKE_API_KEY" -F "file=@rows.parquet"

$A upload <project>.<dataset> rows.parquet --mode SNAPSHOT
$A upload <project>.<dataset> export.xlsx --path exports/2026
$A call GET /datasets/res.dataset.…/files/exports/2026/export.xlsx -o export.xlsx
```

The answer to an upload is `{"filename", "path", "file_size", "uploaded": true}`.

**On a file dataset** the file lands as it is.

**On a tabular dataset** the upload is parsed and written into the table. Accepted: Parquet, ORC, Arrow IPC (`.feather`, `.arrow`), Avro, CSV, TSV, JSON (an array, or one object per line), `.jsonl`/`.ndjson`, Excel (first sheet), and the text formats gzipped. Columns are matched to the table's by name and cast; a column the table does not have yet is added. `?mode=` says how the rows land:

| `mode` | Effect |
| --- | --- |
| `APPEND` (default) | adds the rows |
| `SNAPSHOT` | replaces every row with the upload |
| `UPDATE` | upserts on the dataset's key columns; `?keys=a,b` names others |
| `DELETE` | no file: removes the rows matching `?delete_filter=`, a row filter such as `country == 'FR'` |

```bash
$A call POST /datasets/res.dataset.…/files -q mode=DELETE -q "delete_filter=country == 'FR'"
```

Every write is a snapshot of the table. On a tabular dataset the files listing shows the table's physical files, an implementation detail: read the rows with SQL, and remove rows with `mode=DELETE` or `empty`, never file by file.

Library: `client.files.list(id, path=…)`, `.upload(id, "rows.parquet", mode="SNAPSHOT", path=…, branch=…)` (a path or raw bytes with `filename=`), `.download(id, "a/b.xlsx")`, `.presigned_url(id, "rows.parquet", expires_in=600)["url"]`, `.delete(id, "rows.parquet")`. CLI: `gwenlake files list|upload|download|delete` (`--mode APPEND|SNAPSHOT|UPSERT`, `--path`, `--branch`).

## SQL statements

`POST /sql/statements` runs one read-only `SELECT` on **DuckDB**.

```json
{"statement": "SELECT carrier, count(*) AS n FROM 'flights.flight-data' GROUP BY 1", "format": "json", "limit": 50000}
```

| Field | Meaning |
| --- | --- |
| `statement` | a single `SELECT`. Datasets are named by their handle in single quotes; joins across datasets of the same organization are allowed |
| `format` | `json` → `{"object": "list", "data": [...], "truncated", "limit"}`; `csv` → CSV bytes; `pyarrow` → an Arrow IPC file. **Over HTTP the default is `pyarrow`**; the library defaults to `json` |
| `limit` | the cap applied when the statement has no `LIMIT` of its own: 1000 by default |

A cut is reported in the JSON body (`truncated`, `limit`) and, for every format, in the `X-Gwenlake-Truncated` and `X-Gwenlake-Row-Limit` headers. To read more than the cap, page with `LIMIT`/`OFFSET` in the statement (with an `ORDER BY`, so pages do not overlap).

Handle suffixes:

| Handle | Reads |
| --- | --- |
| `'p.ds'` | the dataset, on the trunk |
| `'p.ds:experiment'` | the dataset on a data branch; an unknown branch is a `400` |
| `'p.ds@123'` | a table as it was at snapshot `123` |
| `'p.ds@123..456'` | the rows appended between two snapshots |

The snapshot forms exist for incremental transforms; an ordinary statement does not need them.

What goes wrong:

- `400` with the engine's message: a syntax error, an unknown column, a statement that is not a `SELECT`, a file dataset with no Parquet (`No Parquet files match this dataset`).
- `403 Cannot query this dataset`: a file dataset of CSVs, a vector dataset. A wrong handle also answers `403` or `400`: check the slugs.
- A slow answer: a scan reads every file before the first byte comes back. Raise the timeout, filter, or aggregate.

Statements read datasets only. Querying a connection's own engine (a PostgreSQL database) is done from the Atlas interface.

Library:

```python
rows = client.statements.create(statement="SELECT … LIMIT 100", format="json")["data"]
client.statements.create(statement="SELECT …", limit=50_000, timeout=300)

df = client.statements.to_dataframe("SELECT * FROM 'p.ds'")           # pages past the cap
table = client.statements.read_all("SELECT * FROM 'p.ds' WHERE …")    # pyarrow.Table
client.statements.to_file("SELECT * FROM 'p.ds'", "out.parquet")      # .parquet, .csv, .json, .jsonl; streams
for page in client.statements.iter_arrow("SELECT * FROM 'p.ds'", page_rows=100_000): ...
```

CLI: `gwenlake sql "SELECT …"`, `--file report.sql`, `--json`, `--limit`, `--out customers.parquet`, `-o - --format parquet` (stdout); `gwenlake datasets export <project>.<dataset> --out orders.csv --where "region = 'west'"`.

## Stored queries and SQL transforms

A **query** is a SQL text kept on the platform and versioned. Wired to a **SQL transform**, it produces a dataset, with its inputs derived from the `FROM`/`JOIN` references of the text.

| Request | Does |
| --- | --- |
| `POST /sql/queries` — `{name, project_id, sql}` | stores a query |
| `GET /sql/queries` (`?project_id=`), `GET /sql/queries/{id}` | lists (without the text), reads one with its text |
| `PATCH /sql/queries/{id}` | a new version of the text, or a rename; the inputs of the transforms wired to it are re-derived |
| `GET /sql/queries/{id}/versions`, `…/versions/{version}` | the history, one past text |
| `POST /sql/queries/{id}/execute` | runs the transform wired to the query, as a build of its output |
| `DELETE /sql/queries/{id}` | refused (`409`) while a transform references it |

`?branch=` on the reads and the `PATCH` addresses a data branch's copy of the text.

Wire it to an output dataset:

```json
POST /transforms
{"name": "orders_by_day", "project_id": "res.project.…", "type": "sql",
 "output": "res.dataset.…", "config": {"query_id": "res.sql-query.…"}}
```

Rules enforced at save time (`400` naming the reference): every `FROM`/`JOIN` reference is a dataset **of the same project**; no `:branch` and no `@snapshot` suffix; the output is a tabular dataset produced by this transform alone (`409` for a second producer).

The same from a repository the platform scans — a `.sql` file with a header:

```sql
-- @output: sales.orders_by_day
-- @input orders: sales.orders

SELECT CAST(placed_at AS DATE) AS day, count(*) AS n, sum(amount) AS total
FROM 'sales.orders'
GROUP BY 1
```

Library: `client.queries`. CLI: `gwenlake queries list|get|execute`.

## Data branches

A data branch is a named view of a **tabular** dataset where writes land without touching the trunk, `main`. It is created by its first write, forked in constant time, and promoted by moving the trunk to its snapshot. Names: a letter or digit, then letters, digits, `.`, `_`, `-`, up to 100 characters.

- Write on a branch: `?branch=experiment` on the files routes and on `empty`.
- Read it: `SELECT … FROM 'p.ds:experiment'`.
- List: `GET /datasets/{id}/branches`.
- Promote one dataset's branch: `POST /datasets/{id}/branches/{name}/promote`.
- Fork, build and merge a branch across a whole lineage: `references/pipelines.md`.

A file dataset has one version: a write naming another branch is a `400`, a read ignores the branch. Vector datasets and mediasets have no branches.

## Vector datasets and search

A vector dataset holds one row per chunk: its `text`, its `vector`, and any other column as metadata (`path`, `page`…). The embedding `model` is set on the dataset. The platform's document pipeline produces one from a mediaset; an upload of a tabular file carrying a `vector` column also fills it, with the same modes as a table.

```bash
$A call POST /datasets/res.dataset.…/search -d '{"query": "What is the refund policy?", "limit": 5, "where": "path LIKE '\''contracts/%'\''"}'
```

| Field | Meaning |
| --- | --- |
| `query` | a text, embedded with the dataset's model as the caller — or `vector`, a ready-made one |
| `limit` | 5 by default, 100 at most |
| `where` | a SQL filter on the metadata columns |

Each hit carries `id`, `text`, `score` (the cosine distance: **lower is closer**) and `metadata`. A dataset holding no vectors yet answers `400`. A vector dataset has no SQL surface and no branches.

## Mediasets

A mediaset holds media files of **one** kind, declared at creation and never changed. It is where a document pipeline starts.

| `media_type` | Formats |
| --- | --- |
| `document` | PDF, DOCX, PPTX, TXT, HTML, EML |
| `image` | PNG, JPEG, TIFF, GIF, WebP, BMP |
| `audio` | MP3, WAV, FLAC, OGG, M4A |
| `video` | MP4, MOV, AVI, MKV, WebM |

| Request | Does |
| --- | --- |
| `GET /mediasets/media-types` | the registry, with extensions and content types |
| `POST /mediasets` — `{name, slug, project_id, media_type}` | creates one |
| `GET /mediasets` (`?project_id=`), `GET` / `PATCH` / `DELETE /mediasets/{id}` | lists, reads, renames, deletes (with the sync that fed it) |
| `GET /mediasets/{id}/files?path=` | the files of a directory |
| `POST /mediasets/{id}/files`, `…/files/{path}` | uploads one file (multipart `file`); a file that is not of the media type is refused with `415` |
| `GET /mediasets/{id}/files/{filepath}` | downloads a file |
| `GET /mediasets/{id}/files/{filepath}/presigned-url?expires_in=` | a time-limited link |
| `DELETE /mediasets/{id}/files/{filepath}` | removes a file |
| `POST /mediasets/{id}/empty`, `GET /mediasets/{id}/summary` | removes every file; file count, size, last modification |

The usual way to fill a mediaset is a file [sync](#syncs) from a connection. The platform ships ready-made transforms that take a document mediaset to vectors — OCR (one row per page), chunking, embedding, or a vectorizer doing both — each configured with `parameters` rather than code.

## Connections

A connection is an external source a project declares once: an S3 bucket, an SMB share, a SharePoint library, a database. The platform keeps its credentials; they never reach your code. Creating or changing one is an admin's right; reading what it holds is a viewer's.

| Request | Does |
| --- | --- |
| `GET /connections` (`?project_id=`) | lists: identity and `type`, no configuration |
| `GET /connections/{id}` | one connection with its configuration, credentials always absent |
| `GET /connections/{id}/files` | the files it holds, recursive and paged |
| `GET /connections/{id}/files/content?path=` | one file's bytes; a `Range` header reads a part where the source can seek (`206`) |

Check the exact parameters of the two files routes in the API reference (links in `SKILL.md`); from Python the library wraps them:

```python
page = client.connections.list_files(cid, path="2026", glob="**/*.pdf", limit=500)
page["data"], page["next_start_after"]
for f in client.connections.iter_files(cid, glob="**/*.pdf"):     # follows the pages
    print(f["path"], f["size"])
data = client.connections.download(cid, "2026/q3/report.pdf")
head = client.connections.download(cid, "2026/q3/big.bin", offset=0, length=1024)
```

Each entry carries `path` (relative to the connection's root), `filename`, `size`, `last_modified`, `is_dir`. In a glob, `*` stays within a directory and `**` descends. A connection is read-only: data comes from it, and is written into a dataset.

## Syncs

A sync is a configured pull from a connection into a dataset or a mediaset — not code. It runs by hand, as part of a build of its output, or on a schedule.

| `type` | Reads | Writes into |
| --- | --- | --- |
| `table` | a table or a query on a connection with a query engine (PostgreSQL, SQL Server, Salesforce…) | a tabular or file dataset |
| `file` | the files matching a glob on a file source (S3, SMB, SharePoint, Google Drive, a git repository) | a dataset or a mediaset |

```json
POST /syncs
{"name": "Orders from the ERP", "project_id": "res.project.…", "type": "table",
 "output": "res.dataset.…",
 "config": {"connection_id": "res.connection.…", "query": "SELECT * FROM orders", "mode": "SNAPSHOT"}}
```

`config` holds `connection_id`, `mode` (`SNAPSHOT`, the default, replaces the output's content; `APPEND` adds to it) and the source keys: `table` or `query` for a table sync, `path_glob` for a file sync (`exports/2026/*.parquet`). The sync, its connection and its output must be in the same project.

`POST /syncs/{id}/execute` runs it now and answers `202` with the build it started; `GET /syncs?project_id=` lists them, each with its `last_execution` (status, timing, rows or files written). A `SNAPSHOT` run stages the new content and swaps it in at the end, so a source failing mid-way leaves the previous content whole.
