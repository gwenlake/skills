---
name: atlas-applications
description: "Build, edit, validate and publish Gwenlake Atlas applications with the Gwenlake MCP server: the declarative business screens (filters, KPIs, charts, tables, maps, agent chats) described by one app.yaml file (apiVersion atlas/v1, kind App) over the datasets of an Atlas project. Use whenever the user asks for an application, app, dashboard, screen, cockpit or report page in Gwenlake Atlas, mentions app.yaml or Atlas widgets, wants to add a filter, chart, KPI, table, map or chat to an existing Atlas app, or has an app definition that is refused or shows an error card."
---

# Gwenlake Atlas applications

An Atlas **application** is a screen for the people who use the data: a few filters, some indicators, charts, a table, a map, a chat with an agent. It lives in a project, next to the datasets it reads.

An application is **declarative**. You do not write React, HTML or a backend: you write **one YAML file, `app.yaml`**, that says which data the app reads, which widgets it shows and where each one goes. The platform validates the file, stores every save as a revision, and renders it. So "create an application" always means: *write a valid `app.yaml` and send it to the platform*.

Two things make this harder than it looks, and are the reason this skill exists:

- The format is strict. Any unknown key is refused, identifiers have a fixed shape, and a refused file stores nothing.
- The platform's validation **does not know the widget types**. It accepts `type: tabel` or a misspelled prop without a word; the interface then shows an error card in place of that widget. A file can be "valid" and still be broken on screen. Check every widget against the catalog below yourself: nothing else will.

## Workflow

Everything goes through the tools of the `gwenlake` MCP server, as the signed-in user. No script and no API key are involved.

1. **Find the data.** Get the project, its datasets and their real column names. Never invent a column: a wrong name passes validation and fails on screen.
2. **Design the screen** from what the user wants to *decide or see*, not from the list of widgets: which filters, which 2–4 headline numbers, which charts, whether a table or a chat helps.
3. **Write `app.yaml`**: sources → state → widgets → layout.
4. **Validate** with `validate_application` (nothing is saved), fix every error and warning, and check each widget against the catalog.
5. **Show the user what you are about to publish and get their agreement**, then create the application with `create_application`, or save a new revision of an existing one with `update_application`.
6. **Check that the data comes back**, then tell the user the application id and anything you assumed.

| Step | Tool |
| --- | --- |
| find the project | `search_catalog`, `list_projects` |
| its datasets | `list_datasets(project_id)` |
| real column names, and the names to write in a source | `describe_dataset(dataset_id)` |
| look at values, test a query | `query_dataset(statement)`, DuckDB, read-only |
| find an existing application | `search_catalog(query, resource_type="application")`, `list_project_contents(project_id, resource_type="application")` |
| read its `app.yaml` | `get_application(application_id)`: `definition` is the YAML, `version` its revision |
| check a draft | `validate_application(definition, project_id=…)` |
| publish | `create_application(project_id, definition)`, `update_application(application_id, definition, base_version)` |

`definition` is always the YAML text itself, whole, never a path and never a fragment.

**The name of a dataset in a source** is `<project slug>/<dataset slug>`, with a slash. `describe_dataset` gives `sql_name` as `<project>.<dataset>`, with a dot: the same two names, so replace the dot with a slash in `sources`, and keep the dot when you test a query with `query_dataset`.

If a tool answers that it is disabled on this MCP server, writing is off for this deployment or this plan. Still do steps 1 to 4, say what you could not do, and hand over the YAML: the user pastes it in the Atlas interface (**New app** → **Edit** → **YAML** tab → **Save**), which validates it the same way.

## The file

