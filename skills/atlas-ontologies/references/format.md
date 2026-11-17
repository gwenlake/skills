# The ontology format and API

The format in full, the routes, and what the platform answers. The workflow and the modelling decisions are in `SKILL.md`.

## Contents

- [The document](#the-document)
- [Object types](#object-types)
- [Properties and data types](#properties-and-data-types)
- [Link types](#link-types)
- [Action types](#action-types)
- [What the platform validates, and what it does not](#what-the-platform-validates-and-what-it-does-not)
- [Routes](#routes)
- [Objects as JSON-LD](#objects-as-json-ld)
- [Status codes and messages](#status-codes-and-messages)
- [Differences with the public guide](#differences-with-the-public-guide)

## The document

```json
{
  "name": "Sales",
  "project_id": "res.project.…",
  "api_name": "sales",
  "version": "1",
  "description": "…",
  "base_uri": null,
  "object_types": [],
  "link_types": [],
  "action_types": []
}
```

| Key | Type | Notes |
| --- | --- | --- |
| `name` | text | required. The resource's name; its slug is derived from it (`Sales model` → `sales-model`) |
| `project_id` | text | required on create: the project that holds the ontology |
| `api_name` | identifier | required. The stable identifier. Not unique on the platform: two ontologies of a project may share one — avoid it |
| `version` | text | free (`"1"`, `"1.2.0"`). A number is refused: quote it |
| `description` | text | what the model covers |
| `base_uri` | text | the base of every `@id`. Absent: `urn:ontology:<api_name>` |
| `object_types`, `link_types`, `action_types` | lists | absent or `[]` for none |

A read (`GET /ontologies/{id}`) returns the same keys plus the resource's own: `object`, `id`, `slug`, `alias`, `organization_id`, `parent_id`, `created_by`, `created_at`, `updated_at`, `is_standard`. Every optional key comes back, `null` when unset.

## Object types

```json
{
  "api_name": "product",
  "display_name": "Product",
  "description": "An article of the catalogue, one row per SKU.",
  "primary_key": "sku",
  "properties": {
    "sku":   {"data_type": "string", "required": true},
    "label": {"data_type": "string"}
  },
  "subtypes": [],
  "dataset_id": "res.dataset.…"
}
```

| Key | Type | Notes |
| --- | --- | --- |
| `api_name` | identifier | required, unique among the object types. It is the `@type` of the instances and a segment of their `@id` |
| `display_name` | text | the name shown to people |
| `description` | text | what one instance is |
| `primary_key` | property name | must be a declared property. Needed to address an instance; required in practice for a bound type |
| `properties` | map | name → property. May be empty for an unbound, purely descriptive type |
| `subtypes` | list of identifiers | an is-a list: the kinds of this object. Not bound to data, not enforced |
| `dataset_id` | dataset id | binds the type: one row of the dataset is one instance |

A bound type reads **only its declared properties**, by name: `SELECT "sku", "label" FROM <dataset>`. So a property name is a column name, exactly; a column that is not declared is never exposed; and a declared property that is not a column fails every read of the type.

An object type without `dataset_id` is a concept: it documents the domain (and can be the end of a descriptive link) but has no instances to read.

## Properties and data types

```json
"amount": {"data_type": "double", "required": false, "display_name": "Amount", "description": "Euros, excluding tax."}
```

| `data_type` | For a column of type (DuckDB / Iceberg) |
| --- | --- |
| `string` | VARCHAR, UUID |
| `boolean` | BOOLEAN |
| `byte`, `short`, `integer`, `long` | TINYINT, SMALLINT, INTEGER, BIGINT |
| `float`, `double` | FLOAT, DOUBLE |
| `decimal` | DECIMAL(p, s) |
| `date` | DATE |
| `timestamp` | TIMESTAMP, TIMESTAMP WITH TIME ZONE |

A list, a struct, a blob or a time-of-day column cannot be a property: leave it out, or expose a scalar version of it from a SQL transform.

`required: true` documents that the value is always present. It is not enforced on the data: set it from what the profile shows (no null), not from what should be.

The property name must match `[A-Za-z_][A-Za-z0-9_]*`. A column named `Order ID` or `montant-ht` cannot be a property as it is: rename the column upstream (a SQL transform: `SELECT "Order ID" AS order_id …`) and bind the result.

## Link types

```json
{
  "api_name": "customer_orders",
  "display_name": "places",
  "description": "The orders placed by a customer.",
  "source_object_type": "customer",
  "target_object_type": "order",
  "cardinality": "ONE_TO_MANY",
  "foreign_key_property": "customer_id",
  "inverse_of": null
}
```

| Key | Type | Notes |
| --- | --- | --- |
| `api_name` | identifier | required, unique among the link types |
| `source_object_type`, `target_object_type` | name, list of names, or absent | a declared object type; a list gives alternatives (`["organization", "location"]`); absent leaves the end untyped. Source and target may be the same type (a hierarchy) |
| `cardinality` | enum | `ONE_TO_ONE`, `ONE_TO_MANY`, `MANY_TO_MANY` |
| `foreign_key_property` | property name | a property **of the target** whose value is the **primary key of the source**. `ONE_TO_ONE` and `ONE_TO_MANY` only; needs exactly one source and one target |
| `dataset_id` | dataset id | an **edge dataset**: one row per (source, target) pair. The way to back a `MANY_TO_MANY` link |
| `source_key`, `target_key` | column names | the columns of the edge dataset holding the two primary keys; `source_id` and `target_id` when absent |
| `inverse_of` | link name | the reciprocal link, when both directions are declared |

Three kinds of link:

- **Backed by a foreign key** — the usual case. `customer` → `order`, `ONE_TO_MANY`, `foreign_key_property: customer_id`: the `order` dataset has a `customer_id` column holding a customer's key. The key is always on the target; the source is always the "one" side.
- **Backed by an edge dataset** — for many-to-many: `product` ↔ `supplier` through a table `product_suppliers(product_sku, supplier_id)`, declared with `dataset_id`, `source_key: product_sku`, `target_key: supplier_id`.
- **Descriptive** — no backing. The link says what relates to what and can be read in the model, but not traversed. Only single-typed, backed links are traversable.

## Action types

An action type declares a change the domain allows: what it takes (`parameters`), when it is allowed (`rules`), who may ask for it (`scope`) and what it does (`operations`). It is a contract stored with the model, so that an agent or an application knows which changes exist and under which conditions.

```json
{
  "api_name": "record_invoice_line",
  "display_name": "Record an invoice line",
  "description": "Creates the line, then attaches it to the contact invoiced and to the ledger account.",
  "parameters": {
    "contact": {"data_type": {"type": "ontology_object", "object_type_api_name": "contact"}, "required": true,
                "description": "The contact invoiced."},
    "account": {"data_type": {"type": "ontology_object", "object_type_api_name": "account"}, "required": true},
    "line_id": {"data_type": {"type": "long"}, "required": true},
    "amount":  {"data_type": {"type": "double"}, "required": true, "description": "Euros, excluding tax."}
  },
  "rules": [
    {"parameter": "contact", "property": "contact_type", "operator": "in", "value": ["CLIENT", "FOURNISSEUR"],
     "message": "Only a client or a supplier can be invoiced."}
  ],
  "scope": "invoices:write",
  "operations": [
    {"type": "create_object", "object_type_api_name": "invoice_line", "assign_to_parameter": "line",
     "property_values": {
       "line_id":   {"type": "parameter_value", "parameter": "line_id"},
       "amount":    {"type": "parameter_value", "parameter": "amount"},
       "direction": {"type": "static_value", "value": "SALE"}
     }},
    {"type": "add_link", "link_type_api_name": "contact_invoice_lines",
     "source_object_parameter": "contact", "target_object_parameter": "line"},
    {"type": "add_link", "link_type_api_name": "account_invoice_lines",
     "source_object_parameter": "account", "target_object_parameter": "line"}
  ]
}
```

| Key | Type | Notes |
| --- | --- | --- |
| `api_name` | identifier | required, unique among the action types. A verb phrase |
| `display_name`, `description` | text | what the action is for |
| `parameters` | map | name → parameter. May be empty |
| `rules` | list | preconditions; all must hold. May be empty |
| `scope` | text | `<resource>:<action>`, lowercase (`invoices:write`, `claims:approve`). Any pair of that shape is accepted; absent means no scope of its own |
| `operations` | list | applied in order. An empty list is accepted and does nothing |

**A parameter** is `{data_type, required, display_name, description}`. `data_type` is an object, never a bare name:

| `data_type` | The parameter holds |
| --- | --- |
| `{"type": "string"}` — or any of the eleven property data types | a value the caller passes |
| `{"type": "ontology_object", "object_type_api_name": "contact"}` | an object of the ontology, of a declared object type |

**A rule** is `{parameter, property, operator, value, message}`: the `property` of the object held by `parameter` — which must be an `ontology_object` parameter — is compared to `value`. `message` is what the caller is told when the rule refuses the action.

| `operator` | `value` |
| --- | --- |
| `equals`, `not_equals` | a constant |
| `greater_than`, `greater_than_or_equal`, `less_than`, `less_than_or_equal` | a constant |
| `in`, `not_in` | a list of constants (a scalar is refused) |
| `is_null`, `is_not_null` | none |

**An operation** has a `type` and the keys of that type:

| `type` | Keys | Does |
| --- | --- | --- |
| `modify_object` | `target_object_parameter`, `property_modifications` | sets properties of the object held by an object parameter |
| `create_object` | `object_type_api_name`, `property_values`, `assign_to_parameter` | creates an object of a declared type. `assign_to_parameter` names it for the operations that follow; it must be a **new** name, not one of the parameters |
| `delete_object` | `target_object_parameter` | deletes the object held by an object parameter |
| `add_link`, `remove_link` | `link_type_api_name`, `source_object_parameter`, `target_object_parameter` | adds or removes an edge of a declared link type between two objects, each an object parameter or an object created earlier in the action |

`property_modifications` and `property_values` are maps, property → value, where a value is one of:

```json
{"type": "static_value", "value": "CLIENT"}
{"type": "parameter_value", "parameter": "amount"}
```

A bare value (`"contact_type": "CLIENT"`) is refused.

Operations are checked in order: a name introduced by `assign_to_parameter` can be used by every operation after it, which is how an action creates an object and links it in one go.

**Refused when saving**: a parameter naming an undeclared object type; a rule on an unknown parameter, on a value parameter, or on a property the object type does not have; an unknown operator; `in` / `not_in` without a list; an operation naming an unknown parameter, a value parameter where an object is needed, an unknown object type, an unknown link type, or a property the object type does not have; `assign_to_parameter` reusing a parameter's name; a scope that is not `<resource>:<action>`.

**Accepted, though it cannot be right** — the platform says nothing:

- unknown keys, dropped. The guide's `"parameter"` and `"properties"` in a `modify_object` are two of them: the operation is stored with an empty `property_modifications` and changes nothing;
- a value whose type does not fit the property (`"high"` into a `double`), or a parameter of another type;
- a rule comparing with no `value`, or with a value of another type;
- a `create_object` that does not set the primary key;
- an `assign_to_parameter` that no later operation uses;
- a link operation whose two ends are swapped with respect to the link type;
- a `modify_object` that changes the primary key.

`scripts/atlas_ontology.py check` reports the first list as errors and the second as errors (dropped keys) or warnings.

An action is declared on the model; it does not depend on the bindings. Take the constants of its rules and static values from the data (`PROSPECT`, not `prospect`): a rule comparing to a value the column never holds refuses every call.

## What the platform validates, and what it does not

**Validated when saving** (a `422`, or a `400` on an update):

- the shape of the document: lists and maps, the type of each value;
- identifiers: `api_name`s, property names, subtypes;
- `data_type` and `cardinality` values;
- `primary_key` is a declared property;
- a link's ends are declared object types;
- `foreign_key_property` is a property of the target, and is not set on a `MANY_TO_MANY` link;
- in an action: the references to parameters, object types, properties and link types, the operators, the shape of values (see [Action types](#action-types));
- on an update, that no stored link is left naming a removed object type.

**Not validated** — accepted, and broken or wrong when read:

- that `dataset_id` exists, is readable, is in the project, is tabular;
- that each property is a column of the dataset;
- that a property's `data_type` agrees with the column's;
- that the primary key is unique and never null;
- that a foreign key's values exist on the other side;
- unknown keys, which are dropped silently — at every level, operations of an action included;
- in an action: the type of a value against its property, the primary key of a created object, the direction of a link operation;
- that `api_name` is not already used by another ontology of the project.

`scripts/atlas_ontology.py check` covers both lists.

## Routes

Base URL `https://atlas.gwenlake.com/api/v1` (a tenant: `https://<tenant>.gwenlakeatlas.com/api/v1`), `Authorization: Bearer <key>`, JSON bodies.

| Request | Does |
| --- | --- |
| `GET /ontologies` (`?project_id=`) | summaries: `id`, `name`, `slug`, `api_name`, `version`, `is_standard`. The platform's twenty standard ontologies are always in the listing |
| `GET /ontologies/{id}` | the whole specification |
| `POST /ontologies` | creates one in `project_id`; answers the stored ontology with its `id` |
| `PATCH /ontologies/{id}` | updates. A collection given (`object_types`, `link_types`, `action_types`) **replaces the stored one wholesale**; a collection left out is kept. `name` regenerates the slug |
| `DELETE /ontologies/{id}` | deletes it; the datasets are untouched |
| `GET /ontologies/{id}/objects/{object_type}?limit=&offset=` | the instances of a bound type |
| `GET /ontologies/{id}/objects/{object_type}/{pk}` | one instance |
| `GET /ontologies/{id}/objects/{object_type}/{pk}/links/{link_type}` | the objects linked to an instance |
| `GET /ontologies/{id}/links/{link_type}?limit=` | the edges of a link, as source and target references |

There is no validate-only route and no version history: check before saving, and keep the JSON file under version control.

```bash
curl -X POST https://atlas.gwenlake.com/api/v1/ontologies \
  -H "Authorization: Bearer $GWENLAKE_API_KEY" -H "Content-Type: application/json" \
  -d @ontology.json          # the file must hold "project_id"
```

Rights: reading takes the Viewer role, creating and changing the Editor role. Reading instances also takes the right to read the bound dataset (`datasets:read`).

## Objects as JSON-LD

Instances are served as `application/ld+json`, read from the datasets with the same engine as SQL.

```json
{
  "@context": {"@vocab": "urn:ontology:sales#"},
  "@graph": [
    {"@type": "customer", "@id": "urn:ontology:sales/customer/C-00412",
     "customer_id": "C-00412", "name": "Emballages Dupont", "segment": "pro"}
  ]
}
```

- `@id` is `{base_uri}/{object_type}/{primary key}`; `@type` is the object type's `api_name`.
- One instance (`…/objects/customer/C-00412`) is the node itself, with the `@context`.
- Linked objects (`…/objects/customer/C-00412/links/customer_orders`) are a `@graph` of target nodes.
- The edges of a link (`…/links/customer_orders`) are `{"@type": "customer_orders", "source": {"@id": …}, "target": {"@id": …}}`.

## Status codes and messages

| Status | Message | Meaning |
| --- | --- | --- |
| `422` | `Field required` at `api_name` | the document has no `api_name` |
| `422` | `'x-y' is not a valid identifier (letters, digits and underscores only, must not start with a digit)` | an `api_name`, a property name or a subtype |
| `422` | `Input should be a valid list` at `object_types` | a map where a list is expected |
| `422` | `Input should be a valid dictionary` at `…properties` | a list where the properties map is expected |
| `422` | `Unknown data_type 'text'. Allowed: […]` | a data type outside the eleven |
| `422` | `object_type 'x': primary_key 'y' is not a declared property` | declare the property, or fix the name |
| `422` | `link_type 'x': unknown cardinality 'MANY'` | use one of the three |
| `422` | `link_type 'x' references unknown source_object_type 'y'` | a link end that is not a declared object type |
| `422` | `link_type 'x': foreign_key_property 'y' is not a property of target object_type 'z'` | the key is on the wrong side, or not declared |
| `422` | `a MANY_TO_MANY link cannot be backed by a foreign_key_property — use an edge dataset (dataset_id)` | |
| `422` | `action_type 'x': parameter 'y' references unknown object_type 'z'` | an object parameter of an undeclared type |
| `422` | `action_type 'x': rule references unknown parameter 'y'` / `rule parameter 'y' must be an ontology_object parameter` / `rule targets unknown property 'y' of object_type 'z'` | a rule compares a property of an object parameter |
| `422` | `Unknown rule operator 'neq'. Allowed: […]` | use `not_equals` |
| `422` | `rule operator 'in' requires a list \`value\`` | |
| `422` | `action_type 'x': operation references unknown parameter 'y'` / `operation parameter 'y' must be an ontology_object parameter` | |
| `422` | `action_type 'x': property_modification targets unknown property 'y' of object_type 'z'` (or `property_value`) | |
| `422` | `action_type 'x': create_object assigns to 'y', which is already a parameter` | choose a new name |
| `422` | `action_type 'x': link operation references unknown link_type 'y'` | |
| `422` | `'x' is not a valid scope; expected \`<resource>:<action>\`, lowercase` | |
| `422` | a long list naming `ModifyObjectOperation`, `CreateObjectOperation`, `LinkOperation`… with `Field required` | one operation matches none of the five shapes: the platform lists what each shape misses. Find the one of your `type` and add its missing key |
| `400` | `link_type 'x' references unknown target_object_type 'y'` on a `PATCH` | the update removed a type a stored link still names |
| `400` | `Error querying dataset … Referenced column "x" not found` on a read | a declared property is not a column of the bound dataset |
| `403` | `Missing scope 'datasets:read' on res.dataset.…` on a read | the bound dataset is not readable by the caller — or does not exist |
| `404` | on `/ontologies/{id}/…` | no such ontology, object type or object |

The platform reports its `422` errors together, each with the place (`object_types.0.properties.sku.data_type`): fix them all, then save again.

## Differences with the public guide

The guide at https://docs.gwenlake.com/atlas/guides/ontologies shows the three collections as maps keyed by name:

```json
"object_types": {"customer": {"primary_key": "customer_id", "properties": {…}}}
```

The platform refuses that form and takes lists, the name moving into `api_name`:

```json
"object_types": [{"api_name": "customer", "primary_key": "customer_id", "properties": {…}}]
```

The same holds for `link_types` and `action_types`.

The guide's action example differs in three more ways:

| The guide writes | The platform takes |
| --- | --- |
| `"operator": "neq"` | `"operator": "not_equals"` (refused otherwise) |
| `{"type": "modify_object", "parameter": "customer", "properties": {"segment": "flagged"}}` | `{"type": "modify_object", "target_object_parameter": "customer", "property_modifications": {"segment": {"type": "static_value", "value": "flagged"}}}` — the guide's two keys are dropped silently |
| `"scope": "datasets:write"` | any `<resource>:<action>`; name it after the object and the verb |

Everything else in the guide — the data types, the cardinalities, the binding rules, the JSON-LD routes — agrees with what the platform does.
