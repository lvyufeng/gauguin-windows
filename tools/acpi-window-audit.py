#!/usr/bin/env python3
"""Check every `Memory32Fixed` window's LENGTH, which no other gate reads.

The gap this closes is not hypothetical, and it has now been hit three times.

`tools/acpi-dt-crosscheck.py` is a GSI checker: it anchors each `Interrupt ()`
to a window by **base address** and never reads the length.  So a window can be
right where it starts and wrong where it ends, and every gate the repository
has - `iasl`, the `cmp` twin, `acpi-runtime-check.py` (which compares the file
against itself), the crosscheck - passes it:

    GPU0  four windows, each length the tree's value with an extra hex digit
          (0x800->0x8000, 0x1000->0x10000, 0x214->0x2140, 0x30->0x3000)
    MMU1  0x10000 doubled to 0x20000 - and the only table claiming 0x20000
          anywhere was this port's own, disassembled back into the corpus

The shape is the same both times: a plausible hex-digit slip, invisible to a
base-keyed check.

**The tree alone cannot settle a length, and the corpus alone cannot either.**
For two of gauguin's windows the tree and the corpus disagree, and the corpus
is right because it is a table convention rather than a hardware fact:

    UFS0  0x01D84000 : tree 0x3000+0x8000 (two nodes), corpus 0x14000 (12
                       boards, against 0x1c000 x10 and 0x15000 x7)
    URS0  0x0A600000 : tree 0x200000 (ssusb) and 0xe000 (dwc3), corpus
                       0xfffff (23 boards, against 0x100000 x3)

So each window is classified against BOTH, and only a window that neither
source supports is a failure:

    EXACT       the tree has a node at this base with this length
    UNION       the tree's nodes at this base sum to this length (2 x 0x10000)
    CORPUS      no tree match, but >= --min-boards corpus boards at this base
                write this length - a convention, not a slip
    UNSUPPORTED neither.  This is the GPU0/MMU1 class and the only failure.

    python3 tools/acpi-window-audit.py --asl tools/acpi/gauguin.asl \
        --dtb /tmp/gauguin-vendor.dtb --corpus /tmp/allboards
"""

from __future__ import annotations

import argparse
import collections
import glob
import os
import re
import subprocess
import sys
import tempfile

MEM32_RE = re.compile(
    r"Memory32Fixed \(\s*\w+\s*,\s*\n\s*(0x[0-9A-Fa-f]+)\s*,\s*\n\s*(0x[0-9A-Fa-f]+)"
)
DEV_RE = re.compile(r"Device \((\w+)\)")
# A corpus window is a base comment immediately followed by a length comment.
CORPUS_RE = re.compile(
    r"0x([0-9A-Fa-f]{8}),\s*//\s*Address Base\s*\n\s*"
    r"0x([0-9A-Fa-f]{8}),\s*//\s*Address Length"
)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def asl_windows(path: str):
    """Yield (device, base, length), attributing each window to its ENCLOSING
    device by brace depth.

    A backward scan for the nearest `Device (...)` misnames the window: `GPU0`
    declares a child `MON0` before its own `_CRS`, so every window in that
    `_CRS` would be reported against `MON0` - which is how the four GPU0
    lengths came out labelled `MON0` and one of hardware's own came out `SDC2`.
    """
    src = strip_comments(open(path, encoding="utf-8", errors="replace").read())
    tokens = []  # (position, kind, payload)
    for m in re.finditer(DEV_RE.pattern, src):
        tokens.append((m.start(), "dev", m.group(1)))
    for m in re.finditer(MEM32_RE.pattern, src):
        tokens.append((m.start(), "win",
                       (int(m.group(1), 16), int(m.group(2), 16))))
    for m in re.finditer(r"[{}]", src):
        tokens.append((m.start(), "brace", m.group(0)))
    tokens.sort()

    stack: list[str] = []
    pending: str | None = None
    for _pos, kind, payload in tokens:
        if kind == "dev":
            pending = payload
        elif kind == "brace":
            if payload == "{":
                if pending is not None:
                    stack.append(pending)
                    pending = None
                else:
                    stack.append(stack[-1] if stack else "?")
            elif stack:
                stack.pop()
        else:
            yield (stack[-1] if stack else "?"), payload[0], payload[1]


def tree_windows(dtb: str):
    """Every (base, length) pair in every `reg`, plus which node it came from."""
    out = collections.defaultdict(list)
    dts = subprocess.run(["dtc", "-I", "dtb", "-O", "dts", dtb],
                         capture_output=True, text=True)
    if dts.returncode:
        sys.exit(f"dtc failed on {dtb}: {dts.stderr.strip()[:200]}")
    for m in re.finditer(r"reg = <([^>]*)>", dts.stdout):
        try:
            nums = [int(t, 16) for t in m.group(1).split()]
        except ValueError:
            continue
        for i in range(0, len(nums) - 1, 2):
            out[nums[i]].append(nums[i + 1])
    return out, dts.stdout


def corpus_windows(paths):
    """Count (base, length) across disassembled reference tables."""
    counts = collections.Counter()
    for p in paths:
        text = open(p, encoding="utf-8", errors="replace").read()
        for m in CORPUS_RE.finditer(text):
            counts[(int(m.group(1), 16), int(m.group(2), 16))] += 1
    return counts


