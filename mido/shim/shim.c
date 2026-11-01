/*
 * mido XNU shim: lk2nd-loaded RAM image that acts as "iBoot" for xnu.
 *
 * Entry (entry.S, hardware-validated by mido/m1): EL1, MMU + D-cache off,
 * x0 = DTB from lk2nd. This file adds, on top of the m1 24bpp console:
 *   1. find the SWEETXNU payload (tools/mkpayload.py): /chosen linux,initrd-*
 *      from the DTB, else the fixed boot-image ramdisk address 0x13600000;
 *   2. validate every header field and every destination range;
 *   3. copy segments to phys_base + (vmaddr - virt_base), place ADT + boot_args;
 *   4. jump to the kernel entry, MMU/caches off, x0 = boot_args (physical).
 * Every risky step is announced on the console BEFORE it runs, so a photo of a
 * hung phone shows where it stopped. Nothing here touches storage or the MMU.
 * 4 KiB pages everywhere (the Cortex-A53 has no 16K granule).
 */
#include <stdint.h>
#include <stddef.h>
#include "font.h"

/* ---- display: lk2nd continuous splash, 24bpp, memory byte order B,G,R [HW] ---- */
#define FB_BASE		0x90001000UL
#define FB_W		1080
#define FB_H		1920
#define FB_STRIDE	3240
#define SCALE		2
#define CH_W		(8 * SCALE)
#define CH_H		(16 * SCALE)
#define MARGIN		12
#define COLS		((FB_W - 2 * MARGIN) / CH_W)

/* ---- memory contract ---- */
#define RAM_FREE_LO		0x10000000UL	/* HARDWARE.md: 0x10000000..0x80000000 unreserved */
#define RAM_FREE_HI		0x80000000UL
#define RAMDISK_FALLBACK	0x13600000UL	/* ramdisk address in the boot image header */
#define PAGE			0x1000UL
#define L2_BLOCK		0x200000UL
#define MAX_SEGS		32
#define BOOT_LINE_LENGTH	608

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })

extern char _start[] __attribute__((visibility("hidden")));
extern char _image_end[] __attribute__((visibility("hidden")));

/* Compilers may still emit calls to these even with -fno-builtin; keep them local. */
void *memset(void *d, int v, size_t n)
{
	volatile unsigned char *t = d;
	for (size_t i = 0; i < n; i++)
		t[i] = (unsigned char)v;
	return d;
}

void *memcpy(void *d, const void *s, size_t n)
{
	volatile unsigned char *t = d;
	const volatile unsigned char *i = s;
	for (size_t k = 0; k < n; k++)
		t[k] = i[k];
	return d;
}

/* lk2nd's DTB must validate (root marker + simple-framebuffer) before we draw anything */
#include "fb_dtb.inc"

/* ---- console (state lives in .data: the linker script forbids .bss) ---- */
static volatile unsigned char *fb __attribute__((section(".data"))) = 0;
static unsigned int col __attribute__((section(".data"))) = 0;
static unsigned int row __attribute__((section(".data"))) = 0;
static unsigned int level __attribute__((section(".data"))) = 1;
static unsigned char fg[3] __attribute__((section(".data"))) = {255, 255, 255};
static unsigned char bg[3] __attribute__((section(".data"))) = {40, 24, 8};	/* B,G,R */

static void put_px(unsigned int x, unsigned int y, const unsigned char *c)
{
	volatile unsigned char *p = fb + (size_t)y * FB_STRIDE + x * 3;
	p[0] = c[0];
	p[1] = c[1];
	p[2] = c[2];
}

static void clear(void)
{
	for (unsigned int y = 0; y < FB_H; y++)
		for (unsigned int x = 0; x < FB_W; x++)
			put_px(x, y, bg);
	col = row = 0;
}

