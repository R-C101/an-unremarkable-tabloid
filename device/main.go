// tabloid-show draws a PNG on the reMarkable 1 e-ink screen.
//
// It writes the image into the Linux framebuffer (/dev/fb0) and then asks the
// i.MX EPDC driver for a full-screen GC16 (16-grey) refresh. It changes
// nothing else on the tablet: no files outside its own folder, no services.
// The caller is expected to stop xochitl first so it does not draw over us.
//
// Usage:
//
//	tabloid-show [-fb /dev/fb0] image.png
//	tabloid-show -info
package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"syscall"
	"unsafe"
)

const (
	fbiogetVScreeninfo = 0x4600
	fbiogetFScreeninfo = 0x4602

	// _IOW('F', 0x2E, struct mxcfb_update_data) with sizeof == 72 on ARM32.
	mxcfbSendUpdate = 0x4048462E
	// _IOWR('F', 0x2F, struct mxcfb_update_marker_data) with sizeof == 8.
	mxcfbWaitForUpdateComplete = 0xC008462F

	waveformGC16      = 2
	updateModeFull    = 1
	tempUseAmbient    = 0x1000
	updateMarker      = 0x7d45
	varScreeninfoSize = 160
	fixScreeninfoSize = 68 // ARM32 layout (unsigned long is 4 bytes)
)

type mxcfbRect struct{ Top, Left, Width, Height uint32 }

type mxcfbUpdateData struct {
	UpdateRegion mxcfbRect
	WaveformMode uint32
	UpdateMode   uint32
	UpdateMarker uint32
	Temp         int32
	Flags        uint32
	DitherMode   int32
	QuantBit     int32
	// struct mxcfb_alt_buffer_data
	AltPhysAddr uint32
	AltWidth    uint32
	AltHeight   uint32
	AltRegion   mxcfbRect
}

type mxcfbUpdateMarkerData struct {
	Marker        uint32
	CollisionTest uint32
}

type screen struct {
	xres, yres, xresVirtual, yoffset, bpp, lineLength uint32
}

func ioctl(fd uintptr, req uintptr, arg unsafe.Pointer) error {
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, fd, req, uintptr(arg))
	if errno != 0 {
		return errno
	}
	return nil
}

func readScreen(f *os.File) (screen, error) {
	var v [varScreeninfoSize]byte
	var x [fixScreeninfoSize + 32]byte // slack in case of a larger fix struct
	if err := ioctl(f.Fd(), fbiogetVScreeninfo, unsafe.Pointer(&v[0])); err != nil {
		return screen{}, fmt.Errorf("FBIOGET_VSCREENINFO: %w", err)
	}
	if err := ioctl(f.Fd(), fbiogetFScreeninfo, unsafe.Pointer(&x[0])); err != nil {
		return screen{}, fmt.Errorf("FBIOGET_FSCREENINFO: %w", err)
	}
	le := binary.LittleEndian
	s := screen{
		xres:        le.Uint32(v[0:]),
		yres:        le.Uint32(v[4:]),
		xresVirtual: le.Uint32(v[8:]),
		yoffset:     le.Uint32(v[20:]),
		bpp:         le.Uint32(v[24:]),
		lineLength:  le.Uint32(x[44:]),
	}
	if s.lineLength == 0 {
		s.lineLength = s.xresVirtual * s.bpp / 8
	}
	return s, nil
}

// fit places img on a white canvas of the screen size, centred, without scaling.
func fit(img image.Image, w, h int) *image.Gray {
	out := image.NewGray(image.Rect(0, 0, w, h))
	draw.Draw(out, out.Bounds(), image.White, image.Point{}, draw.Src)
	b := img.Bounds()
	off := image.Pt((w-b.Dx())/2, (h-b.Dy())/2)
	draw.Draw(out, b.Sub(b.Min).Add(off), img, b.Min, draw.Src)
	return out
}

func encode(g *image.Gray, s screen) []byte {
	buf := make([]byte, int(s.lineLength)*int(s.yres))
	bytesPP := int(s.bpp / 8)
	for y := 0; y < int(s.yres); y++ {
		row := buf[y*int(s.lineLength):]
		for x := 0; x < int(s.xres); x++ {
			v := g.GrayAt(x, y).Y
			switch bytesPP {
			case 1:
				row[x] = v
			case 2: // RGB565, little endian
				p := uint16(v>>3)<<11 | uint16(v>>2)<<5 | uint16(v>>3)
				row[2*x] = byte(p)
				row[2*x+1] = byte(p >> 8)
			case 4: // XRGB8888
				row[4*x], row[4*x+1], row[4*x+2], row[4*x+3] = v, v, v, 0xff
			}
		}
	}
	return buf
}

func main() {
	fbPath := flag.String("fb", "/dev/fb0", "framebuffer device")
	info := flag.Bool("info", false, "print framebuffer geometry and exit")
	flag.Parse()

	f, err := os.OpenFile(*fbPath, os.O_RDWR, 0)
	if err != nil {
		fail(err)
	}
	defer f.Close()
	s, err := readScreen(f)
	if err != nil {
		fail(err)
	}
	if *info {
		fmt.Printf("xres=%d yres=%d xres_virtual=%d yoffset=%d bpp=%d line_length=%d\n",
			s.xres, s.yres, s.xresVirtual, s.yoffset, s.bpp, s.lineLength)
		return
	}
	if flag.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: tabloid-show [-fb /dev/fb0] image.png | -info")
		os.Exit(2)
	}
	switch s.bpp {
	case 8, 16, 32:
	default:
		fail(fmt.Errorf("unsupported framebuffer depth %d bpp", s.bpp))
	}

	in, err := os.Open(flag.Arg(0))
	if err != nil {
		fail(err)
	}
	img, _, err := image.Decode(in)
	in.Close()
	if err != nil {
		fail(fmt.Errorf("decode %s: %w", flag.Arg(0), err))
	}
	g, ok := img.(*image.Gray)
	if !ok || g.Bounds() != image.Rect(0, 0, int(s.xres), int(s.yres)) {
		g = fit(toGray(img), int(s.xres), int(s.yres))
	}

	if _, err := f.WriteAt(encode(g, s), int64(s.yoffset)*int64(s.lineLength)); err != nil {
		fail(fmt.Errorf("write framebuffer: %w", err))
	}

	upd := mxcfbUpdateData{
		UpdateRegion: mxcfbRect{Width: s.xres, Height: s.yres},
		WaveformMode: waveformGC16,
		UpdateMode:   updateModeFull,
		UpdateMarker: updateMarker,
		Temp:         tempUseAmbient,
	}
	if err := ioctl(f.Fd(), mxcfbSendUpdate, unsafe.Pointer(&upd)); err != nil {
		fail(fmt.Errorf("MXCFB_SEND_UPDATE: %w", err))
	}
	wait := mxcfbUpdateMarkerData{Marker: updateMarker}
	_ = ioctl(f.Fd(), mxcfbWaitForUpdateComplete, unsafe.Pointer(&wait))
	fmt.Println("ok")
}

func toGray(img image.Image) *image.Gray {
	b := img.Bounds()
	g := image.NewGray(b)
	for y := b.Min.Y; y < b.Max.Y; y++ {
		for x := b.Min.X; x < b.Max.X; x++ {
			g.Set(x, y, color.GrayModel.Convert(img.At(x, y)))
		}
	}
	return g
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, "tabloid-show:", err)
	os.Exit(1)
}
