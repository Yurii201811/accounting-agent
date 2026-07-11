import { openPreferences, expect, test } from "./fixtures";

const widths = [320, 375, 414, 768, 1280, 1920] as const;
const responsiveScenarios = [
  ...widths.map((width) => ({ name: `default at ${width}px`, width })),
  {
    name: "Swedish Expert with the long small-firm role at 320px",
    width: 320,
    locale: "sv-SE",
    mode: "expert",
    role: "small-firm",
  },
  {
    name: "Swedish Expert with the long small-firm role at 1280px",
    width: 1280,
    locale: "sv-SE",
    mode: "expert",
    role: "small-firm",
  },
] as const;

const targetSelector = [
  "a[href]",
  "button",
  'input:not([type="radio"])',
  "select",
  "summary",
  ".view-toggle label",
].join(",");

async function targetSizeViolations(page: import("@playwright/test").Page, selector: string) {
  return page.locator(selector).evaluateAll((elements) =>
    elements
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0;
      })
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width < 44 || rect.height < 44;
      })
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName,
          text: element.textContent?.trim().slice(0, 60),
          width: rect.width,
          height: rect.height,
        };
      }),
  );
}

for (const scenario of responsiveScenarios) {
  test(`responsive integrity · ${scenario.name}`, async ({ page }) => {
    await page.setViewportSize({ width: scenario.width, height: 900 });
    await page.goto("/");
    if ("locale" in scenario) {
      await openPreferences(page);
      await page.locator("#locale-select").selectOption(scenario.locale);
      await page.locator("#role-select").selectOption(scenario.role);
      await page.locator(`input[name="view"][value="${scenario.mode}"] + span`).click();
      await expect(page.locator("html")).toHaveAttribute("lang", scenario.locale);
      await expect(page.locator("body")).toHaveAttribute("data-view", scenario.mode);
      await expect(page.locator("body")).toHaveAttribute("data-role", scenario.role);
      await expect(page.locator("#role-select option:checked")).toHaveText(
        "Redovisningskonsult, mindre byrå",
      );
    }

    const dimensions = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);

    const undersizedTargets = await targetSizeViolations(page, targetSelector);
    expect(undersizedTargets, JSON.stringify(undersizedTargets, null, 2)).toEqual([]);

    await page.locator("#command-trigger").click();
    const commandTargetViolations = await targetSizeViolations(
      page,
      "#command-dialog button, #command-dialog input, #command-dialog a[href]",
    );
    expect(commandTargetViolations, JSON.stringify(commandTargetViolations, null, 2)).toEqual([]);
    await page.keyboard.press("Escape");

    const wrappingTargets = await page.locator(
      [
        "button",
        ".wordmark",
        ".section-nav a",
        ".attention-action a",
        ".step-meta a",
        ".artifact-open",
        ".section-action a",
      ].join(","),
    ).evaluateAll((elements) =>
      elements
        .filter((element) => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0;
        })
        .filter((element) => getComputedStyle(element).whiteSpace !== "nowrap")
        .map((element) => ({ tag: element.tagName, text: element.textContent?.trim().slice(0, 60) })),
    );
    expect(wrappingTargets, JSON.stringify(wrappingTargets, null, 2)).toEqual([]);
  });
}

test("runtime requests are restricted to the loopback preview bundle", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto("/");
  await page.locator("#command-trigger").click();
  await page.getByRole("button", { name: "Close" }).click();

  const allowedPaths = new Set(["/", "/index.html", "/tokens.css", "/favicon.svg"]);
  const unexpected = requests.filter((requestUrl) => {
    const url = new URL(requestUrl);
    return url.hostname !== "127.0.0.1" || !allowedPaths.has(url.pathname);
  });
  expect(unexpected, JSON.stringify({ requests, unexpected }, null, 2)).toEqual([]);
});
