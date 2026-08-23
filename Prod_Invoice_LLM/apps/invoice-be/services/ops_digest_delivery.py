"""Feature 24 (Ops Digest Agent) — delivery, to the same channel critical alerts already use.

The decision this implements
----------------------------
The founder decided the digest shares the **same** channel as critical alerts
rather than getting its own. The open question in `feature_24_ops_digest_agent.md`
("same Teams channel, or a separate one?") is therefore closed as *same*.

How that is actually wired, and why it is not a config value
-------------------------------------------------------------
Azure Monitor action groups cannot be "fired" programmatically — there is no
`POST .../actionGroups/{name}/notify` for arbitrary content. The only way to
reach the same humans is to send to the same *receivers* the action group holds.

So instead of copying the Teams webhook URL into a second place (a Key Vault
secret, a bicep param, an env var) where it can silently drift from the action
group, `resolve_critical_channel()` **reads the deployed action group over ARM
and delivers to exactly the receivers it finds there**. If someone changes where
critical alerts go, the digest follows automatically, because it is reading the
same resource rather than a copy of it.

What is actually deployed, checked live on 2026-08-23 (not read off the bicep)
------------------------------------------------------------------------------
``az monitor action-group show -g rg-invoice-llm-dev -n ag-invoice-llm-dev``:

* One email receiver, ``application@infinevocloud.com``.
* One webhook receiver, ``teams-alert-channel``, whose ``serviceUri`` is a
  **Power Automate** flow trigger (``…/powerautomate/automations/direct/…``),
  with ``useCommonAlertSchema: true``.

Two pieces of drift worth stating plainly, because they change what this module
has to handle:

1. ``infra/modules/monitoring/action-group.bicep`` declares a ``-critical`` /
   ``-info`` **split**. Neither exists live — the deployed groups are
   ``ag-invoice-llm-dev`` and ``ag-invoicellm-dev``, i.e. Stage 9 has not been
   redeployed since that split was authored. So the candidate name list below
   tries the bicep name first and falls back to the live one, and works either
   way.
2. Because the receiver has ``useCommonAlertSchema: true``, the Power Automate
   flow on the other end is parsing the **common alert schema** shape
   (``data.essentials.*``). This module therefore posts that shape, with the
   digest text in ``description``, so the existing flow has the fields it
   expects rather than an unrecognised blob.

   **This specific payload has not been verified end to end**, and that is
   stated rather than glossed: verifying it means posting a real message into
   the founder's live Teams channel, which is not something to do unasked while
   building. The shape is right; whether that particular flow renders
   ``description`` nicely is unknown until someone sends one.

SendGrid is not wired on any container either
---------------------------------------------
``az containerapp show -g rg-invoice-llm-dev -n ca-invoice-be-dev`` lists 11
secrets and ``sendgrid-key-secret`` is **not** among them, even though
`invoice-be.bicep` declares it — the same source-vs-deployed drift as Gap 290.
So email delivery works from this code, but will raise "SENDGRID_API_KEY is not
configured" until a deploy actually seeds it. `deliver_digest()` reports that per
channel instead of failing the run: a digest that reached one of two channels is
a success with a caveat, not a failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


ARM_ENDPOINT = "https://management.azure.com"

#: Same api-version `infra/modules/monitoring/action-group.bicep` pins, so the
#: reader and the writer of this resource cannot drift apart -- the same reason
#: `azure_cost.CONSUMPTION_API_VERSION` matches `10-budget.bicep`.
ACTION_GROUP_API_VERSION = "2023-01-01"

#: Tried in order. The first is what `action-group.bicep` *declares*; the second
#: is what is *deployed* today (see the module docstring). Hardcoding the live
#: name as a fallback rather than deriving it follows
#: `azure_cost.resolve_budget_name()`'s precedent: a derived name would 404
#: against the real environment.
DEFAULT_ACTION_GROUP_NAMES = ("ag-invoice-llm-dev-critical", "ag-invoice-llm-dev")

#: Webhook POST budget. A Power Automate trigger answers in well under this;
#: a scheduled job must not hang on a stalled flow.
WEBHOOK_TIMEOUT_SECONDS = 30.0

DELIVERY_AUTO = "auto"
DELIVERY_TEAMS = "teams"
DELIVERY_EMAIL = "email"
DELIVERY_NONE = "none"


@dataclass
class CriticalChannel:
    """Where critical alerts actually go, as read from the deployed action group."""

    action_group_name: str = ""
    webhook_urls: List[str] = field(default_factory=list)
    email_addresses: List[str] = field(default_factory=list)
    #: How this was resolved: "action_group" (read from ARM) or "settings"
    #: (explicit override). On the digest's footer so a reader can tell whether
    #: it really followed the alert channel or fell back to configuration.
    source: str = ""
    error: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.webhook_urls and not self.email_addresses


@dataclass
class DeliveryResult:
    delivered: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    channel: Optional[CriticalChannel] = None

    @property
    def any_delivered(self) -> bool:
        return bool(self.delivered)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delivered": list(self.delivered),
            "skipped": list(self.skipped),
            "errors": list(self.errors),
            "action_group": self.channel.action_group_name if self.channel else "",
            "channel_source": self.channel.source if self.channel else "",
        }


def _action_group_url(name: str) -> str:
    from services.azure_cost import cost_scope  # noqa: PLC0415

    return (
        f"{ARM_ENDPOINT}{cost_scope()}/providers/microsoft.insights/actionGroups/"
        f"{name}?api-version={ACTION_GROUP_API_VERSION}"
    )


def candidate_action_group_names() -> List[str]:
    configured = (settings.OPS_DIGEST_ACTION_GROUP or "").strip()
    if configured:
        return [configured]
    return list(DEFAULT_ACTION_GROUP_NAMES)


def resolve_critical_channel() -> CriticalChannel:
    """Where critical alerts are delivered today.

    Explicit settings win, so a local run or a non-Azure environment can still
    deliver somewhere; otherwise the deployed action group is read. Never
    raises — an unreadable action group returns an empty channel carrying the
    reason, and the caller reports "not delivered, here is why" instead of
    losing the digest to an exception.
    """
    override_webhook = (settings.OPS_DIGEST_TEAMS_WEBHOOK_URL or "").strip()
    override_email = (settings.OPS_DIGEST_EMAIL or "").strip()
    if override_webhook or override_email:
        return CriticalChannel(
            action_group_name="(settings override)",
            webhook_urls=[override_webhook] if override_webhook else [],
            email_addresses=[override_email] if override_email else [],
            source="settings",
        )

    try:
        from services.azure_cost import arm_request  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - import-time failure is still a reason
        return CriticalChannel(error=f"ARM client unavailable: {exc}")

    last_error = ""
    for name in candidate_action_group_names():
        try:
            payload = arm_request("GET", _action_group_url(name))
        except Exception as exc:  # noqa: BLE001
            last_error = f"{name}: {type(exc).__name__}: {exc}"
            logger.debug("Ops digest: action group %s unreadable: %s", name, exc)
            continue

        properties = payload.get("properties") or {}
        webhooks = [
            str(receiver.get("serviceUri") or "").strip()
            for receiver in (properties.get("webhookReceivers") or [])
            if (receiver or {}).get("serviceUri")
        ]
        emails = [
            str(receiver.get("emailAddress") or "").strip().lower()
            for receiver in (properties.get("emailReceivers") or [])
            if (receiver or {}).get("emailAddress")
        ]
        return CriticalChannel(
            action_group_name=str(payload.get("name") or name),
            webhook_urls=[url for url in webhooks if url],
            email_addresses=[email for email in emails if email],
            source="action_group",
        )

    return CriticalChannel(
        error=(
            "no action group could be read "
            f"({last_error or 'none of ' + ', '.join(candidate_action_group_names())}); "
            "set OPS_DIGEST_TEAMS_WEBHOOK_URL or OPS_DIGEST_EMAIL to deliver anyway"
        )
    )


def build_common_alert_schema_payload(
    subject: str,
    body: str,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """The digest, shaped as Azure Monitor's common alert schema.

    Not decoration: the live webhook receiver is registered with
    ``useCommonAlertSchema: true``, so whatever is on the other end was built to
    read ``data.essentials.*``. Posting a bespoke ``{"text": …}`` object into a
    flow expecting that shape is the difference between a rendered message and a
    silent parse failure.

    ``monitorCondition`` is deliberately ``"Resolved"`` and ``severity``
    ``"Sev4"``: many Teams flow templates colour the card red on ``Fired`` and
    on low Sev numbers. A digest is informational by construction, and it must
    not look like a page — the entire point of the two-tier split is that these
    two things are visually distinguishable in the same channel.
    """
    fired_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "schemaId": "azureMonitorCommonAlertSchema",
        "data": {
            "essentials": {
                "alertId": f"ops-digest-{int(fired_at.timestamp())}",
                "alertRule": subject,
                "severity": "Sev4",
                "signalType": "Log",
                "monitorCondition": "Resolved",
                "monitoringService": "InvoiceEQ Ops Digest Agent",
                "alertTargetIDs": [],
                "originAlertId": f"ops-digest-{int(fired_at.timestamp())}",
                "firedDateTime": fired_at.isoformat(),
                "description": body,
                "essentialsVersion": "1.0",
                "alertContextVersion": "1.0",
            },
            "alertContext": {
                "source": "feature_24_ops_digest_agent",
                "subject": subject,
                "digest": body,
            },
        },
    }


def post_to_webhook(url: str, payload: Dict[str, Any]) -> None:
    """POST the digest to one webhook receiver. Raises on a non-2xx."""
    with httpx.Client(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
        response = client.post(url, json=payload)
    if response.status_code >= 300:
        raise RuntimeError(
            f"webhook returned {response.status_code}: {response.text[:300]}"
        )


def deliver_digest(
    subject: str,
    body: str,
    *,
    channel: Optional[CriticalChannel] = None,
    mode: Optional[str] = None,
    now: Optional[datetime] = None,
) -> DeliveryResult:
    """Send one digest to every receiver the critical channel has.

    `mode` (`OPS_DIGEST_DELIVERY`): ``auto`` sends to everything the channel
    resolves to, ``teams``/``email`` restrict to one, ``none`` resolves the
    channel and sends nothing (useful to confirm *where* it would go without
    posting into a live Teams channel).

    Partial success is a success: each receiver is attempted independently and
    its outcome recorded, because losing the email because a Power Automate flow
    was down would be a worse outcome than a slightly noisy result object.
    """
    mode = (mode or settings.OPS_DIGEST_DELIVERY or DELIVERY_AUTO).strip().lower()
    channel = channel if channel is not None else resolve_critical_channel()
    result = DeliveryResult(channel=channel)

    if channel.error:
        result.errors.append(f"channel: {channel.error}")
    if mode == DELIVERY_NONE:
        result.skipped.append("delivery mode is 'none' — nothing sent")
        return result
    if channel.is_empty:
        result.skipped.append("no receivers resolved — nothing sent")
        return result

    if mode in (DELIVERY_AUTO, DELIVERY_TEAMS):
        payload = build_common_alert_schema_payload(subject, body, now=now)
        for url in channel.webhook_urls:
            try:
                post_to_webhook(url, payload)
                result.delivered.append(f"webhook:{_redact(url)}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ops digest: webhook delivery failed: %s", exc)
                result.errors.append(f"webhook {_redact(url)}: {exc}")
        if not channel.webhook_urls and mode == DELIVERY_TEAMS:
            result.skipped.append("mode 'teams' but the channel has no webhook receiver")

    if mode in (DELIVERY_AUTO, DELIVERY_EMAIL):
        if channel.email_addresses:
            try:
                from services.outbound_email import send_email  # noqa: PLC0415

                send_email(
                    to_addresses=channel.email_addresses,
                    subject=subject,
                    plain_body=body,
                )
                result.delivered.append(f"email:{len(channel.email_addresses)}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ops digest: email delivery failed: %s", exc)
                result.errors.append(f"email: {type(exc).__name__}: {exc}")
        elif mode == DELIVERY_EMAIL:
            result.skipped.append("mode 'email' but the channel has no email receiver")

    return result


def _redact(url: str) -> str:
    """Enough of a webhook URL to identify it, never enough to replay it.

    The live Teams webhook carries a ``sig=`` query parameter that is a bearer
    credential — anyone holding the full URL can post into that channel. This
    string ends up in logs and in the run's telemetry event, so it is truncated
    at the query string.
    """
    if not url:
        return ""
    base = url.split("?", 1)[0]
    return base[:60] + ("…" if len(base) > 60 else "")


__all__ = [
    "ACTION_GROUP_API_VERSION",
    "DEFAULT_ACTION_GROUP_NAMES",
    "DELIVERY_AUTO",
    "DELIVERY_EMAIL",
    "DELIVERY_NONE",
    "DELIVERY_TEAMS",
    "CriticalChannel",
    "DeliveryResult",
    "build_common_alert_schema_payload",
    "candidate_action_group_names",
    "deliver_digest",
    "post_to_webhook",
    "resolve_critical_channel",
]
