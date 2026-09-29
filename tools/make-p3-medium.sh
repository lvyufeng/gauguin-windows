#!/usr/bin/env bash
#
# Assemble the P3 gate's install medium from an ARM64 Windows 11 ISO.
#
# P3's gate is "a Windows 11 ARM64 installer boots off a USB stick and sees the
# internal UFS". `tools/make-p3-stick.sh` set out to build that medium and built
# an x86_64 one: it merged `p3-medium-built/media1` (the setup engine) with
# `p3-medium-built/usb-p3` (a WinRE-only `BOOT.WIM`) and then split
# `$WOA/win11-25h2/install.wim` into `install.swm` - and that image, like the
# `.swm` set built from it, is **x86_64 for all eleven editions**. The script's
# docstring promised an ARM64 stick and it never once read an architecture
# string; its verification block checked only that files exist. A medium that
# cannot install Windows is not a test of the firmware, so this file replaces
# that step with one whose first act is to refuse an image whose architecture is
# not ARM64, and whose failure mode is loud rather than a tree that looks
# complete.
#
# It also drops the two-half merge entirely. The reason for the merge was that
# neither staged half was complete: `media1` had no install image, and `usb-p3`'s
# `BOOT.WIM` was Microsoft Windows RE, whose single image has no `Windows Setup`
# to run. `~/work/win11/build/26100.1_PROFESSIONAL_ARM64_EN-US.ISO` - the ARM64
# ISO this project's UUP converter already produced on 2026-09-29 - is a complete
# install medium and supersedes both halves:
#
#   * `sources/install.wim` 3,520,950,655 B, one image, Architecture ARM64,
#     Edition `Professional`, Build 26100, 82,652 files - and under FAT32's 4 GiB
#     per-file ceiling, so no `.swm` split is needed and Setup is not asked to
#     reassemble anything.
#   * `sources/boot.wim` 465,806,736 B, **two** images, both ARM64, boot index 2:
#     index 1 `Microsoft Windows PE`, index 2 `Microsoft Windows Setup`. The
#     second is the image `usb-p3` did not have, and it is the one Setup boots.
#   * `efi/boot/bootaa64.efi` Aarch64, `efi/microsoft/boot/bcd` present.
#   * `sources/boot.wim` image 2 carries the inbox `storufs.inf` /
#     `storufs.sys` in both `System32\drivers` and the DriverStore at
#     `storufs.inf_arm64_744761edc9e26f6c`, so `ACPI\QCOM24A5` - the id
#     `tools/acpi-hid-census.py --drivers ... --bind --asl` reports as the one
#     gauguin's `UFS0` node presents - has a driver on the medium before anything
#     is injected.
#
# What the ISO does *not* carry is the platform around the UFS controller: no
# PEP, no PMIC, no SPMI, no SCM, no GLINK, no ADSP. Those are the 112 CABs of the
# SC7280/Kodiak package, and they are injected the same way `make-p3-stick.sh`
# injected them - at `X:\Drivers`, loaded by a `startnet.cmd` that runs `drvload`
# on each INF before `wpeinit` - because WinPE has no offline DISM and this host
# is Linux. The packages are kept one directory per CAB and never flattened: a
# Windows driver package is a directory, and four of the 112 carry a filename at
# two different contents (the three `qcfirmware7280.cat` variants, `libcdsprpc.dll`
# and `libadsprpc.dll`), so flattening hands two of them the wrong catalog and
# Windows rejects them as unsigned.
#
# One further difference from `make-p3-stick.sh`, and it is a correctness one:
# the injection targets the WIM's **boot index**, not image 1. This ISO's
# `boot.wim` boot index is 2 - the `Microsoft Windows Setup` image - and
# `make-p3-stick.sh`'s `wimlib-imagex update "$WIM" 1` would have edited
# `Microsoft Windows PE` instead, the image nothing boots.
#
# `startnet.cmd` ends by launching `X:\setup.exe`. WinPE runs `startnet.cmd`
# only because `boot.wim` image 2 has no `winpeshl.ini` (measured: image 1 has
# one in `p3-medium-built/usb-p3`'s WIM, image 2 here does not); adding one means
# the default "launch Setup" is replaced, so the script has to do it. Setup then
# finds `install.wim` by scanning the removable media, which is how Microsoft's
# own media works.
#
# Nothing here touches the phone. It writes only under --out and --stage, and
# only reads the ISO and the CAB directory.
#
# Usage:
#   make-p3-medium.sh [--iso FILE] [--tree DIR] [--cabs DIR] [--out DIR]
#                     [--stage DIR] [--img FILE] [--size 6G] [--check]
#
#   --iso    the ARM64 ISO to build from (default: the project's build)
#   --tree   a pre-extracted ISO tree; skips the 4 GiB extraction
#   --img    also write a FAT32 stick image, via tools/make-win-stick.sh
#   --check  stop after the input and architecture checks

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
WOA=${WOA:-$HOME/work/woa-ref}
ISO=${ISO:-$REPO/work/win11/build/26100.1_PROFESSIONAL_ARM64_EN-US.ISO}
CABS=${CABS:-$WOA/qrd/7280_CLS/200.0.4.0}
OUT=${OUT:-$REPO/work/out/p3-medium-arm64}
STAGE=${DRIVER_CACHE:-$REPO/work/out/.p3-medium-drivers}
TREE=
IMG=
SIZE=6G
CHECK=0

