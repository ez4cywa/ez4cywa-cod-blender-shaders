"""Build or upgrade Blender materials from cast material specifications.

Runs inside Blender (batch convention):
  blender -b --factory-startup --python-exit-code 1 -- --cast x.cast [--import] ...

Flow:
  1. Optionally import geometry with the vendored upstream cast add-on (--import)
  2. Extract a spec in-process via scripts/cast_spec.py (or load --spec file)
  3. Append the node groups shipped in shaders/ez4cywa_COD_Shader_Library.blend
  4. Wire top-level materials per profile; upgrade add-on-created materials in place
  5. Optionally apply the camo layer stack (--camo-dir)
  6. Assign materials to meshes (.001-tolerant / source_asset aware) and write a manifest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import bpy

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / "shaders" / "ez4cywa_COD_Shader_Library.blend"
sys.path.insert(0, str(REPO / "scripts"))
import cast_spec  # noqa: E402

SENTINEL_VALUES = {
    "black": (0.0, 0.0, 0.0, 1.0),
    "white": (1.0, 1.0, 1.0, 1.0),
    "identitypackednog": (0.0, 128.0 / 255.0, 1.0, 128.0 / 255.0),
}
CAMO_GROUPS = ("COD_Camo_Layer_v3", "COD_Camo_Coordinates_v1")


def node(tree, typ, name, xy=(0, 0), width=190):
    n = tree.nodes.new(typ)
    n.name = name
    n.label = name
    n.location = xy
    n.width = width
    return n


def wire(tree, value, target):
    tree.links.new(value, target)


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description="Auto-build Blender materials from cast specs")
    ap.add_argument("--cast", action="append", default=[], help=".cast file (repeatable)")
    ap.add_argument("--camo-dir", help="directory containing camo_*.txt + images")
    ap.add_argument("--apply-to", help="comma-separated camo targets (default: weapon profile)")
    ap.add_argument("--config", help="optional mike4.json / dallas.json schema config")
    ap.add_argument("--profiles", default=str(REPO / "scripts" / "profiles.json"))
    ap.add_argument("--profile", default="auto", help="force profile for all materials")
    ap.add_argument("--spec", help="use an existing spec.json instead of extracting")
    ap.add_argument("--import", dest="do_import", action="store_true",
                    help="import geometry first via the vendored upstream add-on")
    ap.add_argument("--manifest", help="write build manifest JSON here")
    ap.add_argument("--out", help="save the resulting .blend here")
    args = ap.parse_args(argv)
    if not args.cast and not args.spec:
        ap.error("provide --cast (repeatable) or --spec")
    if args.camo_dir and not args.cast and not args.spec:
        ap.error("--camo-dir requires material input")
    return args


def load_spec(args: argparse.Namespace) -> dict:
    if args.spec:
        return json.loads(Path(args.spec).read_text(encoding="utf-8"))
    return cast_spec.build_spec(args)


def import_casts(casts: list[str]) -> None:
    sys.path.insert(0, str(REPO / "vendor"))
    import cast_addon
    cast_addon.register()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for cast in casts:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.cast(filepath=cast, import_skin=True)
        asset = Path(cast).stem
        for ob in set(bpy.data.objects) - before:
            if ob.type == "MESH":
                ob["source_asset"] = asset
        print(f"IMPORTED {Path(cast).name}: tagged {sum(1 for o in set(bpy.data.objects) - before if o.type == 'MESH')} meshes as {asset}")


def wanted_groups(spec: dict) -> set[str]:
    wanted: set[str] = set()
    for m in spec["materials"]:
        wanted.add(m.get("group") or "COD_Weapon_Master_v1")
    if spec.get("camo"):
        wanted.update(CAMO_GROUPS)
    return wanted


def append_groups(wanted: set[str]) -> dict[str, bpy.types.NodeTree]:
    missing = sorted(n for n in wanted if n not in bpy.data.node_groups)
    if missing:
        with bpy.data.libraries.load(str(LIB), link=False) as (src, dst):
            dst.node_groups = [n for n in missing if n in src.node_groups]
    bad = [g.name for g in bpy.data.node_groups if re.search(r"\.\d{3}$", g.name)]
    if bad:
        raise RuntimeError(f"duplicate node groups after append (library mismatch): {bad}")
    trees = {n: bpy.data.node_groups[n] for n in wanted}
    absent = sorted(n for n, t in trees.items() if t is None)
    if absent:
        raise RuntimeError(f"node groups missing from library {LIB.name}: {absent}")
    return trees


def constant_image(key: str, rgba: tuple[float, ...]) -> bpy.types.Image:
    im = bpy.data.images.new(key, 4, 4, alpha=True, float_buffer=False)
    im.pixels[:] = list(rgba) * (4 * 4)
    im.use_fake_user = True
    im.pack()
    return im


def image_for(tex: dict, space: str) -> bpy.types.Image:
    if "sentinel" in tex:
        key = f"${tex['sentinel']} | {space}"
        im = bpy.data.images.get(key)
        if im is None:
            value = SENTINEL_VALUES[tex["sentinel"]]
            im = constant_image(key, value)
    elif tex.get("color"):
        rgba = tuple(tex["color"])
        key = f"cast color {rgba} | {space}"
        im = bpy.data.images.get(key)
        if im is None:
            im = constant_image(key, rgba)
    else:
        p = Path(tex["path"])
        key = f"{p.name} | {space}"
        im = bpy.data.images.get(key)
        if im is None:
            im = bpy.data.images.load(str(p), check_existing=False)
            im.name = key
    im.colorspace_settings.name = space
    im.alpha_mode = "CHANNEL_PACKED"
    return im


def objects_index() -> list[tuple[str | None, bpy.types.Material]]:
    index: list[tuple[str | None, bpy.types.Material]] = []
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH":
            continue
        for slot in ob.material_slots:
            if slot.material:
                index.append((ob.get("source_asset"), slot.material))
    return index


def resolve_material(item: dict, assigned: list[tuple[str | None, bpy.types.Material]]) -> bpy.types.Material:
    cast_asset, cast_name = item["asset"], item["name"]
    for m in bpy.data.materials:
        if m.get("cast_name") == cast_name and m.get("cast_asset") == cast_asset:
            return m
    base = re.compile(rf"^{re.escape(cast_name)}(\.\d+)?$")
    cands = {m for asset, m in assigned
             if base.match(m.name) and (asset is None or asset == cast_asset)}
    if len(cands) > 1:
        raise RuntimeError(f"ambiguous materials for {cast_name} in asset {cast_asset}: "
                           f"{sorted(m.name for m in cands)}")
    chosen = next(iter(cands), None)
    if chosen is not None and chosen.get("cast_asset") not in (None, cast_asset):
        # Shared add-on material already claimed by another asset: split into a new one;
        # assign() repoints this asset's slots afterwards.
        chosen = None
    if chosen is None:
        return bpy.data.materials.new(cast_name)
    return chosen


def set_controls(group_node, controls: dict, mat_name: str) -> list[str]:
    applied = []
    for key, value in controls.items():
        if key not in group_node.inputs:
            raise KeyError(f"{mat_name}: control '{key}' not a socket of {group_node.node_tree.name}")
        group_node.inputs[key].default_value = value
        applied.append(key)
    return applied


def tex_node(tree, tex: dict, space: str, name: str, xy) -> bpy.types.Node:
    n = node(tree, "ShaderNodeTexImage", name, xy)
    n.image = image_for(tex, space)
    return n


def build_plain(item: dict, mat: bpy.types.Material, trees: dict) -> list[str]:
    """weapon / generic / character profiles: UV -> textures -> master group -> output."""
    warnings: list[str] = []
    group_tree = trees[item["group"]]
    is_character = item["profile"].startswith("character")
    mat.use_nodes = True
    t = mat.node_tree
    t.nodes.clear()
    uv = node(t, "ShaderNodeUVMap", "UVMap", (-760, 100))
    uv.uv_map = "UVMap"
    master_name = "Character Master" if is_character else "COD Weapon Master"
    master = node(t, "ShaderNodeGroup", master_name, (0, 180), width=320)
    master.node_tree = group_tree

    color_tex = item["textures"].get("color")
    if color_tex:
        ct = tex_node(t, color_tex, "sRGB", "47 | Color + Alpha", (-500, 300))
        wire(t, uv.outputs["UV"], ct.inputs["Vector"])
        wire(t, ct.outputs["Color"], master.inputs["Base Color"])
        wire(t, ct.outputs["Alpha"], master.inputs["Color Alpha"])
    else:
        warnings.append(f"{item['name']}: no color texture; group default kept")

    nog_tex = item["textures"].get("nog")
    if nog_tex:
        nt = tex_node(t, nog_tex, "Non-Color", "48 | NOG packed data", (-500, -60))
        wire(t, uv.outputs["UV"], nt.inputs["Vector"])
        wire(t, nt.outputs["Color"], master.inputs["NOG RGB"])
        wire(t, nt.outputs["Alpha"], master.inputs["NOG Alpha"])

    opacity_tex = item["textures"].get("opacity")
    if opacity_tex and "Opacity" in master.inputs:
        ot = tex_node(t, opacity_tex, "Non-Color", "4a | Coverage candidate", (-500, -440))
        wire(t, uv.outputs["UV"], ot.inputs["Vector"])
        wire(t, ot.outputs["Color"], master.inputs["Opacity"])

    applied = set_controls(master, item["controls"], item["name"])
    if item.get("unplug_base_color"):
        for link in list(master.inputs["Base Color"].links):
            t.links.remove(link)
        master.inputs["Base Color"].default_value = (1, 1, 1, 1)

    out = node(t, "ShaderNodeOutputMaterial", "Material Output", (440, 180))
    wire(t, master.outputs["Shader"], out.inputs["Surface"])
    if is_character:
        mat.surface_render_method = "DITHERED"

    mat["profile"] = item["profile"]
    mat["cast_name"] = item["name"]
    mat["cast_asset"] = item["asset"]
    mat["semantic_references"] = json.dumps(item["all_slots"], ensure_ascii=False)
    mat["unresolved_semantics"] = json.dumps(item["unresolved"], ensure_ascii=False)
    mat["controls_applied"] = json.dumps(sorted(applied))
    return warnings


def apply_camo(spec: dict, built: dict[str, bpy.types.Material], trees: dict) -> dict:
    camo = spec["camo"]
    roles = camo["roles"]
    coords_cfg = camo["coordinates"]
    missing = [n for n in (m for m in camo["apply_to"]) if n not in built]
    if missing:
        raise RuntimeError(
            f"camo --apply-to materials not built in this run: {missing}; "
            f"available: {sorted(built)}")
    anchor = bpy.data.objects.get("Camo projection origin")
    if anchor is None:
        anchor = bpy.data.objects.new("Camo projection origin", None)
        bpy.context.scene.collection.objects.link(anchor)
    anchor.location = tuple(camo["origin_world"])
    anchor.empty_display_size = 0.03

    layer_tree = trees["COD_Camo_Layer_v3"]
    coord_tree = trees["COD_Camo_Coordinates_v1"]
    applied: dict[str, dict] = {}
    for name in camo["apply_to"]:
        mat = built[name]
        t = mat.node_tree
        master = t.nodes.get("COD Weapon Master")
        if master is None:
            raise RuntimeError(f"{name}: camo requires a weapon master material in this run")
        for n in [n for n in t.nodes if n.name.startswith("Camo |")]:
            t.nodes.remove(n)

        texco = node(t, "ShaderNodeTexCoord", "Camo | Object coordinates", (-1600, -800))
        texco.object = anchor
        sep = node(t, "ShaderNodeSeparateXYZ", "Camo | World-like axes", (-1380, -800))
        wire(t, texco.outputs["Object"], sep.inputs[0])
        plane = node(t, "ShaderNodeCombineXYZ", "Camo | X Z projection", (-1160, -800))
        wire(t, sep.outputs["X"], plane.inputs["X"])
        wire(t, sep.outputs["Z"], plane.inputs["Y"])

        coords: dict[str, bpy.types.Node] = {}
        for j, placement in enumerate(("paint", "pattern", "sticker")):
            c = node(t, "ShaderNodeGroup", f"Camo | {placement} coordinates", (-920, -550 - j * 270))
            c.node_tree = coord_tree
            wire(t, plane.outputs[0], c.inputs["Planar Vector"])
            conf = coords_cfg.get(placement, {})
            if "scale" in conf:
                c.inputs["Scale"].default_value = conf["scale"]
            if "offset" in conf:
                c.inputs["Offset"].default_value = tuple(conf["offset"])
            if "rotation" in conf:
                c.inputs["Rotation"].default_value = conf["rotation"]
            coords[placement] = c

        layer = node(t, "ShaderNodeGroup", "Camo | Layer", (800, 200), width=300)
        layer.node_tree = layer_tree
        set_controls(layer, camo["controls"], name)

        wire(t, master.outputs["Shader"], layer.inputs["Underlying Shader"])
        wire(t, master.outputs["Metallic"], layer.inputs["Original Metallic"])
        nm = node(t, "ShaderNodeNormalMap", "Camo | Retained weapon normal", (530, -450))
        nm.uv_map = "UVMap"
        wire(t, master.outputs["Decoded Normal"], nm.inputs["Color"])
        nm.inputs["Strength"].default_value = master.inputs["Normal Strength"].default_value
        wire(t, nm.outputs["Normal"], layer.inputs["Underlying Normal"])

        routing = [
            ("paint_color", "sRGB", "paint", "Color", None),
            ("pattern_color", "sRGB", "pattern", "Color", None),
            ("pattern_mask", "Non-Color", "pattern", "Fac", None),
            ("sticker_color", "sRGB", "sticker", "Color", None),
            ("sticker_mask", "Non-Color", "sticker", "Fac", None),
            ("paint_nog_candidate", "Non-Color", "paint", "R", "Paint Gloss"),
            ("sticker_nog_candidate", "Non-Color", "sticker", "R", "Sticker Gloss"),
        ]
        wired_roles = []
        for j, (role, space, placement, kind, explicit_dst) in enumerate(routing):
            tex = roles.get(role)
            if tex is None:
                continue
            n = tex_node(t, tex, space, f"Camo | {role}", (-550 + (j % 2) * 360, -650 - (j // 2) * 300))
            n.extension = "CLIP" if placement == "sticker" else "REPEAT"
            wire(t, coords[placement].outputs["Vector"], n.inputs["Vector"])
            value = n.outputs["Color"]
            if explicit_dst:
                r = node(t, "ShaderNodeSeparateColor", f"Camo | {role} R", (230, -850 - j * 160))
                wire(t, value, r.inputs[0])
                value = r.outputs["Red"]
                dst = explicit_dst
            else:
                dst = {
                    ("paint_color", "Color"): "Paint Color",
                    ("pattern_color", "Color"): "Pattern Color",
                    ("pattern_mask", "Fac"): "Pattern Mask",
                    ("sticker_color", "Color"): "Sticker Color",
                    ("sticker_mask", "Fac"): "Sticker Mask",
                }[(role, kind)]
            wire(t, value, layer.inputs[dst])
            wired_roles.append(role)

        out = t.nodes.get("Material Output")
        if out is None:
            out = node(t, "ShaderNodeOutputMaterial", "Material Output", (1230, 200))
        out.location = (1230, 200)
        wire(t, layer.outputs["Shader"], out.inputs["Surface"])
        mat["camo_status"] = camo["status"]
        mat["camo_mapping"] = "World X/Z planar projection via Camo projection origin; artist-facing assumption"
        mat["camo_roles"] = json.dumps(wired_roles)
        applied[name] = {"roles": wired_roles, "coordinates": coords_cfg}
    return {
        "apply_to": camo["apply_to"],
        "roles": {k: v["path"] for k, v in roles.items()},
        "origin_world": camo["origin_world"],
        "anchor": anchor.name,
        "materials": applied,
        "status": camo["status"],
        "manual_note": "Scale/Offset/Rotation are defaults; adjust per material to position the pattern.",
    }


def assign(built: dict[str, bpy.types.Material]) -> list[dict]:
    assignments: list[dict] = []
    by_asset: dict[str, dict[str, bpy.types.Material]] = {}
    for (asset, name), mat in built.items():
        by_asset.setdefault(asset, {})[name] = mat
    name_only = {name: mat for (_, name), mat in built.items()}
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH":
            continue
        asset = ob.get("source_asset")
        table = by_asset.get(asset, name_only) if asset else name_only
        for slot in ob.material_slots:
            if not slot.material:
                continue
            base = slot.material.name
            hit = table.get(base) or next(
                (m for n, m in table.items() if base.startswith(n + ".") and base[len(n) + 1:].isdigit()),
                None)
            if hit and slot.material is not hit:
                slot.material = hit
            if hit:
                assignments.append({"object": ob.name, "asset": asset, "material": hit.name})
    return assignments


def main() -> None:
    args = parse_args()
    spec = load_spec(args)
    if args.do_import:
        if not args.cast:
            raise RuntimeError("--import requires --cast")
        import_casts(args.cast)

    trees = append_groups(wanted_groups(spec))
    for sentinel in SENTINEL_VALUES:
        for space in ("sRGB", "Non-Color"):
            image_for({"sentinel": sentinel}, space)
    assigned = objects_index()

    built: dict[str, bpy.types.Material] = {}
    warnings = list(spec.get("warnings", []))
    for item in spec["materials"]:
        mat = resolve_material(item, assigned)
        assigned = [(a, m) for a, m in assigned if m is not mat]
        warnings.extend(build_plain(item, mat, trees))
        built[(item["asset"], item["name"])] = mat

    camo_result = None
    if spec.get("camo"):
        by_name = {name: mat for (_, name), mat in built.items()}
        camo_result = apply_camo(spec, by_name, trees)

    assignments = assign(built)

    manifest = {
        "blender": bpy.app.version_string,
        "library": LIB.name,
        "groups_used": sorted({t.name for t in trees.values()}),
        "casts": spec.get("casts", []),
        "counts": {
            "materials": len(built),
            "groups": len(trees),
            "assignments": len(assignments),
            "camo_materials": len(spec["camo"]["apply_to"]) if spec.get("camo") else 0,
        },
        "materials": [
            {
                "name": item["name"],
                "asset": item["asset"],
                "profile": item["profile"],
                "group": item["group"],
                "blender_material": built[(item["asset"], item["name"])].name,
                "textures": {
                    role: tex.get("path") or tex.get("sentinel") or "color-constant"
                    for role, tex in item["textures"].items()
                },
                "controls": item["controls"],
                "unresolved_count": len(item["unresolved"]),
                "warnings": item["warnings"],
            }
            for item in spec["materials"]
        ],
        "camo": camo_result,
        "assignments": assignments,
        "warnings": warnings,
    }
    if args.manifest:
        Path(args.manifest).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("AUTOBUILD", json.dumps(manifest["counts"], ensure_ascii=False),
          "warnings:", len(warnings))
    if warnings:
        for w in warnings:
            print("WARNING", w)
    if args.out:
        out = Path(args.out)
        bpy.ops.wm.save_as_mainfile(filepath=str(out), relative_remap=True)
        bpy.ops.file.make_paths_relative()
        bpy.ops.wm.save_as_mainfile(filepath=str(out))
        print("SAVED", out)


if __name__ == "__main__":
    main()
