#!/usr/bin/env python3
"""Read the bring-up console off a firmware running under QEMU, by sampling its own memory.

The panel is the only channel this firmware has. `SerialPortLib` is bound to
`FrameBufferSerialPortLib` in a DEBUG build, so every `DEBUG ((...))` in the tree
comes out as pixels in the "Display Reserved" region and nowhere else, and every
reading this phase has produced has been a person looking at a screen and typing
back what they saw - which is why `panel-text.py` exists and why its history is a
list of mis-transcriptions.

The screen is not the only thing that holds those pixels. Under QEMU the firmware
runs in a process that can dump its own memory, so the same console can be read
without a photograph, without a phone, and without a transcription: dump the region
`GetFrameBufferMemory` prints into and hand it to `panel-text.py --fb`, which
decodes it exactly - the values are only 0 and 1 and the origin is known, so there
is nothing to estimate.

What this tool adds is the part the console makes hard: **a dump is one screen and
not the log.** When the cursor passes the last row, `AdvanceNewLine` zeroes the
whole buffer rather than scrolling, so a log longer than the panel is read as the
last 100 printed rows and never the first. Every run of this payload so far has
been the other case - 92 rows of log onto a 100-row screen, so the screen holds the
whole log from its first row and each sample is the previous one extended, which is
what lets the record read as one continuous stream. Either way the region is
sampled repeatedly and the screens are joined on content (`panel-text.py`'s
`fb_overlap`), which recovers the stream as long as consecutive samples share a
line. At `PcdFrameBufferDelay` 10000 us per newline a full screen takes about a
second, so the default quarter-second interval has room to spare.

A sample that joins onto nothing is reported and not spliced over, and the report
says which of two things it was, because they are not the same finding: a row the
console rewrote in place (a line printed without a newline, so the next print
continues on its row) shows up as a screen the stream already holds most of, and
appending it duplicates the log while losing nothing; a screen of rows the stream
does not hold is text printed between two samples, and that is a hole.

The region's address and length are read out of the platform's `MemoryMapLib.c` and
not passed in, for the same reason `panel-text.py` reads the font out of `Font.h`:
a remembered 0xA0000000 is a guess that stops being true silently.

    # launch the payload and sample it for a minute
    tools/qemu-panel-read.py --kernel /tmp/gauguin-kernel.raw --seconds 60

    # the same, under an EL3 that exists, so an SMC returns instead of faulting
    tools/qemu-panel-read.py --kernel /tmp/gauguin-kernel.raw --el3-stub --seconds 60

    # and with an address the machine does not decode reading as zero, so that a
    # driver which reads a pointer out of one can be got past
    tools/qemu-panel-read.py --kernel /tmp/gauguin-kernel.raw --el3-stub \
        --el3-zero-mem --seconds 60

    # or attach to a QEMU already running with -monitor unix:/tmp/qmon.sock,...
    tools/qemu-panel-read.py --socket /tmp/qmon.sock --seconds 60

The output file carries the run's provenance - payload hash, the command line, the
region, the sample count, the gaps - because a boot log with no record of what was
booted is a paragraph someone typed.
"""

import argparse
import hashlib
import importlib.util
import io
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEFAULT_MU = os.path.join(REPO, "work", "uefi", "Mu-Silicium")
PANEL_TEXT = os.path.join(REPO, "tools", "panel-text.py")
# Where BootShim expects to be loaded. `_Payload` is copied from here to the FD
# base in the header it carries, so this is an address the payload names itself
# rather than one chosen for it - see the REQUIRES_KERNEL_HEADER block.
DEFAULT_LOAD_ADDR = 0x48000000
# How far above the stub the payload is placed. The stub is 16 KB with the
# stage-2 tables in it and under 5 KB without, so this is alignment slack rather
# than a fit, and it keeps the two apart by more than either can grow into.
STUB_GAP = 0x10000

# The address EnvDxe reads at Apriori slot 2 and cannot get under `virt`.
#
# The address is not a guess and not a constant of the tool's own choosing: it is
# in the driver's image. EnvDxe loads 0x01F00000 from RVA 0xC7D0, adds the pair
# (0x0D4000, 0x0D4004) from RVA 0xC7F4, and dereferences the sum, and the `ldr`
# that faults has 0x1FD4000 in FAR - the two agree, and `qemu-el3-stub.S` carries
# the same derivation. It is *inside* `TCSR_TCSR_REGS`, 0x01FC0000 for 0x40000,
# which this board's memory map declares; so is the second address the guest
# stops on, 0x0C264000, which is `PSHOLD`. Both aborts are EC 0x25 with DFSC
# 0b010000 - a synchronous external abort, which is a bus with nothing at the
# address, not a translation fault, which is what an unmapped region looks like.
# So this is kept as the spot the read-back checks, and not as the one address the
# instrument aims at - see LOW_MMIO_LIMIT.
ZERO_MEM_IPA = 0x01FD4000

# Everything at or above this is left alone by the stage-2 instrument, and
# everything below it that the platform's memory map declares is backed with RAM.
#
# The line is not arbitrary. It is where `-M virt`'s own RAM begins, so a
# redirect destination below it would be RAM the guest can also reach by identity;
# and it is where this platform's DDR ends and its register blocks stop: every
# register region in `device/config/uefiplat.cfg` is below 0x40000000, and the
# only DDR region below it is `LLCC0` at 0x09200000.
LOW_MMIO_LIMIT = 0x40000000

# The pool the redirected blocks are pointed at: `-M virt`'s RAM base, below the
# payload's own load address, so the blocks are real memory nothing else claims.
# `l2_plan` assigns them densely from here and refuses to run if they would reach
# the payload.
ZERO_MEM_POOL_BASE = 0x40000000

# The size of a stage-2 level 2 block, which is what a redirected region is.
STAGE2_BLOCK = 0x200000

# Where `-M virt` puts its own GIC. It is a property of the machine, not of the
# board, and it is read here once so that `REAL_REGIONS`, `REAL_PAGES`,
# `machine_gic` and the header's readback all name the same address. `info mtree
# -f` on this command line gives `gic_dist` at +0, `gic_cpu` at +0x10000,
# `gicv2m` at +0x20000, `gic_viface` at +0x30000, `gic_vcpu` at +0x40000; the
# words `machine_gic` reads are the first and second of those and a probe of the
# hole the third window's IPA lands in.
MACHINE_GIC_BASE = 0x08000000

# How much of that controller there is, and how many CPU interfaces, both read off
# the machine rather than remembered: `GICD_TYPER` byte 0 is `(num_irq / 32) - 1 |
# (num_cpu - 1) << 5` (`arm_gic.c:970-973`), and this machine's own read-back is
# 0x408 - ITLinesNumber 8, CPU count field 0. So 288 interrupts, nine 32-bit
# register words, one CPU interface, which is what the stub programs from EL3 when
# `--el3-gic-secure` is on and what the header checks its own read-back against: a
# wrapped word or a missing CPU interface would be a step of eight interrupts
# mislabeled, and that is a comparison this file can make instead of asserting.
MACHINE_GIC_NUM_IRQ = 288
MACHINE_GIC_WORDS = MACHINE_GIC_NUM_IRQ // 32
MACHINE_GIC_NUM_CPU = 1

# The board windows `-M virt` implements itself, and where it puts them. A region
# named here is *not* pointed at the pool: the 2 MB stage-2 block it occupies is
# pointed at the machine's own device, so the guest's register accesses reach
# hardware that can hold pending state and raise a line. Everything else this
# platform declares below `LOW_MMIO_LIMIT` keeps the RAM model, and the tool says
# so in its own header rather than leaving the difference to be inferred.
#
# The first entry is the one that matters. `APSS_GIC600_GICD` is the board's
# interrupt controller, 0x17A00000..0x17B6FFFF, and `-M virt`'s GICv2 sits at
# 0x08000000 with `gic_dist` at +0, `gic_cpu` at +0x10000 and the rest behind it
# (`info mtree -f`, 4.200). Both are in one 2 MB block, and the board's own
# distributor/CPU-interface spacing is the machine's, so the block maps whole:
# 0x17A00000 -> 0x08000000, 0x17A10000 -> 0x08010000. `APSS_GIC500_GICR` is in the
# same block and is *not* implemented by a GICv2 - 0x17A60000 lands on
# 0x08060000, which `-M virt` has nothing at, the same zero an untouched pool
# block reads. The payload's own dispatcher takes the V2 path (4.201 read the
# writes), so nothing under this instrument should read it; a run whose payload
# took the V3 path would find no redistributor here and that is a limit of the
# machine, not a finding about the board.
REAL_REGIONS = (("APSS_GIC600_GICD", MACHINE_GIC_BASE),)

# Single 4 KB register banks the machine implements at a *board* address, which
# cannot ride along with a block alias because the board address is not inside the
# aliased block. There is exactly one, and it is the reason this file has a level
# 3 table at all.
#
# The GICv2 CPU interface is programmed at `PcdGicInterruptInterfaceBase`, and
# that PCD is **0**: `BitraPkg.dsc.inc:45-46` overrides the distributor and the
# redistributor bases and does not override this one, so it stays at
# `ArmPkg.dec:284`'s default 0. 4.201 confirmed it by execution - the writer
# stored ICCBPR, ICCPMR and ICCICR at base 0 and ICDDCR at 0x17A00000. Under the
# RAM model that base is block 0 of the pool, which is where a CPU interface goes
# to be forgotten: the distributor can be told to forward and the CPU end can
# never be told to receive. `-M virt`'s GICv2 has `gic_cpu` at 0x08010000, so IPA
# page 0 is aliased there and the rest of block 0 - `GCC CLK CTL` at 0x00100000,
# which the clock driver reads back - keeps its pool page, page for page.
REAL_PAGES = ((0x00000000, 0x08010000, "PcdGicInterruptInterfaceBase"),)

# The seed's own numbers, as names in `qemu-el3-stub.S`. Naming what to read is
# the whole of this file's list: the values themselves are read out of the
# assembled object, so an edit to the assembly that this file does not follow
# shows up as a mismatch rather than as two files agreeing on a stale number.
STUB_SEED_CONSTS = (
    "SEED_SMEM_OFF", "SEED_SMEM_MAGIC", "SEED_SMEM_FLAG_OFF",
    "SEED_SMEM_FLAG", "SEED_SMEM_PART_OFF", "SEED_SMEM_PART_SIZE",
    "SEED_SMEM_PART_MAGIC", "SEED_SMEM_TOC_MAGIC",
    "SEED_SMEM_TOC_VERSION", "SEED_SMEM_ENTRY_HOST", "SEED_SMEM_ENTRY_DIV",
    "SEED_SMEM_BLOCK_TAG", "SEED_SMEM_BLOCK_SIZE",
    "SEED_SMEM_PTABLE_MAGIC0", "SEED_SMEM_PTABLE_MAGIC1",
    "SEED_SMEM_PTABLE_ENTRIES", "SEED_SMEM_TABLE_REL",
    "SEED_AOP_REC_OFF")

# How far past the SMEM word the fabricated target-info structure goes. Same
# name, same job, and the same rule as the tuple above: this is the stub's
# number, used here only to say what was asked for. Every check compares
# against `sc[...]`, which is the assembler's copy.
SEED_SMEM_OFF = 0x10

# The magic `EnvDxe` compares the structure's first word against, read off its
# own image at RVA 0x9530 (`mov w13,#0x4953; movk w13,#0x4949,lsl #16`) and
# carried in `qemu-el3-stub.S` as SEED_SMEM_MAGIC. Used here only to check the
# read-back; the write is the stub's.
SEED_SMEM_MAGIC = 0x49494953

# The word EnvDxe reads out of SMEM itself, at SMEM + this offset, and compares
# against 1 - `ldr w9,[x8,#192]; cmp w9,#1; b.ne <assert>` at RVA 0x823C, which
# is `smem.c +671` "SMEM is not initialized by Boot." The stub writes it; this
# is the offset the read-back fetches it from, and it is named in
# `qemu-el3-stub.S` as SEED_SMEM_FLAG_OFF.
SEED_SMEM_FLAG_OFF = 0xC0

# What that word has to be. It is 1 on the device because XBL put it there.
SEED_SMEM_FLAG = 1

# The three places in CmdDbDxe that say what its entry gate wants, and the region
# the word lives in. This is the second thing the instrument fabricates, and the
# numbers are decoded out of the driver's own instructions rather than typed in as
# values: `0x45c0: mov w8,#0xc; movk w8,#0xc3f,lsl #16; ldr w0,[x8]` is the read,
# `0x256c: cmp w9,#1` and `0x2578: mov w11,#0x30db; movk w11,#0xc03,lsl #16` are
# the two comparisons the word's target is put to. The instruction at 0x2568 is
# `ldr w9,[x8]`, which is the part that is easy to get wrong: the word at
# 0x0C3F000C is a *pointer*, and the state and the magic are at *it* and four
# bytes past it - not at 0x0C3F0010, which nothing in any image reads.
#
# The RVAs are this platform image's. The same gate is at 0x45c0 in the gauguin,
# cepheus, nabu, miatoll and vayu images and at 0x41a0 or 0x48ec in others, so an
# RVA that is right for one device is wrong for another - which is why the bytes
# at these three are decoded and the shape of the instruction is required, rather
# than the value being read out of whatever happens to be there. A `--platform`
# pointing at a package whose CmdDbDxe is laid out differently stops the run with
# a message saying so; it does not seed a number nothing compares against.
AOP_GATE_RVA = 0x45C0
AOP_STATE_RVA = 0x256C
AOP_MAGIC_RVA = 0x2578

# The window the mailbox word is in, by the name this platform's own memory map
# gives it. Looked up rather than written down for the same reason SMEM's base and
# size are: the board declares it, and the seed is only faithful if it is written
# inside the region the board says is there.
AOP_REGION = "AOP_SS_MSG_RAM"

# How far past the mailbox word the record it points at goes. The same number is
# in `qemu-el3-stub.S` as SEED_AOP_REC_OFF and it is there that it decides
# anything; here it is what this end asks the stub for and what the read-back
# compares the stub's own arithmetic against, so the copy cannot go stale in
# silence. Eight is the smallest offset that keeps the pair 8-byte aligned, which
# the four-byte stores do not need but the qword read-back prefers.
AOP_REC_OFF = 8

# A stage-2 level 2 table has 512 entries covering the low gigabyte.
STAGE2_L2_ENTRIES = 512


def die(msg):
    sys.exit(f"qemu-panel-read: {msg}")


