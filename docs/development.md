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

脚本校验固定上游提交与精确 captcha 补丁、测试三个 Go 包、编译 Linux amd64/arm64、生成 SHA256 和依赖许可证清单。输出在 `outputs/`。构建包会先生成受版本管理的二进制名称，避免替换正在运行的可执行文件。

需要将源码包带到 Linux HA 执行位受限的文件系统时，确认 `bin/mi-cateye-media-linux-*` 有执行权限。发布包会自行校验媒体核心 SHA256，缺失或不匹配不会绕过校验运行。

rc1 是候选版本；前台手机自动弹窗和卸载旧链路后的完整三端体验仍应实机验收。不要将未通过的项目写成已完成。
