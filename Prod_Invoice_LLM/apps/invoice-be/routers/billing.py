"""
Feature 11: PayU Billing API.

PayU's classic hash-based integration has no dashboard-configured webhook
and no native subscription/proration object (unlike Stripe/Razorpay, both
considered and ruled out before this -- see feature_11_billing.md for the
full provider-decision history, including the 2026-07-31 end-to-end
connection test against PayU's real sandbox). Payment confirmation instead
flows through surl/furl: PayU POSTs the transaction result to these URLs.
That POST is never trusted on its own -- it's checked two ways: (1) the
response hash PayU itself sends, and (2) a server-to-server cross-check via
PayU's verify_payment API (the same call already verified working manually).

Reachability: this router's ingress is internal-only, so surl/furl are built
from BACKEND_PUBLIC_URL, which points at *invoice-website*'s public origin.
That app carries a verbatim, unauthenticated pass-through at the identical
path (app/api/v1/billing/payu/{success,failure}/route.ts) which forwards the
raw form body here and relays the 303 back to the browser. Nothing about the
URL shape below changes as a result. The user-facing landing pages
(/billing/success, /billing/failed) live in invoice-website too, addressed
via PUBLIC_APP_URL -- see config.py for why that is separate from
FRONTEND_URL.

Renewal model: manual monthly re-payment (the tenant re-runs checkout each
cycle) rather than true auto-debit -- PayU's classic API has no recurring
object to build against. A scheduled lapse-detection job (flip billing_plan
to 'unpaid' once a cycle passes with no new successful txnid) is a follow-up,
not built here -- see feature_11_billing.md Task 11.3.
"""
import hashlib
import hmac
import logging
import uuid
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session

from config import settings
from dependencies import get_tenant_context, get_db_session, TenantContext
from models import Tenant, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])

# Plan -> monthly price (feature_3.1_vendor_flow_pricing.md). PayU's classic
# API has no plan/subscription object of its own -- these are our own
# prices, not anything registered on PayU's side.
PLAN_AMOUNTS = {
    "pro": "4999.00",
    "pro_combined": "8999.00",
}

PAYU_ACTION_URL = {
    "test": "https://test.payu.in/_payment",
    "live": "https://secure.payu.in/_payment",
}

# Verified reachable 2026-07-31 (test.payu.in) -- live URL per PayU's docs,
# not yet exercised against a real live-mode account.
PAYU_VERIFY_URL = {
    "test": "https://test.payu.in/merchant/postservice.php?form=2",
    "live": "https://info.payu.in/merchant/postservice.php?form=2",
}


class CheckoutSessionRequest(BaseModel):
    plan: Literal["pro", "pro_combined"]


class CheckoutSessionResponse(BaseModel):
    action_url: str
    key: str
    txnid: str
    amount: str
    productinfo: str
    firstname: str
    email: str
    phone: str
    surl: str
    furl: str
    udf1: str
    hash: str
    service_provider: str = "payu_paisa"


# ---------------------------------------------------------------------------
# Hashing -- built from an explicit 10-element udf list rather than
# hand-counted pipe strings, since PayU's hash format is a well-known source
# of integration bugs when the separator count is miscounted by hand.
# ---------------------------------------------------------------------------

def _request_hash(txnid: str, amount: str, productinfo: str, firstname: str, email: str, udf1: str) -> str:
    udfs = [udf1, "", "", "", "", "", "", "", "", ""]  # udf1..udf10
    parts = [settings.PAYU_MERCHANT_KEY, txnid, amount, productinfo, firstname, email, *udfs, settings.PAYU_MERCHANT_SALT]
    return hashlib.sha512("|".join(parts).encode("utf-8")).hexdigest()


def _response_hash(status_str: str, txnid: str, amount: str, productinfo: str, firstname: str, email: str, udf1: str) -> str:
    # Reverse of the request hash, with status inserted after salt -- PayU's
    # documented response-hash sequence.
    udfs_reversed = ["", "", "", "", "", "", "", "", "", udf1]  # udf10..udf1
    parts = [settings.PAYU_MERCHANT_SALT, status_str, *udfs_reversed, email, firstname, productinfo, amount, txnid, settings.PAYU_MERCHANT_KEY]
    return hashlib.sha512("|".join(parts).encode("utf-8")).hexdigest()


