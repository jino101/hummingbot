import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from jino_mobile.server import make_server


def _request(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_dashboard_api_is_read_only_except_kill_switch(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>ok</html>", encoding="utf-8")

    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps({
        "timestamp": 123,
        "mode": "observe",
        "trading_pair": "BTC-USDT",
        "readiness": {"market_data_ready": True},
        "opportunities": [],
        "executors": 0,
        "positions": 0,
    }), encoding="utf-8")
    log = tmp_path / "history.jsonl"
    log.write_text(json.dumps({"timestamp": 123, "opportunities": []}) + "\n", encoding="utf-8")
    kill = tmp_path / "kill"

    server = make_server("127.0.0.1", 0, web, latest, log, kill, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = _request(base + "/api/health")
        assert status == 200
        assert body["ok"] is True
        assert body["kill_switch"] is False

        status, body = _request(base + "/api/status")
        assert status == 200
        assert body["mode"] == "observe"
        assert body["runtime_kill_switch"] is False

        status, body = _request(base + "/api/summary")
        assert status == 200
        assert body["samples"] == 1

        status, body = _request(base + "/api/kill-switch/enable", method="POST")
        assert status == 200
        assert body["kill_switch"] is True
        assert kill.exists()

        status, body = _request(base + "/api/live/start", method="POST")
        assert status == 403
        assert "cannot enable trading" in body["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
