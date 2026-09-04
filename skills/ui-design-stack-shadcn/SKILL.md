---
name: ui-design-stack-shadcn
description: Use when building or restyling the user's GUI applications - desktop apps with PyTauri and mobile apps with React Native. Defines the UI stack (shadcn/ui, Tailwind, NativeWind, React Native Reusables) and the design rules every screen should follow.
---

# UI Design Stack

You are a strong modern product designer as well as an engineer. You have
taste: you know what current, well-crafted software looks like, and you care
about spacing, hierarchy, and restraint. Build interfaces that would not look
out of place next to Linear, Vercel, or Raycast.

## The stack

**Desktop (default: PyTauri)**

- PyTauri shell - Rust + an embedded Python interpreter in a single process
- Python for all application logic
- React + TypeScript for the frontend
- Tailwind CSS for styling
- shadcn/ui for components

**Mobile (default: React Native)**

- Expo for tooling and builds
- React Native + TypeScript
- NativeWind for styling
- React Native Reusables for components
- Reanimated for animation

**Web** uses the desktop stack minus PyTauri: Vite + React + TypeScript +
Tailwind + shadcn/ui.

Avoid Tkinter, CustomTkinter, PyQt/PySide, and Electron. Don't substitute a
different component library unless asked.

## PyTauri

PyTauri is young and its API is not well represented in model training data.
Read the documentation before writing PyTauri code rather than recalling an
API shape from memory:

- https://pytauri.github.io/pytauri/
- https://github.com/pytauri/pytauri
- https://github.com/pytauri/example-pytauri-app-react
- https://v2.tauri.app/ (underlying shell, bundling, updater)

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

## Working with shadcn/ui

shadcn/ui is a code distribution system, not a dependency. The CLI copies
source files into the project and they become project code from then on.

- Initialise once: `npx shadcn@latest init`
- Add components on demand: `npx shadcn@latest add button card dialog`
- Inspect before installing: `npx shadcn@latest add button --view`
- Compare a locally modified component with upstream: `--diff`
- Search across configured registries: `npx shadcn@latest search <query>`

Guidelines:

- Obtain components through the CLI. Don't reconstruct one from memory or
  paste it from a GitHub snapshot - the registry is the source of truth and
  remembered code is usually outdated.
- Install components when they are needed rather than speculatively.
- Other registries can be mixed into the same project when a specific effect
  is wanted, e.g. `npx shadcn@latest add @magicui/shimmer-button`. Keep
  shadcn/ui as the base and treat other registries as accents.
- If a shadcn MCP server is available in the session, prefer it over guessing
  component APIs.

References: https://ui.shadcn.com/docs and https://ui.shadcn.com/docs/cli

## Design rules

- **Minimal.** Generous spacing, soft radii, thin borders, muted surfaces, a
  single accent colour. No rainbow gradients, no icon clutter, no boxes
  around everything.
- **Both themes.** Light and dark are both implemented and both look
  intentional. Dark mode is not an inverted afterthought.
- **Tokens only.** Style through semantic classes - `bg-background`,
  `text-foreground`, `text-muted-foreground`, `border-border`, `bg-primary`,
  `bg-card`. Don't hard-code hex colours in a component; if a colour is
  missing, add a token.
- **Consistency over novelty.** Reuse the spacing, radius, and typography
  scales across screens. Two buttons doing the same job look identical.
- **Hierarchy.** One clear primary action per view; everything else is
  secondary, ghost, or plain text.
- **Restyling components is fine when the user asks for it**, and reasonable
  on your own initiative when a component doesn't quite fit. Keep the result
  inside the same visual system so one screen doesn't drift into a different
  aesthetic.

If the user has generated a theme externally (for example with tweakcn),
treat the exported CSS variables as the source of truth and don't quietly
rewrite them.

## Animation

Interaction states - hover, press, focus, enter and exit - are part of a
finished interface. Implement them by default: Tailwind transitions and the
`animate-in` / `animate-out` utilities on desktop, Reanimated on mobile.

When the user asks for more motion, go through the interface and animate what
is missing rather than only the element mentioned: list and card entrances,
modal and popover transitions, layout shifts, loading and empty states,
number and progress changes. Keep one shared vocabulary - the same easing,
similar durations (roughly 150-250 ms for state changes, 250-400 ms for
layout), consistent direction of movement - so the app feels like one piece
of software.

Where to get motion:

- Desktop / web: Tailwind utilities for simple state changes; **Motion**
  (`npm i motion`, formerly Framer Motion) for layout transitions, gestures,
  and springs; animated components from registries such as Magic UI when a
  specific effect is wanted.
- Mobile: **Reanimated** for everything, plus `react-native-gesture-handler`
  for gesture-driven motion. Don't drive animation with JS timers.

Taste still applies - motion should support the interaction, not perform.

## Mobile notes

Same design language, but layouts are redrawn for touch rather than scaled
down: large hit targets, bottom navigation, safe-area insets, single-column
flows. Components come from React Native Reusables via its CLI and are styled
with NativeWind, so token names carry over from the desktop project - keep
them in sync deliberately.

References: https://docs.expo.dev/, https://reactnativereusables.com/docs,
https://www.nativewind.dev/

## Before calling a UI task done

- Components came from the CLI, not from memory.
- Only semantic colour classes are used.
- Light and dark themes both checked.
- Interaction states exist on every interactive element.
- PyTauri logic goes through `@commands.command()` and events, without an
  unnecessary local server.
