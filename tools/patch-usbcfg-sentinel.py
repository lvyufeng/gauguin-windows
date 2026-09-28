#!/usr/bin/env python3
"""Rewrite the one instruction in UsbConfigDxe that shuts XhciPciEmulation's gate.

Why this exists. Steps 4.181-4.183 established a chain of three facts about the
shipped `UsbConfigDxe` and the sibling `XhciPciEmulationDxe`:

  * `XhciPciEmulation`'s `DriverBinding->Supported` accepts an `E722B03F`
    interface only if `[iface+0x88] <= 3` **and** `[iface+0x8c] == 1` (VA
    `0x1464`, read off the shipped bitra blob);
  * the interface this platform produces carries `[iface+0x8c] == 0x00010000`,
    which is `UsbConfigDxe`'s own *unassigned* sentinel for that word, and the
    only caller that ever replaces it with a real mode is `UsbStartController`,
    which in this guest never runs because its PMIC and IOMMU bring-up fails
    first;
  * and even when the handle is offered to the emulation after dispatch (4.183
    did this by connecting it), the emulation declines -- so the sentinel is a
    barrier in its own right, independent of the dispatch order.

So the emulated USB host controller cannot be published in this firmware, and
`pciio` stays zero, as long as that word holds `0x10000`. Two of the three
candidate repairs are out of reach: re-connecting the handle is measured not to
work (4.183), and `UsbStartController` lives inside the same shipped binary and
needs a working PMIC to run at all. What is left is to change the word.

Step 4.185 changed it, and the change is necessary but not sufficient: the gate
opens, the emulation binds and reaches `ConfigUsb`, and `ConfigUsb`'s entry guard
refuses the *other* word of the same record -- the index -- so the run still ends
with `pciio=0`. That is why this file now carries three sites rather than one, and
why the two live sites are meant to be applied together; the paragraph below on
the individual sites says what each does and what pairing them costs.

Which word, and which store, took one more step than expected. Step 4.184
patched the record initialiser's sentinel store and the word did not move: the
gate still read `w8c=00010000` on every pass. The census's own `w88` says why.
The interface the gate reads is `rec_base + 0x100`, and the only stores into the
two gated words in the whole image are:

    39e0: str  w9,  [x8, #0x188]     ; rec_base+0x188 == rec[1]+0xB0 == iface+0x88
    39e4: orr  w10, wzr, #0x10000
    39e8: str  w10, [x8, #0x18c]     ; rec_base+0x18c == rec[1]+0xB4 == iface+0x8C
    ...
    3b5c: str  w9,  [x11, #0xb0]     ; rec[i]+0xB0, i = the loop counter
    3b70: str  w9,  [x8,  #0xb4]     ; rec[i]+0xB4, i = the loop counter
    ...
    50f0: str  w8,  [x11, #0xb0]     ; rec[i]+0xB0, i = a mode-set argument
    5108: str  w8,  [x9,  #0xb4]     ; rec[i]+0xB4, the same argument
    ...
    4da0: str  w9,  [x10, #0xb4]     ; rec[i]+0xB4 == 0x10000, UsbStopController

and the loop at `0x3b1c` is bounded by `cmp x8, #0x1 ; b.hs` -- it runs for
`Index = 0` alone. It initialises **record 0**, and record 0 is not the record
the `E722B03F` interface points into. Record 1 -- index 1, `rec_base + 0xd8`, the
host-client record, whose `+0x28` is `rec_base + 0x100` -- is initialised by hand,
a few instructions earlier in the same function (which names itself in its own
error strings: `"UsbConfigInit: Error - Failed to install USB_CONFIG protocol"`):

    39bc: add  x0, x8, #0x100         ; x8 = rec_base, so dest = rec_base+0x100
    39c4: add  x1, x1, #0x168         ; the template
    39c8: mov  w9, #0xa8
    39d4: bl   memcpy
    39d8: orr  w9, wzr, #0x1
    39e0: str  w9,  [x8, #0x188]      ; rec_base+0x188 = rec[1]+0xB0 = iface+0x88 = 1
    39e4: orr  w10, wzr, #0x10000
    39e8: str  w10, [x8, #0x18c]      ; rec_base+0x18c = rec[1]+0xB4 = iface+0x8C
    39ec: mov  x1, xzr
    39f0: str  x1,  [x8, #0xe0]       ; and it clears the two words below
    39f4: str  x1,  [x8, #0xe8]
    ...
    39b4 was reached only because [rec_base+0xe8] was zero, and this block zeroes
    that word itself, so the guard does not latch: the block re-runs on every
    entry. What the census proves is the part that matters -- in this guest no
    *other* store reaches the gated word afterwards.

and the interface this produces is the memory the gate reads, by the same
function's next call, three instructions' worth of argument setup later:

    3aa4: adrp x1, 0x11000 ; add x1, x1, #0x98   ; 0x11098, and the GUID at file
                                                 ; offset 0x11098 is
                                                 ; E722B03F-B250-42CE-8EBD-5BD51812D037
    3a9c: add  x0, x9, #0xe8                     ; the handle slot, rec_base+0xe8
    3aa0: add  x2, x9, #0x100                    ; the interface, rec_base+0x100
    3ab4: blr  x8                                ; through [0x11590]+0x148

-- which is `InstallMultipleProtocolInterfaces` for the very GUID `Supported`
opens. So `iface` in the gate's row and `rec_base+0x100` here are the same
address, and `iface+0x8C` is the word written at `0x39e8`.

The sites, therefore, are three, and they are not equivalent:

  * `host` (`0x39e4`) is the live writer of the word `Supported` reads, and the
    one this file exists to change. Rewriting it puts the record in the state
    `UsbStartController` leaves a started controller in: the word becomes `0x1`,
    which is the *mode*, and `1` is the mode the emulation's second clause asks
    for. Step 4.185 built and ran this site alone, and it is what took the gate
    from shut to open: `P2 GATE2 w8c` moved `00010000` -> `00000001` on every
    pass, and `P2 SUPP BEB12BEE-… s=` moved `Unsupported` -> `Success`.
  * `index` (`0x39d8`) is the *other* word of the same hand-written block, and
    4.185's run names it: with the gate open the emulation opens `E722B03F`,
    calls `ConfigUsb` through the interface's `+0x10` thunk, and is refused --
    `ConfigUsb: ConfigUsb: Error - Invalid CoreNum passed: 1`. That `1` is
    `[iface+0x88]`, i.e. the word this site writes, and `ConfigUsb` refuses it
    *by value*: `0x2ea4: cmp w8, #0x1 ; b.hs` takes the `EFI_INVALID_PARAMETER`
    exit, and the same value is used as a record index (stride `0xd8` from
    `0x112b8`) to fetch `UsbCoreIfc` from `rec[i]+0x18`. So the gate needs
    `+0x8C == 1` **and** `ConfigUsb` needs `+0x88 == 0`, and neither site alone
    is a working controller: `host` alone reaches the guard and stops, `index`
    alone does not open the gate at all. Paired, they describe record 1 with
    record 0's index -- a *counterfeit* construction-time value, and the run it
    produces must be read as a probe of what `ConfigUsb` does next, never as a
    device behaviour.
  * `loop` (`0x3b6c`) is the one 4.184 patched, and that is 4.184's result: it
    changes nothing measurable, because the loop it sits in is
    `for (Index = 0; Index < 1; Index++)` (`0x3af4` sets the counter, `0x3b00`
    `cmp x8, #0x1 ; b.hs` leaves the loop) and initialises **record 0**, which is
    not the record the `E722B03F` interface points into. It is kept, not deleted,
    because the measurement that it changes nothing is a result this repository
    has to be able to reproduce, and because a future step may want record 0's
    word changed on purpose. It is *not* the default.

The cost is real and is the reason this is a switch and not a default. The same
word is the record's *index* and *mode*, and other code in the same binary reads
them as such: at `0x5034` a store of `0x10000` is what tells the caller "this core
is unassigned, do not call the stop helper", and at `0x49b8` `UsbStopController`
compares the word against a target mode and reports `"Unable to stop controller
on core %d (curr mode %d, target mode %d)"` on a mismatch; `UsbStartController`
(`0x4dc8`) guards its own arguments the same way this file's `index` site feeds
`ConfigUsb` -- `0x4df4: cmp w8, #0x1 ; b.hs` on the index and
`0x4e08: cmp w8, #0x10000 ; b.lo` on the mode -- and writes `rec[i]+0xB0 = i` and
`rec[Index]+0xB4 = Mode` (`0x50f0`, `0x5108`). With these patches a record that
was never started reads as started, so those paths would take the wrong branch.
In this guest nothing starts a controller and nothing calls `UsbStopController`,
so the change is observable only through the gate; on a device with a working
PMIC it would not be, and none of these patches may be read as a device-side
repair.

Usage:
    tools/patch-usbcfg-sentinel.py --check FILE
    tools/patch-usbcfg-sentinel.py --check FILE --site host
    tools/patch-usbcfg-sentinel.py --apply FILE --site host|index|loop
    tools/patch-usbcfg-sentinel.py --apply FILE --site host,index
    tools/patch-usbcfg-sentinel.py --in-image IMG --site S[,S...] --expect patched|original

`--apply` is in place and refuses a file that is neither the known pristine image
nor already patched, so it cannot be run twice or against the wrong binary.

A comma-separated `--site` applies to several sites in one pass, which is how the
paired `host,index` build is made: the two words are in the same record and
neither alone is a working controller, so the experiment that asks what
`ConfigUsb` does next has to change both. See the note on `counterfeit` above --
the pair is a construction-time value no device would produce, and the run it
makes is a probe of the shipped binary.

`--in-image` is the gate that a build has to pass, and it deliberately does not
look for the file at a fixed offset. The build runs `GenFw` over a `PE32` binary
module before packing it, so what lands in the volume is not guaranteed to be
the input byte for byte and the VA == offset arithmetic above cannot be assumed
to hold inside an image. What is checked instead is the eight bytes of the
instruction pair -- the `orr` together with the store that follows it -- because
the bare `orr` is not unique: ten instructions in this image materialise
`0x10000`. Each eight-byte pair used here was counted in the shipped binary and
occurs once (see `SITES`), and what the gate asserts is that the volume carries
the expected variant of that one pair exactly once and the other variant not at
all. That is a statement about the volume that came out, which is the only
statement worth gating on.
"""
import argparse
import hashlib
import importlib.util
import os
import struct
import sys

