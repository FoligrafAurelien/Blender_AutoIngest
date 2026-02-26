# AutoIngest — Blender 5.0.1 Plugin

> Batch OBJ importer for 3D artists. Drop a folder, hit **Start Import**, done.

**Author:** Aurelien Binauld aka Foligraf  
**Version:** 1.1.0  
**Blender:** 5.0.1+  
**Category:** Import-Export

---

## What it does

AutoIngest scans a folder (and all its sub-folders) for `.obj` files and imports them one by one, fully automatically. For each file it:

1. Imports the OBJ using the native Blender importer with the Up Axis you defined
2. Centers the pivot on the object's bounding-box (optional)
3. Moves the object to world origin `(0, 0, 0)`
4. Scales it to match a reference object, homothetically — the ratio is never broken (optional)
5. Creates a **Plain Axes Empty** named `EMPTY_<filename>` at the origin
6. Parents all imported mesh objects to that Empty
7. Packs everything into a dedicated **Collection** named after the OBJ file
8. Hides the previous collection and keeps only the latest one visible
9. Moves on to the next file

---

## Installation

1. Download `auto_ingest.py`
2. Open Blender → **Edit › Preferences › Add-ons › Install…**
3. Select `auto_ingest.py` and confirm
4. Enable **AutoIngest** in the add-on list
5. Open the **N-Panel** (`N` key in the 3D Viewport) → tab **AutoIngest**

---

## UI Overview

```
┌─ AutoIngest ──────────────────────────┐
│                                       │
│  📁 Source Folder                     │
│  [ /path/to/your/folder            ]  │
│                                       │
│  🌐 Import Axes                       │
│  Up Axis  [ Y ▾ ]                     │
│                                       │
│  ⚙ Import Options                    │
│  ☑ Center All Pivots                  │
│  ☐ Scale to Reference                 │
│      Reference  [ — ]                 │
│      ☑ Apply Scale                    │
│                                       │
│  [▶  Start Import          ]          │
│  [🗑 Replace if Existing   ]  ← red   │
│                                       │
│  🎨 Material Utilities                │
│  ☐ Import Diffuse as Emissive         │
└───────────────────────────────────────┘
```

---

## Options Reference

### Import Axes

| Option | Description |
|--------|-------------|
| **Up Axis** | Sets the up direction for the OBJ importer (`X` `Y` `Z` `-X` `-Y` `-Z`). Blender deduces Forward automatically, preventing invalid axis combinations. |

### Import Options

| Option | Default | Description |
|--------|---------|-------------|
| **Center All Pivots** | ✅ On | Moves each object's origin to its geometric bounding-box center before placing it at `(0,0,0)`. Implemented via direct vertex offset — no `bpy.ops` overhead. |
| **Scale to Reference** | Off | Scales every imported object so its **longest axis** matches the same dimension on the reference object. The scale is always **homothetic** — aspect ratio is never distorted. Comparison uses world-space dimensions (scale-aware), so a reference with `scale = 2.0` is correctly measured in metres. |
| **Apply Scale** | ✅ On | Bakes the scale factor into vertex coordinates after scaling (`obj.scale` returns to `1, 1, 1`). Recommended for export, rigging and modifiers. Disable if you want to keep the scale as a visible transform. Only available when *Scale to Reference* is active. |

### Replace if Existing

| State | Behaviour |
|-------|-----------|
| **Off** (default) | If a collection with the same name already exists, the new one is suffixed `_001`, `_002` … `_999` |
| **On** (red) | The existing collection and all its objects are deleted before re-importing |

> ⚠️ *Replace if Existing* is highlighted in **red** when active as a visual warning — this operation is destructive and cannot be undone.

### Material Utilities

| Option | Description |
|--------|-------------|
| **Import Diffuse as Emissive** | After import, wires the texture connected to **Base Color** of every Principled BSDF directly to **Emission Color** as well, then sets **Emission Strength** to `1.0`. Works on all BSDF nodes in all materials — multi-material objects are fully supported. |

---

## Performance & Technical Notes

### No `bpy.ops` in the pipeline
All object and data manipulation uses the `bpy.data` API directly:
- **Empty creation** → `bpy.data.objects.new()` — no scene graph refresh
- **Pivot centering** → direct vertex offset on `mesh.vertices` — no selection side-effects
- **Scale baking** → per-component `v.co` multiplication — no `transform_apply` call

The only `bpy.ops` call is `wm.obj_import`, which is unavoidable.

### Undo disabled during import
Global undo (`preferences.edit.use_global_undo`) is disabled for the duration of the import and restored immediately after (or on ESC). This prevents Blender from storing hundreds of intermediate states in memory during a large batch.

### O(1) visibility updates
After each OBJ is imported, only the **immediately previous** collection is hidden. All earlier ones are already hidden from their own iteration — the loop cost is constant regardless of batch size.

### Modal operator
The import runs inside a Blender modal operator. The UI stays responsive throughout. Press `ESC` at any time to cancel — already-imported objects are kept and the undo preference is restored.

---

## Collection Structure

For each OBJ file named `MyAsset.obj`, AutoIngest produces:

```
📁 MyAsset              ← Collection
 ┣ ✛ EMPTY_MyAsset     ← Plain Axes Empty at (0, 0, 0)
 ┗ 🔷 MyAsset_mesh     ← Imported mesh(es), parented to the Empty
```

---

## Limitations & Known Issues

- Only `.obj` files are scanned. MTL files are loaded automatically by the native importer if they sit alongside the OBJ.
- *Apply Scale* only operates on `MESH` objects. Curves, surfaces or other types imported from OBJ groups are scaled but not baked.
- *Import Diffuse as Emissive* only patches **Principled BSDF** nodes. Custom shader setups are not modified.
- Collection suffix search (`_001` → `_999`) raises a `RuntimeError` if all 999 slots are taken.

---

## Changelog

### 1.1.0
- Added **Up Axis** selector (Forward deduced by Blender to prevent invalid combinations)
- Added **Replace if Existing** toggle with red alert state
- Added **Apply Scale** option (decouples scale baking from scale-to-reference)
- Added **Import Diffuse as Emissive** — now iterates all BSDF nodes per material
- Replaced all `bpy.ops` in the pipeline with `bpy.data` API calls
- O(1) visibility update (was O(n²))
- Global undo disabled during batch import to reduce RAM usage
- Start Import button is greyed out when no valid folder is selected

### 1.0.0
- Initial release

---

## License

MIT — free to use, modify and distribute. Credit appreciated.
