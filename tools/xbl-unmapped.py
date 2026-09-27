#!/usr/bin/env python3
"""Every driver in the XBL extraction that no table in this build names.

Why this exists. `tools/make_xbl_binaries.py`'s `DRIVERS` table is the gate the
whole packaging pipeline runs through: `present_drivers()` iterates *that table*
and checks the `.efi` beside each name, so a driver whose `.efi` and `.ffs` both
sit in `device/dxe/` but whose name is not a key in the table is not "a driver we
chose not to ship" - it is a driver nothing in this repository has ever read.
`tools/make_uefi_platform.py` cannot report it either: its orphan report is
`have - referenced`, and `have` is built from the same table, so the one
instrument aimed at "packaged but not in the volume" is blind to "not packaged at
all". That is the gap this tool measures.

The table's own comment says how it was built - *"Derived by matching against
Binaries/surya/QcomPkg/Drivers, which is the same Qualcomm driver set for a
sibling SoC"* - and that is the whole rule: an extracted driver gets a row when
surya's package has one. So the set this tool reports is not a set of accidents.
It is exactly `extraction - surya`, and it is invisible by construction.

Two readings of every row, and they are not the same question:

    a driver the tree builds from source instead
        The right answer for most of them. Mu-Silicium carries source for DxeCore,
        Fat, PartitionDxe, DiskIoDxe, HiiDatabase and the Arm architectural
        drivers, and building those from source rather than shipping Qualcomm's
        signed copy is the deliberate policy of this port. Matched by the INF's
        own `BASE_NAME`, so the match is against the name the build actually uses
        and not against the file name - which is what makes the list short rather
        than alarming.
    a driver nothing covers
        These are the rows worth reading. A driver that is in the phone's own XBL,
        is not built from source anywhere in the tree, and is not named by the
        blob table is a driver this firmware does not have and cannot acquire.

The first cut of this tool scored a `BASE_NAME` hit as "the tree builds it", and
that is one step too generous. The tree contains far more INFs than any one
platform builds - `MdeModulePkg.dsc` alone lists FvSimpleFileSystemDxe - so an
INF with a matching name proves the source is *present*, not that anything
compiles it into this volume. The two are different answers and the difference
is exactly one row: `FvSimpleFileSystem`, whose source sits in the tree, whose
INF `MdeModulePkg.dsc:487` names, whose INF `gauguinPkg/Include/DXE.inc` does
not, and which the stock firmware promotes at a-priori entry 28. So the built-
from-source reading now additionally requires the INF to appear in DXE.inc, and
a name that fails that second test is reported with `source, not built` rather
than counted as covered.

The second group is reported against the stock firmware's own a-priori array when
one is supplied (`--stock-array`), because that array is the phone's own answer to
"which of these does the firmware promote" - and it is the one authority here that
is not a sibling SoC's opinion. An entry in that array is not proof the driver is
needed for anything this port does; it is proof the device's own firmware ran it.

Usage:
    tools/xbl-unmapped.py
    tools/xbl-unmapped.py --stock-array /tmp/phone-payload.raw
    tools/xbl-unmapped.py --dxe device/dxe --mu work/uefi/Mu-Silicium --rows
"""
import argparse
import glob
import importlib.util
import os
import re
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DXE = os.path.join(ROOT, "device", "dxe")
DEFAULT_MU = os.path.join(ROOT, "work", "uefi", "Mu-Silicium")
DEFAULT_DXE_INC = os.path.join(ROOT, "uefi", "Platforms", "Xiaomi", "gauguinPkg",
                               "Include", "DXE.inc")

# The FREEFORM file the stock firmware's own a-priori array lives in. Not
# `FC510EE7-...`, which is the PI file GenFv emits for *our* builds - the stock
# array is a separate, vendor-named file beside it, and its 16-byte entries are
# firmware-file GUIDs rather than the INF-order list ours holds. See docs/08
# step 4.169.
STOCK_APRIORI_GUID = "6A69BA33-B140-5742-ABC9-0C5D03920B42"
SECTION_RAW = 0x19

