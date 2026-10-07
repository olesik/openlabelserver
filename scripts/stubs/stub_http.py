#!/usr/bin/env python3
"""Minimal HTTP stub for OpenLabelServer service placeholders."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class StubHandler(BaseHTTPRequestHandler):
    service_name = "unknown"

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/health", "/health/"}:
            payload = {
                "status": "ok",
                "service": self.service_name,
                "mode": "stub",
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--service", default="unknown")
    args = parser.parse_args()

    handler = type(
        "ServiceStubHandler",
        (StubHandler,),
        {"service_name": args.service},
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(
        f"OpenLabelServer stub listening on {args.host}:{args.port} "
        f"(service={args.service})",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
