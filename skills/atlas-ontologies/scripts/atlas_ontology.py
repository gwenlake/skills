#!/usr/bin/env python3
"""atlas_ontology.py — build a Gwenlake Atlas ontology from the data of a project.

Standard library only.

    atlas_ontology.py profile <project> -o profile.json     # what the tables hold: columns, keys, values, joins
    atlas_ontology.py draft profile.json -o ontology.json   # a first ontology, mechanically, to be refined
    atlas_ontology.py check ontology.json                    # the format AND the data behind it; saves nothing
    atlas_ontology.py create ontology.json --project <project>
    atlas_ontology.py update ontology.json --ontology <id>   # replaces the three collections
    atlas_ontology.py verify <ontology id>                   # reads every bound type and link back
    atlas_ontology.py list [--project <project>] | get <ontology id> [-o file]

A project is named by its slug or its id (res.project.…).

Why `check` matters: when an ontology is saved, the platform validates its
format and its internal references, but NOT its bindings. A property that is
not a column, a primary key that is not unique, a dataset that does not exist
are all accepted, and only fail (or answer wrong objects) when read.

Credentials, in order: --api-key, --profile (or GWENLAKE_PROFILE),
GWENLAKE_API_KEY, the `default` profile of ~/.gwenlake/credentials. The
endpoint: --base-url, GWENLAKE_BASE_URL, the profile's, else
https://atlas.gwenlake.com/api/v1.

Exit status: 0 done, 1 the ontology has errors or the API refused, 2 usage or
configuration problem.
"""

import argparse
import configparser
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://atlas.gwenlake.com/api/v1"
TENANT_URL = "https://{tenant}.gwenlakeatlas.com/api/v1"
TENANT_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DATA_TYPES = ("string", "integer", "long", "short", "byte", "double", "float", "decimal", "boolean", "date", "timestamp")
CARDINALITIES = ("ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_MANY")
OPERATORS = ("equals", "not_equals", "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal",
             "in", "not_in", "is_null", "is_not_null")
OPERATION_KEYS = {
    "modify_object": ("type", "target_object_parameter", "property_modifications"),
    "create_object": ("type", "object_type_api_name", "property_values", "assign_to_parameter"),
    "delete_object": ("type", "target_object_parameter"),
    "add_link": ("type", "link_type_api_name", "source_object_parameter", "target_object_parameter"),
    "remove_link": ("type", "link_type_api_name", "source_object_parameter", "target_object_parameter"),
}
# data_type → the family two columns must share to be compared or joined
FAMILY = {
    "string": "text", "boolean": "bool", "date": "date", "timestamp": "time",
    "byte": "int", "short": "int", "integer": "int", "long": "int",
    "float": "real", "double": "real", "decimal": "real",
}


class Problem(Exception):
    """A configuration or usage problem: printed, exit status 2."""


# ---------------------------------------------------------------------------
# Credentials, endpoint, HTTP
# ---------------------------------------------------------------------------


def credentials_path():
    base = os.getenv("APPDATA") if os.name == "nt" else None
    return os.path.join(base or os.path.expanduser("~"), ".gwenlake", "credentials")


def read_profile(name):
    config = configparser.ConfigParser()
    try:
        config.read(credentials_path())
    except configparser.Error as e:
        raise Problem(f"Cannot read {credentials_path()}: {e}")
    return dict(config[name]) if config.has_section(name) else None


def normalise_base_url(url):
    url = url.strip()
    at_root = url.endswith("/") and "/" not in url.partition("://")[2].rstrip("/")
    url = url.rstrip("/")
    if url.lower() in ("atlas", "api"):
        return DEFAULT_BASE_URL
    if TENANT_NAME.fullmatch(url) and url.lower() != "localhost":
        return TENANT_URL.format(tenant=url.lower())
    if "://" not in url:
        url = "https://" + url
    scheme, _, rest = url.partition("://")
    host, _, path = rest.partition("/")
    if not path:
        return f"{scheme}://{host}" if at_root else f"{scheme}://{host}/v1"
    if path == "api":
        return f"{scheme}://{host}/api/v1"
    return url


def oauth_token(profile_name):
    try:
        from gwenlake import Credentials  # type: ignore
    except Exception:
        raise Problem(
            f"Profile `{profile_name}` holds an OAuth2 client: install the `gwenlake` library "
            "(pip install gwenlake) or pass an API key (--api-key, GWENLAKE_API_KEY)."
        )
    creds = Credentials.from_profile(profile_name)
    if creds is None or not creds.is_configured:
        raise Problem(f"Profile `{profile_name}` cannot produce a token.")
    return creds.get_token().access_token


def resolve_credentials(args):
    profile_name = args.profile or os.environ.get("GWENLAKE_PROFILE")
    profile = None
    token = args.api_key
    if not token and profile_name:
        profile = read_profile(profile_name)
        if profile is None:
            raise Problem(f"No profile `{profile_name}` in {credentials_path()}.")
    if not token and profile is None:
        token = os.environ.get("GWENLAKE_API_KEY")
    if not token and profile is None:
        profile_name = "default"
        profile = read_profile(profile_name)
    if not token and profile is not None:
        token = profile.get("token") or (oauth_token(profile_name) if profile.get("client_id") else None)
    if not token:
        raise Problem(
            "No API key found. Set GWENLAKE_API_KEY, pass --api-key or --profile, or create a profile with "
            "`gwenlake config set-profile default --token sk-...`."
        )
    endpoint = args.base_url or os.environ.get("GWENLAKE_BASE_URL")
    if not endpoint and profile is not None:
        endpoint = profile.get("base_url") or profile.get("endpoint") or profile.get("host")
        hostname = profile.get("hostname")
        if not endpoint and hostname and (TENANT_NAME.fullmatch(hostname.strip()) or not profile.get("client_id")):
            endpoint = hostname
    return token, normalise_base_url(endpoint or DEFAULT_BASE_URL)


class ApiError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body
        detail = body.get("detail", body) if isinstance(body, dict) else body
        super().__init__(detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False))


class Api:
    def __init__(self, token, base_url, timeout=300):
        self.token, self.base_url, self.timeout = token, base_url, timeout

    def call(self, method, path, *, params=None, body=None):
        """The parsed answer; raises ApiError on a 4xx/5xx."""
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = self.base_url + urllib.parse.quote(path, safe="/:@") + ("?" + query if query else "")
        headers = {"Authorization": "Bearer " + self.token, "User-Agent": "atlas-ontologies-skill"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except urllib.error.URLError as e:
            raise Problem(f"Cannot reach {self.base_url}: {e.reason}")
        except OSError as e:
            raise Problem(f"{method} {path} did not answer within {self.timeout}s ({e}): raise --timeout.")
        text = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text) if text.strip() else None
        except ValueError:
            parsed = text
        if status >= 400:
            raise ApiError(status, parsed)
        return parsed

    def sql(self, statement, limit=None):
        body = {"statement": statement, "format": "json"}
        if limit:
            body["limit"] = limit
        return (self.call("POST", "/sql/statements", body=body) or {}).get("data") or []


