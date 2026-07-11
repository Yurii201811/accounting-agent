import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";

import { openPreferences, expect, test } from "./fixtures";

const states = [
  ...["en-GB", "sv-SE"].flatMap((locale) =>
    ["guided", "expert"].flatMap((mode) =>
      ["small-firm", "accountant", "senior", "controller", "auditor", "operator"].map(
        (role) => ({ locale, mode, role }),
      ),
    ),
  ),
];

async function tabTo(page: Page, target: Locator, limit = 20): Promise<void> {
  for (let attempt = 0; attempt < limit; attempt += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => element === document.activeElement)) return;
  }
  await expect(target).toBeFocused();
}

test("all locale, mode, and role states pass WCAG 2.2 A/AA axe rules", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await openPreferences(page);

  for (const state of states) {
    await test.step(`${state.locale} · ${state.mode} · ${state.role}`, async () => {
      await page.locator("#locale-select").selectOption(state.locale);
      await page.locator("#role-select").selectOption(state.role);
      await page.locator(`input[name="view"][value="${state.mode}"] + span`).click();
      const scan = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();
      const violations = scan.violations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        targets: violation.nodes.map((node) => node.target),
      }));
      expect(violations, JSON.stringify({ state, violations }, null, 2)).toEqual([]);
    });
  }
});

test("skip link and command dialog are keyboard operable with focus restoration", async ({
  browserName,
  page,
}) => {
  await page.goto("/");
  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  if (browserName === "webkit") {
    // Headless macOS WebKit follows the system default that requires Full Keyboard
    // Access before Tab focuses links. Keyboard activation is still exercised below.
    await skipLink.focus();
  } else {
    await page.keyboard.press("Tab");
  }
  await expect(skipLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  const trigger = page.locator("#command-trigger");
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Find a section" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});

test("settings, review work, hash navigation, and modal focus are keyboard-only operable", async ({
  browserName,
  page,
}) => {
  await page.goto("/");

  const preferences = page.locator("details.workspace-preferences");
  const preferencesSummary = preferences.locator("summary");
  await tabTo(page, preferencesSummary);
  await page.keyboard.press("Enter");
  await expect(preferences).toHaveAttribute("open", "");

  const roleSelect = page.getByRole("combobox", { name: "Guidance perspective" });
  await page.keyboard.press("Tab");
  await expect(roleSelect).toBeFocused();
  await page.keyboard.type("Accountant");
  await expect(roleSelect).toHaveValue("accountant");
  await expect(page.locator("body")).toHaveAttribute("data-role", "accountant");

  await page.keyboard.press("Tab");
  await expect(page.getByRole("combobox", { name: "Language" })).toBeFocused();
  await page.keyboard.press(browserName === "webkit" ? "Alt+Tab" : "Tab");
  const guidedRadio = page.getByRole("radio", { name: "Guided" });
  const expertRadio = page.getByRole("radio", { name: "Expert" });
  await expect(guidedRadio).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(expertRadio).toBeChecked();
  await expect(page.locator("body")).toHaveAttribute("data-view", "expert");

  const trigger = page.locator("#command-trigger");
  const dialog = page.getByRole("dialog", { name: "Find a section" });
  await page.keyboard.press("ControlOrMeta+K");
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Search this cockpit" })).toBeFocused();

  const reverseTab = browserName === "webkit" ? "Alt+Shift+Tab" : "Shift+Tab";
  await page.keyboard.press(reverseTab);
  await expect(page.getByRole("button", { name: "Close" })).toBeFocused();
  await page.keyboard.press(reverseTab);
  expect(
    await dialog.evaluate((element) => element.contains(document.activeElement)),
    "Reverse tabbing must wrap to the last command without leaving the modal",
  ).toBe(true);

  const focusableCount = await dialog.locator("button, input, a[href]").count();
  for (let index = 0; index <= focusableCount; index += 1) {
    await page.keyboard.press(browserName === "webkit" ? "Alt+Tab" : "Tab");
    expect(
      await dialog.evaluate((element) => element.contains(document.activeElement)),
      "Focus must remain inside the modal while tabbing",
    ).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();

  await page.keyboard.press("ControlOrMeta+K");
  await page.keyboard.type("Review");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("link", { name: /Open Review/ })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#review$/);
  const reviewHeading = page.getByRole("heading", { level: 2, name: "Review" });
  await expect(reviewHeading).toBeFocused();

  const reviewSearch = page.getByRole("searchbox", { name: "Search review work" });
  await page.keyboard.press("Tab");
  await expect(reviewSearch).toBeFocused();
  await page.keyboard.type("does-not-exist");
  await expect(page.locator("#review-result-count")).toHaveText("0 items shown");
  await expect(page.locator("#review-empty")).toBeVisible();

  await page.keyboard.press("Tab");
  await expect(page.getByRole("combobox", { name: "Priority" })).toBeFocused();
  await page.keyboard.press(browserName === "webkit" ? "Alt+Tab" : "Tab");
  await expect(page.getByRole("button", { name: "Clear filters" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#review-result-count")).toHaveText("3 items shown");
  await expect(reviewSearch).toBeFocused();
});

test("focus indicators, forced colors, and reduced motion remain usable", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.goto("/");
  await page.keyboard.press("Tab");
  const focused = page.locator(":focus");
  await expect(focused).toBeVisible();
  const focusStyle = await focused.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
  });
  expect(focusStyle.outlineStyle).not.toBe("none");
  expect(Number.parseFloat(focusStyle.outlineWidth)).toBeGreaterThanOrEqual(2);
  await expect(page.locator(".environment-strip")).toBeVisible();
});
