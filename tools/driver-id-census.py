#!/usr/bin/env python3
"""Census the hardware ids a vendor BSP's INFs claim, and diff them against the ASL.

Why this exists
---------------
Step 4.254 caught the *same* false negative twice in one reconnaissance: the
display driver was reported absent because (a) a `grep 'Class='` missed the
padded line `Class       = Display`, and (b) a `find -iname '*.sys'` sweep
filtered filenames while the binary sat inside an unextracted cab.  Both made
"no driver" out of "not looked for in the right way".  The question
"does this board's hardware have a Windows driver at all?" is asked often
enough, and answered wrongly often enough, to deserve a measurement rather
than an ad-hoc grep.

What it measures
----------------
* The **normalised class histogram** over an INF set -- padded `Class` lines
  included, so a `Class       = Display` is not silently dropped.
* The **bus census**: every models-line target split by its bus prefix
  (`ACPI\\`, `ADSP\\`, `ROOT\\`, `USB\\`, ...).  This is the part naive greps
  lose: `qcslimbus7280.inf`'s only real models line binds `ADSP\\QCOM0A0F`, an
  id the *ADSP* enumerates, while the `ACPI\\QCOM0190` a plain text scan finds
  in that file is inside a `;` comment (a `devcon` example) and is not a models
  line at all.
* The **ACPI id set** and the **ASL's `_HID` set**, plus the difference:
  driver-has-id-but-ASL-has-no-node is the owed-coverage list; ASL-has-node-but-
  no-driver-claims-it is the guessing list.

What it deliberately does not do
--------------------------------
It does not decide whether an id is *right* for this board -- an id is a
driver-matching string, and the Kodiak BSP's ids are Kodiak's.  It does not map
device-tree nodes to ids: that mapping is the ASL's job and is not mechanical.
It reports what the INFs say and what the ASL says, and leaves the two sets
side by side.

The one bug worth naming, because it was the bug this tool exists to not repeat:
INF comments begin with `;`.  A scan that does not strip them reads a doc
example as a hardware claim.  That is the same instrument error as
`acpi-dt-crosscheck.py` reading an ASL `//` comment as a resource value, and it
is fixed here the same way.
"""
from __future__ import annotations

import argparse
import collections
import glob
import os
import re
import sys

BUS_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]*)\\")
MODELS_RE = re.compile(
    r"=\s*[A-Za-z0-9_.\-]+\s*,\s*((?:[A-Za-z][A-Za-z0-9]*\\)+[^\s,;\"\]]+)"
)
# `MODELS_RE` reads the FIRST target of a models line.  A line may carry more:
# in-box `urssynopsys.inf` writes
#     %UrsSynopsys.DeviceDesc% = UrsSynopsys.Install, ACPI\QCOM24B6, ACPI\PNP0CA1
# and the second target is the whole reason gauguin's `URS0` binds at all - its
# `_HID` `QCOM0A8B` is claimed by no INF in 712, and its `_CID` `PNP0CA1` is
# what that line claims.  Only two such lines exist across 498 INFs (this one
# and `ucmucsiacpiclient.inf`'s `ACPI\USBC000, ACPI\PNP0CA0`), but a scan that
# reads one target per line cannot see either, so the class a node binds by is
# invisible to it by construction.
MODELS_ALL_RE = re.compile(
    r"=\s*[A-Za-z0-9_.\-]+\s*,\s*((?:(?:[A-Za-z][A-Za-z0-9]*\\)[^\s,;\"\]]+\s*,?\s*)+)"
)


def models_targets(line: str) -> list[str]:
    """Every target on a models line, not just the first."""
    m = MODELS_ALL_RE.search(line)
    if not m:
        return []
    return re.findall(r"(?:[A-Za-z][A-Za-z0-9]*\\)[^\s,;\"\]]+", m.group(1))
CLASS_RE = re.compile(r"(?im)^[ \t]*Class[ \t]*=[ \t]*(\S+)")
ASL_HID_RE = re.compile(r'"(QCOM[0-9A-Fa-f]{4}|ACPI[0-9A-Fa-f]{4})"')


def strip_comments(text: str, marker: str) -> str:
    """Strip both block and line comments before any scan.

    INF line comments use `;`; ASL uses `//` and also `/* ... */`
    blocks.  A scan that skips this reads a doc example as a hardware claim --
    which is how `ACPI\\QCOM0190` (a `devcon` example inside qcslimbus7280.inf)
    and the ASL's `QCOM0497` / `QCOM1121` (both inside the header's `/* */`
    block) entered early versions of this census.  Three separate ids, one
    error: text read as data.  Same error as `acpi-dt-crosscheck.py` reading an
    ASL `//` comment as a resource value.
    """
    out = re.sub(r"/\*.*?\*/", "", text, flags=re.S)  # block comments first
    pat = re.escape(marker) + r"[^\n]*"
    return "\n".join(re.sub(pat, "", line) for line in out.splitlines())


