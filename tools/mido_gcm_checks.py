"""Independent checks of isolated ARM64 GCM callbacks, not an XNU boot."""


def run(create, call, check, base):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    context, source, output = base, base + 1024, base + 3072
    tag, aad, iv_pointer, key_pointer = base + 6000, base + 6144, base + 7008, base + 7040
    for key_length in (16, 24, 32):
        key = bytes(range(key_length))
        for iv_length in (8, 12, 16):
            iv = bytes(index + 32 for index in range(iv_length))
            for length in (0, 1, 15, 16, 17, 31, 32, 129, 1024):
                plain = bytes((index * 37 + length) % 256 for index in range(length))
                additional = bytes(range(length % 131))
                reference = Cipher(algorithms.AES(key), modes.GCM(iv)).encryptor()
                reference.authenticate_additional_data(additional)
                encrypted = reference.update(plain) + reference.finalize()
                expected_tag = reference.tag
                for decrypt in (0, 1):
                    for inplace in (0, 1):
                        cpu, events = create()
                        cpu.mem_write(key_pointer, key)
                        cpu.mem_write(iv_pointer, iv)
                        cpu.mem_write(aad, additional or b"\0")
                        cpu.mem_write(source, (encrypted if decrypt else plain) or b"\0")
                        cpu.mem_write(tag, expected_tag if decrypt else bytes(16))
                        destination = source if inplace else output
                        cpu.mem_write(destination + length, b"guard")
                        check("gcm-init", call(cpu, events, "mido_gcm_test_init", (decrypt, context, key_length, key_pointer)) == 0)
                        check("gcm-iv", call(cpu, events, "mido_gcm_test_iv", (context, iv_length, iv_pointer)) == 0)
                        first = min(len(additional), 1)
                        for start, count in ((0, first), (first, len(additional) - first)):
                            check("gcm-stream-aad", call(cpu, events, "mido_gcm_test_aad", (context, count, aad + start)) == 0)
                        offset = 0
                        for count in (0, min(length, 1), min(max(length - 1, 0), 16), max(length - 17, 0)):
                            check("gcm-stream-data", call(cpu, events, "mido_gcm_test_update",
                                  (context, count, source + offset, destination + offset)) == 0)
                            offset += count
                        check(f"gcm-reference-{key_length}-{iv_length}-{length}-{decrypt}-{inplace}",
                              offset == length and call(cpu, events, "mido_gcm_test_final", (context, 16, tag)) == 0 and
                              bytes(cpu.mem_read(destination, length)) == (plain if decrypt else encrypted) and
                              bytes(cpu.mem_read(tag, 16)) == expected_tag and
                              bytes(cpu.mem_read(destination + length, 5)) == b"guard" and
                              bytes(cpu.mem_read(iv_pointer, iv_length)) == iv)

    cpu, events = create()
    cpu.mem_write(key_pointer, bytes(16))
    cpu.mem_write(iv_pointer, bytes(12))
    cpu.mem_write(source, bytes(16))
    call(cpu, events, "mido_gcm_test_init", (0, context, 16, key_pointer))
    call(cpu, events, "mido_gcm_test_iv", (context, 12, iv_pointer))
    call(cpu, events, "mido_gcm_test_update", (context, 16, source, output))
    check("gcm-nist-zero-vector", call(cpu, events, "mido_gcm_test_final", (context, 16, tag)) == 0 and
          bytes(cpu.mem_read(output, 16)).hex() == "0388dace60b6a392f328c2b971b2fe78" and
          bytes(cpu.mem_read(tag, 16)).hex() == "ab6e47d42cec13bdf53a67b21257bddf")

    def initialized(decrypt=0, managed=False, nonce=bytes(12)):
        cpu, events = create()
        cpu.mem_write(key_pointer, bytes(16))
        cpu.mem_write(iv_pointer, nonce)
        if managed:
            result = call(cpu, events, "mido_gcm_test_init_managed", (decrypt, context, 16, key_pointer, iv_pointer))
        else:
            result = call(cpu, events, "mido_gcm_test_init", (decrypt, context, 16, key_pointer))
            if result == 0:
                result = call(cpu, events, "mido_gcm_test_iv", (context, len(nonce), iv_pointer))
        check("gcm-case-init", result == 0)
        return cpu, events

    reference = Cipher(algorithms.AES(bytes(16)), modes.GCM(bytes(12))).encryptor()
    encrypted = reference.update(bytes(31)) + reference.finalize()
    for tag_length in (4, 8, 12, 13, 14, 15, 16):
        for bad_tag in (False, True):
            cpu, events = initialized(1)
            cpu.mem_write(source, encrypted)
            provided = bytearray(reference.tag[:tag_length])
            if bad_tag:
                provided[-1] ^= 1
            cpu.mem_write(tag, bytes(provided))
            call(cpu, events, "mido_gcm_test_update", (context, 31, source, output))
            result = call(cpu, events, "mido_gcm_test_final", (context, tag_length, tag))
            check(f"gcm-authenticate-truncated-{tag_length}-{bad_tag}",
                  (result != 0) == bad_tag and bytes(cpu.mem_read(tag, tag_length)) == reference.tag[:tag_length])
            before = bytes(cpu.mem_read(base, 8192))
            check("gcm-cannot-finalize-twice", call(cpu, events, "mido_gcm_test_final", (context, tag_length, tag)) != 0 and
                  bytes(cpu.mem_read(base, 8192)) == before)

    for name, function, arguments in (
        ("null-context", "mido_gcm_test_update", (0, 1, source, output)),
        ("misaligned-context", "mido_gcm_test_update", (context + 1, 1, source, output)),
        ("null-input", "mido_gcm_test_update", (context, 1, 0, output)),
        ("null-output", "mido_gcm_test_update", (context, 1, source, 0)),
        ("partial-overlap", "mido_gcm_test_update", (context, 16, source, source + 1)),
        ("context-input", "mido_gcm_test_update", (context, 1, context, output)),
        ("context-output", "mido_gcm_test_update", (context, 1, source, context)),
        ("wrapped-input", "mido_gcm_test_update", (context, 16, (1 << 64) - 8, output)),
        ("wrapped-output", "mido_gcm_test_update", (context, 16, source, (1 << 64) - 8)),
        ("payload-limit", "mido_gcm_test_update", (context, (1 << 36) - 31, source, output)),
        ("aad-limit", "mido_gcm_test_aad", (context, 1 << 61, aad)),
        ("aad-context", "mido_gcm_test_aad", (context, 1, context)),
        ("iv-set-twice", "mido_gcm_test_iv", (context, 12, iv_pointer)),
        ("iv-inc-unmanaged", "mido_gcm_test_inc", (0, context, iv_pointer)),
        ("tag-context", "mido_gcm_test_final", (context, 16, context)),
        ("null-tag", "mido_gcm_test_final", (context, 16, 0)),
    ):
        cpu, events = initialized()
        before = bytes(cpu.mem_read(base, 8192))
        check("gcm-reject-" + name, call(cpu, events, function, arguments) != 0 and bytes(cpu.mem_read(base, 8192)) == before)
    for length in (0, 1, 2, 3, 5, 7, 9, 11, 17):
        cpu, events = initialized()
        before = bytes(cpu.mem_read(base, 8192))
        check("gcm-reject-invalid-tag-length", call(cpu, events, "mido_gcm_test_final", (context, length, tag)) != 0 and
              bytes(cpu.mem_read(base, 8192)) == before)
    cpu, events = initialized()
    call(cpu, events, "mido_gcm_test_update", (context, 0, 0, 0))
    check("gcm-reject-aad-after-data", call(cpu, events, "mido_gcm_test_aad", (context, 0, 0)) != 0)
    call(cpu, events, "mido_gcm_test_reset", (context,))
    check("gcm-reject-data-before-iv", call(cpu, events, "mido_gcm_test_update", (context, 0, 0, 0)) != 0)
    for length, pointer in ((0, iv_pointer), (12, 0), (12, context), (1 << 61, iv_pointer)):
        before = bytes(cpu.mem_read(base, 8192))
        check("gcm-reject-invalid-iv", call(cpu, events, "mido_gcm_test_iv", (context, length, pointer)) != 0 and
              bytes(cpu.mem_read(base, 8192)) == before)

    for decrypt in (0, 1):
        cpu, events = initialized(decrypt, managed=True, nonce=bytes.fromhex("1122334400000000000000fe"))
        check("gcm-managed-reject-manual-iv", call(cpu, events, "mido_gcm_test_iv", (context, 12, iv_pointer)) != 0)
        check("gcm-managed-require-reset", call(cpu, events, "mido_gcm_test_inc", (decrypt, context, iv_pointer)) != 0)
        call(cpu, events, "mido_gcm_test_reset", (context,))
        before = bytes(cpu.mem_read(base, 8192))
        check("gcm-managed-reject-wrong-mode", call(cpu, events, "mido_gcm_test_inc", (1 - decrypt, context, iv_pointer)) != 0 and
              bytes(cpu.mem_read(base, 8192)) == before)
        check("gcm-managed-increment", call(cpu, events, "mido_gcm_test_inc", (decrypt, context, iv_pointer)) == 0 and
              bytes(cpu.mem_read(iv_pointer, 12)).hex() == "1122334400000000000000ff")
        call(cpu, events, "mido_gcm_test_reset", (context,))
        check("gcm-managed-carry", call(cpu, events, "mido_gcm_test_inc", (decrypt, context, iv_pointer)) == 0 and
              bytes(cpu.mem_read(iv_pointer, 12)).hex() == "112233440000000000000100")
        cpu, events = initialized(decrypt, managed=True, nonce=bytes.fromhex("11223344ffffffffffffffff"))
        call(cpu, events, "mido_gcm_test_reset", (context,))
        before = bytes(cpu.mem_read(base, 8192))
        check("gcm-managed-refuse-wrap", call(cpu, events, "mido_gcm_test_inc", (decrypt, context, iv_pointer)) != 0 and
              bytes(cpu.mem_read(base, 8192)) == before)
