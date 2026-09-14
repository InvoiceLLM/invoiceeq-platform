"use client";

import { ArrowUpRight, Info } from "lucide-react";
import type { ChatAbstention } from "@/types/chat";

/**
 * FE Gap 470 — the structured refusal (Feature 29 decision 3), rendered on the
 * key's presence alone. Three parts, in the order the founder ruled: what is
 * missing, what IS on file, the nearest next step. The next step SEEDS the
 * composer through `onSeed`; it never sends (same rule as the Discuss button).
 *
 * A turn without `abstention` takes no branch here and renders exactly as before.
 */
export default function AbstentionCard({
  abstention,
  onSeed,
}: {
  abstention: ChatAbstention;
  onSeed?: (seedText: string) => void;
}) {
  const missing = abstention.missing ?? [];
  const onFile = abstention.on_file ?? [];
  return (
    <div
      data-testid="chat-abstention"
      data-status={abstention.status}
      className="mt-1.5 rounded-lg border border-amber-800/50 bg-amber-950/30 px-3 py-2 text-[12px] text-amber-100"
    >
      <div className="flex items-start gap-1.5">
        <Info className="mt-px h-3.5 w-3.5 shrink-0 text-amber-300" />
        <span>{abstention.message || "This could not be confirmed from the records on file."}</span>
      </div>
      {missing.length > 0 && (
        <p data-testid="chat-abstention-missing" className="mt-1.5 text-amber-200/90">
          <span className="font-medium">Not on file:</span> {missing.join(", ")}
        </p>
      )}
      {onFile.length > 0 && (
        <p data-testid="chat-abstention-on-file" className="mt-0.5 text-amber-200/80">
          <span className="font-medium">On file:</span> {onFile.join(", ")}
        </p>
      )}
      {abstention.next_step && (
        <button
          type="button"
          data-testid="chat-abstention-next-step"
          onClick={() => onSeed?.(abstention.next_step || "")}
          disabled={!onSeed}
          className="mt-2 inline-flex items-center gap-1 rounded-full border border-amber-700/60 bg-amber-900/40 px-2 py-0.5 text-[11px] font-medium text-amber-100 hover:bg-amber-900/70 disabled:opacity-60"
        >
          {abstention.next_step}
          <ArrowUpRight className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
