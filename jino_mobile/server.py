#!/usr/bin/env python3
"""Tiny dependency-free dashboard/API server for Jino.

This service is intentionally read-mostly. It exposes observation data and can only
engage the runtime kill switch. It cannot disable the kill switch, enable live mode,
or submit an exchange order.
"""
import argparse
import json
import mimetypes
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from hummingbot.jino_arbitrage.observation_store import (
    read_latest_observation,
    read_observation_history,
    summarize_observations,
)


class JinoDashboardHandler(BaseHTTPRequestHandler):
    server_version = "JinoDashboard/1.0"

    @property
    def root(self) -> Path:
        return Path(self.server.web_root)

    def _authorized(self) -> bool:
        expected = getattr(self.server, "access_token", "")
        if not expected:
            return False
        supplied = self.headers.get("Authorization", "")
        return supplied == f"Bearer {expected}"

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return False

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path):
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        media_type, _ = mimetypes.guess_type(str(path))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", media_type or "application/octet-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/health":
            latest = read_latest_observation(self.server.latest_path)
            self._send_json({
                "ok": True,
                "has_observation": bool(latest),
                "mode": latest.get("mode"),
                "timestamp": latest.get("timestamp"),
                "kill_switch": Path(self.server.kill_switch_path).exists(),
            })
            return

        if route == "/api/status":
            if not self._require_auth():
                return
            latest = read_latest_observation(self.server.latest_path)
            latest = dict(latest)
            latest["runtime_kill_switch"] = Path(self.server.kill_switch_path).exists()
            self._send_json(latest)
            return

        if route == "/api/history":
            if not self._require_auth():
                return
            rows = read_observation_history(self.server.log_path, limit=250)
            self._send_json({"records": rows})
            return

        if route == "/api/summary":
            if not self._require_auth():
                return
            rows = read_observation_history(self.server.log_path, limit=5000)
            self._send_json(summarize_observations(rows))
            return

        if route in {"/", "/index.html"}:
            self._serve_file(self.root / "index.html")
            return
        if route == "/app.js":
            self._serve_file(self.root / "app.js")
            return
        if route == "/styles.css":
            self._serve_file(self.root / "styles.css")
            return
        if route == "/manifest.webmanifest":
            self._serve_file(self.root / "manifest.webmanifest")
            return
        if route == "/sw.js":
            self._serve_file(self.root / "sw.js")
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        route = urlparse(self.path).path
        if not self._require_auth():
            return
        if route != "/api/kill-switch/enable":
            self._send_json(
                {"error": "unsupported action; dashboard cannot enable trading or disable safety controls"},
                status=HTTPStatus.FORBIDDEN,
            )
            return

        path = Path(self.server.kill_switch_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("engaged\n", encoding="utf-8")
        self._send_json({"ok": True, "kill_switch": True})

    def log_message(self, fmt, *args):
        if not getattr(self.server, "quiet", False):
            super().log_message(fmt, *args)


def make_server(host, port, web_root, latest_path, log_path, kill_switch_path, access_token, quiet=False):
    server = ThreadingHTTPServer((host, port), JinoDashboardHandler)
    server.web_root = str(web_root)
    server.latest_path = str(latest_path)
    server.log_path = str(log_path)
    server.kill_switch_path = str(kill_switch_path)
    server.access_token = access_token
    server.quiet = quiet
    return server


def main():
    parser = argparse.ArgumentParser(description="Jino mobile dashboard")
    parser.add_argument("--host", default=os.environ.get("JINO_DASHBOARD_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("JINO_DASHBOARD_PORT", "8787")))
    parser.add_argument("--web-root", default="jino_mobile/web")
    parser.add_argument("--latest", default="data/jino_observe_latest.json")
    parser.add_argument("--log", default="data/jino_observations.jsonl")
    parser.add_argument("--kill-switch", default="data/jino_kill_switch")
    args = parser.parse_args()

    access_token = os.environ.get("JINO_DASHBOARD_TOKEN") or secrets.token_urlsafe(24)
    server = make_server(
        args.host, args.port, args.web_root, args.latest, args.log, args.kill_switch, access_token
    )
    print(f"Jino dashboard: http://{args.host}:{args.port}")
    print(f"JINO DASHBOARD TOKEN: {access_token}")
    print("Read-only dashboard. Only safety action available: ENGAGE KILL SWITCH.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
