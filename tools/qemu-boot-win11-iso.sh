#!/usr/bin/env bash
# Boot the built Windows 11 ARM64 installer media under QEMU's ARM64 virt
# machine and photograph what comes up.
#
# The P3 gate is "a Windows 11 ARM64 installer boots off a USB stick and sees the
# internal UFS". The stick and the phone are both out of reach from this host, so
# the part of that sentence this script can test is the media: that the media's
# own EFI bootloader loads, that Windows Setup starts, and that Setup's
# disk-selection step sees a disk. `tools/inspect-win-iso.py` answers the cheaper
# half of the same question by reading the media; this is the half that needs the
# thing to run.
#
# Two media are accepted and they are not equivalent, so which one is handed over
# decides what the run is evidence for.
#
#   *.iso   the converter's own output: UDF bridge, ISO 9660 tree emptied by
#           `--hide "*"`, El Torito boot image of 6.88 MB holding one file,
#           `\EFI\BOOT\BOOTAA64.EFI`. Booting it exercises `PartitionDxe`'s El
#           Torito path and then needs a UDF driver to reach `\sources\boot.wim`.
#   *.img   the FAT32 stick `tools/make-win-stick.sh` builds. Booting it
#           exercises the path the phone will actually take, because the phone's
#           firmware has `Fat` and neither a UDF nor an ISO 9660 driver.
#
# A run against the ISO can therefore fail on this host for a reason that has
# nothing to do with gauguin -- whether AAVMF carries `UdfDxe` -- while a run
# against the stick cannot fail that way on either machine. Prefer the stick; run
# the ISO when the question is about the ISO.
#
# Two properties of this host shape every choice below.
#
# The first is that KVM cannot run an ARM64 guest on an x86_64 host -- KVM is
# same-architecture only, and `qemu-system-aarch64 -accel kvm` answers `invalid
# accelerator kvm` here. So this is TCG, which is software emulation: Windows
# Setup on four emulated ARM64 cores takes tens of minutes to reach the first
# drawn pixel, and a run that ends in nothing has to be told apart from a run
# that had not finished. That is why the screen is dumped on a schedule and the
# dumps are kept rather than only the last one.
#
# The second is that `virt` is not gauguin: different interrupt controller,
# different UART, a GICv3 and no UFS, and the disk and the install media are both
# behind a QEMU XHCI rather than behind UFS and a real hub. A Setup screen here
# therefore does not prove the phone boots this media. What it proves is that the
# artifact is not the thing that fails first, which is the failure that would
# otherwise be discovered on the phone -- one flash later, under `先读屏，再刷下一次`.
#
# The TPM this attaches is a QEMU convenience and is not what gauguin has: gauguin
# has no discrete TPM and no TPM CRB, and Windows 11's own check would have to be
# answered on the phone some other way (an fTPM behind OP-TEE, or the setup-time
# registry bypass). It is attached here only so that this run gets past that check
# and reaches the disk step, which is the step the gate is about. `--no-tpm` runs
# without it, and then the Setup screen that appears is the refusal screen -- also
# a screen, and still evidence the media booted.
#
#   tools/qemu-boot-win11-iso.sh MEDIA [OUTDIR] [SECONDS] [--no-tpm]
set -u

MEDIA="${1:?usage: qemu-boot-win11-iso.sh media.iso|media.img [outdir] [seconds]}"
OUT="${2:-$(dirname "$MEDIA")/qemu-boot}"
SECS="${3:-10800}"          # 3 h: TCG, and one boot may be slower than it looks
USE_TPM=1
[ "${4:-}" = "--no-tpm" ] && USE_TPM=0

FW_CODE=/usr/share/AAVMF/AAVMF_CODE.no-secboot.fd
FW_VARS=/usr/share/AAVMF/AAVMF_VARS.fd
[ -r "$FW_CODE" ] || { echo "no AAVMF firmware at $FW_CODE"; exit 1; }
[ -r "$MEDIA" ]   || { echo "no media at $MEDIA"; exit 1; }

