#!/usr/bin/env python3
"""atlas_app.py — create, validate and save Gwenlake Atlas applications (app.yaml).

Standard library only. The `gwenlake` command line and Python library do not
send an app.yaml yet (they speak JSON; the application routes take raw YAML),
which is what this script is for.

    atlas_app.py projects                              # the projects you can reach
    atlas_app.py datasets <project>                    # the datasets of a project, with their slugs
    atlas_app.py columns <project>/<dataset>           # the columns of a dataset, with sample values
    atlas_app.py validate app.yaml --project <project> # check, save nothing
    atlas_app.py create app.yaml --project <project>   # create the application
    atlas_app.py save app.yaml --app <application id>  # save a new revision
    atlas_app.py list [--project <project>]            # the applications
    atlas_app.py get <application id> [--yaml] [-o f]  # the application, or its YAML source
    atlas_app.py source-columns <application id> <source>
    atlas_app.py read <application id> <source> [--options '{"aggregate": "count(*)"}']

A project is named by its slug or its id (res.project.…).

Credentials, in the order the `gwenlake` command resolves them: --api-key,
--profile (or GWENLAKE_PROFILE), GWENLAKE_API_KEY, the `default` profile of
~/.gwenlake/credentials. The endpoint: --base-url, GWENLAKE_BASE_URL, the
profile's, else https://atlas.gwenlake.com/api/v1.

Exit status: 0 when the command did what it says, 1 when the definition is
invalid or the API refused, 2 on a usage or configuration problem.
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
YAML = "application/yaml"


class Problem(Exception):
    """A configuration or usage problem: printed, exit status 2."""


# ---------------------------------------------------------------------------
# Credentials and endpoint
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
    """Same completion as the gwenlake library: a bare name is a tenant, a
    bare host gets /v1, a host with /api gets /api/v1, any other path is kept."""
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
    """A token for a profile holding an OAuth2 client: left to the gwenlake library."""
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


def resolve(args):
    """(token, base URL) for this run."""
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


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Api:
    def __init__(self, token, base_url):
        self.token = token
        self.base_url = base_url

    def call(self, method, path, *, params=None, body=None, content_type=None, accept="application/json"):
        """(status, parsed body, headers). The body is parsed as JSON when the
        answer is JSON, returned as text otherwise. Never raises on a 4xx/5xx."""
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = self.base_url + path + ("?" + query if query else "")
        data = None
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": accept,
            "User-Agent": "atlas-applications-skill",
        }
        if body is not None:
            if isinstance(body, (dict, list)):
                data = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            else:
                data = body.encode("utf-8") if isinstance(body, str) else body
                headers["Content-Type"] = content_type or YAML
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                status, raw, got = response.status, response.read(), response.headers
        except urllib.error.HTTPError as e:
            status, raw, got = e.code, e.read(), e.headers
        except urllib.error.URLError as e:
            raise Problem(f"Cannot reach {self.base_url}: {e.reason}")
        except OSError as e:  # a timeout while the answer is being read
            raise Problem(f"{method} {path} did not answer: {e}")
        text = raw.decode("utf-8", errors="replace")
        kind = got.get("Content-Type", "")
        if "json" in kind:
            try:
                return status, json.loads(text), got
            except ValueError:
                pass
        if "html" in kind:
            raise Problem(
                f"{url} answered an HTML page, not the API. An Atlas host serves the API under /api/v1, "
                "a gateway under /v1: check --base-url."
            )
        return status, text, got


def fail(status, body):
    """Print what the API refused and exit 1."""
    detail = body.get("detail") if isinstance(body, dict) else body
    print(f"error: HTTP {status}: {detail if detail else body}", file=sys.stderr)
    hint = {
        401: "the API key is missing, revoked or for another endpoint.",
        402: "the organization's plan does not include this.",
        403: "the credentials lack the scope (applications:read / applications:write), or the resource is outside the key's project.",
        404: "no such resource at this endpoint — check the id and the endpoint (--base-url / --profile).",
        409: "conflict: the slug (metadata.name) is taken, or a newer revision was saved since --base-version.",
        415: "the body must be sent as Content-Type: application/yaml.",
    }.get(status)
    if "no declarative definition" in str(detail):
        hint = ("this application holds no app.yaml (it is rendered by a template, or was created empty): "
                "there is no YAML to fetch. Create a new application from an app.yaml instead.")
    if hint:
        print("hint: " + hint, file=sys.stderr)
    sys.exit(1)


def rows(body):
    return (body.get("data") or []) if isinstance(body, dict) else (body or [])


def slug_of(resource):
    return resource.get("slug") or resource.get("alias") or ""


def project_id(api, ref):
    """A project named by its slug or its id → its id."""
    if ref.startswith("res.project."):
        return ref
    status, body, _ = api.call("GET", "/filesystem/projects")
    if status != 200:
        fail(status, body)
    for project in rows(body):
        if slug_of(project) == ref or project.get("name") == ref:
            return project["id"]
    known = ", ".join(sorted(slug_of(p) for p in rows(body) if slug_of(p))) or "none"
    raise Problem(f"No project `{ref}`. Projects you can reach: {known}.")


# ---------------------------------------------------------------------------
# Widget props — what the Atlas interface checks before it draws a widget.
#
# The platform's validation does not know the widget types: it accepts any
# `type` and any props, and the interface then replaces a widget it cannot
# draw with an error card. This table mirrors the interface's registry
# (web/src/apps/registry.tsx) so the mistake is caught before the save.
# kind: string | number | boolean | enum | color | background | source |
#       field | fields | aggregate | bind | filter | agent | object
# ---------------------------------------------------------------------------

COLORS = ("blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red")
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
AGGREGATE = re.compile(r"^(sum|avg|min|max|count)\(\s*(\*|[A-Za-z_][A-Za-z0-9_]*)\s*\)$")
EXPRESSION = re.compile(r"\$\{state\.[a-z][a-z0-9_]*\}")
BIND = re.compile(r"^state\.([a-z][a-z0-9_]*)$")


def P(kind, required=False, **extra):
    return dict(kind=kind, required=required, **extra)


_TEXT = P("string", expression=True)
_SOURCE = P("source", True)
_CARTESIAN = {
    "title": _TEXT, "source": _SOURCE, "x": P("field", True), "y": P("field", True),
    "color": P("color"), "baseline": P("number"), "background": P("background"), "filter": P("filter"),
}

WIDGETS = {
    "filter.select": {
        "label": _TEXT, "bind": P("bind", True),
        "options": P("object", True, fields={"source": _SOURCE, "field": P("field", True)}),
        "placeholder": P("string"),
    },
    "filter.text": {"label": _TEXT, "bind": P("bind", True, types=("string", "number")), "placeholder": P("string")},
    "filter.number": {
        "label": _TEXT, "bind": P("bind", True, types=("number",)),
        "min": P("number"), "max": P("number"), "step": P("number"), "placeholder": P("string"),
    },
    "filter.date": {"label": _TEXT, "bind": P("bind", True, types=("date", "string"))},
    "filter.toggle": {"label": _TEXT, "bind": P("bind", True, types=("boolean",))},
    "kpi": {
        "label": _TEXT, "source": _SOURCE, "value": P("aggregate", True),
        "format": P("enum", options=("number", "eur", "percent")), "subtitle": _TEXT,
        "color": P("color"), "background": P("background"), "filter": P("filter"),
    },
    "table": {
        "title": _TEXT, "source": _SOURCE, "columns": P("fields"),
        "page_size": P("number", min=1, max=1000), "background": P("background"), "filter": P("filter"),
    },
    "chart.bar": _CARTESIAN,
    "chart.line": {**_CARTESIAN, "fill": P("boolean")},
    "chart.area": _CARTESIAN,
    "chart.pie": {
        "title": _TEXT, "source": _SOURCE, "category": P("field", True), "value": P("aggregate", True),
        "color": P("color"), "background": P("background"), "filter": P("filter"),
    },
    "map": {
        "title": _TEXT, "source": _SOURCE, "lat": P("field", True), "lon": P("field", True),
        "label": P("field"), "color": P("color"), "size": P("number", min=1, max=40),
        "view": P("enum", options=("map", "globe")), "background": P("background"), "filter": P("filter"),
    },
    "text": {"content": P("string", True, expression=True)},
    "agent.chat": {"agent": P("agent", True)},
    "chat": {"model": P("string"), "system": P("string")},
}


def _scalar(v):
    return v is None or isinstance(v, (str, int, float, bool))


def _has_expression(v):
    return isinstance(v, str) and bool(EXPRESSION.search(v))


def _is_color(v):
    return isinstance(v, str) and (v in COLORS or bool(HEX.match(v)))


def _check(field, value, path, state, out):
    kind = field["kind"]
    bad = lambda message: out.append((path, message))  # noqa: E731
    if kind == "string":
        if not isinstance(value, str) and not (field.get("expression") and _scalar(value)):
            bad("must be a text")
    elif kind == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "min" in field and value < field["min"]:
                bad(f"must be at least {field['min']}")
            if "max" in field and value > field["max"]:
                bad(f"must be at most {field['max']}")
        elif not _has_expression(value):
            bad("must be a number")
    elif kind == "boolean":
        if not isinstance(value, bool) and not _has_expression(value):
            bad("must be true or false")
    elif kind == "enum":
        if value not in field["options"]:
            bad("must be one of: " + ", ".join(field["options"]))
    elif kind == "color":
        if not _is_color(value) and not _has_expression(value):
            bad("must be a hex color in quotes (\"#0ea5e9\") or one of: " + ", ".join(COLORS))
    elif kind == "background":
        if isinstance(value, dict):
            if not value or any(k not in ("light", "dark") or not _is_color(c) for k, c in value.items()):
                bad("must be a color, or { light, dark } holding colors")
        elif not _is_color(value):
            bad("must be a hex color in quotes (\"#0ea5e9\"), one of: " + ", ".join(COLORS) + ", or { light, dark }")
    elif kind in ("source", "field", "agent"):
        if not isinstance(value, str) or not value:
            bad({"source": "must name a source", "field": "must name a field", "agent": "must name an agent"}[kind])
    elif kind == "fields":
        if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
            bad("must be a list of fields")
    elif kind == "aggregate":
        if not isinstance(value, str) or not AGGREGATE.match(value.strip()) or (
            "*" in value and not value.strip().startswith("count")
        ):
            bad("must be an aggregate such as sum(field) — sum, avg, min, max or count; count(*) counts rows. "
                "The field is a plain column name: compute anything else in a `query` source")
    elif kind == "bind":
        m = BIND.match(value) if isinstance(value, str) else None
        if not m:
            bad("must be state.<variable>")
        elif field.get("types") and m.group(1) in state and state[m.group(1)].get("type") not in field["types"]:
            bad(f"is bound to a `{state[m.group(1)].get('type')}` variable; this widget needs: " + ", ".join(field["types"]))
    elif kind == "filter":
        if not isinstance(value, dict):
            bad("must be a table of field: value")
        else:
            for k, v in value.items():
                if not (_scalar(v) or (isinstance(v, list) and all(_scalar(i) for i in v))):
                    out.append((f"{path}.{k}", "must be a value, a list of values or null"))
    elif kind == "object":
        if not isinstance(value, dict):
            bad("must be an object")
        else:
            _check_object(field["fields"], value, path, state, out)


def _check_object(schema, props, prefix, state, out):
    for key, field in schema.items():
        value = props.get(key)
        path = f"{prefix}.{key}"
        if value is None:
            if field["required"]:
                out.append((path, "is required"))
            continue
        _check(field, value, path, state, out)
    for key in props:
        if key not in schema:
            out.append((f"{prefix}.{key}", "is not a prop of this widget. Props: " + ", ".join(schema)))


def lint_widgets(spec):
    """Problems the interface would show as error cards, as (path, message)."""
    out = []
    state = spec.get("state") or {}
    sources = spec.get("sources") or {}
    for name, widget in (spec.get("widgets") or {}).items():
        kind = widget.get("type")
        schema = WIDGETS.get(kind)
        if schema is None:
            out.append((f"widgets.{name}.type", f"`{kind}` is not a widget type. Types: " + ", ".join(WIDGETS)))
            continue
        props = widget.get("props") or {}
        _check_object(schema, props, f"widgets.{name}.props", state, out)
        if kind in ("chart.bar", "chart.line", "chart.area"):
            source = sources.get(props.get("source")) or {}
            if source.get("kind") == "dataset":
                out.append((
                    f"widgets.{name}.props.source",
                    "note: this chart draws the rows of a dataset as they are (first 500, unsorted). "
                    "To chart an aggregate or a sorted series, give it a `query` source.",
                ))
    return out


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def read_text(path):
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        raise Problem(f"Cannot read {path}: {e.strerror}")


def print_issues(label, issues, stream=sys.stdout):
    for issue in issues:
        where = issue.get("path") or "(document)"
        at = f" [line {issue['line']}, column {issue['column']}]" if issue.get("line") else ""
        print(f"  {label} {where}{at}: {issue['message']}", file=stream)


def report(spec, warnings):
    """Warnings of the platform, then the widget problems. True when no widget would show an error card."""
    print_issues("warning", warnings or [])
    problems = lint_widgets(spec or {})
    notes = [(p, m) for p, m in problems if m.startswith("note: ")]
    errors = [(p, m) for p, m in problems if not m.startswith("note: ")]
    for path, message in notes:
        print(f"  note {path}: {message[len('note: '):]}")
    for path, message in errors:
        print(f"  widget error {path}: {message}")
    if errors:
        print(f"{len(errors)} widget problem(s): the platform accepts the file, but the interface would show "
              "an error card in place of each of these widgets. Fix them.")
    return not errors


def app_url(api, application_id):
    host = api.base_url.split("/api/")[0] if "/api/" in api.base_url else api.base_url.rsplit("/v1", 1)[0]
    return f"{host}/applications/{application_id}"


def cmd_projects(api, args):
    status, body, _ = api.call("GET", "/filesystem/projects")
    if status != 200:
        fail(status, body)
    for p in rows(body):
        print(f"{slug_of(p):32} {p.get('id', ''):40} {p.get('name', '')}")


def cmd_datasets(api, args):
    pid = project_id(api, args.project)
    status, body, _ = api.call("GET", "/datasets", params={"project_id": pid})
    if status != 200:
        fail(status, body)
    project_slug = args.project if not args.project.startswith("res.") else "<project>"
    print("# source reference (project/dataset)        type      name")
    for d in rows(body):
        kind = d.get("type") or (d.get("properties") or {}).get("type") or ""
        print(f"{project_slug + '/' + slug_of(d):42} {kind:9} {d.get('name', '')}")
    print("# An app source reads tabular datasets only (files holding Parquet, or iceberg) — not vector datasets.")


def cmd_columns(api, args):
    project, _, dataset = args.dataset.partition("/")
    if not dataset:
        project, _, dataset = args.dataset.partition(".")
    if not dataset:
        raise Problem("Name the dataset `<project>/<dataset>`.")
    statement = f"SELECT * FROM '{project}.{dataset}' LIMIT {args.rows}"
    status, body, _ = api.call("POST", "/sql/statements", body={"statement": statement, "format": "json"})
    if status != 200:
        fail(status, body)
    data = rows(body)
    if not data:
        print("The dataset holds no row: its columns cannot be read from a sample.")
        return
    print(f"# {project}/{dataset} — column: sample values")
    for column in data[0]:
        samples = []
        for row in data:
            v = row.get(column)
            if v is not None and v not in samples:
                samples.append(v)
        kind = type(samples[0]).__name__ if samples else "null"
        shown = ", ".join(json.dumps(s, ensure_ascii=False, default=str)[:40] for s in samples[:3])
        print(f"{column:32} {kind:6} {shown}")


def cmd_validate(api, args):
    text = read_text(args.file)
    params = {}
    if args.app:
        params["application_id"] = args.app
    elif args.project:
        params["project_id"] = project_id(api, args.project)
    else:
        print("note: without --project (or --app), the datasets named by the sources are not checked.")
    status, body, _ = api.call("POST", "/applications/validate", params=params, body=text)
    if status != 200:
        fail(status, body)
    if not body.get("valid"):
        errors = body.get("errors") or []
        print(f"INVALID — {len(errors)} error(s), nothing would be saved:")
        print_issues("error", errors)
        sys.exit(1)
    ok = report(body.get("spec"), body.get("warnings"))
    print("VALID" if ok else "VALID for the platform, but with widget problems")
    if args.spec:
        print(json.dumps(body.get("spec"), indent=2, ensure_ascii=False))
    sys.exit(0 if ok else 1)


def _saved(api, status, body, verb):
    if status == 422 and isinstance(body, dict):
        print(f"REFUSED — {body.get('detail', 'the definition is invalid')}")
        print_issues("error", body.get("errors") or [])
        sys.exit(1)
    if status not in (200, 201):
        fail(status, body)
    ok = report(body.get("spec"), body.get("warnings"))
    print(f"{verb}: {body.get('id')}  (slug {slug_of(body)}, revision {body.get('version')})")
    print(f"open: {app_url(api, body.get('id'))}")
    sys.exit(0 if ok else 1)


def cmd_create(api, args):
    text = read_text(args.file)
    status, body, _ = api.call("POST", "/applications", params={"project_id": project_id(api, args.project)}, body=text)
    _saved(api, status, body, "created")


def cmd_save(api, args):
    text = read_text(args.file)
    params = {"branch": args.branch, "base_version": args.base_version}
    status, body, _ = api.call("PUT", f"/applications/{args.app}", params=params, body=text)
    _saved(api, status, body, "saved")


def cmd_list(api, args):
    params = {"project_id": project_id(api, args.project)} if args.project else {}
    status, body, _ = api.call("GET", "/applications", params=params)
    if status != 200:
        fail(status, body)
    for a in rows(body):
        kind = f"template:{a['template']}" if a.get("template") else "app"
        print(f"{a.get('id', ''):44} {slug_of(a):28} {kind:18} {a.get('name', '')}")


def cmd_get(api, args):
    params = {"branch": args.branch, "version": args.version}
    if args.yaml:
        status, body, headers = api.call("GET", f"/applications/{args.app}", params=params, accept=YAML)
        if status != 200:
            fail(status, body)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(body)
            print(f"wrote {args.output} (revision {headers.get('x-gwenlake-version', '')})")
        else:
            sys.stdout.write(body)
        return
    status, body, _ = api.call("GET", f"/applications/{args.app}", params=params)
    if status != 200:
        fail(status, body)
    print(json.dumps(body, indent=2, ensure_ascii=False))


def cmd_source_columns(api, args):
    status, body, _ = api.call("GET", f"/applications/{args.app}/sources/{args.source}/columns")
    if status != 200:
        fail(status, body)
    for c in rows(body):
        print(f"{c.get('name', ''):32} {c.get('type', '')}")


def cmd_read(api, args):
    try:
        options = json.loads(args.options) if args.options else {}
    except ValueError as e:
        raise Problem(f"--options is not JSON: {e}")
    status, body, _ = api.call("POST", f"/applications/{args.app}/sources/{args.source}/read", body=options)
    if status != 200:
        fail(status, body)
    print(json.dumps(body, indent=2, ensure_ascii=False, default=str))


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="a profile of ~/.gwenlake/credentials")
    common.add_argument("--api-key", help="an API key (prefer GWENLAKE_API_KEY or a profile)")
    common.add_argument("--base-url", help="the endpoint: a tenant's name, a host or a URL")

    parser = argparse.ArgumentParser(
        description="Create, validate and save Gwenlake Atlas applications (app.yaml).", parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, fn, help):
        p = sub.add_parser(name, help=help, parents=[common])
        p.set_defaults(fn=fn)
        return p

    command("projects", cmd_projects, "the projects you can reach")
    p = command("datasets", cmd_datasets, "the datasets of a project")
    p.add_argument("project")
    p = command("columns", cmd_columns, "the columns of a dataset, with sample values")
    p.add_argument("dataset", help="<project>/<dataset>")
    p.add_argument("--rows", type=int, default=20, help="rows sampled (default 20)")
    p = command("validate", cmd_validate, "check an app.yaml; nothing is saved")
    p.add_argument("file", help="the app.yaml (- for stdin)")
    p.add_argument("--project", help="also check that the datasets exist and are readable")
    p.add_argument("--app", help="same check, in the organization of this application")
    p.add_argument("--spec", action="store_true", help="print the normalized form")
    p = command("create", cmd_create, "create an application from an app.yaml")
    p.add_argument("file")
    p.add_argument("--project", required=True)
    p = command("save", cmd_save, "save a new revision of an application")
    p.add_argument("file")
    p.add_argument("--app", required=True, help="the application id (res.application.…)")
    p.add_argument("--branch", help="data branch (default main)")
    p.add_argument("--base-version", help="the revision the edit started from: refused (409) if a newer one exists")
    p = command("list", cmd_list, "the applications")
    p.add_argument("--project")
    p = command("get", cmd_get, "an application (JSON), or its YAML source with --yaml")
    p.add_argument("app")
    p.add_argument("--yaml", action="store_true")
    p.add_argument("-o", "--output", help="with --yaml: write the source to this file")
    p.add_argument("--branch")
    p.add_argument("--version", help="an older revision")
    p = command("source-columns", cmd_source_columns, "the columns of a source of a saved application")
    p.add_argument("app")
    p.add_argument("source")
    p = command("read", cmd_read, "read a source of a saved application")
    p.add_argument("app")
    p.add_argument("source")
    p.add_argument("--options", help='JSON: {"filter", "aggregate", "group_by", "distinct", "columns", "sort", "limit", "offset", "state"}')

    args = parser.parse_args()
    try:
        token, base_url = resolve(args)
        args.fn(Api(token, base_url), args)
    except Problem as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
