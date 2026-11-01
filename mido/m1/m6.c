/*
 * mido M1: 24bpp text console + hardware probes, RAM-only (loaded by lk2nd).
 *
 * Reuses the already hardware-validated entry (EL1/EL2, MMU+D-cache off,
 * x0 = DTB) and the strict simplefb parser of devices/mido/screen-test.
 * Every probe prints its label BEFORE touching hardware, so if a read
 * faults or hangs the photo shows where it stopped. Faults draw ESR/ELR/FAR.
 * Nothing here writes to the phone's storage or enables the MMU/GIC.
 */
#include <stdint.h>
#include <stddef.h>
#include "font.h"

#include "fdt_fb.inc"

#define FB_W		1080
#define FB_H		1920
#define FB_STRIDE	3240
#define SCALE		2
#define CH_W		(8 * SCALE)
#define CH_H		(16 * SCALE)
#define MARGIN		12
#define COLS		((FB_W - 2 * MARGIN) / CH_W)

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })

/* State lives in .data: the linker script forbids .bss. */
static volatile unsigned char *fb __attribute__((section(".data"))) = 0;
static unsigned int col __attribute__((section(".data"))) = 0;
static unsigned int row __attribute__((section(".data"))) = 0;
static unsigned int level __attribute__((section(".data"))) = 1;
static unsigned char fg[3] __attribute__((section(".data"))) = {255, 255, 255};
static unsigned char bg[3] __attribute__((section(".data"))) = {40, 24, 8};

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

/* ---- tiny FDT walker: print /memory, /reserved-memory, /chosen, /cpus ---- */

static int starts(const char *s, const char *p)
{
	while (*p)
		if (*s++ != *p++)
			return 0;
	return 1;
}

