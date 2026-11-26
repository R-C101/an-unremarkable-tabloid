package main

import (
	"testing"
	"unsafe"
)

func TestStructSizes(t *testing.T) {
	if s := unsafe.Sizeof(mxcfbUpdateData{}); s != 72 {
		t.Fatalf("mxcfb_update_data is %d bytes, want 72", s)
	}
	if s := unsafe.Sizeof(mxcfbUpdateMarkerData{}); s != 8 {
		t.Fatalf("mxcfb_update_marker_data is %d bytes, want 8", s)
	}
}