# The shipped image: identical in device/dxe/ and uefi/Binaries/gauguin/, and the
# one this project has measured through five steps. A different sha256 means a
# different build, and the offsets below are read off the disassembly of *this*
# one -- so a mismatch is a refusal, not a warning.
PRISTINE_SHA256 = "6943cc615f7d4ba502c87bcf14a76e6e1398975a4101ed2711ba9e1c6e2566f5"

# VA == file offset in this image, checked below against the section table rather
# than assumed: .text VMA 0x1000 / file 0x1000, .data VMA 0x11000 / file 0x11000.
# So the offset of an instruction is its VA.
#
# Each entry is (VA of the `orr`, its original word, its patched word, the word
# that follows it, a one-line description). The pair (original, following) must
# occur exactly once in the shipped binary or the gate below is not a gate; that
# count is asserted by `--check-seeds`.
# What the two instruction words of each site read as, for the report only. The
# pair convention above is "the rewritten instruction and whatever follows it",
# so the second half is a store for two of the three sites and a load for the
# third; naming it "the store that follows" for every site -- which this report
# did while there was one site -- misdescribed `index` and printed a fixed
# `orr w?, wzr, #0x10000` label over a word that is not that instruction.
WORDS = {
    "host":  ("orr  w10, wzr, #0x10000", "mov  w10, #0x1"),
    "index": ("orr  w9,  wzr, #0x1",     "mov  w9,  wzr"),
    "loop":  ("orr  w9,  wzr, #0x10000", "mov  w9,  #0x1"),
}

