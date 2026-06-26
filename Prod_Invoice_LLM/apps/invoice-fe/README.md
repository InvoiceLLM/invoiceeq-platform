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

## Directory Structure
```
invoice-fe/
├── app/                        # Next.js App Router pages
├── components/
│   ├── ui/                     # Shadcn/UI base components
│   ├── dashboard/              # KPI cards, filter bar, metrics grid
│   ├── ingestion/              # Drag & drop upload, status table
│   ├── audit/                  # PDF viewer, extracted data form, approval buttons
│   └── chat/                   # Chat bubbles, input bar, citation links
├── hooks/                      # Custom React hooks (usePolling, useSSEStream, useAuth, etc.)
└── lib/                        # API client, utilities, constants
```

## Screens
| Screen              | Description                                              |
|---------------------|----------------------------------------------------------|
| **Dashboard**       | Bento-box KPIs, date/vendor/status filters               |
| **File Ingestion**  | Row-level checkboxes to add `#tags` before uploading → drag & drop uploader with non-blocking status alerts |
| **Auditor Tab**     | Split-screen: PDF preview (left) + editable values form (right) with interactive alert dismissal, marking PAID or REJECTED |
| **Semantic Chat**   | Message-style layout with citation links to source PDFs  |

## Golden Rule
> The Frontend **never** interacts with Redis/Celery directly. It only speaks to the FastAPI Backend.

## API Communication (Hybrid: Polling + SSE)

The frontend uses a **hybrid notification strategy** based on upload volume:

| Scenario       | Mechanism                  | Implementation                                               |
|----------------|----------------------------|--------------------------------------------------------------|
| 1–5 PDFs       | **Polling** (React Query)  | `useQuery` with `refetchInterval` (~2s) on `GET /status/{job_id}` |
| 6+ PDFs (bulk) | **SSE** (Server-Sent Events)| `EventSource` on `GET /stream/{batch_id}` — server pushes updates |

- **Polling**: TanStack Query polls `GET /invoices/status/{job_id}` every 2 seconds, stops when status is `COMPLETED` or `REJECTED`
- **SSE**: Browser-native `EventSource` API opens a single persistent connection; backend pushes a status event as each PDF completes
- All requests include `tenant_id` from the Auth Provider (Clerk/Auth0) JWT in the `Authorization` header

## Environment Variables
```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
NEXT_PUBLIC_API_URL=
```
