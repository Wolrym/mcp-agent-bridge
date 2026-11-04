#!/usr/bin/env node
/**
 * figure: command-line tool for the linear-lib figure engine.
 *
 *   node skills/linear-figure/scripts/figure.mjs check my-figure.json
 *   npm run figure -- svg fig-cubes --state hover -o out/cubes.svg
 *
 * Plain Node ESM with no dependencies. The engine is loaded straight from
 * the project's TypeScript sources (src/lib/figure/index.ts), which needs
 * Node >= 22.18 (native type stripping).
 */
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs"
import { basename, dirname, extname, join, resolve } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import process from "node:process"

const ENTRY = "src/lib/figure/index.ts"
const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))

const HELP = `figure: validate, render and generate code for linear-lib figures

Usage: figure <command> [args] [options]

<spec> is a .json file, "-" for stdin, or a preset id (see "figure presets").

Commands
  check <spec>              validate + compile; exit 1 on errors
  format <spec> [--write]   pretty-print the spec (--write rewrites the file)
  svg <spec>                render the settled frame of a state to SVG
      --state <name>          state to render (default: the inView/initial state)
      --theme dark|light|css  colours (default dark; css = var(--figure-*))
      --width <px>            default 480; --height defaults to width / aspect
      --background            paint the background rectangle
  tsx <spec> [--name X]     React component that renders the spec
  import <model>            .obj .stl .gltf .glb .svg .json -> spec JSON
      --max-faces <n>         face budget (default 2400)
      --mode auto|edges|slices  drawing style (auto: smooth -> slices)
      --up auto|y|z           source up axis (auto: z for STL)
      --size <n>              largest side in world units (default 1.6)
      --max-parts <n>         merge meshes beyond this count (default 8)
      --depth <n>             SVG extrusion depth (default 0.18)
      --orient upright|flat   SVG orientation (default upright)
      --title <text>          spec title (default: file name)
  presets                   list built-in presets
  new [preset]              print a starter spec (or a copy of a preset)
  schema [--md|--json]      spec reference as Markdown (default) or JSON Schema
  help                      this text

Options
  -o, --out <file>          write to a file (folders are created) instead of stdout
  -q, --quiet               no notes on stderr (errors are still printed)
  --project <dir>           linear-lib root (else $LINEAR_LIB_ROOT, else found
                            by walking up from the cwd and from this script)

Examples
  figure new > figure.json && figure check figure.json
  figure import model.stl --max-faces 1800 -o figures/model.json
  figure svg figures/model.json --theme light -o public/model.svg
  figure tsx figures/model.json --name ModelFigure -o src/figures/model.tsx
`

/** A starter spec that validates and animates: a plinth with a block on top. */
const STARTER = {
  version: 1,
  title: "New figure",
  camera: { view: "isometric", padding: 0.14 },
  parts: [
    { id: "base", shape: { type: "box", size: [1.4, 0.16, 1.4], radius: 0.06 } },
    { id: "block", shape: { type: "box", size: [0.7, 0.7, 0.7], radius: 0.08 }, position: [0, 0.43, 0] },
  ],
  states: {
    intro: { parts: { "*": { draw: 0, offset: [0, 0.18, 0] } } },
    rest: { transition: { spring: "smooth", stagger: 0.08, order: "y" } },
    hover: { parts: { block: { offset: [0, 0.14, 0], accent: 0.6 } }, camera: { yaw: 10 } },
  },
  initial: "intro",
  interaction: { inView: "rest", hover: "hover" },
}

const BOOL = new Set(["quiet", "help", "write", "md", "json", "background"])
const SHORT = { o: "out", q: "quiet", h: "help" }
const KNOWN = new Set([
  ...BOOL, "out", "project", "state", "theme", "width", "height", "name",
  "max-faces", "mode", "up", "size", "max-parts", "depth", "orient", "title",
])

class CliError extends Error {}
const fail = (msg) => {
  throw new CliError(msg)
}

