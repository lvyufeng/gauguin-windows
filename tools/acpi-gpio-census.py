#!/usr/bin/env python3
"""Measure what the reference tables give the buttons node, and its controller.

P3 item 4 is `ButtonsDxe` plus a way to choose boot entries, and the node the
driver binds is `BTNS` at the end of `tools/acpi/gauguin.asl`: `_HID` `ACPI0011`,
a three-descriptor `_CRS` of `GpioInt`s that all name `\\_SB.PM01`, and the Generic
Buttons `_DSD`. The question the record asked of it was whether the controller
those descriptors name can resolve, and the first answer was that it cannot -
`PM01`'s `_CRS` carries one shared level interrupt on `0x201` and no pin range, so
the descriptors had, it said, no controller to bind through.

That answer was an argument from the ACPI resource model and not a measurement,
and this tool is the measurement. It reads every table in the `Silicium-ACPI` tree
and reports, per table, what `BTNS` declares, which controller its `GpioInt`
descriptors name, and what `PM01._CRS` holds. What that showed at Step 4.215, over
66 tables: **no table in the corpus declares a `GpioIo` or a `GpioInt` in
`PM01._CRS`** - all 22 that declare a `PM01._CRS` at all hold the same shared level
interrupt instead, 21 of them one and Kailua two - so an empty pin space is the
reference shape rather than a gap in this table, and the characterisation above is
withdrawn. A number a reader cannot ask again from the repository is not a
measurement, which is why this is here and not in `/tmp`.

Three readings of this corpus were wrong before the tool was right, and all three
are recorded at the site of the mistake rather than here, because each is a way for
a negative result to come out of a parser bug rather than out of the tables: a
`DSDT.aml`-only glob (58 of 66), a `Method (_CRS)`-only search (`gts8p`, `r0q`), and
a `ResourceTemplate` search started in the block it opens. Each printed something
that read as the answer the caller was looking for. The totals this tool now
produces agree with the independent count that was taken by hand.

The unit is the node, and the two nodes are reported together rather than as two
totals: a table can carry a `BTNS` and no `PM01` (then its descriptors name
something else, or `PM01` is in a `DSDT` the corpus does not hold - both Samsung
rows here are SSDTs and this is the likelier reading), and a table can carry a
`PM01` and no `BTNS`. Neither count alone answers the question, because the
question is about the pairing - so the corpus counts at the end are over tables,
and a table is in the interesting set only when it has both.

    python3 tools/acpi-gpio-census.py             # the pairing table
    python3 tools/acpi-gpio-census.py --summary   # only the totals
    python3 tools/acpi-gpio-census.py --tree DIR  # a different corpus
"""
import argparse
import glob
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TREE = os.path.join(REPO, "work/uefi/Mu-Silicium/Silicium-ACPI")
DEFAULT_CACHE = "/tmp/acpi-hid-census"

# The resource descriptors a `_CRS` template can carry that matter here. `GpioIo`
# and `GpioInt` are the two that declare a pin, and their absence from every
# `PM01._CRS` in the corpus is the finding; `Interrupt` and `Memory32Fixed` are
# listed so that a template reads as what it is rather than as "not gpio".
HAVE_GUID = re.compile(r"^[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}$")


