# Maya 2025 移植可行性分析与分阶段计划

对本仓库 19 个节点组与材质管线移植到 Autodesk Maya 2025 的完整评估。**结论先行：可行**，工作量集中在数据通路与表面标定，不在数学本身。

> 状态：分析与计划文档（P0 交付物），尚未开始移植实施。

## 1. 结论摘要

| 层 | 内容 | 移植难度 | 说明 |
| --- | --- | --- | --- |
| ① 数学层 | HemiOct 解码、XY 累积、矩阵插值、迷彩坐标运算 | **低** | 纯标量/向量数学，可机械翻译为 Arnold/Maya 工具节点，或用 OSL 精确复刻 |
| ② 纹理层 | 贴图采样、多 UV、色彩空间、Alpha 语义 | **中** | 节点一一对应，但 sRGB/Raw 与"Alpha 是数据不是透明度"必须逐图核对 |
| ③ 数据通路 | CORNER 域属性（v5/v7/v10 的 TBN、矩阵、valid） | **高** | Blender 面角属性没有直接等价物，推荐导入期离线烘焙（见 §5） |
| ④ 表面层 | Principled BSDF → aiStandardSurface | **中高** | 参数可映射但能量模型不等价（SSS 方法、视图变换），需按基线重新对拍 |

数学层在原项目中就以"节点输出 vs 独立 Python 数学"对拍验证（误差 1e-5 ~ 1e-8），这个方法论直接迁移：**数值层可脱离 Blender 复现**，是移植可行性的核心依据。

## 2. 环境事实（已核实）

- Maya 2025：Python 3.11（本机已安装 `D:\Maya2025`）
- 官方配套渲染器：MtoA 5.4.0 = Arnold 7.3.0.0 核心（GPU/OptiX 8 重构）；**本机当前未安装 MtoA**，做原型验证前需另装
- 已装组件：MayaUSD、LookdevX（MaterialX 工作流入口）
- `scripts/cast_spec.py` 依赖的 `cast.py` 是纯标准库解析器，可在 Maya 2025 的 Python 3.11 中**零改动**运行——这是跨 DCC 共享规格的现成接口（P0 已就绪）

## 3. 可复用资产盘点

| 资产 | Maya 可复用性 |
| --- | --- |
| `scripts/cast_spec.py`（cast→spec.json） | 直接运行，输出同一份规格 JSON |
| `scripts/profiles.json`（profile 规则与控制值） | 直接读取，控制值是渲染器无关的美术参数 |
| `vendor/cast_addon/cast.py` | 直接 import（几何解析 API 相同） |
| `vendor/cast_addon/import_cast.py` | **不可复用**（bpy 专属），需独立 Maya 几何导入器（P1） |
| 19 个节点组的连线与公式 | 作为移植的**规格说明**（本文档 §4 映射表），不以 `.blend` 形式迁移 |
| 验证方法论（数值探针、单因素对照） | 直接迁移 |

## 4. 节点四层映射表（Blender → Maya 2025 / Arnold）

### ① 数学层

