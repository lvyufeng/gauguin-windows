# 00 — Phase plan

Goal: **Windows 11 on ARM running on the gauguin test phone**, with as much of the hardware
driven as is physically possible. See [`README.md`](../README.md) for the honest ceiling —
cellular and cameras are permanently out of reach, Wi-Fi/audio/GPU are hard but plausible.

Each phase ends with a commit. A phase is only "done" when its gate has actually been
observed on hardware, not when the code compiles.

## Where things actually stand (2026-09-26)

Nothing below is "done" except P0, and the only gate observed on hardware is
P0's plus the first half of P2's (see its row). This table is the honest state;
the sections under it are the plan.

| phase | gate | state |
|---|---|---|
| **P0** survey + backup | partitions dumped and verified; no existing port | **done** — 74 partitions carved and signature-checked, `boot`/`abl`/`recovery` hashes match the device, 86 XBL drivers recovered, and `git ls-files Silicon/Qualcomm` confirms no SM7225 package upstream |
| **P1** mainline kernel | device boots mainline and prints something | **not done** — `work/out/boot-pstore.img` is built, reproducible (`make_boot_image.py --kernel`), and carries both channels a device with no UART needs: the panel itself (`simple-framebuffer` + `simpledrm` + fbcon, so the boot log is photographed off the screen) and pstore (`console-ramoops-0`, readable from Android after a warm reboot). The earlier `fastboot boot` was refused with `Failed to load/authenticate boot image` on the RAM path, and the partition path has never been tried |
| **P2** UEFI skeleton | the boot manager draws on the phone's screen and UFS appears as a block device | **half met, and it is the half that decides viability** — **our firmware executes on this phone**. The image carrying the current device tree was written to `boot`, and on the reboot the panel filled with our own output, ending in `ASSERT [DxeCore] DxeMain.c(593)`. That is the **phone's** stop, off the `boot`-partition write and not the mirror's: the mirror's own run of record stops earlier and elsewhere, at `ASSERT DebugLib.c +78` inside `RpmhDxe` — a `DebugPrint` reached with a null format, one entry past `K 18` (`docs/08` step 4.128) — so the two runs are not the same stop and the sentence should not be read as describing the mirror. What the phone's line means is fixed by the source and not inferred: `DxeMain.c:593` is `ASSERT_EFI_ERROR (Status)` on `Status = CoreAllEfiServicesAvailable ()` at `:582`, which runs *after* `CoreDispatcher ()` at `:562` returns — so the phone ran its whole batch and then failed the architectural-protocol check, and `CoreDisplayMissingArchProtocols ()` at `:568` had already printed the missing names above the assert. That text can only come from us: `DxeMain.c:593` is our line, and in a DEBUG build `SerialPortLib` is bound to `FrameBufferSerialPortLib`, so every `DEBUG ()` string is drawn into the framebuffer — which is why the firmware can talk while there is no shell, no boot-manager menu and no UART. (It also means text on the panel is not evidence that BDS ran.) What remains is the second half: DXE stops because at least one *architectural protocol* was never installed, and the name of the first missing one is printed two lines above the assert, on a screen that is legible by design (`GetFontScale ()` gives 10×24 glyphs, ~90×100 of them) and is wiped only when it runs past the last row — which the mirror's own run of record does not: its log is 92 rows on a 100-row panel, so no capture of this payload shows a wipe, and a *gap* between two samples is a row the console rewrote in place rather than text that was lost (`docs/08` step 4.125). `docs/08` step 4.8 has the reading, and the dep chain that narrows it. That chain's length was itself wrong for a while: `docs/08` step 4.9 recorded the panel as naming **eight** missing protocols, and the set is **nine** — `Variable` and `Variable Write` are installed by one driver, two statements apart, and that driver's `P2 SEQ` letter is `L`, so it installed neither. Step 4.95 derives the set from the volume and the source (`tools/arch-protocol-census.py`) and corrects every count that came off that reading; the partition is exact both ways — nine protocols absent on eight `L` producers, four present on four `s` — so the missing name is not a judgement call. Nothing about the blocker changes, because the ninth name shares a producer with the eighth and lands on the same `SEQ` index. The three earlier attempts stopped before any of our code for a reason now fixed: the tree in the image had no `/__symbols__`, so ABL refused the vendor overlay (`docs/07`). The gate said "reaches a shell" until the volume was inventoried and the shell turned out to be absent from *every* platform in the tree, `suryaPkg` included, so it would not have distinguished our firmware from a working one |
| **P3** ACPI | Windows installer boots and sees UFS | **item 1 well along, 2–4 not started** — the DSDT, `APIC`, `FACP`, `FACS`, `GTDT` and the shared `SSDT` are in the build and were read back out of the artifact; UFS, USB, the PMIC family, the GPIO controller, the Type-C controller, all six of the QUP engines the board leaves running, the two GPI DMA controllers those engines are wired to the two SMMUs those controllers sit behind, the `IPCC` mailbox every one of the family's `_DEP`s resolves through, the `ABD` bridge the family reads its zero-configuration data out of, the `SCM0` secure-channel interface three of the family's later nodes name, the `PMAP` PMIC Apps device that is the first node here whose `_DEP` is written whole because its three referents are now all present, the `PRTC` Time and Alarm Device whose `_HID` is the first in this table that is not a QCOM id at all, and the `PML0` companion PMIC on I2C, the first node here whose *name* a driver package states rather than the corpus agreeing on it and the first whose address set a registry default explains rather than a majority vote, and the `PILC` Peripheral Image Loader, the first node here whose id comes from the **06** generation of the service group — a generation measured across seven nodes at once and decided by the installed driver set rather than by the silicon — and the `RPEN` Reset Power Error Notifier beside it, the same rule confirmed from outside by a second node derived on its own, and the first node here whose *absence* another node's `_DEP` names, and the `GLNK` Generic Link transport, the first node here whose id is fixed by a fourth id this table had already written rather than by the driver set alone and the first whose dependency the board states rather than the corpus — its three `glink-edge`s all mbox into the `IPCC` mailbox, and the `IPC0` IPC router beside it, the other half of the pair `GLNK` belongs to — its id is fixed by the same fourth id and its body is the smallest this table has written, and the `TFTP` subsystem transport beside it, the first node here placed by measurement rather than by reading a neighbour — its id is fixed by the `PILC`/`RPEN`/`IPCC` triple all 21 tables carrying one agree on, table for table, which is the mirror image of the rule that had to read the *transport* id off an id already in the table, and its slot is the unique maximum of a scoring over the 602 table-votes its relations carry, a measurement that also accounted for the first time for every one of the 128 corpus relations this table's node order contradicts, all 128 falling out of seven placements, and the `BAM1` crypto BAM beside it, the first node here whose `_CRS` the corpus and the board state identically — base `0x01DC4000`, length `0x24000`, GSI `0x130` all three agreed by 21 of 21 tables and by `dma-controller@1dc4000` — whose id two arguments reach independently, the shipped driver set claiming one BAM id of nine and this platform's own prefix giving the same one, and whose position is the first this file could not decide by vote: the 356 table-votes its relations carry have a maximum of 335 reached by six slots, so adjacency decides instead — and with it the record that its partner `BAM5` is owed rather than written, because its `0x03A84000`/GSI `0xC4` is corroborated only by another die, and that this node's one unsatisfied relation and the twelve 4.84 already counted are the same `SPMI` misplacement, two independent measurements agreeing where the fault is, and the correction that renames the QUP SE1 engine `UAR2` — the board's one enabled GENI UART at `0x884000`, carrying the high-speed compatible, three `pinctrl` states and a `qcom,wakeup-byte` against the two `status = "disabled"` nodes that the board's alias, the payload's alias and the firmware's only UART string all point at, and the family's `_STA 0x0B` hiding measured to track a `BTH0` claimant — nineteen tables carry one and every one of them names its own table's UART in its `_DEP` — that a SLIMbus Bluetooth board cannot have, the rename moving no slot and keeping `_UID 0x02`, and bringing two counts this range had written back for re-measurement, and the ladder that names these engines re-read as the special case it is — `_UID` being the engine's **SE number plus one**, whose eight-per-wrapper form (`8 * wrapper + SE index + 1`) fits all nineteen tagged engine nodes in wrapper 0 and seventeen of the twenty-seven at wrappers 1 and 2 over a 46-node corpus, and whose gauguin instantiation is settled by the board's own aliases: `qupv3_se1_4uart` at `0x884000`, and `0x980000` through `0x990000` numbered `qupv3_se6` through `qupv3_se10` for six SEs per wrapper, so this step's engine is 2 by both routes while the three wrapper-1 nodes the table writes at `0x984000`, `0x988000` and `0x990000` are SE 7, 8 and 10 and each two too high — `IC10`, `IC11` and `IC13` following their numbers, a correction measured at 4.86 and applied at 4.87, where those three nodes became **`I2C8` (`_UID 0x08`), `I2C9` (`0x09`) and `IC11` (`0x0B`)** and `PML0`'s `_DEP` and both of its `I2cSerialBusV2` entries moved to `\_SB.IC11` — and that rename is **witnessed and not only derived**, by two tables of this generation whose wrappers carry six SEs as well: miatoll and a52q both put wrapper 1 at `0x00A80000` and write `I2C8` at `+0x4000` with `_UID 0x08`, `UARD` at `+0x8000` with `0x09`, `IC10` at `+0xC000` with `0x0A` and `SP12`/`IC12` at `+0x14000` with `0x0C` with the SE 10 at `+0x10000` left unwritten, and a52q writes wrapper 0's `I2C5` at `0x00890000` with `_UID 5`, the same rule carrying no wrapper at all, so the name at gauguin's offset is another SoC's name and the engine at `+0x8000` is the one field that does not cross — a UART on both witnesses, an I2C engine here, which is 4.71's rule that the slot identifies the engine and the board the protocol, and **Step 4.88** wrote no node and reordered the file instead: the 35 top-level declarations moved into the order the corpus itself states (`UFS0 ABD PMIC PML0 PM01 PMAP PRTC BAM1 I2C8 I2C9 UAR2 IC11 RPEN PILC TFTP MMU0 MMU1 SCM0 SPMI GIO0 IPCC IPC0 GLNK CPU0…CPU7 QGP0 QGP1 URS0 UCS0`), which is 8 relocations of 35 units by longest common subsequence — `SPMI` 3→18, `GIO0` 11→19, `IPC0` 19→21, `GLNK` 20→22, `QGP0` 21→31, `QGP1` 22→32, `URS0` 2→33, `UCS0` 1→34 — against a measured cost of **112 broken relations over 32 nodes** and a score of 7,874 of a 9,768 ceiling, now **0 broken and 9,768 of 9,768**, the ceiling being what `--prove` computes as the pairwise bound and 9,840 − 72 unavoidable single-table dissents (60 pairs, 48 with one dissenting table and 12 with two: `vili` alone in most, `kebab` beside it on each CPU against `SPMI`, and nine pairs where `aston` alone or `aston` with `nx729j` act on `CPU0`–`CPU3` against `I2C9` and `UFS0`, the only pairs of the 60 `vili` does not join); two faults in the apparatus came out with it, both fixed and both recorded, the corpus carrying a disassembly of *this* table (`Platforms-Xiaomi-gauguin-DSDT.dsl`, so the file was one of its own 58 voters, now left out by name with `--keep-self` to put it back — 57 tables/558 pairs/9,840 votes against 58/595/10,440, the two framings agreeing on broken 0 and score equal to the ceiling) and `tools/acpi-hid-census.py`'s `disassemble()` keying its cache on the path alone, which left this table's cached disassembly built from a 1,520-byte AML 4,830 bytes behind the 6,350-byte file it was a copy of — 65 of 66 cached disassemblies current, that one not, now rebuilt when older than its `.aml`; the stale copy was rebuilt to measure what it costs, and it changes **no verdict** (broken 0 and score equal to the ceiling in both readings) because it contributes **no pair** — its ten nodes are the P2-era skeleton, every pair they make is already declared elsewhere, so it only adds votes and moves the two totals together, 9,768 → 9,805, which is why the fault went unnoticed; the 116-vs-112 difference belongs instead to the *current* copy, whose four relations at weight 1 are `SPMI`, `GIO0`, `URS0` and `UCS0` each after `UAR2`, i.e. the 37 pairs no other table declares, 34 of them `UAR2`'s; the move is proved textual rather than asserted, the **multiset of non-comment lines identical** between the two revisions, the diff's 1,284 removed and 1,284 inserted lines carrying 834 non-comment lines each way, and the only six same-position hunks all comment-only (28 comment lines out, 37 in) in `ABD`'s, `BAM1`'s and `RPEN`'s preambles, which is where the debts those three recorded for this step were marked paid — `BAM1`'s 17 relations all holding once `SPMI` stood after `SCM0`, `RPEN`'s six now satisfied, `ABD`'s slot re-derived as after `UFS0`; and `--fixed-point` measures what the corpus does *not* decide, giving 31 of 35 nodes a determined slot and leaving the four QUP engines free (`UAR2` ties with every one of the 35 slots, `I2C8` with 8–11, `I2C9` with 8–10, `IC11` with 10–11), so the region is a window and not an order, and the silence is located rather than general — of the 595 pairs these 35 units make, **37 have no declarer outside this table** (34 `UAR2`'s, three `I2C8`'s), so with the copy out `UAR2` keeps 0 pairs while the other engines keep 30 to 33; the correction also separated two numbers this row had been reading off one another, the **wrapper-relative index** that the `_STR` and the board's `dmas` carry and that travels between SoCs, and the **global SE number** that plus one is the slot and that does not, so 4.68's “slot 11” for `i2c@988000` is slot **9** on gauguin while the engine, its GSI `0x183` and the `focaltech@38` on it are unmoved; the AML is **6,350 bytes**, 266 opcodes and 409 named objects again, and by derivation rather than resemblance — a reorder of whole declarations permutes the bytes and moves no multiset-dependent number, so size, checksum `0xcc`, opcode count and named-object count are 4.87's exactly, and only the sha256 moves, `b4f900f9…5732c59e` → `3f8d7472…cd6ebd5`, with the control that the 4.87 source compiled now is also 6,350 bytes with the same byte multiset, first differing at offset 314, the ids moving with their declarations exactly as a reorder must and a rename never does (`QCOM0A16` 3099 → 1695, the three `QCOM0A10` 2859/2979/3219 → 1455/1575/1815, `QCOM06DC` 3411 → 2007, `QCOM0A0D` 3464 → 4790, `QCOM0A84` 3507 → 4833), the `DSDT` readback at `0x0054d4c8` for an **eighteenth step** and `EFI_FV_TAKEN_SIZE 0x703fe8` unmoved while `FVMAIN_COMPACT`'s taken size goes `0x10aff8` → `0x10afe0` (Steps 4.69–4.88) are described, and so is **Step 4.89**, whose one new node is `BTNS` — `_HID` `ACPI0011`, the generic button device, and the first node here whose driver the operating system supplies rather than a vendor `.inf` does, on the widest unanimity any node here has been written on (22 of the corpus's 66 tables carry it, and 22 of 22 state that id) — with three `GpioInt` descriptors whose first and third pin lists are the PON's kpdpwr and resin indices, the very numbers `PM01._DSM` function 1 returns, which is where the correction in that step came from: that function returned lisa's `{0x07, 0x06}` and returns this board's `{0x00, 0x01}`, measured first from the corpus (in all 20 tables carrying both a `PM01` and a `BTNS` the pair equals that node's `pins[0]` and `pins[2]` field for field) and then from this board's tree, whose `pon@800` under `pm6350` names pwrkey and resin at 0 and 1 while the tempting `pmk8350` pair of 7 and 6 is `status = "disabled"` on both keys; its middle pin list is the volume-up key at **`0x0081`**, which is **reasoned and not measured** — `pm6350`'s PMIC-GPIO 2 under a base of `0x7F`, one of the only three bases the corpus carries (`0x7F` at SPMI slot 0, `0xC0` at slot 1, `0x207` at slot 4), and `pm6350` is the one PMIC here with no precedent in any device tree or driver on this machine. The AML is **6,587 bytes**, 267 opcodes and 416 named objects, checksum `0xa4`, length `0x19bb`, whose 237-byte growth is 239 added and 2 removed — `0x07, 0x06` → `0x00, 0x01` is two one-byte constant opcodes in place of two two-byte ones, the first structural difference at offset 763; the `DSDT` readback sits at `0x0054d4c8` for a **nineteenth step** with `EFI_FV_TAKEN_SIZE 0x7040d8` and `FVMAIN` itself grown a page to `0x705000` because 4.88's volume had only `0x18` bytes free at its end; the census is **52 declarations, 38 distinct**, `ACPI0011` being the whole of the change; and the payload set `aec449a5…`/`48705893…`/`52107ae9…` is archived in `work/out/p2-4.89`. **Step 4.90** then put the USB port's `_UPC` and `_PLD` where the corpus puts them: off `USB0` and `UFN0` themselves and onto a `RHUB`/`PRT1` pair under each — `_ADR`-addressed children, the second node here that answers to no driver id, where `BTNS` needs none because the operating system supplies its driver and this pair needs none because the address is the identity — and the first node placed by a disagreement with bitra rather than by agreement with it: bitra is family `04` and carries the pair on the controller itself, while both of family `0A`'s tables carry it only inside `PRT1`, which is the rule `URS0._HID` settled at 4.65. It is a move and not a rewrite, and the measurement says so: the 27-field `_PLD` and the four-field `_UPC` are the two blobs that were standing on the two controllers, byte-identical as a multiset before and after, so the file's `Name` count rises by four and its blob count by nothing; 20 of the 65 tables that are not this one carry the pair and 20 of 20 carry it under both controllers, 44 carry neither — the two counts as **Step 4.91** re-derived them, not as this clause first stated them, when the pair was framed as 20 of 66 and the tables declaring neither as 43 — and the placement majority differs between the two by one slot, which the node follows per device rather than harmonising. The AML is **6,641 bytes**, `f260db3a…`, checksum `0x4f`, length `0x19f1`, **+54 bytes** for four device headers and their package lengths; the `DSDT` readback sits at `0x0054d4c8` for a **twentieth step**, `EFI_FV_TAKEN_SIZE 0x704110` up `0x38` with `FVMAIN` itself unmoved at `0x705000`, so the three payloads keep 4.89's sizes to the byte; the order vote does not move at all — 10,356 of a 10,356 ceiling with the same four free nodes and 0 broken relations of 532 — because the four new devices are members inside units the table already had; the census is **52 declarations, 38 distinct**, unchanged, which is the point of the node rather than an omission; and the payload set `45c978f37…`/`e1b23ab0…`/`0be06803…` is archived in `work/out/p2-4.90`, which leaves the 4.74 control in `work/out/p2-variants` intact for a **fourteenth** step. **Step 4.91** is the one step here whose subject is the evidence and not the firmware: it wrote no node, added no id, moved no resource, and did not change a byte of the compiled table — the AML is **6,641 bytes**, `f260db3a…`, checksum `0x4f`, length `0x19f1`, 267 opcodes and 424 named objects, byte-identical to 4.90's, and the `DSDT` readback sits at `0x0054d4c8` for a **twenty-first step** with `EFI_FV_TAKEN_SIZE 0x704110` and `FVMAIN_COMPACT`'s taken size `0x10b0e8` both unmoved, so all three payloads keep 4.90's sizes and hashes to the byte and are archived in `work/out/p2-4.91` as well, which leaves the 4.74 control in `work/out/p2-variants` intact for a **fifteenth** step. What it did was make that comment's numbers reproducible and then correct them: they had been measured with a throwaway script in `/tmp`, and this repository's own standard is that a number a reader cannot re-derive from the repository is not a measurement, so `tools/acpi-usb-pair-census.py` now asks the same questions from here — by *declaration* rather than by `grep`, one brace-stack pass attributing each `RHUB` to the device that encloses it, so `USB0`'s and `UFN0`'s are two occurrences with different parents rather than two matches of one pattern, which is precisely what `nabu` breaks. Seven of the numbers moved. The pair is 20 of the **65** tables that are not this one, not 20 of 66: the corpus is a Mu-Silicium checkout's `Silicium-ACPI` submodule and `tools/sync-uefi-platform.sh` installs ours into it, so ours is one of the sixty-six and a file scoring itself is not a measurement — the same rule and the same default `tools/acpi-order-votes.py` already keeps, with `--keep-self` printing the other framing beside it because the difference *is* the contribution of the file being written. **44** tables declare neither, not 43. `RHUB`'s own body is one `Name (_ADR, Zero)` in **58 of 60**, not 59 of 60, and `caymanslm` is not the corpus's only non-bare hub: `nabu` carries a third `RHUB`, under a `USBD`, holding an `MP0` with an `XMKB` in it. `PLD_GroupPosition` `0x3` stands on **four** ports, not vayu's two — pipa's two state it as well. The slot denominators are **21 and 20**, not 20 and 19. And the seventh is not an arithmetic slip but a field the earlier reading could not see at all: pipa's four `_PLD`s were reported as stating no `GroupPosition`, and they state one, because iasl renders a `_PLD` built as a `VarPackage` (opcode `0x13`) as a raw `Buffer (0x14)` rather than as the named fields of a `ToPLD` (`0x12`), and a reader that knows only the field names cannot look inside it — the field is seven bits at bit 7 of bytes 10–11, little endian, measured by compiling `ToPLD` at 0, 1, 2, 3, 4, `0x0F`, `0x1F` and `0x7F` and reading the bytes back, which gives `gp=0x01 → 80 00` and `gp=0x02 → 00 01`, and pipa's four read `0x0` on its two `URS0` ports and `0x3` on its two `URS1` ones — which makes `0x0` unanimous on all **40** `URS0` ports, 38 of them named in a `ToPLD` and two read out of the twenty bytes. The two facts a later step inherits are that `caymanslm`'s exception is two boards wide rather than one, and that the `URS0`/`URS1` split in `GroupPosition` is 40 of 40 against 14 and 4 rather than against 14 and 2. The order vote does not move — 10,356 of a 10,356 ceiling, 0 broken relations of 532, the same four free nodes — and the census is still **52 declarations, 38 distinct**, because the step changed no node for either to see. **Step 4.92** writes `ADC1` (`QCOM0A11`, the one id `qcadc7280.inf` claims, service `qcADC`) as the last device of `_SB`: the first node here that waits on nothing this table has not already got, since both its `_DEP`s and the one resource provider its `_CRS` names are in it, and the first whose twelve bytes of vendor data had to be answered by the corpus rather than by the board — no partition of this device's firmware carries a DSDT at all and the driver reads its own `ADC1.bin`, so `tools/acpi-adc-blob-census.py` is the tool that answers for them, and its 20 tables say the first of the two moving bytes travels with the pin pair and the second with the `_HID`, which is why `0x34` is written and `0x35` is what one byte's difference would give. The AML is **6,891 bytes**, `8d0a821f…`, checksum `0x92`, length `0x1aeb`, 273 opcodes and 435 named objects, 0 errors with 24 warnings; the `DSDT` reads back out of the payload at `0x0054d4c8` for a **twenty-second step** with `EFI_FV_TAKEN_SIZE 0x704208` and `FVMAIN_COMPACT`'s taken size `0x10b178`; the device count moves 43 -> **44**, methods 101 -> **103**; the census is **53 declarations, 39 distinct** and the order vote moves for the first time since 4.89 to **10,964 of a 10,964 ceiling** over 627 pairs and 567 relations; and the payload set `01568bf2…`/`570db208…`/`1d424e87…` is archived in `work/out/p2-4.92`, which leaves the 4.74 control in `work/out/p2-variants` intact for a **sixteenth** step. **Step 4.93** writes `PEP0` (`QCOM0A17`, `_CID` `PNP0D80`, claimed by `qcpep.wd7280.inf`) with its companion `AGR0` (`ACPI000C`) after `UCS0` — the node every withheld `_DEP` in this file has been waiting on, and the one carrying both interfaces the Windows power engine uses: the `_DSM` whose UUID is the raw GUID at offset 1707616 of `qcpep7280.sys` and whose six subsystem selectors are `External`-declared and `CondRefOf`-guarded here because this board's six are firmware and not ACPI nodes, and the `THTZ` dispatcher, written over this table's own thirteen zones rather than over lisa's thirty-two keys, with one block temporary per key (`_T_1`…`_T_D`, the compiler's own `_T_0`…`_T_W` numbering, which is also why this shape of method caps at thirty-six blocks). Its `_CRS` is eleven GSIs and the set is a function of the `_HID`'s family byte rather than of the SoC, but the first four are derived from this board — `qcom,pdc-ranges` maps pins `0x1A`–`0x1D` to INTIDs `0x21A`–`0x21D` and those four pins are exactly the `uplow`/`critical` lines of the two `thermal-sensor@c263000`/`@c265000` blocks — and its `PPPP` is forty-six rails, every one a regulator node in this board's own tree and every name in `qcpep7280.sys`'s own vocabulary. It also lands the `_DEP`s that only became writable with it: on `ABD`, on `UCS0`, on `URS0` (`{PEP0, UCS0}`), and as a `Method` on twelve of the thirteen thermal zones — `TZ13` left out because its corpus form names `\_SB.BCL1` and this table has none — plus `_TZD` on the three `_UID One` pairs. The AML is **12,257 bytes**, `7f171e70…`, checksum `0xab`, length `0x2fe1`, 742 opcodes and 508 named objects, 0 errors and 26 warnings, the two new ones being the `_SUB` fall-through the corpus's own tables also leave out; the `DSDT` reads back out of the payload at `0x0054d4c8` for a **twenty-third step**, byte-identical to the direct compile, with `EFI_FV_TAKEN_SIZE 0x705700` and `FVMAIN_COMPACT`'s taken size `0x10b650`; the device count moves 44 -> **46** and methods 103 -> **132**; the census is **56 declarations, 42 distinct** with the unclaimed pair unchanged at `QCOM0A8B` and `QCOM24A5`; the order vote is **12,240 of a 12,240 ceiling** over 700 pairs and 640 relations with 0 broken and the same 72 unavoidable dissent votes in 60 pairs, none of them naming a node this step wrote; and the payload set `3275a907…`/`df3d59c9…`/`8f3ac2bd…` is archived in `work/out/p2-4.93`, which leaves the 4.74 control in `work/out/p2-variants` intact for a **seventeenth** step. It also corrects five comments its own landing falsified: the two SMMU paragraphs and the QUP/UART paragraph that said PEP0 was absent and the entries therefore un-writable, and the `UCS0` paragraph that reserved the very `_DEP` line this step wrote — and the SMMU count was wrong besides, `_DEP` is `{PEP0}` in 31 of the 40 nodes and `{MMU1}` in the other 9 where the file said all 40, so that entry now waits on a split rather than on a missing node and belongs to the next step with the IC, SPI, `SCM0` and UART counts. The corrections are comments only and the AML did not move: re-building from the corrected source produced the same three payload hashes, byte for byte, in `work/out/p2-4.93`. **Step 4.94** writes the seven `_DEP`s that only `PEP0` could unblock — `Name (_DEP, Package (One) { \_SB.PEP0 })` on the four QUP engines the board leaves running (`I2C8`, `I2C9`, `UAR2`, `IC11`) and on `MMU0`, `MMU1` and `SCM0` — and then re-measures every count in this file that a `_DEP` appears in, which is where it found more than it wrote. The measurement is in the repository now as `tools/acpi-dep-census.py` rather than in a throwaway script, because all three of the step's findings are findings about the *reading*. (a) The corpus contains this table: `tools/sync-uefi-platform.sh` installs ours into the `Silicium-ACPI` tree, so `Platforms/Xiaomi/gauguin/DSDT.aml` is one of the 66, and a census of the family that includes the file being written is not a census — the tool drops it by default and `--keep-self` prints the other framing, whose difference *is* this table's own contribution, **I2C/IC 55 nodes and 43 `{PEP0}` → 58 and 46, UART 34 and 31 → 35 and 32**. (b) `_DEP`'s brace is inside the declaration's own parentheses — `Name (_DEP, Package (0x01) { ... })` — so the shared `span` helper, which looks for a brace *after* them, finds none and reports every one of these nodes as carrying an empty package; the census needs a `Package (`-anchored brace matcher of its own. (c) `walk`'s `DECL` regex required exactly four characters, so it could not see any short name at all: the corpus holds **196 three-character `Device`s** (`ABD`, `CDI`, `GPS`, `GSI`, `IPA`, `LLC`, `MPA`, `QSM`, `RP1`, `SSM`, …), 150 three-character `ThermalZone`s, 79 short `Method`s and 56 short `Name`s, 19 of them two characters, **481 declarations** a `{4}` regex read as no declaration and billed to whatever enclosed them — which is why `--empty ABD` came back with zero rows and no complaint. The first five alternatives are `{1,4}` now. `Scope` and `External` keep the four-character floor, because their argument is a namespace *path* and the twelve tables that print bare `Scope (_SB)` would otherwise push a frame named `_SB` and re-parent every device in them — measured rather than assumed: the first attempt widened them too, and moved `tools/acpi-adc-blob-census.py`'s "the block is the last device of the table" reading from 21 of 21 to 20 of 21, while the four-character floor returns that census byte-identical to its pre-widening output. The widening is not a no-op either: the pair census moves on exactly two lines, both `Platforms-Xiaomi-nabu-DSDT`, where the old regex never pushed `MP0`'s frame and so billed `XMKB`, a later sibling at the same brace depth, to the `RHUB` above it. Eight comment corrections follow from the re-measurement and are recorded as corrections rather than folded in: the two `ABD`/`SCM0` paragraphs that said Waipio is "the only table in the corpus with no PEP0 anywhere in it", which is false of the corpus — **45 of the 65 reference tables declare no PEP0 device of their own, 3 of those declaring no device at all** — and true only of the family, where `--carrier ABD SCM0` reads *21 tables carry it, 20 also name PEP0, and 1 does not*; the `GIO0` entry sets, whose counts stood as "three", "three" and "one" and named `SPI1` for the shape `SPI5` carries (`{GIO0, PEP0, SPI5}` on `TSC1` in three tables, `{GIO0, PEP0, SPI1}` on surya's `TSC1` in one, `{GIO0, I2C4}` on four tables' speaker amps, `{AFT1, GIO0, IC10}` on miatoll's `SPK1`) and whose UART denominator read 38 and is 34; the prose "52 of the 53 I2C nodes and 38 of 38 UART nodes" and the table above it, which disagreed with each other *and* with the corpus, now both **43 of the 55 I2C/IC nodes and 31 of the 34 UART nodes**; and the QGP nearest-base rule, which held "in all five of its I2C nodes that name one" and is **8 I2C nodes over 5 distinct engine names in 4 tables**, with the one counterexample the step found written in — pipa's `SPI4` sits at `0x88C000` and names `QGP0` at `0x904000`, above it, while its four siblings at the same address name `QGP0` at `0x804000`. The eight families that carry no `_DEP` anywhere are re-confirmed over the 65 tables and unchanged: SPMI 22, BAM1 21, GIO0 21, RPEN 21, QGP1 21, PILC 19, QGP0 19, AGR0 20, all zero. The AML is **12,341 bytes**, `0f5df26b…`, checksum `0x42`, length `0x3035`, 742 opcodes and 515 named objects (from 12,257 at `7f171e70…`), 0 errors with 26 warnings and 93 remarks; the `DSDT` reads back out of the payload at `0x0054d4c8` for a **twenty-fourth step**, byte-identical to the direct compile, with `EFI_FV_TAKEN_SIZE 0x705750` and `FVMAIN_COMPACT`'s taken size `0x10b670`, and the `AcpiTables` file up 13,618 → 13,702 for exactly the 84 new bytes of AML; the device count stays **46** and methods stay **132**; the census is **56 declarations, 42 distinct** with the unclaimed pair unchanged at `QCOM0A8B` and `QCOM24A5`; the order vote is unmoved at **12,240 of a 12,240 ceiling** over 700 pairs and 640 relations with 0 broken; and the corrections are comments only, so re-building from the corrected source produced the same three payload hashes byte for byte — `d621f732…`/`d0de6b3d…`/`bd3b67d1…`, archived in `work/out/p2-4.94`, which leaves the 4.74 control in `work/out/p2-variants` intact for an **eighteenth** step. Thirteen of the thermal zones are described with them, and buttons now are; the rest of the thermal zones and the SPI engines are not. The thermal zones left unwritten need `_HID`s a device tree does not carry, and the reference corpus shows the id is `QCOM<family byte><block index>`. Both inputs are now known: the index is measured off the 66-table corpus, and the byte is `0A`, measured against the SC7280/Kodiak Windows driver set (8 of gauguin's 10 blocks named, 0 of 10 under every other byte) and corroborated by the only two corpus tables carrying those ids, `Xiaomi/lisa` and `Samsung/a52sxq`. Every node added since Step 4.63 answers a shipped `.inf` that names its id outright. The one block no driver names is the TSENS *controller*; the 29 thermal *zones* are a different matter and Step 4.66's census found all of their ids determined and claimed, nine of them (`QCOM04C0`–`QCOM04C8`) on family `04` under `qcthermalmdm7280.inf` rather than family `0A` under `qcpep`, which is why the family byte is the id space a block was defined in and not always the SoC. Step 4.67 then measured the other half and found the zone *data* is not missing either — `work/out/gauguin.dts` carries zones with sensor indices and trips — so what the zones still needed was the mapping from the device tree's per-zone names to the corpus's per-`_HID`-plus-`_UID` grouping, which is a join and not a search. Step 4.73 closed that join and found the names were never the join at all: it is the driver's id list, and the same-SoC table is the wrong source — see below. The count this cell carried from 4.66/4.67 was 40 zones, and the board's own tree has **92** (95 directories under `soc/thermal-zones`, three of them not zones) with **127 trip points**, every one of them `passive`. The same step took `PEP0` apart: it is a ~630-line skeleton plus one ~58-line case per thermal zone inside `THTZ`, the zero-zone form is shipped as a five-line `Return (0xFFFF)`, `THTZ` is called by nothing in any table that declares it, and `PEP0` reaches `IPCC`, `ABD`, `AGR0`, six subsystem `_STA` tests and the zones — so it cannot be ported whole — and not the 13,000-line node this tree described it as in two other places until Step 4.67 corrected both, a factor of five. Step 4.68 then finished the correction 4.66 had left half-done — `CCVL` is bound on one device in the family and was bound on three here, so the two that named the same `\_SB.CCST` unreachably went, while `PHYC` stayed on the same evidence — and found the node the Type-C path is actually missing at its root: `QCOM0A10`, the QUP I2C engine, claimed by `qci2c7280.inf` and carried by exactly two of the 66 tables, lisa and a52sxq, the same pair that settled `URS0`'s and `UCS0`'s ids. `PEP0`'s `Field (\_SB.ABD.ROP1)`, the `_DEP` `UCS0` cannot yet write, and the I2C addresses `PML0` needs all wait on it, which makes the I2C node the one item the other three converge on; gauguin's tree has the engines for it — five I2C serial engines across two `geniqup` wrappers, three of them `okay` in the device's own tree and two in the payload's, which corrects this cell's earlier count of one. Step 4.69 then answered the question 4.68 had left open and found it was two questions. The arithmetic one closes: `_UID = 8*wrapper + SE + 1` fits all 23 engine nodes in the three tables that carry any — lisa, a52sxq, the SC7280 CRD — with no exception, including the CRD's `I2C1` at `_UID One`, and the device name is the same ladder in decimal, `"I2C"` + `_UID` up to 9 and `"IC"` + `_UID` from 10, which is `I2C1`, `I2C2`, `I2C4`, `I2C5`, `I2C9`, `IC10`, `IC11`, `IC14` exactly. So `IC11` is the family's name for slot 11 and not a bus with known contents: gauguin's slot 11 is `i2c@988000`, the touch and NFC bus, reached by the same GSI `0x183` lisa's `IC11` is reached by. The wiring question is answered by gauguin's own tree, and the answer is wrapper 1 engine 4 — `i2c@990000`, the only bus in the tree carrying `fsa4480@42` (the Type-C analog switch) with `qcom,pm8008@8`/`@9`, `qcom,smb1396@34`, `bq25970-standalone@66` and `aw8624_haptic@5A`, and the only one marked `qcom,shared` with an explicit `qcom,clk-freq-out`. The engine index is measured four ways that all agree: the address stride `(0x990000 − 0x980000) / 0x4000`, the TLMM function the payload's `pinctrl-0` names (`qup14`), the `qcom,wrapper-core` phandle `0x193` that names `qcom,qupv3_1_geni_se@9c0000` outright, and the interrupt ladder — gauguin's wrapper-1 GSIs `0x181`–`0x185` are the corpus's `0x181`–`0x186` one per slot, and its wrapper-0 SE 0 is the CRD's `I2C1` at `0x279`, even though the two SoCs put the wrappers at different addresses (wrapper 1: gauguin `0x980000`, the CRD and a52sxq `0xA80000`; wrapper 0: gauguin `0x880000`, the CRD `0x980000`), which is the ids' own lesson a second time — the slot travels between SoCs and the address does not. The node written is **`IC13` at `QCOM0A10`**, slot 13, `_UID 0x0D`, `0x990000 + 0x4000`, INTID `0x185`; `_DEP` is omitted as on `UCS0` because every I2C node in the family depends on `\_SB.PEP0` and this table has none, and the `,Shared` suffix is omitted because lisa's only one is on `I2C2` while lisa's own charger engine `IC11` has none. The AML is now **2,465 bytes**, `b9e70ee6…65a3df6`, and the delta is exactly the node: disassembling the old and new tables and diffing them gives `IC13` and nothing else, and `SSDT`, `APIC`, `FACP`, `FACS` and `GTDT` are byte-identical sha256 for sha256 between the two payloads. Step 4.70 then finished the engines and corrected this cell's own count — it said five engines at I2C addresses with three `okay`, and the number that matters is not the node count but the enabled one: the board leaves **six** QUP engines running, three I2C, two SPI and one UART, read off the `status` of every node at a QUP address in the tree dumped from the running kernel — `0x880000` SPI with `touch_spi@0`, `0x884000` the 4-wire UART the console runs on, `0x984000` I2C with two `cs35l41`, `0x988000` I2C with `focaltech@38` and `nq@28`, `0x98c000` SPI with `irled@0`, `0x990000` I2C with the charger cluster. The two that were missed were missed because the payload's tree disagrees with the board's about exactly those two addresses (`i2c@880000` against `spi@880000`, `serial@98c000` against `spi@98c000`), and the board wins for the same reason it won the last two times. Three nodes are written — **`IC10`** (`QCOM0A10`, `_UID 0x0A`, `0x984000`, INTID `0x182`), **`IC11`** (`QCOM0A10`, `_UID 0x0B`, `0x988000`, INTID `0x183`) and **`UARD`** (`QCOM0A16`, `_UID 0x02`, `0x884000`, INTID `0x27A`) — which brings the table to 22 devices and every one of gauguin's six live engines under a node. The two SPI engines are withheld and the reason is one search, not a preference: `QCOM0A0E` is claimed by no `.inf` in any of the five driver trees on this host, where `QCOM0A0B`/`QCOM0A0C`/`QCOM0A10`/`QCOM0A16` are each claimed outright, so `SP1` and `SP12` would register two unknown devices reserving memory and GSIs against no driver — withheld, not refused, since lisa declares an `SP14` and the node is four lines the day a driver appears. That is why this cell's "the I2C engines" is now stated as a count of engines and not a count of buses: the buses are all described and what is missing from them is the drivers. Three more things moved from the corpus to the board. The GSIs: a device-tree interrupt specifier `<0 N 4>` names GIC INTID `N + 32`, ACPI's GSI is that INTID, and all six of gauguin's `interrupts` values convert to exactly the ladder the corpus shows — `0x259 + 32 = 0x279`, the CRD's `I2C1`, included — so the ladder is now measured twice from two directions. The protocols: each engine's is the TLMM group its `pinctrl-0` resolves to (`se0_spi`, `se1_4uart`, `se2_i2c`/`se2_spi`, `se6_i2c`/`se6_spi`, `se7_2uart`/`se7_i2c`, `se8_i2c`, `se9_2uart`/`se9_spi`, `se10_i2c`), and the `se` index in those names is a **fourth** index convention distinct from the slot, the address and the `_STR`: `se0`–`se5` are wrapper 0 and wrapper 1 starts at `se6`, so `se7` is wrapper 1's engine 1 and not engine 7. And the naming ladder has one exception, which venus settles: the debug UART is called `UARD` at any slot and its slot lives only in `_UID` — lisa `_UID 6`, venus `_UID 4` with `_STR "QUP_0_SE_3,DBG"` — which is why Step 4.69 read gauguin's engine at `0x884000` as `UARD` `_UID 2` and not `UAR2` — a reading Step 4.86 corrected, that engine being the four-wire port this board leaves enabled while its console is elsewhere, so the node is `UAR2` and `8 * 0 + 1 + 1 = 2` is the number its name carries. The touch question 4.69 left open closes the opposite way from the node names: `spi@880000`'s `touch_spi@0` carries a `compatible`, a `reg` and a clock and nothing else, while `focaltech@38` on `i2c@988000` carries the interrupt, the reset, the supply, six panel phandles and `max-touch-number 5`, and `qcom,i2c-touch-active = "focaltech,fts_ts"` marks the I2C path active — so slot 11 is the touch's bus, which is the same slot lisa's `IC11` reaches by the same GSI `0x183`, and the node names were never evidence. That bus's driver set is empty in both directions, which makes `IC11` the prerequisite and not the feature. The AML is now **2,833 bytes**, `a98c1a98095f77e2a1dde01cefe99b9a91ae6af1926f7fed5053353581f5af5b` with checksum valid, the delta is exactly the three nodes (72 added disassembly lines, 3 × 24, 0 changed, 0 removed; 19 devices to 22), `SSDT`, `APIC`, `FACP`, `FACS` and `GTDT` are byte-identical to 4.69's again, the devices whose id a driver in the set claims went 6 → **9** of 22, and the same two — `QCOM0A8B` (`URS0`) and `QCOM24A5` (`UFS0`) — remain unclaimed. Step 4.71 then wrote the two controllers every live engine above is not self-driving without — **`QGP0` and `QGP1`, `QCOM0A88`, `_UID Zero`/`One`, windows `0x00804000 + 0x50000` and `0x00904000 + 0x50000`, GSIs `0x114`/`0x115` and `0x2A5`/`0x2A6`** — which is the pair this cell had listed first among the measured-but-unwritten. The pairing is stated twice and independently: in the board's `dmas`, where each of the five live engines names its **own wrapper's** controller (`0x186` is `qcom,gpi-dma@800000`, `0x190` is `qcom,gpi-dma@900000`, and none crosses over), and in the corpus's `_DEP`, where three engines per table name a `QGP`. A `dmas` specifier turns out to be six entries — `<phandle, tx/rx, SE index, code, 0x40, 0>` — and its second cell is the SE index in all five, a further measurement of the numbering the `IC` nodes were built on, from a property that had no part in deriving it, while its third is constant per protocol (1 on the two SPI engines, 3 on the three I2C engines) and is recorded rather than decoded. The corpus's own clearest proof of the rule this table has run on since 4.70 comes out of the same pair of tables: lisa's `SP14` and a52sxq's `IC14` are the same engine — same address, same `_UID 0x0E`, same `_STR "QUP_1_SE_5"`, same `INTID 0x186`, same `_DEP` — and differ in exactly two lines, the `_HID` (`QCOM0A0E` against `QCOM0A10`) and the name; so **the slot identifies the engine and the board identifies the protocol**, which is why gauguin's two withheld SPI engines would be `SP1` and `SP12`, and why lisa can run an SPI engine where a52sxq runs an I2C one at the identical slot. The id is broad rather than a pair for once: 20 of the 66 tables declare a `QGP` under nine distinct ids, the same block is indexed `88` in five families (09, 0A, 0C, 1A, 25), `93` in three and `F4` in one, so the index is a property of the generation and `0A` sits in the `88` group — and `qcgpi7280.inf` claims it outright. The window is a derivation and not a copy: the corpus's `_CRS` is the board's region less its first `0x4000`, `0x50000` long on lisa and on a52sxq alike, and both of gauguin's regions are `0x60000` under the reg-name `"gpi-top"` that says the skipped block is there — the second time this cell has been able to derive a family number rather than copy one. **The interrupts are the one place in the step where copying the corpus would have been wrong**: both boards declare ten lines and `qcom,max-num-gpii = 10`, the family declares two, and at wrapper 0 the family's two are gauguin's first two to the digit (`0x114`, `0x115`) while at wrapper 1 the family's `0x137`/`0x138` sit 374 from gauguin's `0x2A5`/`0x2A6`; the count transfers and the numbers do not, and nothing here explains the split. Neither node carries a `_DEP`: the family's own `QGP` nodes have none, the dependency runs engine-to-controller, and all three of the family's shapes for an engine `_DEP` begin with `PEP0`, which this table still does not have, while a one-entry `_DEP` is a shape no family table carries. The AML is now **3,027 bytes**, `fd760ef74f093d5d65d7959702f668af26f2f09daf9cb32af1f92cd6385939f3`, checksum `0xCC`, the delta is exactly the two nodes (3 changed header lines, 57 added, 0 removed; 22 devices to 24), `SSDT`, `APIC`, `FACP`, `FACS` and `GTDT` are byte-identical to 4.70's a third time, and the claim count is now **11 of 24**. Step 4.72 then reversed the negative result 4.71 left behind and wrote the node it had recorded as unbuildable: both SMMUs are derivable and both are now in the table — **`MMU0` (`QCOM0A09`, `_UID Zero`, `0x15000000 + 0x100000`, 81 interrupts in five runs `0x61`, `0x7F`–`0x96`, `0xD5`–`0xE0`, `0x15B`–`0x179`, `0x1B1`–`0x1BD`) and `MMU1` (`QCOM0A09`, `_UID One`, `0x03D40000 + 0x00020000`, ten interrupts `0x105`, `0x107`, `0x18C`–`0x193`)** — which unblocks the other half of every engine `_DEP` that names a GPI DMA. The pair is the first in this table whose *form*, meaning which resources go on which of two nodes sharing one id, came out of a driver's record of two instances rather than a sibling table's single one: `qcsmmu7280.inf` claims `ACPI\QCOM0A09` once and hangs two per-instance registry sets off it, `Parameters\0` with its context-bank page at `0x80` pages and `MDP`/`VFE`/`VIDEO` as its `PREFETCHDETAILS` clients and `Parameters\1` with its CB page at `0x10` pages and **`GPU`** as its only client — the file's own comment calls the second "GFX MMU version specific settings" — so instance 1 is the GPU's SMMU and the board's two IOMMU blocks identify themselves three ways over (`apps-smmu@15000000` and `arm,smmu-kgsl@3d40000` in the vendor tree, the same two as `qcom,sm6350-smmu-500` and `qcom,sm6350-smmu-v2` with **`qcom,adreno-smmu`** in the payload's kernel tree, and the driver's client lists). The corpus agrees about the id and supplies neither: 20 of 66 tables carry the pair, all with `_UID Zero`/`One` under the same one id, and no table declares a second id for a second SMMU. `MMU0`'s window is the board's rather than the family's for once — `0x15000000 + `0x100000` is the one SMMU window in the family that does not move with the SoC (17 of the 20) — and its 81 interrupts are `#global-interrupts = 1` plus 80 context banks, the count the board's and the ladder's shape the family's without conflict: the runs opening at `0xD5` and `0x15B` are in all 20 tables, lisa's `0xD5`–`0xE0` and `0x15B`–`0x178` sit inside gauguin's to the digit, and lisa's own count is 65 against this board's 81, across a corpus that declares 43, 57, 58, 63, 65 or 71. `MMU1`'s base is the board's and its **length is the driver's**: the board's `0x10000` is a register footprint (`attach-impl-defs` reaches `0x6b68`, the page instance 1 calls implementation defined 1 at `0x06` pages) and the instance-1 context-bank page at `0x10` pages lands exactly where a `0x10000` window ends, so the node takes the `0x20000` the family gives the same node, also the largest power of two that stops short of the GPU's region at `0x3d61000` — the first time in this file that a driver's page arithmetic rather than a sibling `_CRS` has settled a window length. `MMU1`'s eight context-bank GSIs `0x18C`–`0x193` are another family's group (`QCOM0212`/`QCOM0809`/`QCOM1409`, and a52q, miatoll, surya) while gauguin's peers lisa and a52sxq use `0x2C6`–`0x2CF`, the same kind of split the GPI DMA showed at wrapper 1, with the board's own ladder backing the eight: they lie between `MMU0`'s third run, ending at `0x179`, and its fourth, opening at `0x1B1`. **The trigger is the one place in this file where the corpus disagrees with the board**: all 1400 SMMU descriptors in the corpus are `Edge, ActiveHigh, Exclusive` and all 91 of gauguin's specifiers carry type cell 4, level, which is what the kernel programs those GIC lines with — the corpus is faithful elsewhere (its `UFS0` and `QGP0` are Level, matching the board's cells), so the disagreement is specific and is recorded rather than resolved. Three things every corpus SMMU carries are deliberately absent: the `_DEP {PEP0}` (40 of 40 nodes, and a one-entry `_DEP` is a shape no table has), `_STA` (absent from 19 of 20 `MMU0`s and 9 of 20 `MMU1`s; the ones returning `Zero` hide an SMMU rather than describe one), and `Alias (\_SB.SVMJ, _HRV)` — `SVMJ` is a single `Name (SVMJ, 0xFFFF)` under `\_SB` and this table has none. The AML is now **3,997 bytes**, `47d7dc0acda977e79b48aa9c1d4efc64020704045302a6c048f3ea26bbf1545e`, checksum `0xBC`, the delta is exactly the two nodes (2 changed header lines, 400 added, 0 removed; 24 devices to 26; 196/181 opcodes and named objects to 198/193), `SSDT`, `APIC`, `FACP`, `FACS` and `GTDT` are byte-identical a fourth time, and the claim count is now **13 of 26**. Step 4.73 then wrote the first thirteen thermal zones — **`TZ0`–`TZ7`, `TZ9`–`TZ13`, ids `QCOM0A58`/`0A59`/`0AD4` as two `_UID` instances each plus `0A91`, `0A51`, `0A4C`, `0A92`, `0ABF`, `0A4B`, `0A57`** — and closed the join 4.66 and 4.67 left open, by finding that it was never a name correspondence: the zones are joined by the **driver's id list**, and the driver is `qcpep.wd7280.inf`, which accepts `0A17`, `0A37`–`0A51`, `0A57`–`0A64`, `0A91`, `0A92`, `0ABF`, `0AC8`–`0ACB`, `0AD4` and `0AD8`–`0AE0` — the family `Xiaomi/lisa` and `Samsung/a52sxq` write and no other table does. The same-SoC table, `Samsung/a52q`, writes family `08` (`084B`, `084F`, `085C`–`085F`, `0862`, `0863`, `0865`, `0867`, `089D`, `089E`) and **no `.inf` in any of the five driver trees on this host claims one of those**, so a52q is the wrong source here for exactly the reason it was the right one in earlier steps: the id family is the driver set's, not the silicon's, which is the third time this file has learned that (4.71's GPI DMA, 4.72's SMMU). The id-per-instance pattern is the third appearance too — `0A58`, `0A59` and `0AD4` each carry `_UID Zero` and `One` in all 20 tables that have them — so a zone is named for the sensor *block* and not the sensor, and the corpus's `TZ<n>` labels (which skip 8 and 14) are kept as provenance rather than treated as identities. **A temperature is where this step deviates from its source, deliberately and once**: `_PSV` is written only where this board has a trip to cite, and the encoding both sides use is `(C + 273) * 10`, which makes the comparison possible — `0x0E60` = 95 C matches `gpu-trip0` and `npu-trip0` on `TZ6` and `TZ10`; `0x0F28` = 115 C is lisa's PMIC `_CRT` and also gauguin's `reset-mon-cfg`, so `_CRT` is written on all thirteen where lisa writes it only on the PMIC group; and the three `_UID One` zones take **`0x0EF6` = 110 C** from the board's `cpuNN-config` rather than lisa's `0x0EC4` = 105 C, because a passive trip is a thermal-design decision and gauguin's tree has no 105 C trip anywhere. The same rule drops `QCOM0ABF`'s `_PSV`, which lisa sets to `0x0EC4`: nothing here names that block, so there is no measurement to cite. `_TZD` is not written (lisa's lists `\_SB.GPU0` and `\_SB.PEP0`, neither of which this table has) and neither is `_DEP`, which is `{PEP0}` alone on all but the PMIC group and a one-entry `_DEP` is a shape no table has. **The step also caught a mistake that compiled cleanly**: the first build wrote the zones as `Device (TZ0)`, which reported `0 Errors` and the same size, opcode count and object count as the correct form — ASL's `ThermalZone` is not sugar for `Device` but AML's `ThermalZoneOp`, `0x5B 0x85` against `DeviceOp`'s `0x5B 0x82`, a different opcode of identical length, so the only instrument that showed it was the disassembler. The AML is now **5,210 bytes**, `ff492bef347825a846b03469a15fce2679ecdfe85003e1bf35f2845e79c1d639`, 237 opcodes and 326 named objects, 26 devices to 39, `SSDT`/`APIC`/`FACP`/`FACS`/`GTDT` byte-identical a fifth time, and the claim count is **23 of 25 distinct ids**. Four groups are absent and each needs a device this table has not got: the PMIC group (`0AC8`/`0AC9`/`0ACB`, the only one with a two-entry `_DEP`, a `_DSM` and a `GpioInt` `_CRS` on `\_SB.PM01` pin `0x00C0`), the ADC group (`0A5F`/`0A61`/`0A63`, `_DEP` on `ADC1`), `TZ99` (`0A5A`, whose `_TZD` names five absent containers) and the modem's nine `04C0`–`04C8` under `qcthermalmdm7280.inf`. **The space looked like the binding constraint and is not**: this step first read `FVMAIN`'s 1,160 bytes free of `0x704000` as a cap, which would have meant the PMIC group's three nodes did not fit. `[FV.FvMain]` declares `NumBlocks = 0` with `BlockSize = 0x1000`, so GenFv sizes the volume to content and rounds up to the next block — the free space is that rounding's slack, not headroom in a fixed region. A throwaway ~4 KB probe built a `0x705000` volume, one block larger with the same slack; removing it restored the same `FVMAIN.Fv` hash the payloads came from. The real cap is `FVMAIN_COMPACT`'s fixed `0x300000`, at 1,089,206 used and **2,056,522 free**, and this step measured the shrink at 0.22 (271 compact bytes per 1,216 of `FVMAIN`), which is on the order of 9 MB of headroom. The four zone groups stay withheld because each needs a device this table has not got, not for space. Step 4.74 then wrote the node `PEP0`'s own `_DEP` names — **`IPCC` at `QCOM06C2`, `_UID Zero`, `Alias (^PSUB, _SUB)`, one interrupt at GSI `0x104`, `Level, ActiveHigh`** — the first link of the chain every remaining `_DEP` in the family begins with, and the first node in this file whose source question was settled by a **provable collision** rather than by the board-wins rule. The board gives it whole (`mailbox@408000`, `"qcom,sm6350-ipcc"`/`"qcom,ipcc"`, `reg` `0x408000 + 0x1000`, `interrupts = <0 0xe4 4>` → INTID `0x104`). The corpus's 12 IPCCs use three ids, and only `QCOM06C2` (7 tables, including lisa and a52sxq) is reachable — `qcipcc7280.inf` claims it outright and claims no other IPCC id. All 12 write the triple `0x105`, `0x106`, `0x107`, which **cannot be this board's: Step 4.72 measured this board's GPU SMMU on `0x105` and `0x107`**, so copying the corpus would give two devices the same two GIC lines. `0x2EA` is in one variant and not the other, so it is a leaf. And the trigger is `Edge` in the `QCOM06C2` variant against `Level` in the `QCOM1AC2` one — **the corpus splits, so it is evidence about nothing**, and the board's type cell 4 breaks the tie; that is a different case from 4.72's, where the corpus was unanimous and the board the lone dissent. No `_DEP` is written, not because of the one-entry rule but because no corpus IPCC has one and the dependency runs the other way: `PEP0`'s `_DEP` is `Package (One) { \_SB.IPCC }`, so this node is what that resolves to, and `PEP0` now has one fewer unresolved reference. Recorded for `PEP0` itself: its `_SUB` branches on `\_SB.PSUB` against `"IDP07280"`/`"CRD07280"` with no `Else` and no trailing `Return`, and gauguin's `PSUB` is `"MTP07225"`, so on this table it has no branch to take — a defect in the method, not in the value. The AML is **5,280 bytes**, `41ed014369c3d79eef4b267646e26f1e8986ef2d5d1ec126359332b26f93f52e`, 238 opcodes, 332 named objects, 39 devices to 40, `SSDT`/`APIC`/`FACP`/`FACS`/`GTDT` byte-identical a sixth time, and the claim count is **24 of 26 distinct ids**. Two things are still measured and are not written: `FSA04480`, the Type-C analog switch (3 of 66 tables, alioth/venus/pipa, no `.inf` in the set claims it; gauguin's `fsa4480@42` is at exactly the `0x42` the corpus gives and is `disabled` in the vendor's board file — which is the vendor's switch, not the charger). And `AGR0` is `ACPI000C`, a standard Processor Aggregator Device with no vendor id, no `_CRS` and no driver, so PEP0's `NPUR` dependency is a five-line node rather than a census; the other two, `IPCC` and `ABD`, are unchanged. Step 4.75 then wrote the second of the two nodes `PEP0`'s own text names — **`ABD` at `QCOM0427`, `_UID Zero`, `Alias (^PSUB, _SUB)`, an `OperationRegion (ROP1, GenericSerialBus, Zero, 0x0100)`, `Name (AVBL, Zero)`, a `_REG` that sets `AVBL` when `Arg0 == 0x09` and an `_STA` returning `0x0F`** — which closes the last reference the two written nodes still owed each other: `PEP0`'s `_DEP` is `Package (One) { \_SB.IPCC }` and `PEP0`'s single `Field` is on `\_SB.ABD.ROP1`, so `IPCC`'s node resolves the first and this one resolves the second. The driver says what it is rather than the name: `qcabd.inf` calls the device a **"Qualcomm(R) ACPI Bridge Device"**, KMDF 1.33, class System, `SERVICE_DEMAND_START`, and claims `ACPI\QCOM0427`. **The id's family byte is authored and not silicon**, which is why this step needed the driver rather than the SoC: 21 corpus tables carry an ABD and split four ways — 12 × `QCOM0427`, 5 × `QCOM0527`, 1 × `QCOM1427` (surya), 1 × `QCOM0242` (caymanslm) — and the split does not follow the platform, because venus and vili are SM8350 and write `0527` while Lahaina is SM8350 and writes `0427`. `0427` is taken because the set claims it and nothing else, the same rule the I2C, GPI DMA, SMMU and IPCC nodes were built on, and for the first time the rule and the majority vote agree rather than diverge. The shape is identical in 19 of the 21, and the two exceptions are the two this file has met before: vili adds an `_STA` returning `0x0F`, and Waipio replaces the `_SUB` `Alias` with a method, drops `_DEP` and adds `_STA`. **The `_DEP` is withheld because `PEP0` is absent, and Waipio is the exception that proves the rule by being both halves at once**: it is the only table in the corpus with no `PEP0` anywhere, and its ABD is the only one of the 21 with no `_DEP`. `_STA` is written because both corpus tables that carry one return `0x0F` and the nineteen that omit it are present by ACPI default, so writing it costs a method and removes an ambiguity. No `_CRS`, because none of the 21 has one. **The step also falsified a sentence this file has been repeating**: the SMMU comment says "a one-entry `_DEP` is a shape no table has", which was true of the tables it had read and is false — ABD's `_DEP` is one entry in 19 tables and `PRTC`'s is one entry naming `\_SB.PMAP`. The rule lands in the same place (the `_DEP` stays unwritten) but the reason is not the size: what makes an entry un-writable is that it names a node the table has not got, and `\_SB.PEP0` is such a node one step further out. The correction is recorded in the ABD comment; the SMMU comment still carries the old wording and is owed an edit. The region this node declares is what the rest of the family reads its zero-configuration data out of, and the corpus's `Field` declarations give it a channel map worth keeping: `0x0001` `PEP0`, `AttribRawBytes (0x15)`, 168 bytes; `0x0002` `PRTC`, `AttribRawBytes (0x18)`, 192 bytes — the standard Time and Alarm Device's RTC, so this node is also what `PRTC` is waiting on; `0x0003` and `0x0004` both `PMGK`, `AttribRawBytes (0x30)` and `(0x40)`, the second only on Kailua and Waipio. Kailua is the one table that writes `0x1A` for `PEP0`'s channel where the other twenty write `0x01`, and nothing in the step explains the divergence, so it is recorded rather than resolved. `AVBL`'s readers are the family's cameras, `TSC1` and `NFCD`, and the cameras are one of the two things this port cannot drive at all, which is what makes this a node written for `PEP0` and not for `ABD`. The AML is now **5,364 bytes**, `efb48f9ffc6f4a5909eadd866e1afc92f76d74cdc5b6ee1ff353992214f6b74a`, 242 opcodes, 340 named objects, 40 devices to 41, `SSDT`/`APIC`/`FACP`/`FACS`/`GTDT` byte-identical a seventh time, and the claim count is **25 of 27 distinct ids**. The 4.75 payload set is `b9948a03…` (silicon/gzip), `40f0a769…` (stock/gzip) and `0792c2e1…` (stock/none), all three matching GenFv's map at 123 offsets and GUIDs with zero mismatches, and reading the DSDT back out of one of them gives the same 5,364 bytes and the same hash as the compile. Step 4.76 then wrote the third of `PMAP`'s three `_DEP` entries — **`SCM0` at `QCOM04DD`, `_UID Zero`, `Alias (^PSUB, _SUB)`, `_STA` returning `0x0F`** — which is the last of them: `PMIC` is Step 4.63's, `ABD` is 4.75's, and until this node lands a `_DEP` for `PMAP` has an entry it cannot write in a table with no `PEP0`, so this is the node that makes the whole `PMAP` → `PRTC` subtree reachable. It is also broader than `PMAP`: across the corpus `\_SB.SCM0` is named by `PMAP` in 20 tables, `MON0` in 19 and `ARPC` in 19, plus `NSPM` twice and `VFE0` twice, which is what makes it a hub rather than a leaf and the reason to write it now. `qcscm.inf` names it for itself — "Qualcomm(R) System Manager SCM Device", class SYSTEM, a kernel-mode service at `SERVICE_SYSTEM_START`, `LoadOrderGroup "Extended Base"`, shipping `qcscm.sys` and `SCMF.bin`, KMDF 1.33, `PnpLockDown = 1` — and binds `ACPI\QCOM04DD` and nothing else. **The id is where this step differs from every one before it, and the difference is that the corpus's own spread becomes the argument.** The corpus gives this single device six ids across 21 declarations: `QCOM04DD` in 9 tables, `QCOM050B` in 5, `QCOM05DD` in 3, `QCOM080B` in 2, and `QCOM0214` and `QCOM140B` in 1 each. Exactly one of the six is claimed by any `.inf` in the five driver trees on this host. So this is no longer "the driver set agrees with the corpus majority" — the majority is only 9 of 21 and five of the six ids have no driver at all, which means the corpus's spread is not a vote to be counted but a reason the driver's answer is the only answer available. The same-SoC table is the sharpest part of it and it is a repeat: **a52q, SM7225, writes `QCOM080B`, and `QCOM080B` is one of the five that nothing claims** — Step 4.73's family-08 finding, on the same table, for a different device. `QCOM04DD` is also exclusive: nine occurrences in the corpus and every one of them is `SCM0`, so no two nodes share it. The shape is `ABD`'s shape and the pair of exceptions reappears in the same table: eight of the nine `QCOM04DD` tables are byte-identical, and Waipio is the ninth, differing the same two ways it differs on `ABD` — no `_DEP` at all, and `_SUB` as a method returning `\_SB.PSUB` — and it is still the only table in the corpus with no `PEP0`. The `_DEP` is withheld, and here the corpus leaves it more open than it did one step earlier: across the 21 declarations the dependency is present in 11 and absent in 10, and split by its referent the implication holds in all 21 — every table naming `\_SB.PEP0` has a `PEP0`, and the one table without a `PEP0` is the one without a `_DEP` — but 11 of the 20 tables that do have a `PEP0` still omit it, so this is the first node where the corpus would leave the choice genuinely open on a board that had one. That does not change this table's answer, because the entry would name a device gauguin has not got; it changes how the answer is recorded, as a fact about the referent rather than about what the family does. No `_CRS`, and here the absence is a fact about the device and not about the corpus: none of the 21 has one and **gauguin's own tree carries nothing to build one from** — `scm { compatible = "qcom,scm-sm6350", "qcom,scm"; #reset-cells = <1>; }`, with no `reg` and no `interrupts`, because the SCM is a secure-monitor call interface and not an MMIO block — and the node is in the SoC dtsi rather than the board file, so it is a property of every SM6350/SM7225 board and gauguin inherits it unchanged. The AML is now **5,411 bytes**, `7ec0c8c1b28723288afdc3a8574139181c180cb1a317feda2f7ac761472c4713`, 243 opcodes, 345 named objects, 41 devices to 42, `SSDT`/`APIC`/`FACP`/`FACS`/`GTDT` byte-identical an eighth time, `FVMAIN` still `0x704000`, and the claim count is **26 of 28 distinct ids** with the same two — `QCOM0A8B` (`URS0`) and `QCOM24A5` (`UFS0`) — unclaimed. The three payloads are `dcf4b1d5…` (silicon/gzip), `3152a8ec…` (stock/gzip) and `681a7d9c…` (stock/none), all three matching GenFv's map at 123 offsets and GUIDs with zero mismatches, all three returning rc=0 from `probe-fingerprint.py --expect P2FreeWhy`, and the archive directory is `work/out/p2-4.76`; `work/out/p2-variants` still holds the 4.74 set because `P2DIR` was set, so the 4.74 control survives in two places. Step 4.77 then wrote `PMAP`, the PMIC Apps device `QcPmicApps7280.inf` binds — **`QCOM0A2C`**, `Alias (^PSUB, _SUB)`, `_STA 0x0F`, and the corpus's two-byte empty `_CRS` — and it is the first node in this table whose `_DEP` is written complete rather than withheld: `{\_SB.PMIC, \_SB.ABD, \_SB.SCM0}`, identical in all 20 corpus declarations, with all three referents now present, which is the inverse of Steps 4.75 and 4.76 where the entry named a device the table had not got. It is also the first node where the two witnesses agree instead of one carrying the decision alone: `QCOM0A2C` is family `0A`, gauguin's own family, written by the `lisa`/`a52sxq` pair every other PMIC-family decision came from, **and** it is the one id of the node's nine corpus ids that the shipped driver set claims. That claim check is stronger than the two before it: all 112 `.inf` files were extracted from the 112 `.cab` files of the 7280 set and every id grepped against all of them, which re-derives `QCOM04DD → qcscm.inf` and `QCOM0427 → qcabd.inf` by the same route and confirms both earlier steps rather than repeating them. The node sits where the corpus puts it — immediately after `PM01` in all 20 tables, the first *positional* rule this file has been able to read off the corpus, and the reason it is not adjacent to the `ABD` and `SCM0` it depends on. It carries `GEPT`, and that method belongs to three nodes and not to this one: `PEP0`'s returns `One` (20 declarations), `PMGK`'s `0x03` (10 of 11, Waipio's being a buffer-returning variant), and both of those nodes are still absent, so PMAP's is the only one of the three writable today. Nothing in any table calls `GEPT`, and **the driver-binary string test that resolved `OFNI` on `GIO0` fails here and is recorded as failing**: `qcpmicapps7280.sys` has no standalone four-character name run — `RSDS`, `PAGE`, `NULL`, `INIT`, `GCTL`, `DITM`, with `GCTL` also in `qcgpio.sys`, which is what a shared compiler artefact looks like — `GEPT` occurs only inside the eight-byte run `AeiBGEPT`, and `qcabd.sys` carries `AeiBSSID` while `SSID` names nothing in any of the 66 tables, so the inference is dropped in both directions rather than asserted in one. `_STA` writes `0x0F`; the three corpus tables that write `0x0B`, hiding the device from Device Manager while still starting it, are `a52q`, `miatoll` and `surya` — families `08`, `08`, `14`, none of them gauguin's. `_CRS` is the empty two-byte `0x79 0x00` 18 of 20 write; the exception is `caymanslm`, whose `GpioInt` sits on `\_SB.PM01` pin `0x01C0`, and gauguin's only PMIC interrupt is the SPMI arbiter's own PDC pin 1 already in `PM01`'s `_CRS`, so there is nothing here to cite. The AML is now **5,545 bytes**, `5c7e20e28ca9cfb766a7f05c4c76f691d5f9af70ea46363ecaefb234ce954626`, 247 opcodes, 356 named objects, 42 devices to 43, 0 errors, `SSDT`/`APIC`/`FACP`/`FACS`/`GTDT` byte-identical a ninth time, `FVMAIN` still `0x704000` at sha256 `94e89dd1…`, `FVMAIN_COMPACT` at 1,093,352 of `0x300000`, and the claim count is **27 of 29 distinct ids** with the same two — `QCOM0A8B` (`URS0`) and `QCOM24A5` (`UFS0`) — unclaimed. The three payloads are `8fb44bb0…`, `9ca7b05b…` and `23ce3d5f…`, GenFv-clean at 123 offsets and GUIDs, archived in `work/out/p2-4.77`, which leaves the 4.74 control in `work/out/p2-variants` intact for a third step. What it unblocks is `PRTC`, the Time and Alarm Device, and Step 4.78 wrote it. All 20 corpus `PRTC`s carry `ACPI000E` and one `_DEP` naming `\_SB.PMAP` — 19 as a string, one as a path — so the entry is writable, and the node is the first in this table whose `_HID` is not a QCOM id: `ACPI000E` is the OS-supplied Time and Alarm Device class id, **not one of the 158 ACPI ids in the shipped driver set** — 0 of the 112 `.inf` files mention it — so on this one node the entire id-family rule that has carried since Step 4.63 has nothing to say, and the decision was made on shape instead. The string-versus-path question was settled by counting rather than by taste: inside `PRTC` the string form wins 19 to 1, and corpus-wide the 66 tables hold **1,416 `_DEP` packages with 3,058 entries**, of which **3,039 are name references** (3,038 absolute, plus `alioth`'s relative `I2C9`) and **19 are strings**, those 19 being exactly one per table and all of them on `PRTC`. Counting the corpus inverts the local vote and the path form is what is written. The node carries no `_UID` and no `_CRS`, `_STA` returns `0x0F` (`a52q`/`miatoll`/`surya` again the three that write `0x0B`), and `_GCP` returns `0x04` with the decode recorded **open** rather than guessed: `_GWS`/`_STW`/`_STV`, the alarm half of the Time and Alarm Device interface, appear in **0 of the 66 tables**, so nothing in the corpus can be advertising an alarm. `_GRT` builds a 26-byte local with `TME1` at bit `0x10` and returns it; `_SRT` builds a 50-byte local, writes time and clears `ACT1`/`ACW1`, and does `BUFF = FLD0 = BUFF`, returning `One` if the `STAT` byte changed — a write-then-readback, not a blind write. Its `Field` sits on `\_SB.ABD.ROP1`, which is why `ABD` exists, and that forced the step's one structural change: a `Field` cannot reference an `OperationRegion` declared later, so iasl refused the first build with `Error 6142 - Illegal forward reference (\_SB.ABD.ROP1)`, and the whole 131-line `ABD` block was moved from its old slot between `MMU1` and `SCM0` to its corpus position immediately before `PMIC`. That position is independently measured — `ABD` immediately precedes `PMIC` in **21 of 21** tables and is preceded by `SDC2` in 18 and `UFS0` in 3, which is ordinal 2–5 in every table, and this file has no `SDC1`/`SDC2`, so its slot is between `SPMI` and `PMIC`. The `ROP1` channel/field inventory was re-measured during this step and corrected two inherited errors: **all 53 fields** are `0x0001` `PEP0` `AttribRawBytes (0x15)` `FLD0` 168 bits (18 tables), `0x0001` `PEP0` `AttribRawBytes (0x1A)` **`FLD1` 40 bits** (the two `Kailua` tables — a different field, not a mis-sized one), `0x0002` `PRTC` `AttribRawBytes (0x18)` `FLD0` 192 bits (19), `0x0003` `PMGK` `AttribRawBytes (0x30)` **`UCSI`** 384 bits (11) and `0x0004` `PMGK` `AttribRawBytes (0x40)` **`GOEM`** 512 bits (two `Kailua` plus `Waipio`) — the field name being the client's own, which is why `PMGK`'s two are not `FLD0`/`FLD1`. `caymanslm`'s `PRTC` is a *broken* declaration — no `Field`, and it reads bare `FLD0`, which resolves to `\_SB.PEP0.FLD0` and makes iasl emit `External (FLD0, IntObj)` — so the byte-identical-in-body corpus is **19 tables, not 20**, and `Waipio` is the lone variant (path form, `Name (_GCP, 0x04)` instead of a method, `_STA 0x0F` added). The AML is now **5,843 bytes**, `25c09e85445a1e4c013d3514c1974be6de7cdc22a2de64e216ff4b6b63ab1f08`, 260 opcodes, 374 named objects, 0 errors, 24 warnings, 53 remarks, 115 optimizations, checksum byte `0xf2`, length field `0x16d3`; `SSDT`/`APIC`/`FACP`/`FACS`/`GTDT` are byte-identical a **tenth** time; `FVMAIN` is still `0x704000` at sha256 `b7ea91b1…`; `FVMAIN_COMPACT` is at 1,093,512 of `0x300000`; the three payloads are `7c2f7284…`, `1ce18003…` and `7400b7a6…`, GenFv-clean at 123 offsets and GUIDs, every one carrying the full ten-instrument ladder, archived in `work/out/p2-4.78`, which leaves the 4.74 control in `work/out/p2-variants` intact for a **fourth** step. The census is now **44 declarations, 30 distinct, 28 claimed**, with `ACPI000E` counted as a standard id alongside the eight `ACPI0007` CPUs, and the same two still unclaimed — `QCOM0A8B` (`URS0`) and `QCOM24A5` (`UFS0`). Step 4.70 added a third and fourth entry to the not-written list — the two live SPI engines — and they are the only pair withheld on a driver argument rather than a data one: `QCOM0A0E` is claimed by no `.inf` in any of the five driver trees on this host, where `QCOM0A0B`, `QCOM0A0C`, `QCOM0A10` and `QCOM0A16` are each claimed outright. The UCSI chain is likewise two paths and not one: the HPD path (`Q21`/`Q22` → `Notify (\_SB.UCS0, 0xA0)`) and the firmware-event path (`INTR` → `EAPQ` → `\_SB.UBTC.QUCM ()` → `Notify (\_SB.UBTC, 0x80)`), of which the first ends on a device this table has and the second on one it does not. What none of it settles is the charger *slave*: the CRD's `IC11` `Scope` addresses a part at I2C `0x76` and nothing on gauguin's `i2c@990000` is at `0x76`, so the engine is measured and the chip is not identified. No `.inf` gates the UEFI phase. `AcpiTableUpdate` is a no-op in ours alone: all 13 sibling packages implement it, 1,188–11,685 bytes, and every one patches the DSDT and reinstalls it. The two nearest SoCs, Kodiak (SM7325) and Rennell (SM7125), write 32 named fields; even the smallest sibling writes two. So the machinery exists and what is missing is the SMEM-derived values our DSDT does not declare. Step 4.79 wrote `PML0`, the second device in the same driver package as `PMIC`, and it is the first node in this table whose *name* the driver package states rather than the corpus agreeing on it — `qcpmic7280.inf` carries `%PML0.DeviceDesc%=PMICLC_Inst,ACPI\QCOM0AD3` beside its `QCOM0A2B` entry for `PMIC`, and `[Strings]` gives the description as `Qualcomm(R) Power Management PML0` — and the first whose address set is explained by a registry default rather than by a majority: `HKR,PMICLC,"LeicaCfgBitMap",%REG_DWORD%,3` with the vendor's own comment `bit map of I2C Leica PMIC configuration 0b11, both leica 1&2 (P&Q) present` turns the corpus's three address groups — `0x08`/`0x09` in all nine tables with an I2C entry, `+0x0C`/`0x0D` in six of them, `+0x10`/`0x11` in lisa alone — into one bitmap, and lisa's `SKUV` branch is that bitmap as a namespace test. `0x08`/`0x09` is one part and not two: `drivers/mfd/qcom-pm8008.c:204` claims `client->addr + 1` outright, and the stock dtbo's gauguin entry resolves the symbols `pm8008_8` and `pm8008_9` into the sinks this tree generates as `s136`/`s137`, so the vendor's name for the PM8008's two register windows is its two addresses. gauguin's board carries one part, at `0x08`, the only child of `i2c@990000`, so it is the `0b01` case and the `_CRS` stops at the pair. The other two cells the corpus cannot supply are the board's and were read from the tree: the bus is `IC13` (`0x00990000 + 0x4000`, `_UID 0x0D`, `QUP_1_SE_4`), and the part's `reset-gpios`/`interrupts-extended` are TLMM 58/59 — which `pm8008-default-state` names — on `GIO0` (`QCOM0A0C`, `0x0F100000 + 0x300000`). The pin *order* is the one cell with no witness at all: nine tables list two pins, seven ascending and both Kailua tables descending, and lisa and a52sxq are not evidence because there the second pin appears only in the branch that also adds Leica 2's addresses. gauguin's two are `0x003A` then `0x003B`, ascending, which is also reset before interrupt. `_STA` is `0x0B` as a board answer — the corpus splits seven `Zero` to four `0x0B` across a single id, lisa and a52sxq both declaring `QCOM0AD3` — and gauguin's part is used, its thermal zone taking the node's phandle. The compile is 0 errors, 6,048 bytes of AML, 262 opcodes, 381 named objects, checksum `0x9f` with length field `0x17a0`, and the DSDT read back out of the payload at `0x54d4c8` — the same offset for a ninth step — hashes as compiled, `c663b28e…`. The device count moves 44 -> **45** and the census is **45 declarations, 31 distinct, 29 claimed**; the five shared tables are byte-identical an **eleventh** time; and the payload set `d0a845a9…`/`4b2ce72a…`/`58450c3c…` is archived in `work/out/p2-4.79`, which leaves the 4.74 control in `work/out/p2-variants` intact for a **fifth** step. Step 4.80 wrote `PILC`, the Peripheral Image Loader that brings the DSPs up, and it is the first node in this table whose id was chosen by measuring a *generation* rather than a name: the corpus declares this service group under seven ids, one per board generation — `QCOM06E0` six times, `QCOM051B` five, `QCOM1AE0` three, `QCOM04DF` two, `QCOM023B`/`QCOM14DF`/`QCOM25E0` once each — and the same seven generations stand on its six siblings `RPEN`/`SSVC`/`TFTP`/`QCDB`/`PDSR`/`SOCP`, so reading *per table* rather than per node gives 19 of the 20 carriers writing one generation across all seven nodes; and of those seven the 112 infs claim exactly one, the `06` form, `qcpil.inf` carrying `%PIL.DeviceDesc%=PIL_Device, ACPI\QCOM06E0` with `qcpilfilterext.inf` as its upper filter. So the generation is the table's and not the SoC's, the choice is forced by the installed driver set rather than by the silicon, and it retroactively explains `IPCC`'s `QCOM06C2` from Step 4.73 without licensing `06` anywhere else, since the set legitimately spans `0A` and `04` too. It is also the first device here with no `_SUB`: four of the six `06` tables omit the alias, this node's role sits *outside* any subsystem because it is what brings subsystems up, and the board's own `PSUB` is `MTP07225` where the drivers compare against `IDP07280`/`CRD07280`, so a `_SUB` here would return a string no branch can take. No `_CRS`, no `_UID` and no `_DEP` either, with `_STA 0x0F` — all four hold for every one of the 19 tables, so nothing is carried over from a minority form. Position came from nine unanimous relations that the one slot also satisfies — all nineteen put `RPEN` immediately before and `CDI` immediately after, inside a run no table splits, and `MMU0`/`MMU1`/`SCM0`/`QGP1` follow it in 19 of 19 each — with three relations the file cannot satisfy in *any* slot (`USB0`, `SPMI` and `GIO0` sit after `PILC` in 19 of 19, and this file had already placed all three earlier) recorded in the node comment rather than repaired, because a reordering would be its own measurement. The hardware evidence is the board's own device tree: three remoteprocs named `qcom,sm6350-adsp-pas`, `qcom,sm6350-mpss-pas` and `qcom,sm6350-cdsp-pas`, `pas` being the service this node drives. The AML is now **6,080 bytes**, `ae08726a…`, 263 opcodes, 384 named objects, checksum byte `0xe5`, length field `0x17c0`; the DSDT read back out of the payload at `0x54d4c8` — the same offset for a tenth step — hashes as compiled; `FVMAIN` is still `0x704000` at sha256 `f8b47e66…` with `EFI_FV_TAKEN_SIZE 0x703ed8`, up `0x20` for exactly the 32 new bytes of AML; the five shared tables are byte-identical a **twelfth** time; the device count moves 45 -> **46** and the census is **46 declarations, 32 distinct, 30 claimed**; and the payload set `18fdcf5f…`/`463eca48…`/`9cbbf9e6…` is archived in `work/out/p2-4.80`, which leaves the 4.74 control in `work/out/p2-variants` intact for a **sixth** step. Step 4.81 wrote `RPEN` (`QCOM06E1`), the **Reset Power Error Notifier** — `qcrpen.inf`'s own description — in the one slot the corpus fixes harder than any other relation in this table: immediately before `PILC`, where 19 of the 19 `PILC`-bearing tables put it, with the two exceptions (vili, Waipio) being exactly the two tables that have no `PILC`, so the adjacency is not an artefact of the id pair. The body is `PILC`'s mirror image and the pair's only difference is the alias: all 21 `RPEN` tables carry `_SUB` (20 as `Alias (\_SB.PSUB, _SUB)`, Waipio as the `Method (_SUB)` form 4.78 already recorded as that file's habit) while `PILC` carries it in only 6 of 19, which is the corpus saying that the nodes which *report* on a subsystem belong to one and the loader that brings them up does not. The id is the second in the group decided by the 4.80 rule rather than copied from a table, and it confirms the rule from outside: the corpus declares `RPEN` under the same seven generations `PILC`'s are `06`/`05`/`1A`/`04`/`02`/`14`/`25` — `06E1` seven times, `0533` five, `1AE1` four, `04E0` two and `026D`/`14E0`/`25E1` once each — and the pair is consecutive in only five of the seven (`06` is `E0`/`E1`, as are `1A`, `25`, `14` and `04`; the `05` generation is `051B` beside `0533` and caymanslm's `02` is `023B` beside `026D`), so the id could not have been counted up from `PILC`'s. Again the set decides: `qcrpen.inf` carries one hardware-id line, `%RPEN.DeviceDesc%=RPEN_Device, ACPI\QCOM06E1`, with the service `QCRPEN` from `qcrpen.sys`, KMDF, `Class=System`, an ACL admitting only the built-in Admins and Local System, and `WDTFSOCDeviceCategory`, and no inf among the 112 names any of the other six forms. The node is also the first here whose *absence* another node names — `GLNK`'s `_DEP` is `{\_SB.IPCC, \_SB.RPEN}` in 12 of its 21 tables and `{\_SB.RPEN}` in the other 9 — so `GLNK`, claimed and still unwritten, now has something to wait on rather than a dangling dependency, and `_DEP` read across the corpus for this group also gives `IPC0`→`GLNK`, `TFTP`→`IPC0`, `PDSR`→`PEP0`/`GLNK`/`IPC0`, `SSVC`→`IPC0`/`QDIG`, `PMIC`→`SPMI` and `PM01`→`PMIC`. Deriving this node re-walked the same corpus the previous one used and **corrected two of 4.80's findings**, both recorded rather than folded in: `PILC`'s `_STA 0x0F` is in **11 of 19**, not 9, the split being 06/14/1A/25 against 02/04/05 (caymanslm's 02 form writing a `PILX` and an `ACPO` method rather than `_HID` alone), and the alias count is **6 of 19**, not 5, alioth's 25 form having it; and the relations around `PILC` that no slot can satisfy number **six**, not three (`UCS0` at 10 of 10, `URS0`, `USB0`, `UFN0` and `GIO0` at 19 of 19, and `SPMI` at 19 of 19). No node changed for either: `_STA 0x0F` is this file's convention on every device it writes, the `_SUB` omission rests on the six 06 tables alone, and the position was fixed by the fifteen relations that *are* satisfied. The AML is now **6,121 bytes**, `78645724…`, 264 opcodes, 388 named objects, 0 errors with the same 24 warnings and 55 remarks as 4.80; the DSDT reads back out of the payload at `0x0054d4c8` — the same offset for an **eleventh** step — byte-identical to the direct compile; `FVMAIN` is still `0x704000` at sha256 `5f30de51…` with `EFI_FV_TAKEN_SIZE 0x703f08`, up `0x30` for 41 new bytes of AML; the device count moves 33 -> **34** (46 -> **47** named ACPI objects with the thirteen thermal zones) and the census is **47 declarations, 33 distinct, 31 claimed**; and the payload set `95e65229…`/`e7473050…`/`fb7873c9…` is archived in `work/out/p2-4.81`. **Step 4.82** adds `GLNK` (`QCOM0A84`) between `PILC` and `QGP0`, the slot two unanimous relations force because those two are adjacent here; its id comes out of the **0A** family this table had already fixed when it wrote `QGP0`/`QGP1` as `QCOM0A88`, against six corpus tables that share its `PILC`, `RPEN` and `IPCC` ids byte for byte and split three ways on this one; its body is one switch with three symptoms (the nine tables with a `_CRS` are exactly the nine with no `IPCC`, and they are the older generations); and its `_DEP` names `IPCC` and `RPEN`, both of which are now here. The AML is **6,174 bytes**, `b783500f…` (from 6,121 at `78645724…`), 264 opcodes, 393 named objects, 0 errors with the same 24 warnings and 55 remarks as 4.81; the DSDT reads back out of the payload at `0x0054d4c8` — the same offset for a **twelfth** step — byte-identical to the direct compile; `FVMAIN` is still `0x704000` with `EFI_FV_TAKEN_SIZE 0x703f38`, the `AcpiTables` file up 7,482 → 7,534 and the volume's 123 files up by the same 52; the device count moves 34 -> **35** (47 -> **48** named ACPI objects with the thirteen thermal zones) and the census is **48 declarations, 34 distinct, 32 claimed**; and the payload set `1366617…`/`7560e87d…`/`734e65c8…` is archived in `work/out/p2-4.82`, which leaves the 4.74 control in `work/out/p2-variants` intact for an **eighth** step. **Step 4.83** adds `IPC0` (`QCOM0A0D`) in the slot between `PILC` and `GLNK` that three unanimous relations leave — `RPEN` before it (21/21), `PILC` before it (19/19) and `GLNK` after it (21/21) against this file's consecutive `RPEN`, `PILC`, `GLNK` — which is where 4.82 predicted it would land and for the reason it gave; its id is the other half of the pair `GLNK` belongs to, and the pair is what carries the generation: across 21 tables the high byte of a `GLNK` id and of its own table's `IPC0` id is never different, and the low byte never crosses between the three groups (84 with 0D, 8D with 0E, F9 with 1C), so `QGP0`/`QGP1`'s `QCOM0A88` fixes both halves at once and exactly one `IPC0` id and one `GLNK` id appear in the 112 infs, both 0A; its body is the smallest yet written — `_DEP {GLNK}`, `_HID`, alias, with no `_UID` in 21 of 21 and no `_CRS` in any table, including the nine where the `GLNK` above it carries nine Interrupt descriptors, which are the transport's own lines; and it is the first node here whose driver ships a user-mode half (`qsocketipcrum.dll` into System32 and one extra ACE, the user-mode-driver SID). The AML is **6,217 bytes**, `0361354c…` (from 6,174 at `b783500f…`), 264 opcodes, 397 named objects, 0 errors with the same 24 warnings and 55 remarks as 4.82; the DSDT reads back out of the payload at `0x0054d4c8` — the same offset for a **thirteenth** step — byte-identical to the direct compile, and the three 0A ids now sit adjacent in it at 3331, 3374 and 3428 in namespace order; `FVMAIN` is still `0x704000` with `EFI_FV_TAKEN_SIZE 0x703f68`, the `AcpiTables` file up 7,534 → 7,578 and the volume's 123 files up 7,355,711 → 7,355,755; the device count moves 35 -> **36** (48 -> **49** named ACPI objects with the thirteen thermal zones) and the census is **49 declarations, 35 distinct, 33 claimed**; and the payload set `787764ba…`/`6af857cf…`/`45a4040e…` is archived in `work/out/p2-4.83`, which leaves the 4.74 control in `work/out/p2-variants` intact for a **ninth** step. 2–4 are **not** volume-gated: see the space note below |
| **P4** Windows | desktop appears | not started — destroys `userdata` |
| **P5** peripherals | touch, Wi-Fi, GPU, audio | not started |

The commits so far are checkpoints inside P2, not a completed phase. Read the
phase state from this table, not from the commit titles.

### The one thing blocking progress

It is no longer a physical reset, and it is no longer an unread line either. The
reset happened and the panel was read; `docs/08` steps 4.8, 4.9 and 4.95 then
derived the set from the volume and the source rather than from the panel, and it
is **nine architectural protocols with eight producers** — the ninth name shares
a producer with the eighth. The panel's own reading agreed, and the count in the
first draft of this section ("the thirteen candidates") was wrong twice over.

What blocks progress now is one step further in: **the nine are absent because
their producers never loaded**, and the producers are eight of the 27
`CoreLoadImage` failures the volume's own `P2 SEQ` string measures. The string is
`ssssssssssssssssssLLLsLLLLLLLLLLLLLLLLLLLLLLLL` — 46 matches, 19 started, 27
failed to load, and not one `?`. The counts stand and the ordinary reading of the
last clause does not: a 46-character line **is** the stopping. Every build on this
disk carries the same 70-entry array with nothing missing and the core file at
index 0, so a completed walk promotes 69 entries and prints 69 characters
(`docs/08` step 4.130); the only stops this volume allows that give exactly 46 are
physical 49 and 50, both `miss=14 PlatformInfoDxeDriver` and `unhit=24`. (**Amended 2026-09-27 by
step 4.165:** the walk-stop reading is now measured against the same payload on the host, and the
same volume gives the whole walk there — `P2 STATS discovered=80 apriori=69/70 started=73 diag=7
noload=0` with a 69-character `SEQ` — while the phone's line is 46. So the 46 is not a property of
this volume; it is either a property of the machine or a reading of a payload that is not this one,
which is the `90b21643…` / `ecc10a22…` fork below. See `docs/08` step 4.165. **Amended again
2026-09-27 by step 4.166:** the fork is now decidable from the panel without hashing anything — a
payload that prints `P2 WALK` is the `usb-host` class and one that prints `Loading driver at` is the
phone's, because a literal count over the two inflated volumes finds the phone's carrying only
`P2 SEQ`, `P2 STATS`, `P2 DIAG` and `Loading driver at` while `usb-host`'s carries those three plus
`P2 WHY`, `P2 ERR`, `P2 FREE`, `P2 WALK`, `P2 APRI`, `P2 RETRY`, `P2 FWHY` and `P2 BIN`. The rows this
section has been calling owed are therefore absent from the device's image by construction and
present in the tree's — whose `Build/gauguinPkg/DEBUG_CLANGPDB/FV/FVMAIN.Fv` is byte-identical (`cmp`
clean) to the `usb-host` volume, so no rebuild is needed to obtain them. And the physical-stop pair
named in the sentence above can now be stated as a DRIVER-rank boundary: `seen` 48 or 49, with
`DALTLMM` at rank 47 the last entry inside the batch, `FeatureEnablerDxe` at 48 the file between the
two that is not an Apriori entry, and `SimpleFbDxe` at 49 the lowest unhit one that has a file.
**Amended a third time 2026-09-27, still step 4.166:** the sentence forty lines down that reads the
string through the *loop's* map — slot *k* = the *k*-th entry that **matched** — is now decided
against the alternative, rather than merely preferred. `tools/fv-census.py` prints the other map
(slot *k* = array entry *k+1*), under which slot 21 is `ap22 ShmBridgeDxe`; that driver's DRIVER rank
is **72 of 80**, and a walk that reached rank 72 promotes all 69 matchable entries and prints 69
characters. On a 46-character line the identity map's slot 21 therefore cannot be `ShmBridgeDxe`, so
the loop's map is the one the letters are readable through and `DiskIoDxe` is the driver the lone `s`
belongs to. `BdsDxe` at rank 71 is the same argument for the ninth missing name — its `L` cannot be
on a 46-character line either, which is why the missing-`Bds` row is a walk failure and not a load
failure. And the same census run over **every archived image on this disk** returns 70 entries with
69 matchable `DRIVER` files in all of them, so a complete walk prints 69 characters on every image
this repository has built and the 46 cannot be a completed walk on any of them — which leaves the
`entries=70` versus `entries=47` fork a run-time read and not an image property. The phone payload's
volume is byte-identical to `work/out/boot-before-p2walk.img`'s at `c8f57e46046c86c5…`, written
2026-09-23 15:09. See `docs/08` step 4.166.) Zero `?`
says the 46 promoted drivers were all *attempted* — a statement about the drain,
not about the walk. The names move too, because `P2 SEQ`'s slot *k* belongs to the
*k*-th entry that **matched** and a stopped walk's batch is not `ap1..apN`: at
those two stops 33 of the 46 slots name a different entry than the identity map
does, from slot 13 on. So the failure begins at slot 18, which is **Apriori 20 =
`PdcDxe`**, not `RpmhDxe`; from there to the end of the string 27 of the 28
remaining slots are `L`, the one exception being slot 21, which is **Apriori 24 =
`DiskIoDxe`** — `ShmBridgeDxe` (ap22) is *unhit* at that stop, so it was never
promoted and never loaded. One `P2 DIAG` line rendered **Out of
Resources**, which is the status that pairs with `P2 FREE largest=` — `docs/08`
steps 4.18 onward are the analysis of that pair, and step 4.129 closes its
mechanical half: `FindFreePages`' third rung searches the **whole** map below
`MAX_ALLOC_ADDRESS` (`Mem/Page.c:1317-1402`), so rung 4's recursive retry is the
only terminal refusal; `Alignment` is one page for every memory type, because
`Silicon/Silicium/SiliciumPkg/SiliciumPkg.dsc.inc:14` sets
`__DEPRECATED_AARCH64_4K_RUNTIME_GRANULARITY` and the `#else` 64 KiB arm is dead;
and `NeedGuard` is FALSE for all of them. A nine-page request can therefore fail
only for want of a **single nine-page `EfiConventionalMemory` run**, which is a
heap-state statement and not an arithmetic one.

