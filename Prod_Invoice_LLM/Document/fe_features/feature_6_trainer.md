# Feature 6: AI Trainer Interactive Sandbox

Develop the training document loader, chat verification panel, and registry commit workflows.

### Theme & Styling Specifications
* Layout: Split screen panel. Left panel is a clean PDF viewer. Right panel is the chat interface.
* Action Buttons: Header registry submit button (`bg-[#10B981] hover:bg-[#059669] text-white font-medium px-4 py-2 rounded-lg`).

### File Coordinates
* Trainer Page: [apps/invoice-fe/app/trainer/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/trainer/page.tsx)
* Training Uploader: [apps/invoice-fe/components/trainer/TrainerUploader.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/components/trainer/TrainerUploader.tsx)
* Q&A Console: [apps/invoice-fe/components/trainer/QnAPanel.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/components/trainer/QnAPanel.tsx)

### Tasks
- [ ] **Task 6.1: Build Transient Document Ingester**
  - Implement a simple file uploader to load training PDFs directly without standard tagging.
  - Dispatch files to `/api/v1/trainer/upload` and render the PDF on the left.
- [ ] **Task 6.2: Build Q&A Validation Panel**
  - Build the training chat panel on the right side of the screen.
  - Display the key-value extraction list alongside conversational bubbles.
- [ ] **Task 6.3: Implement AI Instruction Adjustment**
  - Bind chat input to send corrections (e.g., *"No, read the date as DD-MM-YYYY"*).
  - Update the extracted variables view dynamically based on the updated extraction response.
- [ ] **Task 6.4: Code Template Registry Commit Handler**
  - Create the `Commit to Template Registry` action button in the header.
  - Dispatch rules updates to `/api/v1/trainer/sessions/{session_id}/commit` and display a success notification.

### Verification Plan
* **Manual Verification**: Upload a mock invoice in the Trainer Console, submit corrections, and click Commit to verify the template coordinates update in the DB.
