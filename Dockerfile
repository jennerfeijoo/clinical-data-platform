FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade \
        pip \
        "setuptools>=83" \
        "wheel>=0.46.2" \
    && /opt/venv/bin/python -m pip install --no-cache-dir .

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN python -m pip uninstall -y \
        pip \
        setuptools \
        wheel \
        msgpack \
        jaraco.context \
        || true \
    && rm -rf \
        /usr/local/bin/pip* \
        /usr/local/lib/python3.11/site-packages/pip* \
        /usr/local/lib/python3.11/site-packages/setuptools* \
        /usr/local/lib/python3.11/site-packages/_distutils_hack \
        /usr/local/lib/python3.11/site-packages/wheel* \
        /usr/local/lib/python3.11/site-packages/msgpack* \
        /usr/local/lib/python3.11/site-packages/jaraco*

COPY --from=builder /opt/venv /opt/venv
COPY data ./data
COPY sql ./sql

ENTRYPOINT ["clinical-data"]
CMD ["--help"]