```yaml
apiVersion: atlas/v1
kind: App
metadata:
  name: suivi-portefeuille            # the app's slug
  title: Suivi du portefeuille crédit # the name displayed

sources:
  expositions:
    dataset: risque-credit/expositions        # <project slug>/<dataset slug>
  scores:
    dataset: risque-credit/scores
  scores_secteur:
    query: |
      select secteur, avg(score) as score_moyen
      from ${sources.scores}
      where ${state.region} is null or region = ${state.region}
      group by secteur
      order by score_moyen desc

state:
  region: { type: string }             # no default: null, "nothing chosen"

layout:
  row:
    - column:
        width: 4
        rows:
          - row: [filtre, encours]
          - row: [scores: 2, repartition: 1]
          - table: 1
    - chat: 1

widgets:
  filtre:
    type: filter.select
    props:
      label: Région
      placeholder: Toutes les régions
      bind: state.region
      options: { source: expositions, field: region }
  encours:
    type: kpi
    props:
      source: expositions
      value: sum(montant)
      format: eur
      label: Encours total
      filter: { region: "${state.region}" }
  scores:
    type: chart.bar
    props: { source: scores_secteur, x: secteur, y: score_moyen, title: Score moyen par secteur }
  repartition:
    type: chart.pie
    props:
      source: expositions
      category: secteur
      value: sum(montant)
      filter: { region: "${state.region}" }
  table:
    type: table
    props:
      source: expositions
      filter: { region: "${state.region}" }
  chat:
    type: agent.chat
    props: { agent: analyste-risque }
```

| Key | Required | Content |
| --- | --- | --- |
| `apiVersion` | yes | always `atlas/v1` |
| `kind` | yes | always `App` |
| `metadata` | yes | `name` (required): the slug — lowercase letters, digits, hyphens, underscores. `title`: the displayed name. Nothing else. |
| `theme` | no | `background` (the page) and `card` (default background of cards) |
| `sources` | no | the data the app reads, by identifier |
| `state` | no | the variables widgets share, by identifier |
| `layout` | yes | where each widget goes (`layout: []` is an empty app) |
| `widgets` | no | each widget, by identifier |

**Rules that are refused when broken:**

- Any unknown key, anywhere except inside a widget's `props`: at the root, in `metadata`, in a state variable (`type`, `default` only), in a widget (`type`, `props` only), in a layout container.
- **Identifiers** of sources, state variables and widgets match `^[a-z][a-z0-9_]*$`: lowercase, digits, underscores, starting with a letter. **No hyphen** (`chiffre-affaires` is refused, `chiffre_affaires` is fine) — unlike `metadata.name` and dataset slugs, which may have hyphens.
- `row`, `column` and `tabs` are reserved: no widget may be called that.
- Duplicate keys are refused. The document is at most 256 KiB.

### Sources

A source has **exactly one key**.

- `dataset: <project>/<dataset>` — a dataset by the slugs of its project and its own (a slash, not the dot used in SQL handles), in the application's organization. It must be **tabular**: Parquet files or an Iceberg table. A vector dataset or a file dataset of CSVs cannot be a source.
- `query: <SQL>` — a single `SELECT`, in **DuckDB** SQL. It reads its tables through `${sources.<id>}`, where `<id>` is a `dataset` source of the same app — **never another query, never a table name written directly**. It takes values through `${state.<id>}`.

A query runs confined to the sources it names, so every dataset it needs must be declared as a `dataset` source first (declaring one only for a query to read is normal and gives no warning).

`${state.<id>}` in a query is **never pasted into the SQL**: it is a bound parameter cast to the variable's type (`string` → VARCHAR, `number` → DOUBLE, `boolean` → BOOLEAN, `date` → DATE). Two consequences:

- Do not put quotes around it: `where region = ${state.region}`, not `'${state.region}'`.
- A variable with no value is `NULL`, and `region = NULL` matches nothing. A filter that can be empty must plan for it: `where ${state.region} is null or region = ${state.region}`. A default does not protect you: the person can pick the empty choice of a select or clear a text, number or date input, and the variable is `null` again (`montant >= coalesce(${state.seuil}, 0)`). Only a `boolean` written by a toggle is never emptied — give it a default.

### State

`state` declares the variables widgets share: a filter writes one, other widgets read it.

```yaml
state:
  region: { type: string, default: Bretagne }
  seuil: { type: number, default: 0.5 }
  actifs: { type: boolean, default: true }
  depuis: { type: date, default: 2026-01-01 }     # YYYY-MM-DD
  secteur: { type: string }                       # no default: null
```

`type` is required: `string`, `number`, `boolean` or `date`. `default` is optional and must be of that type (quote a string that reads as a number: `default: "2024"`). Without a default the variable is `null`: nothing chosen.

### References: how widgets reach sources and state

- **By name**, in two reserved props. `source` (at any depth of `props`) names a declared source. `bind: state.<id>` ties a widget to a variable it reads and writes.
- **By expression.** `${state.<id>}` is allowed in a `query` and in any text value of `props`. `${sources.<id>}` is allowed in a `query` **only**.

