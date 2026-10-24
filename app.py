"""Page for entering clinics and generating their stickers: python app.py

Serves the page on port 8765 to this computer and to others on the same
network. Each browser keeps its own clinic list; the PDFs a person generates
are downloaded by their browser, into their Downloads folder.
"""

import base64
import ipaddress
import json
import socket
import sys
import tempfile
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from generate import DENSE_QR_NOTE, MAX_QR_VERSION, STATIC, check_row, generate, make_qr_svg

FIELDS = ["name_bn", "url", "slug"]
PORT = 8765
LOCAL_ADDRESS = f"http://127.0.0.1:{PORT}"
COMPUTER_NAME = socket.gethostname().lower()
GENERATING = threading.Lock()  # one batch at a time; other people's exports wait their turn


def network_address() -> str | None:
    """This computer's address on the local network, or None without one."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # picks the outgoing interface; sends nothing
            return s.getsockname()[0]
    except OSError:
        return None


class Server(ThreadingHTTPServer):
    # Threaded: a browser's idle spare connection must not hold up the page's requests.
    # Windows would otherwise let a second copy share the port instead of reporting it busy.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def from_this_page(self) -> bool:
        """False for requests another website makes the browser send here.

        The page is opened by IP address or by this computer's name; a website
        trying to reach it through its own domain (DNS rebinding) is refused.
        """
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host in ("localhost", COMPUTER_NAME, f"{COMPUTER_NAME}.local"):
            return True
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    def do_GET(self):
        if not self.from_this_page():
            return self.send_error(403)
        url = urlsplit(self.path)
        if url.path == "/":
            self.path = "/app.html"
        elif url.path == "/api/qr":
            return self.send_json(self.qr(parse_qs(url.query).get("url", [""])[0].strip()))
        super().do_GET()

    def qr(self, link: str) -> dict:
        reason = check_row("-", link)
        if reason:
            return {"error": reason}
        try:
            svg, version = make_qr_svg(link)
        except ValueError as error:
            return {"error": str(error)}
        return {"svg": svg, "note": DENSE_QR_NOTE if version > MAX_QR_VERSION else ""}

    def do_POST(self):
        # JSON only: browsers will not send it cross-site without permission, which this server never gives.
        if not self.from_this_page() or self.headers.get("Content-Type") != "application/json":
            return self.send_error(403)
        if self.path != "/api/generate":
            return self.send_error(404)
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send_error(400)

        clinics = [
            {field: " ".join(str(clinic.get(field, "")).split()) for field in FIELDS}
            for clinic in data.get("clinics", [])
        ]

        # One line of JSON per clinic as it finishes, carrying its PDF for the browser to download.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.end_headers()

        def send_line(message):
            self.wfile.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
            self.wfile.flush()

        try:
            # PDFs are made in a private folder per export, so two people never overwrite each other's files.
            with GENERATING, tempfile.TemporaryDirectory() as folder:
                for number, pdf, notes in generate(enumerate(clinics, start=1), Path(folder)):
                    message = {"row": number, "file": None, "notes": notes}
                    if pdf:
                        message.update(file=pdf.name, pdf=base64.b64encode(pdf.read_bytes()).decode())
                    send_line(message)
        except ConnectionError:  # the page was closed mid-run
            pass
        except Exception as error:
            send_line({"error": str(error) or type(error).__name__})


def main():
    open_browser = "--no-browser" not in sys.argv
    try:
        # Only static/ is served as files; the code stays private.
        server = Server(("0.0.0.0", PORT), partial(Handler, directory=str(STATIC)))
    except OSError:
        print(f"Already running at {LOCAL_ADDRESS}")
        if open_browser:
            webbrowser.open(LOCAL_ADDRESS)
        return
    print("Sticker generator running (Ctrl+C to stop)")
    print(f"  On this computer:    {LOCAL_ADDRESS}")
    address = network_address()
    if address:
        print(f"  On the same network: http://{address}:{PORT}")
    if open_browser:
        webbrowser.open(LOCAL_ADDRESS)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
