#!/usr/bin/env python3
"""Plan and apply the P4 shrink of `userdata`, so Windows has somewhere to live.

P4's gate is a Windows desktop, and the first thing it needs is partitions. The
plan in `docs/00`, "P4 — Windows deployment", is cheap for one structural reason:
`userdata` is #34, **the last entry in the table**, so shrinking it and appending
ESP, MSR and NTFS rewrites one partition's end LBA and adds entries - and **moves
no other partition**. This tool exists because that step is the irreversible one:
an interruption between the GPT write and the filesystem resize leaves `userdata`
unreadable, and the installed ROM is a `user/dev-keys` build with no public image
to restore it from.

It is therefore two-phase, and it never writes in place:

    gpt-shrink-userdata.py --images DIR            # read, print the plan, write nothing
    gpt-shrink-userdata.py --images DIR --apply --out DIR

`--plan` prints every partition with its old and new LBA range and marks the ones
that move. `--apply` requires `--out`, writes a fresh head and tail GPT there and
leaves the input untouched; the result is then read back by a **second parser**
(`reparse`, sharing nothing with the writer except the CRC routine) and a
mismatch is a hard error rather than a warning.

A shrink rewrites **both** GPTs. The primary at LBA 1 and the secondary at the
last LBA carry a copy of the same entry array, and the secondary is the one a
failed edit leaves inconsistent, because it lives at the end of the disk and is
the copy nothing reads until something has already gone wrong. This tool
therefore refuses to run without the **tail** of the device: given only the head
it cannot rewrite the secondary, and a tool that quietly produced a half-updated
table would be worse than no tool at all.

Usage:
    gpt-shrink-userdata.py [--images DIR] [--win-gib 64] [--esp-mib 512]
                           [--msr-mib 16] [--keep-userdata-gib N]
    gpt-shrink-userdata.py --apply --out DIR            # writes, never in place

Exit codes: 0 planned or applied, 2 no secondary GPT in --images, 3 the two entry
arrays already disagree, 4 the rewrite did not verify, 5 --apply without --out.
"""
import argparse
import json
import os
import struct
import sys
import uuid

GPT_SIG = b"EFI PART"
MIB = 1024 * 1024
GIB = 1024 * 1024 * 1024

ESP_TYPE = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
MSR_TYPE = "E3C9E316-0B5C-4DB8-817D-F92DF00215AE"
WIN_TYPE = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"

# This device's `userdata` type, read from the recorded table rather than assumed:
# it is not the Windows basic-data GUID and not 0 either.
USERDATA_TYPE = "1B81E7E6-F50D-419B-A739-2AEEF8DA3335"


def le16(b, o): return struct.unpack_from("<H", b, o)[0]
def le32(b, o): return struct.unpack_from("<I", b, o)[0]
def le64(b, o): return struct.unpack_from("<Q", b, o)[0]


def crc32(data):
    """The GPT CRC: reflected, poly 0xEDB88320, init 0xFFFFFFFF, final inversion.

    That is plain standard CRC-32, and it is bit-for-bit `zlib.crc32`. An earlier
    note in this file claimed the opposite -- that EDK2's `CalculateCrc32` omits
    the final inversion and so is *not* `zlib.crc32` -- and the claim was wrong.
    EDK2's `BaseLib/Crc32.c` opens with `Crc = 0xFFFFFFFF` and closes with
    `return Crc ^ 0xFFFFFFFF`, and the device settles it: the recorded primary
    header out of `~/backup/gauguin/images/GPT-sda.bin` stores `c52f1afc` where
    `zlib.crc32` of that header with its own CRC field zeroed is `c52f1afc`, and
    its 64-entry array stores `651472fe` where `zlib.crc32` of the 8192 bytes at
    `PartitionEntryLBA` is `651472fe`. Both match, and only `zlib.crc32` matches.

    The loop below is kept rather than replaced with the one-liner so that this
    file has no import beyond `struct`/`json`/`uuid`, and so the polynomial and
    the inversion are both visible at the site that depends on them. Confidence
    here is not from reading the source, it is from the two CRC fields the
    firmware itself wrote, which this function reproduces.
    """
    poly, crc = 0xEDB88320, 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (poly & -(crc & 1))
    return crc ^ 0xFFFFFFFF


