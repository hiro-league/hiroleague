"""Hello, the test app the core installs, upgrades and removes ("Installing apps", phase 5): the smallest app on the
backend kit that has what an installed app needs (a database with a migration, a health path, its UI inside its
package, a console script its service runs, the kit's predeploy).
"""

from pathlib import Path

import hiro_extension_kit

from .config import config
from .extension import EXTENSION

hiro_extension_kit.setup(name="hello", title="Hello", package=Path(__file__).parent,
                         data_dir=config.data_dir, static_dir=config.static_dir, extension=EXTENSION)
