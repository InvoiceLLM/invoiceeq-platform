"use client";

import { useEffect } from "react";

/**
 * When PayU checkout was opened via window.open from Subscriptions, the
 * success/failed return lands in that popup. Notify the opener and close so
 * the user stays on the app; if there is no opener (same-tab checkout), do
 * nothing and leave this page visible.
 */
export function PayuPopupReturn({ status }: { status: "success" | "failed" }) {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const opener = window.opener;
    if (!opener || opener.closed) return;

    try {
      opener.postMessage(
        { source: "invoice-payu", type: "payu-return", status },
        window.location.origin
      );
      opener.focus();
    } catch {
      // Cross-origin opener (shouldn't happen under Multi-Zone same origin).
    }

    // Allow the message to flush, then close the PayU window.
    const t = window.setTimeout(() => {
      try {
        window.close();
      } catch {
        // Some browsers block window.close() if the script didn't open it.
      }
    }, 150);
    return () => window.clearTimeout(t);
  }, [status]);

  return null;
}
