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


C = _load_census()

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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--infs", action="append", required=True, metavar="DIR",
                    help="an INF tree to sweep; repeatable, and repeat it "
                         "with every tree you have or the answer is wrong")
    ap.add_argument("--asl", default="tools/acpi/gauguin.asl")
    ap.add_argument("--quiet", action="store_true")
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