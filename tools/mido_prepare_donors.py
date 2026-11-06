import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


SAILFISH_COMMIT = "6f27e41ff249f2680540ebe8ee5ab982c5e641c9"
KERNEL_FILES = (
    "bsd/dev/sweet_gpu.c",
    "bsd/dev/sweet_gpu.h",
    "bsd/dev/sweet_gpu_shaders.h",
    "iokit/Kernel/arm/SweetGPU.cpp",
    "bsd/dev/sailfish_wlan.c",
    "iokit/Kernel/arm/SailfishWLAN.cpp",
)


def git_read(donor, *arguments):
    return subprocess.check_output(["git", "-C", str(donor), *arguments])


def apply_selected(directory, patch, paths):
    selected = [path for path in paths
                if ("+++ b/" + path + "\n").encode() in patch]
    if not selected:
        return False
    subprocess.run(["git", "apply", "--whitespace=nowarn",
                    *["--include=" + path for path in selected], "-"],
                   cwd=directory, input=patch, check=True, capture_output=True)
    return True


def adapt_gpu_frontend(source):
    replacements = {
        "ARM64_BOARD_CONFIG_SWEET": "MIDO",
        "SweetSurface": "MidoSurface",
        "sweet_surface_": "mido_surface_",
    }
    for original, replacement in replacements.items():
        if original not in source:
            raise ValueError("donor frontend changed: " + original)
        source = source.replace(original, replacement)
    return "#include <pexpert/arm64/board_config.h>\n" + source


def adapt_wifi_frontend(source):
    replacements = {
        "ARM64_BOARD_CONFIG_SWEET": "MIDO",
        "SailfishWLAN": "MidoWLAN",
        "sailfish_wlan_": "mido_wlan_",
        "sailfishwlan": "midowlan",
    }
    for original, replacement in replacements.items():
        if original not in source:
            raise ValueError("donor WLAN frontend changed: " + original)
        source = source.replace(original, replacement)
    return "#include <pexpert/arm64/board_config.h>\n" + source


def prepare(donor, output):
    donor = donor.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError("output must not exist; refusing to overwrite analysis")
    listing = git_read(donor, "ls-tree", "-r", "--name-only",
                       SAILFISH_COMMIT).decode().splitlines()
    patches = sorted(path for path in listing
                     if path.startswith("xnu/patches/") and path.endswith(".patch"))
    bridge_paths = [path for path in listing
                    if path.startswith("tools/sweetgl/")
                    or path == "xnu/patches/0175-stage-ionetworking.sh"]
    applied = []
    with tempfile.TemporaryDirectory(prefix="mido-donor-") as directory:
        staging = Path(directory)
        for patch_path in patches:
            patch = git_read(donor, "show", SAILFISH_COMMIT + ":" + patch_path)
            if apply_selected(staging, patch, KERNEL_FILES):
                applied.append({"path": patch_path,
                                "sha256": hashlib.sha256(patch).hexdigest()})
        for path in KERNEL_FILES:
            if not (staging / path).is_file():
                raise ValueError("missing reconstructed donor file: " + path)
        for path in bridge_paths:
            target = staging / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git_read(donor, "show", SAILFISH_COMMIT + ":" + path))
        frontend = staging / "adapted/iokit/Kernel/arm/MidoGPU.cpp"
        frontend.parent.mkdir(parents=True)
        frontend.write_text(adapt_gpu_frontend(
            (staging / "iokit/Kernel/arm/SweetGPU.cpp").read_text()), encoding="utf-8")
        wlan_frontend = frontend.parent / "MidoWLAN.cpp"
        wlan_frontend.write_text(adapt_wifi_frontend(
            (staging / "iokit/Kernel/arm/SailfishWLAN.cpp").read_text()), encoding="utf-8")
        files = {}
        for target in sorted(staging.rglob("*")):
            if target.is_file():
                files[target.relative_to(staging).as_posix()] = {
                    "bytes": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
        manifest = {"donor_commit": SAILFISH_COMMIT,
                    "purpose": "offline adaptation only; not a mido driver",
                    "patches_applied": applied, "files": files,
                    "hardware_accessed": False, "kernel_integrated": False,
                    "compiled": False, "gpu_acceleration": False,
                    "wifi_network": False}
        output.mkdir(parents=True)
        for relative in files:
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((staging / relative).read_bytes())
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Reconstruct pinned Sailfish GPU/WLAN donors offline; no build or device access")
    parser.add_argument("donor", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    manifest = prepare(arguments.donor, arguments.output)
    print(json.dumps({"commit": manifest["donor_commit"],
                      "patches": len(manifest["patches_applied"]),
                      "files": len(manifest["files"]),
                      "output": str(arguments.output),
                      "kernel_integrated": False}, indent=2))


if __name__ == "__main__":
    main()