function parseArgs(argv) {
  const args = []
  const opts = {}
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === "--") {
      args.push(...argv.slice(i + 1))
      break
    }
    let key
    let value
    if (a.startsWith("--")) {
      const eq = a.indexOf("=")
      key = eq < 0 ? a.slice(2) : a.slice(2, eq)
      if (eq >= 0) value = a.slice(eq + 1)
    } else if (/^-[a-z]$/i.test(a)) {
      key = SHORT[a[1]]
      if (!key) fail(`unknown option ${a}`)
    } else {
      args.push(a)
      continue
    }
    if (!KNOWN.has(key)) fail(`unknown option --${key}; see "figure help"`)
    if (BOOL.has(key)) {
      opts[key] = value === undefined ? true : !/^(0|false|no)$/i.test(value)
      continue
    }
    if (value === undefined) {
      if (i + 1 >= argv.length) fail(`--${key} needs a value`)
      value = argv[++i]
    }
    opts[key] = value
  }
  return { args, opts }
}

function number(opts, key) {
  if (opts[key] === undefined) return undefined
  const n = Number(opts[key])
  if (!Number.isFinite(n)) fail(`--${key} expects a number, got "${opts[key]}"`)
  return n
}

function oneOf(opts, key, values) {
  const v = opts[key]
  if (v !== undefined && !values.includes(v)) fail(`--${key} must be one of ${values.join(", ")}, got "${v}"`)
  return v
}

function checkNode(quiet) {
  const [maj, min] = process.versions.node.split(".").map(Number)
  const ok = maj > 23 || (maj === 23 && min >= 6) || (maj === 22 && min >= 18)
  if (!ok && !quiet)
    process.stderr.write(
      `warning: Node ${process.versions.node} may not load .ts files; use Node >= 22.18 or add --experimental-strip-types\n`,
    )
}

function findRoot(start) {
  let dir = resolve(start)
  for (;;) {
    if (existsSync(join(dir, ENTRY))) return dir
    const up = dirname(dir)
    if (up === dir) return null
    dir = up
  }
}

function projectRoot(opts) {
  const explicit = opts.project ?? process.env.LINEAR_LIB_ROOT
  if (explicit) {
    const dir = resolve(explicit)
    if (!existsSync(join(dir, ENTRY))) fail(`${dir} is not a linear-lib project (no ${ENTRY})`)
    return dir
  }
  const dir = findRoot(process.cwd()) ?? findRoot(SCRIPT_DIR)
  if (!dir) fail(`cannot find ${ENTRY}; pass --project <dir> or set LINEAR_LIB_ROOT`)
  return dir
}

async function loadEngine(opts) {
  const root = projectRoot(opts)
  return import(pathToFileURL(join(root, ENTRY)).href)
}

async function readStdin() {
  const chunks = []
  for await (const c of process.stdin) chunks.push(c)
  return Buffer.concat(chunks).toString("utf8")
}

const isFile = (p) => existsSync(p) && statSync(p).isFile()

/** Resolve <spec>: a file, "-" (stdin) or a preset id. Returns raw (unvalidated) JSON. */
async function loadSpec(F, arg) {
  if (!arg) fail(`missing <spec>: a .json file, "-" for stdin, or a preset id`)
  let text
  let file
  if (arg === "-") text = await readStdin()
  else if (isFile(arg)) {
    file = arg
    text = readFileSync(arg, "utf8")
  } else {
    const preset = F.getPreset(arg)
    if (preset) return { spec: structuredClone(preset.spec), label: `preset ${arg}` }
    const ids = F.PRESETS.map((p) => p.id)
    const near = ids.find((id) => id.includes(arg) || arg.includes(id))
    fail(`no file or preset "${arg}"${near ? ` (did you mean "${near}"?)` : `; presets: ${ids.join(", ")}`}`)
  }
  let spec
  try {
    spec = JSON.parse(text.replace(/^\uFEFF/, ""))
  } catch (e) {
    fail(`${file ?? "stdin"}: invalid JSON: ${e.message}`)
  }
  // accept { spec: {...} } wrappers (preset objects, Studio drafts)
  if (spec && typeof spec === "object" && "spec" in spec && !("parts" in spec)) spec = spec.spec
  return { spec, file, label: file ?? "stdin" }
}

