/*
 * Adreno 530 kernel API (bsd/dev/sweet_gpu.c), used by the SweetGPU user
 * client (iokit/Kernel/arm/SweetGPU.cpp). The struct is also the user
 * client's quad argument, so its layout is ABI.
 */
#ifndef _SWEET_GPU_H
#define _SWEET_GPU_H

#include <sys/cdefs.h>
#include <stdint.h>
#include <stdbool.h>

__BEGIN_DECLS

/*
 * Textured quad: for each pixel (X, Y) of the dst rect (x0, y0, w, h) on
 * the inner side of the nedges edges (a (X+.5) + b (Y+.5) + c >= 0),
 * (u, v) = (m[0] m[2]; m[1] m[3]) (X + .5, Y + .5) + (m[4], m[5]) in src
 * texels (unnormalized), s = bilinear (flags bit 0: nearest) sample of src,
 * clamped to its edge, channels picked by src_swiz, times color (per
 * channel); dst = s + dst * (1 - s.a) (source-over; flags SWEET_GPU_QUAD_ADD:
 * min(s + dst, 1), SWEET_GPU_QUAD_COPY: s). dst is 4 bytes per pixel,
 * premultiplied, alpha in byte 3 (BGRA8 or RGBA8); src is src_fmt. Images at
 * GPU VAs from sweet_gpu_vm_map (64-byte aligned); pitches in bytes, multiples
 * of 64 (the texture unit rounds a pitch up to 64: with any other pitch it
 * reads past the image, faults and hangs, 0140a). dst must be in a writable
 * mapping.
 */
struct sweet_gpu_quad {
	uint64_t src_va, dst_va;
	uint32_t src_w, src_h, src_pitch;
	uint32_t dst_w, dst_h, dst_pitch;
	uint32_t x0, y0, w, h;
	uint32_t m[6];          /* float bits: a, b, c, d, tx, ty */
	uint32_t reserved;      /* 0 (was opacity: use color) */
	uint32_t flags;
	uint32_t color[4];      /* float bits, per channel in memory order */
	uint32_t src_fmt;       /* SWEET_GPU_FMT_* */
	uint32_t src_swiz;      /* 4 x 3 bits, channel x first: 0-3 texel x y z w, 4 = 0, 5 = 1 (0x688 = xyzw) */
	uint32_t nedges;        /* 0-4 */
	uint32_t edge[4][3];    /* float bits a, b, c */
};

#define SWEET_GPU_FMT_RGBA8     0u      /* 4 bytes per pixel */
#define SWEET_GPU_FMT_R8        1u      /* 1 byte */
#define SWEET_GPU_FMT_RG8       2u      /* 2 bytes */

#define SWEET_GPU_QUAD_NEAREST  1u
#define SWEET_GPU_QUAD_ADD      2u
#define SWEET_GPU_QUAD_COPY     4u

/* True once the GPU is up (sweetgpu=8) and accepts work. */
bool sweet_gpu_ready(void);

/*
 * Map npages pages (PAGE_SIZE each) at a new GPU VA; 0 on failure. A
 * read-only mapping can only be a quad source (SMMU entries read-only).
 */
uint64_t sweet_gpu_vm_map(const uint64_t *pa, uint32_t npages, bool readonly);

/* Unmap a VA returned by sweet_gpu_vm_map. */
void sweet_gpu_vm_unmap(uint64_t va);

/*
 * Run one quad and wait for it; 0 on success, else an errno value. After a
 * timeout (GPU hung) the service is off until reboot: ENXIO from then on.
 */
int sweet_gpu_quad(const struct sweet_gpu_quad *q);

/*
 * Command submission for user-space drivers (Mesa freedreno through the
 * SweetGPU user client). Each IB is a CP_INDIRECT_BUFFER_PFE of dwords
 * dwords at a GPU VA inside a mapping; after them the ring writes the
 * submit's sequence number to the fence page (CACHE_FLUSH_TS). Returns 0
 * and the sequence number, ENXIO (GPU off), EINVAL, EFAULT (IB outside the
 * mapped window) or ETIMEDOUT (ring full for 500 ms: hung, service off).
 */
struct sweet_gpu_ib {
	uint64_t iova;
	uint32_t dwords;
	uint32_t pad;
};
#define SWEET_GPU_MAX_IBS       256u

int sweet_gpu_submit(const struct sweet_gpu_ib *ib, uint32_t n, uint32_t *seqno);

/*
 * Wait until submit seqno has completed: 0, ETIMEDOUT after timeout_ms, or
 * ENXIO (GPU off; also when the fence has not moved for 2 s with work
 * outstanding: the GPU is declared hung and the service goes off).
 */
int sweet_gpu_wait(uint32_t seqno, uint32_t timeout_ms);

struct sweet_gpu_info {
	uint32_t chip_id;               /* core << 24 | major << 16 | minor << 8 | patch */
	uint32_t gmem_size;
	uint64_t gmem_base;
	uint64_t max_freq;              /* Hz */
	uint64_t fence_pa;              /* page: u32 last completed seqno at +0 */
};

void sweet_gpu_get_info(struct sweet_gpu_info *info);

/* The fence page (SweetGPU allocates it so that it can map it into clients). */
void sweet_gpu_set_fence_page(uintptr_t kva, uint64_t pa);

__END_DECLS

#endif /* _SWEET_GPU_H */
