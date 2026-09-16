"use client";

// =============================================================================
// FILE: hooks/useHashScroll.ts
// FEATURE: FE Feature 22 Task 22.3 — `/settings#inbox` lands on Inbox, and stays there.
//
// WHY NOT RELY ON THE BROWSER: a native anchor jump happens once, at load. On
// the single Settings page every section fetches its own data after mounting,
// so the sections ABOVE the target grow after the jump and push the target out
// of view — People (the Admin Console's user table) sits first and grows most.
// This scrolls on mount and on every `hashchange`, then keeps re-pinning the
// target while the page's size settles — until the user scrolls, clicks or
// types, or three seconds pass, whichever is first. It never fights the user.
// =============================================================================

import { useEffect, type RefObject } from "react";

const SETTLE_MS = 3000;
const USER_INPUT_EVENTS = ["wheel", "touchstart", "keydown", "mousedown"] as const;

export function scrollToLocationHash(): boolean {
  const id = decodeURIComponent(window.location.hash.replace(/^#/, ""));
  if (!id) return false;
  const target = document.getElementById(id);
  if (!target) return false;
  target.scrollIntoView({ block: "start" });
  return true;
}

export function useHashScroll(containerRef: RefObject<HTMLElement>): void {
  useEffect(() => {
    let settling = true;
    const stopSettling = () => {
      settling = false;
    };

    scrollToLocationHash();

    const onHashChange = () => {
      scrollToLocationHash();
    };
    window.addEventListener("hashchange", onHashChange);

    const container = containerRef.current;
    const observer =
      typeof ResizeObserver !== "undefined" && container
        ? new ResizeObserver(() => {
            if (settling) scrollToLocationHash();
          })
        : null;
    if (observer && container) observer.observe(container);

    const timer = window.setTimeout(stopSettling, SETTLE_MS);
    USER_INPUT_EVENTS.forEach((type) => window.addEventListener(type, stopSettling, { passive: true }));

    return () => {
      window.removeEventListener("hashchange", onHashChange);
      observer?.disconnect();
      window.clearTimeout(timer);
      USER_INPUT_EVENTS.forEach((type) => window.removeEventListener(type, stopSettling));
    };
  }, [containerRef]);
}
