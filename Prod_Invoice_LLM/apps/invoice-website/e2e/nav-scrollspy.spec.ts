import { test, expect } from "@playwright/test";

test.describe("Header Navigation Scroll-Spy & Active Button Highlighting", () => {
  test("highlights Pricing button when scrolled to the pricing section", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation");
    const pricingLink = nav.getByRole("link", { name: "Pricing" });
    const featuresLink = nav.getByRole("link", { name: "Features" });

    // Scroll down directly to the #pricing section
    await page.locator("#pricing").scrollIntoViewIfNeeded();
    await page.waitForTimeout(600); // Allow scroll spy check to settle

    // Pricing link should be marked active with aria-current="page"
    await expect(pricingLink).toHaveAttribute("aria-current", "page");
    await expect(featuresLink).not.toHaveAttribute("aria-current", "page");

    // Verify active styling classes on the pricing button
    await expect(pricingLink).toHaveClass(/text-white/);
    await expect(pricingLink).toHaveClass(/drop-shadow-/);

    // Save screenshot of the header and pricing section
    await page.screenshot({
      path: "C:/Users/K Sonalkar/.gemini/antigravity-ide/brain/b3bd4725-e479-4127-a22a-3a934da401ff/pricing_nav_highlighted.png",
      fullPage: false,
    });
  });

  test("clicking Pricing button highlights Pricing instantly", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation");
    const pricingLink = nav.getByRole("link", { name: "Pricing" });
    const featuresLink = nav.getByRole("link", { name: "Features" });

    // Click Pricing
    await pricingLink.click();
    await page.waitForTimeout(600);

    await expect(pricingLink).toHaveAttribute("aria-current", "page");
    await expect(featuresLink).not.toHaveAttribute("aria-current", "page");
  });

  test("clicking Features button highlights Features", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation");
    const featuresLink = nav.getByRole("link", { name: "Features" });

    // Click Features
    await featuresLink.click();
    await page.waitForTimeout(600);

    await expect(featuresLink).toHaveAttribute("aria-current", "page");

    // Save screenshot of the header with Features highlighted
    await page.screenshot({
      path: "C:/Users/K Sonalkar/.gemini/antigravity-ide/brain/b3bd4725-e479-4127-a22a-3a934da401ff/features_nav_highlighted.png",
      fullPage: false,
    });
  });

  test("highlights Contact Us when visiting /contact", async ({ page }) => {
    await page.goto("/contact");
    const nav = page.getByRole("navigation");
    const contactLink = nav.getByRole("link", { name: "Contact Us" });
    const pricingLink = nav.getByRole("link", { name: "Pricing" });

    await expect(contactLink).toHaveAttribute("aria-current", "page");
    await expect(pricingLink).not.toHaveAttribute("aria-current", "page");
  });
});
