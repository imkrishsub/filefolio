"""Checks on docker-compose.yml — the file the README's Docker quick start runs."""

import re
from pathlib import Path

COMPOSE = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text()


def test_host_port_follows_the_port_variable():
    # README documents `PORT=8080 docker compose up`.
    assert '"${PORT:-8000}:8000"' in COMPOSE


def test_port_is_not_passed_into_the_container():
    # The container must keep listening on 8000 (Dockerfile ENV PORT=8000),
    # or the mapping above would point at nothing.
    assert not re.search(r"^\s*-\s*PORT=", COMPOSE, re.MULTILINE)
