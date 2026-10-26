"""Opt-in MIDO startup gate for the already-disabled Image4 configuration."""

import hashlib


STARTUP_SHA256 = "5247178d4525c857e11f8ce960d5776c6ae136bb1307d97f97908440abcb5eff"
ANCHOR = b'#ifndef BCM2837\n\tkernel_bootstrap_log("trust_cache_init");'
REPLACEMENT = b'#if !defined(BCM2837) && !defined(ARM64_BOARD_CONFIG_MIDO)\n\tkernel_bootstrap_log("trust_cache_init");'


def stage_nonapple_boot(source):
    source = source.resolve()
    startup = source / "osfmk/kern/startup.c"
    configuration = source / "config/MASTER.arm64.MIDO"
    for path in (startup, configuration):
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped MIDO non-Apple startup input")
    before = startup.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(before).hexdigest() != STARTUP_SHA256:
        raise ValueError("unexpected original startup source for MIDO trust-cache gate")
    config = configuration.read_bytes()
    if b"config_img4" in config.lower():
        raise ValueError("refusing non-Apple startup gate when MIDO requests Image4")
    if before.count(ANCHOR) != 1:
        raise ValueError("unexpected upstream non-Apple trust-cache startup gate")
    after = before.replace(ANCHOR, REPLACEMENT)
    startup.write_bytes(after)
    return {"diagnostic_only": True, "image4_backend_available": False,
            "amfi_backend_available": False, "apple_trust_cache_boot_initialization": "not attempted",
            "trust_cache_api_implementations_modified": False, "code_signature_api_implementations_modified": False,
            "basis": "MIDO omits config_img4; upstream BCM2837 already omits this startup block",
            "startup_before_sha256": STARTUP_SHA256, "startup_sha256": hashlib.sha256(after).hexdigest(),
            "mido_configuration_sha256": hashlib.sha256(config).hexdigest(), "boot_approved": False}
