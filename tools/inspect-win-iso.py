#!/usr/bin/env python3
"""Read a Windows ARM64 install ISO and say what is on it, without booting it.

The P3 gate is "a Windows 11 ARM64 installer boots off a USB stick and sees the
internal UFS", and the ISO is the thing that would have to boot. Booting it under
QEMU is the direct test and `tools/qemu-boot-win11-iso.sh` runs that test -- but
on this host a QEMU run of an ARM64 guest is software emulation on an x86_64 CPU,
because KVM is same-architecture only and `qemu-system-aarch64 -accel kvm` answers
`invalid accelerator kvm` here. A TCG boot of Windows Setup takes hours, so when
it fails this reader cannot tell a defective ISO from a slow one.

This is the cheap question asked first: is the ISO even shaped like bootable ARM64
media. It reads the El Torito boot catalog, follows the catalog's own load address
to the EFI System Partition, walks that FAT image, reads the PE headers of the
bootloaders it finds, and reads the WIM signatures out of the ISO 9660 tree. A
`bootaa64.efi` that is not an AArch64 PE, or a catalog entry whose load address
holds no FAT, or a `install.wim` whose signature is not `MSWIM` is a media defect
that under QEMU would look exactly like a boot that has not finished yet.

Nothing here is inferred from a filename alone: the machine type comes out of the
PE optional header, and the WIM check is the file's own eight-byte signature.

    python3 tools/inspect-win-iso.py work/win11/build/Win11_25H2.iso
"""
import argparse
import os
import struct
import sys

SECTOR = 2048

# `platform id` in an El Torito section header, and the `system type` byte in an
# entry. The two are separate fields that happen to share a numbering.
PLATFORM = {0x00: "x86 BIOS", 0x01: "PowerPC", 0x02: "Mac", 0xEF: "EFI"}
MEDIA = {0: "no emulation", 1: "1.2M floppy", 2: "1.44M floppy",
         3: "2.88M floppy", 4: "hard disk", 5: "CD-ROM"}

# `IMAGE_FILE_MACHINE_*`. A bootloader for the wrong architecture is the defect
# this reader most needs to be able to name, so the table carries the wrong ones
# rather than only the right one.
MACHINE = {0xAA64: "AArch64", 0x8664: "x86-64", 0x014C: "i386",
           0x01C0: "ARM", 0x01C4: "ARMv7 Thumb-2", 0x5032: "RISC-V 32",
           0x5064: "RISC-V 64"}

EFI_PATHS = ("EFI/BOOT/BOOTAA64.EFI",
             "EFI/MICROSOFT/BOOT/BOOTMGFW.EFI",
             "EFI/MICROSOFT/BOOT/BOOTAA64.EFI")
WIMS = ("SOURCES/BOOT.WIM", "SOURCES/INSTALL.WIM", "SOURCES/INSTALL.ESD")


