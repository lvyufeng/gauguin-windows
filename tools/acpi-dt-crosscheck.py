#!/usr/bin/env python3
"""Measure every `Interrupt ()` in the ASL against the device tree's own cells.

`tools/acpi-runtime-check.py` proves the table survives `iasl` -> AML -> ACPICA.
Its documented limit is that it reads `tools/acpi/gauguin.asl` for its
expectation, so a table that is *consistently* wrong passes it. This tool is the
other direction: it reads nothing from the ASL except the numbers it is
checking, and takes their truth from the device tree.

The gap it closes is not hypothetical. Step 4.250 wrote three CSI bridges whose
`Interrupt ()` carries the device tree's **SPI** number where the ACPI resource
needs the **GSI**:

    Device (CSID)   dts spi 0x1D0 (464)   GSI is 0x1F0   file had 0x1D0
    Device (CSI1)   dts spi 0x1D2 (466)   GSI is 0x1F2   file had 0x1D2
    Device (CSI2)   dts spi 0x2CD (717)   GSI is 0x2ED   file had 0x2CD

Every gate the repository had passed that table. `iasl` compiles it, the
generated twin is `cmp`-identical to it, `acpiexec` loads and runs it, and
`acpi-runtime-check.py` reports 30 identical resource bodies - because all four
compare the file against itself. The fourth camera node written in the *same*
step, `VFE0`, took dts SPI 0x1D1 and wrote 0x1F1, correctly. So the raw SPI is
not a second valid encoding: it is a slip, and this tool names it as one.

**The rule.** ACPI GSI = GIC SPI + 32 (INTID = 32 + SPI), which is stated at the
top of `tools/acpi/gauguin.asl` and obeyed by every other node in it. The same
+32 applies after a PDC pin has been mapped to its SPI through
`qcom,pdc-ranges`, which is why `0x20E`/`0x20F`/`0x211` (PDC pins 14/15/17 ->
SPI 494/495/497) and `0x201` (pin 1 -> SPI 481) are all correct without being
SPI+32 of anything the node lists directly.

**What it does.** Decodes the DTB itself - no `dtc`, no `fdtget` - walking the
FDT structure block, reading `#address-cells`/`#size-cells` from each parent so
`reg` decodes correctly, finding the GIC and the PDC by `compatible` and
phandle, and turning every node's `interrupts` and `interrupts-extended` into
two sets: the GSIs it declares, and the GSIs it would declare if its SPI field
had been written raw. Then, for each top-level `Device (X)` in the ASL and each
of that device's `_CRS` windows, it matches the node overlapping the window most
and classifies each GSI against the node of the block it belongs to:

    ok            in the node's GSI set
    SLIP          in the node's *raw SPI* set, and value + 32 is in its GSI set
    unaccounted   neither - reported with the node's GSIs, and with the deepest
                  descendant that does claim it, since an aggregate node like
                  URS0 legitimately carries its children's interrupts

Exit status is 2 for a SLIP and 0 otherwise; `unaccounted` is a warning because
it has legitimate causes (a nested device's interrupt, a `_CRS` that is a
deliberate sub-window, one tree describing a line the other omits) and a tool
that fails on those stops being read. `--strict` promotes it to a failure.

**What it does not prove.** That the node is the right node: the match is by
address overlap, so a window on the wrong address is checked against whatever it
landed on and can come back `ok`. It also cannot see a missing interrupt, only a
wrong one, and it only knows the two encodings above - a GSI from a firmware
table or a GPIO controller would read as `unaccounted`. It checks each line
against *some* window's block, not against the window it was written next to, so
a node that swapped two of its own lines would still pass; the pairing between
`Memory32Fixed` and `Interrupt ()` within a `_CRS` is an ordering convention no
tree records. Nor is there any check of which tree is authoritative: pass the
tree the node was derived from, or the result is about the wrong file.
`Resources/DTBs/gauguin.dtb` is the firmware's own 56-node tree and does not
carry the camera nodes at all; the vendor tree pulled from the running phone's
`/sys/firmware/fdt` (451 `/soc` children) does.

Usage:
    tools/acpi-dt-crosscheck.py --dtb work/uefi/Mu-Silicium/Resources/DTBs/gauguin.dtb
    tools/acpi-dt-crosscheck.py --dtb /tmp/live-gauguin.dtb --asl tools/acpi/gauguin.asl
    tools/acpi-dt-crosscheck.py --dtb a.dtb --dtb b.dtb --strict
"""

