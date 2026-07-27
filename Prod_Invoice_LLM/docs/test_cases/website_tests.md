# Website (invoice-website) Test Cases

This document details the test suite for the public marketing website, billing, and auth gateway pages.

## Feature 1: Landing Page & Core Shell
### TC-WEB-01: Visual Layout & Navigation Links
* **Goal**: Validate canvas theme styles (`#0B0F19`), hero text styling, and active navigation headers.
* **How to Test**: Load `/`. Verify header links are clickable. Assert background and gradient heading styles.

### TC-WEB-02: Call-to-Action Routes
* **Goal**: Verify that landing buttons lead to correct destination pages.
* **How to Test**: Click the "Get Started Free" button. Assert browser redirects to the Clerk sign-up wizard.

---

## Feature 2: Multi-Tenant Workspace Showcase
### TC-WEB-03: Video Demonstration & Interactive Mockups
* **Goal**: Ensure the visual demo video or mockups play/render properly.
* **How to Test**: Navigate to the Showcase section. Assert video container initializes and play actions work.

### TC-WEB-04: Feature Carousel Interaction
* **Goal**: Verify carousel tabs switch layout screens.
* **How to Test**: Click on "Extraction Sandbox" tab. Assert showcase screenshot updates and description changes.

---

## Feature 3: Pricing Table & Stripe Checkout Integration
### TC-WEB-05: Dynamic Pricing Toggle
* **Goal**: Verify monthly/annual price billing toggle updates price cards.
* **How to Test**: Click the Monthly/Annual toggle. Assert card text price changes dynamically.

### TC-WEB-06: Stripe Checkout Session Dispatch
* **Goal**: Verify that clicking a plan redirects to Stripe Checkout.
* **How to Test**: Click "Upgrade" on a paid tier. Assert call triggers backend session creation and redirects to a `checkout.stripe.com` page.

---

## Feature 4: Clerk Auth Gateway & Company Provisioning
### TC-WEB-07: Clerk SSO Gateway Render
* **Goal**: Verify email and passwordless social login boxes display.
* **How to Test**: Click "Login" on the website. Verify Clerk authentication modal loads.

### TC-WEB-08: Tenant Company Organization Creation
* **Goal**: Verify workspace settings initialize after first-time login.
* **How to Test**: Perform initial signup. Assert that workspace creation form requests company name and redirects user to dashboard upon completion.
