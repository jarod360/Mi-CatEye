// SPDX-License-Identifier: MIT
// Read-only camera-cloud requests using go2rtc's existing Xiaomi login.
package xiaomi

import (
    "bytes"
    "encoding/base64"
    "encoding/json"
    "errors"
    "io"
    "net/http"
    "net/url"
    "strings"
)

func (c *Cloud) CameraURL(region, path, params string) (string, error) {
    switch path {
    case "/common/app/get/eventlist", "/common/app/m3u8", "/miot/camera/app/v1/alarm/playlist/limit":
    default: return "", errors.New("camera endpoint not allowed")
    }
    prefix:=""
    switch region {
    case "cn":
    case "de","i2","ru","sg","us": prefix=region+"."
    default: return "", errors.New("camera region not allowed")
    }
    nonce:=genNonce()
    signed:=genSignedNonce(c.ssecurity,nonce)
    form:=url.Values{"data":{params}}
    form.Set("rc4_hash__",genSignature64("GET",path,form,signed))
    for _,values:=range form {
        encrypted,err:=crypt(signed,[]byte(values[0])); if err!=nil{return "",err}
        values[0]=base64.StdEncoding.EncodeToString(encrypted)
    }
    form.Set("signature",genSignature64("GET",path,form,signed))
    form.Set("ssecurity",base64.StdEncoding.EncodeToString(c.ssecurity))
    form.Set("_nonce",base64.StdEncoding.EncodeToString(nonce))
    for _,part:=range strings.Split(c.cookies,";") {
        key,value,ok:=strings.Cut(strings.TrimSpace(part),"=")
        if ok && key=="serviceToken" {form.Set("yetAnotherServiceToken",value)}
    }
    return "https://"+prefix+"business.smartcamera.api.io.mi.com"+path+"?"+form.Encode(),nil
}

func (c *Cloud) CameraRequest(region,path,params string) (json.RawMessage,error) {
    address,err:=c.CameraURL(region,path,params);if err!=nil{return nil,err}
    req,err:=http.NewRequest("GET",address,nil);if err!=nil{return nil,errors.New("camera request failed")}
    req.Header.Set("Cookie",c.cookies+"; locale=zh_CN; timezone=GMT+08:00; channel=MI_APP_STORE")
    req.Header.Set("MIOT-ENCRYPT-ALGORITHM","ENCRYPT-RC4")
    req.Header.Set("Accept-Encoding","identity")
    req.Header.Set("X-XIAOMI-PROTOCAL-FLAG-CLI","PROTOCAL-HTTP2")
    res,err:=c.client.Do(req);if err!=nil{return nil,errors.New("camera connection failed")}
    defer res.Body.Close()
    if res.StatusCode!=200{return nil,errors.New("camera HTTP request rejected")}
    data,err:=io.ReadAll(io.LimitReader(res.Body,4*1024*1024+1));if err!=nil||len(data)>4*1024*1024{return nil,errors.New("camera response invalid")}
    if !json.Valid(data) {
        encrypted,err:=base64.StdEncoding.DecodeString(string(bytes.TrimSpace(data)));if err!=nil{return nil,errors.New("camera response invalid")}
        nonce,_:=base64.StdEncoding.DecodeString(req.URL.Query().Get("_nonce"))
        data,err=crypt(genSignedNonce(c.ssecurity,nonce),encrypted);if err!=nil{return nil,errors.New("camera response invalid")}
    }
    var status struct{Code int `json:"code"`}
    if json.Unmarshal(data,&status)!=nil{return nil,errors.New("camera response invalid")}
    if status.Code!=0{return nil,errors.New("camera authorization or request rejected")}
    return data,nil
}
