"""Shared constants for the server application."""

# HA Supervisor internal IP — used for Ingress trust authentication
HA_SUPERVISOR_IP = "172.30.32.2"

# HTTP headers
HEADER_AUTHORIZATION = "Authorization"
HEADER_X_SERVER_VERSION = "X-Server-Version"
HEADER_X_CLIENT_ID = "X-Client-Id"
HEADER_X_WORKER_ID = "X-Worker-Id"
HEADER_X_INGRESS_PATH = "X-Ingress-Path"

# File names
SECRETS_YAML = "secrets.yaml"

# Minimum client Docker image version the server expects. Workers reporting an
# older image_version (or missing one) will be flagged in the UI and will NOT
# receive source-code auto-update payloads — updating .py files in place can't
# fix a stale image (missing system packages, old Python, old requirements).
# Bump this when a change in the client Dockerfile requires workers to rebuild
# their image (e.g. adding a new system dep or Python library).
MIN_IMAGE_VERSION = "5"
