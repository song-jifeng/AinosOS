#!/usr/bin/env python3
"""
Ainos OS - Web 管理面板 HTTP 服务器
桥接浏览器 HTTP 请求到 ai-daemon TCP IPC

用法:
  python web_server.py
  python web_server.py --port 9501 --daemon 127.0.0.1:9500
"""

import argparse
import json
import socket
import http.server
import urllib.parse
from pathlib import Path
from datetime import datetime


class AinosBridge:
    """与 ai-daemon 的 TCP IPC 桥接"""

    def __init__(self, host="127.0.0.1", port=9500):
        self.host = host
        self.port = port

    def send_request(self, msg: dict) -> dict:
        """发送 IPC 请求并接收响应"""
        data = json.dumps(msg) + "\n"
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        try:
            s.connect((self.host, self.port))
            s.sendall(data.encode("utf-8"))
            resp = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp += chunk
                if b"\n" in resp:
                    break
            return json.loads(resp.decode("utf-8").strip())
        except Exception as e:
            return {"type": "Error", "error": str(e)}
        finally:
            s.close()

    def status(self) -> dict:
        return self.send_request({"type": "Status"})

    def inference(self, prompt: str, model: str = "default") -> dict:
        return self.send_request({
            "type": "Inference",
            "model": model,
            "prompt": prompt,
            "temperature": 0.7,
            "max_tokens": 512,
        })

    def model_list(self) -> dict:
        return self.send_request({"type": "ModelList"})

    def context_store(self, key: str, value: str) -> dict:
        return self.send_request({"type": "ContextStore", "key": key, "value": value})

    def context_retrieve(self, key: str) -> dict:
        return self.send_request({"type": "ContextRetrieve", "key": key})


class AinosHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP 请求处理器"""

    bridge = None  # 类变量，在 main 中设置

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._serve_static("index.html")
        elif path == "/api/status":
            self._json_response(self.bridge.status())
        elif path == "/api/models":
            self._json_response(self.bridge.model_list())
        elif path == "/api/health":
            self._json_response({
                "status": "ok",
                "name": "Ainos OS",
                "version": "0.1.0",
                "time": datetime.now().isoformat(),
            })
        elif path.startswith("/api/context"):
            qs = urllib.parse.parse_qs(parsed.query)
            key = qs.get("key", [""])[0]
            if key:
                self._json_response(self.bridge.context_retrieve(key))
            else:
                self._json_response({"error": "missing key"})
        elif path.startswith("/static/"):
            self._serve_static(path[1:])
        else:
            self._serve_static("index.html")  # SPA fallback

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b"{}"
        data = json.loads(body) if body else {}

        if parsed.path == "/api/inference":
            prompt = data.get("prompt", "")
            model = data.get("model", "default")
            self._json_response(self.bridge.inference(prompt, model))
        elif parsed.path == "/api/context":
            key = data.get("key", "")
            value = data.get("value", "")
            self._json_response(self.bridge.context_store(key, value))
        else:
            self._json_response({"error": "not found"})

    def _serve_static(self, filename):
        web_dir = Path(__file__).resolve().parent
        filepath = web_dir / filename
        if filepath.exists():
            with open(filepath, "rb") as f:
                content = f.read()
            ext = filepath.suffix
            if ext == ".html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(content)
            elif ext == ".js":
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.end_headers()
                self.wfile.write(content)
            elif ext == ".css":
                self.send_response(200)
                self.send_header("Content-Type", "text/css")
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]} {args[2]}")


def main():
    parser = argparse.ArgumentParser(description="Ainos OS Web 管理面板")
    parser.add_argument("--port", type=int, default=9501, help="HTTP 端口")
    parser.add_argument("--daemon", type=str, default="127.0.0.1:9500", help="ai-daemon 地址")
    parser.add_argument("--bind", type=str, default="127.0.0.1", help="绑定地址")
    args = parser.parse_args()

    daemon_host, daemon_port = args.daemon.split(":")
    AinosHTTPHandler.bridge = AinosBridge(daemon_host, int(daemon_port))

    server = http.server.HTTPServer((args.bind, args.port), AinosHTTPHandler)
    print(f"Ainos OS Web 管理面板")
    print(f"  HTTP: http://{args.bind}:{args.port}")
    print(f"  守护进程: {args.daemon}")
    print(f"  按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止中...")
        server.shutdown()


if __name__ == "__main__":
    main()