The same step removes the last alternative reading of the failure. The volume's
27 dependency expressions split **21 inert / 6 gated** — the a-priori rule marks a
driver `Dependent = FALSE` before anything runs (`Dispatcher.c:2104-2120`), so 21
of the 27 are read and never evaluated — and **not one of the 27 waits on a
protocol this volume has no producer for**. The one that cannot be judged is
`UsbInitDxe`'s `E722B03F-…`, and step 4.129 places its bytes in exactly two files
of the volume, `UsbfnDwc3Dxe` and `UsbConfigDxe`, so that question is *no header in
the tree* rather than *no producer in the image*.

**This is a question only the phone can answer, and that is now a measurement
rather than an excuse.** `docs/08` step 4.124 reads where the instrument's own
printer lives: every `P2` digest row is written from `P2Digest ()`, which
`CoreDisplayDiscoveredNotDispatched ()` calls and which `DxeMain.c:576` reaches
only *after* `CoreDispatcher ()` at `:562` has returned. So a run that stops
anywhere inside the Apriori batch prints none of them, and the `--el3-stub`
configurations all used to stop inside `EnvDxe`, which is Apriori entry 2.

Step 4.125 moved that ceiling without removing it. The stop was never the
stage-2 map — the redirect moves *addresses*, while what `EnvDxe` needs at
`0x01FD4000` is a *value* XBL and TZ write before the firmware runs — so the
value was fabricated: three writes into three addresses (the pointer, the SMEM
target-info structure it names, and the `SMEM + 0xC0` flag) buy the mirror past
`smem_target.c +435`, then `smem.c +659`, then `smem.c +671`. With those in place
the run walks the Apriori batch in order, prints `K 1` through `K 18` with a name
for each row, and dies on **Apriori 19 = `RpmhDxe`** — the same *slot* the
device's `P2 SEQ` records its first failure in, though by the other mechanism and
in the adjacent entry: the string's 19th character belongs to Apriori 20 =
`PdcDxe` once the batch is read as the loop fills it, so the two runs fail at the
same position and not at the same driver (`docs/08` step 4.130). There the image
fails to load, here it loads, starts, and then asserts
inside its own error branch. The last two panel rows decode — `EFI_SOFTWARE |
EFI_SW_EC_ILLEGAL_SOFTWARE_STATE`, reported under `RpmhDxe`'s own baked-in caller
id, and then a `DebugLib` guard firing because a print was reached with a null
format. Step 4.128 answers which of `rpmh_image_os.c`'s four such sites was reached: **one of
three** — the module's 22 `bl` calls to `DebugVPrint` include exactly three that pass
`mov x1, xzr` (`0x6004`, `0x6120`, `0x6190`), and those three are three of the four
`rpmh_image_os.c` sites, at lines 84, 175 and 187; the fourth, line 197, prints the real format
`RPMH_ERR_FATAL` and cannot trip the guard. So the branch is in `rpmh_image_os.c` after all and
the row's file is `DebugLib.c`'s, because `DebugVPrint`'s own null test at `0x191c` fires before
the site's `ASSERT (0)` and spins, which is why the site's `ASSERT rpmh_image_os.c +N: 0` is
never printed. Which of the three is still open. The
assert is `RpmhDxe`'s own `DebugLib.c:78` (`ASSERT (Format != NULL)`, whose `CpuDeadLoop` is the
`b .` at RVA `0x19d8`), and one `DebugAssert` at `0x19e0` in that image emits both panel rows.
The digest is still absent for the original reason: this run dies
inside the batch too.

