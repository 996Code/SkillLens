"""S27 试点彩排：本地 webhook 接收器——验证通知端到端送达。

用法：uv run python ../scripts/webhook_receiver.py [端口，默认 8790]
收到的请求体逐行追加到 webhook_received.log。
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "server" / "webhook_received.log"


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        body = self.rfile.read(n).decode("utf-8", "replace")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(body + "\n")
        self.send_response(200)
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
    print(f"receiver on :{port}, log -> {LOG}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