static int same(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

static void dump_fdt(const unsigned char *d)
{
	uint32_t p = read_be32(d + 8), strings = read_be32(d + 12);
	uint32_t end = p + read_be32(d + 36);
	const char *names[8];
	int depth = 0;
	char path[96];

	puts_("DTB bytes ");
	hex(read_be32(d + 4), 8);
	putc_('\n');
	while (p + 4 <= end) {
		uint32_t tok = read_be32(d + p);
		p += 4;
		if (tok == 1) {
			const char *n = (const char *)(d + p);
			uint32_t l = 0;
			while (n[l])
				l++;
			if (depth < 8)
				names[depth] = n;
			depth++;
			p = (p + l + 1 + 3) & ~3U;
		} else if (tok == 2) {
			depth--;
		} else if (tok == 3) {
			uint32_t len = read_be32(d + p), off = read_be32(d + p + 4);
			const unsigned char *v = d + p + 8;
			const char *pn = (const char *)(d + strings + off);
			int n = 0;
			/* build "/a/b" path of the current node */
			path[0] = 0;
			for (int i = 1; i < depth && i < 8 && n < 80; i++) {
				path[n++] = '/';
				for (const char *s = names[i]; *s && n < 90; s++)
					path[n++] = *s;
			}
			path[n] = 0;
			if (same(pn, "reg") && (starts(path, "/memory") || starts(path, "/reserved-memory/")) && len >= 16) {
				puts_(path);
				putc_(' ');
				for (uint32_t o = 0; o + 16 <= len; o += 16) {
					hex(read_be64(v + o), 9);
					putc_('+');
					hex(read_be64(v + o + 8), 8);
					putc_(' ');
				}
				putc_('\n');
			} else if (starts(path, "/chosen") && path[7] == 0) {
				puts_(" chosen.");
				puts_(pn);
				putc_('=');
				if (len == 4)
					hex(read_be32(v), 8);
				else if (len == 8)
					hex(read_be64(v), 16);
				else if (len > 1 && len < 40 && v[len - 1] == 0 && v[0] >= 0x20)
					puts_((const char *)v);
				else {
					puts_("len ");
					hex(len, 4);
				}
				putc_('\n');
			}
			p = (p + 8 + len + 3) & ~3U;
		} else if (tok == 9) {
			break;
		}
	}
}


/* ---- eMMC full re-init from reset, SDHCI hc_mem @0x07824900 + core_mem @0x07824000 ---- */

#define SDHC		0x07824900UL
#define CORE		0x07824000UL

static uint32_t r32(unsigned o) { return *(volatile uint32_t *)(SDHC + o); }
static uint16_t r16(unsigned o) { return *(volatile uint16_t *)(SDHC + o); }
static uint8_t  r8(unsigned o)  { return *(volatile uint8_t *)(SDHC + o); }
static void w32(unsigned o, uint32_t v) { *(volatile uint32_t *)(SDHC + o) = v; }
static void w16(unsigned o, uint16_t v) { *(volatile uint16_t *)(SDHC + o) = v; }
static void w8(unsigned o, uint8_t v)   { *(volatile uint8_t *)(SDHC + o) = v; }
static uint32_t c32(unsigned o) { return *(volatile uint32_t *)(CORE + o); }
static void cw32(unsigned o, uint32_t v) { *(volatile uint32_t *)(CORE + o) = v; }

static void delay_us(unsigned us)
{
	uint64_t f = rsr("cntfrq_el0"), t0 = rsr("cntpct_el0");
	while ((rsr("cntpct_el0") - t0) < f / 1000000 * us)
		;
}

static void reg(const char *name, uint64_t v, int digits)
{
	puts_(name);
	hex(v, digits);
	puts_("  ");
}

static void cmd_reset(void)
{
	unsigned n;
	w8(0x2f, 0x06);				/* reset CMD + DAT lines */
	for (n = 0; n < 1000 && (r8(0x2f) & 6); n++)
		delay_us(10);
	w32(0x30, 0xffffffff);
}

/*
 * Returns 0 ok, else INT_STATUS (error bits) or 0x80000000 | state on poll timeout.
 * flags: bits1:0 response (0 none,1 136,2 48,3 48+busy), bit3 crc, bit4 index, bit5 data.
 */
static uint32_t cmd(unsigned idx, uint32_t arg, unsigned flags, unsigned mode, uint32_t resp[4])
{
	unsigned n;
	uint32_t st = 0;
	for (n = 0; n < 5000 && (r32(0x24) & 3); n++)
		delay_us(10);
	if (n == 5000) {
		cmd_reset();
		return 0x80000001;
	}
	w32(0x30, 0xffffffff);
	w32(0x08, arg);
	w32(0x0c, (uint32_t)mode | ((uint32_t)((idx << 8) | flags) << 16));
	for (n = 0; n < 200000; n++) {		/* up to ~1 s */
		st = r32(0x30);
		if ((st & 0x8000) || (st & 1))
			break;
		delay_us(5);
	}
	if (n == 200000 || (st & 0x8000)) {
		uint32_t r = (n == 200000) ? 0x80000002 : st;
		cmd_reset();
		return r;
	}
	if (resp) {
		resp[0] = r32(0x10); resp[1] = r32(0x14); resp[2] = r32(0x18); resp[3] = r32(0x1c);
	}
	w32(0x30, 1);
	if ((flags & 3) == 3) {
		for (n = 0; n < 400000 && !(r32(0x30) & 2); n++)
			delay_us(5);
		w32(0x30, 2);
	}
	return 0;
}

static void set_clock(unsigned n)		/* SDCLK = 200 MHz / (2*n), n = 0: base */
{
	unsigned i;
	uint16_t v;
	w16(0x2c, 0);
	v = (uint16_t)(((n & 0xff) << 8) | (((n >> 8) & 3) << 6) | 1);
	w16(0x2c, v);
	for (i = 0; i < 20000 && !(r16(0x2c) & 2); i++)
		delay_us(10);
	w16(0x2c, v | 4);
}

static uint32_t read_block(uint32_t arg, unsigned idx, unsigned char *buf)
{
	uint32_t r, st = 0, resp[4];
	unsigned n, i;

	w16(0x04, 0x0200);
	w16(0x06, 1);
	r = cmd(idx, arg, 0x3a, 0x0010, resp);	/* data present, read, PIO */
	if (r)
		return r;
	for (n = 0; n < 400000; n++) {
		st = r32(0x30);
		if (st & 0x20)
			break;
		if (st & 0x8000)
			return st;
		delay_us(5);
	}
	if (n == 400000)
		return 0x80000003;
	for (i = 0; i < 512; i += 4) {
		uint32_t v = r32(0x20);
		buf[i] = v; buf[i + 1] = v >> 8; buf[i + 2] = v >> 16; buf[i + 3] = v >> 24;
	}
	for (n = 0; n < 400000 && !(r32(0x30) & 2); n++)
		delay_us(5);
	w32(0x30, 0xffffffff);
	return 0;
}

static uint32_t le32(const unsigned char *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }

__attribute__((visibility("hidden")))
void m1_exception(uint64_t slot)
{
	bg[0] = 0; bg[1] = 0; bg[2] = 160;
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

static void step(const char *name, uint32_t e, const uint32_t *resp)
{
	puts_(name);
	puts_(": ");
	hex(e, 8);
	if (resp) {
		putc_(' ');
		hex(resp[0], 8);
	}
	putc_('\n');
}

static void dump(const char *name, unsigned long base, unsigned from, unsigned to)
{
	unsigned o;
	puts_(name);
	putc_('\n');
	for (o = from; o < to; o += 16) {
		hex(o, 3);
		puts_(":");
		for (unsigned k = 0; k < 16; k += 4) {
			putc_(' ');
			hex(*(volatile uint32_t *)(base + o + k), 8);
		}
		putc_('\n');
	}
}

static int try_cmd(const char *label)
{
	uint32_t resp[4] = {0, 0, 0, 0};
	uint32_t e = cmd(13, 1u << 16, 0x1a, 0, resp);
	puts_(label);
	puts_(" CMD13: ");
	hex(e, 8);
	puts_(" INT ");
	hex(r32(0x30), 4);
	putc_('\n');
	return e == 0;
}

__attribute__((visibility("hidden")))
void m1_main(uintptr_t dtb_address, unsigned long lvl)
{
	struct node_state f = {0};
	uint32_t st, e, resp[4] = {0, 0, 0, 0};
	unsigned n;

	if (dtb_address < 0x10000000 || dtb_address > 0x849f0000 || (dtb_address & 7))
		return;
	if (!framebuffer((const unsigned char *)dtb_address, &f))
		return;
	fb = (volatile unsigned char *)(uintptr_t)f.base;
	level = (unsigned int)lvl;
	clear();
	puts_("MIDO M6 SDHCI DIAG (READ MOSTLY, NOT IOS)\n");
	dump("core+0x00", CORE, 0x00, 0x40);
	dump("core+0x70", CORE, 0x70, 0x90);
	dump("core+0xd0", CORE, 0xd0, 0xf0);
	dump("core+0x100", CORE, 0x100, 0x130);
	dump("hc+0x100", SDHC, 0x100, 0x130);
	dump("hc+0xd0", SDHC, 0xd0, 0xf0);
	putc_('\n');

	if (try_cmd("A as-is"))
		goto done;
	st = c32(0xdc);
	puts_("PWRCTL status core+0xdc = "); hex(st, 8); puts_(" hc+0xdc = "); hex(*(volatile uint32_t *)(SDHC + 0xdc), 8); putc_('\n');
	if (st) {
		uint32_t ctl = 0;
		cw32(0xe0, st);
		if (st & 3)
			ctl |= 1;
		if (st & 0xc)
			ctl |= 4;
		cw32(0xe8, ctl);
		puts_("acked PWRCTL ctl="); hex(ctl, 4); putc_('\n');
		if (try_cmd("B after pwrctl ack"))
			goto done;
	}
	cw32(0x78, c32(0x78) | 1);
	puts_("HC_MODE now "); hex(c32(0x78), 8); putc_('\n');
	if (try_cmd("C after HC_MODE_EN"))
		goto done;
	/* D: slow clock, legacy timing, CMD0 + init */
	w16(0x2c, 0);
	w16(0x3e, 0);
	set_clock(250);
	delay_us(5000);
	e = cmd(0, 0, 0x00, 0, 0);
	puts_("D CMD0: "); hex(e, 8); putc_('\n');
	for (n = 0; n < 100; n++) {
		e = cmd(1, 0x40ff8080u, 0x02, 0, resp);
		if (e || (resp[0] & 0x80000000u))
			break;
		delay_us(5000);
	}
	puts_("D CMD1: "); hex(e, 8); putc_(' '); hex(resp[0], 8); putc_('\n');
done:
	puts_("PRES "); hex(r32(0x24), 8); puts_(" CLK "); hex(r16(0x2c), 4); puts_(" HCTL "); hex(r8(0x28), 2); puts_(" PWR "); hex(r8(0x29), 2); puts_(" HC2 "); hex(r16(0x3e), 4); putc_('\n');
	puts_("\nDONE. Hold power to restart.\n");
}
