#!/bin/sh
# Runs on every container start, in both dev and prod — the only difference is
# the command it execs afterwards.
set -eu

# `migrate` with no --database targets `default` (portal). config/db_router.py
# refuses the `kb` alias outright, so the read-only rule holds even here
# (docs/adr/002).
echo "Applying portal migrations..."
python manage.py migrate --noinput

exec "$@"
