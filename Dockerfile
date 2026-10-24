# Playwright's image comes with Chromium and everything it needs to render the PDFs.
# Keep its version the same as playwright in requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV BROWSER_CHANNEL=chromium \
    PYTHONUNBUFFERED=1
USER pwuser
EXPOSE 8765
CMD ["python", "app.py", "--no-browser"]
