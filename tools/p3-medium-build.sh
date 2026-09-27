#!/usr/bin/env bash
#
# Assemble the P3 boot medium: the USB stick the firmware's BDS hands off to.
#
# Why this exists, and why it is a USB stick rather than a partition. `boot`, the
# one partition the standing relaxation allows writing, is **128 MiB**
# (`docs/02-partitions.md`, `sde` offset 667,574,272) and it holds the *firmware*
# - the payload `tools/*` builds and `fastboot flash boot` writes - not a
# Windows image. The smallest Microsoft-signed Windows image obtainable is the
# ARM64 WinRE at 426.3 MiB LZX, and the ESP that boots it is another 33 MiB, so
# no medium fits beside the firmware in 128 MiB and none was ever going to. The
# medium is external, which is also why the UEFI's USB host stack is P3 work and
# not a P5 nicety: on this design the stick is how Windows arrives.
#
# What it is made of, all of it Microsoft-signed. The ARM64 25H2 edition ESD
# (`professional_en-us.esd`, Step 4.153) holds three images and the medium is
# two of them plus the third when P4 needs it:
#
#   image 1  Windows Setup Media      the ESP tree: /efi/, /boot/, /bootmgr.efi
#   image 2  WinRE (arm64)            becomes \sources\boot.wim
#   image 3  Windows 11 Pro (ARM64)   P4's install.wim, not used here
#
# Image 1 carries no `/sources/boot.wim` among its 934 files under `/sources/`,
# which is why image 2 is not optional - the BCD image 1 ships names
# `\sources\boot.wim` and `\boot\boot.sdi` in its own strings (Step 4.154), and
# image 1 supplies only the second. The pairing is the contract, not a choice.
#
# The one name that matters and is easy to get wrong: the removable-media slot
# on ARM64 is `\EFI\BOOT\BOOTAA64.EFI`. There is no `bootarm64.efi` or
# `bootx64.efi` anywhere in the three images - `bootarm64` reads as the obvious
# analogue and firmware would find nothing on a stick written with it - and
# image 1's `bootaa64.efi` is byte-identical to image 2's `bootmgfw.efi`
# (sha256 6a5aa7f0bcd53267ae551ebe0b667b4a60eb02535b52b53480173f0c2eb8c332), so
# the fallback name is the boot manager in that slot rather than a loader of its
# own. Either file will do; this script uses image 1's, the one Microsoft put
# there.
#
# Nothing is modified. `winpeshl.ini` is *not* overridden: image 2's own 53-byte
# copy launches `X:\sources\recovery\recenv.exe`, so the stock image boots the
# Recovery Environment, and for the P3 gate that is the better target - a GUI on
# the panel is a stronger visible signal than a prompt, and Recovery's own
# command prompt is where a UFS check would be typed. A prompt-first variant is
# a `winpeshl.ini` update away and is deliberately not built here.
#
# Measured 2026-09-27 against the arm64 25H2 set. The two `apply` calls give
# 274,582,934 B for image 1 and 1,565,170,844 B for image 2 (hard links
# materialised once, so well under image 2's 2,765,776,494 B of file data), and
# `wimlib-imagex export ... 2 --compress=LZX` gives a 446,983,676 B boot.wim
# that verifies clean. The assembled medium is 51 files and 481,626,167 B
# (459.3 MiB); a 512 MB stick is too small for it once FAT overhead is counted
# and a 1 GB one is the smallest comfortable answer.
#
# The base image is split across the download set, so `--ref` to the other
# ESD/WIM files is required and is not optional: without it wimlib fails the
# pattern with "a file resource needed to complete the operation was missing".
# Refs are built from `*.esd`/`*.wim` only - a glob that also matches the
# `.cab` files in the set dies with "Invalid magic characters in header", which
# reads like a corrupt download and is not.
#
# Usage:  tools/p3-medium-build.sh <setdir> <outdir>
#         tools/p3-medium-build.sh ~/work/woa-ref/arm64-25h2-uup/files /tmp/p3-medium
#
#         The setdir must contain `professional_en-us.esd` and the rest of the
#         download set. The output tree is `<outdir>/usb-p3`, laid out as the
#         stick's FAT32 root; copy it to a FAT32-formatted stick and nothing
#         else needs doing.
#
# Requires `wimlib-imagex`. It is not packaged for Deepin; Step 4.153 unpacked
# it with `dpkg-deb -x` into `~/opt/wimlib` and it is run there with
# `LD_LIBRARY_PATH=$HOME/opt/wimlib/usr/lib/x86_64-linux-gnu`. Set `WIMLIB` and
# `WIMLIB_LIB` to override.
#
# Nothing is flashed and no device is touched: this writes a directory, not a
# partition, and the stick is written by the operator.
set -u

SRC=${1:-}
OUT=${2:-}
WIMLIB=${WIMLIB:-$HOME/opt/wimlib/usr/bin/wimlib-imagex}
WIMLIB_LIB=${WIMLIB_LIB:-$HOME/opt/wimlib/usr/lib/x86_64-linux-gnu}
ESD=${ESD:-professional_en-us.esd}

log() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

usage() {
    awk 'NR > 1 && /^set -u/ { exit } NR > 1' "$0" | sed 's/^# \{0,1\}//'
}

case "${1:-}" in
    -h|--help|"") usage; exit 0 ;;
