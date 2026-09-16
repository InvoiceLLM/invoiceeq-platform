"""
InvoiceLLM — Partner API Test Runner (Python CLI)
Bypasses browser CORS and directly tests all live endpoints.
"""
import urllib.request
import urllib.error
import json
import time

TARGET_URL = "https://ca-invoice-website-dev.thankfulmeadow-4281ea23.eastus2.azurecontainerapps.io"
WEBHOOK_SECRET = "AdmInvoiceSecret2026"

def print_separator(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def test_support_ticket():
    print_separator("TEST 2: Support Ticket API (POST /api/contact)")
    url = f"{TARGET_URL}/api/contact"
    payload = {
        "name": "Partner Integration Agent",
        "email": "partner.tester@admsofttech.com",
        "subject": "Live API Test Runner",
        "message": "Automated pipeline validation from testing suite."
    }
    
    start = time.time()
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req) as resp:
            latency = int((time.time() - start) * 1000)
            data = json.loads(resp.read().decode())
            print(f"Status:   {resp.status} OK ({latency}ms)")
            print(f"Response: {json.dumps(data, indent=2)}")
            return True
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode()}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_inbound_webhook():
    print_separator("TEST 1: Inbound Webhook (POST /api/v1/email/mailintegration)")
    url = f"{TARGET_URL}/api/v1/email/mailintegration?key={WEBHOOK_SECRET}"
    
    # Boundary for multipart form
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="from"\r\n\r\n'
        f"vendor@sample-corp.com\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="to"\r\n\r\n'
        f"invoice@receive.invoicellm.admsofttech.com\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="subject"\r\n\r\n'
        f"Invoice #INV-2026-9901 for Services Rendered\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="text"\r\n\r\n'
        f"Please find attached invoice for payment.\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="attachment1"; filename="test_invoice.pdf"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
        f"%PDF-1.4\n%EOF\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    
    start = time.time()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    
    try:
        with urllib.request.urlopen(req) as resp:
            latency = int((time.time() - start) * 1000)
            data = json.loads(resp.read().decode())
            print(f"Status:   {resp.status} OK ({latency}ms)")
            print(f"Response: {json.dumps(data, indent=2)}")
            return True
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode()}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    print("Starting InvoiceLLM Live Partner API Test Suite...")
    print(f"Target: {TARGET_URL}")
    
    t2 = test_support_ticket()
    t1 = test_inbound_webhook()
    
    print("\n" + "=" * 60)
    print("SUMMARY RESULTS:")
    print(f"  Test 1 (Inbound Webhook): {'[PASS]' if t1 else '[FAIL]'}")
    print(f"  Test 2 (Support Ticket):  {'[PASS]' if t2 else '[FAIL]'}")
    print("=" * 60)
