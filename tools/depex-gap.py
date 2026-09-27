#!/usr/bin/env python3
"""Which drivers in a built volume have *no* dependency expression, and whose stock one we hold?

Why this exists. `tools/pci-guid-census.py --depex` answers "does this volume wait on a GUID"; this
tool answers the question underneath it, which nothing was asking: **how many of the files in the
volume carry a `DXE_DEPEX` section at all, and for the ones that do not, is the driver's real depex
sitting in this repository.**

The two answers differ, and the difference is what the tool is for. A driver whose FFS file has no
`DXE_DEPEX` is not "a driver with no dependencies" to the DXE core - it is a driver the core treats
as UEFI 2.0, dispatched the moment all EFI services are available rather than when the protocols it
names exist (`MdeModulePkg/Core/Dxe/Dispatcher/Dispatcher.c` sets `Depex = NULL` on a failed
`ReadSection`, and `Dispatcher/Dependency.c`'s `CoreIsSchedulable` then returns TRUE on
`CoreAllEfiServicesAvailable`). The stock firmware did not ship them that way: the extraction kept
the whole stock FFS file in `device/dxe/<name>.ffs`, `DXE_DEPEX` section included, and the generated
platform only ever shipped the `PE32` out of it.

Usage:

    tools/depex-gap.py work/out/depex/Mu-gauguin-depex-gzip.img
    tools/depex-gap.py /tmp/fv-usb.bin --stock device/dxe --rows
    tools/depex-gap.py <volume> --stock device/dxe --tree <Mu-Silicium>

The argument is any of three shapes, because the payloads this project produces have been all
three: a bare firmware volume (what a step extracts before measuring), a payload image whose
gunzipped kernel *is* a volume, and - the shape every current payload has - a boot image whose
kernel is a BootShim-wrapped FD holding the volume compressed inside `FVMAIN_COMPACT`. The last
one is why `read_volume` below is not simply `tools/pci-guid-census.py`'s: that one stops at the
first two shapes, and an image it cannot read raises rather than measuring the wrong bytes, so
the failure is loud - but it is still a payload this tool has to be able to read.

Two cautions, both learned the hard way in the step that first ran this:

    absent is not the same as undefined
        a driver with no depex section still runs, and still runs *early* - which is the failure this
        tool exists to make visible, not a missing feature to be tolerated
    a name is not a file
        the stock `.ffs` is matched to a volume file by module name, so a driver built from source in
        this tree and a stock file with the same name are counted together; `--rows` prints the
        stock file's own size beside the volume file's so that mismatch is visible rather than
        averaged away
"""
import argparse
import glob
import importlib.util
import os
import re
import struct
import sys
import uuid
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_TREE = os.path.join(ROOT, "work", "uefi", "Mu-Silicium")
DEFAULT_STOCK = os.path.join(ROOT, "device", "dxe")
SECTION_DXE_DEPEX = 0x13


def by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_volume(path):
    """The volume bytes of `path`, in any of the three shapes a payload has had here.

    `tools/pci-guid-census.py`'s reader is tried first and covers two of them: a bare volume, and
    a boot image whose gunzipped kernel *is* one. Every payload built since the BootShim moved
    inside the kernel is the third shape - boot image -> gzip -> BootShim -> FD -> LZMA'd
    `FVMAIN_COMPACT` -> the volume - and for that one the descent is delegated to
    `tools/fv-inventory.py`, which already carries it (its `_walk_from`/`decompress_guided` hold
    the padding and `DataOffset` rules). This tool measures volumes and has no business keeping a
    second copy of those rules.

    The delegation is by *try*, not by magic-number test, because the two readers disagree about
    an image whose payload starts with the gzip magic and still is not a volume: a failed read is
    a `SystemExit` there, and it is caught here rather than allowed to end the run.
    """
    census = by_path("census", os.path.join(HERE, "pci-guid-census.py"))
    try:
        return census.read_volume(path)
    except SystemExit:
        pass

    fvi = by_path("fvi", os.path.join(HERE, "fv-inventory.py"))
    d = open(path, "rb").read()
    if d[:8] != b"ANDROID!":
        raise SystemExit("%s: neither a firmware volume nor an Android boot image" % path)
    ks, ps = struct.unpack("<I", d[8:12])[0], struct.unpack("<I", d[36:40])[0]
    blob = d[ps:ps + ks]
    if blob[:2] == b"\x1f\x8b":
        payload = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(blob)
    else:
        payload = blob
    # The BootShim stub precedes the FD and its size is a constant of BootShim's build, so the FD
    # is found by the FV magic rather than by a hard-coded offset - a header that grows by eight
    # bytes would otherwise read as a volume that starts eight bytes late.
    sig = payload.find(b"_FVH")
    if sig < fvi.FV_SIG:
        raise SystemExit("%s: no FD inside the kernel payload" % path)
    _files, fv_len, _offs, inner = fvi.fvmain_of_fd(payload[sig - fvi.FV_SIG:], verbose=False)
    if inner is None or not fv_len:
        raise SystemExit("%s: the FD holds no decompressible FVMAIN_COMPACT" % path)
    return inner[:fv_len]


