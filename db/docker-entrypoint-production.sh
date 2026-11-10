#!/bin/bash
set -e

if [ -n "${MONGO_INITDB_ROOT_PASSWORD_FILE:-}" ]; then
    MONGO_INITDB_ROOT_PASSWORD="$(< "${MONGO_INITDB_ROOT_PASSWORD_FILE}")"
    export MONGO_INITDB_ROOT_PASSWORD
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