In `props`, a value that is exactly one expression takes the variable's value with its type (`null` stays `null`); inside a longer text the value is inserted, `null` as an empty text: `title: "Encours — ${state.region}"`.

In YAML, a value holding `${...}` inside braces must be quoted, or the document is not valid YAML:

```yaml
filter: { region: "${state.region}" }     # right
filter: { region: ${state.region} }       # refused: invalid YAML
```

### Two ways to filter

| | Widget `filter` prop | `query` source with `${state.x}` |
| --- | --- | --- |
| Written | `filter: { region: "${state.region}" }` | `where ${state.region} is null or region = ${state.region}` |
| Can express | equality; a list is a membership | anything SQL can: ranges, dates, `like`, joins |
| Empty variable | the condition is dropped automatically | you handle `NULL` yourself |
| Use for | KPIs, tables, pies, maps on a dataset | charts of aggregates, thresholds, date ranges |

A widget `filter` applies to the columns of the widget's source — for a `query` source, the columns the query *returns*. To filter a chart of aggregates by a column that the aggregation removes, put the condition in the query.

## Widgets

A widget has a `type` and `props`. These eighteen types are all there is; `*` marks a required prop. An unknown type, an unknown prop or a missing required prop puts an error card in place of the widget.

| Type | Props | What it shows |
| --- | --- | --- |
| `filter.select` | `bind`\*, `options: { source, field }`\*, `label`, `placeholder` | a choice among the distinct values of a field (up to 1000). The empty choice, named by `placeholder` ("All" by default), sets the variable to `null` |
| `filter.text` | `bind`\*, `label`, `placeholder` | a typed value, for a `string` or `number` variable |
| `filter.number` | `bind`\*, `label`, `min`, `max`, `step`, `placeholder` | a number, for a `number` variable |
| `filter.date` | `bind`\*, `label` | a day, for a `date` (or `string`) variable |
| `filter.toggle` | `bind`\*, `label` | a switch, for a `boolean` variable |
| `kpi` | `source`\*, `value`\* (aggregate), `label`, `format`, `subtitle`, `color`, `background`, `filter` | one headline number. `format`: `number` (default), `eur`, `percent` |
| `ranking` | `source`\*, `name`\*, `value`\*, `title`, `order`, `limit`, `format`, `color`, `background`, `filter` | the best or the worst rows by a value: `name` is the field naming each row, `value` the field they are ranked by. `order`: `top` (default) or `bottom`; `limit`: 1–50, 5 by default |
| `table` | `source`\*, `title`, `columns`, `page_size`, `background`, `filter` | the rows of a source, by pages, sortable. `columns`: a list of fields (all when absent); `page_size`: 1–1000, 50 by default |
| `chart.bar` | `source`\*, `x`\*, `y`\*, `title`, `color`, `baseline`, `background`, `filter` | one bar per row |
| `chart.line` | `source`\*, `x`\*, `y`\*, `title`, `color`, `fill`, `baseline`, `background`, `filter` | a trend along `x`; `fill: true` fills under the curve |
| `chart.area` | `source`\*, `x`\*, `y`\*, `title`, `color`, `baseline`, `background`, `filter` | a trend, always filled |
| `chart.pie` | `source`\*, `category`\*, `value`\* (aggregate), `title`, `color`, `background`, `filter` | the share of each value of `category` |
| `map` | `source`\*, `lat`\*, `lon`\*, `title`, `label`, `color`, `size`, `view`, `background`, `filter` | one point per row. `label`: the field shown on hover; `size`: 1–40 px; `view`: `map` or `globe` |
| `section` | `title`, `description`, `divider`, `color` | the heading of a part of the app: a large title, a description under it (Markdown). `divider: true` draws a line above; `color` a colored mark beside the title |
| `divider` | `label`, `style` | a line between two parts: horizontal in a `column`, vertical in a `row` (place it as `{ sep: auto }` there). `style`: `line` (default), `strong`, `dashed` |
| `text` | `content`\* | Markdown; `${state.<id>}` is replaced |
| `agent.chat` | `agent`\* | a chat with an agent **of the app's project**, by slug or id (`res.agent.…`) |
| `chat` | `model`, `system` | a chat with a model, no agent: a model id and a system prompt |

