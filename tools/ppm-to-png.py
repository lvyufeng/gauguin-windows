#!/usr/bin/env python3
"""Turn a QEMU `screendump` PPM into a PNG, and say how much is on it.

Two jobs, both of them about being able to look at a boot that is happening on a
machine with no display attached.

The PNG is written by hand rather than with ImageMagick, because the point of
this file is to be readable on a host where the graphics packages are not
installed -- and a PPM is a header and a block of RGB triples, which zlib and
`struct` are enough for.

The colour count is the part that gets quoted. `screendump` at a fixed moment
returns a black frame both when the guest has drawn nothing and when the guest
has not started, and those are different answers that look identical; the number
of distinct colours in the frame is what tells them apart, and a frame that is a
single colour is a frame with nothing on it. The count is printed on stdout, and
`--scale N` prints a coarse ASCII view of the whole frame -- useful because a
Windows Setup window and a firmware menu are distinguishable at 40x12 even when
neither is legible.

    python3 tools/ppm-to-png.py shot-004.ppm            # writes shot-004.png
    python3 tools/ppm-to-png.py shot-004.ppm --scale 60
"""
import argparse
import os
import struct
import sys
import zlib


def read_ppm(path):
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"P6"):
        raise SystemExit("%s is not a binary PPM (magic %r)" % (path, data[:2]))
    # The header is three whitespace-separated tokens with `#` comments allowed
    # between them, and the single whitespace byte after `maxval` is where the
    # pixels begin. Splitting on whitespace and then finding that byte is more
    # robust than three `readline` calls, which a comment line breaks.
    fields, i = [], 2
    while len(fields) < 3:
        while i < len(data) and data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while data[i:i + 1] not in (b"\n", b""):
                i += 1
            continue
        j = i
        while j < len(data) and not data[j:j + 1].isspace():
            j += 1
        fields.append(int(data[i:j]))
        i = j
    i += 1
    w, h, maxval = fields
    if maxval != 255:
        raise SystemExit("only 8-bit PPM is read here (maxval %d)" % maxval)
    px = data[i:i + w * h * 3]
    if len(px) < w * h * 3:
        raise SystemExit("truncated PPM: %d of %d pixel bytes" % (len(px), w * h * 3))
    return w, h, px


def write_png(path, w, h, px):
    raw = bytearray()
    for y in range(h):
        raw.append(0)                       # filter type 0 (None) per scanline
        raw += px[y * w * 3:(y + 1) * w * 3]

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
        f.write(chunk(b"IEND", b""))


def count_colours(px, cap=1 << 22):
    """How many distinct colours the frame holds, or `>cap` when there are more.

    The set is the whole answer and not a sample of it: a firmware screen is a
    handful of colours and a text Setup screen is a few thousand, so the boundary
    that matters is far below any sampling error, and stopping at `cap` bounds the
    memory a runaway frame can take.
    """
    seen = set()
    for i in range(0, len(px), 3):
        seen.add(px[i:i + 3])
        if len(seen) > cap:
            return ">%d" % cap
    return str(len(seen))


def ascii_view(w, h, px, cols):
    """A coarse luminance view, so a frame can be told apart without being read."""
    rows = max(3, cols * h // (w * 2))
    ramp = " .:-=+*#%@"
    out = []
    for r in range(rows):
        y0, y1 = r * h // rows, max(r * h // rows + 1, (r + 1) * h // rows)
        line = []
        for c in range(cols):
            x0, x1 = c * w // cols, max(c * w // cols + 1, (c + 1) * w // cols)
            tot = n = 0
            for y in range(y0, y1, max(1, (y1 - y0) // 4)):
                base = y * w * 3
                for x in range(x0, x1, max(1, (x1 - x0) // 4)):
                    o = base + x * 3
                    tot += 299 * px[o] + 587 * px[o + 1] + 114 * px[o + 2]
                    n += 1
            lum = (tot // n) // 1000 if n else 0      # 0..255, the 1000 is 299+587+114
            line.append(ramp[min(9, lum * 9 // 255)])
        out.append("".join(line))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ppm")
    ap.add_argument("--scale", type=int, default=0,
                    help="also print a coarse ASCII view this many columns wide")
    ap.add_argument("-o", "--out", help="PNG path (default: the PPM's name)")
    args = ap.parse_args()

    w, h, px = read_ppm(args.ppm)
    out = args.out or (os.path.splitext(args.ppm)[0] + ".png")
    write_png(out, w, h, px)
    print("%dx%d %s colours -> %s" % (w, h, count_colours(px), out))
    if args.scale:
        print(ascii_view(w, h, px, args.scale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
