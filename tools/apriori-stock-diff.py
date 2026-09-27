#!/usr/bin/env python3
"""What order does the *stock* firmware promote its drivers in, and how does ours differ?

Why this exists. This project's a-priori order does not come from the device. `APRIORI.inc` is
generated from the `suryaPkg` reference package and rewritten to `Binaries/gauguin/`, so the order
the payload actually promotes drivers in is another board's order with this board's drivers
substituted into it. The device's own order was never read - until it turned out to be sitting in
the repository already.

Qualcomm's XBL delivers its a-priori list as a raw file *named after the a-priori file GUID*, and
`tools/make_uefi_platform.py` copies that XBL raw file into the volume verbatim, under a generated
file GUID (`6A69BA33-B140-5742-ABC9-0C5D03920B42`) whose `UI` section is the XBL filename. So the
stock order is both in `device/dxe-inventory.txt` (as the XBL file `fc510ee7-…`, `raw 1184B`) and in
every volume this build produces. It is inert for the a-priori read itself - `Dispatcher.c:2062`
calls `Fv->ReadSection (Fv, &gAprioriGuid, EFI_SECTION_RAW, 0, …)`, which matches on the *file
GUID*, and this copy has a different one - but it is a complete, checkable statement of the order
the stock firmware used on this exact handset.

This tool puts the two orders side by side and names every difference. Two cautions it keeps:

    a GUID is not a name   the stock build names its files with the *module's* id (RpmhDxe is
                           `CB29F4D1-…9766` in the stock table) while this build names them with
                           the INF's `FILE_GUID` (`60F4DF83-…`), so a GUID-level comparison would
                           report every driver as different. Both are resolved to names first.
    a name is not a file   the same driver can be built from a different source package on the two
                           sides, and where that is true it is visible in the substitution rows
                           rather than hidden in a count

Usage:

    tools/apriori-stock-diff.py work/out/usb-host/Mu-gauguin-xhci-host-gzip.img
    tools/apriori-stock-diff.py <img> --stock <file> --tree work/uefi/Mu-Silicium
    tools/apriori-stock-diff.py <img> --device device/dxe   # validate the stock side

`--device` checks the stock list against the extracted stock FFS files: every GUID in a genuine
a-priori array names a file in the volume it belongs to, and a GUID that names nothing means the
file being read is not one. That check is what identified the `?` row in the first run - the one
entry `inf_and_pi_names` could not resolve was `ADSPDxe`, which this tree does not have.
"""
import argparse
import difflib
import glob
import hashlib
import importlib.util
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_TREE = os.path.join(ROOT, "work", "uefi", "Mu-Silicium")
DEFAULT_STOCK = os.path.join(DEFAULT_TREE, "Binaries", "gauguin", "RawFiles",
                             "fc510ee7-ffdc-11d4-bd41-0080c73c8881")
# The FREEFORM file this build emits the stock array as, for `--from-volume`.
STOCK_COPY_GUID = "6A69BA33-B140-5742-ABC9-0C5D03920B42"
SECTION_RAW = 0x19


def by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def guids_of(blob, what):
    if len(blob) % 16:
        sys.exit("%s: %d bytes, not a multiple of 16 - not a GUID array" % (what, len(blob)))
    return [str(uuid.UUID(bytes_le=blob[i:i + 16])).upper() for i in range(0, len(blob), 16)]