def guid_bytes(s):
    a, b, c, d, e = s.replace("{", "").replace("}", "").split("-")
    return struct.pack("<IHH", int(a, 16), int(b, 16), int(c, 16)) + bytes.fromhex(d + e)


def guid_str(b):
    return "%08X-%04X-%04X-%s-%s" % (le32(b, 0), le16(b, 4), le16(b, 6),
                                     b[8:10].hex().upper(), b[10:16].hex().upper())


def parse_header(hdr):
    """Pull the fields this tool uses out of one 92-byte GPT header."""
    return dict(my_lba=le64(hdr, 24), alt_lba=le64(hdr, 32),
                usable_first=le64(hdr, 40), usable_last=le64(hdr, 48),
                disk_guid=hdr[56:72], ent_lba=le64(hdr, 72),
                num=le32(hdr, 80), esz=le32(hdr, 84),
                ent_crc=le32(hdr, 88), hdr_crc=le32(hdr, 16),
                hdr_size=le32(hdr, 12))


def load_entries(blob, num, esz):
    out = []
    for i in range(num):
        e = blob[i * esz:(i + 1) * esz]
        if len(e) < esz:
            raise ValueError("entry array ends early at index %d" % i)
        if e[:16] == b"\x00" * 16:
            out.append(None)
            continue
        out.append(dict(type=e[:16], guid=e[16:32], first=le64(e, 32),
                        last=le64(e, 40), attrs=le64(e, 48),
                        name=e[56:128].decode("utf-16-le").split("\x00")[0]))
    return out


