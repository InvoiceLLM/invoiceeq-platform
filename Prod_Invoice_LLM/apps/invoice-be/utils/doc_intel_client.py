"""Round-robins Document Intelligence calls across multiple configured
resources (Gap 41/42, Jul 2026).

Each S0 Doc Intelligence resource has its own independent rate limit (15
req/10s, ~90/min) - unlike Azure OpenAI, there's no shared regional quota
pool to raise instead, so horizontal scale-out via multiple resources is
the effective lever. 3 resources combined = ~270 req/min vs. a single
resource's ~90/min.

Endpoint/key pairs are read from config.py::Settings, merging two sources
so both local .env convenience and Container Apps' per-secret env-var
wiring work: (1) comma-separated AZURE_DOC_INTEL_ENDPOINTS/KEYS, and
(2) numbered AZURE_DOC_INTEL_ENDPOINT_2/_KEY_2, _3/_3, ... (Container Apps
can't join multiple Key Vault secretRefs into one comma-separated value
declaratively, so each additional resource gets its own numbered pair).
Adding a resource beyond the numbered slots defined in config.py requires
adding one more _N pair there; anything already using the comma-separated
form needs no code change at all.
"""
import itertools
import threading

from config import Settings


def _collect_endpoint_key_pairs(settings: Settings) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    if settings.AZURE_DOC_INTEL_ENDPOINT and settings.AZURE_DOC_INTEL_KEY:
        pairs.append((settings.AZURE_DOC_INTEL_ENDPOINT, settings.AZURE_DOC_INTEL_KEY))

    if settings.AZURE_DOC_INTEL_ENDPOINTS and settings.AZURE_DOC_INTEL_KEYS:
        endpoints = [e.strip() for e in settings.AZURE_DOC_INTEL_ENDPOINTS.split(",") if e.strip()]
        keys = [k.strip() for k in settings.AZURE_DOC_INTEL_KEYS.split(",") if k.strip()]
        pairs.extend(zip(endpoints, keys))

    for endpoint_attr, key_attr in (
        ("AZURE_DOC_INTEL_ENDPOINT_2", "AZURE_DOC_INTEL_KEY_2"),
        ("AZURE_DOC_INTEL_ENDPOINT_3", "AZURE_DOC_INTEL_KEY_3"),
    ):
        endpoint = getattr(settings, endpoint_attr, "")
        key = getattr(settings, key_attr, "")
        if endpoint and key:
            pairs.append((endpoint, key))

    # De-dupe while preserving order (a resource configured via both the
    # comma-separated and numbered forms shouldn't get double weight).
    seen = set()
    deduped = []
    for pair in pairs:
        if pair not in seen:
            seen.add(pair)
            deduped.append(pair)
    return deduped


class DocIntelPool:
    """Thread-safe round-robin over configured Doc Intelligence resources."""

    def __init__(self, settings: Settings):
        self._pairs = _collect_endpoint_key_pairs(settings)
        if not self._pairs:
            raise ValueError("Azure Document Intelligence credentials (endpoint or key) are missing in settings.")
        self._cycle = itertools.cycle(self._pairs)
        self._lock = threading.Lock()

    @property
    def resource_count(self) -> int:
        return len(self._pairs)

    def next_endpoint_key(self) -> tuple[str, str]:
        with self._lock:
            return next(self._cycle)


_pool: DocIntelPool | None = None
_pool_lock = threading.Lock()


def get_doc_intel_pool(settings: Settings) -> DocIntelPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = DocIntelPool(settings)
    return _pool
