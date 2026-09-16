"""Redirect with a toast message carried in the query string.

The handler in app/templates/base.html reads the toast and toast_type
query parameters, renders the toast with SxToast, and strips both from
the address bar. Spec: docs/specs/toast-redirect-kind.md.

The message is encoded exactly once here and decoded exactly once by
URLSearchParams in the browser, so any character survives the trip.
"""
from urllib.parse import urlencode

from fastapi.responses import RedirectResponse

TOAST_KINDS = ("success", "error", "warning", "info")


def toast_redirect(url, message, kind="success"):
    """Return a 303 RedirectResponse to url carrying message as a toast.

    kind is one of TOAST_KINDS. success is the handler default, so it is
    not written into the URL; the other three are sent as toast_type.
    A url that already has a query string gets the parameters appended.
    """
    if kind not in TOAST_KINDS:
        raise ValueError("toast kind must be one of %s, got %r" % (TOAST_KINDS, kind))
    params = {"toast": message}
    if kind != "success":
        params["toast_type"] = kind
    separator = "&" if "?" in url else "?"
    return RedirectResponse(url + separator + urlencode(params), status_code=303)
