#!/bin/sh
set -e

cd /uis/website && npm run dev -- -p 3000 &
cd /uis/backoffice && npm run dev -- -p 3001 &

wait