# A `.efi` is a DXE driver here. The extraction also holds RAW files (the panel
# XMLs, the charger config, `uefipil.cfg`, the boot logo) which are packaged by a
# different path entirely and are not this tool's subject.
PE32_SECTION = 0x10


def by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def blob_table():
    """The names `tools/make_xbl_binaries.py` will package, i.e. the whole gate."""
    mx = by_path("mx", os.path.join(ROOT, "tools", "make_xbl_binaries.py"))
    return set(mx.DRIVERS)


def source_bases(mu_root):
    """BASE_NAME -> INF path, over the tree's sources.

    `Binaries/` is excluded on purpose, and it is the point of the exclusion: a
    hit under `Binaries/<other device>/` is a *different device's blob* and
    answering "the tree builds this" with another phone's signed binary would
    make every row in the report look covered.
    """
    out = {}
    for root, _dirs, files in os.walk(mu_root):
        if os.sep + "Build" in root or os.sep + "Binaries" in root:
            continue
        for f in files:
            if not f.endswith(".inf"):
                continue
            p = os.path.join(root, f)
            try:
                text = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            m = re.search(r"^\s*BASE_NAME\s*=\s*(\S+)", text, re.M)
            if m:
                out.setdefault(m.group(1), p)
    return out


def built_infs(inc_path):
    """The INF basenames this platform's volume actually compiles.

    Presence of source is not presence of the driver: the tree holds INFs for
    every package it vendors, and a platform DSC picks a subset. `DXE.inc` is
    that subset for the DXE volume - every line is either a source INF the build
    compiles or a `Binaries/` blob it packages - so it is the right thing to
    test a `BASE_NAME` hit against. Compares on basename because the include
    spells source INFs by their package-relative path and blobs by
    `Binaries/<device>/...`, and a path prefix is not the question.
    """
    out = set()
    if not os.path.exists(inc_path):
        return out
    for line in open(inc_path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line.startswith("INF "):
            continue
        out.add(os.path.basename(line.split()[-1]).lower())
    return out


def ffs_sections(path):
    """The section types of an FFS file, so a RAW payload is not counted a driver."""
    c = by_path("c", os.path.join(ROOT, "tools", "pci-guid-census.py"))
    d = open(path, "rb").read()
    return [styp for styp, _sz, _pay in c.sections(d[24:])]


def stock_apriori_names(path, dxe_dir):
    """The stock firmware's a-priori array as driver names, or {} if not found.

    Two shapes are accepted because both have been how this array was read: a
    payload image (BootShim -> FD -> FVMAIN), which is what `/tmp/phone-payload.raw`
    is, and a bare FD. The GUID is looked for in the volume's file roster rather
    than at a fixed offset, for the same reason `tools/fv-inventory.py` finds the
    FD by its magic.
    """
    fvi = by_path("fvi", os.path.join(ROOT, "tools", "fv-inventory.py"))
    d = open(path, "rb").read()
    if d[:8] == b"ANDROID!":
        files, _len, offsets, inner = fvi.unpack(path)
    elif d[:2] == b"\x81\x03":
        files, _len, offsets, inner = fvi.fvmain_of_fd(d, verbose=False)
    else:
        files, _len, offsets, inner = fvi.fvmain_of_fd(d, verbose=False)
    at = next((i for i, f in enumerate(files) if f[0] == STOCK_APRIORI_GUID), None)
    if at is None:
        return None
    _g, _t, size, _n, _s = files[at]
    body = inner[offsets[at] + 24:offsets[at] + size]
    blob = next((b for st, b in fvi.sections(body) if st == SECTION_RAW), None)
    if blob is None or len(blob) % 16:
        return None

    # The array's entries are firmware-file GUIDs, so they resolve against the
    # stock `.ffs` NameGuids - the same resolution docs/08 steps 4.169 and 4.171
    # use, which is 74 of 74 on this device and is why the names are trustworthy.
    by_guid = {}
    for f in glob.glob(os.path.join(dxe_dir, "*.ffs")):
        hdr = open(f, "rb").read(16)
        by_guid[str(uuid.UUID(bytes_le=hdr)).upper()] = os.path.basename(f)[:-4]
    return [by_guid.get(fvi.guid_str(blob[i:i + 16])) or fvi.guid_str(blob[i:i + 16])
            for i in range(0, len(blob), 16)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dxe", default=DEFAULT_DXE, help="the XBL extraction directory")
    ap.add_argument("--mu", default=DEFAULT_MU, help="Mu-Silicium checkout")
    ap.add_argument("--dxe-inc", default=DEFAULT_DXE_INC,
                    help="the platform include listing the volume's INFs, used to "
                         "tell 'the tree builds this' from 'the tree has the "
                         "source and builds something else'")
    ap.add_argument("--stock-array", default=None,
                    help="a payload image carrying the stock firmware's own a-priori "
                         "array, used to say whether the device ran each driver")
    ap.add_argument("--rows", action="store_true",
                    help="print every extracted driver, not only the uncovered ones")
    args = ap.parse_args()

    blobs = blob_table()
    bases = source_bases(args.mu) if os.path.isdir(args.mu) else {}
    built = built_infs(args.dxe_inc)
    stock = stock_apriori_names(args.stock_array, args.dxe) if args.stock_array else None

    efis = sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(args.dxe, "*.efi")))
    print("=== %s: %d .efi files" % (os.path.relpath(args.dxe, ROOT), len(efis)))
    print("    blob table (tools/make_xbl_binaries.py DRIVERS): %d names" % len(blobs))
    print("    source BASE_NAMEs in %s: %d" % (os.path.relpath(args.mu, ROOT), len(bases)))
    print("    INFs listed by %s: %d" % (os.path.relpath(args.dxe_inc, ROOT), len(built)))
    if args.stock_array:
        print("    stock a-priori array: %s"
              % ("%d entries" % len(stock) if stock else "NOT FOUND in " + args.stock_array))

    rows = []
    for n in efis:
        if n in blobs:
            rows.append((n, "blob", "", ""))
            continue
        inf = bases.get(n)
        if inf and os.path.basename(inf).lower() in built:
            rows.append((n, "source", os.path.relpath(inf, args.mu), ""))
            continue
        secs = ffs_sections(os.path.join(args.dxe, n + ".ffs"))
        kind = "driver" if PE32_SECTION in secs else "not a PE32 (data file)"
        if inf:
            kind += ", source in tree but the volume does not build it"
        at = ""
        if stock is not None and n in stock:
            at = "stock a-priori entry %d" % stock.index(n)
        rows.append((n, "NOTHING", kind, at))

    covered = [r for r in rows if r[1] != "NOTHING"]
    naked = [r for r in rows if r[1] == "NOTHING"]
    n_blob = len([r for r in rows if r[1] == "blob"])
    n_src = len([r for r in rows if r[1] == "source"])

    if args.rows:
        print("\n-- every extracted .efi --")
        print("%-26s %-9s %s" % ("driver", "covered by", "detail"))
        for n, how, det, at in rows:
            print("%-26s %-9s %s %s" % (n, how, det, at))

    print("\n=== %d of %d extracted DXE drivers are accounted for by this build"
          % (len(covered), len(efis)))
    print("      %-3d packaged from the extraction (a `DRIVERS` table row)" % n_blob)
    print("      %-3d built from tree source instead, INF listed in DXE.inc" % n_src)
    print("      %-3d named by nothing: not packaged, not built, and not reported by"
          % len(naked))
    print("          the generator's orphan line, whose input is the blob table itself")
    print("    (%d + %d + %d = %d)" % (n_blob, n_src, len(naked), len(efis)))
    if naked:
        print("\n-- the uncovered ones --")
        for n, _how, kind, at in naked:
            print("    %-24s %-44s %s" % (n, kind, at))
        if stock is not None:
            promoted = [r for r in naked if r[3]]
            print("\n    %d of them are promoted by the device's own firmware" % len(promoted))
            print("    (the stock a-priori array names them, so the stock firmware ran them):")
            for n, _h, _k, at in promoted:
                print("      %-24s %s" % (n, at))
    print("\n  a name here is a driver that this repository has never read, not a driver"
          "\n  it decided against - the decision the extraction represents was never taken.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
