"""The grid download reads the network in a worker and honours Cancel."""

import http.server
import os
import tempfile
import threading
from unittest.mock import MagicMock, patch

import pytest

_PAYLOAD = os.urandom(300_000)


class _GridHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(_PAYLOAD)))
        self.end_headers()
        self.wfile.write(_PAYLOAD)

    def log_message(self, *args):
        pass


@pytest.fixture
def grid_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _GridHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/grid.zip"
    server.shutdown()
    server.server_close()


def _owner(cancelled=False):
    owner = MagicMock()
    owner._grid_download_cancelled = cancelled
    return owner


def test_the_grid_is_read_in_a_worker_and_written_whole(grid_url):
    from bdc_loader_plugin.core import grid

    read_in = []
    real_stream = grid._stream_grid

    def _stream(*args):
        read_in.append(threading.current_thread())
        return real_stream(*args)

    owner = _owner()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "grid.zip")
        with patch.object(grid, "_stream_grid", side_effect=_stream):
            assert grid.GridManager._fetch_grid_file(owner, grid_url, path, "BDC_SM_V2") is True
        with open(path, "rb") as f:
            assert f.read() == _PAYLOAD
    assert read_in and read_in[0] is not threading.main_thread()


def test_cancel_stops_the_grid_download(grid_url):
    from bdc_loader_plugin.core import grid

    with tempfile.TemporaryDirectory() as tmp:
        assert grid.GridManager._fetch_grid_file(_owner(True), grid_url, os.path.join(tmp, "g.zip"), "X") is False
