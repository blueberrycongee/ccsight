# ccsight

Inline image rendering for terminals **wrapped by agentic CLIs** like Claude
Code, Cursor, and Aider — which capture and sanitize their child processes'
stdout, eating the ESC bytes that every inline-image protocol depends on.

`ccsight` doesn't fight the wrapper. It walks around it: finds the wrapper's
own controlling pty via `/proc`, and writes the sixel image directly to that
device. The wrapper never sees the bytes — they go straight from kernel to
terminal. A dose of trailing newlines pushes the image into the terminal's
scrollback, where the wrapper can't repaint over it.

```
$ ccsight screenshot.png
ccsight: sent 227387 bytes of sixel to /dev/pts/3
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
git clone https://github.com/<you>/ccsight.git
cd ccsight
ln -sf "$(pwd)/ccsight" ~/.local/bin/ccsight
```

Requires `python3 + Pillow` and a sixel-capable terminal:
- ✅ `xterm` (compiled with `--enable-sixel-graphics`, default in most distros)
- ✅ `mlterm`, `foot`, `wezterm`, `contour`, `mintty`
- ❌ iTerm2 / Kitty (use their native protocols; ccsight may add fallbacks
  later)
- ❌ macOS Terminal.app, gnome-terminal (no sixel)

Quick sixel sniff: paste this into your terminal, expect a small red bar:
```bash
printf '\eP0;0;0q#0;2;100;0;0#0!10~-\e\\\n'
```

## Usage

```
ccsight <image.png>                    # inline render — width, height, padding auto-fit
ccsight a.png b.png c.png              # stack multiple images, single trailing pad
ccsight foo.png --width 800            # narrower
ccsight foo.png --colors 64            # tighter palette, smaller payload
ccsight foo.png --max-h 0              # don't cap height — render at native, scroll
ccsight foo.png --padding 200          # push deeper into scrollback
ccsight foo.png --cell-h 24            # see "Calibration" — sets padding tightness
ccsight foo.png --pts /dev/pts/3       # explicit target if auto-detect misses
ccsight foo.png --quiet                # skip the trailing hint line
```

After running, **scroll up** in your terminal — the clean image is sitting
in the scrollback. Your agentic CLI's UI may briefly look weird (input
prompt pushed off-screen). Press any key, the wrapper redraws, normal again.

### Multi-image stacks

Passing several paths in one invocation stacks them vertically and pads
once at the end:

```bash
ccsight before.png after.png diff.png
# → 3 image(s), 412k bytes ... padding=37 rows
```

Stacking happens INSIDE one subprocess. Chaining ccsight calls instead
(`ccsight a.png; ccsight b.png`) doesn't work — the wrapping CLI paints
its "Bash tool result" row in between, repainting onto the first image.
One invocation, one paint cycle, one clean stack.

### Single-image vertical fit

By default each image is capped at `terminal_rows × cell_h` pixels tall —
guaranteed to fit in one viewport, so one PageUp shows the whole thing.
Pass `--max-h 0` to render at native size and accept multiple scrolls
for very tall screenshots.

## Calibration: how much to scroll back

ccsight auto-sizes padding and per-image vertical fit to match the
terminal's actual cell height (pixels per character row). The conversion
matters because the same 800 px image is "50 rows" on a 16 px font and
"30 rows" on a 26 px font — different padding requirements.

### One-time setup: run `ccsight calibrate` in a bare shell

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
--cell-h flag   →   $CCSIGHT_CELL_H   →   ~/.config/ccsight/config   →   16 (last resort)
```

(No automatic probe in this chain — it's strictly opt-in via
`ccsight calibrate`.)

### Manual override

When DSR is impossible:

```bash
# eyeball estimate: render once at default, count rows, divide:
ccsight foo.png --cell-h 50

# persistent
export CCSIGHT_CELL_H=50
```

Over-padding is harmless (image is deeper in scrollback, still clean).
Under-padding risks the wrapper's chat-flow repaint clipping rows of
the image, which IS bad — so when in doubt, lean high.

## How it actually works

1. **Find the target pty.** Tries `--pts`, then `$CCSIGHT_PTS`, then
   `/dev/tty`, then walks the parent process tree looking for a process
   named `claude*` / `cursor*` / `aider*` and reads its `tty=` field.
2. **Encode the PNG to sixel.** Pure-Python with Pillow — no `chafa`,
   no `libsixel`, no ImageMagick. Quantizes to N colors, emits one band
   per 6 pixel rows in the standard sixel DCS form. Auto-resizes to
   `cols × 8 px` so the image fits the viewport horizontally; reports
   the post-resize pixel size on stderr so the wrapper knows how much
   padding to add.
3. **Inject + flush to scrollback.** `cat sixel > /dev/pts/N`, then
   `ceil(image_h / cell_h) + 4` blank lines after to scroll the image
   past the wrapper's redraw region. Capped at `terminal_rows` so we
   never overshoot a full page.

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
disabled. The right architecture is: child process writes `stdout`, parent
displays it as text. ccsight is a hatch for the rare case where you
actually want raw graphics, and you accept that it temporarily perturbs
the wrapper's UI.

## Limits / roadmap

- [x] sixel via `/proc/<wrapper_pid>/tty` discovery
- [ ] iTerm2 OSC 1337 protocol (for iTerm2 / WezTerm / Ghostty users
      whose wrapper still strips ESC)
- [ ] Kitty graphics protocol
- [ ] Terminal capability auto-detect via `\e[c` query (needs raw TTY
      access, not always available inside agentic shells)
- [ ] Skill manifests for Claude Code so the agent invokes ccsight
      automatically when asked to "show this image"
- [ ] `--watch` mode that re-renders when the file changes

## License

MIT — see [LICENSE](LICENSE).

## Genesis

Built in conversation with Claude (Opus 4.7) while debugging UI snapshots
inside Claude Code. The bypass was not the first idea — see the commit log
for the dead ends (write to `/proc/<pid>/fd/1` blocked by sandbox; OSC 1337
in stdout stripped; Kitty/iTerm2 protocols depending on terminal we didn't
have). Worth open-sourcing because every agentic CLI is going to inherit
the same constraint.
