#!/usr/bin/env python3
"""Execute with fixed VM configuration; never evaluate it as shell code."""

import os
import re
import shlex
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: with-config.py CONFIG COMMAND [ARG...]")
    path = Path(sys.argv[1])
    if not path.is_absolute():
        raise SystemExit("Production configuration must have an absolute path.")
    values = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, raw = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            raise SystemExit(f"Invalid configuration entry at line {number}.")
        if "$" in raw or "\\" in raw or "\x00" in raw:
            raise SystemExit(f"Unsupported configuration syntax at line {number}.")
        tokens = shlex.split(raw)
        if len(tokens) > 1:
            raise SystemExit(f"Quote values containing spaces at line {number}.")
        values[name] = tokens[0] if tokens else ""
    values.update(os.environ)
    values["APP_ENV"] = "production"
    values["PYTHON_DOTENV_DISABLED"] = "1"
    os.execvpe(sys.argv[2], sys.argv[2:], values)


if __name__ == "__main__":
    main()
