# Invoice AI — Frontend Dashboard (`/apps/invoice-fe`)

## Purpose
Internal dashboard application for authenticated users.  
Provides invoice management, audit workflows, semantic AI chat, and analytics dashboards.

## Tech Stack
| Layer              | Technology                     |
|--------------------|--------------------------------|
| Framework          | Next.js (App Router)           |
| Language           | TypeScript                     |
| UI Components      | Shadcn/UI + Tailwind CSS       |
| Forms/Validation   | Zod + React Hook Form          |
| API/State          | TanStack Query (React Query)   |

---

## Directory Structure (File-Level)

```
invoice-fe/
│
├── app/                                  # Next.js App Router — pages & layouts
│   ├── layout.tsx                        # Root layout (Clerk Auth provider, global fonts)
│   ├── page.tsx                          # Entry point — redirects to /dashboard
│   ├── dashboard/
│   │   └── page.tsx                      # Dashboard screen
│   ├── ingestion/
│   │   └── page.tsx                      # File upload & status tracking screen
│   ├── audit/
│   │   └── page.tsx                      # Auditor split-screen review screen
│   └── chat/
│       └── page.tsx                      # Semantic chat screen
│
├── components/
│   ├── ui/                               # Shadcn/UI base components (Button, Card, Toast, etc.)
│   │                                     # Never modify these directly — extend via feature components
│   │
│   ├── dashboard/
│   │   ├── KpiCard.tsx                   # Single KPI metric display card (Processed, Spend, Audit Queue)
│   │   ├── FilterBar.tsx                 # Date range picker, vendor dropdown, status filter
│   │   └── MetricsGrid.tsx               # Bento-box layout wrapper — composes KpiCards
│   │
│   ├── ingestion/
│   │   ├── TagSelector.tsx               # Row-level #tag checkbox selector (applied before upload)
│   │   ├── DropZone.tsx                  # Drag & drop PDF upload area (supports multi-file)
│   │   ├── StatusTable.tsx               # Real-time processing status table (polling + SSE rows)
│   │   ├── ConnectorGrid.tsx             # Card selectors to connect/configure third-party integration accounts
│   │   └── FileBrowserModal.tsx          # Remote folder tree browser modal for selecting and importing invoices
│   │
│   ├── audit/
│   │   ├── PdfViewer.tsx                 # react-pdf based PDF preview panel (left panel)
│   │   ├── ExtractedDataForm.tsx         # Editable invoice fields form using React Hook Form + Zod
│   │   ├── AlertDismissal.tsx            # Per-alert dismiss button — removes alert from active list
│   │   └── AuditActionBar.tsx            # Bottom bar — [Reject] [Approve/Pending] [Mark as Paid] buttons
│   │
│   └── chat/
│       ├── ChatWindow.tsx                # Scrollable conversation message history container
│       ├── ChatBubble.tsx                # Single message bubble (role: 'user' | 'assistant')
│       ├── CitationLink.tsx              # Clickable source PDF citation link (opens Blob signed URL)
│       └── ChatInput.tsx                 # Bottom input bar with Send icon button
│
├── hooks/                                # Custom React hooks — encapsulate all side-effect logic
│   ├── usePolling.ts                     # TanStack Query polling hook for 1–5 PDF job status updates
│   ├── useSSEStream.ts                   # EventSource hook for 6+ PDF bulk batch status streams
│   ├── useAuth.ts                        # Extracts tenant_id + JWT from Clerk/Auth0 session token
│   └── useChatSession.ts                 # Manages thread_id UUID lifecycle for multi-turn chat memory
│
└── lib/                                  # Shared utilities, API client, and constants
    ├── apiClient.ts                      # Axios base client — same-origin `/api` prefix, routed through
    │                                     # this app's own Route Handlers (app/api/**)
    ├── backendProxy.ts                   # Server-only helper used by Route Handlers to call
    │                                     # BACKEND_API_URL (never exposed to the browser)
    ├── constants.ts                      # API base URL, polling intervals (2000ms), SSE endpoints
    └── utils.ts                          # Tailwind class merger (cn()), currency & date formatters
```

---

## Screens
| Screen              | Description                                                                                          |
|---------------------|------------------------------------------------------------------------------------------------------|
| **Dashboard**       | Bento-box KPIs, date/vendor/status filters                                                           |
| **File Ingestion**  | Row-level checkboxes to add `#tags` before uploading → drag & drop uploader with non-blocking status alerts |
| **Auditor Tab**     | Split-screen: PDF preview (left) + editable values form (right) with interactive alert dismissal, marking PAID or REJECTED |
| **Semantic Chat**   | Message-style layout with citation links to source PDFs                                              |

---

## Key Design Decisions

| Decision | Detail |
|---|---|
| **Single API entry point** | All HTTP calls go through `lib/apiClient.ts`. No component calls `fetch()` directly. |
| **Auth ownership** | `hooks/useAuth.ts` is the sole owner of `tenant_id` extraction. No other file reads JWT claims. |
| **Chat memory** | `hooks/useChatSession.ts` generates and persists `thread_id` per session. Passed to every `POST /chat/query`. |
| **SSE vs Polling** | Decided at upload time by file count. `useSSEStream.ts` for 6+ files, `usePolling.ts` for 1–5 files. |
| **Shadcn base isolation** | Components inside `components/ui/` are never modified directly. Feature-specific wrappers live in their own folders. |
| **Form validation** | All audit form fields validated client-side via Zod schemas before calling `PUT /audit/resolve`. |
| **Connector Integration** | 1-time OAuth authorization stores refresh tokens on the backend; subsequent folder browses load instantly without re-authentication. Ingestion triggers a background Celery task, allowing the UI to remain responsive. |

---

## Golden Rule
> The Frontend **never** interacts with Redis/Celery directly. It only speaks to the FastAPI Backend.

---

## API Communication (Hybrid: Polling + SSE)

The frontend uses a **hybrid notification strategy** based on upload volume:

| Scenario       | Mechanism                  | Implementation                                               |
|----------------|----------------------------|--------------------------------------------------------------|
| 1–5 PDFs       | **Polling** (React Query)  | `useQuery` with `refetchInterval` (~2s) on `GET /status/{job_id}` |
| 6+ PDFs (bulk) | **SSE** (Server-Sent Events)| `EventSource` on `GET /stream/{batch_id}` — server pushes updates |

- **Polling**: TanStack Query polls `GET /invoices/status/{job_id}` every 2 seconds, stops when status is `COMPLETED` or `REJECTED`
- **SSE**: Browser-native `EventSource` API opens a single persistent connection; backend pushes a status event as each PDF completes
- All requests include `tenant_id` from the Auth Provider (Clerk/Auth0) JWT in the `Authorization` header

---

## Environment Variables
```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=     # Clerk publishable key for SSO auth
BACKEND_API_URL=                       # Base URL of the FastAPI backend (e.g. https://api.yourdomain.com)
                                        # Server-only — read exclusively by Route Handlers under app/api/**,
                                        # never bundled into client JS. No NEXT_PUBLIC_ prefix.
```

---

## Local Development Setup
```bash
# Install dependencies
npm install

# Run development server
npm run dev
```

> Ensure `BACKEND_API_URL` points to a running instance of the backend (`apps/invoice-be`) before starting.
