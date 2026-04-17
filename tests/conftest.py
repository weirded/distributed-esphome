"""pytest configuration — adds source paths to sys.path."""
import sys
from pathlib import Path

# Server modules
sys.path.insert(0, str(Path(__file__).parent.parent / "ha-addon" / "server"))
# Client modules
sys.path.insert(0, str(Path(__file__).parent.parent / "ha-addon" / "client"))
# HA custom integration lives under ha-addon/custom_integration/ so the
# add-on's Dockerfile can COPY it into the container. Tests import it as
# `esphome_fleet.*` — the enclosing directory goes on sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent / "ha-addon" / "custom_integration"))


