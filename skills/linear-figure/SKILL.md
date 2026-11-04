---
name: linear-figure
description: Create, edit, validate and render linear-lib figures, the animated isometric line-art illustrations in the style of linear.app (FIG 0.1–0.3). A figure is a JSON FigureSpec (parts, states, springs, pointer fields) rendered by <Figure> or exported to SVG/TSX. Use when asked for a hero or card illustration, an animated diagram, a 3D model (OBJ/STL/glTF/SVG) turned into line art, or a change to a FigureSpec; includes a dependency-free CLI (scripts/figure.mjs).
---

# linear-figure

A figure is data: a `FigureSpec` JSON with solids (`parts`), named poses (`states`), spring
transitions between them, and what triggers them (`interaction`, `pointer`). The engine
(`src/lib/figure`, no dependencies) validates it, draws hidden-line edges on a canvas and exports SVG
or a React component. Because it is data, write it, check it with the CLI, render it, look, repeat.

Full field reference: `docs/figures-schema.md` in the linear-lib repo (generated from the schema;
or run `figure schema`). Human guide (Ukrainian): `docs/figures.md`, `docs/studio.md`.

## CLI

```bash
node --no-warnings skills/linear-figure/scripts/figure.mjs <command> [args] [-o file] [-q]
# inside the repo, the same: npm run -s figure -- <command> …   (-s, or npm adds its banner to stdout)
```

Needs Node ≥ 22.18 (native type stripping; it loads `src/lib/figure/index.ts` directly). It finds
the linear-lib root from the cwd or its own location; otherwise pass `--project <dir>` or set
`LINEAR_LIB_ROOT`. `<spec>` is a `.json` file, `-` for stdin, or a preset id.

| Command | Does |
| --- | --- |
| `new [preset]` | starter spec (plinth + block) or a copy of a preset |
| `check <spec>` | validate + compile; exit 1 with `error <path>: <message> (hint)` lines |
| `format <spec> [--write]` | canonical formatting (short arrays on one line) |
| `svg <spec> --state <s>` | settled frame of a state; `--theme dark\|light\|css`, `--width 480`, `--background` |
| `tsx <spec> --name XFigure` | React component wrapping `<Figure spec>` |
| `import <model>` | `.obj .stl .gltf .glb .svg .json` → spec |
| `presets` | list built-in presets |
| `schema [--md\|--json]` | reference as Markdown or JSON Schema |

Always write files with `-o` (folders are created) rather than shell redirection.

## Workflow

1. **Start** from the closest preset or the starter: `figure new fig-plates -o figures/hero.json`.
   Presets: `fig-layers` (layers peel off a block), `fig-cubes` (rounded cubes, hover lifts the nearest),
   `fig-plates` (staircase of plates, hover shifts the peak), `sliced-torus` (slices mode, idle spin),
   `vase` (lathe printed layer by layer), `logo` (extruded SVG, tilt + float), `stairs` (click rolls a
   ball), `dithered-sphere` (dotted slices go solid on hover), `exploded` (click explodes an assembly).
2. **Edit** the JSON. Keep part ids short and meaningful; tag groups you will address together.
3. **Check**: `figure check figures/hero.json` until it prints `✓ … ok`. Structural errors are
   reported first; reference errors (unknown part in a selector, unknown state) appear once the
   structure is valid, so re-run after each fix. Read warnings too.
4. **Look**: render every state you defined, e.g.
   `figure svg figures/hero.json --state hover --theme light --background -o .tmp/hero-hover.svg`.
   If you can view images, convert the SVG to PNG (headless browser, ImageMagick, sharp) and inspect
   it: silhouette readable, nothing clipped, parts not intersecting, the change between states obvious.
5. **Ship**: either `<Figure spec={spec} />` with the JSON imported, or
   `figure tsx figures/hero.json --name HeroFigure -o src/figures/hero-figure.tsx`.
   For static use (email, README, print): `figure svg … --theme light` (self-contained hex colours) or
   `<FigureStatic>`.

