#!/usr/bin/env python3
"""atlas_api.py — call the Gwenlake Atlas REST API from a shell.

Standard library only. It resolves the credentials and the endpoint like the
`gwenlake` command, so a call needs no key on the command line.

    atlas_api.py whoami                                    # who the credentials belong to, and the endpoint
    atlas_api.py call GET /datasets -q project_id=res.project.…
    atlas_api.py call POST /orchestration/builds -d '{"target_id": "res.dataset.…"}'
    atlas_api.py call PATCH /datasets/res.dataset.… -d @body.json
    atlas_api.py call GET /datasets/res.dataset.…/files/exports/a.xlsx -o a.xlsx
    atlas_api.py resolve <project>.<dataset>               # a handle → the dataset id
    atlas_api.py sql "SELECT * FROM '<project>.<dataset>' LIMIT 5"
    atlas_api.py sql --file report.sql --format csv -o report.csv
    atlas_api.py upload <dataset: id or handle> rows.parquet [--mode SNAPSHOT] [--path dir] [--branch b]

Credentials, in order: --api-key, --profile (or GWENLAKE_PROFILE),
GWENLAKE_API_KEY, the `default` profile of ~/.gwenlake/credentials. The
endpoint: --base-url, GWENLAKE_BASE_URL, the profile's, else
https://atlas.gwenlake.com/api/v1.

Exit status: 0 when the API answered 2xx, 1 when it refused, 2 on a usage or
configuration problem. The key is never printed.
"""

import argparse
import configparser
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_BASE_URL = "https://atlas.gwenlake.com/api/v1"
TENANT_URL = "https://{tenant}.gwenlakeatlas.com/api/v1"
TENANT_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")

HINTS = {
    400: "the request cannot be honoured: read `detail` — an unknown branch, a reference across projects, "
         "a write mode the dataset's kind refuses, a statement that is not a single SELECT.",
    401: "the token is missing, revoked, or for another endpoint (check --profile / --base-url).",
    402: "the organization's plan does not include this, or its inference budget is spent.",
    403: "the credentials lack the scope, the resource is outside the API key's project, or the id does not exist "
         "(an unknown id often answers 403, not 404).",
    404: "no such resource — or this route is not served at this endpoint: check the path against the references.",
    409: "conflict with the resource's state: a taken slug, a second producer, a build already running.",
    422: "the body or the parameters are invalid: `detail` lists the fields.",
}


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
    """A bare name is a tenant, a bare host gets /v1, a host with /api gets
    /api/v1, any other path is kept — the completion the gwenlake library does."""
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
    def __init__(self, token, base_url, timeout=120):
        self.token = token
        self.base_url = base_url
        self.timeout = timeout

    def call(self, method, path, *, params=None, body=None, content_type=None, accept=None):
        """(status, raw bytes, headers). Never raises on a 4xx/5xx."""
        if not path.startswith("/"):
            path = "/" + path
        query = urllib.parse.urlencode([(k, v) for k, v in (params or []) if v is not None])
        url = self.base_url + urllib.parse.quote(path, safe="/:@!$&'()*+,;=~") + ("?" + query if query else "")
        headers = {"Authorization": "Bearer " + self.token, "User-Agent": "atlas-api-skill"}
        if accept:
            headers["Accept"] = accept
        data = None
        if body is not None:
            if isinstance(body, (dict, list)):
                data = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            else:
                data = body.encode("utf-8") if isinstance(body, str) else body
                headers["Content-Type"] = content_type or "application/json"
        request = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers
        except urllib.error.URLError as e:
            raise Problem(f"Cannot reach {self.base_url}: {e.reason}")
        except OSError as e:
            raise Problem(f"{method} {path} did not answer within {self.timeout}s ({e}): raise --timeout.")

    def json(self, method, path, **kw):
        """(status, parsed JSON or text)."""
        status, raw, headers = self.call(method, path, **kw)
        return status, parse(raw, headers)


def parse(raw, headers):
    text = raw.decode("utf-8", errors="replace")
    if "json" in (headers.get("Content-Type") or ""):
        try:
            return json.loads(text)
        except ValueError:
            pass
    return text


