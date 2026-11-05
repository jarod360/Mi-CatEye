# 安防宽卡候选

实现位于 [`frontend/mi-security-card.js`](../frontend/mi-security-card.js)。这是独立验证的候选，尚未加入安装包或自动切换用户主题；当前部署顺序仍是先完成猫眼存储卡回放，再合并两个主题。

卡片横跨两列，旧主题高度 178px，弧光高度 170px。默认显示餐厅、阳台 SVG 场景封面及名称，不取快照、不预加载视频。点击播放同时观看两路，停止或离开即释放；点击单路放大时保留 iframe。录像按钮先停止实时画面，再进入对应设备存储卡回看。暂不包含云台、麦克风或对讲。

手动评估候选时，将 JS 放在 HA `www` 目录并添加 module 类型 Lovelace 资源，然后使用以下结构。设备标识必须换成集成选项中实际选中的摄像机 DID，示例 `1`、`2` 是占位值。原生 grid-layout 以外的布局需要按自己的网格设置宽度。

```yaml
type: custom:mi-security-card
variant: arc # classic 为旧主题尺寸
view_layout:
  grid-column: span 2
cameras:
  - device: "1"
    name: 餐厅
    scene: dining
  - device: "2"
    name: 阳台
    scene: balcony
```

候选使用当前 HA 会话签发短期路径，沿用集成既有视频入口。默认静音；不保存账号和视频地址，也不创建第二套接收客户端。测试涵盖手机/桌面布局、默认零请求、晚到签名取消、关闭释放以及真实两路解码。仅已验证的两款摄像机可作为当前部署依据。
