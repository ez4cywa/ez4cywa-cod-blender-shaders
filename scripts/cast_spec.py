"""Extract material specifications from .cast files. Pure Python, no Blender required.

Pipeline: cast slots + _mat_info semantics + optional config + profile rules -> spec.json

The spec is the machine-readable contract consumed by
scripts/autobuild_materials.py (Blender).

Role resolution priority:
  1. _mat_info/<material>.txt semantic table cross-checked against cast slots by path
  2. Named cast slots (albedo/diffuse/normal/...) — 'normal' is ASSUMED packed NOG,
     unverified for foreign exports (see docs/AUTO_MATERIALS.md boundaries)
  3. Explicit --config overrides (compatible with the research project's
     mike4.json / dallas.json schema: name / color / nog / profile / controls)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor" / "cast_addon"))

from cast import Cast, Color, File, Model  # noqa: E402  (vendored upstream parser)

SEMANTIC_ROLES = {
    "unk_semantic_47": "color",
    "unk_semantic_48": "nog",
    "unk_semantic_4a": "opacity",
}
NAMED_SLOT_ROLES = {
    "albedo": "color",
    "diffuse": "color",
    "basecolor": "color",
    "normal": "nog",
    "nog": "nog",
    "opacity": "opacity",
}
SENTINELS = {"$black", "$white", "$identitypackednog"}


def parse_mat_info(cast_dir: Path, material_name: str) -> dict | None:
    """Read _mat_info/<name with / replaced by _>.txt -> {techset, slots:[(sem, stem)]}."""
    if not material_name:
        return None
    path = cast_dir / "_mat_info" / (material_name.replace("/", "_") + ".txt")
    if not path.is_file():
        return None
    techset = None
    slots: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("Techset:"):
            techset = line.split(":", 1)[1].strip()
        elif line.startswith("unk_semantic_") and "," in line:
            sem, stem = line.split(",", 1)
            slots.append((sem.strip(), stem.strip()))
    if not slots:
        return None
    return {"techset": techset, "slots": slots, "source": str(path)}


def load_profiles(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "profiles" not in data or "rules" not in data:
        raise ValueError(f"{path}: not a profiles file (missing profiles/rules)")
    return data


def resolve_profile(name: str, techset: str | None, asset: str, profiles: dict) -> tuple[str, list[str]]:
    warnings: list[str] = []
    for rule in profiles["rules"]:
        m = rule.get("match", {})
        hit = False
        if "name" in m:
            hit = name == m["name"]
        elif "name_regex" in m:
            hit = re.search(m["name_regex"], name) is not None
        elif "techset" in m:
            hit = techset == m["techset"]
        elif "techset_in" in m:
            hit = techset in m["techset_in"]
        elif "asset_regex" in m:
            hit = re.search(m["asset_regex"], asset) is not None
        if hit:
            profile = rule["profile"]
            if profile not in profiles["profiles"] and profile.split(".")[0] not in profiles["profiles"]:
                warnings.append(f"rule {rule} resolved unknown profile {profile}")
                break
            return profile, warnings
    return profiles.get("default_profile", "generic"), warnings


def merge_profile(profile_key: str, profiles: dict) -> dict:
    """Profile entry with base fallback: 'character.skin' falls back to 'character'."""
    base_name, _, sub = profile_key.partition(".")
    entry: dict = {}
    if sub and base_name in profiles["profiles"]:
        entry.update(profiles["profiles"][base_name])
    own = profiles["profiles"].get(profile_key, {})
    entry.update(own)
    entry.setdefault("controls", {})
    return entry


def _resolve_path(cast_dir: Path, rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute():
        return p
    return (cast_dir / p).resolve()


def resolve_texture(
    role: str,
    mat_info: dict | None,
    cast_dir: Path,
    slot_entries: list[tuple[str, dict]],
    warnings: list[str],
) -> dict | None:
    """Find the texture for a role: semantic table first (path-matched), named slots second."""
    if mat_info:
        stem_to_path = {
            Path(e["path"]).stem: e["path"]
            for _, e in slot_entries
            if e.get("kind") == "file"
        }
        for sem, stem in mat_info["slots"]:
            if SEMANTIC_ROLES.get(sem) != role:
                continue
            if stem in SENTINELS:
                return {"sentinel": stem[1:]}
            rel = stem_to_path.get(stem)
            if rel is None:
                candidate = cast_dir / "_images" / (stem + ".png")
                if candidate.is_file():
                    rel = str(candidate)
                    warnings.append(f"role {role}: semantic {sem} path not in cast slots, used disk file")
                else:
                    warnings.append(f"role {role}: semantic {sem} image {stem} not found on disk")
                    return None
            p = _resolve_path(cast_dir, rel)
            if not p.is_file():
                warnings.append(f"role {role}: missing file {p}")
                return None
            return {"path": str(p), "semantic": sem}
    for slot_name, entry in slot_entries:
        if slot_name.lower() in NAMED_SLOT_ROLES and NAMED_SLOT_ROLES[slot_name.lower()] == role:
            if entry.get("kind") == "color":
                return {"color": entry.get("rgba"), "colorspace": entry.get("colorspace", "srgb")}
            p = _resolve_path(cast_dir, entry["path"])
            if not p.is_file():
                warnings.append(f"role {role}: missing file {p} (named slot {slot_name})")
                return None
            note = None
            if role == "nog":
                note = "assumed packed NOG format from named 'normal' slot; unverified without _mat_info"
                warnings.append(note)
            result = {"path": str(p), "slot": slot_name}
            if note:
                result["assumption"] = note
            return result
    return None


def config_index(config_path: Path | None) -> dict:
    if config_path is None:
        return {}
    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    items = data.get("materials", [data] if "name" in data else [])
    return {item["name"]: item for item in items if "name" in item}


def resolve_config_path(value: str, config_path: Path, cast_dir: Path) -> str:
    p = Path(value)
    if p.is_absolute():
        return str(p)
    for candidate in (p, config_path.parent / p, cast_dir / p,
                      config_path.parent.parent.parent / p, REPO / p):
        if candidate.is_file():
            return str(candidate.resolve())
    return str((cast_dir / p).resolve())


def extract_cast(cast_path: Path, profiles: dict, cfg: dict, profile_override: str | None) -> dict:
    cast = Cast.load(str(cast_path))
    cast_dir = cast_path.parent
    asset = cast_path.stem
    warnings: list[str] = []
    materials: list[dict] = []
    seen: set[str] = set()
    for root in cast.Roots():
        for model in root.ChildrenOfType(Model):
            for m in model.Materials():
                name = m.Name() or ""
                if name in seen:
                    continue
                seen.add(name)
                slot_entries: list[tuple[str, dict]] = []
                for slot_name, ref in m.Slots().items():
                    if isinstance(ref, File):
                        slot_entries.append((slot_name, {"kind": "file", "path": ref.Path() or ""}))
                    elif isinstance(ref, Color):
                        slot_entries.append((slot_name, {
                            "kind": "color",
                            "rgba": list(ref.Rgba()) if ref.Rgba() else None,
                            "colorspace": ref.ColorSpace(),
                        }))
                mat_info = parse_mat_info(cast_dir, name)
                mat_warnings: list[str] = []
                textures: dict[str, dict] = {}
                for role in ("color", "nog", "opacity"):
                    hit = resolve_texture(role, mat_info, cast_dir, slot_entries, mat_warnings)
                    if hit:
                        textures[role] = hit
                all_slots = (
                    {sem: stem for sem, stem in mat_info["slots"]} if mat_info
                    else {s: (e.get("path") or e.get("rgba")) for s, e in slot_entries}
                )
                cfg_item = cfg.get(name, {})
                for role, key in (("color", "color"), ("nog", "nog")):
                    if key in cfg_item and cfg_item[key]:
                        resolved = resolve_config_path(cfg_item[key], cfg_item.get("_path", Path(".")), cast_dir)
                        textures[role] = {"path": resolved, "source": "config"}
                techset = mat_info["techset"] if mat_info else cfg_item.get("techset")
                if profile_override:
                    profile = profile_override
                    prof_warnings: list[str] = []
                else:
                    profile, prof_warnings = resolve_profile(name, techset, asset, profiles)
                    if "profile" in cfg_item:
                        profile = cfg_item["profile"]
                entry_profile = profile.partition(".")[0]
                if entry_profile not in profiles["profiles"]:
                    profile = profiles.get("default_profile", "generic")
                prof = merge_profile(profile, profiles)
                controls = dict(prof.get("controls", {}))
                controls.update(cfg_item.get("controls", {}))
                if "color" not in textures:
                    mat_warnings.append("no color texture resolved; material will use group default")
                if "nog" not in textures:
                    controls["Roughness Map Weight"] = 0.0
                    controls["Normal Strength"] = 0.0
                    mat_warnings.append("no NOG texture resolved; normal/roughness map contribution disabled")
                for required in prof.get("requires", []):
                    if required not in textures:
                        mat_warnings.append(f"profile {profile} expects texture role '{required}' which is missing")
                consumed = {v["semantic"] for v in textures.values() if "semantic" in v}
                if cfg_item.get("color"):
                    consumed |= {s for s in all_slots if SEMANTIC_ROLES.get(s) == "color"}
                if cfg_item.get("nog"):
                    consumed |= {s for s in all_slots if SEMANTIC_ROLES.get(s) == "nog"}
                materials.append({
                    "name": name,
                    "asset": asset,
                    "cast": str(cast_path),
                    "techset": techset,
                    "profile": profile,
                    "group": prof.get("group", "COD_Weapon_Master_v1"),
                    "unplug_base_color": bool(prof.get("unplug_base_color")),
                    "textures": textures,
                    "controls": controls,
                    "all_slots": all_slots,
                    "unresolved": [s for s in all_slots if s not in consumed],
                    "warnings": mat_warnings,
                })
                warnings.extend(f"{name}: {w}" for w in mat_warnings + prof_warnings)
    return {
        "cast": str(cast_path),
        "asset": asset,
        "materials": materials,
        "warnings": warnings,
    }


def parse_camo(camo_dir: Path, profiles: dict, apply_to: list[str] | None) -> dict:
    txt = sorted(camo_dir.glob("camo_*.txt"))
    if not txt:
        raise FileNotFoundError(f"no camo_*.txt in {camo_dir}")
    camo_cfg = profiles.get("camo", {})
    declared = camo_cfg.get("roles", {})
    table: dict[str, str] = {}
    for raw in txt[0].read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("unk_semantic_") and "," in line:
            sem, stem = line.split(",", 1)
            table[sem.removeprefix("unk_semantic_")] = stem.strip()
    warnings: list[str] = []
    roles: dict[str, dict] = {}
    for role, slot in declared.items():
        stem = table.get(slot)
        if stem is None:
            if role.endswith("_nog_candidate"):
                warnings.append(f"camo role {role}: slot {slot} absent; optional, left unwired")
                continue
            raise FileNotFoundError(f"camo role {role}: required slot {slot} missing in {txt[0].name}")
        p = camo_dir / (stem + ".png")
        if not p.is_file():
            raise FileNotFoundError(f"camo role {role}: {p} not found")
        roles[role] = {"path": str(p), "slot": slot}
    return {
        "source_dir": str(camo_dir),
        "file": str(txt[0]),
        "table": table,
        "roles": roles,
        "apply_to": apply_to or [],
        "origin_world": camo_cfg.get("origin_world", [0, 0, 0]),
        "coordinates": camo_cfg.get("coordinates", {}),
        "controls": camo_cfg.get("controls", {}),
        "alias_slots": camo_cfg.get("alias_slots", {}),
        "retained_not_applied": camo_cfg.get("retained_not_applied", []),
        "warnings": warnings,
        "status": "Layered camo prototype: placement and masks are artist-facing assumptions, not recovered game transforms.",
    }


def build_spec(args: argparse.Namespace) -> dict:
    profiles = load_profiles(Path(args.profiles))
    cfg: dict = {}
    cfg_path = Path(args.config) if args.config else None
    for name, item in config_index(cfg_path).items():
        item = dict(item)
        item["_path"] = cfg_path
        cfg[name] = item
    spec = {
        "schema_version": 1,
        "generator": "scripts/cast_spec.py",
        "casts": [],
        "materials": [],
        "warnings": [],
    }
    if args.profile and args.profile != "auto":
        forced = args.profile
    else:
        forced = None
    for cast in args.cast:
        part = extract_cast(Path(cast), profiles, cfg, forced)
        spec["casts"].append(part["cast"])
        spec["materials"].extend(part["materials"])
        spec["warnings"].extend(part["warnings"])
    if args.camo_dir:
        apply_to = args.apply_to.split(",") if args.apply_to else None
        if not apply_to:
            apply_to = [m["name"] for m in spec["materials"] if m["profile"] == "weapon"]
        spec["camo"] = parse_camo(Path(args.camo_dir), profiles, apply_to)
        spec["warnings"].extend(spec["camo"]["warnings"])
    else:
        spec["camo"] = None
    return spec


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract cast material specifications (no Blender needed)")
    ap.add_argument("--cast", action="append", required=True, help=".cast file (repeatable)")
    ap.add_argument("--camo-dir", help="directory containing camo_*.txt + images")
    ap.add_argument("--apply-to", help="comma-separated material names for camo (default: weapon profile)")
    ap.add_argument("--config", help="optional config JSON (mike4.json / dallas.json schema)")
    ap.add_argument("--profiles", default=str(REPO / "scripts" / "profiles.json"))
    ap.add_argument("--profile", default="auto", help="force profile for all materials (default: auto rules)")
    ap.add_argument("--out", help="write spec JSON to this path (default: stdout)")
    args = ap.parse_args()
    spec = build_spec(args)
    text = json.dumps(spec, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"SPEC {args.out}: {len(spec['materials'])} materials, "
              f"{len(spec['warnings'])} warnings, camo={'yes' if spec['camo'] else 'no'}")
    else:
        print(text)


if __name__ == "__main__":
    main()
