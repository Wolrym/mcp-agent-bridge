---
name: ui-morph-motion
description: Use when making Dribbble-grade UI motion - looping product/showreel videos where one shape morphs through UI states on the beat (React + seek(t) rendering with Playwright/ffmpeg, beat-synced UI sounds), or when adding the same spring motion (morphs, liquid indicators, rubber-band sliders, content swaps) to real React apps. Built on the morphkit library.
---

# UI Morph Motion (morphkit)

You are a senior motion designer who also writes the renderer. The bar is
Dribbble's front page: one idea, executed with restraint, every frame on
purpose. A reference implementation lives at
`C:\Users\Dima\VSCodeProjects\_sandbox\test-motion-1` (showreel app +
`packages/morphkit` + render/audio scripts). Start new work by copying that
repo (or `packages/morphkit` + `scripts/` into a bigger app) — do not rewrite
the engine.

## The one rule: everything is a pure function of time

`seek(t)` must be able to draw any frame, in any order, many times, identically.

- Motion comes from **closed-form springs** (`springStep(t, spring)`), never
  integrators, `requestAnimationFrame` state, CSS transitions/animations,
  `setTimeout`, `useState` or `Math.random()` (use `hash(n)`).
- A value is a **track**: first target + every later change riding its own
  spring from the moment it was set (`track(keys, { period })`). Retargeting
  mid-flight keeps velocity automatically. Targets may be functions of `t`.
- **Loops**: pass `period: T` to every track/presence/cursor. Changes from the
  previous cycle finish after the wrap, so the last frame flows into the first.
  Audio is placed circularly too (sounds near t=0 wrap from the end).
- Composition data (`script.ts`) has no DOM/React imports — the same file
  feeds the renderer, the preview and the audio cue export.

## Workflow (do it in this order)

1. **Beat sheet first.** Fix BPM × bars (e.g. 120 × 7 = 28 beats = 14 s). Write
   a table: beat → event. Something happens on *every* beat; a state change,
   click, type, hover or data move. No dead time, no beat with two big moves.
2. **Layouts as data** (`L`): w, h, radius, color per state. One shape morphs
   between them (`MorphBox`); content inside swaps with `presence()` + `<Swap>`.
3. **Camera**: one target scale per scene, tracked in **log space**
   (`exp(track(log(scale)))`, `springs.camera`) so the active state fills
   ~55–70% of the frame. Divide shadows/strokes by camera scale when they
   must look screen-constant.
4. **Cursor** (`cursorPath`): S-curve springs (`order: 2`), arrives ~0.15–0.25 s
   before the beat, press peaks *on* the beat (`pressTrack`). Drags use
   `holds`; values follow the cursor while held, then `releaseSpring` keeps
   the release velocity. Past a limit use `rubberband()` (stretch, not stop).
5. **Render one frame per beat before anything else**:
   `npm run render:beats` → `out/beats/contact-sheet.png` (also `--at 0.9`
   for late-beat phase). Review every state at full size: crisp text,
   alignment, camera fill, nothing clipped. Fix, repeat. Only then render video.
6. **Audio**: `npm run audio` — song (or synthesized loop) → numpy beat
   analysis → `beatgrid.json` → cue export → UI sounds placed by **measured
   peak** on the cue time → `public/audio/mix.wav`. Listen to
   `out/audio/beat-check.wav`.
7. **Video**: `npm run render` → 60 fps, 4 subframes averaged by ffmpeg `tmix`
   (180° shutter), muxed with the mix; `-x3.mp4` plays the loop three times —
   watch the seam. `--subframes 8` for the final if fast morphs show steps.

## Taste rules (non-negotiable)

- Springs only, damping ≥ 0.75 (presets in `springs`): `morph` 0.32/0.84 for
  shapes, `exit` 0.1/1 (content leaves fast), `enter` 0.22/0.92 after a
  0.05–0.09 s delay (old content gone before new appears), `camera`/`cursor`
  critically damped order-2. **No bouncy easing**, no back/elastic curves.
