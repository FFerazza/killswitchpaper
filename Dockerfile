# Reproducible environment for the pipeline, including libbgpstream (Stage 2).
# bullseye, not bookworm: libbgpstream 2.2.0 uses pthread_yield, which was
# removed in glibc 2.34.
FROM python:3.11-slim-bullseye

# libbgpstream: build from source (Debian has no packaged libbgpstream2).
# wandio also from source: Debian's libwandio is older than the >=4.2.0
# (with HTTP support) that libbgpstream's configure requires.
ARG WANDIO_VERSION=4.2.7-1
ARG BGPSTREAM_VERSION=2.2.0
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates file autoconf automake libtool \
        zlib1g-dev libbz2-dev liblzma-dev libzstd-dev \
        libcurl4-openssl-dev librdkafka-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://github.com/LibtraceTeam/wandio/archive/refs/tags/${WANDIO_VERSION}.tar.gz" \
        | tar -xz -C /tmp \
    && cd /tmp/wandio-${WANDIO_VERSION} \
    && ./bootstrap.sh && ./configure && make -j"$(nproc)" && make install && ldconfig \
    && rm -rf /tmp/wandio-${WANDIO_VERSION}

RUN curl -fsSL -o /tmp/libbgpstream.tar.gz \
        "https://github.com/CAIDA/libbgpstream/releases/download/v${BGPSTREAM_VERSION}/libbgpstream-${BGPSTREAM_VERSION}.tar.gz" \
    && tar -xzf /tmp/libbgpstream.tar.gz -C /tmp \
    && cd /tmp/libbgpstream-${BGPSTREAM_VERSION} \
    && ./configure && make -j"$(nproc)" && make install && ldconfig \
    && rm -rf /tmp/libbgpstream*

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        requests PyYAML pandas pyarrow py-radix pytest \
    && pip install --no-cache-dir pybgpstream

COPY config/ config/
COPY src/ src/
COPY tests/ tests/
COPY Makefile ./

# data/ and outputs/ are bind-mounted at run time (see RUNNING.md).
ENTRYPOINT ["python"]
