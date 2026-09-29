#!/usr/bin/env bash
# Build a FAT32 USB stick image out of a Windows 11 ARM64 install tree.
#
# The P3 gate is "a Windows 11 ARM64 installer boots off a USB stick and sees the
# internal UFS". This builds the stick. It is not a convenience wrapper around
# `cp`: the filesystem choice is the whole point, and it is forced by what the
# phone's own firmware can read.
#
# Three measurements decide it, and each one rules out an alternative.
#
# 1. The firmware has `DiskIoDxe`, `PartitionDxe` and `Fat`, and no UDF driver.
#    `uefi/Platforms/Xiaomi/gauguinPkg/Include/DXE.inc:76-78` and
#    `APRIORI.inc:52-59` list those three, and `grep -rn -i 'udf|iso9660'` over
#    the whole package returns nothing. EDK2 ships **no ISO 9660 driver at all**
#    -- `MdeModulePkg/Universal/Disk/` holds DiskIoDxe, UdfDxe, PartitionDxe,
#    UnicodeCollation, RamDiskDxe and CdExpressPei, and nothing else -- so on any
#    EDK2 firmware the only reader for a UDF-bridge CD is `UdfDxe`.
#
# 2. The installer ISO the converter produces is UDF-bridge media whose ISO 9660
#    tree is empty by construction: the converter's ARM64 branch runs
#    `genisoimage ... --udf -iso-level 3 --hide "*"`, and `--hide "*"` removes
#    every directory record, which `tools/inspect-win-iso.py` reads back as
#    `iso9660 root holds 0 entries`. So on that media there is no second tree to
#    fall back to, and a firmware without `UdfDxe` sees a 6.88 MB El Torito boot
#    image, boots `\EFI\BOOT\BOOTAA64.EFI` off it, and then finds no BCD --
#    because the BCD is in the UDF tree it cannot read.
#
# 3. `install.wim` is 3,520,950,655 bytes, which is under FAT32's 4 GiB per-file
#    limit, so no `.swm` split is needed and Windows Setup is not asked to
#    reassemble anything. This is why FAT32 is available here at all: had the WIM
#    been larger, the same tree would have needed `wimlib-imagex split` and a
#    `install.swm` set, which is what Microsoft's own Media Creation Tool does.
#
# So FAT32 is not a preference, it is the one filesystem both ends already agree
# on, and the stick is the medium the gate names. MBR rather than GPT because it
# is the layout every UEFI firmware's removable-media path accepts, and because
# nothing here needs more than one partition.
#
#   tools/make-win-stick.sh /mnt/win11iso work/win11/stick/win11arm64-stick.img [6G]
set -eu

SRC="${1:?usage: make-win-stick.sh <install tree> <out.img> [size, default 6G]}"
IMG="${2:?usage: make-win-stick.sh <install tree> <out.img> [size, default 6G]}"
SIZE="${3:-6G}"

[ -d "$SRC" ] || { echo "no such tree: $SRC"; exit 1; }
[ -e "$SRC/efi/boot/bootaa64.efi" ] || {
  echo "$SRC is not a Windows ARM64 install tree (no efi/boot/bootaa64.efi)"; exit 1; }
[ -e "$SRC/sources/boot.wim" ] || {
  echo "$SRC has no sources/boot.wim: Setup would have nothing to boot"; exit 1; }

# The 4 GiB limit is checked before 4 GB is copied, not after mkfs.vfat fails.
big=$(find "$SRC" -type f -size +4G -printf '%s %p\n' 2>/dev/null | head -5 || true)
if [ -n "$big" ]; then
  echo "FAT32 cannot hold a file over 4 GiB. Split these first with"
  echo "  wimlib-imagex split <wim> <name>.swm 4095"
  echo "$big"
  exit 1
fi

mkdir -p "$(dirname "$IMG")"
rm -f "$IMG"
truncate -s "$SIZE" "$IMG"
parted -s "$IMG" mklabel msdos mkpart primary fat32 1MiB 100% set 1 boot on

# `-fP` so the kernel re-reads the partition table it just gained, which is what
# makes `${LOOP}p1` exist without a separate `partprobe` that would race it.
LOOP=$(losetup -fP --show "$IMG")
cleanup() {
  mountpoint -q /mnt/win-stick && umount /mnt/win-stick
  losetup -d "$LOOP" 2>/dev/null || true
}
trap cleanup EXIT

mkfs.vfat -F32 -n WIN11ARM64 "${LOOP}p1" >/dev/null
mkdir -p /mnt/win-stick
mount "${LOOP}p1" /mnt/win-stick

# A byte-for-byte copy of the tree, because it *is* the tree Microsoft's media
# carries: the same `\efi\microsoft\boot\bcd` the El Torito stub looks for, and
# the same `\sources\boot.wim` Setup loads. The mount is UDF and read-only, so
# the source modes are 0444 and are re-created by vfat from the umask; nothing
# here depends on a permission bit surviving.
cp -r "$SRC/." /mnt/win-stick/
sync

echo "=== what the stick holds ==="
find /mnt/win-stick -maxdepth 1 -mindepth 1 -printf '  %-16f\n' | sort
printf '  installer path   %s\n' "$(test -e /mnt/win-stick/efi/boot/bootaa64.efi && echo '/efi/boot/bootaa64.efi present' || echo MISSING)"
printf '  BCD              %s\n' "$(test -e /mnt/win-stick/efi/microsoft/boot/bcd && echo 'present' || echo MISSING)"
printf '  boot.wim         %s bytes\n' "$(stat -c %s /mnt/win-stick/sources/boot.wim)"
printf '  used             %s\n' "$(df -h /mnt/win-stick | awk 'NR==2{print $3" of "$2}')"

umount /mnt/win-stick
losetup -d "$LOOP"
trap - EXIT

# Checked after the fact with an independent reader (`fsck.vfat` is not this
# script's own code), because a stick that mounts here and is unreadable to the
# firmware on the other side is the failure this whole file exists to avoid. The
# partition is the point: on the whole image sector 0 is the MBR, and a filesystem
# checker handed an MBR reads the partition table's first entry as a BPB and
# reports nonsense -- `only 1 or 2 FATs are supported, not 251`, from the LBA
# field.
#
# How to hand it the partition and not the MBR is not a free choice here: this
# host's `fsck.fat 4.2-deepin1` has no `--offset` at all -- `fsck.vfat -n
# --offset=2048 <img>` prints its usage text and exits 2, so that form of the
# check reported nothing while looking like a check. A second loop device
# publishing `${LOOP}p1` is the form this checker does accept.
echo "=== fsck.vfat on the partition, not on the MBR ==="
CHK=$(losetup -fP --show "$IMG")
fsck.vfat -n "${CHK}p1" 2>&1 | tail -4
losetup -d "$CHK"
echo "=== image ==="
ls -la "$IMG"

# Handed back to whoever invoked this, not left owned by root. The image is what
# QEMU opens, and QEMU opens it read-write: a root-owned 0644 file answers
# `Could not open ... Permission denied` from QEMU's *device* line rather than
# from its drive line, which reads like a missing bus and is not one.
if [ -n "${SUDO_UID:-}" ]; then
  chown "$SUDO_UID:${SUDO_GID:-$SUDO_UID}" "$IMG" "$(dirname "$IMG")" 2>/dev/null || true
fi
ls -la "$IMG"
