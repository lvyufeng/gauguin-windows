#!/usr/bin/env python3
"""Read the loaded/failed split of a `P2 SEQ` off the *volume*, not off the panel.

`P2 SEQ` says 27 of the 46 promoted drivers failed at `CoreLoadImage` and that
their entry points were never called. `docs/08` has carried "which 27, and why"
as blocked on the phone, on the grounds that the status behind each `L` lives in
`P2 WHY` and `P2 WHY` has never been photographed. That is true of the *status*
and it is not true of the *mechanism*, because the mechanism is a property of
the 46 images and this tool reads all 46 out of the volume the payload carries.

THE ONE CALL.  `CoreLoadImage` -> `CoreLoadImageCommon` -> `CoreLoadPeImage`
(`Mu_Basecore/MdeModulePkg/Core/Dxe/Image/Image.c`), and the reachable returns
for an Apriori-promoted FFS driver -- the caller passes `DriverEntry->
FvFileDevicePath` and `DstBuffer = NULL` -- are:

  :1311  EFI_NOT_FOUND       `GetFileBufferByFilePath` returned NULL, i.e. the
                             PE32 section could not be read out of the FFS file
  :1383  SecurityStatus      `gSecurity2->FileAuthentication` failed and not
                             with EFI_SECURITY_VIOLATION
  :1393  EFI_OUT_OF_RESOURCES the LOADED_IMAGE_PRIVATE_DATA allocation failed
  :711   (CoreLoadPeImage)   the AllocateAddress arm -- unreachable here, below
  :740   (CoreLoadPeImage)   the image-page allocation
  :795   EFI_OUT_OF_RESOURCES the RuntimeDriver FixupData pool allocation
  :782   PeCoffLoaderLoadImage's own status
  :805   PeCoffLoaderRelocateImage's own status

`:711` is unreachable and that is the first measured result, because it decides
whether anything *per-image* can be the mechanism at all.  At `:697` `Status` is
initialised to `EFI_OUT_OF_RESOURCES`; then

    if ((PcdImageLargeAddressLoad && ImageAddress >= 0x100000) ||
        RelocationsStripped)
    {
        Status = CoreAllocatePages (AllocateAddress, ..., &ImageAddress);   // :711
    }
    if (EFI_ERROR (Status) && !RelocationsStripped) {
        Status = CoreAllocatePages (AllocateAnyPages, ..., &ImageAddress);  // :722
    }
    if (EFI_ERROR (Status)) {
        return Status;                                                      // :740
    }

`PcdImageLargeAddressLoad` is TRUE (the MdeModulePkg DEC default; this tree does
not override it) and `PcdLoadModuleAtFixAddressEnable` is 0, so the first
condition reduces to `ImageAddress >= 0x100000 || RelocationsStripped`.  Both
halves are false for all 46: `ImageAddress` is the PE's own `ImageBase` and
every one of the 46 is `0x0`, and `RelocationsStripped` is set by
`BasePeCoff.c:659-667` from `EFI_IMAGE_FILE_RELOCS_STRIPPED` (Characteristics
bit 0) *alone* and nothing else -- the BaseReloc directory plays no part in it,
which is the third of that function's three cases, "relocatable but has no base
relocs to apply".  Characteristics is `0x2022` or `0x002e` on all 46, so bit 0
is clear on all 46 and `RelocationsStripped` is FALSE on all 46.

So every one of the 46 takes exactly one page allocation, the `AllocateAnyPages`
call at `:722`, of `EFI_SIZE_TO_PAGES (SizeOfImage)` pages of the memory type
that `Image.c:629-646` derives from the PE subsystem -- 11 (`EFI_IMAGE_SUBSYSTEM_
EFI_BOOT_SERVICE_DRIVER`) gives `EfiBootServicesCode`, 12 gives
`EfiRuntimeServicesCode`.  Both columns are printed below, because the firmware's
own `P2 BIN` comment argues from them.

WHERE A FAILURE BECOMES TERMINAL.  That one call goes
`CoreInternalAllocatePages` -> `FindFreePages` (`Page.c:1583`) ->
`CoreFindFreePagesI`, which searches `gMemoryMap` for `EfiConventionalMemory` of
that size.  If it finds none, `FindFreePages` calls `PromoteMemoryResource ()`
(`Page.c:1598`), which converts the largest promotable chunk of another type to
conventional, and re-searches; only when promotion itself returns FALSE does it
call `P2FreeWhy (MaxAddress, NoPages, NewType, Alignment)` and return 0
(`Page.c:1386` rung, `:1598` rung) -> `EFI_OUT_OF_RESOURCES` -> `:740` ->
`CoreLoadImage` error -> the `L` at `Dispatcher.c:1111`.  So an `L` from this
path is the strong statement: **no conventional run of N pages anywhere at or
below `MAX_ALLOC_ADDRESS`, and nothing left to promote.**  `P2 FWHY`'s
`free`/`big`/`c` is therefore a description of a map promotion has already
failed to enlarge, not merely of a small one.

AND WHY THE LETTER IS NOT THAT STATEMENT.  `CoreLoadPeImage`'s `Done:` at
`:940-948` frees `Image->ImageContext.ImageAddress` whenever `DstBufAlocated` is
set -- which it is, in this path -- so an image that *allocates its pages and
then fails downstream* at `:782`, `:795` or `:805` gives them straight back.  An
`L` therefore covers two opposite events: *refused* (nothing was taken) and
*loaded, then failed* (pages were taken and returned).  The letter cannot tell
them apart and the heap consequence is the reverse in each case.  That is what
`P2 WHY` is for and it is why this tool does not claim to give the status.

WHAT THAT BUYS, MEASURED.  Four of the 46 are byte-for-byte identical in every
field this tool reads -- `StatusCodeHandlerRuntimeDxe` (slot 3, letter `s`) and
`EmbeddedMonotonicCounter` (34), `RealTimeClock` (35), `CapsuleRuntimeDxe` (38),
all `L`: 327,680 B of `SizeOfImage`, `SectionAlignment 0x10000`, `ImageBase 0`,
Characteristics `0x2022`, DllCharacteristics `0x160`, subsystem 12, so each is
one request for 80 pages of `EfiRuntimeServicesCode`.  Four identical requests
partition 1-against-3 by *when*, not by *what*, which is what retires the
per-image search this tool was written to run: no field of the image separates
them, because the images do not differ.

The counter-example that keeps this honest, and where it is recorded rather than
resolved: `DiskIoDxe` (slot 21) *succeeds* on 49,152 B at subsystem 11 between
`ScmDxe` (20, `49,152`, `L`) and `PartitionDxe` (22, `53,248`, `L`) -- the same
memory type, the same size, the same one-page alignment, between a failure of
the same size and a failure of a larger one.  If `ScmDxe`'s `L` is `:740` it is
a refusal, and a refusal at 12 pages makes the next 12-page request impossible;
so either `ScmDxe`'s `L` is a load-then-fail whose pages came back, or the slot
map is wrong at this index.  Both are testable and neither is tested yet.

SLOT MAP.  Slot `k` is the `k`-th Apriori entry that *matched*, in Apriori array
order, which at this volume's 46-promotion stops is `tools/apriori-prefix.py`'s
`--seen` batch and not the identity map (`docs/08` steps 4.130, 4.142).
`P2MarkSeq` indexes `mP2AprioriGuid`, the promotion loop's own array, so the SEQ
really is in promotion order and not in execution order; the batch question is
only about which entries matched.  Two other tools in this tree decode the same
string with the identity join -- `tools/apriori-index.py` by construction and
`tools/pe-facts.py` as `apriori[k+1]` -- and `pe-facts.py` is what produced the
firmware's `P2 BIN` comment ("21 of the 27 are subsystem-11 ... against 6 that
are subsystem-12").  The cross-tab below is the cut map's answer to that same
question and it reproduces the comment's six names and its four names exactly,
so the two maps agree on the runtime set.  `--map identity` runs the census the
other way, and the monotone test below is run under both because that is the
one question the map choice could have decided: it does not.  Both maps show the
same shape of violation, so the SEQ is inconsistent with "every `L` is the page
call and nothing ever frees" whichever map is used, and the identity/cut
conflict is not what decides the 27.

TWO NUMBERS THIS TOOL CORRECTS, both of them other tools'.  The request is
`ceil (SizeOfImage / 4096)` rounded up to a multiple of 16 pages for the runtime
types (see `req_pages`), where `tools/pe-facts.py` computes `ceil ((SizeOfImage
+ SectionAlignment) / 4096)` -- a 64-KiB alignment modelled as 16 extra pages,
which is neither the same request nor a bound on it, and which over-states every
one of the 8 runtime members here.  And `Page.c`'s own `P2BRINGUP` comment
asserts that "RUNTIME_PAGE_ALLOCATION_GRANULARITY is 0x1000 here ... which is
the #else arm of ProcessorBind.h:163-170 and is not compiled": the tree defines
`__DEPRECATED_AARCH64_4K_RUNTIME_GRANULARITY` nowhere, and 0x1000 is the `#ifdef`
arm rather than the `#else` one, so the comment has the arms swapped and its
conclusion is wrong for the 8 runtime members.  `raw > big` -- the case the
comment says cannot happen and kept the `raw` field for -- is exactly the case
that can happen.

Rows printed per slot, all read from the PE32+ optional header of the file's
`EFI_SECTION_PE32`:

    chars   COFF Characteristics; bit 0x0001 is EFI_IMAGE_FILE_RELOCS_STRIPPED
    reloc   the base-relocation directory's VirtualSize; 0 with bit 0 clear is
            BasePeCoff.c's third case, "relocatable, no base relocs to apply"
    base    ImageBase, 0x0 on all 46
    sizimg  SizeOfImage
    req     the pages Image.c:722 asks for, after CoreInternalAllocatePages'
            per-type rounding (see req_pages)
    sa      SectionAlignment
    sub     PE subsystem, and the memory type Image.c:629-646 derives from it

Usage:
    tools/load-failure-census.py work/out/usb-host/Mu-gauguin-xhci-host-gzip.img
    tools/load-failure-census.py IMG --seen 48
    tools/load-failure-census.py IMG --map identity
    tools/load-failure-census.py IMG --all          # all 126 files, not the batch
"""
import argparse
import contextlib
import importlib.util
import io
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SEQ = "s" * 18 + "L" * 3 + "s" + "L" * 24

