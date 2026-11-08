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
        for later in ("0108-mido-scanout-cost-and-input-diagnostics.patch",
                      "0109-mido-touch-rpm-rails.patch",
                      "0110-mido-touch-block-read-backlight-packed-scanout.patch",
                      "0111-mido-wled-module-off-and-touch-report-evidence.patch",
                      "0112-mido-ft5435-observed-header-and-fifo-guard.patch",
                      "0115-mido-serialized-gpu-cx-vote.patch",
                      "0117-mido-rpm-kvp-ack-format.patch",
                      "0118-mido-gfx-bhs-preparation.patch",
                      "0121-mido-cx-domain-and-wcnss-discovery.patch",
                      "0123-mido-cx-writable-readback.patch",
                      "0124-mido-gx-xo-power-and-scm-info.patch",
                      "0125-mido-gpu-branches-and-pas-support.patch",
                      "0126-mido-temporary-mmio-map-lifetime.patch",
                      "0127-mido-cbcr-noc-fsm-status.patch",
                      "0128-mido-donor-backend-bridges.patch",
                      "0129-mido-gpu-core-retention.patch",
                      "0130-mido-shared-cx-and-pronto-supply-votes.patch",
                      "0131-mido-secure-restore-and-pronto-loader.patch",
                      "0132-mido-pronto-private-bundle-and-memory-adapter.patch",
                      "0134-mido-recoverable-gpu-mmio-scan.patch"):
            if later <= base:
                continue
            subprocess.run(["git", "apply", "--include=" + relative,
                            str(root / "xnu/patches" / later)],
                           cwd=directory, check=True, capture_output=True)
        return target.read_text()
