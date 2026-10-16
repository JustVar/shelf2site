"""Error pages a browser sees: access denied (403) and page not found (404).
API callers and HTMX swaps keep FastAPI's JSON shape."""

HTML = {"Accept": "text/html"}


def test_access_denied_renders_inside_the_app(viewer_client):
    r = viewer_client.get("/admin/users", headers=HTML)
    assert r.status_code == 403
    assert "Access denied" in r.text and "sx-nav" in r.text


def test_an_unknown_page_renders_not_found(admin_client):
    r = admin_client.get("/no-such-page", headers=HTML)
    assert r.status_code == 404
    assert "Page not found" in r.text and "sx-nav" in r.text


def test_an_unknown_page_signed_out_goes_to_login(anon):
    r = anon.get("/no-such-page", headers=HTML)
    assert r.status_code in (302, 303) and r.headers["location"].endswith("/login")


def test_api_and_htmx_404s_stay_json(admin_client):
    for path, headers in [("/api/no-such-thing", HTML),
                          ("/no-such-page", {"Accept": "application/json"}),
                          ("/no-such-page", {**HTML, "HX-Request": "true"})]:
        r = admin_client.get(path, headers=headers)
        assert r.status_code == 404, path
        assert r.json() == {"detail": "Not Found"}, path


def test_a_wrong_method_stays_json(admin_client):
    r = admin_client.put("/dashboard", headers=HTML)
    assert r.status_code == 405
    assert r.json() == {"detail": "Method Not Allowed"}
