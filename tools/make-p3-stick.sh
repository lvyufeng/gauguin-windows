#!/usr/bin/env bash
#
# Assemble a complete Windows 11 ARM64 install stick for the P3 gate.
#
# P3's gate is "a Windows 11 ARM64 installer boots off a USB stick and sees the
# internal UFS". Three things have to be true of the stick for that to be a test
# of the firmware rather than of the medium, and the medium staged at
# `~/work/woa-ref/p3-medium-built` satisfies none of them:
#
#   1. `media1` is the setup engine and nothing else - 265 MB, with
#      `sources/setup.exe` and `sources/winsetup.dll` but no `boot.wim`, no
#      `install.wim` and no `install.esd`. The install image is 6,868,632,137
#      bytes - 6.40 GiB, which `du -h` reports as `6.4G` - of
#      `win11-25h2/install.wim` sitting in a different directory, never placed
#      into `sources/`. A stick built from `media1` alone runs setup and finds
#      nothing to install.
#
#   2. `usb-p3` is the boot half - `EFI/BOOT/BOOTAA64.EFI`, `BOOT/BOOT.SDI`,
#      `SOURCES/BOOT.WIM` - and its `BOOT.WIM` is Windows RE, not Setup: one
#      image, "Microsoft Windows Recovery Environment (arm64)", 17,406 files.
#      Booting it gives the recovery tools. Windows install media normally
#      carries a second image in that WIM named "Windows Setup"; this one has
#      only the recovery image, so the two halves have to be merged into one
#      tree before either is complete.
#
#   3. Neither half carries a Qualcomm platform driver. The WinPE DriverStore
#      holds 233 packages and exactly three Qualcomm ones - `qcgpio_i.inf`,
#      `qci2c_i.inf` and `qctree_i.inf`, all Microsoft's inbox `_i` flavour -
#      plus `storufs.inf` for the UFS controller itself. None of the 112 CABs
#      in the SC7280/Kodiak package is in there, so there is no PEP, no PMIC,
#      no SPMI, no SCM, no GLINK and no ADSP. `QCOM24A5` is claimed by the
#      inbox `storufs.inf` (`%ACPI\QCOM24A5.DeviceDesc%=UfsQualcomm8996Install`
#      - the id `tools/acpi-hid-census.py --drivers ... --bind --asl` reports
#      as unclaimed by the Kodiak set), so the controller has a driver; what
#      the controller needs to be *reachable* is the platform around it.
#
# So this merges the two halves, adds the install image, and injects the
# Kodiak package into the WinPE so the drivers are on `X:` when it starts.
# WinPE has no DISM offline, so the drivers are not serviced into the
# DriverStore: they are dropped at `X:\Drivers` and loaded by a `startnet.cmd`
# that runs `drvload` on each INF before `wpeinit`, which is the documented
# runtime path and the one that works without a Windows host.
#
# The install image is split rather than copied: a FAT32 stick cannot hold a
# 6.40 GiB file - the format's ceiling is 4,294,967,295 bytes and this one is
# 6,868,632,137 - and `install.swm` + `install2.swm` in `sources/` is the form
# Setup looks for when a single image does not fit.
#
# Nothing here touches the phone. It writes only under --out.
#
# Usage:  make-p3-stick.sh [--out DIR] [--woa DIR] [--part-mb N] [--check]

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
WOA=${WOA:-$HOME/work/woa-ref}
OUT=${OUT:-$REPO/work/out/p3-stick}
PART_MB=3800
CHECK=0

while [ $# -gt 0 ]; do
    case "$1" in
        --out)     OUT=$2; shift 2 ;;
        --woa)     WOA=$2; shift 2 ;;
        --part-mb) PART_MB=$2; shift 2 ;;
        --check)   CHECK=1; shift ;;
        -h|--help) sed -n '2,45p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

die() { echo "error: $*" >&2; exit 1; }
say() { printf '\033[1m== %s\033[0m\n' "$*"; }

WPE=$WOA/p3-medium-built/usb-p3
MEDIA=$WOA/p3-medium-built/media1
INSTALL=$WOA/win11-25h2/install.wim
CABS=$WOA/qrd/7280_CLS/200.0.4.0

