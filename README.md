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

ccsight auto-sizes padding to match the rendered image's actual height,
so smaller images don't push you a full screen up. The calculation needs
to know how tall a single character cell is in pixels — the conversion
factor between "image pixels emitted" and "terminal rows scrolled."

The default is **16 px / cell**, which matches typical xterm at default
font size. If your terminal uses a larger font (HiDPI / 12pt monospace
on a Retina display), each cell is taller — say 24..50 px — and the
default over-pads. Symptom: you scroll way more than needed to find a
small image.

To calibrate, eyeball your image once: roughly how many character rows
does it occupy in the terminal? Then:

```
cell-h ≈ image_height_px / image_rows_visible
```

For example, a 680 px image that visually spans ~13 rows → cell-h ≈ 52.
Pin it via:

```bash
# one-shot
ccsight foo.png --cell-h 50

# persistent (add to ~/.bashrc / ~/.zshrc)
export CCSIGHT_CELL_H=50
```

When in doubt, leave the default — over-padding is harmless (image is
deeper in scrollback, but still clean). Under-padding risks the
wrapper's chat-flow repaint clipping rows of the image, which IS bad.

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