**What you need to know to use them well:**

- An **aggregate** is `sum`, `avg`, `min`, `max` or `count` of **one plain column name**: `sum(montant)`, `count(*)`. Not an expression — `sum(prix * quantite)` or `count(distinct client)` must be computed in a `query` source, then read with a plain aggregate (`max(valeur)` on a one-row query, for instance).
- **`chart.bar`, `chart.line` and `chart.area` draw the rows of their source as they are**, one mark per row, the first 500, in the source's order. They do not aggregate. Pointed at a raw dataset they draw 500 arbitrary rows — almost always wrong. Give them a `query` source that groups, and `order by` in it (by date for a trend, by value for a ranking). Only `kpi` and `chart.pie` aggregate by themselves.
- `chart.pie` keeps the eight largest slices and folds the rest into "Other".
- `format: percent` multiplies by 100: the value must be a ratio (`0.42` shows 42 %). `eur` shows whole euros.
- A `kpi` without a `label` shows the widget's identifier. Give every KPI a `label` and every chart a `title`.
- **Colors**: a name of the palette — `blue`, `orange`, `aqua`, `yellow`, `magenta`, `green`, `violet`, `red` — which follows light and dark mode, or a hex color **in quotes** (`"#0ea5e9"`: an unquoted `#` starts a YAML comment). `background` also takes `{ light: ..., dark: ... }`. A bar chart without `color` gives each bar its own color when `x` holds labels, blue when it holds dates or numbers.
- `baseline` (a number) draws a dashed reference line on bar, line and area charts.
- A `map` reads up to 100 000 rows; past that, aggregate in a `query` (one row per place).
- `filter.select` options usually come from a `dataset` source. If they come from a `query`, that query should not depend on the variable the filter writes, or the list shrinks to the chosen value.
- Match the filter to the variable's type (a `filter.toggle` on a `string` variable is an error card).

More detail on each widget, with examples: `references/widgets.md`.

## Layout

The layout is a tree of containers — `row` (elements side by side) and `column` (elements stacked) — whose leaves are widget identifiers. It is the flexbox model. The root is a mapping with a single key, `row` or `column`, or directly a list, which is a `column`.

| Written | Means |
| --- | --- |
| `encours` | the widget, default size |
| `scores: 2` | the widget, size 2 |
| `chat: 360px` | the widget, fixed size |
| `row: [a, b]` / `column: [a, b]` | a container, default size |
| `row: { height: 1, columns: [a, b] }` | long form of a `row` with its size — children under `columns` |
| `column: { width: 4, rows: [a, b] }` | long form of a `column` with its size — children under `rows` |
| `[a, b]` | inside a `column` only: a `row` |

A **size** applies along the parent container: it is a `width` inside a `row`, a `height` inside a `column` (the other one is an error). The root has no size. Values: a number above 0 is a **weight** (a share of the remaining space), `<n>px` is fixed, `auto` is the natural size. Defaults: weight 1 in a `row` (a row shares its width equally), `auto` in a `column` (each element takes its natural height: about 280 px for a chart, 380 for a table, 420 for a map, 480 for a chat, its content for a filter, a KPI, a section, a divider or a text).

A container is never empty (except the root). **A widget is placed exactly once**; a widget declared but not placed is only a warning, and is not displayed.

The shape that works for most apps — a list is a column, each inner list a row:

```yaml
layout:
  - [filtre_region, filtre_periode]        # filters
  - [ca, marge, commandes, panier]         # KPIs share the width
  - [evolution: 2, repartition: 1]         # charts, 2/3 – 1/3
  - detail: 1                              # the table takes the remaining height and scrolls inside it
```

Give the table (or the one element that should absorb the height) a weight, as `detail: 1` above. For a side panel over the full height — typically a chat — make the root a `row`:

```yaml
layout:
  row:
    - column: { width: 3, rows: [[f1, f2], [k1, k2, k3], [c1, c2], tableau: 1] }
    - chat: 1
```

Keep rows to four or five widgets: beyond that they are too narrow to read.

## Theme

Optional. An app has the look of the platform; `theme` changes two backgrounds:

```yaml
theme:
  background: { light: "#f1f5f9", dark: "#0b1220" }   # the page
  card: blue                                          # every card that sets no `background` of its own
```

