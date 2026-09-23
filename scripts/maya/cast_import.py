"""P1: import .cast geometry into Maya with the official vendored translator.

Runs inside mayabatch:
  mayabatch -command "python(\"import sys; sys.argv=['cast_import', r'<config.json>'); exec(open(r'<script>').read())\")"

Config JSON:
  {"casts": ["abs/path.cast", ...],
   "report": "abs/path/report.json",
   "save":   "abs/path/out.ma"}          # optional mayaAscii save

Verifies per cast: mesh counts, vertex/face totals, UV set names,
material assignments, and tags every imported mesh with source_asset.
"""
import json
import sys
from pathlib import Path

import maya.cmds as cmds

REPO = Path(r"E:\blender_render_reseach\tmp\publish\ez4cywa-cod-blender-shaders")
VENDOR_PLUGIN = REPO / "vendor" / "maya_cast_plugin" / "castplugin.py"

cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))


def release_existing_cast_translator():
    """Unload any plugin that already registered a 'cast' file translator."""
    released = []
    for plug in cmds.pluginInfo(q=True, listPlugins=True) or []:
        try:
            fts = [t.lower() for t in (cmds.pluginInfo(plug, q=True, listFileTypes=True) or [])]
        except Exception:
            continue
        if "cast" in fts:
            try:
                cmds.unloadPlugin(plug)
                released.append(plug)
            except Exception:
                pass
    return released


def load_official_plugin():
    released = release_existing_cast_translator()
    info = {"released": released}
    try:
        cmds.loadPlugin(str(VENDOR_PLUGIN))
        info["loaded"] = str(VENDOR_PLUGIN)
    except Exception:
        # Translator may already be registered by an identical upstream copy.
        ok = any("cast" in [t.lower() for t in (cmds.pluginInfo(p, q=True, listFileTypes=True) or [])]
                 for p in cmds.pluginInfo(q=True, listPlugins=True) or [])
        if not ok:
            raise
        info["loaded"] = "already-registered copy"
    return info


def shapes_of(objs):
    shapes = cmds.ls(objs, dag=True, type="mesh", long=True) or []
    return [s for s in shapes if not cmds.getAttr(s + ".intermediateObject")]


def mesh_record(shape):
    verts = cmds.polyEvaluate(shape, vertex=True)
    faces = cmds.polyEvaluate(shape, face=True)
    if isinstance(verts, list):
        verts = sum(verts)
    if isinstance(faces, list):
        faces = sum(faces)
    uvs = cmds.polyUVSet(shape, q=True, allUVSets=True) or []
    engines = cmds.listConnections(shape + ".instObjGroups", type="shadingEngine") or []
    materials = []
    for eng in sorted(set(engines)):
        surf = cmds.listConnections(eng + ".surfaceShader", source=True, destination=False) or []
        materials.extend(surf)
    return {
        "shape": shape.rsplit("|", 1)[-1],
        "verts": verts,
        "faces": faces,
        "uv_sets": uvs,
        "materials": sorted(set(materials)),
        "source_asset": (cmds.getAttr(shape + ".source_asset")
                         if cmds.attributeQuery("source_asset", node=shape, exists=True) else None),
    }


report = {
    "maya": cmds.about(version=True),
    "plugin": load_official_plugin(),
    "casts": [],
    "failed": [],
}

cmds.file(new=True, force=True)
for cast in cfg["casts"]:
    stem = Path(cast).stem
    before = set(cmds.ls(long=True) or [])
    try:
        cmds.file(cast, i=True, type="cast")
    except Exception as e:
        report["failed"].append({"cast": cast, "error": str(e)})
        continue
    after = set(cmds.ls(long=True) or [])
    new_objs = sorted(after - before)
    all_meshes = cmds.ls(new_objs, dag=True, type="mesh", long=True) or []
    intermediates = [s for s in all_meshes if cmds.getAttr(s + ".intermediateObject")]
    new_meshes = shapes_of(new_objs)
    tagged = 0
    for shape in new_meshes:
        if not cmds.attributeQuery("source_asset", node=shape, exists=True):
            cmds.addAttr(shape, longName="source_asset", dataType="string")
        cmds.setAttr(shape + ".source_asset", stem, type="string")
        tagged += 1
    # also tag transforms for easy filtering
    for obj in cmds.ls(new_objs, type="transform", long=True) or []:
        if not cmds.attributeQuery("source_asset", node=obj, exists=True):
            cmds.addAttr(obj, longName="source_asset", dataType="string")
        cmds.setAttr(obj + ".source_asset", stem, type="string")
    joints = cmds.ls(new_objs, type="joint", long=True) or []
    records = [mesh_record(s) for s in new_meshes]
    report["casts"].append({
        "cast": cast,
        "asset": stem,
        "meshes": len(records),
        "intermediate_shapes": len(intermediates),
        "tagged_shapes": tagged,
        "joints": len(joints),
        "vert_total": sum(r["verts"] for r in records),
        "face_total": sum(r["faces"] for r in records),
        "uv_sets": sorted({u for r in records for u in r["uv_sets"]}),
        "materials": sorted({m for r in records for m in r["materials"]}),
        "missing_material": [r["shape"] for r in records if not r["materials"]],
        "detail": records,
    })

report["totals"] = {
    "meshes": sum(c["meshes"] for c in report["casts"]),
    "tagged": sum(c["tagged_shapes"] for c in report["casts"]),
    "joints": sum(c["joints"] for c in report["casts"]),
}
if cfg.get("save"):
    cmds.file(rename=cfg["save"])
    cmds.file(save=True, type="mayaAscii", force=True)
    report["saved"] = cfg["save"]

Path(cfg["report"]).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print("P1_IMPORT_DONE meshes=%d failed=%d" % (report["totals"]["meshes"], len(report["failed"])))
