# Gap 278 — Chroma connect timeout + RAG startup warm-up (senior-dev)

- [x] Read Gap 278 entry in `be_features_tracker.md` in full (root cause: unbounded `chromadb.HttpClient` connect + inline bge-m3 cold load)
- [x] Read installed chromadb 1.5.9 API — confirm how a timeout can actually be passed
  - `chromadb.HttpClient(host, port, ssl, headers, settings, tenant, database)` — **no timeout param**
  - `chromadb/api/fastapi.py:86-92` hardcodes `httpx.Client(timeout=None, ...)`
  - `chromadb/config.py` has only server-side `chroma_{logservice,sysdb,query}_request_timeout_seconds` — nothing for the client session
  - `chromadb/api/client.py::Client.__init__` calls `get_user_identity()` → the hang happens **inside the constructor**, before `heartbeat()`
- [x] Implement bounded timeout in `chroma_client.py` (`_TimeoutBoundHttpx`, `_chroma_http_timeout()`, `_bounded_chroma_http_timeout()`, `_build_chroma_client()`)
- [x] Add `_chroma_lock` so concurrent first requests don't both construct
- [x] Add `warm_rag_dependencies()` in `chroma_client.py`
- [x] Add FastAPI lifespan in `main.py` (`lifespan()` + `_start_rag_warmup()`) starting the warm-up in a daemon thread (ACA startup probe budget is only 65s — must not block)
- [x] Add 5 tests in `tests/test_rag.py` (timeout injected at the real call site + chromadb call-site pin, timeout in force during construction + fast fallback, warm-up primes both singletons, warm-up survives dead Chroma, lifespan hook fires)
- [x] Negative check: stubbed the shim to a no-op → both timeout tests fail; reverted
- [x] `pytest tests/test_rag.py` → 56 passed
- [x] `pytest tests/test_api_keys.py tests/test_rag.py` → 78 passed (checks the new tests are hermetic w.r.t. the cached `get_settings()` / MOCK_EMBEDDINGS ordering trap)
- [x] Full top-level suite `pytest tests/test_*.py` → 733 passed, 6 skipped, 2 failed — both failures are pre-existing `test_connectors.py` redis-refused (localhost:6379 not running), reproduced identically running that module alone
- [x] Update `feature_6_rag.md` (File Coordinates + Gap 278 fix narrative)
- [x] Update Gap 278 tracker entry → `[x]` with what shipped + verification

Final status: complete. Fix + 5 tests + docs. Left uncommitted. Not yet deployed to dev — the live "first chat turn after a deploy is fast" confirmation still has to be taken from `ca-invoice-be-dev` logs after the next deploy.
