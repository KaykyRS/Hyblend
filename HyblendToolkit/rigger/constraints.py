"""Auto-Rigger -- helpers de constraint/driver/switch e cálculo de pole angle."""

import bpy
from mathutils import Vector

from ..translations import get_language, tr

from .constants import (
    CONSTRAINT_IK,
    PROP_FK_IK_SWITCH,
    PROP_RIG_LAYER,
    _COPY_CONSTRAINT_TYPES,
)


def ensure_copy_constraint(pose_bone, target_obj, subtarget_name, copy_type, name, space="LOCAL", head_tail=None):
    con = pose_bone.constraints.get(name)
    if con is None:
        con = pose_bone.constraints.new(_COPY_CONSTRAINT_TYPES[copy_type])
        con.name = name
    con.target = target_obj
    con.subtarget = subtarget_name
    con.target_space = space
    con.owner_space = space
    con.mute = False
    if head_tail is not None and copy_type == "LOCATION":  # head_tail só existe em COPY_LOCATION
        con.head_tail = head_tail
    return con


def ensure_copy_set(pose_bone, target_obj, subtarget_name, name_prefix, types=("LOCATION", "ROTATION", "SCALE")):
    result = {}
    for copy_type in types:
        cname = f"{name_prefix}_{copy_type.title()}"
        result[copy_type] = ensure_copy_constraint(pose_bone, target_obj, subtarget_name, copy_type, cname)
    return result


def ensure_ik_constraint(pose_bone, armature_obj, target_name, pole_name, chain_count, pole_angle_rad):
    con = pose_bone.constraints.get(CONSTRAINT_IK)
    if con is None:
        con = pose_bone.constraints.new("IK")
        con.name = CONSTRAINT_IK
    con.target = armature_obj
    con.subtarget = target_name
    con.pole_target = armature_obj
    con.pole_subtarget = pole_name
    con.chain_count = chain_count
    con.pole_angle = pole_angle_rad
    con.use_tail = True
    return con


def ensure_child_of_constraint(pose_bone, armature_obj, subtarget_name, name, influence):
    con = pose_bone.constraints.get(name)
    if con is None:
        con = pose_bone.constraints.new("CHILD_OF")
        con.name = name
    con.target = armature_obj
    con.subtarget = subtarget_name
    con.influence = influence
    return con


def ensure_stretch_to_constraint(pose_bone, armature_obj, subtarget_name, name):
    """Stretch To simples, sempre esticando pro subtarget -- usado pelo
    bone "_Pole_Line" mirando no "_Pole_CTRL" do mesmo lado/cadeia."""
    con = pose_bone.constraints.get(name)
    if con is None:
        con = pose_bone.constraints.new("STRETCH_TO")
        con.name = name
    con.target = armature_obj
    con.subtarget = subtarget_name
    con.rest_length = 0.0
    return con


def switch_property_name(tip_org_name, side):
    """Nome da custom property de FK/IK switch de uma cadeia (guardada
    no bone PROPERTIES). Prefixo tirado do ORG da ponta + sufixo L/R,
    pra não colidir quando duas cadeias moram no mesmo bone.
    Ex.: "L-Hand" + "LEFT" -> "hand_fk_ik_switch_L"."""
    base = tip_org_name
    for prefix in ("L-", "R-"):
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    prefix_word = base.lower()
    suffix = "L" if side == "LEFT" else "R"
    return f"{prefix_word}_{PROP_FK_IK_SWITCH}_{suffix}"


def ensure_switch_property(pose_bone, prop_name, description=None, default_value=0):
    """Cria (ou reaproveita) uma custom property 0..1 com UI configurada
    -- usado por qualquer switch de constraint por driver deste addon
    (ver add_switch_driver). default_value só é aplicado na CRIAÇÃO,
    nunca sobrescreve um valor que o usuário já tenha ajustado."""
    if description is None:
        description = tr("rigger.runtime.fk_ik_switch_description", get_language(bpy.context))
    if prop_name not in pose_bone.keys():
        pose_bone[prop_name] = default_value
    try:
        ui = pose_bone.id_properties_ui(prop_name)
        ui.update(min=0, max=1, default=default_value, description=description)
    except Exception:
        pass


def add_switch_driver(constraint, armature_obj, switch_bone_name, switch_prop_name, expression="switch"):
    """Liga constraint.influence à custom property de switch do bone
    PROPERTIES. `expression`: "switch" segue o IK, "1 - switch" o FK."""
    constraint.driver_remove("influence")
    fcurve = constraint.driver_add("influence")
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    driver.expression = expression
    for existing_var in list(driver.variables):
        driver.variables.remove(existing_var)
    var = driver.variables.new()
    var.name = "switch"
    var.type = "SINGLE_PROP"
    target = var.targets[0]
    target.id_type = "OBJECT"
    target.id = armature_obj
    target.data_path = f'pose.bones["{switch_bone_name}"]["{switch_prop_name}"]'


