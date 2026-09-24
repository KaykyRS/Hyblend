"""Auto-Rigger -- Validate Rig (diagnóstico read-only) e Clear Generated Bones."""

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Menu, Operator

from ..common import BONE_RIGGER_CREATED_PROP, is_active_armature
from ..templates import (
    get_rig_template,
)
from ..translations import localized_props, tooltip, tr

from .constants import (
    COLL_INTERNAL,
    COLL_MAIN,
    COLL_ORG,
    CONSTRAINT_ORG_TO_MCH,
    PROP_RIG_LAYER,
    SUFFIX_CTRL,
)

from .helpers import _find_bone_collection_anywhere, _resolve_parent_override, control_name, resolve_root_slots, set_bone_collection_visibility
from .widgets import _find_widgets_collection, _unlink_and_remove_collection
from .bone_collections import _head_spine_bone_names
from .bone_settings import find_shared_pole_angle_preset_warnings, resolve_pole_angle_preset_degrees
from .texture_picker import _remove_texture_picker, _texture_picker_cursor_name
from .camera import _remove_first_person_camera


def _validate_rig_props(lang):
    return {
        "export_collection_name": StringProperty(
            name="Export Collection",
            default="Hytale Export",
            description=tr("rigger.prop.validate_rig_export_collection_name", lang),
        ),
    }


