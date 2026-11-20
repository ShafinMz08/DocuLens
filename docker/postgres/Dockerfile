FROM postgres:16-alpine

# pgvector is not available as an Alpine package compatible with the official
# Postgres image (which builds PostgreSQL from source under /usr/local), so we
# build pgvector v0.8.1 from source against the image's own pg_config.
RUN apk add --no-cache build-base wget \
    && wget -q https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.1.tar.gz -O /tmp/pgvector.tar.gz \
    && tar -xzf /tmp/pgvector.tar.gz -C /tmp \
    && make -C /tmp/pgvector-0.8.1 PG_CONFIG=/usr/local/bin/pg_config with_llvm=no \
    && make -C /tmp/pgvector-0.8.1 install PG_CONFIG=/usr/local/bin/pg_config with_llvm=no \
    && rm -rf /tmp/pgvector* /var/cache/apk/*

# Create the dedicated test database on fresh PostgreSQL initialization.
COPY --chmod=755 init/01-create-test-db.sh /docker-entrypoint-initdb.d/01-create-test-db.sh