"""Page for entering clinics and generating their stickers: python app.py

Opens http://127.0.0.1:8765 in the browser. The list is kept in clinics.csv,
the same file generate.py reads. Only this computer can reach the page.
"""

import csv
import json
import os
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from generate import (
    DENSE_QR_NOTE, MAX_QR_VERSION, OUTPUT, ROOT, check_row, generate, make_qr_svg, read_rows,
)

CSV_PATH = ROOT / "clinics.csv"
FIELDS = ["name_bn", "url", "slug"]
PORT = 8765
ADDRESS = f"http://127.0.0.1:{PORT}"
GENERATING = threading.Lock()  # one batch at a time, even with the page open in two tabs


def load_clinics() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    return [{field: row.get(field, "") for field in FIELDS} for _, row in read_rows(CSV_PATH)]


def save_clinics(clinics: list[dict]):
    # utf-8-sig so Excel also shows the Bengali names correctly
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(clinics)


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
        """False for requests another website makes the browser send here."""
        return self.headers.get("Host") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def do_GET(self):
        if not self.from_this_page():
            return self.send_error(403)
        url = urlsplit(self.path)
        if url.path == "/":
            self.path = "/app.html"
        elif url.path == "/api/clinics":
            try:
                return self.send_json(load_clinics())
            except SystemExit as error:  # read_rows: the file lacks a column
                return self.send_json({"error": str(error)}, 500)
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
        if not self.from_this_page() or self.headers.get("Content-Type") != "application/json":
            return self.send_error(403)
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

        if self.path == "/api/open":
            OUTPUT.mkdir(exist_ok=True)
            os.startfile(OUTPUT)
            return self.send_json({})
        if self.path not in ("/api/clinics", "/api/generate"):
            return self.send_error(404)

        clinics = [
            {field: " ".join(str(clinic.get(field, "")).split()) for field in FIELDS}
            for clinic in data.get("clinics", [])
        ]
        save_clinics(clinics)
        if self.path == "/api/clinics":
            return self.send_json({})

        # One line of JSON per clinic as it finishes, so the page can show progress.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.end_headers()

        def send_line(message):
            self.wfile.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
            self.wfile.flush()

        try:
            with GENERATING:
                for number, out_dir, notes in generate(enumerate(clinics, start=1)):
                    send_line({"row": number, "folder": out_dir.name if out_dir else None, "notes": notes})
        except ConnectionError:  # the page was closed mid-run
            pass
        except Exception as error:
            send_line({"error": str(error) or type(error).__name__})


def main():
    open_browser = "--no-browser" not in sys.argv
    try:
        # Threaded: a browser's idle spare connection must not hold up the page's requests.
        server = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(ROOT)))
    except OSError:
        print(f"Already running at {ADDRESS}")
        if open_browser:
            webbrowser.open(ADDRESS)
        return
    print(f"Sticker generator running at {ADDRESS} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(ADDRESS)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
