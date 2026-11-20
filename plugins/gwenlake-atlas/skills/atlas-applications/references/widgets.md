# Widgets in detail

Every widget type an Atlas application can hold, with what it reads, how it behaves and an example. `*` marks a required prop. The summary table is in `SKILL.md`; come here when a widget does not behave as expected or you need a prop's exact meaning.

## Contents

- [How a widget reads its data](#how-a-widget-reads-its-data)
- [Shared props](#shared-props)
- [Filters](#filters): `filter.select`, `filter.text`, `filter.number`, `filter.date`, `filter.toggle`
- [Indicator](#indicator-kpi): `kpi`
- [Table](#table)
- [Charts](#charts): `chart.bar`, `chart.line`, `chart.area`, `chart.pie`
- [Map](#map)
- [Sections and dividers](#sections-and-dividers): `section`, `divider`
- [Text](#text)
- [Chats](#chats): `agent.chat`, `chat`
- [Colors and backgrounds](#colors-and-backgrounds)
- [Sizes](#sizes)
- [What an error card means](#what-an-error-card-means)

## How a widget reads its data

A widget never sends SQL nor a dataset name. It names one source of the app and structured options (a filter, an aggregate, a page); the platform finds the dataset or the SQL in the **saved** YAML and reads it with the rights of the person looking at the app.

| Widget | What it asks its source for |
| --- | --- |
| `kpi` | one aggregate over the rows kept by `filter` → one number |
| `chart.pie` | one aggregate per value of `category` (up to 1000 groups) |
| `chart.bar` / `chart.line` / `chart.area` | the **rows as they are**, the first 500, no aggregation, no sort |
| `table` | a page of rows, sorted by the column the person clicks |
| `map` | up to 100 000 rows, only the fields it shows |
| `filter.select` | the distinct non-null values of a field, sorted, up to 1000 |

A widget is read again when a state variable it depends on changes: one its props cite, or one cited by the query its source is.

## Shared props

| Prop | Meaning |
| --- | --- |
| `source` | the identifier of a source declared under `sources` |
| `filter` | the rows kept, as field → value. A value is an equality, a list a membership (`{ statut: [ouvert, en_cours] }`). A value is usually a variable, `{ region: "${state.region}" }`; a variable that is `null` removes its condition. Several fields are combined with AND. No ranges, no `like`: use a `query` source for those |
| `bind` | `state.<id>`: the variable the widget reads and writes |
| `label`, `title` | a text displayed with the widget; may hold `${state.<id>}` |
| `color` | a color: a palette name or a hex color in quotes |
| `background` | the background of the widget's card. Accepted by `kpi`, `table`, the charts and `map` |

An **aggregate** is `sum`, `avg`, `min`, `max` or `count` applied to one field of the source, written `sum(montant)`; `count(*)` counts the rows. The field is a plain column name (letters, digits, underscores). Anything else — a product, a ratio, `count(distinct …)` — is computed in a `query` source and read back with a plain aggregate.

## Filters

A filter writes a state variable; the widgets that cite the variable follow. A filter holds no data of its own.

| Type | Props | Variable type |
| --- | --- | --- |
| `filter.select` | `bind`\*, `options: { source, field }`\*, `label`, `placeholder` | any; usually `string` |
| `filter.text` | `bind`\*, `label`, `placeholder` | `string` or `number` |
| `filter.number` | `bind`\*, `label`, `min`, `max`, `step`, `placeholder` | `number` |
| `filter.date` | `bind`\*, `label` | `date` (or `string`) |
| `filter.toggle` | `bind`\*, `label` | `boolean` |

```yaml
state:
  region: { type: string }
  recherche: { type: string }
  seuil: { type: number, default: 1000 }
  depuis: { type: date }
  actifs: { type: boolean, default: true }

widgets:
  f_region:
    type: filter.select
    props:
      label: Région
      placeholder: Toutes les régions       # the empty choice; sets the variable to null
      bind: state.region
      options: { source: expositions, field: region }
  f_recherche:
    type: filter.text
    props: { label: Client, placeholder: Nom du client, bind: state.recherche }
  f_seuil:
    type: filter.number
    props: { label: Montant minimum, bind: state.seuil, min: 0, step: 500 }
  f_depuis:
    type: filter.date
    props: { label: Depuis le, bind: state.depuis }
  f_actifs:
    type: filter.toggle
    props: { label: Actifs seulement, bind: state.actifs }
```

- `filter.select` always offers an empty choice, labelled by `placeholder` ("All" when absent). Choosing it sets the variable to `null`.
- The options of a select are the distinct values of `options.field` in `options.source`, at most 1000. Point it at a `dataset` source, or at a query that does not depend on the variable the select writes.
- A text input writes the variable after a short pause in typing; an emptied input writes `null`. For a contains-search, use the variable in a query: `where ${state.recherche} is null or client ilike '%' || ${state.recherche} || '%'`.
- A cleared number or date input writes `null` too, whatever the default.
- A toggle writes `true` or `false`. Give its variable a default so it is never `null`.

## Indicator: `kpi`

| Props | |
| --- | --- |
| `source`\*, `value`\* (an aggregate), `label`, `format`, `subtitle`, `color`, `background`, `filter` | one headline number |

- `format`: `number` (default, up to two decimals), `eur` (whole euros), `percent` (the value is a **ratio**: `0.42` shows 42 %).
- `label` is the caption; without it the widget's identifier is shown. `subtitle` is a line under the number and may hold `${state.<id>}`. `color` colors the number.
- An empty result shows `—`.

```yaml
widgets:
  encours:
    type: kpi
    props:
      source: expositions
      value: sum(montant)
      format: eur
      label: Encours total
      subtitle: "Région : ${state.region}"
      color: violet
      filter: { region: "${state.region}" }
```

A number a plain aggregate cannot give — a ratio, a distinct count, a difference between two periods — comes from a one-row query:

```yaml
sources:
  ratios:
    query: |
      select sum(marge) / nullif(sum(montant), 0) as taux_marge
      from ${sources.commandes}
widgets:
  marge:
    type: kpi
    props: { source: ratios, value: max(taux_marge), format: percent, label: Taux de marge }
```

## Table

| Props | |
| --- | --- |
| `source`\*, `title`, `columns`, `page_size`, `background`, `filter` | the rows of a source, by pages read from the platform |

- `columns` lists the fields shown, in that order; all of them when absent.
- `page_size` is the rows per page: 1 to 1000, 50 by default. The person can change it and sort by clicking a column.
- A filter that changes brings the table back to its first page.
- Give the table a weight in its column (`table: 1`) so it takes the remaining height and scrolls inside it; otherwise it is 380 px high.
- To rename, format or compute columns, point the table at a `query` source that selects them (`select date_commande as "Date", round(montant, 2) as montant …`).

## Charts

| Type | Props | |
| --- | --- | --- |
| `chart.bar` | `source`\*, `x`\*, `y`\*, `title`, `color`, `baseline`, `background`, `filter` | one bar per row: `x` the field of the categories, `y` the field of the values |
| `chart.line` | `source`\*, `x`\*, `y`\*, `title`, `color`, `fill`, `baseline`, `background`, `filter` | a trend along `x` |
| `chart.area` | `source`\*, `x`\*, `y`\*, `title`, `color`, `baseline`, `background`, `filter` | a trend where the magnitude matters: a line that is always filled |
| `chart.pie` | `source`\*, `category`\*, `value`\* (an aggregate), `title`, `color`, `background`, `filter` | the share of each value of `category`, in shades of one color |

**Bar, line and area draw the rows of their source as they are** — one mark per row, the first 500 (a note says so when there are more), in the order the source returns them. One series per chart: one `y`. So:

- to chart an aggregate, give the chart a `query` source that computes it;
- `order by` in that query: by `x` for a trend, by the value for a ranking, with a `limit` for a top N;
- for dates, return a date or a short text (`date_trunc('month', d)::date`, `strftime(d, '%Y-%m')`), one row per period;
- for several series, use several charts side by side.

```yaml
sources:
  scores_secteur:
    query: |
      select secteur, avg(score) as score_moyen
      from ${sources.scores}
      where ${state.region} is null or region = ${state.region}
      group by secteur
      order by score_moyen desc
widgets:
  scores:
    type: chart.bar
    props: { title: Score moyen par secteur, source: scores_secteur, x: secteur, y: score_moyen }
```

`chart.pie` aggregates by itself: it groups its source by `category` and applies `value`. It drops slices that are zero or negative, keeps the eight largest and folds the rest into "Other", and shows the percentages in a legend beside it.

```yaml
widgets:
  repartition:
    type: chart.pie
    props: { title: Encours par secteur, source: expositions, category: secteur, value: sum(montant) }
```

**Fill and baseline.** `fill: true` on a `chart.line` fills the area between the curve and the baseline with a lighter shade of the curve's color. `baseline` is a number, 0 when absent; when given, a dashed reference line is drawn at that value and the axis is extended to hold it. Accepted by `chart.bar`, `chart.line` and `chart.area`.

```yaml
widgets:
  marge:
    type: chart.line
    props: { source: marge_mensuelle, x: mois, y: marge, color: green, fill: true, baseline: 100 }
```

**Bar colors.** A bar chart without a `color` chooses by what `x` holds: labels (a sector, a country) give each bar its own color, in the order of the palette, which starts again after eight bars; dates or numbers give every bar blue. With a `color`, every bar has that color.

## Map

| Props | |
| --- | --- |
| `source`\*, `lat`\*, `lon`\*, `title`, `label`, `color`, `size`, `view`, `background`, `filter` | one point per row of the source, on satellite imagery |

- `lat` and `lon` are the fields holding the latitude and the longitude, in decimal degrees. A row without both, or outside −90…90 and −180…180, is left out and counted in a note on the map.
- `label` is the **field** shown when a point is hovered (not a text); without it, the coordinates.
- `color` is the color of the points (blue by default), `size` their radius in pixels (5 by default, 1 to 40). Points shrink as the map zooms out.
- `view` is `map` (flat, the default) or `globe`. A button on the map switches between the two, and a search box flies to a place.
- The map opens framed on its points, then stays where the person puts it: a filter that changes the points does not move it.
- A map reads at most 100 000 rows of its source and says so when the source holds more. Past that, give it a `query` source that aggregates — one row per port, per cell of a grid.

```yaml
widgets:
  ports:
    type: map
    props: { source: ports, lat: latitude, lon: longitude, label: nom, color: orange }
```

## Sections and dividers

Structure, no data: `section` opens a part of the app with a title, `divider` draws a line between two parts.

| Type | Props | |
| --- | --- | --- |
| `section` | `title`, `description`, `divider`, `color` | a large title and, under it, a subtitle or a few lines of description (Markdown, single line breaks kept). `divider: true` draws a line above the title, closing the part before it; `color` (a palette name or a hex color) adds a colored mark beside the title |
| `divider` | `label`, `style` | a line: horizontal between the elements of a `column`, vertical between those of a `row`. `label` is a short text in the middle of the line; `style` is `line` (default), `strong` or `dashed` |

`title`, `description` and `label` may hold `${state.<id>}`. Neither widget draws a card, so neither accepts `background`.

```yaml
layout:
  - ventes
  - row: [ca, { sep: auto }, volumes]

widgets:
  ventes:
    type: section
    props:
      title: Ventes
      description: Chiffre d'affaires et volumes de la région **${state.region}**.
      divider: true
      color: blue
  sep:
    type: divider
```

Use a `section` rather than a `text` holding `## Title` to head each part of a dashboard: the title is larger and the description is set apart. In a `row`, size a divider `auto` (`{ sep: auto }`), or it takes an equal share of the width.

## Text

| Props | |
| --- | --- |
| `content`\* | Markdown; `${state.<id>}` is replaced by the variable's value |

Use it for a short explanation, a legend, a note; for the heading of a part of the app, use a `section`. Write multi-line content with a YAML block (`content: |`).

## Chats

| Type | Props | |
| --- | --- | --- |
| `agent.chat` | `agent`\* | a conversation with an agent of the application's project, named by its slug or its id (`res.agent.…`). The agent works with the rights of the person talking to it |
| `chat` | `model`, `system` | a conversation with a model, without an agent: `model` is a model id (as `GET /models` lists them), `system` a system prompt |

The agent must exist in the **same project** as the application; an unknown slug shows "No agent … in this project" in the widget. List them with `GET /agents?project_id=`. An agent is useful in an app when it is bound to the same datasets (`resources:` in its `agent.md`), so it can answer questions about what the screen shows. A chat does not read the app's state: it does not know which filter is selected.

Chats are tall (480 px by default, 240 at least): place one in its own column over the full height, or give it a weight.

## Colors and backgrounds

A color is a name of the palette — `blue`, `orange`, `aqua`, `yellow`, `magenta`, `green`, `violet`, `red` — or a hex color (`"#0ea5e9"` or `"#0af"`), quoted because `#` starts a comment in YAML. A name follows the theme, with a shade for the light interface and one for the dark; a hex color is drawn as written in both. A chart is blue unless told otherwise.

`background` (on `kpi`, `table`, the charts and `map`) takes:

- a palette name: a soft tint of that hue, lighter in light mode and deeper in dark mode;
- a hex color, used as written in both modes; the text on the card turns light on a dark color and dark on a light one;
- `{ light: ..., dark: ... }`: one color per mode. A mode left out keeps the platform's background.

```yaml
widgets:
  encours:
    type: kpi
    props: { source: expositions, value: sum(montant), label: Encours total, background: blue }
  scores:
    type: chart.bar
    props:
      source: scores_secteur
      x: secteur
      y: score_moyen
      background: { light: "#fef3c7", dark: "#3b2f0b" }
```

To give every card the same background, or to color the page itself, set the application's `theme` (`background`, `card`) instead of repeating a prop.

## Sizes

Each type has a natural height, used when the layout gives it none (`auto`, the default in a column), and a minimum under which a weighted widget does not shrink.

| Widget | Natural height | Minimum |
| --- | --- | --- |
| filters | their content (about 60 px; a toggle 32) | 60 (toggle 32) |
| `kpi` | its content | 76 |
| `section` | its content | 32 |
| `divider` | its content | 16 |
| `text` | its content | 24 |
| charts | 280 px | 160 |
| `table` | 380 px | 180 |
| `map` | 420 px | 240 |
| `agent.chat`, `chat` | 480 px | 240 |

A weight makes a widget share the space left in its container. In a column, weighted elements share what the `auto` and `px` elements leave: one weighted table under auto-height rows fills the rest of the page.

## What an error card means

The platform's validation checks the references inside `props` (`source`, `bind`, `${state.x}`) and nothing else about a widget. The interface checks the rest before drawing, and replaces a widget it cannot draw with a card naming the problem; the rest of the application is displayed.

| Card says | Fix |
| --- | --- |
| unknown widget type | the `type` is not one of the eighteen listed in `SKILL.md` (`chart.donut`, `kpi.card`, `filter.dropdown` do not exist) |
| `<prop> is not a prop of this widget` | a prop this type does not accept (`title` on a `kpi`: use `label`; `label` on a chart: use `title`; `value` on a `chart.bar`: use `y`) |
| `<prop> is required` | a required prop is missing |
| `must be an aggregate such as sum(field)` | an expression where a plain aggregate is expected |
| `must be one of: …` | a value outside an enumeration (`format`, `view`) |
| a data error in the card | the source reads but the field does not exist, or the viewer cannot read the dataset |

`validate_application` does not report these problems: check each widget against this file before the save.