SITES = {
    "host": (
        0x39E4,
        0x321003EA,     # orr  w10, wzr, #0x10000
        0x5280002A,     # mov  w10, #0x1
        0xB9018D0A,     # str  w10, [x8, #0x18c]  -> rec[1]+0xB4 == iface+0x8C
        "the mode word of the host-client record, in UsbConfigInit's own"
        " one-time initialisation -- the store the gate reads",
    ),
    "index": (
        0x39D8,
        0x320003E9,     # orr  w9, wzr, #0x1
        0x2A1F03E9,     # mov  w9, wzr
        0xF85A83A8,     # ldur x8, [x29, #-0x58]
        "the index word of the same record, written by the same block eight"
        " bytes earlier -- the value ConfigUsb's entry guard rejects",
    ),
    "loop": (
        0x3B6C,
        0x321003E9,     # orr  w9, wzr, #0x10000
        0x52800029,     # mov  w9, #0x1
        0xB900B509,     # str  w9, [x8, #0xb4]  -> rec[0]+0xB4 (loop runs for i=0)
        "the sentinel of record 0 in the initialiser loop, which is bounded by"
        " Index < 1 and never reaches the gated record (4.184's site)",
    ),
}
DEFAULT_SITE = "host"

# A second control, kept because it is the cheapest way to show the gate reads a
# number and not a constant: the same site with `mov w10, #0` in it, which the
# gate's second clause (`== 1`) must reject for the opposite reason.
SITE_ZEROED = 0x5280000A


