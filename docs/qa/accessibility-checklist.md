# Accessibility release checklist

Automated Playwright and axe checks cover the supported locale, view, role, browser, and viewport states. They do not replace an assistive-technology review. Complete this checklist against the exact generated synthetic preview that is being released.

## Automated evidence

- [ ] English and Swedish pass in Guided and Expert views for all six roles.
- [ ] Chromium, Firefox, and WebKit complete without console warnings or errors.
- [ ] Default states at widths 320, 375, 414, 768, 1280, and 1920 have no global horizontal overflow; Swedish Expert with the long small-firm role also passes at 320 and 1280.
- [ ] Every exposed link, button, form control, summary, view toggle, and open command-dialog control measures at least 44 by 44 CSS px; no spacing exception is currently used.
- [ ] A genuine keyboard-only journey covers settings, review filtering and clearing, command-dialog focus containment, Escape return, hash navigation, and focus transfer to the selected section heading without programmatic click, fill, focus, or select actions.
- [ ] Axe reports zero WCAG 2.2 A/AA violations in every exposed state.
- [ ] Forced-colors and reduced-motion checks pass.
- [ ] Runtime requests remain inside the loopback synthetic preview bundle.

## Manual macOS VoiceOver pass

- [ ] Record tester name, UTC date, macOS version, browser and version, VoiceOver version, build revision, and preview bundle hash.
- [ ] Confirm the document title and main heading are announced on load.
- [ ] Traverse landmarks in a meaningful order: safety context, banner, navigation, main, and content information.
- [ ] Confirm the skip link moves both VoiceOver and keyboard focus to main content.
- [ ] Confirm settings expose labels, selected values, and Guided/Expert radio state.
- [ ] Change to Swedish and confirm labels update without losing the active control.
- [ ] Filter review work and confirm singular, plural, zero-result, and clear-filter states are announced.
- [ ] Open the command dialog and confirm its name and focus containment. Confirm Escape returns focus to “Find work”, while selecting a command moves focus to the selected section heading.
- [ ] Confirm visually hidden Guided/Expert content is not announced.
- [ ] In Expert view, confirm integration table headers are associated with provider cells.
- [ ] Confirm no approval, risk, or block state relies on color alone.
- [ ] Record every finding with severity, reproduction steps, expected result, and evidence path.

The shorter test-adjacent checklist is kept at `tests/ui/VOICEOVER_CHECKLIST.md`. Release evidence must state `passed`, `failed`, or `pending`; an axe pass must never be converted automatically into a manual VoiceOver pass.