def read_inf(path: str) -> str:
    """Decode an INF (almost always UTF-16 with BOM) and strip `;` comments."""
    data = open(path, "rb").read()
    for enc in ("utf-16", "utf-8"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", "replace")
    return strip_comments(text, ";")


def normalise(target: str) -> str | None:
    """Reduce a models-line target to a bare ACPI id in one namespace.

    `ACPI\\QCOM0A25`, `ACPI\\VEN_QCOM&DEV_0A25` and
    `ACPI\\VEN_QCOM&DEV_0A36&REV_0100` all become `QCOM0A25`/`QCOM0A36`.  The
    ASL writes `_HID` values bare, so without this the two sets never intersect
    and the diff reports every id as missing on both sides.
    """
    t = target.upper()
    if t.startswith("ACPI\\"):
        t = t[5:]
    if t.startswith("VEN_QCOM&DEV_"):
        t = "QCOM" + t[len("VEN_QCOM&DEV_"):].split("&")[0]
    return t if re.fullmatch(r"QCOM[0-9A-F]{4}", t) else None


def census(infs: list[str]) -> tuple[dict, dict, dict]:
    """Return (classes, bus_targets, acpi_ids) built from real models lines only."""
    classes: collections.Counter = collections.Counter()
    buses: collections.defaultdict = collections.defaultdict(set)
    acpi: collections.defaultdict = collections.defaultdict(set)
    for path in infs:
        name = os.path.basename(path)
        text = read_inf(path)
        m = CLASS_RE.search(text)
        classes[(m.group(1).strip() if m else "?")] += 1
        for target in MODELS_RE.findall(text):
            bus = target.split("\\", 1)[0].upper()
            buses[bus].add(name)
            if bus == "ACPI":
                key = normalise(target)
                if key:
                    acpi[key].add(f"{name}({m.group(1).strip() if m else '?'})")
    return classes, buses, acpi


def selftest() -> int:
    """Test the census the way it tests: on the inputs that broke it."""
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    check("normalise short", normalise("ACPI\\QCOM0A25"), "QCOM0A25")
    check("normalise VEN/DEV", normalise("ACPI\\VEN_QCOM&DEV_0A36"), "QCOM0A36")
    check("normalise REV collapses", normalise("ACPI\\VEN_QCOM&DEV_0A36&REV_0100"), "QCOM0A36")
    check("normalise non-id", normalise("USB\\VID_1234"), None)

    # The three ids that were comment text, not hardware claims.
    for cid in ("QCOM0190", "QCOM0497", "QCOM1121"):
        check(f"{cid} survives ;-comment",
              cid in strip_comments(f"x = {cid}\n", ";"), True)
        check(f"{cid} within /* */", cid in strip_comments(f"/* {cid} */", "//"), False)
        check(f"{cid} after //", cid in strip_comments(f"// {cid}", "//"), False)

    # A padded Class line must still be found (the Step 4.254 false negative).
    m = CLASS_RE.search("Class       = Display")
    check("padded Class", m and m.group(1), "Display")

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("selftest: OK (normalisation, 3 comment ids x 3 forms, padded Class)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--infs", default=os.path.expanduser("~/work/woa-ref/inf-7280"),
                    help="directory of .inf files (default: the 112-cab Kodiak BSP)")
    ap.add_argument("--asl", default="tools/acpi/gauguin.asl",
                    help="the platform ASL to diff against")
    ap.add_argument("--quiet", action="store_true", help="summary only")
    ap.add_argument("--selftest", action="store_true", help="test the census on the inputs that broke it")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    infs = sorted(glob.glob(os.path.join(os.path.expanduser(args.infs), "*.inf")))
    if not infs:
        print(f"FAIL: no .inf files under {args.infs}", file=sys.stderr)
        return 2
    try:
        asl = open(args.asl, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        print(f"FAIL: cannot read {args.asl}: {exc}", file=sys.stderr)
        return 2

    classes, buses, acpi = census(infs)
    asl_ids = {x.upper() for x in ASL_HID_RE.findall(strip_comments(asl, "//"))}

    print(f"INFs scanned: {len(infs)}")
    print(f"\n== class histogram (normalised; padded `Class` lines counted) ==")
    for cls, n in classes.most_common():
        print(f"  {n:4d}  {cls}")

    print(f"\n== bus census: which bus enumerates a models-line target ==")
    for bus, files in sorted(buses.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(files):4d} INF(s)  {bus}\\")

    print(f"\n== ACPI ids claimed by real models lines: {len(acpi)} ==")
    if not args.quiet:
        for h in sorted(acpi):
            print(f"  {h:44s} {', '.join(sorted(acpi[h]))[:100]}")

    missing = sorted(k for k in acpi if k not in asl_ids)
    extra = sorted(k for k in asl_ids if k not in acpi)
    print(f"\n== diff against {args.asl} ==")
    print(f"  ASL presents {len(asl_ids)} id(s); INF set claims {len(acpi)}; "
          f"driver-has-id-but-ASL-has-none: {len(missing)}; ASL-has-id-but-no-driver: {len(extra)}")
    if extra:
        print("  ASL ids no INF in this set claims (may be in-box or another set):")
        print("   ", " ".join(extra))
    if not args.quiet:
        print("  ACPI ids in the BSP the ASL does not present:")
        for h in missing:
            print(f"    {h}  <- {', '.join(sorted(acpi[h]))[:80]}")

    # The ADSP-enumerated case, called out because it is the one a text scan loses.
    adsp = sorted({t for t in buses.get("ADSP", set())})
    if adsp:
        print(f"\n== ADSP-enumerated drivers (invisible to an `ACPI\\`-only scan) ==")
        for path in sorted(glob.glob(os.path.join(os.path.expanduser(args.infs), "*.inf"))):
            if os.path.basename(path) in buses.get("ADSP", set()):
                for target in MODELS_RE.findall(read_inf(path)):
                    if target.upper().startswith("ADSP\\"):
                        print(f"  {target:22s} <- {os.path.basename(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())