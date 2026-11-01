#!/usr/bin/env python3
"""Extract the D21AP (iPhone 8 Plus) DeviceTree from an IPSW, read-only.

  python -I tools/extract_d21ap.py IPSW OUTDIR

Writes OUTDIR/DeviceTree.d21ap.im4p and OUTDIR/d21ap.adt (IM4P unwrapped,
LZFSE decoded by tools/lzfse.py). OUTDIR must not exist or must be empty. The
IPSW is untrusted input: only that one member is read, with a size cap.
"""
import os, shutil, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

MEMBER = 'Firmware/all_flash/DeviceTree.d21ap.im4p'
MAX = 4 * 1024 * 1024


def main(ipsw, outdir):
    if os.path.exists(outdir) and os.listdir(outdir):
        raise SystemExit('output directory not empty')
    os.makedirs(outdir, exist_ok=True)
    with zipfile.ZipFile(ipsw) as z:
        info = z.getinfo(MEMBER)
        if info.file_size > MAX:
            raise SystemExit('unexpected member size')
        im4p = os.path.join(outdir, 'DeviceTree.d21ap.im4p')
        with z.open(info) as s, open(im4p, 'xb') as d:
            shutil.copyfileobj(s, d)
    raw = adt.load(im4p)
    root, end = adt.parse(raw)
    assert end == len(raw), 'trailing data after ADT'
    with open(os.path.join(outdir, 'd21ap.adt'), 'xb') as f:
        f.write(raw)
    print(len(raw), 'bytes; compatible', root.prop('compatible'))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
