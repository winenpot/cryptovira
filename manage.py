#!/usr/bin/env python
"""Django's command-line utility.

Run it through uv so the interpreter and dependencies always match ``uv.lock``:

    uv run manage.py <command>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    # src-layout: keep the package importable even when the project isn't installed.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cryptovira.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
