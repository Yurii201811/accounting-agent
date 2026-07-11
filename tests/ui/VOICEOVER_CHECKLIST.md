# Operations cockpit assistive-technology release checklist

Automated Playwright and axe checks cover semantics, keyboard operation, focus, WCAG 2.2 A/AA rules, forced colors, reduced motion, and every supported locale/mode/role state. Before a public release, complete this short macOS VoiceOver pass against the generated synthetic preview:

- [ ] The page title and “Move the close forward” heading are announced on load.
- [ ] Landmarks are announced in order: safety context, banner, navigation, main, content information.
- [ ] The skip link moves the VoiceOver cursor and keyboard focus to main content.
- [ ] View settings announce labels, selected values, and the Guided/Expert radio state.
- [ ] Changing language announces Swedish labels without losing the current control.
- [ ] Review filtering announces “1 item shown” / “1 post visas” and the empty state.
- [ ] The command dialog announces its title and keeps navigation inside the modal. Escape returns focus to “Find work”; selecting a command moves focus to the selected section heading.
- [ ] Guided and Expert content is not announced when visually hidden.
- [ ] Integration table headers are associated with every provider cell in Expert view.
- [ ] No safety state is communicated by color alone.

Record the tester, macOS version, browser version, VoiceOver version, date, and any finding in the release QA report. Do not mark this checklist complete from axe results alone.
