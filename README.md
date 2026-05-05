# ccsight

Inline image rendering for terminals **wrapped by agentic CLIs** like Claude
Code, Cursor, and Aider — which capture and sanitize their child processes'
stdout, eating the ESC bytes that every inline-image protocol depends on.

`ccsight` doesn't fight the wrapper. It walks around it: finds the wrapper's
own controlling pty via `/proc`, encodes the image with the right protocol
for your terminal (sixel, iTerm2 OSC 1337, or Kitty graphics), and writes
the bytes directly to that pty. The wrapper never sees them — they go
straight from kernel to terminal. A short tail of newlines pushes the image
into the terminal's scrollback, where the wrapper can't repaint over it.

```
$ ccsight screenshot.png
ccsight: 1 image(s), 192513 bytes via sixel to /dev/pts/3 (cell_h=26px, heights=680px, padding=31 rows)
```

Now scroll up.

## Why

Agentic CLIs run their own TUIs. They capture child-process output to
display in their chat history, and they sanitize control sequences so a
malicious tool can't, say, repaint the agent's status bar to phish you.
A reasonable safety stance — but it means `chafa`, `imgcat`, `kitten icat`
and friends all silently lose their escape bytes between Bash and your
eyes.

The fix isn't to defeat sanitization, it's to **never go through it**. Your
shell's controlling pty is `/dev/pts/N`. As the same UID, you can write to
it directly. The bytes hit your terminal raw, image renders, done.

## Install

```bash
git clone https://github.com/blueberrycongee/ccsight.git
cd ccsight
ln -sf "$(pwd)/ccsight" ~/.local/bin/ccsight
```

Requires `python3 + Pillow`. Input formats: anything Pillow opens — PNG,
JPEG, GIF (first frame), WebP, BMP, TIFF.

### Terminal support

| Terminal | Protocol used | Notes |
|---|---|---|
| iTerm2 | iterm2 (OSC 1337) | full color, instant — no quantize |
| WezTerm | iterm2 | also supports sixel + kitty if forced |
| Ghostty | iterm2 | |
| Kitty | kitty (graphics) | full color, chunked transfer, instant |
| xterm (with sixel) | sixel | most distros ship sixel-enabled by default |
| mlterm / foot / contour / mintty | sixel | |
| macOS Terminal.app | ❌ | no inline image protocol |
| gnome-terminal | ❌ | no sixel, no inline image protocol |

`ccsight` auto-detects which protocol your terminal speaks via
`TERM_PROGRAM`, `LC_TERMINAL`, and `KITTY_WINDOW_ID`. Override with
`--protocol sixel|iterm2|kitty` or `CCSIGHT_PROTOCOL=...`.

Quick sixel sniff (xterm-style terminals): paste this, expect a small red bar:
```bash
printf '\eP0;0;0q#0;2;100;0;0#0!10~-\e\\\n'
```

## Usage

```bash
ccsight <image>                          # auto: protocol, width, height, padding
ccsight a.png b.png c.png                # stack vertically, single trailing pad
ccsight diff before.png after.png        # stack with auto labels (before/after)
ccsight a.png b.png --labels "桌面,移动"  # explicit labels per image

ccsight foo.png --width 800              # narrower
ccsight foo.png --colors 64              # tighter sixel palette
ccsight foo.png --max-h 0                # no height cap (multi-scroll for tall images)
ccsight foo.png --cell-h 24              # see "Calibration" — sets padding tightness
ccsight foo.png --protocol sixel         # force a specific protocol
ccsight foo.png --no-cache               # bypass the encode cache
ccsight foo.png --pts /dev/pts/3         # explicit target if auto-detect misses
ccsight foo.png --quiet                  # skip the trailing hint line
```

After running, **scroll up** in your terminal — the clean image is sitting
in the scrollback. Your agentic CLI's UI may briefly look weird (input
prompt pushed off-screen). Press any key, the wrapper redraws, normal again.

### Multi-image stacks

Passing several paths in one invocation stacks them vertically and pads
once at the end, sized to the combined stack height:

```bash
ccsight before.png after.png diff.png
# → 3 image(s), 412k bytes via iterm2 ... padding=37 rows
```

Stacking happens INSIDE one subprocess. Chaining `ccsight` calls instead
(`ccsight a.png; ccsight b.png`) doesn't work — the wrapping CLI paints
its "Bash tool result" row in between, repainting onto the first image.
One invocation, one paint cycle, one clean stack.

