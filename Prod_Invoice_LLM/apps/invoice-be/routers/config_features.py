"""GET /config/features — the process-wide feature flags, for the frontend.

FOUNDER RULING, 2026-09-03 (Feature 27 §10B task R5(a)). §4 requires the
`DropZone` accept-list widening be gated on `ENABLE_GENERIC_EXTRACTION`
"surfaced via the existing config/feature endpoint, not hardcoded" -- and FE
Gap 378 recorded, correctly, that no such endpoint existed. Every `ENABLE_*` in
`config.py` was consumed server-side only, `main.py` registered no `/config` or
`/features` router, and the only flag-shaped values the FE could see were
build-time `NEXT_PUBLIC_*` env vars, which cannot reflect a backend process
setting. So the widening was blocked on a mechanism, not on FE work.

WHY AN ENDPOINT RATHER THAN RESPONSE-SHAPE ADAPTATION. The alternative -- the
pattern `ENABLE_ASYNC_CHAT_QUEUE` uses, where the FE infers the flag from whether
a response carries a `job_id` -- works for exactly one flag and couples every
future flag to whatever endpoint happens to sit nearby. `ENABLE_GENERIC_EXTRACTION`
has no natural response to adapt: it changes what a user may UPLOAD, and the
upload has not happened yet at the moment the picker needs to know. An endpoint
costs about an hour and answers for every flag after this one.

WHAT THIS DELIBERATELY IS NOT.

  * **Not per-tenant.** E2 is explicit and the reasoning is recorded there in
    full: these flags are software-level, there is no per-tenant flag mechanism
    in this codebase, and mixed-mode data is worse than either mode. This
    endpoint returns the same map to every caller in the deployment, and adding a
    tenant dimension here would be the first step in building exactly the thing
    E2 forbids.
  * **Not a settings surface.** It is READ-ONLY. `routers/settings.py` owns
    tenant configuration and credentials; this owns process booleans and nothing
    else. There is no PUT.
  * **Not an arbitrary config reader.** Only names beginning `ENABLE_` are
    published, and only their boolean values. `config.py` also holds API keys,
    connection strings and endpoints; an endpoint that returned "a config value
    by name" would be one refactor away from returning
    `AZURE_OPENAI_API_KEY`. The allow-shape is structural, not a filter someone
    has to remember to apply.

SECURITY NOTE (security-tester, 2026-09-03). This is new public-ish surface, so
what it exposes was enumerated rather than assumed. The response is four
booleans naming capabilities that are already visible in the product's own
behaviour -- whether chat streams, whether non-invoice documents are classified.
It carries no tenant identifier, no secret, and no value DERIVED from a secret
(a flag's value does not vary with credentials). Knowing a flag is off tells an
attacker that a code path is unreachable, which is not a lever. It sits behind
the existing session dependency anyway, so it is not anonymous.
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config import get_settings
from dependencies import TenantContext, get_tenant_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])

#: The only prefix published. Structural rather than a curated list, so a flag
#: added to `config.py` is visible here without a second edit -- and a NON-flag
#: setting can never become visible by being added to a list by mistake.
_PUBLISHED_PREFIX = "ENABLE_"


class FeatureFlagsOut(BaseModel):
    """A flat boolean map. Deliberately not nested and not versioned.

    Flat because the consumer is a feature check (`flags.ENABLE_X`), and a
    nesting scheme would be a taxonomy nobody asked for. Unversioned because
    adding a key is backwards-compatible and removing one happens exactly when a
    flag is deleted -- at which point the FE reading it should break loudly
    rather than silently read `undefined` as `false`.
    """

    flags: dict[str, bool]


@router.get("/features", response_model=FeatureFlagsOut)
def get_feature_flags(
    tenant_context: TenantContext = Depends(get_tenant_context),
) -> FeatureFlagsOut:
    """Every process-wide `ENABLE_*` flag and its current value.

    `tenant_context` is required but NOT READ. That is deliberate and is worth
    stating rather than leaving as a puzzle: the dependency keeps this off the
    anonymous surface (it is not information the world needs), while the response
    is identical for every tenant because the flags are process-wide (E2). A
    reader who sees the parameter should not go looking for the per-tenant
    resolution it implies -- there is none, and there must not be.
    """
    settings = get_settings()
    flags = {
        name: bool(getattr(settings, name))
        for name in sorted(type(settings).model_fields)
        if name.startswith(_PUBLISHED_PREFIX)
        and isinstance(getattr(settings, name, None), bool)
    }
    return FeatureFlagsOut(flags=flags)
