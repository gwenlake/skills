---
name: atlas-ontologies
description: "Design, check and publish Gwenlake Atlas ontologies with the Gwenlake MCP server: the typed model of a project's domain (object types, properties, links, actions) bound to the datasets that hold the instances. Explains the format the platform accepts, and how to build an ontology from a project by profiling its tables in SQL (schema, keys, the values of categorical columns, the references between tables) so that it matches the data exactly. Use whenever the user asks to create, generate, update, fix or explain an ontology, a semantic layer, a data model or a knowledge graph in Gwenlake Atlas, wants the datasets of a project described as business objects for an agent, mentions object_types or link_types, or has an ontology that is refused or returns wrong or empty objects, even when they only say 'model my project'."
---

# Gwenlake Atlas ontologies

An **ontology** describes the domain of a project in business terms: the kinds of things that exist (**object types**: a customer, an order, a ledger account), what is known about each (**properties**), and how they relate (**link types**: a customer *places* orders). Each object type can be **bound** to the dataset that holds its instances — one row, one object.

It is the semantic layer over the data. An agent bound to an ontology queries it **first**, before the raw tables; the platform serves the instances as JSON-LD. So an ontology is only worth what it says truthfully about the data: a model that looks right but names a column that does not exist, or a key that repeats, answers errors or wrong objects.

Two facts shape this skill:

- **The format in the public guide is not the one the platform accepts.** The guide shows `object_types` as a map keyed by name; the platform wants a **list** of objects, each with its `api_name`. Its action example uses keys and an operator the platform does not know. Follow this file.
- **The platform checks the format when it saves, not the data.** A property that is not a column, a primary key that is not unique, a dataset that does not exist: all accepted, all broken on read. Checking against the data is your job, and you do it in SQL before saving.

Everything here goes through the tools of the `gwenlake` MCP server, as the signed-in user. No script and no API key are involved.

## Workflow

When the user hands you a project and asks for its ontology, do not model from the table names. Read the data.

