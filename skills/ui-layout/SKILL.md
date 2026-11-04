---
name: ui-layout
description: Use when laying out or reviewing any interface (pages, panels, cards, forms, toolbars, widgets, desktop/mobile apps) to get composition right — spacing scale, grouping by proximity, alignment, visual hierarchy, nested corner radii, control and touch-target sizes, text measure, grids and responsive breakpoints — plus a measurable audit (blur/squint test, spacing checks). Research-backed rules with sources; pairs with the morphkit skill for React UI.
---

# UI layout & composition

Good layout is mostly **space used on purpose**: a small spacing scale, related things close, unrelated
things apart, everything aligned to a few edges, one clear focal point. Apply the steps in order; then run
the audit. Rules marked *(heuristic)* are house defaults, not cited standards.

## 1. Decide the hierarchy before drawing anything

- List the screen's content and rank it: what must be seen first, second, third. Place the most important
  items near the top and the leading side — people read top-to-bottom, leading-to-trailing [3].
- Hierarchy comes from **contrast** (value/saturation against the surroundings, not the hue itself),
  **scale** and **grouping/space** [2].
- Use **≤ 3 type sizes** for a view (e.g. body 14–16 px, subhead 18–22 px, header up to ~32 px) and let at most
  **2 elements be big** [2]. ≤ 3 contrast levels; ≈ 2 primary + 2 secondary colors; never rely on color alone [2].
- Give the most important element the most space around it ("let it breathe"); add a container (border,
  background) only when whitespace alone does not separate groups [2].
- Use progressive disclosure (menus, disclosure, nested views) instead of showing everything [3].

## 2. Use one spacing scale

- Base unit **8 px** with a **4 px** half-step: `0 2 4 8 12 16 24 32 40 48 64 80`. Use multiples of 8 for
  dimensions, padding and margins; pair an 8 pt UI grid with a 4 pt baseline grid for text [4][5].
- Pick by range [5]:
  - **0–8 px** — inside small, dense components: badge/icon-button padding, title ↔ description in a card,
    trigger ↔ dropdown gap.
  - **12–24 px** — component padding, gaps between controls, card padding.
  - **32–80 px** — between page sections and around major regions.
- Text-only blocks (buttons, chips): set the font size, let **padding** define the height; full-width blocks:
  padding sets height, a consistent side margin sets width [4].
- Fewer options = faster, more consistent decisions ("removing 7 of every 8 spacing options") [4].
- In code: spacing tokens (CSS custom properties / theme constants), `gap` on flex/grid instead of margins on
  children, no one-off values.

## 3. Group with proximity

- Elements near each other read as related; separated ones as different groups. Proximity overpowers
  color and shape similarity [1].
- **Inner space < outer space.** The gap inside a group must be clearly smaller than the gap between groups.
  *(heuristic: outer ≥ 2× inner, e.g. 8 inside / 16–24 between / 32+ between sections.)*
- Headings sit **closer to the content they label** than to the previous section [1][2].
- Forms: a label is closer to its own field than to the previous field; chunk long forms into meaningful
  groups (12 fields → 3 groups of 4 feel easier) [1][11].
- Keep actions next to what they act on; far-away controls get missed ("tunnel vision") [1].
- Don't park unrelated buttons together (e.g. "Add" next to "Next / Save / Cancel") [1].
- Re-check groupings at every breakpoint — stacking columns can separate things that belong together [1].

## 4. Align to few edges

- Aligned items are perceived as related; **indentation** signals subordination [3]. Keep a small number of
  vertical alignment lines per view (content edge, label column, action column).
- Left-align text blocks and labels (leading-align in RTL); center only short, single-line, symmetric content.
- Optical alignment: icons and round shapes may need ±1–2 px nudges to *look* aligned *(heuristic)*.
- Numbers in tables/tickers: tabular figures, right-aligned columns.

## 5. Corners: nested radius

- Inner radius = **outer radius − padding (gap)** so corner gaps stay even [7].
  `--inner-radius: calc(var(--outer-radius) - var(--padding));`
  Example: card 24 px radius with 8 px padding → children 16 px.
- If padding ≥ outer radius, use a small inner radius (≈ 4–8 px) or square *(heuristic)*.
- Pills (radius = height / 2) for controls; surfaces 12–24 px; one radius family per product *(heuristic)*.

## 6. Control and target sizes

| Platform / standard | Minimum target |
|---|---|
| WCAG 2.2 SC 2.5.8 (AA) | **24 × 24 CSS px**, or enough spacing that 24 px circles centred on targets don't overlap [6] |
| Apple iOS / iPadOS / watchOS | **44 × 44 pt** default control size (28 × 28 minimum); macOS 28 × 28 (20 × 20 min); visionOS 60 × 60 (28 min) [9] |
| Android / Material | **48 × 48 dp** (~9 mm), separated by ≥ 8 dp; touch area may extend beyond the visible icon [10] |

- Desktop web defaults *(heuristic, = morphkit)*: controls 36 / 44 / 52 px high (sm / md / lg),
  icons 16 / 18 / 20 px at one stroke width, horizontal pill padding ≈ 0.45 × height.
- Touch UIs: ≥ 44 px (≥ 48 px Android). Pad small icons to reach the target size instead of enlarging the glyph [10].
- Keep a consistent control height per row (inputs, buttons, selects side by side share one height).

