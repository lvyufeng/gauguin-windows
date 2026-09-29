#!/usr/bin/env python3
"""Classify every id the ASL presents that a vendor BSP's INFs do not claim.

`tools/driver-id-census.py` answers "which hardware ids does the vendor BSP
claim that the table does not present" - a question about *omissions*.  Its
other figure, `ASL-has-id-but-no-driver`, reads like a defect list and is not
one, and the reason is structural:

    A BSP ships only the drivers Qualcomm chose to redistribute.  Storage,
    SD, USB role-switch and the ACPI enumerators themselves are *in-box* -
    they live in the base image, not in a vendor cab - so an id the BSP does
    not claim has three possible explanations, not one: the hardware is
    absent, the driver is in-box, or the id is wrong.

    Worse, the vendor cab's absence proves nothing, because the id can be
    wrong *and* in-box.  gauguin's `URS0` is the worked case: its `_HID`
    `QCOM0A8B` is claimed by no INF in 712 on disk, and the node binds anyway
    because its `_CID` `PNP0CA1` is what in-box `urssynopsys.inf` claims.

So this tool does not guess.  It takes a list of INF trees and sorts each
presented id into one of:

    BOUND       some INF in the sweep claims the exact id
    CLASS       some INF claims the node's `_CID`, which binds it by class
    KNOWN-GAP   no INF claims it, and the id is recorded below with its reason
    UNEXPLAINED none of the above - a defect in the table or in this list

`UNEXPLAINED` is the only failing outcome, and the only one that needs a
decision.  Run it with every INF tree you have; an unbounded sweep cannot
tell BOUND from UNEXPLAINED.

    python3 tools/presented-id-coverage.py \
        --infs ~/work/woa-ref/inf-7280 \
        --infs ~/work/woa-ref/infs-install \
        --asl tools/acpi/gauguin.asl
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module

_census = import_module("driver-id-census".replace("-", "_")) if False else None


def _load_census():
    """Import driver-id-census.py, whose name is not a valid module name."""
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "driver_id_census", os.path.join(here, "driver-id-census.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_blocks():
    """Import acpi-hid-census.py for BLOCKS, the block table's one definition.

    The two censuses are separate tools with separate scopes - this one sweeps
    INFs, that one reads the ASL and the reference corpus - and BLOCKS lives
    in the second.  Re-typing the twelve rows here would be a second copy of a
    measured table, which is exactly the kind of drift the matrix is meant to
    catch; so the block list is imported, not repeated.
    """
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "acpi_hid_census", os.path.join(here, "acpi-hid-census.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.BLOCKS


C = _load_census()
BLOCKS = _load_blocks()

# An id no INF on disk claims, with the reason it is nonetheless correct.
# Every entry here is a claim this port makes about the hardware, so each one
# has to say which bench proved it.  An id that is here without a reason, or
# whose reason has stopped being true, is a defect - that is the whole point
# of the list being explicit rather than a count.
KNOWN_GAPS = {
    "QCOM24A5": (
        "UFS0.  In-box `storufs.inf` (Provider=%Microsoft%, "
        "Class=SCSIAdapter) claims it as `UfsQualcomm8996Install`.  It is "
        "*in* that sweep, so this entry only fires when the sweep omits the "
        "in-box tree."
    ),
    "QCOM2466": (
        "SDC2.  In-box `sdbus.inf` (Provider=%Msft%, Class=SDHost) claims it "
        "as `SDHostQualcomm8974Std`.  Same condition as QCOM24A5."
    ),
    "QCOM24BF": (
        "SDC1.  In-box `sdbus.inf`, `SDHostQualcomm8994Std`.  Same condition."
    ),
    "QCOM0A8B": (
        "URS0.  Claimed by NO INF in 712 on disk, and it binds anyway: the "
        "node's `_CID` is `PNP0CA1`, which is what in-box `urssynopsys.inf` "
        "claims.  The BSP is silent because the generic class driver (also "
        "the SD/USB role-switch driver) is not a vendor redistributable.  "
        "This is the case that shows a vendor-BSP absence is not evidence."
    ),
}


def acpi_claims(trees: list[str]) -> tuple[dict, dict]:
    """Sweep every INF in every tree; return (qcom ids, non-QCOM ACPI targets).

    Unlike the omission census this keeps the non-QCOM targets, because a
    `PNP0CA1` in a models line is exactly what binds a node whose `_HID`
    nothing claims.
    """
    qcom: collections.defaultdict = collections.defaultdict(set)
    other: collections.defaultdict = collections.defaultdict(set)
    files = []
    for tree in trees:
        for root, _dirs, names in os.walk(tree):
            for n in names:
                if n.lower().endswith(".inf"):
                    files.append(os.path.join(root, n))
    for path in files:
        text = C.read_inf(path)
        name = os.path.basename(path)
        targets = [t for ln in text.splitlines() for t in C.models_targets(ln)]
        for target in targets:
            if not target.upper().startswith("ACPI\\"):
                continue
            key = C.normalise(target)
            if key:
                qcom[key].add(name)
            else:
                t = target.upper()[5:].split("&")[0]
                if re.fullmatch(r"[A-Z]{3}[0-9A-F]{4}", t):
                    other[t].add(name)
    return qcom, other, len(files)


def peripheral_matrix(src, qcom, other):
    """One row per addressable peripheral: is hardware, node, driver, binding.

    The QCOM-HID sweep answers "is every id the table presents claimed".  It
    cannot answer "is every piece of hardware addressable", because an id that
    is *absent* is invisible to it.  So the matrix also carries the blocks the
    device tree has and the table does not - discovered here by looking for a
    node whose `_CRS` window *contains* the block base, the same containment
    test `acpi-hid-census.py --census` uses, rather than an equality an ACPI
    `_CRS` (often much coarser than the block it declares) would fail.
    """
    # Own-body per device (block minus nested Device subtrees), and the
    # attributes the matrix reads: _HID, _CID, _STA-presence, the first window.
    spans, stack, pend = [], [], None
    i, n = 0, len(src)
    D = re.compile(r"Device \((\w+)\)")
    while i < n:
        m = D.match(src, i)
        if m and (i == 0 or src[i - 1] in " \t\n{"):
            pend = (m.group(1), i)
            i = m.end()
            continue
        c = src[i]
        if c == "{":
            stack.append(pend)
            pend = None
        elif c == "}" and stack:
            top = stack.pop()
            if top:
                spans.append((top[0], top[1], i + 1))
        i += 1

    nodes = []  # (node, hid, cid, sta, base, length)
    seen = collections.Counter()
    for name, s, e in spans:
        blk = src[s:e]
        second = blk.find("Device (", 1)
        head = blk if second < 0 else blk[:second]
        hid = re.search(r'_HID,\s*"([^"]+)"', head)
        cid = re.search(r'_CID,\s*"([^"]+)"', head)
        sta = bool(re.search(r"\b(?:Name|Method) \(_STA\b", head))
        win = re.search(r"Memory32Fixed \(ReadWrite,\s*(0x[0-9A-Fa-f]+),"
                        r"\s*(0x[0-9A-Fa-f]+)", head)
        seen[name] += 1
        key = name if seen[name] == 1 else f"{name}#{seen[name]}"
        nodes.append((key, hid.group(1).upper() if hid else None,
                      cid.group(1).upper() if cid else None, sta,
                      int(win.group(1), 16) if win else None,
                      int(win.group(2), 16) if win else None))

    def covers(base):
        """The node whose window contains `base`, preferring the tightest."""
        best = None
        for node, hid, cid, sta, b, ln in nodes:
            if b is None or ln is None:
                continue
            if b <= base < b + max(ln, 1):
                if best is None or ln < best[5]:
                    best = (node, hid, cid, sta, b, ln)
        return best

    rows = []
    for label, base, _len, _dt, _why in BLOCKS:
        hit = covers(base)
        if hit is None:
            rows.append((label, base, None, None, "-", "-", "NO NODE"))
            continue
        node, hid, cid, sta, b, ln = hit
        why = "exact" if b == base else f"within 0x{b:08X}+0x{ln:X}"
        # driver status, reusing the same three outcomes the sweep produces
        if hid and hid in qcom:
            bind = "BOUND"
        elif cid and cid in other:
            bind = "CLASS"
        elif hid and hid in KNOWN_GAPS:
            bind = "KNOWN-GAP"
        elif hid:
            bind = "UNEXPLAINED"
        else:
            bind = "NO _HID"
        rows.append((label, base, node, hid, cid or "-", why, bind))
    return rows


# What each device-tree block's absence of an ACPI *Device node* means.
#
# `acpi-hid-census.py --blocks` lists the tree's blocks with a one-line
# rationale each, and read as a work list it over-states the gaps: two of the
# twelve describe hardware ACPI does not address with a `Device ()` at all, and
# two more name a bus the tree itself disables.  The matrix has to say which
# absence is a defect and which is the shape of the thing, or every run reads
# as six failures.  Each entry below is a claim about the hardware, so each
# carries the reason it is not a gap.
ABSENCE_OK = {
    "TSENS0": (
        "no Device node by design - the on-die sensors are the ACPI "
        "`ThermalZone (TZ0..TZ10)` objects (gauguin.asl:6252+), and "
        "`qcthermalmdm7280.inf`'s 27 ids bind those, not a `_CRS` node. The "
        "block itself is not Windows-addressable and has no driver."
    ),
    "TSENS1": (
        "the second sensing block; same as TSENS0, encoded in the same "
        "`ThermalZone` objects. See the tree: `tsens@c263000` and "
        "`tsens@c265000` (phandles 0x39/0x3a) both feed the `soc` zone."
    ),
    "SE1": "the tree disables this bus (`i2c@888000 status = \"disabled\"`) - no slave, nothing to bind.",
    "SE2": "the tree disables this bus (`i2c@980000 status = \"disabled\"`) - no slave, nothing to bind.",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--infs", action="append", required=True, metavar="DIR",
                    help="an INF tree to sweep; repeatable, and repeat it "
                         "with every tree you have or the answer is wrong")
    ap.add_argument("--asl", default="tools/acpi/gauguin.asl")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--matrix", action="store_true",
                    help="print the per-peripheral drivability matrix: every "
                         "device-tree block against the node that describes "
                         "it and the driver that claims that node's id")
    a = ap.parse_args(argv)

    asl = open(a.asl, encoding="utf-8", errors="replace").read()
    src = C.strip_comments(asl, "//")

    # The ASL's own namespace, and which node each id belongs to.
    node_of: dict[str, str] = {}   # _HID value -> node
    node_cid: dict[str, str] = {}  # node -> its _CID value(s), non-QCOM only
    dev = None
    for line in src.splitlines():
        m = re.match(r"\s*Device \((\w+)\)", line)
        if m:
            dev = m.group(1)
        m = re.search(r'_HID,\s*"([^"]+)"', line)
        if m and dev:
            node_of.setdefault(m.group(1).upper(), dev)
        m = re.search(r'_CID,\s*"([^"]+)"', line)
        if m and dev and not re.fullmatch(r"QCOM[0-9A-F]{4}", m.group(1).upper()):
            node_cid[dev] = m.group(1).upper()

    hid_ids = {x for x in node_of if re.fullmatch(r"QCOM[0-9A-F]{4}", x)}

    qcom, other, nfiles = acpi_claims(a.infs)

    if a.matrix:
        print(f"gauguin's device-tree blocks against the ACPI node that "
              f"describes each,\nand the driver that claims that node "
              f"({nfiles} INF(s) swept):\n")
        w = max(len(l) for l, *_ in BLOCKS)
        print(f"  {'block':<{w}}  {'node':<8} {'_HID':<12} {'_CID':<10} "
              f"{'bind':<11} window")
        bad = []
        for label, base, node, hid, cid, why, bind in peripheral_matrix(
                src, qcom, other):
            note = ""
            if bind == "NO NODE" and label in ABSENCE_OK:
                bind = "NO NODE*"
                note = ABSENCE_OK[label].split(" - ")[0].split(";")[0]
            print(f"  {label:<{w}}  {str(node):<8} {str(hid or '-'):<12} "
                  f"{cid:<10} {bind:<11} {why}")
            if bind in ("NO NODE", "UNEXPLAINED"):
                bad.append(label)
        print()
        print("  NO NODE      - the block has hardware and no ACPI node, so "
              "Windows has no device to bind and nothing in Device Manager.")
        print("  NO NODE*     - the absence is the shape of the hardware, not "
              "a gap:")
        for label, _b, node, *_rest in peripheral_matrix(src, qcom, other):
            if node is None and label in ABSENCE_OK:
                print(f"                   {label}: {ABSENCE_OK[label]}")
        print("  UNEXPLAINED  - a node exists and no swept INF claims its id.")
        if bad:
            print(f"\nFAIL: {len(bad)} block(s) undrivable as tabled: "
                  + ", ".join(bad))
            return 1
        print("\nPASS: every block either has a bound node, or its absence is "
              "recorded with a reason.")
        return 0

    rows = []
    for i in sorted(hid_ids):
        if i in qcom:
            rows.append(("BOUND", i, node_of[i], sorted(qcom[i])[0]))
        elif node_cid.get(node_of[i]) in other:
            rows.append(("CLASS", i, node_of[i],
                         f"_CID {node_cid[node_of[i]]} <- "
                         f"{sorted(other[node_cid[node_of[i]]])[0]}"))
        elif i in KNOWN_GAPS:
            rows.append(("KNOWN-GAP", i, node_of[i], KNOWN_GAPS[i].split(".")[0]))
        else:
            rows.append(("UNEXPLAINED", i, node_of[i], "no INF claims id or _CID"))

    if not a.quiet:
        print(f"{nfiles} .inf file(s) in {len(a.infs)} tree(s); swept "
              f"{len(qcom)} ACPI\\QCOM ids and {len(other)} non-QCOM ACPI ids")
        print(f"{len(hid_ids)} QCOM id(s) presented by {a.asl}\n")
        w = max(len(r[1]) for r in rows)
        for kind, i, node, why in rows:
            print(f"  {kind:12s} {i}  {node:6s} {why}")

    bad = [r for r in rows if r[0] == "UNEXPLAINED"]
    counts = collections.Counter(r[0] for r in rows)
    print("\n" + "  ".join(f"{k}={counts[k]}" for k in
                           ("BOUND", "CLASS", "KNOWN-GAP", "UNEXPLAINED")))
    if bad:
        print(f"\nFAIL: {len(bad)} presented id(s) neither claimed nor "
              f"recorded: " + " ".join(f"{r[1]}({r[2]})" for r in bad))
        return 1
    print("PASS: every presented QCOM id is bound, class-matched, or "
          "recorded with a reason.")
    return 0


if __name__ == "__main__":
    sys.exit(main())