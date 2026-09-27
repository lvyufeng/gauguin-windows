#!/usr/bin/env bash
#
# Pull the driver packages' .inf files out of a Windows image, so that
# `tools/acpi-hid-census.py --drivers` can be pointed at the OS's own drivers.
#
# Why this exists: that census was written against a *vendor* driver set — one
# board's package, which is where a platform driver comes from. Some of the ids
# this port writes are not the vendor's at all, and the vendor set's silence
# about them reads exactly like a gap. `ACPI\QCOM24A5` on UFS0 is claimed by no
# .inf in the 112-cab Kodiak set and by exactly one .inf in Windows itself,
# `storufs.inf` (Microsoft's UFS host driver, `[Qualcomm.NTamd64]
# %ACPI\QCOM24A5.DeviceDesc%=UfsQualcomm8996Install`); the parent of the two
# `URS\QCOM0A8B&…` children the vendor's USB filters bind is Microsoft's
# role-switch stack, which no vendor package ships either. So the OS is a
# second oracle, and for ids like those two it is the only oracle.
#
# What it reads: the DriverStore package INFs out of one image. In an installer
# that set is exactly what the installer can bind, which is what makes boot.wim
# the interesting image for the P3 gate — "the Windows installer boots and sees
# UFS" is a statement about boot.wim's drivers, not about a full install's.
#
# Usage:  tools/os-driver-store.sh <iso|wim> <outdir> [image-index]
#         tools/os-driver-store.sh ~/Downloads/Win11.iso /tmp/winpe-infs
#
#         WIM=sources/install.wim tools/os-driver-store.sh <iso> <outdir>
#             read the full OS instead of the installer (default is boot.wim).
#
# Measured 2026-09-27 on Win11 25H2 x64 (10.0.26100). The two images are not
# the same set, and the difference is the point. Counts are *claims*: an id
# bound by a models line or named by `ExcludeFromSelect`, not every place the
# string `ACPI\...` occurs (Step 4.151 - the earlier counts here included five
# `[Strings]` key names per image that bind nothing):
#
#   boot.wim   index 1   339 .inf   80 claimed ids   1 of gauguin's 34
#   install.wim index 1  712 .inf  111 claimed ids   1 of gauguin's 34
#
# install.wim's 111 are 105 hardware ids, 3 compatible-only (`PNP0CA0`,
# `PNP0CA1`, `WACF006`) and 3 `ExcludeFromSelect`-only (`NVDA0112`,
# `NVDA0212`, `TXNW0073`). The compatible bucket is the one that matters here:
# `PNP0CA1` is a bind for a node whose *hardware* id nothing claims.
#
# Both claim `QCOM24A5` (UFS0, `storufs.inf`) and no other QCOM id of ours; the
# vendor set answers 32 of the 34 and the union is 33. What install.wim adds is
# the URS *parent*: `urssynopsys.inf` binds `ACPI\QCOM24B6, ACPI\PNP0CA1`, so the
# `_CID` this port writes on URS0 is claimed there and appears claimed nowhere
# in boot.wim, whose only URS file is the function-side child driver.
# That last clause is an x64 measurement and does *not* transfer - see Step 4.154
# at the end of this header.
#
# Read out of an *x64* image, and that is measured rather than taken from the
# ISO's name: a DriverStore folder is `<inf>_<arch>_<hash>`, so the suffix
# counts what the image is. install.wim index 1 gives 710 `_amd64_` and 2
# `_x86_` and no `_arm64_` at all; boot.wim index 1 gives 339 `_amd64_` and no
# `_arm64_`. All five infs behind the two verdicts above - `QCOM24A5` and
# `PNP0CA1` - are UTF-16 with every `[Manufacturer]` entry ending `,NTamd64` and
# every models section `.NTamd64`, and no `NTarm64` section in any of them - so
# `storufs.inf` binding `ACPI\QCOM24A5` is a statement about the file in an x64
# image, whose ARM64 twin is a different file carrying a different section - and
# that file was not on this host when that paragraph was written. The vendor set
# is the other way round:
# `~/work/woa-ref/inf-7280` is 112 `.inf`, all UTF-16, 241 `NTARM64` decorations
# and not one line mentioning `NTamd64`, `NTx86` or `NTia64`. Its 155 claims are
# ARM64 claims already, so what is missing costs the OS-side verdicts alone - and
# those two are not equal in weight: `QCOM0A8B` is USB, `QCOM24A5` is the storage
# Windows boots from.
#
# Step 4.153 read the ARM64 twin. The blocker was never the media; it was the
# host. `dl.delivery.mp.microsoft.com` answers 000 from here, which is what the
# ISO's own download path uses, but a UUP `get.php` id returns per-file URLs on
# `tlu.dl.delivery.mp.microsoft.com` and that host answers 206 on a range
# request in 0.28 s. `api.uupdump.net/get.php?id=<build>&lang=en-us&edition=…`
# with an arm64 25H2 build id gives 68 files, 8.07 GiB, each with its own signed
# URL and sha1; all 68 downloaded and all 68 verified. `listid.php` is what
# finds the id - the earlier 400/404s were a bad id and a wrong parameter, not a
# dead route.
#
# Two things about reading it are worth knowing before the next attempt. The
# edition ESD (`professional_en-us.esd`, image 3 = Windows 11 Pro, ARM64, 16.0
# GB) is a *delta* WIM: 7z lists all 389 of its DriverStore packages and
# extracts 159 of them as zero-byte files with `Data Error`, and wimlib without
# `--ref` fails the whole pattern with "a file resource needed to complete the
# operation was missing". `wimlib-imagex extract <esd> 3 <path> --ref=<each of
# the other 18 ESD/WIM files>` resolves them - the base image is split across the
# download set. Extracting the 389 paths one at a time, tolerating failures,
# gives 386, none of them empty; the three that cannot be read are `helloface`,
# `ntprint` and `prnms003`, none of which names a device gauguin has.
#
# The arm64 DriverStore is 389 packages, 387 `_arm64_` and 2 `_x86_` - the same
# shape as the x64 one (710/2) - and `--bind` against it moves no verdict for
# gauguin. `storufs.inf` binds `ACPI\QCOM24A5` under `[Qualcomm.NTarm64]`;
# `urssynopsys.inf` binds `ACPI\QCOM24B6, ACPI\PNP0CA1` under `[UrsSynopsys.NTarm64]`.
# So the two OS-side claims were the same claim in both builds and the x64
# reading was not a weaker one - which is what this header said it might be, now
# checked rather than assumed. What the arm64 set adds is that the generic route
# is there too: `storufs.inf` binds `ACPI\CC_010901` in `[Generic.NTarm64]`.
#
# `wimlib-imagex` is not packaged for this host - Deepin's index has no
# `wimtools` candidate and `apt-get update` does not finish - so it was unpacked
# from the Debian trixie debs into `~/opt/wimlib` with `dpkg-deb -x`, together
# with `libwim15t64`, `libntfs-3g90` and `libfuse3-4`, and run with
# `LD_LIBRARY_PATH=$HOME/opt/wimlib/usr/lib/x86_64-linux-gnu`. The same unpack
# provides `mkwinpeimg`, which is what a P3 boot medium will be built with.
#
# Step 4.154 read the ARM64 image the P3 gate actually loads, and it is the ESD's
# *second* image rather than its first. The three are one medium in three pieces:
# image 1 `Windows Setup Media` (274.6 MB) is the medium's whole EFI tree and has
# no `/sources/boot.wim` among its 934 files under `/sources/`; image 2 (WinRE) is
# that WIM; image 3 is the OS. So the ARM64 twin of the x64 `boot.wim` run above
# is **image 2**, and its numbers are 233 DriverStore packages, **all 233
# `_arm64_`**, all 233 `.inf` extractable in one glob with the `--ref` set and
# none of them empty - the delta penalty above is image 3's, not this one's.
# `--bind` gives 63 claimed ids: 55 hardware, 5 compatible-only, 3
# `ExcludeFromSelect`-only, and the same five `[Strings]` key names.
#
# The correction, and the reason the x64 clause four paragraphs up is marked: on
# ARM64 the boot image claims **both** of this table's storage ids. `storufs.inf`
# claims `ACPI\QCOM24A5` for UFS0, and `urssynopsys.inf` claims `ACPI\PNP0CA1` -
# URS0's `_CID`, in the `compatible` position - because all four URS files are
# present in image 2, not only the function-side children. The x64 boot.wim and
# the ARM64 boot image are therefore not the same set with different suffixes, so
# "nothing binds this" read off one is not a statement about the other. Which
# image you read is part of the answer, and so is which architecture it is.
#
# For the medium itself, two facts worth carrying: the removable-media loader slot
# is `BOOTAA64.EFI` - a grep for `bootarm64` or `bootx64` across all three images
# returns nothing, and the obvious-looking analogue is the one name firmware would
# not find - and image 1's `bootaa64.efi` hashes identically to image 2's
# `bootmgfw.efi`, so it is the boot manager renamed into that slot. The BCD is a
# `regf` hive whose own strings name `\boot\boot.sdi` and `\sources\boot.wim`, so
# the medium's contract with this script is explicit: image 1's EFI tree, image 2
# written out at that path, and at most a two-line `winpeshl.ini`.
#
# An earlier draft of this header said "both images: 339 .inf files, 85 distinct
# `ACPI\` ids". That was boot.wim's count written twice: the install.wim run had
# not been made, and a number copied forward from the run that had reads exactly
# like a measurement of the run that had not.
#
# Point the census at both directories rather than picking one, or the answer is
# a statement about one package read as a statement about the system.
#
# Nothing is mounted and nothing outside <outdir> is written. The .inf files
# are text; no .sys is extracted, so this answers which ids and services an
# image declares, not what a binary does with them.
set -u