Step 4.126 is the one place in the record where the two runs can be held against each
other, and it settles part of that. `P2 SEQ`'s slot *k* belongs to the *k*-th entry
the promotion loop **matched**, which is Apriori entry *k + 1* only on a completed
walk — and this batch is not one, so the phone's eighteen slots here hold Apriori
1..13 and then 15..19, with ap14 `PlatformInfoDxeDriver` *unhit* at that stop
(`docs/08` step 4.130). The comparison survives the shift because all eighteen of
those letters are `s`: the mirror's `K` rows count the same loop, so the phone's
letters and the mirror's 18 rows still cover the same eighteen starts, **seventeen
agree and one does not** —
Apriori 17 = `CmdDbDxe`, where the phone's `EntryPoint` returned `EFI_SUCCESS` and the
mirror's returned `EFI_UNSUPPORTED`. The letters differ at Apriori 11 as well (`SO`
against `s`) and that is not a second disagreement: `s` means the start did not fail,
not that the status was zero, and `DALSYS`'s status was non-zero with bit 63 clear.
Two things follow. First, the coincidence of the 19th position is **not** corroboration —
the phone fails to *load* `PdcDxe` there, and the mirror loads `RpmhDxe` and asserts inside
it, which is one slot occupied by two adjacent entries reached by two mechanisms. Second, the mirror's `CmdDbDxe` is
a genuine divergence and it is confounded: the seed's SMEM has no heap, which two
earlier entries say in SMEM's own words — `EnvDxe` at Apriori 2 cannot read the
partition table, `DALSys`'s allocation fails at Apriori 11 — and the phone's payload —
md5 `a2963f46…`, the one artifact that would separate the seed from the build — **is on
this disk**, as the gzip-compressed kernel inside `work/out/boot-before-p2walk.img`
(1,142,784 B, sha256 `fb697f47…`), which is the image that drew the 46-character `P2 SEQ`
and the only file under `work/` whose decompressed payload carries that md5 (step 4.132).
The seed's next rung is therefore SMEM's heap and not a new driver, and the current
capture is already its control.

Two readings are therefore owed to the phone, and both are short — `P2 WHAT` for
the value behind `K 11 SO`'s non-error, non-`EFI_STATUS` letter, and
`P2 APRI unhit=` for how many Apriori entries the walk never handed to the
promotion loop, which is a *discovery* count and not a presence one: no name is
missing from any of the 121 volumes measured, so the number is 1 on a completed
walk (index 0 alone) and 24 at a 46-promotion stop. Its twin, `P2 APRI first=`,
now has a single admissible value on this disk —
`D6A2CB7F-6A18-4E2F-B43B-9920A733700A` — which makes the phone's own array row the
cheapest instrument the record is missing (`docs/08` step 4.130).
Neither blocks building. The payload that carries the `P2` digest literals is
already built and hashed — `work/out/p2-variants/Mu-gauguin-silicon-gzip.img`,
`90b21643…` — and still owes its first reading, under *先读屏，再刷下一次*.

The pieces a device session uses — the full sequence, with what each outcome
means and which payload to try next, is
[`08-device-session.md`](08-device-session.md):

1. `tools/fastboot-capture.sh` — first thing it asks is `oem fbreason`, which
   reports why ABL entered fastboot and can say `Reason:LoadImageAndAuth Fail`
   or `Reason:BootLinux Fail`. Either of those means the payload was reached.
   Then `oem uefilog` / `lkmsg` / `lpmsg`, plus `slot-unbootable` /
   `slot-retry-count`. If ABL is silent it runs `tools/unwedge-fastboot.py`,
   which classifies *which* silence it is — a reply left unread (recoverable by
   draining the endpoint), a download left waiting (recoverable in principle),
   or a fastboot thread stuck behind a still-live USB stack (not recoverable;
   power button). That was the state before the payload of step 4.8 ran; it is
   not the state now, and the difference is worth keeping straight, because it
   looked the same from the host both times.
   Note that `oem fbreason` and `oem uefilog` are commands **this phone's**
   ABL has and a Mu-Silicium-built one does not (`docs/07`), so their absence
   is not by itself a wedged fastboot.
2. `tools/pull-bootloader-log.sh` + `tools/read-logfs.py` — the device's third
   log channel, and the only one that does not depend on the payload running.
   ABL writes a log of every boot into the `logfs` partition: a FAT12 volume
   holding a ring of five 32 KiB `UEFILOG*.TXT` files, read here as a stage
   table with the last stage reached marked. Baseline, from the P0 dump: all
   five recorded boots reached `Start EBS`, i.e. handed over — so a slot that
   stops earlier is the answer, and `Apply Overlay` / `DTB offset is NULL` are
   both in ABL's own string table, meaning a refusal is written down even
   though the phone says nothing. Routes: `fastboot oem uefilog` (never yet
   returned anything here), `dd` of `/dev/block/by-name/logfs` from TWRP or
   root Android, or the P0 dump. `docs/07` has the format; `docs/08` step 4.6
   has how to read an answer.
3. `tools/restore-stock-boot.sh` — the A/B control: put the stock `boot` back
   and see whether Android returns.
4. `tools/flash-boot.sh` — the one command that writes a payload to `boot`, over
   whichever route answers. It exists because step 1b can make the fastboot route
   unreachable (the image in `boot` wedging ABL, so a reset reproduces the wedge)
   and TWRP is then not a fallback but the only way in; it also reads the
   partition back and compares the hash, so "the write landed" is established
   rather than assumed.
5. `work/out/boot-pstore.img` and its five siblings `-raw`, `-raw-txt`,
   `-raw-noefi`, `-gz-noefi`, `-gz-fixedsz` — P1's mainline kernel in the six
   shapes that differ on the properties separating our images from the one the
   phone boots (raw vs compressed, EFI-stub form of the arm64
   header, `text_offset`), each with `CONFIG_PSTORE_CONSOLE`/`PSTORE_RAM` and a
   cmdline that puts the kernel log in a pstore region **we choose**
   (`0xd0000000`, `ramoops@d0000000`, `no-map`). The phone declares no ramoops
   region of its own — its panic log goes through `mtdoops` to a raw partition —
   so there is nothing to match and the address is checked against the phone's
   DRAM partitions *and* its `no-map` carveouts (`tools/abl-boot-check.py`); the
   two earlier addresses were wrong in exactly those two ways, one outside every
   RAM partition and one inside the bootloader's `removed-dma-pool` for the modem
   and DSPs. The cmdline carries `reboot=panic_warm`, so a payload with no UART
   and no screen driver can still be read back at
   `/sys/fs/pstore/console-ramoops-0` after the phone reboots itself (step 4.5 in
   the runbook; the reasoning is in `docs/07`). `tools/build-p1-payloads.sh`
   builds the DTB and all of the images in one pass and refuses to ship a tree
   that is missing either log channel — one `ramoops` node at the address above,
   **or a `/chosen` with no `simple-framebuffer`** — because both are in that one
   file and a payload missing either is indistinguishable from one that works;
   `tools/check-payload.py` refuses to let a structurally wrong one reach the
   device. The screen half is the one that
   needs no round trip: the logo being replaced by the kernel log, and then by
   init's `alive: N s uptime` heartbeat, is P1's gate observed directly. The log
   half needs the phone to restart itself, so the kernel is also built to panic on
   the two failures this bring-up is most likely to hit (an oops in a probe, and a
   spin waiting on a clock or regulator that never comes ready) — otherwise both
   end in a kernel that neither prints nor reboots, and the ring is never read.
6. `work/out/p2-variants/Mu-gauguin-stock-{none,gzip}.img` — two stock-shaped
   builds, one per surviving candidate (uncompressed vs gzip kernel). Each pairs
   with a P1 variant on the compression property, which is what makes the pair —
   and not the individual attempt — the thing to read: see step 4b/4c in the
   runbook. A third image sits beside them, `Mu-gauguin-silicon-gzip.img`,
   deliberately not part of the pair: it varies the header version, the page size
   and where the tree lives all at once, so it cannot be read as a one-variable
   experiment, and it is kept as the fallback for the case where both stock
   variants are refused for a reason that turns out to be the stock shape itself.
   All three are built by `tools/build-p2-payloads.sh`, and the earlier build
   of the pair — made by hand, never flashed — could not have run at all: it
   carried a stale device tree with no `/__symbols__`, so ABL would have refused
   the vendor overlay (`docs/07`). What was in `boot` when the first attempt was
   made was the same shape as the third image — v1, page 2048, tree after the
   gzip stream — and carried that same stale tree, 71,737 bytes of it against
   the current build's 87,594; both images hold a *byte-identical* firmware
   (`SILICIUM_UEFI.fd` `md5 9c104725…`), so the tree is the only variable
   between them and step 4.8 is a clean one-variable experiment. `boot` now
   holds `Mu-gauguin-silicon-gzip.img`, `sha256 816b1d41…`.

Those pieces are backed by the offline tools below, which exist because a device
cycle is expensive and a bad image costs a physical reset. Every defect this
project has found in a payload was found by one of them rather than by the phone:

- `tools/abl-boot-check.py` — replays ABL's decision path over a built image and
  says whether *this phone* would take it: the arm64 header check, the
  `msm-id`/`board-id` selection, the overlay's fixups against our `/__symbols__`
  (replayed in Python *and* merged for real by `fdtoverlay`, since libfdt and
  libufdt disagree on a tree whose symbols point at phandle-less nodes — one
  refuses, the other boots with the fragments silently dropped), and the two
  placement questions (inside a DRAM partition, outside every `no-map` carveout)
  for the ramoops region and the framebuffer. Run by
  `tools/build-p1-payloads.sh` at the end, so a payload that fails it never
  reaches anyone.
- `tools/gauguin.py` — this phone's memory model in one place: the DRAM
  partitions and the `no-map` carveouts, both measured from the running phone's
  `/proc/device-tree` rather than read out of a tree's source.
- `tools/fdt.py` — just enough flattened-device-tree parsing to ask questions
  about a blob: the header, the node walk, `/__symbols__`, the overlay's
  `__fixups__`/`__overlay__` fragments, and the `qcom,msm-id`/`qcom,board-id`
  cells the selection turns on.
- `tools/make_dtbo_sinks.py` — generates the `/__symbols__` and the empty sink
  nodes the vendor overlay's 158 fixups resolve against. An input to the build
  rather than a check: without it ABL refuses every payload with
  `ApplyOverlay: ufdt apply overlay failed`, and with it the overlay lands in a
  subtree nothing binds to.
- `tools/build-device-tree.sh` — builds the one device tree every payload
  carries, and checks the built blob rather than the source it came from: the
  `/__symbols__` count, exactly one `ramoops` node at `0xd0000000`, and the four
  `/chosen/framebuffer` properties. It is a script of its own because the tree
  has two consumers — the P1 payloads and the UEFI ones — and holding it in one
  builder is what stops the second consumer building against a stale copy, which
  is what happened (`docs/07`).
- `tools/build-p1-payloads.sh` / `tools/build-p2-payloads.sh` — the two payload
  sets, each ending in both checkers so a payload that fails one never reaches
  anyone.
- `tools/read-logfs.py` — reads the bootloader's own per-boot log out of the
  `logfs` partition, from a raw image, an extracted slot, or a `oem uefilog`
  dump, and prints it as a stage table with the last stage reached marked. It is
  the one reader here that is aimed at the device rather than at a file we built,
  and it is offline in the sense that matters for the current blocker: the P0
  dump answers it with no phone at all.

The reference for all of these is Qualcomm's own `QcomModulePkg` (the ABL
source), vendored at `work/ref/mu_qcommodulepkg` from
`Daniel224455/mu_qcommodulepkg` and validated byte-for-byte against the PE
extracted from this phone. It is gitignored — a large copy of someone else's
tree — and used as the authority for what ABL does, which is why `docs/07`'s
claims about `CheckAllBitsSet`, `GZipPkgCheck` and the ramoops address can be
read against `file:line` instead of inferred from behaviour.

### Standing decisions, with one amendment

