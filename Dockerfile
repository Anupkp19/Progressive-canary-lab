FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY cmd ./cmd
COPY internal ./internal

# SERVICE build arg selects which service to run (e.g. app, flag-service, router, etc.)
ARG SERVICE
ENV SERVICE=${SERVICE}

EXPOSE 8080

CMD ["sh", "-c", "python cmd/${SERVICE}/main.py"]