## 7. Text measure and rhythm

- Body line length **50–75 characters**; never above ~80 (WCAG 1.4.8). In CSS: `max-width: ~70ch` (adjust
  per font) [8].
- Line height ≈ 1.4–1.6 for body, 1.1–1.25 for headings *(heuristic)*; snap vertical rhythm to the 4 px
  baseline [4].
- Prepare for larger text (Dynamic Type / browser zoom): rows grow, side-by-side items may stack [3].

## 8. Grids and responsive layout

- Breakpoints (pick one set and stick to it):
  - Material / Android window size classes: **compact < 600 dp**, **medium 600–840**, **expanded 840–1200** [12].
  - GitHub Primer: **narrow < 768 px → 1 column**, **regular ≥ 768 → up to 2**, **wide ≥ 1400 → up to 3**;
    page padding 16 px, 24 px from 1280 px [13].
- Design the smallest and largest layouts first, then the middle [3]. Respect safe areas and system margins [3].
- Narrow screens: one column, full-width controls in forms, sticky primary action near the thumb *(heuristic)*.
- Never lose functionality on small screens; split complex multi-column views into multiple views [13].
- Prefer intrinsic layouts: CSS grid `repeat(auto-fit, minmax(240px, 1fr))`, flex-wrap clusters,
  `clamp()` for fluid spacing, container queries for components that live in different widths.
- Controls float above content: Apple asks to differentiate controls from content, e.g. Liquid Glass
  material for controls and content extending underneath bars [3] — morphkit's `LiquidGlass` does this
  on the web.

## 9. Audit (run this every time)

1. **Blur / squint test.** Blur a screenshot by 5–10 px (or squint): the intended groups and the single most
   important element must still stand out; a 20 px blur reveals accidental focal points such as strong
   imagery [2]. Playwright:
   ```js
   await page.addStyleTag({ content: 'body{filter:blur(8px)}' });
   await page.screenshot({ path: 'blur.png', fullPage: true });
   ```
2. **Spacing scan** — every padding/gap/margin is on the scale; inner < outer everywhere; heading-to-content
   < section-to-section. Script it: collect `getComputedStyle` paddings/gaps of all elements and list values
   not in the scale.
3. **Alignment scan** — count distinct left edges of text blocks in a view (`getBoundingClientRect().left`);
   more than ~3–4 means drifting alignment *(heuristic)*.
4. **Radius scan** — nested surfaces follow outer − padding.
5. **Targets** — all interactive elements ≥ 24 px (web AA), ≥ 44 px on touch [6][9].
6. **Measure** — long text ≤ ~75 characters per line [8].
7. **Breakpoints** — screenshot at 375, 768, 1024, 1440 px; check groupings didn't split [1][13].
8. **Content stress** — long names, empty states, huge numbers, other languages (see the `break-ui` skill).
9. **Contrast** — text and icons meet WCAG contrast against their real backgrounds (glass included) [9].

## 10. Quick fixes for common smells

| Smell | Fix |
|---|---|
| Everything equally spaced, nothing groups | Shrink spacing inside groups, grow it between groups [1]. |
| Heading floats between sections | Move it closer to its content [1][2]. |
| Many competing bold/large things | Max 2 big elements, 3 sizes, 3 contrast levels [2]. |
| Boxes inside boxes inside boxes | Remove containers; use whitespace for grouping, containers sparingly [2]. |
| Corners look "off" in nested cards | inner radius = outer − padding [7]. |
| Random 13 / 17 / 22 px gaps | Snap to the 4/8 scale [4][5]. |
| Tiny icon buttons on touch | Pad to 44/48 targets [9][10]. |
| Wall of full-width text | `max-width: 70ch` [8]. |

## Sources

1. Nielsen Norman Group — *Proximity Principle in Visual Design*. https://www.nngroup.com/articles/gestalt-proximity/
2. Nielsen Norman Group — *Visual Hierarchy in UX: Definition*. https://www.nngroup.com/articles/visual-hierarchy-ux-definition/
3. Apple Human Interface Guidelines — *Layout*. https://developer.apple.com/design/human-interface-guidelines/layout
4. spec.fm — *The 8-Point Grid*. https://spec.fm/specifics/8-pt-grid
5. Atlassian Design System — *Spacing*. https://atlassian.design/foundations/spacing
6. W3C — *Understanding SC 2.5.8 Target Size (Minimum)*, WCAG 2.2. https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
7. Cloud Four — *The Math Behind Nesting Rounded Corners*. https://cloudfour.com/thinks/the-math-behind-nesting-rounded-corners/
8. Baymard Institute — *Readability: The Optimal Line Length*. https://baymard.com/blog/line-length-readability
9. Apple Human Interface Guidelines — *Accessibility* (control sizes, contrast). https://developer.apple.com/design/human-interface-guidelines/accessibility
10. Google — *Touch target size* (Android accessibility). https://support.google.com/accessibility/android/answer/7101858
11. Nielsen Norman Group — *Form Design Quick Fix: Group Form Elements Effectively Using White Space*. https://www.nngroup.com/articles/form-design-white-space/
12. Android Developers — *Use window size classes*. https://developer.android.com/develop/ui/compose/layouts/adaptive/use-window-size-classes
13. GitHub Primer — *Layout*. https://primer.style/product/getting-started/foundations/layout/