The original rule was "**Never write to the device's storage until P4**". That was
relaxed once, with the user's explicit authorization, to write the `boot`
partition for the P2 test — and `boot` was backed up and verified beforehand
precisely so that relaxation would be safe. The rule stands for everything else:
`userdata`, the partition table, and the firmware LUNs are still off limits
until P4.

---

## P0 — Survey, backup, firmware inventory

**Why first:** the installed ROM is a `user/dev-keys` Smartisan port with no public image.
Anything that re-partitions storage before a backup exists risks an unrecoverable device.
And the port itself cannot be scoped until we know which of Qualcomm's signed drivers this
phone's firmware actually contains.

Work:

1. Identify the hardware correctly (the device lies about its model — see `01-hardware.md`)
2. Dump every partition to `~/backup/gauguin/images/`
3. Recover the DXE driver set and platform config from the phone's own XBL
4. Establish that no existing UEFI port covers this SoC

**Gate:** every partition except `userdata` dumped and verified; DXE inventory extracted;
confirm by search that no `gauguin`/`SM7225`/`Bitra` UEFI port exists anywhere public.

**Result:** satisfied. 86 signed AArch64 DXE drivers recovered, `uefiplat.cfg` recovered,
no existing port found.

---

## P1 — Mainline Linux bring-up

**Why this and not UEFI directly:** a UEFI platform package is mostly a hardware
description — clock trees, regulator relationships, GPIO pins, panel timings, MMIO bases.
Writing that description blind, against a device that only has a 4.19 vendor kernel and no
schematics, is guesswork. Mainline Linux already has all of it **for the same silicon**:
`arch/arm64/boot/dts/qcom/sm7225.dtsi` + `sm6350.dtsi` describe SM7225 exactly, and
`sm7225-fairphone-fp4.dts` is a worked example for the same `msm-id 459`. Booting mainline
converts guesswork into measurement, and it is a small amount of work because the
bootloader is already unlocked.

Work:

1. Fetch a mainline kernel and `sm6350`/`sm7225` DTS support
2. Write `arch/arm64/boot/dts/qcom/sm7225-xiaomi-gauguin.dts` — clone the Fairphone 4
   board file, change panel, touch controller, regulators, and the `qcom,board-id`
3. Build `Image` + `dtb`, wrap into an Android boot image — with our tree in the
   boot image's DTB slot. That does **not** make ABL use it as-is: matching
   `msm-id`/`board-id` gets two of the six bits `CheckAllBitsSet` needs, and the
   tree declares no `pmic-id`, `softsku-id`, `platform-subtype` or `foundry-id`,
   so the vendor overlay is applied to our tree on every boot. The tree therefore
   carries the `/__symbols__` the overlay's fixups resolve against
   (`tools/make_dtbo_sinks.py`), and a payload built without it is refused before
   the kernel runs (`docs/07`). Add the pstore cmdline so the boot leaves a
   readable log at an address we choose, checked against the phone's own DRAM map
   and carveouts.
4. `fastboot boot boot.img` — nothing written to the device
5. Use `extract_dtb` / `/proc/device-tree` output as the hardware reference

**Gate:** the device boots mainline, prints to a serial console or on-screen framebuffer,
and enumerates UFS. That output is the input to P2.

**Risk:** moderate. Panel and touch are the fiddly parts; both have mainline drivers for
this SoC (`mdss`/`dsi` and `novatek-nvt-ts` respectively).

---

## P2 — UEFI skeleton

**Why:** this is the phase that decides whether the project is viable. Before writing any
Windows-specific code, UEFI has to run at all on this board.

Approach, mirroring what Mu-Silicium does for other SoCs:

1. Clone `Project-Silicium/Mu-Silicium` (Project Mu — BSD licensed, the community standard)
2. Create `Silicon/Qualcomm/BitraPkg` by adapting `RennellPkg` (SM7125) and `MooreaPkg`
   (SM7150) — the closest-spec existing packages
3. Create `Platforms/Xiaomi/gauguinPkg` from the same references, parameterised with the
   values in `04-uefi-platform-config.md`
4. Feed in the drivers extracted in P0 where the open-source equivalents are not needed
5. Compile the missing open-source pieces from `edk2-porting/edk2-msm`'s `QcomPkg`
   (`UsbBusDxe`, `UsbKbDxe`, `UsbMassStorageDxe`, `AdrenoDxe`)
6. Emit an Android boot image, `fastboot boot` it

**Gate:** the boot manager draws on the phone's screen, and the storage it lists includes
UFS as a block device. If this fails, stop and reconsider — everything downstream depends
on it.

**Status:** the first half of the gate is met and the second is not. Our firmware runs
and draws its own DEBUG stream on the panel — the whole of `docs/08` step 4.8 — and
then halts in `DxeMain` because an architectural protocol is missing. The boot manager
is not reached, so nothing is listed yet. Read the gate as "runs" (answered yes) and
"hands off to BDS" (open).

The gate originally said "`fastboot boot` shows the UEFI Shell". That was wrong twice
over, and `docs/07` has the evidence: this platform boots via `fastboot flash boot` and
not `fastboot boot` (different ABL code paths), and **no Mu-Silicium phone platform ships
the shell at all** — `ShellPkg/Application/Shell/Shell.inf` is referenced by no platform
under `Platforms/`. A gate the reference for this same `msm-id` cannot meet is not a gate.
The shell is a decision to revisit after the first execution; what the volume does
provide, and what the gate now asks for, is `BootManagerMenuApp` drawing on the panel.

Step 4.156 then took the 27 `CoreLoadImage` failures off the device for the first time. The flag
`Image.c:700-741` branches on, `RelocationsStripped`, is set by `BasePeCoff.c:659-667` from COFF
Characteristics bit 0 and from nothing else; all 46 promoted images have that bit clear and are
linked at `ImageBase 0x0`, so the `AllocateAddress` arm is dead code and every one of the 46 makes
exactly one `AllocateAnyPages` call. Measured against the volume, no per-image property can
therefore separate the letters, and none does: 27 of the 46 belong to eight groups of images
making a request the loader cannot distinguish, and every one of the eight is split by letter with
the successes always earlier than the failures. The run then breaks the premise `P2 RETRY` re-asks
under — a 9-page refusal two slots before a 12-page success, and an exact 12-page refusal
immediately before a 12-page success — and it breaks it under *both* candidate slot maps, so the
identity/cut join disagreement does not decide the 27. `CoreLoadImage` has four other reachable
failure sites, two of them pool and two after the image already holds its pages, which
`Image.c:940-948` gives back on the way out; an `L` covers *refused* and *loaded-then-failed*
alike and the letter does not say which. That is `P2 WHY` and `P2 ERR`, neither ever photographed,
and they are what the next device window reads. The same step corrected the model `P2 RETRY`
re-asks with: `__DEPRECATED_AARCH64_4K_RUNTIME_GRANULARITY` is defined nowhere in this tree, so a
runtime image's request is 64-KiB-aligned and rounded up to a multiple of 16 pages, where
`tools/pe-facts.py` and the firmware's own `P2BRINGUP` comment both model it as one page.

**Step 4.157 withdrew that correction, and it was a glob away from being right.** The search that
reported the macro absent listed `.dsc` and not `*.dsc.inc`; the definition is
`Silicon/Silicium/SiliciumPkg/SiliciumPkg.dsc.inc:14`, reached through
`gauguin.dsc:71 → BitraPkg.dsc.inc:20 → QcomPkg.dsc.inc:10`, and
`Build/gauguinPkg/DEBUG_CLANGPDB/AARCH64/…/DxeMain/GNUmakefile:131` carries
`-D __DEPRECATED_AARCH64_4K_RUNTIME_GRANULARITY` in the compiled `CC_FLAGS`. So
`RUNTIME_PAGE_ALLOCATION_GRANULARITY` is 0x1000, `Alignment` is one page for all four memory
types, `tools/pe-facts.py`'s expression is the loader's own `Image.c:682-688` and keeps it, and
the 16-page column comes back out of `tools/load-failure-census.py`. Only the ten runtime-typed
images move — their requests sum to 873 pages either way under both slot maps, and the batch's
whole demand is 1,462 pages on the cut map against 1,562 for the `apriori[k+1]` join — so the
step's own findings stand untouched: the eight split groups, the falsified premise, and
`P2 WHY`/`P2 ERR` as what decides the 27. The nine missing architectural protocols are nine under
both maps as well. The same step decoded the two rows that end every QEMU run as two reports:
the `ERROR: C90000002:V03000007 I0 CB29F4D1-…766` row is the serial status-code handler's third
branch with `Data == NULL` (68 bytes into a 512-byte buffer, not the overflow an earlier reading
called it), and the `ASSERT DebugLib.c +78: Format != ((void *) 0)` row is a second report — a
NULL format reaching `DebugPrintMarker` — from the image that carries both that literal and that
caller id, `RpmhDxe.efi`.

**Step 4.158 read the two rows the record has been calling owed off the host instead of the
phone, and found they were never owed.** The volume is LZMA-compressed, which is why a `grep` for
any string the firmware prints returns nothing: the `LZMA_CUSTOM` GUID sits at `0xf008` and
`0x1101c` and the stream at `0x11030`, and inflating it gives 7,536,648 B for the current build
against 7,348,232 for the payload installed on the phone — `work/out/boot-before-p2walk.img`,
whose kernel is byte-identical to `/tmp/phone-payload.raw` (sha256 `d0919c00…`). Counted there,
the phone's payload carries `P2 SEQ` twice and **no `P2 WHY`, `P2 ERR`, `P2 FREE`, `P2 FWHY`,
`P2 APRI`, `P2 RETRY` or `K` literal at all**, while the current build carries every one of them,
so "SEQ read three times and WHY never read once" is a build history and not three lost
photographs. `tools/probe-fingerprint.py` reads the two the same way — **4/14** rungs on the
phone's payload against **14/14** on the current one. (**Amended 2026-09-27 by step 4.165:** the two
numbers are one volume each in two conventions — `lzma`'s output is 8 bytes longer than
`tools/fv-inventory.py`'s `inner` on every image and `lz[8:] == inner` is `True`, so 7,536,648 and
7,536,640, and 7,348,232 and 7,348,224, each name one volume; and "the current build" here is now
identified — its `.fd` inflates to that 7,536,648 B volume and that volume is byte-identical to the
unflashed `work/out/usb-host/Mu-gauguin-xhci-host-gzip.img`. See `docs/08` step 4.165.) And the two digest lines are not separate readings: `P2Record`/`P2MarkSeq` write the
phase character and `P2WhyLetter (Status)` into the slot's array and `P2Tick` prints that same
pair as the `%c%c` of one live row per dispatch attempt with the slot's GUID beside it, so
`P2 SEQ`+`P2 WHY` are the `K` rows compressed by slot and `P2 ERR` is those statuses named.
`P2Digest`'s only caller is `CoreDisplayDispatchedNotDispatched`, which runs after
`CoreDispatcher` returns, so no run that dies inside the Apriori phase can carry any of the three
— which is what both new runs do. They run the current payload under the standing EL3 stub: the
standing instrument ticks 18 rows and dies, and step 4.135's two RSC seeds buy exactly one more,
`Rpmh Sleep callback registration failed, Status = 0x8000000000000003` then
`K 19 Ss 19/69 free=1024 60F4DF83-C758-52B5-9AA0-92EA560EDB8F`, which `Guid.xref` resolves to
`RpmhDxe` (Apriori line 20, with `PdcDxe` on line 21), before the same `ASSERT` returns with the
caller id moved to `B43C22DB-…`, `PdcDxe`'s. All 19 rows are `Ss` with `free=1024`, which
`P2LargestAlloc`'s ladder makes a band rather than a maximum — the 4096-page rung failed, so the
largest free run is in `[1024, 4096)` pages. The caller id is not the FFS GUID: gauguin's
`RpmhDxe.inf` declares `60F4DF83-…` over a binary carrying `CB29F4D1-…` at `0xe018`, and
`PdcDxe.inf` declares `C4D86DF4-…` over one carrying `B43C22DB-…` at `0x7018` — the shared ids of
57 and 22 other boards' stubs. That also closes the question step 4.157 re-opened, since steps
4.136-4.138 had already named the call site. What is genuinely still owed is one row family,
`P2 APRI`'s `matched`/`miss`/`entries`, which describes the promotion walk itself and has no
per-dispatch analogue.

**Step 4.159 put step 4.139's third seed under that same payload and crossed the slot-20 wall, and
what is behind it is a different kind of wall.** Three preloaded blobs now buy three slots: the
standing instrument ticks 18, the two RSC seeds from step 4.135 buy slot 19, and step 4.139's
`pdc-cap.bin` — four bytes, `00 00 10 00`, at `0x424a1008`, chosen from `PdcDxe.efi`'s own compare
at `0x2784` where bits [23:16] must be non-zero — buys slot 20. The run
(`work/out/qemu-panel-4.159-pdc-cap.txt`, 678 screens/170.3 s) is the **first reading in this tree
with a `K 20` row and the first with `4DB5DEA6-…` in it**, and its tail is

    K 18 Ss 18/69 free=1024 40256211-624E-580B-97ED-3011FB3CB9A3
    Rpmh Sleep callback registration failed, Status = 0x8000000000000003
    K 19 Ss 19/69 free=1024 60F4DF83-C758-52B5-9AA0-92EA560EDB8F
    K 20 Ss 20/69 free=1024 C4D86DF4-D250-5062-8078-1DA30EA6D240
    Clock_DriverInitERROR: C90000002:V03000007 I0 4DB5DEA6-5302-4D1A-8A82-677A683B0D29
    ASSERT ClockDriver.c +260: 0

so slot 20 is `PdcDxe` (`C4D86DF4-…` is its FFS GUID, present on a panel for the first time) and the
wall is now slot 21, `ClockDxe`. The assert changes kind: the first two walls end at
`DebugLib.c +78: Format != ((void) 0)`, which is `DebugVPrint`'s guard firing on a NULL format — a
formatting accident reached from a failure path — while this one ends at `ClockDriver.c +260: 0`,
`DebugAssert` called by the driver with its own file, line and description, the first ladder failure
in this tree readable without a disassembler. The row above it is that driver's own banner printed
with no newline, `Clock_DriverInit` (`ClockDxe.efi:0x131b5`, 192,512 B, sha256 `c200d38e…`), and
the literals around it name a sub-init per stage — `DALSYS_LOGEVENT_FATAL_ERROR: Clock_Init{Bases,
Voltage,Target,NPA} failed.` at `0x13214`-`0x132b6` — none of which printed, so the assert preceded
the fatal log. The names split three-for-three now: each `K` row names the driver by gauguin's own
FFS GUID and each `ERROR` row names it by the shared id compiled into the vendor blob, `4DB5DEA6-…`
at `ClockDxe.efi:0x1d018` being 73 boards' `ClockDxe` against gauguin's `34F25731-…`. All 20 `K`
rows are still `Ss` with `free=1024`. The phase still does not finish, so `P2 APRI` remains the one
row family nothing has read. See `docs/08` step 4.159.

**Step 4.160 opened `Clock_InitTarget` and the wall inside it is the driver's own data, not this
machine.** Step 4.159's question — is `ClockDriver.c +260` a checkable state or another unpassable
one — has an answer that is neither: line 260 is a **block** assert. `ClockDxe`'s init at `0x28d0`
runs five checks, each with its own fatal string and its own assert line — `0x92a8`/145 (a DAL
`DALSYS_SyncCreate` dispatch), `0x2f6c`/199 (`Clock_InitBases`), `0x6b9c`/232 (`Clock_InitVoltage`),
`0xa75c`/260 (`Clock_InitTarget`), `0x31f4`/275 (`Clock_InitNPA`) — and the run's line 260 says the
fourth is where it stopped, so blocks 1-4 passed. Block 3 passing is load-bearing: `0x6b9c` walks
the driver's rails and resolves each one's default boot voltage out of the DAL property
`ClockRailConfig` (`0x1561c`), logging `Unable to determine default boot voltage for %s.`
(`0x13b0b`) when a rail is absent — and it did not log, so the DAL config database is live here. A
`Clock_InitTarget` failure is one of exactly **five** exits inside `0xa75c`, each setting
`0xfffffffd` and jumping to the same epilogue at `0xa7b4`: from `0xa93c` (`0xa7b0`), from `0x33d8`
(`0xa7f4`, a name absent from the context's own table, `-41`), from `0x3468` (`0xa804`, a tagged
index out of range), and from `0xb348` for domain 0 and domain 2 (`0xa888`, `0xa898`). Only the
first touches hardware, and it **cannot fire**: `0xa93c` loops 3 domains × 40 clocks calling
`0xb9cc`/`0xba88`, which read the six clock-controller bases `0x18321110`/`0x18321114`/
`0x18323110`/`0x18323114`/`0x18325910`/`0x18325914` (`+ index*32`) into out-structs and return `1`
unconditionally, returning `0` only for a domain above 2, an index above 39 or a NULL out-pointer —
none of which `0xa93c` ever passes. So the zeroed reads are information-gathering, not the wall.
The `ERROR: C90000002:V03000007 I0 <caller>` row above the assert is not the driver's failure status
either: it is `DebugAssert`'s own report at `0x8170`, `EFI_ERROR_UNRECOVERED|EFI_ERROR_CODE` and
`EFI_SOFTWARE|EFI_SW_EC_ILLEGAL_SOFTWARE_STATE` under `SerialStatusCodeWorker.c:84`, stamped with
`gEfiCallerIdGuid` — which `0xff18` loads from `0x1d018`, the only reference to it in the image —
so the codes are identical in 4.158's `RpmhDxe` failure and 4.159's `ClockDxe` one and the row's
only content is the caller id. What separates the five exits is one register: `X30` at RVA `0xa7b4`
reads `0xa7b0`/`0xa7f4`/`0xa804`/`0xa888`/`0xa898` for exits 1-5, so one breakpoint there decides
it without a new seed. See `docs/08` step 4.160.

That breakpoint was set, and the exit that fires is **4**: `X30 = 0x9c40d888` at RVA `0xa7b4` is
`0xa888`'s `bl 0xb348` for domain 0, the `w0 = 0` rate call, with `x0 = 0xffffffff` — `0xb348`'s own
failure value — as the branch's operand. The helper it fails in is a bounded poll, and that makes
4.160's remaining question decidable from code alone: `0xb8f0` re-reads one status register at most
200 times, returns `1` only once bit 31 of it has gone to 1 (with the low six bits of that family's
`+16` register as the rate), and returns `0` otherwise, on which `0xb348` returns `-1`. A zeroed
register model therefore fails this call **by construction** — the zeroed clock registers are exit
4's cause, not a bystander. Acting on that, `/tmp/apcs-clk.bin`'s four nonzero words loaded at
`0x46d21700` — the stage-2 image, via the block-193 redirect recorded in `s2_l2.inc`, of the two
registers `0xb8f0` polls — carry the same 175 s panel **past `ClockDriver.c +260`**: no
`Clock_DriverInit` row, no `ERROR: C90000002`, no assert, and 140 driver loads instead of 34, through
`ShmBridgeDxe`, `ScmDxe`, `SdccDxe`, `UFSDxe`, `PmicDxe`, `BdsDxe`, `GpiDxe` and `I2C` to a new and
different wall in `AdcDxe` — a synchronous exception at `DALSys.dll+0x346c`, `FAR
0xAFAFAFAFAFAFAFAF` (`PcdDebugClearMemoryValue`, `MdePkg.dec:2440`), inside the function whose own
exhausted-search message is `DAL device (0x%s) not found`. So the ladder has moved for the first
time since 4.139's seeds, and it moved onto a driver data structure with an uninitialised field
rather than a clock register. It has not moved onto a clock controller: the ready bit and the rate
index are fabricated by the instrument, and on hardware those registers are the controller's real
state. See `docs/08` step 4.161.

That uninitialised field is not a driver bug in the ordinary sense: it is a **use-after-unload**.
Registering at the registry's own two bodies (`DALSys+0x335c` register, `+0x33b0` deregister) shows the
first free of 32 slots taking a pointer **inside `PmicDxe`'s image** (`0x9c206278 = PmicDxe+0x1F278`,
its `.data`, entry 0 `/pmic/target`, `lr = PmicDxe+0x1580`) at 9.9 s, `AdcDxe` registering its own
record at 12.0 s (`AdcDxe+0x8838`, `/core/hwengines/adc/pmic_0/vadc`, `lr = AdcDxe+0x13FC`), and the
fault 2.1 s later walking the **first** of them, all `0xAF`. No deregister ever fired.
`PmicDxe`'s entry point returns `EFI_DEVICE_ERROR` (`PMIC was not detected`), so `CoreStartImage`
(`Image.c:1842`) calls `CoreUnloadAndCloseImage`, whose `CoreFreePages` (`Image.c:1130`) has
`CoreConvertPagesEx` (`Page.c:615`) convert the image's pages to `EfiConventionalMemory` and clear them
at `Page.c:813` with `PcdDebugClearMemoryValue` `0xAF` (`SiliciumPkg.dsc.inc:70`) — the panel's own
rows show `PmicDxe` loading at `0x9C1E7000` three times (rows 608, 628, 650), each followed by its
failure and `Error: Image at 0009C1E7000 start failed: Device Error` (`CoreExit`, `Image.c:1925`),
which is only possible if the extent was handed back each time. DALSys's 32-pointer list has no unload
hook, so the slot kept pointing into the freed page — and because the lookup's loop test is that
cleared word (`[+16] = 0xAFAFAFAF` is a *count*, `cmp w26, w8; b.cc` on the unsigned compare), a
cleared record is a crash rather than a miss. So any DAL-registering driver whose entry point returns
an error poisons the registry. In this environment the poisoner is guaranteed — QEMU `virt` has no
PMIC, so `PmicDxe` can never succeed — and the same run is the first of the tree's 22 panels to load
`BdsDxe`, `GpiDxe`, `I2C` and `AdcDxe`, i.e. BDS starts and its connect phase is where the stale
record is hit. It is a real defect and a QEMU-only *instance* of it: on the phone the PMIC answers, so
this particular collision would not happen, and what remains in that run is the shared-IMEM rows,
`UFSDxe`'s IOMMU attach failure and `AdcDxe`'s own attach. See `docs/08` step 4.162.

The counter-experiment 4.162 designed was run, and it answers yes. Suppressing exactly that one
registration — reading the record at the registry body and zeroing `x0` when its first device name is
`/pmic/target`, with no code patched and no slot edited — leaves the fault site *executed* but makes
it harmless: `x21` is `AdcDxe`'s own live record (`0x9c0bc838`, `[+24]` its live table) instead of the
freed `PmicDxe` extent, and the panel loses its `Synchronous Exception`, its
`FAR 0xAFAFAFAFAFAFAFAF` and its `ASSERT [ArmCpuDxe]` entirely. The same run then goes to **310**
`Loading driver at` rows against the control's 137 — through `BdsDxe`, `RamManagerDxe`,
`SetupBrowser` and `AcpiPlatform` — and draws this tree's first `P2` digest: `P2 STATS discovered=80
apriori=69/70 started=73 diag=7 noload=0`, seven named failures (`UFSDxe` and `PmicDxe` Device Error,
`AdcDxe` and `LimitsDxe` Unsupported, `UsbPwrCtrlDxe` Access Denied, `ButtonsDxe` Not Found,
`AcpiPlatform` Aborted) and a 69-character `P2 SEQ` whose six uppercase `S` sit on exactly the six
Apriori-array positions those first six GUIDs occupy, with `AcpiPlatform` in no array slot at all —
six for six, and the phone's own 46-character string is 19 `s` and 27 `L` with no `S`, i.e. the phone
fails at *load* and this build fails only at *start*. Its last state is not a fault but a poll: the
guest is parked on `ClockDxe + 0x11cbc`, `ldr w9,[x19]; tbnz w9,#0x0,` on bit 0 of the dword at
`0x12000c` — the literal first qword of ClockDxe's own `.data` object at RVA `0x27a98`, unrelocated —
in the range QEMU's `virt.flash0` serves as **writable zero memory**, so the driver's own `str` is the
only write that ever sets the bit it then waits on. A rail handshake against a clock controller QEMU
does not have, one layer below 4.160's `Clock_InitTarget`; the `DALLOG … Unable to set rail` row just
above it in the panel is the shape it would have and not proof. See `docs/08` step 4.163.

That suggestion is now withdrawn and the wall behind the handshake is named. One write of zero to the
polled word, made while the PC is inside the poll, releases the handshake in under a second — and the
run does not crash, it *diagnoses*: `HAL_clk_FabiaPLLEnableVote Activate Failure`, then
`DebugAssert`'s row carrying `4DB5DEA6-5302-4D1A-8A82-677A683B0D29` (the shared module GUID the blob
carries, not gauguin's `34F25731-…` — i.e. `ClockDxe` itself), then `ASSERT HALclkFabiaPLL.c +184: 0`,
and then it stops on `ClockDxe + 0xff4c`, which is `str xzr,[sp,#8]; ldr x8,[sp,#8]; cbz x8,.` —
edk2's `CpuDeadLoop`, entered by `bl 0xff2c` from `ClockDxe + 0x81d0` and terminal for the CPU. Two
runs drew the same three rows, against a no-write control that ends at `Unable to set rail` and stays
parked. So the ladder is three rungs deep on this guest and every rung is the same absence:
`Clock_InitTarget`'s `0xfffffffd` (4.160), the handshake that cannot complete (4.163), and now a named
Fabia PLL vote whose failure is unconditional — each the firmware correctly discovering that the
hardware it was written for is not there. That bounds what further instrumentation buys, which is the
useful result: faking clock votes one at a time is finite and uninformative, and the informative
question is on the phone, where the controller is real and the wall is the missing architectural
protocols at `DxeMain.c:593`. The stack also settles 4.163's other open item the other way round: at
the handshake the caller chain is three `ClockDxe` frames (`+0x3a48`, `+0x3e0c`, `+0x1540`) on five
`SdccDxe` frames (`+0xf768`, `+0x9c08`, `+0x7668`, `+0x21a4`, `+0x2d74`, all inside its 106,496-byte
image), with no `VcsDxe` address in the window — so the waiting driver is the SD-card controller and
the `VCS: Unable to set rail` row above it on the console is a neighbour, not the caller. The panel
gives order; only the stack gives nesting. See `docs/08` step 4.164.

**Step 4.165 is a correction of bookkeeping, and it is the one that decides how the phone's own
reading is to be used.** Step 4.163 closed by splitting the phone's 46-character `P2 SEQ` and the
panels' 69-character one into two builds — "the phone's is `work/out/boot-before-p2walk.img`, whose
inflated build is 7,348,232 B, against 7,536,648 B here, so this is a statement about two builds and
not about two machines" — and the second clause is wrong: the runs labelled "here" were handed
`/tmp/phone-payload.raw`, which is the gunzipped kernel of `work/out/boot-before-p2walk.img`
(`fb697f47…` → `d0919c00…`) and therefore the phone's own payload. The panels say so themselves: all
five carry `# payload /tmp/phone-payload.raw` and `# sha256 d0919c00…` on their header lines, and
`tools/qemu-panel-read.py` writes those from the file it is given. The 7,536,648 belongs to a build two
rungs later — the tree's current `Build/…/SILICIUM_UEFI.fd` inflates to it, and that volume is
byte-identical to the unflashed `work/out/usb-host/Mu-gauguin-xhci-host-gzip.img`. Three consequences
follow. **The 46 and the 69 are one payload read on two machines**, so the 27 `L`s are made by
something the machine supplies or fails to supply, and the emulator's reading is the control the
phone's is measured against rather than a sibling case. **The record's two inflated-size conventions
are one volume each**: `lzma`'s output is 8 bytes longer than `tools/fv-inventory.py`'s `inner` on
every image (`lz[8:] == inner` is `True`), the 8 being a prefix carrying the volume's own size field,
so 7,348,232 and 7,348,224 — and 7,536,648 and 7,536,640 — name one volume apiece. And **the deciding
field is on the payload**: `P2 STATS discovered=80 apriori=69/70 started=73 diag=7 noload=0` with a
69-character `SEQ` is 4.121's "walk and list both whole" row, read on the host for the build the record
says is installed on the phone. What is now first in the device window is the `P2 STATS` row beside
the phone's own 46-character `SEQ` — one row, on a screen already photographed — and the fork it also
settles is which build is in `boot`, since the record calls `90b21643…` (the `p2-variants` class,
which does carry `P2 WHY` and `P2 ERR`) "the payload in `boot`" against an on-device readback of
`ecc10a22…`. The one thing the correction does *not* disturb is the disassembly: `ClockDxe`'s FFS file
is byte-identical in the phone's volume and in `usb-host`'s (`4320c1d319b99897…`, 192,562 B, the vendor
blob `c200d38e…` verbatim at `+0x1c`), so the addresses steps 4.159-4.164 are written in hold on the
phone's payload too. See `docs/08` step 4.165.


**Risk:** **high, and this is the real wall.** No Bitra-family device has ever had a UEFI
port. The signed blobs are unlikely to load cleanly into a different DXE core on the first
attempt; expect a long debugging loop, and serial output is essential (the device has no
exposed UART — plan on the UEFI `ULogDxe` log buffer or on-screen debug). That is how it
went, and the on-screen half is the half that worked: the DEBUG build's console *is* the
framebuffer, so the firmware's own `DEBUG ()` strings are readable off the panel with no
UART and no shell. What it does not give is scrollback — the console clears itself when
it runs off the bottom, which on this payload it never does (92 rows of 100), and it is
write-only, so nothing can be read back after the fact. What does read it back is
`tools/qemu-panel-read.py`, which samples the region from a running mirror and joins the
screens into one stream; `docs/08` step 4.125 is the account of what that stream is and of
what a gap in it is not.

---

## P3 — Full UEFI with ACPI

**Why:** Windows does not read device trees. It needs ACPI tables describing the board, and
it needs the display, storage, USB host and input all working *inside UEFI* to install.

Work:

1. Add `Silicium-ACPI`'s Qualcomm Moorea/Rennell tables as a starting point, write the
   gauguin tables (DSDT/SSDT: UFS, XHCI, I2C, GPIO, buttons, thermal zones)
2. Bring up `DisplayDxe` + framebuffer
3. Bring up USB host (`UsbBusDxe`) — needed to install from a USB stick
4. Bring up `ButtonsDxe`, and a way to choose boot entries

**Gate:** a Windows 11 ARM64 installer boots off a USB stick and sees the internal UFS.

