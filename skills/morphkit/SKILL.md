---
name: morphkit
description: Use when building React UI with the user's morphkit library (spring motion engine, <Motion>, 50+ animated components, Liquid Glass) — installing it into a new or existing project (Vite, Next.js, Tauri), theming it, picking the right component, writing custom animated components on its engine, or extending/releasing morphkit itself. Covers exact APIs, setup steps, glass caveats and verification.
---

# morphkit — usage skill

morphkit is the user's own React motion kit. Source of truth:
`C:\Users\Dima\VSCodeProjects\_sandbox\test-motion-1\packages\morphkit`
(docs in `docs/`, generated API in `docs/api/`, gallery: `npm run playground` in the repo root).
Read the relevant doc file before using an API you are unsure about — never invent props.

What it gives you:
- **Engine**: `MotionValue` (closed-form spring; `set()` retargets keeping velocity), one rAF ticker
  that sleeps at rest, `<Motion>` that writes live styles to the DOM (**no React re-render per frame**).
- **50+ controlled components** with keyboard + ARIA, all on springs.
- **Liquid Glass**: refractive `LiquidGlass` + `GlassToggle`, `GlassSlider`, `GlassButton`, `GlassSegmented`.
- **Theme tokens** (`configureMorphkit`, `darkTheme`), Geist font.
- Time-driven primitives for rendering UI motion to video (see the `ui-morph-motion` skill).

## 1. Install into a project

morphkit is not on npm. Use the tarball:

```bat
cd C:\Users\Dima\VSCodeProjects\_sandbox\test-motion-1
npm run lib:pack
:: → out\morphkit-0.2.0.tgz
cd <your-app>
npm i C:\Users\Dima\VSCodeProjects\_sandbox\test-motion-1\out\morphkit-0.2.0.tgz @fontsource-variable/geist
```

- Peer deps: `react`, `react-dom` ≥ 18. Zero runtime deps.
- After changing morphkit: bump `version` in `packages/morphkit/package.json` (or reinstall the
  tgz after deleting `node_modules/morphkit`), `npm run lib:pack`, `npm i <tgz>` again.
- Linking the folder (`npm i ../test-motion-1/packages/morphkit`) needs `npm run lib:build` first and
  `resolve: { dedupe: ['react', 'react-dom'] }` in Vite (else "Invalid hook call").
- New Vite app: `npm create vite@latest app -- --template react-ts`, then install as above.

TypeScript: `"jsx": "react-jsx"`, `"moduleResolution": "bundler"` (or `node16`/`nodenext`).

Entry: `import '@fontsource-variable/geist'` once, `className="mk-root"` on the app root.

```tsx
import { configureMorphkit, darkTheme } from 'morphkit/react';
configureMorphkit({ theme: { ink: '#1D4ED8', canvas: '#EEF2FF' } }); // before createRoot().render
// or: configureMorphkit({ theme: darkTheme })
```

Framework notes:
- **Next.js App Router**: leaf modules are `'use client'`. Interactive usage (callbacks) must sit in
  your own `'use client'` component. Put `configureMorphkit` in a module imported by both the root
  layout and a client `Providers` component; inline `<style data-morphkit="" dangerouslySetInnerHTML={{ __html: morphkitCss() }} />` in `<head>`.
- **Tauri**: Windows (WebView2 = Chromium) gets full glass refraction; macOS/Linux (WebKit) get the
  frosted fallback automatically.

## 2. Pick the component