SRC=${1:-}
OUT=${2:-}
INDEX=${3:-1}
WIM=${WIM:-sources/boot.wim}

log() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

usage() {
    # The header, not a line range. Line ranges here have been wrong twice -
    # Step 4.151 moved 2,50p to 2,58p when the header grew, and this step's
    # paragraphs ran past 58 again - and a --help that stops mid-sentence reads
    # like the header ended there. Stop at the first line of code instead.
    awk 'NR > 1 && /^set -u/ { exit } NR > 1' "$0" | sed 's/^# \{0,1\}//'
}

case "${1:-}" in
    -h|--help|"") usage; exit 0 ;;
esac
if [ -z "${1:-}" ] || [ -z "${2:-}" ]; then
    usage
    exit 2
fi
command -v 7z >/dev/null 2>&1 || die "7z not found (p7zip-full); nothing else here reads .wim"
[ -f "$SRC" ] || die "no such image: $SRC"
case "$INDEX" in
    ''|*[!0-9]*) die "image index must be a number, not '$INDEX'" ;;
esac

WORK="$OUT.wim"
mkdir -p "$OUT" || die "cannot create $OUT"

# An .iso is a container around the .wim, and 7z will not chain the two: the
# wim comes out first, whole, next to the output directory rather than inside
# it, so that the walk below sees drivers and nothing else.
case "$SRC" in
    *.iso|*.ISO)
        log "== extracting $WIM from $(basename "$SRC")"
        7z e -y -o"$(dirname "$WORK")" "$SRC" "$WIM" >/dev/null \
            || die "could not read $WIM out of $SRC"
        WIMPATH="$(dirname "$WORK")/$(basename "$WIM")"
        ;;
    *)  WIMPATH="$SRC" ;;
