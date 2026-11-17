"""The core's constants for the workspace knowledge service: where its files live, its limits, its events.

The engine's own constants (the collection's shape, default models, batch and chunk sizes) are in
``hiro_memory.knowledge.constants``.
"""

from __future__ import annotations

KNOWLEDGE_DIR = "knowledge"
DB_FILENAME = "knowledge.db"
QDRANT_DIR = "qdrant"
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
PREVIEW_MAX_BYTES = 2 * 1024 * 1024

KNOWLEDGE_JOB_STARTED = "knowledge.job.started"
KNOWLEDGE_JOB_PROGRESS = "knowledge.job.progress"
KNOWLEDGE_JOB_COMPLETED = "knowledge.job.completed"
KNOWLEDGE_JOB_FAILED = "knowledge.job.failed"
KNOWLEDGE_INGESTED = "knowledge.ingested"
KNOWLEDGE_DELETED = "knowledge.deleted"
# The graph's live-update event names live in ``hiro_memory.graph.constants``.
