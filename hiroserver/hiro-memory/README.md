# hiro-memory

Hiro's memory engine, shared by the HiroLeague core and EvalHiro: the Graphiti temporal graph on Kuzu,
conversation memory and its recall agent, and the run ledger that prices and traces every step.

The library never imports the core. Whoever uses it hands in what it needs: the model clients (a
`model_builder`), the embedder and reranker, the settings values, and the callbacks for events and AI usage.
