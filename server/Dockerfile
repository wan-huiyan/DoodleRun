# DoodleRun API container.
#
# Build context is the repo root so we can copy both server/ and prototype/:
#     docker build -t doodlerun-server -f server/Dockerfile .
#     docker run -p 8000:8000 doodlerun-server
#
# For corporate TLS-inspected networks, mount or copy a CA bundle and set:
#     -e DOODLERUN_CA_BUNDLE=/etc/ssl/corp-ca.pem -v $PWD/corp.pem:/etc/ssl/corp-ca.pem:ro
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so layer cache survives source edits.
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# Copy source. server/ imports prototype/ via sys.path at runtime, so both
# directories must be present.
COPY prototype/ /app/prototype/
COPY server/ /app/server/

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
