import argparse
import json
import secrets
import sys
from collections import Counter, OrderedDict
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "agent"))

from carrier import MockServices
from local_model import classify_reply
from pickup import Case, handle

MODEL = "qwen2.5:1.5b"
HOST = "127.0.0.1"
RECORDS = {"P101", "P103", "P109"}
PAGES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
}


class Inbox(HTTPServer):
    def __init__(self, port):
        MockServices()
        self.sessions = OrderedDict()
        super().__init__((HOST, port), RequestHandler)
        self.host = f"{HOST}:{self.server_port}"

    def read_turn(self, record, key, email):
        if key is None:
            key = secrets.token_urlsafe(20)
            if len(self.sessions) >= 32:
                self.sessions.popitem(last=False)
            self.sessions[key] = {"case": Case(record), "tools": MockServices(), "turn": 0}

        session = self.sessions.get(key)
        if session is None or session["case"].case_id != record or session["turn"] >= 24:
            raise LookupError("Start a new case to continue.")

        self.sessions.move_to_end(key)
        decisions = []

        @lru_cache(maxsize=4)
        def classify(message):
            counts = Counter()
            label = classify_reply(message, MODEL, outcomes=counts)
            decisions.append({"intent": label, "source": next(iter(counts), "rules")})
            return label

        case, tools = session["case"], session["tools"]
        start = len(tools.calls)
        session["turn"] += 1
        result = handle(case, tools, email, message_id=str(session["turn"]), classify=classify)
        return {
            "session": key, "decisions": decisions, "message": result["message"],
            "calls": tools.calls[start:], "state": case.state.value, "model": MODEL,
        }


class RequestHandler(BaseHTTPRequestHandler):
    def send(self, status, payload, mime):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(payload)

    def json(self, status, data):
        self.send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        if self.headers.get("Host") != self.server.host:
            return self.json(403, {"error": "Open the local demo address."})
        if self.path == "/health":
            return self.json(200, {"app": "pickup-demo"})
        if self.path not in PAGES:
            return self.json(404, {"error": "Page not found."})
        name, mime = PAGES[self.path]
        self.send(200, (HERE / name).read_bytes(), mime)

    def do_POST(self):
        host = self.server.host
        if self.headers.get("Host") != host or self.headers.get("Origin") != f"http://{host}":
            return self.json(403, {"error": "Open the local demo address."})
        if self.path != "/turn":
            return self.json(404, {"error": "Page not found."})
        if self.headers.get_content_type() != "application/json":
            return self.json(415, {"error": "Expected a JSON request."})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 16_384:
                raise ValueError
            body = json.loads(self.rfile.read(size))
            email = body["email"].strip()
            record = body["record"]
            key = body.get("session")
            if not 1 <= len(email) <= 2000 or record not in RECORDS or (key is not None and not isinstance(key, str)):
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            return self.json(400, {"error": "Choose a carrier record and enter a shopper email."})

        try:
            result = self.server.read_turn(record, key, email)
        except LookupError as error:
            return self.json(409, {"error": str(error)})
        self.json(200, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the local pickup inbox.")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    with Inbox(args.port) as server:
        print(f"Pickup inbox: http://{server.host}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