> **The gate's own artifact, as of Step 4.112 (2026-09-26).** The payload built to satisfy the
> "boots off a USB stick" half is `work/out/usb-host/Mu-gauguin-xhci-host-gzip.img` —
> **1,171,456 B, sha256 `f1a7106b76f98e11bb2608557e76085e1b3dcba86fda472c89bcefa1783f1c84`,
> unflashed**. It is the record payload's file set plus exactly three drivers (`XhciDxe`,
> `XhciPciEmulation`, `UsbInitDxe`) and a byte-identical `AcpiTables`, and its Apriori array is
> the same 70 entries. **This digest superseded `efc8e10d09f0f286…` on the same day**, and the
> reason is worth keeping: the earlier candidate had been built twenty-six hours before, from a
> tree predating Step 4.65, so its `DSDT` was 1,520 bytes against `boot`'s 5,280 and it still
> carried bitra's `QCOM0497` where URS0 now has `QCOM0A8B` — on the node its own three drivers
> bind through. It was audited against the wrong base and read as current for six steps. Two
> consequences for a reader of this plan: the sizes in the P3 narrative below are stale (the
> `DSDT` is 12,341 bytes, not 2,369), and **the gate is still unmet** — two of the three new
> drivers' dependency expressions cannot evaluate on this driver set, and nine architectural
> protocols the P2 assert is about are still absent — nine protocols, eight producers, the
> distinction the P2 row above draws. No USB stick can be seen yet.
>
> **Step 4.113 measured the gate's *other* half and found no obstacle of its own.** The storage
> chain the second clause needs — `UFSDxe`, `DiskIoDxe`, `PartitionDxe`, `Fat`, with `SdccDxe`
> and `EnglishDxe` — sits at Apriori **25–30** as one contiguous run, and not one of the six
> carries a depex, so the disk stack is promoted unconditionally and awaits nothing: its
> producers are all in the volume and its consumers all run in the first round. It still does
> not pass, because what the gate waits on is upstream of it — the `ASSERT_EFI_ERROR` at
> `DxeMain.c:593` that Step 4.108 and Step 4.109 located, which fires before BDS is entered.
> So "item 1 is done for UFS" below is true of the firmware and not yet true of the device.
>
> **Step 4.116 measured the trio the sentence above counts, and the count has no reading
> that fits all three.** "Two of the three new drivers' dependency expressions cannot
> evaluate on this driver set" is true if the two are the drivers that *carry* an expression
> — and then the third reads as unaffected, which it is not; and it is true if the two are
> the drivers that cannot run — and then the word "expression" is wrong for `XhciDxe`, which
> has none. Measured on the candidate, the three land **one in each of the three buckets
> `tools/depex-census.py` prints**, and that is why no pair of them shares a route:
> `XhciPciEmulation`'s stored depex is a thirteen-term AND naming eight of the nine absent
> protocols; `XhciDxe` carries no depex at all and is held by the UEFI 2.0 rule that requires
> all thirteen (`Dependency.c:221-234`); and `UsbInitDxe`'s one-term depex names
> `E722B03F-…`, defined by no header in the tree, so whether it is schedulable **cannot be
> judged from the image** — Step 4.105 narrowed its publisher to `UsbfnDwc3Dxe` and
> `UsbConfigDxe` and left that one question open. The bucket deltas from the record to the
> candidate are the measurement, not the prose: `0→1` waiting, `0→1` unjudgeable, `5→6` held
> by the no-depex rule. Nothing about the gate changes — none of the three can run.
>
> **Step 4.166 (2026-09-27) measured what the volume already contains for items 3 and 4, and one
> of them is not work to add.** The phone's volume holds **five FFS `APPLICATION` (0x09) files** —
> `MassStorage` (297,528 B), `BootManagerMenuApp` (98,404), `MsBootPolicy` (357,436), `UFPLoader`
> (22,580) and `ufpdevicefw` (443,974) — the same five and the same sizes in `usb-host`'s, and
> **none of them is in the Apriori array or could be**: the promotion loop matches only what the
> walk discovered and the walk is type-filtered to `DRIVER` and `DXE_CORE`, so an application is
> reachable only by the DXE core's loader at BDS's request. Microsoft's boot-policy application is
> therefore already in the image, and item 4's "way to choose boot entries" is not a driver to
> write but a BDS to reach — which is the same nine-name wall this section's blockquotes keep
> arriving at. The volume also carries the 36 `FREEFORM` blobs that platform data lives in: twenty
> `Panel_*.xml` panel tables, `QcomChargerCfg.cfg`, `BDS_Menu.cfg`, `uefipil.cfg` and a dozen boot
> logos and battery symbols. And item 3's USB-stick half has no PCI stack to build on: a 16-byte
> scan of both volumes finds **no** `PciRootBridgeIo`, no `PciHostBridgeResourceAllocation`, no
> `PciBusDxe` and no `PciHostBridgeDxe`, and every occurrence of the `PciIo` constant is a
> consumer's — `ConPlatformDxe`, `BdsDxe`, `BootManagerMenuApp` and `MsBootPolicy` in the phone's
> volume, plus `XhciPciEmulation` and `XhciDxe` in `usb-host`'s, the two this plan added. So the
> XHCI path is the whole of the PCI world in this firmware by design, and adding a PCI bus stack
> would be an FDF `INF` question plus a `PciHostBridgeLib` one, not a discovery one. See
> `docs/08` step 4.166.
>
> **Step 4.167 (2026-09-27) re-read that PCI scan's inputs from the files that define them, and the
> `PciHostBridgeDxe` GUID the paragraph above used is not that driver's.** Its `FILE_GUID` is
> `128FB770-5E79-4176-9E51-9BB268A17DD1` per `PciHostBridgeDxe.inf`, not `de375b25-…`; the
> resource-allocation GUID is `CF8034BE-6768-4D8B-B739-7CCE683A9FBE` per
> `Protocol/PciHostBridgeResourceAllocation.h:27-30`. The zero-hit result survives both corrections,
> and the scan is now complete instead of sampled: of the **fifteen** PCI-named protocol GUIDs the
> headers define, `PciIo` is the only one either volume carries (4 in the phone, 6 in `usb-host`),
> and of the **forty-nine** PCI-named `FILE_GUID`s in the tree's `INF`s the only nonzero row is
> `XhciPciEmulation` (`XhciDxe`'s `B7F50E91-…` reads `[0, 2]` outside that set) — so `NvmExpressDxe`,
> `UhciDxe`, `EhciDxe`, `SdMmcPciHcDxe`, `UfsPciHcDxe`, `SataController` and `IdeController` are all
> absent too, which is what bounds "this firmware has no PCI": the storage and USB stacks here are
> the Qualcomm non-PCI ones. The instrument is `tools/pci-guid-census.py`, which rebuilds both GUID
> maps from the tree on every run. Moreover no `DXE_DEPEX` in either volume names any of the 64
> scanned GUIDs — 27 files carry a depex in the phone's volume and 21 of them are `TRUE`, 29 and 22
> in `usb-host`'s, and the non-`TRUE` set is PCD, HII and `XhciPciEmulation`'s twelve architectural
> protocols, with no PCI term anywhere — so nothing in either image even *waits* on a `PciIo`
> producer, which is why the absence never appears as a depex failure. And the cost of a host bridge
> is now measured on both halves: the two `INF`s are in the tree, and the only `PciHostBridgeLib`
> instances are `PciHostBridgeLibNull` and a GoogleTest mock — there is no real implementation in
> this tree for any Qualcomm platform, so a host bridge is a library to write, not a line to add.
> `usb-host`'s XHCI pair is the reason item 3's USB-stick half needs none of that. See `docs/08`
> step 4.167.
>
> **Step 4.168 (2026-09-27) disassembled the references 4.167 could only count, and both of that
> step's inferences come out right — one of them now a measurement instead of an inference.** The
> paragraph above says every occurrence of the `PciIo` constant is a consumer's; that was read off
> the set of files carrying it, and reading the call sites says the same thing site by site: the
> phone's four files hold **seven** references and **not one** is an install — `ConPlatformDxe`
> `LocateDevicePath` at `0x2584`, and a `LocateHandleBuffer`/`HandleProtocol` pair each in `BdsDxe`
> (`0xa920`, `0xa950`), `BootManagerMenuApp` (`0x9950`, `0x9980`) and `MsBootPolicy` (`0x8dc8`,
> `0x8df8`), i.e. the BDS, the boot menu and the boot policy each enumerating PCI handles for a
> device list. So the sharper form of this section's claim is available now: the phone's payload does
> not merely lack a producer, it **asks for a PCI handle seven times and cannot answer once.** In
> `usb-host`'s volume the same four files are there with exactly **one** producer added —
> `XhciPciEmulation`'s `InstallMultipleProtocolInterfaces` of `PciIo` beside a
> `EFI_DEVICE_PATH_PROTOCOL_GUID` at `0x187c` — with `XhciDxe` around it in the standard binding
> shape (`OpenProtocol` at `0x1500`/`0x17f0`/`0x1bbc`, `CloseProtocol` at `0x1488`/`0x1564`, and a
> close-and-uninstall of its own `PciIo` at `0x18e8`/`0x1918` when the emulated device is stopped).
> So item 3's USB-stick half rests on a pair this plan added that is **complete on both sides by
> construction**: one file fabricates the PCI device, one binds to it. Second, **the open question
> this section has carried since 4.105 is closed**: 4.105 narrowed the publisher `UsbInitDxe`'s
> depex waits on to `UsbfnDwc3Dxe` or `UsbConfigDxe` and left "whether either candidate installs it"
> open; disassembled, `UsbConfigDxe` installs `E722B03F-B250-42CE-8EBD-5BD51812D037` at `0x3aa4`,
> `0x517c` and `0x52c8` and `UsbfnDwc3Dxe` only opens and closes it — so the publisher is the
> depex-less file promoted in the first round and the waiter is the depexed one judged in the second,
> and the affirmative ordering 4.105 hoped for is the measured one. The same pass found where the
> XHCI pair comes from: the five USB `PE32` sections in `usb-host`'s volume are each byte-identical
> to one prebuilt under `Binaries/`, `UsbConfigDxe` and `UsbfnDwc3Dxe` to gauguin's and `XhciDxe`,
> `XhciPciEmulationDxe` and `UsbInitDxe` to bitra's, and `Binaries/gauguin/QcomPkg/Drivers` has none
> of those three — which is why the phone's volume carries neither XHCI file nor `UsbInitDxe`, and
> why `UsbConfigDxe`'s publisher has no consumer there. The instrument is `tools/guid-refs.py`, new
> here, which resolves the `ADRP`+`ADD` pair that materialises a GUID's address and reads which
> `EFI_BOOT_SERVICES` slot the register is handed to — the slot, not the presence, is the answer, and
> an install slot versus `LocateProtocol`/`OpenProtocol` is what separates a publisher from a
> consumer. A call site is a fact about the binary, not about the run: nothing here says any of these
> paths is reached on the device, and the phone payload's park inside `ClockDxe`'s `CpuDeadLoop`
> (4.164) sits upstream of all of them. See `docs/08` step 4.168.
>
> **Step 4.169 (2026-09-27) found the device's own promotion order already in the repository, and it
> is the reference for every later ordering question.** The FREEFORM file 4.166 could not name
> (`6A69BA33-B140-5742-ABC9-0C5D03920B42`, at `0x4f8f40`) is the **stock firmware's a-priori
> array** — 74 entries, 1,184 bytes = 74 × 16 with no header, RAW-identical to the XBL file
> `device/dxe-inventory.txt:7` records as `fc510ee7-… raw 1184B`, and every one of its 74 entries
> names a `.ffs` present in `device/dxe`. Its UI section is the UTF-16LE of the a-priori GUID
> *string*, because that is the name the XBL raw file has and `tools/make_uefi_platform.py` re-emits
> it verbatim under a generated file GUID. It is **inert** for the a-priori read — `Dispatcher.c:2062`
> calls `Fv->ReadSection (Fv, &gAprioriGuid, …)`, which selects by file GUID — so the volume can
> carry the stock order without anything reading it, which is why it went unnoticed. 4.166's "not a
> second copy of the array" was a match against **our** array, whose second entry is `PcdDxe` where
> the stock array's is `EnvDxe`. `tools/apriori-stock-diff.py`, new here, aligns the two by name
> (the stock build names files with the module's own id, so a GUID comparison would call every
> driver different): **54 of the 74 entries are the same sequence in the same order**, including the
> whole architectural-protocol front and `ClockDxe, ShmBridgeDxe, ScmDxe` into the storage band, and
> the differences are the boards' own families — Qualcomm's `PwrUtilsDxe`, `VcsDxe`,
> `FeatureEnablerDxe`, `QcomWDogDxe`, `DisplayDxe`, `FvDxe`, `ADSPDxe`, `PILProxyDxe`, `PILDxe`,
> `CPRDxe`, `ASN1X509Dxe`, `SecRSADxe`, `VerifiedBootDxe`, `FontDxe`, `QcomBds`, `FvSimpleFileSystem`
> against Mu's `PcdDxe`, `VariableRuntimeDxe`, `ResetSystemRuntimeDxe`, `SecurityStubDxe`,
> `HashDxe`/`CipherDxe`/`RngDxe`, `BdsDxe`, `SimpleFbDxe` and the five USB device-mode drivers. The
> part that bears on the plan is that the two P3 items still open now have **positions in the stock
> order**: `DisplayDxe` is stock entry **41**, in the power/TZ band between `PmicDxe` and
> `WatchdogTimer`, where our build promotes `SimpleFbDxe` at entry **60** in the console tail; and
> `QcomBds` is stock entry **58** with `FontDxe` immediately before it, where ours promotes `BdsDxe`
> at 44 and carries no font driver at all. Item 2's driver is a build flag with a stock precedent
> and a known position (`USE_CUSTOM_DISPLAY_DRIVER`'s `= 1` branch, which moves nine entries), and
> item 4's boot-entry machinery is two adjacent stock entries rather than an unnamed wall — though
> neither says either driver would install if promoted. And "stock-only" is a statement about the
> promotion order, not about what the volume carries: **`PwrUtilsDxe` (32,824 B), `VcsDxe` (49,198 B)
> and `FeatureEnablerDxe` (32,836 B) are in both volumes as `DRIVER` files built from
> `Binaries/gauguin/QcomPkg/Drivers/` and are not in `APRIORI.inc`**, while the other eleven
> stock-only entries are in neither volume — and nine of those eleven (`DisplayDxe`, `ADSPDxe`,
> `PILProxyDxe`, `PILDxe`, `CPRDxe`, `QcomWDogDxe`, `SecRSADxe`, `VerifiedBootDxe`, `QcomBds`) have
> a packaged `.efi` and `.inf` under `Binaries/gauguin/QcomPkg/Drivers/` and are held out by a line
> of `DXE.inc` (`CPRDxe` and `DisplayDxe` behind the display flag; the rest named in `DXE.inc`'s own
> header comment as packaged-but-not-listed, with an invitation to add the line). Only `FvDxe` and
> `FontDxe` are not in the tree at all. That matters because of where they sit: `VcsDxe` is stock entry 21, immediately
> before `ClockDxe` at 22, and `PwrUtilsDxe` is 17 — so the batch this build runs goes from `PdcDxe`
> straight into `ClockDxe`, which is exactly where the phone payload parks (4.164). This step does
> not claim the two are connected, and a Fabia PLL vote failing is not obviously about either
> driver; what it says is that the stock batch was not ours minus nothing, and that promoting the
> three is a one-line `APRIORI.inc` change with the machinery already in place
> (`tools/make_uefi_platform.py --apriori-move`, `tools/build-apriori-variant.sh`). See `docs/08`
> step 4.169.
>
> **Step 4.170 (2026-09-27) gave 37 of the drivers in the volume their stock dependency expression
> back, and the measurement says that is one binding depex and one no-op rather than a
> re-ordering.** `tools/make_xbl_binaries.py` had been shipping `PE32|<name>.efi|<mtype>` and nothing
> else, while the extraction's `<name>.ffs` carries the stock `DXE_DEPEX` section beside the `PE32` —
> so **no** driver this build packaged from the extraction had a dependency expression, and the DXE
> core reads that as UEFI 2.0 (`Dispatcher.c:892`) and releases the driver on
> `CoreAllEfiServicesAvailable` (`Dependency.c:221-225`). Measured: the volume's 42
> `Binaries/gauguin`-resolved files went from **0 to 37** depex sections, 0 lost, and the whole
> volume from 29-with to 66-with. The part that matters is what that binds: read out of the artifact
> rather than out of `APRIORI.inc`, **35 of the 37 sit in the 70-entry a-priori array**, where
> `Dispatcher.c:2114-2125` sets `DriverEntry->Dependent = FALSE` before the depex is ever consulted —
> so for those 35 the restored expression is dead code. The two that bind are exactly the two 4.169
> had singled out by position and by their absence from `APRIORI.inc`: **`VcsDxe`**
> (`AE37B942 AND gEfiChipInfoProtocolGuid`, both producers in the array) and **`PwrUtilsDxe`**
> (`TRUE`). Nothing in the change can make a driver disappear; it can only delay one, and the three
> depex terms with no publisher in the volume are consumed only by promoted drivers, which is why
> they cannot stall anything. This does **not** claim to explain 4.164's `HAL_clk_FabiaPLLEnableVote`
> park, and `VcsDxe` remains un-promoted, so the batch still goes from `PdcDxe` into `ClockDxe`. See
> `docs/08` step 4.170.
>
> **Step 4.171 (2026-09-27) found that the one-line change 4.170 pointed at could not have been made
> by the tool as it stood: four rows of `tools/make_uefi_platform.py`'s `EXTRA_DRIVERS` table have
> never done anything.** The table lists `PwrUtilsDxe`, `VcsDxe`, `FeatureEnablerDxe` and `MacDxe`
> twice — once for `DXE.inc`, once for `APRIORI.inc` — and just after any generation all four are in
> `DXE.inc` and **none** is in `APRIORI.inc`, with the generator reporting nothing. The cause is one
> `referenced = set()` shared by both files where it has to be per file: the `DXE.inc` pass inserts
> each path and records it, and the `APRIORI.inc` pass then skips the row on `path in referenced`,
> which is a bare `continue` rather than a `dropped` entry — so the miss left no trace in the
> generated file or on stdout. It is not a missing anchor; all four anchors resolve against
> `suryaPkg/Include/APRIORI.inc` (checked first, and the guess was wrong). What settles the intent is
> the stock firmware's own 74-entry a-priori array, which can now be resolved by name 74 of 74:
> it promotes `PwrUtilsDxe`, `VcsDxe` and `FeatureEnablerDxe`, and **not** `MacDxe` — three of the
> four rows describe what this phone's firmware does. The repair is `referenced` per file (with the
> two sets still unioned for the orphan report, whose count is 11 either way — the one place the bug
> would have surfaced is the one place it could not) plus `--apriori-extras`, **off by default**,
> because promotion is a dispatch-order change and the only one in this series that *discards* a
> depex 4.170 had just restored: `Dispatcher.c:2114` sets `Dependent = FALSE`, so promoting `VcsDxe`
> means `VcsDxe` no longer waits for `ChipInfo`. The default regeneration of the tree is otherwise
> unchanged (72 `INF` lines before and after, `DXE.inc` byte-identical) and now writes the four
> withheld rows into its header instead of staying quiet about them; `--apriori-extras` adds exactly
> four `INF` lines. Built and gated as `tools/build-apriori-variant.sh apriori-extras`:
> `work/out/p2-variants/Mu-gauguin-apriori-extras-gzip.img` (`2a5b6326cda68457…`, 1,144,832 B), whose
> array the build's own gate reads back at **74 entries** against the payload of record's 70, with the
> alignment to the stock array moving 54 → 57, while the `usb-host` payload stays at 70. See `docs/08`
> step 4.171.
>
> **Step 4.172 (2026-09-28) measured the class of driver this repository has no instrument
> for at all: the ones no table ever names.** `tools/make_xbl_binaries.py:219-227`'s
> `present_drivers()` iterates the `DRIVERS` table and asks the extraction about each name
> in it, and `tools/make_uefi_platform.py`'s orphan line is `have - referenced` with `have`
> built from that same table — so a driver whose `.efi` sits in `device/dxe` but whose name
> is not a key is neither packaged nor reported, by anything. The table's own header comment
> says why the class exists: it was *"Derived by matching against
> `Binaries/surya/QcomPkg/Drivers`"*, so the blind spot is exactly `extraction − surya` and
> it is invisible by construction. `tools/xbl-unmapped.py`, new, measures it: of the 86
> `.efi` in `device/dxe`, **55 are packaged, 22 are built from tree source, and 9 are named
> by nothing** — `RscRtDxe`, `SCHandlerRtDxe`, `FvSimpleFileSystem`, `VariableDxe`,
> `ResetRuntimeDxe`, `FvDxe`, `ASN1X509Dxe`, `FontDxe`, `MiTokenDxe`. The device's own
> a-priori array promotes eight of the nine (entries 2, 3, 28, 33, 39, 42, 48, 57), so the
> phone ran them; two of the eight (`VariableDxe`, `ResetRuntimeDxe`) are substitutions for
> the Mu drivers this volume ships at `DXE.inc:12` and `:15`, and the two arrays name
> neither of the other's — which makes them a choice of implementation rather than a
> missing service. The tool's first run was wrong by one in each direction and the error is
> recorded rather than quietly fixed: it scored any `BASE_NAME` hit as "the tree builds
> this", and `FvSimpleFileSystem` refutes that — source at
> `Mu_Basecore/MdeModulePkg/Universal/FvSimpleFileSystemDxe/`, INF listed by
> `MdeModulePkg.dsc:487`, and 0 occurrences of the name anywhere in `gauguinPkg`. A source
> row now also requires the INF to be listed by `DXE.inc`, so the count is 22 and 9. The
> same array settles a P3 candidate gap the other way: it promotes `DiskIoDxe` 25,
> `PartitionDxe` 26, `UFSDxe` 30, `Fat` 31 and **no SCSI disk driver**, and `device/dxe`
> has no `ScsiDisk*` at all — because `UFSDxe.ffs`'s 22-byte `DXE_DEPEX` is a single `PUSH`
> on `gEfiSMEMProtocolGuid` and the `BlockIo` GUID is in its image and not in its depex, so
> the UFS is published as a block device with no SCSI layer above it. The half of the gate
> that says *sees the internal UFS* has no missing driver; the half that says *boots off a
> USB stick* is still the `xhci-host` work. See `docs/08` step 4.172.
>
> **Step 4.173 (2026-09-28) read the dependency structure of the payload that would be
> flashed next** — `work/out/usb-host/Mu-gauguin-xhci-host-gzip.img`, the one carrying the
> USB host stack — and it has **no term this volume cannot satisfy**: 83 dispatcher-visible
> files, 66 with a depex of which 56 are promoted (depex inert) and 10 gated, 4 on the UEFI
> 2.0 rule, and 0 gated on a protocol no file in the payload produces. The three GUIDs the
> census could not name because no header defines them were narrowed by a carrier scan:
> `UsbInitDxe`'s single term is carried by `UsbConfigDxe` and `UsbfnDwc3Dxe`, **both
> a-priori** (`APRIORI.inc:96`, `:88`), and 4.168 had already identified `UsbConfigDxe` as
> the publisher by its call sites. The three staged sibling blobs take their depexes from a
> binary `.depex` beside the `.efi` — `XhciPciEmulationDxe.depex` is 13 `PUSH`es ANDed and
> `UsbInitDxe.depex` is one — and **not** from the `[Depex] TRUE` their INFs carry, which is
> why 4.170's restore-the-stock-`DXE_DEPEX` repair cannot reach this sourcing path: bitra
> ships no `.ffs`. `XhciDxe` is the one file whose depex exists nowhere, on the UEFI 2.0
> rule, and that is bitra's own condition rather than this port's. The ordering the USB half
> depends on is settled by `BdsEntry.c:3-5` rather than by the a-priori array: `BdsDxe`
> installs `gEfiBdsArchProtocolGuid` **when it is dispatched**, `BdsEntry` runs only after
> DxeCore finishes the DXE phase, and `XhciPciEmulation`'s depex names that protocol — so
> the emulated host controller is installed during dispatch, before BDS's connect-all sweep.
> The corollary is a warning: promotion sets `Dependent = FALSE`, so the array must **not** be
> used to "help" `XhciPciEmulation`, whose thirteen-term depex is load-bearing. No firmware
> was built and nothing was flashed. See `docs/08` step 4.173.
>
> **Step 4.174 (2026-09-28) gave every depex term 4.173 could not judge a named publisher inside
> the volume.** The census's band — *"gated, and the depex names a protocol no header defines"* —
> was partly an artifact of the instrument: two of the five directories `load_guid_names()` walked,
> `QcomPkg/Include` and `SiliciumPkg/Include`, **are not directories at the tree root** (the
> packages are at `Silicon/Qualcomm/QcomPkg/` and `Silicon/Silicium/SiliciumPkg/`), and
> `Silicon/Qualcomm/QcomPkg/QcomPkg.dec` was not in the `.dec` list either, so **no Qualcomm GUID
> had ever had a name in that tool** — 745 → 817 GUIDs once corrected. The term that costs is
> `B0760469-970C-487A-A4B5-28DB7B45CEF1` = `gEfiChipInfoProtocolGuid` (`QcomPkg.dec:70`); the band
> heading and the run's summary line are unchanged either way, so the repair removed a false
> unknown from a row and moved no count. `tools/guid-refs.py` gained the two things it needed: its
> volume loader could not read **any** payload this project builds (its two-shape reader versus the
> three-layer boot image — now delegates to `tools/fv-inventory.py`), and a new `--extracted DIR`
> mode serves `device/dxe/` directly. With those, the install-vs-locate disassembly names a
> publisher for all three GUIDs: **`DALSys` installs `AE37B942`** (one install site, 19 consumers
> including `VcsDxe`), **`ChipInfo` installs `B0760469`**, **`UsbConfigDxe` installs `E722B03F`**
> at three sites. All three publishers are promoted by the payload's own a-priori array — `DALSys`
> entry 11, `ChipInfo` 13, `UsbConfigDxe` 57 of 70, read out of the artifact and not from
> `APRIORI.inc` — so each runs before the consumer gated on it, and `VcsDxe`'s
> `AE37B942 AND gEfiChipInfoProtocolGuid` has two producers that are promoted. 4.168's and 4.170's
> earlier readings of those same two GUIDs are confirmed by a different axis. One sharpening:
> `XhciDxe`, the no-depex file in the UEFI 2.0 band, **locates** `E722B03F` at VA 0x01960 rather
> than running blind. No firmware was built. See `docs/08` step 4.174.
>
> **Step 4.175 (2026-09-28) opened the half of the first P3 clause that no step had ever read,
> and found the platform side of it already complete.** The clause is *"a Windows 11 ARM64
> installer boots off a USB stick and sees the internal UFS"*, and fifteen steps had measured
> only the controller; `grep -c` over all nine docs returns **0** for `USB Storage`,
> `RegisterDefaultBootOptions`, `MsBootPolicy`, `ConnectConInEvent`, `UsbControllerInitGuid` and
> the rest of the boot-option vocabulary. Two of the clause's three parts are on the platform
> side and both are done: `MsBootOptionsLibRegisterDefaultBootOptions`
> (`MsBootOptionsLib.c:240`) registers `L"USB Storage"` against `gMsBootPolicyFileGuid` with
> `Position = (UINTN)-1` (**append**) and `LOAD_OPTION_ACTIVE`, so the option is in `BootOrder`
> and active from the first boot — it cannot be a device path, because the path of a stick that
> is not plugged in yet cannot be named in advance — and the application it names is **in the
> volume**: `MsBootPolicy`, FFS type `0x09`, 357,436 B, present in both built images in 126 and
> 123 files. The instrument says otherwise and is wrong: a raw scan for the 16 bytes returns **0
> in both artifacts**, because `FVMAIN_COMPACT` is compressed; the positive control `BdsDxe`
> (`6D33944A-EC75-4855-A54D-809C75241F6C`) reads 0 by the same scan and is present in the same
> roster. **The rule this leaves is that a file-GUID lookup must go through
> `tools/fv-inventory.py`'s decompressed roster**, the second time in two steps that a shape
> mismatch produced an "absent" for something present. Nor is the target a stub:
> `MsBootPolicyEntry` switches `'U'` to a USB-only sequence, calls `EfiBootManagerConnectAll ()`
> at `:636` — *"Connect All is required for this type of boot"* — and selects `FilterOnlyUSB`
> with a 6-second `PauseToLetUsbDrivesEnumerateThroughHubs`. That call is a **dispatch retry**
> (`BmConnect.c:23-55`, `do { … } while (!EFI_ERROR (gDS->Dispatch ()))`) and still cannot
> dispatch `XhciPciEmulationDxe` (12 of its 13 terms absent) or `XhciDxe` (no depex ⇒ all 13),
> so the boot-option route and P2's assert are **one blocker, not three**. A second, independent
> reason the controller is down is new: the `gUsbControllerInitGuid` group hook is dormant here,
> because `PcdConInConnectOnDemand|TRUE` (`SiliciumPkg.dsc.inc:102`) makes `BdsReadKeys` return
> immediately, connecting a console is a `ConnectController` and not a read, and the platform's
> own key handling bypasses ConSplitter entirely via the keypad's STI. Control: `UsbConfigDxe`
> is in **6 of 6** reference XCHI stacks and `UsbInitDxe` in 4 of 6, which says which of the trio
> a later step should spend time on. No tool was changed and no firmware was built. See `docs/08`
> step 4.175.
>
> **Step 4.176 (2026-09-28) proved dependency ordering cannot be the XCHI obstruction, and removed
> the repair that was going to be built for it.** 4.174 left one thing open — whether `XhciDxe`,
> released by the UEFI 2.0 rule with no depex at all, retries its `LocateProtocol` on `E722B03F` if
> it runs before `UsbConfigDxe` installs it. The natural repair is a reorder: `UsbConfigDxe` is at
> **index 57** of our a-priori array and both XCHI files are in neither array, and
> `tools/build-apriori-variant.sh` plus `make_uefi_platform.py --apriori-move` already exist to do
> it. **`Dispatcher.c:1062-1216` says the worry cannot happen.** The dispatch loop is
> `do { while (!IsListEmpty (&mScheduledQueue)) { …CoreStartImage… }  // :1066
> for (…) if (CoreIsSchedulable (…)) … } while (ReadyToRun)  // :1193, :1216` — every depex is
> evaluated at `:1204`, after the queue at `:1066` has been drained to empty — and
> `CoreFwVolEventProtocolNotify` (`:1860`) fills that queue with the **whole** promoted batch in one
> pass (`:2107-2126`, `Dependent = FALSE` at `:2114`). So every promoted driver's entry point has
> returned before any non-promoted driver is first considered: `UsbConfigDxe` (57) has already
> installed `E722B03F` at its three sites when `XhciDxe`'s locate at VA `0x01960` runs. All thirteen
> terms hold the same way — `ArmCpuDxe` 6, `MetronomeDxe` 8, `ArmTimerDxe` 9, `RuntimeDxe` 5,
> `VariableRuntimeDxe` 31, `ResetSystemRuntimeDxe` 34, `WatchdogTimer` 36, `SecurityStubDxe` 37,
> `EmbeddedMonotonicCounter` 38, `RealTimeClock` 39, `BdsDxe` 44, and the thirteenth,
> `gEfiDriverBindingProtocolGuid`, published by whichever promoted `DRIVER` installs its own binding
> first inside the same drain (DxeCore only consumes it — `DxeMain.inf:149`). **Corollary that
> matters more than the ordering: `P2 SEQ` cannot see either XCHI driver.** Its letter string is
> `mP2Apriori` characters long, one per *promoted* entry (`:2270-2280`), so
> `tools/apriori-index.py` will report them absent — right about the string, wrong about the run.
> The rows that carry them are `P2Tick`'s `K` lines (`:659-682`), which fire for every dispatch
> attempt including the non-promoted ones, since those enter the same queue via
> `CoreInsertOnScheduledQueueWhileProcessingBeforeAndAfter` (`:1242`). *Released* and *succeeded*
> remain different questions. Beside it, the reciprocal of 4.172: of the 11 drivers 4.170 held out
> that have a stock `DXE_DEPEX`, **eight are promoted by the handset's own array** — `QcomWDogDxe`
> 35, `DisplayDxe` 41, `ADSPDxe` 43, `PILProxyDxe` 44, `PILDxe` 45, `CPRDxe` 46, `VerifiedBootDxe`
> 50, `QcomBds` 58 — and six of them are one contiguous run (41–46) our volume carries none of, five
> held out by `DXE.inc` and the sixth, `FvDxe`, named by nothing in this repository. `MinidumpTADxe`,
> `QcomMpmTimerDxe` and `VibratorDxe` are in no stock array at all. The handset promotes **no XCHI
> driver**, so the stock order cannot validate that half of P3 — and both orders put BDS before
> `UsbConfigDxe` (58 < 65 stock, 44 < 57 ours), so the USB region was not rearranged. Instrument:
> `tools/apriori-stock-diff.py --index`. No firmware was built. See `docs/08` step 4.176.
>
> **Step 4.177 — both XCHI drivers are not merely *released* into a complete protocol database but
> *started*, and the dispatcher's own rows say so.** 4.176 closed on a limit in its own words:
> *"Released and succeeded are different questions, and this step answers only the first."* The
> treatment recipe of 4.163 (`gdbprobe26.py`, `/pmic/target`'s stale DALSys record suppressed at
> `DALSys+0x335c`, here with `--base 0x9c40d000` read off *this* guest's own exception dump) applied
> to `work/out/usb-host/Mu-gauguin-xhci-host-gzip.img` reaches the ordinary pass and prints
> `K 73 Ss 67/69 free=1024 BEB12BEE-…`, `K 74 Ss 68/69 free=1024 B7F50E91-…`,
> `K 75 Ss 69/69 free=1024 0A134F0E-…` — `XhciPciEmulation`, `XhciDxe` and `UsbInitDxe`, each
> returning `EFI_SUCCESS`. `P2Tick`'s second letter is the attempt's own status class
> (`P2WhyLetter`, `:555-592`) and `mP2Started` is incremented at `:1158-1159` *before* the row prints
> at `:1167`, so the numerators 67/68/69 already count those three. Its digest
> `P2 STATS discovered=83 apriori=69/70 started=76 diag=7 noload=0` closes against the census's own
> `dispatcher-visible files (DRIVER=83): 83` — 76 + 7 = 83 — and `P2 NOLOAD total=0` says nothing was
> dropped silently. No earlier instrument could have measured this: on the plain panel the same
> payload dies at Apriori slot 18, the phone payload's own wall, and with the four loader seeds added
> it dies on 4.161's wall — `Synchronous Exception at 0x000000009C41046C`, `FAR 0xAFAFAFAFAFAFAFAF`,
> `[ 1] AdcDxe.dll`. `P2 SEQ` is 69 characters on the 80-file and the 83-file payload alike and
> **byte-identical** between them (the older build prints no `P2 WHY`, so only `SEQ` crosses), because
> 69 is what was *promoted* while the array holds 70; its six non-`s` characters are the six promoted
> start failures at positions 28/35/47/48/58/61, and the run's **seventh** failure (`AcpiPlatform`,
> `K 83`) has no character in the string at all — so the string is not merely harder to read than the
> `K` rows, it is incomplete in a direction that would have been invisible. The array's 70th and
> unmatchable entry now has a name: slot 0, `D6A2CB7F-6A18-4E2F-B43B-9920A733700A`, is `DxeCore` —
> the only one of the 70 whose FFS file is not an `FV_FILETYPE_DRIVER` — which is what
> `P2 APRI matched=1..69 unhit=1` refers to and why SEQ position *p* and `K` row *p* name the same
> driver. And **the seventh row is not a failure**: `Aborted` is `EFI_ABORTED` = `ENCODE_ERROR (21)`,
> while `00000001` is `EFI_REQUEST_UNLOAD_IMAGE` = `DXE_ERROR (1)` rendered by `BasePrintLib`'s
> `int`-width `%08X` fallback (`PrintLibInternal.c:1035-1063`) — the exit `AcpiPlatform.c:251`
> returns **on success**, after finding, checksumming and installing all six tables. The cause is the
> fourth added file: the XCHI volume alone carries `AcpiTables`
> (`7E374E25-8E01-4FEE-87F2-390C23C606CD`, 13,702 B), which `PcdAcpiTableStorageFile` names
> (`MdeModulePkg.dec:1511`); the phone's volume has none and its driver takes the `:191`
> `EFI_ABORTED` exit. So **the ACPI half of P3 is further along than any step had measured**, and the
> USB half has its first positive reading — but *started* is not *bound*: an entry point returning
> `EFI_SUCCESS` is not a controller handle and not an enumerated USB device, no row carries a
> `ConnectController` outcome, and whether `XhciDxe` binds to `XhciPciEmulation`'s published root
> bridge under `EfiBootManagerConnectAll` is the next question. Three of the seven failures are
> artifacts of this project's own seeds — `AdcDxe` the `/pmic/target` suppression itself, `LimitsDxe`
> the `CmdDbDxe` AOP gate against a window that is RAM holding zero here, `AcpiPlatform` the added
> tables — and must not be read as regressions. Instrument: `work/out/qemu-probe-4.177/run31.sh`;
> `tools/depex-census.py`, `tools/fv-inventory.py` (`--roster`, `--acpi`, `--dump-fvmain`) and
> `tools/apriori-stock-diff.py --index` were read, not modified. No tool was changed, nothing was
> flashed and no firmware was built. See `docs/08` step 4.177.
>
> **Step 4.178 — the three XCHI drivers' gates are now all named, and `XhciDxe`'s is not a depex at
> all.** 4.177 answered *started* and closed on *bound*; neither it nor 4.176 asked **what made the
> three schedulable**, which is decidable from the volume alone and needs no guest. Measured with
> `tools/fv-apriori.py`'s own `walk_volume` over the inner FV (`/tmp/fv-usb-177.bin`, `sha256
> dbeb98ab…`, 126 files): `XhciPciEmulation` @`0x34a628` `DXE_DEPEX` 234 B + `PE32` 45,056 B,
> `UsbInitDxe` @`0x3b8978` `DXE_DEPEX` 18 B + `PE32` 32,768 B, and **`XhciDxe` @`0x355760` with
> `PE32`, `USER_INTERFACE` and `VERSION` sections and no `DXE_DEPEX` at all** — not an omission of
> this project's packaging: its INF's `[Binaries.AARCH64]` is one line, `PE32|XhciDxe.efi|*`, and no
> `XhciDxe.depex` exists beside the `.efi` while both siblings have one. Every section payload hashes
> equal to the Bitra source `tools/make_xbl_binaries.py:142` copies. The two depexes are pure
> conjunctions — `UsbInitDxe`'s is the single term `E722B03F-B250-42CE-8EBD-5BD51812D037`, and
> `XhciPciEmulation`'s 234 bytes are **thirteen** terms, now all named for the first time
> (`MdePkg.dec:1183-1223`, `:1550`), whose set is exactly
> `{gEfiDriverBindingProtocolGuid} ∪ (mArchProtocols[] − {Capsule})` — and the only 234-byte depex in
> the volume. Because `XhciDxe` has none, `Dispatcher.c:892` leaves `Depex` NULL and
> `CoreIsSchedulable` (`Dependency.c:221`) takes `CoreAllEfiServicesAvailable`
> (`DxeProtocolNotify.c:81`), i.e. one predicate over all **thirteen** `mArchProtocols[]` —
> `Capsule` included, and `Capsule` is exactly the one term `XhciPciEmulation`'s list omits, so the
> one document in the tree that looks like an authoritative arch-protocol list is short by the one
> entry the other route turns on. `tools/arch-protocol-census.py` settles it: **13 present, 0
> absent**, `Capsule` produced by `CapsuleRuntimeDxe` (`42857F0A-…B840`, 21,612 B, `ap42 s`, the only
> Capsule-family file in the roster) — which 4.177's `K 74`/`K 75` had already *implied* without
> saying. `gEfiDriverBindingProtocolGuid`, the depex's first term, is installed by no file in
> `Mu_Basecore/` (`DxeMain.inf:149` is `SOMETIMES_CONSUMES`); it comes from the first promoted
> `DRIVER` to publish its own binding, by 4.176's drain. Also corrects one sentence of 4.177's
> `provenance limit` bullet — `find . -name 'XhciDxe.inf'` returns **40** hits and `uefi/Binaries/`
> **exists**, so the evidence was wrong though the conclusion holds: all 40 resolve via
> `git check-ignore` to `.gitignore:8:work/` and the untracked-by-`work/` `Binaries` tree carries no
> XCHI driver. *Schedulable* is a third verb and joins *released* and *started*; all three stop short
> of *bound*. Instrument: `tools/fv-apriori.py`, `tools/arch-protocol-census.py`,
> `tools/depex-census.py`, `tools/fv-inventory.py --roster`; none modified. No guest was booted, no
> firmware was built. See `docs/08` step 4.178.

> **Step 4.179 — the whole graph of `E722B03F` is now measured, and its publisher's own dependency is
> not satisfiable from its own volume.** Three steps have rested on the premise that `E722B03F` is
> published by `UsbConfigDxe`; 4.174 asserted three install sites and no step had read them off the file
> the volume carries. Read off the inner FV of `work/out/usb-host/Mu-gauguin-xhci-host-gzip.img`
> (`/tmp/fv-usb-177.bin`, `sha256 dbeb98ab…`, re-dumped for this step and byte-identical to what 4.177
> booted): the publisher is FFS `0983C7F2-0EF3-5EC4-83AD-3B32DDEB1E60` @`0x3a58f0`, type `0x07`,
> 77,958 B, sections `DXE_DEPEX` 76→72 + `PE32` 77,828→77,824 + `USER_INTERFACE` 30→26, both payload
> hashes equal to the tracked `uefi/Binaries/gauguin/QcomPkg/Drivers/UsbConfigDxe/` files — **not** the
> Bitra `CD823A4D` / `UsbConfigDxe.hostmode.efi` (94,208 B) that 4.174's citation names and that no
> part of this payload carries. `tools/guid-refs.py` gives the whole graph: **one publisher, four
> consumer drivers, twelve sites** — `UsbfnDwc3Dxe` ×4 (two opens, two closes), `XhciPciEmulation` ×3
> (`0x01488` close, `0x014e0`/`0x019e0` open), `XhciDxe` ×1 and `UsbInitDxe` ×1 (`LocateProtocol`),
> against three `InstallMultipleProtocolInterfaces` in `UsbConfigDxe`. The three installs disassemble
> identically — `gBS` from `.data 0x11590`, `[vtable + 328]` (slot 41, against `+320` = `LocateProtocol`
> for `XhciDxe`/`UsbInitDxe` and `+280` = `OpenProtocol` for `XhciPciEmulation`/`UsbfnDwc3Dxe`), the GUID
> constant at `.data 0x11098`, `x3 = NULL` so each call installs exactly one protocol — and they sit in
> one function, `UsbStartController` (`0xe977`), whose three failure strings name the three handles: the
> bare `%r` path (`0xe8e2`) for the controller handle, `(Peripheral Client Handle)` (`0xea2d`) and
> `(Host Client Handle)` (`0xead1`) for the two client handles, which index a two-record array at
> `.data 0x112b8` of stride `0xd8` tagged `usbc`, each install followed by `ConnectController`. The
> driver's own `DXE_DEPEX` (72 B, `sha256 9f1382dd…`) is a four-term conjunction — and **the record has
> been spelling all four with their first three fields byte-swapped**, which is why `guid-refs.py`
> returns *0 occurrences* for each of them and why `depex-census.py` could not resolve the file.
> Corrected, three of the four are named in this tree: `B0760469-970C-487A-A4B5-28DB7B45CEF1` =
> `gEfiChipInfoProtocolGuid` (`QcomPkg.dec:70`, published by `ChipInfo` `453C9622`),
> `F4E5C7D0-D239-47CB-AACD-7F66EF763238` = `gEfiSMEMProtocolGuid` (`:60`, `SmemDxe` `94527566`), and
> `157A5C45-21B2-43C5-BA7C-822FEE5FE599` = `gEfiPlatformInfoProtocolGuid` (`:67`,
> `PlatformInfoDxeDriver` `09EE56ED`, twelve consumers including `UsbConfigDxe` itself). **The fourth,
> `EB97088E-CFDF-49C6-BE4B-D906A5B20E86`, occurs zero times in the volume** — and zero times in the
> phone's own inner FV (`/tmp/fv-stock-p2walk.bin`, 7,348,224 B, `sha256 c8f57e46…`) as well, while the
> other three are present in both. `QcomPkg.dec` defines 76 GUIDs and this is not one of them. Yet the
> 4.177 panel reads `K 57 Ss 53/69 free=1024 0983C7F2-…` — `UsbConfigDxe` reaching `CoreStartImage` and
> returning success — and `CoreIsSchedulable`'s `EFI_DEP_PUSH` pushes `FALSE` for a GUID
> `CoreLocateProtocol` (`Hand/Locate.c`, `mProtocolDatabase` only) cannot find, with all four pushes
> evaluated before any AND. Three candidate routes are named (the `Depex = NULL` branch at
> `Dispatcher.c:892` for any `ReadSection` failure that is not `PROTOCOL_ERROR`; a run-time-constructed
> GUID; a HOB/PEIM hand-off) and none is tested. The consequence does not wait on the cause: the sole
> publisher of the protocol both remaining XCHI drivers wait on is being started for a reason this
> record has not measured. Instrument: `tools/guid-refs.py`, `tools/fv-inventory.py --dump-fvmain`,
> `tools/fv-apriori.py`'s `walk_volume`, `aarch64-linux-gnu-objdump`; none modified. No guest was
> booted, no firmware was built, no device was touched. See `docs/08` step 4.179.

> **Step 4.180 — the handle census 4.177 and 4.178 both asked for is built and read, and it says the
> chain stops at its first link.** A `P2UsbCensus()` in `Mu_Basecore/.../Dispatcher/Dispatcher.c:547`
> — a `P2HandleCount` wrapper over `CoreLocateHandleBuffer (ByProtocol, …)` called seven times, printed
> as `P2 USB n=%d all=%d pciio=%d usb2hc=%d usbio=%d blkio=%d fs=%d cfg=%d loaded=%d` between `P2Bins ()`
> and `P2Key ()` — was added, `tools/regen-mu-basecore-patch.sh` regenerated the patch, and
> `tools/build-apriori-variant.sh xhci-host` rebuilt the payload through all four of its gates to
> `work/out/usb-host/Mu-gauguin-xhci-host-gzip.img`, 1,173,504 B, `sha256 f2f9d948…` (the 4.177 payload
> preserved as `prev-xhci-nocensus.img`, 1,171,456 B, `sha256 34360470…`). One page of volume growth
> moved `DALSys`, so `run32-plain.sh` was spent on a plain run purely to read the new base off its own
> fault dump: `0x9C40B000` against 4.177's `0x9C40D000`, same `+0x346C` offset, `FAR 0xAFAFAFAF…`.
> `run32.sh` with `BASE=0x9c40b000` and `gdbprobe32.py` (4.177's probe, socket name only) then reaches
> the ordinary pass and ends where 4.177 ended — `K 83 SO 76/69`, `P2 STATS discovered=83 apriori=69/70
> started=76 diag=7 noload=0` — and the census prints **one distinct value across five passes from
> 14.26 s to 60.55 s**, i.e. every pass after dispatch completed at 12.51 s:
> `all=139 pciio=0 usb2hc=0 usbio=0 blkio=0 fs=0 cfg=1 loaded=77`. `all=139` says the probe works;
> `pciio=0` says **no handle in the system carries `gEfiPciIoProtocolGuid`**, so `XhciPciEmulation` —
> which returned `EFI_SUCCESS` from its entry point at `K 73 Ss 67/69` — published no emulated
> controller, and `usb2hc`/`usbio`/`blkio`/`fs` follow from that. A sixth row at `71.56 s` reads `n=3`,
> which is a `SIGTERM`-truncated flush and not a sixth pass: `mP2Census` is only ever incremented.
> `cfg=1` is recorded as one handle against 4.179's three install sites, not as a resolved
> discrepancy, because `CoreLocateHandleBuffer` deduplicates by handle. The *why* was already in
> 4.177's panel and had never been read against a handle count — `UsbConfigDxe`'s own bring-up:
> `UsbPwrCtrlLib_Init Initialize Hardware Configuration Error[Access Denied]`,
> `UsbConfigLibOpenProtocols: gPmicNpaClientSS1 cannot be created`, `failed to locate PMIC version
> protocol`, `PMI version (0x0)`, and `UsbConfigInit: Failed to attach USB Arid 0x0 HAL IOMMU domain
> Result =  (0x4)`. **The load-bearing caveat**: this volume carries no PCI host bridge driver at all
> (`--roster`: 135 files, `XhciPciEmulation` the only `pci`-named one) and the instrument is `-M virt`
> with `-nic none`, so `pciio=0` is consistent with either "the emulation never published" or "this
> machine has no PCI layer to attach to" — and only the device separates them. Instrument: `P2UsbCensus`
> (added), `tools/regen-mu-basecore-patch.sh`, `tools/build-apriori-variant.sh`,
> `tools/fv-inventory.py --roster`; `tools/qemu-panel-read.py` unmodified. No device was touched. See
> `docs/08` step 4.180.

> **Step 4.181 — the gate is shut, and the word that shuts it is one the publisher writes.** A
> `P2UsbGate (EFI_GUID *)` was added beside 4.180's census and `tools/build-apriori-variant.sh
> xhci-host` rebuilt through all four gates to `work/out/usb-host/Mu-gauguin-xhci-host-gzip.img`,
> 1,173,504 B, `sha256 32d359a9…`; the plain pass re-read the module base and it had **not** moved
> (`0x9C40B000`, same `+0x346C`, `FAR 0xAFAFAFAF…`), so 4.180's "one page moves `DALSys`" is a
> property of that page and not a rule. The gated run reaches the ordinary pass and takes **23 digest
> passes**; the probe prints one row per `E722B03F` handle and every one is the same:
> `P2 GATE h=9C028D98 i=9BECC3B8 w00=00010004 w04=00000000 w80=9BEBC650 w88=00000001 w8c=00010000`.
> **This step's own first reading of that row was wrong** — the panel file shows it as
> `… w88=00000001 w8c=0001` because the console is 90 columns wide and a full row continues on the row
> below, with the tail `0000` sitting on the next row as its own line. The mechanism is proved twice in
> that one panel: the same wrap splits `P2 APRI first=… last=CCCB0C28-…-0090273FC1` from its `4D`, and
> the two joined halves are exactly the 70th APRIORI GUID this project has documented for hundreds of
> steps. Across all 35 panels in `work/out/`, 406 rows are full width and exactly **two instrument
> lines** are ever affected — that `P2 APRI` row, and this new one — so no earlier conclusion rests on
> a short read. `tools/qemu-panel-read.py` was repaired rather than warned about: it now counts and
> names full-width rows and gained `--join-wrap`, verified by recovering both strings. With the tail:
> `Supported` requires `[iface+0x88] <= 3` **and** `[iface+0x8c] == 1`; the value is `0x00010000`, the
> *unassigned* sentinel `UsbConfigDxe`'s own initialiser loop writes (`0x3b6c`, `orr w9, wzr,
> #0x10000`), and `1` is written there by one caller only — `UsbStartController`, whose guard is
> `Index = 0` **and `Mode < 0x10000`** (`0x4df4`/`0x4e0c`; the earlier note in this project's record
> had that branch the wrong way round). The surviving interface is **record 1**, which that function
> cannot reach at all — installed early by `UsbConfigInit` (`0x3aa4`, `x2 = rec[1]+0x28`) onto a handle
> slot the very next loop nulls, which is also exactly why 4.180 measured `cfg=1` against three
> install sites. So **`pciio = 0` is not an artefact of `-M virt`**: the emulation's only route to
> publishing is its driver binding and that binding's first gate cannot be satisfied by any interface
> this boot creates. 4.180's two-alternative caveat is closed in favour of its first. Bitra's three
> `UsbConfigDxe` variants were checked and use the same sentinel and the same `+0x88 = i` loop, so this
> is not a version skew to be fixed by swapping a binary. **What remains is the phone**, and it is now
> a one-character prediction: a device run prints `w88=00000000 w8c=00000001` if the PMIC path reaches
> `UsbStartController (0, 1)` and `w88=00000001 w8c=00010000` if it does not. Instrument:
> `P2UsbGate` (added), `tools/regen-mu-basecore-patch.sh`, `tools/build-apriori-variant.sh`,
> `tools/qemu-panel-read.py` (`--join-wrap`, added). No device was touched. See `docs/08` step 4.181.

> **Step 4.182 — the gate 4.181 read is never *reached*, and the reason is the dispatch order.** 4.181
> closed the predicate and left one item explicitly open — *"whether `Supported` is reached at all (a
> counter at its entry, unbuilt)"*. The counter cannot go in `XhciPciEmulation` (source absent), and
> does not need to: every `DriverBinding->Supported` call in the firmware is made in one place,
> `MdeModulePkg/Core/Dxe/Hand/DriverSupport.c`'s `CoreConnectSingleController` inner loop (line 818),
> so counting there counts all of them and the controller handle each was made against. Four counters
> (`gP2SuppCalls`, `gP2SuppCfg`, `gP2ConnCfg`, `gP2ConnAll`), a `P2 SUPP n=` line printed once per
> connect to the `E722B03F` handle before the first `Supported`, and a `P2 CONN` row folded into the
> census's digest block. The caller is *named* without touching it: the dispatcher passes a
> `MEDIA_FW_VOL_FILEPATH_DEVICE_PATH` to `CoreLoadImage` for every FV-dispatched driver
> (`Dispatcher.c:1645`, `:2153`), so the driver's own firmware-file GUID comes back out of
> `LoadedImage->FilePath`. Patch regenerated (14 files, 1864 insertions, 23 deletions);
> `tools/build-apriori-variant.sh xhci-host` rebuilt through all four gates to
> `work/out/usb-host/Mu-gauguin-xhci-host-gzip.img`, 1,173,504 B, `sha256 0400c133…`; the plain pass
> re-read the module base and it had **not** moved a third time (`0x9C40B000`, same `+0x346C`). The
> run takes **23 digest passes** and every one of them reads the same three lines:
> `P2 CONN cc=1 sup=949 cfg=7 all=169`, `P2 SUPP n=7`, and seven `P2 SUPP <guid> s=Unsupported` rows
> — `UsbfnDwc3Dxe`, `UsbMassStorageDxe`, `PartitionDxe`, `DiskIoDxe`, `UsbBusDxe`, `UsbKbDxe`, `Fat`.
> **`BEB12BEE` (`XhciPciEmulation`) is not among them**, and the count and the rows agree one-for-one,
> so nothing this connect considered failed to print. `sup=949` is the liveness check — the instrument
> is not dead; `cfg=7` is a small complete set; `cc=1` says the handle is connected **once in the
> whole boot**; `all=169` says that is one connect in a busy system. The same panel gives the order:
> the seven rows sit immediately after `UsbConfigDxe`'s four bring-up errors and immediately before
> `K 57 Ss 53/69 … 0983C7F2-…` — the connect is made inside `UsbConfigDxe`'s own entry point at
> `K 57` — while `K 73 Ss 67/69 … BEB12BEE-…` shows `XhciPciEmulation` dispatched **sixteen slots
> later**. So the emulation is never offered the handle: at `K 57` the system holds seven driver
> bindings and the emulation is not yet loaded, and nothing connects the handle again. This is a
> second, independent reason to 4.181's predicate that the binding cannot happen — either would
> suffice, and fixing one leaves the other standing. The step was itself wrong once and the mistake is
> kept: the first build wrapped `CoreHandleProtocol` in `CoreAcquireProtocolLock ()`, which *is*
> `CoreOpenProtocol` and takes that lock itself, and asserted `Library.c(64): Lock->Lock ==
> EfiLockReleased` at 3.5 s; the aborted artifacts are named in place rather than deleted. **Still
> open**: which repair to make — reorder the Apriori, re-connect the handle after `K 73`, or change
> the sentinel `UsbStartController` writes — the first P3 clause, and the phone, which now has a
> second prediction that does not depend on the PMIC at all: a device run should print `P2 SUPP n=`
> with **more** than seven and, if anything re-connects, `cc` greater than `1`. Instrument:
> `P2CarriesUsbCfg`/`P2DriverFileGuid`/`P2SuppNote`/`P2Conn` (added),
> `tools/regen-mu-basecore-patch.sh`, `tools/build-apriori-variant.sh`. No device was touched. See
> `docs/08` step 4.182.

