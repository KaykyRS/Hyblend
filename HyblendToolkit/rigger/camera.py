"""Auto-Rigger -- First Person Camera, exclusiva de HEAD."""

import math

import bpy
from bpy.types import Operator
from mathutils import Euler, Matrix

from ..common import is_active_armature
from ..translations import tooltip

from .constants import (
    FIRST_PERSON_CAMERA_SUFFIX,
)


def _build_first_person_camera(context, armature_obj, item):
    """Cria/atualiza o Object Camera bone-parented. Idempotente."""
    parent_bone_name = (item.head_camera_parent_bone or "").strip()
    if not parent_bone_name:
        return False, "No Camera Parent Bone set on this entry."
    data_bone = armature_obj.data.bones.get(parent_bone_name)
    if data_bone is None:
        return False, f"'{parent_bone_name}' not found on this armature."

    camera_name = armature_obj.name + FIRST_PERSON_CAMERA_SUFFIX
    camera_data = bpy.data.cameras.get(camera_name)
    if camera_data is None:
        camera_data = bpy.data.cameras.new(camera_name)
        camera_data.clip_start = 0.01
    # Reaplicado sempre, não só na criação, pra "Create Camera" repetido
    # já atualizar o FOV sem precisar apagar a câmera antes.
    camera_data.lens_unit = "FOV"
    camera_data.angle = math.radians(item.head_camera_fov)

    camera_obj = bpy.data.objects.get(camera_name)
    if camera_obj is None:
        camera_obj = bpy.data.objects.new(camera_name, camera_data)
        for coll in armature_obj.users_collection or [context.collection]:
            coll.objects.link(camera_obj)
    elif camera_obj.data is not camera_data:
        camera_obj.data = camera_data

    # Bone-parenting nativo posiciona relativo à TAIL do bone, não ao
    # head -- corrige com matrix_parent_inverse (mesmo mecanismo do
    # Atlas Plane do Texture Picker; já inverteu o sinal errado uma vez).
    camera_obj.parent = armature_obj
    camera_obj.parent_type = "BONE"
    camera_obj.parent_bone = parent_bone_name
    camera_obj.matrix_parent_inverse = Matrix.Translation((0.0, -data_bone.length, 0.0))
    camera_obj.location = (item.head_camera_offset_x, item.head_camera_offset_y, item.head_camera_offset_z)
    camera_obj.rotation_euler = Euler(
        (
            math.radians(item.head_camera_rotation_x),
            math.radians(item.head_camera_rotation_y),
            math.radians(item.head_camera_rotation_z),
        ),
        "XYZ",
    )

    return True, (
        f"First Person Camera '{camera_obj.name}' parented to '{parent_bone_name}'. Position/rotation are a "
        f"starting point, not a calibrated Hytale value -- fine-tune with the Camera Offset/Rotation fields "
        f"to line up with this character's eyes."
    )


def _remove_first_person_camera(armature_obj):
    """Desfaz _build_first_person_camera. Idempotente."""
    camera_name = armature_obj.name + FIRST_PERSON_CAMERA_SUFFIX
    camera_obj = bpy.data.objects.get(camera_name)
    if camera_obj is None:
        return False
    camera_data = camera_obj.data
    bpy.data.objects.remove(camera_obj, do_unlink=True)
    if camera_data is not None and camera_data.users == 0:
        bpy.data.cameras.remove(camera_data, do_unlink=True)
    return True


class RIG_OT_hytale_camera_create(Operator):
    """Botão 'Create Camera', sobre a entrada HEAD ativa da lista."""

    bl_idname = "armature.hytale_camera_create"
    bl_label = "Create Camera"
    description = tooltip("rigger.tooltip.camera_create")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        armature = obj.data
        index = armature.hytale_ik_chains_index
        if not (0 <= index < len(armature.hytale_ik_chains)):
            return False
        item = armature.hytale_ik_chains[index]
        if item.chain_type != "HEAD" or not item.head_camera_enabled:
            return False
        if not item.head_camera_parent_bone:
            cls.poll_message_set("Set a Camera Parent Bone on this entry first.")
            return False
        if armature.bones.get(item.head_camera_parent_bone) is None:
            cls.poll_message_set(f"'{item.head_camera_parent_bone}' not found on this armature.")
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        armature = obj.data
        item = armature.hytale_ik_chains[armature.hytale_ik_chains_index]
        ok, message = _build_first_person_camera(context, obj, item)
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class RIG_OT_hytale_camera_remove(Operator):
    """Botão 'Remove Camera', desfaz _build_first_person_camera."""

    bl_idname = "armature.hytale_camera_remove"
    bl_label = "Remove Camera"
    description = tooltip("rigger.tooltip.camera_remove")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        armature = obj.data
        index = armature.hytale_ik_chains_index
        return 0 <= index < len(armature.hytale_ik_chains) and armature.hytale_ik_chains[index].chain_type == "HEAD"

    def execute(self, context):
        obj = context.active_object
        removed = _remove_first_person_camera(obj)
        self.report({"INFO"}, "First Person Camera removed." if removed else "Nothing to remove.")
        return {"FINISHED"}
