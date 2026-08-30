"""
Feature 25 (Gap 341): the embedded chat widget's one endpoint, and its own CORS.

POST /api/v1/widget/chat/message
    Authenticated by an `inv_widget_...` token. Sends one chat message and
    returns the answer. **This is the only route a widget token can reach.**

WHY THIS IS A SEPARATE ROUTER WITH A SEPARATE DEPENDENCY
--------------------------------------------------------
A widget token is pasted into a customer's own website's client-side code, so it
is visible in page source to everyone. The containment story is structural, not
procedural:

* `get_widget_context()` returns `dependencies.WidgetContext`, which has no
  `role`, no `key_scope` and none of the three permission booleans. Every
  permission gate in `dependencies.py` is annotated `context: TenantContext` and
  reads one of those fields, so a widget token cannot satisfy any of them --
  there is no field for a future scope bug to get wrong.
* That dependency is declared here and **nowhere else**. Adding it to a second
  route is the change that would need re-reviewing, and it is a one-line change
  that is easy to spot in a diff, which is the property being bought.

Whatever else this file grows, `get_widget_context` stays on exactly one route.
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from dependencies import WidgetContext, get_db_session
from models import ChatSession
from services.api_keys import looks_like_widget_token
from services.widget_tokens import origin_is_allowed, resolve_widget_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widget", tags=["Chat Widget"])

# Path prefix the widget CORS middleware applies to, including main.py's
# `/api/v1` mount. Kept as a constant so the middleware and the router cannot
# disagree about which paths are "widget paths".
WIDGET_PATH_PREFIX = "/api/v1/widget"

# Headers a widget's browser-side fetch legitimately needs to send. Enumerated
# rather than `*` so the preflight answer is a statement about what this surface
# accepts, not a shrug. `Cookie` is deliberately absent and unreachable anyway --
# see WidgetCORSMiddleware on why credentials are off.
_WIDGET_ALLOWED_HEADERS = "Authorization, Content-Type, X-API-Key"
_WIDGET_ALLOWED_METHODS = "POST, OPTIONS"
_WIDGET_PREFLIGHT_MAX_AGE = "600"


class WidgetCORSMiddleware(BaseHTTPMiddleware):
    """CORS for `/api/v1/widget/*` only — deliberately NOT the global middleware.

    ------------------------------------------------------------------------
    WHY THE GLOBAL `CORSMiddleware` IN main.py WAS NOT WIDENED
    ------------------------------------------------------------------------
    A widget is embedded on customer domains this backend has never heard of, so
    making it work "just" needs those origins allowed. The obvious move -- adding
    them to `ALLOWED_ORIGINS` -- is the wrong one, and not marginally:
    `main.py`'s `CORSMiddleware` runs with **`allow_credentials=True`**, which is
    what lets the first-party dashboard send its session. Widening that list
    widens it for **every route in the product**, so every session-authenticated
    endpoint becomes cross-origin reachable, with credentials, from whatever site
    was added. Allowing an arbitrary customer domain there would be handing that
    domain the ability to make authenticated requests as any logged-in user who
    visits it.

    So: this middleware, scoped by path prefix, with credentials **off**.

    HOW IT DIFFERS, precisely:

    * `Access-Control-Allow-Credentials` is **never** emitted. That is the load-
      bearing line. With credentials off, the browser will not attach cookies or
      HTTP auth to a cross-origin widget request no matter what origin is
      reflected -- which is exactly why reflecting the origin is safe here and
      would not be safe in the global middleware.
    * The `Origin` is reflected rather than matched against a list, because the
      list is per-token and a CORS preflight is unauthenticated by definition
      (browsers send no `Authorization` on `OPTIONS`), so the token's registered
      origins are simply not knowable at preflight time. The per-token origin
      check therefore happens in the handler instead -- as one defensive layer,
      not as the control; see the endpoint docstring.
    * The header is **set**, not appended, so if a widget request ever does come
      from an origin that is also in `ALLOWED_ORIGINS`, the response carries one
      `Access-Control-Allow-Origin` value rather than two (two is a protocol
      error and every browser rejects it).

    Mounted after the global CORSMiddleware in main.py, which in Starlette makes
    it the **outer** of the two -- so it sees the request first and can answer a
    preflight for an unknown origin, which the inner one would otherwise pass
    through to a 405.
    """

    def __init__(self, app: ASGIApp, path_prefix: str = WIDGET_PATH_PREFIX):
        super().__init__(app)
        self._path_prefix = path_prefix

    def _apply(self, response: Response, origin: str | None) -> Response:
        # THE LOAD-BEARING LINE, and it is a deletion rather than an omission.
        #
        # Starlette's CORSMiddleware puts `Access-Control-Allow-Credentials:
        # true` in its `simple_headers` and applies them to **every** response
        # to a request that carried an `Origin` header -- unconditionally, before
        # it decides whether that origin is allowed. (Only
        # `Access-Control-Allow-Origin` is conditional.) So the inner global
        # middleware stamps the credentials header onto widget responses too,
        # and combined with the origin this middleware reflects, a browser would
        # have been told it may send cookies cross-origin to a customer's site.
        # Not emitting it here was never going to be enough; it has to be
        # removed.
        #
        # Found by tests/test_widget_token.py::
        # test_widget_response_never_allows_credentials, which asserts the
        # absence on a real response and not just on this function's output.
        if "access-control-allow-credentials" in response.headers:
            del response.headers["access-control-allow-credentials"]

        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            # Caches and CDNs must not serve one customer's origin header to a
            # different customer's visitor.
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = _WIDGET_ALLOWED_METHODS
        response.headers["Access-Control-Allow-Headers"] = _WIDGET_ALLOWED_HEADERS
        response.headers["Access-Control-Max-Age"] = _WIDGET_PREFLIGHT_MAX_AGE
        return response

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self._path_prefix):
            return await call_next(request)

        origin = request.headers.get("origin")

        if request.method == "OPTIONS":
            # Answered here rather than passed down: there is no OPTIONS route,
            # and the global CORSMiddleware only short-circuits preflights whose
            # origin is in ALLOWED_ORIGINS -- which a customer's site never is.
            return self._apply(Response(status_code=status.HTTP_200_OK), origin)

        return self._apply(await call_next(request), origin)


def get_widget_context(
    request: Request,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    db_session: Session = Depends(get_db_session),
) -> WidgetContext:
    """Resolve an `inv_widget_...` token into a `WidgetContext`, or 401.

    **Declared here and mounted on exactly one route.** It deliberately does not
    live in `dependencies.py` next to the other auth dependencies: that file is
    where a reader goes looking for something to reuse, and this one must not be
    reused. `WidgetContext` itself is in `dependencies.py` because the type is
    shared; the dependency that mints it is not.

    Both header spellings are accepted, for the same reason
    `_extract_api_key()` accepts both -- an integrator reaches for one or the
    other without checking, and `services/api_keys.py::
    looks_like_platform_credential()` makes the two behave identically rather
    than one 401ing about a JWT signature.

    An unknown token, a revoked token and a token belonging to a deleted tenant
    are all the same 401 with the same message: distinguishing them tells an
    anonymous caller which tokens exist.
    """
    raw = None
    if x_api_key and x_api_key.strip():
        raw = x_api_key.strip()
    elif authorization and authorization.startswith("Bearer "):
        raw = authorization.split(" ", 1)[1].strip()

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Missing or invalid chat widget token. Send it as "
            "'X-API-Key: inv_widget_...' or 'Authorization: Bearer inv_widget_...'."
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not raw or not looks_like_widget_token(raw):
        raise unauthorized

    token = resolve_widget_token(db_session, raw)
    if token is None:
        raise unauthorized

    # Origin pinning -- ONE DEFENSIVE LAYER, NOT THE CONTROL.
    #
    # `Origin` (and `Referer`) is set by the browser and cannot be overridden by
    # page JavaScript, so this does genuinely stop a scraped token being used
    # from another *site*. It stops nothing at all outside a browser:
    # `curl -H 'Origin: https://acme.com'` is the entire bypass. It is here
    # because it raises the cost of the casual case, and it must never be
    # described -- in code, in docs, or to a customer -- as a guarantee that a
    # widget token only works on the registered domain. The real containment is
    # that this token reaches one chat route and resolves to a type with no
    # permissions on it.
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin_is_allowed(token, origin):
        logger.warning(
            "widget token %s used from unregistered origin %r",
            token.token_prefix, origin,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This chat widget token is not registered for this website. An "
                "Admin can add the domain under Settings -> Security."
            ),
        )

    return WidgetContext(
        tenant_id=token.tenant_id,
        widget_token_id=token.id,
        origin=origin,
    )


class WidgetMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    # Omitted on the first message of a conversation; the response returns the
    # id the widget then echoes back so a visitor's follow-up keeps its context.
    session_id: UUID | None = None


class WidgetMessageResponse(BaseModel):
    session_id: str
    message_id: str
    content: str


@router.post(
    "/chat/message",
    response_model=WidgetMessageResponse,
    summary="Send one chat message from an embedded widget",
)
def post_widget_chat_message(
    payload: WidgetMessageRequest,
    context: WidgetContext = Depends(get_widget_context),
    db_session: Session = Depends(get_db_session),
):
    """Ask the assistant one question on behalf of a tenant's website visitor.

    **The only route `get_widget_context` is mounted on.** Everything a widget
    token can do in this product is what this handler does.

    Session ownership is checked the same way every other handler in
    `routers/chat.py` checks it -- a `session_id` for another tenant is a 403,
    not a silent new session -- because a widget token is published and session
    ids are guessable-ish UUIDs in a URL-less API. An unknown id is 404.

    The turn itself is `routers/chat.py::run_sync_chat_turn()`, i.e. **the same
    function the dashboard uses**, not a second implementation. That is
    deliberate: a widget turn that skipped the quality judge or the turn
    telemetry would be invisible in exactly the surface where an anonymous end
    user is talking to the product, and two copies of the answer path drift.

    Always synchronous. The async queue path (Gap 280) returns a `job_id` the
    caller then polls -- and job status/stream are `routers/chat.py` routes that
    a widget token, by design, cannot reach.
    """
    # Imported here rather than at module scope: routers/chat.py imports the
    # query agent, which pulls in the whole RAG stack, and this module is
    # imported by main.py at process start.
    from routers.chat import charge_sandbox_chat_or_402, run_sync_chat_turn

    if payload.session_id is not None:
        chat_session = db_session.exec(
            select(ChatSession).where(ChatSession.id == payload.session_id)
        ).first()
        if chat_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found.",
            )
        if chat_session.tenant_id != context.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden to this chat session.",
            )
    else:
        chat_session = ChatSession(
            id=uuid4(),
            tenant_id=context.tenant_id,
            # Labelled so an Admin scrolling the tenant's chat history can tell a
            # website visitor's conversation from their own team's.
            title="Website widget chat",
        )
        db_session.add(chat_session)
        db_session.commit()
        db_session.refresh(chat_session)

    # Defence in depth only: a sandbox tenant has no Admin user and therefore no
    # way to issue a widget token in the first place (Gap 340 property 3), so
    # this cannot fire today. It costs one indexed lookup and means the chat
    # meter is charged on *every* door into the chat agent rather than on the
    # ones we happened to think of -- which is the exact shape of the Gap 343
    # defect on the ingestion side.
    charge_sandbox_chat_or_402(db_session, context.tenant_id)

    assistant_msg = run_sync_chat_turn(
        session_id=chat_session.id,
        content=payload.content,
        tenant_id=context.tenant_id,
        db_session=db_session,
    )

    return WidgetMessageResponse(
        session_id=str(chat_session.id),
        message_id=str(assistant_msg.id),
        content=assistant_msg.content,
    )
