"""Generate print-ready clinic stickers: python generate.py [clinics.csv]

For every row of the CSV (name_bn, url, slug) this writes
output/<slug>/portrait.pdf, landscape-1.pdf and landscape-2.pdf.
The clinic name and QR code are vector in the PDF; the artwork is embedded
at its full resolution.
"""

import csv
import re
import sys
from pathlib import Path

import qrcode
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
TEMPLATE = ROOT / "template.html"
LOGO = ROOT / "medikzo-logo-qr.png"
OUTPUT = ROOT / "output"
STICKERS = ["portrait", "landscape-1", "landscape-2"]

# Physical size of the PDF pages: artwork pixels per inch. At 300 the portrait
# sticker is 105 x 169 mm. PDFs can be scaled at print time; this is the size
# at which the background artwork is still fully sharp.
PRINT_DPI = 300

MAX_QR_VERSION = 10  # denser codes than this get a warning: small modules scan less reliably

LOGO_WIDTH = 0.38  # share of the QR width taken by the logo; matches .qr-logo in template.html


def make_qr_svg(url: str) -> tuple[str, int]:
    """QR code as SVG, with a white patch in the centre for the logo. Returns (svg, version)."""
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
        f'<rect width="{n}" height="{n}" fill="#fff"/>'
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


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "clinics.csv"
    problems = []  # (row number, message)
    used_slugs = set()
    done = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page()
        page.goto(TEMPLATE.as_uri())

        for number, row in read_rows(csv_path):
            name = " ".join(row.get("name_bn", "").split())
            url = row.get("url", "")
            reason = check_row(name, url)
            if reason:
                problems.append((number, f"skipped: {reason}"))
                continue

            # Folder name: letters, digits, - and _ only, and unique within this run.
            slug = re.sub(r"[^\w-]+", "-", row.get("slug", "")).strip("-") or f"clinic-{number}"
            if slug.lower() in used_slugs:
                base, n = slug, 2
                while slug.lower() in used_slugs:
                    slug, n = f"{base}-{n}", n + 1
                problems.append((number, f"slug '{base}' already used, saved as '{slug}'"))
            used_slugs.add(slug.lower())

            try:
                svg, version = make_qr_svg(url)
                if not page.evaluate("([name, qr]) => setSticker(name, qr)", [name, svg]):
                    problems.append((number, "skipped: name is too long to fit on the sticker"))
                    continue
                if version > MAX_QR_VERSION:
                    problems.append((number, "long link makes a dense QR code; a shorter link scans more reliably"))

                out_dir = OUTPUT / slug
                out_dir.mkdir(parents=True, exist_ok=True)
                for sticker in STICKERS:
                    size = page.evaluate("id => showOnly(id)", sticker)
                    page.pdf(
                        path=out_dir / f"{sticker}.pdf",
                        width=f"{size['width'] / PRINT_DPI}in",
                        height=f"{size['height'] / PRINT_DPI}in",
                        scale=96 / PRINT_DPI,
                        print_background=True,
                    )
            except Exception as error:  # keep the batch going; report the row at the end
                problems.append((number, f"skipped: {error or type(error).__name__}"))
                continue
            done += 1
            print(f"row {number}: {slug} -> {out_dir}")

        browser.close()

    print(f"\n{done} clinic(s) generated.")
    if problems:
        print("Needs attention:")
        for number, message in problems:
            print(f"  row {number}: {message}")
        sys.exit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
