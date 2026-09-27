#!/usr/bin/env python3
"""Can gauguin's ACPI device names be taken from another Qualcomm DSDT?

`tools/acpi/gauguin.asl` began as exactly five things: UFS, the USB controller
and its two children, and the eight CPUs. P3 item 1 asks for I2C, SPI, GPIO,
buttons and thermal zones on top of that, and none of those nodes was in the
file. The device tree supplies every one of their *addressing* facts - register
windows, interrupt numbers, pin numbers - so the obvious next move is to lift
the nodes out of a platform that already has them and substitute the addresses.
(GPIO and the PMIC family have since gone in that way; this docstring describes
the question the tool was written to answer, and its answer is why they could.)

That move is only sound if the names travel. A Qualcomm DSDT block carries a
`_HID` like `QCOM1A0C`, an `_AEI` template, a `_REG` hook and a `_DSM` whose
UUID and return value are not documented anywhere in this tree. If `QCOM1A0C`
means "the TLMM block, wherever it is", it can be copied with the window
changed. If it means "this SoC's GPIO controller", copying it produces a device
node that no driver binds to - and Windows reports nothing when a device node
has an unknown `_HID`. It is simply absent from Device Manager. A silently
unbound node is worse than no node, because no node is visibly missing.

So this measures the question rather than arguing it. It disassembles every
reference DSDT in the Silicium-ACPI tree, joins each device to the block it
describes by the `Memory32Fixed` base address - the one key both the ACPI and
the device-tree worlds carry - and tabulates the `_HID` seen at each of
gauguin's own block addresses.

    python3 tools/acpi-hid-census.py                   # the address join
    python3 tools/acpi-hid-census.py --functions       # the name join
    python3 tools/acpi-hid-census.py --blocks          # gauguin's block list
    python3 tools/acpi-hid-census.py --drivers DIR     # which INFs bind these

`--drivers` wants a driver set, and there are two worth pointing it at: the
vendored board package (`~/work/woa-ref/inf-7280`) and the OS's own DriverStore,
which `tools/os-driver-store.sh` pulls out of an image. They answer different
halves of the question and the union is the coverage, not either one.

Measured 2026-09-25, **65** reference tables - the 66th file under this tree is
`Platforms/Xiaomi/gauguin/DSDT.aml`, which this build generates from
`tools/acpi/gauguin.asl`, and `table_files` excludes it: a corpus that counts the
table being written scores our own choices back to us, and the numerators below
were always measured against the 65. Three defects were found and fixed in
the drafts of this file, and all three made a negative answer look stronger
than the corpus supports:

    TLMM    0x0F100000   11 tables have a device here, 5 distinct _HIDs
                         QCOM1A0C x4   OnePlus/lemonade, Xiaomi/venus,
                                       Xiaomi/vili, Qualcomm/Lahaina/DSDT_MTP
                         QCOM0A0C x2   Samsung/a52sxq, Xiaomi/lisa
                         QCOM090C x2   Xiaomi/renoir, Qualcomm/Cedros/DSDT_IDP
                         QCOM0C0C x2   Qualcomm/Kailua/DSDT_MTP, .../DSDT_QRD
                         QCOM250C x1   Xiaomi/alioth
    SPMI    0x0C440000   no device *at this address*; 22 tables declare a
                         window at 0x0C400000 that contains it
    TSENS0  0x0C263000   no device at this address, no thermal node anywhere
    TSENS1  0x0C265000   same
    SE0..SE7 0x00[89]xxxxx  every window carries a different name per SoC

The 36 came from reading each platform's `DSDT.aml`, which is the trim. The
board variants are where Qualcomm writes the *complete* device list: Lahaina
ships `DSDT_MTP` (152 `Device` nodes) and `DSDT_Minimal` (8) and no plain
`DSDT.aml` at all, so the trim-only glob read none of Lahaina's device list in
any form - and Lahaina is the platform whose `GIO0` sits on gauguin's exact
TLMM window and length. Three of the four new TLMM references are variants.
Counted by name rather than by address, `GIO0` appears in 21 of the 65 tables
and `SPMI` in 22.

The second error is the join key, and the way it failed is worth copying down
because it is not the obvious one. **An address is a weak key, because a
reference's `_CRS` is often much coarser than the block it declares.** The
corpus's `SPMI` node claims `0x0C400000` for `0x02800000` - forty megabytes -
and gauguin's arbiter at `0x0C440000` sits inside that region. So an equality
test says "no device here" about a block that 22 of these 65 tables describe,
and it does so with the same confidence whether the corpus is empty or full.
Containment, not equality, is the test that matches how `_CRS` is written; what
carries across SoCs even better is the device *name* - every reference table
calls the GPIO controller `GIO0` and the arbiter `SPMI` regardless of where
their windows are. `--functions` joins on that.

Measured 2026-09-25, the name join:

    GIO0   02->17  05->0D  08->0D  09->0C  0A->0C  0C->0C  14->0D  1A->0C  25->0C  60->16
    SPMI   02->16  05->0C  08->0C  09->0B  0A->0B  0C->0B  14->0C  1A->0B  25->0B
    MMU0   02->12  05->09  08->09  09->09  0A->09  0C->09  14->09  1A->09  25->09
    QDSS   02->8C  05->5A  08->5A  09->56  0A->56  0C->56  14->5A  1A->56  25->56
    RFS0   02->35  05->17  08->17  09->15  0A->15  0C->15  14->17  1A->15  25->15

So a Qualcomm `_HID` is `QCOM` + two hex pairs, and the pairs are not
independent. The low pair is a block index that a whole *generation* of the
table generator shares: the families {09, 0A, 0C, 1A, 25} put the arbiter at 0B,
the GPIO controller at 0C, the MMU at 09, QDSS at 56 and RFS at 15, while the
older group {05, 08, 14} uses 0C, 0D, 09, 5A and 17 for the same five devices.
SDM850's 02 is a third group of its own - 16, 17, 12, 8C, 35 - which is why this
list used to be wrong: treating {02, 05, 08, 14} as one generation put the
arbiter at the wrong index for one of its four families. `MMU0` is the exception
that shows the axis is the generator and not the silicon: it stayed at 09 across
05 08 09 0A 0C 14 1A 25 and moved only for 02.

The high pair is a chipset-family token, and it does not follow the SoC's
marketing number: pipa and alioth both declare `SDM8250` and carry 05 and 25
respectively. Across the eleven tables where a GIO0 and an OEM table id can both
be read, the pairs are SDM850 02, SDM8150 05, SDM8250 05, SDM8250 25, SDM7180 08,
SDM7350 09, SDM7280 0A, SDM8550 0C, SDM7150 14, SDM8350 1A, SDM636 60.

**What that leaves is one byte, not a name.** The node shapes are all here -
`GIO0` with its `_CRS`, its interrupts and its pin tables; `SPMI`; `I2C<n>`,
`SPI<n>` and `UR<n>` for the GENI SE blocks, named by protocol; `BTNS` as a
standard `ACPI0011` Generic Buttons Device with Microsoft's `_DSD` UUID, whose
own `_HID` needs no vendor INF - though its `_CRS` names `\\_SB.PM01` as the
controller its `GpioInt` resources belong to, so it cannot be added on its own
either: a PMIC node has to exist for it, and a PMIC node carries this same
family byte. What cannot be read off the corpus is which family
SM7225 carries, and therefore whether its GPIO controller is `QCOM??0C` or
`QCOM??0D` - let alone what `??` is. But the search for it is finite and
mechanical: ten of gauguin's twelve blocks have a known index in each of the
measured generations, so a driver set either answers to `QCOM<byte><index>` for
all ten or it does not. No SM7225 table exists here: the only one that declares
the name is `Platforms/Xiaomi/gauguin/DSDT.aml`, and that is the file this tree
generated. Searching the corpus for `SM7225` returns our own work.

**And the reason is structural, not an accident of this corpus.** ACPI's `_HID`
is not a hardware fact; it is a string this port gets to choose, and the only
thing that constrains the choice is that a driver has to claim it. That the same
block appears under five different names in five reference DSDTs is evidence
about the choice being free, not about a name being lost.

So the direction of the work is unchanged but much narrower than "the tables
cannot be written": **adopt a driver set first, then name every block after it.**
The DSDT is written *to a driver*, not *to the SoC*, and an `.inf` lists exactly
the ids its driver answers to - so the driver set is not a later step, it is
where the missing two digits come from. A node described with an `_HID` no
available driver claims is hardware that cannot be driven, and it fails
silently: no error, no warning, just a device absent from Device Manager.

`--drivers DIR` takes a set and reports which of gauguin's blocks it covers,
which is the check to run the moment one is in hand, and it also answers the
question in the other direction - whose driver set this is, read off which names
it answers to. The same mechanism is what P5 means by "re-bind the WoA driver
INF" for the GPU.

Every `yes` row names the `.inf` that declares the id, which is not decoration.
A covered block and a *collision* look identical in a `yes`, and the difference
is only visible in the file: measured 2026-09-27, the SC7280/Kodiak set answers
`yes` to `SE1`, `SE2`, `SE3`, `SE5` and `SE7` on `QCOM0A10`, and `QCOM0A10` is
`qci2c7280.inf` - the **I2C** controller. Those five rows were coverage of the
I2C engines, which gauguin already has, being read as coverage of SPI engines it
does not. The set's `0F` is the same story in the other direction: `QCOM0A0F` is
in it, and the file that declares it is `qcslimbus7280.inf`.

Three ways this file fooled itself, recorded because all three agreed with the
conclusion being reached at the time. The `isinstance(True, int)` sentinel in
`devices_in`, which reported that *no* reference describes *any* of gauguin's
blocks; reading `*/DSDT.aml` alone, which reported that two of them have no
reference *at all*; and an equality test on the address, where containment is
what a `_CRS` actually means. Each one produced the same answer - nothing here
describes this - with perfect confidence and for a reason unconnected to the
corpus. A negative result is easiest to believe when it matches what you were
about to say, and the third one is the hardest to notice, because a miss read as
an absence looks exactly like a miss.
"""
import argparse
import glob
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TREE = os.path.join(
    REPO, "work/uefi/Mu-Silicium/Silicium-ACPI")
