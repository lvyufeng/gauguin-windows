#!/usr/bin/env python3
"""Does a volume carry - or *wait on* - any PCI GUID this tree defines?

Why this exists. Step 4.166 concluded from a carrier count that this firmware has no PCI host bridge
and no producer of `PciIo`. A carrier count cannot support that on its own, for two reasons that this
tool exists to separate:

    a carrier is not a consumer   `InstallMultipleProtocolInterfaces (&gEfiPciIoProtocolGuid, ...)` and
                                  `LocateDevicePath (&gEfiPciIoProtocolGuid, ...)` leave the same 16
                                  bytes in the same `.text`/`.data`, so counting occurrences tells you
                                  a driver mentions a protocol and nothing about which way
    a sample is not a census      four GUIDs scanned is four GUIDs chosen, and three of the four
                                  4.166 quoted were written from memory - one of them, `de375b25-...`
                                  for `PciHostBridgeDxe`, is no driver's `FILE_GUID` in this tree at
                                  all, and a zero-hit result for the wrong GUID is a zero-hit result
                                  for the wrong reason

So both inputs here are read from the files that state them. The protocol GUIDs come from the
`*_GUID` defines themselves under `MdePkg/Include`, and the driver GUIDs from each `INF`'s own
`FILE_GUID` line - every GUID the tree defines whose name or path carries `pci`, with no list kept in
this file. `--depex` then answers the second question by decoding each `DXE_DEPEX` (0x13) and
`PEI_DEPEX` (0x1B) section in the volume and reporting which of the scanned GUIDs appear *in a
depex*, i.e. which are waited on rather than merely mentioned.

This is deliberately not `tools/depex-census.py`. That tool asks the harder question - which drivers
are held off the queue by their dependency expression, and whether the protocol they wait on has a
producer in the volume at all - and its docstring carries the two wrong answers that shaped it. This
tool answers a set-membership question and no more: it does not know whether a depex term is
satisfiable, only whether it is there.

Usage:

    python3 tools/pci-guid-census.py /tmp/fv-old.bin /tmp/fv-usb.bin
    python3 tools/pci-guid-census.py --depex /tmp/fv-usb.bin
    python3 tools/pci-guid-census.py --all --json /tmp/pci.json /tmp/fv-old.bin

`--all` scans every GUID the tree defines rather than only the PCI-named ones, which is the run that
says how many GUIDs carry a name in the tree at all (1,799 distinct `FILE_GUID`s over 8,503 `INF`
files, 482 protocol GUIDs resolved out of 527 `*_GUID` defines). The argument is any file
`tools/fv-apriori.py`'s `walk_volume` accepts: a bare firmware volume, or an Android boot image whose
gunzipped payload is one.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
import struct
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_TREE = os.path.join(ROOT, "work", "uefi", "Mu-Silicium")

DEPEX_TYPES = (0x13, 0x1B)


def load_walker():
    """`tools/fv-apriori.py`'s `walk_volume`, imported by path: `tools/` is not a package."""
    spec = importlib.util.spec_from_file_location("fvap", os.path.join(HERE, "fv-apriori.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_volume(path):
    """The volume bytes: the file itself, or the gunzipped payload of an Android boot image."""
    d = open(path, "rb").read()
    if d[:8] == b"ANDROID!":
        for off in range(0x800, min(len(d), 0x20000), 4):
            try:
                payload = gzip.decompress(d[off:])
            except (OSError, EOFError):
                continue
            if payload[0x28:0x2C] == b"_FVH":
                return payload
        raise SystemExit("%s: ANDROID! header but no volume in its first 128 KiB" % path)
    if d[0x28:0x2C] != b"_FVH":
        raise SystemExit("%s: no _FVH signature at 0x28 - not a firmware volume" % path)
    return d


def protocol_names(tree):
    """GUID -> the `*_GUID` macro that defines it, over the headers under `MdePkg/Include`."""
    out = {}
    define = re.compile(r"#define\s+(\w+_GUID)\b")
    token = re.compile(r"0x[0-9A-Fa-f]+")
    base = os.path.join(tree, "Mu_Basecore", "MdePkg", "Include")
    if not os.path.isdir(base):
        return out
    for root, _dirs, files in os.walk(base):
        for f in files:
            if not f.endswith(".h"):
                continue
            text = open(os.path.join(root, f), errors="replace").read()
            for m in define.finditer(text):
                seg = text[m.end():m.end() + 400]
                nxt = seg.find("#define")
                if nxt >= 0:
                    seg = seg[:nxt]
                vals = [int(x, 16) for x in token.findall(seg)]
                if len(vals) < 11 or vals[0] > 0xFFFFFFFF or vals[1] > 0xFFFF or vals[2] > 0xFFFF:
                    continue
                rest = vals[3:11]
                try:
                    u = uuid.UUID("%08x-%04x-%04x-%02x%02x-%s" % (
                        vals[0], vals[1], vals[2], rest[0], rest[1],
                        "".join("%02x" % v for v in rest[2:])))
                except (ValueError, IndexError):
                    continue
                out.setdefault(str(u).upper(), m.group(1))
    return out


def inf_and_pi_names(tree):
    """GUID -> (name, source) over every `INF` in the tree and every `MdePkg/Include` header, so a
    driver GUID prints as an `INF`'s `BASE_NAME` and a protocol GUID as its macro."""
    out = {}
    pat = re.compile(r"FILE_GUID\s*=\s*([0-9A-Fa-f\-]{36})")
    for root, _dirs, files in os.walk(tree):
        for f in files:
            if not f.lower().endswith(".inf"):
                continue
            p = os.path.join(root, f)
            try:
                text = open(p, errors="replace").read()
            except OSError:
                continue
            m = pat.search(text)
            if not m:
                continue
            try:
                u = str(uuid.UUID(m.group(1))).upper()
            except ValueError:
                continue
            base = re.search(r"BASE_NAME\s*=\s*(\S+)", text)
            out.setdefault(u, (base.group(1) if base else f[:-4], os.path.relpath(p, tree)))
    for g, macro in protocol_names(tree).items():
        entry = out.setdefault(g, (macro, "MdePkg/Include"))
        if entry[1] == "MdePkg/Include":
            out[g] = (macro, entry[1])
    return out


def sections(blob):
    """(type, size, payload) for the top-level section stream at `blob`."""
    o = 0
    while o + 4 <= len(blob):
        size = struct.unpack_from("<I", blob, o)[0] & 0xFFFFFF
        typ = blob[o + 3]
        if size < 4 or o + size > len(blob):
            break
        yield typ, size, blob[o + 4:o + size]
        o += (size + 3) & ~3


def depex_guids(payload):
    """The pushed GUIDs of a packed depex. `0x02` (`PUSH`) is the only opcode that carries a GUID:
    `0x00` BEFORE, `0x01` AFTER, `0x03` AND, `0x04` OR, `0x05` NOT, `0x06` TRUE, `0x07` FALSE,
    `0x08` END and `0x09` SOR take no argument, so treating any of them as a GUID marker
    desynchronises the stream and every later GUID comes out as noise."""
    out = []
    if len(payload) < 2 or payload[0] != 0x02:
        return out
    i = 1
    while i < len(payload):
        op = payload[i]
        i += 1
        if op == 0x00:
            break
        if op != 0x02:
            continue
        if i + 16 <= len(payload):
            out.append(str(uuid.UUID(bytes_le=payload[i:i + 16])).upper())
            i += 16
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("volumes", nargs="+", help="firmware volume, or boot image holding one")
    ap.add_argument("--tree", default=DEFAULT_TREE, help="Mu-Silicium tree the names come from")
    ap.add_argument("--all", action="store_true", help="scan every named GUID, not only PCI-named")
    ap.add_argument("--depex", action="store_true",
                    help="decode each volume's depex sections and report which scanned GUIDs appear")
    ap.add_argument("--json", help="write the census here as JSON as well as printing it")
    args = ap.parse_args()

    walker = load_walker()
    names = inf_and_pi_names(args.tree)
    if not names:
        sys.exit("no GUID definitions found under %s - wrong --tree?" % args.tree)

    def name_of(g):
        n = names.get(g)
        return n[0] if n else "?"

    volumes = []
    for path in args.volumes:
        d = read_volume(path)
        volumes.append((path, d))
        print("=== %s  %d B  sha256=%s" % (path, len(d), hashlib.sha256(d).hexdigest()[:16]))
    print("    names from %s: %d distinct GUIDs"
          % (os.path.relpath(args.tree, ROOT), len(names)))

    if args.all:
        want = sorted(names)
        label = "every named GUID"
    else:
        want = sorted(g for g, (n, src) in names.items()
                      if "PCI" in g.upper() or "PCI" in n.upper() or "pci" in n.lower()
                      or "pci" in src.lower())
        label = "every PCI-named GUID"
    print("\n-- %s the tree defines: %d rows --" % (label, len(want)))
    print("%-52s %s  %s" % ("GUID", "  ".join("%-11s" % os.path.basename(p) for p, _ in volumes),
                            "name"))

    counts, nonzero = {}, []
    for g in want:
        b = uuid.UUID(g).bytes_le
        counts[g] = [d.count(b) for _, d in volumes]
        if any(counts[g]):
            nonzero.append(g)
        print("%-52s %s  %s" % (g, "  ".join("%-11d" % c for c in counts[g]), name_of(g)))
    print("\n  %d of %d rows nonzero: %s" % (
        len(nonzero), len(want),
        ", ".join("%s %s" % (name_of(g), counts[g]) for g in nonzero) or "none"))

    result = {"volumes": {p: hashlib.sha256(d).hexdigest() for p, d in volumes},
              "counts": {g: counts[g] for g in want}, "nonzero": nonzero}

    if args.depex:
        for path, d in volumes:
            files = walker.walk_volume(d)
            print("\n=== %s: %d files, depex sections decoded" % (path, len(files)))
            in_depex, files_with, true_depex = {}, 0, 0
            for off, g, typ, size in files:
                for styp, _ssz, spay in sections(d[off + 24:off + size]):
                    if styp not in DEPEX_TYPES:
                        continue
                    files_with += 1
                    terms = depex_guids(spay)
                    if not terms:
                        true_depex += 1
                    for t in terms:
                        in_depex.setdefault(t, []).append(name_of(g))
            print("  %d depex section(s), %d of them the single TRUE byte" % (files_with, true_depex))
            hit = [g for g in want if g in in_depex]
            print("  of the %d scanned GUIDs, %d appear in a depex:%s"
                  % (len(want), len(hit), "" if hit else "  (none - nothing in this volume waits "
                     "on any of them)"))
            for g in hit:
                print("    %-52s waited on by %s" % (g, ", ".join(sorted(set(in_depex[g])))))
            result.setdefault("depex", {})[path] = {
                "depex_sections": files_with, "true_depex": true_depex,
                "scanned_in_depex": {g: sorted(set(in_depex[g])) for g in hit}}

    if args.json:
        json.dump(result, open(args.json, "w"), indent=1)
        print("\nwrote %s" % args.json)


if __name__ == "__main__":
    main()
