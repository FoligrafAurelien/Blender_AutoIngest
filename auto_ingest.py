"""
AutoIngest - Blender 5.0.1 Plugin
Batch OBJ importer with pivot, scale reference, collection management,
diffuse→emissive transfer and visibility control.

Author  : Aurelien Binauld aka Foligraf
Version : 1.1.0
"""

bl_info = {
    "name": "AutoIngest",
    "author": "Aurelien Binauld aka Foligraf",
    "version": (1, 1, 0),
    "blender": (5, 0, 1),
    "location": "View3D > N-Panel > AutoIngest",
    "description": "Batch import OBJ files with auto-pivot, scale reference, collection setup and material utilities",
    "category": "Import-Export",
}

import bpy
import os
from pathlib import Path
from mathutils import Vector


# ─────────────────────────────────────────────────────────────────────────────
#  Axis enum items  (shared for Forward & Up)
# ─────────────────────────────────────────────────────────────────────────────

AXIS_ITEMS = [
    ("X",          "X",  ""),
    ("Y",          "Y",  ""),
    ("Z",          "Z",  ""),
    ("NEGATIVE_X", "-X", ""),
    ("NEGATIVE_Y", "-Y", ""),
    ("NEGATIVE_Z", "-Z", ""),
]


# ─────────────────────────────────────────────────────────────────────────────
#  Scene Properties
# ─────────────────────────────────────────────────────────────────────────────

