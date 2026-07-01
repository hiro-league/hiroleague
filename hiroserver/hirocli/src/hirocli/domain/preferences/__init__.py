"""Workspace preferences — models, persistence, and resolvers.

Split into submodules for readability; this package re-exports the public API so that
``from hirocli.domain.preferences import X`` keeps resolving exactly as before. The prose
defaults live in the sibling ``hirocli.domain.prompts`` package (loaded as markdown).
"""

from .defaults import *  # noqa: F401,F403
from .diff import *  # noqa: F401,F403
from .models import *  # noqa: F401,F403
from .io import *  # noqa: F401,F403
from .resolvers import *  # noqa: F401,F403
