# tabloid-show for the reMarkable 2

The reMarkable 2 has no hardware display controller. Its e-ink panel is driven in software through the raw
`/dev/fb0`, normally by xochitl, so the reMarkable 1 program (`../main.go`) shows nothing on it.

`main.cpp` is the reMarkable 2 version of the same program: it decodes a PNG, starts a software display driver,
shows the image with one full 16-grey refresh, shuts the driver down and exits. Same interface as the rM1 program:

```sh
tabloid-show image.png    # prints "ok"
tabloid-show -info        # read-only, safe while xochitl is running
```

It runs from `/home/root/tabloid` with xochitl stopped. It needs no Toltec, xovi, rm2fb server, `LD_PRELOAD` or
service, and it writes nothing outside its own folder (it takes the usual `/tmp/epd.lock` while it draws).
If xochitl is still running it refuses to start and leaves the screen alone.

## What it's built from

| Part | Source | Licence |
|---|---|---|
| `main.cpp` | this project | MIT |
| swtcon, the software display driver | [timower/rM2-stuff](https://github.com/timower/rM2-stuff) `libs/swtcon`, pinned commit | GPL-3.0 |
| `stb_image.h`, PNG/JPEG decoder | [nothings/stb](https://github.com/nothings/stb), pinned commit | public domain / MIT |

**Licence note.** swtcon is GPL-3.0, so the combined binary `unremarkable/bin/tabloid-show-rm2-armv7` is
GPL-3.0, unlike the rest of this MIT project. Its complete source is `main.cpp` plus the two pinned sources that
`build.sh` downloads, and `build.sh` is the build recipe. The Python package only uploads and runs the binary as
a separate program.

## Build

On Linux or WSL, with an ARM cross compiler that supports C++20:

```sh
sudo apt install g++-arm-linux-gnueabihf git curl
sh device/rm2/build.sh        # writes unremarkable/bin/tabloid-show-rm2-armv7
```

The script checks out rM2-stuff at the pinned commit, verifies the checksum of `stb_image.h`, and links one
static binary, so it doesn't depend on the C library of a particular firmware. Set `BUILD_DIR` to keep the
downloads somewhere else (the default is `device/rm2/build`, which is git-ignored).

## Verified

reMarkable 2, firmware 3.29.1.0 (kernel 5.4.70): draws the dashboard in about 2.5 s, including the driver's
start-up flash. The driver finds the panel's waveform file in `/var/lib/uboot/` and the temperature sensor by itself.

swtcon is reverse-engineered and its author lists newer firmware as beta. It doesn't hook xochitl, so it isn't
tied to a firmware version by design, but only the version above has been tested here.