class AutoIngestProperties(bpy.types.PropertyGroup):

    folder_path: bpy.props.StringProperty(
        name="Folder",
        description="Root folder to scan for OBJ files (sub-folders included)",
        subtype="DIR_PATH",
        default="",
    )

    # ── Axes ──────────────────────────────────────────────────────────────────
    # Only Up Axis is exposed. Blender's importer deduces Forward automatically,
    # which prevents invalid axis combinations (e.g. -Z / -Z).
    up_axis: bpy.props.EnumProperty(
        name="Up Axis",
        description="Up axis used by the OBJ importer (Forward is deduced by Blender)",
        items=AXIS_ITEMS,
        default="Y",
    )

    # ── Pivot / position ──────────────────────────────────────────────────────
    center_pivots: bpy.props.BoolProperty(
        name="Center All Pivots",
        description="Move each object's origin to its geometric center before positioning",
        default=True,
    )

    # ── Scale reference ───────────────────────────────────────────────────────
    use_scale_ref: bpy.props.BoolProperty(
        name="Scale to Reference",
        description="Scale every imported object so its longest axis matches the reference object",
        default=False,
    )
    reference_object: bpy.props.PointerProperty(
        name="Reference Object",
        description="Object whose longest-axis dimension is used as the scale target",
        type=bpy.types.Object,
    )

    # ── Replace existing ──────────────────────────────────────────────────────
    replace_existing: bpy.props.BoolProperty(
        name="Replace if Existing",
        description=(
            "ON  → delete existing collection with the same name and re-import\n"
            "OFF → keep existing collection and suffix the new one with _001 … _999"
        ),
        default=False,
    )

    # ── Apply Scale ───────────────────────────────────────────────────────────
    apply_scale: bpy.props.BoolProperty(
        name="Apply Scale",
        description=(
            "Bake the scale into vertex coordinates after scaling to reference.\n"
            "Recommended for export pipelines, rigging and modifiers.\n"
            "Disable if you prefer to keep a clean transform (scale stays visible)"
        ),
        default=True,
    )

    # ── Diffuse as Emissive ───────────────────────────────────────────────────
    diffuse_as_emissive: bpy.props.BoolProperty(
        name="Import Diffuse as Emissive",
        description=(
            "After import, wire the diffuse texture to the Emission Color socket "
            "of the Principled BSDF and set Emission Strength to 1"
        ),
        default=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers – geometry / scale
# ─────────────────────────────────────────────────────────────────────────────

def collect_obj_files(root: str) -> list:
    return sorted(Path(root).rglob("*.obj"))


def get_longest_axis_size(obj):
    """Return (world-space size along longest axis, axis index 0/1/2)."""
    bbox_world = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mins = Vector((min(v[i] for v in bbox_world) for i in range(3)))
    maxs = Vector((max(v[i] for v in bbox_world) for i in range(3)))
    dims = maxs - mins
    axis = list(dims).index(max(dims))
    return dims[axis], axis


def set_origin_to_geometry(obj):
    """
    Move the object's origin to its bounding-box center using only bpy.data.
    No bpy.ops → no scene graph refresh, no selection side-effects.

    Strategy:
      1. Compute the bbox center in local space.
      2. Shift all vertices by -center_local so geometry is centred on origin.
      3. Compensate in world space by moving obj.location by +center_world_delta.
    """
    if obj.type != "MESH" or obj.data is None:
        return

    mesh = obj.data
    if not mesh.vertices:
        return

    # Bounding-box center in local space (bound_box is already in local coords)
    bbox_local = [Vector(c) for c in obj.bound_box]
    center_local = sum(bbox_local, Vector()) / 8.0

    # Shift every vertex so the centre lands on the local origin
    for v in mesh.vertices:
        v.co -= center_local

    # Translate the object in world space to compensate
    # (matrix_world converts local → world, without moving the geometry visually)
    obj.location = obj.matrix_world @ center_local
    mesh.update()


def apply_scale_reference(objects, ref_obj, apply_scale: bool):
    """
    Homothetic scale so the longest axis of each object matches ref_obj.
    Uses only bpy.data — no bpy.ops, no selection side-effects.

    If *apply_scale* is True, the scale is baked into vertex coordinates
    so obj.scale returns to (1, 1, 1).  Otherwise the scale factor is left
    as a transform, which is cleaner visually but may cause issues downstream.
    """
    ref_size, _ = get_longest_axis_size(ref_obj)
    if ref_size == 0:
        return

    for obj in objects:
        obj_size, _ = get_longest_axis_size(obj)
        if obj_size == 0:
            continue

        factor = ref_size / obj_size
        obj.scale *= factor   # homothetic: all 3 axes × same factor

        if apply_scale and obj.type == "MESH" and obj.data is not None:
            # Bake scale into vertex coords without bpy.ops.transform_apply.
            # We build a pure-scale matrix from the current object scale and
            # apply it to every vertex position directly.
            sx, sy, sz = obj.scale
            for v in obj.data.vertices:
                v.co.x *= sx
                v.co.y *= sy
                v.co.z *= sz
            obj.scale = (1.0, 1.0, 1.0)
            obj.data.update()


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers – materials
# ─────────────────────────────────────────────────────────────────────────────

def apply_diffuse_as_emissive(objects):
    """
    For EVERY Principled BSDF found in every material of *objects*:
    - retrieve the exact output socket wired to Base Color
    - connect it to Emission Color as well (shared link, no texture duplication)
    - set Emission Strength to 1.0

    Iterates ALL BSDF_PRINCIPLED nodes so multi-material objects and complex
    node graphs (e.g. OBJ groups that spawn several shaders) are fully covered.
    """
    for obj in objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or mat.node_tree is None:
                continue
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links

            # ── Loop over ALL Principled BSDF nodes, not just the first ───────
            for principled in (n for n in nodes if n.type == "BSDF_PRINCIPLED"):
                base_color_in = principled.inputs.get("Base Color")
                if base_color_in is None or not base_color_in.is_linked:
                    continue

                from_socket = base_color_in.links[0].from_socket

                # Blender 4+ uses "Emission Color"; older builds use "Emission"
                emission_in = (
                    principled.inputs.get("Emission Color")
                    or principled.inputs.get("Emission")
                )
                if emission_in is None:
                    continue

                links.new(from_socket, emission_in)

                strength_in = principled.inputs.get("Emission Strength")
                if strength_in is not None:
                    strength_in.default_value = 1.0


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers – collections & visibility
# ─────────────────────────────────────────────────────────────────────────────

def unique_collection_name(base_name: str) -> str:
    """
    Return *base_name* if available, otherwise *base_name*_001 … _999.
    """
    if base_name not in bpy.data.collections:
        return base_name
    for i in range(1, 1000):
        candidate = f"{base_name}_{i:03d}"
        if candidate not in bpy.data.collections:
            return candidate
    raise RuntimeError(f"All suffixes exhausted for collection '{base_name}'")


def delete_collection_recursive(col):
    """Remove a collection, all its children and every object they contain."""
    for child_col in list(col.children):
        delete_collection_recursive(child_col)
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(col)


def find_layer_collection(layer_col, name: str):
    if layer_col.collection.name == name:
        return layer_col
    for child in layer_col.children:
        result = find_layer_collection(child, name)
        if result:
            return result
    return None


def set_collection_visibility(col_name: str, visible: bool):
    layer_col = find_layer_collection(
        bpy.context.view_layer.layer_collection, col_name
    )
    if layer_col:
        layer_col.exclude = not visible


def move_to_collection(obj, col):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)


