# Knowledge Service V1 Design Review

@hiroleague/docs/knowledge-service-v1-design.md review the implmentation for quality design and quality implementation, correctness and completeness. group and sort your feedback by severity. do not list compliance, only list problems that require change/fix.

# Answer

I've reviewed the design document and the implementation across the service layer, agent graph, vector store, catalog, embedders, tools, runtime manager, admin routes, and the Svelte page. Below is a severity-grouped list of problems requiring change/fix.


## Medium

- **`detailTagsText` is sourced from `chunks[0].tags` rather than the document row.** For a document in `failed` / `embedding` status with no chunks yet, the tag editor in the drawer always shows an empty string regardless of stored tags. Pull tags from the document API instead.

  ```390:396:admin_frontend/src/lib/features/knowledge/KnowledgePage.svelte
    const payload = await getKnowledgeDocument(documentId);
    chunks = payload.data.chunks;
    const first = payload.data.chunks[0] as KnowledgeChunk | undefined;
    detailTagsText = Array.isArray(first?.tags) ? (first.tags as string[]).join(', ') : '';
  ```

- **`_collection_vector_size` returns `None` for any non-standard vector config and the caller falls through silently.** If `info.config.params.vectors` is a named-vector dict whose first value lacks `.size`, the function returns `None`, and `_ensure_collection`'s mismatch guard is skipped entirely. That's a possible quiet acceptance of an incompatible collection. Either raise on `None` (we wrote this collection, we know what shape it should have) or assert the expected shape up front.

  ```289:299:hiroserver/hirocli/src/hirocli/services/knowledge/vector_store.py
      @staticmethod
      def _collection_vector_size(client, collection_name) -> int | None:
          info = client.get_collection(collection_name)
          vectors = info.config.params.vectors
          if hasattr(vectors, "size"):
              return int(vectors.size)
          if isinstance(vectors, dict) and vectors:
              first = next(iter(vectors.values()))
              if hasattr(first, "size"):
                  return int(first.size)
          return None
  ```

- **SSE event-queue overflow silently drops events.** When a slow consumer fills the 100-event queue, `put_nowait` swallows the event with a single warning log. UI then misses `progress`/`completed`/`failed` transitions and won't recover until a manual refresh. Either bump the queue, drop intermediate progress only (keep terminal events), or make the queue blocking on a bounded back-pressure window.

  ```336:350:hiroserver/hirocli/src/hirocli/admin_svelte/routes/knowledge.py
      queue: asyncio.Queue[DomainEvent] = asyncio.Queue(maxsize=100)
      async def handler(event: DomainEvent) -> None:
          ...
          try:
              queue.put_nowait(event)
          except asyncio.QueueFull:
              log.warning("knowledge event stream queue full", event_type=event.type)
  ```

## Low

- **Double resolution of file concurrency.** `start_ingest` calls `_resolve_file_concurrency` and stores the value in `params`, then `_run_ingest_job` re-runs `bounded_file_concurrency(params.get("file_concurrency"), fallback=default_file_concurrency_for_embedder(self.embedder))` on the same value. Pick one resolution point.

- **`validate_category_assignment` runs both at job start and once per file** (`start_ingest` and `_upsert_document_and_vectors` via `CatalogStore`). Per-file is redundant since the params don't change inside the job.

- **`ensure_tags` is called twice in `_update_document_metadata_sync`.** Once inside `catalog.update_document_metadata`, again in the surrounding `_update_document_metadata_sync` before `sync_payload_metadata`.

- **`KnowledgeAgentState.hits` / `.sources` typed as `list[Any]`.** Concrete types (`list[KnowledgeSearchHit]`, `list[KnowledgeSource]`) exist and are exported; type the state with them.

- **`SourceScanner.scan` stats every file synchronously in the calling thread** (it's wrapped in `to_thread` so it doesn't block the loop, but a single scan still blocks the threadpool slot for large trees). Consider `os.scandir` for stat info and yielding control periodically, or document the max tree size.

- **`scroll_document_chunks` caps at 500 by clamping `limit`** while the service-level caller defaults to 100. A document chunked above 500 will show truncated chunks in the detail drawer with no pagination cursor or warning.

- **`KnowledgeListDocumentsResult.documents` ordering is fixed to `COALESCE(ingested_at, updated_at) DESC`.** No order parameter is accepted by `list_documents`; Tab 3's "Sort by any column" cannot be implemented without changing this contract.

- **Per-call SQLite connections.** Every catalog method opens a fresh `sqlite3.connect(self.db_path)`. For an ingest job, that's dozens of connections per file. Reuse a connection (or pool) for the duration of `_run_ingest_job`.

- **Embedding reload reactor has no unit/integration test.** `_embedding_reload_reactor` runs `resolve_knowledge_embedder` on a thread and calls `reload_embedder`, but `test_service.py` covers only the lock raise via `save_preferences`. The reload path is the harder code (it touches credential stores and may swap into an empty collection); add a test.

- **CLI `knowledge search` formats only a fixed subset of fields.** It silently drops `owner_id`, `category_id`, `subcategory_id`, `score` decimals beyond 3 places — minor display issue.

- **`KnowledgePage.svelte` filter inputs trigger `loadDocuments` on every keystroke** (`oninput={() => void loadDocuments()}`). With workspaces of a few hundred docs this is fine, but debouncing is worth adding now to avoid request storms later.

- **`_pick_folder_dialog` instantiates `tk.Tk()` per call** and runs `root.destroy()` in the `finally` — fine for one shot, but it's also blocking; a server-wide concurrent click would serialize on the threadpool. Acceptable for v1 if dialog is rare, but document.

---
