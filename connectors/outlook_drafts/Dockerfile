FROM python:3.12-slim

# Run as an unprivileged user. The audit volume must be writable by uid 10001.
RUN useradd --create-home --uid 10001 app
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=120 --retries 10 -r requirements.txt
COPY outlook_drafts ./outlook_drafts

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["python", "-m", "outlook_drafts.server"]