def _fv_inventory():
    """tools/fv-inventory.py, whose name is not importable as it stands."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fv-inventory.py")
    spec = importlib.util.spec_from_file_location("fv_inventory", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_sites(text):
    """A comma-separated `--site` value as a list of known site names.

    Several sites in one invocation is not a convenience: `host` and `index` are
    two words of the same record, neither of which alone leaves a controller the
    publisher will initialise, so the run that asks what happens next has to write
    both (and is a counterfeit construction-time record -- see the module
    docstring). Order is kept as given, minus duplicates; the writes themselves go
    in ascending offset order so that a log of two runs is comparable.
    """
    names = [s.strip() for s in text.split(",") if s.strip()]
    if not names:
        sys.exit("error: --site was given but names no site")
    bad = [n for n in names if n not in SITES]
    if bad:
        sys.exit(f"error: unknown site(s) {', '.join(bad)} - "
                 f"known: {', '.join(SITES)}")
    out = []
    for n in names:
        if n not in out:
            out.append(n)
    return out


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def pairs(site):
    """(original 8 bytes, patched 8 bytes) for one site, little-endian."""
    _va, orig, patched, follows, _note = SITES[site]
    return (struct.pack("<II", orig, follows), struct.pack("<II", patched, follows))


def state(data, site):
    """'pristine', 'patched', or a string naming what is wrong with the site."""
    va, orig, patched, follows, _note = SITES[site]
    if len(data) < va + 8:
        return "too short to hold the site"
    word = struct.unpack_from("<I", data, va)[0]
    word2 = struct.unpack_from("<I", data, va + 4)[0]
    if word2 != follows:
        return (f"the instruction after the site is {word2:#010x}, not "
                f"{follows:#010x} - this is not the image these offsets were "
                f"read off")
    if word == orig:
        return "pristine"
    if word == patched:
        return "patched"
    if word == SITE_ZEROED and site == DEFAULT_SITE:
        return "zeroed"
    return (f"the site holds {word:#010x}, which is neither the original "
            f"{orig:#010x} nor the patched {patched:#010x}")


def overall(states):
    """One word for a whole file, over every site asked about."""
    vals = set(states.values())
    if vals == {"pristine"}:
        return "pristine"
    if vals == {"patched"}:
        return "patched"
    return "mixed (" + ", ".join(f"{k} {v}" for k, v in states.items()) + ")"


def check_file(path, sites):
    data = open(path, "rb").read()
    print(path)
    print(f"  sha256  {sha256(data)}")
    states = {}
    for site in sites:
        va, orig, patched, _f, note = SITES[site]
        st = state(data, site)
        states[site] = st
        print(f"  {site:7} {va:#06x}  {st:10} {struct.unpack_from('<I', data, va)[0]:#010x}"
              f"   {note}")
    print(f"  state   {overall(states)}")
    return 0


def check_seeds(path):
    """The gate's own precondition: each site's pair is unique in the image."""
    data = open(path, "rb").read()
    bad = 0
    for site in SITES:
        po, pp = pairs(site)
        no, np_ = data.count(po), data.count(pp)
        print(f"  {site:7} original pair {no}   patched pair {np_}"
              f"   {'ok' if no == 1 and np_ == 0 else 'NOT UNIQUE - the gate would be void'}")
        bad += 0 if (no == 1 and np_ == 0) else 1
    return 0 if not bad else 2


def check_image(img, sites, expect):
    """Does the volume inside IMG carry the instruction pairs we asked for?

    Reads the payload out of the Android boot image with tools/fv-inventory.py, so
    the volume this examines is the one the build actually produced rather than
    the one it meant to produce.

    Every site named is checked, and each has to be exactly one of the variant
    asked for and none of the other. With several sites the checks are
    independent -- the pairs are eight bytes each and distinct -- so a volume that
    carries the `host` patch and not the `index` one fails here rather than
    passing on the strength of the other.
    """
    inv = _fv_inventory()
    # unpack() walks boot image -> FD -> FVMAIN and prints two lines of its own
    # about the payload and the inner volume; they are left in, because this is
    # the same descent every other gate in this repository reads and a gate that
    # hid it would be the only one whose input is unstated.
    _out, _len, _offs, inner = inv.unpack(img)

    print(f"{os.path.basename(img)}: FVMAIN {len(inner)} bytes")
    for site in sites:
        po, pp = pairs(site)
        n_orig = inner.count(po)
        n_patch = inner.count(pp)
        va, orig, patched, follows, note = SITES[site]

        print(f'  site "{site}" @ {va:#06x}: {note}')
        w_o, w_p = WORDS[site]
        print(f"  {w_o + f' then {follows:#010x}':<48} {n_orig}   (original)")
        print(f"  {w_p + f' then {follows:#010x}':<48} {n_patch}   (patched)")

        want, other, want_n = (
            ("patched", "original", n_patch) if expect == "patched"
            else ("original", "patched", n_orig))
        if want_n != 1 or (n_orig + n_patch) != 1:
            sys.exit(f"error: expected exactly one {want} pair for site {site} in "
                     f"the volume, found {n_patch} patched and {n_orig} original")
        print(f'  ok: the volume carries the {want} pair of site "{site}" once '
              f"and no {other} pair")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", metavar="FILE", help="report state, change nothing")
    g.add_argument("--check-seeds", metavar="FILE",
                   help="count every site's pairs in a pristine image")
    g.add_argument("--apply", metavar="FILE", help="patch in place")
    g.add_argument("--in-image", metavar="IMG",
                   help="check the volume inside a built payload (needs --site)")
    ap.add_argument("--site", metavar="S[,S...]",
                    help=f"which instruction(s), comma-separated (default "
                         f"{DEFAULT_SITE} for --check); known: {', '.join(SITES)}")
    ap.add_argument("--expect", choices=("patched", "original"),
                    help="with --in-image: which pair the volume should carry")
    args = ap.parse_args()
    sites = parse_sites(args.site) if args.site else None

    if args.in_image:
        if not sites or not args.expect:
            sys.exit("error: --in-image needs --site and --expect")
        check_image(args.in_image, sites, args.expect)
        return
    if args.expect:
        sys.exit("error: --expect only means something with --in-image")

    if args.check_seeds:
        sys.exit(check_seeds(args.check_seeds))

    if args.check and not sites:
        return check_file(args.check, list(SITES))
    if args.check:
        return check_file(args.check, sites)

    # --apply: the site has to be named. Three sites with different meanings and a
    # default among them is how a build ends up patching the wrong instruction,
    # which is exactly what 4.184 did.
    if not sites:
        sys.exit(f"error: --apply needs --site {{{','.join(SITES)}}} - "
                 f"\"{DEFAULT_SITE}\" is the store the gate reads, \"index\" is the"
                 f" word ConfigUsb's guard reads in the same record, \"loop\" is"
                 f" record 0's sentinel and changes nothing measurable")

    path = args.apply
    data = bytearray(open(path, "rb").read())
    dig = sha256(data)
    st = state(data, sites[0])

    # Both checks before the write: the site says this is the image the offsets
    # were read off, the digest says it is the build this project has measured.
    if st not in ("pristine", "patched"):
        sys.exit(f"error: {path}: {st}")
    if dig != PRISTINE_SHA256:
        sys.exit(f"error: {path} has sha256 {dig}, but these offsets were read off\n"
                 f"       {PRISTINE_SHA256}\n"
                 f"       and a different build is a different set of offsets")

    # Ascending offset, so a two-site run writes the record's words in the order
    # they appear in the image and the log reads like the source does.
    print(path)
    for site in sorted(sites, key=lambda s: SITES[s][0]):
        va, orig, patched, _f, _n = SITES[site]
        st = state(data, site)
        if st == "patched":
            sys.exit(f"error: {path} already carries the {site} patch "
                     f"(sha256 {dig})")
        if st != "pristine":
            sys.exit(f"error: {path}: site {site}: {st}")
        struct.pack_into("<I", data, va, patched)
        print(f"  site \"{site}\"  {va:#06x}: {orig:#010x} -> {patched:#010x}")
    print(f"  sha256  {dig}\n       -> {sha256(bytes(data))}")
    open(path, "wb").write(bytes(data))


if __name__ == "__main__":
    main()
