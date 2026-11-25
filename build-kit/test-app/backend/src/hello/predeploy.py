"""An upgrade's copy and trial: `python -m hello.predeploy snapshot|trial|restore <stamp>` (the kit's steps)."""

import sys

import hello  # noqa: F401  (tells the kit which app this is: DATA_DIR/hello.db)
from hiro_extension_kit.predeploy import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