> **Step 4.183 — the emulation's `Supported` *is* asked, once the handle is offered after dispatch,
> and it answers `EFI_UNSUPPORTED`.** 4.182 asserted that the ordering barrier and 4.181's sentinel
> were independent; that was an inference, because 4.181 read the two words at *census* time and a
> census runs after dispatch. Separating "the ordering is the whole story" from "both barriers are
> real" needs the ordering removed, and `Supported` has one call site, so the question cannot be asked
> without connecting the controller — this step acts rather than reads. `P2Reconnect` was added to
> `Dispatcher.c` and called from `P2UsbCensus` before `P2UsbGate`, one-shot and with `Recursive =
> FALSE`; the outcome goes into a repeating `P2 RCNN` row rather than a line of its own, because
> `P2Digest` repeats by design and a probe that connected on every pass would make the panel stop
> being a steady state. `P2SuppNote` now resolves the caller's file GUID *before* the handle test and
> keeps `gP2EmuSupp`/`gP2EmuStatus` keyed on `BEB12BEE` itself, so "was this driver ever asked" no
> longer depends on which handle it was asked about. The owed `P2 GATE` split is done too:
> `P2 GATE h=… i=… w00=… w04=…` (55 columns) plus `P2 GATE2 w80=… w88=… w8c=…` (47), replacing a
> 94-column row on a 90-column console. Patch regenerated (14 files, 2021 insertions, 23 deletions);
> rebuilt to `work/out/usb-host/Mu-gauguin-xhci-host-gzip.img`, 1,173,504 B, `sha256 43d8d7ab…`; the
> base did not move a fourth time (`0x9C40B000`, same `+0x346C`); the new format strings were read
> back out of the built inner FVMAIN before the run. **The reading, one distinct line across all 24
> census passes**: `P2 SUPP n=17` — 17 bindings exist after dispatch, against the 7 that existed at
> `K 57` — and among the 17 rows is `P2 SUPP BEB12BEE-F6E1-11E1-9FB8-6C626DE4AEB1 s=Unsupported`;
> `P2 RECONN h=9C028D98 s=Not Found`, `sup=949+17 cfg=7+17`; `P2 GATE2 … w88=00000001
> w8c=00010000` read unwrapped 24 of 24; `P2 CONN cc=2 sup=966 cfg=24 all=170`; `P2 RCNN rc=1 re=Not
> Found ru=17 rf=17 es=20 er=Unsupported`. So the emulation is offered the handle, **is asked**, and
> refuses; `all` rose by exactly one, so the re-connect did not recurse; and `es=20` says its binding
> was asked 20 times across the boot, 19 of them about other handles — it was loaded and working all
> along, and this handle was the one thing it was never offered. **This eliminates one of 4.182's
> three repairs**: re-connecting the handle after `K 73` does not work. Two remain and they are not
> equally cheap — reorder the Apriori (a platform change this project can make and re-measure), or
> change the sentinel `UsbStartController` writes (inside a shipped binary this project cannot
> rebuild). That is a decision, not a measurement, and it is the next step. Instrument:
> `P2Reconnect`, `gP2EmuSupp`/`gP2EmuStatus` (added), `P2 GATE` split,
> `tools/regen-mu-basecore-patch.sh`, `tools/build-apriori-variant.sh`. No device was touched. See
> `docs/08` step 4.183.

