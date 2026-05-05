#!/usr/bin/env python3
# Pure-PIL PNG -> sixel encoder.
#
# Sixel format primer:
#   DCS q                     start
#   "Pan;Pad;Ph;Pv            raster attributes (aspect 1:1 + image WxH)
#   #c;2;r;g;b                define palette index c as RGB (0..100 scale)
#   #c                        select palette index c for following sixel chars
#   <char in 0x3F..0x7E>      6 vertical pixels packed bottom-up bit 0..5
#   !<n><char>                run-length: char repeated n times
#   $                         carriage return (overlay another color on row)
#   -                         line feed (advance 6 px down)
#   ST  ESC backslash         end
import sys
from PIL import Image


def png_to_sixel(
    path: str,
    max_width: int = 1280,
    max_colors: int = 128,
) -> tuple[str, int, int]:
    """Encode `path` as a sixel string.

    Returns (sixel_payload, rendered_width_px, rendered_height_px). Callers
    use the post-resize height to decide how aggressively to scroll the
    image into scrollback after the wrapper's TUI lands its next repaint.
    """
    img = Image.open(path).convert("RGB")
    if img.width > max_width:
        new_h = int(img.height * max_width / img.width)
        img = img.resize((max_width, new_h), Image.LANCZOS)

    img_p = img.quantize(colors=max_colors, dither=Image.Dither.NONE)
    palette = img_p.getpalette()
    width, height = img_p.size
    pixels = img_p.tobytes()

    out: list[str] = []
    out.append("\x1bPq")
    out.append(f'"1;1;{width};{height}')

    used = sorted(set(pixels))
    for color in used:
        r = palette[color * 3] * 100 // 255
        g = palette[color * 3 + 1] * 100 // 255
        b = palette[color * 3 + 2] * 100 // 255
        out.append(f"#{color};2;{r};{g};{b}")

    for band_y in range(0, height, 6):
        rows: list[bytes] = []
        for sub in range(6):
            y = band_y + sub
            if y < height:
                rows.append(pixels[y * width : (y + 1) * width])
            else:
                rows.append(b"\x00" * width)

        band_colors: set[int] = set()
        for row in rows:
            band_colors.update(row)

        for color in sorted(band_colors):
            chars: list[str] = []
            any_set = False
            for x in range(width):
                bits = 0
                for sub_idx, row in enumerate(rows):
                    if row[x] == color:
                        bits |= 1 << sub_idx
                if bits:
                    any_set = True
                chars.append(chr(0x3F + bits))
            if not any_set:
                continue

            out.append(f"#{color}")
            i = 0
            while i < width:
                char = chars[i]
                j = i + 1
                while j < width and chars[j] == char:
                    j += 1
                run = j - i
                if run >= 4:
                    out.append(f"!{run}{char}")
                else:
                    out.append(char * run)
                i = j
            out.append("$")
        out.append("-")

    out.append("\x1b\\")
    return "".join(out), width, height


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(
            "usage: png2sixel.py <png> [max_width=1280] [max_colors=128]",
            file=sys.stderr,
        )
        return 0 if len(sys.argv) >= 2 else 2
    path = sys.argv[1]
    max_width = int(sys.argv[2]) if len(sys.argv) > 2 else 1280
    max_colors = int(sys.argv[3]) if len(sys.argv) > 3 else 128
    payload, w, h = png_to_sixel(path, max_width, max_colors)
    sys.stdout.write(payload)
    # Stderr metadata so the bash wrapper can size auto-padding to the
    # actual rendered image, not a worst-case constant.
    sys.stderr.write(f"WIDTH={w}\nHEIGHT={h}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
