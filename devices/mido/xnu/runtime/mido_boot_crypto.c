#include <kern/debug.h>
#include <kern/startup.h>
#include <libkern/crypto/register_crypto.h>
#include <libkern/section_keywords.h>
#include "mido_digest.h"
#include "mido_hmac.h"
#include "mido_aes_cbc.h"
#include "mido_aes_ctr.h"
#include "mido_aes_xts.h"
#include "mido_aes_gcm.h"
#include "mido_ccrng.h"
#include "mido_kmem_random.h"
#include "mido_prng_bridge.h"

#if !defined(ARM64_BOARD_CONFIG_MIDO) || !defined(MIDO_BOOT_CRYPTO_DIAGNOSTIC)
#error MIDO boot crypto requires explicit diagnostic-only opt-in
#endif

_Static_assert(sizeof(void *) == 8, "MIDO requires ARM64");
_Static_assert(sizeof(struct crypto_functions) == 56 * sizeof(void *), "XNU crypto table changed");
_Static_assert(offsetof(struct crypto_functions, random_kmem_ctx_size_fn) == 0x150,
               "XNU kmem crypto callback offset changed");

#define UNAVAILABLE(result, name, parameters) \
    static __attribute__((noreturn)) result name parameters { panic("MIDO diagnostic crypto: unsupported " #name); }

UNAVAILABLE(int, ecb_init, (const struct ccmode_ecb *mode __unused,
    ccecb_ctx *context __unused, size_t length __unused, const void *key __unused))
UNAVAILABLE(int, ecb_update, (const ccecb_ctx *context __unused,
    size_t blocks __unused, const void *input __unused, void *output __unused))
UNAVAILABLE(void, ecb_roundkey, (const ccecb_ctx *context __unused,
    unsigned round __unused, void *key __unused))
UNAVAILABLE(int, des_init, (const struct ccmode_cbc *mode __unused,
    cccbc_ctx *context __unused, size_t length __unused, const void *key __unused))
UNAVAILABLE(int, des_update, (const cccbc_ctx *context __unused, cccbc_iv *iv __unused,
    size_t blocks __unused, const void *input __unused, void *output __unused))
UNAVAILABLE(int, des_weak_key, (void *key __unused, unsigned long length __unused))
UNAVAILABLE(void, des_parity, (void *key __unused, unsigned long length __unused))
UNAVAILABLE(size_t, cts3, (const struct ccmode_cbc *mode __unused,
    cccbc_ctx *context __unused, cccbc_iv *iv __unused, size_t length __unused,
    const void *input __unused, void *output __unused))
UNAVAILABLE(int, rsa_make, (ccrsa_pub_ctx_t context __unused,
    size_t exponent_length __unused, const uint8_t *exponent __unused,
    size_t modulus_length __unused, const uint8_t *modulus __unused))
UNAVAILABLE(int, rsa_verify, (ccrsa_pub_ctx_t context __unused, const uint8_t *oid __unused,
    size_t digest_length __unused, const uint8_t *digest __unused,
    size_t signature_length __unused, const uint8_t *signature __unused, bool *valid __unused))

UNAVAILABLE(const struct ccchacha20poly1305_info *, chacha_info, (void))
UNAVAILABLE(int, chacha_init, (const struct ccchacha20poly1305_info *info __unused,
    ccchacha20poly1305_ctx *context __unused, const uint8_t *key __unused))
UNAVAILABLE(int, chacha_reset, (const struct ccchacha20poly1305_info *info __unused,
    ccchacha20poly1305_ctx *context __unused))
UNAVAILABLE(int, chacha_setnonce, (const struct ccchacha20poly1305_info *info __unused,
    ccchacha20poly1305_ctx *context __unused, const uint8_t *nonce __unused))
UNAVAILABLE(int, chacha_incnonce, (const struct ccchacha20poly1305_info *info __unused,
    ccchacha20poly1305_ctx *context __unused, uint8_t *nonce __unused))
UNAVAILABLE(int, chacha_aad, (const struct ccchacha20poly1305_info *info __unused,
    ccchacha20poly1305_ctx *context __unused, size_t length __unused, const void *input __unused))
UNAVAILABLE(int, chacha_crypt, (const struct ccchacha20poly1305_info *info __unused,
    ccchacha20poly1305_ctx *context __unused, size_t length __unused,
    const void *input __unused, void *output __unused))
UNAVAILABLE(int, chacha_final, (const struct ccchacha20poly1305_info *info __unused,
    ccchacha20poly1305_ctx *context __unused, uint8_t *tag __unused))
UNAVAILABLE(int, chacha_verify, (const struct ccchacha20poly1305_info *info __unused,
    ccchacha20poly1305_ctx *context __unused, const uint8_t *tag __unused))

UNAVAILABLE(size_t, digest_size, (crypto_digest_alg_t algorithm __unused))
UNAVAILABLE(void, digest_init, (crypto_digest_alg_t algorithm __unused,
    void *context __unused, size_t context_size __unused))
UNAVAILABLE(void, digest_update, (crypto_digest_alg_t algorithm __unused,
    void *context __unused, size_t context_size __unused,
    const void *input __unused, size_t length __unused))
UNAVAILABLE(void, digest_final, (crypto_digest_alg_t algorithm __unused,
    void *context __unused, size_t context_size __unused,
    void *output __unused, size_t length __unused))
UNAVAILABLE(void, digest_once, (crypto_digest_alg_t algorithm __unused,
    const void *input __unused, size_t input_length __unused,
    void *output __unused, size_t output_length __unused))
UNAVAILABLE(void, hmac_init, (crypto_digest_alg_t algorithm __unused,
    void *context __unused, size_t context_size __unused,
    const void *key __unused, size_t key_length __unused))
UNAVAILABLE(void, hmac_generate, (crypto_digest_alg_t algorithm __unused,
    const void *key __unused, size_t key_length __unused,
    const void *input __unused, size_t input_length __unused,
    void *output __unused, size_t output_length __unused))
UNAVAILABLE(bool, hmac_verify, (crypto_digest_alg_t algorithm __unused,
    const void *key __unused, size_t key_length __unused,
    const void *input __unused, size_t input_length __unused,
    const void *tag __unused, size_t tag_length __unused))
UNAVAILABLE(bool, hmac_final_verify, (crypto_digest_alg_t algorithm __unused,
    void *context __unused, size_t context_size __unused,
    const void *tag __unused, size_t tag_length __unused))

static const struct ccmode_ecb unavailable_aes_ecb = {
    .size = 16, .block_size = 16, .init = ecb_init, .ecb = ecb_update, .roundkey = ecb_roundkey,
};
static const struct ccmode_ecb unavailable_des_ecb = {
    .size = 16, .block_size = 8, .init = ecb_init, .ecb = ecb_update, .roundkey = ecb_roundkey,
};
static const struct ccmode_cbc unavailable_des_cbc = {
    .size = 16, .block_size = 8, .init = des_init, .cbc = des_update,
};
static const struct ccchacha20poly1305_fns unavailable_chacha = {
    .info = chacha_info, .init = chacha_init, .reset = chacha_reset,
    .setnonce = chacha_setnonce, .incnonce = chacha_incnonce, .aad = chacha_aad,
    .encrypt = chacha_crypt, .decrypt = chacha_crypt,
    .finalize = chacha_final, .verify = chacha_verify,
};

static SECURITY_READ_ONLY_LATE(struct crypto_functions) boot_functions = {
    .ccdigest_init_fn = mido_digest_init,
    .ccdigest_update_fn = mido_digest_update,
    .ccdigest_final_fn = mido_digest_final_callback,
    .ccdigest_fn = mido_digest,
    .ccmd5_di = &mido_md5_info,
    .ccsha1_di = &mido_sha1_info,
    .ccsha256_di = &mido_sha256_info,
    .ccsha384_di = &mido_sha384_info,
    .ccsha512_di = &mido_sha512_info,
    .cchmac_init_fn = mido_hmac_init,
    .cchmac_update_fn = mido_hmac_update,
    .cchmac_final_fn = mido_hmac_final,
    .cchmac_fn = mido_hmac,
    .ccaes_ecb_encrypt = &unavailable_aes_ecb,
    .ccaes_ecb_decrypt = &unavailable_aes_ecb,
    .ccaes_cbc_encrypt = &mido_aes_cbc_encrypt,
    .ccaes_cbc_decrypt = &mido_aes_cbc_decrypt,
    .ccaes_ctr_crypt = &mido_aes_ctr_crypt,
    .ccaes_xts_encrypt = &mido_aes_xts_encrypt,
    .ccaes_xts_decrypt = &mido_aes_xts_decrypt,
    .ccaes_gcm_encrypt = &mido_aes_gcm_encrypt,
    .ccaes_gcm_decrypt = &mido_aes_gcm_decrypt,
    .ccgcm_init_with_iv_fn = mido_gcm_init_with_iv,
    .ccgcm_inc_iv_fn = mido_gcm_inc_iv,
    .ccchacha20poly1305_fns = &unavailable_chacha,
    .ccdes_ecb_encrypt = &unavailable_des_ecb,
    .ccdes_ecb_decrypt = &unavailable_des_ecb,
    .ccdes_cbc_encrypt = &unavailable_des_cbc,
    .ccdes_cbc_decrypt = &unavailable_des_cbc,
    .cctdes_ecb_encrypt = &unavailable_des_ecb,
    .cctdes_ecb_decrypt = &unavailable_des_ecb,
    .cctdes_cbc_encrypt = &unavailable_des_cbc,
    .cctdes_cbc_decrypt = &unavailable_des_cbc,
    .ccdes_key_is_weak_fn = des_weak_key,
    .ccdes_key_set_odd_parity_fn = des_parity,
    .ccpad_cts3_encrypt_fn = cts3,
    .ccpad_cts3_decrypt_fn = cts3,
    .ccrng_fn = mido_ccrng,
    .ccrsa_make_pub_fn = rsa_make,
    .ccrsa_verify_pkcs1v15_fn = rsa_verify,
    .random_generate_fn = mido_kmem_random_generate,
    .random_uniform_fn = mido_kmem_random_uniform,
    .random_kmem_ctx_size_fn = mido_kmem_random_size,
    .random_kmem_init_fn = mido_kmem_random_init,
    .digest_ctx_size_fn = digest_size,
    .digest_init_fn = digest_init,
    .digest_update_fn = digest_update,
    .digest_final_fn = digest_final,
    .digest_fn = digest_once,
    .hmac_ctx_size_fn = digest_size,
    .hmac_init_fn = hmac_init,
    .hmac_update_fn = digest_update,
    .hmac_final_generate_fn = digest_final,
    .hmac_final_verify_fn = hmac_final_verify,
    .hmac_generate_fn = hmac_generate,
    .hmac_verify_fn = hmac_verify,
};

static void mido_boot_crypto_startup(void)
{
    if (startup_phase < STARTUP_SUB_PERCPU || startup_phase >= STARTUP_SUB_EARLY_BOOT)
        panic("MIDO diagnostic crypto: unexpected startup phase");
    if (register_crypto_functions(&boot_functions) != 0)
        panic("MIDO diagnostic crypto: provider already registered");
    mido_kernel_prng_install_native();
    if (!mido_kernel_prng_is_ready())
        panic("MIDO diagnostic crypto: PRNG publication incomplete");
}

STARTUP(EARLY_BOOT, STARTUP_RANK_FIRST, mido_boot_crypto_startup);
