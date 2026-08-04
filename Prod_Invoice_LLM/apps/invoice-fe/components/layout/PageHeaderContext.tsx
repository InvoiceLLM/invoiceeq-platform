"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { createPortal } from "react-dom";

/**
 * FE Gap 110 — one page header for the whole app, rendered once.
 *
 * Before this, every screen built its own title block: Dashboard/Ingestion/
 * Audit Queue each rendered their own `<PageHeader>` inside the page body,
 * while Trainer, Settings and all four Settings sub-pages rendered a full
 * `h-16 border-b` `<header>` bar of their own *below* Shell's global Header --
 * two stacked header bars on one screen (the leftover half of Gaps 76/88).
 *
 * A routed page cannot render into the layout that wraps it, so the title has
 * to travel upward. This module is that channel:
 *
 *   - `usePageHeader({...})`  — a page declares its title/badge/subtitle.
 *   - `<PageHeaderActions>`   — a page renders its own header-row controls
 *                               (Trainer's Commit button, Ingestion's
 *                               Receiving/Sending toggle, ...) into the shared
 *                               header via a portal.
 *
 * The split is deliberate. The metadata is all primitives, so it can live in
 * context state keyed on those values with no risk of an update loop. Actions
 * are arbitrary JSX with live handlers and would be a *new* element on every
 * render, so pushing them through the same state would re-set context on every
 * render and never settle. A portal sidesteps that entirely: the markup stays
 * in the page's own render tree (handlers and state included) and only the DOM
 * destination changes.
 */

export interface PageHeaderMeta {
  /** Screen name, e.g. "Command Center". Rendered as the app's only `<h1>`. */
  title: string;
  /** Emoji "cartoon" icon for this screen's agent, e.g. "🤖". */
  agentIcon?: string;
  /** Agent codename, e.g. "NOVA". */
  agentName?: string;
  /** Short role explanation shown after the codename, e.g. "Extraction & Validation". */
  agentRole?: string;
  /** Secondary line under the title, e.g. "Invoice #INV-1042". */
  subtitle?: string;
  /**
   * Renders a back arrow before the title. Sub-pages (Settings → Connectors,
   * Audit Queue → Review) used to draw their own; an explicit href is used
   * rather than `router.back()` so a deep-linked arrival lands somewhere in
   * this app instead of leaving it.
   */
  backHref?: string;
}

interface PageHeaderContextValue {
  meta: PageHeaderMeta | null;
  setMeta: (meta: PageHeaderMeta | null) => void;
  actionsSlot: HTMLElement | null;
  setActionsSlot: (el: HTMLElement | null) => void;
}

const PageHeaderContext = createContext<PageHeaderContextValue | null>(null);

export function PageHeaderProvider({ children }: { children: React.ReactNode }) {
  const [meta, setMeta] = useState<PageHeaderMeta | null>(null);
  const [actionsSlot, setActionsSlot] = useState<HTMLElement | null>(null);

  const value = useMemo(
    () => ({ meta, setMeta, actionsSlot, setActionsSlot }),
    [meta, actionsSlot]
  );

  return (
    <PageHeaderContext.Provider value={value}>{children}</PageHeaderContext.Provider>
  );
}

/** Read by `Header.tsx` only. Null on routes that declare nothing. */
export function usePageHeaderMeta(): PageHeaderMeta | null {
  return useContext(PageHeaderContext)?.meta ?? null;
}

/**
 * Ref callback for the shared header's actions container. `useState`'s setter
 * is referentially stable, so passing it straight to `ref` never detaches and
 * re-attaches the portal target between renders.
 */
export function usePageHeaderActionsRef(): (el: HTMLElement | null) => void {
  const ctx = useContext(PageHeaderContext);
  return ctx ? ctx.setActionsSlot : NOOP_REF;
}

const NOOP_REF = (_el: HTMLElement | null) => undefined;

/**
 * Declares this screen's header content. Call it unconditionally at the top of
 * the page component -- above any early return for loading/error states, so a
 * screen that is still fetching still names itself.
 */
export function usePageHeader(meta: PageHeaderMeta): void {
  const ctx = useContext(PageHeaderContext);
  const setMeta = ctx?.setMeta;
  const { title, agentIcon, agentName, agentRole, subtitle, backHref } = meta;

  useEffect(() => {
    if (!setMeta) return;
    setMeta({ title, agentIcon, agentName, agentRole, subtitle, backHref });
    // Clearing on unmount rather than leaving the last value in place: during a
    // route change React flushes this cleanup and the next screen's effect in
    // the same pass, so the two setState calls batch into one render -- no
    // blank frame, and no stale title if the next screen declares none.
    return () => setMeta(null);
  }, [setMeta, title, agentIcon, agentName, agentRole, subtitle, backHref]);
}

/**
 * Renders page-specific controls into the shared header row. Returns null until
 * the header has mounted its slot, which also keeps it inert during SSR.
 */
export function PageHeaderActions({ children }: { children: React.ReactNode }) {
  const slot = useContext(PageHeaderContext)?.actionsSlot ?? null;
  if (!slot) return null;
  return createPortal(children, slot);
}
