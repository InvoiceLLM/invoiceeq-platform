# functional-tester — live chat progress screenshot capture (2026-09-02)

Founder wants a real screenshot of the chat screen mid-processing. Scope: no
code changes, no test files -- pure capture task, local dev stack only.

Do NOT touch: any BE/FE application code, any spec/tracker doc content besides
this tasklist and (at the end) test_coverage_map.md if the screenshot warrants
a coverage-map entry.

- [x] 1. Read CONVENTIONS.md, feature_26 P2.9 (known attachment-progress
      limitation), ChatWindow.tsx / useChatSession.ts for whether the H10-H12
      attachment UI is wired yet (it is -- H12's proxies + hook wiring landed).
- [x] 2. Confirmed ENABLE_ASYNC_CHAT_QUEUE defaults False (config.py) -- so
      BOTH plain and attachment turns run synchronous by default, and the FE
      shows only a generic 3-dot typing indicator (MessageStream.tsx L724-738),
      not the real per-step progress. This applies regardless of chat type,
      separate from and in addition to §P2.9's attachment-specific SSE bug.
- [x] 3. Temporarily set ENABLE_ASYNC_CHAT_QUEUE=true in
      apps/invoice-be/.env (gitignored, local-only) purely to screenshot the
      wired step display -- NOT a D7 flip-criteria clearance. To be reverted
      after capture.
- [ ] 4. Confirm docker infra up (postgres/redis/chroma/azurite) -- was
      already running (17h uptime); chromadb container shows "unhealthy",
      check if that blocks anything.
- [ ] 5. Start invoice-be (uv run uvicorn), queue_worker
      (uv run python -m queue_worker.main_worker), invoice-fe (npm run dev).
- [ ] 6. Log in via mock auth, ensure at least one invoice exists in the tenant
      (seed if needed).
- [ ] 7. Playwright: send a plain chat question, screenshot mid-processing
      (should show real step list, async on).
- [ ] 8. Check whether attachment/upload UI is reachable; if so attach a doc
      and screenshot its processing state, noting whether it matches §P2.9's
      known-broken behaviour or something else.
- [ ] 9. Revert .env change (ENABLE_ASYNC_CHAT_QUEUE back off / line removed).
- [ ] 10. Save screenshots to local/screenshots/, report paths + honest
      findings back to coordinator.

Final status: _in progress_
