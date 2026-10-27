# The container runs exactly the `waitarr` CLI the Python package
# installs. Two stages: Poetry and the build tooling never reach the
# runtime image, which receives a ready virtualenv at the same path.
#
# Renovate keeps the digest current; the tag says what it is. The Python
# version moves with the integration and publish jobs (renovate.json).
ARG PYTHON_IMAGE=python:3.15-slim@sha256:f786b2e19cf9bb54e96bfcd4c1b40c4c56336c22e60607ffd4b080ae5b5dee83

FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml poetry.lock README.md LICENSE ./
COPY src ./src

# The locked versions, not whatever PyPI resolves today: Poetry installs
# from poetry.lock into the virtualenv, then Waitarr itself, no deps.
ENV VIRTUAL_ENV=/opt/waitarr \
    PATH=/opt/waitarr/bin:$PATH \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1
RUN pip install "poetry>=2,<3" \
    && python -m venv /opt/waitarr \
    && poetry install --only main --no-root \
    && /opt/waitarr/bin/pip install --no-deps . \
    && /opt/waitarr/bin/pip uninstall --yes pip


FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION="0+unknown"
ARG REVISION="unknown"
ARG CREATED=""

LABEL org.opencontainers.image.title="Waitarr" \
      org.opencontainers.image.description="Throttle qBittorrent while something plays on Jellyfin, without pausing a single torrent." \
      org.opencontainers.image.source="https://github.com/LECOQQ/Waitarr" \
      org.opencontainers.image.url="https://github.com/LECOQQ/Waitarr" \
      org.opencontainers.image.documentation="https://github.com/LECOQQ/Waitarr/blob/main/README.md" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WAITARR_CONFIG=/config/waitarr.toml

COPY --from=builder /opt/waitarr /opt/waitarr
ENV PATH=/opt/waitarr/bin:$PATH

# Nothing installs at runtime: pip, and the copy ensurepip bundles, are
# only attack surface (`make vulns` flags their known vulnerabilities).
RUN /usr/local/bin/python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.*/ensurepip/_bundled

# Non-root. /data holds the state file and must survive the container.
RUN groupadd --gid 1000 waitarr \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin waitarr \
    && mkdir -p /data /config \
    && chown 1000:1000 /data

VOLUME ["/data"]
WORKDIR /data
USER 1000:1000
EXPOSE 8778

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ["waitarr", "status", "--quiet"]

ENTRYPOINT ["waitarr"]
CMD ["run"]