# ─────────────────────────────────────────────────────────────────────────────
#  OBJ import wrapper
# ─────────────────────────────────────────────────────────────────────────────

def import_obj_file(filepath: Path, up_axis: str) -> list:
    before = set(bpy.data.objects)
    bpy.ops.wm.obj_import(
        filepath=str(filepath),
        up_axis=up_axis,
    )
    return [o for o in bpy.data.objects if o not in before]


# ─────────────────────────────────────────────────────────────────────────────
#  Per-file pipeline
# ─────────────────────────────────────────────────────────────────────────────

def process_single_obj(filepath: Path, settings: dict, created_collections: list):
    """
    Full pipeline for one OBJ file.
    *created_collections* is a running list; every collection added here is
    appended so the next call can hide it before making the new one visible.
    """
    stem = filepath.stem

    # ── Handle name collision ──────────────────────────────────────────────────
    if settings["replace_existing"] and stem in bpy.data.collections:
        delete_collection_recursive(bpy.data.collections[stem])
        col_name = stem
    else:
        col_name = unique_collection_name(stem)

    # ── Import ─────────────────────────────────────────────────────────────────
    new_objects = import_obj_file(
        filepath, settings["up_axis"]
    )
    if not new_objects:
        return

    # ── Center pivots ──────────────────────────────────────────────────────────
    if settings["center_pivots"]:
        for obj in new_objects:
            set_origin_to_geometry(obj)

    # ── Move to world origin ───────────────────────────────────────────────────
    for obj in new_objects:
        obj.location = (0.0, 0.0, 0.0)

    # ── Scale to reference ─────────────────────────────────────────────────────
    if settings["use_scale_ref"] and settings["ref_obj"] is not None:
        apply_scale_reference(new_objects, settings["ref_obj"], settings["apply_scale"])

    # ── Diffuse as emissive ────────────────────────────────────────────────────
    if settings["diffuse_as_emissive"]:
        apply_diffuse_as_emissive(new_objects)

    # ── Create Empty (Plain Axes) via bpy.data — no ops, no scene refresh ────
    empty = bpy.data.objects.new(f"EMPTY_{stem}", None)
    empty.empty_display_type = "PLAIN_AXES"
    # Link into scene so it appears in the outliner (will be moved to col below)
    bpy.context.scene.collection.objects.link(empty)

    # ── Parent objects → empty ─────────────────────────────────────────────────
    for obj in new_objects:
        obj.parent = empty
        obj.matrix_parent_inverse.identity()

    # ── Create collection ──────────────────────────────────────────────────────
    col = bpy.data.collections.new(col_name)
    bpy.context.scene.collection.children.link(col)

    move_to_collection(empty, col)
    for obj in new_objects:
        move_to_collection(obj, col)

    # ── Visibility: O(1) — only hide the immediately preceding collection ─────
    # All earlier ones are already hidden from their own iteration.
    # New collections start visible by default, so we only touch the last one.
    if created_collections:
        set_collection_visibility(created_collections[-1], False)

    set_collection_visibility(col_name, True)
    created_collections.append(col_name)


