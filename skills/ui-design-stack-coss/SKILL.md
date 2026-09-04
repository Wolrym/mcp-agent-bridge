---
name: ui-design-stack-coss
description: Use when building or restyling the user's GUI applications with the coss ui component system (formerly Origin UI, built on Base UI) - desktop apps with PyTauri and mobile apps with React Native. Defines the UI stack and the design rules every screen should follow.
---

# UI Design Stack - coss ui

You are a strong modern product designer as well as an engineer. You have
taste: you know what current, well-crafted software looks like, and you care
about spacing, hierarchy, and restraint. Build interfaces that would not look
out of place next to Linear, Vercel, or Cal.com.

coss ui is the component system for this project. Keep it as the single
source of components - mixing several component libraries in one project
produces inconsistent styling.

## What coss ui is

**Origin UI was acquired by Cal.com in October 2025 and became coss ui**, at
https://coss.com/ui. This matters practically:

- coss ui is the actively developed library. It is built on **Base UI**
  primitives (not Radix) and styled with **Tailwind CSS v4**. It is the
  official design system of Cal.com.
- The original Origin UI collection still exists at https://coss.com/origin
  as a **legacy snapshot** - Radix-based, shadcn-style, kept available but
  with limited support and no active development.
- Use coss ui for new work. Only fall back to the Origin snapshot if the user
  explicitly wants a component that only exists there.
- Repository: https://github.com/cosscom/coss

The library is layered into **primitives** (button, card, dialog, tabs...),
**particles** (larger composed blocks, ~490 of them), and **atoms**.

## The stack

**Desktop (default: PyTauri)**

- PyTauri shell - Rust + an embedded Python interpreter in a single process
- Python for all application logic
- React + TypeScript for the frontend
- Tailwind CSS v4 for styling
- coss ui for components (Base UI underneath)

**Mobile (default: React Native)**

- Expo, React Native + TypeScript
- NativeWind for styling, Reanimated for animation
- Components: React Native Reusables. coss ui is web-only - Base UI depends
  on the DOM - so the mobile side keeps its own component source and only
  shares design tokens with the desktop project.

**Web** uses the desktop stack minus PyTauri: Vite or Next.js + React +
Tailwind v4 + coss ui.

Avoid Tkinter, CustomTkinter, PyQt/PySide, and Electron.

## Installing coss ui

coss ui has **no CLI of its own - it ships as a shadcn registry**, so the
shadcn CLI is the installer. Don't invent a `coss` command.

New project, full setup in one command:

```bash
pnpm dlx shadcn@latest init @coss/style
```

That installs the UI components, the neutral colour system, sidebar
variables, base styles, and the default fonts (Inter for `--font-sans` and
`--font-heading`, Geist Mono for `--font-mono`), wiring them into
`layout.tsx`.

Existing project:

```bash
pnpm dlx shadcn@latest add @coss/ui              # all UI primitives
pnpm dlx shadcn@latest add @coss/style           # full theme: colours, sidebar, fonts
pnpm dlx shadcn@latest add @coss/ui @coss/colors-neutral   # components + colour tokens only
```

Individual component pages on the docs site each show their own `add`
command - prefer copying that command over guessing an item name.

Manual copying is supported (copy the Code tab into `components/ui/`, then
install the dependencies the page lists), but the CLI is preferred because it
also brings in the extra design tokens automatically.

Docs: https://coss.com/ui/docs, https://coss.com/ui/docs/get-started

### Do not guess the API

coss ui is new and thinly represented in model training data, and its
primitives follow **Base UI**, not Radix - prop names and composition differ.
Read the component's documentation page before writing code against it.
The docs are built for this: every page has a *Copy Markdown* button, there
is an `llms.txt` map of the documentation, and the primitives include Radix
to Base UI migration notes.

Components that wrap a Base UI primitive re-export it, so use the styled
component when the defaults fit and the primitive when a different
composition is needed:

```tsx
import { Slider, SliderValue, SliderPrimitive } from "@coss/ui/components/slider"
```

When only Base UI utilities are needed, import them through coss rather than
adding `@base-ui/react` as a direct dependency:
`@coss/ui/base-ui/use-render`, `.../merge-props`, `.../csp-provider`,
`.../direction-provider`.

## Design tokens