static void putc_(char ch)
{
	if (ch == '\n') {
		col = 0;
		row++;
		return;
	}
	if (ch < 0x20 || ch > 0x7e)
		ch = '?';
	if (col >= COLS) {
		col = 0;
		row++;
	}
	unsigned int x0 = MARGIN + col * CH_W, y0 = MARGIN + row * CH_H;
	if (y0 + CH_H > FB_H)
		return;
	const unsigned char *g = font8x16[ch - 0x20];
	for (unsigned int gy = 0; gy < 16; gy++)
		for (unsigned int gx = 0; gx < 8; gx++) {
			const unsigned char *c = (g[gy] & (0x80 >> gx)) ? fg : bg;
			for (unsigned int sy = 0; sy < SCALE; sy++)
				for (unsigned int sx = 0; sx < SCALE; sx++)
					put_px(x0 + gx * SCALE + sx, y0 + gy * SCALE + sy, c);
		}
	col++;
	__asm__ volatile("dsb sy" ::: "memory");
}

static void puts_(const char *s)
{
	while (*s)
		putc_(*s++);
}

static void hex(uint64_t v, int digits)
{
	static const char h[] = "0123456789ABCDEF";
	for (int i = digits - 1; i >= 0; i--)
		putc_(h[(v >> (4 * i)) & 15]);
}

static void line(const char *label, uint64_t v, int digits)
{
	puts_(label);
	hex(v, digits);
	putc_('\n');
}

static void line2(const char *l1, uint64_t v1, const char *l2, uint64_t v2)
{
	puts_(l1);
	hex(v1, 9);
	putc_(' ');
	puts_(l2);
	hex(v2, 9);
	putc_('\n');
}

static void fail(const char *why)
{
	bg[0] = 0;
	bg[1] = 0;
	bg[2] = 160;	/* red background; the text stays */
	puts_("\n*** FAIL: ");
	puts_(why);
	puts_("\nHALTED. Hold power to restart.\n");
	for (;;)
		__asm__ volatile("wfe");
}

__attribute__((visibility("hidden")))
void shim_exception(uint64_t slot)
{
	bg[0] = 0;
	bg[1] = 0;
	bg[2] = 160;
	puts_("\n*** EXCEPTION slot ");
	hex(slot, 2);
	putc_('\n');
	line("ESR ", level == 1 ? rsr("esr_el1") : rsr("esr_el2"), 16);
	line("ELR ", level == 1 ? rsr("elr_el1") : rsr("elr_el2"), 16);
	line("FAR ", level == 1 ? rsr("far_el1") : rsr("far_el2"), 16);
	puts_("HALTED\n");
	for (;;)
		__asm__ volatile("wfe");
}

/* ---- memory helpers: MMU off means Device memory, so only aligned accesses ---- */
static void copy_mem(uintptr_t dst, uintptr_t src, uint64_t n)
{
	if (((dst | src) & 7) == 0) {
		volatile uint64_t *d = (volatile uint64_t *)dst;
		volatile const uint64_t *s = (volatile const uint64_t *)src;
		uint64_t words = n / 8, i = 0;
		for (; i + 2 <= words; i += 2) {
			uint64_t a = s[i], b = s[i + 1];
			d[i] = a;
			d[i + 1] = b;
		}
		for (; i < words; i++)
			d[i] = s[i];
		dst += words * 8;
		src += words * 8;
		n -= words * 8;
	}
	volatile unsigned char *d = (volatile unsigned char *)dst;
	volatile const unsigned char *s = (volatile const unsigned char *)src;
	for (uint64_t i = 0; i < n; i++)
		d[i] = s[i];
}

static void zero_mem(uintptr_t dst, uint64_t n)
{
	if ((dst & 7) == 0) {
		volatile uint64_t *d = (volatile uint64_t *)dst;
		for (uint64_t i = 0; i < n / 8; i++)
			d[i] = 0;
		dst += n & ~7ULL;
		n &= 7;
	}
	volatile unsigned char *d = (volatile unsigned char *)dst;
	for (uint64_t i = 0; i < n; i++)
		d[i] = 0;
}

/* ---- DTB: bounded walk to /chosen linux,initrd-start / -end ---- */
static uint32_t be32(uintptr_t a)
{
	return __builtin_bswap32(*(volatile uint32_t *)a);
}

