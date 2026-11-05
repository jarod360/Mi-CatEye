# 开发与验证

源码不包含账号、设备地址、实体 ID、签名链接、刷机镜像或私有配置。不要将现场 `.local`、`.storage`、备份或录像复制进仓库。

## 依赖与测试

使用匹配 Home Assistant 2026.10 的 Python 3.14 环境，安装 HA、`requirements-test.txt` 所列测试依赖。

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin tests -q
```

已通过的集成行为测试覆盖授权校验、单会话、播放认证、录像字段过滤/时间范围/Range限制、音量恢复、指定手机弹窗和空目标不广播。浏览器实测与单元测试是两类证据，不可互相替代。

## 重建媒体核心与安装包

```sh
git clone https://github.com/AlexxIT/go2rtc.git work/go2rtc
git -C work/go2rtc checkout 7c05066c90ab6ad1fccb506d5f0408aa31ebe60f
python tools/package_mi_cateye.py --go go --upstream work/go2rtc
python tools/verify_mi_cateye_package.py
```

脚本校验固定上游提交与完整 `runtime.patch`（验证码恢复、通话协议、活动 producer 防护与音频封装）、应用明确列出的叠加文件、执行相关 Go 测试，编译 Linux amd64/arm64，生成 SHA256 和依赖许可证清单。输出在 `outputs/`。请使用干净的固定版本检出，不把现场研究目录直接当成构建输入。构建包会先生成受版本管理的二进制名称，避免替换正在运行的可执行文件。

需要将源码包带到 Linux HA 执行位受限的文件系统时，确认 `bin/mi-cateye-media-linux-*` 有执行权限。发布包会自行校验媒体核心 SHA256，缺失或不匹配不会绕过校验运行。

rc1 是候选版本。2026-10-29 用户已实际按铃确认手机前台弹窗和图标60秒复位正常；后续采样电视/小爱出首帧并自动结束，音量恢复。此前报告的偶发卡顿仍需长期验证，不应将单轮通过写为长期稳定。

## 0.2.0b2 验证

运行 `node tests/recording-event-labels.cjs` 核对组合事件文案。多摄像机入口改动只在 HA 集成层；本版保留 rc2 已校验媒体核心，不混入 SD 或对讲实验补丁。未对旧偶发故障作已修复承诺。

## 0.2.0b4 验证

本版改用已验证对讲协议的媒体核心。Python 全套测试之外执行 `node tests/manual-battery-notice.cjs`；接收器在自己的构建目录执行 `testDebugUnitTest`。实机结论及未部署的小修订见 [交接](TALK_HANDOFF_2026_11_05.md)，不要把单测通过写成 TV 声音清晰度验收。

构建工具会使用去符号参数重新生成媒体核心，重新生成的散列会与现场调试构建不同；必须连同新 `bin/manifest.json` 分发，不能沿用旧散列。