coss ui uses **the same CSS variables as shadcn/ui**, plus a few extra for
finer control:

- `--destructive-foreground`
- `--info` / `--info-foreground`
- `--success` / `--success-foreground`
- `--warning` / `--warning-foreground`

The CLI adds these automatically; if components are copied manually, the
tokens have to be added to the global stylesheet by hand or destructive,
info, success, and warning states will render wrong.

Because the variables match shadcn, externally generated themes (tweakcn and
similar) still apply. Treat an exported theme as the source of truth and
don't quietly rewrite it.

Typography runs through `--font-sans`, `--font-mono`, and `--font-heading`.
Next.js starters default to names like `--font-geist-sans`, which coss does
not recognise - if fonts look wrong after setup, check the variable names
first.

## PyTauri

PyTauri is young and its API is not well represented in model training data.
Read the documentation before writing PyTauri code rather than recalling an
API shape from memory:

- https://pytauri.github.io/pytauri/
- https://github.com/pytauri/pytauri
- https://github.com/pytauri/example-pytauri-app-react
- https://v2.tauri.app/

Python is exposed to the frontend as commands:

```python
from pydantic import BaseModel
from pytauri import Commands

commands = Commands()

class Req(BaseModel):
    path: str

class Res(BaseModel):
    items: list[str]

@commands.command()
async def scan_dir(body: Req) -> Res:
    import os
    return Res(items=os.listdir(body.path))
```

```tsx
import { pyInvoke } from "tauri-plugin-pytauri-api"
const res = await pyInvoke<Res>("scan_dir", { path: "C:/" })
```

PyTauri already solves Python-to-frontend communication in-process, so build
the normal application on commands and events rather than standing up a local
HTTP server - it is simpler and avoids the startup cost. Where a local
endpoint genuinely is the right tool, such as streaming an OpenCV video feed
into an `<img>` tag, use one; just keep it the exception rather than the
default architecture.

## Design rules

- **Minimal.** Generous spacing, soft radii, thin borders, muted surfaces, a
  single accent colour. No rainbow gradients, no icon clutter, no boxes
  around everything.
- **Both themes.** Light and dark are both implemented and both look
  intentional. Dark mode is not an inverted afterthought.
- **Tokens only.** Style through semantic classes - `bg-background`,
  `text-foreground`, `text-muted-foreground`, `border-border`, `bg-primary`,
  `bg-card`, plus the coss additions above. Don't hard-code hex colours; if a
  colour is missing, add a token.
- **Consistency over novelty.** Reuse the spacing, radius, and typography
  scales across screens. Two buttons doing the same job look identical.
- **Hierarchy.** One clear primary action per view; everything else is
  secondary, ghost, or plain text.
- **Restyling components is fine when the user asks for it**, and reasonable
  on your own initiative when a component doesn't quite fit. Keep the result
  inside the same visual system.
- Prefer a **particle** over hand-assembling a block from primitives when one
  already covers the pattern.

## Animation

Interaction states - hover, press, focus, enter and exit - are part of a
finished interface. Implement them by default: Tailwind transitions and
`animate-in` / `animate-out` on desktop, Reanimated on mobile. coss also
ships easing classes; use them so timing stays consistent with the library.

When the user asks for more motion, go through the interface and animate what
is missing rather than only the element mentioned: list and card entrances,
modal and popover transitions, layout shifts, loading and empty states,
number and progress changes. Keep one shared vocabulary - same easing,
similar durations (roughly 150-250 ms for state changes, 250-400 ms for
layout), consistent direction of movement.

Where to get motion:

- Desktop / web: Tailwind utilities and coss easing classes for state
  changes; **Motion** (`npm i motion`) for layout transitions, gestures, and
  springs.
- Mobile: **Reanimated**, plus `react-native-gesture-handler` for
  gesture-driven motion. Don't drive animation with JS timers.

Taste still applies - motion should support the interaction, not perform.

## Before calling a UI task done

- Components came from the registry via the shadcn CLI, not from memory.
- Component APIs were checked against the docs, not assumed from Radix.
- The extra coss tokens are present in the stylesheet.
- Only semantic colour classes are used.
- Light and dark themes both checked.
- Interaction states exist on every interactive element.
- PyTauri logic goes through `@commands.command()` and events, without an
  unnecessary local server.
