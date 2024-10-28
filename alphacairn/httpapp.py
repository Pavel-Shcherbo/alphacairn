"""Loopback application host for a small local workbench."""

import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def serve(evaluate, example, default_port, *, research=None):
    parser = argparse.ArgumentParser(description="Start the local workbench")
    parser.add_argument("--port", type=int, default=default_port)
    args = parser.parse_args()
    static = Path(__file__).parent / "static"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, code, payload, mime="application/json"):
            body = (
                json.dumps(payload, allow_nan=False).encode()
                if mime == "application/json"
                else payload
            )
            self.send_response(code)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") in {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }

        def do_GET(self):
            if not self.valid_host():
                self.respond(
                    403, {"error": "Use the loopback address printed at startup"}
                )
                return
            path = urlsplit(self.path).path
            if path == "/health":
                self.respond(200, {"status": "ok"})
            elif path == "/api/example":
                self.respond(200, example())
            elif path in {
                "/",
                "/index.html",
                "/app.js",
                "/style.css",
                "/research.html",
                "/research.js",
                "/research.css",
            }:
                name = "index.html" if path == "/" else path[1:]
                mime = {
                    "html": "text/html",
                    "js": "text/javascript",
                    "css": "text/css",
                }[name.rsplit(".", 1)[1]]
                self.respond(200, (static / name).read_bytes(), mime)
            elif path == "/favicon.ico":
                self.respond(204, b"", "image/x-icon")
            else:
                self.respond(404, {"error": "Unknown route"})

        def do_POST(self):
            origin = self.headers.get("Origin")
            valid_origins = {
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            }
            if (
                not self.valid_host()
                or (origin and origin not in valid_origins)
                or self.headers.get("X-Local-Request") != "1"
            ):
                self.respond(
                    403, {"error": "Only local workbench requests are accepted"}
                )
                return
            path = urlsplit(self.path).path
            if path not in {"/api/evaluate", "/api/research"} or (
                path == "/api/research" and research is None
            ):
                self.respond(404, {"error": "Unknown route"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                maximum = 8 * 1024 * 1024 if path == "/api/research" else 1024 * 1024
                if not 0 < length <= maximum or self.headers.get("Transfer-Encoding"):
                    raise ValueError(
                        f"Provide a JSON request of at most {maximum} bytes"
                    )
                if (
                    self.headers.get("Content-Type", "").split(";")[0]
                    != "application/json"
                ):
                    raise ValueError("Content-Type must be application/json")
                self.connection.settimeout(5)

                def pairs(values):
                    result = {}
                    for key, value in values:
                        if key in result:
                            raise ValueError("Duplicate JSON field")
                        result[key] = value
                    return result

                def reject(value):
                    raise ValueError("JSON numbers must be finite")

                params = json.loads(
                    self.rfile.read(length),
                    object_pairs_hook=pairs,
                    parse_constant=reject,
                )
                if not isinstance(params, dict):
                    raise ValueError("Expected a JSON object")
                result = (
                    research(params) if path == "/api/research" else evaluate(params)
                )
                self.respond(200, result)
            except (
                ValueError,
                KeyError,
                TypeError,
                OSError,
                TimeoutError,
                sqlite3.Error,
                ArithmeticError,
                RecursionError,
            ) as error:
                self.respond(400, {"error": str(error)})

    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Workbench: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