def load_panel_text():
    """`panel-text.py` as a module, so there is one decoder and not two.

    Read by path rather than imported by name because it is a script in `tools/`
    and this is another one; a second font parser here would be a second answer to
    what the screen says.
    """
    spec = importlib.util.spec_from_file_location("panel_text", PANEL_TEXT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def platform_paths(mu, pkg):
    """(the package directory, its DSC) for a platform, defaulting to gauguin.

    Two files, one place: `panel-text.py` wants the DSC and the memory map is
    beside it, and deriving the second from the first is what keeps a `--platform`
    pointing at one device rather than a pair that can disagree.
    """
    pkg = pkg or os.path.join(mu, "Platforms", "Xiaomi", "gauguinPkg")
    base = os.path.basename(pkg.rstrip("/"))
    dsc = os.path.join(pkg, base[:-3] + ".dsc" if base.endswith("Pkg") else base + ".dsc")
    if not os.path.exists(dsc):
        die(f"no DSC at {dsc} - --platform takes a package directory such as"
            f" Platforms/Xiaomi/gauguinPkg")
    return pkg, dsc


def platform_binaries(mu, pkg, *parts):
    """A path under the prebuilt tree for this platform.

    `Platforms/Xiaomi/gauguinPkg` and `Binaries/gauguin/QcomPkg/...` are the same
    device spelled two ways, and the second is derived from the first rather than
    passed in beside it so that a `--platform` cannot point the memory map at one
    device and the driver image at another.
    """
    device = os.path.basename(pkg.rstrip("/"))
    if device.endswith("Pkg"):
        device = device[:-3]
    return os.path.join(mu, "Binaries", device, *parts)


def mmap_region(pkg, name, why=""):
    """(base, size) of a region this platform's own memory map declares.

    The map is `MemoryMapLib.c`, one line a region, the name first and the two
    numbers next. Read here rather than written down for the third time: the
    framebuffer, SMEM and the AOP mailbox are all regions of this board, and a
    remembered address is a guess that stops being true in silence.

    `why` is what the caller adds to the failure: the map's silence means
    different things to a region the console draws into and a region a driver
    parses a fabricated structure into, and the sentence that says which is the
    caller's.
    """
    path = os.path.join(pkg, "Library", "MemoryMapLib", "MemoryMapLib.c")
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        die(f"cannot read the platform memory map at {path}: {exc}")
    m = re.search(r'\{\s*"' + re.escape(name) + r'"\s*,\s*(0x[0-9A-Fa-f]+)\s*,'
                  r'\s*(0x[0-9A-Fa-f]+)', text)
    if not m:
        die(f"{os.path.relpath(path, REPO)} declares no \"{name}\" region{why}")
    return int(m.group(1), 16), int(m.group(2), 16)


def _movz_movk(blob):
    """The 32-bit value a `mov`/`movk` pair builds, or None if it is not one.

    A 32-bit MOVZ is `0b0_10_100101` in bits 31:23 and a MOVK `0b0_11_100101`,
    with the immediate in bits 20:5 and its shift in 22:21. Telling the two apart,
    reading them, and requiring them to name the same register is what lets this
    file read a value out of an image instead of trusting an address: None means
    the bytes at the RVA are not the pair this file cites, and the caller stops
    rather than reading a number out of unrelated instructions.
    """
    if len(blob) < 8:
        return None
    lo, hi = struct.unpack("<II", blob[:8])
    if (lo >> 23) & 0x1FF != 0x0A5 or (hi >> 23) & 0x1FF != 0x0E5:
        return None
    if (lo & 0x1F) != (hi & 0x1F):
        return None
    value = 0
    for word in (lo, hi):
        value |= ((word >> 5) & 0xFFFF) << (((word >> 21) & 0x3) * 16)
    return value


def _cmp_imm(word):
    """`(register, immediate)` of a 32-bit `cmp wN, #imm`, or None.

    A 32-bit SUBS-immediate with Rd = 31, which is what the assembler emits for
    `cmp`: bits 31:24 are 0x71, bits 4:0 are 0x1F, the register is in 9:5 and the
    immediate in 21:10.
    """
    if (word >> 24) != 0x71 or (word & 0x1F) != 0x1F:
        return None
    return (word >> 5) & 0x1F, (word >> 10) & 0xFFF


def aop_gate(mu, pkg):
    """`(ipa, state, magic, region)` for CmdDbDxe's entry gate, from its image.

    Every number here is read out of the driver's own instructions - the address
    out of the `mov`/`movk` pair at `AOP_GATE_RVA`, the state out of the `cmp` at
    `AOP_STATE_RVA`, the magic out of the pair at `AOP_MAGIC_RVA` - so what the
    seed writes is what the driver compares against, and a rebuild that moved any
    of the three stops this run instead of seeding a value nothing checks. The
    region is the board's own declaration of the window that address is in, and
    the address has to be inside it: outside, the seed would be writing to a
    region the memory map does not have, which is a claim about this machine that
    nothing in the tree supports.
    """
    path = platform_binaries(mu, pkg, "QcomPkg", "Drivers", "CmdDbDxe",
                             "CmdDbDxe.efi")
    try:
        with io.open(path, "rb") as fh:
            img = fh.read()
    except OSError as exc:
        die(f"reading the driver under test needs its image at {path}: {exc}")

    def at(rva, n, what):
        if rva + n > len(img):
            die(f"{os.path.relpath(path, REPO)} is {len(img):#x} bytes and has"
                f" nothing at {rva:#x} for {what}; the RVAs in this file are the"
                f" gauguin image's and this is another device's")
        return img[rva:rva + n]

    ipa = _movz_movk(at(AOP_GATE_RVA, 8, "the mailbox address"))
    if ipa is None:
        die(f"{os.path.relpath(path, REPO)} has no `mov`/`movk` pair at"
            f" {AOP_GATE_RVA:#x}, so the address this file says the gate reads is"
            f" not what that image does; re-read the RVAs before running rather"
            f" than seeding a word nothing looks at")
    pair = _cmp_imm(struct.unpack("<I", at(AOP_STATE_RVA, 4,
                                          "the state comparison"))[0])
    if pair is None or pair[1] == 0:
        die(f"{os.path.relpath(path, REPO)} has no `cmp wN, #imm` at"
            f" {AOP_STATE_RVA:#x}, or an immediate of zero, so the state the gate"
            f" requires is not in this image where this file says it is")
    state = pair[1]
    magic = _movz_movk(at(AOP_MAGIC_RVA, 8, "the magic"))
    if magic is None:
        die(f"{os.path.relpath(path, REPO)} has no `mov`/`movk` pair at"
            f" {AOP_MAGIC_RVA:#x}, so the value it compares the record's second"
            f" word against is not in this image where this file says it is")

    base, size = mmap_region(pkg, AOP_REGION)
    if not base <= ipa < base + size:
        die(f"the gate reads {ipa:#x}, which is not inside this board's"
            f" \"{AOP_REGION}\" region {base:#x}..{base + size:#x} as its own"
            f" memory map declares it; the seed would be writing a window the"
            f" board does not have and nothing here would be modelling the device")
    return ipa, state, magic, (base, size)


def fb_region(pkg):
    """(name, base, length) of the framebuffer, out of the platform's memory map.

    The console finds its buffer with `LocateMemoryRegionByName ("Display
    Reserved", ...)`, so the region that matters is the one the platform declares
    under that name. Both spellings are in the tree - the library is tried with
    each in turn - so either matches.
    """
    path = os.path.join(pkg, "Library", "MemoryMapLib", "MemoryMapLib.c")
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        die(f"cannot read the platform memory map at {path}: {exc}")
    m = re.search(r'\{\s*"Display[_ ]Reserved"\s*,\s*(0x[0-9A-Fa-f]+)\s*,'
                  r'\s*(0x[0-9A-Fa-f]+)', text)
    if not m:
        die(f"{os.path.relpath(path, REPO)} has no \"Display Reserved\" region - the"
            f" console would have nothing to print into, so this tool's whole"
            f" premise needs rechecking before its numbers are used")
    return "Display Reserved", int(m.group(1), 16), int(m.group(2), 16)


class Monitor:
    """QEMU's monitor, one command at a time, waiting for the prompt.

    The prompt and not a sleep: `pmemsave` of a few megabytes takes as long as it
    takes, and a sampler that guesses has to guess long enough for the worst case
    and therefore samples the console more slowly than it could. Readline's echo
    and bracketed-paste noise are stripped, because a command is recognised by its
    result and not by its own echo coming back.
    """

    def __init__(self, path, timeout=10.0):
        self.s = socket.socket(socket.AF_UNIX)
        deadline = time.time() + timeout
        while True:
            try:
                self.s.connect(path)
                break
            except OSError:
                if time.time() > deadline:
                    die(f"no QEMU monitor at {path} after {timeout:.0f}s - pass"
                        f" --launch, or start QEMU with -monitor unix:{path},"
                        f"server=on,wait=off")
                time.sleep(0.1)
        self.s.settimeout(timeout)
        self._read_until_prompt()

    def _read_until_prompt(self, timeout=10.0):
        buf = b""
        end = time.time() + timeout
        while time.time() < end:
            self.s.settimeout(max(0.05, end - time.time()))
            try:
                chunk = self.s.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            if buf.rstrip().endswith(b"(qemu)"):
                break
        return re.sub(rb"\x1b\[[0-9;]*[A-Za-z]", b"", buf).decode("latin1", "replace")

    def cmd(self, text, timeout=10.0):
        self.s.sendall(text.encode() + b"\n")
        return self._read_until_prompt(timeout)


def launch(kernel, sock, machine, memory, load_addr, extra, stub=None):
    """Start QEMU with the payload loaded where BootShim expects it.

    `-device loader,force-raw=on` and not `-kernel`: this is not an ELF and not a
    Linux image, it is the raw BootShim + FD that Android's boot image carries, and
    QEMU's `-kernel` would try to find a header in it. The `-M virt` flat RAM is
    what makes the platform's fixed addresses (FD 0x9FC00000, DXE heap 0x9B800000,
    Display Reserved 0xA0000000) reachable at all.

    `-serial none` and `-display none` because the console is in memory and
    `pmemsave` is how it is read; a serial port here would be a second, emptier
    channel that invites the wrong conclusion when it stays silent.

    With `stub`, the EL3 stub is the thing QEMU resets into and the payload is
    loaded one gap above it, so that the stub's `eret` is what starts the
    firmware. Only then is `cpu-num=0` the stub's and not the payload's.
    """
    argv = ["qemu-system-aarch64", "-M", machine, "-cpu", "max", "-m", str(memory),
            "-nic", "none", "-display", "none", "-serial", "none",
            "-monitor", f"unix:{sock},server=on,wait=off"]
    if stub:
        argv += ["-device", f"loader,file={stub},addr={load_addr:#x},force-raw=on,cpu-num=0",
                 "-device", f"loader,file={kernel},addr={load_addr + STUB_GAP:#x},force-raw=on"]
    else:
        argv += ["-device", f"loader,file={kernel},addr={load_addr:#x},force-raw=on,cpu-num=0"]
    argv += extra
    print("  " + " ".join(argv))
    return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def low_regions(pkg):
    """Every region the platform's own memory map puts below `LOW_MMIO_LIMIT`.

    Read out of the *generated* `MemoryMapLib.c` and not out of the generator's
    input, because the claim this list supports is about the firmware under test:
    what it believes it has is what its own map says, and a table built from the
    configuration instead would be modelling the intent rather than the image.

    Both classes come back: register regions, which under `virt` have nothing at
    them at all, and any DDR region down here - `LLCC0` is one - which has nothing
    at it either. They are handed back the same way because the machine cannot
    reach the difference, and because giving each its own RAM makes a DDR region
    behave like memory rather than like a register file that reads zero.
    """
    path = os.path.join(pkg, "Library", "MemoryMapLib", "MemoryMapLib.c")
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        die(f"cannot read the platform memory map at {path}: {exc}")
    found = re.findall(r'\{\s*"([^"]+)"\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)',
                       text)
    regions = [(n, int(b, 16), int(s, 16)) for n, b, s in found if int(b, 16) < LOW_MMIO_LIMIT]
    if not regions:
        die(f"{os.path.relpath(path, REPO)} declares nothing below"
            f" {LOW_MMIO_LIMIT:#x}; there is then no reason for --el3-zero-mem to"
            f" exist and the flag is being asked to model a machine this map does"
            f" not describe")
    for n, b, s in regions:
        if s == 0 or b + s > LOW_MMIO_LIMIT:
            die(f"{os.path.relpath(path, REPO)}'s {n} runs {b:#x}..{b + s:#x}, which"
                f" crosses the {LOW_MMIO_LIMIT:#x} line this instrument stops at;"
                f" the partial-block arithmetic below would be wrong and guessing at"
                f" it is worse than stopping")
    return regions


def l2_plan(regions, load_addr):
    """`{block index: scratch address}` for the stage-2 level 2 table.

    One 2 MB block of the pool per 2 MB block of low address that a region
    occupies, assigned densely from `ZERO_MEM_POOL_BASE`. Dense and not
    identity-offset, because the pool has to stay below the payload: the block for
    low address 0x08000000 would land on the payload if the two indices were made
    to agree, and the payload is the one thing here that must not be written.

    Refuses rather than overlaps. A pool that reached the stub or the payload is a
    run whose lie would land on the code under test, and the symptom - a guest
    that dies somewhere else entirely - would look like a finding.
    """
    blocks = sorted({blk for _n, b, s in regions
                     for blk in range(b // STAGE2_BLOCK, (b + s - 1) // STAGE2_BLOCK + 1)})
    top = ZERO_MEM_POOL_BASE + len(blocks) * STAGE2_BLOCK
    if top > load_addr:
        die(f"{len(blocks)} blocks of low memory need"
            f" {len(blocks) * STAGE2_BLOCK:#x} bytes of pool, which runs"
            f" {ZERO_MEM_POOL_BASE:#x}..{top:#x} and reaches the load address"
            f" {load_addr:#x}; the instrument would be writing the payload it is"
            f" meant to be observing")
    return {blk: ZERO_MEM_POOL_BASE + i * STAGE2_BLOCK for i, blk in enumerate(blocks)}


def smem_region(pkg):
    """(base, size) of this board's SMEM, out of the platform's own memory map.

    Read for the same reason `low_regions` reads the map: EnvDxe's SMEM driver
    takes the base and size out of the structure this instrument fabricates, so
    the values have to be the board's declaration and not a guess.

    This is deliberately *not* filtered by `LOW_MMIO_LIMIT`: SMEM is at
    0x80900000, above it, because on this board SMEM is in DDR and not in the
    register space. The stage-2 redirect does not touch it and does not need to -
    `-M virt` backs that address with real RAM, so the driver that maps it gets
    zeroed memory, which is what a machine with no secure world would have there.
    """
    return mmap_region(pkg, "SMEM", ", so this board's SMEM base and size are not"
                                  " in the tree and the structure EnvDxe parses"
                                  " would have to be invented rather than"
                                  " transcribed; stopping rather than seeding a"
                                  " number nothing in the tree says")


# The machine's own controller, and the registers of it whose values decide
# whether the alias did anything. Read out of the machine at the end of the run
# with the same `pmemsave` the stage-2 tables are read with, because "the block
# points at the machine's GIC" and "the guest's writes reached it" are two claims
# and only the second one is about the guest. The distributor's first page and the
# CPU interface's are read separately: `-M virt` puts them 64 KB apart, which is
# the spacing the board uses too, and that spacing is exactly why one 2 MB block
# alias can serve both.
#
# The three that matter most. The enable set over the machine's whole interrupt
# range, because word 0 holds the bits for every interrupt ID below 32 - which is
# every PPI and SGI, and the ARM generic timer is a PPI - so it is where the
# payload's own numbering would show, and the SPIs above it are where a
# controller's line lives if the payload registers one at all. The pending set,
# which says which of them the machine has raised. And the priority mask, which
# without a secure world's help decides on its own that nothing is ever delivered.
# The caveat that came out of the first run with real hardware behind these rows:
# `pmemsave` carries QEMU's unspecified transaction attributes and this machine has
# the security extensions on (`-M virt,secure=on` -> `hw/arm/virt.c:754`), so every
# word below is read as a NON-SECURE access. `GICD_IGROUPR` is RAZ/WI for such an
# access by definition (`arm_gic.c:988-993`), `GICD_ISENABLER` and `GICD_ISPENDR`
# return only the Group-1 bits (`:1019-1022`), and a priority mask in the lower half
# reads zero (`:712-725`) - so a zero in any of those rows is the non-secure view
# and is *not* proof that the payload wrote nothing. `GICD_ISPENDR0` otherwise says
# which of them the machine has raised. A line raised and not enabled is the
# difference between a controller that works and a number that does not match, and
# no amount of reasoning about the firmware's PCDs can tell those two apart from
# the guest's side. What *does* separate "the writes arrived and were refused" from
# "the writes never happened" is the pair of words that are non-secure-writable
# anyway - `GICD_CTLR`'s Group-1 enable bit (`:1202-1209`) and `GICC_CTLR`'s
# (`:748-757`) - because those two are the ones that read back set.
GIC_DIST_WORDS = ((0x000, "GICD_CTLR"), (0x004, "GICD_TYPER"),
                  (0x008, "GICD_IIDR"), (0x080, "GICD_IGROUPR0"),
                  (0x180, "GICD_ICENABLER0"),
                  (0x280, "GICD_ICPENDR0"),
                  (0x300, "GICD_ISACTIVER0"), (0xC00, "GICD_ICFGR0"),
                  (0xC04, "GICD_ICFGR1")) + tuple(
                      # The enable and pending sets over the machine's whole
                      # interrupt range and not only word 0. Word 0 is where the
                      # firmware's own numbering would show, because every PPI and
                      # SGI is in it and the ARM generic timer is a PPI; the words
                      # above it are the SPIs, which is where a controller's line
                      # lives if the firmware registers one at all. Reading one
                      # word and not the rest would make a zero ambiguous between
                      # "not enabled" and "not read".
                      (0x100 + 4 * i, f"GICD_ISENABLER{i}")
                      for i in range(MACHINE_GIC_WORDS)) + tuple(
                      (0x200 + 4 * i, f"GICD_ISPENDR{i}")
                      for i in range(MACHINE_GIC_WORDS))
GIC_CPU_WORDS = ((0x000, "GICC_CTLR"), (0x004, "GICC_PRIMASK"),
                 (0x008, "GICC_BPR"), (0x00C, "GICC_IAR"),
                 (0x014, "GICC_RPR"), (0x018, "GICC_HPPIR"))


def gic_intids(gw, kind):
    """The interrupt IDs the machine's own enable or pending set holds.

    `kind` is `ISENABLER` or `ISPENDR`. These are non-secure reads, so on a
    TZ-aware GIC what comes back is the Group-1 bits only (`arm_gic.c:1019-1022`)
    - which under `--el3-gic-secure` is every interrupt, because the stub put them
    all in Group 1 before the payload started, and without that flag is nothing at
    all, every bit being Group 0. The two readings of the same rows mean different
    things and the header says which one it is holding.
    """
    v = 0
    for i in range(MACHINE_GIC_WORDS):
        v |= gw[f"GICD_{kind}{i}"] << (32 * i)
    return [i for i in range(MACHINE_GIC_NUM_IRQ) if v >> i & 1]


def gic_set_words(gw, kind):
    """Those words as the machine holds them, high word first."""
    return " ".join(f"{gw[f'GICD_{kind}{i}']:08x}"
                    for i in range(MACHINE_GIC_WORDS - 1, -1, -1))


def intids(ids):
    """An interrupt-ID list as text, or `none` when it is empty."""
    return ", ".join(str(i) for i in ids) or "none"


GIC_PRIO_OFF = 0x400
"""`GICD_IPRIORITYR0` - one byte per interrupt, the machine's whole interrupt
range in one read. Read as a range and not as words because 72 monitor round
trips to say the same thing is a cost with no answer in it, and because the
question it answers is about individual bytes: a non-secure read of an interrupt's
priority is `(prio << 1) & 0xff` (`arm_gic.c:683-694`), so a byte the payload's own
driver wrote reads back as that value with its low bit cleared and a `0x80` put
there from the secure side reads back as `0x00`."""


def machine_gic(mon):
    """`(words, priorities)` for the machine's GIC, or None if the read failed.

    `words` maps each named 32-bit register below to its value -- a dict, because
    every caller asks for `gw["GICD_ISENABLER3"]` by name and the order of the
    names carries no meaning once they are read -- and `priorities` is the whole
    `GICD_IPRIORITYR` range as bytes, one per interrupt.

    Two physical reads and no interpretation: the distributor's first page at the
    machine's own base and the CPU interface's first page 64 KB above it, plus the
    hole the board's redistributor window was aliased into, which is worth one word
    because "a GICv2 has no redistributor and the alias put that window where the
    machine has nothing" is a claim this instrument makes and can be caught making.
    """
    scratch = tempfile.mkdtemp(prefix="qemu-gic-")
    try:
        got = {}
        for base, off, name in (
                [(MACHINE_GIC_BASE, off, name) for off, name in GIC_DIST_WORDS]
                + [(MACHINE_GIC_BASE + 0x10000, off, name)
                   for off, name in GIC_CPU_WORDS]
                + [(MACHINE_GIC_BASE + 0x60000, 0x000, "GICR window (aliased)")]):
            dump = os.path.join(scratch, "w.bin")
            mon.cmd(f'pmemsave {base + off:#x} 4 "{dump}"', timeout=10.0)
            with open(dump, "rb") as fh:
                blob = fh.read()
            if len(blob) < 4:
                return None
            got[name] = struct.unpack_from("<I", blob, 0)[0]
        dump = os.path.join(scratch, "prio.bin")
        mon.cmd(f'pmemsave {MACHINE_GIC_BASE + GIC_PRIO_OFF:#x}'
                f' {MACHINE_GIC_NUM_IRQ} "{dump}"', timeout=10.0)
        with open(dump, "rb") as fh:
            prio = fh.read()
        if len(prio) < MACHINE_GIC_NUM_IRQ:
            return None
    except (OSError, SystemExit):
        return None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return got, prio


def real_aliases(regions, on):
    """`({block: machine address}, {block: {page: machine address}})`.

    Both empty unless `on`. Derived from the region list rather than written
    beside it: the block is the one the *platform's own map* puts that region in,
    so the alias and the redirect are two answers about the same bytes and they
    cannot drift apart without one of them being visibly wrong about the block
    index. What is *not* derived is the machine address - that is `REAL_REGIONS`
    and `REAL_PAGES`, read out of `-M virt` rather than out of the board, because
    it is a fact about the machine the instrument runs on and not about the phone.

    A block alias and a page alias for the same block would disagree about every
    page the page alias does not name, so that pair is refused rather than
    resolved in favour of one of them.
    """
    if not on:
        return {}, {}
    by_name = {n: (b, s) for n, b, s in regions}
    blocks = {}
    for name, pa in REAL_REGIONS:
        if name not in by_name:
            die(f"the alias table names {name}, and this platform's memory map"
                f" declares nothing by that name below {LOW_MMIO_LIMIT:#x}; pointing"
                f" a block at the machine because a region *should* be there would"
                f" be aliasing a window this firmware does not have")
        b, s = by_name[name]
        for blk in range(b // STAGE2_BLOCK, (b + s - 1) // STAGE2_BLOCK + 1):
            blocks[blk] = pa + blk * STAGE2_BLOCK - b
    pages = {}
    for ipa, pa, why in REAL_PAGES:
        blk, page = ipa // STAGE2_BLOCK, ipa // 0x1000 % (STAGE2_BLOCK // 0x1000)
        if blk in blocks:
            die(f"{why} at {ipa:#x} is in block {blk}, which is aliased whole to"
                f" {blocks[blk]:#x}; a page alias inside a block alias would leave"
                f" every other page of that block pointing at the machine too, and"
                f" the regions sharing the block would be silently aliased with it")
        pages.setdefault(blk, {})[page] = pa
    return blocks, pages


def block_for_ipa(plan, ipa, what):
    """The pool address an address's 2 MB block is redirected to.

    One lookup, and it is a lookup rather than an arithmetic of this file's own
    because the pool is assigned densely and out of order - block 15 of the low
    gigabyte is the 6th block `l2_plan` handed out, not the 16th - so the address
    is a fact about the plan and not something to be recomputed beside it. If the
    block is not in the plan then nothing the guest does at that address reaches
    RAM, and seeding it would be writing bytes into a block no redirect points
    at: a run whose header said it was seeded and whose driver still stopped.
    """
    blk = ipa // STAGE2_BLOCK
    if blk not in plan:
        die(f"{what} is at {ipa:#x}, in block {blk}, which the plan does not"
            f" redirect - the platform's memory map does not declare a region"
            f" there, so a seed written into the pool would never be read and the"
            f" run would stop exactly where an unseeded one does")
    return plan[blk]


def seed_block_for(plan):
    """The pool address the SMEM seed goes in: the block holding `ZERO_MEM_IPA`."""
    return block_for_ipa(plan, ZERO_MEM_IPA, "EnvDxe's SMEM word")


def aop_block_for(plan, ipa, rec_off):
    """The pool block the mailbox word and the record it points at both land in.

    Both, and not just the word: the gate dereferences the word, and this
    instrument reaches the record by writing it through the same redirect, so if
    the record's address were in a different 2 MB block the seed would have to
    write two blocks and the launcher would read two. Requiring them to be one
    block is a property of this seed's choice of record address, and it is checked
    rather than assumed because the pool addresses of two blocks are not related
    to each other in any way a sum could express.
    """
    at = block_for_ipa(plan, ipa, "CmdDbDxe's AOP mailbox word")
    end = ipa + rec_off + 8 - 1
    if end // STAGE2_BLOCK != ipa // STAGE2_BLOCK:
        die(f"the mailbox word is at {ipa:#x} and the record it points at ends at"
            f" {end:#x}, which is past the end of that 2 MB block: the two would"
            f" need different pool blocks, and this seed writes one")
    return at


def build_el3_stub(load_addr, out, zero_mem=False, plan=None, seed=None,
                   aop=None, alias=None, pages=None, gic_secure=False):
    """Assemble `qemu-el3-stub.S` to the addresses the run will use.

    Every address the stub has to agree with is a `--defsym` and not a `.set` in
    the source: the payload's, because the stub's `eret` has to land on the same
    byte the `-device loader` line puts there; its own, because a stage-2 table
    entry is an absolute physical address and the stub is raw bytes at an address
    rather than a linked image; and the address whose stage-2 block is redirected,
    because the same number has to be read back out of the guest afterwards. A
    number written in two files is a number that can differ. The source's own
    header has the argument for existing at all.

    `zero_mem` adds the stage-2 half, which is assembled in or out rather than
    branched over, so a capture with it off is the same capture as before it
    existed. With it on, `plan` is the redirect table `l2_plan` worked out and it
    is written out as `s2_l2.inc` for the source to `.include`: the assembler has
    no way to read a memory map, and a table transcribed into the source by hand
    would be a second description of this machine that could drift from the one
    the firmware was built with.

    The object is *linked* and only then turned into raw bytes, and that is not
    decoration. A PC-relative reference to a global symbol is not something the
    assembler may resolve - the linker could still move it - so `as` emits a
    relocation and leaves the field zero. `objcopy -O binary` on the unlinked
    object therefore produces a stub whose `adr x2, s2_l1` loads the address of
    the `adr` itself: the stage-2 half was inert for two runs, with VTTBR_EL2
    pointing at the stub's own instructions, and the symptom was a boot that
    looked like a stage-2 permission fault. Linking the object is what makes the
    addresses in the binary the addresses the assembly names. Local symbols were
    resolved all along, which is why only the stage-2 half was affected and the
    plain EL3 stub worked.

    `seed` is `(pool block, base, size)` - the address `l2_plan` gave the block
    holding `ZERO_MEM_IPA`, and this board's SMEM region - and passing it is what
    turns SEED_SMEM on. The stub does the rest of the arithmetic: it adds the
    IPA's own offset within its 2 MB and SEED_SMEM_OFF to reach the two places it
    writes, so the offset is written in one file, and the read-back below checks
    the result rather than assuming it. A seed and a redirect are one feature: the
    pool block the seed lands in is reached by the guest only because the redirect
    exists, and a seed with no redirect would be bytes nothing reads.

    The symbol table the launcher reads offsets from stays the object's - a linked
    ELF's symbols are absolute and `stub_symbol`'s offsets would stop being
    offsets - so only the binary comes from the linked image.

    `aop` is `(pool block, ipa, state, magic)` - where the block holding
    `AOP_SS_MSG_RAM` was put, the address `CmdDbDxe` reads, and the two values its
    entry gate compares the pointer's target against - and passing it turns
    SEED_AOP on. It is a second seed and deliberately not folded into the first:
    the two answer different drivers, the first is what gets the boot past Apriori
    slot 2 at all, and a rung that turns both on at once cannot say which of the
    two moved the log. The stub's own header has the argument for why the word is
    a pointer.

    `gic_secure` turns GIC_SECURE on, which is the one flag here that changes the
    *machine* rather than the guest's view of it: the stub programs the
    distributor and the CPU interface from EL3, before `SCR_EL3.NS` is set, with
    what a secure world programs them with and this machine's own reset does not
    (`arm_gic_common.c:279-318`). It takes addresses and counts as defsyms like
    everything else - the machine's GIC base, its CPU interface base, and how many
    interrupts and CPU interfaces `MACHINE_GIC_NUM_IRQ` and `MACHINE_GIC_NUM_CPU`
    say there are - so the stub cannot be assembled against a machine other than
    the one the header reads back.
    """
    src = os.path.join(REPO, "tools", "qemu-el3-stub.S")
    asm = shutil.which("aarch64-linux-gnu-as")
    ld = shutil.which("aarch64-linux-gnu-ld")
    objcopy = shutil.which("aarch64-linux-gnu-objcopy")
    if not asm or not ld or not objcopy:
        die(f"--el3-stub needs an AArch64 binutils ({os.path.basename(src)} is"
            f" assembled and linked with it); aarch64-linux-gnu-as, its ld or its"
            f" objcopy was not on PATH")
    obj = out + ".o"
    elf = out + ".elf"
    defsym = ["--defsym", f"PAYLOAD={load_addr + STUB_GAP:#x}",
              "--defsym", f"EL3_LOAD={load_addr:#x}"]
    include = []
    if zero_mem:
        if not plan:
            die("--el3-zero-mem needs the redirect table it is supposed to"
                " assemble; the caller has to have read a memory map first")
        inc = os.path.join(os.path.dirname(os.path.abspath(out)), "s2_l2.inc")
        alias = alias or {}
        pages = pages or {}
        if len(pages) > 8:
            die(f"{len(pages)} block(s) need a level 3 table and the stub reserves"
                f" 8; the tables start at S2_L3_OFF and each is"
                f" {STAGE2_BLOCK // 0x1000 * 8:#x} bytes, so the ninth would run into"
                f" the rest of the stub")
        l3_off = {blk: n for n, blk in enumerate(sorted(pages))}
        with io.open(inc, "w", encoding="utf-8") as fh:
            fh.write(f"/* GENERATED by tools/qemu-panel-read.py - do not edit by hand.\n"
                     f" *\n"
                     f" * The stage-2 level 2 table for the low gigabyte: identity for\n"
                     f" * every 2 MB block except the"
                     f" {len(plan) - len(alias) - len(pages)} that the\n"
                     f" * platform's own MemoryMapLib.c declares below {LOW_MMIO_LIMIT:#x},\n"
                     f" * which point at {ZERO_MEM_POOL_BASE:#x} + n * {STAGE2_BLOCK:#x}\n"
                     f" * instead, the {len(alias)} the machine implements itself, which\n"
                     f" * point at the machine, and the {len(pages)} that need 4 KB\n"
                     f" * granularity, which point at a level 3 table in s2_l3.inc.\n"
                     f" */\n")
            for i in range(STAGE2_L2_ENTRIES):
                if i in pages:
                    fh.write(f"    .quad EL3_LOAD + S2_L3_OFF"
                             f"{f' + {l3_off[i] * 0x1000:#x}' if l3_off[i] else ''}"
                             f" + 0x3    /* block {i}, {i * STAGE2_BLOCK:#x}"
                             f" - level 3 table */\n")
                elif i in alias:
                    fh.write(f"    .quad S2_BLOCK | {alias[i]:#x}"
                             f"    /* block {i}, {i * STAGE2_BLOCK:#x}"
                             f" - the machine's own device */\n")
                elif i in plan:
                    fh.write(f"    .quad S2_BLOCK | {plan[i]:#x}"
                             f"    /* block {i}, {i * STAGE2_BLOCK:#x} - redirected */\n")
                else:
                    fh.write(f"    .quad S2_BLOCK | {i * STAGE2_BLOCK:#x}\n")
            fh.write("\n")
        if pages:
            l3 = os.path.join(os.path.dirname(inc), "s2_l3.inc")
            with io.open(l3, "w", encoding="utf-8") as fh:
                fh.write(f"/* GENERATED by tools/qemu-panel-read.py - do not edit"
                         f" by hand.\n"
                         f" *\n"
                         f" * One level 3 table per block that needs 4 KB granularity,\n"
                         f" * in block order and {STAGE2_BLOCK // 0x1000} entries each.\n"
                         f" * The aliased pages point at the machine; every other page\n"
                         f" * of the block points at the same offsets *inside* the pool\n"
                         f" * block that block already had, so the pages this file does\n"
                         f" * not name are the RAM model they were before.\n"
                         f" */\n")
                for blk in sorted(pages):
                    fh.write(f"    /* block {blk}, {blk * STAGE2_BLOCK:#x}"
                             f" - level 3 table at S2_L3_OFF"
                             f"{f' + {l3_off[blk] * 0x1000:#x}' if l3_off[blk] else ''}"
                             f" */\n")
                    for p in range(STAGE2_BLOCK // 0x1000):
                        pa = pages[blk].get(p)
                        note = ""
                        if pa is None:
                            pa = plan[blk] + p * 0x1000
                        else:
                            note = "    /* the machine's own */"
                        fh.write(f"    .quad S2_PAGE | {pa:#x}{note}\n")
                fh.write("\n")
            defsym += ["--defsym", "S2_L3=1"]
        include = ["-I", os.path.dirname(inc)]
        defsym += ["--defsym", "ZERO_MEM=1",
                   "--defsym", f"S2_MOVED_IPA={ZERO_MEM_IPA:#x}"]
        if gic_secure:
            defsym += ["--defsym", "GIC_SECURE=1",
                       "--defsym", f"GIC_DIST_BASE={MACHINE_GIC_BASE:#x}",
                       "--defsym",
                       f"GIC_CPU_BASE={MACHINE_GIC_BASE + 0x10000:#x}",
                       "--defsym", f"GIC_NUM_IRQ={MACHINE_GIC_NUM_IRQ}",
                       "--defsym",
                       f"GIC_IGROUPR_WORDS={MACHINE_GIC_WORDS}",
                       "--defsym", f"GIC_NUM_CPU={MACHINE_GIC_NUM_CPU}"]
    if seed:
        if not zero_mem:
            die("--el3-seed-smem writes into a pool block that only"
                " --el3-zero-mem creates; the seed would land in memory the"
                " guest cannot reach and the run would be a plain one wearing a"
                " seeded run's header")
        block, smem_base, smem_size = seed
        defsym += ["--defsym", "SEED_SMEM=1",
                   "--defsym", f"SEED_SMEM_BLOCK={block:#x}",
                   "--defsym", f"SEED_SMEM_IPA={ZERO_MEM_IPA:#x}",
                   "--defsym", f"SEED_SMEM_BASE={smem_base:#x}",
                   "--defsym", f"SEED_SMEM_SIZE={smem_size:#x}"]
    if aop:
        if not seed:
            die("--el3-seed-aop writes the second thing this instrument"
                " fabricates, and it is only reachable at all from the Apriori"
                " slot the SMEM seed is what gets the boot to: without"
                " --el3-seed-smem the run stops at slot 2 and the AOP words are"
                " never read, so the capture would be a plain one wearing a"
                " seeded run's header")
        block, ipa, state, magic = aop
        defsym += ["--defsym", "SEED_AOP=1",
                   "--defsym", f"SEED_AOP_BLOCK={block:#x}",
                   "--defsym", f"SEED_AOP_IPA={ipa:#x}",
                   "--defsym", f"SEED_AOP_STATE={state:#x}",
                   "--defsym", f"SEED_AOP_MAGIC={magic:#x}"]
    for argv in ([asm] + defsym + include + ["-o", obj, src],
                 [ld, "-Ttext", f"{load_addr:#x}", "--build-id=none",
                  "-o", elf, obj],
                 [objcopy, "-O", "binary", elf, out]):
        run = subprocess.run(argv, stderr=subprocess.PIPE)
        if run.returncode:
            die(f"{argv[0]} failed: {run.stderr.decode('utf-8', 'replace').strip()}")
    return out, obj


def stub_symbol(obj, name):
    """Where `name` lands inside the stub's own 64 KB, as an offset from its load.

    Asked of the object file rather than written down here. The stub's layout is
    the assembly's business and a number repeated in this file would be a second
    answer to where its tables are. For a relocatable object `readelf` prints the
    section offset, and `.text` is the one section `objcopy -O binary` lays down,
    so the section offset is the offset in the binary.
    """
    readelf = shutil.which("aarch64-linux-gnu-readelf")
    if not readelf:
        die("reading the stub's tables back needs aarch64-linux-gnu-readelf to"
            " find them; it was not on PATH")
    run = subprocess.run([readelf, "-sW", obj], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    for line in run.stdout.decode("utf-8", "replace").splitlines():
        field = line.split()
        if len(field) >= 8 and field[7] == name:
            return int(field[1], 16)
    die(f"the stub object has no symbol {name!r} - the stage-2 tables were renamed"
        f" or assembled out, and a header that claimed to report on them would be"
        f" reporting on nothing")


def stub_consts(obj, names):
    """`{name: value}` for the assembly's own `.equ`s, read out of the object.

    The SMEM structure is a dozen numbers - three magics, two sizes, an offset, a
    divisor, a host id - and every one of them is decided in `qemu-el3-stub.S`,
    which is the file that writes them. Copying them here to check against would
    be this launcher's opinion of what the seed should be rather than a check on
    what it is, and the two would agree by construction. Read from the object, the
    check is against the value the assembler actually folded into the instruction,
    so an edit to one file that the other did not follow shows up as a mismatch
    instead of as two files agreeing on a stale number.
    """
    readelf = shutil.which("aarch64-linux-gnu-readelf")
    if not readelf:
        die("reading the stub's own constants back needs aarch64-linux-gnu-readelf;"
            " it was not on PATH")
    run = subprocess.run([readelf, "-sW", obj], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    found = {}
    for line in run.stdout.decode("utf-8", "replace").splitlines():
        field = line.split()
        if len(field) >= 8 and field[7] in names:
            found[field[7]] = int(field[1], 16)
    missing = [n for n in names if n not in found]
    if missing:
        die(f"the stub object has no {', '.join(missing)} - the seed was"
            f" restructured and this file is checking for values the assembly no"
            f" longer has, which would make every check below pass vacuously")
    return found


def stub_tables(mon, load_addr, obj, plan, pages=None):
    """The stage-2 evidence, read out of the running guest.

    Returns `(l1_0, l2, backing, diag, l3)` or None if the read failed, where `l3`
    is the level 3 tables' pages, concatenated in block order, or None when there
    are none. `l2` is
    the 512 level 2 entries as the guest's memory holds them, `backing` is what the
    address `ZERO_MEM_IPA` is redirected to actually contains, and `diag` is
    `(vtcr, vttbr, hcr, scr)` as the guest itself read them back - plus, when
    `--el3-gic-secure` is on, the two words the stub read back out of the machine's
    controller while it was still the secure side doing the reading: its
    `GICD_IGROUPR0` and its `GICC_PMR`, which are the same two registers the header
    reads non-securely and reads differently. The pair is what separates "the write
    happened" from "the non-secure read is a view that hides it".

    This is the read-back that keeps the header honest. A capture that says the
    machine answered a register read has to be able to show the entries that
    answered it, and the only place those entries exist is the guest's memory - so
    they are read there, after the guest has been running, rather than written
    beside it. The whole table and not just the one entry: the claim is now about
    a set of regions, and a set is exactly what one sampled entry cannot support.
    The caller checks the entries against the plan it handed over, so the two ends
    of the instrument are compared rather than each being announced.

    `backing` is what the driver will see at the address it faults on; the whole
    point of pointing it at untouched RAM is that this is zero, and that is worth
    checking rather than asserting.

    The four registers are here because the first run of this instrument was
    reverted by the machine - the guest stopped on a translation fault for the
    payload's own first instruction - and nothing but a read-back distinguishes "the
    registers say stage 2 is on" from "the registers were written and ignored".
    """
    scratch = tempfile.mkdtemp(prefix="qemu-el3-tbl-")
    dump = os.path.join(scratch, "tables.bin")
    try:
        diag_off = stub_symbol(obj, "s2_diag")
        l1_off = stub_symbol(obj, "s2_l1")
        l2_off = stub_symbol(obj, "s2_l2")
        # The level 3 tables sit directly after the level 2 one when they exist,
        # and they are read by the same pass so that a capture cannot carry the
        # block descriptor that names a level 3 table without the table it names.
        l3_off = stub_symbol(obj, "s2_l3") if pages else None
        span = l2_off - l1_off + 8 * STAGE2_L2_ENTRIES
        if l3_off is not None:
            span = l3_off - l1_off + 8 * STAGE2_BLOCK // 0x1000 * len(pages)
        mon.cmd(f'pmemsave {load_addr + l1_off:#x} {span:#x} "{dump}"', timeout=10.0)
        with open(dump, "rb") as fh:
            blob = fh.read()
        diag = os.path.join(scratch, "diag.bin")
        mon.cmd(f'pmemsave {load_addr + diag_off:#x} 48 "{diag}"', timeout=10.0)
        with open(diag, "rb") as fh:
            words = struct.unpack("<QQQQQQ", fh.read(48))
        blk = ZERO_MEM_IPA & ~(STAGE2_BLOCK - 1)
        backing_at = plan[(blk // STAGE2_BLOCK) & (STAGE2_L2_ENTRIES - 1)]
        backing_at += ZERO_MEM_IPA - blk
        far = os.path.join(scratch, "backing.bin")
        mon.cmd(f'pmemsave {backing_at:#x} 16 "{far}"', timeout=10.0)
        with open(far, "rb") as fh:
            backing = fh.read(16)
    except (OSError, SystemExit):
        return None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    l2_at = l2_off - l1_off
    if len(blob) < l2_at + 8 * STAGE2_L2_ENTRIES or len(backing) < 16:
        return None
    l3 = None
    if l3_off is not None:
        at = l3_off - l1_off
        want = 8 * STAGE2_BLOCK // 0x1000 * len(pages)
        if len(blob) < at + want:
            return None
        l3 = struct.unpack_from(f"<{STAGE2_BLOCK // 0x1000 * len(pages)}Q", blob, at)
    return (struct.unpack_from("<Q", blob, 0)[0],
            struct.unpack_from(f"<{STAGE2_L2_ENTRIES}Q", blob, l2_at),
            struct.unpack_from("<QQ", backing, 0),
            words, l3)


def aop_words(aop_bytes, rec):
    """`(word, state_got, magic_got)` out of the raw AOP read, or None if short.

    The record is unpacked at `rec` and not at zero because that is where the
    driver reads it: the word at the gate is a pointer, and the two values its
    entry gate compares are at the pointer and four bytes past it. A read-back
    that unpacked three consecutive words from zero would compare the pointer with
    the state it points at, call the pair disagreeing, and be wrong about which of
    the two had moved - which is exactly what the first run of this seed printed.
    """
    if len(aop_bytes) < rec + 8:
        return None
    word = struct.unpack_from("<I", aop_bytes, 0)[0]
    state_got, magic_got = struct.unpack_from("<II", aop_bytes, rec)
    return word, state_got, magic_got


def stub_seed(mon, load_addr, obj, plan, flag_addr, aop=None):
    """What the seed actually put in memory, read back out of the machine.

    Returns `(pool_page, pointer, struct_pool, written, struct_bytes, flag,
    toc, toc_bytes, table, table_bytes, aop_got, aop_bytes)` or None if the read
    failed: the pool address of the page holding the SMEM word, the pointer value
    as the guest will dereference it, the pool address of the structure, the first
    qword as the stub recorded having written it, the structure's three words as
    the machine holds them, the word the stub put at `flag_addr` - which is inside
    SMEM itself and not inside anything this file laid out - the two addresses in
    SMEM that only the stub knows along with what the machine holds at each, and
    the pool address of the AOP mailbox word (zero when that seed is off) along
    with the three words at it.

    The check that matters is not that these equal what the launcher asked for -
    the launcher asked for two addresses and never named the structure - but that
    they are *internally* consistent, which is a claim about the guest's walk and
    not about this file's intent. `pointer - struct_pool` is the IPA offset the
    pointer names minus the pool offset the bytes sit at, and if those are equal
    the byte the guest's stage-2 redirect will fetch is the byte written here.
    The caller does that comparison; this function only fetches.

    The last four fields are the rung above the container, and they are fetched
    the same way and for the same reason: the TOC and the heap table are in SMEM
    rather than in the stub's own 64 KB, so they are read by the address the stub
    recorded instead of by a symbol of this file's, and the AOP pair is in a
    window neither end owns. Every one of them is a read of what the machine
    holds, so a seed that wrote the right number to the wrong place reads back as
    the right number at the wrong place, which is the only way to tell the two
    apart.
    """
    scratch = tempfile.mkdtemp(prefix="qemu-el3-seed-")
    try:
        diag = os.path.join(scratch, "seed.bin")
        off = stub_symbol(obj, "seed_diag")
        mon.cmd(f'pmemsave {load_addr + off:#x} 64 "{diag}"', timeout=10.0)
        with open(diag, "rb") as fh:
            (pool_page, pointer, struct_pool, written,
             toc, table, aop_got, _pad) = struct.unpack("<QQQQQQQQ", fh.read(64))
        if not struct_pool:
            return None
        body = os.path.join(scratch, "struct.bin")
        mon.cmd(f'pmemsave {struct_pool:#x} 24 "{body}"', timeout=10.0)
        with open(body, "rb") as fh:
            struct_bytes = struct.unpack("<QQQ", fh.read(24))
        # The flag is not in the stub's own memory, so it is fetched by its
        # address in SMEM instead of by a stub symbol: this is the one read that
        # would still be right if the stub were wrong about where it wrote.
        word = os.path.join(scratch, "flag.bin")
        mon.cmd(f'pmemsave {flag_addr:#x} 4 "{word}"', timeout=10.0)
        with open(word, "rb") as fh:
            flag = struct.unpack("<I", fh.read(4))[0]
        # The TOC page and the heap table, both in SMEM. The table is read from
        # its own 0xA5A5 tag to just past the entry count, which is everything
        # the stub wrote there; the TOC is read from its header through the
        # entry the allocator will follow.
        toc_bytes = b""
        if toc:
            path = os.path.join(scratch, "toc.bin")
            mon.cmd(f'pmemsave {toc:#x} 0x38 "{path}"', timeout=10.0)
            with open(path, "rb") as fh:
                toc_bytes = fh.read(0x38)
        table_bytes = b""
        if table:
            path = os.path.join(scratch, "table.bin")
            mon.cmd(f'pmemsave {table:#x} 0x1C "{path}"', timeout=10.0)
            with open(path, "rb") as fh:
                table_bytes = fh.read(0x1C)
        # The AOP pair: the mailbox word at +0 and the record it points at,
        # SEED_AOP_REC_OFF bytes further in. Both are read in one go because they
        # are adjacent and because reading the record from its own offset is what
        # makes the read-back catch this seed being written at the wrong one.
        aop_bytes = b""
        if aop is not None and aop_got:
            path = os.path.join(scratch, "aop.bin")
            mon.cmd(f'pmemsave {aop_got:#x} {AOP_REC_OFF + 16:#x} "{path}"',
                    timeout=10.0)
            with open(path, "rb") as fh:
                aop_bytes = fh.read(AOP_REC_OFF + 16)
    except (OSError, SystemExit):
        return None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return (pool_page, pointer, struct_pool, written, struct_bytes, flag,
            toc, toc_bytes, table, table_bytes, aop_got, aop_bytes)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kernel", help="the raw BootShim + FD payload to launch")
    ap.add_argument("--socket", default="/tmp/qmon.sock")
    ap.add_argument("--machine", default="virt",
                    help="QEMU machine. Plain `virt`: an SMC at EL1 is then"
                         " architecturally undefined and QEMU raises it as EC 0x00,"
                         " which is not what the hardware does and stops the boot at"
                         " Apriori slot 2. `--el3-stub` is how that is answered.")
    ap.add_argument("--el3-stub", action="store_true",
                    help="run under an EL3 that exists, so an SMC returns an error"
                         " instead of faulting. Sets the machine to virt,secure=on;"
                         " see tools/qemu-el3-stub.S for what that buys and what it"
                         " costs in fidelity")
    ap.add_argument("--el3-zero-mem", action="store_true",
                    help="with --el3-stub: turn on stage 2 and give the guest a"
                         " 4 GB identity map in which every 2 MB block holding a"
                         " region the platform's own MemoryMapLib.c declares below"
                         " 0x40000000 is pointed at its own 2 MB of untouched RAM"
                         " below the payload, so that a driver reading a register"
                         " virt does not decode gets zero back instead of an abort."
                         " The payload is not touched; the guest's own page tables"
                         " are not touched; an access at or above 4 GB is a"
                         " translation fault that only this instrument produces")
    ap.add_argument("--el3-gic-real", action="store_true",
                    help="with --el3-stub --el3-zero-mem: stop pretending the"
                         " interrupt controller is RAM. The board's GIC window"
                         " 0x17A00000 is 2 MB that this platform's own map declares"
                         " and this instrument has been pointing at zeroed pool RAM"
                         " since the flag existed, which is a controller that cannot"
                         " hold pending state, cannot raise a line, and cannot"
                         " deliver an interrupt of any kind - so every facility in"
                         " the payload that waits on one waits forever. With this"
                         " flag the block is pointed at the machine's own GICv2"
                         " instead (0x08000000, whose gic_dist and gic_cpu spacing"
                         " is the board's), and IPA page 0 - where"
                         " PcdGicInterruptInterfaceBase, which BitraPkg does not"
                         " override, puts the CPU interface - is pointed at gic_cpu"
                         " page for page through a level 3 table. Everything else,"
                         " SPMI included, keeps the RAM model and the tool's header"
                         " says which is which: this makes the controller real, it"
                         " does not make the *sources* real, and which interrupts"
                         " the payload asks for is still the payload's own PCDs")
    ap.add_argument("--el3-gic-secure", action="store_true",
                    help="with --el3-gic-real: do what a secure world does to that"
                         " controller before the payload starts, because on this"
                         " machine nothing does. The machine is TZ-aware and has no"
                         " secure firmware, so its reset leaves every interrupt in"
                         " Group 0 and the priority mask at zero - and an interrupt"
                         " in Group 0 is one a non-secure enable never enables,"
                         " while the mask cannot be moved by a non-secure write in"
                         " the lower half at all. So the stops are: every"
                         " interrupt's priority to 0x80, every interrupt into"
                         " Group 1, and GICC_PMR to 0xff on each CPU interface, all"
                         " from EL3 before SCR_EL3.NS is set. It is QEMU's own"
                         " non-secure-boot reset plus the mask, and it is a change"
                         " to the *machine*, not to the guest: the distributor's"
                         " and the CPU interface's own enables stay the payload's."
                         " What the payload's enables are is then readable at last,"
                         " because a non-secure read of the enable set returns"
                         " exactly the Group-1 bits")
    ap.add_argument("--el3-seed-smem", action="store_true",
                    help="with --el3-stub --el3-zero-mem: fabricate the small"
                         " structure EnvDxe reads at Apriori slot 2 - the pointer"
                         f" at {ZERO_MEM_IPA:#x} and the three fields it addresses -"
                         " so that the dispatcher gets past the driver instead of"
                         " asserting on the zero a register model returns, and the"
                         " digest rows DxeCore prints after the batch can be read."
                         " The container is invented; the SMEM base and size in it"
                         " and the magic its first word is checked against are the"
                         " board's own declaration and the driver's own compare,"
                         " read out of the platform's memory map and the driver's"
                         " image. One more word is written, into SMEM itself rather"
                         " than into the container, because the driver asserts"
                         " after reading it; see the SEEDED block in the output"
                         " for which parts are the board's and which are not")
    ap.add_argument("--el3-seed-aop", action="store_true",
                    help="with --el3-stub --el3-zero-mem --el3-seed-smem: the"
                         " second seed, for the driver the first one's success"
                         " reaches. CmdDbDxe's entry gate reads the word at the"
                         " address its own `mov w8,#0xc; movk w8,#0xc3f,lsl #16`"
                         " names, treats it as a pointer, and requires `p[0] == 1`"
                         " and `p[1] == 0x0c0330db`; under this instrument that"
                         " window is RAM holding zero, so the driver returns"
                         " EFI_UNSUPPORTED and the Apriori row that follows it is"
                         " an `R`, not a `U`. All three numbers are decoded out of"
                         " the driver's own instructions and the region is the one"
                         " this board's memory map declares, so the only invented"
                         " thing is that a processor this instrument does not run"
                         " left a record there - which is exactly the claim under"
                         " test; see the SEEDED block in the output")
    ap.add_argument("--memory", type=int, default=4096, help="MB")
    ap.add_argument("--load-addr", default=DEFAULT_LOAD_ADDR, type=lambda v: int(v, 0))
    ap.add_argument("--extra", action="append", default=[], metavar="ARG",
                    help="one more QEMU argument (repeatable)")
    ap.add_argument("--mu", default=DEFAULT_MU)
    ap.add_argument("--platform", default=None,
                    help="the platform package directory, if not"
                         " Platforms/Xiaomi/gauguinPkg")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=0.25)
    ap.add_argument("--min-margin", type=float, default=1.5)
    ap.add_argument("--out", default=os.path.join(REPO, "work", "out", "qemu-panel.txt"))
    ap.add_argument("--quiet", action="store_true",
                    help="report only the stream, not each sample's progress")
    ap.add_argument("--join-wrap", action="store_true",
                    help="in --out, append to a row that fills the console's last"
                         " column the row below it, on the theory that the console"
                         " wrapped. Off by default because the two cases are not"
                         " distinguishable on the screen: a console line of exactly"
                         " `columns` characters also puts the cursor on the next row"
                         " without having wrapped. The count of full-width rows is"
                         " reported either way, because a wrapped row read as a whole"
                         " line is a reading error this file cannot prevent")
    args = ap.parse_args()

    if args.kernel and not os.path.exists(args.kernel):
        die(f"no payload at {args.kernel} - decompress the boot image's kernel first"
            f" (the payload is a gzip member followed by the device tree, so it needs"
            f" zlib.decompressobj(31) and not gzip.decompress)")
    if os.path.exists(args.socket):
        os.unlink(args.socket)

    # The stub needs secure=on and the payload needs an address, so the two are
    # decided together and neither is a default a caller can half-set. The
    # platform comes first here because the stage-2 instrument is built out of
    # the platform's own memory map.
    pkg, dsc = platform_paths(args.mu, args.platform)
    stub, stub_obj, plan, seed, aop = None, None, None, None, None
    sc, drift = {}, []
    if args.el3_stub:
        if args.machine != "virt":
            die(f"--el3-stub and --machine {args.machine} disagree about whether the"
                f" guest has an EL3; the stub replaces the answer rather than adding"
                f" to it")
        args.machine = "virt,secure=on"
        alias, pages = {}, {}
        if args.el3_gic_real and not args.el3_zero_mem:
            die("--el3-gic-real changes what a stage-2 block points at, and the"
                " stage-2 table is what --el3-zero-mem builds; without it the flag"
                " would be dropped and the run would be a plain one whose header"
                " claimed the machine's own controller was behind the guest's GIC"
                " window")
        if args.el3_gic_secure and not args.el3_gic_real:
            die("--el3-gic-secure programs the machine's own GIC from EL3, and"
                " without --el3-gic-real the guest's GIC window is a page of pool"
                " RAM: the writes would land in the pool and the run would be a"
                " plain one carrying a header that claimed the payload's role in"
                " delivery had been measured")
        if args.el3_zero_mem:
            # What is redirected is not one address but every region this board's
            # map declares below LOW_MMIO_LIMIT, because the firmware's use of its
            # SoC is not one read: the same run that stops on TCSR at slot 2 has
            # PSHOLD two instructions behind it, and the drivers after that have
            # the rest. Modelling one address at a time would be a boot that dies
            # somewhere new each run, which is indistinguishable from progress.
            regions = low_regions(pkg)
            plan = l2_plan(regions, args.load_addr)
            alias, pages = real_aliases(regions, args.el3_gic_real)
            print(f"stage 2  {len(regions)} region(s) below {LOW_MMIO_LIMIT:#x} in"
                  f" {os.path.basename(pkg)}, {len(plan)} 2 MB block(s):"
                  f" {len(plan) - len(alias) - len(pages)} redirected to"
                  f" {ZERO_MEM_POOL_BASE:#x}..{ZERO_MEM_POOL_BASE + len(plan) * STAGE2_BLOCK:#x}")
            for i in sorted(alias):
                print(f"         block {i} ({i * STAGE2_BLOCK:#x}) is the machine's"
                      f" own device at {alias[i]:#x}")
            for blk in sorted(pages):
                for p, pa in sorted(pages[blk].items()):
                    print(f"         block {blk} page {p}"
                          f" ({blk * STAGE2_BLOCK + p * 0x1000:#x}) is the machine's"
                          f" own device at {pa:#x}")
            # Stage 2 is only in force if the machine gave the CPU an EL2 at all.
            # QEMU's virt machine turns EL2 on for the CPU it creates as part of
            # `virtualization=on`, and without it the stub's `msr hcr_el2` is
            # accepted - it comes from EL3, so the access check passes - and then
            # ignored, because QEMU's translation path reads HCR_EL2 through
            # `arm_hcr_el2_eff()` and that returns zero when EL2 is absent. The
            # first run of this instrument showed exactly that: the tables in the
            # guest, the entry pointing at the RAM, and the same external abort,
            # because nothing consulted them.
            #
            # GICv2 is pinned to what `secure=on` chose on its own. Left to itself
            # `virtualization=on` can select GICv3, which moves the distributor,
            # adds a redistributor, and changes the interrupt topology the firmware
            # under test is looking at - one variable too many in a log whose whole
            # value is that the only difference from the previous one is a flag.
            args.machine += ",virtualization=on,gic-version=2"
            if args.el3_seed_smem:
                smem_base, smem_size = smem_region(pkg)
                seed = (seed_block_for(plan), smem_base, smem_size)
            if args.el3_seed_aop:
                ipa, state, magic, (aop_base, aop_size) = aop_gate(args.mu, pkg)
                aop = (aop_block_for(plan, ipa, AOP_REC_OFF), ipa, state, magic)
        stub, stub_obj = build_el3_stub(
            args.load_addr,
            os.path.join(tempfile.mkdtemp(prefix="qemu-el3-"), "el3.bin"),
            args.el3_zero_mem, plan, seed, aop, alias, pages,
            args.el3_gic_secure)
        # The seed's own numbers, read back out of the assembly that folded them
        # into instructions. Every comparison below - the header's, the read-back's
        # and the exit status's - is against these and not against a copy kept in
        # this file, because a copy would make each of them agree with itself: the
        # claim being tested is that what the machine holds is what the stub meant,
        # and that is only a test if the two ends can disagree.
        sc = stub_consts(stub_obj, STUB_SEED_CONSTS) if seed else {}
        # This file keeps a short name for five of the seed's numbers - they are
        # read a dozen times each below and a string index would be noise - and
        # the copies are compared against the assembler's here, once, rather than
        # being trusted. A disagreement means one of the two files was edited
        # without the other, and every check that used the copy would otherwise
        # pass while the machine held the other number.
        drift = [(n, v, sc[n]) for n, v in (
            ("SEED_SMEM_OFF", SEED_SMEM_OFF),
            ("SEED_SMEM_MAGIC", SEED_SMEM_MAGIC),
            ("SEED_SMEM_FLAG_OFF", SEED_SMEM_FLAG_OFF),
            ("SEED_SMEM_FLAG", SEED_SMEM_FLAG),
            ("SEED_AOP_REC_OFF", AOP_REC_OFF)) if n in sc and sc[n] != v]
        if drift:
            for n, here, there in drift:
                print(f"  the seed constant {n} is {here:#x} in this file and"
                      f" {there:#x} in the stub's own assembly")
        if seed:
            print(f"seed     EnvDxe's SMEM word at {ZERO_MEM_IPA:#x} -> pointer to"
                  f" {ZERO_MEM_IPA + sc['SEED_SMEM_OFF']:#x}, structure written at"
                  f" {seed[0] + (ZERO_MEM_IPA & (STAGE2_BLOCK - 1)) + sc['SEED_SMEM_OFF']:#x}"
                  f" in the pool block for {(ZERO_MEM_IPA // STAGE2_BLOCK) * STAGE2_BLOCK:#x}"
                  f" - the container is fabricated, the base"
                  f" {smem_base:#x} and size {smem_size:#x} are this board's own"
                  f" declaration; see tools/qemu-el3-stub.S")
        if aop:
            at, ipa, state, magic = aop
            print(f"aop seed CmdDbDxe's gate at {ipa:#x}: the word becomes a pointer"
                  f" to {ipa + sc['SEED_AOP_REC_OFF']:#x}, where {state:#x} and"
                  f" {magic:#x} are written at pool"
                  f" {at + (ipa & (STAGE2_BLOCK - 1)):#x} - the three numbers are"
                  f" decoded out of the driver's own instructions; see"
                  f" tools/qemu-el3-stub.S")
    elif args.el3_gic_real:
        die("--el3-gic-real changes what a stage-2 block points at, so it means"
            " nothing without --el3-zero-mem to build the stage-2 table it is a"
            " change to; the run would be a plain one wearing an aliased one's"
            " header")
    elif args.el3_zero_mem:
        die("--el3-zero-mem is the stub's behaviour and means nothing without"
            " --el3-stub; an abort it did not answer would still stop the boot")
    elif args.el3_seed_smem:
        die("--el3-seed-smem writes into the pool block the stage-2 redirect"
            " creates, so it means nothing without --el3-zero-mem; without the"
            " redirect the seed would sit in memory no guest access reaches and"
            " the run would stop exactly where an unseeded one does, wearing a"
            " header that said it was seeded")
    elif args.el3_seed_aop:
        die("--el3-seed-aop writes the word CmdDbDxe reads, and that driver is"
            " Apriori slot 17 - reached only if the boot got past slot 2, which"
            " is what --el3-seed-smem is for; and it writes into the pool block"
            " the stage-2 redirect creates. Without both, the run would stop"
            " before the word is ever read")

    pt = load_panel_text()
    geo = pt.load_geometry(args.mu, dsc)
    font = pt.load_font(args.mu)
    name, base, length = fb_region(pkg)
    need = geo["width"] * geo["height"] * (geo["bpp"] // 8)
    if length < need:
        die(f"{name} is {length:#x} bytes and the console draws {need:#x} - the"
            f" platform's region is too small for its own panel, which is a source"
            f" disagreement and not something to sample around")

    print(f"panel   {geo['width']}x{geo['height']} {geo['bpp']}bpp, cell"
          f" {geo['cell_w']}x{geo['cell_h']}, {geo['columns']}x{geo['rows']} cells")
    print(f"region  {name} {base:#x}..{base + length:#x}, of which the console draws"
          f" {need:#x}")

    proc = None
    if args.kernel:
        proc = launch(args.kernel, args.socket, args.machine, args.memory,
                      args.load_addr, args.extra, stub)
        time.sleep(0.5)
    mon = Monitor(args.socket)

    lines, screens, gaps = [], 0, []
    tables, seed_got, gic = None, None, None
    worst, weak = 60.0, 0
    scratch = tempfile.mkdtemp(prefix="qemu-panel-")
    dump = os.path.join(scratch, "fb.bin")
    # Only the drawn part is dumped: the region is 0x2400000 here and the console
    # touches 0x9E3400 of it, so the other 28 MB would be sampled and decoded as
    # black forty times a second.
    sample = f'pmemsave {base:#x} {need:#x} "{dump}"'
    t0 = time.time()
    try:
        while time.time() - t0 < args.seconds:
            tick = time.time()
            mon.cmd(sample, timeout=max(5.0, args.interval * 4))
            try:
                got, report, _t = pt.fb_lines(dump, geo, font, args.min_margin)
            except SystemExit as exc:            # a short dump: say so, keep going
                print(f"  {tick - t0:6.2f}s  dump not usable: {exc}")
                continue
            for rep in report:
                worst = min(worst, rep["worst"])
                weak += len(rep["weak"])
            k = pt.fb_overlap(lines, got)
            if screens and got and k == 0:
                # A screen that joins onto nothing is either one the console
                # rewrote while it was being read - a line printed without a
                # newline, so the next print continued on that row, and the rows
                # below then repeat the log above - or text printed between two
                # samples, which is gone. The count of the screen's rows the stream
                # already holds is the fact both cases can be read off; the header
                # does not decide which this sample was.
                gaps.append((tick - t0, len(got),
                             sum(1 for row in got if row in lines)))
            new = got[k:]
            if new and not args.quiet:
                for line in new:
                    print(f"  {tick - t0:6.2f}s  {line}")
            lines += new
            if got:
                screens += 1
            time.sleep(max(0.0, args.interval - (time.time() - tick)))
    except KeyboardInterrupt:
        pass
    finally:
        # The stage-2 tables are in the guest's own memory, so they are read while
        # it is still running and before anything is torn down. A header that says
        # an address was answered read as zero has to be able to show the entry
        # that answered it.
        if stub and args.el3_zero_mem:
            tables = stub_tables(mon, args.load_addr, stub_obj, plan, pages)
            if seed:
                seed_got = stub_seed(mon, args.load_addr, stub_obj, plan,
                                     seed[1] + SEED_SMEM_FLAG_OFF, aop)
            # The machine's own interrupt controller, read here for the same reason
            # the tables are: it is the other end of the redirect. That the alias
            # exists is one claim; that the payload's own writes landed in it is
            # another, and only the second one is about the guest. Read while it is
            # still running and before anything is torn down.
            if alias or pages:
                gic = machine_gic(mon)
        shutil.rmtree(scratch, ignore_errors=True)
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    digest = hashlib.sha256(open(args.kernel, "rb").read()).hexdigest() if args.kernel else None
    # What the read-back found, decided once while the header is being written and
    # reported again on stdout and in the exit status. None means "not asked for or
    # not readable", which is the same thing to a caller that has to decide whether
    # to believe the run.
    seed_ok, aop_ok = None, None
    # The stub's own read-backs, and None until the tables they come with have
    # been read. `gic` can be set while `tables` is not - the controller read is
    # guarded on the alias and not on the tables - so a header that reached for
    # the secure pair without this default would be a NameError rather than a
    # header that says the read failed.
    diag = None
    with io.open(args.out, "w", encoding="utf-8") as fh:
        fh.write(f"# qemu-panel-read.py - the console off a running firmware's own memory\n")
        fh.write(f"# sampled {screens} screens over {time.time() - t0:.1f}s at"
                 f" {args.interval}s intervals\n")
        if args.kernel:
            fh.write(f"# payload {args.kernel}\n#         sha256 {digest}\n")
            fh.write(f"# machine {args.machine}, -cpu max, -m {args.memory},"
                     f" load {args.load_addr:#x}\n")
            if stub:
                where = os.path.relpath(stub, REPO) if stub.startswith(REPO) else stub
                fh.write(f"# el3 stub {where}, sha256"
                         f" {hashlib.sha256(open(stub, 'rb').read()).hexdigest()},"
                         f" payload at {args.load_addr + STUB_GAP:#x} - an SMC in this"
                         f" log returned an error rather than faulting\n")
                if args.el3_gic_secure:
                    fh.write(f"# el3 GIC-SECURE ON, and this run's machine is not"
                             f" the one every earlier capture here ran on: from"
                             f" EL3 and before SCR_EL3.NS was set, the stub wrote"
                             f" every interrupt's priority to 0x80, every interrupt"
                             f" into Group 1, and GICC_PMR to 0xff on each CPU"
                             f" interface, and then read two of them back"
                             f" itself. Those are the three things a secure world"
                             f" does on a TZ-aware machine and this machine's own"
                             f" reset does not, because nothing here is the secure"
                             f" side (`arm_gic_common.c:279-286`) - and they are"
                             f" what stands between this machine and an interrupt"
                             f" that is never delivered, whatever the payload"
                             f" asked for. The distributor's and the CPU"
                             f" interface's own enables are untouched: those are"
                             f" the payload's two bits. Everything below is said"
                             f" about a machine that could deliver, and nothing"
                             f" below is a statement about the machine the earlier"
                             f" captures measured. See tools/qemu-el3-stub.S\n")
                if not args.el3_zero_mem:
                    fh.write(f"# el3 zero-mem off - a physical address virt does not"
                             f" decode stopped this run where the guest's own"
                             f" exception handler printed it\n")
                elif tables is None:
                    fh.write(f"# el3 zero-mem on, but the stage-2 tables could not be"
                             f" read back out of the guest; nothing is claimed about"
                             f" them and the run below is only as good as its own"
                             f" evidence\n")
                    if seed:
                        fh.write(f"# SEEDED, and the tables could not be read back, so"
                                 f" the seed is unverified too: the two halves of this"
                                 f" instrument are the redirect and the value, and a"
                                 f" capture that cannot show the first says nothing"
                                 f" about the second\n")
                else:
                    l1_0, l2, backing, diag, l3 = tables
                    l2_addr = args.load_addr + stub_symbol(stub_obj, "s2_l2")
                    l3_addr = (args.load_addr + stub_symbol(stub_obj, "s2_l3")
                               if pages else None)
                    # Every entry is checked against the plan this end handed over,
                    # and every entry that is not in the plan is checked for being
                    # the identity. Not the one address this end named: what the
                    # instrument now claims is a *set* of regions - the platform's
                    # own - and one sampled entry cannot support a claim about a set.
                    # The two ends of the instrument are compared here rather than
                    # each announcing itself.
                    #
                    # Four kinds of entry now, not two, and each is checked against
                    # the thing that produced it: a redirected block against the pool
                    # address the plan gave it, an aliased block against the machine
                    # address the alias table gave it, a paged block against a table
                    # descriptor naming its level 3 table, and everything else
                    # against the identity.
                    red = [i for i in plan if i not in alias and i not in pages]
                    wrong = [i for i in red
                             if (l2[i] & 0x3) != 0x1
                             or (l2[i] & ~(STAGE2_BLOCK - 1)) != plan[i]]
                    bad_alias = [i for i in sorted(alias)
                                 if (l2[i] & 0x3) != 0x1
                                 or (l2[i] & ~(STAGE2_BLOCK - 1)) != alias[i]]
                    bad_page = [i for i in sorted(pages)
                                if (l2[i] & 0x3) != 0x3
                                or (l2[i] & ~0xFFF) != l3_addr]
                    ident = sum(1 for i, e in enumerate(l2)
                                if i not in plan and (e & 0x3) == 0x1
                                and (e & ~(STAGE2_BLOCK - 1)) == i * STAGE2_BLOCK)
                    want_ident = STAGE2_L2_ENTRIES - len(plan)
                    # The pages of a paged block, against the two sources that
                    # named them: the machine for the aliased page, the block's own
                    # pool 2 MB for the rest.
                    bad_l3 = []
                    if l3 is not None:
                        n = STAGE2_BLOCK // 0x1000
                        for k, blk in enumerate(sorted(pages)):
                            for p in range(n):
                                want = pages[blk].get(p)
                                want = (plan[blk] + p * 0x1000
                                        if want is None else want)
                                got = l3[k * n + p]
                                if ((got & 0x3) != 0x3
                                        or (got & ~0xFFF) != want):
                                    bad_l3.append((blk, p, got, want))
                    ok = ((l1_0 & 0x3) == 0x3 and (l1_0 & ~0xFFF) == l2_addr
                          and not wrong and not bad_alias and not bad_page
                          and not bad_l3 and ident == want_ident)
                    fh.write(f"# el3 zero-mem on: stage 2 gives the guest a 4 GB"
                             f" identity map, with the {len(red)} 2 MB block(s)"
                             f" holding this platform's declared regions below"
                             f" {LOW_MMIO_LIMIT:#x} redirected to"
                             f" {ZERO_MEM_POOL_BASE:#x}.."
                             f"{ZERO_MEM_POOL_BASE + len(plan) * STAGE2_BLOCK:#x},"
                             f" one block each so that a register written and read"
                             f" back is the value that was written. No byte of the"
                             f" payload was changed\n")
                    if alias or pages:
                        fh.write(f"#   and {len(alias)} of those block(s) are not"
                                 f" given RAM at all - they are pointed at the"
                                 f" machine's own device, because it implements"
                                 f" them: "
                                 + ", ".join(f"block {i} ({i * STAGE2_BLOCK:#x})"
                                             f" -> {alias[i]:#x}"
                                             for i in sorted(alias))
                                 + (f", and block {sorted(pages)[0]}"
                                    f" ({sorted(pages)[0] * STAGE2_BLOCK:#x})"
                                    f" page by page through a level 3 table"
                                    f" at {l3_addr:#x} with "
                                    + ", ".join(f"page {p} -> {pa:#x}"
                                                for p, pa in sorted(
                                                    pages[sorted(pages)[0]].items()))
                                    if pages else "")
                                 + f"\n")
                    fh.write(f"#   read back out of the guest: L1[0] = {l1_0:#x},"
                             f" {len(red) - len(wrong)}/{len(red)} redirected"
                             f" entries, {len(alias) - len(bad_alias)}/{len(alias)}"
                             f" aliased entries and {ident}/{want_ident} identity"
                             f" entries"
                             + (f", and {len(pages) * (STAGE2_BLOCK // 0x1000) - len(bad_l3)}"
                                f"/{len(pages) * (STAGE2_BLOCK // 0x1000)}"
                                f" level 3 page(s)" if pages else "")
                             + f" are what this header describes -"
                             f" {'the walk is the one this header describes' if ok else 'THE WALK IS NOT THE ONE THIS HEADER DESCRIBES'}\n")
                    for i in wrong[:1]:
                        fh.write(f"#   L2[{i}] = {l2[i]:#x}, but block"
                                 f" {i * STAGE2_BLOCK:#x} is declared and the plan"
                                 f" put it at {plan[i]:#x}\n")
                    for i in bad_alias[:1]:
                        fh.write(f"#   L2[{i}] = {l2[i]:#x}, but block"
                                 f" {i * STAGE2_BLOCK:#x} was to be pointed at the"
                                 f" machine's {alias[i]:#x}\n")
                    for i in bad_page[:1]:
                        fh.write(f"#   L2[{i}] = {l2[i]:#x}, but block"
                                 f" {i * STAGE2_BLOCK:#x} was to be a level 3 table"
                                 f" descriptor naming {l3_addr:#x}"
                                 f" ({l3_addr + 0x3:#x})\n")
                    for blk, p, got, want in bad_l3[:1]:
                        fh.write(f"#   L3[{blk}][{p}] = {got:#x}, but page"
                                 f" {p} of block {blk} was to be {want:#x}\n")
                    if not ok and (l1_0 & ~0xFFF) != l2_addr:
                        fh.write(f"#   L1[0] should name the L2 table at"
                                 f" {l2_addr:#x} as a table descriptor"
                                 f" ({l2_addr + 0x3:#x})\n")
                    fh.write(f"#   so {ZERO_MEM_IPA:#x} reads what"
                             f" {ZERO_MEM_IPA - (ZERO_MEM_IPA & ~(STAGE2_BLOCK - 1)):#x}"
                             f" bytes into a redirected block, which holds"
                             f" {backing[0]:#010x} {backing[1]:#010x}\n")
                    fh.write(f"#   as the guest read them back after writing them:"
                             f" VTCR_EL2={diag[0]:#x} VTTBR_EL2={diag[1]:#x}"
                             f" HCR_EL2={diag[2]:#x} SCR_EL3={diag[3]:#x}\n")
                    fh.write(f"#   an access at or above 4 GB is a stage-2 translation"
                             f" fault here; the device it is standing in for has no"
                             f" such input limit\n")
                    if seed:
                        block, smem_base, smem_size = seed
                        fh.write(f"# SEEDED: the word at {ZERO_MEM_IPA:#x} is not the"
                                 f" zero a register model returns - it is"
                                 f" FABRICATED, and so is the structure it points at."
                                 f" EnvDxe reads the word as the address of the SMEM"
                                 f" target-info structure and asserts when it is"
                                 f" zero, so no unseeded run under this instrument"
                                 f" gets past Apriori slot 2 and no unseeded run"
                                 f" carries the digest rows. This one may, and"
                                 f" anything it says about EnvDxe or about what"
                                 f" follows it is said with this lie in place."
                                 f" See tools/qemu-el3-stub.S\n")
                        fh.write(f"#   what the container holds: the SMEM base"
                                 f" {smem_base:#x} and size {smem_size:#x} are this"
                                 f" board's own, out of its uefiplat.cfg by way of"
                                 f" MemoryMapLib.c, and the magic {SEED_SMEM_MAGIC:#x}"
                                 f" is out of the driver's own compare at RVA 0x9530."
                                 f" The structure's third qword is zero because"
                                 f" nothing in the image says what belongs there -"
                                 f" only the container is invented, not those"
                                 f" numbers. The last write is not into the"
                                 f" container at all: one word goes into SMEM itself,"
                                 f" at {smem_base + SEED_SMEM_FLAG_OFF:#x}, which is"
                                 f" where EnvDxe reads a {SEED_SMEM_FLAG:#x} and"
                                 f" asserts smem.c +671 when it does not find one -"
                                 f" that word is what XBL would have left there and"
                                 f" this instrument is putting it back by hand\n")
                        if drift:
                            fh.write(f"#   and this file's own copy of the seed"
                                     f" disagrees with the assembled one:"
                                     + "".join(f" {n} is {here:#x} here and"
                                               f" {there:#x} in the assembly;"
                                               for n, here, there in drift)
                                     + " the checks below use this file's copy, so"
                                       " every one of them is comparing the"
                                       " machine against a number the stub did not"
                                       " write\n")
                        if seed_got is None:
                            fh.write(f"#   the seed could not be read back out of the"
                                     f" machine; nothing is claimed about it, and in"
                                     f" particular this run is not evidence that the"
                                     f" word was written\n")
                        else:
                            (pool_page, pointer, struct_pool, written, body, flag,
                             toc, toc_bytes, table, table_bytes,
                             aop_got, aop_bytes) = seed_got
                            ipa_page = ZERO_MEM_IPA & ~0xFFF
                            stride = struct_pool - pool_page
                            want0 = (smem_size << 32) | SEED_SMEM_MAGIC
                            # The rung above the container. Four structures in SMEM
                            # that EnvDxe's own allocator walks before it ever
                            # reaches the item it hands out, and each of them is
                            # read back and compared against the number the
                            # assembly folded into the store - not against a copy
                            # here, which would agree with itself.
                            part_off = sc["SEED_SMEM_PART_OFF"]
                            want_toc = smem_base + smem_size - 0x1000
                            want_table = smem_base + part_off + sc["SEED_SMEM_TABLE_REL"]
                            words = lambda b, at: struct.unpack_from("<I", b, at)[0] \
                                if len(b) >= at + 4 else None
                            toc_ok = (toc == want_toc and len(toc_bytes) == 0x38
                                      and words(toc_bytes, 0) == sc["SEED_SMEM_TOC_MAGIC"]
                                      and words(toc_bytes, 4) == sc["SEED_SMEM_TOC_VERSION"]
                                      and words(toc_bytes, 8) == 1
                                      and words(toc_bytes, 0x20) == part_off
                                      and words(toc_bytes, 0x24) == sc["SEED_SMEM_PART_SIZE"]
                                      and words(toc_bytes, 0x28) == 0
                                      and words(toc_bytes, 0x2c)
                                          == (sc["SEED_SMEM_ENTRY_HOST"] << 16)
                                             | sc["SEED_SMEM_ENTRY_HOST"]
                                      and words(toc_bytes, 0x30) == sc["SEED_SMEM_ENTRY_DIV"]
                                      and words(toc_bytes, 0x34) == 0)
                            table_ok = (table == want_table and len(table_bytes) == 0x1C
                                        and struct.unpack_from("<H", table_bytes, 0)[0]
                                            == sc["SEED_SMEM_BLOCK_TAG"]
                                        and words(table_bytes, 4) == sc["SEED_SMEM_BLOCK_SIZE"]
                                        and words(table_bytes, 0x10)
                                            == sc["SEED_SMEM_PTABLE_MAGIC0"]
                                        and words(table_bytes, 0x14)
                                            == sc["SEED_SMEM_PTABLE_MAGIC1"]
                                        and words(table_bytes, 0x18)
                                            == sc["SEED_SMEM_PTABLE_ENTRIES"])
                            consistent = (pointer - struct_pool == ipa_page - pool_page
                                          and stride == SEED_SMEM_OFF
                                          and written == want0
                                          and body[0] == want0
                                          and body[1] == smem_base
                                          and body[2] == 0
                                          and flag == SEED_SMEM_FLAG
                                          and toc_ok and table_ok)
                            seed_ok = consistent
                            verdict = ("the pointer names the structure, the"
                                       " structure holds the base and size this"
                                       " board declares, and the driver's own"
                                       " checks read off it" if consistent else
                                       "THE SEED IS NOT WHAT THIS HEADER"
                                       " DESCRIBES")
                            fh.write(f"#   read back out of the machine: the pool page"
                                     f" for {ipa_page:#x} is {pool_page:#x}, it holds"
                                     f" the pointer {pointer:#x}, and {struct_pool:#x}"
                                     f" holds {body[0]:#x} {body[1]:#x} {body[2]:#x};"
                                     f" SMEM{SEED_SMEM_FLAG_OFF:#x} holds"
                                     f" {flag:#x} - {verdict}\n")
                            fh.write(f"#   and the rung above it, which is in SMEM"
                                     f" rather than in the pool: the TOC page"
                                     f" {toc:#x} (this board's base + size - 0x1000)"
                                     f" and the heap table {table:#x}"
                                     f" (base + {part_off:#x} + {sc['SEED_SMEM_TABLE_REL']:#x})"
                                     f" - {'both hold' if toc_ok and table_ok else 'WHICH DO NOT BOTH HOLD'}"
                                     f" the header, entry, partition tag and table"
                                     f" magics this file's own copy of the"
                                     f" assembly says they should\n")
                            if not toc_ok:
                                fh.write(f"#   the TOC page holds"
                                         f" {toc_bytes.hex(' ') if toc_bytes else 'nothing read'}"
                                         f"; EnvDxe's allocator follows the entry at"
                                         f" +0x20 into the partition and stops with a"
                                         f" zero size if that field is zero, so a TOC"
                                         f" that is not this one is a seed that"
                                         f" reaches the driver and not the item\n")
                            if not table_ok:
                                fh.write(f"#   the heap table holds"
                                         f" {table_bytes.hex(' ') if table_bytes else 'nothing read'}"
                                         f"; the allocator's own filter reads the"
                                         f" 0xA5A5 tag to decide the block is a heap"
                                         f" block at all, and then the two magics to"
                                         f" decide the heap is initialised, so a"
                                         f" wrong byte here is the assert the run"
                                         f" would stop on\n")
                            if pointer - struct_pool != ipa_page - pool_page:
                                fh.write(f"#   the pointer names {pointer:#x}, which is"
                                         f" {pointer - ipa_page:#x} past the word, but"
                                         f" the structure sits"
                                         f" {struct_pool - pool_page:#x} into the"
                                         f" block; the guest would fetch"
                                         f" {pool_page + pointer - ipa_page:#x}, which"
                                         f" this run did not write\n")
                            if stride != SEED_SMEM_OFF:
                                fh.write(f"#   the stub put the structure"
                                         f" {stride:#x} past the word and this tool"
                                         f" believes it is {SEED_SMEM_OFF:#x}; the"
                                         f" number in the two files has drifted\n")
                            if written != want0 or body[0] != want0:
                                fh.write(f"#   the structure's first qword is"
                                         f" {body[0]:#x} and EnvDxe needs the magic"
                                         f" {SEED_SMEM_MAGIC:#x} in its low half and"
                                         f" the size in its high half, which is"
                                         f" {want0:#x}; a mismatch sends the driver"
                                         f" down its \"not present\" assert and the"
                                         f" rows below are unreachable from here\n")
                            if body[1] != smem_base:
                                fh.write(f"#   the structure's base field is"
                                         f" {body[1]:#x} and this board declares"
                                         f" {smem_base:#x}; EnvDxe asserts"
                                         f" smem.c +659 when that field is zero, and"
                                         f" uses it as the SMEM it maps when it is"
                                         f" not\n")
                            if flag != SEED_SMEM_FLAG:
                                fh.write(f"#   SMEM{SEED_SMEM_FLAG_OFF:#x} holds"
                                         f" {flag:#x} and EnvDxe asserts smem.c +671"
                                         f" unless it holds {SEED_SMEM_FLAG:#x}, so"
                                         f" the write that was meant to reach SMEM"
                                         f" did not; this run's stop is the one an"
                                         f" unseeded run would have made and says"
                                         f" nothing new about the driver\n")
                            if body[2] != 0:
                                fh.write(f"#   the structure's third qword is"
                                         f" {body[2]:#x}, not the zero this run"
                                         f" meant to write\n")
                            if consistent:
                                fh.write(f"#   the machine's own bytes are checked, not"
                                         f" the guest's view of them: this is the"
                                         f" physical read, so it says the seed is"
                                         f" there and not that the guest's stage 1"
                                         f" maps it. The pointer is 16 bytes past the"
                                         f" word's own page base, so the page it"
                                         f" names is the page the driver already"
                                         f" reads; that is why the two are put in"
                                         f" one 4 KB page\n")
                    if aop:
                        at, ipa, state, magic = aop
                        rec = sc["SEED_AOP_REC_OFF"]
                        fh.write(f"# SEEDED: and the second seed, which is an"
                                 f" experiment rather than a fix and a different"
                                 f" kind of claim. The word at {ipa:#x} - inside"
                                 f" this board's \"{AOP_REGION}\" window, whose"
                                 f" address is this board's declaration and whose"
                                 f" region CmdDbDxe's own `mov`/`movk` pair names -"
                                 f" is not a state word but a POINTER, and the"
                                 f" two values the driver's entry gate compares"
                                 f" are at it and four bytes past it. Under this"
                                 f" instrument the window is RAM holding zero, so"
                                 f" the gate's first test fails and the driver"
                                 f" returns EFI_UNSUPPORTED; that is the `U` on"
                                 f" the Apriori row this run has been reading,"
                                 f" and the only thing this seed changes is that"
                                 f" word. See tools/qemu-el3-stub.S\n")
                        fh.write(f"#   the three numbers are decoded out of"
                                 f" CmdDbDxe's own instructions, not chosen here:"
                                 f" {ipa:#x} out of `mov w8,#0xc; movk w8,#0xc3f,lsl"
                                 f" #16` at RVA {AOP_GATE_RVA:#x}, {state:#x} out of"
                                 f" the `cmp wN,#imm` at RVA {AOP_STATE_RVA:#x}, and"
                                 f" {magic:#x} out of the pair at RVA"
                                 f" {AOP_MAGIC_RVA:#x}. The pointer is the one"
                                 f" value nothing in the tree supplies: no image"
                                 f" holds it, it is what an AOP this instrument"
                                 f" does not run would have published, and it is"
                                 f" invented to point at the record inside the"
                                 f" same 2 MB block so one stage-2 entry covers"
                                 f" both. The command database the driver reads"
                                 f" next is at AOP CMD DB 0x80860000, which is"
                                 f" likewise RAM holding zero here - so a failure"
                                 f" further in is the absent database and not"
                                 f" this seed\n")
                        if seed_got is None:
                            fh.write(f"#   the AOP words could not be read back out"
                                     f" of the machine; nothing is claimed about"
                                     f" them\n")
                        else:
                            aw = aop_words(aop_bytes, rec)
                            blk = ipa & ~(STAGE2_BLOCK - 1)
                            aop_ok_here = (aw is not None
                                           and aw[0] == ipa + rec
                                           and aw[1] == state
                                           and aw[2] == magic
                                           and plan.get(blk // STAGE2_BLOCK) == at
                                           and aop_got == at + (ipa & (STAGE2_BLOCK - 1))
                                           and (ipa & (STAGE2_BLOCK - 1)) + rec + 8
                                           <= STAGE2_BLOCK)
                            aop_ok = aop_ok_here
                            fh.write(f"#   read back out of {aop_got:#x}, which is"
                                     f" where the block {blk:#x} the plan put at"
                                     f" {at:#x} answers {ipa:#x}"
                                     f" {ipa & (STAGE2_BLOCK - 1):#x} into it: the"
                                     f" mailbox word"
                                     f" {'was not read' if aw is None else f'{aw[0]:#010x}'},"
                                     f" and the record {rec:#x} past it"
                                     f" {'was not read' if aw is None else f'{aw[1]:#010x} {aw[2]:#010x}'}"
                                     f" - {'the pointer, the state and the magic are all where the driver will look, so the gate this run is testing is the one this header describes' if aop_ok else 'THE AOP SEED IS NOT THE ONE THIS HEADER DESCRIBES'}\n")
                            if aw is None:
                                fh.write(f"#   the AOP pair could not be read back;"
                                         f" this run's Apriori row says nothing"
                                         f" about the gate, because there is no"
                                         f" evidence the word was written\n")
                            elif aw[0] != ipa + rec:
                                fh.write(f"#   the word at {ipa:#x} is {aw[0]:#x}"
                                         f" and CmdDbDxe dereferences it, so the"
                                         f" driver would read {aw[0]:#x} and"
                                         f" {aw[0] + 4:#x} - which this run did not"
                                         f" write; the state and magic below are"
                                         f" then about the wrong pair of bytes\n")
                            elif aw[1] != state or aw[2] != magic:
                                fh.write(f"#   the record holds {aw[1]:#x} and"
                                         f" {aw[2]:#x} and the gate wants"
                                         f" {state:#x} and {magic:#x}; a mismatch"
                                         f" is the `U` the unseeded run printed and"
                                         f" this seed has changed nothing\n")
                            if plan.get(blk // STAGE2_BLOCK) != at:
                                fh.write(f"#   the block {blk:#x} that holds"
                                         f" {ipa:#x} is at {plan.get(blk // STAGE2_BLOCK, 0):#x}"
                                         f" in the plan, not {at:#x} where this"
                                         f" seed wrote; the guest's read and this"
                                         f" write are not the same memory\n")
        if gic is not None and alias:
            gw, gprio = gic
            typer = gw["GICD_TYPER"]
            t_irq = ((typer & 0x1f) + 1) * 32
            t_cpu = ((typer >> 5) & 7) + 1
            en = gic_intids(gw, "ISENABLER")
            pe = gic_intids(gw, "ISPENDR")
            nz = [i for i, v in enumerate(gprio) if v]
            # The four conditional readings below, taken here rather than inline:
            # each is a sentence with an f-string of its own in it, and a nested
            # replacement field is the one thing this file's Python cannot have.
            if (t_irq, t_cpu) == (MACHINE_GIC_NUM_IRQ, MACHINE_GIC_NUM_CPU):
                typer_says = ("which is what this read was built around, so the"
                              " sets below are that wide")
            else:
                typer_says = (f"AND NOT THE {MACHINE_GIC_NUM_IRQ} INTERRUPTS AND"
                              f" {MACHINE_GIC_NUM_CPU} CPU INTERFACE THIS READ WAS"
                              f" BUILT AROUND - every set below is the wrong"
                              f" width and none of it may be read")
            if nz:
                uniform = (len(nz) == MACHINE_GIC_NUM_IRQ
                           and len(set(gprio)) == 1)
                prio_says = (f" - at"
                             f" {', '.join(f'{i}:{gprio[i]:02x}' for i in nz[:24])}"
                             f"{f', and {len(nz) - 24} more' if len(nz) > 24 else ''}"
                             f", which are interrupts whose priority the payload's"
                             f" own driver wrote, because a non-secure write lands"
                             f" as 0x80 | (v >> 1) and reads back as v with its low"
                             f" bit cleared")
                if uniform:
                    prio_says += (f" - and all {MACHINE_GIC_NUM_IRQ} at one value is"
                                  f" not a machine's doing but a driver's default"
                                  f" written across a range it will never use:"
                                  f" running this same instrument against a kernel"
                                  f" of two instructions reads this row as"
                                  f" all zeros, so every byte here is the payload's"
                                  f" and the secure fill below is what it wrote"
                                  f" over")
            else:
                prio_says = (", none of them: a 0x80 written from the secure side"
                             " reads back as 0x00 (`gic_dist_get_priority`'s"
                             " `(prio << 1) & 0xff`), and a priority the payload"
                             " never wrote reads back as 0x00 as well, so this row"
                             " cannot tell the two apart on its own - but it does"
                             " say the payload wrote no priority byte at all, and"
                             " this same instrument run against a kernel of two"
                             " instructions reads it the same way, which is what"
                             " makes the secure pair below the whole of the"
                             " evidence that the fill landed")
            if diag is not None and diag[4] == 0xFFFFFFFF:
                igroupr_says = ("every interrupt into Group 1, which is what the"
                                " non-secure read above cannot show")
            else:
                igroupr_says = ("NOT the all-ones this run means to have written,"
                                " so the grouping above is not the one this header"
                                " describes")
            if diag is not None and diag[5] == 0xFF:
                pmr_says = ("raised, which is what makes the PRIMASK row above"
                            " readable at all")
            else:
                pmr_says = ("NOT raised, so the machine this run measured still"
                            " cannot deliver anything")

            # The other end of the alias, read out of the machine rather than
            # described. Every one of these words is reset-zero when the machine
            # boots and none of them is in the payload's image, so a bit that is set
            # here was set by the payload through the redirect - the read is what
            # makes "the guest's writes reach hardware" a measurement instead of a
            # consequence of the table being written correctly.
            fh.write(f"# GIC: and the block(s) above are not RAM. They are pointed at"
                     f" the machine's own interrupt controller, which is live"
                     f" hardware at {MACHINE_GIC_BASE:#x}, and these are its"
                     f" registers read back out of it after the payload ran. The"
                     f" words are reset-zero and the payload's image does not hold"
                     f" them, so what is set here was set through the alias\n")
            fh.write(f"#   distributor: CTLR {gw['GICD_CTLR']:#x} TYPER"
                     f" {typer:#x} IIDR {gw['GICD_IIDR']:#x} IGROUPR0"
                     f" {gw['GICD_IGROUPR0']:#x} ICENABLER0"
                     f" {gw['GICD_ICENABLER0']:#010x} ICPENDR0"
                     f" {gw['GICD_ICPENDR0']:#010x} ISACTIVER0"
                     f" {gw['GICD_ISACTIVER0']:#010x} ICFGR0"
                     f" {gw['GICD_ICFGR0']:#x} ICFGR1 {gw['GICD_ICFGR1']:#x}"
                     f" - the distributor is"
                     f" {'on' if gw['GICD_CTLR'] & 1 else 'OFF'}, and TYPER says"
                     f" {t_irq} interrupt(s) and {t_cpu} CPU interface(s)"
                     f" {typer_says}\n")
            fh.write(f"#     and ICENABLER0 above is NOT the complement of the enable"
                     f" set: QEMU reads both windows through one branch and"
                     f" returns the enabled bits either way"
                     f" (`arm_gic.c:1009-1027`), so the word is the same set"
                     f" printed twice and the words below are the ones to"
                     f" count\n")
            fh.write(f"#   the enable set, {MACHINE_GIC_WORDS} words from"
                     f" {MACHINE_GIC_WORDS - 1} down:"
                     f" {gic_set_words(gw, 'ISENABLER')}\n")
            fh.write(f"#     enabled in Group 1: {intids(en)}\n")
            fh.write(f"#   the pending set, the same width:"
                     f" {gic_set_words(gw, 'ISPENDR')}\n")
            fh.write(f"#     pending: {intids(pe)}\n")
            fh.write(f"#   and the priority bytes, one per interrupt from 0, as a"
                     f" NON-SECURE read of GICD_IPRIORITYR0"
                     f" ({MACHINE_GIC_BASE + GIC_PRIO_OFF:#x}):"
                     f" {len(nz)} of {MACHINE_GIC_NUM_IRQ} are not zero"
                     f"{prio_says}\n")
            fh.write(f"#   CPU interface at {MACHINE_GIC_BASE + 0x10000:#x}, which is"
                     f" where IPA page 0 was aliased: CTLR {gw['GICC_CTLR']:#x}"
                     f" PRIMASK {gw['GICC_PRIMASK']:#x} BPR {gw['GICC_BPR']:#x}"
                     f" IAR {gw['GICC_IAR']:#x} RPR {gw['GICC_RPR']:#x} HPPIR"
                     f" {gw['GICC_HPPIR']:#x} - the interface is"
                     f" {'on' if gw['GICC_CTLR'] & 1 else 'OFF'}, and an IAR of"
                     f" 0x3ff is the \"no interrupt to give you\" the GICv2 returns,"
                     f" so a value other than that is one the machine had\n")
            fh.write(f"#     and PRIMASK is the word that decides whether any of them"
                     f" can ever be delivered: `gic_update_internal` raises the"
                     f" CPU's line only when the best priority is below it"
                     f" (`arm_gic.c:200`), it resets to zero on this machine"
                     f" because nothing here is the secure side"
                     f" (`arm_gic_common.c:279-286`), and a non-secure write to it"
                     f" is refused while it sits in the lower half (`:697-709`) -"
                     f" so the payload's own ICCPMR 0xff could not repair it. The"
                     f" non-secure view of the mask is 0xfe when it is 0xff, 0x00"
                     f" when it is 0 or 0x80, and nothing else, which is why a 0"
                     f" here is the stop and a 0xfe is not\n")
            if args.el3_gic_secure and diag is not None:
                fh.write(f"#   and the same two registers read the other way, by"
                         f" the stub itself while it was still the secure side and"
                         f" before SCR_EL3.NS was set, out of its own 0x1f00 slot:"
                         f" GICD_IGROUPR0 {diag[4]:#x} and GICC_PMR"
                         f" {diag[5]:#x} - written by the EL3 block this run"
                         f" assembled in ({igroupr_says}), and the mask"
                         f" ({pmr_says}). A zero in the non-secure row above with"
                         f" a value here is the view and the register, side by"
                         f" side, and not one claim read twice\n")
            else:
                fh.write(f"#   and nothing raised that mask from the secure side in"
                         f" this run, because --el3-gic-secure was not passed: the"
                         f" two registers are left exactly as the machine's own"
                         f" non-secure reset leaves them, and the PRIMASK row above"
                         f" is then a statement about this machine and not about"
                         f" the payload\n")
            fh.write(f"#   the board's second window, APSS_GIC500_GICR, which"
                     f" shares the block: {MACHINE_GIC_BASE + 0x60000:#x} holds"
                     f" {gw['GICR window (aliased)']:#010x}, which a GICv2 has"
                     f" nothing at - the redistributor is a GICv3 idea and this"
                     f" machine is a GICv2, so the payload's V2 path never reads it\n")
            # Four rules for reading the rows above. The first is a limit of the
            # read itself, and it is the one that came out of the first run with
            # real hardware behind these rows: `pmemsave` carries QEMU's
            # unspecified attributes and this machine has the security extensions
            # on, so every word was read as a NON-SECURE access. `GICD_IGROUPR` is
            # RAZ/WI for such an access by definition, `GICD_ISENABLER` and
            # `GICD_ISPENDR` return only the Group-1 bits and a priority mask in
            # the lower half reads zero - so the zeros above are the non-secure view
            # and not proof that the payload wrote nothing. The second is what makes
            # the enable set mean anything at all: the Group-1 bits in it are the
            # payload's own enables only under `--el3-gic-secure`, because until
            # something groups the interrupts a non-secure enable lands nowhere, and
            # the row is then empty whatever the payload asked for. The third is the
            # one that matters for the firmware's own claim:
            # `PcdArmArchTimerSecIntrNum` and `PcdArmArchTimerIntrNum` are 17 and 18
            # in this platform (`BitraPkg.dsc.inc:51-52`) while `-M virt` raises its
            # generic timer as PPIs 13 and 14, INTIDs 29 and 30, so an enabled bit
            # at 17 or 18 with a pending bit at 29 or 30 is a delivered interrupt
            # the payload did not register for. The fourth is a limit of the
            # instrument: reading GICC_IAR through the monitor is a real read of the
            # register, and on this machine that acknowledges, so the value above is
            # what was pending when the run ended and the read itself may have taken
            # one away
            fh.write(f"#   read with four rules, and the first is the one that"
                     f" decides how the zeros above may be used: `pmemsave`"
                     f" carries QEMU's unspecified attributes while this machine has"
                     f" the security extensions on, so every word above is a"
                     f" non-secure view - IGROUPR is RAZ/WI for one, the enable and"
                     f" pending sets return only Group-1 bits, and a priority mask in"
                     f" the lower half reads zero, so none of those zeros says the"
                     f" payload wrote nothing; what does say its writes arrived is"
                     f" the pair of words that are non-secure-writable anyway,"
                     f" GICD_CTLR's Group-1 enable and GICC_CTLR's, both of which"
                     f" read back set. Second: the enable set's Group-1 bits are the"
                     f" payload's own enables *only* under --el3-gic-secure, because"
                     f" until a secure world groups the interrupts a non-secure"
                     f" enable lands nowhere; without that flag the rows are empty"
                     f" whatever the payload asked for. Third: BitraPkg sets"
                     f" PcdArmArchTimerSecIntrNum 0x11 and PcdArmArchTimerIntrNum 0x12"
                     f" while this machine raises its generic timer as the PPIs 0x1e"
                     f" for the non-secure EL1 physical timer the payload's own"
                     f" driver programs (USE_PHYSICAL_TIMER = 1), 0x1d for the secure"
                     f" one, 0x1b for the virtual timer and 0x1a for the"
                     f" hypervisor's - measured, not inferred from the DTB: a guest"
                     f" that arms CNTP alone gets INTID 30 and one that arms CNTV"
                     f" alone gets 27. So an enable at 18 with a pending at 30 is a"
                     f" real interrupt the payload did not register for, and the 26"
                     f" and 27 in its enable set are the two timer numbers it did get"
                     f" right, out of ArmPkg.dec's defaults rather than BitraPkg's."
                     f" Fourth: reading GICC_IAR is a real read that acknowledges on"
                     f" this machine, so the value above is what was pending when the"
                     f" run ended, not a count of what was raised\n")
        fh.write(f"# region  {name} at {base:#x}, dumping {need:#x} bytes\n")

        fh.write(f"# {len(lines)} rows, weakest margin {worst:.2f} of 60 sub-blocks,"
                 f" {weak} characters under {args.min_margin}\n")
        if gaps:
            fh.write(f"# {len(gaps)} GAP(S) - samples that could not be joined onto"
                     f" the stream: the tail of what had been read was not the head"
                     f" of the screen, so the rows below a gap are not known to"
                     f" continue the rows above it. Each gap carries how many of the"
                     f" screen's rows the stream already held, which is what the two"
                     f" causes read as and what tells them apart. A row the console"
                     f" rewrote in place - a line printed without a newline, so the"
                     f" next print continued on that row - makes the screen almost"
                     f" all rows the stream already holds, and appending it repeats"
                     f" the log above the gap instead of extending it: the rows to"
                     f" read are the ones after the copy ends, and nothing the run"
                     f" printed is missing. Text printed between two samples makes"
                     f" the screen almost all rows the stream does not hold, and no"
                     f" reading recovers it.\n")
            for t, n, again in gaps:
                fh.write(f"#   at {t:.2f}s, a screen of {n} rows, of which {again}"
                         f" are rows the stream already holds\n")
        # A row the console could not fit is the one thing this file cannot show as
        # one line: the console's own wrap puts the tail on the next row, and a line
        # that is exactly `columns` wide puts the cursor there without having
        # wrapped. Nothing on the screen separates the two - the tail starts at
        # column 1 either way - so both are counted and named rather than guessed
        # at. Measured on the 4.181 gate row: `...w8c=0001` read as a whole line
        # says the mode word is 1, and the `0000` the row below it holds says the
        # word is 0x10000, which is the difference between a gate that is open and
        # a gate that is shut.
        full = [i for i, line in enumerate(lines) if len(line) == geo["columns"]]
        if full:
            fh.write(f"# {len(full)} row(s) fill all {geo['columns']} columns and"
                     f" therefore continue on the row below, at"
                     f" {', '.join(str(i) for i in full[:12])}"
                     f"{', ...' if len(full) > 12 else ''}"
                     f" - each one's next row is that line's tail and not a line of"
                     f" its own\n")
        rows = lines
        if args.join_wrap:
            # Pairwise, and once per full row: a row is glued to the row below it
            # and the pair becomes one entry, so a glued row is never itself the
            # left half of another pair. Testing the accumulated row instead would
            # cascade - the first pair is longer than the console is wide, so every
            # row after it would be glued to it in turn.
            rows, glued, i = [], 0, 0
            while i < len(lines):
                if len(lines[i]) == geo["columns"] and i + 1 < len(lines):
                    rows.append(lines[i] + lines[i + 1])
                    glued += 1
                    i += 2
                else:
                    rows.append(lines[i])
                    i += 1
            fh.write(f"# --join-wrap: {glued} row(s) appended to the full row above"
                     f" them, {len(lines)} -> {len(rows)}. Applied without checking,"
                     f" so a line that is exactly {geo['columns']} wide has had the"
                     f" line below it glued to it, and a line that wrapped twice is"
                     f" still short by its last row\n")
        for i, line in enumerate(rows):
            fh.write(f"{i:4d} |{line}|\n")

    print(f"\n{len(lines)} rows from {screens} screens;"
          f" weakest margin {worst:.2f}, {weak} characters under {args.min_margin}")
    if full:
        print(f"  {len(full)} of those rows fill all {geo['columns']} columns and"
              f" continue on the row below (row"
              f" {', '.join(str(i) for i in full[:6])}"
              f"{', ...' if len(full) > 6 else ''})"
              + (f"; --join-wrap glued {glued}" if args.join_wrap else
                 "; read them joined or they will be read short"))
    for t, n, again in gaps:
        print(f"  at {t:.2f}s a screen of {n} rows, {again} of them rows the stream"
              f" already holds"
              + (" - reads as a rewritten row: the rows below repeat the log, and"
                 " the text after the copy is what the run added"
                 if again * 2 >= n else
                 " - reads as text printed between samples, and the stream is not"
                 " continuous there"))
    if tables:
        _l1_0, l2, backing, diag, _l3 = tables
        wrong = [i for i, pa in sorted(plan.items())
                 if (l2[i] & 0x3) != 0x1
                 or (l2[i] & ~(STAGE2_BLOCK - 1)) != pa]
        print(f"stage 2 redirected {len(plan) - len(wrong)}/{len(plan)} of the"
              f" platform's low regions to RAM of their own, one 2 MB block each;"
              f" {ZERO_MEM_IPA:#x} reads {backing[0]:#x}")
        print(f"  as the guest reads them back: VTCR_EL2={diag[0]:#x}"
              f" VTTBR_EL2={diag[1]:#x} HCR_EL2={diag[2]:#x} SCR_EL3={diag[3]:#x}")
    if gic is not None and alias:
        gw, gprio = gic
        en = gic_intids(gw, "ISENABLER")
        pe = gic_intids(gw, "ISPENDR")
        nz = [i for i, v in enumerate(gprio) if v]

        print(f"gic      the {len(alias)} aliased block(s) are the machine's own"
              f" controller at {MACHINE_GIC_BASE:#x}, not RAM, and it reads back:"
              f" distributor {'on' if gw['GICD_CTLR'] & 1 else 'OFF'}"
              f" (CTLR {gw['GICD_CTLR']:#x} TYPER {gw['GICD_TYPER']:#x} IIDR"
              f" {gw['GICD_IIDR']:#x}), Group-1 enables"
              f" {gic_set_words(gw, 'ISENABLER')}, Group-1 pending"
              f" {gic_set_words(gw, 'ISPENDR')}")
        print(f"  as interrupt IDs: enabled {intids(en)}; pending {intids(pe)},"
              f" and {len(nz)} of {MACHINE_GIC_NUM_IRQ} priority byte(s) are not"
              f" zero")
        if len(nz) == MACHINE_GIC_NUM_IRQ and len(set(gprio)) == 1:
            print(f"  and all {MACHINE_GIC_NUM_IRQ} of those bytes hold the SAME"
                  f" value ({gprio[0]:#04x}), which is a driver's default written"
                  f" across a range it will never use and not a machine's doing:"
                  f" the same instrument against a two-instruction kernel reads"
                  f" this row as all zeros")
        print(f"  CPU interface {'on' if gw['GICC_CTLR'] & 1 else 'OFF'}"
              f" (CTLR {gw['GICC_CTLR']:#x} PRIMASK {gw['GICC_PRIMASK']:#x} BPR"
              f" {gw['GICC_BPR']:#x} IAR {gw['GICC_IAR']:#x} RPR"
              f" {gw['GICC_RPR']:#x} HPPIR {gw['GICC_HPPIR']:#x}); the"
              f" redistributor window reads"
              f" {gw['GICR window (aliased)']:#x}, which a GICv2 has nothing at")
        if diag is not None and args.el3_gic_secure:
            print(f"  and the stub's own SECURE reads of two of those registers,"
                  f" out of its 0x1f00 slot: GICD_IGROUPR0 {diag[4]:#08x},"
                  f" GICC_PMR {diag[5]:#x} - the non-secure zero above and the"
                  f" register itself, side by side")
        else:
            print(f"  every word above is a NON-SECURE view - `pmemsave` carries"
                  f" QEMU's unspecified attributes and this machine has the"
                  f" security extensions on - so IGROUPR is RAZ here, the enable"
                  f" and pending sets hold only Group-1 bits, and a priority mask"
                  f" in the lower half reads zero: those zeros say nothing about"
                  f" what the payload wrote, and the two words that are"
                  f" non-secure-writable anyway (CTLR's Group-1 enable in both"
                  f" windows) read back set, which is what says its writes"
                  f" arrived and were refused")
        if en and not pe:
            print(f"  enabled and not pending: {intids(en)} - a line asked for"
                  f" that the machine never raised is the difference between a"
                  f" controller that delivers and a number that does not match")
        if any(i in (29, 30) for i in pe):
            print(f"  and the pending set includes 29/30, the two EL1 physical"
                  f" timers, of which 30 is the non-secure one this payload's own"
                  f" driver programs (USE_PHYSICAL_TIMER = 1) while BitraPkg tells"
                  f" it that interrupt is 18 and ArmPkg's default is 30 - the"
                  f" interrupt is real and its number is not the one the payload"
                  f" asked for")
        if gw["GICC_PRIMASK"] == 0:
            print(f"  PRIMASK reads 0, and that is the stop that comes before the"
                  f" numbering: `gic_update_internal` raises the CPU's line only"
                  f" when the best priority is below the mask (`arm_gic.c:200`),"
                  f" so with the mask at zero nothing on this machine is"
                  f" deliverable whatever the payload enabled and whatever number"
                  f" it used")
    if seed:
        smem_base, smem_size = seed[1], seed[2]
        if seed_got is None:
            print("seed     SEEDED RUN, but the seed could not be read back out of"
                  " the machine - so nothing here says it was written")
        else:
            (pool_page, pointer, struct_pool, written, body, flag,
             toc, toc_bytes, table, table_bytes, aop_got, aop_bytes) = seed_got
            print(f"seed     FABRICATED container, read back out of the machine:"
                  f" {pool_page:#x} holds the pointer {pointer:#x}, and"
                  f" {struct_pool:#x} holds {body[0]:#x} {body[1]:#x} {body[2]:#x}"
                  f" (base {smem_base:#x}, size {smem_size:#x}), and SMEM"
                  f"{SEED_SMEM_FLAG_OFF:#x} holds {flag:#x}"
                  f" - {'consistent' if seed_ok else 'NOT WHAT THE HEADER DESCRIBES'}")
            rung = ("both as this file's own copy of the assembly says" if seed_ok
                    else "AND AT LEAST ONE OF THEM IS NOT WHAT THE ASSEMBLY SAYS")
            print(f"  and the rung above it in SMEM: the TOC page {toc:#x} and the"
                  f" heap table {table:#x} hold"
                  f" {len(toc_bytes)} and {len(table_bytes)} byte(s) read back,"
                  f" {rung}")
        if drift:
            for n, here, there in drift:
                print(f"  the seed constant {n} is {here:#x} in this file and"
                      f" {there:#x} in the stub's assembly - the two files have"
                      f" drifted and every check above used this file's copy")
    if aop:
        at, ipa, state, magic = aop
        if seed_got is None:
            print("aop seed SEEDED, but the read-back failed, so nothing here says"
                  " the word at the gate was written")
        else:
            aw = aop_words(aop_bytes, sc["SEED_AOP_REC_OFF"])
            rec = sc["SEED_AOP_REC_OFF"]
            print(f"aop seed FABRICATED record for CmdDbDxe's gate, read back out of"
                  f" the machine: {aop_got:#x} holds"
                  f" {'nothing readable' if aw is None else f'{aw[0]:#010x}'}, and"
                  f" the record {rec:#x} past it"
                  f" {'was not read' if aw is None else f'{aw[1]:#010x} {aw[2]:#010x}'}"
                  f" - the word should point at {ipa + rec:#x}"
                  f" and the two values there should be {state:#x} and {magic:#x}"
                  f" - {'consistent' if aop_ok else 'NOT WHAT THE HEADER DESCRIBES'}")
    if gaps:
        print(f"{len(gaps)} sample(s) could not be joined onto the stream, listed"
              f" above and in the header of {os.path.relpath(args.out, REPO)}")
    print(f"wrote {os.path.relpath(args.out, REPO)}")
    bad_seed = (seed_got is None and seed is not None) or seed_ok is False
    bad_aop = (seed is not None and aop and (seed_got is None or aop_ok is False))
    return 1 if (gaps or weak or bad_seed or bad_aop or drift) else 0


if __name__ == "__main__":
    sys.exit(main())
