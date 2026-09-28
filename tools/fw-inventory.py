#!/usr/bin/env python3
"""List the FFS files inside a UEFI firmware volume, decompressing what is packaged.

`tools/xbl_extract.py` does this for one specific container: the ELF-wrapped FV
inside Qualcomm's XBL, whose nested volume is gzip. This script does it for a
bare `.fd` — the shape AAVMF ships — and for any other FV, because the question
"does this firmware contain driver X" has now been answered wrongly twice by
reading the container instead of its contents.

The two wrong answers, and why they were wrong, are the reason this script exists:

  * A byte scan for a driver's `FILE_GUID` in little-endian order. The control —
    three drivers AAVMF certainly contains — read absent, so the method measured
    nothing. An FFS GUID is metadata, not a marker: a file's GUID is only present
    if the file is present, and the volume is compressed, so *no* GUID is present
    until it is decompressed.

  * A byte scan for the driver's name in UTF-16LE. Same defect, and the control
    (`Fat`, `PartitionDxe`, `GraphicsConsoleDxe`) read absent again. The name
    does live in the file as UCS-2, in a UI section — inside the compressed
    volume.

So a name is only readable after decompression, and decompression is what this
script does. Names come from whichever name-bearing section the FFS file carries
(UI, version, or the ASCII UCS-2 section), which is what EDK2's own build puts
there and what `xbl_extract.py` already reads.

Usage:
    fw-inventory.py FIRMWARE.fd [FIRMWARE2.fd ...]
    fw-inventory.py --grep UdfDxe FIRMWARE.fd
"""
import lzma
import gzip
import re
import struct
import sys
import uuid

FFS_TYPES = {
    0x01: "RAW", 0x02: "FREEFORM", 0x03: "SECURITY_CORE", 0x04: "PEI_CORE",
    0x05: "DXE_CORE", 0x06: "PEIM", 0x07: "DRIVER", 0x08: "COMBINED",
    0x09: "APPLICATION", 0x0A: "MM", 0x0B: "FV_IMAGE", 0x0C: "COMBINED_MM_DXE",
    0x0E: "MM_STANDALONE", 0x0F: "MM_CORE_STANDALONE", 0xF0: "PAD",
}
NAME_SECTIONS = (0x15, 0x14, 0x13, 0x18)   # UI, version, ..., ASCII/UCS-2
PE32_SECTION = 0x10
GUIDED_SECTION = 0x02

# The section-definition GUIDs that mean "the payload is compressed". EDK2 names
# the last two in MdeModulePkg; the gzip one is Qualcomm's, and is what XBL's
# nested volume uses.
COMPRESSORS = {
    "ee4e5898-3914-4259-9d6e-dc7bd79403cf": "lzma",
    "d42ae6bd-1352-4bfb-909a-ca72a6eae889": "lzma",
    "a31280ad-481e-41b6-95e8-127f4c984779": "tiano",
    "1d301fe9-be79-4353-91c2-d23c0d59cb45": "gzip",
    "3d532050-5cda-4fd0-879e-0f7f630d5afb": "brotli",
}


def ffs_files(fv, start, end):
    """Yield (offset, guid, ftype, size) for each FFS file in an FV."""
    p = start
    while p + 24 <= end:
        name = fv[p:p + 16]
        if name == b"\xff" * 16 or name == b"\x00" * 16:
            p += 8
            continue
        ftype = fv[p + 18]
        size = struct.unpack("<I", fv[p + 20:p + 24])[0] & 0xFFFFFF
        if ftype not in FFS_TYPES or size < 24 or p + size > end:
            p += 8
            continue
        yield p, uuid.UUID(bytes_le=name), ftype, size
        p = (p + size + 7) & ~7


def sections(fv, start, end):
    p = start
    while p + 4 <= end:
        size = struct.unpack("<I", fv[p:p + 4])[0] & 0xFFFFFF
        stype = fv[p + 3]
        if size < 4 or p + size > end:
            return
        yield p, stype, size
        p = (p + size + 3) & ~3


def file_name(fv, p, size):
    best = ""
    for sp, stype, ssize in sections(fv, p + 24, p + size):
        if stype in NAME_SECTIONS:
            txt = fv[sp + 4:sp + ssize].decode("utf-16-le", errors="ignore")
            txt = "".join(c for c in txt if 32 <= ord(c) < 127).strip()
            if len(txt) > len(best) and not txt.isdigit():
                best = txt
    return best


