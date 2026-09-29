#!/usr/bin/env python3
"""Run the ASL under ACPICA and check that what it says is what it does.

`tools/acpi/gauguin.asl` is verified two ways before a step is committed: `iasl`
must compile it with `0 Errors`, and the generated twin must be `cmp`-identical
to the source. Neither of those says the table **loads**, and neither says a
method **runs**. `iasl -tc` proves syntax and namespace construction; a table
can compile and still fail at load with an unresolved reference, and a `_CRS`
can compile and still evaluate to a buffer that is not the resource it was
written as.

`acpiexec` - ACPICA's AML execution utility, shipped beside the `iasl` this
repository already uses - does both, offline, with no fourth root and nothing to
simulate. This tool drives it and turns the output into the three measurements
that matter:

  1. **load** - objects, devices, methods, regions, and the namespace size, from
     `acpiexec -b quit`. The tool tests the `successfully acquired and loaded`
     line rather than the exit status, which `acpiexec` does not set usefully.
  2. **`_STA`** - every top-level device's status method, run individually, so
     the report distinguishes `AE_NOT_FOUND` (the node has no `_STA`, which is
     legal and is most of this file) from a method that raises. The number that
     is worth watching is not how many answer - it is whether the file has
     drifted into *mixing* the two idioms, a device with a stub `_STA` left
     behind by a rewrite.
  3. **`_CRS`** - every device's resource body - a `Method` on 26 of this
     file's devices and a `Name` holding the template on 4, both of which
     `execute` evaluates - decoded back into windows, interrupts and serial-bus
     descriptors, compared against what the source declares. This is the round trip that a byte-level decode of the AML
     performs and that no amount of reading the source can:

         device tree cell -> iasl -> AML -> ACPICA decode

     and it is why the tool exists. The comparison is exact: a `Memory32Fixed`
     that survives as the wrong length, or an interrupt whose GSI drifted by the
     SPI+32 rule, is a mismatch here and invisible everywhere else.

Modules the ASL carries are parsed off `iasl -d`'s disassembly rather than the
extended-format `acpiexec` printer, so all 48 devices are read the same way and
the counts do not depend on how many descriptors fit on a line.

Four things are deliberately *not* checked, because this tool cannot:

  - `_DSM`. It is four-argument by definition and `execute` passes none, so
    every `_DSM` in this file fails with `AE_AML_UNINITIALIZED_ARG`. That is a
    limit of the driver, not a defect in the table, and the tool says so rather
    than reporting it as a finding.
  - Whether a loaded device **binds**. A load is not a bind; `_HID` values are
    unexercised until a PnP manager sees them, which needs the phone.
  - Whether a GSI is one a real GIC and ITS accept. ACPICA has no GIC.
  - Operation Regions. They are not evaluated unless a method reads them.

Usage:
    tools/acpi-runtime-check.py                 # the ASL and its twin
    tools/acpi-runtime-check.py --asl FILE      # some other table
    tools/acpi-runtime-check.py --keep          # leave the scratch directory
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ASL = os.path.join(REPO, "tools", "acpi", "gauguin.asl")

# `acpiexec`'s batch string is capped hard at 1,023 characters and refuses the
# whole line above it, so every command list is chunked below this. 980 leaves
# room for the longest single `execute` command.
BATCH_LIMIT = 980

# Resource descriptor tags, as they appear in an evaluated buffer.
MEMORY32FIXED = 0x86
EXTENDED_INTERRUPT = 0x89
EXTENDED_GPIO = 0x8C
I2C_SERIAL_BUS = 0x8E
END_TAG = 0x79


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def compile_asl(asl, workdir):
    """Compile and disassemble. Returns (aml, dsl) paths, or raises."""
    for tool in ("iasl", "acpiexec"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"{tool} is not on PATH")
    src = os.path.join(workdir, "table.asl")
    shutil.copyfile(asl, src)
    p = run(["iasl", "-tc", "table.asl"], cwd=workdir)
    if "Compilation successful" not in p.stdout:
        raise RuntimeError("iasl did not report a successful compile:\n"
                           + p.stdout[-2000:] + p.stderr[-2000:])
    # `iasl` names the output after the DefinitionBlock's own signature, not
    # after the input file - `table.asl` holding a `DSDT` writes `DSDT.aml` -
    # so the output is found by suffix rather than by stem.
    amls = [f for f in sorted(os.listdir(workdir)) if f.endswith(".aml")]
    if not amls:
        raise RuntimeError("iasl produced no .aml")
    aml = os.path.join(workdir, amls[0])
    p = run(["iasl", "-d", amls[0]], cwd=workdir)
    dsls = [f for f in sorted(os.listdir(workdir)) if f.endswith(".dsl")]
    if not dsls:
        raise RuntimeError("iasl -d produced no disassembly:\n" + p.stdout[-2000:])
    return aml, os.path.join(workdir, dsls[0])


def load_stats(aml):
    """The load line and namespace line, or None if the load failed."""
    p = run(["acpiexec", "-b", "quit", aml])
    text = p.stdout + p.stderr
    stats = None
    m = re.search(r"\[DSDT: [^\]]*\][^\n]*\n", text)
    if m:
        stats = m.group(0).strip()
    ns = None
    m = re.search(r"Namespace contains (\d+) \(0x[0-9a-fA-F]+\) objects", text)
    if m:
        ns = int(m.group(1))
    loaded = "successfully acquired and loaded" in text
    return {"line": stats, "namespace": ns, "loaded": loaded, "raw": text}


def devices(source_text, indent):
    """{name: block} for `Device (X)` at a given indent, by brace-free slicing."""
    # Exactly N *spaces*, not N whitespace: `\s` matches a newline, which
    # would let one Device match with the previous line's blank space folded
    # in and then slice the block at the wrong place.
    ms = list(re.finditer(r"^ {%d}Device \((\w+)\)" % indent, source_text, re.M))
    out = {}
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(source_text)
        out[m.group(1)] = source_text[m.start():end]
    return out


def batch_commands(devices_, method):
    """`execute` commands chunked under acpiexec's line limit."""
    out, cur = [], []
    for d in devices_:
        cmd = "execute \\_SB.%s.%s" % (d, method)
        if cur and sum(len(c) + 1 for c in cur) + len(cmd) > BATCH_LIMIT:
            out.append(";".join(cur))
            cur = []
        cur.append(cmd)
    if cur:
        out.append(";".join(cur))
    return out


