FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

COPY pyproject.toml README.md build_backend.py ./
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

FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME="/home/clinical" \
    XDG_CACHE_HOME="/tmp/.cache" \
    XDG_CONFIG_HOME="/tmp/.config"

WORKDIR /app

RUN rm -rf \
        /usr/local/bin/pip* \
        /usr/local/lib/python3.11/ensurepip \
        /usr/local/lib/python3.11/site-packages/*

COPY --from=builder --chown=0:0 /opt/venv /opt/venv
COPY --chown=0:0 data/sample ./data/sample
COPY --chown=0:0 sql ./sql

RUN groupadd --gid 10001 clinical \
    && useradd \
        --uid 10001 \
        --gid 10001 \
        --home-dir /home/clinical \
        --create-home \
        --shell /usr/sbin/nologin \
        clinical \
    && mkdir -p \
        /app/data/raw \
        /app/data/processed \
        /app/data/analytics \
    && chown -R 0:0 /opt/venv /app \
    && chmod -R a-w /opt/venv /app \
    && chown -R 10001:10001 \
        /home/clinical \
        /app/data/raw \
        /app/data/processed \
        /app/data/analytics \
    && chmod 0700 /home/clinical \
    && chmod 0750 \
        /app/data/raw \
        /app/data/processed \
        /app/data/analytics \
    && find /usr /bin /sbin -xdev -type f -perm /6000 -exec chmod a-s {} +

USER 10001:10001

ENTRYPOINT ["clinical-data"]
CMD ["--help"]
