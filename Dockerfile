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
    && /opt/venv/bin/python -m pip install --no-cache-dir . \
    && /opt/venv/bin/python -m pip uninstall -y \
        pip \
        setuptools \
        wheel \
    && rm -rf \
        /opt/venv/bin/pip* \
        /opt/venv/lib/python3.11/site-packages/pip* \
        /opt/venv/lib/python3.11/site-packages/setuptools* \
        /opt/venv/lib/python3.11/site-packages/_distutils_hack \
        /opt/venv/lib/python3.11/site-packages/wheel*

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN rm -rf \
        /usr/local/bin/pip* \
        /usr/local/lib/python3.11/ensurepip \
        /usr/local/lib/python3.11/site-packages/*

COPY --from=builder /opt/venv /opt/venv
COPY data ./data
COPY sql ./sql

ENTRYPOINT ["clinical-data"]
CMD ["--help"]