> **Step 4.184 — the sentinel's writer is not the loop: that loop is bounded by `Index < 1` and
> initialises record 0, and the gate reads record 1.** 4.183 left two repairs and said one of them —
> changing the sentinel `UsbStartController` writes — was inside a binary this project cannot rebuild.
> Before accepting that, this step asked *which instruction* writes the word the gate reads, and the
> disassembly says the obvious candidate is not it. The gate's two clauses read `iface+0x88` and
> `iface+0x8C`, and in `UsbConfigDxe`'s own `UsbConfigInit` the only stores into those two words are a
> hand-written pair at `0x39e0`/`0x39e8` (index `1`, mode `0x10000`) and the record-initialiser loop's
> pair at `0x3b5c`/`0x3b70` — and the loop is bounded by `cmp x8, #0x1 ; b.hs` at `0x3b00`, so it runs
> for `Index = 0` alone. The interface the gate reads is `rec_base+0x100`, the host-client record, i.e.
> **record 1**; patching record 0's store is invisible. The measurement agrees exactly: the fourth
> variant (`--site loop`) boots, and on all 23 digest passes the panel reads `P2 GATE2 w8c=00010000`
> and `P2 SUPP BEB12BEE-… s=Unsupported`, with `pciio=0` on every census row, no `ConfigUsb` row and no
> `XhcPciEmulationDriverBindingStart` row. A negative result, and the useful one: the word is written
> **once**, in the record 1 hand initialisation, and nothing in this guest revisits it. Instrument:
> `tools/patch-usbcfg-sentinel.py` (added; `--site loop`), `tools/build-apriori-variant.sh` (4th
> experiment, `usbcfg-sentinel`). No device was touched. See `docs/08` step 4.184.
>
> **Step 4.185 — the gate opens and the binding still fails, one level down.** This step is 4.184's
> same tool aimed one word over: `--site host` rewrites `0x39e4`, the *mode* store of the record the
> gate reads, `orr w10, wzr, #0x10000` becoming `mov w10, #1`. The pattern holds on every one of 25
> digest passes — `P2 GATE2 w8c` moves `00010000` → `00000001` and `P2 SUPP BEB12BEE-… s` moves
> `Unsupported` → `Success` — so 4.181's gate is confirmed as real and as the *first* barrier, not the
> only one. The binding then fails one level down, inside the publisher the emulation just opened: the
> `+0x10` thunk (`0x1428`) re-shuffles its arguments, `ConfigUsb` (`0x2e80`) receives `(Mode = 1,
> Index = iface+0x88 = 1)`, and its entry guard `0x2ea4: cmp w8, #0x1 ; b.hs` takes the
> `EFI_INVALID_PARAMETER` exit, printing `ConfigUsb: ConfigUsb: Error - Invalid CoreNum passed: 1`
> before the emulation's own `XhcPciEmulationDriverBindingStart: Unable to configure USB in host mode,
> Status =  (0x2)`. `pciio` is `0` on every census row: the abort moved, the result did not. `%d` is
> proved to be the index rather than a "core number" by a single-store invariant — the only store to
> `[x29,#-0x10]` is `0x2e90` — and the same word is then used as a record index (stride `0xd8`) to
> fetch `UsbCoreIfc`. The run also settles 4.183's `Access Denied`: `UsbfnDwc3Dxe` opens the **same**
> `E722B03F` GUID `BY_DRIVER`, and the connect loop's second iteration is refused because the
> emulation never releases its own open (`Start` has no `CloseProtocol`; no `[x?,#0x120]` in
> `0x1514–0x1708`). **The decision this forces**: reordering cannot be sufficient and the only repair
> left is inside a shipped binary; the two words are both required — `+0x8C == 1` for the emulation,
> `+0x88 == 0` for `ConfigUsb` — while `UsbfnDwc3Dxe` wants `+0x8C == 4` of the same word, so **no
> single value of the record serves both clients** and the paired patch is a *counterfeit*
> construction-time record that may be read only as a probe of `ConfigUsb`'s next step, never as a
> device behaviour. Two corrections were made to instruments rather than to conclusions: the
> identification of the emulation in the volume is by **whole-file** match (the 45,056-byte Bitra file
> occurs exactly once, at `0x34b134`; the generic file zero times) and not by `.text[0:64]`, which is a
> shared prologue occurring 45 times; and `P2 USB n=` is **not** a pass counter (26 rows over 25
> passes, with `n=8` ×3 and `n=16` ×2) — `P2 CONN`/`GATE`/`GATE2` are. Instrument:
> `tools/patch-usbcfg-sentinel.py` (`--site host`, `--site index`), `tools/build-apriori-variant.sh`.
> **Still open**: whether the paired `host`+`index` build gets past `ConfigUsb` at all (the run either
> asserts `(NULL != UsbCoreIfc)` at `UsbConfigLib.c:304` or calls `UsbCoreIfc+0x18` and prints one of
> the "initializaition" rows), the first P3 clause, and the phone — whose prediction is now one
> character wide, since 4.183's `shut` and 4.185's `open` are the two values a single word can take.
> No device was touched. See `docs/08` step 4.185.
>
> **Step 4.186 — the pair opens the guard and the run then stops inside the publisher's own common
> initialisation, in ClockDxe.** Both words of the record are rewritten at once (`--site host,index`), and
> the two inner FVMAINs differ in **exactly two bytes** — bytes 2 and 3 of the instruction at PE RVA
> `0x39D8` — because the `host` patch was already in 4.185; from the other side, the volume's own
> `UsbConfigDxe` differs from the shipped `device/dxe/UsbConfigDxe.efi` in exactly the six bytes the tool's
> `SITES` table names and no others. `ConfigUsb`'s two refusal rows (`Invalid CoreNum passed: 1`, `Unable to
> configure USB in host mode, Status = (0x2)`) occur **once each** in 4.185's panel and **zero times** in any
> of 4.186's five. What replaces them is a **position**: the re-connect prints `P2 SUPP n=17` and two of its
> seventeen answers — the second being `BEB12BEE`'s `Success` — and then stops, where 4.185 prints fourteen
> more SUPP rows, `cap=24 more`, two `P2 RECONN` rows, `P2 GATE` and `P2 GATE2`; and this build prints **no**
> `P2 GATE`/`GATE2`/`CONN`/`RCNN`/`KEY` row at all, so the headline row that carried 4.185 is not what
> carries this. The frame chain, read out of the machine by matching live bytes against the build's own
> inner FVMAIN, is `XhciPciEmulation+0x15d8` (its `Start` into the `+0x10` thunk) ← `UsbConfigDxe+0x2ffc`
> (`ConfigUsb`'s post-`blr` into `UsbCoreIfc->InitCommon`, past the `0x2fa0` null-guard) ←
> `UsbConfigDxe+0x73c8` (a helper called with `w0 = 1` **and the string `gcc_usb30_prim_gdsc` at RVA
> `0xf059`**) ← `UsbConfigDxe+0x8ad4` (interface `+0x58`, reached only when that bool is 1) ←
> `ClockDxe+0x17a4` (vtable `+0xB0`) ← **`ClockDxe+0x11e8c`, the spin**. That address is ClockDxe's own
> `.data`: `x0 = 0x9c385410` is the GDSC descriptor table's `gcc_usb30_prim_gdsc` entry (file offset
> `0x25400`) plus `0x10`, whose `+0x28` is the ops block `0x2ba20 = {0x11e5c, 0x11e98}` — so the routine the
> run is in is the one the descriptor names — and whose `+0x48` is the rail `/vcs/vdd_cx`, the rail the
> console's last row complains about. The register it clears bit 0 of and then polls bit 31 of is
> **`0x11a004`**, inside `{"GCC CLK CTL", 0x00100000, 0x00200000}` as the board's own `MemoryMapLib.c`
> declares — one of the 55 low regions the run's `--el3-zero-mem` stage-2 map redirects to zeroed RAM, so
> bit 31 never sets. **The decision this forces**: 4.185's two candidates for the next row are both wrong —
> `UsbCoreIfc` is **not** null (the run passes `0x2fa0` and reaches the `blr`), so neither the
> `(NULL != UsbCoreIfc)` assert at `UsbConfigLib.c:304` nor the self-loop at `0x2f80` happened, and it does
> not reach `UsbCoreIfc+0x18` either; the abort is one level further in, on a named GDSC in a named register
> block, on a machine that answers zero. So the remaining question is one bit wide **and is a device
> question**: if the phone's hardware acknowledges, the run gets past `ClockDxe+0x11e8c` and the next rows
> are the ones 4.185 printed after `BEB12BEE s=Success`, or `0xe13d`'s "failed to perform common
> initialization" appears if it fails there for a real reason. Two method corrections are recorded: the
> prior reading's `UsbConfigDxe` PE base was `0x3a7394` and the roster gives **`0x3a6358`** (`0x3c` lower),
> and `iface+0x88`, `rec+0xb0` and the hand-written block's `0x188` are **one word** seen from three bases
> (`0x28 + 0x88 = 0xb0`, `0xd8 + 0xb0 = 0x188`, `0x112b8 + 0xd8 + 0x28 = 0x113b8`), which is why 4.184's
> `loop` patch at `0x3b6c` never moved the gate. Instrument: `tools/patch-usbcfg-sentinel.py`
> (`--site host,index`, `--in-image`, comma-separated sites), `tools/build-apriori-variant.sh`
> (`usb-sentinel-host+index`), `gdbprobe38c.py`/`gdbprobe38e.py`. **Still open**: whether the GDSC operation
> completes on hardware, whether `Supported` is reached at all on the device, the first P3 clause, and
> `P2 WHY`'s `O` at SEQ/WHY index 42. No device was touched. See `docs/08` step 4.186.
>
>
> **Step 4.187 — the instrument's zeroed `IMEM Cookie Base` is not why the UFS `ARID 0x0` attach fails, and
> the row beside it is.** The page really is zeroed and `UFSDxe` really does read it — measured, not
> described: `low_regions` returns **57** declared regions, `l2_plan` turns them into **55** 2 MB blocks in a
> pool `0x40000000..0x46E00000`, and `block_for_ipa` puts `0x146AA000` in block 163 → pool `0x46400000`; and
> live at UFSDxe RVA `0x4468`, `x8 = 0x146aa000` — the `SharedIMEMBaseAddr` config key's own value, its
> literal at RVA `0x14720` — with 32 zero bytes at it, so `ERROR: Failed to Get Shared Imem Boot Device type`
> (the driver's literal at `0x14688`) is a **host artifact** and `--el3-zero-mem` is why it appears. But the
> run reaches `UfsSmmuConfig` by the *other* of the two doors `EfiEntry` opens: `0x2678 bl 0x4304` /
> `0x267c and w8,w0,#0xff` / `0x2680 cbz w8,0x26a8` is a **fork and not a gate**, and the `0x2B5C` side needs
> only `UfsSmmuConfigForOtherBootDev = 1`, which `uefiplat.cfg:149` sets, and never reads IMEM at all. The
> second breakpoint proves which door this run used: `x30 = 0x9C2E7B60` at `UfsSmmuConfig`'s entry is base +
> `0x2B60`, the return from `0x2b5c: bl 0x24d8`. So rows 100 and 101 of one panel are two classes, the
> panel's adjacency of them is not a chain, and 4.141's `P2Record` value is not devalued by the flag it was
> read under — which was the only outcome that would have reached back into that step. Of the four failure
> prints inside `UfsSmmuConfig`, only `UFS IOMMU domain attach ARID 0x0 failed` is on this panel
> (`domain create failed`, `LocateProtocol failed` and `domain configure failed` are **absent**, `grep -c`
> over the 203 rows returning 0, 0, 0, 1), so the attach — `0x25F0: ldr x12,[x13,#16]` / `0x25F4: blr x12`,
> called with `x1 = "\_SB_.UFS0"` and `w2 = w3 = 0`, status `0x8000000000000007` stored at `0x260C` and
> printed as `status 0x7` by the very next row — is the first of the four that failed. Two counts corrected
> in place: 4.186's and this step's earlier *"the platform's 55 declared low regions"* is **57** regions
> touching **55** 2 MB blocks, and `0x0011A004` is block **0** → pool `0x40000000`, which is the same
> redirect 4.186 saw from the other side. Instrument: `work/out/qemu-probe-4.187/gdbprobe4187.py` (log
> `gdb4187-stdout.log`, sha256 `ac84dd4b…`, two `Z0` sites read once each then disarmed, nothing written to
> guest memory) and `work/out/qemu-panel-4.187-ufsdxe-imem.txt` (sha256 `8d4517c5…`, 203 rows, payload
> `/tmp/xhci-sentinel-pair.raw`, sha256 `a64010f4…`); the four probe bugs are recorded as method, because
> each produced output that read like a measurement. **Corrected, not carried**: this step's own working
> hypothesis — that the zeroed IMEM page was the *cause* of the ARID-0 attach failure and by extension
> explained the USB side's `UsbConfigInit: Failed to attach USB Arid 0x0 … (0x4)` — is **refuted**, and
> refuted only by the second breakpoint, since the cookie site alone is consistent with it. **Still open**:
> whether the phone's own `IMEM Cookie Base` holds a valid `0xC1F8DB40` record (a device page the redirect
> makes unreadable here, and now a question with no bearing on the failing route), whether the phone's
> `HALIOMMUDxe` has installed the protocol before `UFSDxe` looks (4.142's caveat, untouched), the
> `gcc_usb30_prim_gdsc` bit-31 poll and its device prediction, `Supported`'s entry counter, the first P3
> clause, and `P2 WHY`'s `O` at SEQ/WHY index 42. **Device state changed, and not by this project**: `adb
> devices` now lists `d25f844e`, with `ro.product.board = gauguin` and `ro.build.display.id = twrp_gauguin-eng
> 127 SP2A.220701.001 eng.dhollmen…` — the phone is booted into **TWRP recovery** with a root ADB shell, so
> `fastboot devices` is empty and the P3 `fastboot boot` workflow cannot run until it is rebooted to the
> bootloader; whether TWRP was booted or flashed to `recovery` is **not** decidable from the props (a
> `fastboot boot` leaves no trace), and `/dev/mem` does not exist on that kernel, so the phone's
> `0x146AA000` cannot be read from there. Nothing was flashed, no partition was written, `userdata` and the
> partition table are untouched, and `device/dxe/UsbConfigDxe.efi` is still `sha256 6943cc61…`. See `docs/08`
> step 4.187.
>
> **Step 4.188 — the GDSC status bit *is* what holds the run, and what lies past it is the same kind of stop
> one register down.** 4.186's closing device question is answered in the direction it was posed, by putting
> the one bit back: one `loader` blob of `0x80000000` at host `0x4011A004` (`0x40000000 + (0x11A004 &
> 0x1FFFFF)`, block 0 → pool `0x40000000` by the same arithmetic that reproduces `0x1FD4000 → 0x40DD4000`,
> `0xC3F000C → 0x42BF000C`, `0x18321700 → 0x46D21700`). Four runs of this payload stop at the shared row
> `DALLOG Device VCS: Unable to set rail…`; the fifth prints three rows past it —
> `SSUsb1InitCommon: gNpaClientSS1Bus is NULL)`, `HAL_clk_FabiaPLLEnableVote Activate Failure…`,
> `ASSERT HALclkFabiaPLL.c +184: 0` — and the control at the identical 150-second window **and** at 300
> seconds returns `grep -c` **0** for all three, in a window whose `K 83 SO 76/69`, `P2 USB`, `P2 SUPP n=17`,
> `P2 STATS discovered=83 apriori=69/70`, `P2 SEQ` and `P2 WHY` rows are identical string for string. So the
> poll at `ClockDxe+0x11E8C` is a real stop under this instrument. **But passing it does not deliver USB
> enumeration**: the run reaches `UsbConfigDxe`'s own common initialisation (a `NULL` AOP/RPMh client, a
> warning on the `NULL` arm of an `if` at `0x7430` that falls through, not a stop) and then stops in
> `ClockDxe+0x11734`, ops `+0x30` of the block at `0x2B8D0`, whose bounded `w2 = 0x7D0` poll of bit 30 fails
> and whose **firmware assert** self-branches at `0x117A4` — a self-branch, so no `ArmCpuDxe` row and no
> exception anywhere in the panel. That is the same shape as the stop the seed just removed, so *"one-bit
> device question"* is not one bit: it is the first link of a chain. **Two corrections to 4.186**, both
> measured: the GDSC descriptor table has stride `0x58` but begins at file offset **`0x24DD0`** and holds
> **22** entries — `0x25400`, which 4.186 named as the start, is entry 18 (`gcc_usb30_prim_gdsc`,
> `+0x10 = 0x0011A004`, `+0x28 = 0x2BA20`, `+0x48 = "/vcs/vdd_cx"`), with `gcc_ufs_phy_gdsc` at entry 17 and
> `cx_gdsc` at 19 — and the ops block at `0x2BA20` holds **eight** pointers
> (`0x11E5C`/`0x11E98`/`0x11EC4`/`0x11EF8`/`0x11F14`/`0x11F2C`/`0x11F44`/`0x11F70`), not the two 4.186
> recorded. Neither touches 4.186's conclusions, and the whole 22-entry table is now named: 21 GDSC names
> from `video_cc_mvs0_gdsc` to `cam_cc_ipe_0_gdsc` and `gcc_usb30_prim_gdsc` the only USB one. **New and
> not established**: which of the **thirteen** `.data` words equal to `0x2B8D0` (at `0x288A8`…`0x2B330`,
> records based `0x20` earlier, names resolving to the rail strings `/vcs/vdd_cx` and `/vcs/vdd_mx`) is the
> Fabia PLL the failing vote used — deriving it would be a guess in the shape of a measurement, so this step
> stops at *a rail vote whose register this instrument models as zero RAM*. **Method, and a dead hypothesis
> recorded dead**: the plain instrument never reaches `ClockDxe+0x11E8C` at all — **five** runs with no probe
> (`K 46` = `I2C`, `D06A77F4-…`, Apriori index 46) die in the driver after it, `AdcDxe` (`9143B2B7-…`), at
> `DALSys.dll+0x346C` with `ELR 0x9C40E46C` and `FAR 0xAFAFAFAFAFAFAFAF`, byte identical each time — which is
> why every K-83 panel of this project carries probe 38e's declared `/pmic/target` suppression, and the
> suppression is visible in the panels themselves: `K 47 SU 44/69 9143B2B7-…` and
> `P2 DIAG S 9143B2B7-… Unsupported`. That the suppression is a *state* difference and not a *timing* one is
> measured, not asserted: under `-icount shift=4,align=off,sleep=off` the unperturbed run aborts at the same
> instruction as its no-`icount` control, and the probe's own log prints `-> x0 zeroed: this record is not
> published`. The elapsed-time hypothesis (this instrument has no `-icount` and no `-rtc clock=`, so a
> gdbstub pause injects guest time) is **refuted** and is recorded so it is not re-derived; two further runs
> spent on it are recorded as spent. **This step's own first panel is a correction to itself**:
> `qemu-panel-4.188-gdsc-seeded.txt` is a plain-instrument run in which the fifth blob was never read, so it
> must not be quoted as a test of the seed. Instrument: `work/out/qemu-probe-4.188/` (seven run scripts) and
> panels `qemu-panel-4.188-seeded-suppressed.txt` (sha256
> `2f2260ac295d73d2b303d0c6e3b26c0db0b93a1a5278d206d74f7327fee1dca0`, 249 rows / 150.2 s),
> `…-suppressed-4blob.txt` (`8d5a6ff6…`, 276 rows / 150.1 s), `…-suppressed-4blob-long.txt` (`dfdbc421…`,
> 350 rows / 300.3 s), `…-control-1.txt` / `-control-2.txt`, `…-icount-A.txt` / `-icount-B.txt`,
> `…-nullprobe.txt`; the seed is `/tmp/gdsc-clk.bin`, 4 bytes `00000080`, sha256
> `6d58692645c9d1cfaf13541cbd258f86193ef63c2f1d38f6bbca9617372d7bd6`. **This step adds the fifth fabricated
> word to this project's list of instrument lies, and it is the most consequential of the five**: the other
> four restore what an absent peer would have published, whereas `0x4011A004` asserts a hardware status bit
> that is false, and every row past the poll is said with that lie in place. Nothing was flashed, no partition
> was written, and `device/dxe/UsbConfigDxe.efi` is still `sha256 6943cc61…`. **The step's one device reading
> is a read-only `dd` of `boot`, and it corrects a record that had stopped being checkable**: the phone is in
> TWRP (`d25f844e`) with `fastboot devices` empty, and the partition holds an instrument payload — `page_size`
> 2048, header version 1, gzip kernel of `kernel_size` 1,136,864, so `0x0..0x116000` written over the
> Smartisan image's tail, which is the flash-based state the standing relaxation describes — reading **13 of
> 14** on `tools/probe-fingerprint.py`'s ladder with only `P2FreeWhy` absent, which **does not agree** with the
> record's `90b21643…` at the full ladder (that file has since been rebuilt under the same name, so the record
> cannot be re-checked against it). No image retained anywhere matches it: the first 1,138,912 bytes were
> compared against all 183 `ANDROID!` files of at least that size under the repository, `/tmp`, `~/backup` and
> `~/Downloads`, and the only two hits are `work/out/boot-readback.bin` (4,194,304 B, sha256 `e905b3a6…`) and
> the 128-MiB `/tmp/boot-now.img` — both reads of the phone itself, so the readback is now its only copy.
> Which build it is, and why thirteen instruments and not fourteen, are **not established**. See `docs/08`
> step 4.188.
>
> **Step 4.189 — the stop past the GDSC is a rail vote, and 4.188's open question about it is answered.**
> 4.188 closed with *"which of the thirteen rail records the FabiaPLL vote belongs to"* as **not
> established**, because the routine at `ClockDxe+0x11734` reads its two addresses out of a **runtime**
> object (`ldr x8,[x0,#8]`, `ldr w10,[x0,#0x10]`) while all thirteen static records carry a CC-block base
> at `+0x08` and a bitfield at `+0x10`, so no static field could be matched to the values the routine used.
> The object the machine passes is read here, with 38e's declared `/pmic/target` suppression kept verbatim
> and one breakpoint at the live `+0x11734`: `x0 = 0x9C389598` is `.data` RVA `0x29598`, i.e. **the record
> at `0x29590` plus eight** — the caller passes `&record + 8`, past the name slot, and the probe's six
> qwords are that record's own `+0x08`, `+0x10`, `+0x18`, `+0x20`, `+0x28`, `+0x30` (`0x100000`,
> `0x152010`, `1`, `0x2B8D0` relocated to the live `0x9C38B8D0`, `0x61`, `0`). The identification rests on
> two fields no other record carries — `+0x08 = 0x100000` and `+0x28 = 0x61` each appear exactly once — and
> the name slot `0x25638` resolves through RVA `0x15774` to **`/vcs/vdd_cx`**, the same rail string the
> GDSC table's entry 18 carries at its `+0x48`. So the failing rail is the `gcc_usb30_prim_gdsc`
> descriptor's own rail and the **first of the thirteen**. Disassembled, the vote is **two registers and
> not one**: it sets **bit 0** at `0x152010` (the mask is `record+0x18 = 1`, *not* the `0x61` the probe log
> shows in `w10` — that is a caller's leftover, and this is a correction to this step's own log) and then
> polls **bit 30 of `0x100000`**, from `record+0x08`, 2000 times, through the helper at `0x9B00`. Both
> addresses are inside the board's declared `{"GCC CLK CTL", 0x00100000, 0x00200000}` and both fall in
> **2 MB block 0 → pool `0x40000000`** — `0x100000 → 0x40100000`, `0x152010 → 0x40152010`, and `0x11A004 →
> 0x4011A004`, which is 4.188's fifth fabricated word. **The seed and the poll are two offsets in one
> redirected block**: the seed sets bit 31 at the first, the GDSC poll passes, the run walks on, and the
> next bounded poll it makes reads the zero nothing has set, so 4.188's *"one register down"* is now an
> address. **The caller is named for the first time**, and this **corrects 4.188's *"Nothing in the image
> calls it"***: the call is `Clock_SourceOn` at RVA `0x5ECC` (`bl 0x9A14`), through a **trampoline family**
> at `0x9A00`/`0x9A14`/`0x9A34`… that reads one slot of an ops block and `br`s to it (`0x9A14` takes
> `[obj+0x18][0x30]` = `0x11734`), which is why no `bl` target anywhere in `.text` is `0x11734` — and the
> same mechanism is how `0x11E5C` is reached, which the run also witnesses (`x0 = 0x9C385410` = `.data`
> `0x25410`, GDSC entry 18's own `+0x10`). The 300-second panel
> (`work/out/qemu-panel-4.189-rail.txt`, sha256 `36be5c28…`) reproduces all three rows with the vote
> breakpoint armed and firing and has **nothing after them**; its header's *328 rows* is 80 too many
> because rows 83–162 repeat rows 3–82, so the run's distinct content is **248 rows** against 4.188's 249,
> and the two agree row for row over their tails — which is what makes the reproduction a reproduction.
> **Not established**: whether the `0x100000` bit-30 poll would pass on hardware; what `Clock_SourceOn`'s
> `tbnz` tests; whether `gNpaClientSS1Bus is NULL` is an absent peer or a second debt. **The next seed is
> named and not run**: bit 30 at host `0x40100000`. Nothing was flashed, no partition was written,
> `device/dxe/UsbConfigDxe.efi` is still `sha256 6943cc61…`, and the phone's state is 4.188's (TWRP
> `d25f844e`, `fastboot devices` empty, no photograph supplied). See `docs/08` step 4.189.
>
> **Step 4.190 — the vote's poll is what held the run, and pre-setting it moves the wall one row.**
> 4.189 named its next seed and did not run it. Run here: four bytes of `0x40000000` — bit 30, the
> poll's own mask — at host `0x40100000`, i.e. IPA `0x100000`, in the declared
> `{"GCC CLK CTL", 0x00100000, 0x00200000}` region's 2 MB block, whose pool page `0x40000000` is the
> **same redirected page** 4.188's fifth blob sits on at `0x4011A004`. The run's command line is
> 4.189's with one `-device loader` line added (`/tmp/cc-vote.bin`, sha256
> `d88c86f1…`) and all five of 4.189's blobs kept. The probe single-steps **nine** instructions at the
> vote instead of four, so the load that produces the mask is inside the window, and reads both
> registers back through the guest's own address space. **The machine now confirms what 4.189 could
> only read out of the file**: `w10` is `0x61` at `pc=0x9C37174C` (the `ldr`'s own address, a caller's
> leftover) and `0x1` at `pc=0x9C371750` (the instruction after it) — **the mask is 1** — while `w9`
> goes `0x20`→`0x0` as `ldr w9,[x8]` completes, and the guest reads back `[0x152010] = 01000000` and
> `[0x100000] = 00000040`. Then, at the poll's return address `0x11760`, `w0 = 0x1`: **the helper
> `0x9B00` returns on its first pass with the bit already set**, `cbz w8,0x11770` is not taken, and
> the `HAL_clk_FabiaPLLEnableVote Activate Failure` log and the `HALclkFabiaPLL.c +184` assert are
> never reached. The 300-second panel (`work/out/qemu-panel-4.190-vote.txt`, sha256 `caddc293…`, 253
> rows, the same four GAP(s) at the same four instants as 4.189's) agrees row for row with 4.189's
> to the tail and differs in exactly two ways: `Unable to set rail[…]` appears **twice** where 4.189
> had it once, and the failure line and the three-row assert block are **gone**. The console then
> freezes at **105.57 s** — the same instant 4.189's froze — with nothing for the remaining ~195 s.
> **So the seed did not remove a wall; it relocated one, one printed row further on.** Which is the
> answer to 4.188's *"the same kind of stop one register down"*: the stop past the GDSC **is** a rail
> vote, and what this run was waiting on at the vote **is** the poll — demonstrated, not argued.
> **Not established**: where the run stops now, and whether that is a self-branch or another bounded
> poll; whether the `gNpaClientSS1Bus is NULL` row and the RSC rail failures are one debt or several;
> and the hardware question is untouched, since the bit written here is fabricated by an instrument.
> **The next move is named**: a probe that **samples the PC** rather than watching five named sites —
> the first step here that could name a wall it was not told about in advance. The command line now
> carries **six** fabricated loader blobs, and every row past the vote is said with all six, plus the
> EL3 stub's three structures, in place. Nothing was flashed, no partition was written,
> `UsbConfigDxe.efi` is still `sha256 6943cc61…`. See `docs/08` step 4.190.
>
> **Step 4.191 — answering the wait at `ClockDxe+0x11CBC` carries the console past 4.190's wall into a second module's assert.**
> 4.190 left two things unnamed: where the run stops once the vote's poll is passed, and whether that stop
> is a self-branch. Run here, twice, with a third run as the control on the same command line: the site
> `ClockDxe+0x11CBC` — the `tbnz w9,#0` of the wait — is **answered**. `x19` names the register block the
> poll tests, and the bit is cleared **through the guest's own store path** (`M` packet, then read back
> through the guest): `[0x11A01C] = 0x1 → 0x0`, `[0x11A034] = 0x1 → 0x0`, `[0x11A060] = 0x1 → 0x0`, twice
> each, six answers, every one `b'OK'` and every one reading back `0x0`. `AFTER POLL` then returns
> `w0 = 0x1` both times. **The console moves**: from 105.57 s and `SSUsb1InitCommon: gNpaClientSS1Bus is
> NULL)` — where 4.190's run and this step's own control both stop, row for row identical — to **106.32 s**
> and a second module's failure: `usb_lane: 0`, `P2 SUPP F056673C… s=Access Denied`, `P2 SUPP B7F50E91…
> s=Success`, then `…/QcomPkg/Drivers/XhciDxe/XhciReg.c:121 ASSERT: (Xhc->CapLength != 0` and
> `ASSERT XhciReg.c +121: 0`. **Which module is established by provenance, not resemblance**:
> `tools/make_xbl_binaries.py` takes `XhciDxe` from `SIBLING_SOURCE = "bitra"`, that image carries
> `ASSERT: (Xhc->CapLength != 0` at its own `0x10F03` and the `ASSERT %a +%d: %a` renderer at `0x133F0`,
> and the local source's `XhcReadOpReg` has `ASSERT (Xhc->CapLength != 0);` at `XhciReg.c:106` immediately
> before the BAR read. So the stop is a real assert on a zero capability length, and every one of the
> three runs that reached this point had all **six fabricated loader blobs** in place — the capability
> length it tests is not hardware's. **Not established**: whether that new stop is a `CpuDeadLoop` or a
> return — a panel cannot tell a self-branch from a poll, and the walk that was to name the module was
> the one whose socket broke — and the hardware question is untouched. Two readings are **withdrawn**
> here: the stuck-PC reading (`0x9BE09E24` / base `0x9BDFA000`) has no artifact anywhere in the tree, and
> the claim that 4.190's and 4.191's panels end on the identical row sequence is false — 4.190's panel
> has zero `usb_lane`, zero `XhciReg` and zero `CapLength`. See `docs/08` step 4.191.
>
> **Step 4.192 — the wall past that assert is a `CpuDeadLoop` in bitra XhciDxe's own image, named from the machine.**
> 4.191 left open whether the stop on `Xhc->CapLength != 0` is a self-branch or a poll, which a panel
> cannot tell apart. Run here with the same six breakpoints 4.190 and 4.191 armed and the same command
> line — the first attempt at this step armed **only** `0x11CBC` and the run went elsewhere (console
> frozen at 102.56 s on a DALSys fault dump no other panel contains, because the `/pmic/target`
> suppression never ran), so the deviating attempt is kept beside the good one as a record that the
> probe is part of the experiment. The trace run reproduces 4.191's handshake row for row, goes **three
> answers further** than 4.191's two (nine, not six — those died on a `BrokenPipeError`), and the
> guest's own verdict that it is free is an empty `c` for 25 s: `nothing stopped in 25s after 9
> answer(s)`. Break-in then gives `pc = 0x9BE09E24`, `lr = 0x9BE09E20`, and twenty single steps over
> **exactly two PCs, alternating**, with `x8 = 0x0` every time. The walk down finds `MZ` at
> `0x9BDFA000` (RVA `0xFE24`), and the module is named twice over from the machine: `x21 = 0x9BE0AFB6`
> → RVA `0x10FB6`, which is the string `XhciReg.c` in `Binaries/bitra/…/XhciDxe.efi` and an empty run
> in `9707f`'s copy, and the sixteen bytes at RVA `0xFE24` occur at that RVA in two of 6,857 images.
> The two instructions are `ldr x8,[sp,#8]` / `cbz x8, 0xFE24` — the branch target is the load itself
> and the word is zero — so it is a two-instruction self-branch, `CpuDeadLoop`, in the same image the
> assert was rendered from. **So both of 4.190's and 4.191's open questions are now closed, and in the
> same direction**: the first stop was a poll the instrument can answer, the second is a dead end it
> cannot. The block the assert is about reads zero through the guest (`USB30_PRIM 0x0A600000` and the
> other four addresses), which is consistent with `CapLength == 0` but indistinguishable from a wrong
> core base, and is zero here because no blob populates it — a consistency check, not a hardware
> finding. **Restored**: the stuck-PC reading 4.191 withdrew for want of an artifact (`0x9BE09E24`,
> base `0x9BDFA000`, RVA `0xFE24`) is exactly what this run shows, and the note that the descent from
> `0x9BE09000` would have found `0x9BD05000` is corrected — the walk finds an `MZ` fifteen pages below.
> **Offered and not taken**: a seventh blob at the XHCI IPA the machine read as zero, which is what
> would let the `CapLength` assert be passed the way the wait was. See `docs/08` step 4.192.
>
> **Step 4.193 — the live phone read as an oracle: the real hardware's answers to the values this
> instrument has been fabricating.** Every stop since 4.186 has turned on a register the instrument
> fabricates, justified by the claim that the *addresses* are the board's own and only the *contents*
> invented. With the phone sitting in TWRP — no flash needed — that half of the claim was tested.
> `devmem` is dead on this ROM even as root with SELinux Permissive (`mknod /dev/mem c 1 1` creates the
> node and the read still returns `No such device or address`), `/proc/kcore` is absent and
> `kptr_restrict` is `2`; `mount -t debugfs none /sys/kernel/debug` succeeds and is the whole route.
> **The only things changed on the phone were a `mknod` into a `tmpfs` `/dev` and that mount** — `/` is
> `rootfs`, i.e. TWRP's ramdisk — so no partition was touched and nothing was flashed.
> **What the machine says**: `gcc_usb30_prim_gdsc` **use = 1**, the exact descriptor 4.186 found ClockDxe
> driving, is powered on the real phone, so that stop was the instrument's power model and not the
> hardware's; `gcc_usb30_prim_master_clk_src` runs at **133333333 Hz** (3/3) while
> `gcc_usb3_prim_phy_pipe_clk` sits at **0 Hz, 0/0/0**; the **whole UFS clock tree is at zero**; the real
> `cmd_db` is indexed by **ID string** (`cx.lvl` `0x30000`, `qphy.lvl` `0x30090`, the eight `.mol`
> entries, the PMIC family from `0x50000`, `vrm.soc` `0x43700`, `soc.pbs` `0x43900`). **Two addresses the
> fabrication rests on are the board's own**: `reserved-memory` has `compatible = "qcom,cmd-db"` at
> **`0x80860000 + 0x200`**, and `qcom,qmp-aop@c300000` is **`0x0C300000 + 0x100000`**, so the `0xC3F000C`
> word the EL3 AOP seed writes sits inside the real mailbox window at offset `0xF000C`. The real DWC3
> reports `GSNPSID = 0x5533330a`, `GHWPARAMS0 = 0x4020400a` (MODE = **DRD**),
> `GHWPARAMS3 = 0x10420085` (**a GEN1 SuperSpeed PHY is present**), and `GHWPARAMS6 = 0x07ea0020` (BC,
> OTG3, ADP, HNP and SRP all zero in *capabilities*) — but `mode` reads **`device`**, `link_state`
> `On`, and `/sys/kernel/debug/usb/xhci/` is **empty**, so every value is the *device-mode* profile of a
> DRD core with no host instance to read. **So this oracle cannot answer 4.192's open question** —
> whether a real capability block at `0x0A60C100` holds a non-zero `CapLength` — and the honest statement
> is that no reading exists, not that a reading disagrees. (4.194: `0x0A60C100` is `USB30_PRIM + 0xC100`,
> the project's own arithmetic, not a read; the live tree claims that window as `dwc3@a600000`'s global
> register block. **4.195: the answer was in the module all along** — the assert is `XhcReadOpReg`'s own
> line 121, reached through `XhcReadCapReg8` at `0x4230`, so `CapLength` *is* read, from the capability
> block at the DWC3 base `0x0A600000` = guest IP `0x41A00000`; `0x0A60C100` is the block *after* xHCI
> (`DWC3_GLOBALS_REGS_START`), and the instrument's zero model is what makes the byte zero. 4.192's probe
> asked its question of the identity address — which the redirect answers with the zero model — and its
> pool reads came back `unreadable`, a method defect now recorded.) **4.196: the seed 4.195 named was
> written, and it moved the stop.** One added loader line puts a **fabricated** xHCI capability block
> (CAPLENGTH `0x20`) at pool `0x41A00000`, the guest IP the redirect serves the DWC3 base from, and the
> `ASSERT XhciReg.c:121` row **disappears from the panel** (349 rows, ending on UsbConfigDxe's Vbus trio)
> while the run goes free after the same nine `ClockDxe` answers; the register block then reads
> `USB30_PRIM 0x0A600000 = 20001001`, which is that blob's own first four bytes `20 00 10 01` printed in
> memory order, against `00000000` in the control — 4.192's redirect claim shown by changing the value.
> The break-in PC is not a stop at all: `0x9c4b7c10` is `MetronomeDxe+0x2C10`, the `ret` of `ArmReadCntPct`,
> and the twenty-step trace is a byte-exact four-module chain — bitra XhciDxe `0x4918` `blr` `gBS->Stall`
> → `CoreStall` (`DxeCore+0xCC00`) → `CoreInternalWaitForTick` (`DxeCore+0xCBA0`) → `WaitForTick`
> (`MetronomeDxe+0x123C`, returning `EFI_SUCCESS`) → `MicroSecondDelay` (`MetronomeDxe+0x16FC`) — so the
> wall past the assert is the xHCI poll's own 1 µs stall loop, with a `Timeout × 1000` =
> 10 000 000-iteration bound that a block of pool RAM can only ever reach. The poll helper `0x48AC` has
> exactly two callers: a per-port PORTSC routine in `Xhci.c` waiting for bit 21 **set** and
> `XhcDisableAllDeviceSlotsAndPorts` (`0xAA2C`, its own `%a` name and `Failed to disable port %d` format in
> the image's rodata) waiting for bit 9 (PP) **clear**. The next experiment — pre-set the bit the poll
> waits on, the mirror of 4.190's trick — is named and **not run**. (4.197, the control: the same run with
> that one loader line deleted reproduces 4.192 instruction for instruction, `pc=0x9be09e24`, `rva=0xfe24`,
> twenty steps over two alternating PCs, the assert back at panel row 359 — so the assert's disappearance
> is the seed's doing; and three runs holding three different subsets of `{K24, K25, K26}` with the fully
> lost gaps every panel reports makes 4.196's row-163 difference sampling loss, not an effect of the blob.
> A panel read is destructive (`efi_panic_clear()`) and cannot settle what the guest executed; the CPU can.)
> **4.198: the poll is named at its own entry.** 4.196's open item (a) — *which* way into the poll helper
> the seeded guest had taken — is decided by reading the helper's arguments instead of its `lr`, because the
> `lr` 4.196 published, `0x9bdfe91c` = `XhciDxe+0x491c`, is the helper's *own* return after its internal
> `blr x8` and is shared by every caller. One added `Z0` at `XHCI + 0x48AC` fired twice: `@16.7s`
> `w1=0 w2=2 w3=0 w4=0x3E8` from `x30 = XhciDxe+0x164C`, the reset poll (`0x4A84` sets `USBCMD.HCRST` and
> waits for it to clear) reading `0x2` at IPA `0x0A600020`; and `@30.1s` `w1=4 w2=1 w3=0 w4=0x2710` from
> `x30 = XhciDxe+0x1684`, the run poll (`0x4B80` sets `Run/Stop` and waits for `USBSTS.HCHalted` to clear)
> reading the seed's own `0x1` at `0x0A600024`. Both call sites are in one routine, `XhciDxe` RVA `0x153C`,
> named by its own five failure strings (`XhcDriverBindingStart: failed to enable controller`, `…create
> USB2_HC`, `…start async interrupt monitor`, `…install USB2_HC Protocol`, `…install USB Port test
> Protocol`) and by its `Xhci.c` 2654/2660 asserts; so the ten-million-iteration bound 4.196 predicted is the
> *second* poll, and the first is the reset, reached and failed 13.4 s earlier. The break-in register file
> reads the same poll out (`x22 = 0x9BD60018`, `x24 = 0`, `x25 = 0x989680`, `x26 = XHCI + 0x15000`,
> `x23 = 1,883,502` of 10,000,000 at 55.1 s) and two intervals agree on the instrument's `Stall(1)` cost at
> 13.27 µs per iteration, putting the second poll's expiry at ≈163 s. This caller **discards both statuses**
> (`0x164C mov x0,x20`, `0x1684 ldr x10,[x23,#992]`), which is why the 281-row panel ends on UsbConfigDxe's
> Vbus trio with no reset-failure row. Corrected from 4.196: the `x22`–`x26` inheritance holds but `x20` is
> not the helper's (`MicroSecondDelay` overwrites it at RVA `0x1748`), and the probe's `WANTS` line prints
> the mask where the expected value belongs. `0xAA2C` is excluded for this run. The next experiment is the
> sharper mirror of 4.190's: seed **both** polled bits — HCRST clear at `0x0A600020` *and* HCHalted clear at
> `0x0A600024` — after which the two polls pass on their first try and the run tests what lies downstream of
> a reset that reads as successful, rather than only what the driver prints.)
> **4.199: the poll is answered instead of seeded, and the wall is another driver's.** 4.198's named follow-up
> — seed both polled bits — is impossible with a loader: the block behind `0x0A600000` is pool RAM
> (`ZERO_MEM_POOL_BASE = 0x40000000`), so the driver's own `USBCMD.HCRST` store sticks and real hardware's
> self-clear has no counterpart there. So the probe writes at the same entry it used to read at
> (`--xanswer 16`; `new = (val & ~w2) | (w2 if want else 0)`, put back with `mwrite` and read straight back),
> with the answer's shape taken from the helper's own `bics/cset/cmp/b.eq`. Both entries fired 0.1 s apart
> (4.198: 13.4 s), so the first poll's bound was never spent, and both readbacks took — the falsifier in the
> runner's header did not occur. The run then stops in `UsbBusDxe`'s `UsbRootHubInit`: `pc = 0x9BF9EEF4`,
> `ldrb w8,[x19,#201]` / `cmp w8,#6` / `b.cc`, i.e. `PollCount` on a pool `HubIf` spun until 6. The module is
> this tree's own build (`SizeOfImage 0x10000`, 5 sections, the pattern once at file `0x42F4` = rva `0x4EF4`,
> the machine's `x22` equal to the built code's `adrp` operand — the Qualcomm prebuilt has neither the pattern
> nor the string), the routine is named by its own `DEBUG_INFO` string at rva `0xA090` and by its
> `CreateEvent`/`SetTimer (TimerPeriodic, 0xF4240)` arguments and struct offsets, and the wait is
> `UsbHub.c:1002`–`1020`'s `// MU_CHANGE Add USB Hub Enumeration delay` — 6 and 200 (`UsbBus.h:61`, `:67`), a
> block upstream edk2 does not have, satisfiable in principle (6 ≤ 200) but reading **1** at the break-in, which
> is what the immediate `SignalEvent` gives and no evidence that the armed 100 ms timer ever ran (only the
> interrupt path can advance it — not a TPL effect, since DxeCore dispatches timer notifications at
> TPL_HIGH_LEVEL from its own tick). The wall did move, and the two late samples bracket it: 4.198's
> `pc=0x9c4b7c10 lr=0x9c4b6754` is `ArmReadCntPct`'s `ret` under `MetronomeDxe+0x1754` =
> `MicroSecondDelay+0x58` — the leaf of the `Stall(1)` the xHCI poll helper calls each iteration — so 4.198's
> guest was still inside its run poll at 55.1 s and had not reached `UsbBusDxe` at all. The console's row set is unchanged from 4.198, so the answering changed
> nothing printed. What the guest's position does prove is the chain `UsbRootHubInit` → `mUsbRootHubApi.Init`
> (`UsbBus.c:1178`) → `UsbBusBuildProtocol` → `OpenProtocol (gEfiUsb2HcProtocolGuid)` (`UsbBus.c:1304`): **the
> USB2_HC protocol was published**, and the only other holder of that GUID is the bitra `XhciDxe.efi` itself.
> The next experiment is named and not run: a `Z0` at `UsbBusDxe+0x658C` to count whether the periodic callback
> is ever delivered, or answer `[x19+201]` with 6 the way this step answered the xHCI polls, which carries the
> run into `UsbBus->Devices[0] = RootHub` and real device enumeration.)
> **4.200: the interrupt controller the payload programs is one 2 MB page of the pool.** The question 4.199
> left open — whether the periodic timer's notification ever arrives — needs no run: the board's map declares
> `APSS_GIC600_GICD 0x17A00000+0x170000` and `APSS_GIC500_GICR 0x17A60000+0x100000`
> (`MemoryMapLib.c:81-82`), both below `LOW_MMIO_LIMIT`, so `--el3-zero-mem`'s `l2_plan()` puts **both in one
> 2 MB block**, 189, whose pool address is `0x46800000` — the tool's own `low_regions()`/`l2_plan()`/
> `block_for_ipa()` say so in one line. QEMU's controller is at `0x08000000` (block 64, undeclared and
> untranslated), and the machine's timer lines are PPIs 13/14/11/10 against this board's 1/2/3/0, which are
> the ones the firmware is built with (`PcdArmArchTimerSecIntrNum|17`, `PcdArmArchTimerIntrNum|18`, baked at
> `ArmTimerDxe.efi:0x11c4`/`0x11c8`) on the **non-secure EL1 physical** timer (`CNTP_CTL_EL0`/`CNTP_CVAL_EL0`).
> So no interrupt can be delivered to this guest at all, `gBS->Stall` works only because it busy-waits on
> `CNTPCT_EL0`, and 4.199's frozen `PollCount` is the instrument's arithmetic and not the driver's. Method
> point recorded with it: a panel log's row times are the sampler's clock (the banner re-appears at the same
> `90.80s` in three runs whose guests stopped in three places). Next, named and not run: `Z0` at
> `UsbBusDxe+0x658C` + read `[x19+201]` (predicts the callback never fires), `Z2` watchpoints on
> `0x17A00000`/`0x17A60000` to name the writer, and answering the wall as 4.199 answered the polls — the only
> way a machine that cannot interrupt can proceed.)
> **4.201: the re-run holds, and the census's own call site moves every USB event in this family inside the
> instrument's one-shot `CoreConnectController`.** `run-hand11.sh`'s second attempt is the first with the
> harness defect `free` fixed (`free = False` at the head of `watch()`, or phase 1 returns at `@0.0s` and spends
> none of its window), and all three parts came back. **Part 2** — `@4.9s WATCHPOINT #1 at 0x17a00000
> pc=0x9c4c1b64 lr=0x9c4bf54c`, module `MZ` at `0x9c4be000`, so rva `0x3b64`/`0x154c`; the image's own bytes at
> rva `0x1520` are ICCBPR `0x7`, ICCPMR `0xff`, **ICCICR at base 0** and ICDDCR at `0x17A00000` into
> `IoLib`'s `MmioWrite32` (`ArmGicV2Dxe.c:632`/`:635`/`:486`/`:463`), so the V2 path 4.200 left open is closed
> by execution, and the `0x08000000` control never fired and read `unreadable`. **Part 1** — `HUB NOTIFY #1`
> fires once, `PollCount` 0 → 1, the wall reads `01`, and 25 s at a 100 ms period delivers nothing more; the
> runner's own *"never fires"* is falsified and re-framed as *"runs once and never again"*. **Part 3** — the
> wall takes `0x06` and is never hit again, and phase 1's break-in finds the guest at rva `0x18f68` of
> `DxeCore.efi`, in `CacheRangeOperation` (`0x18f34`) running `dc civac` (`0x1e260`) forward over the
> `Display Reserved` framebuffer at `0xa0ec5000` — the tail of `SerialPortWrite`'s
> `WriteBackInvalidateDataCacheRange ((VOID *)FbBase, FbLength)` (`FrameBufferSerialPortLib.c:276`), 9.9 MB per
> printed line — so nothing is stopped and the guest is running the instrument's own digest loop. That loop is
> now named: `P2UsbCensus ()` is called at the tail of `P2Digest ()` (`mu-basecore-local.patch:1749`), which
> `CoreDisplayDiscoveredNotDispatched ()` calls once and 40 more times with `P2Hold ()` between
> (`Dispatcher.c:2912`, `:2914-2917`), itself called once from `DxeMain.c:576` after `CoreDispatcher ()`. So
> `P2 USB n=` is a **pass counter** — the three baselines carry one pass (`FREE` ×1, `WALK` ×5, `BIN` ×4)
> against `panel4201`'s 21/106/82 — and with the panel's ~90 s load offset the probe's xHCI polls (`@17.1s`),
> hub notification (`@18.2s`) and wall (`@18.7s`) all fall in the 27 s in which `P2UsbCensus`'s `P2Reconnect`
> is inside `CoreConnectController`: 4.199's and 4.200's driver is the right driver, and the context it was
> placed in is not — DXE dispatch had ended ~2 s earlier at `P2 NOLOAD total=0 shown=0`. Pass 1's census row,
> the only pre-connect reading, is `P2 USB n=1 all=139 pciio=0 usb2hc=0 usbio=0 blkio=0 fs=0 cfg=1 loaded=77`
> in all four runs; passes 2-19 read `pciio=1 usb2hc=1 usbio=0 blkio=0 fs=0`, so this machine publishes the USB
> bus protocols and has nothing behind them. Nothing was flashed, `UsbConfigDxe.efi` is still
> `sha256 6943cc61…`. See `docs/08` step 4.201.
> **4.202: the gate four steps called shut is open in every payload this family ran, and with it open the USB
> chain assembles.** `P2 GATE2` reads `w88=00000000 w8c=00000001` on every pass of both 4.201 runs, and those
> are exactly the two words `tools/patch-usbcfg-sentinel.py`'s `SITES` table rewrites, so the payload carries
> the paired `host,index` patch and the instrument did not write them (its ledger is nine answers at the wait,
> two at the xHCI polls, one at the wall). 4.181's/4.182's/4.183's shut-gate readings are readings of the
> pristine binary; both on-disk copies are still pristine and git-ignored, so `device/dxe` is untouched. With
> the gate open, `P2 SUPP BEB12BEE-…` (`XhciPciEmulation`) `s=Success` at `106.06s` and `P2 SUPP B7F50E91-…`
> (`XhciDxe`) `s=Success` at `107.06s`, and `usb2hc` goes 0 → 1 — so the emulated controller is published and
> bound, and the chain stops only at the root hub's wait for an interrupt the instrument cannot deliver (4.200).
> 4.201's two open items are decided without a run: `P2Reconnect` is the only connect (`cc=2`, both its own),
> and all 41 digest passes would run, because no counter the digest prints moves across the eighteen the window
> captured. The patched payload is a **counterfeit** construction-time value and the patcher's cost paragraph is
> carried with it. Nothing was flashed, `UsbConfigDxe.efi` is still `sha256 6943cc61…`. See `docs/08` step 4.202.
> **4.203: the `GetOtgStatus` row is printed by `XhciDxe`, the payload's provenance is measured, and the head of
> 4.202's chain is an instrument artefact.** The format string lives at `0x10637` in the bitra `XhciDxe.efi` and is
> referenced once, at `0x33d0`/`0x33d4` (not the carried `0x43d0`), printing only for a non-`UNSUPPORTED` result of
> the protocol member at `[x0, #152]` — a generic error arm, not a device message; the second `#0x637` reference is
> at `0xaeac` over base `0x12000`, i.e. `0x12637`, an unrelated assert. The provenance census compares the build
> tree's 87 `<GUID>SEC2.1.pe32` images against the 86 stock `device/dxe/*.efi`: 41 byte-identical, 21 wholesale
> different (the EDK2 core is Mu-Silicium's), **`UsbConfigDxe` different by exactly six bytes** — one basic block,
> `FVMAIN.Fv` `0x3a9d30` against the pre-depex archive `0x3a8cec`, `orr w9, wzr, #0x1` → `mov w9, wzr` and
> `orr w10, wzr, #0x10000` → `mov w10, #0x1`, the paired signature occurring once in `FVMAIN.Fv` and never in the
> archive or the device copy — 23 stock images with no `SEC2.1.pe32`, and 24 build-only images including `XhciDxe`,
> `XhciPciEmulation` and the whole host-mode USB stack, so the payload's device-mode stack is stock Qualcomm.
> **And `PMIC was not detected`, the head of 4.202's chain, is producible by this instrument alone**:
> `MemoryMapLib.c:75` declares `PMIC ARB SPMI` at `0x0C400000`+`0x02800000`, and `tools/qemu-panel-read.py`'s own
> `low_regions()`/`l2_plan()`/`block_for_ipa()` put it in stage-2 blocks **98-117 → pool `0x42c00000`-`0x45200000`**,
> zeroed RAM (both GIC windows being block 189 → `0x46800000`), so every SPMI read in `PmicDxe`'s presence probe
> returns zero, the 13-slave scan for slave `0x51` finds nothing, and the driver reports not-detected — which makes
> "a payload failure on real hardware" an open question rather than a finding. Nothing was flashed,
> `UsbConfigDxe.efi` is still `sha256 6943cc61…`. See `docs/08` step 4.203.
> **4.204: the instrument's GIC block is the machine's own controller, and the payload's writes reach it and are
> refused.** `--el3-gic-real` (`MACHINE_GIC_BASE = 0x08000000`, `REAL_REGIONS`, `REAL_PAGES` in
> `tools/qemu-panel-read.py`; `S2_L3_OFF` and the `.ifdef S2_L3` include in `tools/qemu-el3-stub.S`) points stage-2
> block 189 at the machine's distributor and aliases IPA page 0 — which is `PcdGicInterruptInterfaceBase`, 0 here
> because `BitraPkg.dsc.inc:44-46` overrides only the distributor and redistributor bases — through a generated
> level-3 table to `0x08010000`, because IPA 0 shares its block with `GCC CLK CTL`. Measured three ways: the header
> self-verifies (`L1[0] = 0x48003003, 53/53 redirected, 1/1 aliased, 457/457 identity, 512/512 level 3 pages`), the
> registers read back live (`GICD_CTLR 0x1 TYPER 0x408 IIDR 0x43b`; `GICC_CTLR 0x1 PRIMASK 0x0 BPR 0x7 IAR 0x3ff`),
> and `0x17A60000` now **aborts** through the guest where 4.201 read pool RAM. The payload's `ICDDCR`/`ICCICR` writes
> arrive — they are the two bits a non-secure writer may set (`arm_gic.c:1200-1209`, `:745-763`) and they read back
> set, while nothing else could have written them (no monitor write command, and `-device loader` at a device
> address is silently dropped). **The zeros are a non-secure view, proved not assumed**: `GICD_CTLR` prints `0x1`
> where a secure read (`:958-967`) would print `0x2`, and `GICD_IGROUPR0 = 0x0` is RAZ/WI for NS by definition
> (`:988-993`). **Nothing is delivered** because `-M virt,secure=on` sets `has-security-extensions`
> (`hw/arm/virt.c:754`), no secure firmware runs, so `arm_gic_common_reset_hold` takes `resetprio = 0`
> (`arm_gic_common.c:279-286`; `irq_reset_nonsecure` is set only by `arm_gic_common_linux_init` `:334-347`, which
> `virt.c` never calls) and every interrupt stays in Group 0 — and `ArmGicV2Dxe.c` writes no `ICDIGROUPR` at all,
> because on the phone the secure world does the grouping first. **The timer number is wrong too**: `-M virt`'s DTB
> gives INTIDs 29/30/27/26 against `BitraPkg.dsc.inc:51-52`'s 17/18 and `ArmPkg.dec:266-267`'s 27/26. The carried
> prediction that `PcdArmArchTimerVirtIntrNum` is unset is **false** (`ArmPkg.dec:267`, `TimerDxe.inf`
> `[Pcd.common]`), and `TimerDxe` ran (`K 9 Ss 9/69 … 49EA041E-…`). Otherwise the run is 4.201 line for line:
> `HUB NOTIFY` exactly once at 18.2 s, the wall answered by hand at 43.6 s, digest rows unchanged. SPMI stays blank
> as the directive said: no SPMI arbiter on `-M virt` to alias to. Nothing was flashed, `UsbConfigDxe.efi` is still
> `sha256 6943cc61…`. See `docs/08` step 4.204.
> **4.205: the instrument delivers — one interrupt per leg, INTID 30 for `CNTP` and 27 for `CNTV`, counted by the
> guest's own handler.** The stub gained a `GIC_SECURE` block (behind the reader's `--el3-gic-secure`, `:792` in
> `tools/qemu-el3-stub.S`) that runs before `scr_el3` is written and does what `arm_gic_common_linux_init` would do
> if `virt.c` called it: `0x80` to all 288 priority bytes, `0xFFFFFFFF` to all 9 `IGROUPR` words, `0xff` to
> `GICC_PMR`, then `dsb sy` and two **secure** read-backs into `s2_diag` words 4 and 5 — never touching `GICD_CTLR`,
> because the payload's own write is what turns Group-1 forwarding on. A 4,236-byte non-secure EL1 guest
> (`work/out/qemu-probe-4.205/gic-selfirq.S`) repeats the payload's four writes, enables all four timer PPIs, arms
> **one** timer, waits masked on the machine's own `GICD_ISPENDR` bit, unmasks, and in its handler reads `GICC_IAR`,
> writes `GICC_EOIR` and clears the taken INTID's enable. Measured: `ICENABLER0 = 0x2c00ffff` with `pending: 30` on
> the `CNTP` leg and `0x6400ffff` with `pending: 27` on the `CNTV` leg, i.e. **exactly one delivery per leg**, with
> the delivered INTID provably the one taken because it is the only INTID the guest enabled that is missing from
> that leg's Group-1 set; `GICC_PRIMASK 0xfe`, `GICC_PMR 0xff` and `GICD_IGROUPR0 0xffffffff` alongside. **The
> INTIDs are pinned by measurement**: the DTB's `/timer` order is S_EL1, NS_EL1, VIRT, NS_EL2 (`virt.c:362-378`),
> `intidbase = NUM_IRQS + i*GIC_INTERNAL` makes `INTID = 16 + PPI` (`virt.c:810-812`) and `[GTIMER_PHYS] =
> ARCH_TIMER_NS_EL1_IRQ` (`virt.c:817-820`), giving **29 secure EL1, 30 non-secure EL1, 27 virtual, 26 EL2** — which
> **corrects 4.204's parenthetical**, where 29/30 and 27/26 were swapped. **Why the payload still sees nothing is a
> number**: its `GICD_ISENABLER0 = 0x0c06ffff` (`0..15, 17, 18, 26, 27`) is precisely `TimerDxe.c:401/409/413/416`'s
> four registrations, `ArmPkg.dec:264-267` defaults them 29/30/26/27 and `BitraPkg.dsc.inc:51-52` overrides
> `Sec|0x11` and `Int|0x12`, while `USE_PHYSICAL_TIMER = 1` (`BitraPkg.dsc.inc:10`) makes `TimerDxe.c:161-166`
> program `CNTP` — the machine raises **30**, a number the payload registered nothing for; the next run changes
> `PcdArmArchTimerIntrNum` 18 → 30. The enable row is the Group-1-enabled set rather than RAZ, so `ICENABLER0` is
> the same set printed twice and not its complement (`arm_gic.c:1009-1027`), correcting 4.204's *"only the Group-1
> bits"* framing; the SGIs 0-15 are a reset default (`arm_gic_common.c:295-299`); an isolation run with no payload
> reads **0 of 288** priority bytes non-zero, so every `0x80` in the payload run is the payload's own; and the
> carried open item that the delivery guest's PPI enables *"did not land"* is withdrawn — it was a 16-bit-shifted
> literal (`0x6C00`) in that file, not a property of the machine. SPMI stays blank, nothing was flashed,
> `UsbConfigDxe.efi` is still `sha256 6943cc61…`. See `docs/08` step 4.205.
> **One map gap named**: the platform's own
> `MemoryMapLib.c` declares `USB30_PRIM`, `USB_RUMI`, `USB30_SEC` and the four `*_CLK_CTL` at
> `0x18280000`, and **no row *named* for `0x088E3000` or `0x088E8000`**, where the live tree puts
> `/soc/qusb@88e3000` and `/soc/ssphy@88e8000` (`/proc/iomem` confirms `088e3000-088e33ff :
> qusb_phy_base`). **Corrected in 4.194**: the missing *name* is not a missing *region* — the same file
> declares `{"PERIPH_SS", 0x08800000, 0x00200000}`, whose 2 MB block 68 covers both addresses, and
> `l2_plan()` redirects every block a declared region touches, so those registers **are** served by the
> zero model; the 4.193 sentence that they "fall through to the identity map" is withdrawn. A candidate
> edit — add finer `PERIPH_SS` sub-regions so each live tenant has a name — is **offered and not made**.
> `ufshc@1d84000` carries
> **no `iommus` property**, and there is **no framebuffer route** (`/dev/fb*`, `/proc/fb` and
> `/sys/class/graphics/` all absent), so `先读屏` stays a photograph. See `docs/08` step 4.193.
>