### Diff workflow

`ccsight diff a.png b.png` is shorthand for "two-or-more images stacked
with default labels." Useful for screenshot-comparison loops:

```bash
$ ccsight snap.png > /tmp/before-state
$ # ... change CSS ...
$ ccsight snap.png > /tmp/after-state
$ ccsight diff /tmp/before-state /tmp/after-state
[ before ]
<image>
[ after ]
<image>
```

For custom labels, use `--labels` directly. Labels go through the side
channel like the images, so they sit cleanly in scrollback alongside.

### Single-image vertical fit

By default each image is capped at `terminal_rows × cell_h` pixels tall —
guaranteed to fit in one viewport, so one PageUp shows the whole thing.
Pass `--max-h 0` to render at native size and accept multiple scrolls
for very tall screenshots.

## Calibration

ccsight auto-sizes padding and per-image vertical fit to match the
terminal's actual cell height (pixels per character row). The conversion
matters because the same 800 px image is "50 rows" on a 16 px font and
"30 rows" on a 26 px font — different padding requirements.

### One-time setup: `ccsight calibrate` in a bare shell

```bash
# In a fresh terminal, NOT inside Claude Code / Cursor / Aider:
ccsight calibrate
# → ccsight: detected cell_h = 26px (saved to ~/.config/ccsight/config)
```

`calibrate` sends `CSI 14 t` (window pixel size), reads the response on
the same pty, divides height by `stty rows`, and caches the result.
Once cached, every ccsight invocation (including those wrapped inside
an agentic CLI) reads the cached value — zero overhead, correct sizing.

### Why bare shell

The DSR probe response goes to whoever calls `read()` first on the pty.
Inside an agentic CLI the wrapper is ALSO blocked on `read()` for your
keystrokes, so the response often lands in the wrapper's input parser
instead — which has been observed to:

- Print stray characters (`[4;928;1224t`) into the input box.
- Leave the wrapper's input handler in a state where Enter no longer
  submits.

To prevent this, ccsight refuses to probe inside a wrapper unless you
pass `--force`. The main rendering flow (`ccsight foo.png`) **never
probes** — it only reads the cache. So users who haven't calibrated
yet just get the safe default of `cell_h=16` and slightly over-padded
images, never a broken terminal.

### Resolution priority

```
--cell-h flag → $CCSIGHT_CELL_H → ~/.config/ccsight/config → 16 (last resort)
```

(No automatic probe in this chain — it's strictly opt-in via
`ccsight calibrate`.)

### Manual override

When DSR is impossible (terminal that doesn't respond, no bare-shell
access):

```bash
# eyeball: render at default, count rows, divide image_height_px by row count
ccsight foo.png --cell-h 50

# persistent:
export CCSIGHT_CELL_H=50
# or:
echo 'cell_h=50' > ~/.config/ccsight/config
```

Over-padding is harmless (image is deeper in scrollback, still clean).
Under-padding risks the wrapper's chat-flow repaint clipping rows of
the image, which IS bad — so when in doubt, lean high.

## Caching

Sixel encoding is the slow path (2–4 seconds for a 1280-wide PNG in pure
Python). Re-rendering the same screenshot during UI iteration is a
common workflow, so ccsight caches encoded payloads:

```bash
ccsight snap.png    # cold: ~2.6s on a 1280-wide PNG
ccsight snap.png    # warm: ~25ms (sha256 + 2 cp)
```

Cache key = `sha256(file_bytes + protocol + width + colors + max_h)`.
Hashing the file content (not just path/mtime) means the cache
auto-invalidates the moment the source changes.

- Cache dir: `~/.cache/ccsight/` (override via `XDG_CACHE_HOME`)
- Bypass for one call: `--no-cache`
- Wipe everything: `rm -rf ~/.cache/ccsight`

iTerm2 and Kitty paths are already sub-100ms (no quantize step), so
caching is mostly a sixel win. But the cache works for all protocols
for consistency.

## How it actually works

1. **Find the target pty.** Tries `--pts`, then `$CCSIGHT_PTS`, then
   `/dev/tty`, then walks the parent process tree looking for a process
   named `claude*` / `cursor*` / `aider*` and reads its `tty=` field.