# ─────────────────────────────────────────────────────────────────────────────
#  Modal Operator
# ─────────────────────────────────────────────────────────────────────────────

class AUTOINGEST_OT_Import(bpy.types.Operator):
    bl_idname = "autoingest.import"
    bl_label = "Import OBJ Files"
    bl_description = "Scan the selected folder and import all OBJ files"
    bl_options = {"REGISTER", "UNDO"}

    _timer = None
    _obj_files: list = []
    _index: int = 0
    _total: int = 0
    _errors: list = []
    _settings: dict = {}
    _created_collections: list = []
    _undo_was_enabled: bool = True   # snapshot of preferences.edit.use_global_undo

    def invoke(self, context, event):
        props = context.scene.autoingest

        if not props.folder_path or not os.path.isdir(props.folder_path):
            self.report({"ERROR"}, "Please select a valid folder.")
            return {"CANCELLED"}

        if props.use_scale_ref and props.reference_object is None:
            self.report({"ERROR"}, "Scale to Reference is enabled but no reference object is set.")
            return {"CANCELLED"}

        obj_files = collect_obj_files(props.folder_path)
        if not obj_files:
            self.report({"WARNING"}, "No OBJ files found in the selected folder.")
            return {"CANCELLED"}

        cls = self.__class__
        cls._obj_files = obj_files
        cls._index = 0
        cls._total = len(obj_files)
        cls._errors = []
        cls._created_collections = []
        cls._settings = {
            "up_axis":             props.up_axis,
            "center_pivots":       props.center_pivots,
            "use_scale_ref":       props.use_scale_ref,
            "ref_obj":             props.reference_object,
            "apply_scale":         props.apply_scale,
            "replace_existing":    props.replace_existing,
            "diffuse_as_emissive": props.diffuse_as_emissive,
        }

        # ── Disable undo for the duration of the import ───────────────────────
        # Storing every intermediate state in the undo stack during a batch
        # import of hundreds of OBJs would saturate RAM needlessly.
        # We save the current setting, turn it off, and restore it in _finish().
        cls._undo_was_enabled = context.preferences.edit.use_global_undo
        context.preferences.edit.use_global_undo = False

        self._timer = context.window_manager.event_timer_add(0.01, window=context.window)
        context.window_manager.modal_handler_add(self)
        context.scene.autoingest_progress = 0
        context.scene.autoingest_running = True
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        cls = self.__class__

        if event.type == "ESC":
            return self._finish(context, cancelled=True)

        if event.type == "TIMER":
            if cls._index >= cls._total:
                return self._finish(context)

            # Show progress BEFORE the heavy import so the bar moves immediately.
            # (index + 1) so the very first file already shows > 0 %.
            context.scene.autoingest_progress = int(((cls._index + 1) / cls._total) * 100)

            # Force the depsgraph to acknowledge bpy.data changes from the
            # previous tick before we start the next import and before redraw.
            context.view_layer.update()

            # Tag only the UI region of every VIEW_3D area across all windows.
            # The N-Panel lives in region type 'UI' — more precise than tagging
            # the entire area, and covers multi-window setups.
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == "VIEW_3D":
                        for region in area.regions:
                            if region.type == "UI":
                                region.tag_redraw()

            filepath = cls._obj_files[cls._index]
            try:
                process_single_obj(filepath, cls._settings, cls._created_collections)
            except Exception as e:
                cls._errors.append(f"{filepath.name}: {e}")

            cls._index += 1

        return {"PASS_THROUGH"}

    def _finish(self, context, cancelled=False):
        cls = self.__class__
        context.window_manager.event_timer_remove(self._timer)

        # ── Restore undo preference ────────────────────────────────────────────
        context.preferences.edit.use_global_undo = cls._undo_was_enabled

        context.scene.autoingest_running = False
        context.scene.autoingest_progress = 0

        if cancelled:
            self.report({"WARNING"}, f"Import cancelled after {cls._index}/{cls._total} files.")
        else:
            msg = f"AutoIngest: {cls._total - len(cls._errors)} OBJ(s) imported."
            if cls._errors:
                msg += f"  {len(cls._errors)} error(s) – see system console."
                for e in cls._errors:
                    print(f"[AutoIngest ERROR] {e}")
            self.report({"INFO"}, msg)

        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