def mainline_windows(paths):
    """Base -> lengths from MAINLINE device-tree SOURCE (.dts/.dtsi).

    A third reference, independent of both the vendor tree (decompiled from
    the phone's DTB) and the Qualcomm ACPI corpus.  `reg` here is written with
    an address-cells/size-cells pair, so `<0 0x03d40000 0 0x10000>` is four
    cells rather than two; both forms are read.
    """
    out = collections.defaultdict(set)
    for p in paths:
        text = open(p, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"reg\s*=\s*((?:<[^>]*>\s*,?\s*)+)", text):
            for g in re.findall(r"<([^>]*)>", m.group(1)):
                try:
                    v = [int(x, 16) for x in g.split()]
                except ValueError:
                    continue
                if len(v) >= 4 and v[0] == 0 and v[2] == 0:
                    for i in range(0, len(v) - 3, 4):
                        if v[i] == 0 and v[i + 2] == 0:
                            out[v[i + 1]].add(v[i + 3])
                elif len(v) >= 2:
                    for i in range(0, len(v) - 1, 2):
                        out[v[i]].add(v[i + 1])
    return out


def disassemble(aml_paths):
    """Return .dsl paths for the corpus, disassembling into a temp dir."""
    tmp = tempfile.mkdtemp(prefix="win-audit-")
    out = []
    for a in aml_paths:
        sibling = os.path.splitext(a)[0] + ".dsl"
        if os.path.exists(sibling) and os.path.getmtime(sibling) >= os.path.getmtime(a):
            out.append(sibling)
            continue
        subprocess.run(["iasl", "-d", "-p", os.path.join(tmp, os.path.basename(a)),
                        a], capture_output=True)
        made = os.path.join(tmp, os.path.basename(a).replace(".aml", ".dsl"))
        if os.path.exists(made):
            out.append(made)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asl", default="tools/acpi/gauguin.asl")
    ap.add_argument("--dtb", required=True,
                    help="the board's own tree - pass the VENDOR tree off the "
                         "phone, not the firmware's DTB")
    ap.add_argument("--corpus", default=None,
                    help="dir of .dsl/.aml reference tables (the 32-board set)")
    ap.add_argument("--min-boards", type=int, default=3,
                    help="corpus boards that must agree before a convention "
                         "outranks the tree (default 3)")
    ap.add_argument("--mainline", action="append", default=None,
                    metavar="FILE.dts",
                    help="a mainline DTS/DTSI to read as a THIRD reference; "
                         "repeatable. The upstream sm6350.dtsi + sm7225.dtsi "
                         "settle windows the vendor tree and the corpus "
                         "disagree about.")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    tree, _dts = tree_windows(a.dtb)
    L = mainline_windows(a.mainline or [])
    if a.mainline and not a.quiet:
        print(f"mainline: {len(L)} base address(es) from "
              f"{len(a.mainline)} file(s)")
    counts = collections.Counter()
    if a.corpus:
        refs = sorted(glob.glob(os.path.join(a.corpus, "*.dsl")))
        if not refs:
            refs = disassemble(sorted(glob.glob(os.path.join(a.corpus, "*.aml"))))
        counts = corpus_windows(refs)
        if not a.quiet:
            print(f"corpus: {len(refs)} table(s) under {a.corpus}")

    rows = []
    for dev, base, length in asl_windows(a.asl):
        ml = sorted(L.get(base, ()))
        if base in tree:
            if length in tree[base]:
                kind, why = "EXACT", "tree"
            elif sum(tree[base]) == length:
                kind, why = "UNION", "tree declares it once (n compatibles)"
            else:
                kind, why = None, ""
        else:
            kind, why = None, ""
        if kind is None:
            n = counts.get((base, length), 0)
            if length in ml:
                kind, why = "MAINLINE", f"upstream writes it"
            elif n >= a.min_boards:
                kind, why = "CORPUS", f"{n} board(s) write it"
            else:
                kind, why = "UNSUPPORTED", (
                    f"tree {[hex(x) for x in tree[base]] or 'no node'}, "
                    f"corpus {n} board(s), mainline "
                    f"{[hex(x) for x in ml] or 'no node'}")
        rows.append((kind, dev, base, length, why))

    if not a.quiet:
        print(f"{len(rows)} Memory32Fixed window(s) in {a.asl}\n")
        for kind, dev, base, length, why in rows:
            if kind != "EXACT":
                print(f"  {kind:12s} {dev:6s} {base:#010x} +{length:#x}  {why}")
        # A window where mainline names the same hardware and DISagrees is not
        # a failure - the corpus is a product table and may round - but the
        # three sources not agreeing is itself the finding, so it is printed.
        dis = [(d, b, l) for _k, d, b, l, _w in rows
               if L.get(b) and l not in L[b]]
        if dis and a.mainline:
            print(f"\n  mainline disagrees with {len(dis)} window(s) it names:")
            for d, b, l in dis:
                print(f"    {d:6s} {b:#010x}: file +{l:#x}, "
                      f"upstream {[hex(x) for x in sorted(L[b])]}")

    c = collections.Counter(r[0] for r in rows)
    bad = [r for r in rows if r[0] == "UNSUPPORTED"]
    print("\n" + "  ".join(f"{k}={c[k]}" for k in
                           ("EXACT", "UNION", "MAINLINE", "CORPUS",
                            "UNSUPPORTED")))
    if bad:
        print(f"\nFAIL: {len(bad)} window(s) neither the tree nor the corpus "
              f"supports:")
        for _k, dev, base, length, why in bad:
            print(f"  {dev} {base:#010x}+{length:#x}: {why}")
        return 1
    print("PASS: every window's length is the tree's, the tree's summed, or a "
          "corpus convention.")
    return 0


if __name__ == "__main__":
    sys.exit(main())