# ---------------------------------------------------------------------------
# Inputs. Each check names the specific defect it is looking for rather than
# just "missing file", because all three halves exist and the failure mode is a
# tree that looks complete and is not.
# ---------------------------------------------------------------------------
say "checking inputs"
[ -f "$WPE/SOURCES/BOOT.WIM" ] || die "no $WPE/SOURCES/BOOT.WIM - the boot half of the medium"
[ -f "$WPE/EFI/BOOT/BOOTAA64.EFI" ] || die "no $WPE/EFI/BOOT/BOOTAA64.EFI - the stick would not boot"
[ -f "$MEDIA/sources/setup.exe" ] || die "no $MEDIA/sources/setup.exe - the setup engine"
[ -f "$INSTALL" ] || die "no $INSTALL - the install image (6,868,632,137 B, 11 editions)"
[ -d "$CABS" ] || die "no $CABS - the SC7280/Kodiak driver package"
command -v wimlib-imagex >/dev/null || die "wimlib-imagex not found"
command -v cabextract >/dev/null || die "cabextract not found"

n_cabs=$(find "$CABS" -maxdepth 1 -name '*.cab' | wc -l)
[ "$n_cabs" -gt 0 ] || die "$CABS holds no .cab files"

# The boot half's WIM has to be the one image we know about, or the notes below
# about WinRE-vs-Setup describe a different file.
boot_images=$(wimlib-imagex info "$WPE/SOURCES/BOOT.WIM" 2>/dev/null |
              sed -n 's/^Image Count: *//p')
boot_name=$(wimlib-imagex info "$WPE/SOURCES/BOOT.WIM" 2>/dev/null |
            sed -n 's/^Name: *//p' | head -1)

install_images=$(wimlib-imagex info "$INSTALL" 2>/dev/null |
                 sed -n 's/^Image Count: *//p')

echo "   boot half      $WPE  (BOOT.WIM: $boot_images image(s), \"$boot_name\")"
echo "   setup half     $MEDIA  (setup.exe present, no install image of its own)"
echo "   install image  $INSTALL  ($install_images edition(s), $(du -h "$INSTALL" | cut -f1))"
echo "   driver set     $CABS  ($n_cabs CABs)"

if [ "$boot_images" -lt 2 ]; then
    cat <<EOF

   note: that BOOT.WIM has $boot_images image, so it is Windows RE and not
   Setup - booting it reaches the recovery tools. Setup still runs from it:
   open a command prompt, find the stick's letter, and run its
   sources\\setup.exe. The alternative is a Setup image built from the UUP's
   WinPE-Setup packages, which are not assembled in this tree.
EOF
fi

if [ "$CHECK" = 1 ]; then
    say "check only; nothing written"
    exit 0
fi

# ---------------------------------------------------------------------------
say "laying out the merged medium"
# ---------------------------------------------------------------------------
# media1 first, then the boot half over it. The two halves do not share a
# spelling: media1 uses the medium's own lowercase convention (`sources`,
# `boot`, `efi`, `efi/microsoft/boot`) and usb-p3 uses the build tree's
# uppercase one (`SOURCES`, `BOOT`, `EFI/MICROSOFT/BOOT`). On the FAT32 stick
# those are one directory each, but on this host they are two, so a plain
# `cp -a` of both produces a tree with `sources/setup.exe` and
# `SOURCES/BOOT.WIM` side by side - which is not what the stick will look like
# and which hides the merge behind a check that then fails on a file that is
# present under the other spelling. Everything is folded to lowercase on the
# way in instead, which is what the target filesystem means by these names
# anyway, so the two halves merge where they overlap rather than beside each
# other. Where they overlap the boot half wins: it is the half built for ARM64.
rm -rf "$OUT"
mkdir -p "$OUT"
cp -a "$MEDIA/." "$OUT/"
( cd "$WPE" && find . -type f ) | while IFS= read -r rel; do
    dst=$(printf '%s' "${rel#./}" | tr 'A-Z' 'a-z')
    mkdir -p "$OUT/$(dirname "$dst")"
    cp -a "$WPE/${rel#./}" "$OUT/$dst"
done

[ -f "$OUT/efi/boot/bootaa64.efi" ] || die "merge lost efi/boot/bootaa64.efi"
[ -f "$OUT/sources/boot.wim" ] || die "merge lost sources/BOOT.WIM"
[ -f "$OUT/sources/setup.exe" ] || die "merge lost sources/setup.exe"
[ -f "$OUT/boot/boot.sdi" ] || die "merge lost boot/boot.sdi"
echo "   $OUT  ($(find "$OUT" -type f | wc -l) files, $(du -sh "$OUT" | cut -f1))"

