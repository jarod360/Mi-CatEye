package xiaomi

import (
 "io"
 "net/http"
 "strings"
 "testing"
)

type challengeTransport func(*http.Request) (*http.Response, error)
func (f challengeTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestCatEyeRefreshWithoutSubmittingCode(t *testing.T) {
 c := NewCloud("test")
 if c.RefreshCaptcha() == nil { t.Fatal("missing challenge accepted") }
 c.auth = map[string]string{"ick":"old"}
 c.captchaURL = "/pass/getCode?icodeType=login"
 calls := 0
 c.client = &http.Client{Transport: challengeTransport(func(r *http.Request) (*http.Response,error) {
  calls++
  if r.Method != "GET" || r.URL.Path != "/pass/getCode" { t.Fatal("refresh must only fetch challenge") }
  if r.URL.Query().Get("captCode") != "" { t.Fatal("guessed captcha submitted") }
  return &http.Response{StatusCode:200, Header:http.Header{"Set-Cookie":[]string{"ick=new; Path=/"}}, Body:io.NopCloser(strings.NewReader("new image"))},nil
 })}
 err := c.RefreshCaptcha()
 login,ok := err.(*LoginError)
 if !ok || string(login.Captcha)!="new image" || c.auth["ick"]!="new" || calls!=1 { t.Fatal("challenge not refreshed") }
}
