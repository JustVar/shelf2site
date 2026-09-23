"""A stale CSRF token from a browser form is sent back with a warning, not a 403 page.

Board N10: a page left open across a login elsewhere carries the old token.
Spec: docs/specs/toast-redirect-kind.md, After ratification.
"""
from urllib.parse import parse_qs, urlsplit

from app.config import settings
from app.csrf import STALE_MESSAGE

BP = settings.ROOT_PATH.rstrip("/")
ORIGIN = "http://127.0.0.1:8081"


def _post_stale_logout(client, referer):
    headers = {"accept": "text/html"}
    if referer is not None:
        headers["referer"] = referer
    return client.post("/logout", data={"csrf_token": "stale"}, headers=headers)


def test_stale_logout_goes_back_with_a_warning_and_keeps_the_session(fresh_viewer_client):
    r = _post_stale_logout(fresh_viewer_client, ORIGIN + BP + "/sites/?keep=1")
    assert r.status_code == 303
    loc = urlsplit(r.headers["location"])
    assert loc.path == BP + "/sites/"
    q = parse_qs(loc.query)
    assert q["keep"] == ["1"]
    assert q["toast"] == [STALE_MESSAGE]
    assert q["toast_type"] == ["warning"]
    # nothing ran: the session is still logged in
    assert fresh_viewer_client.get("/dashboard").status_code == 200


def test_referer_outside_the_app_falls_back_to_the_dashboard(fresh_viewer_client):
    cases = [None, ORIGIN + "//evil.example" + BP + "/x"]
    if BP:
        # only a sub-path deployment has paths outside the app on this host
        cases.append("https://evil.example/x")
    for referer in cases:
        r = _post_stale_logout(fresh_viewer_client, referer)
        assert r.status_code == 303, referer
        assert urlsplit(r.headers["location"]).path == BP + "/dashboard", referer


def test_non_browser_caller_still_gets_json_403(fresh_viewer_client):
    r = fresh_viewer_client.post("/logout", data={"csrf_token": "stale"})
    assert r.status_code == 403
    assert r.json()["detail"] == "CSRF token invalid"
