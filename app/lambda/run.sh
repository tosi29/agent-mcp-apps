#!/bin/sh
set -eu
cd "${LAMBDA_TASK_ROOT:-/var/task}"
exec node server.js