`skills/linear-figure/examples/stacked-plates.json` is a small spec that uses most features (repeat,
tags, intro/rest/hover, a ramp spread, an accent, a pointer field) and passes `check`.

## Authoring model

```json
{
  "version": 1,
  "title": "New figure",
  "camera": { "view": "isometric", "padding": 0.14 },
  "parts": [
    { "id": "base", "shape": { "type": "box", "size": [1.4, 0.16, 1.4], "radius": 0.06 } },
    { "id": "block", "shape": { "type": "box", "size": [0.7, 0.7, 0.7], "radius": 0.08 }, "position": [0, 0.43, 0] }
  ],
  "states": {
    "intro": { "parts": { "*": { "draw": 0, "offset": [0, 0.18, 0] } } },
    "rest": { "transition": { "spring": "smooth", "stagger": 0.08, "order": "y" } },
    "hover": { "parts": { "block": { "offset": [0, 0.14, 0], "accent": 0.6 } }, "camera": { "yaw": 10 } }
  },
  "initial": "intro",
  "interaction": { "inView": "rest", "hover": "hover" }
}
```

- **World**: Y up, units are arbitrary (figures are fitted to the canvas; ~1–2 units across works well).
  `position` is the **bottom centre** of a part: a block on a 0.16-high plinth sits at `y = 0.16`.
  `rotation` in degrees, applied X then Y then Z. `scale` is a number or `[x, y, z]`.
- **Shapes** (`shape.type`): `box` (`size`, `radius`, `round` axis), `cylinder`, `prism` (`sides`), `cone`
  (`top` radius), `sphere`, `torus` (`tube`), `stairs` (`steps`), `plane` (open, double-sided), `extrude`
  (SVG `path`, `depth`, `orient: flat|upright`), `lathe` (`profile` revolved around Y), `mesh`
  (`positions` + `indices`/`faces`), `group` (`children` drawn as one outline).
- **repeat** `{ count, step, rotate, scale }` makes copies addressed as `id[0]`, `id[1]`, …
- **States** are poses. A state with no changes is the base pose (`rest`). `extends` starts from another
  state. `camera` in a state is a delta (`yaw`, `pitch` added; `zoom` multiplied).
- **Channels** (what animates): `offset [x,y,z]`, `rotate [x,y,z]`, `scale`, `stretch [x,y,z]` (grow
  without distorting rounded corners), `opacity`, `draw` (0 = lines not drawn yet), `inner` (crease
  strength), `accent` (mix toward the accent tone + glow), `dither` (<1 = dotted), `explode`.
- **Selectors** (keys of `states.*.parts`): `"*"`, `"id"`, `"id[2]"`, `".tag"`, comma-separated.
  Specificity `*` < `.tag` < `id` < `id[n]`.
- **Spreads**: any channel value can be a ramp across the matched instances
  `{ "from": a, "to": b, "ease": "linear" | "in" | "out" | "inOut" }` or a cycled list `{ "values": [a, b, c] }`.
  This is how fans, staircases and cascades are made.
- **Transitions** (per state or top-level): `spring` = `snappy` 0.2 · `smooth` 0.34 · `morph` 0.42/0.14 ·
  `sheet` · `flick` · `gentle` 0.7 · `liquidLead` · `liquidTrail` or `{ "duration", "bounce" }`; `delay`,
  `stagger` (s between instances), `order`: `index` | `reverse` | `center` | `random` | `x` | `y` | `z`.
- **Triggers**: `initial` (first frame), `interaction: { inView, hover, press, click }` (`click` toggles,
  also by Enter). `pointer.tilt` (°, ≤ 45) tilts the camera toward the cursor. `pointer.fields`
  deform by cursor position: `{ parts, axis, shape: "bump" | "step", width, invert, add: { channels } }`
  (`bump` = peak under the cursor, `step` = everything past it). `idle: { spin, float, period }`.