@localized_props(_validate_rig_props)
class RIG_OT_hytale_validate_rig(Operator):
    """Diagnóstico read-only, não muda nada no rig. Roda 4 checagens e
    relata cada problema como WARNING (ou um INFO "tudo certo"):
    1. Nomes de bone (root/tip/pole/parent_override, Head/Spine/
       Attachments/Texture Picker, câmera) que não existem no armature.
    2. Preset de pole angle que não existe no rig template ativo.
    3. Mesmo preset compartilhado por chain_types diferentes.
    4. Bones ORG fora da bone collection de export."""

    bl_idname = "armature.hytale_validate_rig"
    bl_label = "Validate Rig"
    description = tooltip("rigger.tooltip.validate_rig")
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def execute(self, context):
        armature = context.active_object.data
        bones = armature.bones  # funciona em qualquer modo, não precisa de Edit Mode
        problems = []

        # 1. Nomes de bone que não existem, por item da lista.
        for i, item in enumerate(armature.hytale_ik_chains):
            label = item.label or f"#{i}"
            if item.root_bone and bones.get(item.root_bone) is None:
                problems.append(f"Chain '{label}': root_bone '{item.root_bone}' not found on this armature.")
            if item.tip_bone and bones.get(item.tip_bone) is None:
                problems.append(f"Chain '{label}': tip_bone '{item.tip_bone}' not found on this armature.")
            if item.pole_bone and bones.get(item.pole_bone) is None:
                problems.append(f"Chain '{label}': pole_bone '{item.pole_bone}' not found on this armature.")
            if item.parent_override and _resolve_parent_override(bones, item.parent_override) is None:
                problems.append(
                    f"Chain '{label}': parent_override '{item.parent_override}' does not resolve to any "
                    f"bone on this armature (checked PARENT_OVERRIDE_ALIASES and the literal name)."
                )
            if item.chain_type in ("HEAD", "SPINE", "ATTACHMENTS", "TEXTURE_PICKER"):
                for name in _head_spine_bone_names(item):
                    if bones.get(name) is None:
                        problems.append(f"{item.chain_type.title()} '{label}': bone '{name}' not found on this armature.")
                    elif bones.get(control_name(armature, name, SUFFIX_CTRL)) is None:
                        problems.append(
                            f"{item.chain_type.title()} '{label}': '{name}' exists, but its control bone "
                            f"'{control_name(armature, name, SUFFIX_CTRL)}' doesn't -- Create Rig hasn't run yet, or this bone is "
                            f"excluded from the generic ORG->CTRL loop."
                        )
            if item.chain_type == "ROOT":
                # Só a PRIMEIRA entrada ROOT vale (ver resolve_root_item).
                first_root = next(c for c in armature.hytale_ik_chains if c.chain_type == "ROOT")
                if first_root.as_pointer() != item.as_pointer():
                    problems.append(f"Root '{label}': only the first Root entry is used -- this one is ignored.")
                else:
                    slots = resolve_root_slots(armature)
                    if not slots:
                        problems.append(
                            f"Root '{label}': Origin (Root 1) is empty -- the whole Root entry is ignored and the "
                            f"legacy 'Origin' bone is used instead. Pick a bone or turn on 'New Bone'."
                        )
                    for slot, name, create in slots:
                        if bones.get(name) is None:
                            if not create:
                                problems.append(f"Root '{label}': Root {slot} bone '{name}' not found on this armature.")
                            # "New Bone" que ainda não existe: Create Rig cria -- não é problema.
                        elif bones.get(control_name(armature, name, SUFFIX_CTRL)) is None:
                            problems.append(
                                f"Root '{label}': '{name}' exists, but its control bone '{control_name(armature, name, SUFFIX_CTRL)}' "
                                f"doesn't -- Create Rig hasn't run yet."
                            )
            if item.chain_type in ("HEAD", "SPINE") and item.continuous_chain:
                link_name = (item.continuous_chain_link_bone or "").strip()
                if link_name and bones.get(link_name) is None:
                    problems.append(
                        f"{item.chain_type.title()} '{label}': continuous_chain connect target "
                        f"'{link_name}' not found on this armature."
                    )
            # O cursor/root da UI do Texture Picker só existe depois de
            # "Create Texture Picker" -- aviso separado, não erro.
            if item.chain_type == "TEXTURE_PICKER" and item.texture_picker_bone:
                cursor_name = _texture_picker_cursor_name(item.texture_picker_bone.strip())
                if bones.get(cursor_name) is None:
                    problems.append(
                        f"Texture Picker '{label}': '{cursor_name}' not found -- 'Create Texture Picker' hasn't "
                        f"been run yet for this entry."
                    )
            if item.chain_type == "HEAD" and item.head_camera_enabled:
                camera_bone_name = (item.head_camera_parent_bone or "").strip()
                if not camera_bone_name:
                    problems.append(f"Head '{label}': Create First Person Camera is on, but no Camera Parent Bone is set.")
                elif bones.get(camera_bone_name) is None:
                    problems.append(
                        f"Head '{label}': Camera Parent Bone '{camera_bone_name}' not found on this armature."
                    )

        # 2. Preset de pole angle que não existe no template ativo.
        rig_template = get_rig_template(getattr(armature, "hytale_active_rig_template", ""))
        for i, item in enumerate(armature.hytale_ik_chains):
            if item.pole_angle_mode != "PRESET":
                continue
            label = item.label or f"#{i}"
            deg = resolve_pole_angle_preset_degrees(rig_template, item.pole_angle_preset_name, item.side)
            if deg is None:
                template_name = getattr(armature, "hytale_active_rig_template", "") or "(none)"
                problems.append(
                    f"Chain '{label}': pole angle preset '{item.pole_angle_preset_name}' (side "
                    f"'{item.side}') not found in the active rig template ('{template_name}')."
                )

        # 3. Mesmo preset compartilhado por chain_types diferentes.
        chains_data = [
            {
                "pole_angle_mode": item.pole_angle_mode,
                "pole_angle_preset_name": item.pole_angle_preset_name,
                "chain_type": item.chain_type,
            }
            for item in armature.hytale_ik_chains
        ]
        for name, types in find_shared_pole_angle_preset_warnings(chains_data):
            problems.append(
                f"Pole angle preset '{name}' is used in PRESET mode by more than one chain type "
                f"({', '.join(types)}) -- they'll share the exact same calibrated angle per side."
            )

        # 4. Bones originais fora da collection de export.
        export_coll_name = self.export_collection_name or "Hytale Export"
        export_coll = _find_bone_collection_anywhere(armature, export_coll_name)
        if export_coll is None:
            problems.append(
                f"Bone collection '{export_coll_name}' not found on this armature -- can't check which "
                f"original bones are/aren't marked for export."
            )
        else:
            # bone.collections só aceita STRING no `in`, não o objeto
            # BoneCollection -- comparação por nome (TypeError em
            # runtime senão, não pego por ast.parse/pyflakes).
            export_members = {
                b.name for b in bones
                if any(c.name == export_coll.name for c in b.collections)
            }
            for bone in bones:
                if PROP_RIG_LAYER in bone.keys():
                    continue  # só bones ORG entram nesta checagem
                if bone.get(BONE_RIGGER_CREATED_PROP):
                    continue  # criado pelo rigger (Origin/Root "New Bone") -- fora do export de propósito
                if bone.name not in export_members:
                    problems.append(
                        f"Original bone '{bone.name}' is not in the '{export_coll_name}' bone collection -- "
                        f"it may be skipped on export."
                    )

        if not problems:
            self.report({"INFO"}, "Validate Rig: no issues found.")
            return {"FINISHED"}

        for problem in problems:
            self.report({"WARNING"}, problem)
        self.report({"WARNING"}, f"Validate Rig: {len(problems)} issue(s) found (see warnings above).")
        return {"FINISHED"}