function makeIO(opts) {
  const note = (msg) => {
    if (!opts.quiet) process.stderr.write(`${msg}\n`)
  }
  const emit = (text) => {
    const out = text.endsWith("\n") ? text : `${text}\n`
    if (opts.out) {
      const file = resolve(opts.out)
      mkdirSync(dirname(file), { recursive: true })
      writeFileSync(file, out)
      note(`wrote ${opts.out}`)
    } else process.stdout.write(out)
  }
  return { note, emit }
}

/** Validate; print issues; return the spec or fail. */
function valid(F, loaded, io) {
  const v = F.validateFigure(loaded.spec)
  if (!v.ok) {
    process.stderr.write(`${F.formatIssues(v)}\n`)
    fail(`${loaded.label}: ${v.errors.length} error${v.errors.length === 1 ? "" : "s"}`)
  }
  if (v.warnings.length) io.note(F.formatIssues({ errors: [], warnings: v.warnings }))
  return v.spec
}

function compile(F, spec, io) {
  try {
    const fig = F.compileFigure(spec)
    for (const w of fig.warnings) io.note(`warn  ${w}`)
    return fig
  } catch (e) {
    fail(e instanceof F.FigureError ? e.message : `compile failed: ${e.message}`)
  }
}

const stateNames = (fig) => [...fig.states.keys()].filter(Boolean)

