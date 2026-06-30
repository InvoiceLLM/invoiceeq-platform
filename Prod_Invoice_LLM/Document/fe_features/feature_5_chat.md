# Feature 5: Semantic Chat Assistant & SQL Audit Drawer

Build the conversational invoice analyst RAG chat box, document citation connectors, and database query inspection drawers.

### Theme & Styling Specifications
* Chat Bubble:
  * User: `bg-[#1E293B] text-slate-100 rounded-2xl rounded-tr-none`.
  * Assistant: `bg-gradient-to-r from-blue-950/20 to-purple-950/20 border border-blue-800/40 rounded-2xl rounded-tl-none`.
* Citation Pills: `bg-[#1E293B] border border-[#222D3D] text-slate-300 hover:text-white cursor-pointer px-3 py-1 rounded-full text-xs`.
* SQL Code block: `bg-[#0B0F19] text-[#10B981] border border-[#222D3D] font-mono rounded-lg p-3`.

### File Coordinates
* Chat Page: [apps/invoice-fe/app/chat/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/chat/page.tsx)
* Chat Messages Panel: [apps/invoice-fe/components/chat/MessageStream.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/components/chat/MessageStream.tsx)
* SQL Audit Drawer: [apps/invoice-fe/components/chat/SqlAuditDrawer.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/components/chat/SqlAuditDrawer.tsx)

### Tasks
- [ ] **Task 5.1: Build Conversational Message Thread Interface**
  - Implement a scroll-to-bottom chat bubble container with markdown formatting rendering.
  - Implement thread selectors and a `New Chat` action clearing active states.
- [ ] **Task 5.2: Integrate Interactive Citations**
  - Parse references in the chat API response (e.g. `[page 14]`) and render them as interactive pills.
  - Bind pills to open the source document on the referenced page.
- [ ] **Task 5.3: Build Expandable SQL Drawer**
  - Create a collapsible accordion container titled `Executed SQL Query & Data Sources`.
  - Format the SQL code returned in the API payload inside a code container with a copy-to-clipboard action.
- [ ] **Task 5.4: Bind Chat Queries to Backend**
  - Code async submit hooks posting prompts to `/api/v1/chat/sessions/{session_id}/query`.

### Verification Plan
* **Manual Verification**: Launch the Chat screen. Type a query (e.g., *"What is my total spend?"*), confirm the SQL drawer displays the query, and click a citation pill to check its behavior.
