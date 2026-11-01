"""Read the MIDO persistent console log (kernel patch 0100) from a phone in TWRP (adb root).

    python -I tools/mido-log-pull.py OUT.txt [--adb PATH] [--device /dev/block/...]

Reads only: the last 8193 sectors (header + 4 MiB ring) of the userdata partition.
"""
import argparse
import struct
import subprocess
import sys

SECTOR = 512
RING = 4 << 20
SECTORS = 1 + RING // SECTOR


def adb(path, *args, binary=False):
    r = subprocess.run([path, *args], capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode('utf-8', 'replace')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--adb', default=r'C:\platform-tools\adb.exe')
    ap.add_argument('--device', default='')
    a = ap.parse_args()
    dev = a.device or adb(a.adb, 'shell',
                          'for d in /dev/block/by-name/userdata /dev/block/bootdevice/by-name/userdata; '
                          'do [ -e $d ] && readlink -f $d && break; done').strip()
    if not dev:
        sys.exit('userdata block device not found (is the phone in TWRP with adb?)')
    size = int(adb(a.adb, 'shell', f'blockdev --getsize64 {dev}').strip())
    skip = size // SECTOR - SECTORS
    data = adb(a.adb, 'exec-out', f'dd if={dev} bs={SECTOR} skip={skip} count={SECTORS} 2>/dev/null', binary=True)
    print(f'{dev}: {size} bytes, read {len(data)} bytes from sector {skip}', file=sys.stderr)
    magic, version, ring, total, seq = struct.unpack_from('<8sIIQQ', data, 0)
    if magic != b'MIDOLOG\0':
        sys.exit('no MIDOLOG header (log never flushed, or wrong area)')
    body = data[SECTOR:SECTOR + ring]
    if total <= ring:
        text = body[:total]
    else:
        start = total % ring
        text = body[start:] + body[:start]
    open(a.out, 'w', encoding='utf-8', newline='').write(text.decode('utf-8', 'replace').replace('\r', ''))
    print(f'# version {version}, ring {ring}, total {total} bytes, flush #{seq}'
          f'{" (wrapped)" if total > ring else ""} -> {a.out}', file=sys.stderr)


main()