| Need | Use |
|---|---|
| Primary/secondary action | `Button variant="primary\|secondary\|soft\|ghost" size="sm\|md\|lg" icon loading` |
| Icon-only action | `IconButton icon label` (label required) |
| Async action with result | `MorphButton label onAction={() => promise}` |
| Play/pause | `PlayPauseButton playing onToggle` |
| On/off setting | `Toggle checked onChange label description` (`Switch` alias); glass: `GlassToggle` |
| Multi-select item | `Checkbox checked onChange indeterminate label` |
| One of few (vertical) | `RadioGroup options value onChange` |
| One of 2–5 (inline) | `SegmentedControl items value onChange variant="paper\|well"`; glass: `GlassSegmented` |
| Tabs with panels | `Tabs tabs={[{ value, label, content }]} value onChange` |
| Continuous value | `Slider value onChange min max step showValue format icons`; `VolumeSlider`; glass: `GlassSlider` |
| Filters | `Chips options selected onChange` |
| Choose from list | `Select options value onChange placeholder label` |
| Overflow actions | `Menu items={[{ label, icon, shortcut, danger, onSelect } \| 'separator']}` |
| Text | `TextInput label value onChange type icon hint error clearable onEnter` |
| Search | `SearchField value onChange onSubmit` (button → field) |
| Long text | `Textarea label value onChange maxLength minRows` |
| Code | `OTPInput value onChange length status onComplete` |
| Quantity | `NumberField value onChange min max step label` |
| Tags | `TagInput tags onChange placeholder` |
| Pages | `Pagination page count onChange` (1-based) |
| Wizard progress | `Stepper steps current` (0-based) |
| Formatting bar | `Toolbar items={[{ icon, label, active, onClick }]}` |
| ⌘K | `CommandPalette items={[{ label, icon, shortcut, group }]} onSelect` |
| Progress | `ProgressBar value` (`null` = indeterminate) · `ProgressRing value` (→ check at 1) |
| Loading content | `SkeletonSwap loading skeleton={<Skeleton …/>}` |
| Notifications | `const { toasts, push, dismiss } = useToasts()` + `<ToastStack toasts onDismiss fixed />` |
| Status / counts | `Badge tone` · `IconBadge icon count` · `NumberTicker value decimals prefix group` |
| Hint | `Tooltip label side` around a child |
| Confirm | `MorphDialog label title description confirmLabel danger onConfirm` |
| Disclosure | `Accordion items={[{ id, title, content }]} multiple` |
| Music UI | `MusicPlayer tracks onPlayChange onTrackChange` · `DynamicIsland state` · `LiveWaveform clock energy` |
| Chart | `LineChart series={{ values, labels }} prefix format` |
| People | `AvatarGroup people max` |
| Anything glass | `LiquidGlass radius tint interactive …` |
| Icons | `Icon name size color` — names: search check circle-check arrow-right arrow-up-right command rocket layers trash grid user-plus volume-low volume-high corner-down-left x sun moon bell heart plus minus volume-x chevron-down/up/left/right eye eye-off mail lock user alert-circle info x-circle star upload file copy settings pencil share more-horizontal calendar bold italic underline link image repeat shuffle minimize phone timer mic filter home inbox sparkles log-out archive. Add more: `iconPaths['name'] = [['path', d]]`. |

Every component is controlled: keep the state in the parent. Exact props: `docs/api/components.md`.

## 3. Animate your own UI (engine)

```tsx
import { springs } from 'morphkit';
import { Motion, useSpring, useMotionValue, useLiquid, useSpringColor, usePresence, swapLive, usePress, useHover, theme } from 'morphkit/react';

const p = useSpring(open ? 1 : 0, springs.morph);          // follows state on a spring
<Motion style={{ height: () => 44 + 200 * p.get(), borderRadius: 22, blur: () => (1 - p.get()) * 3, background: theme.ink }} />
```

- Style values: constant | MotionValue | `() => value`. Shorthands `x y scale scaleX scaleY rotate blur`
  (blur filter removed at 0). `attrs` for SVG (`d`, `cx`), `text` for live text.
- `MotionValue`: `set(v)`, `set(v, spring)`, `set(v, { spring, delay })`, `jump(v)` (drag),
  `release(velocity, target)` (fling), `get()` (subscribes inside live functions), `peek()`,
  `goal`, `velocity()`, `onRest(fn)`. Create with `useMotionValue(initial, spring?, precision=0.001)`.
- Springs `{ response, damping }`: `morph` (geometry), `snappy` (default), `smooth` (color/opacity, no
  overshoot), `enter`, `exit` (fast), `press`, `release` (slight bounce), `lead`/`trail` (liquid edges).
- Hooks: `useSpring`, `useSpringColor(color)` (hex/rgb), `useLiquid(start, end)` / `liquidTo(a, b, s, e)`,
  `usePresence(show) → { p, mounted }` + `swapLive(p, { blur, scale, y })`, `usePress() → { p, handlers }`,
  `useHover() → { h, handlers }`, `useSize(ref, fn)`, `useDismiss(open, [refs], fn)`, `useClock`,
  `useSignal`, `useLiveState(() => derived)`.
- Presence: `<SwapContent k>` (keyed blur swap), `<Reveal show>`, `<Collapse open>`,
  `<MorphSurface contentKey radius background padding={[x, y]}>` (one shape springs to its content).
- Debug: `setTimeScale(0.25)` (slow-mo), `setReducedMotion(true)`.

