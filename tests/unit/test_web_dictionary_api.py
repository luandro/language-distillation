"""Request-level tests for the portal's dictionary endpoints."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

from tests.fixtures.artifacts import requires_built_web_data

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = REPO_ROOT / "exports" / "web" / "server.py"


def _load_server_module():
    spec = importlib.util.spec_from_file_location("portal_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["portal_server"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def live_server():
    module = _load_server_module()
    httpd = HTTPServer(("127.0.0.1", 0), module.SyntheticLKBRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(base: str, path: str):
    with urllib.request.urlopen(f"{base}{path}", timeout=30) as resp:
        return resp.status, resp.read()


@requires_built_web_data
def test_session_endpoint_returns_entries(live_server: str):
    status, body = _get(live_server, "/api/dictionary/session?lang=mzr&view=clean")
    assert status == 200
    payload = json.loads(body)
    assert payload["meta"]["target_lang"] == "mzr"
    assert payload["meta"]["total_entries"] == 892
    assert len(payload["entries"]) == 892
    first = payload["entries"][0]
    for key in (
        "headword",
        "search_key",
        "letter",
        "pos",
        "glosses",
        "status",
        "examples",
        "domain",
        "attestations",
    ):
        assert key in first, key
    assert payload["letters"], "the A-Z index must be present"
    assert payload["reverse"], "the reverse index must be present"


def test_session_entries_are_sorted_by_search_key(live_server: str):
    _, body = _get(live_server, "/api/dictionary/session?lang=mzr&view=clean")
    payload = json.loads(body)
    keys = [e["search_key"] for e in payload["entries"]]
    assert keys == sorted(keys)


@requires_built_web_data
def test_session_letter_buckets_are_normalized(live_server: str):
    _, body = _get(live_server, "/api/dictionary/session?lang=mzr&view=clean")
    payload = json.loads(body)
    letters = [entry["letter"] for entry in payload["letters"]]
    assert letters == sorted(letters)
    assert all(ch.isalpha() and ch.isupper() for ch in letters)
    # 'ártemis' must live under A, not under a separate 'Á'.
    by_head = {e["headword"]: e["letter"] for e in payload["entries"]}
    assert by_head["ártemis"] == "A"
    assert by_head["ẽa"] == "E"


@pytest.mark.parametrize(
    "artifact",
    [
        "/formats/mzr/dictionary_mzr.lift",
        "/formats/mzr/cldf/Dictionary-metadata.json",
        "/formats/mzr/dictionary_mzr_printable.html",
    ],
)
@requires_built_web_data
def test_advertised_artifact_links_resolve(live_server: str, artifact: str):
    """The Exports tab advertises these links; they must not 404."""
    status, _ = _get(live_server, artifact)
    assert status == 200, f"{artifact} returned {status}"


def test_formats_route_rejects_path_traversal(live_server: str):
    """The formats route must not serve files outside exports/<lang>/formats/."""
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(live_server, "/formats/mzr/../../../etc/passwd")
    assert excinfo.value.code == 404


@requires_built_web_data
def test_pdf_is_reachable_under_formats(live_server: str):
    """The print artifact must be downloadable once the edition has been built."""
    status, body = _get(live_server, "/formats/mzr/dictionary_mzr_printable.pdf")
    if status == 404:
        pytest.skip("the print edition has not been built yet")
    assert status == 200
    assert body[:5] == b"%PDF-"