while [ $# -gt 0 ]; do
    case "$1" in
        --iso)     ISO=$2; shift 2 ;;
        --tree)    TREE=$2; shift 2 ;;
        --cabs)    CABS=$2; shift 2 ;;
        --out)     OUT=$2; shift 2 ;;
        --stage)   STAGE=$2; shift 2 ;;
        --img)     IMG=$2; shift 2 ;;
        --size)    SIZE=$2; shift 2 ;;
        --check)   CHECK=1; shift ;;
        -h|--help) sed -n '2,90p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

die() { echo "error: $*" >&2; exit 1; }
say() { printf '\033[1m== %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
# The architecture assertion. `wiminfo` prints one `Architecture:` line per
# image; every image of every WIM that Setup will read has to say ARM64, and the
# count has to match the WIM's own image count so a WIM that reports nothing is
# a failure and not a pass. This is the check whose absence let an x86_64
# `install.wim` sit in a stick documented as ARM64.
# ---------------------------------------------------------------------------
arch_all_arm64() {
    local wim=$1 what=$2
    local n expect got
    expect=$(wiminfo "$wim" 2>/dev/null | sed -n 's/^Image Count: *//p')
    [ -n "$expect" ] || die "$what: $wim is not a readable WIM"
    got=$(wiminfo "$wim" 2>/dev/null | sed -n 's/^Architecture: *//p')
    n=$(printf '%s\n' "$got" | grep -c . || true)
    [ "$n" -eq "$expect" ] || die "$what: $wim reports $n architectures for $expect images"
    if [ "$(printf '%s\n' "$got" | sort -u)" != "ARM64" ]; then
        echo "  $what: $wim"
        printf '%s\n' "$got" | sed 's/^/     Architecture: /'
        die "$what is not ARM64 - this medium would install the wrong architecture"
    fi
    echo "  $what: $expect image(s), all ARM64"
}

# ---------------------------------------------------------------------------
say "checking inputs"
[ -n "$TREE" ] || [ -f "$ISO" ] || die "no $ISO - the ARM64 install ISO"
[ -d "$CABS" ] || die "no $CABS - the SC7280/Kodiak driver package"
[ "$CHECK" -eq 0 ] || [ -d "$TREE" ] || command -v 7z >/dev/null || die "7z not found (needed to extract the ISO)"
command -v wimlib-imagex >/dev/null || die "wimlib-imagex not found"
command -v cabextract >/dev/null || die "cabextract not found"
n_cabs=$(find "$CABS" -maxdepth 1 -name '*.cab' | wc -l)
[ "$n_cabs" -gt 0 ] || die "$CABS holds no .cab files"
echo "   cabs: $n_cabs in $CABS"

# ---------------------------------------------------------------------------
say "staging the ISO tree"
if [ -z "$TREE" ]; then
    TREE=$OUT/.iso-tree
    rm -rf "$TREE"; mkdir -p "$TREE"
    7z x -y -o"$TREE" "$ISO" >/dev/null 2>&1 || die "7z failed to extract $ISO"
fi
[ -d "$TREE/sources" ] || die "$TREE has no sources/ - not an install tree"
echo "   tree: $TREE ($(du -sh "$TREE" | cut -f1))"

# ---------------------------------------------------------------------------
say "checking the architecture this medium will install"
[ -f "$TREE/sources/install.wim" ] || die "no sources/install.wim - Setup would have nothing to install"
[ -f "$TREE/sources/boot.wim" ] || die "no sources/boot.wim - Setup would have nothing to boot"
[ -f "$TREE/efi/boot/bootaa64.efi" ] || die "no efi/boot/bootaa64.efi - this firmware boots removables by that name"
arch_all_arm64 "$TREE/sources/install.wim" "install.wim"
arch_all_arm64 "$TREE/sources/boot.wim"    "boot.wim"

# The boot index is the image WinPE runs. `make-p3-stick.sh` hardcoded 1; the
# ISO's is 2, and injecting into 1 would edit the image nothing boots.
BOOTIDX=$(wiminfo "$TREE/sources/boot.wim" 2>/dev/null | sed -n 's/^Boot Index: *//p')
[ -n "$BOOTIDX" ] || die "boot.wim reports no Boot Index"
bootname=$(wiminfo "$TREE/sources/boot.wim" 2>/dev/null | awk -v i="$BOOTIDX" '
    /^Index:/ { idx=$2 } idx==i && /^Name:/ { sub(/^Name: */,""); print; exit }')
echo "   boot index $BOOTIDX - \"$bootname\""

[ "$CHECK" -eq 1 ] && { say "--check: inputs and architecture are sound"; exit 0; }

# ---------------------------------------------------------------------------
say "extracting the driver packages"
# One directory per CAB and never flattened - see the note at the top.
mkdir -p "$STAGE"
mapfile -t CABNAMES < <(find "$CABS" -maxdepth 1 -name '*.cab' -printf '%f\n' | sort)
made=0 skipped=0
for b in "${CABNAMES[@]}"; do
    d=$STAGE/${b%.cab}
    if [ -d "$d" ] && [ -n "$(find "$d" -name '*.inf' -print -quit)" ]; then
        skipped=$((skipped + 1)); continue
    fi
    rm -rf "$d"; mkdir -p "$d"
    cabextract -q -d "$d" "$CABS/$b" >/dev/null 2>&1 || true
    if [ -n "$(find "$d" -name '*.inf' -print -quit)" ]; then
        made=$((made + 1))
    else
        rm -rf "$d"
    fi
done
DRV=$STAGE/pkg
rm -rf "$DRV"; mkdir -p "$DRV"
for b in "${CABNAMES[@]}"; do [ -d "$STAGE/${b%.cab}" ] && cp -a "$STAGE/${b%.cab}" "$DRV/${b%.cab}"; done
infs=$(find "$DRV" -name '*.inf' | wc -l)
syss=$(find "$DRV" -name '*.sys' | wc -l)
cats=$(find "$DRV" -name '*.cat' | wc -l)
echo "   pkg: $infs INFs, $syss .sys, $cats .cat in $(find "$DRV" -mindepth 1 -maxdepth 1 -type d | wc -l) dirs ($made built, $skipped cached)"
[ "$infs" -eq "$n_cabs" ] || die "only $infs of $n_cabs CABs hold an INF"

# ---------------------------------------------------------------------------
say "injecting into the boot image"
# The tree is ours, so the WIM is edited in place.
WIM=$TREE/sources/boot.wim

# `drvload` before `wpeinit`, so the PnP pass sees the drivers rather than
# discovering devices and then being handed their drivers. INFs that fail are
# named by `drvload` and do not stop the loop - a package for hardware this
# board does not have is not an error here. `X:\setup.exe` is the Setup entry
# point inside this image; without it the injected `startnet.cmd` would replace
# WinPE's default Setup launch with nothing.
cat > "$STAGE/startnet.cmd" <<'CMD'
@echo off
echo Loading the gauguin platform drivers from X:\Drivers
for /r "X:\Drivers" %%i in (*.inf) do (
    echo   %%~nxi
    drvload "%%i"
)
echo Initializing WinPE
wpeinit
echo.
echo Starting Windows Setup.
echo The P3 storage gate is met if Setup's disk list shows the internal UFS.
echo If it does not, press Shift+F10 for a command prompt and run:  diskpart
echo.
X:\setup.exe
CMD

wimlib-imagex update "$WIM" "$BOOTIDX" 2>&1 <<EOF | tail -2
add $DRV /Drivers
add $STAGE/startnet.cmd /Windows/System32/startnet.cmd
EOF

n=$(wimlib-imagex dir "$WIM" "$BOOTIDX" --path='/Drivers' 2>/dev/null | wc -l)
[ "$n" -gt 1 ] || die "injection did not land: /Drivers is empty in image $BOOTIDX"
echo "   /Drivers holds $((n - 1)) entries in image $BOOTIDX"

# ---------------------------------------------------------------------------
say "verifying"
fail=
[ -f "$TREE/sources/install.wim" ]   || fail="$fail install.wim"
[ -f "$TREE/efi/boot/bootaa64.efi" ] || fail="$fail BOOTAA64.EFI"
[ -f "$TREE/efi/microsoft/boot/bcd" ] || fail="$fail BCD"
[ -f "$TREE/sources/boot.wim" ]      || fail="$fail boot.wim"
[ -f "$TREE/boot/boot.sdi" ]         || fail="$fail BOOT.SDI"
[ -z "$fail" ] || die "verification failed, missing:$fail"
arch_all_arm64 "$TREE/sources/install.wim" "install.wim (post)"
arch_all_arm64 "$TREE/sources/boot.wim"    "boot.wim (post)"
n=$(wimlib-imagex dir "$TREE/sources/boot.wim" "$BOOTIDX" --path='/Drivers' 2>/dev/null | wc -l)
echo "   boot.wim image $BOOTIDX /Drivers $((n - 1)) entries; install.wim $(stat -c%s "$TREE/sources/install.wim") B"
echo "   total $(du -sh "$TREE" | cut -f1) in $TREE"

# The FAT32 stick, built by the tool that already exists for it rather than by a
# second implementation here. Under FAT32's 4 GiB ceiling because install.wim is
# 3.28 GiB, so no `.swm` split and no reassembly by Setup.
if [ -n "$IMG" ]; then
    say "building the FAT32 stick image"
    "$REPO/tools/make-win-stick.sh" "$TREE" "$IMG" "$SIZE"
fi

cat <<EOF

Medium is ready at $TREE
   $(du -sh "$TREE" | cut -f1), $(find "$TREE" -type f | wc -l) files, install.wim + boot.wim both ARM64

Write it to a FAT32 stick with:
   cp -a "$TREE"/. /path/to/stick/
   # or:  tools/make-win-stick.sh "$TREE" <out.img> 6G

Then, on the phone: the stick boots Windows Setup (boot.wim image $BOOTIDX). The
injected startnet.cmd loads the 112 platform drivers into WinPE, then runs
Setup. Whether the internal UFS appears in Setup's disk list is the P3 gate. If
it does not, the finding is about this project's ACPI - the medium's own driver
path is complete - and the thing to capture is what Setup's disk list showed.
EOF