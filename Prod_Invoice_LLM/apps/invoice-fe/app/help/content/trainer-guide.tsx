import React from "react";

export interface HelpSection {
  id: string;
  title: string;
  subtitle?: string;
  /** Extra terms the search box should match, beyond the title. */
  keywords: string[];
  /** Flattened body text used for search matching (keep in sync with `body`'s prose). */
  searchText: string;
  body: React.ReactNode;
}

/** Shared image component: real screenshots from live testing, not mockups. */
function Shot({ src, alt, caption }: { src: string; alt: string; caption?: string }) {
  return (
    <figure className="rounded-xl overflow-hidden border border-[#222D3D] bg-[#0B0F19]">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} className="w-full block" />
      {caption && (
        <figcaption className="text-[11px] text-slate-500 px-3 py-2 border-t border-[#222D3D]">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-300 leading-relaxed">{children}</p>;
}

function Callout({ tone, children }: { tone: "info" | "warn"; children: React.ReactNode }) {
  const cls =
    tone === "warn"
      ? "bg-amber-500/10 border-amber-500/25 text-amber-200"
      : "bg-blue-500/10 border-blue-500/25 text-blue-200";
  return <div className={`text-xs rounded-lg border px-3 py-2.5 ${cls}`}>{children}</div>;
}

export const HELP_SECTIONS: HelpSection[] = [
  {
    id: "overview",
    title: "What is the AI Trainer?",
    keywords: ["trainer", "sandbox", "overview", "rules"],
    searchText:
      "AI Trainer sandbox teach extraction rules without code deploy conversational chat",
    body: (
      <>
        <P>
          When the extraction pipeline gets a field wrong — a misread date format, an
          unusual tax layout, a missed compliance code — the normal fix would be a code
          change and a deploy. The <strong>AI Trainer</strong> lets you teach that
          correction conversationally instead: describe what's wrong in plain English,
          and once you commit it, that rule automatically applies to future invoices.
          No code, no deploy.
        </P>
        <P>
          Every rule is stored as a plain-language instruction (e.g. "read the due date
          as DD-MM-YYYY, not MM-DD-YYYY") and gets injected directly into the
          extraction AI's instructions the next time it processes an invoice that rule
          applies to.
        </P>
        <Shot
          src="/help/trainer/01-global-scope.png"
          alt="AI Trainer sandbox, Global scope, empty chat-only state"
          caption="The AI Trainer sandbox — three scope tabs at the top, a document/summary panel on the left, chat on the right."
        />
      </>
    ),
  },
  {
    id: "three-scopes",
    title: "The three modes explained",
    keywords: ["scope", "global", "existing vendor", "new vendor", "modes", "tabs"],
    searchText:
      "Global existing vendor new vendor scope modes tabs tenant-wide cold-start production",
    body: (
      <>
        <P>
          The sandbox has three tabs at the top. Which one you use depends on what
          you're fixing:
        </P>
        <ul className="space-y-3 text-sm text-slate-300">
          <li>
            <strong className="text-white">Global</strong> — a rule that applies to{" "}
            <em>every vendor</em>, tenant-wide (e.g. "VAT is always a tax item, applied
            after discount"). No PDF needed — pure chat. Use this for a business rule
            that isn't specific to one vendor's layout.
          </li>
          <li>
            <strong className="text-white">Existing Vendor</strong> — refine rules for
            a vendor you've already processed invoices from. Pick them from a dropdown
            and the sandbox loads their <em>real</em> most recent production invoice —
            no re-upload needed.
          </li>
          <li>
            <strong className="text-white">New Vendor</strong> — cold-start rules for a
            vendor you've never seen before. Requires uploading a sample PDF, since
            there's no production history to load instead.
          </li>
        </ul>
        <Callout tone="info">
          Global rules apply first, before the vendor is even known. A matching
          vendor-specific rule is layered on top and <strong>wins if the two
          conflict</strong> — e.g. a vendor-specific date format overrides a general one.
        </Callout>
      </>
    ),
  },
  {
    id: "new-vendor-walkthrough",
    title: "Walkthrough: training a new vendor",
    keywords: ["new vendor", "upload", "cold start", "walkthrough"],
    searchText: "new vendor upload PDF cold start walkthrough extracted summary",
    body: (
      <>
        <ol className="list-decimal list-inside space-y-2 text-sm text-slate-300">
          <li>Click the <strong>New Vendor</strong> tab.</li>
          <li>Upload a sample invoice PDF from this vendor.</li>
          <li>
            Wait for extraction to finish — the left panel shows the real PDF plus an{" "}
            <strong>Extracted Summary</strong> strip with the actual values the AI read
            off it.
          </li>
          <li>Check the summary against the PDF. If something's wrong, say so in chat.</li>
          <li>Click <strong>Commit to Template Registry</strong> once you're happy.</li>
        </ol>
        <Shot
          src="/help/trainer/02-new-vendor-loaded.png"
          alt="New Vendor scope with a real uploaded PDF and live extracted summary"
          caption="Real extraction result — vendor, invoice #, dates, and totals are the actual values read from the uploaded PDF, not sample data."
        />
        <Callout tone="info">
          Committing a New Vendor template does <strong>not</strong> trigger a
          background re-audit — there's no past history for this vendor to re-evaluate
          yet.
        </Callout>
      </>
    ),
  },
  {
    id: "existing-vendor-walkthrough",
    title: "Walkthrough: refining an existing vendor",
    keywords: ["existing vendor", "production", "dropdown", "re-audit"],
    searchText: "existing vendor production invoice dropdown reaudit walkthrough",
    body: (
      <>
        <ol className="list-decimal list-inside space-y-2 text-sm text-slate-300">
          <li>Click the <strong>Existing Vendor</strong> tab.</li>
          <li>Pick the vendor from the dropdown — this loads their real latest production invoice, already extracted.</li>
          <li>Describe the correction in chat, same as any other scope.</li>
          <li>Commit — this queues a <strong>background re-audit</strong> that re-runs the new rule against that vendor's past invoices.</li>
        </ol>
        <Shot
          src="/help/trainer/05-existing-vendor.png"
          alt="Existing Vendor scope showing a real production invoice and a registered rule"
          caption="A real production invoice loaded for refinement, with a rule already registered from a chat correction."
        />
      </>
    ),
  },
  {
    id: "confidence",
    title: "Understanding the Extracted Summary & confidence",
    keywords: ["confidence", "extracted summary", "low confidence", "warning"],
    searchText:
      "confidence score extracted summary field percentage low confidence warning audit required",
    body: (
      <>
        <P>
          Every field in the Extracted Summary comes with a confidence score from the
          OCR engine, visible in the <strong>Variables & Rules</strong> tab. If a
          field's confidence is below 60%, the invoice pipeline automatically flags it
          for human review (an <code className="text-blue-300">AUDIT_REQUIRED</code>{" "}
          status with a "low confidence field" alert) — even if the number itself
          happens to be correct.
        </P>
        <Callout tone="warn">
          A low-confidence flag on a synthetic/test PDF is often just a rendering
          quirk of how that PDF was generated, not necessarily a real extraction
          mistake — always cross-check against the actual document before assuming
          something's wrong.
        </Callout>
      </>
    ),
  },
  {
    id: "corrections",
    title: "Making corrections via chat",
    keywords: ["chat", "correction", "teach a rule", "progress", "stuck", "slow", "refining"],
    searchText:
      "chat correction teach a rule progress bar refining rules re-extracting slow stuck finalizing",
    body: (
      <>
        <P>
          Type what's wrong in plain English in the chat box (e.g. "the due date is
          DD-MM-YYYY, not MM-DD-YYYY") and press Enter or click send. Two things
          happen behind the scenes: the AI turns your message into a rule, then
          re-extracts the sample invoice using that new rule so you can immediately
          see whether it fixed the problem.
        </P>
        <P>
          This takes roughly <strong>25-30 seconds</strong> — it's two real AI calls,
          not one. A progress bar with stage labels ("Analyzing correction...",
          "Re-extracting with updated rules...", "Finalizing...") shows how far along
          it is, so it doesn't look stuck.
        </P>
        <Shot
          src="/help/trainer/03-chat-correction-progress.png"
          alt="Chat panel showing a correction in progress with a percentage progress bar"
          caption="A correction in progress — this is normal and typically finishes within ~30 seconds."
        />
      </>
    ),
  },
  {
    id: "commit",
    title: "Committing rules & what re-audit means",
    keywords: ["commit", "registry", "re-audit", "reaudit", "template"],
    searchText:
      "commit to template registry re-audit background queue version toast",
    body: (
      <>
        <P>
          Clicking <strong>Commit to Template Registry</strong> opens a confirmation
          modal summarizing what you're about to save and what happens next, then
          permanently saves the rule set once confirmed.
        </P>
        <Shot
          src="/help/trainer/04-commit-modal.png"
          alt="Commit confirmation modal"
          caption="The commit confirmation modal — explains the re-audit behavior for this specific scope before you confirm."
        />
        <ul className="space-y-1.5 text-sm text-slate-300">
          <li><strong className="text-white">Global</strong> → re-audits every vendor's recent invoices.</li>
          <li><strong className="text-white">Existing Vendor</strong> → re-audits just that vendor's invoices.</li>
          <li><strong className="text-white">New Vendor</strong> → no re-audit (nothing to re-evaluate yet).</li>
        </ul>
        <Callout tone="info">
          After a successful commit, the sandbox resets to a clean state for that
          scope — the session you just committed is gone for good (saved permanently
          to the registry), so don't expect to keep chatting into the same session
          afterward.
        </Callout>
      </>
    ),
  },
  {
    id: "history",
    title: "Rule history & rollback",
    keywords: ["history", "rollback", "version", "undo", "revert"],
    searchText: "rule history rollback version undo revert active current",
    body: (
      <>
        <P>
          Click <strong>Rule History</strong> (top-right of the sandbox) to see every
          version ever committed for the active scope, who changed it, and when. If a
          rule turns out to be wrong, roll back to an earlier version — this creates a{" "}
          <em>new</em> version restoring the old rules (nothing is ever deleted), and
          queues the same re-audit behavior as a normal commit.
        </P>
        <Shot
          src="/help/trainer/06-rule-history.png"
          alt="Rule History drawer showing a committed version"
          caption="Rule History drawer — shows exactly what was committed, by whom, and when."
        />
      </>
    ),
  },
  {
    id: "troubleshooting",
    title: "Troubleshooting common issues",
    keywords: ["troubleshoot", "problem", "not working", "chat not using rule", "issue"],
    searchText:
      "troubleshooting problem not working stuck chat not using my rule global scope only",
    body: (
      <>
        <div className="space-y-4">
          <div>
            <p className="text-sm font-semibold text-white mb-1">
              "The correction has been spinning for a while — is it stuck?"
            </p>
            <P>
              Probably not. A correction genuinely takes ~25-30 seconds (two real AI
              calls in sequence). Watch the progress bar's stage text — as long as the
              percentage is moving, it's working. If it's been stuck at the exact same
              percentage for over a minute, that's worth reporting.
            </P>
          </div>
          <div>
            <p className="text-sm font-semibold text-white mb-1">
              "I asked Chat about something I just taught the Trainer, but it didn't know."
            </p>
            <P>
              Two possibilities: (1) you taught it as a <strong>vendor-specific</strong>{" "}
              rule (Existing Vendor / New Vendor scope) — only <strong>Global</strong>{" "}
              rules currently reach the Chat assistant; vendor-specific rules only
              affect future extraction, not Chat, for now. (2) You asked within an hour
              of committing and got a cached answer from before the rule existed —
              committing a Global rule clears the answer cache automatically, so this
              should be rare.
            </P>
          </div>
          <div>
            <p className="text-sm font-semibold text-white mb-1">
              "An invoice was flagged for audit even though the numbers look right."
            </p>
            <P>
              Check the specific alert on the invoice — a{" "}
              <code className="text-blue-300">low_confidence_field</code> alert means
              the OCR engine itself was unsure about a field, independent of whether
              the value is actually correct. It's a prompt to double-check that one
              field against the source document, not necessarily a wrong answer.
            </P>
          </div>
        </div>
      </>
    ),
  },
];