esac
[ -f "$WIMPATH" ] || die "no image at $WIMPATH"

# One location, not every location. A full install carries the same package
# under WinSxS as well as under DriverStore; extracting both would hand the
# census two paths for one file and it would report the package twice. It
# dedupes per path, and two paths are two paths.
log "== extracting image $INDEX DriverStore INFs"
7z x -y -o"$OUT" "$WIMPATH" \
    "$INDEX/Windows/System32/DriverStore/FileRepository/*/*.inf" >/dev/null \
    || die "extraction failed"

count=$(find "$OUT" -name '*.inf' | wc -l)
log "   ok  $count .inf files under $OUT"
[ "$count" -gt 0 ] || die "no .inf files came out; is image $INDEX the right index?"

cat <<EOF

Read it with the same tool the vendor set is read with:

  python3 tools/acpi-hid-census.py --drivers $OUT --bind --asl tools/acpi/gauguin.asl

An id this set claims and the vendor set does not is an id whose driver is the
OS's; an id this set does not claim either is one nothing in the image binds.
Which image you read is part of the answer, not a detail: boot.wim is what the
installer can bind, so it is the right set for the P3 gate, and it is missing
the URS parent (`urssynopsys.inf`) that install.wim has - so "nothing binds
this" read off boot.wim is a statement about the installer.
On a Windows image for another architecture the ids are the same and the answer
is not: the packages are per-architecture, so an .inf read from an x64 image
says nothing about the ARM64 build of the same driver.
EOF