Leave it out unless the user asks for a look.

## Validating, saving, and fixing errors

`validate_application` runs the same checks as a save and stores nothing: it answers `valid`, `errors` and `warnings`. A save **stores nothing when the YAML has an error**. Every error comes back at once, each with the path of the faulty element, a message saying what to correct, and the line and column. Read them all, fix them all, validate again:

```json
{ "path": "widgets.filtre.props.bind", "message": "`bind` must be `state.<id>` with a declared state variable (got `state.secteur`).", "line": 37, "column": 7 }
```

Beyond the format, a save checks that each `query` is a single `SELECT` and that each dataset exists and can be read by the author. Three things are only **warnings**: a widget declared but not placed, a source nothing reads, a state variable nothing uses — fix them anyway, they are usually a forgotten line.

| Message | Usual cause |
| --- | --- |
| `Invalid YAML … must be quoted` | `${state.x}` unquoted inside `{ }`, or an unquoted `#hex` color |
| `Unknown key …` | a key that does not exist (`description` in `metadata`, `title` on a widget instead of in `props`, `label` on a state variable) |
| `Invalid … identifier` | a hyphen or a capital in a source, state or widget identifier |
| `No widget … is declared` | the layout names a widget that `widgets` does not define (a typo, or a filter you forgot to write) |
| `already placed in the layout` | the same widget twice in the layout |
| `Inside a row, the size of an element is its width` | `height` given to an element of a row (or `width` in a column) |
| `a query reads dataset sources only` | a query citing another query: read the datasets and compose in one statement (a CTE) |
| `${sources.x} is only allowed inside a query` | used in `props`: name the source with the `source` prop |
| `No dataset … or you cannot read it` | wrong slugs, a dot instead of a slash, or a dataset of another organization |
| `… an app source reads tabular datasets only` | the dataset is a vector dataset: pick a tabular one |
| a save refused because the application has no declarative definition | the application is rendered by a **template** (an older, hand-coded app): it cannot take a YAML. Create a new application instead |
| a conflict on save | the slug `metadata.name` is already taken in the project, or someone saved a newer revision |

**Checking the widgets.** Validation does not know the widget types. Before publishing, read each widget of your file against [Widgets](#widgets) and `references/widgets.md`: the `type` is one of the eighteen, every prop belongs to that type, every required prop is there, every field named is a column of its source.

**After a save, check that the data comes back.** For each `query` source, run its statement with `query_dataset`, with the datasets written `<project>.<dataset>` and each `${state.x}` replaced by its default, then by a real value. For a `dataset` source, `SELECT count(*)`. A chart that is empty on screen is usually a query whose `where` meets a `NULL` variable, or a column name that does not exist.

**Editing an existing app**: read it with `get_application`. `definition` is its YAML source; an application that returns none is rendered by a template, or was created empty, so there is nothing to edit: create a new one. Change the text, keeping the comments and the formatting since it is stored as sent, validate it with `validate_application(definition, application_id=…)`, then save it with `update_application`, passing the `version` you read as `base_version`: a save over a revision newer than that one is refused instead of erasing someone else's work. Every save is a revision; restoring one is saving its text again.

**Who can see it**: a source is read with the rights of the person *looking at* the app, who must be able to read the datasets behind it. Saving needs the Editor role (`applications:write`), reading the Viewer role.

## Before you hand over

- Every column named in a prop or a query exists in its source (you looked, you did not guess).
- Every widget is declared **and** placed once; every source and state variable is used.
- Bar, line and area charts read a `query` that aggregates and sorts.
- Every `${state.x}` in a query handles `NULL` (a boolean with a default aside).
- `validate_application` returns no error and no warning, and you checked every widget against the catalog.
- You told the user the application id and what you assumed about the data.

## Bundled files

- `references/widgets.md`: each widget in detail, with examples and sizing.
- `assets/examples/`: complete applications to start from: `sales-dashboard.yaml` (filters, KPIs, charts, table), `map-explorer.yaml` (map and filters), `agent-cockpit.yaml` (side chat with an agent).

The public documentation is at https://docs.gwenlake.com/atlas/guides/applications and https://docs.gwenlake.com/atlas/guides/app-widgets (index for agents: https://docs.gwenlake.com/atlas/llms.txt). If something here disagrees with what the platform answers, the platform is right: follow its error message.
