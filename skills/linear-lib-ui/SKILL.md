---
name: linear-lib-ui
description: Build React interfaces with linear-lib, a Linear-style component library distributed as a shadcn registry (Base UI primitives, Motion springs, OKLCH tokens, line-art figures). Use when adding linear-lib components to a project, building pages or screens in its style, choosing springs and transitions, or changing the library itself (src/components, src/lib, registry).
---

# linear-lib UI

linear-lib is a set of React 19 + Tailwind CSS 4 components in the visual language of linear.app:
dense controls, true-black dark theme, one motion vocabulary, interruptible CSS enter/exit. It ships
as a **shadcn registry**: the CLI copies source files into the consumer project, so the code is theirs.

Human docs (Ukrainian) live in the linear-lib repo: `docs/installation.md`, `docs/components.md`,
`docs/theming.md`, `docs/layout.md`, `docs/motion.md`, `docs/recipes.md`. For figures use the
`linear-figure` skill.

## 1. Install into a project

Requirements: React 19, Tailwind 4, TypeScript, `components.json` (`npx shadcn@latest init`) with
`@/components`, `@/lib`, `@/hooks` aliases, and `"allowImportingTsExtensions": true` in tsconfig
(the figure engine imports `.ts` paths; the Vite template already has it).

The registry must be served. Locally, from the linear-lib repo:

```bash
npm install
npm run registry:build            # registry.json -> public/r/*.json
npm run dev -- --port 5175        # serves http://localhost:5175/r/<name>.json
```

In the consumer project (`REG` = `http://localhost:5175/r` or the hosted URL):

```bash
npx shadcn@latest add $REG/theme.json            # writes src/linear-lib.css
npx shadcn@latest add $REG/button.json $REG/tabs.json
```

Then replace the main CSS file's content with `@import "./linear-lib.css";` (it already imports
tailwindcss, tw-animate-css, shadcn/tailwind.css and the fonts). Registry dependencies resolve
automatically. Optional alias: `"registries": { "@linear": "<REG>/{name}.json" }` in components.json,
then `npx shadcn@latest add @linear/button`.

App wrappers (once, in `main.tsx`):

```tsx
<ThemeProvider attribute="class" defaultTheme="dark" disableTransitionOnChange>  {/* next-themes */}
  <MotionConfig reducedMotion="user">                                            {/* motion/react */}
    <TooltipProvider delay={400}>                                                 {/* only if tooltips are used */}
      <App />
      <Toaster position="bottom-right" />                                        {/* only if sonner is used */}
    </TooltipProvider>
  </MotionConfig>
</ThemeProvider>
```

