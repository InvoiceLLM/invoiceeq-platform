"""
InvoiceLLM — Partner Testing Portal Server + CORS Bypass Proxy
Serves index.html on port 8080 and proxies API requests without browser CORS blocking.
"""
import http.server
import socketserver
import urllib.request
import urllib.error
import json
import os
import sys

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

class ProxyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def do_POST(self):
        if self.path.startswith('/proxy'):
            self._handle_proxy('POST')
        else:
            super().do_POST()

    def do_GET(self):
        if self.path.startswith('/proxy'):
            self._handle_proxy('GET')
        else:
            super().do_GET()

    def _handle_proxy(self, method):
        # Extract target URL from query or headers
        import urllib.parse
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        target_url = qs.get('url', [None])[0]

        if not target_url:
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"error": "Missing ?url= query parameter"}')
            return

        # Read request body if present
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len) if content_len > 0 else None

        # Build forward headers
        forward_headers = {}
        for header, value in self.headers.items():
            if header.lower() not in ['host', 'origin', 'referer', 'content-length']:
                forward_headers[header] = value

        req = urllib.request.Request(target_url, data=body, headers=forward_headers, method=method)

        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for h, v in resp.getheaders():
                    if h.lower() not in ['transfer-encoding', 'content-length', 'access-control-allow-origin']:
                        self.send_header(h, v)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header('Content-Type', e.headers.get('Content-Type', 'application/json'))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as e:
            err_json = json.dumps({"error": str(e)}).encode()
            self.send_response(502)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(err_json)))
            self.end_headers()
            self.wfile.write(err_json)

if __name__ == '__main__':
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), ProxyHTTPRequestHandler) as httpd:
        print(f"Partner Test Portal Server running at: http://localhost:{PORT}")
        sys.stdout.flush()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
