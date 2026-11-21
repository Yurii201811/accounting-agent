import { expect, test as base } from "@playwright/test";

type BrowserHealthFixtures = {
  browserHealth: void;
};

export const test = base.extend<BrowserHealthFixtures>({
  browserHealth: [
    async ({ page }, use, testInfo) => {
      const failures: string[] = [];

      page.on("console", (message) => {
        if (message.type() === "error" || message.type() === "warning") {
          const location = message.location();
          failures.push(
            `[console.${message.type()}] ${message.text()} ${location.url}:${location.lineNumber}`,
          );
        }
      });
      page.on("pageerror", (error) => failures.push(`[pageerror] ${error.stack ?? error.message}`));

      await use();

      if (failures.length) {
        await testInfo.attach("browser-errors", {
          body: failures.join("\n"),
          contentType: "text/plain",
        });
      }
      expect(failures, "The cockpit must not emit browser warnings or errors").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect } from "@playwright/test";

export async function openPreferences(page: import("@playwright/test").Page): Promise<void> {
  const details = page.locator("details.workspace-preferences");
  if (!(await details.getAttribute("open"))) {
    await details.locator("summary").click();
  }
}
