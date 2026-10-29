// SPDX-License-Identifier: MIT
// Fixed-device recording API, available only on the profile's loopback listener.
package xiaomi

import (
    "context"
    "bytes"
    "fmt"
    "crypto/aes"
    "crypto/cipher"
    "crypto/sha256"
    "encoding/hex"
    "encoding/binary"
    "encoding/json"
    "errors"
    "io"
    "net/http"
    "net/url"
    "os"
    "os/exec"
    "path/filepath"
    "sort"
    "strconv"
    "strings"
    "sync"
    "time"

    "github.com/AlexxIT/go2rtc/internal/api"
    "github.com/AlexxIT/go2rtc/internal/app"
    "github.com/AlexxIT/go2rtc/internal/streams"
)

type Recording struct {
    ID string `json:"id"`
    Source string `json:"source"`
    Start int64 `json:"start"`
    Duration float64 `json:"duration"`
    Event string `json:"event"`
    FileID string `json:"-"`
    Alarm bool `json:"-"`
}

type recordingStore struct {
    source *url.URL
    directory string
    mu sync.Mutex
    prepareMu sync.Mutex
    records map[string]Recording
}

func InitRecordings() {
    src:=streams.Get("doorbell_live")
    if src==nil||len(src.Sources())!=1{return}
    source,err:=url.Parse(src.Sources()[0]);if err!=nil||source.User==nil{return}
    store:=&recordingStore{source:source,directory:filepath.Join(filepath.Dir(app.ConfigPath),"recordings"),records:map[string]Recording{}}
    store.prune("")
    api.HandleFunc("api/doorbell/recordings",store.list)
    api.HandleFunc("api/doorbell/recordings/prepare",store.prepare)
    api.HandleFunc("api/doorbell/recordings/clip",store.clip)
}

func jsonReply(w http.ResponseWriter, status int, value any) {
    w.Header().Set("Content-Type","application/json")
    w.Header().Set("Cache-Control","no-store")
    w.WriteHeader(status);json.NewEncoder(w).Encode(value)
}

func recordingWindow(r *http.Request)(int64,int64,error){
    a,e1:=strconv.ParseInt(r.URL.Query().Get("start"),10,64)
    b,e2:=strconv.ParseInt(r.URL.Query().Get("end"),10,64)
    if e1!=nil||e2!=nil||a<1262304000000||b<=a||b-a>86400001||b>time.Now().Add(48*time.Hour).UnixMilli(){return 0,0,errors.New("invalid_time_range")}
    return a,b,nil
}

func (s *recordingStore) list(w http.ResponseWriter,r *http.Request){
    if r.Method!="GET"{jsonReply(w,405,map[string]string{"error":"method_not_allowed"});return}
    start,end,err:=recordingWindow(r);if err!=nil{jsonReply(w,400,map[string]string{"error":"invalid_time_range"});return}
    source:=r.URL.Query().Get("source")
    if source!=""&&source!="cloud"{jsonReply(w,409,map[string]string{"error":"sd_not_verified"});return}
    cloud,err:=getCloud(s.source.User.Username());if err!=nil{jsonReply(w,502,map[string]string{"error":"recording_authorization_failed"});return}
    region,_:=s.source.User.Password()
    items:=[]Recording{}
    until:=end
    for page:=0;page<10;page++ {
        params,_:=json.Marshal(map[string]any{"did":s.source.Query().Get("did"),"model":s.source.Query().Get("model"),"doorBell":true,"eventType":"Default","needMerge":true,"sortType":"DESC","region":strings.ToUpper(region),"language":"zh_CN","beginTime":start,"endTime":until,"limit":50})
        raw,e:=cloud.CameraRequest(region,"/common/app/get/eventlist",string(params));if e!=nil{jsonReply(w,502,map[string]string{"error":"recording_list_failed"});return}
        var result struct{Data struct{Continue bool `json:"isContinue"`;Next int64 `json:"nextTime"`;Items []struct{Start int64 `json:"createTime"`;Duration float64 `json:"duration"`;Type string `json:"eventType"`;FileID string `json:"fileId"`;Alarm bool `json:"isAlarm"`} `json:"thirdPartPlayUnits"`} `json:"data"`}
        if json.Unmarshal(raw,&result)!=nil{jsonReply(w,502,map[string]string{"error":"recording_list_invalid"});return}
        for _,rec:=range result.Data.Items {
            if rec.FileID==""||rec.Start<start||rec.Start>=end {continue}
            hash:=sha256.Sum256([]byte("cloud:"+rec.FileID))
            item:=Recording{ID:hex.EncodeToString(hash[:16]),Source:"cloud",Start:rec.Start,Duration:rec.Duration,Event:rec.Type,FileID:rec.FileID,Alarm:rec.Alarm}
            items=append(items,item)
        }
        if !result.Data.Continue||result.Data.Next<=start||result.Data.Next>=until{break}
        until=result.Data.Next
    }
    sort.Slice(items,func(i,j int)bool{return items[i].Start>items[j].Start})
    s.mu.Lock()
    if len(s.records)>2000{s.records=map[string]Recording{}}
    for _,item:=range items{s.records[item.ID]=item}
    s.mu.Unlock()
    jsonReply(w,200,map[string]any{"items":items,"source":"cloud","sd_supported":false})
}

