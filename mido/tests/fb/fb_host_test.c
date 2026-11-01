/*
 * Host test for the mido 24bpp BGR framebuffer code in xnu patches 0003/0010/0012.
 * Compiled from run_fb_test.py, which extracts the REAL source from a patched
 * xnu tree (the fbcon block of pexpert/arm/pe_serial.c and all of
 * osfmk/arm64/mido_early.c); nothing here is a copy of the logic.
 * Windows host only: VirtualAlloc at 0x90000000 stands in for the splash.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdarg.h>
#include <windows.h>

#define SECURITY_READ_ONLY_LATE(x) x
#include "iso_font.c"
#include "mido_fb.h"

/* ---- fbcon (pe_serial.c extract) ---- */
#include "fbcon_extract.inc"

/* ---- mido_early.c (whole file; header shims in the include path) ---- */
#include "mido_early.c"

static void
fbcon_tprint(const char *s)
{
	while (*s) {
		fbcon_transmit_data((uint8_t)*s++);
	}
}

int
_doprnt(const char *fmt, va_list *a, void (*putc_fn)(char), int radix)
{
	(void)a;
	(void)radix;
	while (*fmt) {
		putc_fn(*fmt++);
	}
	return 0;
}

static void
write_raw(const char *path, const uint8_t *buf, size_t n)
{
	FILE *f = fopen(path, "wb");
	fwrite(buf, 1, n, f);
	fclose(f);
}

int
main(int argc, char **argv)
{
	const char *outdir = argc > 1 ? argv[1] : ".";
	char path[1024];
	size_t total = (size_t)MIDO_FB_BLOCKS * MIDO_FB_BLOCK_SIZE;
	int bad = 0;

	/* Splash stand-in: 3 blocks at 0x90000000, pixels at +0x1000, like the phone. */
	uint8_t *blk = VirtualAlloc((void *)0x90000000, total, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
	if (blk != (uint8_t *)0x90000000) {
		fprintf(stderr, "cannot map 0x90000000\n");
		return 2;
	}
	memset(blk, 0xEE, total);	/* canary: detect stray writes outside the pixel window */
	uint8_t *fb = blk + MIDO_FB_BLOCK_OFFSET;

	/* 1. early console through the VA=PA pointer (default early_fb). */
	for (unsigned s = 0; s <= 7; s++) {
		mido_early_mark(s, "stage reached");
	}
	mido_early_string("early console: 24bpp BGR OK 0123456789\n");
	snprintf(path, sizeof path, "%s/fb_early_dump.bgr", outdir);
	write_raw(path, fb, MIDO_FB_SIZE);

	/* 2. relocate to a "kernel VA" alias: second buffer, block base passed in. */
	uint8_t *alias = VirtualAlloc(NULL, total, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
	memcpy(alias, blk, total);
	mido_early_relocate((uint64_t)(uintptr_t)alias);
	mido_early_string("after relocate: pixels at alias+0x1000\n");

	/* 3. fbcon serial console on the alias: wrap + blank-line marker. */
	fbcon_base = alias + MIDO_FB_BLOCK_OFFSET;
	fbcon_width = MIDO_FB_WIDTH;
	fbcon_height = MIDO_FB_HEIGHT;
	fbcon_stride = MIDO_FB_STRIDE;
	fbcon_init();
	fbcon_tprint("fbcon: 1080x1920 stride 3240 bpp 24 (B,G,R)\n");
	fbcon_tprint("The quick brown fox jumps over the lazy dog 0123456789\n");
	fbcon_tprint("A line that is much longer than the sixty-seven columns the display offers so it must wrap.\n");
	for (int i = 0; i < 70; i++) {
		char b[80];
		snprintf(b, sizeof b, "wrap line %02d ABCDEFGH\n", i);
		fbcon_tprint(b);
	}

	/* canaries outside the pixel window must be untouched (no overrun, no stride skew past the end) */
	for (size_t i = 0; i < MIDO_FB_BLOCK_OFFSET; i++) {
		if (blk[i] != 0xEE || alias[i] != 0xEE) {
			bad++;
			break;
		}
	}
	for (size_t i = MIDO_FB_BLOCK_OFFSET + MIDO_FB_SIZE; i < total; i++) {
		if (blk[i] != 0xEE || alias[i] != 0xEE) {
			bad++;
			break;
		}
	}
	/* above the stage-bar area every pixel is exactly bg or white: nothing else, so no byte mix-ups */
	size_t nfg = 0, nbg = 0, nother = 0;
	for (unsigned y = 0; y < MIDO_FB_HEIGHT - 32; y++) {
		for (unsigned x = 0; x < MIDO_FB_WIDTH; x++) {
			const uint8_t *p = alias + MIDO_FB_BLOCK_OFFSET + (size_t)y * MIDO_FB_STRIDE + (size_t)x * 3;
			if (p[0] == MIDO_FB_BG_B && p[1] == MIDO_FB_BG_G && p[2] == MIDO_FB_BG_R) {
				nbg++;
			} else if (p[0] == 0xff && p[1] == 0xff && p[2] == 0xff) {
				nfg++;
			} else {
				nother++;
			}
		}
	}
	printf("fg=%zu bg=%zu other=%zu canary_bad=%d\n", nfg, nbg, nother, bad);
	if (nother || !nfg) {
		bad++;
	}
	/* stage 3 bar in the early console buffer (fbcon later repaints the whole screen): B=0x00 G=0xff R=96 */
	const uint8_t *q = fb + (size_t)(MIDO_FB_HEIGHT - 1) * MIDO_FB_STRIDE + (size_t)(3 * 48 + 1) * 3;
	if (!(q[0] == 0x00 && q[1] == 0xff && q[2] == 96)) {
		printf("stage bar colour wrong %02x %02x %02x\n", q[0], q[1], q[2]);
		bad++;
	}
	snprintf(path, sizeof path, "%s/fb_dump.bgr", outdir);
	write_raw(path, alias + MIDO_FB_BLOCK_OFFSET, MIDO_FB_SIZE);
	printf(bad ? "FAIL\n" : "PASS\n");
	return bad ? 1 : 0;
}
