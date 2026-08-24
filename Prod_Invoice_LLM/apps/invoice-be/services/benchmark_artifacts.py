"""Feature 23 — mirror both benchmark tracks' results out of the run process.

Why this module exists
----------------------
Track 1 (`scripts/run_extraction_benchmark.py`) and Track 2
(`scripts/run_agent_eval.py`) both produce real, scored numbers, and until this
file **neither of them left the process in a form anything could query**:

  * The nightly job (`caj-benchmark-eval-dev`) runs Track 1 with ``--no-write``
    — a Container Apps Job replica's filesystem is discarded on exit, so the
    ``docs/extraction_benchmark/runs/*.json`` artifact would be written and then
    thrown away. Its results exist only as the execution's stdout.
  * The pre-deploy gate runs Track 2 with ``--no-persist``, and Track 2's only
    telemetry (``telemetry.track_eval_result``) is emitted from inside
    ``persist()`` — so a gate run emits *nothing at all* today.
  * An Azure Monitor workbook cannot query either one. Its data sources are Log
    Analytics / Application Insights, Azure Resource Graph, ARM and ADX; a
    container's stdout reaches Log Analytics only as unstructured console lines,
    and a local JSON file reaches nothing.

So this is the same two-part mirror Feature 20 Area 1 built for cost
(`services/azure_cost.py::emit_cost_snapshot_telemetry` +
`scripts/sweep_azure_cost.py`), applied to the two quality tracks:

  1. **An aggregate custom event per run** — ``extraction_benchmark_run`` and
     ``agent_eval_summary`` (see `telemetry.py` for what each carries and why
     it is aggregate rather than itemised). This is what a workbook charts.
  2. **The full raw JSON to Blob Storage** — Track 1's per-case comparisons and
     Track 2's per-turn detail, whole. A trend panel can only ever show a number
     moving; the run that moved it has to still be readable afterwards, and
     neither track's detail belongs in Log Analytics ingestion (Track 2's output
     is megabytes of prompts, answers and tool results per run).

The event carries the blob name it was uploaded to (``artifact_blob``), which is
the whole join: a workbook panel shows a recall drop at a timestamp, that row
names the blob, the blob holds every case that produced it. The field is empty
rather than guessed when the upload did not happen, so a link that is present is
always a link that resolves.

Storage — what already exists, and what does not
------------------------------------------------
Account ``stinvoicellmdev2`` (the live dev account; note the ``2`` — the
naming-prefix-derived ``stinvoicellmdev`` does not exist, the same drift Gap 298
records). Verified live 2026-08-24:

  * ``id-invoicellm-dev`` holds **Storage Blob Data Contributor** at account
    scope — so the managed-identity path needs **no new role assignment**, and
    that role's ``containers/write`` is also what lets a first run create the
    container.
  * The account has exactly one container, ``invoices``. **``benchmark-artifacts``
    does not exist yet.** It is created on first use here, the same way
    ``services/storage.py`` creates ``invoices`` — see ``_ensure_container()``.
    ``infra/modules/data/storage.bicep`` declares ``invoices`` as a real
    resource, so declaring this one there too is the tidier long-run answer; that
    is an infra change against a stage that cannot currently be redeployed
    cleanly (Gap 298), so it is flagged in the feature doc rather than made here.

Authentication tries, in order:

  1. ``AZURE_STORAGE_CONNECTION_STRING`` — already wired into every scheduled job
     from Key Vault (``modules/compute/scheduled-job.bicep``), and already the
     mechanism ``services/storage.py`` uses. No new plumbing, no new RBAC.
  2. Managed identity against ``AZURE_STORAGE_ACCOUNT`` — the role above. Lazily
     imported because ``azure-identity`` is present only transitively (via
     ``azure-monitor-opentelemetry-exporter``), so this path must degrade to a
     warning rather than an ImportError if that ever changes.

Nothing here is ever allowed to fail a run
-------------------------------------------
Every public function swallows its own exceptions and returns what it managed to
do. A benchmark **gate** that blocked a deploy because a storage account was
briefly unreachable, or a nightly quality job that failed because the telemetry
exporter had a bad minute, would be an instrumentation layer breaking the thing
it instruments — the same contract every ``telemetry.track_*`` emitter holds to,
and the same graceful degradation `services/storage.py` uses when Blob Storage
is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from config import settings

logger = logging.getLogger(__name__)

#: Blob key prefix per track. Hyphenated, lowercase: a blob name is not a Python
#: identifier and these are read by humans in Storage Explorer.
TRACK_EXTRACTION = "extraction"
TRACK_AGENT_EVAL = "agent-eval"

#: Which cadence produced a run. The same two scripts are invoked by the nightly
#: job and by the pre-deploy gate against the same Application Insights resource,
#: over different corpus sizes — see `telemetry.EXTRACTION_BENCHMARK_EVENT_NAME`.
RUN_LABEL_NIGHTLY = "nightly"
RUN_LABEL_PREDEPLOY = "predeploy"
RUN_LABEL_ADHOC = "adhoc"

#: `write_run_artifacts()` names local run files with exactly this stamp format,
#: so a run that also wrote locally is trivially matched to its blob.
_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"

#: The `.env.example` placeholder shape `services/storage.py` already tests for.
_CONNECTION_STRING_PLACEHOLDER = "your_azure_storage"

#: Deliberately far below the SDK's defaults (`retry_total=3` with exponential
#: backoff). This is an artifact upload at the very end of a run that has already
#: produced its numbers — spending half a minute retrying a storage account that
#: is not answering buys nothing and delays a gate. A local dev machine with the
#: `.env` Azurite connection string and no Azurite running is the common case,
#: and it should fail in a second, not thirty.
_BLOB_CLIENT_OPTIONS = {"retry_total": 1, "connection_timeout": 10, "read_timeout": 30}


@dataclass
class MirrorResult:
    """What one mirror attempt actually managed to do.

    Returned rather than logged-and-forgotten so the calling script can print an
    honest line — "emitted 2 events, artifact upload failed" — instead of a
    reassuring one that is not necessarily true.
    """

    events: int = 0
    artifact_blob: str = ""
    errors: list[str] = field(default_factory=list)

    def describe(self) -> str:
        parts = [f"{self.events} telemetry event(s)"]
        parts.append(f"artifact {self.artifact_blob}" if self.artifact_blob else "no artifact")
        if self.errors:
            parts.append(f"{len(self.errors)} error(s): " + "; ".join(self.errors))
        return ", ".join(parts)


# ---------------------------------------------------------------------------
# Exporter wiring — the step a standalone script has to do for itself
# ---------------------------------------------------------------------------


def configure_run_telemetry() -> bool:
    """Attach the Azure Monitor exporter, exactly as `sweep_azure_cost.py` does.

    Not optional boilerplate. `telemetry._emit_event()` logs through the
    ``invoice_be_telemetry`` logger, and that logger carries an Application
    Insights handler *only* because `configure_azure_monitor()` put one there —
    which `main.py` does at import in the API process and which nothing does in
    a `python scripts/...` process. Without this call the events still emit (the
    record propagates to root and Feature 19's `StructuredJsonFormatter` writes
    it to stdout, so it lands in `ContainerAppConsoleLogs_CL`), but **nothing
    reaches the `customEvents` table**, and a workbook cannot query console logs
    as structured data. That is the same silent-no-op class of failure Gap 292
    was, so it is done explicitly rather than assumed.

    Called *late* — immediately before the mirror, not at script import — on
    purpose. Configuring at import would also start exporting every
    `llm_agent_call` event the benchmark's own turns produce, which is a real
    (if small) change in ingestion volume and cost that belongs in its own
    decision, not in this one. Attaching the handler afterwards still works:
    `telemetry._resolve_event_logger()` caches only once a handler is genuinely
    present, precisely so a late attach is picked up.

    Returns True when the exporter is attached, so the caller can report which
    destination the run actually reached instead of assuming.
    """
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        logger.info(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is not set — benchmark events will be "
            "written as structured stdout JSON only (queryable via ContainerAppConsoleLogs_CL, "
            "not customEvents)."
        )
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=connection_string,
            logger_name="invoice_be_telemetry",
        )
        return True
    except Exception as exc:  # pragma: no cover - exporter/SDK availability
        logger.warning("Could not configure Azure Monitor: %s", exc)
        return False


def flush_run_telemetry() -> None:
    """Force the OTel batch exporter out before a short-lived process exits.

    The exporter batches on a background timer. `main.py` is a long-lived server
    so it never has to think about this; a benchmark job that emits its summary
    event and then exits seconds later would drop the whole batch — i.e. produce
    exactly the "the job ran and the workbook shows nothing" symptom this mirror
    exists to prevent. Same step `scripts/sweep_azure_cost.py` takes.
    """
    try:
        from opentelemetry._logs import get_logger_provider

        force_flush = getattr(get_logger_provider(), "force_flush", None)
        if force_flush is not None:
            force_flush(30000)
    except Exception as exc:  # pragma: no cover - SDK internals
        logger.warning("Telemetry flush failed, events may be lost: %s", exc)


# ---------------------------------------------------------------------------
# Blob Storage
# ---------------------------------------------------------------------------


def _connection_string() -> str:
    value = settings.AZURE_STORAGE_CONNECTION_STRING or ""
    if not value or _CONNECTION_STRING_PLACEHOLDER in value:
        return ""
    return value


def _blob_service_client():
    """A ``BlobServiceClient``, or None when nothing is configured to build one.

    None is not an error condition — a local run with no storage configured is
    the normal case, and the caller degrades to "event only, no artifact".
    """
    from azure.storage.blob import BlobServiceClient

    connection_string = _connection_string()
    if connection_string:
        return BlobServiceClient.from_connection_string(
            connection_string, **_BLOB_CLIENT_OPTIONS
        )

    account = (settings.AZURE_STORAGE_ACCOUNT or "").strip()
    if not account:
        return None

    # Lazy, and its own try: `azure-identity` is a *transitive* dependency here
    # (via azure-monitor-opentelemetry-exporter), not a declared one, so an
    # ImportError is a plausible future state and must degrade, not raise.
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError:  # pragma: no cover - depends on the resolved dep tree
        logger.warning(
            "No AZURE_STORAGE_CONNECTION_STRING and azure-identity is not installed; "
            "benchmark artifacts cannot be uploaded."
        )
        return None

    return BlobServiceClient(
        account_url=f"https://{account}.blob.core.windows.net",
        credential=DefaultAzureCredential(),
        **_BLOB_CLIENT_OPTIONS,
    )


def _ensure_container(client) -> None:
    """Create the artifact container if this is the first run to use it.

    `benchmark-artifacts` does not exist on the live dev account (verified
    2026-08-24) and is not declared in `infra/modules/data/storage.bicep`, so
    without this the very first real run would 404. Creating it at runtime is
    exactly what `services/storage.py` already does for `invoices`, and
    `Storage Blob Data Contributor` — the role the managed identity already
    holds — includes `containers/write`.

    An already-existing container is the expected steady state, so a failure
    here is logged at debug and left to the upload call to report properly: it
    is also what a legitimately narrower permission set would produce, and that
    should not read as an error when the upload itself then succeeds.
    """
    try:
        client.get_container_client(settings.BENCHMARK_ARTIFACT_CONTAINER).create_container()
    except Exception:
        logger.debug(
            "Container %s not created (already exists, or no create permission).",
            settings.BENCHMARK_ARTIFACT_CONTAINER,
            exc_info=True,
        )


def artifact_blob_name(
    track: str, *, mode: str, run_label: str, generated_at: datetime
) -> str:
    """``{track}/{stamp}-{mode}-{run_label}.json``.

    Track first so the two tracks are separate virtual folders in any browser.
    Timestamp before mode/label because a blob listing sorts lexically, and this
    is the ordering someone reading it actually wants — the newest runs of a
    track together, rather than every ``live`` run in one clump.

    The stamp is the join key back to the telemetry event, which carries this
    exact name in ``artifact_blob`` as well as the ISO timestamp in
    ``generated_at``.
    """
    stamp = generated_at.astimezone(timezone.utc).strftime(_STAMP_FORMAT)
    suffix = "-".join(part for part in (mode, run_label) if part)
    return f"{track}/{stamp}-{suffix}.json" if suffix else f"{track}/{stamp}.json"


def upload_artifact(
    track: str,
    payload: dict[str, Any],
    *,
    mode: str,
    run_label: str,
    generated_at: datetime,
) -> tuple[str, Optional[str]]:
    """Upload one run's full raw JSON. Returns ``(blob_name, error)``.

    ``blob_name`` is empty when nothing was uploaded, and the error string is
    None on success and on a deliberate skip. Never raises — an upload failure
    is data about the run, not a reason to fail it.
    """
    if not settings.BENCHMARK_ARTIFACT_UPLOAD:
        return "", None

    blob_name = artifact_blob_name(
        track, mode=mode, run_label=run_label, generated_at=generated_at
    )
    try:
        client = _blob_service_client()
        if client is None:
            return "", None

        _ensure_container(client)
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")

        # `ContentSettings` imported here rather than at module scope for the
        # same reason the client is: this module is imported by two standalone
        # scripts that may run with no storage configured at all, and an import
        # error at module scope would take the whole benchmark run down with it.
        from azure.storage.blob import ContentSettings

        client.get_blob_client(
            container=settings.BENCHMARK_ARTIFACT_CONTAINER, blob=blob_name
        ).upload_blob(
            body,
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        logger.info(
            "Uploaded %s benchmark artifact (%s bytes) to %s/%s",
            track,
            len(body),
            settings.BENCHMARK_ARTIFACT_CONTAINER,
            blob_name,
        )
        return blob_name, None
    except Exception as exc:
        message = f"artifact upload failed ({type(exc).__name__}: {exc})"
        logger.warning("Benchmark %s: %s", track, message)
        return "", message


# ---------------------------------------------------------------------------
# Track 1 — extraction & alerts
# ---------------------------------------------------------------------------


def _as_pct(ratio: Optional[float]) -> Optional[float]:
    """0.0-1.0 → 0-100, preserving None.

    None means "no denominator" everywhere in `benchmarks/extraction/metrics.py`
    (`ConfusionMatrix.recall` and friends all return None on an empty cell pair),
    and it has to stay None all the way onto the event — see
    `telemetry.track_extraction_benchmark_run`'s docstring for why a 0.0 here
    would be actively misleading rather than merely imprecise.
    """
    return None if ratio is None else round(float(ratio) * 100.0, 4)


def mirror_extraction_run(
    summary: dict[str, Any],
    detail: Optional[dict[str, Any]] = None,
    *,
    run_label: str = RUN_LABEL_ADHOC,
    generated_at: Optional[datetime] = None,
) -> MirrorResult:
    """Mirror one Track 1 run: upload the raw JSON, then emit the summary event.

    Takes `benchmarks.extraction.artifacts.summarise()`'s output and, optionally,
    `BenchmarkResult.to_dict()` — i.e. exactly the two halves
    `write_run_artifacts()` writes to disk, so the blob and the local run
    artifact are the same document. The script passes both without writing
    either, which is the point: the nightly job runs `--no-write`.

    Upload first, event second, deliberately: the event carries the blob name,
    so the two cannot be emitted in the other order without either fabricating a
    name or leaving the link permanently empty.

    Never raises.
    """
    from telemetry import track_extraction_benchmark_run

    result = MirrorResult()
    generated_at = generated_at or datetime.now(timezone.utc)
    mode = str(summary.get("mode") or "unknown")

    try:
        matrix = summary.get("confusion_matrix") or {}
        field_accuracy = summary.get("field_accuracy") or {}

        blob_name, upload_error = upload_artifact(
            TRACK_EXTRACTION,
            {
                "run_label": run_label,
                "generated_at": generated_at.isoformat(timespec="seconds"),
                "summary": summary,
                "detail": detail or {},
            },
            mode=mode,
            run_label=run_label,
            generated_at=generated_at,
        )
        result.artifact_blob = blob_name
        if upload_error:
            result.errors.append(upload_error)

        track_extraction_benchmark_run(
            run_label=run_label,
            mode=mode,
            clean_documents=int(summary.get("clean_documents") or 0),
            seeded_cases=int(summary.get("seeded_cases") or 0),
            true_positive=int(matrix.get("true_positive") or 0),
            false_negative=int(matrix.get("false_negative") or 0),
            false_positive=int(matrix.get("false_positive") or 0),
            true_negative=int(matrix.get("true_negative") or 0),
            not_applicable=int(matrix.get("not_applicable") or 0),
            alert_recall_pct=_as_pct(matrix.get("recall")),
            clean_false_positive_rate_pct=_as_pct(matrix.get("false_positive_rate")),
            document_level_precision_pct=_as_pct(matrix.get("document_level_precision")),
            field_accuracy_correct=int(field_accuracy.get("correct") or 0),
            field_accuracy_total=int(field_accuracy.get("total") or 0),
            field_accuracy_pct=_as_pct(field_accuracy.get("ratio")),
            missed_cases=len(summary.get("missed_cases") or []),
            false_positive_documents=len(summary.get("false_positive_documents") or []),
            collateral_alert_types=len(summary.get("collateral_alert_types") or []),
            errors=len(summary.get("errors") or []),
            generated_at=generated_at.isoformat(timespec="seconds"),
            artifact_blob=blob_name,
        )
        result.events += 1
    except Exception as exc:  # pragma: no cover - the emitter itself never raises
        result.errors.append(f"telemetry mirror failed ({type(exc).__name__}: {exc})")
        logger.warning("Track 1 telemetry mirror failed", exc_info=True)
    return result


# ---------------------------------------------------------------------------
# Track 2 — SAGE chat quality
# ---------------------------------------------------------------------------

#: `summarise()` in `scripts/run_agent_eval.py` names its per-path means
#: `<dimension>_mean` and its denominators `<dimension>_scored_turns`, for six
#: of the nine dimensions. faithfulness/relevance/accuracy have no per-dimension
#: denominator there (they are scored on every turn that produced an answer), so
#: their count is simply absent from the event rather than invented.
_SUMMARY_MEAN_SUFFIX = "_mean"
_SUMMARY_COUNT_SUFFIX = "_scored_turns"


def mirror_agent_eval_run(
    payload: dict[str, Any],
    *,
    run_label: str = RUN_LABEL_ADHOC,
    generated_at: Optional[datetime] = None,
) -> MirrorResult:
    """Mirror one Track 2 run: upload the full per-turn JSON, emit one event per path.

    `payload` is exactly what `scripts/run_agent_eval.py` writes to `--out` —
    the same document the CI gate's `jq` reads, uploaded whole rather than
    summarised, so the blob answers questions the event cannot (which answer did
    the model actually give, what did the judge object to, which tool ran).

    One event **per path**, not one per run: a run can measure `default` and
    `sage` in the same invocation, and averaging the two together would produce
    a number describing neither. Aggregate per path, though — the per-turn rows
    are `track_eval_result`'s job, and they are in the blob either way.

    Never raises.
    """
    from telemetry import EVAL_SCORE_DIMENSIONS, track_agent_eval_summary

    result = MirrorResult()
    generated_at = generated_at or datetime.now(timezone.utc)
    summary = payload.get("summary") or {}
    judge_mode = str(payload.get("judge_mode") or "separate")
    model_under_test = str(payload.get("model_under_test") or "")

    try:
        # `--paths default,sage` in one run: name both in the blob so the file
        # says what it holds without being parsed.
        paths = "-".join(sorted(summary.keys())) or "none"
        blob_name, upload_error = upload_artifact(
            TRACK_AGENT_EVAL,
            payload,
            mode=paths,
            run_label=run_label,
            generated_at=generated_at,
        )
        result.artifact_blob = blob_name
        if upload_error:
            result.errors.append(upload_error)

        turns = payload.get("turns") or []
        for path, stats in summary.items():
            stats = stats or {}
            track_agent_eval_summary(
                run_label=run_label,
                path=str(path),
                # `summarise()` reports judge_mode as the sorted set of modes
                # actually observed on the turns; the top-level value is what
                # was asked for. Prefer the observed one when there is exactly
                # one, because a --no-score run asks for "none" and scores
                # nothing, and the two must not disagree on the event.
                judge_mode=(
                    stats["judge_mode"][0]
                    if len(stats.get("judge_mode") or []) == 1
                    else judge_mode
                ),
                turns=int(stats.get("turns") or 0),
                errors=int(stats.get("errors") or 0),
                pass_rate=stats.get("pass_rate"),
                scores={
                    dimension: stats.get(f"{dimension}{_SUMMARY_MEAN_SUFFIX}")
                    for dimension in EVAL_SCORE_DIMENSIONS
                },
                scored_turns={
                    dimension: stats.get(f"{dimension}{_SUMMARY_COUNT_SUFFIX}")
                    for dimension in EVAL_SCORE_DIMENSIONS
                },
                llm_calls_total=int(stats.get("llm_calls_total") or 0),
                judge_llm_calls_total=int(stats.get("judge_llm_calls_total") or 0),
                tokens_in_total=int(stats.get("tokens_in_total") or 0),
                tokens_out_total=int(stats.get("tokens_out_total") or 0),
                latency_ms_median=stats.get("latency_ms_median"),
                cost_per_turn_usd=stats.get("cost_per_turn_usd"),
                model_under_test=model_under_test,
                generated_at=generated_at.isoformat(timespec="seconds"),
                artifact_blob=blob_name,
                # Cases, not turns: a 5-case gate run over two paths is 10
                # turns, and "how much of the corpus did this run cover" is the
                # question a reader comparing a gate run to a nightly one is
                # actually asking.
                cases=len({t.get("case_id") for t in turns if t.get("case_id")}) or None,
            )
            result.events += 1
    except Exception as exc:  # pragma: no cover - the emitter itself never raises
        result.errors.append(f"telemetry mirror failed ({type(exc).__name__}: {exc})")
        logger.warning("Track 2 telemetry mirror failed", exc_info=True)
    return result


__all__ = [
    "MirrorResult",
    "RUN_LABEL_ADHOC",
    "RUN_LABEL_NIGHTLY",
    "RUN_LABEL_PREDEPLOY",
    "TRACK_AGENT_EVAL",
    "TRACK_EXTRACTION",
    "artifact_blob_name",
    "configure_run_telemetry",
    "flush_run_telemetry",
    "mirror_agent_eval_run",
    "mirror_extraction_run",
    "upload_artifact",
]