func validRecordingID(id string)bool{if len(id)!=32{return false};_,err:=hex.DecodeString(id);return err==nil}

func (s *recordingStore) find(id string)(Recording,bool){
    if !validRecordingID(id){return Recording{},false}
    s.mu.Lock();defer s.mu.Unlock();item,ok:=s.records[id];return item,ok
}

func (s *recordingStore) prepare(w http.ResponseWriter,r *http.Request){
    if r.Method!="POST"{jsonReply(w,405,map[string]string{"error":"method_not_allowed"});return}
    item,ok:=s.find(r.URL.Query().Get("id"));if !ok{jsonReply(w,404,map[string]string{"error":"recording_not_found"});return}
    ctx,cancel:=context.WithTimeout(r.Context(),90*time.Second);defer cancel()
    if err:=s.download(ctx,item);err!=nil{reason:="recording_download_failed"; for _,known:=range []string{"untrusted_recording_host","recording_not_available","invalid_recording_playlist","invalid_recording_segment","invalid_recording_key","recording_key_failed","invalid_encrypted_recording","invalid_recording_padding","recording_conversion_failed","conversion_moov_missing","conversion_invalid_input","conversion_codec_failed","conversion_format_rejected","recording_write_failed","recording_request_failed","unsupported_recording_encryption"}{if err.Error()==known{reason=known}}; jsonReply(w,502,map[string]string{"error":reason});return}
    jsonReply(w,200,map[string]bool{"ready":true})
}

func (s *recordingStore) clip(w http.ResponseWriter,r *http.Request){
    if r.Method!="GET"&&r.Method!="HEAD"{w.WriteHeader(405);return}
    id:=r.URL.Query().Get("id");if !validRecordingID(id){w.WriteHeader(404);return}
    path:=filepath.Join(s.directory,id+".mp4")
    info,err:=os.Lstat(path);if err!=nil||!info.Mode().IsRegular()||time.Since(info.ModTime())>24*time.Hour{w.WriteHeader(404);return}
    w.Header().Set("Content-Type","video/mp4")
    w.Header().Set("Cache-Control","private, no-store")
    http.ServeFile(w,r,path)
}

func safeCameraAsset(raw string)bool{
    u,err:=url.Parse(raw);if err!=nil||u.Scheme!="https"||u.User!=nil{return false}
    host:=strings.ToLower(u.Hostname())
    for _,suffix:=range []string{".mi.com",".xiaomi.com",".miot.com",".ksyun.com",".ksyuncs.com",".aliyuncs.com"}{if strings.HasSuffix(host,suffix){return true}}
    return false
}

func fetchCameraAsset(ctx context.Context,raw string,limit int64)([]byte,error){
    if !safeCameraAsset(raw){return nil,errors.New("untrusted_recording_host")}
    client:=&http.Client{Timeout:25*time.Second,CheckRedirect:func(req *http.Request,via []*http.Request)error{if len(via)>=3||!safeCameraAsset(req.URL.String()){return errors.New("recording_redirect_rejected")};return nil}}
    req,err:=http.NewRequestWithContext(ctx,"GET",raw,nil);if err!=nil{return nil,errors.New("recording_request_failed")}
    res,err:=client.Do(req);if err!=nil{return nil,errors.New("recording_request_failed")};defer res.Body.Close()
    if res.StatusCode!=200{return nil,errors.New("recording_not_available")}
    data,err:=io.ReadAll(io.LimitReader(res.Body,limit+1));if err!=nil||int64(len(data))>limit{return nil,errors.New("recording_size_limit")}
    return data,nil
}