const commands = {
  async check(F, args, opts, io) {
    const loaded = await loadSpec(F, args[0])
    const spec = valid(F, loaded, io)
    const fig = compile(F, spec, io)
    const n = (x, word) => `${x} ${word}${x === 1 ? "" : "s"}`
    io.emit(
      `✓ "${spec.title ?? loaded.label}" ok · ${n(spec.parts.length, "part")} · ${n(fig.stats.instances, "instance")} · ${n(fig.stats.faces, "face")} · ${n(stateNames(fig).length, "state")}`,
    )
  },

  async format(F, args, opts, io) {
    const loaded = await loadSpec(F, args[0])
    const v = F.validateFigure(loaded.spec)
    if (!v.ok || v.warnings.length) io.note(F.formatIssues(v))
    const text = `${F.formatSpec(loaded.spec)}\n`
    if (opts.write) {
      if (!loaded.file) fail("--write needs a .json file argument")
      writeFileSync(loaded.file, text)
      io.note(`formatted ${loaded.file}`)
    } else io.emit(text)
  },

  async svg(F, args, opts, io) {
    const loaded = await loadSpec(F, args[0])
    const spec = valid(F, loaded, io)
    const fig = compile(F, spec, io)
    const state = opts.state
    if (state !== undefined && !fig.states.has(state)) {
      const names = stateNames(fig)
      fail(`unknown state "${state}"; ${names.length ? `states: ${names.join(", ")}` : "the spec has no states"}`)
    }
    const theme = oneOf(opts, "theme", ["dark", "light", "css"]) ?? "dark"
    io.emit(
      F.toSVGFile(spec, {
        width: number(opts, "width") ?? 480,
        height: number(opts, "height"),
        state,
        theme,
        background: !!opts.background,
      }),
    )
  },

  async tsx(F, args, opts, io) {
    const loaded = await loadSpec(F, args[0])
    const spec = valid(F, loaded, io)
    compile(F, spec, io)
    const name = opts.name
    if (name !== undefined && !/^[A-Z][A-Za-z0-9]*$/.test(name)) fail(`--name must be PascalCase, got "${name}"`)
    io.emit(F.toTSX(spec, { name }))
  },

  async import(F, args, opts, io) {
    const model = args[0]
    if (!model) fail("missing <model>: an .obj, .stl, .gltf, .glb, .svg or .json file")
    if (!isFile(model)) fail(`no such file: ${model}`)
    const ext = extname(model).toLowerCase()
    if (!F.IMPORT_EXTENSIONS.includes(ext)) fail(`unsupported file "${basename(model)}"; use ${F.IMPORT_EXTENSIONS.join(", ")}`)
    const data = new Uint8Array(readFileSync(model))
    const resources = {}
    if (ext === ".gltf") {
      // external buffers sit next to the .gltf
      let json
      try {
        json = JSON.parse(new TextDecoder().decode(data))
      } catch (e) {
        fail(`${model}: invalid JSON: ${e.message}`)
      }
      for (const b of json.buffers ?? []) {
        if (!b.uri || b.uri.startsWith("data:")) continue
        const key = decodeURIComponent(b.uri)
        const file = join(dirname(model), key)
        if (!isFile(file)) fail(`${model}: missing external buffer "${key}" (looked for ${file})`)
        resources[key] = new Uint8Array(readFileSync(file))
      }
    }
    const options = {
      maxFaces: number(opts, "max-faces"),
      maxParts: number(opts, "max-parts"),
      size: number(opts, "size"),
      depth: number(opts, "depth"),
      mode: oneOf(opts, "mode", ["auto", "edges", "slices"]),
      up: oneOf(opts, "up", ["auto", "y", "z"]),
      orient: oneOf(opts, "orient", ["upright", "flat"]),
      title: opts.title,
      resources,
    }
    for (const k of Object.keys(options)) if (options[k] === undefined) delete options[k]
    let result
    try {
      result = F.importFile(basename(model), data, options)
    } catch (e) {
      fail(`${basename(model)}: ${e.message}`)
    }
    const s = result.stats
    const faces = s.decimated ? `${s.faces} → ${s.outputFaces} faces (decimated)` : `${s.faces} faces`
    io.note(`imported ${s.format} · ${s.meshes} mesh${s.meshes === 1 ? "" : "es"} → ${s.parts} part${s.parts === 1 ? "" : "s"} · ${faces}${s.mode ? ` · mode ${s.mode}` : ""}`)
    for (const w of result.warnings) io.note(`note  ${w}`)
    io.emit(F.formatSpec(result.spec))
  },

  async presets(F, args, opts, io) {
    const w = Math.max(...F.PRESETS.map((p) => p.id.length))
    io.emit(F.PRESETS.map((p) => `${p.id.padEnd(w)}  ${p.label} · ${p.title}`).join("\n"))
  },

  async new(F, args, opts, io) {
    let spec = structuredClone(STARTER)
    if (args[0]) {
      const preset = F.getPreset(args[0])
      if (!preset) fail(`no preset "${args[0]}"; presets: ${F.PRESETS.map((p) => p.id).join(", ")}`)
      spec = structuredClone(preset.spec)
    }
    if (opts.title) spec.title = opts.title
    io.emit(F.formatSpec(spec))
  },

  async schema(F, args, opts, io) {
    io.emit(opts.json ? JSON.stringify(F.toJSONSchema(), null, 2) : F.toMarkdown())
  },
}

async function main(argv) {
  const { args, opts } = parseArgs(argv)
  const [cmd, ...rest] = args
  if (!cmd || cmd === "help" || opts.help) {
    process.stdout.write(HELP)
    return
  }
  const run = commands[cmd]
  if (!run) fail(`unknown command "${cmd}"; see "figure help"`)
  checkNode(opts.quiet)
  const F = await loadEngine(opts)
  await run(F, rest, opts, makeIO(opts))
}

main(process.argv.slice(2)).catch((e) => {
  process.stderr.write(`error: ${e instanceof CliError ? e.message : (e?.stack ?? e)}\n`)
  process.exitCode = 1
})
