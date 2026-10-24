# Clinic Sticker Generator

Makes print-ready Medikzo clinic stickers. For each clinic it writes one PDF:
an 18 × 12 in sheet with all three stickers, the clinic's Bengali name and a
QR code linking to its profile. The name and QR codes are vector, so they stay
sharp at any print size.

## Requirements

- Windows with Microsoft Edge (used to render the PDFs)
- Python 3.10 or newer

## Setup

```
pip install -r requirements.txt
```

## Usage

On the computer that hosts the app, double-click **start.bat** (or run
`python app.py`). It shows two addresses:

- **On this computer:** <http://127.0.0.1:8765>
- **On the same network:** for example `http://192.168.0.177:8765`. Open this
  one on any other PC or phone connected to the same Wi-Fi or office network.

The first time it starts, Windows Firewall asks whether to allow Python. Tick
**Private networks** so the other computers can connect.

Then, on any computer:

1. Enter each clinic's name, profile link and, optionally, a file name.
   You can paste the columns straight from Excel or Google Sheets.
2. Check the live preview on the right.
3. Click **Generate stickers**. Each PDF downloads to that computer's
   Downloads folder. With several clinics, the browser may ask once to allow
   multiple downloads.

Each browser keeps its own clinic list, so people don't overwrite each other.
Exports run one at a time; if someone else is exporting, yours starts when
theirs finishes. The host computer must stay on with the app running.

To generate from the command line instead (no page needed):

```
python generate.py [clinics.csv]
```

This writes the PDFs to `output/` on the host computer.

The CSV has the columns `name_bn`, `url` and `slug` (optional file name).

## Running with Docker

On a Linux computer with Docker, the app can run in a container instead,
without installing Python or Edge:

```
docker compose up -d --build
```

`docker compose logs` shows the two addresses, the same as above. The app
starts again when the computer restarts. To stop it: `docker compose down`.

The container uses the computer's own network (host networking), so the page
is on port 8765 of the computer, as with `python app.py`. If a firewall is on,
allow that port, for example `sudo ufw allow 8765/tcp`. The PDFs are rendered
with Chromium instead of Edge.

## Project layout

```
app.py              web server for the page (this computer and the local network)
generate.py         QR codes and PDF rendering
start.bat           starts the app
Dockerfile          container image for the app
compose.yaml        runs the container on the local network
static/
  app.html          the page
  template.html     the sticker sheet layout
  clinic-sticker.png  sheet artwork (3072 × 2048 px)
  medikzo-logo-qr.png logo in the centre of the QR codes
  medikzo-stickers.svg  app logo shown in the page header
  favicon.svg       browser tab icon
  fonts/            Noto Sans Bengali (SIL Open Font License)
```

To move the name or QR codes on the sheet, edit the positions at the top of
`static/template.html`. They are in pixels on the artwork.