static int same(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

static int dtb_ok(uintptr_t d)
{
	if (d < RAM_FREE_LO || d > 0x849f0000UL || (d & 7))
		return 0;
	if (be32(d) != 0xd00dfeed)
		return 0;
	uint32_t total = be32(d + 4), st = be32(d + 8), sts = be32(d + 12);
	return total >= 56 && total <= 0x100000 && st >= 40 && !(st & 3) && st <= total
	    && be32(d + 36) <= total - st && sts <= total && be32(d + 32) <= total - sts;
}

/* Returns 1 and sets *out when the property exists in /chosen with length 4 or 8. */
static int chosen_u64(uintptr_t d, const char *prop, uint64_t *out)
{
	uintptr_t p = d + be32(d + 8), end = p + be32(d + 36);
	uintptr_t strings = d + be32(d + 12), sends = strings + be32(d + 32);
	int depth = 0, in_chosen = 0;

	while (p + 4 <= end) {
		uint32_t tok = be32(p);
		p += 4;
		if (tok == 1) {			/* BEGIN_NODE */
			const char *n = (const char *)p;
			uintptr_t q = p;
			while (q < end && *(volatile char *)q)
				q++;
			if (q >= end)
				return 0;
			depth++;
			in_chosen = depth == 2 && same(n, "chosen");
			p = (q + 1 + 3) & ~3UL;
		} else if (tok == 2) {		/* END_NODE */
			if (in_chosen)
				return 0;
			if (--depth < 0)
				return 0;
		} else if (tok == 3) {		/* PROP */
			if (p + 8 > end)
				return 0;
			uint32_t len = be32(p), off = be32(p + 4);
			uintptr_t val = p + 8, name = strings + off;
			if (len > end - val || name >= sends)
				return 0;
			if (in_chosen && same((const char *)name, prop)) {
				if (len == 4)
					*out = be32(val);
				else if (len == 8)
					*out = (uint64_t)be32(val) << 32 | be32(val + 4);
				else
					return 0;
				return 1;
			}
			p = (val + len + 3) & ~3UL;
		} else if (tok != 4) {		/* not NOP: END or garbage */
			return 0;
		}
	}
	return 0;
}

/* ---- payload (tools/mkpayload.py layout) and boot_args (pexpert/arm64/boot.h rev 2) ---- */
struct payload_seg {
	uint64_t vmaddr, vmsize, file_off, file_size;
};

struct payload {
	char magic[8];
	uint32_t version, nsegs;
	uint64_t virt_base, entry_va, adt_off, adt_size, kernel_end;
	uint64_t phys_base, mem_size;
	char cmdline[BOOT_LINE_LENGTH];
	struct payload_seg segs[];
};

struct boot_video {
	uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth;
};

struct boot_args {
	uint16_t Revision, Version;
	uint64_t virtBase, physBase, memSize, topOfKernelData;
	struct boot_video Video;
	uint32_t machineType;
	uint64_t deviceTreeP;
	uint32_t deviceTreeLength;
	char CommandLine[BOOT_LINE_LENGTH];
	uint64_t bootFlags, memSizeActual;
};

_Static_assert(__builtin_offsetof(struct payload, segs) == 0x2a8, "payload header layout");
_Static_assert(__builtin_offsetof(struct boot_args, Video) == 40, "boot_args layout");
_Static_assert(__builtin_offsetof(struct boot_args, CommandLine) == 108, "boot_args layout");
_Static_assert(sizeof(struct boot_args) == 736, "boot_args layout");

static int range_ok(uint64_t base, uint64_t size, uint64_t lo, uint64_t hi)
{
	return base >= lo && base <= hi && size <= hi - base;
}

static int overlap(uint64_t a, uint64_t as, uint64_t b, uint64_t bs)
{
	return a < b + bs && b < a + as;
}

typedef void (*xnu_entry_t)(uint64_t boot_args_pa);

__attribute__((visibility("hidden")))
void shim_main(uintptr_t dtb, unsigned long lvl)
{
	uint64_t rd_start = 0, rd_end = 0;
	int have_dtb, have_initrd = 0;

	struct node_state f = {0};

	/* Same policy as mido/m1: no validated framebuffer node, no drawing, no boot. */
	if (dtb < RAM_FREE_LO || dtb > 0x849f0000UL || (dtb & 7) || !framebuffer((const unsigned char *)dtb, &f))
		return;
	fb = (volatile unsigned char *)(uintptr_t)f.base;
	level = (unsigned int)lvl;
	clear();
	puts_("MIDO XNU SHIM (RAM ONLY)\n\n");
	line("EL      ", lvl, 1);
	line("DTB     ", dtb, 9);
	line2("SHIM    ", (uintptr_t)_start, "END ", (uintptr_t)_image_end);
	have_dtb = dtb_ok(dtb);
	if (!have_dtb)
		puts_("DTB invalid: using ramdisk fallback\n");

	/* 1. locate the payload */
	if (have_dtb && chosen_u64(dtb, "linux,initrd-start", &rd_start) &&
	    chosen_u64(dtb, "linux,initrd-end", &rd_end) && rd_end > rd_start)
		have_initrd = 1;
	if (have_initrd) {
		line2("INITRD  ", rd_start, "END ", rd_end);
	} else {
		rd_start = RAMDISK_FALLBACK;
		rd_end = 0;
		line("INITRD  none in /chosen; fixed ", rd_start, 9);
	}
	if (!range_ok(rd_start, 0x1000, RAM_FREE_LO, RAM_FREE_HI) || (rd_start & 15))
		fail("payload address outside free RAM or unaligned");

	const struct payload *p = (const struct payload *)rd_start;
	static const char want[8] = "SWEETXNU";
	for (int i = 0; i < 8; i++)
		if (p->magic[i] != want[i])
			fail("no SWEETXNU payload at that address");
	if (p->version != 1 || p->nsegs == 0 || p->nsegs > MAX_SEGS || (p->adt_off & 15))
		fail("bad payload header");

	/* 2. validate: sources inside the payload, destinations inside the arena */
	uint64_t hdr_end = sizeof(struct payload) + p->nsegs * sizeof(struct payload_seg);
	uint64_t extent = p->adt_off + p->adt_size;
	if (p->adt_off < hdr_end || p->adt_size == 0 || extent < p->adt_off || extent > 0x10000000UL)
		fail("bad ADT range");
	for (uint32_t i = 0; i < p->nsegs; i++) {
		const struct payload_seg *s = &p->segs[i];
		if (s->file_off < hdr_end || !range_ok(s->file_off, s->file_size, 0, 0x10000000UL) ||
		    s->file_size > s->vmsize)
			fail("bad segment file range");
		if (s->file_off + s->file_size > extent)
			extent = s->file_off + s->file_size;
	}
	if (rd_end && extent > rd_end - rd_start)
		fail("payload larger than ramdisk");
	line("PAYLOAD ", extent, 9);

	uint64_t pa_of_va = p->phys_base - p->virt_base;	/* pa = va + this (mod 2^64) */
	line2("PHYS    ", p->phys_base, "SIZE ", p->mem_size);
	line2("VIRT    ", p->virt_base, "ENTRY ", p->entry_va);
	if ((p->phys_base & (L2_BLOCK - 1)) || (p->virt_base & (L2_BLOCK - 1)) || (p->mem_size & (PAGE - 1)) ||
	    !range_ok(p->phys_base, p->mem_size, RAM_FREE_LO, RAM_FREE_HI))
		fail("arena not 2MiB aligned or outside free RAM");
	uint64_t kend = p->kernel_end;
	if (kend & (PAGE - 1) || kend <= p->virt_base || kend - p->virt_base > p->mem_size)
		fail("bad kernel_end");
	for (uint32_t i = 0; i < p->nsegs; i++) {
		const struct payload_seg *s = &p->segs[i];
		if (s->vmaddr < p->virt_base || (s->vmaddr & 15) || s->vmsize > kend - p->virt_base ||
		    s->vmaddr - p->virt_base > kend - p->virt_base - s->vmsize)
			fail("segment outside kernel image");
	}
	if (p->entry_va < p->virt_base || p->entry_va >= kend || (p->entry_va & 3))
		fail("entry outside kernel image");

	uintptr_t adt_pa = kend + pa_of_va;
	uintptr_t ba_pa = (adt_pa + p->adt_size + PAGE - 1) & ~(PAGE - 1);
	uintptr_t top = ba_pa + PAGE;
	if (top > p->phys_base + p->mem_size)
		fail("ADT + boot_args exceed arena");
	/* Nothing we read from (shim, DTB, payload) may sit where the kernel goes. */
	if (overlap(p->phys_base, top - p->phys_base, (uintptr_t)_start, (uintptr_t)_image_end - (uintptr_t)_start) ||
	    overlap(p->phys_base, top - p->phys_base, rd_start, extent) ||
	    (have_dtb && overlap(p->phys_base, top - p->phys_base, dtb, be32(dtb + 4))))
		fail("kernel arena overlaps shim, DTB or payload");
	if (lvl != 1)
		fail("not entered at EL1");
	puts_("CHECKS  ok\n");

	/* 3. copy: announce, then do */
	puts_("COPY    segments (screen may pause)\n");
	for (uint32_t i = 0; i < p->nsegs; i++) {
		const struct payload_seg *s = &p->segs[i];
		uintptr_t dst = s->vmaddr + pa_of_va;
		puts_("SEG ");
		hex(i, 2);
		puts_(" PA ");
		hex(dst, 9);
		puts_(" FILE ");
		hex(s->file_size, 8);
		puts_(" VM ");
		hex(s->vmsize, 8);
		putc_('\n');
		copy_mem(dst, rd_start + s->file_off, s->file_size);
		if (s->vmsize > s->file_size)
			zero_mem(dst + s->file_size, s->vmsize - s->file_size);
		/* readback of first and last word proves the RAM accepted the writes */
		if (s->file_size >= 16) {
			volatile const uint64_t *a = (volatile const uint64_t *)(dst);
			volatile const uint64_t *b = (volatile const uint64_t *)(rd_start + s->file_off);
			if ((dst & 7) == 0 && ((rd_start + s->file_off) & 7) == 0 && (a[0] != b[0] || a[1] != b[1]))
				fail("segment readback mismatch");
		}
	}
	puts_("COPY    ADT ");
	hex(adt_pa, 9);
	putc_('\n');
	copy_mem(adt_pa, rd_start + p->adt_off, p->adt_size);

	puts_("BOOTARG ");
	hex(ba_pa, 9);
	puts_(" TOP ");
	hex(top, 9);
	putc_('\n');
	zero_mem(ba_pa, PAGE);
	volatile struct boot_args *ba = (volatile struct boot_args *)ba_pa;
	ba->Revision = 2;
	ba->Version = 2;
	ba->virtBase = p->virt_base;
	ba->physBase = p->phys_base;
	ba->memSize = p->mem_size;
	ba->topOfKernelData = top;
	ba->Video.v_baseAddr = f.base;
	ba->Video.v_display = 1;
	ba->Video.v_rowBytes = FB_STRIDE;
	ba->Video.v_width = FB_W;
	ba->Video.v_height = FB_H;
	ba->Video.v_depth = 24;
	ba->deviceTreeP = adt_pa - pa_of_va;	/* xnu reads it with the MMU on: a VA */
	ba->deviceTreeLength = (uint32_t)p->adt_size;
	for (int i = 0; i < BOOT_LINE_LENGTH; i++)
		ba->CommandLine[i] = p->cmdline[i];
	ba->CommandLine[BOOT_LINE_LENGTH - 1] = 0;
	ba->memSizeActual = p->mem_size;

	/* 4. jump */
	uintptr_t entry_pa = p->entry_va + pa_of_va;
	line("JUMP    entry PA ", entry_pa, 9);
	line("        x0 = ", ba_pa, 9);
	puts_("XNU     jumping (MMU+caches off)\n");
	/* Everything was written with the MMU and caches off; drop stale I-cache lines too. */
	__asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");
	((xnu_entry_t)entry_pa)(ba_pa);
	fail("xnu returned");
}