import argparse
import os
import re
import struct
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ASL = os.path.join(REPO, "tools", "acpi", "gauguin.asl")
DEFAULT_DTB = os.path.join(REPO, "work", "uefi", "Mu-Silicium", "Resources",
                           "DTBs", "gauguin.dtb")

FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9

GIC_SPI = 0
GIC_PPI = 1
# An ACPI Interrupt () carries the INTID, not the SPI: SPIs start at 32, PPIs
# at 16. See the "INTID = 32 + SPI" rule at the top of gauguin.asl.
SPI_BASE = 32
PPI_BASE = 16

# Interrupt-specifier type -> the ACPI trigger the resource descriptor must carry.
# GIC cells: 0 = SPI, 1 = PPI. PDC cells are <pin, type> and the type is the
# *GIC* type the pin is routed as, so the same table decodes both. Only 1 and 4
# are unambiguous; 2 (rising) and 3 (falling) are edge, which is also what 1
# means but with a polarity the ACPI descriptor can express separately, so a
# descriptor that says Edge satisfies all three. Used by `Tree.triggers`.
TYPE_TRIGGER = {1: "Edge", 2: "Edge", 3: "Edge", 4: "Level"}


def align4(n):
    return (n + 3) & ~3


# --------------------------------------------------------------------------
# FDT decoding
# --------------------------------------------------------------------------

def parse_dtb(data):
    """The FDT structure block as a node tree, properties kept as raw bytes."""
    magic, _total, off_struct, off_strings = struct.unpack_from(">4I", data, 0)
    if magic != 0xD00DFEED:
        raise ValueError("not an FDT: magic 0x%08X" % magic)
    version, = struct.unpack_from(">I", data, 20)
    if version < 16:
        raise ValueError("FDT version %d is too old to parse" % version)
    strings = data[off_strings:]

    def name_at(off):
        end = strings.index(b"\0", off)
        return strings[off:end].decode("utf-8", "replace")

    pos = off_struct
    root = {"name": "", "props": {}, "children": []}
    stack = [root]
    while True:
        tok, = struct.unpack_from(">I", data, pos)
        pos += 4
        if tok == FDT_BEGIN_NODE:
            end = data.index(b"\0", pos)
            name = data[pos:end].decode("utf-8", "replace")
            pos = align4(end + 1)
            node = {"name": name, "props": {}, "children": []}
            stack[-1]["children"].append(node)
            stack.append(node)
        elif tok == FDT_END_NODE:
            if len(stack) == 1:
                raise ValueError("unbalanced FDT_END_NODE")
            stack.pop()
        elif tok == FDT_PROP:
            ln, no = struct.unpack_from(">2I", data, pos)
            pos += 8
            stack[-1]["props"][name_at(no)] = data[pos:pos + ln]
            pos = align4(pos + ln)
        elif tok == FDT_NOP:
            pass
        elif tok == FDT_END:
            break
        else:
            raise ValueError("bad FDT token %#x at %#x" % (tok, pos - 4))
    return root


