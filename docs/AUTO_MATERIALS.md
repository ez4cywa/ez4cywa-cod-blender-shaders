# cast 材质自动加载

根据 `.cast` 文件中存储的材质路径与贴图槽位，自动生成接好本仓库节点组的 Blender 材质，并赋予对应网格。覆盖三类材质：**武器 / 人物 / 迷彩分层**。

## 管线总览

```
*.cast ──► scripts/cast_spec.py ──► spec.json ──► scripts/autobuild_materials.py ──► Blender 材质
          纯 Python，无需 Blender                 Append shaders/ez4cywa_COD_Shader_Library.blend
          （也是未来 Maya 移植的共享接口）
```

- `scripts/cast_spec.py`：解析 cast 材质路径与槽位、交叉核对 `_mat_info` 语义表、按规则分类 profile、输出规格 JSON
- `scripts/autobuild_materials.py`：在 Blender 内按 profile 接线节点组、创建/升级材质、赋予网格、写构建 manifest
- `vendor/cast_addon/`：上游 [dtzxporter/cast](https://github.com/dtzxporter/cast)（pinned、未修改，见 [ATTRIBUTION](../vendor/ATTRIBUTION.md)），供 `--import` 导入几何与 `cast_spec.py` 解析

## 快速开始

```powershell
# 1) 只提取材质规格（普通 Python 即可，不需要 Blender）
python scripts/cast_spec.py --cast path/to/model.cast --out spec.json

# 2) 导入几何 + 自动材质（一步到位）
blender -b --factory-startup --python-exit-code 1 --python scripts/autobuild_materials.py -- `
  --import --cast path/to/model.cast `
  --manifest build_manifest.json --out my_materials.blend

# 带迷彩分层（追加 --camo-dir 指向含 camo_*.txt 的目录）
... --camo-dir path/to/camo_asset/ --apply-to "m/wpn_xxx_v0,m/wpn_xxx_v1"
```

已有场景（自己导入或之前构建过）可以省略 `--import`，脚本会按名称**原地升级**上游插件创建的简装材质，保留原有赋予关系。多资产同名材质通过 `source_asset` 标记与 `cast_asset` 属性区分，不会互相覆盖。

## 角色解析（槽位 → 用途）

优先级从高到低：

| 优先级 | 来源 | 说明 |
| --- | --- | --- |
| 1 | `_mat_info/<材质名>.txt` 语义表 | `unk_semantic_47`→color、`48`→NOG、`4a`→opacity；按文件路径与 cast 槽位交叉验证 |
| 2 | cast 具名槽 | `albedo/diffuse`→color、`normal`→NOG（**未验证假设**，见边界）、`opacity`→opacity |
| 3 | `--config` 显式覆盖 | 兼容研究项目 `mike4.json` / `dallas.json` schema（`name/color/nog/profile/controls`），可指向你自己的配置 |

哨兵图 `$black` / `$white` / `$identitypackednog` 不是磁盘文件，由构建器程序生成 4×4 常量图并打包进 `.blend`（identity 值为 `(0,128,255,128)`）。

### 迷彩角色表（`camo_*.txt` 槽位）

| 角色 | 槽位 | 色彩空间 |
| --- | --- | --- |
| paint_color（底纹颜色） | `0` | sRGB |
| pattern_color（重复文字颜色） | `1` | sRGB |
| sticker_color（胶带贴纸颜色） | `2` | sRGB |
| pattern_mask（文字灰度遮罩） | `f` | Non-Color |
| sticker_mask（贴纸遮罩） | `10` | Non-Color |
| paint_nog_candidate / sticker_nog_candidate（R 通道 Gloss 候选） | `7` / `9` | Non-Color |
| 别名槽（内容等同） | `4`=`1`、`12`=`f` | — |
| 保留未接线 | `3`、`a` | — |

迷彩定位使用世界 X/Z 平面投影（`Camo projection origin` Empty），三组 Scale/Offset/Rotation 默认值来自研究资产示例——**定位参数需要人工调整**，构建 manifest 中会明确标注。

## Profile 规则（`scripts/profiles.json`）

规则自上而下匹配，首个命中生效；支持 `name` / `name_regex` / `techset` / `techset_in` / `asset_regex`。未命中走 `default_profile`（`generic`）。

| Profile | 节点组 | 要点 |
| --- | --- | --- |
| `weapon` | `COD_Weapon_Master_v1` | Metalness Weight=1（Alpha 金属候选启用） |
| `generic` | `COD_Weapon_Master_v1` | 金属候选关闭，电介质安全默认 |
| `character.*` | `COD_Character_Surface_v1` | skin / cloth / hair_card / eye / cornea_candidate / tearline / oral / unresolved_overlay，控制值为公开教程默认值 |
| 迷彩（`--camo-dir`） | + `COD_Camo_Layer_v3` + `COD_Camo_Coordinates_v1` | 插在 Master 与 Material Output 之间 |

profile 内的 `requires`（如 hair_card/tearline 需要 opacity 贴图）、`unplug_base_color`（cornea 断开底色接白色）由构建器自动处理。

**没有 NOG 贴图时**（无 `_mat_info` 的外部 cast），自动把 `Normal Strength` 与 `Roughness Map Weight` 置 0 并在警告中说明——不猜测哪个槽是法线。

## 构建 Manifest

`--manifest build_manifest.json` 记录：每个材质的 profile、组、贴图解析来源、应用的 controls、未解析槽位数、警告；迷彩接线的角色与定位；网格赋予明细。未解析槽位（游戏 semantic 中未被 color/nog/opacity 消费的）按项目惯例保留并计数，不乱接线。

## 验证（本仓库的验收方式）

- **spec 层**：真实资产对拍私有清单——武器 color/nog 与 `_mat_info` semantic 47/48、cast 槽位三方一致；人物 profile 分类数量与研究 ground truth 逐项相等（skin 3、hair 3、eye 1、cornea 1、tearline 1、oral 1、overlay 3，基础材质 64=28 cloth+36 equipment）；迷彩 7 角色 11 槽 9 图全部命中
- **Blender 层**：80 材质结构断言（色彩空间 sRGB/Non-Color、`CHANNEL_PACKED`、组全部来自合并库且无 `.001` 残留、皮肤 SSS=0.22、发片 DITHERED+opacity、角膜底色断开、同名跨资产拆分为 2 个材质、97 个槽位全部指向带 cast 标记的材质、无游戏贴图被打包进文件）
- **渲染冒烟**：Cycles CPU 8 spp 出图，像素有限且非黑

## 边界与声明

- 角色子 profile 无法从数据自动推断（techset 是哈希）——规则文件是正式接口，`profiles.json` 内含研究资产示例规则，换资产时按需修改
- 上游 addon 只连 `albedo` 等具名槽到裸 Principled；本工具在导入后重建节点树接入本仓库节点组，不修改上游代码
- 迷彩层序、投影、遮罩与光泽槽仍是研究候选假设，不是已恢复的游戏参数
- 生成的 `.blend` 会引用你本地的贴图路径；发布作品前请自行打包或按需处理贴图版权
- 不包含、不上传任何游戏原始素材；`spec.json` 与 manifest 只是路径与统计信息