def stock_from_volume(path):
    """The stock array out of a *built* volume's FREEFORM copy, rather than the raw file."""
    fvap = by_path("fvap", os.path.join(HERE, "fv-apriori.py"))
    census = by_path("census", os.path.join(HERE, "pci-guid-census.py"))
    d = census.read_volume(path)
    for off, fg, _typ, size in fvap.walk_volume(d):
        if fg.upper() != STOCK_COPY_GUID:
            continue
        for styp, _ssz, spay in census.sections(d[off + 24:off + size]):
            if styp == SECTION_RAW:
                return guids_of(spay, "%s:%s" % (path, fg))
    sys.exit("%s: no FREEFORM %s in it - the volume predates that file" % (path, STOCK_COPY_GUID))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="built payload .img or FD, whose Apriori array is 'ours'")
    ap.add_argument("--stock", default=DEFAULT_STOCK,
                    help="the stock a-priori array (default: the XBL raw file in the tree)")
    ap.add_argument("--from-volume", help="read the stock array out of a built volume instead")
    ap.add_argument("--tree", default=DEFAULT_TREE)
    ap.add_argument("--device", help="directory of extracted stock .ffs files, to validate --stock")
    args = ap.parse_args()

    fvi = by_path("fv_inventory", os.path.join(HERE, "fv-inventory.py"))
    aorder = by_path("apriori_order", os.path.join(HERE, "apriori-order.py"))
    census = by_path("census", os.path.join(HERE, "pci-guid-census.py"))

    ours, nfiles = aorder.apriori_array(fvi, args.image)
    if args.from_volume:
        stock = stock_from_volume(args.from_volume)
        stock_from = args.from_volume
    else:
        blob = open(args.stock, "rb").read()
        stock = guids_of(blob, args.stock)
        stock_from = args.stock
    print("ours  %-52s %3d entries" % (args.image, len(ours)))
    print("stock %-52s %3d entries" % (stock_from, len(stock)))
    print("      sha256(ours)  %s" % hashlib.sha256(
        b"".join(uuid.UUID(g).bytes_le for g in ours)).hexdigest()[:16])
    print("      sha256(stock) %s" % hashlib.sha256(
        b"".join(uuid.UUID(g).bytes_le for g in stock)).hexdigest()[:16])

    names = census.inf_and_pi_names(args.tree)
    if not names:
        sys.exit("no GUID definitions under %s - wrong --tree?" % args.tree)

    dev_name = {}

    def nm(g):
        # The tree's name first, then the device's own FFS filename, and only then silence. The
        # fallback matters: `ADSPDxe` is promoted by the stock firmware and has no INF in this
        # tree at all, so a tree-only lookup prints one `UNNAMED` row in the middle of the block
        # that names the display and PIL family - which reads like a parse failure rather than
        # like the finding it is.
        n = names.get(g, (None, ""))[0]
        return n or dev_name.get(g, "UNNAMED")

    if args.device:
        ffs = glob.glob(os.path.join(args.device, "*.ffs"))
        for f in ffs:
            dev_name[str(uuid.UUID(bytes_le=open(f, "rb").read(16))).upper()] = \
                os.path.basename(f)[:-4]
        miss = [g for g in stock if g not in dev_name]
        print("      device check: %d of %d stock entries name a .ffs under %s%s"
              % (len(stock) - len(miss), len(stock), args.device,
                 "" if not miss else "  - naming nothing: %s" % ", ".join(dev_name.get(g, g) for g in miss)))

    S = [nm(g) for g in stock]
    O = [nm(g) for g in ours]
    sm = difflib.SequenceMatcher(a=S, b=O, autojunk=False)
    print("\n  the two orders, aligned by name (stock on the left):\n")
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            print("  =  %s" % ", ".join(S[i1:i2]))
        elif tag == "delete":
            print("  -  stock only:  %s" % ", ".join(S[i1:i2]))
        elif tag == "insert":
            print("  +  ours only:   %s" % ", ".join(O[j1:j2]))
        else:
            print("  ~  stock %s  ->  ours %s" % (", ".join(S[i1:i2]), ", ".join(O[j1:j2])))

    equal = sum(i2 - i1 for t, i1, i2, _j1, _j2 in sm.get_opcodes() if t == "equal")
    print("\n  %d of %d entries are the same sequence on both sides, in the same order"
          % (equal, len(stock)))
    print("  by position: %d stock-only, %d ours-only, %d substituted against %d"
          % (sum(i2 - i1 for t, i1, i2, _j1, _j2 in sm.get_opcodes() if t == "delete"),
             sum(j2 - j1 for t, _i1, _i2, j1, j2 in sm.get_opcodes() if t == "insert"),
             sum(i2 - i1 for t, i1, i2, _j1, _j2 in sm.get_opcodes() if t == "replace"),
             sum(j2 - j1 for t, _i1, _i2, j1, j2 in sm.get_opcodes() if t == "replace")))
    print("  by name:     %d names only the stock list carries, %d only ours"
          % (len(set(S) - set(O)), len(set(O) - set(S))))
    print("               (the two counts differ because a name can be promoted at a different\n"
          "                position on each side, and then it is stock-only by position and\n"
          "                present on both by name)" if len(set(S) - set(O)) != 0 else "")
    print("\n  the stock array is the order this handset's own firmware promoted in; ours is the\n"
          "  reference package's order with this board's drivers substituted into it.")


if __name__ == "__main__":
    main()
