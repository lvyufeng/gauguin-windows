#!/usr/bin/env python3
"""Who in a volume *touches* a GUID, and through which hand does it touch it?

Why this exists. Steps 4.166 and 4.167 counted how many times a GUID's sixteen bytes occur in
a volume and had to keep saying that a count cannot tell a publisher from a consumer:
`InstallMultipleProtocolInterfaces (&g)` and `LocateProtocol (&g, NULL, &out)` leave the same
bytes in the same `.data`. That caveat is not a limitation to be lived with - it is one
disassembly away from being answered, because the two calls differ in *how the address is used*:
a publisher passes the GUID as an argument to the install entry point of `EFI_BOOT_SERVICES` and
the consumer passes it to `LocateProtocol` or `OpenProtocol`. So this tool extracts each
`EFI_SECTION_PE32` that carries the GUID, disassembles it for AArch64, resolves the `ADRP`+`ADD`
pair that materialises the GUID's address into a register, and reads which `EFI_BOOT_SERVICES`
slot the register is handed to.

What it is not: a decompiler, and not a substitute for a run-time reading. It answers "what does
this binary do with this address", which is a static fact about shipped code. A call site that
exists is not a call site that executes, and where the answer matters that difference is stated
in the step rather than papered over.

Usage:

    tools/guid-refs.py E722B03F-B250-42CE-8EBD-5BD51812D037 /tmp/fv-usb.bin
    tools/guid-refs.py 4CF5B200-68B8-4CA5-9EEC-B23E3F50029A /tmp/fv-old.bin /tmp/fv-usb.bin
    tools/guid-refs.py E722B03F-B250-42CE-8EBD-5BD51812D037 --extracted device/dxe

The volume argument is anything `tools/fv-apriori.py`'s `walk_volume` accepts. `--keep DIR`
writes the extracted `PE32` sections there instead of a temporary directory, which is what the
step that first used this did; the sections are named `<module>-<volume>.efi`.

`--extracted DIR` answers the same question over a directory of *bare* `PE32` images rather
than over a volume, which is the shape this project's other input has: `device/dxe/` is the
XBL extraction, one `.efi` and one `.ffs` per stock driver, and `tools/xbl-unmapped.py` already
treats it as a first-class source. Without this mode the only way to ask "who publishes this
GUID" of the extraction was to re-implement `analyse` in a scratch script, which is what the
step that needed it did before adding the mode. A name here comes from the file name, since an
extracted `.efi` carries no FFS header to resolve - so the column reads `AdcDxe`, not
`AdcDxe  F0A5F597`.
"""
import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# `EFI_BOOT_SERVICES` slots, as offsets from the table's first byte. Only the ones a protocol
# reference can plausibly reach are named; the rest print as `BS+0x..` so an unnamed slot is
# visible as unnamed rather than silently rounded to the nearest name.
BOOT_SERVICES = {
    0x80: "InstallProtocolInterface",
    0x88: "ReinstallProtocolInterface",
    0x90: "UninstallProtocolInterface",
    0x98: "HandleProtocol",
    0xA8: "RegisterProtocolNotify",
    0xB0: "LocateHandle",
    0xB8: "LocateDevicePath",
    0x118: "CloseProtocol",
    0x120: "OpenProtocol",
    0x128: "OpenProtocolInformation",
    0x130: "ProtocolsPerHandle",
    0x138: "LocateHandleBuffer",
    0x140: "LocateProtocol",
    0x148: "InstallMultipleProtocolInterfaces",
    0x150: "UninstallMultipleProtocolInterfaces",
}

# Which slot makes a file a publisher, a consumer, or neither. `InstallProtocolInterface` and
# `InstallMultipleProtocolInterfaces` are the two ways a driver publishes a protocol; the rest
# of the named slots are ways to ask for one that already exists.
PUBLISHES = {"InstallProtocolInterface", "InstallMultipleProtocolInterfaces", "ReinstallProtocolInterface"}
CONSUMES = {"LocateProtocol", "LocateHandle", "LocateHandleBuffer", "LocateDevicePath", "OpenProtocol",
            "HandleProtocol", "RegisterProtocolNotify", "CloseProtocol", "UninstallProtocolInterface"}