**Status (2026-09-25, corrected 2026-09-27 — see Steps 4.147, 4.149, 4.150, 4.151, 4.152, 4.153, 4.154, 4.155, 4.156 and 4.157): item 1 is done for UFS, USB, the PMIC family, the GPIO controller,
the Type-C controller and I2C, and every one of those nodes answers a shipped driver. Of the three
items this sentence used to list as open, **one is open and two were not.** The thermal zones closed
at Step 4.73, which is the step that joined the board's zone names to `qcpep7280.inf`'s ids, and the
thirteen objects it produced are in the DSDT today. The pins of the two TSENS controllers were never
writable: no TSENS device exists in any of the 65 reference tables, and Windows' thermal path is the
`ThermalZone` objects themselves, which take their readings from the TSENS side *under* the PEP — so
there is no TSENS ACPI node to write, and the negative is a measurement rather than a gap. The third
item, **the SPI engines**, is not open work either, and Step 4.149 measures why: `SE0` at
`0x00880000` carries the Novatek touchscreen at 10 MHz and `SE6` at `0x0098C000` the IR blaster in
*this unit's own overlay* (entry 13, Step 4.54 — the stock device tree calls the same two windows
`i2c@880000` and `serial@98c000`), but the SC7280/Kodiak Windows driver set declares no SPI engine id
and contains no SPI controller driver at all, so a node written for either would bind nothing. The
ASL's deferral — "written when a slave with a driver arrives rather than on their own" — is therefore
correct and its condition is *unmet by this set*, which is a different thing from item 1 being
incomplete. Item 1 needs no further ACPI.
Step 4.150 then read the OS's own driver set as a second oracle beside the vendor package, which
is the oracle that answers the two ids the vendor set does not: `storufs.inf` claims
`ACPI\QCOM24A5` for `UFS0` and `urssynopsys.inf` claims `ACPI\PNP0CA1` — `URS0`'s `_CID` — so the
union of the two sets covers 33 of this table's 34 QCOM ids and the single exception is `URS0`'s
`_HID`, which the vendor set names as the parent of the children its own filters bind. The
vehicle is `tools/os-driver-store.sh`, which pulls the DriverStore `.inf` files out of
`boot.wim` or `install.wim` so `--drivers` can be pointed at them; the two images are not the
same set, and the parent driver is in the second one only.
Step 4.151 then made the census count claims rather than the string `ACPI\…`, which had been
standing in for one of five positions an `.inf` writes an id in. The vendor set is 155 claims (from
158: three of its ids were claimed only by `;`-commented installer notes), `boot.wim` 80 of 85
occurrences and `install.wim` 111 of 116 — the difference in each OS image being the same five
`[Strings]` key names, `ARMH_PL180`, `DOCKDEVICE_DESC`, `FIXEDBUTTON_DESC`, `INT33BA` and
`THERMALZONE_DESC`, two of which name a different id than the file binds. Nothing about item 1's
coverage moved: every verdict for this table's 34 ids is unchanged, and `--bind` now prints *where*
each answer came from — the position that matters here is `compatible`, the one `URS0`'s `_CID` is
matched through and the one a hardware-id-only column would have reported as silence.
Step 4.152 then asked the artifacts which *architecture* those two oracles are, rather than taking it
from the ISO's name, and the answer splits the item in half. A DriverStore folder is
`<inf>_<arch>_<hash>`, so the suffix counts what the image is: `install.wim` index 1 holds 710
`_amd64_` packages, 2 `_x86_` and **no `_arm64_`**, `boot.wim` index 1 holds 339 `_amd64_` and no
`_arm64_`, and all five infs behind the two QCOM verdicts (`storufs`, `urssynopsys`, `ufxsynopsys`,
`urschipidea`, `ufxchipidea`) are `NTamd64`-only — every `[Manufacturer]` entry ends `,NTamd64`,
every models section is `.NTamd64`, no `NTarm64` section in any of them. So the OS half of the
reading is missing the file that would carry it, and `storufs.inf` binding `ACPI\QCOM24A5` is a
statement about an x64 image whose ARM64 twin is a different file. The vendor half is already an
ARM64 reading: `~/work/woa-ref/inf-7280` is 112 `.inf`, all UTF-16, 241 `NTARM64` decorations and not
one line mentioning `NTamd64`, `NTx86` or `NTia64`, so its 155 claims are ARM64 claims and the 32 of
this table's 34 ids it answers are answered on the right architecture. What is left costs exactly the
two ids the OS oracle exists for, and they are not equal in weight: `QCOM0A8B` is USB, `QCOM24A5` is
the storage Windows would boot from. The same pass wrote down the two things the vendor USB filters
say that this table had not recorded — `QcXhciFilter7280.inf` also binds the *standalone* host-mode
ids `ACPI\QCOM0A24` and `ACPI\QCOM0AA1`, so the `URS0` route this table took is a choice between two
and not the only one, and its sibling `QcUsbFnSsFilter7280.inf` extends the Synopsys UFX
(`Include=ufxsynopsys.inf`, `StartType=0`, `Group=filter`), which is vendor-side corroboration that
`PNP0CA1` and not the ChipIdea `PNP0C90` is this platform's role-switch — while `storufs.inf`'s own
`ACPI\CC_010901` entry is a third route that is written down and left alone, since whether `acpi.sys`
ever produces a class-code id is not readable from an `.inf`.
Step 4.153 closed the half Step 4.152 left, by reading the ARM64 twin rather than waiting for one. The
blocker had never been the media, it was the host: `dl.delivery.mp.microsoft.com`, which is what the
ISO's own download path uses, answers 000 here, but a UUP `get.php` id returns per-file signed URLs on
`tlu.dl.delivery.mp.microsoft.com` and that host answers 206 on a range request in 0.28 s. 68 files,
8.07 GiB, every one verified against the index. The edition ESD is a *delta* WIM — 7z writes 159 of its
389 DriverStore packages as zero-byte files and `wimlib-imagex` needs `--ref` to each of the other 18
ESD/WIM files in the set to resolve the base — and with that, 386 of the 389 extract, none empty. The
arm64 DriverStore is 389 packages, 387 `_arm64_` and 2 `_x86_`, the same shape as the x64 image's
710/2, and `--bind` against it moves no verdict: `storufs.inf` binds `ACPI\QCOM24A5` under
`[Qualcomm.NTarm64]`, `urssynopsys.inf` binds `ACPI\QCOM24B6, ACPI\PNP0CA1` under
`[UrsSynopsys.NTarm64]`, and the generic `ACPI\CC_010901` route is there too. So the two OS-side
claims were the same claim in both builds, the x64 reading was not a weaker one, and what is still
open is the other thing this file has been carrying: which id names `URS0`'s children, which is
`UrsSynopsys.sys`'s behaviour. The same extraction shows the two URS families split cleanly
(`QCOM24B6`/`PNP0CA1` Synopsys, `QCOM24B7`/`PNP0C90` ChipIdea), that the vendor's own spellings
`QCOM0A8B`, `QCOM0A8C`, `QCOM0A24` and `QCOM0AA1` are named in no file of the OS set, that Microsoft's
URS children are `<parent>&FUNCTION` where the vendor filter's is `<parent>&HOST`, and that `PNP0D80`
*is* named — by `machine.inf`, root-enumerated as `*PNP0D80` with a `NO_DRV` placeholder, a fourth
position the census's `ACPI\` scan cannot see.
Step 4.154 then read the image the P3 gate actually loads, which is the *third* ESD image rather
than the first. The three are one medium in three pieces: image 1, `Windows Setup Media`, 274.6 MB,
is the medium's whole EFI tree — `/efi/boot/bootaa64.efi`, `/bootmgr.efi`, `/efi/microsoft/boot/cdboot.efi`
and its `_noprompt` twin, the BCD, `/boot/boot.sdi`, `efisys.bin`, the boot fonts, `bootres.dll` —
and it holds **no `/sources/boot.wim`** among its 934 files under `/sources/`, because that is image
2. The loaders are ARM64 by their PE headers, not by their names: `bootaa64.efi` (2,622,784 B),
`bootmgr.efi` (2,608,560 B) and `cdboot.efi` (968,096 B) all carry machine `0xaa64`; the
removable-media slot is `BOOTAA64.EFI` and there is no `bootarm64.efi` or `bootx64.efi` in any of
the three images, so the obvious-looking analogue is the one name that would not be found; and
`bootaa64.efi` hashes identically to image 2's `bootmgfw.efi`, so it is the boot manager under its
fallback name rather than a separate program. Image 2 is the WinRE WIM, **233 DriverStore packages,
all 233 `_arm64_`**, all 233 `.inf` readable with `--ref` and none empty, and `--bind` gives 63
claimed ids — 55 hardware, 5 compatible-only, 3 `ExcludeFromSelect`. Both storage-path ids are among
them: `storufs.inf` claims `ACPI\QCOM24A5` for `UFS0` and `urssynopsys.inf` claims `ACPI\PNP0CA1`,
`URS0`'s `_CID`, in the `compatible` position, with all four URS files present in the boot image. That
is a difference from x64, where the boot image carried the child driver only, and it means the
earlier reading that booting the installer would leave `URS0` unbound does not transfer. The image
also carries `diskpart.exe`, `Dism.exe` and `bcdboot.exe`, so Microsoft-signed files alone can
partition, format, apply and re-boot, and the only non-Microsoft byte a P3 medium needs is a
two-line `winpeshl.ini` — image 2's own 53-byte copy starts `recenv.exe`, not a prompt.
Step 4.155 then asked where that medium is supposed to *live*, and the answer makes the USB host
stack part of the gate rather than a peripheral. `boot`, the one partition the standing relaxation
allows writing, is **128 MiB** and holds the firmware — the `fastboot flash boot` payload, currently
1,171,456 B — so no OS image has ever been able to sit there beside it. Against the partition table
the smallest Microsoft-signed ARM64 Windows image, the WinRE at 446,983,676 B LZX, plus the
34,642,491 B ESP that boots it, is 481,626,167 B: `boot`, `recovery` and `rawdump` at 128 MiB miss by
325 MiB, `minidump` at 96 by 357, `cache` and `exaid` at 384 by 69, and the only two large enough are
`super` (the installed ROM, unrecoverable) and `userdata` (off limits). So the medium is external by
design, which is why `UsbBusDxe` is P3 item 2: a BDS without a working XHCI host has reached a menu
with nothing on it. The size profile says stripping was never an option either — applying image 2
gives 1,565,170,844 B, of which `System32` is 933 M and `WinSxS` 364 M before any compression, and
LZX runs 2.8:1 on the deduplicated data, so a stripped PE might reach 250–300 MiB and 128 MiB is
reachable only by a hand-built PE with a file list no ARM64 ADK on this host can supply. The medium
is built by `tools/p3-medium-build.sh` (51 s end to end) and is 51 files of unmodified Microsoft
bytes; the device window reads three outcomes rather than two — the recovery UI means the kernel
booted with a driver set that binds `ACPI\QCOM24A5` and the gate's first half is answered, a Boot
Manager error means handoff succeeded and the failure is downstream, and a blank panel means the
failure is upstream and the stick is not implicated. Its one recorded trap beyond the layout:
`wimlib-imagex export` is not byte-reproducible, so two builds agreeing in every reported field and
in the full file listing still differ in sha256 — a hash of `boot.wim` fingerprints the build, not
the content.
Buttons are written as of Step 4.89 (`BTNS`, `ACPI0011`), the node that needed
no shipped driver at all because the operating system supplies it, and the USB port is written
as of Step 4.90 — the `RHUB`/`PRT1` pair under each of `URS0`'s two children, the node that
needs no driver id because `_ADR` is its identity, and the one that gives Windows a port to
attach instead of a capability blob on the controller that owns it. Step 4.91 wrote no node
of its own — it is the one step here whose subject is the evidence rather than the firmware,
and it moved the counts that justify Step 4.90 into the repository as
`tools/acpi-usb-pair-census.py`, which is where they can be asked again; seven of them
changed when it did, which is the argument for the tool rather than the number. Step 4.92
writes `ADC1` (`QCOM0A11`, the one id `qcadc7280.inf` claims, binding the service `qcADC`) as
the last device of `_SB` — the node that waits on nothing this table has not already got,
because both of its `_DEP`s and the one resource provider its `_CRS` names are in it, and the
first node here whose twelve bytes of vendor data had to be answered by the corpus rather than
by the board, since no firmware partition on this device carries a DSDT and the driver reads
its own `ADC1.bin`; the tool that answers for them is `tools/acpi-adc-blob-census.py`, and its
20 tables say the first of the two moving bytes travels with the pin pair and the second with
the `_HID`, which is why `0x34` is written — `0x35` being what one byte's difference would
give. Step 4.93 writes `PEP0` (`QCOM0A17`, `_CID` `PNP0D80`, claimed by `qcpep.wd7280.inf`)
with its companion `AGR0` (`ACPI000C`) — the node every withheld `_DEP` in this file has been
waiting on, carrying the `_DSM` Windows' power engine calls to ask about subsystem state, the
`THTZ` dispatcher it polls for thermal trip points, the eleven-GSI `_CRS` whose first four are
derived from this board's own PDC ranges and tsens interrupts rather than copied, and a
`PPPP` of forty-six rails that are all this board's regulator nodes. It also lands the
`_DEP`s that only became writable with it: on `ABD`, on `UCS0`, on `URS0`, and as a `Method`
on twelve of the thirteen thermal zones, plus `_TZD` on the three `_UID One` pairs. Five
comments that said PEP0 was absent, and one that reserved the `UCS0` `_DEP` line this step
wrote, are corrected in the same step; the SMMU comment's count was wrong besides — the
corpus's 40 SMMU nodes split 31 `{PEP0}` to 9 `{MMU1}`, not 40 to 0 — so that engine entry
is deferred to the step that settles the family's splits, and the corrections are comments
only: the AML and all three payloads came out byte-identical. Step 4.94 is the second
evidence step, and the one whose subject is the *reader*: it writes the seven engine and
SMMU `_DEP`s that `PEP0` unblocked — `I2C8`, `I2C9`, `UAR2`, `IC11`, `MMU0`, `MMU1`,
`SCM0`, all the one-entry `{PEP0}` form — and then found that every `_DEP` count this file
had written was measured by a reader that could not have measured it: the census counted
this table as part of the corpus it was measuring, read `_DEP`'s in-parenthesis package as
empty, and could not see a three-character device name at all. The re-measurement lives in
`tools/acpi-dep-census.py` now, the walk's short-name blindness is fixed (with `Scope` and
`External` deliberately left at four characters so bare `Scope (_SB)` cannot re-parent a
table), and eight comment corrections are recorded as corrections. 2–4 are not
started, and none of them can
be assessed until P2 hands off to BDS.**

The tables exist, are wired into `gauguin.fdf`
and `gauguin.dsc`, and are in the firmware volume of the build behind the staged P2
payload — `DSDT` (**2,369 bytes**, gauguin's own, `SM7225`, eight `ACPI0007` CPU devices,
the UFS and USB nodes, `SPMI`/`PMIC`/`PM01`, `GIO0` with its `OFNI` gpio count of 156,
and `UCS0`), `APIC`, `FACP`, `FACS`, `GTDT`, plus the shared `SSDT`. The tables were read
back out of the built artifact, the `APIC`
parsed subtable by subtable — its two INTIDs and its redistributor base match this
board's device tree — and the `DSDT` decompiled back out of the volume so that each node
could be read as the firmware will see it rather than as it was written.
`docs/07`'s P3 groundwork section carries the detail.

What admits a node here is no longer a reference table's resemblance but a shipped driver
naming its id, and four nodes now pass that test: `qcgpio7280.inf` binds
`ACPI\QCOM0A0C` for `GIO0`, `qcusbcucsi7280.inf` binds `ACPI\QCOM0AA4` for `UCS0`
(Step 4.66), `qcpmicgpio7280.inf` binds `ACPI\QCOM0A2D` for `PM01`, and the two USB
filters bind `URS\QCOM0A8B` for the `URS0` that already exists — `QcXhciFilter7280.inf`
as `URS\QCOM0A8B&HOST` and `QcUsbFnSsFilter7280.inf` as `URS\QCOM0A8B&FUNCTION`. That
last one was the exception in the group and worth stating plainly: the census tool binds
`ACPI\<id>`, so `--bind QCOM0A8B` reported it **NOT CLAIMED** — correctly, since no
vendor `.inf` attaches a driver to the id itself, the two USB filters attaching under
their own `URS\` prefix. Three of the four were `ACPI\` bindings the tool confirmed by
name and the fourth a binding it could not see. **Step 4.150 corrects the second half of
that sentence and adds a fourth oracle to the first.** The tool can now see it — an id
nothing claims is printed with the other buses that name it, so `QCOM0A8B` reads as the
vendor set's own id with only the attach missing — and the *parent* side is claimed after
all, by the OS rather than the vendor: `urssynopsys.inf` binds `ACPI\QCOM24B6,
ACPI\PNP0CA1`, the second of those being the `_CID` this table writes on `URS0`. The
tool's PNP branch had been printing its own rule ("not looked up in this set") as a fact
about the hardware because it ran before the lookup; read now, three sets give three
different and correct verdicts for that one id.
`UCS0` is the shortest of them: one `GpioIo` on `GIO0` pin 35, and five one-line
accessors that return the `\_SB`-scope state names `MUXC`, `CCST`, `DPPN`, `HPDS` and
`HIRQ`, all of which were already in the table. Note that the DSDT is still smaller in
scope than the list above — at the time of writing neither I2C nor buttons nor the thermal
zones were in it (I2C closed at Step 4.87, buttons at 4.89 and the thermal zones at 4.73,
so **the SPI engines are the only item of that list still out**, for the reason Step 4.149 measures
rather than for a gap in the writing; Steps 4.147 and 4.149 correct this
parenthesis as well) — and the `GIO0`
controller is declared without the corpus's per-pin interrupt catalogue, because that
catalogue is board data and this board's device tree does not carry it.

**One sentence from the previous version of this paragraph was wrong, and Step 4.66
corrects it.** It said `UCS0` "cannot be written before `PEP0`". What cannot be written
before `PEP0` is the `_DEP` — lisa's `UCS0` carries
`Name (_DEP, Package (One) { \_SB.PEP0 })` — and a `_DEP` naming a namespace node that
does not exist resolves to nothing, so it buys nothing while costing a later reader a
dangling name to chase; `_DEP` is advisory start ordering and there is nothing here to
order against. `UCS0` itself is one id, one resource and five accessors, and it is in the
table now. `PEP0` (`QCOM0A17`, which `qcpep.wd7280.inf` binds) is still absent, and Step
4.67 measured what "large" means there: 2,501 lines and 96,109 bytes in lisa, and the same
size again in a52sxq's with exactly two lines differing — both in `_SUB`, which returns
`"CRD07280"` on lisa and `"QRD07280"` on a52sxq from a branch keyed on `\_SB.PSUB`, so it
is generator output carrying a reference-platform string and not board data, and it is the
first thing a port has to change, since this table's `PSUB` is `"MTP07225"` and lisa's
`_SUB` would fall off the end of both branches and answer zero. But 1,826 of those 2,501
lines are one method — `THTZ`, a dispatch on (zone, trip point) that is called by nothing
in any of the 20 tables that declares it — and the node's size is that dispatch's case
count on top of a skeleton of a few hundred lines, because the same node in a platform
with no zones wired to PEP is shipped as 629 lines whose whole `THTZ` is
`Return (0xFFFF)`. So the work is the skeleton plus one case per zone, and the reason it
is still absent is the other thing this step found: `PEP0` reaches `\_SB.IPCC`,
`\_SB.ABD.ROP1`, `\_SB.AGR0`, the `_STA` of six subsystems (`ADSP`, `AMSS`, `SCSS`,
`SPSS`, `WPSS`, `NSP0`) and the zones themselves, of which this table has `PSUB` and
nothing else. It is the opposite kind of node from `UCS0`: `UCS0` could be written before
its dependency, `PEP0` cannot be written before any of its six.

**And the rest is blocked on an input, not on effort.** Every one of those nodes
needs an ACPI `_HID`, and a device tree does not carry ACPI names: it has registers
and pins, which is the half that is knowable. `tools/acpi-hid-census.py` measures what
the reference DSDTs supply, and across all 66 of them the same block at the same
address carries a different `_HID` on every SoC — the TLMM window `0xF100000` is
`QCOM1A0C` on vili, lemonade and venus, `QCOM0A0C` on lisa and a52sxq, `QCOM250C` on
alioth, `QCOM090C` on renoir, `QCOM0C0C` on Kailua. No
Bitra-family reference exists either: `Platforms/Realme/bitra/DSDT.aml`, the source
of this file's form, has the same five devices gauguin has and nothing more.

**The thermal zone is the one item where that sentence has since been measured wrong,
and it is worth the correction because it changes what the item is.** It said "both TSENS
blocks are described by none of the 66: the corpus has no thermal-sensor device of any
kind". The corpus has no TSENS *controller*, which is true — but lisa and a52sxq carry 29
`ThermalZone` devices, every one of them with an `_HID`, and a census of
`qcpep.wd7280.inf`'s own device list gives each id a meaning: `QCOM0A37`–`QCOM0A51` and
`0A58`/`0A59`/`0AD4`/`0A91`/`0ABF`/`0A92`/`0A5A` are its `TSENS` entries,
`QCOM0A5D`–`QCOM0A64` its `ADC`, `QCOM0A57` its `BCL`, `QCOM0AC8`–`QCOM0ACB` its `PMIC`,
`QCOM0AD8`–`QCOM0AE0` its `SRM` — and the nine zones on lisa that are *not* in the 0A
family at all, `QCOM04C0`–`QCOM04C8`, are the ids `qcthermalmdm7280.inf` binds. So every
id is determined and claimed; what is missing is the work and the join — Step 4.67 found
the board data is not missing after all: gauguin's own device tree carries 40 zones with a
sensor index and a trip list each, 27 of them the SoC zones `sm6350.dtsi` declares, so the
trip points (`_PSV`, `_CRT`) are this board's own numbers and readable. The zones are 16 to
134 lines each and name cooling devices in `_TZD` (`\SB.MPA`, `\SB.SYSM.CLUS.CPU0-7`,
`\SB.WLTM`, `\SB.CSW0`, `\SB.GPU0`, `\SB.MJCT`) that this table does not have, and those
remain the gap. What is also still open is the *mapping*: lisa's 29 devices are 26 ids
because three ids carry a pair of zones distinguished by `_UID` `Zero` and `One`, and
nothing in this tree yet says which of the board's 40 zones is which id. None of the 29
carries a `_TMP`, so the ACPI side of a zone is its trip points and its sampling period,
not its readings.

The count is not the point; the decomposition is. A Qualcomm scoped `_HID` is
`QCOM<family byte><block index>`, and the *index* is fixed per generation of the
table generator — measured across 66 tables, the GPIO controller is `..0C` under
every modern family and `..0D` under the three older ones, the arbiter is `..0B`
and `..0C` respectively. Ten of gauguin's twelve blocks therefore have a known
index in each measured generation, and the one input left was which family byte
SM7225 carries. That byte does not follow the marketing name — pipa and
alioth both declare `SDM8250` and carry 05 and 25 — so it has to be read off a
driver set, and `--drivers DIR` tries all 256 bytes against each measured index
table and reports the one that names all ten blocks.

**That byte has now been measured, and it is `0A`.** The set is the SC7280 /
Kodiak one, `WOA-Project/Qualcomm-Reference-Drivers` → `7280_CLS/200.0.4.0`,
112 `.cab` files fetched from Windows Update by the reference-laptop OEM and
extracted to 112 `.inf`. Under the modern index table it names **8 of gauguin's
10 blocks**, and 0 of 10 under each of the other 255 bytes:

| block | id | block | id |
|---|---|---|---|
| SE0u | `QCOM0A16` | SE5 | `QCOM0A10` |
| SE1 | `QCOM0A10` | SE7 | `QCOM0A10` |
| SE2 | `QCOM0A10` | SPMI | `QCOM0A0B` |
| SE3 | `QCOM0A10` | TLMM | `QCOM0A0C` |

The two misses are `SE0` and `SE6`, which the set does not name at all; it would
take `QCOM0A0E`, the correct index for a UART in that table. So the misses are
absences in the *set*, not contradictions of the byte — a Kodiak board simply
does not publish those two as ACPI devices. Two further checks agree: the only
two tables in the whole 66-table corpus that carry these ids are
`Platforms/Xiaomi/lisa` and `Platforms/Samsung/a52sxq`, both declaring `SDM7280`,
both with `Device (GIO0) { Name (_HID, "QCOM0A0C") }`; and all eight ids land on
the expected *kind* of block in the right bit positions — `qcpmicgpio7280.inf`
claims `QCOM0A2D` and `qcpmic7280.inf` claims `QCOM0A2B` plus `QCOM0AD3`, where
`0x2D & 0x7F = 0x53` is a PMIC sub-function. A collision would not organise itself
that way across eight independent ids.

Stated honestly: `0A` is measured on Kodiak (SM7325), which is SM7225's sibling in
the same table generation, and no SM7225 Windows driver set and no independent
SM7225 reference DSDT exists to confirm it on the die itself. It is a measurement
with two independent oracles, not a proof. It also does **not** name the TSENS
sensor block: the set has no thermal-*sensor* device id at all, and neither it nor
any of the 66 tables describes one. What the set does name is the thermal **zones**
— `qcthermalmdm7280.inf` claims the consecutive range `QCOM04B4`–`QCOM04CE`,
which contains `QCOM04C0`–`QCOM04C8`, the nine that Step 4.58 found fixed across
six tables in four families with no explanation. So the zones live in a *fixed*
`QCOM04xx` space rather than the family-byte space, and that observation now has a
driver behind it instead of only the corpus. It still does not say which of
gauguin's 40 device-tree zones takes which id.

Read that as the name being **a declaration rather than a hardware fact**: a device
binds to the `_HID` its `.inf` lists and to nothing else, so the tables are written
*to a driver*, not *to the SoC*, and the corpus disagreeing on every SoC is evidence
the choice is free rather than evidence that a correct name is missing. The driver
set was the missing input; it is now in hand and read, and it is what turns
"a plausible `QCOM`-prefixed name" into "the name a real driver will claim".
Copying a name from another SoC *without* a set does not fail loudly — a node whose
`_HID` no driver claims is absent from Device Manager, and the hardware behind it is
silently not there, which is worse than a node that is visibly missing. Note what
that does and does not gate, though: **there is no `.inf` gate on the UEFI phase.**
`_HID` is firmware-supplied, TianoCore's `AcpiTableDxe` auto-computes
`_CID = PNP0C02` for any `QCOM`-prefixed `_HID` in the reserved range, and the
build already ships `QCOM0497`/`QCOM0498`/`QCOM24A5` with no driver set at all — so
none of this can break P2. What it prevents is authoring names that are *silently
wrong for specific UMDF clients later*. This is the same mechanism P5 names as
"re-bind the WoA driver INF"; P3's tables are its first instance. `BTNS` looks like
an exception —
its `_HID` is a standard `ACPI0011` Generic Buttons Device, so no vendor INF is
needed for it — but its `_CRS` names `\_SB.PM01` as the controller its `GpioInt`
resources belong to, and a PMIC node carries the same family byte (`PM01` is
`QCOM<family>2D` in the modern tables and `QCOM<family>30` under 05 08 14). So
the buttons wait for the same byte the rest of the blocks do.

Items 2–4 were said to be gated on volume space: "**the payload has 760 bytes of free
volume**", so DisplayDxe, UsbBusDxe and ButtonsDxe "will not fit" beside the P2
instrumentation. **That is a misreading of the figure, and the gate is not there.**

`FVMAIN` is declared `BlockSize = 0x1000, NumBlocks = 0` in `gauguin.fdf:19-22`, so
GenFv sizes it to the next 4 KiB boundary above its content and the reported "free"
is the slack left in that last block. Measured, it is exactly that and nothing else:
the 2026-09-24 23:30 build reports `0x702d08` taken → `0x703000` → 760 free, today's
01:20 build `0x72ced0` → `0x72d000` → 304 free, and upstream `suryaPkg` `0x676d30` →
`0x677000` → 720 free. All three are `(-taken) % 4096`; the number is always in
[0, 4095] and carries no capacity information at all. `FVMAIN` in fact **grew by
172,032 bytes between those two gauguin builds** and would have grown further.

What the payload is actually bounded by is the enclosing volume: `SILICIUM_UEFI.fd`
is `FVMAIN_COMPACT`, a fixed 3 MiB region, and today it is **35.6% used with
2,025,744 bytes free**. That 3 MiB is not a Mu-Silicium convention either — it is
the device's own memory map, from the `uefiplat.cfg` recovered out of XBL at P0:
`0x9FC00000, 0x00300000, "UEFI FD"`, walled below by `ABOOT FV` (`0x9FA00000`,
`0x00200000`, ending exactly at `0x9FC00000`) and above by `SEC Heap`
(`0x9FF00000`), with BootShim's `_StackSize` and the FV header's `FvLength` both
equal to `0x300000`.

The refutation needs no arithmetic, though: the `USE_CUSTOM_DISPLAY_DRIVER=1` build —
the one that contains `DisplayDxe` — **has already been built and validated** in this
volume (`Mu-gauguin.img` 1,210,368 bytes, `FVMAIN` `0x753000`, 47 images). So P3 items
2–4 are gated on P2 reaching BDS unconditionally, which is a statement about when the
debug instrumentation can be deleted, not about whether their drivers fit.

Step 4.63 then measured the other half of this — where the failure *does* come from.
A valid 11,536,368-byte `DSDT` (generated by `tools/acpi-pad.py`) builds with `FVMAIN
[99%Full] 18886656 (0x1203000) total, 18886408 used, 248 free` and `PROGRESS - Success`
— 2.57× the volume above, still "99% full" — while 2 MiB of incompressible noise in the
same slot fails as `the required fv image size 0x311bf0 exceeds the set fv image size
0x300000`, against `FVMAIN_COMPACT`. So the budget for a new ACPI node is that outer
volume's free space *after compression* (**2,056,522 bytes** as of Step 4.73, measured to shrink at 0.22 of new `FVMAIN` bytes — the inner `FVMAIN`'s own "1,160 free" is block rounding and not a cap), and
the `[99%Full]` percentage is a rounding artefact in both directions.

**One consequence for the record-keeping this plan asks for:** a payload hash is a hash
of a build, not of the source. `Silicon/Silicium/SiliciumPkg/Sec/Sec.c:48` compiles
`__TIME__`/`__DATE__` into `Sec.efi`, which lives in the outer volume, so two clean
builds of one tree give two `Mu-gauguin-silicon-gzip.img` hashes and **one**
`FVMAIN.Fv` hash (`85f6f9fc…542b30`). Record the `FVMAIN.Fv` hash — `tools/fv-inventory.py
<img> --dump-fvmain PATH` — when the point is *what the build contains*, and the payload
hash only when the point is *which build*, as `probe-fingerprint.py` and the `boot`
control do.

---

## P4 — Windows deployment

1. Repartition: shrink `userdata`, create an ESP, and add the Windows partition layout
2. Fetch a Windows 11 ARM64 build (UUP dump) and deploy it to the device
3. First boot

**Gate:** Windows desktop appears.

**Point of no return:** this phase destroys `userdata`. Everything the user wants to keep
must be off the device before it starts.

---

## P5 — Hardware enablement, one device at a time

In rough order of value-versus-difficulty:

| Order | Subsystem | Work |
|---|---|---|
| 1 | Storage, USB, power, buttons | should already work from P3 |
| 2 | Touchscreen | Novatek over SPI — a Windows HID miniport; several exist upstream |
| 3 | GPU acceleration | Adreno 619 `a6xx`; re-bind the WoA driver INF. CPU rendering until then |
| 4 | Wi-Fi (`wcn3990`) | hardest of the "should work" items |
| 5 | Bluetooth | follows Wi-Fi |
| 6 | Audio | needs a Windows equivalent of the ALSA UCM config |
| 7 | Sensors, vibrator | piecemeal |
| — | **Modem, cameras** | **not attempted — no driver exists** |

---

## Standing decisions

- **Never write to the device's storage until P4.** Everything through P3 runs via
  `fastboot boot`, which is non-destructive and instantly reversible.
- **Keep the backup current.** Any change to the partition layout invalidates parts of it.
- **Serial/log output before anything else.** A bring-up with no way to see what failed is
  not debuggable.
