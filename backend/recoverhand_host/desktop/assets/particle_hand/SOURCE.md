# P03-E 粒子手来源

- 来源项目：`D:/workspace2/OCnotebook/projrct/project_2026_3rdseason/MIdemo`
- 来源包：`VH-MI-RTF/P03E-Developer-Edition-v1.0.0-20260901/手部粒子动画原型-P03E开发版`
- 复制日期：2026-09-11
- 原始 `index.html` SHA-256：`DA384A9340AD58517266CA5185692B218EEE55D532CFCE002A9D2CB332A2E117`
- `hand-particle-data.js` SHA-256：`1722D8A7A8AD36D398DB65AE3FD7A4DB224C296DB9516FFA9FD4D86527640212`

`renderer.html` 由来源包的 `index.html` 派生。RecoverHand 嵌入模式隐藏开发控件、禁用画布鼠标交互并调整背景色；同时针对约 300–400 px 宽的训练页卡片启用性能档：渲染像素比上限为 1、关闭 MSAA 与 `preserveDrawingBuffer`、使用 RGBA8 离屏纹理、将辉光模糊从三轮减为一轮，并停止逐帧刷新已隐藏的开发控件。独立打开的开发页面仍沿用原高画质参数。骨骼、蒙皮、12,000 个手部粒子、接触约束、粒子数据和 JavaScript 控制 API 均未删减。

手部模型资产来自 `leapmotion/leapjs-rigged-hand`，按 Apache License 2.0 使用。分发时必须保留本目录中的许可证和第三方声明。