INSN = re.compile(r"\s*([0-9a-f]+):\t([0-9a-f ]+)\t(\S+)\s*(.*)")


def load_helpers():
    """`tools/pci-guid-census.py` for the GUID maps and `tools/fv-apriori.py` for the walk.

    Both are imported by path: `tools/` is not a package, and neither tool is a library. This is
    the same seam `tools/pci-guid-census.py` uses to reach the walker.
    """
    import importlib.util

    def by_path(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    return by_path("census", os.path.join(HERE, "pci-guid-census.py")), \
        by_path("fvap", os.path.join(HERE, "fv-apriori.py"))


def read_volume(path):
    """The volume bytes, whichever of the three shapes this project's artifacts take.

    `tools/pci-guid-census.py`'s own `read_volume` reads two of them - the file itself, and an
    Android boot image whose gunzipped payload *is* a volume - and that pair is why this mode
    could not read a single payload this project builds. Every boot image it produces wraps the
    volume one layer deeper: the kernel is a BootShim payload holding an FD, the FD holds
    `FVMAIN_COMPACT`, and the volume is the decompressed image inside that. `ANDROID! header but
    no volume in its first 128 KiB` is what the two-shape reader says about all of them.

    So this delegates to `tools/fv-inventory.py`, which reads all three (and prints its own
    walk banner while doing it, hence the redirect). The bare-volume and bare-FD cases are kept
    because the extraction steps work on exactly those.
    """
    import contextlib
    import importlib.util
    import io

    spec = importlib.util.spec_from_file_location("fvi", os.path.join(HERE, "fv-inventory.py"))
    fvi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fvi)

    d = open(path, "rb").read()
    if d[:8] == b"ANDROID!":
        with contextlib.redirect_stdout(io.StringIO()):
            _rows, _len, _offsets, inner = fvi.unpack(path)
        if inner is None:
            sys.exit("%s: boot image with no inner volume" % path)
        return inner
    if d[0x28:0x2C] == b"_FVH":
        return d
    if b"_FVH" in d:
        # A bare FD: the volume is somewhere inside it rather than at 0x28.
        sig = d.find(b"_FVH")
        return d[sig - 0x28:]
    sys.exit("%s: no _FVH anywhere in the file - not a firmware volume" % path)


def objdump():
    for cand in ("aarch64-linux-gnu-objdump", "llvm-objdump", "objdump"):
        p = shutil.which(cand)
        if p:
            return p
    sys.exit("no objdump on PATH - install binutils-aarch64-linux-gnu or llvm")


def disassemble(path):
    out = subprocess.run([objdump(), "-d", path], capture_output=True, text=True).stdout
    ins = []
    for line in out.splitlines():
        m = INSN.match(line)
        if m:
            ins.append((int(m.group(1), 16), m.group(3), m.group(4).strip()))
    return ins


def rva_range(blob, rva):
    """The file offset an RVA maps to, through the PE section headers."""
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    if blob[pe:pe + 4] != b"PE\0\0":
        return None
    nsec = struct.unpack_from("<H", blob, pe + 6)[0]
    optsz = struct.unpack_from("<H", blob, pe + 20)[0]
    for k in range(nsec):
        o = pe + 24 + optsz + k * 40
        vsz, va, rsz, ptr = struct.unpack_from("<IIII", blob, o + 8)
        if va <= rva < va + max(vsz, rsz):
            return ptr + (rva - va)
    return None


def guid_at(blob, off):
    if off is None or off + 16 > len(blob):
        return None
    return str(uuid.UUID(bytes_le=blob[off:off + 16])).upper()