def eval_method(aml, devices_, method):
    """{device: (returned, text)} for one method across every device."""
    got = {}
    for batch in batch_commands(devices_, method):
        p = run(["acpiexec", "-b", batch, aml])
        text = p.stdout + p.stderr
        parts = re.split(r"Evaluating \\_SB\.(\w+)\.%s" % method, text)
        for i in range(1, len(parts), 2):
            got[parts[i]] = parts[i + 1]
    return got


def crs_scope(block):
    """Just the `_CRS` body of a device block - method body or Name template.

    Scanning the whole device block instead is the mistake this function
    exists to prevent, and it was made here first: `URS0` nests `USB0`, whose
    own `_CRS` carries eight interrupts, so a whole-block scan reads eight
    where URS0's own resource list has none; `PEP0` and `ADC1` nest children
    the same way. Both sides of the comparison have to measure one device's
    `_CRS` and nothing else.
    """
    m = re.search(r"Method \(_CRS, 0, NotSerialized\)", block)
    if m:
        i = block.index("{", m.end() - 1)
        depth = 0
        for j in range(i, len(block)):
            if block[j] == "{":
                depth += 1
            elif block[j] == "}":
                depth -= 1
                if depth == 0:
                    return block[i:j + 1]
        return block[i:]
    m = re.search(r"Name \(_CRS,", block)
    if not m:
        return ""
    i = block.index("{", m.end() - 1) if "ResourceTemplate" in block[m.end():m.end()+80] else m.end()
    depth = 0
    for j in range(i, len(block)):
        if block[j] == "{":
            depth += 1
        elif block[j] == "}":
            depth -= 1
            if depth == 0:
                return block[i:j + 1]
    return block[i:]


def source_resources(block):
    """(windows, gsis, gpios, i2c) as declared in the device's `_CRS`."""
    block = crs_scope(block)
    windows = [(int(a, 16), int(b, 16)) for a, b in re.findall(
        r"Memory32Fixed \((?:ReadWrite|ReadOnly),\s*\n\s*0x([0-9A-Fa-f]+),"
        r"\s*(?:// Address Base)?\s*\n\s*0x([0-9A-Fa-f]+),", block)]
    gsis = sorted(int(g, 16) for g in re.findall(
        r"Interrupt \(ResourceConsumer[^\n]*\n\s*\{\s*\n"
        r"\s*0x([0-9A-Fa-f]{8}),", block))
    gpios = len(re.findall(r"\bGpio(?:Int|Io) \(", block))
    # An I2C descriptor can be written two ways and this table uses both: the
    # `I2cSerialBusV2 (...)` macro, and a raw `Buffer` whose first bytes are the
    # descriptor with the device path concatenated on at runtime. `ADC1` does
    # the second - `0x8E, 0x13, ...` twice - so counting only the macro reports
    # zero where the evaluated buffer holds two.
    i2c = (len(re.findall(r"\bI2cSerialBusV2 \(", block))
           + len(re.findall(r"\b0x8E, 0x", block)))
    return windows, gsis, gpios, i2c