# --- Remove bones gerados ---


def _clear_generated_props(lang):
    return {
        "mode": EnumProperty(
            items=[
                (
                    "ONLY_RIG",
                    "Only Rig",
                    tr("rigger.prop.clear_generated_mode_item_only_rig", lang),
                ),
                (
                    "DELETE_ALL",
                    "Delete All",
                    tr("rigger.prop.clear_generated_mode_item_delete_all", lang),
                ),
            ],
            default="ONLY_RIG",
        ),
    }


@localized_props(_clear_generated_props)
class RIG_OT_hytale_clear_generated(Operator):
    """Apaga todo bone criado por "Create Rig" (MCH, CTRL, CTRL-IK,
    MCH-IK/bridge, Pole, bones utilitários root.*), deixando só os
    bones ORG originais. Dois modos, escolhidos num menu popup:

    - ONLY_RIG: bones gerados + bone collections reais sob Main +
      artefatos do Texture Picker/First Person Camera. Não mexe em
      Bone Settings/Collection Settings, nem purga widgets (edição
      manual em Shape Edit Mode sobrevive a este modo).
    - DELETE_ALL: tudo isso, mais purga os widgets (WGT) e limpa Bone
      Settings/Collection Settings por completo -- volta pro estado
      "nunca configurado", útil pra pegar remodelagens novas de
      hytale_widgets.blend (um template já presente na cena nunca é
      atualizado sozinho por ensure_widget_objects)."""

    bl_idname = "armature.hytale_clear_generated_rig"
    bl_label = "Remove Generated Hytale Rig Bones"
    description = tooltip("rigger.tooltip.clear_generated")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        if getattr(obj.data, "hytale_shape_edit_mode", False):
            cls.poll_message_set(
                "Finish Shape Edit Mode first -- removing the generated bones now would discard it.",
            )
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        prev_mode = obj.mode
        bpy.ops.object.mode_set(mode="EDIT")
        removed = 0
        for bone in list(obj.data.edit_bones):
            # Bones criados pelo rigger (Origin automático / Root "New
            # Bone") também são "gerados" -- saem junto.
            if PROP_RIG_LAYER in bone.keys() or bone.get(BONE_RIGGER_CREATED_PROP):
                obj.data.edit_bones.remove(bone)
                removed += 1
        set_bone_collection_visibility(obj.data, {COLL_INTERNAL, COLL_ORG})
        bpy.ops.object.mode_set(mode="OBJECT")

        # Os bones ORG ficam, mas os constraints que o Create Rig pôs neles
        # (o trio Hytale_ORG_to_MCH_Location/Rotation/Scale, que faz o ORG
        # seguir o _MCH) apontariam pra bones que acabaram de ser apagados.
        # Só esse trio sai, pelo nome -- constraint que o usuário colocou
        # num ORG não é tocado.
        org_constraints_removed = 0
        org_constraint_prefix = CONSTRAINT_ORG_TO_MCH + "_"
        for pose_bone in obj.pose.bones:
            for con in list(pose_bone.constraints):
                if con.name.startswith(org_constraint_prefix):
                    pose_bone.constraints.remove(con)
                    org_constraints_removed += 1

        if prev_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=prev_mode)

        # Apaga a collection real Main e tudo aninhado dentro dela
        # (recursivamente) -- Internal/ORG/MCH/CTRL/CTRL-IK/Hytale
        # Export ficam de fora, não são "organização do usuário". Não
        # mexe na LISTA de config (hytale_bone_collections) aqui -- só
        # em DELETE_ALL, mais abaixo.
        removed_collections = 0

        def _remove_tree(coll):
            nonlocal removed_collections
            for child in list(coll.children):
                _remove_tree(child)
            obj.data.collections.remove(coll)
            removed_collections += 1

        main_coll = _find_bone_collection_anywhere(obj.data, COLL_MAIN)
        if main_coll is not None:
            _remove_tree(main_coll)

        purged = 0
        if self.mode == "DELETE_ALL":
            widgets_collection = _find_widgets_collection(obj)
            if widgets_collection is not None:
                for wgt_obj in list(widgets_collection.objects):
                    mesh = wgt_obj.data
                    bpy.data.objects.remove(wgt_obj, do_unlink=True)
                    if mesh is not None and mesh.users == 0:
                        bpy.data.meshes.remove(mesh, do_unlink=True)
                    purged += 1
                if not widgets_collection.objects:
                    _unlink_and_remove_collection(widgets_collection)
                    if obj.get("hytale_widgets_collection"):
                        del obj["hytale_widgets_collection"]

        # Texture Picker e First Person Camera não são feitos só de
        # bone PROP_RIG_LAYER (plane/nodes de material, objeto Camera)
        # -- limpos à parte, reaproveitando os mesmos botões dedicados.
        # Sempre roda, nos dois modos, ANTES da limpeza de hytale_ik_chains.
        texture_picker_cleaned = 0
        for item in obj.data.hytale_ik_chains:
            if item.chain_type == "TEXTURE_PICKER" and item.texture_picker_bone:
                if _remove_texture_picker(obj, item):
                    texture_picker_cleaned += 1

        camera_cleaned = _remove_first_person_camera(obj)

        # Só em DELETE_ALL: limpa Bone Settings e Collection Settings
        # por completo, resetando os flags de "já inicializado".
        chains_cleared = 0
        collections_cleared = 0
        if self.mode == "DELETE_ALL":
            chains_cleared = len(obj.data.hytale_ik_chains)
            obj.data.hytale_ik_chains.clear()
            collections_cleared = len(obj.data.hytale_bone_collections)
            obj.data.hytale_bone_collections.clear()
            obj.data.hytale_bone_collections_initialized = False

        self.report(
            {"INFO"},
            f"Removed {removed} generated bone(s) and {removed_collections} bone collection(s) under Main"
            + (f"; purged {purged} cached widget object(s)" if self.mode == "DELETE_ALL" else "")
            + (f"; cleaned {texture_picker_cleaned} Texture Picker setup(s)" if texture_picker_cleaned else "")
            + ("; removed First Person Camera" if camera_cleaned else "")
            + (f"; removed {org_constraints_removed} rig constraint(s) from the original bones" if org_constraints_removed else "")
            + (
                f"; cleared {chains_cleared} Bone Settings entrie(s) and {collections_cleared} Collection "
                f"Settings entrie(s)"
                if self.mode == "DELETE_ALL"
                else ""
            )
            + ".",
        )
        return {"FINISHED"}


class RIG_MT_hytale_clear_generated_menu(Menu):
    """Menu popup do ícone de lixeira ao lado de "Create Rig" --
    pergunta qual modo usar antes de apagar."""

    bl_idname = "RIG_MT_hytale_clear_generated_menu"
    bl_label = "Remove Generated Bones"
    description = tooltip("rigger.tooltip.clear_generated_menu")

    def draw(self, context):
        layout = self.layout
        layout.operator(
            RIG_OT_hytale_clear_generated.bl_idname, text="Only Rig", icon="ARMATURE_DATA"
        ).mode = "ONLY_RIG"
        layout.operator(
            RIG_OT_hytale_clear_generated.bl_idname, text="Delete All", icon="TRASH"
        ).mode = "DELETE_ALL"
