"""Fail closed for a boolean entitlement query when AMFI is not registered."""

import hashlib


SOURCE_SHA256 = "e35916c887ad13109b8a40b6cddb2d3381407e945a2ad587585beb64dcfebd27"
ANCHOR = (b"IOTaskHasEntitlement(task_t task, const char *entitlement)\n{\n"
          b"\tif (task == NULL) {\n")
GUARD = (b"#if defined(ARM64_BOARD_CONFIG_MIDO) && defined(MIDO_DIAGNOSTIC_ENTITLEMENT_GUARD)\n"
         b"\tif (amfi == NULL) {\n\t\treturn false;\n\t}\n#endif\n\n")


def stage_entitlement_guard(source):
    source = source.resolve()
    unit = "iokit/bsddev/IOKitBSDInit.cpp"
    makefile = "iokit/conf/Makefile.arm64"
    configuration = "config/MASTER.arm64.MIDO"
    before = {}
    for relative in (unit, makefile, configuration):
        path = source / relative
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped MIDO entitlement staging path")
        before[relative] = path.read_bytes().replace(b"\r\n", b"\n")
    if b"pseudo-device mido_runtime" not in before[configuration].splitlines():
        raise ValueError("entitlement guard requires MIDO runtime configuration")
    if hashlib.sha256(before[unit]).hexdigest() != SOURCE_SHA256 or before[unit].count(ANCHOR) != 1:
        raise ValueError("unexpected original IOKit boolean entitlement query")
    if b"MIDO_DIAGNOSTIC_ENTITLEMENT_GUARD" in before[makefile]:
        raise ValueError("entitlement guard already staged")
    guarded = ANCHOR.replace(b"{\n\tif", b"{\n" + GUARD + b"\tif", 1)
    after = {unit: before[unit].replace(ANCHOR, guarded),
             makefile: before[makefile] + b"\nIOKitBSDInit.cpo_CFLAGS_ADD += -DMIDO_DIAGNOSTIC_ENTITLEMENT_GUARD=1\n"}
    records = {}
    for relative, data in after.items():
        (source / relative).write_bytes(data)
        records[relative] = dict(before_sha256=hashlib.sha256(before[relative]).hexdigest(),
                                 sha256=hashlib.sha256(data).hexdigest())
    return dict(files=records, diagnostic_only=True, missing_amfi_boolean_result=False,
                registered_provider_query_preserved=True, entitlements_granted=False,
                amfi_provider_implemented=False, signature_verification_bypassed=False, boot_approved=False)
