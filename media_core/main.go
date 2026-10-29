// SPDX-License-Identifier: MIT
// Doorbell-only profile; upstream go2rtc implementations retain their license.
package main

import (
	"fmt"
	"net"
	"os"
	"runtime"
	"time"

	"github.com/AlexxIT/go2rtc/internal/api"
	"github.com/AlexxIT/go2rtc/internal/api/ws"
	"github.com/AlexxIT/go2rtc/internal/app"
	"github.com/AlexxIT/go2rtc/internal/exec"
	"github.com/AlexxIT/go2rtc/internal/ffmpeg"
	"github.com/AlexxIT/go2rtc/internal/http"
	"github.com/AlexxIT/go2rtc/internal/mjpeg"
	"github.com/AlexxIT/go2rtc/internal/mp4"
	"github.com/AlexxIT/go2rtc/internal/rtsp"
	"github.com/AlexxIT/go2rtc/internal/streams"
	"github.com/AlexxIT/go2rtc/internal/xiaomi"
	"github.com/AlexxIT/go2rtc/pkg/shell"
)

func loopback(address string) bool {
	host, port, err := net.SplitHostPort(address)
	if err != nil || port == "" { return false }
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func validate(apiListen, rtspListen, tlsListen, unixListen, origin string) error {
	if !loopback(apiListen) || !loopback(rtspListen) || tlsListen != "" || unixListen != "" || origin != "" {
		return fmt.Errorf("doorbell core requires explicit loopback API/RTSP and no extra API listeners or CORS origin")
	}
	return nil
}

func main() {
	app.Version = "1.9.15-doorbell-candidate.1"
	app.Init()
	var cfg struct {
		API struct {
			Listen string `yaml:"listen"`
			TLS string `yaml:"tls_listen"`
			Unix string `yaml:"unix_listen"`
			Origin string `yaml:"origin"`
		} `yaml:"api"`
		RTSP struct { Listen string `yaml:"listen"` } `yaml:"rtsp"`
		Doorbell struct { Instance string `yaml:"instance_id"` } `yaml:"doorbell"`
	}
	app.LoadConfig(&cfg)
	if err := validate(cfg.API.Listen, cfg.RTSP.Listen, cfg.API.TLS, cfg.API.Unix, cfg.API.Origin); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	app.Info["doorbell_instance"] = cfg.Doorbell.Instance
	api.Init()
	ws.Init()
	streams.Init()
	http.Init()
	rtsp.Init()
	mp4.Init()
	mjpeg.Init()
	exec.Init()
	ffmpeg.Init()
	xiaomi.Init()
	xiaomi.InitRecordings()
	if runtime.GOOS == "linux" {
		parent := os.Getppid()
		go func() {
			ticker := time.NewTicker(time.Second)
			defer ticker.Stop()
			for range ticker.C {
				if os.Getppid() != parent { os.Exit(0) }
			}
		}()
	}
	shell.RunUntilSignal()
}