type recordingSegment struct{URL string; Key string; IV []byte}
type playlist struct{Key string; IV []byte; Segments []recordingSegment}

func parseCameraPlaylist(body []byte)(playlist,error){
    var p playlist
    var sequence uint64
    if !strings.HasPrefix(string(body),"#EXTM3U"){return p,errors.New("invalid_recording_playlist")}
    for _,line:=range strings.Split(string(body),"\n"){
        line=strings.TrimSpace(line)
        if strings.HasPrefix(line,"#EXT-X-MEDIA-SEQUENCE:"){
            value,err:=strconv.ParseUint(strings.TrimPrefix(line,"#EXT-X-MEDIA-SEQUENCE:"),10,64);if err!=nil{return p,errors.New("invalid_recording_sequence")};sequence=value
        }else if strings.HasPrefix(line,"#EXT-X-KEY:"){
            if strings.Contains(line,"METHOD=NONE"){p.Key="";p.IV=nil;continue}
            if !strings.Contains(line,"METHOD=AES-128"){return p,errors.New("unsupported_recording_encryption")}
            p.IV=nil
            for _,part:=range strings.Split(strings.TrimPrefix(line,"#EXT-X-KEY:"),","){
                key,value,_:=strings.Cut(part,"=")
                switch strings.TrimSpace(key){case "URI":p.Key=strings.Trim(value,"\"");case "IV":iv,err:=hex.DecodeString(strings.TrimPrefix(value,"0x"));if err!=nil||len(iv)!=16{return p,errors.New("invalid_recording_iv")};p.IV=iv}
            }
        }else if line!=""&&!strings.HasPrefix(line,"#"){
            if !safeCameraAsset(line)||len(p.Segments)>=128{return p,errors.New("invalid_recording_segment")}
            iv:=append([]byte(nil),p.IV...)
            if p.Key!=""&&len(iv)==0{iv=make([]byte,16);binary.BigEndian.PutUint64(iv[8:],sequence)}
            if p.Key!=""&&!safeCameraAsset(p.Key){return p,errors.New("invalid_recording_key")}
            p.Segments=append(p.Segments,recordingSegment{URL:line,Key:p.Key,IV:iv})
            sequence++
        }
    }
    if len(p.Segments)==0{return p,errors.New("incomplete_recording_playlist")}
    return p,nil
}

func decryptRecording(data,key,iv []byte)([]byte,error){
    if len(key)!=16||len(iv)!=16||len(data)==0||len(data)%16!=0{return nil,errors.New("invalid_encrypted_recording")}
    block,err:=aes.NewCipher(key);if err!=nil{return nil,err}
    out:=make([]byte,len(data));cipher.NewCBCDecrypter(block,iv).CryptBlocks(out,data)
    padding:=int(out[len(out)-1]);if padding<1||padding>16||padding>len(out){return nil,errors.New("invalid_recording_padding")}
    for _,b:=range out[len(out)-padding:]{if int(b)!=padding{return nil,errors.New("invalid_recording_padding")}}
    return out[:len(out)-padding],nil
}