def words(node, key):
    """A property as a big-endian 32-bit cell list; () if absent or ragged."""
    v = node["props"].get(key)
    if v is None or len(v) % 4:
        return []
    return list(struct.unpack(">%dI" % (len(v) // 4), v))


def strings(node, key):
    """A stringlist property as a list of strings; the list is NUL-separated."""
    v = node["props"].get(key)
    if v is None:
        return []
    return [s.decode("utf-8", "replace") for s in v.split(b"\0") if s]


def one(node, key, default=None):
    v = node["props"].get(key)
    if v is None:
        return default
    if len(v) == 4:
        return struct.unpack(">I", v)[0]
    try:
        return int(v.rstrip(b"\0").decode())
    except ValueError:
        return default


class Tree:
    """A decoded DTB, indexed by path, with the two interrupt encodings."""

    def __init__(self, data, label):
        self.label = label
        self.root = parse_dtb(data)
        self.phandle = {}     # phandle -> node
        self.ac = {}          # id(node) -> (address-cells, size-cells)
        self.path = {}        # id(node) -> path
        self.nodes = []       # every node, in tree order
        self.gic_phandle = None
        self.gic_cells = 3
        self.pdc_phandle = None
        self.pdc_cells = 2
        self.pdc_pin_to_spi = {}
        self._index(self.root, "/", (2, 1))
        self._find_controllers()

    def _index(self, node, path, ac_sc):
        node["_path"] = path
        node["_ac_sc"] = ac_sc
        self.path[id(node)] = path
        self.nodes.append(node)
        ph = one(node, "phandle", one(node, "linux,phandle"))
        if ph is not None:
            self.phandle[ph] = node
        child_ac_sc = (one(node, "#address-cells", 2), one(node, "#size-cells", 1))
        for c in node["children"]:
            self._index(c, path.rstrip("/") + "/" + c["name"], child_ac_sc)

    def _find_controllers(self):
        for n in self.nodes:
            compat = strings(n, "compatible")
            if any(c.startswith("arm,gic") for c in compat):
                self.gic_phandle = one(n, "phandle", one(n, "linux,phandle"))
                self.gic_cells = one(n, "#interrupt-cells", 3)
            if any("pdc" in c for c in compat):
                self.pdc_phandle = one(n, "phandle", one(n, "linux,phandle"))
                self.pdc_cells = one(n, "#interrupt-cells", 2)
        if self.pdc_phandle is not None:
            ranges = words(self.phandle[self.pdc_phandle], "qcom,pdc-ranges")
            for i in range(0, len(ranges) - 2, 3):
                pin0, spi0, count = ranges[i:i + 3]
                for k in range(count):
                    self.pdc_pin_to_spi[pin0 + k] = spi0 + k

    def regs(self, node):
        """[(base, size)] from `reg`, using the *parent's* cell counts."""
        ac, sc = node["_ac_sc"]
        if ac == 0 or sc == 0:
            return []
        w = words(node, "reg")
        out = []
        for i in range(0, len(w) - (ac + sc) + 1, ac + sc):
            base = size = 0
            for x in w[i:i + ac]:
                base = (base << 32) | x
            for x in w[i + ac:i + ac + sc]:
                size = (size << 32) | x
            out.append((base, size))
        return out

    def _decode(self, phandle, cells_):
        """One interrupt specifier -> (gsi, raw, trigger) or None."""
        if phandle == self.gic_phandle and len(cells_) >= 2:
            typ, num = cells_[0], cells_[1]
            trig = TYPE_TRIGGER.get(cells_[2]) if len(cells_) >= 3 else None
            if typ == GIC_SPI:
                return num + SPI_BASE, num, trig
            if typ == GIC_PPI:
                return num + PPI_BASE, num, trig
            return None
        if phandle == self.pdc_phandle and len(cells_) >= 1:
            spi = self.pdc_pin_to_spi.get(cells_[0])
            if spi is None:
                return None
            # <pin, type>: the second cell is the GIC type the pin is routed as.
            trig = TYPE_TRIGGER.get(cells_[1]) if len(cells_) >= 2 else None
            return spi + SPI_BASE, spi, trig
        return None

    def interrupts_typed(self, node):
        """[(gsi, raw_spi, trigger)] from `interrupts` and `interrupts-extended`.

        The trigger is the ACPI word the descriptor must carry, or None when the
        specifier's type cell says something this reader does not map. It is a
        separate method rather than extra return slots on `interrupts` because
        the accounting loop and the windows want the sets, while only the trigger
        check wants the type - and the type is the one thing `qcom,pdc-ranges`
        does *not* carry, since it is a cell of the consumer's specifier.
        """
        out = []

        parent = one(node, "interrupt-parent", self.gic_phandle)
        w = words(node, "interrupts")
        n = self.gic_cells if parent == self.gic_phandle else self.pdc_cells
        if n:
            for i in range(0, len(w) - n + 1, n):
                got = self._decode(parent, w[i:i + n])
                if got:
                    out.append(got)

        w = words(node, "interrupts-extended")
        i = 0
        while i < len(w):
            ph = w[i]
            target = self.phandle.get(ph)
            if target is None:
                break
            n = self.gic_cells if ph == self.gic_phandle else self.pdc_cells
            got = self._decode(ph, w[i + 1:i + 1 + n])
            if got:
                out.append(got)
            i += 1 + n
        return out

    def interrupts(self, node):
        """(gsi_set, raw_spi_set) from `interrupts` and `interrupts-extended`."""
        gsis, raws = set(), set()
        for gsi, raw, _trig in self.interrupts_typed(node):
            gsis.add(gsi)
            raws.add(raw)
        return gsis, raws

    def descendants(self, node):
        out = []
        for c in node["children"]:
            out.append(c)
            out += self.descendants(c)
        return out

    def claims(self, gsi):
        """Every node that declares this GSI, as (path, is_raw_spi) pairs."""
        out = []
        for node in self.nodes:
            gsi_set, raw_set = self.interrupts(node)
            if gsi in gsi_set:
                out.append((self.path[id(node)], False))
            elif gsi in raw_set:
                out.append((self.path[id(node)], True))
        return out

    def triggers(self, gsi):
        """The set of triggers every node declaring this GSI asks for.

        A set, not one word: two nodes can claim the same number - the payload
        tree has `pmu@90b6300` (bwmon) and `system-cache-controller@9200000`
        (LLCC) on GSI `0x265` - and a reader has to see that before concluding
        the ASL is wrong. A node with no type cell contributes nothing.
        """
        out = set()
        for node in self.nodes:
            for g, _raw, trig in self.interrupts_typed(node):
                if g == gsi and trig:
                    out.add(trig)
        return out


# --------------------------------------------------------------------------
# The ASL side
# --------------------------------------------------------------------------

def own_scope(block):
    """The device's own body with every nested `Device (...)` subtree removed.

    Removing subtrees rather than cutting at an offset is what makes this right
    in both cases at once. Cutting at the first nested `Device (` (the original
    form) loses the parent's `_CRS` when a child is declared ahead of it - GPU0
    declares MON0 at offset 350 of its block while its `_CRS` begins at 1007.
    Cutting at the first nested device *after* `_CRS` instead keeps a child that
    sits *before* `_CRS`, so URS0's MON0-shaped children stayed in its body and
    made it look as though it declared interrupts, which it does not. Subtracting
    the subtrees has neither failure: the parent keeps its own `_CRS` wherever
    the child was written, and inherits nothing from it.

    Nested interrupts must not read as the parent's - that is the mistake 4.252
    documents for URS0 nesting USB0 and for PEP0 and ADC1 nesting children.
    """
    src = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    out, i, n, depth = [], 0, len(src), 0
    while i < n:
        c = src[i]
        if c == "{":
            depth += 1
            out.append(c)
            i += 1
            continue
        if c == "}":
            depth -= 1
            out.append(c)
            i += 1
            continue
        if depth == 1:
            m = re.match(r"\s*Device \(\w+\)\s*", src[i:])
            if m:
                j = src.find("{", i + m.end())
                if j != -1:
                    d, k = 0, j
                    while k < n:
                        if src[k] == "{":
                            d += 1
                        elif src[k] == "}":
                            d -= 1
                            if d == 0:
                                k += 1
                                break
                        k += 1
                    i = k
                    continue
        out.append(c)
        i += 1
    return "".join(out)


def interrupts_by_brace_depth(text):
    """{device: count} for `Interrupt (` tokens, attributed by BRACE DEPTH.

    Deliberately independent of `own_scope()` and `asl_crs()`, which it exists
    to audit. Those two derive a device's own text from the source; this one
    walks the source once and attributes each interrupt to whichever `Device`
    is open at its brace depth, so a bug in either extractor cannot hide behind
    the other. `tools/acpi-window-audit.py` uses the same technique for windows
    and attributes GPU0's ten windows correctly, which is why it is trusted
    here.
    """
    src = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    counts = {}
    stack, pending = [], None
    i, n = 0, len(src)
    while i < n:
        m = re.compile(r"Device \((\w+)\)").match(src, i)
        if m and (i == 0 or src[i - 1] in " \t\n{"):
            pending = m.group(1)
            i = m.end()
            continue
        m = re.compile(r"Interrupt \(").match(src, i)
        if m:
            if stack:
                counts[stack[-1]] = counts.get(stack[-1], 0) + 1
            i = m.end()
            continue
        c = src[i]
        if c == "{":
            if pending is not None:
                stack.append(pending)
                pending = None
            else:
                stack.append(stack[-1] if stack else "?")
        elif c == "}" and stack:
            stack.pop()
        i += 1
    return counts


def device_spans(text):
    """[(name, start, end)] for every `Device (X)`, at ANY nesting depth.

    Brace- and comment-aware, and that is the point: the previous extractor
    anchored on `^ {8}Device`, so it read top-level devices only. URS0's two
    children carry eight interrupts between them - `USB0` six, `UFN0` two - and
    every one is claimed by the vendor tree, yet no gate ever saw them because
    they were never extracted at all (Step 4.284). The span is the whole
    `Device (...) { ... }` block by brace matching, so a child declared before
    its parent's `_CRS` cannot cut the parent's body away: that defect is
    `own_scope()`'s, applied from the other side.

    Validated against `interrupts_by_brace_depth()`'s independent ground truth -
    163 `Interrupt` entries across 31 devices - with zero mismatches over all 89
    devices on this table. That check is the reason this could be changed at
    all: Step 4.284 tried an all-device sweep and mis-attributed `USB0` and
    reported `GPU0` as three GSIs against a truth of two, so it was reverted
    rather than committed.
    """
    spans, stack, pending = [], [], None
    i, n = 0, len(text)
    D = re.compile(r"Device \((\w+)\)")
    while i < n:
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        m = D.match(text, i)
        if m and (i == 0 or text[i - 1] in " \t\n{"):
            pending = (m.group(1), i)
            i = m.end()
            continue
        c = text[i]
        if c == "{":
            stack.append(pending)
            pending = None
        elif c == "}" and stack:
            top = stack.pop()
            if top is not None:
                spans.append((top[0], top[1], i + 1))
        i += 1
    return spans


def asl_devices(text):
    """{name: (block, own-body)} for every `Device (X)`, any depth.

    `own-body` is the block minus nested `Device` subtrees, so a child's
    interrupts are never read as the parent's. A repeated name gets a `#n`
    suffix so a second `RHUB` or `PRT1` cannot overwrite the first - a silent
    overwrite is the same failure class as the dropped report this file already
    carries scars from.
    """
    out, seen = {}, {}
    for name, start, end in device_spans(text):
        block = text[start:end]
        k = seen.get(name, 0) + 1
        seen[name] = k
        key = name if k == 1 else "%s#%d" % (name, k)
        out[key] = (block, own_scope(block))
    return out


def asl_crs(body):
    """Just the device's own `_CRS` - method body or Name template."""
    m = re.search(r"Method \(_CRS, 0, NotSerialized\)", body)
    if m:
        return body[m.start():]
    m = re.search(r"Name \(_CRS,", body)
    if m:
        return body[m.start():]
    return ""


def strip_comments(text):
    """Drop `//` comments.

    A template's own trailing comments carry numbers - "// GSI: dts SPI 464
    (0x1D0) + 32" - and a naive scan reads those as a second resource value.
    That is not hypothetical: this tool did it, flagging the three fixed camera
    GSIs as still-wrong until the comments were stripped.
    """
    return re.sub(r"//[^\n]*", "", text)


def asl_resources(crs):
    """(windows, gsis, typed) as declared, in source order.

    `gsis` is the flat list the accounting loop walks; `typed` is the same
    interrupts as (gsi, trigger) with the trigger taken from the descriptor's own
    second field, so the one check that *can* fail on a wrong trigger has the
    source's word for it and not a default.
    """
    crs = strip_comments(crs)
    windows = [(int(a, 16), int(b, 16)) for a, b in re.findall(
        r"Memory32Fixed \((?:ReadWrite|ReadOnly),\s*\n\s*0x([0-9A-Fa-f]+),"
        r"\s*\n\s*0x([0-9A-Fa-f]+),", crs)]
    gsis, typed = [], []
    for m in re.finditer(
            r"Interrupt \(ResourceConsumer, (Edge|Level),[^\n]*\n\s*\{([^}]*)\}",
            crs):
        trig = m.group(1)
        for x in re.findall(r"0x([0-9A-Fa-f]+)", m.group(2)):
            g = int(x, 16)
            gsis.append(g)
            typed.append((g, trig))
    return windows, gsis, typed


# --------------------------------------------------------------------------
# Matching and reporting
# --------------------------------------------------------------------------

def overlap(a, b):
    lo = max(a[0], b[0])
    hi = min(a[0] + a[1], b[0] + b[1])
    return max(0, hi - lo)


def best_nodes(trees, window):
    """Every node with the largest overlap of the window, across every tree.

    All of them, not one. The vendor tree describes `0x3d40000` twice -
    `qcom,kgsl-iommu@3d40000` with no interrupts and `arm,smmu-kgsl@3d40000`
    (the mainline name) with all ten - so returning whichever came first made
    MMU1 read `0/10 GSI(s) accounted` and produced ten false warnings. The sets
    of every maximally-overlapping node are merged instead, and a node that
    declares no interrupt at all is not allowed to win a tie.
    """
    best, hits = 0, []
    for tree in trees:
        for node in tree.nodes:
            n = max((overlap(window, r) for r in tree.regs(node)), default=0)
            if not n:
                continue
            if n > best:
                best, hits = n, [(tree, node)]
            elif n == best:
                hits.append((tree, node))
    with_int = [(t, n) for t, n in hits if any(t.interrupts(n))]
    return (with_int or hits), best


def node_label(hits):
    """The `tree path` label one node set is reported under."""
    return " & ".join(sorted("%s %s" % (t.label, t.path[id(n)]) for t, n in hits))


def window_sets(trees, windows):
    """(nodes, gsi_set, raw_set) for each `_CRS` window, in source order.

    One tuple per window, not one for the whole device. A device whose `_CRS`
    carries N blocks declares N interrupts - one per block - and checking all of
    them against `windows[0]`'s node asks the wrong block about N-1 of them. The
    cost was visible from 4.253: `JPGE` is one driver over two blocks
    (`jpegenc@ac4e000`, `jpegdma@ac52000`) and its second line, `0x1FB`, came
    back `unaccounted` because only the first block was consulted. It was read
    as a legitimate warning and resolved by hand; the tool should not have made
    it a reader's job. A CSIPHY node aggregating four PHYs would have had three
    of its four lines unverifiable, which is the failure class this tool exists
    to name.
    """
    out = []
    for w in windows:
        nodes = best_nodes(trees, w)[0]
        gs, rs = set(), set()
        for tree, node in nodes:
            g, r = tree.interrupts(node)
            gs |= g
            rs |= r
        out.append((nodes, gs, rs))
    return out


def load(argv_dtb):
    """One Tree per --dtb, compiling a .dts through dtc when needed."""
    trees = []
    for path in argv_dtb:
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise RuntimeError("no such device tree: %s" % path)
        if path.endswith(".dts"):
            workdir = tempfile.mkdtemp(prefix="dt-crosscheck-")
            out = os.path.join(workdir, "tree.dtb")
            p = subprocess.run(["dtc", "-f", "-I", "dts", "-O", "dtb", "-o", out, path],
                               capture_output=True, text=True)
            if not os.path.exists(out):
                raise RuntimeError("dtc failed on %s:\n%s%s" % (path, p.stdout, p.stderr))
            path = out
        label = os.path.relpath(path, REPO) if path.startswith(REPO) else path
        try:
            trees.append(Tree(open(path, "rb").read(), label))
        except (ValueError, struct.error, IndexError) as e:
            raise RuntimeError("%s is not a usable device tree: %s" % (label, e))
    return trees


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asl", default=DEFAULT_ASL)
    ap.add_argument("--dtb", action="append", default=None,
                    help="a .dtb or .dts to cross-check against; repeatable, and "
                         "a device is checked against whichever tree claims its "
                         "window. Default: the firmware's own gauguin.dtb, which "
                         "does not carry the camera nodes")
    ap.add_argument("--strict", action="store_true",
                    help="treat every `unaccounted` GSI as a failure")
    args = ap.parse_args()

    asl = os.path.abspath(args.asl)
    if not os.path.exists(asl):
        print("no such ASL: %s" % asl, file=sys.stderr)
        return 1
    text = open(asl, encoding="utf-8").read()

    try:
        trees = load(args.dtb or [DEFAULT_DTB])
    except RuntimeError as e:
        print("FAIL: %s" % e, file=sys.stderr)
        return 2
    for t in trees:
        print("tree %s: %d nodes, gic phandle %s (%d cells), pdc %s, %d pins mapped"
              % (t.label, len(t.nodes), t.gic_phandle, t.gic_cells,
                 t.pdc_phandle, len(t.pdc_pin_to_spi)))
        if t.gic_phandle is None:
            print("  no arm,gic node: interrupts cannot be decoded")
            return 2
    print()

    slips, unaccounted, checked, unmapped, triggers = [], [], 0, [], []
    unamatchable = []  # interrupts no window can reach, whatever the base
    # Every device that declares an interrupt, and every device this run names
    # in a report. The difference is the silent-drop class: a device the tool
    # read but never reported on, because some branch `continue`d before the
    # print. GPU0 was there for six steps.
    with_gsis, named = [], []
    for name, (block, body) in sorted(asl_devices(text).items()):
        crs = asl_crs(body)
        windows, gsis, typed = asl_resources(crs)
        if not gsis:
            continue
        with_gsis.append(name)

        # Trigger check first, before any window can `continue` past it. A device
        # with no matchable window is exactly the device whose trigger nobody
        # else checks - ADSP, CAMP, PEP0 and PM01 are four of them here - and
        # putting this loop after the window logic would keep it silent on the
        # nodes it was written for. That is the failure this tool has recorded
        # twice: an input it cannot parse is not a failure, it is a silence.
        #
        # Against every tree at once and against the union of every node that
        # declares the number: two nodes can share a GSI with different types
        # (`pmu@90b6300` is Level and `system-cache-controller@9200000` Level on
        # 0x265, but the corpus's PEP0 asks Edge for the same number), so the
        # report is a set and a reader has to see all of it.
        for g, trig in typed:
            want = "Level" if trig == "Level" else "Edge"
            seen = set()
            for tree in trees:
                seen |= tree.triggers(g)
            if seen and want not in seen:
                triggers.append((name, g, trig, sorted(seen)))

        if not windows:
            # A device that really has no `Memory32Fixed` has no base to match a
            # node on, so its interrupts are checked by nothing - and if none of
            # them appears in any tree either, then not one line of its `_CRS`
            # has been verified. ADSP, AMSS, IPCC, NSP0, PEP0 and PM01 are the
            # six here.
            #
            # This is NOT the class GPU0 was in, and the report must not be read
            # as covering that one. GPU0 was dropped one branch earlier, at
            # `if not gsis: continue`, because `asl_devices()` truncated its own
            # body before its `_CRS` (a child declared ahead of the resources);
            # through Steps 4.277-4.282 its two GSIs were read by no gate and
            # named by no list. Step 4.283 fixed the extractor, and the lesson is
            # the one below: a branch that `continue`s before the report hides
            # its own input, so any device missing from BOTH lists has to be
            # accounted for, not assumed checked.
            unmatchable = [g for g in gsis
                           if not any(t.claims(g) for t in trees)]
            if unmatchable:
                unamatchable.append((name, unmatchable))
            unmapped.append((name, "no Memory32Fixed to match a node by"))
            named.append(name)
            continue
        if not best_nodes(trees, windows[0])[0]:
            unmapped.append((name, "no node overlaps 0x%X+0x%X"
                             % windows[0]))
            named.append(name)
            continue
        per_window = window_sets(trees, windows)
        label = node_label(per_window[0][0])
        extra = sum(1 for nodes, _g, _r in per_window[1:] if nodes)
        if extra:
            label += " +%d block(s)" % extra
        checked += 1
        named.append(name)
        ok_n = 0
        for g in gsis:
            # Accounted, then a slip, then unaccounted - in that order and over
            # every window before moving on. Deciding per window as it is
            # scanned would call a line a slip because block 1 writes it raw
            # while block 2 declares it correctly.
            if any(g in gs for _n, gs, _r in per_window):
                ok_n += 1
                continue
            slip = next(((nodes, gs) for nodes, gs, rs in per_window
                         if g in rs and (g + SPI_BASE) in gs), None)
            if slip:
                slips.append((name, g, g + SPI_BASE, node_label(slip[0])))
                continue
            elsewhere = []
            for tree in trees:
                elsewhere += tree.claims(g)
            unaccounted.append((name, g, label, elsewhere))
        print("  %-6s %-58s %2d/%2d GSI(s) accounted"
              % (name, label, ok_n, len(gsis)))

    print()
    if unmapped:
        print("%d device(s) with interrupts and no matchable window:" % len(unmapped))
        for name, why in unmapped:
            print("  %-6s %s" % (name, why))
        print()
    if unamatchable:
        print("%d device(s) whose interrupts no window can reach AND no tree "
              "claims:" % len(unamatchable))
        for name, gs in unamatchable:
            print("  %-6s %s" % (name, " ".join("0x%X" % g for g in gs)))
        print("  These are UNVERIFIED, not wrong: the device has no window to "
              "match on, so nothing anchors it, and the tree does not declare "
              "the numbers either. A line here has passed every gate by being "
              "invisible to all of them.")
        print()
    if unaccounted:
        print("%d GSI(s) not in their matched node's own set:" % len(unaccounted))
        for name, g, label, elsewhere in unaccounted:
            print("  %-6s 0x%X  vs %s" % (name, g, label))
            for path, is_raw in elsewhere[:3]:
                print("           declared by %s%s"
                      % (path, "  [as a raw SPI, not a GSI]" if is_raw else ""))
            if not elsewhere:
                print("           no node in any tree declares it")
        print("  These are warnings: a nested device's interrupt, a `_CRS` "
              "that is a deliberate sub-window, or a line one tree carries and "
              "another does not. A device's *own* second block is no longer "
              "among them: it is checked against that block.")
        print()
    if slips:
        print("%d GSI(s) written as the raw device-tree SPI:" % len(slips))
        for name, had, want, label in slips:
            print("  %-6s vs %s  had 0x%X  want 0x%X (dts SPI 0x%X + %d)"
                  % (name, label, had, want, had, SPI_BASE))
        print()
    if triggers:
        print("%d interrupt trigger(s) the tree does not agree with:" % len(triggers))
        for name, g, trig, seen in triggers:
            print("  %-6s 0x%-5X  ASL %s  tree %s"
                  % (name, g, trig, " & ".join(seen)))
        print("  A warning, not a failure: this port writes several nodes from the")
        print("  corpus's tables rather than from this board's tree, and a mismatch")
        print("  is either a descriptor to change here or a corpus default that this")
        print("  board overrides - two different findings, and only a reader can say")
        print("  which. A GSI two nodes claim with different types is reported as")
        print("  both, because the tree does not settle it.")
        print()

    # The GPU0 class, detected where it actually lives, and detected WITHOUT the
    # extractor's own logic. A device whose source carries an `Interrupt` at its
    # own brace depth while `asl_devices` + `asl_crs` find no interrupt in its
    # own body has had its body cut away, so it was dropped at
    # `if not gsis: continue` - and from inside the loop that is
    # indistinguishable from a device with no interrupts, because `named` and
    # `with_gsis` are both built after the drop.
    truth = interrupts_by_brace_depth(text)
    hidden, misattributed = [], []
    for name, (_block, body) in asl_devices(text).items():
        if truth.get(name, 0) and not asl_resources(asl_crs(body))[1]:
            hidden.append(name)

    # Soundness of the extractor itself, against the independent detector. This
    # is the gate Step 4.284 lacked: an all-depth extractor can mis-attribute a
    # child's interrupts to its parent, and a mismatch in either direction means
    # a body was cut wrong. The previous attempt pulled `USB0` (six interrupts,
    # no `_CRS`) and reported `GPU0` as three GSIs against a truth of two, and it
    # was caught only by hand. The counts must agree device by device, and no
    # device the detector names may be missing from the extractor's set.
    for name, (_block, body) in asl_devices(text).items():
        got = len(re.findall(r"Interrupt \(", body))
        want = truth.get(name, 0)
        if got != want:
            misattributed.append((name, got, want))
    seen = {n for n in asl_devices(text) if n in truth}
    for name, cnt in truth.items():
        if name not in seen:
            misattributed.append((name, 0, cnt))

    dropped = [n for n in with_gsis if n not in named]
    if dropped or hidden or misattributed:
        if dropped:
            print("%d device(s) with interrupts that NO report above names:" % len(dropped))
            for n in dropped:
                print("  %-6s read, then dropped by a branch that continues "
                      "before the reports" % n)
        if hidden:
            print("%d device(s) whose full block declares interrupts but whose "
                  "own body does not:" % len(hidden))
            for n in hidden:
                print("  %-6s `_CRS` cut away by the body extractor, so the "
                      "device was dropped before any report" % n)
        if misattributed:
            print("%d device(s) whose extracted interrupt count disagrees with "
                  "the brace-depth detector:" % len(misattributed))
            for n, got, want in misattributed:
                print("  %-6s extractor %d, brace-depth truth %d" % (n, got, want))
            print("  The extractor is unsound, so every count above is suspect - "
                  "not just this device's. Fix the extractor, not the count.")
        print("  The rest are UNVERIFIED and unreported at once. A device here "
              "has passed every gate by being invisible to all of them.")
        print()

    ok = (not slips and not dropped and not hidden and not misattributed
          and (not args.strict or not unaccounted))
    print("%d device(s) cross-checked; %d slip(s), %d unaccounted%s"
          % (checked, len(slips), len(unaccounted),
             "" if not (dropped or hidden or misattributed)
             else ", %d hidden" % (len(dropped) + len(hidden) + len(misattributed))))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())