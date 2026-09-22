# ez4cywa-cod-blender-shaders

**从《使命召唤》材质逆向研究中提炼的可复用 Blender 节点组库**，附中文教程总览。
**Reusable Blender node groups distilled from a reverse-engineering study of Call of Duty materials, with a Chinese tutorial guide.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Blender](https://img.shields.io/badge/Blender-5.2.2%20LTS-orange)](https://www.blender.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)](#)

---

## 这是什么

本项目源自一个基于《使命召唤：现代战争》导出资产的材质研究工程：从本地游戏程序逆向（DXIL 反汇编）、贴图通道分析到真实几何切线框架恢复，逐版本沉淀出一套可复用的 Blender 节点组。

这里是该研究的**干净开源子集**：

- ✅ **21 个自包含节点组**——全部合并进单一 `.blend` 文件，无贴图依赖、无外部路径、开箱即用
- ✅ **cast 材质自动加载**——根据 `.cast` 文件中的材质路径与贴图槽位，自动生成接好节点组的武器/人物/迷彩材质并赋予网格，见 [docs/AUTO_MATERIALS.md](docs/AUTO_MATERIALS.md)
- ✅ **资产浏览器友好**——所有节点组已标记为 Blender 资产并打好分类标签，追加后直接在 Asset Browser 里筛选
- ✅ **经过数值验证**——各版本交付均附带 Cycles 32 位线性 EXR 探针，误差普遍在 1e-5 ~ 1e-8 量级
- ✅ **中文教程总览**——16 篇教程的知识地图与阅读路径，见 [docs/TUTORIALS_SUMMARY.md](docs/TUTORIALS_SUMMARY.md)

❌ 不包含任何游戏原始素材：无贴图、无模型、无提取内容。节点组中的参数是研究候选值，不代表游戏运行时常量。

## 节点组目录

在 Blender 中 `File → Append` 打开 `shaders/ez4cywa_COD_Shader_Library.blend`，或将其添加到资产库后直接拖入节点编辑器。

### 解码 Decode

| 节点组 | 功能 |
| --- | --- |
| `COD_Decode_HemiOct_NOG_v1` | 半八面体 NOG 法线解码：G/Alpha 联合编码 → 切线空间法线（x=G+A−1, y=G−A, z=1−\|x\|−\|y\|） |
| `COD_Game_NOG_Decode_v2` | v2 NOG 解码：按 DXIL 证据先做 G/A 编码前缩放与 R 通道线性调整，再重建 Z |

### 迷彩 Camo

| 节点组 | 功能 |
| --- | --- |
| `COD_Camo_Coordinates_v1` | 迷彩投影坐标：按 Empty 物体或 UV 生成可平移/旋转/平铺的图案坐标 |
| `COD_Camo_Layer_v1` | 迷彩图层：遮罩混合 + 覆盖率控制，`Strength=0` 一键关闭回退原 Shader |
| `COD_Game_Camo_UV_v2` | 两级缩放、旋转、周期平移的迷彩 UV 坐标组（严格按游戏程序运算顺序） |
| `COD_Game_Camo_Color_v3` | v3 迷彩颜色：真实普通分支 `L = SampleColor × c × c` 的参数平方数学 |
| `COD_Camo_Layer_v3` | v3 迷彩图层：底纹、重复文字与胶带贴纸三层分离控制，独立定位与露底 |

### 法线 Normal

| 节点组 | 功能 |
| --- | --- |
| `COD_Game_NormalXY_Layer_v4` | 法线 XY 逐层累积：显式方向矩阵 + 加法/覆盖两种模式，可串联多实例 |
| `COD_Game_NormalXY_Finish_v4` | 法线 XY 收尾：二次近似 `z = 1 − 0.6(x²+y²)` 重建 Z 并归一化，只接一次 |
| `COD_Corner_Matrix_Normal_v7` | 压缩三角形解码的角点法线：符号幅度差值 + 跨页寻址 + 角点插值 |

### 几何 Basis / Frame

| 节点组 | 功能 |
| --- | --- |
| `COD_Packed_Matrix_RGBA_v5` | 原始 RGBA 矩阵解包：UV 方向基矩阵行输出与失效检测 |
| `COD_Matrix_Linear_Interpolate_v6` | 分页几何矩阵的三顶点线性插值（插值后不归一化，符合游戏原路径） |
| `COD_Recovered_TBN_v10` | 真实 QTangent 切线框架恢复：T/N 插值、带符号叉乘 B、统一归一化 |
| `COD_Weapon_Recovered_Frame_v10` | v10 武器切线框架候选外层：含属性缺失/混合符号/关闭/背面四处保守回退 |
| `COD_Static_Frame_Candidate_v10` | v10 静态武器候选框架输出，带 `Recovered Frame Enable` 开关 |

### 主材质 Master

| 节点组 | 功能 |
| --- | --- |
| `COD_Weapon_Master_v1` | 武器总装：NOG 解码 + 底色/粗糙度/金属度/法线强度完整链路 |
| `COD_Weapon_Master_v2` | v2 武器总装：接入 DXIL 证据的编码缩放与光泽调整 |
| `COD_Character_Surface_v1` | 人物表面总装：皮肤尺度、发片覆盖、眼部层次的分类材质 |
| `COD_Character_Surface_v2` | v2 人物表面：将 v2 控制应用于原有分类人物表面 |
| `COD_Master_Surface_v11` | 统一主入口：`Glass Mode` 开关在武器 v2 与薄壁玻璃间切换 |

### 玻璃 Glass

| 节点组 | 功能 |
| --- | --- |
| `COD_Optic_Glass_Master_v1` | 光学薄壁玻璃：Tint/IOR 1.46/Thin Wall、NOG 法线与光泽候选、污渍 Mix 与纳米镀膜薄膜（默认关闭） |

## 快速开始

1. 下载本仓库（无需 Git LFS），得到 `shaders/ez4cywa_COD_Shader_Library.blend`
2. 用 Blender 5.2.2 LTS（4.x 大体兼容，未逐项验证）打开或直接 Append
3. 在你自己的材质中添加 **Group** 节点，选择追加进来的节点组

最简武器用法（对应教程《从 COD 贴图到 Blender 材质》第 3 章）：

```
UV Map ──► Image Texture (albedo, sRGB)  ──► COD_Weapon_Master_v1 / Base Color
UV Map ──► Image Texture (NOG, Non-Color) ──► COD_Weapon_Master_v1 / NOG RGB + NOG Alpha
COD_Weapon_Master_v1 / Shader ──► Material Output / Surface
```

没有游戏贴图也能用：把任意普通法线图经 Separate Color 处理后接 `COD_Game_NormalXY_Layer_v4` 系列做实验，或用 `COD_Camo_Coordinates_v1` 给自己的图案做可平移平铺投影。

## 从 cast 自动加载材质

用 vendored 的 [cast 解析器](vendor/ATTRIBUTION.md) 一步完成"导入几何 + 按材质路径自动生成接好节点组的材质 + 赋予网格"：

```powershell
blender -b --factory-startup --python-exit-code 1 --python scripts/autobuild_materials.py -- `
  --import --cast path/to/model.cast `
  --camo-dir path/to/camo_asset/ --manifest build_manifest.json --out my_materials.blend
```

- 语义解析：`_mat_info` 语义表交叉验证（47=底色 / 48=NOG / 4a=覆盖）优先，cast 具名槽兜底
- Profile 规则（`scripts/profiles.json`）：武器 / 通用 / 人物子 profile（skin、hair、eye…）/ 迷彩分层自动分类，可自行扩展
- 哨兵图程序生成、上游插件原地升级、跨资产同名材质自动拆分
- 详细用法、角色表与边界：**[docs/AUTO_MATERIALS.md](docs/AUTO_MATERIALS.md)**

只提取规格（普通 Python，不需要 Blender，也是 Maya 移植的共享接口）：

```powershell
python scripts/cast_spec.py --cast path/to/model.cast --out spec.json
```

## Maya 2025 移植状态

**可行性分析与分阶段移植计划已交付（P0）**：结论为可行——数学层低难度、纹理层中等、CORNER 数据通路推荐导入期离线烘焙、Principled→aiStandardSurface 需标定；推荐"Arnold 原生节点图为主干 + OSL 承载数学核心"的组合路线。含四层节点映射表、三条路径对比与 P1–P6 阶段验收标准，见 **[docs/MAYA_2025_PORT.md](docs/MAYA_2025_PORT.md)**。尚未开始移植实施。

## 资产浏览器用法

把本仓库目录添加为 Blender 资产库（`Preferences → File Paths → Asset Libraries`），打开库文件即可看到全部节点组，按标签筛选：

- `COD 解码 Decode` · `COD 迷彩 Camo` · `COD 法线 Normal` · `COD 几何 Basis Frame` · `COD 主材质 Master` · `COD 玻璃 Glass`

## 学习路径

完整教程全文在私密研究仓库中，本仓库提供 **[教程总览](docs/TUTORIALS_SUMMARY.md)**：16 篇教程的定位、要点、对应节点组与推荐阅读路径。独立成篇的实战：**[瞄准镜薄壁玻璃 v11](docs/GLASS_V11_TUTORIAL.md)**。工具文档：**[cast 材质自动加载](docs/AUTO_MATERIALS.md)** · **[Maya 2025 移植计划](docs/MAYA_2025_PORT.md)**。三条典型路径：

- **入门**：节点连线指导 → 武器与人物实战 → 迷彩实战
- **原理**：本地游戏程序与 Shader v2 → 法线 v4 → 方向基 v5 → 分页矩阵 v6 → 压缩三角形 v7
- **数据链**：缓存与贴图 v8 → 包索引 v9 → 真实切线框架 v10

## 边界与声明

- 本项目是**候选还原**研究产物：缺少游戏对照截图与完整运行时常量，节点参数不等于游戏内实际值，不能视为已验收的游戏同画面复刻。
- v10 切线框架仅适用于静态、无变形、正均匀缩放的网格；动态蒙皮尚未接入。
- 本仓库与 Activision 无关，未获官方授权；不含任何游戏原始素材，节点组的独创连线与文档为本仓库作者所有。
- 复现研究方法时请遵守目标软件的最终用户许可协议与当地法律。

## License

[MIT](LICENSE) © 2026 ez4cywa