DEFAULT_CACHE = "/tmp/acpi-hid-census"

# gauguin's blocks, every address from work/out/gauguin.dts (the generated tree
# from the tracked dts) or, where marked, the merged tree Step 4.54 read - the
# overlay that carries the second SPI controller is one of the ones our
# generated tree replaced with empty sinks, so that node is not in it.
#
# (label, base, length, node in the device tree, what it is for)
BLOCKS = [
    ("TLMM",   0x0F100000, 0x300000, "pinctrl@f100000",
     "GPIO controller: the touchscreen IRQ, the fingerprint IRQ and the volume "
     "keys are all GPIO interrupts, so nothing interrupts without it"),
    ("SPMI",   0x0C440000, 0x000000, "spmi@c440000",
     "PMIC arbiter: the power key and both volume keys are PMIC GPIOs"),
    ("TSENS0", 0x0C263000, 0x0001FF, "thermal-sensor@c263000",
     "temperature sensing, low and critical trip interrupts"),
    ("TSENS1", 0x0C265000, 0x0001FF, "thermal-sensor@c265000",
     "the second sensing block, four more zones"),
    ("SE0",    0x00880000, 0x004000, "spi@880000 (merged tree, Step 4.54)",
     "the touchscreen bus - touch_spi@0 with a Novatek NVT part at 10 MHz"),
    ("SE0u",   0x00884000, 0x004000, "serial@884000", "the Bluetooth UART"),
    ("SE1",    0x00888000, 0x004000, "i2c@888000", "disabled in the tree"),
    ("SE2",    0x00980000, 0x004000, "i2c@980000", "disabled in the tree"),
    ("SE3",    0x00984000, 0x004000, "i2c@984000",
     "the two cs35l41 audio amplifiers (overlay 13)"),
    ("SE5",    0x00988000, 0x004000, "i2c@988000", "the nq NFC controller"),
    ("SE6",    0x0098C000, 0x004000, "serial@98c000 -> spi@98c000 (overlay 13)",
     "the IR blaster"),
    ("SE7",    0x00990000, 0x004000, "i2c@990000",
     "fsa4480, aw8624 haptics, bq25970 charger, pm8008"),
]

# The census joins on the base address alone. A device whose window is a
# sub-block of one of these (the PMIC arbiter's five windows, the second TSENS
# window at 0xC222000) would not match, and does not need to: it is the same
# ACPI device.
MEMFIX_CALL = re.compile(r"Memory32Fixed \(\s*ReadWrite\s*,\s*(.*)$")
HEX = re.compile(r"0x[0-9A-Fa-f]+")
DEVICE = re.compile(r"^( *)Device \(([A-Z0-9_]{4})\)")
NAME_HID = re.compile(r'Name \(_HID, "(?:EisaId \(")?([^"]+)"')
NAME_CID = re.compile(r'Name \(_CID, "(?:EisaId \(")?([^"]+)"')
# An .inf names the hardware it binds as ACPI\<HID>, with the HID either four
# to eight alphanumerics (QCOM1A0C) or a PNP id (PNP0C0E). Both are matched:
# the question is coverage, and a block covered by a PNP device is covered.
#
# This pattern alone is not a claim - it is the *string*, wherever it is
# written, and an .inf writes it in five places of which two are a driver
# answering to the id. `inf_claim_shapes` sorts the positions apart; nothing
# should use this regex to decide that a set claims an id.
INF_ACPI = re.compile(r"ACPI\\\s*([A-Za-z0-9_]{3,16})", re.I)
# A third net, and it does not answer `INF_ACPI`'s question. An .inf names ids it
# does not bind: `URS\QCOM0A8B&HOST` is a *child* of the ACPI node QCOM0A8B,
# created by whoever binds the node, and a quoted `_HID` default written by an
# extension ("_HID",%REG_SZ%,"QCOM0A0F") is an id going into the registry. Both
# are the set naming an id; neither is the set attaching a driver to it. So they
# are kept in their own column and printed beside `NOT CLAIMED` rather than
# folded into it - widening `INF_ACPI` would silently redefine "claimed" in
# every count above.
#
# The id in the second group is not `QCOM`-shaped on purpose. Windows' own
# driver packages name children of PNP ids too: `ufxsynopsys.inf` binds
# `URS\PNP0CA1&FUNCTION` and `ufxchipidea.inf` binds `URS\PNP0C90&FUNCTION`, and
# `PNP0CA1` is the `_CID` this port writes on URS0. A net that only sees four
# hex digits after `QCOM` reads the OS's answer for that node as silence.
#
# It runs over the whole file text and so returns everything of that shape, not
# only device ids. Measured against `~/work/woa-ref/inf-7280`, 2026-09-27: 631
# ids under 210 prefixes, of which twelve prefixes are device buses (`ADSP` 70,
# `CDSP` 52, `USBFN` 10, `AUCD` 8, `ADCM` 6, and `URS`, `UEFI`, `VIDEO`, `IPAB`,
# `WPSS`, `QCA_SHB`, `SWC`) and the rest are registry roots, keys and value
# names, 20-hex-char `Mappings\TFTP\Default\<hash>` fragments, and hex literals
# (`DEFAULT` 468, `X04` 47, `MCFG` 28, `AUTOLOGGER` 20, plus `PARAMETERS`,
# `MAPPINGS`, `PROFILES`, `SOFTWARE`, `CONTROL`, `CURRENTCONTROLSET`,
# `DRIVERSTORE`, country and carrier names, `0X00`-`0X37`). Two side effects of
# the shape, both visible in that tally: the `&`-split below folds the five
# `VEN_QCOM&DEV_*` forms (`&DEV_0A22`, `&DEV_0A28`, `&DEV_0A29`, `&DEV_0AC1`,
# `&DEV_QCListenSoundModel`) into the single id `VEN_QCOM`, and
# `UEFI\RES_{guid}` is filed as the id `RES_`.
#
# None of that reaches a verdict this tree depends on: of the 42 ids in
# `tools/acpi/gauguin.asl`, exactly one carries a bus note - `QCOM0A8B`, as
# `URS\QCOM0A8B&FUNCTION` and `URS\QCOM0A8B&HOST`, both real. But an id whose
# spelling collides with a registry key would print under `NOT CLAIMED` as
# "named by this set on another bus" when the set had named nothing, which is
# the same failure direction Step 4.151 removed from the claim column. Working
# out what separates "names a device id" from "contains a path of that shape"
# is left open rather than guessed at: every candidate rule (a bus whitelist, a
# per-section scan, a path-shape test) can go stale without saying so, which is
# what Step 4.149 was about.
INF_BUS = re.compile(r"([A-Za-z][A-Za-z0-9_]{1,11})\\\s*"
                     r"([A-Za-z0-9_]{3,20}(?:&[A-Za-z0-9_]+)?)")


def read_win_text(path):
    """A Windows text file as `str`, whatever it was encoded in.

    Measured the hard way: every `.inf` in a Windows Update driver package is
    UTF-16 with a BOM, and reading one as UTF-8 does not fail - it succeeds and
    returns text whose every other byte is NUL, so `ACPI\\QCOM0A0C` arrives as
    `A\\x00C\\x00P\\x00I\\x00...` and *no* regex matches it. That produced the
    worst kind of wrong answer: `--drivers` reported 0 ids for a set that lists
    157 of them, and then concluded the set was "for some other SoC". A reader
    that silently sees nothing is not a reader, so the BOM is checked first and
    the NULs are used as a second signal for the files that lack one.
    """
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if b"\x00" in raw[:4096]:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def strip_inf_comments(text):
    """An `.inf` with its `;` comments removed, quotes respected.

    An `.inf` comments with `;` to end of line, and the comments in a driver
    package are not decoration: they are the disabled half. Measured
    2026-09-27 against `~/work/woa-ref/inf-7280`, three of its 158 `ACPI\\` ids
    are claimed *only* by text a compiler never reads -

        QCOM0200   qciommu.inf, qciommuext7280.inf, qcsmmu7280.inf,
                   qcsyscache7280.inf, all four as the installer note
                   ";    Using Devcon: Type "devcon update IOMMU.inf
                   ACPI\\QCOM0200" to install"
        QCOM02FA   qcipcc7280.inf's ";%DeviceDesc%=IPCC_Inst,,ACPI\\QCOM02FA",
                   a models line commented out
        QCOM0190   qcslimbus7280.inf, the same installer note

    so `--bind` reported them claimed by files that bind nothing, and the set's
    coverage was three ids larger than the set is. The failure direction is the
    dangerous one and it is the same one `inf_claim_shapes` describes below: the
    answer says a driver answers to the id when no driver does, so a node written
    on the strength of it is absent from Device Manager with nothing to say why.

    None of gauguin's 34 ids is affected - the whole set of them is 3 - and the
    two OS DriverStores have no comment-only claim at all, which is why this was
    found by asking the question rather than by a decision going wrong. Stripped
    in `load_driver_set` so all three nets read one text; the alternative, an
    exclusion list per net, is how the same text gets read two ways.
    """
    out = []
    for line in text.splitlines():
        quoted, keep = False, []
        for ch in line:
            if ch == '"':
                quoted = not quoted
            elif ch == ";" and not quoted:
                break
            keep.append(ch)
        out.append("".join(keep))
    return "\n".join(out)


