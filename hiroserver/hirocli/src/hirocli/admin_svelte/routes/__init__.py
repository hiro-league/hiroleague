"""Sub-routers for the Svelte admin API (split from ``api`` by domain).

``events`` holds SSE/long-lived streams; other modules are CRUD-style HTTP handlers.
Workspace-scoped handlers use ``SelectedWorkspaceIdDep`` in ``admin_svelte.deps``.
"""
