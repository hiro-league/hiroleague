"""Runtime server components for hirocli.

All runtime modules receive a shared ``ServerContext`` (defined in
``server_context.py``) instead of individual workspace_path / config
parameters.  The composition root in ``server_process.py`` creates the
context, calls factory functions owned by each subsystem, and starts
the asyncio event loop.
"""
