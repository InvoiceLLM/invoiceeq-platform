import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.benchmark.generator import generate_daily_batch
from tests.e2e.pdf_builder import build_invoice_pdf

OUT_DIR = os.path.dirname(__file__)

# One clean invoice for the ingestion+chat window test
[inv1] = generate_daily_batch("US", day_seed=99001, count=1)
path1 = os.path.join(OUT_DIR, "ingestion_test.pdf")
build_invoice_pdf(path1, **inv1.pdf_kwargs)
print("Wrote", path1)
print("Ground truth:", inv1.ground_truth)

# A different clean invoice (different vendor) for the trainer New Vendor scope test
[inv2] = generate_daily_batch("US", day_seed=99002, count=1)
path2 = os.path.join(OUT_DIR, "trainer_new_vendor_test.pdf")
build_invoice_pdf(path2, **inv2.pdf_kwargs)
print("Wrote", path2)
print("Ground truth:", inv2.ground_truth)
