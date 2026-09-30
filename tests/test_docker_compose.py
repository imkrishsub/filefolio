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


def test_time_zone_is_passed_into_the_container():
    # Without TZ the container runs in UTC, so upload times and stored
    # filenames are off by the user's offset. README documents TZ in .env.
    assert re.search(r"^\s*-\s*TZ=\$\{TZ:-UTC\}\s*$", COMPOSE, re.MULTILINE)


def test_image_installs_time_zone_data():
    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text()
    assert re.search(r"^\s*tzdata\s*\\?$", dockerfile, re.MULTILINE)