def add_custom_shape_scale_switch_driver(pose_bone, armature_obj, switch_bone_name, switch_prop_name, target_scale, mode):
    """Liga custom_shape_scale_xyz à custom property de switch -- um
    driver por eixo (0/1/2). `target_scale` é o tamanho "cheio" deste
    bone, embutido como literal em cada driver (bones diferentes podem
    ter alvos diferentes sem cálculo compartilhado). `mode`: "IK" fica
    visível quando switch=1, "FK" quando switch=0."""
    template = "{v}*switch" if mode == "IK" else "{v}*(1 - switch)"
    for i in range(3):
        pose_bone.driver_remove("custom_shape_scale_xyz", i)
        fcurve = pose_bone.driver_add("custom_shape_scale_xyz", i)
        driver = fcurve.driver
        driver.type = "SCRIPTED"
        driver.expression = template.format(v=target_scale[i])
        for existing_var in list(driver.variables):
            driver.variables.remove(existing_var)
        var = driver.variables.new()
        var.name = "switch"
        var.type = "SINGLE_PROP"
        target = var.targets[0]
        target.id_type = "OBJECT"
        target.id = armature_obj
        target.data_path = f'pose.bones["{switch_bone_name}"]["{switch_prop_name}"]'


def armature_has_generated_bones(armature):
    """True se "Create Rig" já rodou pelo menos uma vez (algum bone tem
    PROP_RIG_LAYER). Usa armature.bones, não edit_bones -- funciona em
    qualquer modo."""
    return any(PROP_RIG_LAYER in b.keys() for b in armature.bones)


def _angle_on_plane(plane, vec1, vec2):
    """Ângulo entre dois vetores projetados num plano."""
    v1 = vec1 - plane * plane.dot(vec1)
    v2 = vec2 - plane * plane.dot(vec2)
    if v1.length < 1e-9 or v2.length < 1e-9:
        return 0.0
    v1.normalize()
    v2.normalize()
    angle = v1.angle(v2)
    if v1.cross(v2).dot(plane) < 0:
        angle = -angle
    return angle


def compute_pole_angle_edit(armature_obj, base_bone, pole_bone):
    """Mesma matemática de compute_pole_angle, mas em Edit Bones (world
    space direto) -- pra medir o DELTA de pole_angle causado por mover
    um bone, sem sair do Edit Mode. O chamador também inverte o sinal,
    igual lá."""
    arm_matrix = armature_obj.matrix_world
    base_head = arm_matrix @ base_bone.head
    base_tail = arm_matrix @ base_bone.tail
    pole_head = arm_matrix @ pole_bone.head

    base_vector = base_tail - base_head
    if base_vector.length < 1e-9:
        return 0.0
    base_vector.normalize()

    base_x_axis = arm_matrix.to_3x3() @ base_bone.x_axis
    if base_x_axis.length < 1e-9:
        return 0.0
    base_x_axis.normalize()

    pole_normal = (pole_head - base_head).cross(pole_head - base_tail)
    projected_pole_axis = pole_normal.cross(base_tail - base_head)

    return _angle_on_plane(base_vector, base_x_axis, projected_pole_axis)


def compute_pole_angle(armature_obj, base_bone_name, pole_bone_name):
    """Pole_angle "cru" pra rest pose atual. O chamador inverte o sinal
    do resultado (correção empírica, ver _build_pose_constraints)."""
    bones = armature_obj.data.bones
    base = bones.get(base_bone_name)
    pole = bones.get(pole_bone_name)
    if base is None or pole is None:
        return 0.0

    arm_matrix = armature_obj.matrix_world
    base_head = arm_matrix @ base.matrix_local.translation
    base_tail = arm_matrix @ (base.matrix_local @ Vector((0.0, base.length, 0.0)))
    pole_head = arm_matrix @ pole.matrix_local.translation

    base_vector = base_tail - base_head
    if base_vector.length < 1e-9:
        return 0.0
    base_vector.normalize()

    base_x_axis = arm_matrix.to_3x3() @ base.matrix_local.to_3x3() @ Vector((1.0, 0.0, 0.0))
    if base_x_axis.length < 1e-9:
        return 0.0
    base_x_axis.normalize()

    pole_normal = (pole_head - base_head).cross(pole_head - base_tail)
    projected_pole_axis = pole_normal.cross(base_tail - base_head)

    return _angle_on_plane(base_vector, base_x_axis, projected_pole_axis)
