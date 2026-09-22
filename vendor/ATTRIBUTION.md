# Vendored Dependencies

## cast_addon/

Upstream: [dtzxporter/cast](https://github.com/dtzxporter/cast)
Pinned commit: `363cb39c0425844e29bf4c2457bbbb1d2b9bb4c6`
License: MIT (see [cast_addon/LICENSE](cast_addon/LICENSE))
Files: `__init__.py`, `cast.py`, `import_cast.py`, `export_cast.py`, `shared_cast.py` — copied unmodified.

`cast.py` is a dependency-free (Python standard library only) parser for the `.cast`
model/texture container format. This repository uses it in two ways:

1. `scripts/cast_spec.py` imports `cast.Cast` directly to extract material paths,
   texture slots and mesh→material references — no Blender required.
2. `scripts/autobuild_materials.py --import` registers the full upstream add-on
   (`bpy.ops.import_scene.cast`) to import geometry, then replaces its basic
   Principled wiring with this repository's shader node groups.

This repository does not patch the vendored add-on. Updates follow upstream
pinned commits only.