func (s *recordingStore) download(ctx context.Context,item Recording)error{
    if !s.prepareMu.TryLock(){return errors.New("recording_preparation_busy")};defer s.prepareMu.Unlock()
    if ctx.Err()!=nil{return ctx.Err()}
    if err:=os.MkdirAll(s.directory,0700);err!=nil{return err}
    path:=filepath.Join(s.directory,item.ID+".mp4")
    if info,err:=os.Lstat(path);err==nil&&info.Mode().IsRegular()&&info.Size()>1024&&time.Since(info.ModTime())<24*time.Hour{return nil}
    cloud,err:=getCloud(s.source.User.Username());if err!=nil{return errors.New("recording_login_failed")}
    region,_:=s.source.User.Password()
    params,_:=json.Marshal(map[string]any{"did":s.source.Query().Get("did"),"model":s.source.Query().Get("model"),"fileId":item.FileID,"isAlarm":item.Alarm,"videoCodec":"H265"})
    address,err:=cloud.CameraURL(region,"/common/app/m3u8",string(params));if err!=nil{return err}
    body,err:=fetchCameraAsset(ctx,address,1024*1024);if err!=nil{return err}
    p,err:=parseCameraPlaylist(body);if err!=nil{return err}
    keys:=map[string][]byte{}
    work,err:=os.MkdirTemp(s.directory,".prepare-");if err!=nil{return err};defer os.RemoveAll(work)
    output:=filepath.Join(work,"clip.mp4")
    var entries strings.Builder
    total:=0
    for index,segment:=range p.Segments {
        encrypted,e:=fetchCameraAsset(ctx,segment.URL,32*1024*1024);if e!=nil{return e}
        total+=len(encrypted);if total>128*1024*1024{return errors.New("recording_size_limit")}
        plain:=encrypted
        if segment.Key!=""{
            key:=keys[segment.Key]
            if key==nil{key,e=fetchCameraAsset(ctx,segment.Key,32);if e!=nil||len(key)!=16{return errors.New("recording_key_failed")};keys[segment.Key]=key}
            plain,e=decryptRecording(encrypted,key,segment.IV);if e!=nil{return e}
        }
        name:=fmt.Sprintf("%04d.media",index)
        if e=os.WriteFile(filepath.Join(work,name),plain,0600);e!=nil{return errors.New("recording_write_failed")}
        fmt.Fprintf(&entries,"file '%s'\n",name)
    }
    list:=filepath.Join(work,"segments.txt")
    if err=os.WriteFile(list,[]byte(entries.String()),0600);err!=nil{return errors.New("recording_write_failed")}
    cmd:=exec.CommandContext(ctx,"ffmpeg","-nostdin","-loglevel","error","-y","-protocol_whitelist","file,pipe","-format_whitelist","concat,mov,mpegts,h264,hevc","-f","concat","-safe","1","-i",list,"-map","0:v:0","-map","0:a?","-c:v","copy","-c:a","aac","-movflags","+faststart",output)
    var diagnostic bytes.Buffer
    cmd.Stdout=io.Discard;cmd.Stderr=&diagnostic
    if err=cmd.Run();err!=nil{return errors.New(recordingConversionReason(diagnostic.String()))}
    info,err:=os.Stat(output);if err!=nil||info.Size()<1024{return errors.New("recording_file_invalid")}
    if err=os.Chmod(output,0600);err!=nil{return err}
    if err=os.Rename(output,path);err!=nil{return err}
    s.prune(item.ID)
    return nil
}

func (s *recordingStore) prune(keep string){
    entries,_:=os.ReadDir(s.directory)
    type cached struct{name string;size int64;at time.Time}
    files:=[]cached{};var total int64
    for _,entry:=range entries{if entry.IsDir()||!strings.HasSuffix(entry.Name(),".mp4")||!validRecordingID(strings.TrimSuffix(entry.Name(),".mp4")){continue};info,e:=entry.Info();if e==nil&&info.Mode().IsRegular(){files=append(files,cached{entry.Name(),info.Size(),info.ModTime()});total+=info.Size()}}
    sort.Slice(files,func(i,j int)bool{return files[i].at.Before(files[j].at)})
    count:=len(files)
    for _,file:=range files{if file.name==keep+".mp4"{continue};if count>5||total>128*1024*1024||time.Since(file.at)>24*time.Hour{if os.Remove(filepath.Join(s.directory,file.name))==nil{count--;total-=file.size}}}
}


// Return fixed reason codes only; never expose media content, paths or FFmpeg text.
func recordingConversionReason(message string)string{
    for _,item:=range []struct{match,code string}{
        {"moov atom not found","conversion_moov_missing"},
        {"Invalid data found","conversion_invalid_input"},
        {"not on whitelist","conversion_format_rejected"},
        {"Could not find codec parameters","conversion_codec_failed"},
    }{if strings.Contains(message,item.match){return item.code}}
    return "recording_conversion_failed"
}