esac
if [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
    usage
    exit 2
fi

[ -d "$SRC" ] || die "no such directory: $SRC"
[ -f "$SRC/$ESD" ] || die "no $ESD in $SRC"
[ -x "$WIMLIB" ] || die "wimlib-imagex not executable at $WIMLIB (set WIMLIB=)"

# Refs are the other WIM-format members of the set, never the .cab files: the
# set's AggregatedMetadata.cab has no WIM magic and wimlib rejects the whole
# ref list on it.
REFS=()
for f in "$SRC"/*.esd "$SRC"/*.wim; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in "$ESD") continue ;; esac
    REFS+=("--ref=$f")
done
[ "${#REFS[@]}" -gt 0 ] || die "no refs found beside $ESD; image 1 is unreadable without them"

export LD_LIBRARY_PATH="$WIMLIB_LIB"

MEDIA="$OUT/media1"
WINRE="$OUT/winre"
USB="$OUT/usb-p3"
BOOTWIM="$OUT/boot.wim"

mkdir -p "$OUT" || die "cannot create $OUT"
rm -rf "$MEDIA" "$WINRE" "$USB"

log "== image 1 -> $MEDIA  (the Setup Media tree: the ESP lives here)"
mkdir -p "$MEDIA"
"$WIMLIB" apply "$SRC/$ESD" 1 "$MEDIA" "${REFS[@]}" >/dev/null \
    || die "apply of image 1 failed"
[ -f "$MEDIA/efi/boot/bootaa64.efi" ] || die "image 1 has no /efi/boot/bootaa64.efi; is index 1 the Setup Media?"

log "== image 2 -> $BOOTWIM  (WinRE, the WIM the medium's BCD loads)"
"$WIMLIB" export "$SRC/$ESD" 2 "$BOOTWIM" --compress=LZX --boot "${REFS[@]}" >/dev/null \
    || die "export of image 2 failed"
"$WIMLIB" verify "$BOOTWIM" >/dev/null 2>&1 || die "the exported boot.wim does not verify"

# The medium. Uppercase because FAT32 stores it that way and the ESP convention
# is uppercase; the two paths the BCD names are `\boot\boot.sdi` and
# `\sources\boot.wim`, both case-insensitive on the stick and both present below.
log "== assembling $USB"
mkdir -p "$USB/EFI/BOOT" "$USB/EFI/MICROSOFT/BOOT" "$USB/BOOT" "$USB/SOURCES"

# The removable-media loader. Image 1's bootaa64.efi and image 2's bootmgfw.efi
# are the same file; image 1's is the one Microsoft ships in that slot.
cp "$MEDIA/efi/boot/bootaa64.efi"              "$USB/EFI/BOOT/BOOTAA64.EFI"
# The BCD, and everything its boot UI reads.
cp "$MEDIA/efi/microsoft/boot/bcd"             "$USB/EFI/MICROSOFT/BOOT/BCD"
cp "$MEDIA/efi/microsoft/boot/boot.stl"        "$USB/EFI/MICROSOFT/BOOT/"
cp "$MEDIA/efi/microsoft/boot/winsipolicy.p7b" "$USB/EFI/MICROSOFT/BOOT/"
cp -r "$MEDIA/efi/microsoft/boot/fonts"        "$USB/EFI/MICROSOFT/BOOT/"
cp -r "$MEDIA/efi/microsoft/boot/resources"    "$USB/EFI/MICROSOFT/BOOT/"
cp -r "$MEDIA/efi/microsoft/boot/cipolicies"   "$USB/EFI/MICROSOFT/BOOT/"
# The RAM-disk path the BCD's device element names, and the BIOS-side font set -
# kept although this medium is UEFI-only, because 13 MiB is cheaper than a boot
# that fails for a reason nobody will look for.
cp "$MEDIA/boot/boot.sdi"                      "$USB/BOOT/BOOT.SDI"
cp -r "$MEDIA/boot/fonts"                      "$USB/BOOT/"
# The image itself.
cp "$BOOTWIM"                                  "$USB/SOURCES/BOOT.WIM"

# What the BCD says it will load, checked against what is on the stick. These
# are the strings Step 4.154 read out of the BCD; a medium missing either one
# boots to an error the panel shows as a hex status, which is a worse afternoon
# than a failed check here.
for p in BOOT/BOOT.SDI SOURCES/BOOT.WIM EFI/BOOT/BOOTAA64.EFI EFI/MICROSOFT/BOOT/BCD; do
    [ -f "$USB/$p" ] || die "the BCD names this path and the medium lacks it: $p"
done

log "== manifest"
python3 - "$USB" <<'PY'
import hashlib, os, sys
root = sys.argv[1]
files, total = [], 0
for r, _, fs in os.walk(root):
    for f in fs:
        p = os.path.join(r, f)
        n = os.path.getsize(p)
        total += n
        files.append((os.path.relpath(p, root), n))
files.sort()
for rel, n in files:
    print(f"   {n:>12,}  {rel}")
print(f"   {total:>12,}  {len(files)} files, {total/2**20:.1f} MiB")
PY

cat <<EOF

Copy $USB to the FAT32 root of a USB stick. 1 GB is the smallest comfortable
size: the tree is 459 MiB, FAT32's cluster and directory overhead adds a little,
and a 512 MB stick is not worth the margin.

There is no boot code to install - UEFI reads \\EFI\\BOOT\\BOOTAA64.EFI from the
ESP's FAT32 filesystem and no MBR or boot sector is involved. On a GPT stick,
the partition holding this tree should carry the ESP type (EF00) for firmware
that filters on it; the loader file is what the UEFI specification falls back to
either way.

What the stick boots is Windows Recovery Environment on ARM64, unmodified, from
\\sources\\boot.wim. It carries storufs.inf binding \`ACPI\\QCOM24A5\` and
\`urssynopsys.inf\` binding \`ACPI\\PNP0CA1\`, so if this platform reaches BDS and
the stick, the OS that comes up is one that can see UFS by construction. If the
panel shows the recovery UI the P3 gate's first half is answered; if it shows a
Windows Boot Manager error the BCD ran and the failure is downstream of handoff;
if it shows nothing the failure is upstream and the medium is not implicated.
EOF
