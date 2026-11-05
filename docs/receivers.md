# 接收器

电视与小爱通过局域网 HTTP 接收通知。当前已验证的是基于 PiPup 的定制接收器，不代表任意同名应用均兼容。

- 电视：端口 7980，`POST /notify`，原始 H.265、EXO、软件 HEVC 选择字段；60 秒后关闭弹窗，节目继续播放。
- 小爱：端口 7979，`/notify`、`/volume`、`/power`、`/state`；视频按 854×480 居中裁切适配 800×480 屏幕。提示音临时 80%，播完恢复原音量；用户手动调整时不覆盖。保留原生首页、语音与音乐环境。
- 接收器防火墙仅允许 HA 主机和 localhost，不要直接向公网暴露。

当前完整定制差异见 `receiver-patches/pipup-0.30.1-cateye.patch`，固定上游版本见同目录 `SOURCE.json`；保留原始许可。旧 `pipup-0.29.2-hevc-local.patch` 仅是历史片段，不应叠加到新补丁。仓库不附签名私钥或设备镜像，也不提供一键刷机。

## 重建单客户端

```sh
git clone https://github.com/mhoogenbosch/PiPup.git PiPup
git -C PiPup checkout b95ecc7b81e7190ddd201a415152d39e17ec376c
git -C PiPup apply /absolute/path/to/Mi-CatEye/receiver-patches/pipup-0.30.1-cateye.patch
cd PiPup
# JDK 17，Android SDK 35 / Build Tools 35.0.0；配置自己的 SDK 路径。
./gradlew testDebugUnitTest assembleDebug -PreceiverApplicationId=nl.rogro82.pipup -PreceiverPort=7979
# TV 单独构建；两个设备无需各自安装两份客户端。
./gradlew testDebugUnitTest assembleDebug -PreceiverApplicationId=nl.rogro82.pipup.doorbelltest -PreceiverPort=7980
```

PowerShell 下将整个 `-PreceiverApplicationId=...` 参数加引号。正式分发请使用自己的持久签名密钥，通过 `KEYSTORE_FILE`、`KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD` 环境变量配置后构建 `assembleRelease`；不要提交密钥。默认 debug 构建使用本机 Android 调试密钥，无法覆盖不同签名的原版。迁移前先在电脑保存原 APK 和配置，不要在小爱存放历史安装包。

设备需允许悬浮窗；只有使用实时通话才需麦克风权限。权限页完成会自动退出；维护设置可显式通过 `show_settings=true` 打开。定制版禁用上游自动升级提示和安装入口，维护者负责跟踪上游修复。

`GET /state` 返回 `doorbellTalk=true` 后 HA 才发送两个控制按钮与短期授权入口。按接通才申请麦克风，挂断/离开/超时释放；男声回复无需开启麦克风。TV 遥控器选好短句按确认焦点直达发送，还需再确认一次才发送。最新代码增加通话期间的临时音频焦点压低请求，结束释放，不直接改全局音量；实际节目是否遵循音频焦点需要实机确认。

协议、安全边界及实机进度见 [交接](TALK_HANDOFF_2026_11_05.md)。

手机不需要上述接收器。HA Companion 接收通知，点击进入 `/mi-cateye`；前台弹窗需 Browser Mod 注册的目标手机 ID。集成选项留空 Browser ID 时不弹窗，不广播给其他浏览器。