async def _verify_payment_with_payu(txnid: str) -> str | None:
    """Server-to-server cross-check -- returns PayU's own recorded status
    for this txnid, or None if PayU couldn't be reached / found nothing."""
    verify_hash = hashlib.sha512(
        f"{settings.PAYU_MERCHANT_KEY}|verify_payment|{txnid}|{settings.PAYU_MERCHANT_SALT}".encode("utf-8")
    ).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            resp = await http_client.post(
                PAYU_VERIFY_URL[settings.PAYU_MODE],
                data={"key": settings.PAYU_MERCHANT_KEY, "command": "verify_payment", "var1": txnid, "hash": verify_hash},
            )
        resp.raise_for_status()
        data = resp.json()
        return data.get("transaction_details", {}).get(txnid, {}).get("status")
    except httpx.HTTPError as e:
        logger.error("PayU verify_payment call failed for txnid=%s: %s", txnid, e)
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/create-checkout-session", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    payload: CheckoutSessionRequest,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Generates a PayU hash-signed payment form. Admin-only, matching the
    Admin gate already used for other billing-plan-affecting actions (see
    routers/settings.py::update_vendor_flow_settings)."""
    if context.role != "Admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Admin users can manage billing.")

    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    user = db_session.get(User, context.db_user_id) if context.db_user_id else None
    email = user.email if user else f"billing@{tenant.domain}"
    firstname = (user.first_name if user and user.first_name else tenant.name)[:60]

    amount = PLAN_AMOUNTS[payload.plan]
    txnid = f"txn_{uuid.uuid4().hex[:20]}"
    productinfo = f"InvoiceAI-{payload.plan}"
    # tenant_id is threaded through udf1 so the surl/furl callback -- which
    # only gets back the fields PayU echoes -- can identify which tenant to
    # update. Without this there's no reliable way to map a PayU callback
    # back to a tenant.
    udf1 = str(context.tenant_id)

    req_hash = _request_hash(txnid, amount, productinfo, firstname, email, udf1)

    base_url = settings.BACKEND_PUBLIC_URL.rstrip("/")

    logger.info("PayU checkout session created: tenant=%s plan=%s txnid=%s amount=%s", context.tenant_id, payload.plan, txnid, amount)

    return CheckoutSessionResponse(
        action_url=PAYU_ACTION_URL[settings.PAYU_MODE],
        key=settings.PAYU_MERCHANT_KEY,
        txnid=txnid,
        amount=amount,
        productinfo=productinfo,
        firstname=firstname,
        email=email,
        phone="9999999999",
        surl=f"{base_url}/api/v1/billing/payu/success",
        furl=f"{base_url}/api/v1/billing/payu/failure",
        udf1=udf1,
        hash=req_hash,
    )


async def _handle_payu_callback(form: dict, db_session: Session, is_surl: bool) -> RedirectResponse:
    txnid = form.get("txnid", "")
    status_str = form.get("status", "")
    amount = form.get("amount", "")
    productinfo = form.get("productinfo", "")
    firstname = form.get("firstname", "")
    email = form.get("email", "")
    udf1 = form.get("udf1", "") or ""
    received_hash = form.get("hash", "")

    # PUBLIC_APP_URL, not FRONTEND_URL: /billing/success and /billing/failed
    # are invoice-website routes (invoice-fe is internal-only post-proxy, so
    # a browser returning from PayU can't reach it) -- see config.py.
    fail_redirect = f"{settings.PUBLIC_APP_URL.rstrip('/')}/billing/failed"

    if not txnid:
        logger.warning("PayU callback with no txnid, ignoring.")
        return RedirectResponse(f"{fail_redirect}?reason=malformed", status_code=status.HTTP_303_SEE_OTHER)

    # 1. Verify the response hash PayU sent -- defends against a tampered
    # or entirely spoofed POST to this public URL.
    expected_hash = _response_hash(status_str, txnid, amount, productinfo, firstname, email, udf1)
    if not hmac.compare_digest(expected_hash, received_hash):
        logger.error("PayU callback hash mismatch for txnid=%s -- not trusting this POST.", txnid)
        # txnid is carried on every reason= branch below too: these are exactly
        # the cases where the user may have been charged but we can't confirm
        # it, so the landing page has to be able to show them a reference to
        # quote to support.
        return RedirectResponse(f"{fail_redirect}?reason=hash_mismatch&txnid={txnid}", status_code=status.HTTP_303_SEE_OTHER)

    # 2. Cross-check server-to-server via verify_payment -- the response
    # hash alone only proves this POST's fields weren't tampered with in
    # transit, not that a real payment actually happened on PayU's side
    # (a hash-valid POST could in principle be crafted directly, without
    # ever visiting PayU, if the attacker knew a completed txnid). Ask
    # PayU's own servers what actually happened for this txnid.
    verified_status = await _verify_payment_with_payu(txnid)
    if verified_status is None:
        logger.error("Could not reach PayU verify_payment for txnid=%s -- not trusting this callback.", txnid)
        return RedirectResponse(f"{fail_redirect}?reason=unverifiable&txnid={txnid}", status_code=status.HTTP_303_SEE_OTHER)

    if not is_surl or status_str.lower() != "success" or verified_status.lower() != "success":
        logger.info("PayU payment not successful: txnid=%s callback_status=%s verified_status=%s", txnid, status_str, verified_status)
        return RedirectResponse(f"{fail_redirect}?txnid={txnid}", status_code=status.HTTP_303_SEE_OTHER)

    plan = productinfo.removeprefix("InvoiceAI-") if productinfo.startswith("InvoiceAI-") else None
    if plan not in PLAN_AMOUNTS:
        logger.error("PayU callback verified but productinfo=%r doesn't map to a known plan, txnid=%s", productinfo, txnid)
        return RedirectResponse(f"{fail_redirect}?reason=unknown_plan&txnid={txnid}", status_code=status.HTTP_303_SEE_OTHER)

    try:
        tenant_id = uuid.UUID(udf1)
    except ValueError:
        logger.error("PayU callback verified but udf1=%r isn't a valid tenant_id, txnid=%s", udf1, txnid)
        return RedirectResponse(f"{fail_redirect}?reason=unknown_tenant&txnid={txnid}", status_code=status.HTTP_303_SEE_OTHER)

    tenant = db_session.get(Tenant, tenant_id)
    if not tenant:
        logger.error("PayU callback verified for txnid=%s but tenant %s no longer exists.", txnid, tenant_id)
        return RedirectResponse(f"{fail_redirect}?reason=unknown_tenant&txnid={txnid}", status_code=status.HTTP_303_SEE_OTHER)

    tenant.billing_plan = plan
    tenant.payu_subscription_id = txnid
    db_session.add(tenant)
    db_session.commit()

    logger.info("PayU payment verified, tenant=%s upgraded to plan=%s (txnid=%s).", tenant_id, plan, txnid)
    # The plan change is already committed above, so the landing page needs no
    # API call of its own -- it is purely informational. Deliberate: a fetch on
    # that page could fail and make a successful payment look failed.
    success_url = f"{settings.PUBLIC_APP_URL.rstrip('/')}/billing/success"
    return RedirectResponse(f"{success_url}?plan={plan}&txnid={txnid}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/payu/success")
async def payu_success(request: Request, db_session: Session = Depends(get_db_session)):
    form = dict(await request.form())
    return await _handle_payu_callback(form, db_session, is_surl=True)


@router.post("/payu/failure")
async def payu_failure(request: Request, db_session: Session = Depends(get_db_session)):
    form = dict(await request.form())
    return await _handle_payu_callback(form, db_session, is_surl=False)