#  UI Panel
# ─────────────────────────────────────────────────────────────────────────────

class AUTOINGEST_PT_MainPanel(bpy.types.Panel):
    bl_label = "AutoIngest"
    bl_idname = "AUTOINGEST_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AutoIngest"

    def draw_header(self, context):
        self.layout.label(icon="IMPORT")

    def draw(self, context):
        layout = self.layout
        props = context.scene.autoingest
        running = getattr(context.scene, "autoingest_running", False)
        progress = getattr(context.scene, "autoingest_progress", 0)

        # ── Folder ────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Source Folder", icon="FILE_FOLDER")
        box.prop(props, "folder_path", text="")

        layout.separator(factor=0.5)

        # ── Import Axes ───────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Import Axes", icon="ORIENTATION_GLOBAL")
        box.prop(props, "up_axis", text="Up Axis")

        layout.separator(factor=0.5)

        # ── Import Options ────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Import Options", icon="SETTINGS")

        box.prop(props, "center_pivots")

        box.separator(factor=0.3)
        box.prop(props, "use_scale_ref")
        sub = box.column()
        sub.enabled = props.use_scale_ref
        sub.prop(props, "reference_object", text="Reference")
        # Apply Scale is only meaningful when Scale to Reference is active
        sub2 = box.column()
        sub2.enabled = props.use_scale_ref
        sub2.prop(props, "apply_scale")

        layout.separator()

        # ── Start Import ──────────────────────────────────────────────────────
        # Button is greyed out when no valid folder is set (UX protection)
        folder_ok = bool(props.folder_path and os.path.isdir(props.folder_path))

        if running:
            col = layout.column(align=True)
            col.label(text=f"Importing… {progress}%", icon="TIME")
            col.progress(factor=progress / 100.0, text=f"{progress}%")
            col.separator(factor=0.3)
            col.label(text="Press ESC to cancel", icon="ERROR")
        else:
            row = layout.row()
            row.enabled = folder_ok   # greys out automatically when no folder set
            row.scale_y = 1.8
            row.operator(
                AUTOINGEST_OT_Import.bl_idname,
                text="  Start Import",
                icon="PLAY",
            )

        # ── Replace if existing  ──────────────────────────────────────────────
        # row.alert = True → Blender renders the widget in red when ON
        row = layout.row()
        row.alert = props.replace_existing
        row.prop(
            props,
            "replace_existing",
            toggle=True,
            icon="TRASH",
        )

        layout.separator(factor=0.8)

        # ── Material Utilities (bottom) ───────────────────────────────────────
        box = layout.box()
        box.label(text="Material Utilities", icon="MATERIAL")
        box.prop(props, "diffuse_as_emissive")


# ─────────────────────────────────────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────────────────────────────────────

CLASSES = (
    AutoIngestProperties,
    AUTOINGEST_OT_Import,
    AUTOINGEST_PT_MainPanel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.autoingest = bpy.props.PointerProperty(type=AutoIngestProperties)
    bpy.types.Scene.autoingest_progress = bpy.props.IntProperty(default=0, min=0, max=100)
    bpy.types.Scene.autoingest_running = bpy.props.BoolProperty(default=False)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.autoingest
    del bpy.types.Scene.autoingest_progress
    del bpy.types.Scene.autoingest_running


if __name__ == "__main__":
    register()
