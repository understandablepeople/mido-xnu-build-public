#include <errno.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static void print_channel(const char *name, const struct fb_bitfield *channel)
{
    printf("    \"%s\": {\"offset\": %u, \"length\": %u, \"msb_right\": %u}",
           name, channel->offset, channel->length, channel->msb_right);
}

int main(void)
{
    const char *paths[] = {"/dev/graphics/fb0", "/dev/fb0"};
    const char *selected = NULL;
    struct fb_fix_screeninfo fixed = {0};
    struct fb_var_screeninfo variable = {0};
    int descriptor = -1;

    for (size_t index = 0; index < sizeof(paths) / sizeof(paths[0]); index++) {
        descriptor = open(paths[index], O_RDONLY | O_CLOEXEC);
        if (descriptor >= 0) {
            selected = paths[index];
            break;
        }
    }
    if (descriptor < 0) {
        fprintf(stderr, "Cannot open framebuffer read-only: %s\n", strerror(errno));
        return 1;
    }
    if (ioctl(descriptor, FBIOGET_FSCREENINFO, &fixed) < 0) {
        fprintf(stderr, "FBIOGET_FSCREENINFO failed: %s\n", strerror(errno));
        close(descriptor);
        return 1;
    }
    if (ioctl(descriptor, FBIOGET_VSCREENINFO, &variable) < 0) {
        fprintf(stderr, "FBIOGET_VSCREENINFO failed: %s\n", strerror(errno));
        close(descriptor);
        return 1;
    }
    close(descriptor);

    printf("{\n  \"device\": \"%s\",\n", selected);
    printf("  \"smem_start\": \"0x%lx\",\n", fixed.smem_start);
    printf("  \"smem_length\": %u,\n", fixed.smem_len);
    printf("  \"line_length\": %u,\n", fixed.line_length);
    printf("  \"type\": %u,\n  \"visual\": %u,\n", fixed.type, fixed.visual);
    printf("  \"xres\": %u,\n  \"yres\": %u,\n", variable.xres, variable.yres);
    printf("  \"xres_virtual\": %u,\n  \"yres_virtual\": %u,\n",
           variable.xres_virtual, variable.yres_virtual);
    printf("  \"xoffset\": %u,\n  \"yoffset\": %u,\n", variable.xoffset, variable.yoffset);
    printf("  \"bits_per_pixel\": %u,\n  \"rotate\": %u,\n", variable.bits_per_pixel, variable.rotate);
    printf("  \"channels\": {\n");
    print_channel("red", &variable.red);
    printf(",\n");
    print_channel("green", &variable.green);
    printf(",\n");
    print_channel("blue", &variable.blue);
    printf(",\n");
    print_channel("alpha", &variable.transp);
    printf("\n  }\n}\n");
    return 0;
}