def disassemble(aml, cache, tree=None):
    """(dsl_path or None) - `iasl -d`, cached, and the cache is keyed on the
    tree and the mtime.

    `tools/acpi-hid-census.py` states why the second half of that key matters and
    the reason is not repeated here in full: the one table in this tree that
    changes is our own, so a cache keyed on the path alone serves the corpus a
    disassembly of `gauguin/DSDT.aml` from an earlier revision while looking
    exactly like a reading.

    The cache name is `--tree`-relative, so a second corpus with the same layout
    lands beside the first rather than on top of it.
    """
    rel = os.path.relpath(aml, tree or DEFAULT_TREE)
    name = rel.replace("/", "-").replace(".aml", "")
    dsl = os.path.join(cache, name + ".dsl")
    if not os.path.exists(dsl) or os.path.getmtime(dsl) < os.path.getmtime(aml):
        os.makedirs(cache, exist_ok=True)
        subprocess.run(["iasl", "-d", "-p", os.path.join(cache, name), aml],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dsl if os.path.exists(dsl) else None


def block(text, start):
    """The balanced-brace block whose opening brace is the first one after
    `start`.

    The one way this goes wrong is the way the first version of this measurement
    went wrong, so it is stated here rather than left to be rediscovered: a
    `re.search` run over an *extracted* block returns offsets into that block, and
    using one of them to index the enclosing text reads the wrong region and
    returns an empty template rather than an error - which then reads as "this
    table declares nothing", i.e. as the answer the caller was looking for.
    """
    i = text.index("{", start)
    depth, j = 0, i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1
    return text[i:]


def device(text, name):
    """The body of `Device (name)`, or None."""
    m = re.search(r"Device\s*\(\s*%s\s*\)" % re.escape(name), text)
    return block(text, m.start()) if m else None


def crs_template(body):
    """The resource template a device's `_CRS` carries, or one of the strings
    `'no _CRS'` / `'no template'` so a caller can tell the two absences apart.

    `_CRS` is a `Name` in one table and a `Method` in the next, and both spellings
    are ordinary ACPI - a fixed `_CRS` has no reason to be a method at all. Reading
    only the method form was this tool's second wrong answer, and it failed in the
    direction the first one did: `gts8p` and `r0q` declare three real `GpioInt`
    descriptors under `Name (_CRS, ResourceTemplate () …)`, and the row printed
    `n 0` for both - while printing `PM01` in the controller column from the same
    descriptors, which is the only reason the row did not read as a clean negative.
    Both branches are therefore taken below, and the descriptor count belongs to
    the text this returns.
    """
    if body is None:
        return None
    c = re.search(r"(?:Method|Name)\s*\(\s*_CRS\b", body)
    if not c:
        return "no _CRS"
    # The search starts at the `_CRS` declaration in the *outer* text, not in the
    # block starting there. That distinction is the third wrong answer this tool
    # gave and it is worth the sentence: for `Name (_CRS, ResourceTemplate () …)`
    # the first brace after the declaration is the template's own, so the block is
    # the template body - and a `ResourceTemplate ()` search inside it finds
    # nothing, because the words are just before the brace that opened it. `gts8p`
    # and `r0q` printed `no template` for that reason while their descriptors sat
    # three lines away.
    r = re.search(r"ResourceTemplate\s*\(\)", body[c.start():])
    if not r:
        return "no template"
    return block(body, c.start() + r.start())


def sources_named(text):
    """The device names a GpioInt/GpioIo descriptor in this block points at, as
    written - `PM01` for `"\\\\_SB.PM01"`, and `GIO0` for cepheus's fourth."""
    return sorted(set(re.findall(r'"\\\\?_SB\.([A-Z0-9_]+)"', text)))


def pins(tpl):
    """The pin numbers under the `GpioInt`/`GpioIo` descriptors, in order.

    These are the numbers the finding is about. They are indices into a pin space
    the same table is supposed to declare, so a table whose controller declares
    none and whose descriptors number three has an unresolvable pair - which is
    what gauguin's row is, and the reason the numbers are printed beside it rather
    than left to be read out of the ASL.
    """
    if not tpl or tpl.startswith("no "):
        return []
    out = []
    for m in re.finditer(r"\bGpio(?:Int|Io)\b", tpl):
        seg = tpl[m.start():]
        try:
            b = block(seg, seg.index("{"))
        except ValueError:
            continue
        vals = re.findall(r"0x([0-9A-Fa-f]+)", b)
        out.append(vals[0].upper() if vals else "?")
    return out


def resources(tpl):
    """[(name, count)] for the descriptor names present in a template."""
    if not tpl or tpl.startswith("no "):
        return []
    out = []
    for n in ("GpioIo", "GpioInt", "Interrupt", "Memory32Fixed", "QwordMemory",
              "FixedIO", "DMA", "WordBusNumber"):
        c = len(re.findall(r"\b%s\b" % n, tpl))
        if c:
            out.append((n, c))
    return out


def members(body):
    """The named members a device declares, in the order ACPI's own list puts
    them, so two tables' memberships compare as strings."""
    order = ("_HID", "_CID", "_UID", "_SUB", "_STA", "_CRS", "_DSD", "_DSM",
             "_AEI", "_DEP")
    return [m for m in order if re.search(r"\b%s\b" % m, body)]


def tables(tree):
    """Every table in the corpus, as (label, aml_path).

    `DSDT.aml` *or* `SSDT.aml`, and the choice is not cosmetic: eight of the
    corpus's forty platform tables ship under the second name, and a glob for the
    first alone silently reads 32 of 40 - `citrus`, `ingres`, `lisa`, `pipa`,
    `spes` and three others, none of them any less a reference than the rest. The
    first run of this tool did exactly that (58 tables against the corpus's 66) and
    the count is stated here so that a later reading of it is not mistaken for the
    corpus having shrunk.
    """
    amls = sorted(glob.glob(tree + "/Platforms/*/*/DSDT.aml")
                  + glob.glob(tree + "/Platforms/*/*/SSDT.aml")
                  + glob.glob(tree + "/Silicon/Qualcomm/*/DSDT*.aml"))
    for aml in amls:
        yield os.path.relpath(aml, tree).replace(".aml", ""), aml


def pon_indices(body):
    """PM01's `_DSM` function 1 - the PON's own kpdpwr and resin **pin indices**,
    or None when the device declares no such answer.

    This is the authority the buttons descriptors are read against, and it is the
    reason the first and third of gauguin's three pins are not reasoned values:
    the controller itself states which pins the power and reset keys are on, in
    the same pin space the `_CRS` descriptors index. Function 0 returning
    `Buffer (One) {0x03}` is the GPIO Controller revision and carries no pins; only
    function 1 does.

    The shape varies enough between tables that a single regex is not worth
    trusting - gauguin writes `If ((ToInteger (Arg2) == One))` with a plain
    `Package (0x02) { Zero, One }`, while vili and most of the corpus route it
    through a compiler-emitted `_T_1` temporary and an `ElseIf`. So this takes the
    `Package` that follows whichever spelling of the function-1 test the table
    uses, and returns its two integers.
    """
    if body is None:
        return None
    d = re.search(r"Method\s*\(\s*_DSM\b", body)
    if not d:
        return None
    db = block(body, d.start())
    for m in re.finditer(r"(?:ToInteger\s*\(\s*Arg2\s*\)|_T_\w+)\s*==\s*"
                         r"(?:One|0x0*1)\b", db):
        seg = db[m.end():]
        p = re.search(r"Package\s*\(\s*0x0*2\s*\)", seg)
        if not p:
            continue
        pk = block(seg, p.start())
        nums = [t for t in re.findall(r"\b(Zero|One|0x[0-9A-Fa-f]+|\d+)\b", pk)
                if t not in ("0x02", "2")]
        if len(nums) >= 2:
            return [tv(v) for v in nums[:2]]
    return None


def tv(tok):
    """`Zero`/`One`/hex/decimal as an int, so two spellings of one pin compare
    equal."""
    if tok == "Zero":
        return 0
    if tok == "One":
        return 1
    return int(tok, 16) if tok.lower().startswith("0x") else int(tok)


def describe(row):
    """What PM01's `_CRS` is, in words that do not let two different answers look
    alike.

    There are four states and only one of them is the finding, so each gets its own
    spelling. No `PM01` at all and a `PM01` with no `_CRS` are absences of the
    controller's resource declaration; a `_CRS` with no template and a template with
    no descriptors are different again - the last is the one that would say "PM01
    declares a pin space and it is empty", and it does not occur in this corpus. A
    row printing `(empty template)` for any of the four would read as that last one.
    """
    if not row["pm01"]:
        return "no PM01 device"
    if row["pm_state"] in ("no _CRS", "no template"):
        return row["pm_state"]
    if not row["pm_res"]:
        return "template with no descriptors"
    return " ".join("%s=%d" % (n, c) for n, c in row["pm_res"])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tree", default=DEFAULT_TREE,
                    help="the ACPI corpus root (default: the build tree's)")
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--summary", action="store_true",
                    help="totals only, no per-table rows")
    args = ap.parse_args()

    if not os.path.isdir(args.cache):
        os.makedirs(args.cache, exist_ok=True)

    rows = []
    for label, aml in tables(args.tree):
        dsl = disassemble(aml, args.cache, args.tree)
        if dsl is None:
            continue
        text = open(dsl, encoding="utf-8", errors="replace").read()
        btns, pm01 = device(text, "BTNS"), device(text, "PM01")
        b_tpl = crs_template(btns) if btns else None
        p_tpl = crs_template(pm01) if pm01 else None
        rows.append({
            "table": label,
            "btns": bool(btns),
            "members": ",".join(members(btns)) if btns else "",
            "srcs": ",".join(sources_named(btns)) if btns else "",
            "ndsc": sum(c for n, c in resources(b_tpl) if n.startswith("Gpio"))
                    if isinstance(b_tpl, str) and not b_tpl.startswith("no") else 0,
            "pins": ",".join(pins(b_tpl)),
            "pon": pon_indices(pm01),
            "pm01": pm01 is not None,
            "pm_res": resources(p_tpl) if isinstance(p_tpl, str) else None,
            "pm_state": p_tpl if not isinstance(p_tpl, str) or (
                p_tpl.startswith("no")) else "ok",
        })

    if not args.summary:
        print("%-34s %-5s %-18s %-11s %-16s %-3s %s"
              % ("table", "BTNS", "members", "controller", "pins", "n",
                 "PM01._CRS"))
        for r in rows:
            print("%-34s %-5s %-18s %-11s %-16s %-3d %s"
                  % (r["table"][:34], "yes" if r["btns"] else "-",
                     r["members"], r["srcs"], r["pins"], r["ndsc"],
                     describe(r)))

    n = len(rows)
    with_btns = [r for r in rows if r["btns"]]
    with_pm = [r for r in rows if r["pm01"]]
    pair = [r for r in with_btns if r["pm01"]]
    three = [r for r in with_btns if r["ndsc"] == 3]
    pm_crs = [r for r in with_pm if r["pm_state"] not in ("no _CRS", "no template")]
    gpio_in_pm = [r for r in pm_crs
                  if any(nm in ("GpioIo", "GpioInt") for nm, _ in r["pm_res"])]
    srcs = {}
    for r in with_btns:
        for s in (r["srcs"].split(",") if r["srcs"] else ["(none)"]):
            srcs[s] = srcs.get(s, 0) + 1

    print()
    print("tables read                              %d" % n)
    print("carry a BTNS                             %d" % len(with_btns))
    print("  of those, with a GpioInt descriptor    %d"
          % len([r for r in with_btns if r["ndsc"] > 0]))
    print("  of those, the three-descriptor shape   %d" % len(three))
    print("carry a PM01                             %d" % len(with_pm))
    print("  of those, declaring a _CRS             %d" % len(pm_crs))
    print("  of those, declaring no _CRS            %d" % (len(with_pm) - len(pm_crs)))
    print("carry both a BTNS and a PM01             %d" % len(pair))
    print("controllers the BTNS descriptors name:")
    for s, c in sorted(srcs.items(), key=lambda kv: -kv[1]):
        print("  %-10s %d" % (s, c))
    print("PM01._CRS carrying a GpioIo or GpioInt: %d of %d"
          % (len(gpio_in_pm), len(pm_crs)))
    for r in gpio_in_pm:
        print("  %s -> %s" % (r["table"], r["pm_res"]))
    if not gpio_in_pm:
        print("  (no table in this corpus declares a pin range in PM01._CRS. What")
        print("   the %d declaring ones carry is the interrupt below, and it is the"
              % len(pm_crs))
        print("   same one in every table but Kailua's, which carries two.)")

    # The PON comparison. This is the part that turns the three descriptor numbers
    # from a claim about gauguin into a claim about the corpus: PM01's `_DSM`
    # function 1 names the pins its own power and reset keys are on, so where a
    # table has both nodes the first and third descriptors can be *checked* rather
    # than read. What the corpus says about the middle one is the last block.
    have = [r for r in pair if r["pon"] is not None and r["ndsc"] >= 3]
    longer = [r for r in pair if r["pon"] is not None and r["ndsc"] > 3]
    ok, bad = [], []
    for r in have:
        p = [int(x, 16) for x in r["pins"].split(",")]
        # Cells 0 and 2, not first and last: caymanslm carries five descriptors and
        # cepheus four, so the last cell is an extra pin rather than the resin key -
        # and reading it as one would report those two tables as disagreeing with
        # their own PON when their first and third cells agree with it exactly.
        (ok if (p[0], p[2]) == tuple(r["pon"]) else bad).append((r["table"], p, r["pon"]))
    print()
    print("tables with both nodes, three or more descriptors, and a PON answer: %d"
          % len(have))
    print("  cells 0 and 2 == _DSM function 1:                  %d" % len(ok))
    print("  and differ:                                        %d" % len(bad))
    for t, p, pon in bad:
        print("    %s  descriptors %s  PON %s" % (t, p, pon))
    mid = {}
    for r in pair:
        if r["ndsc"] < 2:
            continue
        p = r["pins"].split(",")[1]
        mid.setdefault(p, []).append(r["table"])
    print("  the middle descriptor's pin, by table:")
    for k in sorted(mid, key=lambda k: -len(mid[k])):
        print("    0x%-6s %2d  %s" % (k, len(mid[k]),
                                      ", ".join(sorted(x.split("/")[-2]
                                                       for x in mid[k]))))
    print("  tables where that pin is one the PON also names: %d"
          % len([r for r in pair if r["pon"] and r["ndsc"] >= 2
                 and int(r["pins"].split(",")[1], 16) in r["pon"]]))
    if longer:
        print("  (%s carry more than three descriptors, and are in the count"
              % ", ".join("%s %s" % (r["table"].split("/")[-2], r["pins"])
                          for r in longer))
        print("   above on their cells 0 and 2, as the file's own claim is stated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