1. **Profile the project.** Columns and types, row counts, which columns are unique, the values of every categorical column, which columns reference another table. See [Profiling with SQL](#profiling-with-sql).
2. **Decide the model** from the profile: which tables are business objects, what identifies each, which columns are classifications, what links to what. This is the part that needs judgement: see [Modelling from the data](#modelling-from-the-data).
3. **Write the ontology** by the rules of [The format](#the-format).
4. **Check it** against the format rules and against the data, with the queries of [Checking, saving, fixing](#checking-saving-fixing). Fix every error before saving anything.
5. **Show the model to the user and get their agreement**, then create it with `create_ontology` (or change the existing one with `update_ontology`).
6. **Verify** that every bound type and every link reads: `list_ontology_objects` on each type, `list_linked_objects` on one instance per link.
7. **Report**: the ontology id, what each object type is bound to, what you left out and why, and the questions only the user can answer.

| Step | Tool |
| --- | --- |
| find the project and its tables | `search_catalog`, `list_projects`, `list_datasets(project_id)` |
| columns, row count and the name to use in SQL | `describe_dataset(dataset_id)`: `sql_name` is what goes in a `FROM` clause |
| read the data | `query_dataset(statement)`, DuckDB, read-only |
| existing ontologies of the project | `list_ontologies(project_id)`, `get_ontology(ontology_id)` |
| save | `create_ontology`, `update_ontology` |
| read back | `list_ontology_objects`, `get_ontology_object`, `list_linked_objects` |

If `create_ontology` answers that it is disabled on this MCP server, writing is off for this deployment or this plan. Hand the user the JSON document and tell them to save it from the Atlas interface.

## Profiling with SQL

Profile every tabular dataset of the project that could be part of the domain. `t` below stands for a dataset's `sql_name`. Results are capped at 200 rows, so always aggregate in the statement.

**Rows, distinct values and nulls of every column, in one statement per table**:

```sql
SELECT count(*) AS n_rows,
       count(DISTINCT contact_id) AS d_contact_id, count(*) - count(contact_id) AS null_contact_id,
       count(DISTINCT contact_type) AS d_contact_type, count(*) - count(contact_type) AS null_contact_type
FROM t
```

A column is a **key candidate** when its distinct count equals the row count and it has no null. A column with few distinct values relative to the rows (up to a few dozen) is **categorical**.

**The values of a categorical column, most frequent first**:

```sql
SELECT contact_type AS value, count(*) AS n FROM t GROUP BY 1 ORDER BY n DESC LIMIT 50
```

**The range of a date or numeric column**: `SELECT min(created_at), max(created_at) FROM t`.

**A reference between two tables**: for a column of `child` whose name or values suggest the key of `parent`, measure the share of its distinct values found on the other side.

```sql
SELECT count(DISTINCT c.contact_id) AS n_values,
       count(DISTINCT c.contact_id) FILTER (WHERE p.contact_id IS NOT NULL) AS n_found
FROM child c LEFT JOIN parent p ON c.contact_id = p.contact_id
WHERE c.contact_id IS NOT NULL
```

Test the pairs that make sense (same column name as a key candidate, or a name ending in `_id`, `_code`, `_number`), not every pair. On a project with many tables, start with the ones the user named and say which ones you left unprofiled.

Without access to the data, ask the user for the columns of each table, a sample and the values of its categorical columns, write the JSON by the rules below, say that it was **not** checked against the data, and hand it over.

## The format

An ontology is one JSON document.

```json
{
  "name": "Trading company",
  "api_name": "trading_company",
  "version": "1",
  "description": "Who the business deals with, what it sells, where each invoice line is booked.",
  "object_types": [
    {
      "api_name": "contact",
      "display_name": "Contact",
      "description": "A company or person the business deals with, one row per contact.",
      "primary_key": "contact_id",
      "properties": {
        "contact_id":   {"data_type": "string", "required": true},
        "name":         {"data_type": "string", "required": true},
        "contact_type": {"data_type": "string", "description": "Values as stored: CLIENT, FOURNISSEUR, PROSPECT."}
      },
      "subtypes": ["client", "fournisseur", "prospect"],
      "dataset_id": "res.dataset.…"
    },
    {
      "api_name": "invoice_line",
      "description": "One line of an invoice.",
      "primary_key": "line_id",
      "properties": {
        "line_id":    {"data_type": "long", "required": true},
        "contact_id": {"data_type": "string"},
        "amount":     {"data_type": "double"}
      },
      "dataset_id": "res.dataset.…"
    }
  ],
  "link_types": [
    {
      "api_name": "contact_invoice_lines",
      "description": "The invoice lines of a contact.",
      "source_object_type": "contact",
      "target_object_type": "invoice_line",
      "cardinality": "ONE_TO_MANY",
      "foreign_key_property": "contact_id"
    }
  ],
  "action_types": [
    {
      "api_name": "convert_prospect",
      "description": "Turns a prospect into a client once a first order is signed.",
      "parameters": {
        "contact": {"data_type": {"type": "ontology_object", "object_type_api_name": "contact"}, "required": true}
      },
      "rules": [
        {"parameter": "contact", "property": "contact_type", "operator": "equals", "value": "PROSPECT",
         "message": "Only a prospect can be converted into a client."}
      ],
      "scope": "contacts:convert",
      "operations": [
        {"type": "modify_object", "target_object_parameter": "contact",
         "property_modifications": {"contact_type": {"type": "static_value", "value": "CLIENT"}}}
      ]
    }
  ]
}
```

**The document**

| Key | Required | Meaning |
| --- | --- | --- |
| `api_name` | yes | the ontology's stable identifier, e.g. `sales`. It is the base of every object's `@id` (`urn:ontology:<api_name>/…`): do not change it once others rely on it |
| `name` | yes | the displayed name; the resource's slug is derived from it |
| `project_id` | on create | the project that holds it: an argument of `create_ontology` |
| `version` | no | a text of your choice (`"1"`, `"2026-11"`); bump it when the model changes |
| `description` | no | what the model covers — an agent reads it to decide whether to use the ontology |
| `base_uri` | no | the base of every `@id`; `urn:ontology:<api_name>` when absent |
| `object_types`, `link_types`, `action_types` | no | **lists** |

**An object type** — one entry of `object_types`

| Key | Meaning |
| --- | --- |
| `api_name` | its identifier, singular: `contact`, `invoice_line` |
| `display_name`, `description` | the name people read; what one instance *is* ("one row per contact") |
| `properties` | a **map**: property name → `{data_type, required, description, display_name}` |
| `primary_key` | the property that identifies an instance. Required for a bound type |
| `subtypes` | a list of names: the kinds of this object (`client`, `supplier`). Descriptive |
| `dataset_id` | the dataset holding the instances (`res.dataset.…`), one row per object |

**A link type** — one entry of `link_types`

| Key | Meaning |
| --- | --- |
| `api_name`, `display_name`, `description` | its identifier and what it means, read from source to target |
| `source_object_type`, `target_object_type` | an object type's `api_name`; a list of names for alternatives; absent for an untyped end |
| `cardinality` | `ONE_TO_ONE`, `ONE_TO_MANY` or `MANY_TO_MANY` |
| `foreign_key_property` | a property **of the target** holding the **source's primary key** (`ONE_TO_ONE`, `ONE_TO_MANY`) |
| `dataset_id`, `source_key`, `target_key` | an edge dataset, one row per pair, for `MANY_TO_MANY` (`source_id` / `target_id` by default) |
| `inverse_of` | the `api_name` of the reciprocal link |

**An action type** — one entry of `action_types`: a change the domain allows, declared as a contract — what it takes, when it is allowed, what it does.

| Key | Meaning |
| --- | --- |
| `api_name`, `display_name`, `description` | its identifier, a verb phrase (`convert_prospect`), and what it is for |
| `parameters` | a **map**: name → `{data_type, required, description}`. `data_type` is an **object**: `{"type": "string"}` (any property data type) for a value, `{"type": "ontology_object", "object_type_api_name": "contact"}` for an object of the ontology |
| `rules` | a list of preconditions, each `{parameter, property, operator, value, message}`: a property of an **object** parameter compared to a value. All must hold. `operator`: `equals`, `not_equals`, `greater_than`, `greater_than_or_equal`, `less_than`, `less_than_or_equal`, `in`, `not_in` (a list `value`), `is_null`, `is_not_null` (no `value`) |
| `scope` | the scope a caller needs, `<resource>:<action>` in lowercase: `contacts:convert` |
| `operations` | what the action does, in order (below) |

| Operation `type` | Keys |
| --- | --- |
| `modify_object` | `target_object_parameter` (an object parameter), `property_modifications`: property → value |
| `create_object` | `object_type_api_name`, `property_values`: property → value, `assign_to_parameter`: a **new** name under which later operations of the action reach the created object |
| `delete_object` | `target_object_parameter` |
| `add_link`, `remove_link` | `link_type_api_name`, `source_object_parameter`, `target_object_parameter` |

A value, in `property_modifications` and `property_values`, is never bare: `{"type": "static_value", "value": "CLIENT"}` for a constant, `{"type": "parameter_value", "parameter": "amount"}` for what the caller passed.

**Rules — what is refused, and what is accepted but wrong**

- **Identifiers**: every `api_name`, property name and subtype matches `[A-Za-z_][A-Za-z0-9_]*`. No space, hyphen or accent: `Class A` is refused, `class_a` is fine. Use snake_case.
- **`object_types`, `link_types`, `action_types` are lists**; `properties` is a map. The reverse is refused (`Input should be a valid list`).
- **`data_type`** is one of `string`, `integer`, `long`, `short`, `byte`, `double`, `float`, `decimal`, `boolean`, `date`, `timestamp`. `text`, `int`, `number`, `datetime` are refused.
- **`primary_key` names a declared property.** One property: there is no composite key.
- **A link's ends are declared object types**; a `foreign_key_property` is a property of the *target*; a `MANY_TO_MANY` link cannot have one.
- **An unknown key is dropped without a word.** `primaryKey`, `type` instead of `data_type`, `source` instead of `source_object_type`: the save succeeds and the setting is lost.
- **A property name must be the dataset's column name, exactly**, case included. Only the declared properties are ever read, so undeclared columns stay private — and a declared property that is not a column makes every read of the type fail (`400 … Referenced column "x" not found`).
- **The primary key must be unique and never null in the dataset.** The platform does not check: with a key that repeats, several objects share one `@id` and reading "one object" returns an arbitrary row.
- **The foreign key lives on the "many" side.** For "a contact has many invoice lines", the link goes `contact` → `invoice_line` with `foreign_key_property: contact_id`, a column of *invoice_line*. To express the many-to-one reading, name the link accordingly or add a reciprocal link with `inverse_of`; you cannot put the key on the source.
- **A link with neither a foreign key nor an edge dataset is descriptive**: it tells what relates to what, but cannot be traversed.
- **In an action**, a parameter's object type, a rule's parameter and property, an operation's parameters, properties and link type must all be declared; a rule's parameter must be an object parameter; `in` and `not_in` take a list. The guide's spelling — `"operator": "neq"`, `"parameter"` and `"properties"` in an operation — is not the platform's: the operator is refused, and the two keys are dropped silently, **leaving an action that saves and changes nothing**. The platform does not check that a value fits the property's type, that a `create_object` sets the primary key, nor that the two ends of a link operation are the right way round.

Nothing enforces the data rules for you: run the checks of [Checking, saving, fixing](#checking-saving-fixing). Every field and the error messages: `references/format.md`.

## Modelling from the data

The profile gives you facts; the model is a set of decisions about them. Make them in this order.

**1. Which tables are object types.** A table is a business object when one row is one thing with an identity: a contact, a product, an invoice, an order. It has a **key candidate** in the profile — a column unique and never null.

- A table with **no single-column key** (daily aggregates, an event log keyed by two columns) is not an object type as it stands. Leave it out and say so, or ask whether a key can be added upstream (a SQL transform producing `concat(a, '|', b) AS id`). Never pick a column that repeats.
- Staging and technical tables (`*_raw`, ingestion runs, quality reports) are rarely part of the domain. Leave them out unless the user's domain *is* the pipeline.
- When several key candidates exist, choose the one the business uses (`sku`, `account_number`), not a coincidence of a small table (`rows_read` unique among 4 rows).

**2. Properties.** Declare the columns that mean something; drop technical ones and those that are always null. Take each `data_type` from the profile. Mark `required` the columns that are never null. Identifiers that look numeric but are not quantities (account numbers, postal codes, phone numbers) stay `string` if stored as text: leading zeros matter.

**3. Categorical columns — the content of the tables.** This is where an ontology built from the data differs from one built from the schema. For every column whose values the profile lists, decide which of four things it is:

| The column is… | Example | Model it as |
| --- | --- | --- |
| a **kind of the object itself** — the rows are different sorts of the same thing | `contact_type`: CLIENT, FOURNISSEUR, PROSPECT | **`subtypes`** of the object type, one per value, in snake_case — and the exact stored values in the property's `description` |
| a **reference to a table that exists** in the project | `format_code` → the `carton_formats` table; `account_number` → the chart of accounts | its own **object type** bound to that table, and a **link** backed by the column |
| a **reference to a concept with attributes of its own, but no table** | carton formats that only appear as codes in `products` | a property with its values described — and tell the user a reference table would let it become an object type. Do not invent a dataset |
| a **state, flag or unit** | `status`: open, closed; `currency`: EUR, USD | a plain property, values listed in its `description` |

Write the values **as the data spells them** in the description (`Values as stored: CLIENT, FOURNISSEUR`). An agent filtering on that column needs the literal value, and a subtype name (`fournisseur`) is not it. When a column has more values than are worth listing, give the count and the most frequent ones.

A code that carries a hierarchy (ledger accounts `6` → `60` → `607`, a product family tree) is an object type with a link **to itself** when the table has a parent column: `account` → `account`, `ONE_TO_MANY`, `foreign_key_property: parent_number`. When the hierarchy is only in the digits, say so in the description of the property.

**4. Links.** Take them from the profile's *References found between datasets*: a column of one table whose values are the key of another, with the share of values found. A reference at 100% is a link; one at 93% is a link with orphans — keep it and report the orphans; a low one is a coincidence of names. Orient every link from the "one" side (source) to the "many" side (target), the foreign key being a property of the target. Declare the foreign-key column as a property of the target, or the link is refused.

**5. Actions.** Declare an action for each change the business makes to these objects and that the user wants agents or applications to be allowed to make: converting a prospect, withdrawing a product, booking an invoice line. An action is worth declaring when it has a **precondition the data can express** — and the profile is where the precondition's values come from: "only a prospect can be converted" is `contact_type equals PROSPECT`, with `PROSPECT` spelled as the table spells it. Take every constant in a rule or a `static_value` from the profile's values, never from memory. Name the action as a verb (`convert_prospect`), give each rule a `message` a person can act on, and give the action a `scope` named after the object and the verb (`contacts:convert`). Do not invent actions to fill the list: when the user asked only for a description of the data, `"action_types": []` is right — propose the two or three the data suggests and let them choose.

**6. Names and descriptions.** Names come from the business, not from the table: `contact`, not `crm_contacts_v2`. A description says what one instance is and where it comes from. They are not decoration — they are what an agent reads to choose what to query. Use the language of the data and of the user for display names and descriptions; identifiers stay ASCII.

**Ask the user** what the data cannot tell: which of two candidate keys the business uses, whether a table is in scope, what a cryptic code means. Carry on with a stated assumption rather than stopping.

Worked decisions on a profile, designing actions, edge datasets, standard ontologies: `references/modelling.md`.

## Checking, saving, fixing

There is no validate-only call for an ontology, and a save that succeeds proves nothing about the data. Check in two passes before `create_ontology`.

**Format, by reading your own document** against the rules above: lists and maps the right way round, every identifier valid, every `data_type` in the allowed list, every `primary_key` a declared property, every link end a declared object type, every `foreign_key_property` a property of the *target*, no unknown key.

**Data, with `query_dataset`**, for every bound object type and every link:

| Check | Query | Must hold |
| --- | --- | --- |
| every property is a column | `SELECT <every declared property> FROM t LIMIT 1` | the statement runs; a misspelled name fails with `Referenced column "x" not found` |
| the primary key identifies a row | `SELECT count(*), count(DISTINCT pk), count(*) - count(pk) FROM t` | the first two are equal and the third is 0 |
| a link joins data | the reference query of [Profiling with SQL](#profiling-with-sql), on the foreign key of the target and the primary key of the source | `n_found` is not 0; if it is below `n_values`, report the orphans |
| a constant of a rule or a `static_value` exists | `SELECT count(*) FROM t WHERE contact_type = 'PROSPECT'` | not 0, with the spelling of the data |

Compare each declared `data_type` with the column type `describe_dataset` gives; a difference deserves a decision, not always a fix.

**After saving**, read back: `list_ontology_objects(ontology_id, object_type, limit=3)` for every bound type, then `list_linked_objects` on one of those instances for every link that has a binding. An error here is a binding to fix, not a transient failure.

| Message | Cause and fix |
| --- | --- |
| `Input should be a valid list` | the map form of the guide: turn `{"customer": {…}}` into `[{"api_name": "customer", …}]` |
| an identifier refused | a space, hyphen, accent or leading digit in an `api_name`, a property or a subtype |
| `Unknown data_type` | `text`, `int`, `number`, `datetime`: use the allowed names |
| `Referenced column "x" not found`, on read | the property is not spelled as the column is, or the type is bound to the wrong dataset |
| several objects with one `@id`, or an arbitrary row for "one object" | the primary key repeats: choose another column, or the table is not one row per object |
| a foreign key refused as not a property of the target | the foreign key is on the wrong side: turn the link round |
| a link that returns nothing | it joins nothing: wrong column, wrong direction, or two columns that only share a name |
| an operator refused | a rule written `neq`, `eq`, `gt`, `==`: use `not_equals`, `equals`, `greater_than`… |
| an action that saves and changes nothing | `parameter` / `properties` from the guide: write `target_object_parameter` and `property_modifications` |
| a bare value refused in an operation | wrap it: `{"type": "static_value", "value": …}` |
| a save refused as invalid | a format rule the platform enforces; the message names the element |
| `references unknown …` on update | you removed an object type a link still names: remove or repoint the link in the same update |
| a refusal about permission | no right on the ontology or on a bound dataset, or an id that does not exist |

**Updating**: read the current model with `get_ontology`, change it, and call `update_ontology` with the collections you changed. A collection passed **replaces the stored one wholesale**: send it complete, not just the part that changed. A collection left out is kept. There is no version history to restore from: before an update, show the user what will change, and keep the previous model in the conversation.

**One ontology per domain in a project.** `api_name` is not unique on the platform: creating twice makes two ontologies with the same `@id`s. Call `list_ontologies(project_id)` first, and update the existing one instead of creating a second.

**Deleting** an ontology is not possible through the MCP server: the user does it from the Atlas interface. Datasets are never touched by an ontology: it only reads them.

## Using the ontology

- **In an agent**: name it under `resources:` of the agent's `agent.md` (`- ref: <project>.<ontology slug>`). The agent gets `model`, `list_objects`, `get_object`, `list_links` and `list_linked_objects`, and is told to query the ontology before the datasets behind it.
- **From Claude**: `get_ontology` for the model, then `list_ontology_objects`, `get_ontology_object` and `list_linked_objects`. The caller must be able to read the ontology **and** the datasets.

## Before you hand over

- You profiled the data; no column, key or value in the ontology is a guess.
- Every bound object type has a primary key that a query found unique and never null.
- Every categorical column was decided: subtypes, a linked object type, or described values — with the values as stored.
- Every link is oriented one → many, backed by a column of the target, and joins data.
- Every action has a rule or a reason to have none, constants spelled as the data spells them, and complete operations.
- Every check query passed, and every bound type and link read back after saving.
- You told the user the ontology id, what you left out and why, and what you assumed.

## Bundled files

- `references/format.md`: every field, action types in full, the JSON-LD answers, the platform's messages.
- `references/modelling.md`: reading a profile, the decisions worked on examples, designing actions, edge datasets, standard ontologies.
- `assets/examples/trading-company.json`: a complete ontology: contacts with subtypes, a carton-format reference table, a chart of accounts with a self-link, invoice lines linked to all three, and three actions (a guarded modification, a withdrawal, a creation followed by two links). Replace the `dataset_id` placeholders.

The public guide is at https://docs.gwenlake.com/atlas/guides/ontologies. Where it and this file disagree on the format, this file was checked against the platform; and if the platform answers otherwise than both, the platform is right: follow its error message.
