FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade \
        pip \
        "setuptools>=83" \
        "wheel>=0.46.2" \
        "jaraco.context>=6.1.0" \
    && python -m pip install --no-cache-dir .

COPY data ./data
COPY sql ./sql

ENTRYPOINT ["clinical-data"]
CMD ["--help"]
