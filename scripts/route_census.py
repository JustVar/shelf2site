"""Route census: dump every route with its resolved auth dependencies as JSON lines.

Run inside the app container: python - < route_census.py
Handles FastAPI 0.138 lazy _IncludedRouter wrappers (recurses via include_context).
Identity-maps dependency callables back to their app.auth / app.csrf names so
closures like require_role(...)->dependency resolve to require_admin etc.
"""
import json

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
    print(json.dumps({
        "path": prefix + route.path,
        "methods": methods,
        "endpoint": f"{getattr(endpoint, '__module__', '?')}.{getattr(endpoint, '__name__', '?')}",
        "deps": deps,
        "name": route.name,
    }))


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
            print(json.dumps({"path": prefix + r.path, "methods": ["MOUNT"], "endpoint": type(r.app).__name__, "deps": [], "name": r.name}))
        elif isinstance(r, Route):
            emit_methods = sorted((r.methods or set()) - {"HEAD", "OPTIONS"})
            print(json.dumps({"path": prefix + r.path, "methods": emit_methods, "endpoint": getattr(r.endpoint, "__name__", str(r.endpoint)), "deps": [], "name": r.name}))
        else:
            print(json.dumps({"path": prefix + getattr(r, "path", "?"), "methods": [f"UNKNOWN:{tname}"], "endpoint": "?", "deps": [], "name": getattr(r, "name", "?")}))


walk(app.routes)
