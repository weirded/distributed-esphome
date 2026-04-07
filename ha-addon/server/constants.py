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