2. **Pick a protocol.** Detects via `TERM_PROGRAM` / `LC_TERMINAL` /
   `KITTY_WINDOW_ID`, falls back to sixel.
3. **Encode the image.**
   - **sixel**: pure-Python with Pillow, quantize to N colors, emit one
     band per 6 pixel rows. Auto-resizes width to `cols × 8 px`.
   - **iterm2 (OSC 1337)**: read original bytes, base64-encode, wrap in
     `\e]1337;File=inline=1;width=Npx;height=Npx:<base64>\a`. Terminal
     scales for us. No quantize.
   - **kitty (graphics)**: same idea, but chunked into 4096-byte
     `\e_G...\e\\` envelopes with `m=1` continuation flags. `q=2`
     suppresses Kitty's ack response so we don't race the wrapper's
     stdin read.
4. **Inject + flush to scrollback.** Stack the encoded payloads,
   followed by `ceil(total_height / cell_h) + 4` blank lines to scroll
   everything past the wrapper's redraw region. Capped at
   `terminal_rows`.

Why scrollback specifically: Claude-Code-style TUIs maintain an internal
"this chat-flow row should show that text" model and use absolute cursor
positioning (`\e[<row>;<col>H`) to repaint. Anything still in the
viewport will eventually be overwritten. Scrollback is the only region
the wrapper never targets.

The wrapper's `stdout` capture only sees `ccsight: sent N bytes` — the
useful payload was sent on a side channel.

## Why agentic CLIs aren't broken

The wrapper isn't wrong to sanitize child stdout. The OWASP-y reason is
real — escape sequences can hijack cursor position, repaint the prompt,
fake a successful auth flow, or silently re-enable streams the wrapper
disabled. The right architecture is: child process writes `stdout`,
parent displays it as text. ccsight is a hatch for the rare case where
you actually want raw graphics, and you accept that it temporarily
perturbs the wrapper's UI.

## Configuration summary

```bash
# CLI flags
--protocol auto|sixel|iterm2|kitty
--width N              # display width in pixels
--colors N             # sixel palette size (8..256)
--padding N            # explicit blank-line count
--cell-h N             # cell height for padding calc
--max-h N              # per-image height cap (0 to disable)
--labels CSV           # labels per stacked image
--pts /dev/pts/N       # explicit pty target
--no-cache             # bypass encode cache
--quiet                # silence status line
--force                # (calibrate only) probe even inside a wrapper

# Environment
CCSIGHT_PROTOCOL       # default protocol
CCSIGHT_CELL_H         # default cell height
CCSIGHT_PTS            # default pty target
XDG_CONFIG_HOME        # config root (default ~/.config)
XDG_CACHE_HOME         # cache root (default ~/.cache)

# Persistent files
~/.config/ccsight/config   # cell_h cache from `ccsight calibrate`
~/.cache/ccsight/          # encoded payload cache
```

## Roadmap

- [x] sixel via `/proc/<wrapper_pid>/tty` discovery
- [x] iTerm2 OSC 1337 protocol
- [x] Kitty graphics protocol
- [x] cell_h auto-detect via `CSI 14 t` (cached, opt-in via `calibrate`)
- [x] image-height-aware auto-padding (small images don't over-scroll)
- [x] multi-image stacking inside one subprocess
- [x] `ccsight diff` shorthand + `--labels`
- [x] Encoded-payload cache (~100× speedup on repeat renders)
- [x] Multi-format input (PNG / JPEG / GIF / WebP / BMP / TIFF)
- [ ] Skill / hook manifest for Claude Code so it auto-invokes when an
      agent wants to show an image
- [ ] `--watch` mode that re-renders on file change
- [ ] numpy-accelerated sixel encoder (drops the cold-render time
      meaningfully if numpy is already installed)
- [ ] Animated GIF playback (current behavior: first frame only)

## License

MIT — see [LICENSE](LICENSE).

## Genesis

Built in conversation with Claude (Opus 4.7) while debugging UI snapshots
inside Claude Code. The bypass was not the first idea — see the commit
log for the dead ends (write to `/proc/<pid>/fd/1` blocked by sandbox;
OSC 1337 in stdout stripped; protocol-detection-via-DSR breaking the
wrapper's input parser). Worth open-sourcing because every agentic CLI
is going to inherit the same constraint.