class Fat:
    """A reader for the FAT12/16/32 image in an EFI System Partition.

    The whole image is held in memory, which is what makes this simple: an ESP
    on install media is a few megabytes, and every offset below is then relative
    to one buffer with no file seek to get wrong.
    """

    def __init__(self, data):
        self.d = data
        if len(data) < 512 or data[510:512] != b"\x55\xAA":
            raise ValueError("no FAT boot sector signature")
        self.bps, self.spc = struct.unpack_from("<H", data, 11)[0], data[13]
        self.rsvd, self.nfats = struct.unpack_from("<H", data, 14)[0], data[16]
        self.root_ents = struct.unpack_from("<H", data, 17)[0]
        spf16, = struct.unpack_from("<H", data, 22)
        spf32, = struct.unpack_from("<I", data, 36)
        self.spf = spf16 or spf32
        self.fat32 = spf16 == 0
        self.root_clus, = struct.unpack_from("<I", data, 44)
        if not self.bps or not self.spf or self.bps & (self.bps - 1):
            raise ValueError("implausible BPB: %d bytes/sector, %d sectors/FAT"
                             % (self.bps, self.spf))
        self.fat = self.rsvd * self.bps
        self.data0 = (self.rsvd + self.spf * self.nfats
                      + (self.root_ents * 32 + self.bps - 1) // self.bps) * self.bps

    def _next(self, c):
        step = 4 if self.fat32 else 2
        off = self.fat + c * step
        if off + step > len(self.d):
            return 0x0FFFFFFF
        return struct.unpack_from("<I" if self.fat32 else "<H", self.d, off)[0]

    def chain(self, c):
        out, seen = [], set()
        while 2 <= c < (0x0FFFFFF8 if self.fat32 else 0xFFF8) and c not in seen:
            seen.add(c)
            out.append(c)
            c = self._next(c)
        return out

    def cluster(self, c):
        base = self.data0 + (c - 2) * self.spc * self.bps
        return self.d[base:base + self.spc * self.bps]

    def root(self):
        if self.root_ents:
            off = self.data0 - (self.root_ents * 32 + self.bps - 1) // self.bps * self.bps
            return self.d[off:off + self.root_ents * 32]
        return b"".join(self.cluster(c) for c in self.chain(self.root_clus))

    def walk(self, buf=None, prefix="", depth=0):
        """{upper-case path: (offset in the image, length)} for every file."""
        if depth > 8:
            return {}
        buf = self.root() if buf is None else buf
        out = {}
        for o in range(0, len(buf) - 31, 32):
            e = buf[o:o + 32]
            if e[0] == 0x00:
                break
            if e[0] == 0xE5 or e[11] & 0x0F == 0x0F:
                continue
            name = (e[0:8].decode("latin-1").rstrip(" ")
                    + "." + e[8:11].decode("latin-1").rstrip(" ")).rstrip(".")
            clus, = struct.unpack_from("<H", e, 26)
            if e[11] & 0x10:
                if e[0] == 0x2E:
                    continue
                sub = b"".join(self.cluster(c) for c in self.chain(clus))
                out.update(self.walk(sub, prefix + name.upper() + "/", depth + 1))
            else:
                base = self.data0 + (clus - 2) * self.spc * self.bps
                out[prefix + name.upper()] = (base, struct.unpack_from("<I", e, 28)[0])
        return out


def iso_records(f, extent, length):
    """The directory records at an extent, as (name, extent, length, is_dir).

    The two self-referential records do not spell themselves: ECMA-119 gives `.`
    the identifier `0x00` and `..` the identifier `0x01`, each one byte long and
    therefore not a name at all. Left untranslated they decode to those two
    control bytes, sort unequal to the literal `"."` / `".."` a caller filters
    on, and print as two blanks -- which is how this read a root that holds only
    itself as a root that holds two nameless entries.
    """
    f.seek(extent * SECTOR)
    buf = f.read(length)
    out, o = [], 0
    while o < len(buf):
        rec = buf[o]
        if rec == 0:
            o = (o // SECTOR + 1) * SECTOR
            continue
        nl = buf[o + 32]
        raw = buf[o + 33:o + 33 + nl]
        name = {b"\x00": ".", b"\x01": ".."}.get(
            raw, raw.decode("latin-1").split(";")[0])
        out.append((name,
                    struct.unpack_from("<I", buf, o + 2)[0],
                    struct.unpack_from("<I", buf, o + 10)[0],
                    bool(buf[o + 25] & 0x02)))
        o += rec
    return out


def iso_lookup(f, path):
    """(extent, length) for an ISO 9660 file, or None. `;1` is stripped."""
    f.seek(16 * SECTOR)
    root = f.read(SECTOR)[156:190]
    ext, ln = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
    for want in path.split("/"):
        hit = next((r for r in iso_records(f, ext, ln)
                    if r[0].upper() == want.upper()), None)
        if not hit:
            return None
        ext, ln = hit[1], hit[2]
    return ext, ln


def eltorito(f):
    """(catalog LBA, [(slot, kind, media, sector count, load RBA)]) or None.

    Entries are collected by the same rule the firmware uses, which is not the
    rule the El Torito specification invites a reader to use. EDK2's
    `MdeModulePkg/Universal/Disk/PartitionDxe/ElTorito.c` walks the catalog as a
    flat array of 32-byte slots starting at slot 1 and takes **every** slot whose
    boot indicator is `0x88` and whose load address is non-zero -- it never looks
    at the platform id at all, and it does not care whether a slot is a default
    entry, an entry under a section header, or a bare entry with no header. So the
    question "will this media boot" is answered by that scan and not by the
    specification's structure, and this reads it the same way.

    Three earlier readings of this catalog were wrong and each is worth its
    sentence, because all three misread the media rather than the code:

    * Reading only slots under a `0x01` section header found zero entries, because
      this catalog's slot 1 is a boot entry and its section header sits at slot 2
      with id `0x91`.
    * Reading only the default entry found one entry and missed the real one. The
      default entry here is 8 sectors of x86 code; the bootloader is the entry
      under the section header at slot 3, 3360 sectors of FAT12 at LBA 1415.
    * Trusting the platform id would have rejected both: the validation entry says
      `0x00` (x86) and so does the section header, on media whose bootloader is
      AArch64. genisoimage's `-b` writes a BIOS catalog; `-eltorito-platform efi`
      is what would mark it, and the converter's ARM64 branch does not pass it.
      The firmware does not read the field, which is the only reason this is a
      curiosity rather than the reason the media fails -- and it is why the boot
      image is identified below by reading it.
    """
    f.seek(17 * SECTOR)
    cat = None
    while True:
        d = f.read(SECTOR)
        if not d or d[0:1] == b"\xff":
            return None
        if d[0] == 0 and d[1:6] == b"CD001":
            cat = struct.unpack_from("<I", d, 71)[0]
            break
    f.seek(cat * SECTOR)
    head = f.read(SECTOR)
    if head[0] != 0x01:
        return None
    out = []
    for slot in range(1, SECTOR // 32):
        e = head[slot * 32:(slot + 1) * 32]
        if len(e) < 32:
            break
        if e[0] & 0xFE == 0x90:
            # A section header: indicator 0x90, or 0x91 meaning a further header
            # follows. Its second byte is a platform id, freed from the boot-entry
            # meaning of that byte, and its word at offset 2 is the entry count.
            out.append((slot, "header", e[1], struct.unpack_from("<H", e, 2)[0], 0))
            continue
        if e[0] != 0x88:
            # Not bootable, or an empty slot. The scan continues rather than stops,
            # because a 0x00 indicator means both and the terminator is not
            # distinguishable from a non-bootable entry; the sector's end is the
            # only bound the firmware uses either.
            continue
        lba = struct.unpack_from("<I", e, 8)[0]
        if lba == 0:
            continue
        out.append((slot, "entry", e[1], struct.unpack_from("<H", e, 6)[0], lba))
    return cat, out


def pe(f, off):
    """(machine, subsystem) for the PE at `off`, or None."""
    f.seek(off)
    if f.read(2) != b"MZ":
        return None
    f.seek(off + 0x3C)
    lfanew, = struct.unpack("<I", f.read(4))
    if not 0 < lfanew < 0x1000:
        return None
    f.seek(off + lfanew)
    if f.read(4) != b"PE\0\0":
        return None
    mach, = struct.unpack("<H", f.read(2))
    f.seek(off + lfanew + 24 + 68)
    subsys, = struct.unpack("<H", f.read(2))
    return mach, subsys


def vrs(f):
    """The volume recognition sequence: the identifiers at sector 16 upward.

    This is where a UDF bridge announces itself. `BEA01` / `NSR02` / `TEA01` is
    ECMA-167's volume recognition sequence and its presence is what says the
    volume's real filesystem is UDF rather than ISO 9660 -- which matters here
    because the install media this reads is exactly that, and because whether a
    firmware can read the media turns on whether it has a UDF driver.
    """
    out = []
    for lba in range(16, 32):
        f.seek(lba * SECTOR)
        d = f.read(6)
        if len(d) < 6 or d[1:6] not in (b"CD001", b"BEA01", b"NSR02", b"NSR03",
                                        b"TEA01", b"BOOT2"):
            break
        out.append((lba, d[1:6].decode()))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("iso")
    args = ap.parse_args()
    if not os.path.exists(args.iso):
        raise SystemExit("no such file: %s" % args.iso)

    size = os.path.getsize(args.iso)
    bad = 0
    print("file      %s" % args.iso)
    print("size      %d bytes (%.2f GiB)" % (size, size / 2 ** 30))

    with open(args.iso, "rb") as f:
        f.seek(16 * SECTOR)
        pvd = f.read(SECTOR)
        if pvd[1:6] != b"CD001":
            raise SystemExit("not an ISO 9660 volume: %r at sector 16" % pvd[1:6])
        print("volume    %d blocks x %d B = %.2f GiB"
              % (struct.unpack_from("<I", pvd, 80)[0],
                 struct.unpack_from("<H", pvd, 128)[0],
                 struct.unpack_from("<I", pvd, 80)[0]
                 * struct.unpack_from("<H", pvd, 128)[0] / 2 ** 30))

        ids = vrs(f)
        udf = [i for _, i in ids if i.startswith("NSR")]
        print("vrs       %s" % " ".join(i for _, i in ids))
        if udf:
            print("          ^ UDF: the filesystem on this volume is ECMA-167, and")
            print("            the ISO 9660 tree below is a bridge, not the content")

        el = eltorito(f)
        esp_lbas = []
        if el is None:
            print("eltorito  NO BOOT RECORD -- nothing can boot this volume")
            bad += 1
        else:
            cat, slots = el
            boot = [s for s in slots if s[1] == "entry"]
            print("eltorito  catalog at LBA %d: %d slot%s used, %d bootable entr%s"
                  % (cat, len(slots), "" if len(slots) == 1 else "s",
                     len(boot), "y" if len(boot) == 1 else "ies"))
            for slot, kind, field, count, lba in slots:
                if kind == "header":
                    print("          slot %-2d section header, platform id %s, "
                          "declares %d entr%s   (a field the firmware never reads)"
                          % (slot, PLATFORM.get(field, "0x%02X" % field), count,
                             "y" if count == 1 else "ies"))
                    continue
                print("          slot %-2d media %-13s %6d sector%s  load RBA %-6d "
                      "(byte %d)%s"
                      % (slot, MEDIA.get(field, "0x%02X" % field), count,
                         "" if count == 1 else "s", lba, lba * SECTOR,
                         "" if count >= 2 else "   <-- <2: whole CD from here"))
                esp_lbas.append(lba)
            if not boot:
                print("          ^ no bootable entry: this volume cannot boot")
                bad += 1

        # The boot image is identified by reading it, never by a name or a header
        # field. A default entry carries no `platform id` at all, so for media in
        # that shape this is the only thing that settles what the entry is.
        real = []
        for lba in esp_lbas:
            f.seek(lba * SECTOR)
            blob = f.read(24 * 2 ** 20)
            try:
                esp = Fat(blob)
            except Exception as exc:
                print("boot image LBA %d: not a FAT image (%s)" % (lba, exc))
                continue
            files = esp.walk()
            efi = [p for p in files if p.endswith(".EFI")]
            print("boot image LBA %d: FAT%d, %d files, %d .EFI  %s"
                  % (lba, 32 if esp.fat32 else 16, len(files), len(efi),
                     ", ".join(sorted(efi)[:6]) or "(none)"))
            real.append((lba, esp, files))

        for lba, esp, files in real:
            for p in EFI_PATHS:
                if p not in files:
                    continue
                off, ln = files[p]
                got = pe(f, lba * SECTOR + off)
                if not got:
                    print("          %-32s %8d B  NOT a PE image" % (p, ln))
                    bad += 1
                else:
                    mach, subsys = got
                    ok = mach == 0xAA64
                    print("          %-32s %8d B  %-12s subsystem %d  %s"
                          % (p, ln, MACHINE.get(mach, hex(mach)), subsys,
                             "AArch64" if ok else "WRONG ARCHITECTURE"))
                    bad += 0 if ok else 1
        if real and not any(p in files for _, _, files in real for p in EFI_PATHS):
            print("          no EFI bootloader in any boot image: nothing to chain to")
            bad += 1

        # What the ISO 9660 tree holds. On Windows ARM64 install media this is
        # empty on purpose and the emptiness is the finding, not a defect in the
        # reading: the converter builds it with `--hide "*"`, which hides every
        # name from ISO 9660 while leaving the data in place for UDF.
        f.seek(16 * SECTOR)
        root = f.read(SECTOR)[156:190]
        ext, ln = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
        top = iso_records(f, ext, ln)
        names = [n for n, _, _, _ in top if n not in (".", "..")]
        print("iso9660   root holds %d entr%s: %s"
              % (len(names), "y" if len(names) == 1 else "ies",
                 ", ".join(names) or "(nothing)"))
        if not names and udf:
            print("          ^ empty by construction, not by damage: the files are")
            print("            reachable through UDF only. Read them with")
            print("            `mount -o loop,ro -t udf`, which is an independent")
            print("            reader from this one and is what the check below uses")
            print("            a filesystem driver for.")

        for w in WIMS:
            hit = iso_lookup(f, w)
            if hit:
                ext, ln = hit
                f.seek(ext * SECTOR)
                sig = f.read(8)
                ok = sig == b"MSWIM\0\0\0"
                print("wim       %-22s %9.1f MiB at LBA %-8d %s"
                      % (w, ln / 2 ** 20, ext, "MSWIM" if ok else "sig %r" % sig))
                bad += 0 if ok else 1
            else:
                print("wim       %-22s not in the ISO 9660 tree%s"
                      % (w, " (expected: hidden)" if udf else ""))

    if not udf:
        print()
        print("RESULT: %s" % ("media is shaped like bootable ARM64 Windows install "
                              "media" if bad == 0
                              else "%d problem(s) above" % bad))
    else:
        print()
        print("RESULT: %d problem(s) in the ISO 9660 and El Torito structures; the"
              % bad)
        print("        files themselves are in UDF and are not read here")
    return 1 if bad else 0



if __name__ == "__main__":
    sys.exit(main())
