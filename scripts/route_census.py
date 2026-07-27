"""Route census: dump every route with its resolved auth dependencies as JSON lines.

Run inside the app container: python - < route_census.py
Handles FastAPI 0.138 lazy _IncludedRouter wrappers (recurses via include_context).
Identity-maps dependency callables back to their app.auth / app.csrf names so
closures like require_role(...)->dependency resolve to require_admin etc.
"""
import datetime
import json
import sys

from app.main import app
import app.auth as auth_mod

try:
    from app import csrf as csrf_mod
except Exception:
    csrf_mod = None

from fastapi.routing import APIRoute
from starlette.routing import Mount, Route

ident = {}
for mod in [m for m in (auth_mod, csrf_mod) if m is not None]:
    short = mod.__name__.split(".")[-1]
    for k, v in vars(mod).items():
        if callable(v) and not isinstance(v, type):
            ident.setdefault(id(v), f"{short}.{k}")


_entries = []


def out(obj):
    _entries.append(obj)
    print(json.dumps(obj))

def dep_name(call):
    name = ident.get(id(call))
    if name is None:
        qn = getattr(call, "__qualname__", getattr(call, "__name__", str(call)))
        name = f"{getattr(call, '__module__', '?')}.{qn}"
    return name


def collect(dependant, acc):
    for d in dependant.dependencies:
        if d.call is not None:
            acc.append(dep_name(d.call))
        collect(d, acc)
    return acc


def emit(route, prefix, extra_deps):
    deps = collect(route.dependant, []) if isinstance(route, APIRoute) else []
    deps = extra_deps + deps
    methods = sorted((route.methods or set()) - {"HEAD", "OPTIONS"})
    endpoint = route.endpoint
    out({
        "path": prefix + route.path,
        "methods": methods,
        "endpoint": f"{getattr(endpoint, '__module__', '?')}.{getattr(endpoint, '__name__', '?')}",
        "deps": deps,
        "name": route.name,
    })


def walk(routes, prefix="", extra_deps=None):
    extra_deps = extra_deps or []
    for r in routes:
        tname = type(r).__name__
        if isinstance(r, APIRoute):
            emit(r, prefix, extra_deps)
        elif tname == "_IncludedRouter":
            ctx = r.include_context
            inc_deps = [dep_name(d.dependency) for d in (ctx.dependencies or [])]
            walk(ctx.included_router.routes, prefix + (ctx.prefix or ""), extra_deps + inc_deps)
        elif isinstance(r, Mount):
            out({"path": prefix + r.path, "methods": ["MOUNT"], "endpoint": type(r.app).__name__, "deps": [], "name": r.name})
        elif isinstance(r, Route):
            emit_methods = sorted((r.methods or set()) - {"HEAD", "OPTIONS"})
            out({"path": prefix + r.path, "methods": emit_methods, "endpoint": getattr(r.endpoint, "__name__", str(r.endpoint)), "deps": [], "name": r.name})
        else:
            out({"path": prefix + getattr(r, "path", "?"), "methods": [f"UNKNOWN:{tname}"], "endpoint": "?", "deps": [], "name": getattr(r, "name", "?")})


walk(app.routes)

_mounts = [e for e in _entries if "MOUNT" in e["methods"]]
_unknown = [e for e in _entries if any(str(m).startswith("UNKNOWN:") for m in e["methods"])]
_paths = sorted({e["path"] for e in _entries})
_total = len(_entries)
_http = _total - len(_mounts)
_mword = "mount" if len(_mounts) == 1 else "mounts"
_today = datetime.date.today().isoformat()

print("**Reconciled " + _today + "** against live route introspection: " + str(_total)
      + " route entries", file=sys.stderr)
print("(" + str(_http) + " HTTP routes plus " + str(len(_mounts)) + " " + _mword
      + ") across " + str(len(_paths)) + " unique paths. No commit pin, since any commit",
      file=sys.stderr)
print("that updates this file changes the count it would name. Regenerate with the command below.",
      file=sys.stderr)

if _unknown:
    print("WARNING: " + str(len(_unknown)) + " entries hit the UNKNOWN fallback:", file=sys.stderr)
    for e in _unknown:
        print("  " + e["path"] + " " + str(e["methods"]), file=sys.stderr)
