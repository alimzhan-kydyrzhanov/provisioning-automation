"""Minimal HTTP endpoint that receives Salesforce webhooks (stdlib only, no framework).

Security: every request must carry X-Signature = HMAC-SHA256(secret, body), so nobody
can trigger provisioning by posting a fake order.
"""
import hashlib
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def sign(secret: bytes, body: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def make_server(engine, secret: bytes, host="127.0.0.1", port=8080):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code, data):
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/webhooks/salesforce":
                return self._reply(404, {"error": "not found"})
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if not hmac.compare_digest(self.headers.get("X-Signature", ""), sign(secret, body)):
                return self._reply(401, {"error": "bad signature"})
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return self._reply(400, {"error": "invalid JSON"})
            self._reply(202, engine.handle_salesforce_event(payload))

        def log_message(self, *args):  # keep test output clean
            pass

    return ThreadingHTTPServer((host, port), Handler)
