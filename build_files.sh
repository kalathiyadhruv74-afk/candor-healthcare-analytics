#!/bin/bash
set -e

echo "=== Vercel Python Build Starting ==="

# Check python version
python3 --version || python --version

# Upgrade pip and install requirements
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

# Run collectstatic with dummy environment to ensure no DB connection needed during build
echo "=== Running Django collectstatic ==="
USE_LIVE_DO_MYSQL=0 python3 manage.py collectstatic --noinput --clear || python manage.py collectstatic --noinput --clear

echo "=== Build Completed Successfully ==="
