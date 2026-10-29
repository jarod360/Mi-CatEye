// SPDX-License-Identifier: MIT
package xiaomi

import (
    "bytes"
    "crypto/aes"
    "crypto/cipher"
    "net/http/httptest"
    "os"
    "path/filepath"
    "strings"
    "testing"
    "time"
)

func TestRecordingWindowBoundedAndWrongSourceRejected(t *testing.T){
    for _,query:=range []string{"","?start=1&end=2","?start=1793200000000&end=1793400000000"}{
        if _,_,err:=recordingWindow(httptest.NewRequest("GET","/"+query,nil));err==nil{t.Fatal("invalid window accepted")}
    }
    if _,_,err:=recordingWindow(httptest.NewRequest("GET","/?start=1793200000000&end=1793286399999",nil));err!=nil{t.Fatal(err)}
    if validRecordingID("../../secret")||validRecordingID(strings.Repeat("g",32)){t.Fatal("unsafe recording ID")}
}

func TestCameraPlaylistRejectsLocalAndUnexpectedEncryption(t *testing.T){
    good:=[]byte("#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"https://app-processor.smartcamera.api.io.mi.com/key\",IV=0x00000000000000000000000000000000\n#EXTINF:2.0,\nhttps://app-processor.smartcamera.api.io.mi.com/part\n#EXT-X-ENDLIST\n")
    p,err:=parseCameraPlaylist(good);if err!=nil||len(p.Segments)!=1||len(p.IV)!=16{t.Fatal("valid playlist rejected")}
    for _,replacement:=range []string{"http://127.0.0.1/secret","https://evil.example/secret","file:///etc/passwd"}{
        bad:=bytes.ReplaceAll(good,[]byte("https://app-processor.smartcamera.api.io.mi.com/part"),[]byte(replacement))
        if _,err=parseCameraPlaylist(bad);err==nil{t.Fatal("unsafe media URL accepted")}
    }
    if safeCameraAsset("https://mi.com.evil.example/a")||safeCameraAsset("https://user:pass@a.mi.com/a"){t.Fatal("unsafe host accepted")}
}

func TestRecordingAESPaddingAndTruncation(t *testing.T){
    key,iv:=bytes.Repeat([]byte{2},16),make([]byte,16)
    plain:=[]byte("transport stream bytes")
    padding:=16-len(plain)%16; padded:=append(bytes.Clone(plain),bytes.Repeat([]byte{byte(padding)},padding)...)
    block,_:=aes.NewCipher(key);encrypted:=make([]byte,len(padded));cipher.NewCBCEncrypter(block,iv).CryptBlocks(encrypted,padded)
    got,err:=decryptRecording(encrypted,key,iv);if err!=nil||!bytes.Equal(got,plain){t.Fatal("recording decryption failed")}
    if _,err=decryptRecording(encrypted[:len(encrypted)-1],key,iv);err==nil{t.Fatal("truncated segment accepted")}
    encrypted[len(encrypted)-1]^=0xff
    if _,err=decryptRecording(encrypted,key,iv);err==nil{t.Fatal("invalid padding accepted")}
}

func TestPlaylistRetainsEachSegmentsKeyAndIV(t *testing.T){
    body:=[]byte("#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:7\n#EXT-X-KEY:METHOD=AES-128,URI=\"https://x.mi.com/key1\"\nhttps://x.mi.com/a\n#EXT-X-KEY:METHOD=AES-128,URI=\"https://x.mi.com/key2\",IV=0x00000000000000000000000000000003\nhttps://x.mi.com/b\n")
    p,err:=parseCameraPlaylist(body);if err!=nil||len(p.Segments)!=2{t.Fatal("playlist failed")}
    if p.Segments[0].Key==p.Segments[1].Key||p.Segments[0].IV[15]!=7||p.Segments[1].IV[15]!=3{t.Fatal("segment encryption state overwritten")}
}

func TestPruneOnlyOwnedMP4AndPreservesSelectedClip(t *testing.T){
    directory:=t.TempDir();s:=recordingStore{directory:directory}
    keep:=strings.Repeat("a",32);old:=strings.Repeat("b",32)+".mp4"
    os.WriteFile(filepath.Join(directory,keep+".mp4"),[]byte("current"),0600)
    os.WriteFile(filepath.Join(directory,old),[]byte("old"),0600)
    os.WriteFile(filepath.Join(directory,"user-video.mp4"),[]byte("unrelated"),0600)
    ago:=time.Now().Add(-25*time.Hour);os.Chtimes(filepath.Join(directory,old),ago,ago)
    s.prune(keep)
    if _,err:=os.Stat(filepath.Join(directory,old));!os.IsNotExist(err){t.Fatal("expired owned file retained")}
    for _,name:=range []string{keep+".mp4","user-video.mp4"}{if _,err:=os.Stat(filepath.Join(directory,name));err!=nil{t.Fatal("unrelated or selected file removed")}}
}
