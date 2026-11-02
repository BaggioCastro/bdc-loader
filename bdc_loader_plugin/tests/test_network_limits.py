"""A STAC server that accepts the connection and never answers must not hold the plugin.

A real local HTTP server and the bundled pystac_client; the request limit is
shortened so each test takes about a second.
"""

import http.server
import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


class _SilentSearchHandler(http.server.BaseHTTPRequestHandler):
    release = threading.Event()

    def _json(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") == "":
            base = f"http://127.0.0.1:{self.server.server_port}"
            self._json(
                {
                    "type": "Catalog",
                    "id": "test",
                    "description": "test",
                    "stac_version": "1.0.0",
                    "conformsTo": ["https://api.stacspec.org/v1.0.0-rc.1/item-search"],
                    "links": [
                        {"rel": "self", "href": base + "/"},
                        {"rel": "root", "href": base + "/"},
                        {"rel": "search", "href": base + "/search", "method": "GET"},
                    ],
                }
            )
            return
        self.release.wait(30)

    do_POST = do_GET

    def log_message(self, *args):
        pass


@pytest.fixture
def silent_server():
    _SilentSearchHandler.release.clear()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SilentSearchHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    _SilentSearchHandler.release.set()
    server.shutdown()
    server.server_close()


def test_a_search_on_a_silent_server_ends_with_a_timeout(silent_server):
    from bdc_loader_plugin.core.search import SearchEngine
    from bdc_loader_plugin.stac.client import open_stac_client
    from bdc_loader_plugin.vendored import ensure_pystac_client

    with patch("bdc_loader_plugin.stac.client.STAC_PAGE_S", (2, 0.5)):
        owner = MagicMock()
        owner.client = open_stac_client(ensure_pystac_client(), silent_server)
        started = time.monotonic()
        with pytest.raises(Exception, match="(?i)timed? ?out"):
            SearchEngine._fetch_items(owner, {"collections": ["X"], "max_items": 10}, 10)
    assert time.monotonic() - started < 5


def test_the_time_series_panel_client_has_the_same_limit(silent_server):
    from bdc_loader_plugin.stac.client import open_stac_client, search_items
    from bdc_loader_plugin.vendored import ensure_pystac_client

    with patch("bdc_loader_plugin.stac.client.STAC_PAGE_S", (2, 0.5)):
        client = open_stac_client(ensure_pystac_client(), silent_server)
        started = time.monotonic()
        with pytest.raises(Exception, match="(?i)timed? ?out"):
            list(search_items(client.search(collections=["X"], max_items=10)))
    assert time.monotonic() - started < 5