def fail(status, body):
    detail = body.get("detail", body.get("error", body)) if isinstance(body, dict) else body
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    print(f"error: HTTP {status}: {detail.strip()[:2000]}", file=sys.stderr)
    if status in HINTS:
        print("hint: " + HINTS[status], file=sys.stderr)
    sys.exit(1)


def rows(body):
    """The items of a listing: most answer {"object": "list", "data": [...]}, a few a bare array."""
    if isinstance(body, dict):
        return body.get("data") or []
    return body if isinstance(body, list) else []


def dataset_id(api, ref):
    """A dataset named by its id or its handle `<project>.<dataset>` → its id."""
    if ref.startswith("res."):
        return ref
    project, _, dataset = ref.partition(".")
    if not dataset:
        project, _, dataset = ref.partition("/")
    if not dataset:
        raise Problem("Name the dataset by its id (res.dataset.…) or its handle `<project>.<dataset>`.")
    status, body = api.json("GET", "/filesystem/projects")
    if status != 200:
        fail(status, body)
    pid = next((p["id"] for p in rows(body) if project in (p.get("slug"), p.get("alias"))), None)
    if pid is None:
        known = ", ".join(sorted(p.get("slug") or "" for p in rows(body))) or "none"
        raise Problem(f"No project `{project}`. Projects you can reach: {known}.")
    status, body = api.json("GET", "/datasets", params=[("project_id", pid)])
    if status != 200:
        fail(status, body)
    for d in rows(body):
        if dataset in (d.get("slug"), d.get("alias")):
            return d["id"]
    known = ", ".join(sorted(d.get("slug") or "" for d in rows(body))) or "none"
    raise Problem(f"No dataset `{dataset}` in project `{project}`. Datasets: {known}.")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def emit(raw, headers, output):
    """Write an answer: to a file as bytes, else pretty JSON or the text as it is."""
    if output and output != "-":
        with open(output, "wb") as f:
            f.write(raw)
        print(f"wrote {output} ({len(raw)} bytes)", file=sys.stderr)
        return
    body = parse(raw, headers)
    if isinstance(body, str):
        kind = headers.get("Content-Type") or ""
        if raw and not (kind.startswith("text/") or "yaml" in kind or "csv" in kind or "event-stream" in kind):
            raise Problem(f"The answer is binary ({kind or 'no content type'}, {len(raw)} bytes): write it with -o <file>.")
        sys.stdout.write(body if body.endswith("\n") or not body else body + "\n")
    else:
        print(json.dumps(body, indent=2, ensure_ascii=False))


def read_body(value):
    if value is None:
        return None
    if value == "@-":
        return sys.stdin.read()
    if value.startswith("@"):
        try:
            with open(value[1:], "rb") as f:
                return f.read()
        except OSError as e:
            raise Problem(f"Cannot read {value[1:]}: {e.strerror}")
    return value


def cmd_whoami(api, args):
    status, body = api.json("GET", "/users/me")
    if status != 200:
        fail(status, body)
    print(json.dumps({"endpoint": api.base_url, "user": body}, indent=2, ensure_ascii=False))


def cmd_call(api, args):
    params = []
    for item in args.query or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise Problem(f"-q takes key=value (got `{item}`).")
        params.append((key, value))
    body = read_body(args.data)
    if isinstance(body, str) and (args.content_type or "json") in ("json", "application/json"):
        try:
            body = json.loads(body)
        except ValueError as e:
            raise Problem(f"-d is not JSON ({e}). For another body, pass --content-type.")
    status, raw, headers = api.call(
        args.method, args.path, params=params, body=body,
        content_type=args.content_type if args.content_type not in (None, "json") else None, accept=args.accept,
    )
    if status >= 400:
        fail(status, parse(raw, headers))
    if args.include:
        for name in ("X-Gwenlake-Truncated", "X-Gwenlake-Row-Limit", "X-Gwenlake-Version", "Content-Type"):
            if headers.get(name):
                print(f"{name}: {headers[name]}", file=sys.stderr)
    emit(raw, headers, args.output)


def cmd_resolve(api, args):
    print(dataset_id(api, args.dataset))