def register_values(ins, upto, back=8):
    """Every argument register whose value the preceding `ADRP`/`ADD` pair fixes, at `upto`.

    `ADRP` gives a 4 KiB-aligned page and the `ADD` beside it the offset within the page; the
    pair is how AArch64 materialises a static address, and it is the only way this tool needs to
    understand. The window is deliberately short: a register whose value was set forty
    instructions ago belongs to some other call, and reporting it would put a GUID in the
    argument list that the call never sees.
    """
    vals = {}
    for i in range(max(0, upto - back), upto):
        mn, ops = ins[i][1], ins[i][2]
        m = re.match(r"(x\d+), (0x[0-9a-f]+)$", ops) if mn == "adrp" else None
        if m:
            vals[m.group(1)] = int(m.group(2), 16)
            continue
        m = re.match(r"(x\d+), (x\d+), #0x([0-9a-f]+)$", ops) if mn == "add" else None
        if m and m.group(2) in vals:
            vals[m.group(1)] = vals[m.group(2)] + int(m.group(3), 16)
            continue
        m = re.match(r"(x\d+), (x\d+)$", ops) if mn == "mov" else None
        if m and m.group(2) in vals:
            vals[m.group(1)] = vals[m.group(2)]
    return vals


def call_slot(ins, i, reg, back=20):
    """The `EFI_BOOT_SERVICES` offset a `BLR reg` goes through, if it goes through one.

    Two hops: a global holds the table, and the slot is loaded off it - `ldr x8, [x?, #imm]`
    for the table, `ldr x8, [x8, #slot]` for the entry. Only the second answers the question, and
    it is not always the nearest load into that register: the table load sits between the two,
    and setting up a six-argument call puts several instructions in between. So the scan walks
    back over the whole window and prefers a load whose offset is a real slot, falling back to
    the nearest load into the register when none is - which prints as `BS+0x..` and is then
    visibly a miss rather than silently a name.
    """
    nearest = None
    for b in reversed(range(max(0, i - back), i)):
        m = re.match(r"%s, \[(\w+), #(\d+)\]$" % re.escape(reg), ins[b][2])
        if not m:
            continue
        off = int(m.group(2))
        if off in BOOT_SERVICES:
            return off
        if nearest is None:
            nearest = off
    return nearest


def analyse(section, blob, target, names):
    """Every reference to `target` in one extracted image, with the hand that holds it."""
    d = open(section, "rb").read()
    guids = uuid.UUID(target).bytes_le

    def file_rva(off):
        """File offset -> RVA, through the PE section headers."""
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        if d[pe:pe + 4] != b"PE\0\0":
            return None
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        optsz = struct.unpack_from("<H", d, pe + 20)[0]
        for k in range(nsec):
            o = pe + 24 + optsz + k * 40
            vsz, va, rsz, ptr = struct.unpack_from("<IIII", d, o + 8)
            if ptr <= off < ptr + rsz:
                return va + (off - ptr)
        return None

    # every occurrence, not just the first: a GUID can be defined twice in one image - once in
    # `.data` for the code and once in a read-only table - and a first-only scan would report
    # the references to one of them and silently miss the other.
    rvas = []
    at = d.find(guids)
    while at >= 0:
        r = file_rva(at)
        if r is not None:
            rvas.append(r)
        at = d.find(guids, at + 1)
    if not rvas:
        return []

    ins = disassemble(section)
    out = []
    for i, (addr, mn, ops) in enumerate(ins):
        if mn != "adrp":
            continue
        m = re.match(r"(x\d+), (0x[0-9a-f]+)$", ops)
        if not m or int(m.group(2), 16) not in {r & ~0xFFF for r in rvas}:
            continue
        # does this page-plus-offset pair land on one of the GUID's addresses, within the next
        # few instructions?
        j = i
        for k in range(i + 1, min(i + 5, len(ins))):
            if ins[k][1] == "add" and re.match(r"%s, %s, #0x([0-9a-f]+)$"
                                               % (m.group(1), m.group(1)), ins[k][2]):
                whole = int(m.group(2), 16) + int(re.search(r"#0x([0-9a-f]+)$",
                                                            ins[k][2]).group(1), 16)
                if whole in rvas:
                    j = k
                break
        if j == i:
            continue
        # the call this materialisation is an argument to
        for k in range(j, min(j + 16, len(ins))):
            if ins[k][1] != "blr":
                continue
            reg = ins[k][2]
            slot = call_slot(ins, k, reg)
            api = BOOT_SERVICES.get(slot, "BS+%#x" % slot if slot is not None else "?")
            vals = register_values(ins, k)
            others = []
            for r, v in sorted(vals.items(), key=lambda kv: int(kv[0][1:])):
                # x0 holds the target GUID at a `LocateProtocol` and the handle at an install,
                # so it is never a *second* GUID worth printing; and only GUIDs the tree can
                # name are printed, because an unaligned or stale register resolves to sixteen
                # arbitrary bytes and printing those is how a scan grows confident about noise.
                if r == "x0" or int(r[1:]) > 6:
                    continue
                g = guid_at(d, rva_range(d, v))
                if g and g in names and set(g.replace("-", "")) != {"0"}:
                    others.append("%s=&%s" % (r, names[g][0]))
            out.append((addr, api, others))
            break
    return out


