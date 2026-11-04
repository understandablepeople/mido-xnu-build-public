import subprocess
import tempfile
from pathlib import Path


def kernel_source(root, name, base):
    relative = "iokit/Kernel/arm/" + name
    patch = (root / "xnu/patches" / base).read_text()
    section = patch.split("+++ b/" + relative + chr(10), 1)[1]
    section = section.split(chr(10) + "--- ", 1)[0]
    text = chr(10).join(line[1:] for line in section.splitlines()
                        if line.startswith("+")) + chr(10)
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / relative
        target.parent.mkdir(parents=True)
        target.write_text(text)
        subprocess.run(["git", "apply", "--include=" + relative,
                        str(root / "xnu/patches/0108-mido-scanout-cost-and-input-diagnostics.patch")],
                       cwd=directory, check=True, capture_output=True)
        return target.read_text()