def rows(body):
    if isinstance(body, dict):
        return body.get("data") or []
    return body if isinstance(body, list) else []


def slug_of(resource):
    return resource.get("slug") or resource.get("alias") or ""


def find_project(api, ref):
    projects = rows(api.call("GET", "/filesystem/projects"))
    for p in projects:
        if ref in (p.get("id"), slug_of(p)):
            return p
    known = ", ".join(sorted(slug_of(p) for p in projects if slug_of(p))) or "none"
    raise Problem(f"No project `{ref}`. Projects you can reach: {known}.")


def explain(e):
    """An API refusal, one line per problem."""
    detail = e.body.get("detail", e.body) if isinstance(e.body, dict) else e.body
    lines = []
    if isinstance(detail, list):
        for item in detail:
            if isinstance(item, dict) and "msg" in item:
                where = ".".join(str(x) for x in item.get("loc", []) if x != "body")
                message = item["msg"].replace("Value error, ", "")
                lines.append(f"{where or '(document)'}: {message}")
            else:
                lines.append(str(item))
    else:
        lines.append(str(detail)[:1500])
    return f"HTTP {e.status}", lines


def fail(e):
    head, lines = explain(e)
    print(f"error: {head}", file=sys.stderr)
    for line in lines:
        print("  " + line, file=sys.stderr)
    if e.status == 403:
        print("hint: the credentials lack the scope, the resource is outside the API key's project, or the id "
              "does not exist (an unknown id answers 403).", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Reading the data
# ---------------------------------------------------------------------------


def q(name):
    """A quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def data_type_of(column_type):
    """A DuckDB column type → the ontology data_type, or None when a property cannot hold it."""
    t = column_type.upper()
    if t.startswith("DECIMAL") or t.startswith("NUMERIC"):
        return "decimal"
    if t.startswith("TIMESTAMP") or t == "DATETIME":
        return "timestamp"
    return {
        "VARCHAR": "string", "TEXT": "string", "STRING": "string", "UUID": "string",
        "BOOLEAN": "boolean", "DATE": "date",
        "TINYINT": "byte", "UTINYINT": "short", "SMALLINT": "short", "USMALLINT": "integer",
        "INTEGER": "integer", "INT": "integer", "UINTEGER": "long",
        "BIGINT": "long", "UBIGINT": "long", "HUGEINT": "long",
        "FLOAT": "float", "REAL": "float", "DOUBLE": "double",
    }.get(t)


def describe(api, handle):
    """[(column, DuckDB type)] of a dataset."""
    data = api.sql(f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM '{handle}')")
    return [(r["column_name"], r["column_type"]) for r in data]


def show(value, width=40):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= width else text[: width - 1] + "…"


def profile_dataset(api, handle, max_values, exact_rows):
    """Columns, row count, null and distinct counts, key candidates, values of the categorical columns."""
    columns = [{"name": n, "column_type": t, "data_type": data_type_of(t)} for n, t in describe(api, handle)]
    scalar = [c for c in columns if c["data_type"]]
    out = {"columns": columns, "rows": 0, "key_candidates": [], "notes": []}
    out["rows"] = n = int(api.sql(f"SELECT count(*) AS n FROM '{handle}'")[0]["n"])
    if not n or not scalar:
        if not n:
            out["notes"].append("The dataset holds no row: nothing can be learnt from its content.")
        return out

    exact = n <= exact_rows
    distinct = "count(DISTINCT {c})" if exact else "approx_count_distinct({c})"
    parts = []
    for i, c in enumerate(scalar):
        col = q(c["name"])
        parts.append(f"count({col}) AS nn_{i}, {distinct.format(c=col)} AS d_{i}")
        if FAMILY[c["data_type"]] in ("int", "real", "date", "time"):
            parts.append(f"min({col}) AS lo_{i}, max({col}) AS hi_{i}")
        elif c["data_type"] == "string":
            parts.append(f"max(length({col})) AS len_{i}")
    stats = api.sql(f"SELECT {', '.join(parts)} FROM '{handle}'")[0]
    for i, c in enumerate(scalar):
        c["non_null"] = int(stats[f"nn_{i}"])
        c["nulls"] = n - c["non_null"]
        c["distinct"] = int(stats[f"d_{i}"])
        if f"lo_{i}" in stats:
            c["min"], c["max"] = stats[f"lo_{i}"], stats[f"hi_{i}"]
        if stats.get(f"len_{i}") is not None:
            c["max_length"] = int(stats[f"len_{i}"])
    if not exact:
        out["notes"].append(f"More than {exact_rows} rows: distinct counts are approximate, except on key candidates.")
        likely = [c for c in scalar if c["nulls"] == 0 and c["distinct"] >= 0.9 * n
                  and FAMILY[c["data_type"]] in ("text", "int")]
        if likely:
            counts = api.sql("SELECT " + ", ".join(
                f"count(DISTINCT {q(c['name'])}) AS d_{i}" for i, c in enumerate(likely)) + f" FROM '{handle}'")[0]
            for i, c in enumerate(likely):
                c["distinct"], c["distinct_exact"] = int(counts[f"d_{i}"]), True

    for c in scalar:
        is_exact = exact or c.get("distinct_exact")
        if is_exact and c["nulls"] == 0 and c["distinct"] == n and FAMILY[c["data_type"]] in ("text", "int"):
            c["unique"] = True
            if c.get("max_length", 0) <= 200:  # a long text may be unique, it is not an identifier
                out["key_candidates"].append(c["name"])
        categorical = FAMILY[c["data_type"]] in ("text", "bool", "int") and 1 <= c["distinct"] <= max_values
        if categorical and not c.get("unique") and c["distinct"] * 2 <= n and c.get("max_length", 0) <= 200:
            col = q(c["name"])
            values = api.sql(
                f"SELECT {col} AS v, count(*) AS n FROM '{handle}' WHERE {col} IS NOT NULL "
                f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {max_values + 1}"
            )
            c["values"] = [{"value": r["v"], "rows": int(r["n"])} for r in values[:max_values]]
    order = [c["name"] for c in columns]
    out["key_candidates"].sort(key=lambda name: key_rank(name, order))
    sample = api.sql(f"SELECT * FROM '{handle}' LIMIT 3")
    out["sample"] = [{k: (show(v, 120) if isinstance(v, (str, list, dict)) else v) for k, v in r.items()} for r in sample]
    return out


def key_rank(name, order):
    """Identifier-looking names first, then the order of the columns: keys usually come first."""
    n = name.lower()
    looks = 0 if n == "id" else 1 if re.search(r"(^|_)(id|uuid|code|key|ref|number|no)$", n) else 2
    return (looks, order.index(name) if name in order else 0)


def singulars(slug):
    """Names a column may use to point at this dataset: the slug, its last word, their singulars."""
    words = {slug, slug.replace("-", "_"), re.split(r"[-_]", slug)[-1]}
    for w in list(words):
        if w.endswith("ies"):
            words.add(w[:-3] + "y")
        if w.endswith("es"):
            words.add(w[:-2])
        if w.endswith("s"):
            words.add(w[:-1])
    return {w.lower() for w in words if w}


def names_key(column, key, slug):
    """Does a column of another dataset look like a reference to `key` of dataset `slug`?"""
    c, k = column.lower(), key.lower()
    if c == k or c.endswith("_" + k) and k not in ("id", "code", "key", "name"):
        return True
    return any(c in (f"{s}_{k}", f"{s}{k}", f"{k}_{s}", s) for s in singulars(slug))


def find_references(api, datasets):
    """Columns that hold the key of another dataset, with the share of their values found there."""
    out = []
    for a in datasets:
        candidates = a.get("key_candidates", [])
        for key in [k for i, k in enumerate(candidates) if i == 0 or key_rank(k, [])[0] < 2]:
            key_col = next(c for c in a["columns"] if c["name"] == key)
            for b in datasets:
                if b is a or not b.get("rows"):
                    continue
                for c in b["columns"]:
                    if not c.get("data_type") or FAMILY[c["data_type"]] != FAMILY[key_col["data_type"]]:
                        continue
                    if not names_key(c["name"], key, a["slug"]) or not c.get("non_null"):
                        continue
                    try:
                        r = api.sql(
                            f"SELECT count(*) AS total, count(a.k) AS found FROM "
                            f"(SELECT DISTINCT {q(c['name'])} AS v FROM '{b['handle']}' WHERE {q(c['name'])} IS NOT NULL) b "
                            f"LEFT JOIN (SELECT {q(key)} AS k FROM '{a['handle']}') a ON b.v = a.k"
                        )[0]
                    except ApiError:
                        continue
                    total, found = int(r["total"]), int(r["found"])
                    if total and found / total >= 0.5:
                        out.append({
                            "one": a["slug"], "key": key, "many": b["slug"], "column": c["name"],
                            "values": total, "found": found, "coverage": round(found / total, 4),
                            "cardinality": "ONE_TO_ONE" if c.get("unique") else "ONE_TO_MANY",
                        })
    return out


def cmd_profile(api, args):
    project = find_project(api, args.project)
    wanted = set(args.datasets.split(",")) if args.datasets else None
    listing = rows(api.call("GET", "/datasets", params={"project_id": project["id"]}))
    datasets, skipped = [], []
    for d in sorted(listing, key=slug_of):
        slug = slug_of(d)
        if wanted and slug not in wanted:
            continue
        entry = {
            "slug": slug, "id": d["id"], "name": d.get("name"), "description": d.get("description"),
            "type": d.get("type"), "handle": f"{slug_of(project)}.{slug}",
        }
        if d.get("type") == "vector":
            skipped.append((slug, "a vector dataset: searched, not modelled"))
            continue
        print(f"profiling {entry['handle']} …", file=sys.stderr)
        try:
            entry.update(profile_dataset(api, entry["handle"], args.max_values, args.exact_rows))
        except ApiError as e:
            skipped.append((slug, f"cannot be read with SQL ({str(e)[:120]})"))
            continue
        datasets.append(entry)
    if wanted and wanted - {d["slug"] for d in datasets} - {s for s, _ in skipped}:
        raise Problem("No such dataset in the project: " + ", ".join(sorted(wanted - {d['slug'] for d in datasets})))
    print("looking for references between datasets …", file=sys.stderr)
    references = find_references(api, datasets)
    profile = {
        "project": {"id": project["id"], "slug": slug_of(project), "name": project.get("name"),
                    "description": project.get("description")},
        "datasets": datasets, "references": references,
        "skipped": [{"slug": s, "reason": r} for s, r in skipped],
    }
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False, default=str)
        print(f"wrote {args.output}", file=sys.stderr)
    print_profile(profile)


def print_profile(profile):
    p = profile["project"]
    print(f"# Project {p['slug']} — {p.get('name') or ''}")
    for d in profile["datasets"]:
        print(f"\n## {d['handle']}  ({d['type']}, {d.get('rows', 0)} rows)  {d['id']}")
        if d.get("description"):
            print("   " + show(d["description"], 220))
        keys = d.get("key_candidates") or []
        more = f" (+{len(keys) - 4} more unique columns, likely measures)" if len(keys) > 4 else ""
        print("   key candidates: " + (", ".join(keys[:4]) + more if keys
                                       else "NONE — no single column is unique and never null"))
        for note in d.get("notes", []):
            print("   note: " + note)
        for c in d["columns"]:
            if not c["data_type"]:
                print(f"   - {c['name']:30} {c['column_type']:12} not a scalar: cannot be a property")
                continue
            facts = []
            if c.get("unique"):
                facts.append("unique")
            if "distinct" in c:
                facts.append(f"{c['distinct']} distinct")
                if c["nulls"]:
                    facts.append(f"{c['nulls']} null" + (" (always)" if c["non_null"] == 0 else ""))
            if "min" in c and c["min"] is not None:
                facts.append(f"{show(c['min'], 22)} … {show(c['max'], 22)}")
            warn = "" if IDENT.match(c["name"]) else "  !! not a valid property name"
            print(f"   - {c['name']:30} {c['data_type']:9} {', '.join(facts)}{warn}")
            if c.get("values"):
                shown = ", ".join(f"{show(v['value'], 28)} ({v['rows']})" for v in c["values"][:20])
                more = f", … {len(c['values']) - 20} more" if len(c["values"]) > 20 else ""
                print(f"       values: {shown}{more}")
    if profile["references"]:
        print("\n## References found between datasets")
        for r in profile["references"]:
            print(f"   {r['many']}.{r['column']} -> {r['one']}.{r['key']}  {r['cardinality']}  "
                  f"{r['found']}/{r['values']} values found ({r['coverage']:.0%})")
    for s in profile["skipped"]:
        print(f"\nskipped {s['slug']}: {s['reason']}")


# ---------------------------------------------------------------------------
# A first draft
# ---------------------------------------------------------------------------


def identifier(text):
    out = re.sub(r"[^A-Za-z0-9_]+", "_", text.strip()).strip("_").lower()
    return ("_" + out) if out and out[0].isdigit() else out


def singular(word):
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes"):
        return word[:-2]
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def cmd_draft(api, args):
    with open(args.profile_file, encoding="utf-8") as f:
        profile = json.load(f)
    project = profile["project"]
    api_name = identifier(args.api_name or project["slug"])
    types, notes, by_slug = [], [], {}
    for d in profile["datasets"]:
        if not d.get("key_candidates"):
            notes.append(f"{d['slug']}: no single-column key — left out. Give it a key upstream, or model it by hand.")
            continue
        name = identifier(singular(d["slug"]))
        properties = {}
        for c in d["columns"]:
            if not c.get("data_type"):
                continue
            if not IDENT.match(c["name"]):
                notes.append(f"{d['slug']}.{c['name']}: not a valid property name — left out.")
                continue
            if c.get("non_null") == 0:
                notes.append(f"{d['slug']}.{c['name']}: always null — left out.")
                continue
            prop = {"data_type": c["data_type"]}
            if c.get("nulls") == 0:
                prop["required"] = True
            if c.get("values"):
                shown = ", ".join(show(v["value"], 40) for v in c["values"][:args.max_values])
                more = " …" if len(c["values"]) > args.max_values else ""
                prop["description"] = f"Values: {shown}{more}"
            properties[c["name"]] = prop
        key = d["key_candidates"][0]
        entry = {
            "api_name": name, "display_name": d.get("name") or name,
            "description": (d.get("description") or "").strip() or None,
            "primary_key": key, "properties": properties, "subtypes": [], "dataset_id": d["id"],
        }
        types.append({k: v for k, v in entry.items() if v is not None})
        by_slug[d["slug"]] = entry
    links, seen = [], set()
    for r in profile.get("references", []):
        one, many = by_slug.get(r["one"]), by_slug.get(r["many"])
        if not one or not many or r["key"] != one["primary_key"] or r["column"] not in many["properties"]:
            continue
        name = f"{one['api_name']}_{many['api_name']}"
        if name in seen:
            name = f"{name}_by_{identifier(r['column'])}"
        seen.add(name)
        links.append({
            "api_name": name, "source_object_type": one["api_name"], "target_object_type": many["api_name"],
            "cardinality": r["cardinality"], "foreign_key_property": r["column"],
            "description": f"{many['api_name']}.{r['column']} holds the {r['key']} of a {one['api_name']} "
                           f"({r['coverage']:.0%} of its values are found there).",
        })
    ontology = {
        "name": args.name or project.get("name") or api_name, "api_name": api_name, "version": "1",
        "description": project.get("description"), "object_types": types, "link_types": links, "action_types": [],
    }
    ontology = {k: v for k, v in ontology.items() if v is not None}
    text = json.dumps(ontology, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"wrote {args.output}: {len(types)} object types, {len(links)} link types", file=sys.stderr)
    else:
        print(text)
    for note in notes:
        print("note: " + note, file=sys.stderr)
    print("This is a mechanical draft. Rename what reads badly, write the descriptions, decide the subtypes, "
          "then run `check`.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


def load_ontology(path):
    try:
        with (sys.stdin if path == "-" else open(path, encoding="utf-8")) as f:
            doc = json.load(f)
    except OSError as e:
        raise Problem(f"Cannot read {path}: {e.strerror}")
    except ValueError as e:
        raise Problem(f"{path} is not valid JSON: {e}")
    if not isinstance(doc, dict):
        raise Problem("The ontology must be a JSON object.")
    return doc


def ends(value):
    """A link end: a name, a list of alternatives, or None (untyped)."""
    return [] if value is None else value if isinstance(value, list) else [value]


KEYS = {
    "ontology": ("name", "description", "project_id", "api_name", "version", "base_uri",
                 "object_types", "link_types", "action_types"),
    "object type": ("api_name", "display_name", "description", "primary_key", "properties", "subtypes", "dataset_id"),
    "property": ("data_type", "display_name", "description", "required"),
    "link type": ("api_name", "display_name", "description", "source_object_type", "target_object_type",
                  "cardinality", "inverse_of", "foreign_key_property", "dataset_id", "source_key", "target_key"),
    "action type": ("api_name", "display_name", "description", "parameters", "rules", "scope", "operations"),
    "parameter": ("data_type", "display_name", "description", "required"),
    "rule": ("parameter", "property", "operator", "value", "message"),
}
# what a GET returns beside the definition; harmless in a file read back from the platform
READ_ONLY = ("object", "id", "slug", "alias", "storage_path", "picture", "organization_id", "parent_id",
             "created_by", "created_at", "updated_at", "is_standard")


def unknown_keys(kind, value, path, out, extra=()):
    """The platform drops a key it does not know without a word: a typo loses the setting."""
    if isinstance(value, dict):
        for key in value:
            if key not in KEYS[kind] and key not in extra:
                out.append(("error", f"{path}.{key}" if path else key,
                            f"is not a key of {'an' if kind[0] == 'o' else 'a'} {kind}: the platform would drop it "
                            f"silently. Keys: {', '.join(KEYS[kind])}."))


def check_format(doc):
    """The rules the platform enforces when it saves, as (level, path, message)."""
    out = []
    err = lambda path, message: out.append(("error", path, message))  # noqa: E731
    unknown_keys("ontology", doc, "", out, extra=READ_ONLY)
    if not isinstance(doc.get("api_name"), str) or not IDENT.match(doc.get("api_name") or ""):
        err("api_name", "is required: letters, digits and underscores, not starting with a digit.")
    for key in ("object_types", "link_types", "action_types"):
        value = doc.get(key, [])
        if isinstance(value, dict):
            err(key, "must be a LIST of objects, each with its `api_name` — not a map keyed by name "
                     "(the form shown in the public guide is refused).")
            doc[key] = []
        elif not isinstance(value, list):
            err(key, "must be a list.")
            doc[key] = []
    types = {}
    for i, t in enumerate(doc.get("object_types", [])):
        path = f"object_types[{i}]"
        name = t.get("api_name") if isinstance(t, dict) else None
        if not isinstance(name, str) or not IDENT.match(name):
            err(path + ".api_name", "is required and must be an identifier.")
            continue
        path = f"object_types.{name}"
        unknown_keys("object type", t, path, out)
        if name in types:
            err(path, "is declared twice.")
        types[name] = t
        props = t.get("properties") or {}
        if not isinstance(props, dict):
            err(path + ".properties", "must be a map: property name → {data_type, required, description}.")
            props = {}
        for prop, spec in props.items():
            if not IDENT.match(prop):
                err(f"{path}.properties.{prop}", "is not a valid identifier (letters, digits, underscores).")
            unknown_keys("property", spec, f"{path}.properties.{prop}", out)
            if not isinstance(spec, dict) or spec.get("data_type") not in DATA_TYPES:
                got = spec.get("data_type") if isinstance(spec, dict) else spec
                err(f"{path}.properties.{prop}.data_type", f"`{got}` is not a data type. Allowed: {', '.join(DATA_TYPES)}.")
        pk = t.get("primary_key")
        if pk is not None and pk not in props:
            err(path + ".primary_key", f"`{pk}` is not a declared property.")
        for sub in t.get("subtypes") or []:
            if not isinstance(sub, str) or not IDENT.match(sub):
                err(path + ".subtypes", f"`{sub}` is not a valid identifier: write it in snake_case (`class_a`) "
                                        "and keep the value as the data spells it in a description.")
        if t.get("dataset_id") and not pk:
            err(path + ".primary_key", "is required on an object type bound to a dataset: without it no object can be addressed.")
        if not t.get("description"):
            out.append(("warning", path + ".description", "is empty: an agent chooses what to query from descriptions."))
    seen = set()
    for i, link in enumerate(doc.get("link_types", [])):
        name = link.get("api_name") if isinstance(link, dict) else None
        if not isinstance(name, str) or not IDENT.match(name):
            err(f"link_types[{i}].api_name", "is required and must be an identifier.")
            continue
        path = f"link_types.{name}"
        unknown_keys("link type", link, path, out)
        if name in seen:
            err(path, "is declared twice.")
        seen.add(name)
        for end in ("source_object_type", "target_object_type"):
            for ref in ends(link.get(end)):
                if ref not in types:
                    err(f"{path}.{end}", f"`{ref}` is not a declared object type.")
        card = link.get("cardinality")
        if card not in CARDINALITIES:
            err(path + ".cardinality", f"`{card}` is not a cardinality. Allowed: {', '.join(CARDINALITIES)}.")
        fk = link.get("foreign_key_property")
        if fk:
            if card == "MANY_TO_MANY":
                err(path + ".foreign_key_property", "a MANY_TO_MANY link cannot be backed by a foreign key: use an edge dataset (`dataset_id`).")
            targets = ends(link.get("target_object_type"))
            if len(targets) != 1 or len(ends(link.get("source_object_type"))) != 1:
                err(path + ".foreign_key_property", "needs exactly one source and one target object type.")
            elif targets[0] in types and fk not in (types[targets[0]].get("properties") or {}):
                err(path + ".foreign_key_property",
                    f"`{fk}` is not a property of the TARGET object type `{targets[0]}`. The foreign key lives on the "
                    "target (the \"many\" side) and holds the primary key of the source: turn the link round if needed.")
        inverse = link.get("inverse_of")
        if inverse and inverse not in {x.get("api_name") for x in doc["link_types"] if isinstance(x, dict)}:
            err(path + ".inverse_of", f"`{inverse}` is not a declared link type.")
    links = {x.get("api_name"): x for x in doc.get("link_types", []) if isinstance(x, dict)}
    seen = set()
    for i, action in enumerate(doc.get("action_types", [])):
        name = action.get("api_name") if isinstance(action, dict) else None
        if not isinstance(name, str) or not IDENT.match(name):
            err(f"action_types[{i}].api_name", "is required and must be an identifier.")
            continue
        path = f"action_types.{name}"
        unknown_keys("action type", action, path, out)
        if name in seen:
            err(path, "is declared twice.")
        seen.add(name)
        check_action(action, path, types, links, out)
    return out, types


def fits(value, data_type):
    """Is a literal value of the kind a property of this data_type holds?"""
    family = FAMILY.get(data_type)
    if value is None or family is None:
        return True
    if family == "bool":
        return isinstance(value, bool)
    if family == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if family == "real":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


def check_action(action, path, types, links, out):
    """An action type: what the platform refuses, and what it accepts but cannot mean."""
    err = lambda where, message: out.append(("error", where, message))  # noqa: E731
    warn = lambda where, message: out.append(("warning", where, message))  # noqa: E731
    params = action.get("parameters") or {}
    if not isinstance(params, dict):
        err(path + ".parameters", "must be a map: parameter name → {data_type, required, description}.")
        params = {}
    kinds = {}  # parameter → ("object", object type) or ("value", data type)
    for pname, spec in params.items():
        where = f"{path}.parameters.{pname}"
        if not IDENT.match(pname):
            err(where, "is not a valid identifier.")
        unknown_keys("parameter", spec, where, out)
        dt = spec.get("data_type") if isinstance(spec, dict) else None
        if not isinstance(dt, dict) or "type" not in dt:
            err(where + ".data_type", 'must be an object: {"type": "string"} for a value, or {"type": "ontology_object", '
                                      '"object_type_api_name": "<object type>"} for an object. A bare "string" is refused.')
        elif dt["type"] == "ontology_object":
            ref = dt.get("object_type_api_name")
            if ref not in types:
                err(where + ".data_type.object_type_api_name", f"`{ref}` is not a declared object type.")
            kinds[pname] = ("object", ref)
        elif dt["type"] in DATA_TYPES:
            kinds[pname] = ("value", dt["type"])
        else:
            err(where + ".data_type.type", f"`{dt['type']}` is not a parameter type. Allowed: ontology_object, {', '.join(DATA_TYPES)}.")

    def object_param(ref, where):
        """The object type behind a parameter that must hold an object."""
        if ref not in kinds:
            err(where, f"`{ref}` is not a parameter of this action" + (" (nor an object created earlier in it)." if ref else "."))
            return None
        if kinds[ref][0] != "object":
            err(where, f"parameter `{ref}` must be an ontology_object parameter.")
            return None
        return kinds[ref][1]

    def props_of(type_name):
        return (types.get(type_name) or {}).get("properties") or {}

    def check_values(values, type_name, where, label):
        if not isinstance(values, dict):
            err(where, "must be a map: property → {\"type\": \"static_value\", \"value\": …} or "
                       "{\"type\": \"parameter_value\", \"parameter\": \"<parameter>\"}.")
            return
        props = props_of(type_name)
        for prop, value in values.items():
            here = f"{where}.{prop}"
            if type_name in types and prop not in props:
                err(here, f"{label} targets unknown property `{prop}` of object type `{type_name}`.")
                continue
            declared = (props.get(prop) or {}).get("data_type")
            if not isinstance(value, dict) or value.get("type") not in ("static_value", "parameter_value"):
                err(here, 'must be {"type": "static_value", "value": …} or {"type": "parameter_value", "parameter": '
                          '"<parameter>"} — a bare value is refused.')
            elif value["type"] == "static_value":
                if "value" not in value:
                    err(here, "a static_value needs a `value`.")
                elif not fits(value["value"], declared):
                    warn(here, f"sets a `{declared}` property to {json.dumps(value['value'])}.")
            else:
                ref = value.get("parameter")
                if ref not in kinds:
                    err(here, f"references unknown parameter `{ref}`.")
                elif kinds[ref][0] == "object":
                    warn(here, f"takes its value from `{ref}`, an object parameter: a property holds a value, not an object.")
                elif declared in FAMILY and FAMILY[kinds[ref][1]] != FAMILY[declared]:
                    warn(here, f"sets a `{declared}` property from `{ref}`, a `{kinds[ref][1]}` parameter.")

    rules = action.get("rules") or []
    if not isinstance(rules, list):
        err(path + ".rules", "must be a list.")
        rules = []
    for j, rule in enumerate(rules):
        where = f"{path}.rules[{j}]"
        if not isinstance(rule, dict):
            err(where, "must be an object: {parameter, property, operator, value, message}.")
            continue
        unknown_keys("rule", rule, where, out)
        target = object_param(rule.get("parameter"), where + ".parameter")
        prop = rule.get("property")
        if target in types and prop not in props_of(target):
            err(where + ".property", f"`{prop}` is not a property of object type `{target}`.")
        op = rule.get("operator")
        if op not in OPERATORS:
            err(where + ".operator", f"`{op}` is not an operator. Allowed: {', '.join(OPERATORS)}.")
        elif op in ("in", "not_in"):
            if not isinstance(rule.get("value"), list):
                err(where + ".value", f"operator `{op}` requires a list.")
        elif op in ("is_null", "is_not_null"):
            if rule.get("value") is not None:
                warn(where + ".value", f"operator `{op}` takes no value.")
        elif rule.get("value") is None:
            warn(where + ".value", f"operator `{op}` compares to nothing: give a `value`.")
        elif target in types and prop in props_of(target) and not fits(rule["value"], props_of(target)[prop].get("data_type")):
            warn(where + ".value", f"compares `{prop}` ({props_of(target)[prop].get('data_type')}) to {json.dumps(rule['value'])}.")
        if not rule.get("message"):
            warn(where + ".message", "is empty: the message is what the caller reads when the rule refuses the action.")

    scope = action.get("scope")
    if scope is not None and not (isinstance(scope, str) and re.fullmatch(r"[a-z][a-z0-9_]*:[a-z][a-z0-9_]*", scope)):
        err(path + ".scope", f"`{scope}` is not a scope: write `<resource>:<action>`, lowercase, e.g. `invoices:approve`.")

    operations = action.get("operations") or []
    if not isinstance(operations, list):
        err(path + ".operations", "must be a list.")
        operations = []
    if not operations:
        warn(path + ".operations", "is empty: the action does nothing.")
    for j, op in enumerate(operations):
        where = f"{path}.operations[{j}]"
        kind = op.get("type") if isinstance(op, dict) else None
        if kind not in OPERATION_KEYS:
            err(where + ".type", f"must be one of: {', '.join(OPERATION_KEYS)}.")
            continue
        for key in op:
            if key not in OPERATION_KEYS[kind]:
                err(f"{where}.{key}", f"is not a key of a {kind} operation: the platform would drop it silently. "
                                      f"Keys: {', '.join(OPERATION_KEYS[kind])}.")
        if kind == "modify_object":
            target = object_param(op.get("target_object_parameter"), where + ".target_object_parameter")
            mods = op.get("property_modifications")
            if not mods:
                warn(where + ".property_modifications", "is empty: the operation changes nothing.")
            elif target:
                check_values(mods, target, where + ".property_modifications", "property_modification")
                if isinstance(mods, dict) and types.get(target, {}).get("primary_key") in mods:
                    warn(where + ".property_modifications", "changes the primary key: the object's identity.")
        elif kind == "create_object":
            target = op.get("object_type_api_name")
            if target not in types:
                err(where + ".object_type_api_name", f"`{target}` is not a declared object type.")
                continue
            values = op.get("property_values") or {}
            check_values(values, target, where + ".property_values", "property_value")
            pk = types[target].get("primary_key")
            if pk and isinstance(values, dict) and pk not in values:
                warn(where + ".property_values", f"does not set the primary key `{pk}`: the created object has no identity.")
            assign = op.get("assign_to_parameter")
            if assign:
                if assign in params:
                    err(where + ".assign_to_parameter", f"`{assign}` is already a parameter: give the created object a new name.")
                elif not IDENT.match(str(assign)):
                    err(where + ".assign_to_parameter", "is not a valid identifier.")
                else:
                    kinds[assign] = ("object", target)
        elif kind == "delete_object":
            object_param(op.get("target_object_parameter"), where + ".target_object_parameter")
        else:
            link = links.get(op.get("link_type_api_name"))
            if link is None:
                err(where + ".link_type_api_name", f"`{op.get('link_type_api_name')}` is not a declared link type.")
            source = object_param(op.get("source_object_parameter"), where + ".source_object_parameter")
            target = object_param(op.get("target_object_parameter"), where + ".target_object_parameter")
            if link and source and target:
                if ends(link.get("source_object_type")) and source not in ends(link.get("source_object_type")):
                    warn(where + ".source_object_parameter",
                         f"is a `{source}` but link `{link['api_name']}` goes from `{link.get('source_object_type')}`: the ends look swapped.")
                if ends(link.get("target_object_type")) and target not in ends(link.get("target_object_type")):
                    warn(where + ".target_object_parameter",
                         f"is a `{target}` but link `{link['api_name']}` goes to `{link.get('target_object_type')}`.")


def check_data(api, doc, types):
    """What the platform does not check at save time: the datasets behind the bindings."""
    out = []
    err = lambda path, message: out.append(("error", path, message))  # noqa: E731
    warn = lambda path, message: out.append(("warning", path, message))  # noqa: E731
    projects = {p["id"]: slug_of(p) for p in rows(api.call("GET", "/filesystem/projects"))}
    bound = {}  # object type → (handle, {column: DuckDB type})
    for name, t in types.items():
        did = t.get("dataset_id")
        if not did:
            continue
        path = f"object_types.{name}"
        try:
            dataset = api.call("GET", f"/datasets/{did}")
        except ApiError as e:
            err(path + ".dataset_id", f"`{did}` cannot be read ({str(e)[:100]}): a wrong id, or a dataset of another project.")
            continue
        if dataset.get("type") == "vector":
            err(path + ".dataset_id", "is a vector dataset: an object type is bound to a table.")
            continue
        handle = f"{projects.get(dataset.get('project_id'), '?')}.{slug_of(dataset)}"
        try:
            columns = dict(describe(api, handle))
        except ApiError as e:
            err(path + ".dataset_id", f"{handle} cannot be queried ({str(e)[:120]}).")
            continue
        bound[name] = (handle, columns)
        props = t.get("properties") or {}
        for prop, spec in props.items():
            if prop not in columns:
                close = [c for c in columns if c.lower() == prop.lower()]
                hint = f" Did you mean `{close[0]}`? Names are case-sensitive." if close else ""
                err(f"{path}.properties.{prop}", f"is not a column of {handle}: reading this object type would fail.{hint}")
                continue
            actual = data_type_of(columns[prop])
            declared = spec.get("data_type") if isinstance(spec, dict) else None
            if actual is None:
                err(f"{path}.properties.{prop}", f"the column is a {columns[prop]}, which a property cannot hold.")
            elif declared in FAMILY and FAMILY[actual] != FAMILY[declared]:
                warn(f"{path}.properties.{prop}.data_type", f"is `{declared}` but the column is a {columns[prop]} (`{actual}`).")
        pk = t.get("primary_key")
        if pk and pk in columns:
            r = api.sql(f"SELECT count(*) AS n, count({q(pk)}) AS nn, count(DISTINCT {q(pk)}) AS d FROM '{handle}'")[0]
            n, nn, d = int(r["n"]), int(r["nn"]), int(r["d"])
            if nn < n:
                err(path + ".primary_key", f"`{pk}` is null on {n - nn} of {n} rows of {handle}: those objects have no identity.")
            if d < nn:
                err(path + ".primary_key",
                    f"`{pk}` is not unique in {handle}: {nn} rows, {d} distinct values. Several objects would share one "
                    "@id. Pick a unique column, or bind a dataset with one row per object.")
        missing = [c for c in columns if c not in props and data_type_of(columns[c])]
        if missing:
            out.append(("note", path, f"{len(missing)} column(s) of {handle} are not declared and will never be read: "
                        + ", ".join(missing[:12]) + (" …" if len(missing) > 12 else "")))
    for link in doc.get("link_types", []):
        name, fk = link.get("api_name"), link.get("foreign_key_property")
        sources, targets = ends(link.get("source_object_type")), ends(link.get("target_object_type"))
        path = f"link_types.{name}"
        if link.get("dataset_id"):
            try:
                dataset = api.call("GET", f"/datasets/{link['dataset_id']}")
                handle = f"{projects.get(dataset.get('project_id'), '?')}.{slug_of(dataset)}"
                columns = dict(describe(api, handle))
                for key in (link.get("source_key") or "source_id", link.get("target_key") or "target_id"):
                    if key not in columns:
                        err(path, f"the edge dataset {handle} has no column `{key}` (set `source_key` / `target_key`).")
            except ApiError as e:
                err(path + ".dataset_id", f"the edge dataset cannot be read ({str(e)[:100]}).")
            continue
        if not fk or len(sources) != 1 or len(targets) != 1:
            if len(sources) == 1 and len(targets) == 1 and sources[0] in bound and targets[0] in bound:
                warn(path, "both ends are bound to data but the link is backed by nothing (no `foreign_key_property`, "
                           "no edge `dataset_id`): it describes the domain but cannot be traversed.")
            continue
        source, target = sources[0], targets[0]
        if source not in bound or target not in bound:
            continue
        spk = types[source].get("primary_key")
        (sh, sc), (th, tc) = bound[source], bound[target]
        if not spk or spk not in sc or fk not in tc:
            continue
        a, b = data_type_of(sc[spk]), data_type_of(tc[fk])
        if a and b and FAMILY[a] != FAMILY[b]:
            err(path, f"{target}.{fk} is a {tc[fk]} and {source}.{spk} a {sc[spk]}: they can never be equal.")
            continue
        r = api.sql(
            f"SELECT count(*) AS total, count(a.k) AS found FROM "
            f"(SELECT DISTINCT {q(fk)} AS v FROM '{th}' WHERE {q(fk)} IS NOT NULL) b "
            f"LEFT JOIN (SELECT DISTINCT {q(spk)} AS k FROM '{sh}') a ON b.v = a.k"
        )[0]
        total, found = int(r["total"]), int(r["found"])
        if total and not found:
            err(path, f"no value of {target}.{fk} is a {source}.{spk}: the link joins nothing. Wrong column, or the link is the wrong way round.")
        elif found < total:
            warn(path, f"{total - found} of {total} distinct values of {target}.{fk} match no {source}.{spk} ({found / total:.0%} do).")
        if link.get("cardinality") == "ONE_TO_ONE":
            r = api.sql(f"SELECT count({q(fk)}) AS nn, count(DISTINCT {q(fk)}) AS d FROM '{th}'")[0]
            if int(r["d"]) < int(r["nn"]):
                err(path + ".cardinality", f"is ONE_TO_ONE but {target}.{fk} repeats: it is ONE_TO_MANY.")
    return out


def run_check(api, doc, offline=False):
    issues, types = check_format(doc)
    if not offline and not any(level == "error" for level, _, _ in issues):
        issues += check_data(api, doc, types)
    for level in ("error", "warning", "note"):
        for lv, path, message in issues:
            if lv == level:
                print(f"  {level} {path}: {message}")
    errors = sum(1 for level, _, _ in issues if level == "error")
    warnings = sum(1 for level, _, _ in issues if level == "warning")
    bound = sum(1 for t in types.values() if t.get("dataset_id"))
    print(f"{len(types)} object types ({bound} bound to a dataset), {len(doc.get('link_types', []))} link types, "
          f"{len(doc.get('action_types', []))} action types — {errors} error(s), {warnings} warning(s)"
          + (" [format only: the data was not checked]" if offline else ""))
    return errors == 0


def cmd_check(api, args):
    doc = load_ontology(args.file)
    ok = run_check(api, doc, args.offline)
    print("OK" if ok else "INVALID — fix the errors before saving")
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------------------
# Saving and reading back
# ---------------------------------------------------------------------------

FIELDS = ("name", "description", "api_name", "version", "base_uri", "object_types", "link_types", "action_types")


def cmd_create(api, args):
    doc = load_ontology(args.file)
    project = find_project(api, args.project)
    if not run_check(api, doc) and not args.force:
        print("NOT CREATED — fix the errors (or pass --force to save it as it is).")
        sys.exit(1)
    existing = [o for o in rows(api.call("GET", "/ontologies", params={"project_id": project["id"]}))
                if not o.get("is_standard") and o.get("api_name") == doc.get("api_name")]
    if existing and not args.force:
        print(f"NOT CREATED — the project already holds an ontology with api_name `{doc['api_name']}`: "
              f"{existing[0]['id']}. Update it (`update --ontology`), or pass --force for a second one.")
        sys.exit(1)
    body = {k: doc[k] for k in FIELDS if k in doc}
    body["project_id"] = project["id"]
    body.setdefault("name", doc.get("api_name"))
    try:
        saved = api.call("POST", "/ontologies", body=body)
    except ApiError as e:
        fail(e)
    print(f"created: {saved['id']}  (api_name {saved.get('api_name')}, slug {slug_of(saved)})")
    print(f"next: verify {saved['id']}")


def cmd_update(api, args):
    doc = load_ontology(args.file)
    if not run_check(api, doc) and not args.force:
        print("NOT SAVED — fix the errors (or pass --force).")
        sys.exit(1)
    body = {k: doc[k] for k in FIELDS if k in doc and k != "api_name"}
    if not args.rename:
        body.pop("name", None)  # a PATCH of the name regenerates the slug
    try:
        saved = api.call("PATCH", f"/ontologies/{args.ontology}", body=body)
    except ApiError as e:
        fail(e)
    print(f"saved: {saved['id']}  (version {saved.get('version')}, {len(saved.get('object_types') or [])} object types, "
          f"{len(saved.get('link_types') or [])} link types)")


def cmd_verify(api, args):
    try:
        doc = api.call("GET", f"/ontologies/{args.ontology}")
    except ApiError as e:
        fail(e)
    failures = 0
    for t in doc.get("object_types") or []:
        if not t.get("dataset_id"):
            continue
        try:
            graph = api.call("GET", f"/ontologies/{args.ontology}/objects/{t['api_name']}", params={"limit": 3}).get("@graph") or []
            first = graph[0] if graph else {}
            shown = ", ".join(f"{k}={show(v, 24)}" for k, v in first.items() if not k.startswith("@"))[:150]
            print(f"  ok   object {t['api_name']}: {'no object' if not graph else first.get('@id')}  {shown}")
        except ApiError as e:
            failures += 1
            print(f"  FAIL object {t['api_name']}: {str(e).splitlines()[0][:220]}")
    for link in doc.get("link_types") or []:
        if not (link.get("foreign_key_property") or link.get("dataset_id")):
            continue
        try:
            graph = api.call("GET", f"/ontologies/{args.ontology}/links/{link['api_name']}", params={"limit": 3}).get("@graph") or []
            edge = graph[0] if graph else {}
            print(f"  ok   link {link['api_name']}: " + ("no edge" if not graph else
                  f"{edge.get('source', {}).get('@id')} -> {edge.get('target', {}).get('@id')}"))
        except ApiError as e:
            failures += 1
            print(f"  FAIL link {link['api_name']}: {str(e).splitlines()[0][:220]}")
    print("VERIFIED: every bound object type and link reads" if not failures else f"{failures} read(s) failed")
    sys.exit(1 if failures else 0)


def cmd_list(api, args):
    params = {"project_id": find_project(api, args.project)["id"]} if args.project else {}
    try:
        data = rows(api.call("GET", "/ontologies", params=params))
    except ApiError as e:
        fail(e)
    for o in data:
        if o.get("is_standard") and not args.standard:
            continue
        kind = "standard" if o.get("is_standard") else "project"
        print(f"{o.get('id', ''):48} {o.get('api_name', ''):24} {kind:9} {o.get('name', '')}")
    if not args.standard:
        print("# the platform's standard ontologies are hidden: --standard lists them", file=sys.stderr)


def cmd_get(api, args):
    try:
        doc = api.call("GET", f"/ontologies/{args.ontology}")
    except ApiError as e:
        fail(e)
    if args.editable:
        doc = {k: doc[k] for k in FIELDS if doc.get(k) is not None}
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(text)


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="a profile of ~/.gwenlake/credentials")
    common.add_argument("--api-key", help="an API key (prefer GWENLAKE_API_KEY or a profile)")
    common.add_argument("--base-url", help="the endpoint: a tenant's name, a host or a URL")
    common.add_argument("--timeout", type=int, default=300, help="seconds to wait for an answer (default 300)")

    parser = argparse.ArgumentParser(description="Build a Gwenlake Atlas ontology from the data of a project.", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, fn, help, needs_api=True):
        p = sub.add_parser(name, help=help, parents=[common])
        p.set_defaults(fn=fn, needs_api=needs_api)
        return p

    p = command("profile", cmd_profile, "what the tables of a project hold")
    p.add_argument("project")
    p.add_argument("--datasets", help="only these dataset slugs, comma-separated")
    p.add_argument("--max-values", type=int, default=50, help="list the values of columns with at most this many (default 50)")
    p.add_argument("--exact-rows", type=int, default=2_000_000, help="above this many rows, distinct counts are approximate")
    p.add_argument("-o", "--output", help="write the profile as JSON (the input of `draft`)")
    p = command("draft", cmd_draft, "a first ontology from a profile, to be refined", needs_api=False)
    p.add_argument("profile_file")
    p.add_argument("--api-name", help="the ontology's identifier (default: the project's slug)")
    p.add_argument("--name", help="the ontology's displayed name")
    p.add_argument("--max-values", type=int, default=25, help="values quoted in a property's description")
    p.add_argument("-o", "--output")
    p = command("check", cmd_check, "check the format and the data behind it; saves nothing")
    p.add_argument("file", help="the ontology, as JSON (- for stdin)")
    p.add_argument("--offline", action="store_true", help="the format only, without reading the datasets")
    p = command("create", cmd_create, "check, then create the ontology in a project")
    p.add_argument("file")
    p.add_argument("--project", required=True)
    p.add_argument("--force", action="store_true", help="save despite errors or an existing api_name")
    p = command("update", cmd_update, "check, then replace an ontology's collections")
    p.add_argument("file")
    p.add_argument("--ontology", required=True, help="the ontology id (res.ontology.…)")
    p.add_argument("--rename", action="store_true", help="also send `name` (this regenerates the slug)")
    p.add_argument("--force", action="store_true")
    p = command("verify", cmd_verify, "read every bound object type and link of a saved ontology")
    p.add_argument("ontology")
    p = command("list", cmd_list, "the ontologies")
    p.add_argument("--project")
    p.add_argument("--standard", action="store_true", help="include the platform's standard ontologies")
    p = command("get", cmd_get, "an ontology, as JSON")
    p.add_argument("ontology")
    p.add_argument("--editable", action="store_true", help="only the fields you send back: ready to edit and `update`")
    p.add_argument("-o", "--output")

    args = parser.parse_args()
    try:
        api = None
        if args.needs_api and not (args.command == "check" and args.offline):
            api = Api(*resolve_credentials(args), timeout=args.timeout)
        args.fn(api, args)
    except Problem as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    except ApiError as e:
        fail(e)


if __name__ == "__main__":
    main()