def aml_resources(buffer_tail):
    """(windows, gsis, gpios, i2c) decoded from an evaluated buffer."""
    hexs = []
    for m in re.finditer(r"([0-9A-F]{4}: (?:[0-9A-F]{2} )+)", buffer_tail):
        hexs += m.group(1).split()[1:]
    b = bytes(int(x, 16) for x in hexs)
    windows, gsis, gpios, i2c = [], [], 0, 0
    j = 0
    while j < len(b):
        op = b[j]
        if op == END_TAG:
            break
        if op == MEMORY32FIXED:
            windows.append((int.from_bytes(b[j + 4:j + 8], "little"),
                            int.from_bytes(b[j + 8:j + 12], "little")))
            j += 12
        elif op == EXTENDED_INTERRUPT:
            ln = int.from_bytes(b[j + 1:j + 3], "little")
            gsis.append(int.from_bytes(b[j + 5:j + 9], "little"))
            j += 3 + ln
        elif op == EXTENDED_GPIO:
            gpios += 1
            j += 3 + int.from_bytes(b[j + 1:j + 3], "little")
        elif op == I2C_SERIAL_BUS:
            i2c += 1
            j += 3 + int.from_bytes(b[j + 1:j + 3], "little")
        else:
            j += 1
    return windows, sorted(gsis), gpios, i2c


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asl", default=DEFAULT_ASL)
    ap.add_argument("--aml", default=None,
                    help="check a pre-built AML instead of compiling --asl; the "
                         "source is still read for the expected resources, so "
                         "this is how the checker itself can be tested by "
                         "perturbing a byte in a built table")
    ap.add_argument("--keep", action="store_true",
                    help="leave the compiled scratch directory in place")
    args = ap.parse_args()

    asl = os.path.abspath(args.asl)
    if not os.path.exists(asl):
        print(f"no such ASL: {asl}", file=sys.stderr)
        return 1
    source = open(asl, encoding="utf-8").read()
    src_devs = devices(source, 8)

    workdir = tempfile.mkdtemp(prefix="acpi-runtime-")
    try:
        if args.aml:
            aml = os.path.abspath(args.aml)
            shutil.copyfile(aml, os.path.join(workdir, "given.aml"))
            run(["iasl", "-d", "given.aml"], cwd=workdir)
            dsl = os.path.join(workdir, "given.dsl")
            if not os.path.exists(dsl):
                raise RuntimeError("could not disassemble the given AML")
        else:
            aml, dsl = compile_asl(asl, workdir)
        disasm = open(dsl, encoding="utf-8", errors="replace").read()
        aml_devs = devices(disasm, 8)
    except RuntimeError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2

    print("### load")
    st = load_stats(aml)
    if not st["loaded"] or st["namespace"] is None:
        print("FAIL: the table did not load")
        print(st["raw"][-3000:])
        return 2
    print(f"    {st['line']}")
    print(f"    namespace {st['namespace']} objects")
    print(f"    disassembles to {len(aml_devs)} top-level devices "
          f"(source declares {len(src_devs)})")
    missing = sorted(set(src_devs) - set(aml_devs))
    if missing:
        print(f"    MISSING from the disassembly: {' '.join(missing)}")
    print()

    order = [d for d in src_devs if d in aml_devs]

    print("### _STA")
    sta = eval_method(aml, order, "_STA")
    present = sorted(d for d in order
                     if "returned object" in sta.get(d, ""))
    absent = sorted(d for d in order
                    if "AE_NOT_FOUND" in sta.get(d, ""))
    raised = sorted(d for d in order
                    if d not in present and d not in absent)
    print(f"    {len(present)} return a value: {' '.join(present)}")
    print(f"    {len(absent)} have no _STA (AE_NOT_FOUND, which is legal): "
          f"{' '.join(absent)}")
    if raised:
        print(f"    {len(raised)} RAISED, which is a defect: {' '.join(raised)}")
        for d in raised:
            print(f"      {d}: {sta[d].strip()[:300]}")
    print()

    print("### _CRS")
    # `execute` runs a method and reads a Name., but this table's own form is
    # worth printing: a node carrying `_CRS` as a Name is re-evaluated on every
    # read, which is correct but is not what most of this file does.
    as_method = [d for d in order
                 if re.search(r"Method \(_CRS, 0, NotSerialized\)", aml_devs[d])]
    as_name = [d for d in order
               if re.search(r"Name \(_CRS,", aml_devs[d])]
    print(f"    {len(as_method)} declare _CRS as a method, "
          f"{len(as_name)} as a Name")
    crs = eval_method(aml, order, "_CRS")
    same = diff = none = raised = 0
    for d in order:
        tail = crs.get(d, "")
        if "AE_NOT_FOUND" in tail:
            none += 1
            continue
        if "returned object" not in tail:
            raised += 1
            print(f"    RAISED {d}: {tail.strip()[:300]}")
            continue
        want = source_resources(src_devs[d])
        got = aml_resources(tail)
        if want == got:
            same += 1
        else:
            diff += 1
            print(f"    MISMATCH {d}")
            print(f"        source {want}")
            print(f"        aml    {got}")
    print(f"    {same} resource bodies identical to the source, "
          f"{diff} mismatched, {none} devices with no _CRS, {raised} raised")
    print()

    print("### not checked here, by construction")
    print("    _DSM: four-argument by definition and `execute` passes none, so")
    print("          every _DSM in this file fails AE_AML_UNINITIALIZED_ARG.")
    print("          A driver limit, not a defect in the table.")
    print("    binding: a load is not a bind, and nothing here has seen a PnP")
    print("          manager.")
    print("    GSI acceptance: ACPICA has no GIC and no ITS.")

    ok = not raised and not diff and not missing
    print()
    print("PASS" if ok else "FAIL")
    if args.keep:
        print(f"scratch kept at {workdir}")
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())