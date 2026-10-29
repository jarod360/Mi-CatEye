# 许可说明

本仓库是混合许可分发，不能将整体标记为 MIT，也不是官方集成。

- 本项目新增的 HA 接入与构建胶水、媒体核心叠加文件：MIT，见 `LICENSE-MIT`。
- `custom_components/mi_cateye/vendor/`：来自 Xiaomi Home 的精简 SDK，保留 `LICENSE-XIAOMI.md`。仅限其许可允许的非商业 Home Assistant 用途；其商标及其他限制继续适用。
- go2rtc 及编译进媒体核心的依赖：保留原始许可，见 `custom_components/mi_cateye/licenses/` 与对应 SOURCE 清单。
- 接收器补丁涉及的上游：见 `receiver-patches/LICENSE.upstream.txt`。

上游来源、版本与文件散列见各 SOURCE.json。重新分发时必须保留这些许可、版权和免责声明；此说明不替代任何上游许可。