- **Liquid edges** for indicators/pills (`liquid()` / `useLiquid`): the
  edge in the direction of travel leads, the other trails.
- Content swaps: opacity + ≤6 px blur + 0.94→1 scale (`swapStyle`). Blur only
  while swapping (`filter` is removed at rest → crisp text).
- Palette: light warm-gray canvas (`#E8E5E0`), black shape (`#0B0B0B`), white
  content, one gray for secondary text. Black & white unless asked.
  Font: Geist (variable, `@fontsource-variable/geist`), tabular numbers for
  changing digits.
- One icon set (Lucide paths) with **one stroke width** (2) everywhere.
- **Banned**: particles, glows, gradients on UI chrome, drop shadows that
  change with zoom, mismatched icon strokes, dead time, overshoot > ~3%,
  text that is too small to read at 1080 px, more than one hero motion at once.
- Last frame = first frame. Verify with the `-x3` file, not by reasoning.

## Renderer gotchas (already solved in the template — keep them)

- `seek` must update the DOM synchronously: `flushSync(() => setT(t))`.
- `window.__morph.ready` only after `document.fonts.ready` (+ one rAF), or
  first frames render in a fallback font.
- **No `will-change: transform`** on scaled layers: Chromium rasterizes at
  the pre-scale size → blurry text at camera zoom.
- Screenshots: `animations: 'disabled'`, `caret: 'hide'`, viewport = size,
  `deviceScaleFactor: 1`. Render in N parallel pages, write frames to
  ffmpeg in order (reorder buffer).
- Motion blur chain (verified): input at `fps×S`, then
  `tmix=frames=S:weights='1 1 1 1',select='not(mod(n+1\,S))',setpts=N/(fps*TB)`.
  Subframe times are centered on the frame and wrapped `mod duration`.
- Looped preview file: re-mux from the *silent video + WAV* with
  `-stream_loop` on both inputs (copying AAC loops leaves priming gaps).
- Windows: Python stdout to a pipe is cp125x → `sys.stdout.reconfigure(encoding="utf-8")`;
  call node tools by path (`node node_modules/tsx/dist/cli.mjs …`), not `npx`, from Python.

## Audio rules

- Beat analysis (numpy only): log-spectral-flux onsets; tempo by
  autocorrelation with a soft 120 BPM prior, scoring each candidate with its
  half and double lag (kills dotted-rhythm 2/3 errors); comb search period ×
  phase; snap to integer BPM within 0.15; phase refined on the >1.5 kHz
  transient envelope (earliest strong rise, median over beats); downbeat =
  chroma change before/after the beat + low end + backbeat (snare 1 and 3
  beats later). Half/double-time remains ambiguous → `--bpm`.
- Cut exactly `bars × beatsPerBar` beats from a downbeat; crossfade the tail
  into the audio *preceding* that downbeat (equal-gain) → seamless.
- UI sounds: short, dry, soft attack ramp, no reverb tails, ≤ 1 s. Peak =
  first strong lobe of a 2 ms RMS envelope; place `cue_time − peak`.
  Whooshes swell *into* the beat. **No inter-channel delays** (mono phone
  speakers comb-filter them). Duck music ~3 dB under sounds.
- Music: Mixkit tracks are free for video; drop into `audio/song.mp3`,
  `npm run audio -- --at <sec>` to pick the section. Default: synthesize an
  original loop (`make_track.py`) — royalty-free by construction.

## Real apps (not videos)

Use the live layer of `morphkit/react`; the gallery (`npm run playground`)
shows every component and is the visual reference. **For the full API, setup
in other projects, theming and Liquid Glass, follow the `morphkit` skill** and
`packages/morphkit/docs/` — this section is the short version.

