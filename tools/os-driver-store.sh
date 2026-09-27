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
    sed -n '2,58p' "$0" | sed 's/^# \{0,1\}//'
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
