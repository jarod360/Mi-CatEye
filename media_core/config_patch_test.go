package main

import (
 "encoding/json"
 "testing"
 "github.com/AlexxIT/go2rtc/pkg/yaml"
)

func TestLoginConfigMustUseBlockYAML(t *testing.T) {
 old := []byte(`{"streams":{},"xiaomi":{}}`)
 broken,err := yaml.Patch(old,[]string{"xiaomi","123"},"test-token")
 if err!=nil { t.Fatal(err) }
 var first map[string]any
 if json.Unmarshal(broken,&first)==nil { t.Fatal("expected JSON+YAML legacy incompatibility") }
 good,err := yaml.Patch([]byte("streams: {}\n"),[]string{"xiaomi","123"},"test-token")
 if err!=nil { t.Fatal(err) }
 var cfg struct { Xiaomi map[string]string `yaml:"xiaomi"` }
 if err=yaml.Unmarshal(good,&cfg); err!=nil || cfg.Xiaomi["123"]!="test-token" { t.Fatal("block YAML did not preserve login") }
}