def read_primary(path, sector):
    """Read and validate the primary GPT. Returns `(hdr_bytes, entry_bytes)`."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(min(size, (2 + 32) * sector))
    if len(head) < sector * 2 or head[sector:sector + 8] != GPT_SIG:
        raise ValueError("%s: no GPT header at LBA 1 (sector=%d)" % (path, sector))
    hdr = head[sector:sector + 92]
    h = parse_header(hdr)
    if h["my_lba"] != 1:
        raise ValueError("%s: header at LBA 1 says MyLBA=%d" % (path, h["my_lba"]))
    stored = h["hdr_crc"]
    probe = bytearray(head[sector:sector + h["hdr_size"]])
    struct.pack_into("<I", probe, 16, 0)
    if crc32(bytes(probe)) != stored:
        raise ValueError("%s: header CRC %08x does not match the header's own bytes"
                         % (path, stored))
    ent_off = h["ent_lba"] * sector
    ent_len = h["num"] * h["esz"]
    blob = head[ent_off:ent_off + ent_len]
    if len(blob) != ent_len:
        raise ValueError("%s: entry array at LBA %d runs past what was read"
                         % (path, h["ent_lba"]))
    if crc32(blob) != h["ent_crc"]:
        raise ValueError("%s: entry array CRC %08x does not match the header's %08x"
                         % (path, crc32(blob), h["ent_crc"]))
    return hdr, blob


def find_tail(images_dir, sector, alt_lba, num, esz):
    """Locate the bytes of the secondary GPT - the tail of the device.

    The head dump this project recorded, `GPT-sda.bin`, is 17,408 bytes and stops
    inside LBA 4, so it holds the primary header and entry array and **not** the
    secondary at `AltLBA`. Looking for the tail is what stops that from being
    silently mistaken for a complete table.

    Either a whole-LUN dump or a dedicated tail dump is accepted, and both are
    recognised by size: a whole-LUN image reaches `(alt_lba + 1) * sector`, and a
    tail dump is exactly the sectors the secondary occupies.
    """
    ent_sectors = (num * esz + sector - 1) // sector
    need = (ent_sectors + 1) * sector
    for name in sorted(os.listdir(images_dir)):
        low = name.lower()
        if "sda" not in low and not low.startswith("gpt-"):
            continue
        p = os.path.join(images_dir, name)
        size = os.path.getsize(p)
        if size >= (alt_lba + 1) * sector:
            return p, size, "whole-LUN"
        if size >= (alt_lba - ent_sectors) * sector + need:
            return p, size, "head+tail"
    for name in sorted(os.listdir(images_dir)):
        if not name.lower().endswith(("-tail.bin", "-tail.img")):
            continue
        p = os.path.join(images_dir, name)
        if os.path.getsize(p) >= need:
            return p, os.path.getsize(p), "tail-only"
    return None, None, None


def read_tail(path, sector, alt_lba, num, esz):
    """Read and validate the secondary GPT, by its own header and its own CRC."""
    ent_sectors = (num * esz + sector - 1) // sector
    with open(path, "rb") as f:
        f.seek(alt_lba * sector)
        hdr = f.read(92)
        f.seek((alt_lba - ent_sectors) * sector)
        blob = f.read(num * esz)
    if hdr[:8] != GPT_SIG:
        raise ValueError("%s: no GPT header at LBA %d" % (path, alt_lba))
    h = parse_header(hdr)
    if h["my_lba"] != alt_lba:
        raise ValueError("%s: header at LBA %d says MyLBA=%d" % (path, alt_lba, h["my_lba"]))
    if h["alt_lba"] != 1:
        raise ValueError("%s: the secondary's AlternateLBA is %d, not 1" % (path, h["alt_lba"]))
    probe = bytearray(hdr[:h["hdr_size"]])
    struct.pack_into("<I", probe, 16, 0)
    if crc32(bytes(probe)) != h["hdr_crc"]:
        raise ValueError("%s: secondary header CRC does not verify" % path)
    if crc32(blob) != h["ent_crc"]:
        raise ValueError("%s: secondary entry array CRC does not verify" % path)
    return h, blob


def plan_layout(ents, sector, usable_last, esp_mib, msr_mib, win_gib, keep_gib):
    """Compute the new entry table. Returns `(new_entries, changes)`.

    `userdata` is found by name and must be the last entry in the table - the
    whole reason this is cheap is that nothing after it has to move. If it is not
    last, or if it is missing, the plan is refused rather than adjusted, because
    every other layout is a different and more expensive operation.
    """
    idx = [i for i, e in enumerate(ents) if e and e["name"] == "userdata"]
    if len(idx) != 1:
        raise ValueError("expected exactly one `userdata` entry, found %d" % len(idx))
    ui = idx[0]
    occupied = [i for i, e in enumerate(ents) if e is not None]
    if ui != max(occupied):
        raise ValueError("`userdata` is #%d but #%d is the last entry; the shrink is only "
                         "cheap when it is last" % (ui, max(occupied)))

    ud = ents[ui]
    start = ud["first"]
    span = usable_last - start + 1
    esp = esp_mib * MIB // sector
    msr = msr_mib * MIB // sector

    # Alignment: every new partition starts on a 1 MiB boundary, which is what
    # Windows Setup's own diskpart aligns to and what a 4 KiB-sector UFS makes
    # free. `userdata` keeps its own start, which the stock table already aligned.
    ALIGN = MIB // sector

    def align_up(lba):
        return (lba + ALIGN - 1) // ALIGN * ALIGN

    # `userdata` keeps its own start and only its end moves, which is what makes
    # this a single-entry edit. Its new size is chosen so that what is left, after
    # the two fixed partitions and the alignment padding, still meets the Windows
    # floor - and the Windows volume then takes the **remainder**, up to
    # LastUsableLBA, so the arithmetic cannot come up short. The padding is at most
    # `ALIGN - 1` sectors at each of three starts, and allowing for all three is
    # cheaper than being clever about a layout that is computed once.
    pad = 3 * (ALIGN - 1)
    if keep_gib is not None:
        ud_new = keep_gib * GIB // sector
        win_floor = 0
    else:
        win_floor = win_gib * GIB // sector
        ud_new = span - win_floor - esp - msr - pad
    if ud_new <= 0:
        raise ValueError("nothing left for `userdata`: %d sectors of span, %d wanted for "
                         "Windows, %d for ESP+MSR" % (span, win_floor, esp + msr))

    ud_last = start + ud_new - 1
    e_first = align_up(ud_last + 1)
    esp_first, esp_last = e_first, e_first + esp - 1
    msr_first = align_up(esp_last + 1)
    msr_last = msr_first + msr - 1
    win_first = align_up(msr_last + 1)
    win = usable_last - win_first + 1
    win_last = usable_last
    if win < win_floor:
        raise ValueError("only %d sectors are left for Windows, under the %d asked for"
                         % (win, win_floor))

    new = [e for e in ents]
    new[ui] = dict(ud, last=ud_last)
    free = [i for i, e in enumerate(new) if e is None]
    if len(free) < 3:
        raise ValueError("only %d free entry slots; three are needed" % len(free))

    def mk(name, typ, first, last):
        return dict(type=guid_bytes(typ), guid=uuid.uuid4().bytes_le,
                    first=first, last=last, attrs=0, name=name)

    new[free[0]] = mk("ESP", ESP_TYPE, esp_first, esp_last)
    new[free[1]] = mk("MSR", MSR_TYPE, msr_first, msr_last)
    new[free[2]] = mk("Windows", WIN_TYPE, win_first, win_last)

    changes = []
    for i, (a, b) in enumerate(zip(ents, new)):
        if a is None and b is None:
            continue
        if a is None:
            changes.append((i, "", None, b))
        elif b is None:
            changes.append((i, a["name"], a, None))
        elif (a["first"], a["last"]) != (b["first"], b["last"]):
            changes.append((i, a["name"], a, b))
    moved = [c for c in changes if c[2] is not None and c[3] is not None]
    if len(moved) != 1 or moved[0][1] != "userdata":
        raise ValueError("the plan moves %d existing partitions (%s); it must move only "
                         "`userdata`" % (len(moved), ", ".join(c[1] for c in moved)))
    return new, changes, (ud_new, esp, msr, win)


def build(sector, alt_lba, usable_first, usable_last, disk_guid, new_entries, old_hdr):
    """Serialise both GPTs for `new_entries`, CRCs stamped.

    `AlternateLBA` is **taken from the device's own header** and not recomputed as
    `LastUsableLBA + 1`. On this device those differ: the table says
    LastUsableLBA = 30944250 and AlternateLBA = 30944255, five sectors of the LUN
    lying past the last usable one. Recomputing would move the secondary GPT
    inwards and leave the real one stale, which is exactly the inconsistency this
    tool exists to prevent.
    """
    num, esz = old_hdr["num"], old_hdr["esz"]
    ent_len = num * esz
    arr = bytearray(ent_len)
    for i, e in enumerate(new_entries):
        if e is None:
            continue
        o = i * esz
        arr[o:o + 16] = e["type"]
        arr[o + 16:o + 32] = e["guid"]
        struct.pack_into("<QQQ", arr, o + 32, e["first"], e["last"], e["attrs"])
        nm = e["name"].encode("utf-16-le")[:72]
        arr[o + 56:o + 56 + len(nm)] = nm
    ent_crc = crc32(bytes(arr))
    ent_sectors = (ent_len + sector - 1) // sector
    sec_ent_lba = alt_lba - ent_sectors
    hdr_size = old_hdr["hdr_size"]

    def header(my_lba, alt, ent_lba):
        h = bytearray(hdr_size)
        h[0:8] = GPT_SIG
        struct.pack_into("<II", h, 8, 0x00010000, hdr_size)
        struct.pack_into("<I", h, 16, 0)
        struct.pack_into("<QQQQ", h, 24, my_lba, alt, usable_first, usable_last)
        h[56:72] = disk_guid
        struct.pack_into("<QIII", h, 72, ent_lba, num, esz, ent_crc)
        struct.pack_into("<I", h, 16, crc32(bytes(h)))
        return bytes(h)

    return (header(1, alt_lba, 2), bytes(arr), header(alt_lba, 1, sec_ent_lba))


def reparse(primary, entries, secondary, sector):
    """Read the rewritten table back with code that does not trust the writer.

    Independent of `build`: every published quantity is re-derived from the bytes
    and compared, so a writer bug that happens to be self-consistent is still
    caught. Returns `(problems, entries)`.
    """
    problems = []
    ph, sh = parse_header(primary), parse_header(secondary)
    if ph["hdr_crc"] == 0 or sh["hdr_crc"] == 0:
        problems.append("a header CRC is zero, which no valid table has")
    for who, hdr, h in (("primary", primary, ph), ("secondary", secondary, sh)):
        probe = bytearray(hdr[:h["hdr_size"]])
        struct.pack_into("<I", probe, 16, 0)
        if crc32(bytes(probe)) != h["hdr_crc"]:
            problems.append("%s header CRC does not verify" % who)
    if crc32(entries) != ph["ent_crc"]:
        problems.append("the entry array CRC does not verify against the primary header")
    if ph["ent_crc"] != sh["ent_crc"]:
        problems.append("the two headers disagree about the entry array CRC")
    if ph["my_lba"] != 1 or ph["alt_lba"] != sh["my_lba"] or sh["alt_lba"] != 1:
        problems.append("MyLBA/AlternateLBA are not each other's mirror")
    if ph["usable_first"] != sh["usable_first"] or ph["usable_last"] != sh["usable_last"]:
        problems.append("the two headers disagree about the usable range")
    if ph["disk_guid"] != sh["disk_guid"]:
        problems.append("the two headers carry different disk GUIDs")
    ents = load_entries(entries, ph["num"], ph["esz"])
    for i, e in enumerate(ents):
        if e is None:
            continue
        if e["first"] > e["last"]:
            problems.append("entry %d has first > last" % i)
        if e["first"] < ph["usable_first"] or e["last"] > ph["usable_last"]:
            problems.append("entry %d (%s) lies outside the usable range" % (i, e["name"]))
    live = sorted((e["first"], e["last"], e["name"]) for e in ents if e)
    for (f1, l1, n1), (f2, l2, n2) in zip(live, live[1:]):
        if f2 <= l1:
            problems.append("%s and %s overlap" % (n1, n2))
    return problems, ents


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default=os.path.expanduser("~/backup/gauguin/images"))
    ap.add_argument("--gpt", default=None)
    ap.add_argument("--sector", type=int, default=4096)
    ap.add_argument("--esp-mib", type=int, default=512)
    ap.add_argument("--msr-mib", type=int, default=16)
    ap.add_argument("--win-gib", type=int, default=64)
    ap.add_argument("--keep-userdata-gib", type=int, default=None)
    ap.add_argument("--plan", action="store_true",
                    help="print the plan and write nothing (the default)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    gpt = a.gpt or os.path.join(a.images, "GPT-sda.bin")
    hdr, blob = read_primary(gpt, a.sector)
    h = parse_header(hdr)
    ents = load_entries(blob, h["num"], h["esz"])
    used = sum(1 for e in ents if e)
    print("== %s" % gpt)
    print("   sector=%d  disk=%s  entries@%d n=%d sz=%d  usable %d..%d  (%d in use)"
          % (a.sector, guid_str(h["disk_guid"]), h["ent_lba"], h["num"], h["esz"],
             h["usable_first"], h["usable_last"], used))
    print("   secondary GPT is at LBA %d, per this header" % h["alt_lba"])

    tail, tail_size, kind = find_tail(a.images, a.sector, h["alt_lba"], h["num"], h["esz"])
    if tail is None:
        ent_sectors = (h["num"] * h["esz"] + a.sector - 1) // a.sector
        print()
        print("!! STOP - the secondary GPT is not in this directory.")
        print("   A shrink rewrites both copies, and the secondary is the one a failed")
        print("   edit leaves inconsistent. Given only the head there is no way to write")
        print("   the tail, so this tool will not plan or apply. Read it off the phone:")
        print()
        print("     sectors  %d .. %d   (%d bytes at %d-byte sectors)"
              % (h["alt_lba"] - ent_sectors, h["alt_lba"], (ent_sectors + 1) * a.sector, a.sector))
        print("     i.e. the last %d bytes of sda" % ((ent_sectors + 1) * a.sector))
        print()
        print("   docs/00 P4 step 3 asks for exactly this. The recorded dump is %d bytes"
              % os.path.getsize(gpt))
        print("   and stops at byte %d of LBA %d; it holds the primary only."
              % (os.path.getsize(gpt) % a.sector, os.path.getsize(gpt) // a.sector))
        return 2

    th, tblob = read_tail(tail, a.sector, h["alt_lba"], h["num"], h["esz"])
    if tblob != blob:
        print("!! the two entry arrays differ; refusing to edit a table that is already"
              " inconsistent")
        return 3
    print("   secondary %s (%d bytes, kind=%s), both arrays agree"
          % (tail, tail_size, kind))

    new, changes, sizes = plan_layout(ents, a.sector, h["usable_last"],
                                      a.esp_mib, a.msr_mib, a.win_gib,
                                      a.keep_userdata_gib)
    ud, esp, msr, win = sizes
    print()
    print("== plan")
    for i, e in enumerate(ents):
        if e is None:
            continue
        mark = ""
        if any(c[0] == i for c in changes):
            mark = "  <- changed"
        print("   %-2d %-12s %12d .. %-12d %10d B%s" % (i, e["name"], e["first"], e["last"],
                                                         (e["last"] - e["first"] + 1) * a.sector,
                                                         mark))
    print()
    for i, name, a_, b_ in changes:
        if a_ is None:
            print("   + %-2d %-12s %12d .. %-12d %10d B" % (i, b_["name"], b_["first"],
                                                             b_["last"], (b_["last"] - b_["first"] + 1) * a.sector))
        else:
            print("   ~ %-2d %-12s %12d .. %-12d  ->  %12d .. %-12d" % (i, name, a_["first"],
                  a_["last"], b_["first"], b_["last"]))
    print()
    print("   userdata  %6.2f GiB after the shrink (was %6.2f GiB)"
          % (ud * a.sector / GIB, (ents[[i for i, e in enumerate(ents)
                                         if e and e["name"] == "userdata"][0]]["last"]
                                   - ents[[i for i, e in enumerate(ents)
                                           if e and e["name"] == "userdata"][0]]["first"] + 1)
             * a.sector / GIB))
    print("   ESP       %6.2f MiB" % (esp * a.sector / MIB))
    print("   MSR       %6.2f MiB" % (msr * a.sector / MIB))
    print("   Windows   %6.2f GiB" % (win * a.sector / GIB))

    pri, arr, sec = build(a.sector, h["alt_lba"], h["usable_first"], h["usable_last"],
                          h["disk_guid"], new, h)
    problems, _ = reparse(pri, arr, sec, a.sector)
    print()
    if problems:
        print("!! the rewritten table does not verify:")
        for p in problems:
            print("   - %s" % p)
        return 4
    print("== verify  the rewritten table re-parses clean: both header CRCs, the shared")
    print("           entry-array CRC, the mirror addresses, and every entry inside")
    print("           FirstUsableLBA..LastUsableLBA. No partition other than `userdata`")
    print("           changed LBA.")

    if not a.apply:
        print()
        print("   --plan only. Nothing was written. Add --apply --out DIR to write it.")
        return 0

    if not a.out:
        print("!! --apply needs --out DIR; nothing written")
        return 5
    os.makedirs(a.out, exist_ok=True)
    ent_sectors = (len(arr) + a.sector - 1) // a.sector
    # The head: the original LBA 0 with the protective MBR, then the new header and
    # array. LBA 0 is copied rather than regenerated - the protective MBR has to
    # keep saying the same thing, and a regenerated one is a new chance to be wrong.
    with open(gpt, "rb") as f:
        mbr = f.read(a.sector)
    with open(os.path.join(a.out, "GPT-sda-head.bin"), "wb") as f:
        f.write(mbr)
        f.write(pri)
        f.write(b"\x00" * (a.sector - len(pri)))
        f.write(arr)
        f.write(b"\x00" * (ent_sectors * a.sector - len(arr)))
    with open(os.path.join(a.out, "GPT-sda-tail.bin"), "wb") as f:
        f.write(arr)
        f.write(b"\x00" * (ent_sectors * a.sector - len(arr)))
        f.write(sec)
        f.write(b"\x00" * (a.sector - len(sec)))
    with open(os.path.join(a.out, "GPT-sda-plan.json"), "w") as f:
        json.dump(dict(sector=a.sector, alt_lba=h["alt_lba"], usable_last=h["usable_last"],
                       userdata_sectors=ud, esp_sectors=esp, msr_sectors=msr,
                       windows_sectors=win,
                       changes=[dict(index=i, name=n,
                                     old=[a_["first"], a_["last"]] if a_ else None,
                                     new=[b_["first"], b_["last"]] if b_ else None)
                                for i, n, a_, b_ in changes]), f, indent=2)
    print()
    print("== wrote")
    for n in ("GPT-sda-head.bin", "GPT-sda-tail.bin", "GPT-sda-plan.json"):
        print("   %s  %d bytes" % (os.path.join(a.out, n), os.path.getsize(os.path.join(a.out, n))))
    print()
    print("   To install: write the head to LBA 0 and the tail to LBA %d..%d. Nothing"
          % (h["alt_lba"] - ent_sectors, h["alt_lba"]))
    print("   here does that, and nothing here resizes the filesystem - the GPT edit and")
    print("   the `userdata` resize are two steps, and an interruption between them is")
    print("   what makes this irreversible.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
