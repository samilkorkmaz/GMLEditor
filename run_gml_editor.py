"""PyInstaller entry point.

PyInstaller packages a script, not a ``python -m package`` invocation, so this
thin wrapper just calls the CLI. Command-line arguments are read from sys.argv
exactly as when run via ``python -m gml_editor``.
"""

import sys

from gml_editor.cli import main

if __name__ == "__main__":
    sys.exit(main())
