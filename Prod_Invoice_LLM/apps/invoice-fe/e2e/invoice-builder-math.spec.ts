import { test, expect } from "@playwright/test";
import { computeTotals, roundHalfUp, toNumber } from "@/lib/invoiceBuilderMath";

/**
 * Feature 20, task 20.2 — unit tests for the display-only totals mirror.
 *
 * These are pure function tests with no browser interaction. They live under
 * `e2e/` because Playwright is this app's only test runner (there is no
 * jest/vitest in `package.json`), and `playwright.config.ts` points at a single
 * `testDir`. Run them alone with:
 *
 *   npx playwright test e2e/invoice-builder-math.spec.ts
 *
 * The cases are deliberately the same ones BE task 17.1 asserts against
 * `services/invoice_builder.py::compute_totals`, because the whole point of
 * this module is that the two agree. If a case here is changed, change it
 * there too or the builder will show the user a total the server will not
 * produce.
 */

test.describe("computeTotals — mirrors BE compute_totals", () => {
  test("BE 17.1 case: [(3, 19.99), (1, 0.005)] → 59.97, 0.01, subtotal 59.98", () => {
    const totals = computeTotals(
      [
        { quantity: 3, unit_price: 19.99 },
        { quantity: 1, unit_price: 0.005 },
      ],
      0
    );
    expect(totals.amounts).toEqual([59.97, 0.01]);
    expect(totals.subtotal).toBe(59.98);
    expect(totals.grand_total).toBe(59.98);
  });

  test("tax is added to the subtotal, not to any line", () => {
    const totals = computeTotals([{ quantity: 2, unit_price: 10 }], 3.5);
    expect(totals.subtotal).toBe(20);
    expect(totals.tax_amount).toBe(3.5);
    expect(totals.grand_total).toBe(23.5);
  });

  test("string inputs from the grid's text fields are parsed", () => {
    const totals = computeTotals(
      [{ quantity: "3", unit_price: "19.99" }],
      "1.01"
    );
    expect(totals.amounts).toEqual([59.97]);
    expect(totals.grand_total).toBe(60.98);
  });

  test("an empty or half-typed field counts as zero rather than NaN", () => {
    const totals = computeTotals(
      [
        { quantity: "", unit_price: "10" },
        { quantity: "2", unit_price: "-" },
      ],
      null
    );
    expect(totals.amounts).toEqual([0, 0]);
    expect(totals.subtotal).toBe(0);
    expect(totals.grand_total).toBe(0);
  });

  test("no items is a zero total, not an error", () => {
    expect(computeTotals([], 0)).toEqual({
      amounts: [],
      subtotal: 0,
      tax_amount: 0,
      grand_total: 0,
    });
  });
});

test.describe("roundHalfUp — Decimal ROUND_HALF_UP semantics", () => {
  test("ties round away from zero in both directions", () => {
    expect(roundHalfUp(0.005)).toBe(0.01);
    expect(roundHalfUp(-0.005)).toBe(-0.01);
    expect(roundHalfUp(2.675)).toBe(2.68);
    expect(roundHalfUp(1.005)).toBe(1.01);
  });

  test("binary float noise does not leak into the result", () => {
    expect(roundHalfUp(3 * 19.99)).toBe(59.97);
    expect(roundHalfUp(0.1 + 0.2)).toBe(0.3);
  });

  test("below a tie still rounds down", () => {
    expect(roundHalfUp(1.004)).toBe(1.0);
    expect(roundHalfUp(-1.004)).toBe(-1.0);
  });
});

test.describe("toNumber", () => {
  test("blank, null and non-numeric text are zero", () => {
    expect(toNumber("")).toBe(0);
    expect(toNumber(null)).toBe(0);
    expect(toNumber(undefined)).toBe(0);
    expect(toNumber("abc")).toBe(0);
  });

  test("thousands separators typed by hand are tolerated", () => {
    expect(toNumber("1,250.00")).toBe(1250);
  });
});
