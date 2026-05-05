#!/usr/bin/env python3
# Image metadata reader for protocols that pass raw image bytes (iTerm2,
# Kitty graphics) instead of re-encoding. Returns the post-scale display
# dimensions ccsight should advertise to the terminal.
#
# The width/height clamps mirror png2sixel.py so padding calculations
# line up across protocols.
import sys

try:
    from PIL import Image
except ImportError:
    sys.stderr.write(
        "imgmeta: Pillow (PIL) is not installed.\n"
        "  Install it with one of:\n"
        "    python3 -m pip install --user Pillow\n"
        "    sudo apt install python3-pil       # Debian/Ubuntu\n"
        "    sudo dnf install python3-pillow    # Fedora\n"
        "    brew install python-pillow         # macOS\n"
    )
    sys.exit(2)


def compute_display_size(path: str, max_w: int, max_h: int) -> tuple[int, int, str]:
    try:
        img = Image.open(path)
    except Exception as exc:
        sys.stderr.write(f"imgmeta: cannot open '{path}': {exc}\n")
        sys.exit(1)
    w, h = img.size
    fmt = img.format or "UNKNOWN"
    if max_w > 0 and w > max_w:
        h = int(h * max_w / w)
        w = max_w
    if max_h > 0 and h > max_h:
        w = int(w * max_h / h)
        h = max_h
    return w, h, fmt


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write(
            "usage: imgmeta.py <path> [max_width=0] [max_height=0]\n"
        )
        return 2
    path = sys.argv[1]
    max_w = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    max_h = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    w, h, fmt = compute_display_size(path, max_w, max_h)
    print(f"WIDTH={w}")
    print(f"HEIGHT={h}")
    print(f"FORMAT={fmt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