# ---------------------------------------------------------------------------
say "staging the driver package"
# ---------------------------------------------------------------------------
# Every CAB must yield an .inf; not every one yields a .sys. cabextract warns
# about trailing bytes on these - they are signed and carry the signature after
# the cabinet - so the warning is not a failure, but a CAB with no .inf is.
#
# Extraction is cached outside --out, because it is the slow half of this
# script (112 cabinets, 211 MB) and it does not depend on --out. The marker is
# the CAB count, so pointing --woa at a package of a different size re-extracts
# rather than reusing the wrong one.
# A package directory is one named after its CAB - `qcadsprpc7280/` - and that
# is the only thing in the cache besides the marker and `startnet.cmd`. The
# directory list is derived from the CABs rather than globbed out of the cache,
# because the cache survives across versions of this script and an earlier one
# left a `flat/` directory behind: a glob would have carried that duplicate
# package in as a 113th one with all 112 INFs in it a second time.
STAGE=${DRIVER_CACHE:-$REPO/work/out/.p3-stick-drivers}
CABNAMES=()
for cab in "$CABS"/*.cab; do CABNAMES+=("$(basename "$cab" .cab)"); done

if [ "$(cat "$STAGE/.cabs" 2>/dev/null)" = "$n_cabs" ]; then
    echo "   reusing $STAGE ($n_cabs CABs)"
else
    rm -rf "$STAGE"; mkdir -p "$STAGE"
    noinf=
    for b in "${CABNAMES[@]}"; do
        mkdir -p "$STAGE/$b"
        cabextract -q -s -d "$STAGE/$b" "$CABS/$b.cab" >/dev/null 2>&1 || true
        compgen -G "$STAGE/$b/*.inf" >/dev/null || noinf="$noinf $b"
    done
    [ -z "$noinf" ] || die "these CABs yielded no .inf:$noinf"
    echo "$n_cabs" > "$STAGE/.cabs"
fi

infs=0; syss=0; cats=0; nosys=0
for b in "${CABNAMES[@]}"; do
    [ -d "$STAGE/$b" ] || die "CAB $b was not extracted into $STAGE"
    compgen -G "$STAGE/$b/*.inf" >/dev/null && infs=$((infs + 1))
    n=0
    for f in "$STAGE/$b"/*.sys; do [ -e "$f" ] && { syss=$((syss + 1)); n=$((n + 1)); }; done
    [ "$n" -gt 0 ] || nosys=$((nosys + 1))
    for f in "$STAGE/$b"/*.cat; do [ -e "$f" ] && cats=$((cats + 1)); done
done
[ "$infs" -eq "$n_cabs" ] || die "only $infs of $n_cabs CABs hold an .inf"
echo "   $infs of $n_cabs CABs hold an INF, with $syss .sys and $cats .cat beside them;"
echo "   $nosys of the $n_cabs carry no .sys at all - extension packages that add"
echo "   registry keys to another driver rather than a service image of their own"

# One directory per CAB, kept as the CAB shipped it. The first version of this
# script flattened all 112 into one directory and refused to continue when four
# names arrived twice with different contents - which is what those four are,
# not a defect in the package. `qcfirmware7280.cat` exists in three variants,
# 11619, 11648 and 11613 bytes, and each variant's INF names it as a sibling:
#
#     CatalogFile = qcfirmware7280.cat
#
# so flattening hands two of the three the wrong catalog and Windows rejects
# them as unsigned. It is the same shape for `libcdsprpc.dll` (183448 bytes out
# of qcadsprpc7280, 183440 out of qccamavs7280) and `libadsprpc.dll` (183432
# out of qcadsprpc7280, 175344 out of qcSensorsConfigCrd7280). A Windows driver
# package is a directory - INF, CAT and SYS are resolved against the INF's own
# location, and a third of the 112 CABs carry an INF and no SYS because they are
# extension packages that add registry keys to another driver. So the tree is
# preserved and `drvload` is pointed at each INF where it lies.
#
# The cache is used for the extraction - 112 signed cabinets, which is the slow
# half of this script - and not for the `pkg` tree, which is a copy of those
# directories that is cheaper to redo than to invalidate.
DRV=$STAGE/pkg
rm -rf "$DRV"; mkdir -p "$DRV"
for b in "${CABNAMES[@]}"; do
    cp -a "$STAGE/$b" "$DRV/$b"
done
echo "   pkg: $(find "$DRV" -name '*.inf' | wc -l) INFs in $(find "$DRV" -mindepth 1 -maxdepth 1 -type d | wc -l) package directories, $(du -sh "$DRV" | cut -f1)"

# ---------------------------------------------------------------------------
say "injecting into the WinPE"
# ---------------------------------------------------------------------------
# A copy is never made: `wimlib-imagex update` rewrites the file it is given,
# and `p3-medium-built/usb-p3/SOURCES/BOOT.WIM` is the only WinRE image this
# tree has. `$WIM` is the merged tree's copy, which is ours.
WIM=$OUT/sources/boot.wim

# `drvload` before `wpeinit`, so the PnP pass sees the drivers rather than
# discovering devices and then being handed their drivers. `storufs` is inbox
# and already loaded; this is for everything around it.
#
# `/r` walks the tree, because the packages are kept in their own directories.
# `drvload` resolves an INF's CAT and its CopyFiles entries against the INF's
# own directory, so it has to be given each INF where it lies rather than a
# copy of it. INFs that fail are reported by name and do not stop the loop -
# a package for hardware this board does not have is not an error here.
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
echo The P3 storage gate is met if DISKPART lists the internal UFS below.
echo    list disk
echo    list volume
echo.
cmd.exe
CMD

# `wimlib-imagex update` takes exactly one --command and reads the rest of them
# from stdin, so both edits go in on one here-document rather than as two flags.
wimlib-imagex update "$WIM" 1 2>&1 <<EOF | tail -3
add $DRV /Drivers
add $STAGE/startnet.cmd /Windows/System32/startnet.cmd
EOF
echo "   BOOT.WIM now $(stat -c%s "$WIM") bytes"

n=$(wimlib-imagex dir "$WIM" 1 --path='/Drivers' 2>/dev/null | wc -l)
[ "$n" -gt 1 ] || die "injection did not land: /Drivers is empty in the WIM"
echo "   /Drivers holds $((n - 1)) entries"

# ---------------------------------------------------------------------------
say "adding the install image"
# ---------------------------------------------------------------------------
# Split, because the stick has to be FAT32 to be read by this device's UEFI and
# FAT32 has a 4 GiB file limit. Setup reads `install.swm` + `install2.swm` from
# `sources/` exactly as it reads a single `install.wim`.
wimlib-imagex split "$INSTALL" "$OUT/sources/install.swm" "$PART_MB" 2>&1 | tail -3
ls -l "$OUT/sources"/install*.swm | awk '{printf "   %s  %s bytes\n", $9, $5}'

# ---------------------------------------------------------------------------
say "verifying"
# ---------------------------------------------------------------------------
fail=
[ -f "$OUT/sources/install.swm" ] || fail="$fail install.swm"
[ -f "$OUT/efi/boot/bootaa64.efi" ] || fail="$fail BOOTAA64.EFI"
[ -f "$OUT/efi/microsoft/boot/bcd" ] || fail="$fail BCD"
[ -f "$OUT/sources/boot.wim" ] || fail="$fail BOOT.WIM"
[ -f "$OUT/sources/setup.exe" ] || fail="$fail setup.exe"
[ -f "$OUT/boot/boot.sdi" ] || fail="$fail BOOT.SDI"
[ -z "$fail" ] || die "verification failed, missing:$fail"

n=$(wimlib-imagex dir "$OUT/sources/boot.wim" 1 --path='/Drivers' 2>/dev/null | wc -l)
echo "   BOOT.WIM  1 image, /Drivers $((n - 1)) entries"
echo "   install    $(ls "$OUT/sources"/install*.swm | wc -l) part(s), $(du -ch "$OUT/sources"/install*.swm | tail -1 | cut -f1)"
echo "   total      $(du -sh "$OUT" | cut -f1) in $OUT"

cat <<EOF

Write it to a FAT32 stick with:
   cp -a "$OUT"/. /path/to/stick/

Then, on the phone: the stick boots to Windows RE (that BOOT.WIM's only image).
Open a command prompt there and run the stick's sources\\setup.exe - the
install image is beside it as install.swm. Before setup, check that
DISKPART's \`list disk\` shows the internal UFS; if it does not, the platform
drivers did not bind and the firmware's ACPI is the thing to look at, not the
medium.
EOF
