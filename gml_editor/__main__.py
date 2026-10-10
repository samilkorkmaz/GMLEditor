"""Enable ``python -m gml_editor <file.gml>``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