- **Style**: `mode: "edges"` (hidden-line) or `"slices"` (stacked plates, `slices: { axis, count,
  thickness }`); tones `line`, `inner`, `faint`, `accent`, `ember`, `fill`, `none` or any CSS colour;
  `fill: "none"` = wireframe, `hidden: "dashed"` (needs `fill: "none"`), `crease` (28°), `guides`, `glow`,
  `width`, `dash`. `style` on a part overrides the figure style. `decals` print SVG line art on a face.

## Design rules (the Linear look)

- Few solids, generous negative space, one idea per figure. Isometric camera unless there is a reason.
- The intro draws lines (`draw: 0` → 1) with a small stagger in a meaningful `order` (`y` for stacks).
- Hover is a small, legible change (lift 0.1–0.3 units, a few degrees of yaw, one accent). Accent at
  most one or two parts; everything else stays neutral grey.
- Springs: `smooth` for settling, `morph` when shapes "arrive", `gentle` for slow reveals. No bounce on
  entrances.
- Keep it under ~3000 faces for smooth animation; prefer analytic shapes over meshes.

## Importing models

```bash
figure import model.stl --max-faces 1800 -o figures/model.json
figure import logo.svg --depth 0.2 --orient flat -o figures/logo.json
```

Options: `--max-faces` (2400), `--mode auto|edges|slices` (auto: smooth/organic → slices, CAD-like →
edges), `--up auto|y|z` (auto = z for STL), `--size` (1.6), `--max-parts` (8), `--depth`, `--orient`,
`--title`. Then add states and interaction by hand (or in Studio).

Limits: glTF geometry only (no materials, animations, Draco or meshopt compression). Non-convex meshes
are drawn face by face, which is slow on big models: lower `--max-faces` (1200–1800). Decimation makes
organic meshes lumpy in `edges` mode, which is why `auto` picks `slices` for them.

## Using it in React

```tsx
import { Figure } from "@/components/figure/figure"
import { FigureCard, FigureGrid } from "@/components/figure/figure-card"
import type { FigureSpec } from "@/lib/figure"
import json from "./figures/hero.json"

// JSON imports widen literals ([0, 1, 0] -> number[]), so a plain `as FigureSpec` fails to compile.
// The spec was validated by `figure check`; cast through unknown, or use `figure tsx` for a typed file.
const spec = json as unknown as FigureSpec

<Figure spec={spec} className="mx-auto w-full max-w-[420px]" />
<Figure preset="fig-cubes" state="hover" interactive={false} />
<FigureGrid>
  <FigureCard preset="fig-layers" />
  <FigureCard spec={spec} label="FIG 2.1" title="Hero" description="…" />
</FigureGrid>
```

The component generated by `figure tsx` type-checks as is. Props: `spec | preset`, `state` (force a state),
`interactive`, `playOnView`, `pointerTarget`, `label`, `handleRef` (`replay()`, `goto(state, instant?)`).
Keep `spec` referentially stable (module scope or `useMemo`). On a card background add
`[--figure-fill:var(--card)]`; recolour with the `--figure-*` CSS variables. Invalid specs never crash
the page: dev shows the error in place, production renders an empty box, both log `[figure] …`.

Install into another project: `npx shadcn@latest add <REGISTRY>/r/figure-card.json` (pulls `figure`,
`figure-engine`, `scramble-text`, `utils`); its tsconfig needs `"allowImportingTsExtensions": true`.
Studio (visual editor with undo, import and TSX/SVG export) runs at `#/studio` of the demo app.

## Changing the engine

`src/lib/figure/schema.ts` is the single source for validation, JSON Schema and the Markdown
reference; keep `types.ts` in sync. After a schema change run
`figure schema -o docs/figures-schema.md`, then `npm run test:figure` and `npm run build`. Engine
files import each other with `.ts` extensions and must stay free of React and DOM (except the
explicit browser helpers in `draw.ts`).