def inf_claim_shapes(text):
    """(hardware, compatible, exclude-only, key-only) - where an `.inf` writes ids.

    `INF_ACPI` answers "does this set contain the string `ACPI\\<HID>`", which is
    not the same question as "does a driver in this set bind it", and the gap
    between the two is measured rather than hypothetical. Counting the three
    positions apart, 2026-09-27:

        ~/work/woa-ref/inf-7280   155 ids   155 hardware, 0 elsewhere
        boot.wim index 1           85 ids    76 hardware, 1 compatible,
                                            3 ExcludeFromSelect, 5 key names
        install.wim index 1       116 ids   105 hardware, 3 compatible,
                                            3 ExcludeFromSelect, 5 key names

    A models line is `%description% = InstallSection, ACPI\\HARDWARE[,  ACPI\\COMPATIBLE...]`.
    The hardware id is the field that follows the install section; anything after
    it is a *compatible* id, the fallback a node is matched on when nothing claims
    its hardware id - the position `URS0`'s `_CID` is bound through and the only
    reason `PNP0CA1` reads as claimed in the full OS. `[ControlFlags]`'s
    `ExcludeFromSelect` names an id without binding it, and of the 3 in each of
    these images, `NVDA0112`, `NVDA0212` and `TXNW0073`, none has a models line
    in the set at all - it is listed so the id does not appear in a
    device-selection list.

    The fifth shape is the one that made this a parser rather than a tally. A
    `[Strings]` entry is `ACPI\\Foo.DeviceDesc = "..."`, and its *key name* holds
    an `ACPI\\` token that `INF_ACPI` reads as an id the set claims. Three of the
    five are keys for devices whose real ids are words:

        %ACPI\\DockDevice_Desc%   = NO_DRV,    ACPI\\DockDevice
        %ACPI\\FixedButton_Desc%  = NO_DRV,    ACPI\\FixedButton
        %ACPI\\ThermalZone_Desc%  = NO_DRV,    ACPI\\ThermalZone

    so `INF_ACPI` reports `DOCKDEVICE_DESC` as an id. The other two are worse,
    because the key is named after a *different* id that the file does not bind:

        %ACPI\\INT33BA.DeviceDesc%  = SDHostIntelEMMC, ACPI\\VEN_INT&DEV_33BA&REV_0001
        %ACPI\\ARMH_PL180.DeviceDesc%= SDHostARMHPL180, ACPI\\ARMH0180

    `ARMH_PL180` is the ARM PrimeCell PL180, `ARMH0180` the id the models line
    actually binds; a reader checking a name against the set was told `ARMH_PL180`
    was in use by a file that binds `ARMH0180`. That is the same species as the
    comment-only claims above and it fails in the same direction.

    Returned as four sets, and the caller is expected to treat `key-only` as *not*
    a claim: that bucket is what an id looks like when nothing claims it.
    """
    hw, compat, exclude, keyonly = set(), set(), set(), set()
    for line in text.splitlines():
        if "=" not in line or "ACPI\\" not in line.upper():
            continue
        left, right = line.split("=", 1)
        head = left.strip().upper()
        if head.startswith("EXCLUDEFROMSELECT"):
            exclude |= {m.group(1).upper() for m in INF_ACPI.finditer(right)}
            continue
        if "%" not in left:
            # A `[Strings]` key, referred to elsewhere as `%<key>%`. The id in
            # the key's name is decoration unless a models line binds the same
            # id, which is exactly what the three-way split above measured.
            if head.startswith("ACPI\\"):
                keyonly |= {m.group(1).upper() for m in INF_ACPI.finditer(left)}
            continue
        fields = right.split(",")
        if len(fields) < 2:
            continue
        # `%desc% = ACPI\X` with no install section is legal and rare; read it
        # rather than dropped, so the id is not lost to a section-less line.
        body = fields if "ACPI\\" in fields[0].upper() else fields[1:]
        for i, field in enumerate(body):
            for m in INF_ACPI.finditer(field):
                (hw if i == 0 else compat).add(m.group(1).upper())
    return hw, compat, exclude, keyonly


def load_driver_set(directory):
    """(id -> [inf paths], encoding tally, file count, notes).

    One reader, used by both `--drivers` and `--bind`, because the encoding
    question above is exactly the kind that gets answered once and then
    answered differently in the second copy.

    `notes` is the second reader: how the set *names* an id besides claiming it,
    as `{"bus": {id: {form: file}}, "text": {file: uppercased text},
    "shape": {id: {shape}}, "keyonly": {id: {file}}}`. It is what
    separates two absences that the `ACPI\\` column reports identically -
    `QCOM0A8B`, which two INFs in this set name as the parent of the children
    they bind, and `QCOM24A5`, which this set does not name at all. Kept in one
    pass rather than a second walk of the tree so the two readers cannot see
    different file sets, and the text is kept as text - with its comments
    stripped, but not reduced to a token regex - because the question "does
    this set ever write this string" has to be answerable for ids of any shape.

    An id reaches the `hids` bucket from a models line or an `ExcludeFromSelect`
    and from nowhere else, because those are the two places a driver says which
    ids it answers to. A `[Strings]` key name wearing an `ACPI\\` token is not
    one of them: see `inf_claim_shapes` for the five ids in a Windows image that
    were counted as claims on that basis alone.
    """
    inffiles = []
    for root, _dirs, names in os.walk(directory):
        inffiles += [os.path.join(root, n)
                     for n in names if n.lower().endswith(".inf")]
    hids, encodings = {}, {}
    notes = {"bus": {}, "text": {}, "shape": {}, "keyonly": {}}
    for inf in inffiles:
        try:
            raw = open(inf, "rb").read()
        except OSError:
            continue
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            enc = "utf-16 (BOM)"
        elif b"\x00" in raw[:4096]:
            enc = "utf-16 (no BOM)"
        else:
            enc = "utf-8"
        encodings[enc] = encodings.get(enc, 0) + 1
        # Stripped once, here, rather than in each of the three walks below:
        # an `.inf`'s comments are the disabled half of it, and a claim read
        # off a commented-out models line is a name reported in use that
        # nothing binds. See `strip_inf_comments` for the three ids that
        # made this a correction rather than a precaution.
        text = strip_inf_comments(read_win_text(inf))
        rel = os.path.relpath(inf, directory)
        notes["text"][rel] = text.upper()
        hw, compat, exclude, keyonly = inf_claim_shapes(text)
        for hid in hw | compat | exclude:
            # Once per *file*, not once per mention: an `.inf` names the id it
            # binds in `[Manufacturer]`, in `[ControlFlags]`'s
            # `ExcludeFromSelect`, again under the manufacturer's section and
            # again as a `%ACPI\...DeviceDesc%` string key. `storufs.inf` does
            # exactly that with `ACPI\QCOM24A5`, and the report read
            # "claimed by <same file> x3 +1", which is one file claiming one id
            # printed as a crowd.
            #
            # Which position named it is kept too, and the strongest wins when
            # one file writes the id twice: a models line is a bind and an
            # `ExcludeFromSelect` entry is not, and only the first is a driver
            # attaching to the node.
            if hid in hw:
                shape = "hardware"
            elif hid in compat:
                shape = "compatible"
            else:
                shape = "exclude"
            notes["shape"].setdefault(hid, set()).add(shape)
            bucket = hids.setdefault(hid, [])
            if rel not in bucket:
                bucket.append(rel)
        for hid in keyonly - hw - compat - exclude:
            notes["keyonly"].setdefault(hid, set()).add(rel)
        for m in INF_BUS.finditer(text):
            if m.group(1).upper() == "ACPI":
                continue
            # Keyed by the id, valued by the whole form: `QCOM0A8B&HOST` and
            # `QCOM0A8B&FUNCTION` are one id in two roles in two files, and
            # collapsing them to the id loses the half that says which.
            hid = m.group(2).split("&")[0].upper()
            form = re.sub(r"\s+", "", m.group(0))
            notes["bus"].setdefault(hid, {})[form] = rel
    return hids, encodings, inffiles, notes