TYPE_DRIVER = 0x07
SECTION_PE32 = 0x10

# COFF Characteristics
IMAGE_FILE_RELOCS_STRIPPED = 0x0001

# PE subsystems that decide ImageCodeMemoryType (Image.c:629-646)
SUBSYSTEM_DRIVER = 11            # EFI_IMAGE_SUBSYSTEM_EFI_BOOT_SERVICE_DRIVER
SUBSYSTEM_RUNTIME = 12           # EFI_IMAGE_SUBSYSTEM_EFI_RUNTIME_DRIVER

MEMTYPE = {
    SUBSYSTEM_DRIVER: "EfiBootServicesCode",
    SUBSYSTEM_RUNTIME: "EfiRuntimeServicesCode",
}

SEEN_DEFAULT = 49


def load(mod, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", mod))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def pe32_facts(body):
    """PE32+ facts from an EFI_SECTION_PE32 body, or None if it is not one.

    AArch64 firmware is PE32+ (`Magic` 0x20b) and every offset below is from the
    optional header's own start, so the field order difference between PE32 and
    PE32+ - `ImageBase` is 8 bytes here and 4 there - is not papered over.
    """
    if body[:2] != b"MZ":
        return None
    e_lfanew, = struct.unpack_from("<I", body, 0x3C)
    if body[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return None
    coff = e_lfanew + 4
    machine, nsec = struct.unpack_from("<HH", body, coff)
    size_opt, chars = struct.unpack_from("<HH", body, coff + 16)
    opt = coff + 20
    magic, = struct.unpack_from("<H", body, opt)
    if magic != 0x20B:
        return {"machine": machine, "chars": chars, "magic": magic,
                "nsec": nsec, "plus": False}
    image_base, = struct.unpack_from("<Q", body, opt + 24)
    sec_align, file_align = struct.unpack_from("<II", body, opt + 32)
    size_image, = struct.unpack_from("<I", body, opt + 56)
    subsystem, = struct.unpack_from("<H", body, opt + 68)
    dllchars, = struct.unpack_from("<H", body, opt + 70)
    nrva, = struct.unpack_from("<I", body, opt + 108)
    dirs = opt + 112
    reloc_rva = reloc_size = 0
    if nrva > 5:                       # EFI_IMAGE_DIRECTORY_ENTRY_BASERELOC == 5
        reloc_rva, reloc_size = struct.unpack_from("<II", body, dirs + 5 * 8)
    return {
        "machine": machine,
        "chars": chars,
        "magic": magic,
        "plus": True,
        "nsec": nsec,
        "size_opt": size_opt,
        "image_base": image_base,
        "sec_align": sec_align,
        "file_align": file_align,
        "size_image": size_image,
        "subsystem": subsystem,
        "dllchars": dllchars,
        "nrva": nrva,
        "reloc_rva": reloc_rva,
        "reloc_size": reloc_size,
    }


def reloc_class(pe):
    """BasePeCoff.c:659-667's three cases, named the way that function names them.

    `RelocationsStripped` follows from Characteristics bit 0 and nothing else,
    so "stripped" here means the bit; an empty BaseReloc directory with the bit
    clear is the third case - relocatable, with no base relocs to apply - and it
    is not a difference the loader can see.
    """
    if pe["chars"] & IMAGE_FILE_RELOCS_STRIPPED:
        return "RELOCS_STRIPPED"
    if pe["reloc_size"] == 0:
        return "relocatable, no .reloc"
    return "relocatable"


def memtype(pe):
    return MEMTYPE.get(pe["subsystem"], f"subsystem {pe['subsystem']}")


def req_pages(pe):
    """The page count `Image.c:722` asks for, with CoreInternalAllocatePages' rounding.

    `CoreInternalAllocatePages` picks `Alignment` from the memory type -- DEFAULT
    (0x1000) for `EfiBootServicesCode`, RUNTIME for `EfiReservedMemoryType`,
    `EfiACPIMemoryNVS`, `EfiRuntimeServicesCode` and `EfiRuntimeServicesData` --
    then does `NumberOfPages += EFI_SIZE_TO_PAGES (Alignment) - 1` and
    `&= ~(EFI_SIZE_TO_PAGES (Alignment) - 1)`.  On AArch64
    `RUNTIME_PAGE_ALLOCATION_GRANULARITY` is 0x10000 unless
    `__DEPRECATED_AARCH64_4K_RUNTIME_GRANULARITY` is defined
    (`MdePkg/Include/AArch64/ProcessorBind.h:163-171`), and that macro is defined
    **nowhere in this tree** -- so a runtime image's request is its page count
    rounded up to a multiple of 16, searched for at a 64-KiB-aligned address.
    `tools/pe-facts.py` models the same request as `ceil ((SizeOfImage +
    SectionAlignment) / 4096)`, which is a different question and over-states
    every runtime member by up to 16 pages.
    """
    n = -(-pe["size_image"] // 0x1000)
    if pe["subsystem"] == SUBSYSTEM_RUNTIME:
        n = -(-n // 16) * 16
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--seen", type=int, default=SEEN_DEFAULT,
                    help=f"the DRIVER-scan length that fixes the batch "
                         f"(default {SEEN_DEFAULT}, docs/08 step 4.142)")
    ap.add_argument("--seq", default=SEQ,
                    help=f"the P2 SEQ letters (default the recorded string, "
                         f"{len(SEQ)} characters)")
    ap.add_argument("--all", action="store_true",
                    help="census every file in the volume, not just the batch")
    ap.add_argument("--map", choices=("cut", "identity"), default="cut",
                    help="how SEQ index k maps to an Apriori entry: `cut` is "
                         "the k-th entry that matched (default), `identity` is "
                         "entry k+1, which tools/apriori-index.py and "
                         "tools/pe-facts.py use")
    ap.add_argument("--hide-names", action="store_true",
                    help="do not print the per-slot names, only the header row")
    args = ap.parse_args()

    fvi = load("fv-inventory.py", "fv_inventory")
    apo = load("apriori-order.py", "apriori_order")

    files, _fv_len, offsets, inner = fvi.unpack(args.image)
    with contextlib.redirect_stdout(io.StringIO()):
        apriori, _nfiles = apo.apriori_array(fvi, args.image)

    rank, order = {}, []
    for i, (g, t, *_r) in enumerate(files):
        if t == TYPE_DRIVER:
            rank[g] = len(order)
            order.append((i, g))

    phys = {g: i for i, (g, *_r) in enumerate(files)}

    if args.all:
        slots = [(None, i) for i in range(len(files))]
    elif args.map == "identity":
        slots = [(a, phys.get(apriori[a]))
                 for a in range(min(len(apriori), len(args.seq)))]
    else:
        slots = [(a, phys[apriori[a]]) for a in
                 [i for i, g in enumerate(apriori) if g in rank and rank[g] < args.seen]]

    print(f"== {os.path.basename(args.image)}")
    print(f"   {len(files)} files, {len(order)} DRIVER(0x07), "
          f"Apriori {len(apriori)} entries, batch {len(slots)} slots "
          f"(seen={args.seen}, map={args.map})")
    if not args.all and len(slots) != len(args.seq):
        print(f"   the batch is {len(slots)} slots and the SEQ is "
              f"{len(args.seq)} characters; the letters below are read at the "
              f"slots that line up")
    print()

    hdr = (f"  {'slot':>4} {'ap':>3} {'phys':>5} {'let':>3}  "
           f"{'chars':>6} {'reloc':>5} {'base':>12} {'sizimg':>8} {'req':>4} "
           f"{'sa':>6} {'dllc':>5} {'sub':>3}  "
           f"{'memory type (Image.c:629-646)':<22} name")
    print(hdr)

    rows = []
    for k, (a, p) in enumerate(slots):
        let = args.seq[k] if (not args.all and k < len(args.seq)) else "."
        if p is None:
            print(f"  {k:>4} {a:>3} {'-':>5} {let:>3}  "
                  f"{'(not in this volume)':>52}")
            rows.append((k, a, None, let, None, "?", []))
            continue
        g, t, size, nm, st = files[p]
        body = inner[offsets[p] + 24:offsets[p] + size]
        secs = fvi.sections(body)
        pe = None
        for stype, sbody in secs:
            if stype == SECTION_PE32:
                pe = pe32_facts(sbody)
                break
        if pe is None:
            print(f"  {k if a is not None else '':>4} "
                  f"{a if a is not None else '':>3} {p:>5} {let:>3}  "
                  f"{'(no PE32 section)':>52}  {nm}")
            rows.append((k, a, p, let, None, nm, [s for s, _ in secs]))
            continue
        nmout = "" if args.hide_names else nm
        print(f"  {k if a is not None else '':>4} {a if a is not None else '':>3} "
              f"{p:>5} {let:>3}  "
              f"{pe['chars']:#06x} {pe['reloc_size']:>5} "
              f"{pe['image_base']:#12x} {pe['size_image']:>8,} "
              f"{req_pages(pe):>4} "
              f"{pe['sec_align']:#6x} {pe['dllchars']:#5x} {pe['subsystem']:>3}  "
              f"{memtype(pe):<22} {nmout}")
        rows.append((k, a, p, let, pe, nm, [s for s, _ in secs]))

    if args.all:
        return

    # ------------------------------------------------------------------
    print()
    print("=== the split, against the two properties that decide the one call")
    print("    (a) RelocationsStripped -- BasePeCoff.c:659-667, Characteristics bit 0 only")
    tab = {}
    for _k, _a, _p, let, pe, nm, _s in rows:
        key = (let, "no PE32" if pe is None else reloc_class(pe))
        tab.setdefault(key, []).append(nm)
    for key in sorted(tab):
        names = tab[key]
        print(f"  {key[0]!r:>4} {key[1]:>22}  {len(names):>3}"
              f"  {', '.join(names[:6])}{' …' if len(names) > 6 else ''}")

    print()
    print("    (b) subsystem -> ImageCodeMemoryType, the type the single call asks for")
    tab = {}
    for _k, _a, _p, let, pe, nm, _s in rows:
        key = (let, "no PE32" if pe is None else memtype(pe))
        tab.setdefault(key, []).append(nm)
    for key in sorted(tab):
        names = tab[key]
        print(f"  {key[0]!r:>4} {key[1]:>22}  {len(names):>3}"
              f"  {', '.join(names[:6])}{' …' if len(names) > 6 else ''}")
    s_rt = len([1 for _k, _a, _p, let, pe, _n, _s in rows
                if pe and let == "s" and pe["subsystem"] == SUBSYSTEM_RUNTIME])
    l_rt = len([1 for _k, _a, _p, let, pe, _n, _s in rows
                if pe and let == "L" and pe["subsystem"] == SUBSYSTEM_RUNTIME])
    print(f"    runtime-typed: {s_rt} of the `s` and {l_rt} of the `L`"
          f"   (the firmware's own `P2 BIN` comment says 6 of the 27)")

    # ------------------------------------------------------------------
    print()
    print("=== identical requests, split by letter")
    print("    the same SizeOfImage, SectionAlignment, Characteristics and "
          "subsystem: the loader cannot tell them apart")
    byreq = {}
    for _k, _a, _p, let, pe, nm, _s in rows:
        if pe is None:
            continue
        byreq.setdefault((pe["size_image"], pe["sec_align"], pe["chars"],
                          pe["dllchars"], pe["subsystem"]), []).append((nm, let))
    for key in sorted(byreq, key=lambda k: (-len(byreq[k]), k)):
        v = byreq[key]
        if len(v) < 2:
            continue
        letters = sorted({l for _n, l in v})
        tag = "  <-- SPLIT" if len(letters) > 1 else ""
        print(f"  {key[0]:>8,} B sa {key[1]:#x} chars {key[2]:#06x} "
              f"dllc {key[3]:#x} sub {key[4]}: {len(v)} request(s), "
              f"letters {''.join(letters)}{tag}")
        print(f"      {', '.join(f'{n}({l})' for n, l in v)}")

    # ------------------------------------------------------------------
    print()
    print("=== monotone-heap consistency: an `L` at slot k forbids a later `s`")
    print("    of >= its request, if every `L` is the page call at Image.c:740 and")
    print("    nothing ever frees -- which is what P2 RETRY's re-asking assumes")
    viol = []
    for k, _a, _p, let, pe, nm, _s in rows:
        if pe is None or let != "L":
            continue
        for k2, _a2, _p2, let2, pe2, nm2, _s2 in rows:
            if pe2 is None or let2 != "s" or k2 <= k:
                continue
            if req_pages(pe2) >= req_pages(pe):
                viol.append((k, nm, req_pages(pe), k2, nm2, req_pages(pe2)))
    print(f"  {len(viol)} violation(s) under the {args.map} map")
    for k, nm, n, k2, nm2, n2 in viol[:10]:
        print(f"    slot {k:>2} {nm} refuses {n:>2} pages, then slot {k2:>2} "
              f"{nm2} takes {n2:>2}")
    if viol:
        print("  so not every `L` can be the :740 refusal: at least one of the two")
        print("  in each pair above is the load-then-fail whose pages come back at")
        print("  Image.c:940-948, or the lookup at :1311, or the pool at :1393/:795")

    # ------------------------------------------------------------------
    print()
    print("=== every ImageBase more than one promoted driver claims")
    bybase = {}
    for _k, _a, _p, let, pe, nm, _s in rows:
        if pe is None:
            continue
        bybase.setdefault(pe["image_base"], []).append((nm, let))
    clash = {b: v for b, v in bybase.items() if len(v) > 1}
    if not clash:
        print("  none - every promoted driver asks for a distinct address")
    for b in sorted(clash):
        if b == 0:
            print(f"  {b:#012x}  all {len(clash[b])} of them - which is why the "
                  f"`AllocateAddress` arm at Image.c:711 is never entered, and "
                  f"why the clash is inert")
        else:
            print(f"  {b:#012x}  {len(clash[b])}: "
                  + ", ".join(f"{n}({l})" for n, l in clash[b]))

    # And the same question one level out, against the branch that is *not*
    # taken: AllocateAddress fails on overlap, not only on an exact-equal base.
    # Printed under its own heading because it is a statement about a branch no
    # batch member reaches.
    print()
    print("=== spans that would overlap, if Image.c:711 were reachable (it is not)")
    spans = []
    for _k, _a, _p, let, pe, nm, _s in rows:
        if pe is None:
            continue
        spans.append((pe["image_base"] & ~(pe["sec_align"] - 1),
                      pe["image_base"] + pe["size_image"] + pe["sec_align"], nm, let))
    spans.sort()
    found = False
    for i, (lo, hi, nm, let) in enumerate(spans):
        for lo2, hi2, nm2, let2 in spans[:i]:
            if lo < hi2 and lo2 < hi:
                if not found:
                    print("  all 46 sit at 0x0, so this is the whole batch "
                          "against itself - a property of a branch that is dead")
                print(f"  {nm}({let}) {lo:#x}..{hi:#x} overlaps "
                      f"{nm2}({let2}) {lo2:#x}..{hi2:#x}")
                found = True
                break
        if found:
            break
    if not found:
        print("  none - the 46 spans are disjoint")


if __name__ == "__main__":
    main()
