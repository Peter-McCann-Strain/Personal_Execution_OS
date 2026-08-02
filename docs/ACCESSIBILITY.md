# Accessibility

Personal Execution OS targets WCAG 2.2 Level AA for the supported web and PWA
experience. This is an engineering target, not a certification claim.
Automated tests cover many detectable failures, while keyboard, screen-reader,
zoom, reflow, comprehension, and cognitive usability still require human
review.

The target and review process follow the
[W3C WCAG 2 overview](https://www.w3.org/WAI/standards-guidelines/wcag/),
[ARIA Authoring Practices Guide](https://www.w3.org/WAI/ARIA/apg/), and
[W3C evaluation guidance](https://www.w3.org/WAI/test-evaluate/). W3C notes
that automated tools alone cannot determine conformance; knowledgeable human
evaluation remains necessary.

## Supported accessibility contract

Every user-facing change should preserve:

- semantic page regions and a logical heading hierarchy;
- native buttons, links, fields, and dialogs where HTML provides them;
- an accessible name for every interactive control;
- complete keyboard operation with visible focus;
- focus placement and restoration for dialogs and route transitions;
- text and meaningful controls that meet AA contrast;
- information that is not communicated by colour, shape, position, or motion
  alone;
- status, validation, loading, and error messages that assistive technology can
  discover;
- reduced-motion behavior through `MotionConfig`;
- reflow without loss of function at 320 CSS pixels;
- usable content at 200% browser zoom and text spacing overrides;
- meaningful image alternative text, with decorative images hidden;
- touch targets and spacing suitable for phone interaction.

Prefer native HTML. ARIA can expose semantics but does not add the keyboard
behavior of a native control.

## Automated evidence

CI runs Playwright with `@axe-core/playwright` across:

- desktop Chromium using Playwright's Desktop Chrome profile;
- desktop Firefox using Playwright's Desktop Firefox profile;
- desktop WebKit using Playwright's Desktop Safari profile;
- mobile Chromium using Playwright's Pixel 7 profile; and
- mobile WebKit using Playwright's iPhone 15 profile.

The current route scan covers:

- all public and authenticated primary routes in every configured browser and
  device project;
- `/welcome`, `/dashboard`, `/workbench`, and `/settings` at 390×844;
- the same representative routes at 320×700;
- WCAG 2 A/AA, WCAG 2.1 A/AA, and WCAG 2.2 AA axe tags.

The browser suite uses fictional data and mocked setup/session API responses.
It checks accessibility issues that axe can detect in those rendered fixtures.
It does not cover live-provider content, every application state, or issues
that require human review.

Run it with:

```sh
cd frontend
npm run test:e2e:install
npm run test:a11y
```

Component and page behavior is also tested under `frontend/tests/`, including
keyboard handling, accessible names, status regions, and design-system
semantics. Playwright critical-path tests cover selected responsive
interactions and the PWA cache boundary.

The mobile projects emulate the selected browser engine, viewport, user agent,
touch input, and device scale factor. They do not reproduce a physical device's
operating-system accessibility stack, virtual keyboard, browser chrome, safe
areas, memory pressure, installation prompts, or background lifecycle. Complete
the manual phone and assistive-technology review below on representative
physical iOS and Android devices before calling a release device-validated.

### Current axe exemptions

Exemptions live in `frontend/e2e/a11y-config.ts` and must remain narrow,
explained, and reviewed:

- contrast scanning excludes the decorative gradient logo because adjacent
  text supplies the name;
- contrast scanning excludes selected sparkline and chart tick regions where
  the parent supplies a text summary;
- the Sonner toast container is excluded from the landmark-uniqueness rule
  while retaining its announcement behavior;
- the `region` rule is disabled globally because two floating application
  bridges render outside the usual landmarks and announce through live regions.

An exemption is debt, not a passed rule. A pull request adding or widening one
must explain why the underlying issue cannot be fixed, identify the
screen-reader alternative, and add a revisit condition.

## Required manual review

Automation cannot prove focus order, screen-reader comprehension, text
clipping, useful alternative text, or the absence of keyboard traps. Complete
this protocol for a new page, interaction pattern, or release candidate.

### Keyboard

1. Reload the page and put the pointing device aside.
2. Navigate forward and backward with `Tab` and `Shift+Tab`.
3. Confirm focus is always visible and follows a meaningful order.
4. Operate every control with its conventional key.
5. Open each dialog or popover, confirm focus enters it, and close with
   `Escape` when that pattern expects it.
6. Confirm focus returns to the invoking control after close.
7. Verify that only a modal surface can contain focus.
8. Complete the primary task and recover from a validation error.

### Screen reader

Test at least one combination available to the reviewer:

- VoiceOver with Safari on current macOS or iOS;
- NVDA with Firefox or Chrome on current Windows;
- TalkBack with Chrome on current Android.

Check:

1. page title, main landmark, and first heading identify the view;
2. landmarks and headings provide a useful navigation outline;
3. controls announce name, role, state, value, and validation;
4. loading, success, failure, and background updates are announced once and
   at an appropriate priority;
5. tables, charts, graphs, and progress displays have an equivalent textual
   explanation;
6. a dialog has a name, description where useful, contained focus, and a
   predictable close;
7. icon-only controls have names that describe the action;
8. the primary workflow can be completed without spatial guesswork.

### Zoom, reflow, and text spacing

1. At a 1280 CSS-pixel desktop viewport, set browser zoom to 200%.
2. Check the same task at 400% where the layout becomes a narrow reflow.
3. At 320 CSS pixels, verify there is no two-dimensional scrolling except for
   content that genuinely requires it, such as a data visualization.
4. Apply the WCAG text-spacing values: line height 1.5, paragraph spacing 2,
   letter spacing 0.12em, and word spacing 0.16em.
5. Confirm text is not clipped, overlapped, or hidden and controls remain
   operable.

### Motion, colour, and contrast

1. Enable the operating system's reduced-motion preference.
2. Confirm information and task completion do not depend on animation.
3. Inspect light and dark themes.
4. Use a contrast analyser for text or controls touched by the change.
5. Verify charts, statuses, and priorities remain understandable without
   colour.
6. Check focus indicators against every background they cross.

### Phone and touch

1. Test portrait at 320 and 390 CSS pixels.
2. Test landscape where the feature is likely to be used.
3. Confirm drawers, dialogs, sticky controls, and the virtual keyboard do not
   hide the current task.
4. Confirm targets are separated enough to avoid accidental activation.
5. Test PWA standalone mode as well as a normal browser tab when possible.

## Evidence record

For a release or material UI pull request, record:

```text
Change or revision:
Routes and workflows:
Automated command and result:
Keyboard/browser/OS:
Screen reader/browser/OS:
Zoom and text-spacing result:
Reduced-motion result:
Phone viewport/device result:
Known exemptions or defects:
Reviewer and date:
```

Do not write "WCAG compliant" from an axe result. State exactly what was tested
and which known exemptions or untested environments remain.

## Component review rules

### Dialogs

- use an accessible dialog primitive;
- provide a visible title;
- move focus inside only after open;
- prevent background interaction while modal;
- close predictably and restore focus;
- do not rely on clicking outside as the only close action.

### Forms

- associate a visible label with every field;
- put instructions before the input when possible;
- connect errors programmatically and preserve user input;
- identify required fields in text and semantics;
- do not disable submission without explaining why;
- announce completion without unexpectedly moving focus.

### Data visualisations and graphs

- provide a concise text summary of the conclusion;
- expose values through a list, table, details panel, or labelled focusable
  elements;
- do not make hover the only inspection method;
- provide keyboard selection where nodes or points are interactive;
- use colour as a redundant cue only.

### Notifications and live updates

- use polite announcements for routine status;
- reserve assertive alerts for conditions requiring immediate attention;
- prevent repeated bridge or polling events from announcing duplicate content;
- leave enough time to read transient content or retain it in a discoverable
  history.

## Documentation accessibility

Mermaid diagrams are supplementary. The paragraph before or after each diagram
must state its conclusion so the narrative remains usable when the diagram is
not exposed to a screen reader. Keep tables narrow; use subsections or lists
when a table would require horizontal scrolling on a phone.

Screenshots require useful alt text and a note when their content is synthetic.
Do not put essential instructions only inside an image.

The primary README, architecture, developer, configuration, capability,
integration, and documentation-index pages use wrapping lists in place of
dense matrices. Large flowcharts use a vertical layout, and every diagram has
a prose conclusion. CI lints all tracked Markdown and renders every discovered
Mermaid block. These checks provide structural evidence; a manual screen-reader
review of the documentation and physical-device validation of the PWA have not
been completed.

## Reporting an accessibility defect

Use the bug template and include:

- route and action;
- browser, operating system, zoom, and assistive technology;
- expected and observed result;
- keyboard or announcement sequence;
- fictional or redacted evidence only.

Treat a blocked primary task, keyboard trap, invisible focus, missing control
name, or destructive action that cannot be reviewed as a release-blocking
defect.

## Related guides

- Contributors should apply the
  [frontend conventions](DEVELOPER_GUIDE.md#frontend-conventions).
- Maintainers should include the manual evidence record in release review.
