// SPDX-License-Identifier: MIT
package xiaomi

import (
    "bytes"
    "encoding/base64"
    "io"
    "net/http"
    "strings"
    "testing"
)

type cameraTransport func(*http.Request)(*http.Response,error)
func(f cameraTransport)RoundTrip(r *http.Request)(*http.Response,error){return f(r)}

func TestCameraGETUsesExistingLoginAndDecrypts(t *testing.T){
    c:=NewCloud("xiaomiio");c.ssecurity=bytes.Repeat([]byte{1},32);c.cookies="userId=123; serviceToken=example"
    c.client=&http.Client{Transport:cameraTransport(func(r *http.Request)(*http.Response,error){
        if r.Method!="GET"||r.URL.Host!="business.smartcamera.api.io.mi.com"||r.Header.Get("MIOT-ENCRYPT-ALGORITHM")!="ENCRYPT-RC4"{t.Fatal("unexpected camera request")}
        nonce,_:=base64.StdEncoding.DecodeString(r.URL.Query().Get("_nonce"));key:=genSignedNonce(c.ssecurity,nonce)
        enc,_:=base64.StdEncoding.DecodeString(r.URL.Query().Get("data"));plain,_:=crypt(key,enc)
        if string(plain)!=`{"limit":1}`{t.Fatal("encrypted payload changed")}
        body,_:=crypt(key,[]byte(`{"code":0,"data":{"thirdPartPlayUnits":[]}}`))
        return &http.Response{StatusCode:200,Body:io.NopCloser(strings.NewReader(base64.StdEncoding.EncodeToString(body)))},nil
    })}
    result,err:=c.CameraRequest("cn","/common/app/get/eventlist",`{"limit":1}`)
    if err!=nil||!bytes.Contains(result,[]byte("thirdPartPlayUnits")){t.Fatal("camera response not decoded")}
}

func TestCameraURLRejectsArbitraryEndpoints(t *testing.T){
    c:=NewCloud("xiaomiio")
    for _,test:=range []struct{region,path string}{{"cn","https://example.com"},{"../bad","/common/app/m3u8"},{"cn","/home/rpc/123"}}{
        if _,err:=c.CameraURL(test.region,test.path,`{}`);err==nil{t.Fatal("unexpected endpoint accepted")}
    }
}