Rules (the kit's taste — follow them in custom components):
1. State in React, motion in MotionValues. Never `useState` per frame, never CSS transitions for motion.
2. Set targets in handlers or `useLayoutEffect`, never during render.
3. Interruptible: always `set()` from where it is; never restart from 0.
4. One shape morphs between states (`MorphSurface`) instead of cross-fading two.
5. Content swaps: blur 4–6 px + scale 0.92–0.96; exit fast, enter a beat later.
6. Travelling things are liquid: two edges on `lead`/`trail` springs; cap stretch.
7. Press = squash with min hold; release = slightly bouncy. Damping ≥ 0.75.
8. Measure real DOM rects (offsetLeft/useSize) for indicators — don't hardcode.
9. Sizes 36/44/52, icons 16/18/20 stroke 2, 4/8 px spacing, nested radius = outer − padding,
   colors only from `theme` (hex/rgb), soft layered shadows.
10. Custom buttons: `className="mku-btn mku-focus"` for reset + focus ring.

Complete recipes (hover card, morphing status pill, drag + fling sheet, liquid switch, live numbers):
`docs/custom-components.md`.

## 4. Liquid Glass

```tsx
import { LiquidGlass, GlassToggle, GlassSlider, GlassButton, GlassSegmented, useGlassSupport } from 'morphkit/react';

<LiquidGlass radius={28} tint="rgba(255,255,255,0.18)" style={{ padding: 20, color: '#fff' }}>…</LiquidGlass>
<LiquidGlass as="button" interactive radius="pill" onClick={…}>…</LiquidGlass>   // press inflate + jelly
<GlassToggle checked={on} onChange={setOn} ariaLabel="Wi-Fi" />                  // color default #34C759
<GlassSlider value={v} onChange={setV} label="Brightness" />
<GlassButton icon="plus" label="Add" />                                           // label = aria-label
<GlassSegmented value={tab} onChange={setTab} ariaLabel="Tabs" items={[{ value: 'home', label: 'Home', icon: 'home' }]} />
```

Optics props: `bezel`, `thickness` (1), `ior` (1.5), `profile` ('squircle' | 'circle' | 'lip'),
`lightAngle` (-135), `refraction` (1, live), `aberration` (0.35), `frost` (0.6 px, live),
`saturation` (1.3), `specular` (0.85, live). `tint` is live too. Springs for custom glass controls:
`GLASS_GROW`, `GLASS_SETTLE`, `GLASS_JELLY` (pill → lens → pill pattern in `docs/liquid-glass.md`).

Must-know caveats:
- Refraction = `backdrop-filter: url(#svg)` → **Chromium only** (Chrome/Edge/Electron/WebView2).
  Safari/Firefox/WebKit get a frosted fallback. `useGlassSupport()`, `setGlassRefraction(false)`.
- **Backdrop root**: no `filter`, `opacity < 1`, `mask`, `clip-path`, `mix-blend-mode`,
  `backdrop-filter`, `will-change` on any ancestor of glass — the glass would refract nothing.
- Don't scale glass > ~1.25× with transforms (resamples → blurry); animate width/height instead.
- Glass needs a rich backdrop (image, gradient, content). Use `tint` 0.2–0.5 for legible text.
- Each glass = one SVG filter; keep a handful of medium surfaces, not dozens of full-screen ones.

## 5. Verify (always)

1. `npx tsc --noEmit` in the app; `npm run build`.
2. Run dev (StrictMode on) and drive it with Playwright: click → assert `aria-checked`/`aria-selected`,
   keyboard Tab/Space/Arrows, no console errors.
3. Deterministic motion frames: `await page.clock.install()` before `goto`, then
   `await page.clock.pauseAt(Date.now() + 1000)`, trigger the interaction,
   `await page.clock.runFor(60)` → screenshot; repeat for a strip (60, 120, 200, 340, 600 ms).
4. Look at the strip: no jumps, nothing restarts, text never stretched, glass shows refraction
   (Chromium) — compare against the gallery (`npm run playground`).
5. Toggle `darkTheme` and reduced motion once.

## 6. Pitfalls → fixes

| Symptom | Fix |
|---|---|
| Invalid hook call | Duplicate React (linked package) → tarball or `dedupe`. |
| Value never animates | You passed `w.get()` (a number) instead of `w` / `() => w.get()`. |
| Restarts every click | MotionValue created during render or element remounted (`key`). |
| Theme ignored | `configureMorphkit` after first render → call before, or remount with `key`. |
| Colors don't spring | Token is a CSS var / hsl / named → use hex or rgb(a). |
| Glass empty | Ancestor creates a backdrop root (see caveats). |
| Glass blurry | Scaled with transform. |
| Unstyled focus/placeholder (SSR) | Inline `morphkitCss()` in `<head>` with `data-morphkit`. |

## 7. Changing morphkit itself

- Components: `packages/morphkit/src/react/live/components/*.tsx`; glass: `src/react/live/glass/`;
  engine: `src/react/live/engine.ts`; tokens: `src/react/live/theme.ts`; core math: `src/core/`.
- Relative imports use `.js` extensions (NodeNext); React leaf modules start with `'use client'`.
- Add the demo to `apps/showreel/src/playground/` (gallery is the visual spec).
- Check: `npm run typecheck`, `npm run build`, `npm run lib:build`, `npm run docs:api -w morphkit`,
  `npm run lib:pack`; install the tgz in a scratch Vite app and type-check with `skipLibCheck: false`.
- Update `docs/*.md` for any new prop/behavior; bump the version for consumers.