def report(module, ident, refs, names):
    """One image's references, in the shape both modes print.

    `ident` is the FFS file GUID for a volume walk and the occurrence count for a bare
    directory of `PE32`s, where there is no FFS header to resolve to a GUID.
    """
    if not refs:
        print("  %-22s %s  (no resolved call site - reference is not an argument)"
              % (module, ident))
    for addr, api, others in refs:
        verdict = ("publishes" if api in PUBLISHES else
                   "consumes" if api in CONSUMES else "?")
        print("  %-22s %s  VA %#07x  %-34s %s%s"
              % (module, ident, addr, api, verdict,
                 "   " + ", ".join(others) if others else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("guid", help="the GUID whose references are wanted")
    ap.add_argument("volumes", nargs="*", help="firmware volume, or boot image holding one")
    ap.add_argument("--extracted", metavar="DIR",
                    help="a directory of bare PE32 images (e.g. device/dxe) instead of a volume")
    ap.add_argument("--tree", default=os.path.join(ROOT, "work", "uefi", "Mu-Silicium"),
                    help="tree the module and protocol names come from")
    ap.add_argument("--keep", help="write the extracted PE32 sections here")
    args = ap.parse_args()

    if not args.volumes and not args.extracted:
        ap.error("give at least one volume, or --extracted DIR")

    target = str(uuid.UUID(args.guid)).upper()
    census, fvap = load_helpers()
    names = census.inf_and_pi_names(args.tree)
    raw = uuid.UUID(target).bytes_le
    print("target %s  (%s)" % (target, names.get(target, ("unnamed in this tree", ""))[0]))

    for path in args.volumes:
        d = read_volume(path)
        tag = os.path.basename(path)
        print("\n=== %s: %d occurrences of the 16 bytes" % (path, d.count(raw)))
        tmp = args.keep or tempfile.mkdtemp(prefix="guid-refs.")
        os.makedirs(tmp, exist_ok=True)
        for off, fg, typ, size in fvap.walk_volume(d):
            body = d[off + 24:off + size]
            if raw not in body:
                continue
            module = names.get(fg, (fg, ""))[0] or fg
            for styp, _ssz, spay in census.sections(body):
                if styp == 0x10 and raw in spay:
                    out = os.path.join(tmp, "%s-%s.efi" % (module, tag))
                    open(out, "wb").write(spay)
                    report(module, fg[:8], analyse(out, d, target, names), names)
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)

    if args.extracted:
        # A bare `.efi` is already a PE32, so nothing is extracted or written here; the
        # name is the file name, which for this project's extraction is the driver's own.
        files = sorted(f for f in os.listdir(args.extracted) if f.endswith(".efi"))
        hits = [f for f in files
                if raw in open(os.path.join(args.extracted, f), "rb").read()]
        print("\n=== %s: %d PE32 files, %d carry the 16 bytes"
              % (args.extracted, len(files), len(hits)))
        for f in hits:
            p = os.path.join(args.extracted, f)
            module = f[:-4]
            report(module, "x%d" % open(p, "rb").read().count(raw),
                   analyse(p, None, target, names), names)

    print("\n  a call site is a fact about the binary; whether it executes is a run-time")
    print("  question this tool does not answer.")


if __name__ == "__main__":
    main()