def cmd_sql(api, args):
    if args.file:
        statement = read_body("@" + args.file)
        statement = statement.decode("utf-8") if isinstance(statement, bytes) else statement
    elif args.statement:
        statement = args.statement
    else:
        raise Problem("Give a statement, or --file.")
    fmt = args.format or "json"
    if fmt != "json" and not args.output:
        raise Problem(f"--format {fmt} needs -o <file>.")
    body = {"statement": statement, "format": fmt}
    if args.limit is not None:
        body["limit"] = args.limit
    status, raw, headers = api.call("POST", "/sql/statements", body=body)
    if status >= 400:
        fail(status, parse(raw, headers))
    if headers.get("X-Gwenlake-Truncated", "").lower() == "true":
        print(
            f"note: the result was cut at {headers.get('X-Gwenlake-Row-Limit')} rows. Add a LIMIT/OFFSET of your own "
            "to page, or raise --limit.", file=sys.stderr,
        )
    emit(raw, headers, args.output)


def cmd_upload(api, args):
    did = dataset_id(api, args.dataset)
    try:
        with open(args.file, "rb") as f:
            content = f.read()
    except OSError as e:
        raise Problem(f"Cannot read {args.file}: {e.strerror}")
    name = args.filename or os.path.basename(args.file)
    boundary = "----atlas" + uuid.uuid4().hex
    kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
        f"Content-Type: {kind}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    path = f"/datasets/{did}/files" + ("/" + args.path.strip("/") if args.path else "")
    params = [("mode", args.mode), ("keys", args.keys), ("branch", args.branch)]
    status, raw, headers = api.call(
        "POST", path, params=params, body=body, content_type=f"multipart/form-data; boundary={boundary}",
    )
    if status >= 400:
        fail(status, parse(raw, headers))
    emit(raw, headers, None)


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="a profile of ~/.gwenlake/credentials")
    common.add_argument("--api-key", help="an API key (prefer GWENLAKE_API_KEY or a profile)")
    common.add_argument("--base-url", help="the endpoint: a tenant's name, a host or a URL")
    common.add_argument("--timeout", type=int, default=120, help="seconds to wait for an answer (default 120)")

    parser = argparse.ArgumentParser(description="Call the Gwenlake Atlas REST API.", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, fn, help):
        p = sub.add_parser(name, help=help, parents=[common])
        p.set_defaults(fn=fn)
        return p

    command("whoami", cmd_whoami, "who the credentials belong to, and the endpoint in use")
    p = command("call", cmd_call, "any request: METHOD PATH")
    p.add_argument("method", help="GET, POST, PATCH, PUT or DELETE")
    p.add_argument("path", help="the resource path, without the base URL: /datasets")
    p.add_argument("-q", "--query", action="append", metavar="KEY=VALUE", help="a query parameter (repeatable)")
    p.add_argument("-d", "--data", help="the body: JSON text, @file, or @- for stdin")
    p.add_argument("--content-type", help="for a body that is not JSON, e.g. application/yaml")
    p.add_argument("--accept", help="an Accept header, e.g. application/yaml")
    p.add_argument("-o", "--output", help="write the answer to this file (needed for binary answers)")
    p.add_argument("-i", "--include", action="store_true", help="print the X-Gwenlake-* headers on stderr")
    p = command("resolve", cmd_resolve, "a dataset handle <project>.<dataset> → its id")
    p.add_argument("dataset")
    p = command("sql", cmd_sql, "run a SELECT on datasets")
    p.add_argument("statement", nargs="?")
    p.add_argument("--file", help="read the statement from a file")
    p.add_argument("--limit", type=int, help="the row cap when the statement has no LIMIT (1000 by default)")
    p.add_argument("--format", choices=("json", "csv", "pyarrow"), help="json by default; csv and pyarrow need -o")
    p.add_argument("-o", "--output")
    p = command("upload", cmd_upload, "upload a file into a dataset")
    p.add_argument("dataset", help="an id (res.dataset.…) or a handle <project>.<dataset>")
    p.add_argument("file")
    p.add_argument("--mode", choices=("APPEND", "SNAPSHOT", "UPDATE"), help="tabular datasets: APPEND by default")
    p.add_argument("--keys", help="UPDATE: comma-separated key columns, when not the dataset's own")
    p.add_argument("--path", help="a subdirectory of the dataset")
    p.add_argument("--filename", help="the name to store the file under")
    p.add_argument("--branch", help="a data branch (default main)")

    args = parser.parse_args()
    try:
        token, base_url = resolve_credentials(args)
        args.fn(Api(token, base_url, args.timeout), args)
    except Problem as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
