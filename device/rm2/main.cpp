// tabloid-show for the reMarkable 2: draws a PNG (or JPEG) on the e-ink screen.
//
// The rM2 has no hardware display controller. Its panel is driven in software
// (a "software TCON") through the raw /dev/fb0, so the reMarkable 1 program
// (../main.go) shows nothing here. This one uses the swtcon library from
// timower/rM2-stuff for that part: it starts the driver, shows one image with
// a full 16-grey refresh, shuts the driver down and exits. It changes nothing
// else on the tablet: no files outside its own folder, no services.
// The caller is expected to stop xochitl first (both take /tmp/epd.lock).
//
// Usage:
//
//	tabloid-show image.png
//	tabloid-show -info
//
// Our code here is MIT like the rest of the project. swtcon is GPL-3.0, so the
// binary built from the two is GPL-3.0. See README.md in this folder.

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include <fcntl.h>
#include <linux/fb.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_ONLY_JPEG
#include "stb_image.h"

#include "swtcon.h"

namespace {

constexpr int kWidth = 1404;
constexpr int kHeight = 1872;

// Index into the waveform file's mode table: 2 is GC16, the full-quality
// 16-grey waveform (the same one ../main.go asks the rM1's controller for).
constexpr int kModeGC16 = 2;
// Lets swtcon pick the pixel formula that belongs to the waveform mode.
constexpr int kPixelModeAuto = 5;

// 8-bit grey -> one of the panel's 16 greys, as an RGB565 pixel.
uint16_t
greyPixel(uint8_t v) {
  int level = (v * 15 + 127) / 255;
  int r5 = (level * 31 + 7) / 15;
  int g6 = (level * 63 + 7) / 15;
  return static_cast<uint16_t>((r5 << 11) | (g6 << 5) | r5);
}

// Places the image on a white canvas of the screen size, centred, without
// scaling (same behaviour as fit() in ../main.go).
std::vector<uint8_t>
fit(const uint8_t* img, int w, int h) {
  std::vector<uint8_t> out(static_cast<size_t>(kWidth) * kHeight, 255);
  int offX = (kWidth - w) / 2;
  int offY = (kHeight - h) / 2;
  for (int y = 0; y < h; y++) {
    int dy = y + offY;
    if (dy < 0 || dy >= kHeight) {
      continue;
    }
    for (int x = 0; x < w; x++) {
      int dx = x + offX;
      if (dx >= 0 && dx < kWidth) {
        out[static_cast<size_t>(dy) * kWidth + dx] = img[static_cast<size_t>(y) * w + x];
      }
    }
  }
  return out;
}

// Read-only: safe to run while xochitl is using the screen.
int
info() {
  int fd = open("/dev/fb0", O_RDONLY);
  if (fd < 0) {
    perror("tabloid-show: /dev/fb0");
    return 1;
  }
  fb_var_screeninfo v{};
  if (ioctl(fd, FBIOGET_VSCREENINFO, &v) != 0) {
    perror("tabloid-show: FBIOGET_VSCREENINFO");
    close(fd);
    return 1;
  }
  close(fd);
  printf("xres=%d yres=%d greys=16 driver=swtcon raw_fb=%ux%u raw_bpp=%u\n",
         kWidth, kHeight, v.xres, v.yres, v.bits_per_pixel);
  return 0;
}

} // namespace

int
main(int argc, char** argv) {
  if (argc == 2 && strcmp(argv[1], "-info") == 0) {
    return info();
  }
  if (argc != 2 || argv[1][0] == '-') {
    fprintf(stderr, "usage: tabloid-show image.png | -info\n");
    return 2;
  }

  int w = 0, h = 0, channels = 0;
  uint8_t* img = stbi_load(argv[1], &w, &h, &channels, 1); // 1 = convert to grey
  if (img == nullptr) {
    fprintf(stderr, "tabloid-show: decode %s: %s\n", argv[1], stbi_failure_reason());
    return 1;
  }
  std::vector<uint8_t> grey = fit(img, w, h);
  stbi_image_free(img);

  // swtcon logs its progress on stdout. Send that to stderr and keep the real
  // stdout for our one-line result, like the rM1 program.
  fflush(stdout);
  int resultFd = dup(STDOUT_FILENO);
  dup2(STDERR_FILENO, STDOUT_FILENO);

  // Takes /tmp/epd.lock, loads the panel's waveform file, starts the driver
  // threads and flashes the screen clean. Fails if xochitl holds the lock.
  uint16_t* fb = swtcon_init();
  if (fb == nullptr) {
    fprintf(stderr, "tabloid-show: cannot start the display driver (is xochitl still running?)\n");
    return 1;
  }
  for (size_t i = 0; i < grey.size(); i++) {
    fb[i] = greyPixel(grey[i]);
  }

  update_data req = { 0, 0, kHeight, kWidth, Sync, kModeGC16, 0, kPixelModeAuto };
  swtcon_lock();
  swtcon_update(&req);
  swtcon_unlock_post();
  swtcon_wait();
  swtcon_shutdown(0); // waits for the panel to finish, then powers it down

  fflush(stdout);
  dprintf(resultFd, "ok\n");
  return 0;
}
