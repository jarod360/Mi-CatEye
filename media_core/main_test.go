// SPDX-License-Identifier: MIT
package main

import "testing"

func TestListenerBoundary(t *testing.T) {
	for _, tc := range []struct{ api, rtsp, tls, unix, origin string; ok bool }{
		{"127.0.0.1:1984", "127.0.0.1:8554", "", "", "", true},
		{"[::1]:1984", "[::1]:8554", "", "", "", true},
		{":1984", "127.0.0.1:8554", "", "", "", false},
		{"127.0.0.1:1984", ":8554", "", "", "", false},
		{"127.0.0.1:1984", "127.0.0.1:8554", ":443", "", "", false},
		{"127.0.0.1:1984", "127.0.0.1:8554", "", "/tmp/api.sock", "", false},
		{"127.0.0.1:1984", "127.0.0.1:8554", "", "", "*", false},
		{"", "", "", "", "", false},
	} {
		if got := validate(tc.api, tc.rtsp, tc.tls, tc.unix, tc.origin); (got == nil) != tc.ok {
			t.Fatalf("unexpected listener validation for %q", tc.api)
		}
	}
}
