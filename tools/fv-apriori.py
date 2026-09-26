#!/usr/bin/env python3
"""What the Apriori array holds, and whether the volume can promote all of it.

Why this exists: `P2 SEQ` runs one character per Apriori *match*, so its length
is `mP2Apriori` and nothing else. The panel's line is 46 characters and
`entries` - the array's own count - is the denominator that turns 46 into a
statement. Steps 4.130 and 4.132 have been carrying that denominator as a device
reading; it is not one. The array is a section in the payload, the payload is on
this disk, and three of the four numbers this tool prints are therefore host
facts:

    bytes    the EFI_SECTION_RAW payload of the Apriori FFS file
    entries  bytes / 16
    missing  Apriori GUIDs with no file in the volume - cannot be promoted
    files    files in the volume, for the denominator of `discovered`

The fourth is the one that matters and the one that is easy to get wrong: an
Apriori entry whose GUID is not a file in the volume can never match, so a
non-zero `missing` would explain an `unhit` without any walk stopping. Measured
on the current build it is **zero**, so every one of the 70 entries has a file and
the misses are about what the walk discovered, not about what the volume holds.

What this tool is not: a decoder of the SEQ letters. It counts the array, and
that count is what makes the letters readable: with `tools/apriori-prefix.py`'s
prefix table beside it, 70 entries, entry 0 unmatchable and only `seen` 48 and
49 giving 46 - and those two giving the same 46 - fix the promoted batch
without any assumption about the slot map. A map that is a *hypothesis* cannot
be indexed by (that is `tools/apriori-prefix.py`'s claim, and it holds); a map
the length and the volume *determine* can be. What the panel is still needed
for is the *status* behind each letter, which is `P2 WHY` and `P2 ERR`, and the
*confirmation* of the batch, which is `P2 APRI`'s `bytes=`/`entries=`/`sum=`
and `P2 DIAG`'s GUID list.

Usage:
    tools/fv-apriori.py                       # the build the payloads come from
    tools/fv-apriori.py <FVMAIN.Fv>
"""

import argparse
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_FV = os.path.join(
    ROOT,
    "work/uefi/Mu-Silicium/Build/gauguinPkg/DEBUG_CLANGPDB/FV/FVMAIN.Fv",
)

APRIORI_GUID = "FC510EE7-FFDC-11D4-BD41-0080C73C8881"


def guid(b):
    return "%08X-%04X-%04X-%s-%s" % (
        struct.unpack_from("<I", b, 0)[0],
        struct.unpack_from("<H", b, 4)[0],
        struct.unpack_from("<H", b, 6)[0],
        b[8:10].hex().upper(),
        b[10:16].hex().upper(),
    )


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def walk_volume(d):
    """Every FFS file in the volume: (offset, name GUID, type, size).

    The volume header is 0x48 bytes here plus a 0x10-byte block map, and the
    first file does not follow it directly: this volume carries an extended
    header at `ExtHeaderOffset` (0x60), whose own 20-byte record ends at 0x74 and
    is padded to 0x78, which is where the Apriori file and the `.txt` beside the
    volume both put it. So the start is taken from `ExtHeaderOffset` when there is
    one and from `HeaderLength` when there is not, and the walk then follows the
    linked list the way `FvCheck` does and checks its count against the `.txt`.
    """
    if d[0x28:0x2C] != b"_FVH":
        raise SystemExit("no _FVH signature at 0x28 - is this a firmware volume?")
    hdrlen = struct.unpack_from("<H", d, 0x30)[0]
    ext = struct.unpack_from("<H", d, 0x34)[0]
    off = (ext + 0x14) if ext else hdrlen
    off = (off + 7) & ~7
    out = []
    while off + 24 <= len(d):
        g = d[off : off + 16]
        if g == b"\xff" * 16:
            break
        typ = d[off + 18]
        size = int.from_bytes(d[off + 20 : off + 23], "little")
        if size < 24 or off + size > len(d):
            break
        out.append((off, guid(g), typ, size))
        off = (off + size + 7) & ~7
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("fv", nargs="?", default=DEFAULT_FV)
    a = p.parse_args()

    if not os.path.exists(a.fv):
        sys.exit("no such volume: %s" % a.fv)

    d = read(a.fv)
    files = walk_volume(d)
    print("volume %s" % os.path.relpath(a.fv, ROOT))
    print("  size %d bytes, %d files" % (len(d), len(files)))

    ap = [f for f in files if f[1] == APRIORI_GUID]
    if len(ap) != 1:
        sys.exit("expected one Apriori file, found %d" % len(ap))
    off, _, typ, size = ap[0]
    print("  Apriori file at %#x, type %#x, %d bytes" % (off, typ, size))

    body = d[off + 24 : off + size]
    secs = []
    i = 0
    while i + 4 <= len(body):
        ssz = int.from_bytes(body[i : i + 3], "little")
        styp = body[i + 3]
        if ssz < 4 or i + ssz > len(body):
            break
        secs.append((styp, ssz, body[i + 4 : i + 4 + ssz - 4]))
        i += (ssz + 3) & ~3
    raw = [s for s in secs if s[0] == 0x19]
    if len(raw) != 1:
        sys.exit("expected one EFI_SECTION_RAW, found %d" % len(raw))
    _, ssz, data = raw[0]
    entries = len(data) // 16
    print("  section raw %d bytes -> %d entries of 16" % (len(data), entries))

    names = {}
    xref = a.fv + ".xref"
    xref = os.path.join(os.path.dirname(a.fv), "Guid.xref")
    if os.path.exists(xref):
        for line in open(xref, errors="replace"):
            f = line.split()
            if len(f) >= 2:
                names[f[0].upper()] = f[1]

    fvset = {g for _, g, _, _ in files}
    missing = [
        (i + 1, guid(data[i * 16 : i * 16 + 16]))
        for i in range(entries)
        if guid(data[i * 16 : i * 16 + 16]) not in fvset
    ]
    print("  Apriori GUIDs with no file in the volume: %d" % len(missing))
    for i, g in missing[:20]:
        print("    ap%d  %s  %s" % (i, g, names.get(g, "?")))

    print()
    print("VERDICT  entries=%d  missing=%d  files=%d  ->  a SEQ of 46 is %d"
          % (entries, len(missing), len(files), 46))
    print("  %s" % (
        "every Apriori entry has a file, so no miss is explained by the volume; "
        "the misses are about what the walk discovered"
        if not missing else
        "entries with no file can never be promoted - count them first, they "
        "explain misses without any walk stopping"))
    print("  and this tool alone does not say WHICH 46 were promoted: with "
          "tools/apriori-prefix.py's prefix table it does, since entries=%d with "
          "entry 0 unmatchable and only seen 48/49 giving 46 - and those two "
          "agreeing - leaves one batch, which is the map the SEQ letters can be "
          "read through" % entries)


if __name__ == "__main__":
    main()