def has_pe32(fv, p, size):
    return any(st == PE32_SECTION for _, st, _ in sections(fv, p + 24, p + size))


def decompress(payload, kind):
    """Undo one GUIDed section. LZMA is EDK2's `.lzma`-alone framing; gzip is XBL's."""
    if kind == "gzip":
        return gzip.decompress(payload)
    if kind == "lzma":
        return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(payload)
    return None            # tiano and brotli are not in the standard library


def find_fv_offsets(d):
    return [m.start() - 0x28 for m in re.finditer(b"_FVH", d)]


def walk(d, out, depth=0, limit=4):
    """Find every FV in d, print its files, recurse into compressed nested FVs."""
    for fv_off in find_fv_offsets(d):
        if fv_off < 0 or fv_off + 0x38 > len(d):
            continue
        fsguid = uuid.UUID(bytes_le=d[fv_off + 0x10:fv_off + 0x20])
        fvlen, = struct.unpack("<Q", d[fv_off + 0x20:fv_off + 0x28])
        hlen, = struct.unpack("<H", d[fv_off + 0x30:fv_off + 0x32])
        if fvlen < 0x1000 or fv_off + fvlen > len(d):
            continue
        pad = "  " * depth
        print(f"{pad}FV at 0x{fv_off:x} len=0x{fvlen:x} hdr={hlen} "
              f"fs={fsguid}")
        fv = d[fv_off:fv_off + fvlen]
        for p, guid, ftype, size in ffs_files(fv, hlen, len(fv)):
            name = file_name(fv, p, size)
            kind = FFS_TYPES[ftype]
            out.append(name or str(guid))
            print(f"{pad}  {kind:14} size={size:#010x} "
                  f"{name or guid}{'  [PE32]' if has_pe32(fv, p, size) else ''}")
            if depth >= limit:
                continue
            for sp, stype, ssize in sections(fv, p + 24, p + size):
                if stype != GUIDED_SECTION:
                    continue
                sg = uuid.UUID(bytes_le=fv[sp + 4:sp + 20])
                dofs, = struct.unpack("<H", fv[sp + 20:sp + 22])
                payload = fv[sp + dofs:sp + ssize]
                how = COMPRESSORS.get(str(sg))
                if not how:
                    print(f"{pad}    guided section {sg} — not a known compressor")
                    continue
                try:
                    inner = decompress(payload, how)
                except Exception as e:                       # noqa: BLE001
                    print(f"{pad}    {how} section did not decompress: {e}")
                    continue
                if inner is None:
                    print(f"{pad}    {how}-compressed section, "
                          f"{len(payload):,} B — no decompressor here")
                    continue
                print(f"{pad}    -> {how} nested volume, {len(inner):,} bytes")
                walk_nested(inner, out, depth + 2, limit)


def walk_nested(inner, out, depth, limit):
    """A nested FV is a bare FV, but its own header may sit at a small offset."""
    for base in (0, 8, 0x48):
        if inner[base:base + 4] != b"\x00\x00\x00\x00" and \
           inner[base + 0x28:base + 0x2C] == b"_FVH":
            walk(inner[base:], out, depth, limit)
            return
    walk(inner, out, depth, limit)


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    grep = None
    # Flags are pulled out wherever they appear, because the natural way to reach
    # for this script is `fw-inventory.py FIRMWARE.fd --grep UdfDxe` — with the
    # file first — and an argument parser that only reads argv[1] then tries to
    # open a file named `--grep`.
    paths = []
    rest = argv[1:]
    while rest:
        if rest[0] == "--grep":
            if len(rest) < 2:
                sys.exit("--grep needs a pattern")
            grep, rest = rest[1], rest[2:]
        else:
            paths.append(rest[0])
            rest = rest[1:]
    for path in paths:
        d = open(path, "rb").read()
        print(f"=== {path} ({len(d):,} bytes)")
        out = []
        walk(d, out)
        named = [n for n in out if not re.fullmatch(r"[0-9a-f-]{36}", n)]
        print(f"--- {len(out)} FFS files, {len(named)} carrying a name")
        if grep:
            hits = [n for n in named if grep.lower() in n.lower()]
            print(f"--- --grep {grep}: {len(hits)} hit(s)"
                  + (f": {hits}" if hits else ""))


if __name__ == "__main__":
    main(sys.argv)
