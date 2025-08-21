#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

def main():
    # Add "<project>/backend" to PYTHONPATH so "core" is importable
    BASE_DIR = Path(__file__).resolve().parent
    sys.path.insert(0, str(BASE_DIR / "backend"))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)

if __name__ == "__main__":
    main()