def package_names(tree):
    """GUID -> macro, over every `*.dec` in the tree.

    `tools/pci-guid-census.py`'s `protocol_names` reads `MdePkg/Include` only, which is where the
    EDK2 protocols live. The Qualcomm ones live in a package declaration instead, so a depex full of
    `gEfiChipInfoProtocolGuid` and its neighbours prints entirely as `unnamed in this tree` without
    this - and an unnamed GUID beside a named one reads like a parse failure rather than like the
    dependency it is.
    """
    out = {}
    define = re.compile(r"(\w+)\s*=\s*\{\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*,"
                        r"\s*(0x[0-9A-Fa-f]+)\s*,\s*\{([^}]*)\}")
    for root, _dirs, files in os.walk(tree):
        if os.sep + "Build" in root:
            continue
        for f in files:
            if not f.endswith(".dec"):
                continue
            text = open(os.path.join(root, f), errors="replace").read()
            for m in define.finditer(text):
                try:
                    parts = [int(x, 16) for x in re.findall(r"0x[0-9A-Fa-f]+", m.group(5))]
                    u = uuid.UUID("%08x-%04x-%04x-%02x%02x-%s" % (
                        int(m.group(2), 16), int(m.group(3), 16), int(m.group(4), 16),
                        parts[0], parts[1], "".join("%02x" % p for p in parts[2:8])))
                except (ValueError, IndexError):
                    continue
                out.setdefault(str(u).upper(), m.group(1))
    return out


def stock_depexes(stock_dir):
    """name -> (depex payload, whole-file size) for every stock `.ffs` that has one."""
    census = by_path("census", os.path.join(HERE, "pci-guid-census.py"))
    out = {}
    for f in sorted(glob.glob(os.path.join(stock_dir, "*.ffs"))):
        d = open(f, "rb").read()
        for styp, _sz, pay in census.sections(d[24:]):
            if styp == SECTION_DXE_DEPEX:
                out[os.path.basename(f)[:-4]] = (pay, len(d))
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("volume", help="firmware volume, or boot image holding one")
    ap.add_argument("--stock", default=DEFAULT_STOCK, help="directory of extracted stock .ffs files")
    ap.add_argument("--tree", default=DEFAULT_TREE, help="tree the GUID names come from")
    ap.add_argument("--rows", action="store_true", help="print one row per driver")
    args = ap.parse_args()

    census = by_path("census", os.path.join(HERE, "pci-guid-census.py"))
    fvap = by_path("fvap", os.path.join(HERE, "fv-apriori.py"))
    names = census.inf_and_pi_names(args.tree)
    decs = package_names(args.tree) if os.path.isdir(args.tree) else {}
    stock = stock_depexes(args.stock)

    d = read_volume(args.volume)
    files = fvap.walk_volume(d)
    have, lack, recoverable, gone = 0, [], [], []
    for off, fg, _typ, size in files:
        body = d[off + 24:off + size]
        dep = None
        for styp, _sz, pay in census.sections(body):
            if styp == SECTION_DXE_DEPEX:
                dep = pay
                break
        nm = (names.get(fg.upper()) or (None, ""))[0]
        if dep is not None:
            have += 1
            continue
        lack.append((nm or fg[:8], size, fg))
        if nm and nm in stock:
            recoverable.append((nm, size, stock[nm]))

    print("=== %s: %d files, %d with a DXE_DEPEX, %d without"
          % (args.volume, len(files), have, len(lack)))
    print("    stock depexes available under %s: %d, over %d stock .ffs files"
          % (args.stock, len(stock), len(glob.glob(os.path.join(args.stock, "*.ffs")))))

    if args.rows:
        print("\n-- the %d files with no depex section --" % len(lack))
        print("%-26s %9s  %s" % ("module", "size", "stock depex"))
        for nm, size, _fg in sorted(lack):
            if nm in stock:
                pay, ssz = stock[nm]
                print("%-26s %9d  yes, %d bytes (stock file %d B): %s"
                      % (nm, size, len(pay), ssz, describe(pay, names, decs)))
            else:
                print("%-26s %9d  no stock file with this name, or none with a depex" % (nm, size))

    print("\n  of the %d without one, %d have a stock namesake that carries a real dependency"
          % (len(lack), len(recoverable)))
    if recoverable:
        print("  expression this build does not ship:")
        for nm, size, (pay, _ssz) in sorted(recoverable):
            print("    %-24s %s" % (nm, describe(pay, names, decs)))
    print("\n  a file with no depex section is dispatched as soon as all EFI services are\n"
          "  available, not when the protocols it names exist - absent is not the same as\n"
          "  undefined, and it is the early dispatch this tool reports.")


def describe(pay, names, decs):
    """The pushed GUIDs of a depex as names, or `TRUE` when it has none."""
    census = by_path("census", os.path.join(HERE, "pci-guid-census.py"))
    terms = census.depex_guids(pay)
    if not terms:
        return "TRUE (no operands)"
    out = []
    for g in terms:
        out.append(names.get(g, (None,))[0] or decs.get(g, g[:8]))
    return " AND ".join(out)


if __name__ == "__main__":
    main()