# The medium's own shape picks the QEMU device, and the difference is not
# cosmetic: `media=cdrom` makes the device report 2048-byte read-only blocks,
# which is the condition `PartitionDxe`'s El Torito path binds to, while a stick
# must present itself as an ordinary removable disk so that `PartitionDxe` reads
# an MBR and `Fat` mounts the partition. Handing an ISO over as a disk loses the
# boot catalog entirely, and handing a stick over as a CD-ROM loses the partition
# table.
case "$MEDIA" in
  *.iso) DRIVE=(-drive if=none,id=boot,format=raw,media=cdrom,readonly=on,file="$MEDIA")
         DEVD=(-device usb-storage,drive=boot,bus=xhci.0,bootindex=1)
         echo "media     ISO, attached as a USB CD-ROM (El Torito path)" ;;
  *)     DRIVE=(-drive if=none,id=boot,format=raw,file="$MEDIA")
         DEVD=(-device usb-storage,drive=boot,bus=xhci.0,bootindex=1)
         echo "media     disk image, attached as USB mass storage (MBR + FAT path)" ;;
esac

mkdir -p "$OUT"
# Absolutised before anything is spawned, because two consumers resolve paths
# against their own working directory rather than against this script's: QEMU
# resolves `-monitor unix:` and `screendump` relative to its own cwd, and the
# monitor's answer is a path this shell then reads. A relative $OUT works only
# while those two agree, which is a coincidence worth not depending on.
OUT=$(cd "$OUT" && pwd)
cp -f "$FW_VARS" "$OUT/vars.fd"
truncate -s 64G "$OUT/disk.img"          # stands in for userdata/internal UFS

declare -a TPM=()
if [ $USE_TPM = 1 ]; then
  # A `swtpm` from an earlier run of this script that died before its own kill is
  # still holding the control socket path, and the new one then fails to bind it
  # and the failure arrives from QEMU's `-chardev` line rather than from swtpm.
  # The pattern is bracketed so it cannot match this shell's own command line,
  # which is how an inline `pkill -f` of the same literal kills the caller.
  pkill -f "swt[m]m socket.*$OUT/" 2>/dev/null || true
  rm -f "$OUT/swtpm.sock" "$OUT/tpm"
  mkdir -p "$OUT/tpm"
  swtpm socket --tpm2 --tpmstate dir="$OUT/tpm" \
    --ctrl type=unixio,path="$OUT/swtpm.sock" --log level=1 \
    --flags not-need-init > "$OUT/swtpm.log" 2>&1 &
  SWTPM=$!
  for _ in $(seq 40); do [ -S "$OUT/swtpm.sock" ] && break; sleep 0.25; done
  TPM=(-chardev socket,id=chrtpm,path="$OUT/swtpm.sock"
       -tpmdev emulator,id=tpm0,chardev=chrtpm
       -device tpm-tis-device,tpmdev=tpm0)
  echo "tpm       swtpm pid $SWTPM, socket $OUT/swtpm.sock"
else
  echo "tpm       none (--no-tpm): the Setup screen reached will be the refusal"
fi

