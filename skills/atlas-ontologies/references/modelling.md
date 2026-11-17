# Modelling an ontology from the data

How to read a profile and turn it into decisions. The format is in `format.md`; the short version of these rules is in `SKILL.md`.

## Contents

- [What the profile tells you](#what-the-profile-tells-you)
- [From a profile to a model: a worked example](#from-a-profile-to-a-model-a-worked-example)
- [Categorical columns in depth](#categorical-columns-in-depth)
- [Tables without a key](#tables-without-a-key)
- [Many-to-many and edge datasets](#many-to-many-and-edge-datasets)
- [Designing actions](#designing-actions)
- [Refining the draft](#refining-the-draft)
- [Standard ontologies](#standard-ontologies)
- [Keeping the ontology true](#keeping-the-ontology-true)

## What the profile tells you

`atlas_ontology.py profile <project> -o profile.json` reads every tabular dataset of the project with SQL and prints, for each:

```
## shop.contacts  (iceberg, 1842 rows)  res.dataset.…
   One row per company or person we trade with.
   key candidates: contact_id
   - contact_id                     string    unique, 1842 distinct
   - name                           string    1840 distinct
   - contact_type                   string    4 distinct
       values: CLIENT (1210), FOURNISSEUR (402), PROSPECT (221), TRANSPORTEUR (9)
   - country                        string    5 distinct, 12 null
       values: FR (1500), BE (180), DE (90), ES (40), IT (20)
   - created_at                     timestamp 1790 distinct, 2019-01-04T09:12:00 … 2026-11-02T16:40:11
```

| Line | What to take from it |
| --- | --- |
| the header | the handle, the kind, the row count, and the **dataset id** to put in `dataset_id` |
| the description | what the table's author says a row is: the seed of the object type's description |
| `key candidates` | the columns that are unique and never null — the only possible `primary_key`s. `NONE` means the table cannot be bound as it is |
| a column line | the name to use **as is** for the property, the `data_type` to declare, how many distinct values, how many nulls, the range |
| `values:` | the content of a categorical column, most frequent first, with the row count of each |
| `!! not a valid property name` | a column whose name is not an identifier: it cannot be a property under that name |
| `not a scalar` | a list or struct column: not a property |

At the end:

```
## References found between datasets
   invoice_lines.contact_id -> contacts.contact_id  ONE_TO_MANY  1795/1795 values found (100%)
   products.format_code -> carton_formats.format_code  ONE_TO_MANY  6/6 values found (100%)
   invoice_lines.account_number -> accounts.account_number  ONE_TO_MANY  212/214 values found (99%)
```

Each line is a column of one table (left) whose values are the key of another (right): a link from the right-hand table (source, the "one") to the left-hand one (target, the "many"), backed by the left-hand column. The share says how many of the distinct values exist on the other side.

The script finds a reference when the column's name matches the key's (`contact_id` ↔ `contact_id`, `contact` ↔ `contacts.id`). A foreign key under an unrelated name (`payer` holding a contact id) is not found: look at the samples and the descriptions, and test a suspicion with SQL —

```sql
SELECT count(*) FROM (SELECT DISTINCT payer FROM 'shop.invoices') i
LEFT JOIN 'shop.contacts' c ON i.payer = c.contact_id WHERE c.contact_id IS NULL   -- 0: every payer is a contact
```

Options: `--datasets a,b` profiles some tables only (a profile of every table of a large project takes minutes); `--max-values 100` lists the values of columns with up to 100 of them (50 by default). Above two million rows the distinct counts are approximate, except for the key candidates, which are confirmed exactly. A table that cannot be read (`skipped …`) is reported at the end: mention it to the user.

## From a profile to a model: a worked example

A project `shop` with five tables: `contacts`, `carton_formats`, `products`, `accounts`, `invoice_lines`. The finished ontology is `assets/examples/trading-company.json`; here is how each part was decided.

**`contacts` → object type `contact`.** One key candidate, `contact_id`. `contact_type` has four values that are four sorts of contact: they become `subtypes` (`client`, `fournisseur`, `prospect`, `transporteur`), and the property's description gives the stored spelling (`CLIENT`, `FOURNISSEUR`…), which is what a query filters on. `country` is an attribute, not a kind of contact: a plain property with its values listed.

**`carton_formats` → object type `carton_format`.** Six rows, a key `format_code`, and columns of its own (dimensions, maximum weight). It is a **reference table**: small, but an object in its own right, because other tables point at it and it carries facts. Its codes are worth listing in the key's description (`C10, C20, C30, C40, PAL80, PAL120`) since there are six.

**`products` → object type `product`**, with `format_code` declared as a property — it must be, to back the link — and the link `carton_format` → `product` (`ONE_TO_MANY`, `foreign_key_property: format_code`): the format is the "one" side, the products packed in it the "many".

**`accounts` → object type `account`.** `account_number` is the key; it is text, and stays `string` (a ledger account is not a quantity). `account_class` has seven values, each a kind of account: subtypes (`expense_account`, `income_account`…) and the stored values with their meaning in the description. The table has a `parent_number` column: the chart is a tree, declared as a link from `account` to itself.

**`invoice_lines` → object type `invoice_line`.** A fact table with a key (`line_id`). It references three tables, hence three links, each oriented from the referenced object to the lines. `direction` (SALE, PURCHASE) is a state of the line, described as a property. One could argue for subtypes (`sale_line`, `purchase_line`): prefer a property when the value is a state or a flag, subtypes when the value changes what the thing *is*.

**Actions.** Three changes the business makes, each with a condition the data expresses: `convert_prospect` (only when `contact_type` is `PROSPECT`), `deactivate_product` (only when `active` is true), `record_invoice_line` (only for a client or a supplier, only on an expense or income account), which creates the line and links it to its contact and its account.

**What was left out**: nothing here. In a real project, expect staging tables, ingestion logs and aggregates; say which you left out and why.

## Categorical columns in depth

The question to ask of each column whose values the profile lists: *what do these values name?*

**They name sorts of the object** → `subtypes`. The test: you would say "a *supplier* is a contact", "a *van* is a vehicle". Subtype names are identifiers, so normalise the values — lowercase, underscores, no accent: `Company car` → `company_car`, `Société` → `societe`, `Over 50 employees` → not a kind at all (see below). Keep the mapping readable in the property's description:

```json
"vehicle_type": {"data_type": "string",
              "description": "Vehicle type as stored: Van, Truck, Trailer, Company car, Forklift, … One subtype per value, in snake_case."}
```

Leave out values that are not kinds — `Other`, `Unknown`, `Undefined`, `Reserved` — or keep them in the description only. Past about thirty values, subtypes stop helping: describe the column instead.

**They name rows of another table** → a link. The profile shows it under *References*. Do not also copy the values into subtypes: the other object type holds them, with their attributes.

**They name things that deserve a table but have none** — carton formats that exist only as codes in `products`, with their dimensions nowhere. Model the column as a property, list its values, and tell the user: "`format_code` takes 6 values; a reference table of formats would let the ontology describe them as objects". An ontology describes the data that exists.

**They name states, flags, units, bands** → a property with described values. `status` (open, closed), `currency`, `is_active`, a size band (`Under 10 employees`, `10 to 50 employees`…). The description gives the values as stored and, when it is not obvious, what each means:

```json
"account_class": {"data_type": "string",
                  "description": "Values: 1 (capital), 2 (fixed assets), 3 (stock), 4 (third parties), 5 (financial), 6 (expenses), 7 (income)."}
```

**They carry a hierarchy** — ledger accounts, product families, organisational units. With a parent column, a self-link (`account` → `account`, foreign key `parent_number`). Without one, the hierarchy is implicit in the code: say how in the description ("the first digit is the class, the first two the sub-class"), and suggest a derived column if the user wants to traverse it.

**Numbers that are categories.** A column of integers with few values is categorical when the values are codes (a `status_code` of 0–4, a `vat_rate` of 0, 5.5, 10, 20) and a measure when they are counts that happen to repeat. The name and the range tell: describe the former, ignore the list for the latter.

When a column has one value only (`status: success` on every row), it tells nothing yet: keep the property if it will vary, and do not present a single observed value as the whole domain — write "Observed: success".

## Tables without a key

`key candidates: NONE` means no single column identifies a row. An object type needs one, so:

- **Aggregates** (`sales_by_day_and_region`): usually not business objects. Leave them out; an agent reads them with SQL.
- **Events and measurements** keyed by two columns (`sensor` + `timestamp`): leave them out, or ask for a key upstream. A SQL transform producing a new dataset is the clean way:

  ```sql
  SELECT concat(sensor_id, '|', CAST(measured_at AS VARCHAR)) AS reading_id, * FROM 'plant.readings'
  ```

  Bind the object type to that dataset. Do not create datasets or transforms on your own initiative: propose it.
- **A table whose natural key repeats because of duplicates**: that is a data-quality finding. Report the count; do not bind on a key that repeats.

Never work round the rule by declaring a non-unique column as `primary_key`: the platform accepts it and answers several objects under one `@id`.

## Many-to-many and edge datasets

When two object types relate many-to-many, the data holds the pairs in a table of its own — `product_suppliers(product_sku, supplier_id, lead_time_days)`. Two ways to model it:

- **An edge dataset**, when the table holds only the pair: a `MANY_TO_MANY` link with `dataset_id` (the table), `source_key: product_sku`, `target_key: supplier_id`.
- **An object type**, when the pair has attributes or a key of its own (an order line between an order and a product, with a quantity): declare it as an object type and link it to both sides with two `ONE_TO_MANY` links. This keeps the attributes reachable.

The profile shows such a table as one referencing two others.

## Designing actions

An ontology that only describes is complete without actions. Add them when the user wants the changes the business makes to be part of the model — so an agent knows that a prospect *can* be converted, and under which condition.

**Find the candidates in the data.** The profile shows where the business changes state:

| In the profile | Suggests |
| --- | --- |
| a status-like column with a small set of values (`contact_type`: PROSPECT → CLIENT; `status`: open → closed) | a `modify_object` moving from one value to another, guarded by a rule on the current value |
| a boolean (`active`, `is_blocked`) | an action that flips it, guarded so it is not flipped twice |
| a fact table referencing other objects (`invoice_lines` → contact, account) | a `create_object` followed by one `add_link` per reference |
| an edge dataset | `add_link` / `remove_link` |

**Write the rule from the values.** A rule is the business condition, in the data's own words:

```json
{"parameter": "contact", "property": "contact_type", "operator": "equals", "value": "PROSPECT",
 "message": "Only a prospect can be converted into a client."}
```

`PROSPECT` is copied from the profile's `values:` line. A rule written from memory (`"prospect"`, `"Prospect"`) never matches and refuses every call. The same goes for `static_value`s: the value an action writes must be one the column already uses, or you have just invented a category.

Numeric guards come from the profile's ranges (`amount greater_than 0`), membership from its value lists (`account_class in ["6", "7"]`), presence from its null counts (`validated_at is_null`).

**Three shapes cover most needs** — all three are in `assets/examples/trading-company.json`:

- *a guarded change of state* (`convert_prospect`): one object parameter, one rule on its current state, one `modify_object`;
- *a withdrawal* (`deactivate_product`): the same, on a boolean. Prefer it to `delete_object` when other objects reference the one being removed — the invoice lines of a deleted product would point at nothing;
- *a creation with its links* (`record_invoice_line`): object parameters for the things referenced, value parameters for the new object's properties, a `create_object` with `assign_to_parameter`, then one `add_link` per reference, each from the "one" side to the created object.

**Parameters.** An object the action reads or changes is an `ontology_object` parameter; a value the caller supplies is a value parameter of the property's data type. Mark `required` what the action cannot do without. In a `create_object`, always set the primary key, from a parameter.

**Scope.** `<resource>:<action>`: the plural of the object and the verb (`contacts:convert`, `invoices:write`). It names the right a caller needs; agree the names with the user when the organization already has a convention.

**Do not** model as actions what the pipeline does (loading, recomputing): actions are what people and agents decide. And ask before adding any: propose the candidates with their rule, and declare the ones the user confirms.

## Refining the draft

`atlas_ontology.py draft profile.json -o ontology.json` writes a first ontology mechanically: one object type per table that has a key (named from the table's slug, described from the table's description, bound to it), every scalar column as a property with the values of categorical columns in its description, and one link per reference found. It is a starting point that is right about the data and naive about the domain. Go through it:

1. **Remove** the object types that are not part of the domain (technical tables), and the links that named them.
2. **Rename** object types to business names, singular. Renaming an object type means renaming it in every link's ends.
3. **Check the primary key** the draft picked (the first candidate) against the others.
4. **Rewrite descriptions**: what one instance is. Describe the properties whose name is not self-explanatory, and the units of measures.
5. **Decide each categorical column** (subtypes, link, description), as above.
6. **Rename links** to something that reads from source to target (`contact_invoice_lines`, `account_children`), give them a `display_name` (`is invoiced`, `has sub-account`), and check each direction.
7. **Drop properties** that are technical (load timestamps, file names) or always null — the draft already skips the latter.
8. Set `api_name`, `name`, `version`, `description` of the ontology itself.
9. Add the actions the user wants (the draft has none): see [Designing actions](#designing-actions).

Then `check`. The draft passes `check` as it comes; your edits are what can break it.

## Standard ontologies

The platform ships twenty read-only ontologies describing domains without any binding — `general`, `business`, `finance`, `financial_analysis`, `accounting`, `insurance`, `legal`, `healthcare`, `human_resources`, `marketing`, `real_estate`, `supply_chain`, `maritime`, `energy`, `environment`, `esg`, `research`, `cyber`, `security`, `geopolitics`. Their ids are `res.ontology.standard-<name>`.

```bash
python scripts/atlas_ontology.py list --standard
python scripts/atlas_ontology.py get res.ontology.standard-accounting -o accounting.json
```

They are vocabularies: object types with subtypes, and typed links, no properties. Use the one closest to the user's domain as a source of names — if `accounting` calls it `ledger_account` and `supply_chain` calls it `shipment`, prefer those words — and of links you might have missed. Do not copy one wholesale: an ontology of the project holds what the project's data holds.

## Keeping the ontology true

An ontology is checked at one moment; the data moves on.

- **A new value appears** in a categorical column (a fifth contact type): the subtypes and the description are stale. Re-profile, compare, update.
- **A column is renamed or dropped**: every read of the object type fails. `verify <id>` shows it; `check` on the saved definition says which property.
- **A table is rebuilt with duplicates**: the key stops being unique. `check` catches it.

When asked to update an ontology, fetch it (`get <id> --editable -o ontology.json`), re-profile the tables it is bound to, apply the differences, bump `version`, `check`, `update`, `verify`. Offer the user to run the same check periodically rather than assuming the model stays true.
