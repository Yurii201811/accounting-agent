import { openPreferences, expect, test } from "./fixtures";

const locales = [
  { value: "en-GB", heading: "Move the close forward." },
  { value: "sv-SE", heading: "För bokslutet framåt." },
] as const;
const modes = ["guided", "expert"] as const;
const roles = ["small-firm", "accountant", "senior", "controller", "auditor", "operator"] as const;

for (const locale of locales) {
  for (const mode of modes) {
    for (const role of roles) {
      test(`${locale.value} · ${mode} · ${role}`, async ({ page }) => {
        await page.goto("/");
        await openPreferences(page);
        await page.locator("#locale-select").selectOption(locale.value);
        await page.locator("#role-select").selectOption(role);
        await page.locator(`input[name="view"][value="${mode}"] + span`).click();

        await expect(page.locator("html")).toHaveAttribute("lang", locale.value);
        await expect(page.locator("body")).toHaveAttribute("data-locale", locale.value);
        await expect(page.locator("body")).toHaveAttribute("data-role", role);
        await expect(page.locator("body")).toHaveAttribute("data-view", mode);
        await expect(page.getByRole("heading", { level: 1, name: locale.heading })).toBeVisible();
        await expect(page.locator("#role-guidance")).not.toBeEmpty();
        await expect(page.locator(".guided-summary").first()).toBeVisible({
          visible: mode === "guided",
        });
        await expect(page.locator(".table-frame.expert-only .integration-table").first()).toBeVisible({
          visible: mode === "expert",
        });
      });
    }
  }
}