- **Install elsewhere**: `npm run lib:pack` in the template →
  `npm i <path>/out/morphkit-0.2.0.tgz` (+ `@fontsource-variable/geist`).
  Inside the monorepo apps compile `src/` via the `morphkit-src` condition.
- **Theme**: `configureMorphkit({ theme: { ink, canvas, … } })` once before
  the first render; `darkTheme` preset; hex/rgb colors only (they spring).
- **Engine**: `MotionValue` (closed-form spring, `set(target)` keeps
  velocity → interruptible; `release(velocity, target)` after drags), one
  global rAF ticker that runs only while something moves. `<Motion style>`
  binds values/functions to the DOM directly — **no React re-render per
  frame, no `useState` for motion, no CSS transitions**.
- **Hooks**: `useSpring(target, spring)`, `useLiquid(start, end)` /
  `liquidTo` (lead/trail edges → liquid knobs and indicators),
  `useSpringColor`, `usePresence(show)` + `swapLive(p)`, `usePress`,
  `useHover`, `useSize`, `useDismiss`, `useClock`, `useLiveState`.
- **Primitives**: `SwapContent` (keyed blur swap, stacked in one grid cell),
  `Reveal`, `Collapse`, `MorphSurface` (springs w/h/radius/color to its
  content).
- **Components** (50+): Button, IconButton, Spinner, MorphButton,
  PlayPauseButton · TextInput, SearchField, Textarea, OTPInput, NumberField,
  TagInput · Toggle, Checkbox, RadioGroup, SegmentedControl, Slider /
  VolumeSlider, Chips, Rating, Select · Tabs, Pagination, Stepper, Menu,
  Toolbar, CommandPalette · ProgressBar, ProgressRing, Skeleton(Swap),
  ToastStack + useToasts, Badge, IconBadge, NumberTicker · Tooltip,
  MorphDialog, Accordion · MusicPlayer, DynamicIsland, LineChart,
  AvatarGroup · **Liquid Glass**: LiquidGlass, GlassToggle, GlassSlider,
  GlassButton, GlassSegmented. All controlled (`value` + `onChange`),
  keyboard + ARIA.

Rules for new live components:
- Measure, don't guess: indicators read real segment rects (`useSize`).
- Each state change = new spring target; never restart from zero.
- Liquid = two edges on different springs; stretch is capped (rubber band
  max ~26 px, knob stretch ≤ 14 %). Swaps = blur 4–6 px + scale 0.92–0.96.
- Overlays that clip labels (`clip-path` copies) need
  `pointer-events: none`, or they steal clicks.
- Effects must be StrictMode-safe (subscribe/unsubscribe symmetrically);
  never put `children` in effect deps that call `setState`.
- Test in dev (StrictMode) with Playwright: click → assert `aria-selected`
  and indicator rect, sample a knob per frame (no jumps), repeat async
  actions 3×, check console for errors.
- `prefers-reduced-motion` is automatic (short critically damped springs);
  `setTimeScale(0.25)` is the slow-mo switch for reviewing transitions.
- Deterministic frame tests: Playwright `page.clock.install()` →
  `pauseAt` → click → `clock.runFor(ms)` → screenshot (no timing flakiness).
- Glass: never put `filter`/`opacity<1`/`mask`/`backdrop-filter` on glass
  ancestors (backdrop root → empty glass); don't scale glass > ~1.25×.

## Delivery checklist

- [ ] Beat table: one event per beat, labels in `BEAT_LABELS`
- [ ] Contact sheet reviewed at two phases (0.42 and 0.9 beat)
- [ ] `npm run typecheck` and `npm run build` pass
- [ ] Live components: playground clicked through in dev (StrictMode), no console errors
- [ ] `beat-check.wav` on the grid; every cue audible, none late
- [ ] `showreel.mp4` 1440², 60 fps, 14.000 s, audio 14.000 s; `-x3` seam invisible
- [ ] No banned items (particles, glows, chrome gradients, bouncy easing, mixed strokes)