# An ASL `_HID` is a plain string in every table this repo has, but `EisaId (...)`
# is the other spelling iasl accepts, so both are read here rather than only the
# one this file happens to use. `_CID` is read too: a node is bound by either.
ASL_HID = re.compile(r'Name \(_([HC]ID), (?:"(?:EisaId \(")?|EisaId \(")'
                     r'([^"]+)"')
ASL_DEVICE = re.compile(r"^\s*(?:Device|ThermalZone) \(([A-Z0-9_]{1,4})\)")
# `ThermalZone` is in that alternation and not left out, because it is a
# different AML opcode rather than a synonym for `Device` (Step 4.73). Left
# out, every zone's `_HID` was attributed to the last `Device` textually above
# it, which until Step 4.74 was harmless-looking and after it was `IPCC` - a
# label naming a node the id does not belong to. The length is 1-4 and not
# exactly 4 for the same reason: `TZ0`-`TZ9` are three characters, so a
# four-character name would have fixed the ten zones above nine and left the
# first ten still labelled `IPCC`.


def strip_asl_comments(lines):
    """Blank out `/* ... */` and `// ...`, keeping every line's number.

    The scan below is line-based, and a declaration is a `Name (...)`, so a
    comment that quotes one reads as one. This file's own header does exactly
    that - it lists the ids it corrected, in prose - and the first run of the
    sweep after that prose was added reported `QCOM0A8B` twice, once from the
    node and once from the sentence describing it.

    That is cosmetic. What is not is the shape behind it: a commented-out
    `_HID` would be cleared rather than reported, and this tool's whole job is
    to clear names before a commit. Stripping first makes the count mean
    declarations, which is what the reader assumes it already means. Each
    input line still yields exactly one output line, so the line numbers the
    report prints stay right.
    """
    out, in_block = [], False
    for line in lines:
        buf = []
        i = 0
        while i < len(line):
            two = line[i:i + 2]
            if in_block:
                if two == "*/":
                    in_block = False
                    i += 2
                else:
                    i += 1
            elif two == "/*":
                in_block = True
                i += 2
            elif two == "//":
                break
            else:
                buf.append(line[i])
                i += 1
        out.append("".join(buf))
    return out


def short(path):
    """A path relative to the repo when it is inside it, absolute when it is not.

    `--drivers` and `--asl` both take paths outside the repo by design - the
    driver set lives in ~/work - and `relpath` on those returns `../../../..`,
    which reads as a mistake rather than as a location.
    """
    rel = os.path.relpath(path, REPO)
    return path if rel.startswith("..") else rel


def print_set_header(inffiles, hids, encodings, notes):
    """One driver set's size, its encodings, and where its ids were written.

    The second line exists because "distinct `ACPI\\` ids" was counting three
    different things and the count changed meaning without changing value. Of
    boot.wim's 85 ids, 76 are the hardware id of a models line, 1 (`WACF006`)
    is a compatible id, 3 (`NVDA0112`, `NVDA0212`, `TXNW0073`) are named only
    by `ExcludeFromSelect`, and 5 are `[Strings]` key names that name no
    device at all. Read as one number, the count answers a question nobody
    asked: whether the *string* is present, rather than whether a driver
    answers to the id.
    """
    print(f"{len(inffiles)} .inf files, {len(hids)} distinct `ACPI\\` ids claimed")
    print(f"  encodings: {', '.join(f'{v} {k}' for k, v in sorted(encodings.items()))}")
    hw = sum(1 for s in notes["shape"].values() if "hardware" in s)
    compat = sum(1 for s in notes["shape"].values()
                 if "hardware" not in s and "compatible" in s)
    print(f"  positions: {hw} hardware, {compat} compatible-only, "
          f"{len(hids) - hw - compat} ExcludeFromSelect-only")
    keyonly = sorted(notes["keyonly"])
    if keyonly:
        shown = ", ".join(keyonly[:6]) + (f" +{len(keyonly) - 6}" if len(keyonly) > 6 else "")
        print(f"  and {len(keyonly)} other name(s) spelled `ACPI\\...` that are "
              f"*not* claimed - string-key names, which bind nothing: {shown}")
    print()


def shape_note(hid, notes):
    """How the set named this id, when that is not the plain case.

    `None` when a models line binds it in the hardware position, which needs no
    remark. The two remarks below are the readings a bare "claimed by <file>"
    hides: `PNP0CA1` is bound only through the compatible position, and a
    reader who took that for a hardware-id match would expect the node's `_HID`
    to be `PNP0CA1` rather than its `_CID`.
    """
    shapes = notes["shape"].get(hid, set())
    if "hardware" in shapes:
        return None
    if "compatible" in shapes:
        return ("compatible id - bound in the position a node is matched on "
                "when nothing claims its hardware id, not as a hardware id")
    if shapes:
        return ("named only by `[ControlFlags] ExcludeFromSelect` - listed so "
                "the id stays out of a device-selection list, and no models "
                "line in this set binds it")
    return None


def cmd_bind(args):
    """Which driver claims a name - the check that the name is not a guess.

    The census decomposes the id into a block index the corpus supplies and a
    family byte a driver set supplies. This is the last step of that: it reads an
    id back out of the ASL that is about to be built and asks the driver set
    whether anything binds to it.

    The failure it exists for is the quiet one. A node whose `_HID` no driver
    claims does not error, warn or fall back at runtime - it is simply absent
    from Device Manager, with the hardware behind it working and unused. So
    "the name I chose" and "the name a driver claims" have to be made the same
    act, or the mistake is only found on the far side of a Windows install.

    One set is not the system, and which set is being read changes the answer.
    A vendor package answers for the blocks *its* board has; the OS answers for
    the ones Microsoft ships a driver for. Measured 2026-09-27: of the 34 ids
    written in `gauguin.asl`, `~/work/woa-ref/inf-7280` claims 32 and leaves
    `QCOM0A8B`/`QCOM24A5`, while a Windows 25H2 x64 `boot.wim`'s DriverStore
    (339 INFs, 80 ids, via `tools/os-driver-store.sh`) claims exactly one of
    them - `QCOM24A5`, in `storufs.inf` - and 33 the vendor set does. Neither
    number is the coverage; the union is, and running one and reporting it as
    the other is the same defect as the encoding bug above.

    The counts in the header are claims and not string occurrences: `--bind`
    prints the position each id was found in, because a compatible id is bound
    without being a hardware id and an `ExcludeFromSelect` entry binds nothing.
    """
    hids, encodings, inffiles, notes = load_driver_set(args.drivers)
    print_set_header(inffiles, hids, encodings, notes)

    if args.asl:
        return bind_asl(args, hids, notes)
    return bind_lookup(args, hids, notes)


def mention_lines(hid, notes):
    """How this set names an id it does not claim - or that it never names.

    The distinction this exists for is the one a single `NOT CLAIMED` line
    erases. `ACPI\\<HID>` is how an `.inf` *binds*; a set can also name an id
    without binding it, and the two absences look identical in the `ACPI\\`
    column. Measured against `~/work/woa-ref/inf-7280` on 2026-09-27:
    `QCOM0A8B` is in two of its `.inf` files, as `URS\\QCOM0A8B&HOST`
    (`QcXhciFilter7280.inf`) and `URS\\QCOM0A8B&FUNCTION`
    (`QcUsbFnSsFilter7280.inf`), and `QCOM24A5` is in none of them in any form.
    The first is an id the set builds on - `URS\\` children are named after the
    parent's `_HID`, so a build with the wrong `_HID` on `URS0` would have no
    filter binding at all - and the second is an id the set has never heard of.
    Both are true statements about *this set*; they are not the same statement.

    Three readings, strongest first, and they are read separately rather than
    ranked into one:
      * named on another bus   - the id is the set's; only the attach is missing.
      * named only as a value  - the set writes the string but binds no device
        of that id (`HKR,...,"_HID",...,"QCOM0A0F"` and `%...DeviceDesc%` keys
        are the shapes; both are text an extension writes into the registry, so
        they say the set knows the name and not that anything answers to it).
      * named nowhere          - no bus prefix, no value, no token at all.

    The first line's strength is the form it prints, not the fact that it
    printed. `URS\\QCOM0A8B&HOST` is the parent token of an id a models line in
    that same file binds, so the set is building on the name; a match inside a
    registry path says only that the spelling occurs. `INF_BUS` returns both and
    the line shows which, so read the form - the column is not a rank.
    """
    bus = notes["bus"].get(hid)
    if bus:
        forms = ", ".join(f"`{f}` ({p})" for f, p in sorted(bus.items()))
        return [f"but named by this set on another bus: {forms}"]
    key = notes["keyonly"].get(hid)
    if key:
        return [f"written in {len(key)} of this set's .inf files, as the name of "
                f"a `[Strings]` key rather than as a device id - a key name binds "
                f"nothing: {', '.join(sorted(key)[:3])}"
                + (f" +{len(key) - 3}" if len(key) > 3 else "")]
    seen = sorted(p for p, text in notes["text"].items() if hid in text)
    if seen:
        return [f"named in {len(seen)} of this set's .inf files, but never after "
                f"a bus prefix (a value it writes, not a device it binds): "
                f"{', '.join(seen[:3])}" + (f" +{len(seen) - 3}" if len(seen) > 3 else "")]
    return ["named nowhere in this set: no bus prefix, no quoted _HID default, "
            "no token at all"]


