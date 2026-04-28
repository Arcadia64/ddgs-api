FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    ddgs fastapi uvicorn requests beautifulsoup4 lxml \
    "curl_cffi>=0.7" \
    playwright "playwright-stealth>=2.0.0" \
    "camoufox[geoip]"

# Install Chromium (fallback), real Google Chrome (preferred), and Camoufox (anti-bot Firefox fork)
RUN playwright install --with-deps chromium chrome
RUN python3 -m camoufox fetch

COPY app/main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
