import { openPreferences, expect, test } from "./fixtures";

test("review filters use correct EN and SV singular/plural copy", async ({ page }) => {
  await page.goto("/");
  const search = page.locator("#review-search");
  const resultCount = page.locator("#review-result-count");

  await expect(resultCount).toHaveText("3 items shown");
  await search.fill("VAT");
  await expect(resultCount).toHaveText("1 item shown");
  await expect(page.locator(".attention-row:not([hidden])")).toHaveCount(1);

  await openPreferences(page);
  await page.locator("#locale-select").selectOption("sv-SE");
  await expect(resultCount).toHaveText("1 post visas");

  await search.fill("finns-inte");
  await expect(resultCount).toHaveText("0 poster visas");
  await expect(page.locator("#review-empty")).toBeVisible();
  await page.getByRole("button", { name: "Rensa filter" }).click();
  await expect(resultCount).toHaveText("3 poster visas");
  await expect(search).toBeFocused();
});

test("command palette focuses a selected section and returns cancel focus", async ({ page }) => {
  await page.goto("/");
  const trigger = page.locator("#command-trigger");
  const dialog = page.getByRole("dialog", { name: "Find a section" });

  await page.keyboard.press("ControlOrMeta+K");
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Search this cockpit" })).toBeFocused();
  await page.getByRole("searchbox", { name: "Search this cockpit" }).fill("Review");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("link", { name: /Open Review/ })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/#review$/);
  await expect(page.getByRole("heading", { level: 2, name: "Review" })).toBeFocused();

  await trigger.click();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("valid preferences persist across reloads", async ({ page }) => {
  await page.goto("/");
  await openPreferences(page);
  await page.locator("#locale-select").selectOption("sv-SE");
  await page.locator("#role-select").selectOption("auditor");
  await page.locator('input[name="view"][value="expert"] + span').click();
  await page.reload();

  await expect(page.locator("html")).toHaveAttribute("lang", "sv-SE");
  await expect(page.locator("body")).toHaveAttribute("data-role", "auditor");
  await expect(page.locator("body")).toHaveAttribute("data-view", "expert");
  await expect(page.locator("#locale-select")).toHaveValue("sv-SE");
  await expect(page.locator("#role-select")).toHaveValue("auditor");
});

test("invalid saved preferences fail closed to supported defaults", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("accounting-cockpit-locale", "xx-INVALID");
    window.localStorage.setItem("accounting-cockpit-role", "super-admin");
    window.localStorage.setItem("accounting-cockpit-view", "unrestricted");
  });
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("lang", "en-GB");
  await expect(page.locator("body")).toHaveAttribute("data-role", "small-firm");
  await expect(page.locator("body")).toHaveAttribute("data-view", "guided");
});

test("unavailable local storage degrades without breaking the cockpit", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("Storage denied", "SecurityError");
      },
    });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Move the close forward." })).toBeVisible();
  await expect(page.locator("body")).toHaveAttribute("data-view", "guided");
  await expect(page.locator("body")).toHaveAttribute("data-role", "small-firm");
});

test("hash navigation exposes current section state", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Connections", exact: true }).click();
  await expect(page).toHaveURL(/#integrations$/);
  await expect(page.getByRole("link", { name: "Connections", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByRole("heading", { level: 2, name: "Integrations" })).toBeVisible();
});

test("connector guidance names tenant, company, and environment binding", async ({ page }) => {
  await page.goto("/#integrations");
  await expect(page.locator("#integrations")).toContainText(
    "Exact tenant, company, and environment binding",
  );
  await openPreferences(page);
  await page.locator("#locale-select").selectOption("sv-SE");
  await expect(page.locator("#integrations")).toContainText(
    "Exakt tenant-, företags- och miljöbindning",
  );
});