| Blender 节点（项目实际用法） | Maya / Arnold 对应 |
| --- | --- |
| Math（ADD/SUB/MUL/DIV/ABS/MAX/COMPARE + `use_clamp`） | `aiMath`（带 clamp 参数）或 `multDivide` / `addMinusAverage` / `condition` |
| VectorMath（NORMALIZE/SCALE/ADD/MUL/SUB/**FRACTION**） | `aiVectorMath`（normalize/scale/add/multiply/subtract/fraction 各 mode） |
| Separate / Combine Color（RGB） | `colorSplit` / `colorCombine`（或 Arnold `aiSeparateColor` 系） |
| Separate / Combine XYZ | `aiSeparateVector` / `aiCombineVector` |
| MixRGB（MIX / MULTIPLY） | `blendColors`（Maya）或 `aiBlendColors` |
| VectorRotate（Z_AXIS 迷彩旋转） | `aiVectorMath` rotate 或自建绕 Z 旋转矩阵工具节点 |
| Vector Transform（Normal，Object→World，v10） | `aiVectorTransform` |
| Value 常量（v5 开关） | 常量 `float` 属性 / `condition` |
| 节点组封装（19 组） | Maya `network` 节点封装，或 OSL 单 shader 封装 |

**注意**：`FRACTION` 对负数的语义（Blender: `x - floor(x)`，恒 ≥0）与 Arnold fraction 一致，但迁移后必须用负输入单测确认；MixRGB 的 blend space 与 `blendColors` 的 alpha 插值方向要对拍。

### ② 纹理层

| Blender | Maya 2025 / Arnold |
| --- | --- |
| Image Texture（sRGB / Non-Color） | `file` 节点：colorSpace = `sRGB` / `Raw`（**逐图核对**） |
| `alpha_mode = CHANNEL_PACKED` | 关闭 premultiply、`alphaIsLuminance=off`；Alpha 作为数据通道直读 |
| UV Map（按名取 UV，`UVMap` / `UVMap.001` / 烘焙 UV） | `place2dTexture.uvSet` 指定同名 UV 集 |
| Texture Coordinate → Object（迷彩 Empty 锚点） | `place2dTexture` 投影变换，或 utility 节点按锚点矩阵复刻（世界 X/Z 平面） |
| Normal Map（Tangent + UV） | `aiNormalMap`（切线空间，需网格切线或 UV 导数） |

这是移植后**最容易出错的单点**：Blender 的 `Non-Color` ≈ Maya `Raw`；给数据贴图套 sRGB 会同时破坏法线与粗糙度，必须沿用项目的"逐图色彩空间断言"做验收。

### ③ 数据通路（最大难点）

| Blender 机制 | 项目用途 | Maya 替代（对应 §5 方案） |
| --- | --- | --- |
| Attribute 节点读 **CORNER** FLOAT_VECTOR 属性 | v5 `codv5_*_row0/1/valid`、v7 `v7_matrix_row0/1`、v10 `codv10_T/N/sign/valid` | 导入期离线烘焙（推荐）→ 顶点色 / 切线法线 / face-vertex user data |
| MixShader（底层 Shader × coverage） | 迷彩覆盖层 | `aiMixShader` 直接对应 |
| Geometry.Backfacing（v10 背面回退） | 保守回退 | Arnold `backfacing` 状态量 |
| 节点组资产 | 19 组复用 | `network` 节点 + 脚本封装；共享语义靠命名保持 |

**保留原项目的关键校验**：v7/v10 明确"缺属性时不做单位矩阵回退"——移植后同样要在导入期报错而不是静默降级。

### ④ 表面层（Principled → aiStandardSurface）

| Principled（项目实际用到的） | aiStandardSurface | 等价性 |
| --- | --- | --- |
| Base Color / Metallic / Roughness / IOR | base / metalness / specular_roughness / specular_IOR | 直接映射 |
| Normal | normal（经 `aiNormalMap`） | 直接映射 |
| Subsurface（RANDOM_WALK_SKIN，Weight/Scale/Radius） | subsurface + `randomwalk` 方法 | **方法相近但半径/缩放语义不同，需按基线标定** |
| Sheen / Coat / Transmission | sheen / coat / transmission | 参数映射，能量响应不同 |
| Alpha（发片 4a 覆盖） | opacity + Opaque 透明深度设置 | 需对齐 Cycles 的 transparent max bounces=16 行为 |
| 视图变换 AgX | Arnold/OCIO 视图变换 | **不等价**；数值层用 Raw/Standard 视图对拍，beauty 层声明差异 |

未使用项（Emission 诊断除外）：各向异性、薄膜、Specular Tint 等两引擎都未启用，不增加移植面。

## 5. CORNER 数据通路：三方案对比

| 方案 | 做法 | 保真度 | 成本 | 结论 |
| --- | --- | --- | --- | --- |
| a | Arnold face-vertex user data / 索引数组 | 高（逐面角） | 数据通路复杂，Maya 端写入与寻址都要自建 | 备选 |
| b | Maya colorSet per-vertex | 低（面角精度丢失，硬边处接缝错误） | 最低 | 否决：v7/v10 的意义就在逐面角 |
| **c（推荐）** | **导入期离线烘焙**：在 Maya 导入器里用 Python 预计算每面角的 TBN/矩阵，烘进顶点切线/法线或拆点网格 | 高 | 导入器一次实现，着色侧走标准切线空间路径 | **主路径** |

依据：v5/v7/v10 的全部 CORNER 值都能从 cast 几何**离线计算**（原项目就是这么做的）——着色器运行时读属性只是 Blender 侧的实现选择，不是本质。烘焙后保留"数据缺失=报错"的导入期校验。混合符号面（武器 12 个）沿用原策略回退原法线。

## 6. 三条移植路径对比

| 路径 | 内容 | 优点 | 缺点 | 定位 |
| --- | --- | --- | --- | --- |
| **A. Arnold 原生节点图 + Maya Python 构建** | 脚本按 spec.json 在 Hypershade 里搭建 `file`/`aiMath`/`aiVectorMath`/`aiNormalMap`/`aiStandardSurface` 网络 | 无新工具链依赖、可视化可编辑、与 Blender 构建器结构同构（复用 autobuild 设计） | 数学图冗长；逐节点对拍要靠脚本 | **推荐主干** |
| **B. OSL 写数学核心** | 解码/XY 累积/矩阵插值/迷彩坐标写成 `.osl`，经 Arnold `aiOSL` 加载 | 与原公式逐行对应、可脱离 DCC 单测、数学层一处维护 | 需要 OSL 编译/搜索路径配置；节点图内不可见 | **推荐用于数学层**（与 A 混合：贴图+表面用 A，纯数学用 B） |
| C. MaterialX / LookdevX | 标准 PBR 图用 MaterialX 表达并跨 DCC 交换 | Maya 2025 原生 LookdevX 支持、标准化 | 自定义位级语义（bit29 符号不插值、frac 语义、参数平方）超出标准图元；CORNER 数据不在其表达范围 | **仅作互操作补充，不作主力** |

**推荐组合**：A 为骨架 + B 承载数学核心。C 仅在未来需要与其他 DCC/USD 流程交换标准 PBR 部分时使用。

## 7. 验证策略

延续原项目方法论，分两层：

1. **数学层（严格）**：utility AOV / 分几何 pass 输出中间值，对拍独立 Python 参考实现，容差 1e-5（与原 Cycles EXR 探针同级）；负输入、缺属性、混合符号面等边界各设探针
2. **Beauty 层（声明差异）**：对拍 Blender Cycles 基线，明示 SSS 方法与视图变换不等价——达到"同参数受控对照"而非逐像素一致；**不以游戏画面为基准**（原项目同样声明缺游戏同画面真值）

## 8. 分阶段移植计划（P0–P6）

| 阶段 | 内容 | 验收标准 |
| --- | --- | --- |
| **P0** ✅ | 共享 `cast_spec.py` + `profiles.json` + 本文档 | spec.json 在独立 Python（含 Maya 3.11）可生成并通过资产对拍 |
| **P1** | Maya cast 几何导入器：顶点/UV（双 UV）/法线/面材质分配 + `source_asset` 等价标记 | 10+60+27 网格导入，材质按 cast 路径分配，UV 名称保留 |
| **P2** | 武器/generic PBR Arnold 基础网络（A 路径）+ NOG 解码（B 路径 OSL 或 A 路径原生） | 数学层探针对拍 ≤1e-5；色彩空间断言通过；受控渲染对照 |
| **P3** | 人物 profile（SSS/发片 opacity/眼球 transmission）+ profile 规则复用 | 控制值应用正确；人物分 profile 渲染对照；差异边界文档化 |
| **P4** | 法线栈 v4/v7：离线烘焙角点矩阵 → 顶点数据通路（方案 c） | 缺属性报错校验保留；探针对拍 v4/v7 公式 |
| **P5** | v10 QTangent 框架：离线算 `codv10_T/N/sign/valid` → 烘焙切线/法线；混合符号面回退 | 97 网格数据核对；TBN 输出对拍；回退行为一致 |
| **P6** | 迷彩层（坐标投影 + 三路贴图 + aiMixShader）+ 端到端验证 harness | 角色表接线断言；Strength=0 关闭回退逐像素一致 |

依赖关系：P1 → P2 → {P3, P4} → P5 → P6；每阶段独立可验收，可随时停在阶段边界。

## 9. 明确不在范围内

- 动态蒙皮 / 骨骼变形材质通路
- 游戏同画面比对（原项目也未完成，缺真值）
- MaterialX 全图直迁
- 修改或分发 MtoA/Arnold 本体（需自备许可与安装）

## 参考

- 四层节点清单与 Blender 侧实现：`shaders/ez4cywa_COD_Shader_Library.blend`、教程总览 [TUTORIALS_SUMMARY.md](TUTORIALS_SUMMARY.md)
- 角色/控制值：[AUTO_MATERIALS.md](AUTO_MATERIALS.md) 与 `scripts/profiles.json`
- Arnold 法线映射：[Normal Map（Arnold Core）](https://help.autodesk.com/cloudhelp/ENU/AR-Core/files/ac-shading/ac-utility-shaders/arnold_core_ac_normal_map_html.html)
- Maya 2025 配套 Arnold：[Arnold for Maya 5.4.0 What's New](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-WhatsNew/files/GUID-3E5E4346-3281-491D-B7AF-1C60B01E8AC4.htm)
- MayaUSD MaterialX 支持：[maya-usd MaterialX.md](https://github.com/Autodesk/maya-usd/blob/dev/doc/MaterialX.md)