In a client-only Vite SPA, also pass `scriptProps={{ type: "application/json" }}` to `ThemeProvider`
(React 19 otherwise logs "Encountered a script tag" in dev) and set the initial theme class with a tiny
inline script in `index.html` `<head>` (see this repo's `index.html`). Do not do this in Next.js/SSR.

Before installing, check what is already there (`ls src/components/ui src/components/motion`). If a
Radix-based shadcn component with the same name exists, the CLI asks to overwrite: confirm with the user.

## 2. Catalogue (49 registry items)

Libraries: `theme` (CSS tokens), `utils` (`cn`), `motion` (`spring`, `ease`, `swap`, `fade`,
`rubberband`, `project`), `keys` (`keyLabel`, `isMac`), `use-measure` (`useMeasure`),
`figure-engine` (`src/lib/figure/**`).

UI primitives (`@/components/ui/<name>`), all on **Base UI**:
accordion, avatar, badge, button, card, checkbox, command, dialog, dropdown-menu, input, input-group,
input-otp, kbd, label, popover, progress, select, separator, sheet, skeleton, slider, sonner, switch,
table, tabs, textarea, toggle, toggle-group, tooltip.

Motion components (`@/components/motion/<name>`):

| Item | Use for |
| --- | --- |
| `liquid-indicator` | One highlight that flows between siblings (tabs, segments, nav, lists). Put it inside a `relative` container whose children toggle `data-active` / `aria-selected`; siblings need `relative z-10` |
| `morph-button` | Button with `status="idle" \| "loading" \| "success" \| "error"`; width follows the label |
| `morph-popover` | Trigger that morphs into its own panel; `children: (close) => ReactNode` |
| `dynamic-island` | Pill that reshapes for each `mode` |
| `auto-height` | Container that animates its height to its content (steps, errors) |
| `number-ticker` | Rolling digits; `value`, `format` (Intl options) |
| `text-morph` | Shared letters slide between two words |
| `scramble-text` | Text resolving from random glyphs; `trigger="mount" \| "view" \| "hover" \| "none"` |
| `elastic-slider` | Control Center slider with rubber-band; `label` is required |
| `spotlight-card` | Card lit by the cursor |
| `glow-tile` | `GlowTileGrid` + `GlowTile`: one ember glow that moves to the active tile |
| `grid-backdrop` | Decorative column grid with a beam (auth pages) |

Figures (`@/components/figure/*`): `figure` (`<Figure>`, `<FigureStatic>`), `figure-card`
(`<FigureCard>`, `<FigureGrid>`). See the `linear-figure` skill.

Variants worth knowing: Button `variant` default | brand | secondary | outline | ghost | destructive |
link, `size` xs | sm | default | lg | icon | icon-xs | icon-sm | icon-lg. Badge adds brand | positive |
warning. `TabsList variant="line"` for underline tabs. `ToggleGroup variant="segmented"` for an iOS
segmented control. `Sheet side="top" | "right" | "bottom" | "left"`. `Kbd glyphs="auto" | "mac"`.

## 3. Base UI, not Radix

- Composition uses the `render` prop, never `asChild`:
  `<DialogTrigger render={<Button variant="secondary" size="sm" />}>Open</DialogTrigger>`.
- Multi-value groups take arrays: `<ToggleGroup defaultValue={["week"]}>`.
- Popups expose `data-starting-style` / `data-ending-style`; animate them with the `motion-*` classes
  below, not keyframes, so they stay interruptible.

## 4. Tokens and surfaces

Use tokens only, never raw hex: `bg-background`, `bg-card`, `bg-popover`, `bg-surface`, `text-foreground`,
`text-muted-foreground`, `border-border`, `border-line`, `text-brand`, `bg-brand-solid`, `text-positive`,
`text-warning`, `text-negative`, `text-ember`, `shadow-pop`.

- Depth: page `bg-background` -> card `bg-card ring-1 ring-border` -> popup
  `bg-popover shadow-pop rounded-xl` -> floating bars `glass`. Do not nest cards; group with spacing.
- Status = pale background + coloured text (`Badge`). One saturated action per screen.
- Radii: controls `rounded-lg` (8) · menus `rounded-xl` (12) · cards `rounded-2xl` (16) · panels
  `rounded-4xl` (28). Inner radius = outer − padding.
- Type: UI text `text-[13px]`, body 14 px, captions 12 px, mono labels 11 px `tracking-[0.06em]`;
  headings `type-display` / `type-title`; numbers `tabular-nums`.
- Utilities: `lit` (top-lit filled buttons), `glass`, `text-shine`.
- Theme = `.dark` / `.light` class on `<html>`. Recolour by overriding variables, not components.

## 5. Layout rules

```tsx
<main className="mx-auto max-w-[1180px] px-4 pt-16 pb-28 sm:px-6">
  <header className="max-w-[640px]">
    <h1 className="type-display text-[clamp(2.5rem,6vw,4rem)]">Title</h1>
    <p className="mt-4 text-[15px] text-muted-foreground">One or two lines.</p>
  </header>
  <section className="mt-16 grid gap-4 md:grid-cols-2 xl:grid-cols-3">…</section>
</main>
```

- 4 px scale. Inside a control 4–8 px, inside a card 12–24 px, between cards 16 px, between sections
  48–96 px. A heading sits closer to its content than to the previous section.
- Controls default to `h-8` (32 px); keep one height per row (input + button + select). List rows 36–40 px.
  Touch targets ≥ 44 px.
- Sticky things inside a page: `top-[var(--header-h)]`. Text blocks ≤ ~640 px wide.
- Flexible columns get `min-w-0` so long names truncate. One column below 640 px; verify from 390 px.

## 6. Motion vocabulary

JS (Motion for React) takes springs from `@/lib/motion`; never invent curves in a component.

| Spring | visualDuration / bounce | Use |
| --- | --- | --- |
| `spring.snappy` | 0.20 / 0 | presses, toggles, small nudges |
| `spring.smooth` | 0.34 / 0 | default for anything that moves |
| `spring.morph` | 0.42 / 0.14 | shape changes (island, button, popover) |
| `spring.sheet` | 0.38 / 0.06 | sheets, panels |
| `spring.flick` | 0.36 / 0.22 | after a flick gesture |
| `spring.liquidLead` / `liquidTrail` | 0.26 / 0.08 · 0.40 / 0.04 | liquid indicator edges |

- Bounce > 0 only for gesture momentum or a morph "arriving". Menus, appearances, tab switches: no bounce.
- Content swaps: `variants={swap}` (with travel) or `fade` (in place) inside
  `<AnimatePresence mode="popLayout" initial={false}>`.
- CSS: `--ease-out`, `--ease-in-out`, `--ease-drawer`, springs `--ease-spring` / `-soft` / `-bounce`
  with `--duration-spring*`.
- Popup classes: `motion-pop` (popover, menu, select; add `origin-(--transform-origin)`), `motion-tip`
  (tooltip), `motion-dialog`, `motion-backdrop`, `motion-collapse` (accordion height).
- Press feedback on pointer-down (`active:scale-[0.97]`); hover changes colour/shadow only, never layout.
- Animate `transform`, `opacity`, `filter`; height only via `motion-collapse` or `AutoHeight`.
- Reduced motion must work: `MotionConfig reducedMotion="user"` + the theme's media query keep opacity
  and drop movement. Cursor effects are decorative; the UI must make sense without them.

## 7. Changing the library itself

Work in the linear-lib repo (`src/components/*`, `src/lib/*`, `src/hooks/*`).

- Library code never imports `src/app/*` (the registry generator fails on it).
- Files with hooks, events or Motion start with `"use client"`.
- Components import figure engine modules directly (`@/lib/figure/scene`, `@/lib/figure/draw`), never
  `@/lib/figure`: the shadcn CLI rewrites imports by their last path segment.
- New file in `components/ui`, `components/motion` or `components/figure` = new registry item
  automatically after `npm run registry`. Never edit `registry.json` or `public/r/*` by hand.
- Add a `Specimen` on `src/app/pages/components.tsx`; describe it in `docs/components.md` (Ukrainian).
- No new dependencies without need: animation is `motion` only, the figure engine has none.
- Conventional Commits (`feat(motion): …`, `fix(registry): …`, `docs: …`). Do not push unless asked.

## 8. Verify before you finish

In the linear-lib repo:

```bash
npm run build            # tsc -b + vite build: the main type check
npm run lint             # oxlint; 4 only-export-components warnings in shadcn files are expected
npm run test:figure      # engine, import, CLI and registry tests
npm run registry:build && npm run registry:check   # needs the dev server on :5175
```

In a consumer project: its own `tsc --noEmit` / build and lint. Then look at the result in both
themes (Shift T in the demo), at 390 / 768 / 1440 px, with reduced motion on, and by keyboard
(Tab order, visible focus, Esc closes popups). Demo routes for reference: `#/components`,
`#/issues`, `#/insights`, `#/sign-in`, `#/showcase`, `#/figures`, `#/studio`.
