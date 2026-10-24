"""Generate print-ready clinic stickers: python generate.py [clinics.csv]

For every row of the CSV (name_bn, url, slug) this writes output/<slug>.pdf:
one 18 x 12 in sheet with all three stickers. Without a slug the file is named
after the clinic. app.py is a page for the same job. The clinic name and QR
codes are vector in the PDF; the artwork is embedded at its full resolution.
"""

import csv
import os
import re
import sys
from pathlib import Path

import qrcode
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
STATIC = ROOT / "static"  # the page, the sticker template and the artwork it uses
TEMPLATE = STATIC / "template.html"
LOGO = STATIC / "medikzo-logo-qr.png"
OUTPUT = ROOT / "output"

# Browser that renders the PDFs: Edge, which comes with Windows. The Docker image uses Playwright's Chromium.
BROWSER_CHANNEL = os.environ.get("BROWSER_CHANNEL", "msedge")

# Printed size of the sheet. The artwork is 3072 x 2048 px, the same 3:2 shape.
SHEET_WIDTH_IN, SHEET_HEIGHT_IN = 18, 12
SHEET_WIDTH_PX = 3072

MAX_QR_VERSION = 10  # denser codes than this get a warning: small modules scan less reliably
DENSE_QR_NOTE = "long link makes a dense QR code; a shorter link scans more reliably"

LOGO_WIDTH = 0.38  # share of the QR width taken by the logo; matches .qr-logo in static/template.html


def make_qr_svg(url: str) -> tuple[str, int]:
    """QR code as SVG, on a transparent background, with a clear patch in the centre for the logo. Returns (svg, version)."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=0)
    qr.add_data(url)
    try:
        qr.make(fit=True)
    except (ValueError, qrcode.exceptions.DataOverflowError):
        raise ValueError("link is too long for a QR code") from None
    matrix = qr.get_matrix()
    n = len(matrix)

    with Image.open(LOGO) as logo:
        logo_w = n * LOGO_WIDTH
        logo_h = logo_w * logo.height / logo.width

    # Patch in whole modules (logo plus half a module of margin each side),
    # with the same parity as n so it sits centred on the module grid.
    def snap(size):
        modules = int(size + 1) + 1
        return modules + (modules - n) % 2

    patch_w, patch_h = snap(logo_w), snap(logo_h)
    left, top = (n - patch_w) // 2, (n - patch_h) // 2

    path = []
    for y, row in enumerate(matrix):
        x = 0
        while x < n:
            in_patch = top <= y < top + patch_h and left <= x < left + patch_w
            if row[x] and not in_patch:
                start = x
                while x < n and row[x] and not (
                    top <= y < top + patch_h and left <= x < left + patch_w
                ):
                    x += 1
                path.append(f"M{start} {y}h{x - start}v1h-{x - start}z")
            else:
                x += 1

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" '
        f'shape-rendering="crispEdges">'
        f'<path d="{"".join(path)}" fill="#000"/></svg>'
    ), qr.version


def read_rows(csv_path: Path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = {(h or "").strip().lower() for h in reader.fieldnames or []}
        missing = {"name_bn", "url"} - headers
        if missing:
            sys.exit(f"{csv_path.name}: missing column(s): {', '.join(sorted(missing))}")
        for number, row in enumerate(reader, start=1):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            yield number, row


def check_row(name: str, url: str) -> str | None:
    """Reason this row cannot be turned into a sticker, or None if it is fine."""
    if not name:
        return "name_bn is empty"
    if not url:
        return "url is empty"
    if not re.match(r"https?://", url, re.IGNORECASE):
        return "url must start with http:// or https://"
    if re.search(r"\s", url):
        return "url contains a space"
    return None


def file_name(text: str) -> str:
    """Text with the characters Windows does not allow in a file name replaced."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", text).strip(" .-")


def generate(rows, output_dir: Path = OUTPUT):
    """Make the stickers for (number, row) pairs, as read_rows gives them, into output_dir.

    Yields (number, pdf, notes) for every row: pdf is the path of its sheet,
    or None when the row was skipped; notes say why, or what to check.
    """
    used_slugs = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=BROWSER_CHANNEL)
        page = browser.new_page()
        page.goto(TEMPLATE.as_uri())

        for number, row in rows:
            name = " ".join(row.get("name_bn", "").split())
            url = row.get("url", "")
            reason = check_row(name, url)
            if reason:
                yield number, None, [f"skipped: {reason}"]
                continue
            notes = []

            # File name: the slug, or the clinic name without one; unique within this run.
            slug = file_name(row.get("slug", "")) or file_name(name) or f"clinic-{number}"
            if slug.lower() in used_slugs:
                base, n = slug, 2
                while slug.lower() in used_slugs:
                    slug, n = f"{base}-{n}", n + 1
                notes.append(f"slug '{base}' already used, saved as '{slug}'")
            used_slugs.add(slug.lower())

            try:
                svg, version = make_qr_svg(url)
                if not page.evaluate("([name, qr]) => setSticker(name, qr)", [name, svg]):
                    yield number, None, notes + ["skipped: name is too long to fit on the sticker"]
                    continue
                if version > MAX_QR_VERSION:
                    notes.append(DENSE_QR_NOTE)

                output_dir.mkdir(exist_ok=True)
                pdf = output_dir / f"{slug}.pdf"
                page.pdf(
                    path=pdf,
                    width=f"{SHEET_WIDTH_IN}in",
                    height=f"{SHEET_HEIGHT_IN}in",
                    scale=SHEET_WIDTH_IN * 96 / SHEET_WIDTH_PX,
                    print_background=True,
                )
            except Exception as error:  # keep the batch going; report the row at the end
                yield number, None, notes + [f"skipped: {error or type(error).__name__}"]
                continue
            yield number, pdf, notes

        browser.close()


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "clinics.csv"
    problems = []  # (row number, message)
    done = 0

    for number, pdf, notes in generate(read_rows(csv_path)):
        problems += [(number, note) for note in notes]
        if pdf:
            done += 1
            print(f"row {number}: {pdf}")

    print(f"\n{done} clinic(s) generated.")
    if problems:
        print("Needs attention:")
        for number, message in problems:
            print(f"  row {number}: {message}")
        sys.exit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