# `-cpu max` rather than a named core, because Windows 11 ARM64 wants the ARMv8.1
# atomics that `cortex-a72` does not have and that a `max` CPU does. `-nic none`
# because the `virt` machine's default NIC is a virtio PCI device whose option ROM
# this host does not have -- the distribution's qemu-system-data ships no `.rom`
# files at all, so `-machine virt` without `-nic none` dies before the firmware
# starts with `failed to find romfile "efi-virtio.rom"`. No network is wanted here
# anyway: the gate is about a disk, and a NIC Windows has no driver for would only
# add a device that cannot work.
#
# The install media and the blank disk are both USB mass storage rather than AHCI,
# because the gate's own words are "boots off a USB stick": this way the path the
# firmware takes here is the path the phone would take. `-device ramfb` is the
# display, and it is the only one: it gives AAVMF a linear framebuffer that the
# firmware exposes as a GOP, that `screendump` then reads, and that Windows' own
# basic display takes over from. A `virtio-gpu-pci` was tried first and left out
# -- Windows 11 ARM64 carries no virtio-gpu driver, so adding it risks Setup
# choosing a primary adapter it cannot draw on. QEMU does log
# `Could not open option rom 'vgabios-ramfb.bin'` for ramfb on this host; that ROM
# is a legacy x86 VGA BIOS that an AArch64 guest never executes, and the dry run
# against the UEFI shell captured a real 800x600 frame with text on it, so the
# warning is not a defect in this path.
#
# The blank disk is 64 GB of zeros standing in for the internal UFS. It is what
# the gate's second half is about -- "and sees the internal UFS" -- so a run that
# reaches Setup's disk step and lists a 64 GB disk has answered that half as far
# as this host can.
setsid qemu-system-aarch64 \
  -machine virt,gic-version=3,highmem=on \
  -accel tcg \
  -cpu max -smp 4 -m 4096 \
  -nic none \
  -rtc base=localtime \
  -drive if=pflash,format=raw,unit=0,file="$FW_CODE",readonly=on \
  -drive if=pflash,format=raw,unit=1,file="$OUT/vars.fd" \
  -device ramfb \
  -device qemu-xhci,id=xhci,p2=4,p3=4 \
  -device usb-kbd,bus=xhci.0 \
  -device usb-tablet,bus=xhci.0 \
  "${DRIVE[@]}" \
  "${DEVD[@]}" \
  -drive if=none,id=hd,format=raw,file="$OUT/disk.img" \
  -device usb-storage,drive=hd,bus=xhci.0,bootindex=2 \
  "${TPM[@]}" \
  -display none \
  -monitor unix:"$OUT/mon.sock",server,nowait \
  -serial "file:$OUT/serial.log" \
  > "$OUT/qemu.log" 2>&1 &
QPID=$!
sleep 2
if ! kill -0 $QPID 2>/dev/null; then
  echo "qemu refused to start:"; cat "$OUT/qemu.log"; exit 1
fi
echo "qemu      pid $QPID, screen dumped into $OUT for up to ${SECS}s"

# The screen is dumped on a schedule rather than once at the end, because the
# transition is the evidence: a single black frame and a single Setup window are
# the same amount of information about whether anything ran. The interval starts
# short, to catch the firmware's own screen before the ISO's bootloader replaces
# it, and grows so that a three-hour run does not fill the disk with frames.
n=0
first=1
end=$((SECONDS + SECS))
while [ $SECONDS -lt $end ]; do
  if ! kill -0 $QPID 2>/dev/null; then echo "qemu    exited at ${SECONDS}s"; break; fi
  if [ $first = 1 ]; then wait_s=10; first=0; else wait_s=120; fi
  sleep $wait_s
  n=$((n + 1))
  ppm="$OUT/shot-$(printf '%03d' "$n").ppm"
  printf 'screendump %s\n' "$ppm" | \
    timeout 30 socat - UNIX-CONNECT:"$OUT/mon.sock" >/dev/null 2>&1
  # The frame just taken is turned into a PNG immediately and its colour count
  # printed, so a long run can be watched for the moment the screen stops being
  # one flat colour -- which is the moment the firmware handed off.
  #
  # The timestamp is folded into a variable rather than written inline, and the
  # `sed` uses `|` as its delimiter: the replacement text is a command
  # substitution, and an inline one inside a `//`-delimited `s` is a shell
  # expansion happening inside a field that later gets re-parsed as a sed script.
  # A missing frame is reported as a missing frame rather than as an empty
  # Python traceback, because "the monitor did not answer" and "the frame is
  # blank" are different findings and both are wanted on the same line.
  stamp=$(date +%H:%M:%S)
  if [ -s "$ppm" ]; then
    python3 "$(dirname "$0")/ppm-to-png.py" "$ppm" 2>&1 | sed "s|^|  $stamp |"
  else
    echo "  $stamp shot-$n: no frame written (screendump unanswered)"
  fi
done

kill $QPID 2>/dev/null; wait $QPID 2>/dev/null
[ $USE_TPM = 1 ] && kill $SWTPM 2>/dev/null
echo
echo "=== screens in $OUT ==="
ls -la "$OUT"/shot-*.png 2>/dev/null | awk '{print $5, $9}'
echo "=== firmware's own last words ==="
tail -12 "$OUT/serial.log" 2>/dev/null
