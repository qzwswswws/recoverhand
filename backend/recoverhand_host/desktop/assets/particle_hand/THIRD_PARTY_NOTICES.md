# 第三方资产说明

## Leap Motion rigged hand

- 项目：`leapmotion/leapjs-rigged-hand`
- 资产：`models/Game Quality Hand/Handsolo/Leapmotion_Handsolo_Rig_Right.json`
- 来源：https://github.com/leapmotion/leapjs-rigged-hand
- 许可证：Apache License 2.0
- 本地许可证副本：`LICENSE-leapmotion-Apache-2.0.txt`

本项目保留了原始模型数据 `hand-model-source.json`，并通过 `convert-hand-model.mjs` 将其转换为浏览器用的网格与粒子绑定数据 `hand-particle-data.js`。转换数据包含网格顶点、骨骼层级、蒙皮权重，以及面积加权采样得到的三角面索引和重心坐标；手势位置由浏览器在每一帧通过骨骼蒙皮计算，不再保存张手、中间和握拳三组离散位置。

[事实] 上游仓库页面标明 Apache-2.0 license；本说明不替代许可证正文。