def bind_asl(args, hids, notes):
    """Every `_HID` in a file, against the set. Returns 1 if any QCOM one misses."""
    try:
        raw = open(args.asl, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print(f"cannot read {args.asl}: {e}")
        return 1
    lines = strip_asl_comments(raw.splitlines())
    device = "?"
    found = []            # (line number, device, hid)
    for n, line in enumerate(lines, 1):
        m = ASL_DEVICE.match(line)
        if m:
            device = m.group(1)
        for m in ASL_HID.finditer(line):
            found.append((n, device, m.group(2).upper()))

    used = sorted({h for _n, _d, h in found})
    print(f"  {len(found)} _HID/_CID declarations in {short(args.asl)}, "
          f"{len(used)} distinct\n")
    unclaimed, standard = [], []
    for hid in used:
        where = sorted({f"{d} (line {n})" for n, d, h in found if h == hid})
        who = hids.get(hid, [])
        if ACPI_ID.match(hid):
            # ACPI0007 is a processor, ACPI0011 a generic button device: the OS
            # ships the driver and no vendor .inf is involved. Not a gap.
            standard.append(hid)
            verdict = "standard id - the OS supplies the driver"
        elif PNP_ID.match(hid):
            # A PNP id is a vendor CIM, not a Microsoft one: PNP0CA1, PNP0CA2
            # and PNP0CA3 are Qualcomm's own for the URS, the SPMI arbiter and
            # the PMIC. Calling these "the OS supplies the driver" was this
            # tool describing its own rule - "not QCOM, so not looked up" - as a
            # fact about the hardware. They are covered by whatever claims the
            # `_HID` beside them, and a *vendor package* lists QCOM ids, so
            # there is usually nothing here to check them against.
            #
            # "Usually" was doing real work in that sentence and this branch was
            # reading it as "always", because it ran before the `who` lookup
            # below. Measured 2026-09-27: against the full OS's DriverStore,
            # `PNP0CA1` printed as "not bound as an ACPI device by this set"
            # while `urssynopsys.inf` in that very set binds
            # `%UrsSynopsys.DeviceDesc% = UrsSynopsys.Install, ACPI\QCOM24B6,
            # ACPI\PNP0CA1` - the Synopsys USB 3.0 dual-role controller, on the
            # compatible id this port writes as `URS0`'s `_CID`. A set can also
            # name the id on another bus (`URS\PNP0CA1&FUNCTION`, the function
            # child that parent enumerates). So the order is now: claimed
            # first, then the bus note, and the "nothing to check it against"
            # sentence only where neither holds - which is what it always said
            # it meant.
            named = notes["bus"].get(hid)
            standard.append(hid)
            if who:
                verdict = f"PNP id - claimed by {', '.join(who[:3])}" + \
                          (f" +{len(who) - 3}" if len(who) > 3 else "")
            elif named:
                forms = ", ".join(f"`{f}` ({p})" for f, p in sorted(named.items()))
                verdict = (f"PNP id - a vendor CIM; not bound as an ACPI device "
                           f"by this set, but named on another bus: {forms}")
            else:
                verdict = ("PNP id - a vendor CIM, not looked up in this set; the "
                           "_HID beside it is what binds")
        elif who:
            verdict = f"claimed by {', '.join(who[:3])}" + \
                      (f" +{len(who) - 3}" if len(who) > 3 else "")
        else:
            unclaimed.append(hid)
            verdict = "NOT CLAIMED by any .inf in this set"
        print(f"    {hid:<12} {len(where)}x  {verdict}")
        print(f"                 {', '.join(sorted(where)[:4])}")
        note = shape_note(hid, notes)
        if note:
            print(f"                 {note}")
        if hid in unclaimed:
            for line in mention_lines(hid, notes):
                print(f"                 {line}")
    print()

    if unclaimed:
        print(f"  {len(unclaimed)} QCOM id(s) no driver in this set claims: "
              f"{' '.join(unclaimed)}")
        print("  Read that as a fact about *this* set rather than a verdict on the")
        print("  name: a set is one board's driver package, so an id gauguin owns")
        print("  and the set's own board does not is absent without being wrong.")
        print("  What it means is that no driver in this set will bind, so on a")
        print("  Windows built from it those nodes are absent from Device Manager.")
        print("  Fine while the block is not needed; a silent failure the moment")
        print("  it is.")
        print("  Where a line under the id says the set names it on another bus, read")
        print("  the form before the line. Where it is the parent token of an id a")
        print("  models line in the same file binds, the set is building on the name")
        print("  and only the attach is missing. Where that line is the name of a")
        print("  `[Strings]` key, nothing binds it and the name is free to take.")
        print("  Where it says nowhere, the set does not carry a driver for the block")
        print("  at all. The three are worth reading separately before acting on any")
        print("  of them.")
        print("  (This used to name UFS and the UART as the pair. Step 4.70 wrote a")
        print("  UART node and the set claims its id, so the examples are the list")
        print("  above and are no longer repeated here - a hardcoded example goes")
        print("  stale the first time the thing it names is fixed.)")
        return 1
    print("  Every QCOM id in this file is claimed by a driver in this set.")
    return 0


def bind_lookup(args, hids, notes):
    """Either look up the ids named on the command line, or list what is spare.

    The spare list is the useful half while the ASL is still being written: it
    is the pool of names a real driver will answer to, so a new node is picked
    from it rather than invented.
    """
    if args.bind:
        rc = 0
        for hid in (h.upper() for h in args.bind):
            who = hids.get(hid, [])
            if who:
                print(f"  {hid:<12} claimed by {', '.join(sorted(who)[:4])}"
                      f"{f' +{len(who) - 4}' if len(who) > 4 else ''}")
                note = shape_note(hid, notes)
                if note:
                    print(f"  {'':<12} - {note}")
            else:
                print(f"  {hid:<12} NOT CLAIMED by any .inf in this set")
                for line in mention_lines(hid, notes):
                    print(f"  {'':<12}   {line}")
                rc = 1
        return rc

    asl = os.path.join(REPO, "tools/acpi/gauguin.asl")
    try:
        text = open(asl, encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    have = {m.group(1).upper() for m in ASL_HID.finditer(text)}

    kinds = {label: BLOCK_KIND.get(label) for label, *_ in BLOCKS}
    modern = GENERATIONS[0][1]
    print("  The pool: ids this set claims, by the block each one names.")
    print("  `used` means gauguin.asl already carries it.\n")
    for label, _base, _len, node, _why in BLOCKS:
        kind = kinds.get(label)
        idx = modern.get(kind) if kind else None
        if not idx:
            reason = ("no corpus index exists for this kind of block" if not kind
                      else f"no `{kind}` index measured in the modern table")
            print(f"    {label:<7} {reason}\n")
            continue
        # Drawn from the file the drivers came in rather than built from the
        # tables above: the set is the oracle, so the suggestion is whatever it
        # actually lists for this block's index.
        pool = sorted(h for h in hids
                      if QCOM_ID.match(h) and len(h) == 8 and h.endswith(idx))
        if not pool:
            print(f"    {label:<7} nothing in this set claims index `{idx}`\n")
            continue
        print(f"    {label:<7} {node}")
        for h in pool:
            mark = "used" if h in have else "    "
            print(f"            {mark}  {h}  {', '.join(sorted(hids[h])[:2])}")
        print()

    # Everything else the set claims. Kept separate from the table above on
    # purpose: those are blocks gauguin's device tree says exist, and this is
    # the remainder, which is where a node this port *chooses* to add - the
    # PMIC at \_SB.PM01, for one - has to be picked from. Folding it into the
    # table would be reporting a choice as a measurement.
    named = set()
    for label, *_ in BLOCKS:
        kind = BLOCK_KIND.get(label)
        idx = modern.get(kind) if kind else None
        if idx:
            named |= {h for h in hids
                      if QCOM_ID.match(h) and len(h) == 8 and h.endswith(idx)}
    rest = sorted(h for h in hids if QCOM_ID.match(h) and h not in named)
    if rest:
        print("  The remainder: QCOM ids this set claims that no block above does.")
        print("  A node this port adds by choice - `\\_SB.PM01`, the PMIC the")
        print("  button node's GpioInt resources belong to - is named from here,\n"
              "  not from the table, so that the choice stays visible as one.")
        print()
        for h in rest:
            print(f"            {h}  {', '.join(sorted(hids[h])[:2])}")
        print()
    return 0


def disassemble(aml, cache):
    """(dsl_path or None) - iasl -d, cached, because 36 trees take ~90 s.

    The cache is a function of the tree, not of /tmp's history: a `.dsl` older
    than its `.aml` is ignored and rebuilt. The first form of this keyed on the
    path alone, and the one table that changes in this tree is our own - so the
    corpus silently kept a disassembly of `gauguin/DSDT.aml` from an earlier
    revision, and `tools/acpi-order-votes.py` scored the file against a copy of
    itself that no longer matched the file on disk. Measured at Step 4.88: 65 of
    the 66 cached disassemblies were current and that one was 4,830 bytes of AML
    behind. A stale cache is worse than no cache here, because it looks like a
    reading: the numbers a caller prints are reproducible from /tmp and not from
    the repository.
    """
    rel = os.path.relpath(aml, DEFAULT_TREE)
    name = rel.replace("/", "-").replace(".aml", "")
    dsl = os.path.join(cache, name + ".dsl")
    if (not os.path.exists(dsl)
            or os.path.getmtime(dsl) < os.path.getmtime(aml)):
        subprocess.run(["iasl", "-d", "-p", os.path.join(cache, name), aml],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dsl if os.path.exists(dsl) else None


def devices_in(dsl):
    """[(device_name, hid, cid, base_address, length)] in file order.

    The walk keeps a stack of enclosing devices. A resource is attributed to
    the innermost enclosing device that has a `_HID`, which is what a driver
    binds to; a `_CRS` inside a child that has only an `_ADR` (the UFS `DEV0`
    case) belongs to the parent.

    The length is carried because a reference's window is sometimes much
    coarser than the block it declares: Lahaina's `SPMI` claims
    `0x0C400000` for `0x02800000`, forty megabytes, which contains gauguin's
    arbiter at `0x0C440000`. An exact-equality census cannot see a block
    inside a window like that, and that - not a window that moves between
    SoCs - is why this tool reported SPMI as having no reference at all.
    """
    out = []
    stack = []

    def attribute(base, length):
        """Give a window to the innermost enclosing device that has a `_HID`."""
        for fr in reversed(stack):
            if fr[1]:
                out.append((fr[0], fr[1], fr[2], base, length))
                return

    # `NEXT` is a string and not True on purpose. `isinstance(True, int)` is
    # true in Python, so a boolean "the address is on the next line" sentinel
    # passes an `isinstance(pending, int)` test, records base 1, and clears
    # itself - which is how the first draft of this tool reported that *no*
    # reference DSDT describes any of gauguin's blocks.
    NEXT = "next"
    pending = None        # base address, an int, or NEXT while it is unread
    want_len = False      # base is known; its length is on the next line
    for ln in open(dsl, errors="replace"):
        m = DEVICE.match(ln)
        if m:
            stack.append([m.group(2), None, None])
            pending = None
            want_len = False
            continue
        h = NAME_HID.search(ln)
        if h and stack:
            for fr in reversed(stack):
                if fr[1] is None:
                    fr[1] = h.group(1)
                    break
            continue
        c = NAME_CID.search(ln)
        if c and stack:
            for fr in reversed(stack):
                if fr[2] is None:
                    fr[2] = c.group(1)
                    break
            continue
        # The disassembly puts a window over three lines - the call, the base
        # with an `// Address Base` comment, then the length - and a source
        # file may put all three on one. Both are accepted; a window whose
        # length never arrives is still recorded, with the length `None`.
        if want_len:
            n = HEX.search(ln)
            if n:
                attribute(pending, int(n.group(0), 16))
                pending = None
            elif ")" in ln:
                attribute(pending, None)
                pending = None
            want_len = False
            continue
        mm = MEMFIX_CALL.search(ln)
        if mm:
            found = HEX.findall(mm.group(1))
            if not found:
                pending = NEXT
            elif len(found) > 1:
                attribute(int(found[0], 16), int(found[1], 16))
            else:
                pending = int(found[0], 16)
                want_len = True
            continue
        if pending is NEXT:
            n = HEX.search(ln)
            if n:
                pending = int(n.group(0), 16)
                want_len = True
    return out


def table_files(tree, keep_self=False):
    """Every ACPI table in the reference tree, not just each platform's DSDT.

    The first draft of this tool read `*/DSDT.aml` alone and concluded that two
    of gauguin's blocks had no reference anywhere. That was wrong, and wrong in
    the direction that flatters a negative result: the tree also carries the
    board variants (`DSDT_MTP`, `DSDT_QRD`, `DSDT_IDP`) and the SSDTs, and the
    variants are where Qualcomm writes the *complete* device list. Lahaina's
    `DSDT.aml` has 24 devices; Lahaina's `DSDT_MTP` has 152, including the
    `GIO0` node on gauguin's exact TLMM window.

    **The one file this excludes is the one being written.** `Platforms/Xiaomi/
    gauguin/DSDT.aml` is generated from `tools/acpi/gauguin.asl` by this tree's
    own build, so counting it makes every question here self-referential in the
    direction that flatters the answer: a block we have already described gains
    a reference, and a name we chose comes back as a name the corpus agrees on.
    It is not hypothetical. The corpus is 66 files of which one is ours, and six
    of our forty-odd nodes were being read back as evidence - `GIO0`, `SPMI`,
    `UAR2`, `I2C8`, `I2C9` and `IC11` - which inflated TLMM from 11 references
    to 12, SE3 from 3 to 4, SE7 from 3 to 4, and gave SE0u and SE5 a third
    "distinct name" apiece that exists in no other table. Measured 2026-09-27.

    Because the effect grows with our own work - every node added to
    `gauguin.asl` adds a reference to its own block - this filter is what makes
    two runs of this tool comparable across time. Step 4.58's counts were taken
    before `UAR2` existed and today's unfiltered run reads one higher for a
    reason that has nothing to do with the corpus. The same class of mistake is
    why `acpi-dep-census.py` was rewritten at Step 4.94 and why the cache key
    below is the tree and not the path.

    `keep_self=True` returns the raw glob, and exists because four tools in
    `tools/` load this module to get the corpus and then do their *own*
    dropping, each with its own `--keep-self`: `acpi-dep-census.py`,
    `acpi-order-votes.py`, `acpi-adc-blob-census.py` and
    `acpi-usb-pair-census.py`. Their drop is by the stem of the `--asl` they
    are handed, which is a different rule from this one and is the rule their
    prose is written against. Excluding the file here as well makes theirs a
    no-op: after Step 4.147 all four printed the same corpus with and without
    `--keep-self`, which silently deleted the second framing each of them
    documents - `acpi-dep-census.py`'s "I2C/IC 55 nodes and 43 `{PEP0}` -> 58
    and 46" is the difference, and it is exactly what a no-op stops printing.
    So the filter is this module's default and is opt-out for a caller that
    has its own. Corrected in Step 4.148.
    """
    self_aml = os.path.join(tree, "Platforms", "Xiaomi", "gauguin", "DSDT.aml")
    pats = ["Platforms/*/*/", "Silicon/Qualcomm/*/"]
    found = sorted(set(
        p for pre in pats
        for pat in ("DSDT*.aml", "SSDT*.aml")
        for p in glob.glob(tree + "/" + pre + pat)))
    if keep_self:
        return found
    return [p for p in found
            if os.path.abspath(p) != os.path.abspath(self_aml)]


def census(tree, cache):
    """({base: [(platform, device, hid, cid, base, len)]}, tables) over the corpus.

    Every window in the corpus is kept, not just the ones at gauguin's own
    addresses, because the second question a caller asks is which references
    *contain* an address. A reference's `_CRS` is often much coarser than the
    block it declares, and equality alone reports that as a miss.
    """
    amls = table_files(tree)
    os.makedirs(cache, exist_ok=True)
    found = {}
    for aml in amls:
        dsl = disassemble(aml, cache)
        if not dsl:
            print(f"  !! iasl could not read {aml}", file=sys.stderr)
            continue
        # Keep the table name: `Xiaomi/lahaina/DSDT` and
        # `Xiaomi/lahaina/DSDT_MTP` are different readings of one platform and
        # collapsing them to `Xiaomi/lahaina` is how the variants went unread.
        plat = os.path.relpath(aml, tree)[:-4]
        plat = re.sub(r"^(Platforms|Silicon)/", "", plat)
        for dev, hid, cid, base, length in devices_in(dsl):
            if base is None:
                continue
            found.setdefault(base, []).append((plat, dev, hid, cid, base, length))
    return found, len(amls)


def containing(found, addr):
    """[(platform, device, hid, base, length)] whose window holds `addr`.

    Strictly bigger than a point: a window that starts at `addr` is the exact
    match the caller already has, and counting it twice would make a 40 MB
    region look like a second reference.
    """
    out = []
    for _base, rows in found.items():
        for plat, dev, hid, _cid, base, length in rows:
            if base != addr and length and base < addr < base + length:
                out.append((plat, dev, hid, base, length))
    return out


def cmd_blocks():
    print("gauguin's blocks, as the device tree gives them:\n")
    print(f"  {'block':<7} {'base':<12} {'len':<9} node")
    for label, base, length, node, why in BLOCKS:
        print(f"  {label:<7} 0x{base:08X}  0x{length:06X}  {node}")
        print(f"  {'':<7} {why}")
    print("\n  Every one of these needs an ACPI node with a `_HID` a driver")
    print("  binds to. The addresses are the part the device tree supplies.")


QCOM_ID = re.compile(r"^QCOM([0-9A-F]{2})([0-9A-F]{2})$")
ACPI_ID = re.compile(r"^ACPI[0-9A-F]{4}$")
PNP_ID = re.compile(r"^PNP[0-9A-F]{4}$")


def collect_by_name(tree, cache):
    """{device name: {hid: [platform/table]}} over every reference table.

    The address join in `census` cannot see SPMI at all: the reference `SPMI`
    node declares `0x0C400000` for `0x02800000` - forty megabytes - while
    gauguin's arbiter sits at `0x0C440000` inside that region, so a reader
    testing for equality reports "no reference device at this address" about
    a block 22 of the 65 tables describe. Qualcomm's reference tables name
    their devices by function, and *that* is the key that carries.
    """
    byname = {}
    for aml in table_files(tree):
        dsl = disassemble(aml, cache)
        if not dsl:
            continue
        plat = re.sub(r"^(Platforms|Silicon)/", "",
                      os.path.relpath(aml, tree)[:-4])
        for dev, hid, _cid, _base, _len in devices_in(dsl):
            if hid:
                byname.setdefault(dev, {}).setdefault(hid, []).append(plat)
    return byname


# The reference device names for the blocks gauguin's destination table has to
# describe. The reference DSDTs use these names on every SoC, which is what
# makes them usable as a join key where an address is not.
REF_NAMES = {
    "GIO0": "TLMM", "SPMI": "SPMI", "PMIC": "SPMI (PMIC child)",
    "IC": "SE* I2C", "SPI": "SE* SPI", "UR": "SE* UART",
    "TSEN": "TSENS", "TSSC": "TSENS", "QTSC": "TSENS",
    "BTNS": "buttons (ACPI0011)",
}

# The measured index tables. The low pair of `QCOM<family><index>` is fixed per
# generation of the table generator - `--functions` prints the evidence, which is
# that the families arrive in groups rather than scattered. There are three of
# those groups in the corpus, not two: this list used to merge 02 in with 05 08
# 14, and family 02 does not share their indices (`SPMI` is 16 under 02 and 0C
# under 05 08 14). The SDM850 table is incomplete because the corpus gives no SE
# indices for it; a `None` there means unmeasured, not absent.
#
# The PMIC nodes are deliberately not in here even though their index is measured
# and splits the same way - `PM01` is `QCOM<family>2D` under 09 0A 0C 1A 25,
# `QCOM<family>30` under 05 08 14 and `QCOM0269` for 02. The index is a fact; which
# of gauguin's four SPMI PMICs becomes `PM01` is a choice this port makes, and a
# count that mixed the two would be reporting the choice as a measurement.
GENERATIONS = [
    ("modern  (index table read off 09 0A 0C 1A 25)", {
        "SPMI": "0B", "TLMM": "0C", "MMU": "09", "QDSS": "56", "RFS": "15",
        "GPU": "36", "I2C": "10", "SPI": "0E", "UART": "16"}),
    ("legacy  (index table read off 05 08 14)", {
        "SPMI": "0C", "TLMM": "0D", "MMU": "09", "QDSS": "5A", "RFS": "17",
        "GPU": "3A", "I2C": "11", "SPI": "0F", "UART": "18"}),
    ("sdm850  (family 02 only, SE indices unmeasured)", {
        "SPMI": "16", "TLMM": "17", "MMU": "12", "QDSS": "8C", "RFS": "35",
        "GPU": "7E", "I2C": None, "SPI": None, "UART": None}),
]

# What each of gauguin's twelve blocks is in the index tables' vocabulary. The
# two TSENS windows have no kind because the corpus has no thermal-sensor device
# at all - 65 tables, no `TSEN`, no `_HID` ending in a thermal index, and no
# device at either of gauguin's windows. Windows on these platforms gets its
# thermal zones from `ThermalZone` objects named `QCOM<family><zone>`, whose
# zone indices are their own per-generation table and which read the PMIC
# rather than a TSENS block. So these two ids cannot be guessed even once the
# family byte is known.
BLOCK_KIND = {
    "TLMM": "TLMM", "SPMI": "SPMI",
    "TSENS0": None, "TSENS1": None,
    "SE0": "SPI", "SE0u": "UART", "SE1": "I2C", "SE2": "I2C",
    "SE3": "I2C", "SE5": "I2C", "SE6": "SPI", "SE7": "I2C",
}


def cmd_functions(args):
    """Is the low pair of a QCOM id the block's function, and the high pair the SoC?

    This is the question `--drivers` and the address census both leave open.
    Every SoC-scoped id in the corpus is `QCOM` + four hex digits. If the last
    two are what the block *is* - the same on every SoC - then the function is
    a fact about the hardware, readable off the corpus; and if the first two
    are the SoC family, then naming gauguin's twelve blocks collapses to
    finding one two-digit number for SM7225. If instead both pairs move
    together, the id is opaque and only a driver set can supply it.
    """
    byname = collect_by_name(args.tree, args.cache)
    tables = len(table_files(args.tree))
    print(f"{tables} reference tables under "
          f"{os.path.relpath(args.tree, REPO)}\n")

    rows = []
    for dev, hids in byname.items():
        forms = {h: p for h, p in hids.items() if QCOM_ID.match(h)}
        if len(forms) < 2:
            continue
        suffixes = {QCOM_ID.match(h).group(2) for h in forms}
        prefixes = {QCOM_ID.match(h).group(1) for h in forms}
        rows.append((dev, forms, prefixes, suffixes))

    # A device whose low pair is constant across SoCs is the evidence for the
    # decomposition; one whose low pair moves is evidence against it, and both
    # belong in the table.
    stable = [r for r in rows if len(r[3]) == 1 and len(r[2]) > 1]
    unstable = [r for r in rows if len(r[3]) > 1]
    stable.sort(key=lambda r: (-len(r[1]), r[0]))

    print(f"  {len(stable)} device names keep one low pair across different "
          f"SoC families:\n")
    print(f"  {'device':<7} {'n':>3}  {'low':<4} {'families (high pair)':<34} ids")
    for dev, forms, prefixes, suffixes in stable[:40]:
        low = next(iter(suffixes))
        fams = " ".join(sorted(prefixes))
        ids = " ".join(sorted(forms))
        note = f"  <- {REF_NAMES[dev]}" if dev in REF_NAMES else ""
        print(f"  {dev:<7} {len(forms):>3}  {low:<4} {fams:<34} {ids}{note}")

    if unstable:
        # The groups are the finding. A device whose low pair takes one value
        # on the five modern families and another on the three older ones is
        # not a counterexample to the decomposition - it is the decomposition
        # with the generation axis still in it, and the axis is the point.
        print(f"\n  {len(unstable)} device names move, and the way they move is\n"
              f"  the generation - the families arrive grouped, not scattered:\n")
        print(f"  {'device':<7} {'n':>3}  low pair <- families")
        for dev, forms, _p, _s in sorted(unstable)[:14]:
            groups = {}
            for h in forms:
                m = QCOM_ID.match(h)
                groups.setdefault(m.group(2), []).append(m.group(1))
            ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            cell = "   ".join(f"{low} <- {' '.join(sorted(f))}"
                              for low, f in ordered[:2])
            if len(ordered) > 2:
                cell += f"   (+{len(ordered) - 2} more)"
            print(f"  {dev:<7} {len(forms):>3}  {cell}")

    print()
    print("  Read the first table as: for those ten the low pair is the same")
    print("  on every family in the corpus, so on its own it reads as a")
    print("  property of the device kind.")
    print()
    print("  Read the second as: for the rest the low pair is fixed per")
    print("  generation of the table generator, and the families arrive")
    print("  grouped rather than scattered. Five of them, groups spelled out:")
    print()
    print("    device   modern (09 0A 0C 1A 25)   older (05 08 14)  02 (SDM850)")
    print("    SPMI     0B                        0C                16")
    print("    GIO0     0C                        0D                17")
    print("    QDSS     56                        5A                8C")
    print("    RFS0     15                        17                35")
    print("    GPU0     36                        3A                7E")
    print()
    print("  which is why gauguin's TLMM window, at gauguin's exact length,")
    print("  is spelled QCOM1A0C in Lahaina's DSDT_MTP. MMU is the exception")
    print("  that fixes what the axis is: it stayed 09 across 05 08 09 0A 0C")
    print("  14 1A 25 and only moved to 12 for 02, so the axis is the")
    print("  generator that emitted the table and not the silicon.")
    print()
    print("  The family sets in that table are the ones each index was")
    print("  measured on, not a closed membership - `GPU0` lands on its")
    print("  modern index 36 under 0E as well, and GIO0 carries a fourth")
    print("  index under family 60. Which is also why `--drivers` tries")
    print("  every byte rather than these:")
    print()
    print("  And the high pair is not the SoC either - pipa and alioth both")
    print("  declare SDM8250 and carry 05 and 25. So the id is two facts in")
    print("  one string: a block index readable off this corpus once the")
    print("  generation is known, and a family token that has to come from a")
    print("  driver set or from firmware that declares it. `--drivers`")
    print("  searches every family byte against each measured index table.")


def cmd_census(args):
    found, total = census(args.tree, args.cache)
    print(f"{total} reference tables under {os.path.relpath(args.tree, REPO)}\n")
    verdicts = []
    for label, base, _len, node, _why in BLOCKS:
        rows = found.get(base, [])
        seen = {}
        for plat, dev, hid, cid, _b, _l in rows:
            seen.setdefault((hid, cid), []).append(f"{plat}/{dev}")
        covers = containing(found, base)
        if not rows:
            print(f"  {label:<7} 0x{base:08X}  {node}")
            print(f"          no reference device sits at this address")
            if covers:
                # The reference describes the block, just as part of a bigger
                # region. That distinction is the difference between "cannot be
                # named from this corpus" and "was read with the wrong test".
                bywin = {}
                for plat, dev, hid, cbase, clen in covers:
                    bywin.setdefault((hid, cbase, clen), []).append(f"{plat}/{dev}")
                for (hid, cbase, clen), where in sorted(
                        bywin.items(), key=lambda kv: -len(kv[1])):
                    who = ", ".join(sorted(where)[:3])
                    more = f" +{len(where) - 3}" if len(where) > 3 else ""
                    print(f"          but {len(where)}x {hid} claim(s) "
                          f"0x{cbase:08X} for 0x{clen:X}, which contains it:")
                    print(f"            {who}{more}")
            verdicts.append((label, 0, 0))
            print()
            continue
        print(f"  {label:<7} 0x{base:08X}  {node}")
        print(f"          {len(rows)} describe it, {len(seen)} distinct name(s)")
        for (hid, cid), where in sorted(seen.items(), key=lambda kv: -len(kv[1])):
            cid_s = f"  _CID {cid}" if cid else ""
            who = ", ".join(sorted(where)[:4])
            more = f" +{len(where) - 4}" if len(where) > 4 else ""
            print(f"            {str(hid):<12}{cid_s:<22} {len(where):>2}x  {who}{more}")
        verdicts.append((label, len(rows), len(seen)))
        print()

    print("  " + "-" * 70)
    unnamable = [l for l, rows, names in verdicts if rows == 0]
    ambiguous = [l for l, rows, names in verdicts if names > 1]
    if unnamable:
        print(f"  no reference device at this address: {', '.join(unnamable)}")
    if ambiguous:
        print(f"  more than one name in the corpus: {', '.join(ambiguous)}")
    print()
    print("  Careful with the first line: an address is a weak join key. A")
    print("  reference `_CRS` is often coarser than the block it declares -")
    print("  `SPMI` claims 0x0C400000 for 0x02800000, forty megabytes, with")
    print("  gauguin's arbiter at 0x0C440000 inside it - so an equality test")
    print("  reports a miss where a containment test finds 22 tables. Any")
    print("  block that line names is worth re-reading above before it is")
    print("  believed. `--functions` joins on the device name, which is the")
    print("  key that carries.")
    if unnamable or ambiguous:
        print()
        print("  Read this as: the name is not a hardware fact. ACPI's _HID is a")
        print("  string this port chooses, and the reference corpus choosing")
        print("  differently on every SoC is evidence the choice is free - not")
        print("  evidence that a correct name exists somewhere and is missing.")
        print("  What constrains it is the driver: a device binds to the name its")
        print("  .inf lists and to nothing else, and a node whose name no driver")
        print("  claims is absent from Device Manager with no error at all.")
        print()
        print("  So adopt a driver set first and name every block after it. The")
        print("  DSDT is written to a driver, not to the SoC. Run --drivers over")
        print("  a set to see which of these blocks it covers, and whose set it is.")
        return 0
    print("  every block has exactly one name in the corpus - safe to carry.")
    return 0


def cmd_drivers(args):
    """Which family byte turns a driver set into a name for every block.

    This is the other half of the census, and the generation search is the
    point of it. The block *index* - the low pair of `QCOM<family><index>` - is
    readable off the corpus; the *family* byte is not, and it is not derivable
    from the SoC's marketing number either: pipa and alioth both declare
    `SDM8250` and carry 05 and 25.

    What an `.inf` does carry is the exact ids its driver binds to. So a driver
    set is a four-hex-digit oracle, and this uses it as one: for each of the 256
    family bytes and each of the measured index tables, build
    `QCOM<family><index>` for every block gauguin has, and count how many of
    them the set answers to. A set that covers all of them names the family, and
    names every block in the same breath.
    """
    hids, encodings, inffiles, notes = load_driver_set(args.drivers)
    if not inffiles:
        print(f"no .inf files under {args.drivers}")
        return 1
    print_set_header(inffiles, hids, encodings, notes)

    qcom = sorted(h for h in hids if QCOM_ID.match(h))
    print(f"  {len(qcom)} of them are QCOM ids: "
          f"{' '.join(qcom[:12])}{' ...' if len(qcom) > 12 else ''}\n")

    kinds = {label: kind for label, kind in BLOCK_KIND.items()}
    nokind = sorted(l for l, k in kinds.items() if not k)
    best = []
    for gen, table in GENERATIONS:
        for byte in range(0x100):
            fam = f"{byte:02X}"
            # `None` in a generation's table means that generation's index for
            # that kind was never measured, so no id can be built from it. The
            # denominator shrinks with it rather than being faked.
            want = {label: f"QCOM{fam}{table[kind]}"
                    for label, kind in kinds.items()
                    if kind and table.get(kind)}
            hits = {label: h for label, h in want.items() if h in hids}
            if hits:
                best.append((len(hits), len(want), gen, fam, want, hits))
    best.sort(key=lambda r: -r[0])

    if nokind:
        print(f"  Not covered by this search at all: {', '.join(nokind)} - the")
        print("  corpus has no device of that kind, so there is no index to fill in.")
        print()

    if not best:
        print("  No family byte under any measured index table makes this set")
        print(f"  answer a name for any of gauguin's {len(BLOCKS)} blocks. So this")
        print("  set is not the one for this device - it is a set for some other")
        print("  SoC, and its ids say which one, above.")
        return 0

    print(f"  {'coverage':<10} {'generation':<36} family  blocks, and the id each gets")
    for n, total, gen, fam, want, hits in best[:6]:
        print(f"  {n}/{total:<8} {gen:<36} {fam}")
        for label in sorted(want):
            mark = "yes" if label in hits else " - "
            # The declaring file, because a `yes` cannot tell coverage from a
            # collision and the file can. `qci2c7280.inf` beside an SPI engine's
            # label is the collision, not the coverage.
            owner = ""
            if label in hits:
                files = sorted(hids.get(hits[label], []))
                if files:
                    owner = "  " + files[0]
                    if len(files) > 1:
                        owner += f" +{len(files) - 1}"
            print(f"  {'':<10} {'':<36} {'':<7}  {mark} {label:<6} "
                  f"{want[label]}{owner}")
        print()
    top = best[0]
    if top[0] == top[1]:
        print(f"  A complete match: family byte {top[3]} under {top[2].split()[0]},")
        print("  and the ids above are the ones the nodes must carry. Check them")
        print("  against BLOCKS before using them - a family byte that happens to")
        print("  collide on a partial set is not the same as a full one.")
    else:
        print(f"  Best is {top[0]} of {top[1]} under family {top[3]}. A partial match")
        print("  is not a family: it can happen by collision, so read the id the")
        print("  set lists for each block AND the .inf beside it before believing")
        print("  any byte - an id whose declaring driver is a different bus than")
        print("  the block is a collision, and it covers nothing.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Is a Qualcomm ACPI block's _HID a property of the block, "
                    "or of the SoC?")
    ap.add_argument("--tree", default=DEFAULT_TREE,
                    help="Silicium-ACPI tree holding the reference DSDTs")
    ap.add_argument("--cache", default=DEFAULT_CACHE,
                    help="where to keep the disassembled .dsl files")
    ap.add_argument("--blocks", action="store_true",
                    help="list gauguin's blocks and why each one is needed")
    ap.add_argument("--functions", action="store_true",
                    help="decompose the QCOM ids by device name (SoC vs block)")
    ap.add_argument("--drivers", metavar="DIR",
                    help="a Windows driver set to check coverage against")
    ap.add_argument("--bind", nargs="*", metavar="HID",
                    help="with --drivers: which driver claims these ids, or with "
                         "none named, the pool of ids the set offers per block; "
                         "an id nothing claims is also reported as named "
                         "elsewhere (another bus, a written value, or nowhere), "
                         "and a claimed one is marked when the claim is a "
                         "compatible id or an ExcludeFromSelect entry rather "
                         "than a models line")
    ap.add_argument("--asl", metavar="FILE",
                    help="with --drivers --bind: every _HID/_CID in this ASL file "
                         "against the set, and for each id nothing claims, how "
                         "else the set names it (default tools/acpi/gauguin.asl)")
    args = ap.parse_args()
    if args.blocks:
        cmd_blocks()
        return 0
    if args.functions:
        return cmd_functions(args)
    if args.bind is not None or args.asl:
        if not args.drivers:
            ap.error("--bind and --asl need --drivers DIR")
        return cmd_bind(args)
    if args.drivers:
        return cmd_drivers(args)
    return cmd_census(args)


if __name__ == "__main__":
    sys.exit(main())
