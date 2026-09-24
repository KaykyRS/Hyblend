"""Auto-Rigger -- RIG_OT_hytale_generate_rig, o operador principal ("Create Rig")."""

import math
import os

import bpy
from bpy.types import Operator
from mathutils import Matrix, Vector

from ..common import BONE_RIGGER_CREATED_PROP, is_active_armature
from ..templates import (
    get_rig_template,
    get_shape_template,
)
from ..translations import get_language, tooltip, tr

from .constants import (
    ATTACHMENT_SHAPE_SCALE,
    BODY_COLLECTION_BONES,
    BONE_COLOR_ATTACHMENT,
    BONE_COLOR_FIXED,
    BONE_COLOR_LEFT,
    BONE_COLOR_NAME_FALLBACK,
    BONE_COLOR_RIGHT,
    BONE_COLOR_ROOT_HEAD,
    BONE_COLOR_SPINE,
    BONE_PROPERTIES,
    BONE_ROOT_MASTER,
    BONE_ROOT_PELVIS,
    BONE_ROOT_SPINE,
    COLL_ATTACHMENTS,
    COLL_ATTACHMENTS_IMPORTED,
    COLL_CTRL,
    COLL_CTRL_IK,
    COLL_HYTALE_EXPORT,
    COLL_INTERNAL,
    COLL_MAIN,
    COLL_MAIN_ARM_L,
    COLL_MAIN_ARM_R,
    COLL_MAIN_BODY,
    COLL_MAIN_CHAIN,
    COLL_MAIN_HEAD,
    COLL_MAIN_LEG_L,
    COLL_MAIN_LEG_R,
    COLL_MAIN_ROOT,
    COLL_MAIN_SPINE,
    COLL_MAIN_TEXTURE_PICKER,
    COLL_MCH,
    COLL_MCH_IK,
    COLL_ORG,
    CONSTRAINT_CHILD_OF_GLOBAL,
    CONSTRAINT_CHILD_OF_LOCAL,
    CONSTRAINT_FK_LOC,
    CONSTRAINT_FK_ROT,
    CONSTRAINT_FK_SCALE,
    CONSTRAINT_HEAD_FOLLOW_LOC,
    CONSTRAINT_HEAD_FOLLOW_ROT,
    CONSTRAINT_IK_LOC,
    CONSTRAINT_IK_ROT,
    CONSTRAINT_IK_SCALE,
    CONSTRAINT_ORG_TO_MCH,
    CONSTRAINT_POLE_LINE_STRETCH,
    CONSTRAINT_SPINE_FOLLOW,
    CTRL_PARENT_OVERRIDES,
    HEAD_FOLLOW_LOC_HEAD_TAIL,
    ORIGIN_FALLBACK_LENGTH,
    ORIGIN_ORG_NAME,
    ROOT_CREATED_LENGTH_STEP,
    PROPERTIES_BONE_OFFSET_Y,
    PROP_HEAD_FOLLOW_SWITCH,
    PROP_RIG_LAYER,
    PROP_SOURCE_ORG,
    ROOT_COLLECTION_BONES,
    ROOT_MASTER_PARENT,
    ROOT_SPINE_LENGTH,
    SPINE_COLLECTION_BONES,
    SPINE_FOLLOW_INFLUENCES,
    SPINE_FOLLOW_TARGET,
    SUFFIX_CTRL,
    SUFFIX_IK,
    SUFFIX_MCH,
    SUFFIX_MCH_IK_TRANSFER,
    SUFFIX_MCH_TRANSFER,
    SUFFIX_POLE,
    SUFFIX_POLE_LINE,
    WGT_DEFAULT_FALLBACK,
    WIDGET_WIRE_WIDTH,
)

from .rename import normalize_bone_fields
from .helpers import control_name, normalize_org_name, source_org_of, _find_bone_collection_anywhere, _resolve_main_limb_roots, _resolve_parent_override, bone_side_prefix, collect_descendants_inclusive, create_bone_like, ensure_bone_collection, find_attachment_child, find_layer_bone, find_non_attachment_children, find_org_path, is_attachment_bone, parent_override_candidates, parent_would_loop, resolve_origin_ctrl_name, resolve_root_org_names, resolve_root_slots, resolve_master_source_org_name, resolve_pelvis_org_name, resolve_spine_segment_org_names, is_excluded_from_main_collections, resolve_head_chain_item, resolve_head_ctrl_name, rotate_edit_bone_local_axis, set_bone_collection_visibility
from .constraints import add_custom_shape_scale_switch_driver, add_switch_driver, compute_pole_angle, compute_pole_angle_edit, ensure_child_of_constraint, ensure_copy_constraint, ensure_copy_set, ensure_ik_constraint, ensure_stretch_to_constraint, ensure_switch_property, switch_property_name
from .widgets import _ensure_bone_widget_copy, _widget_candidates_for_bone, _widgets_library_path, compute_widget_transform_correction, ensure_widget_objects, get_or_create_widgets_collection, list_widget_library_names
from .bone_collections import COLLECTION_OVERRIDE_AUTO, _head_spine_bone_names, _spine_ctrl_override_transform_bone_name, ensure_default_bone_collection_entries, ensure_default_bone_collections, ensure_default_bone_section_backfill, ensure_texture_picker_collection_entry, resolve_collection_override_target, sync_bone_collection_order
from .bone_settings import find_shared_pole_angle_preset_warnings, resolve_pole_angle_preset_degrees
from .texture_picker import _texture_picker_cursor_name, _texture_picker_ui_root_name


_RIGGER_ROLE_PALETTES = (
    BONE_COLOR_LEFT, BONE_COLOR_RIGHT, BONE_COLOR_ROOT_HEAD, BONE_COLOR_SPINE, BONE_COLOR_ATTACHMENT,
)


def _is_rigger_palette(normal_color):
    """True se `normal_color` é a cor "normal" de uma das palettes de
    papel que _build_bone_colors aplica (tolerância de float)."""
    return any(
        all(abs(a - b) < 1e-3 for a, b in zip(normal_color, palette[0]))
        for palette in _RIGGER_ROLE_PALETTES
    )


class RIG_OT_hytale_generate_rig(Operator):
    """Cria/atualiza as camadas ORG/MCH/CTRL/CTRL-IK/MCH-IK, os bones
    utilitários de controle geral e as collections Main/Face/Attachments
    do Armature ativo, lendo as cadeias de IK definidas em
    armature.hytale_ik_chains. Seguro pra rodar de novo depois de
    adicionar attachments novos: só cria o que ainda não existe."""

    bl_idname = "armature.hytale_generate_rig"
    bl_label = "Create Rig"
    description = tooltip("rigger.tooltip.generate_rig")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        if getattr(obj.data, "hytale_shape_edit_mode", False):
            cls.poll_message_set(
                "Finish Shape Edit Mode first -- rebuilding the rig now would discard the sizes you're editing.",
            )
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        armature = obj.data

        # v0.9 -- Collection Settings (Etapa 1). Garante que a lista
        # exista mesmo se o usuário nunca abriu a box "Collection
        # Settings" antes (draw() não pode escrever em dados de ID --
        # ver interface.py; aqui, dentro de execute(), é seguro).
        ensure_default_bone_collections(armature)
        ensure_texture_picker_collection_entry(armature)  # v0.10.5 -- backfill p/ armatures já
        # inicializados antes do Texture Picker existir na grade default, ver docstring da função
        ensure_default_bone_section_backfill(armature)  # v0.7.8 -- mesmo padrão, backfill da Section "Main"
        # Campo do Bone Settings apontando pra um bone GERADO (ex. o
        # "..._CTRL" que o conta-gotas pega no Pose Mode) -- vira o ORG de
        # onde ele nasceu. Sem isso a cadeia inteira era pulada (não há
        # caminho ORG até um bone de controle).
        normalized_fields = normalize_bone_fields(armature)
        if normalized_fields:
            self.report(
                {"WARNING"},
                f"{normalized_fields} Bone Settings field(s) pointed at generated control bones (e.g. '_CTRL') "
                f"-- switched to the original bones.",
            )
        ensure_default_bone_collection_entries(armature)  # v0.7.9 -- idem, pros outros 10 defaults

        # "Pra baixo" (usado no fallback do Foot_IK) precisa ser
        # convertido do espaço mundo pro espaço local do Armature -- as
        # coordenadas dos edit bones NÃO são world space.
        world_down_local = obj.matrix_world.inverted().to_3x3() @ Vector((0.0, 0.0, -1.0))

        prev_mode = obj.mode
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            stats, chains_data, tail_chains_data = self._build_edit_bones(armature, world_down_local)
            joint_fix_count = 0
            if getattr(armature, "hytale_apply_ik_joint_fix", False):
                joint_fix_count = self._apply_ik_joint_fixes(obj, chains_data)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

        self._build_pose_constraints(obj, chains_data)
        tail_constraint_count = self._build_tail_pose_constraints(obj, tail_chains_data)
        # v0.13.12 -- respeita o mesmo "Create root.spine_CTRL" (ver
        # _build_root_controls/HytaleIKChainItem.spine_ctrl_enabled) --
        # sem root.spine_CTRL não tem pra onde apontar o Spine Follow,
        # então nem tenta (evita o WARNING de "bone não encontrado" toda
        # vez que rodar de propósito com a opção desligada).
        if stats["spine_ctrl_enabled"]:
            self._build_spine_follow(obj)
        head_follow_built = self._build_head_follow(obj, stats["head_follow_active"], stats["head_follow_source"])
        self._apply_pole_childof_inverses(obj, chains_data, head_follow_built)
        widget_stats = self._build_custom_shapes(obj, chains_data)
        shape_switch_count = self._build_ik_fk_shape_visibility(obj, chains_data)
        colored_count = self._build_bone_colors(obj, chains_data, tail_chains_data)

        if prev_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=prev_mode)

        self.report(
            {"INFO"},
            f"Rig ready: {stats['mch']} MCH, {stats['ctrl']} CTRL, {stats['ik']} CTRL-IK, "
            f"{stats['ik_mch']} MCH-IK, {stats['mch_transfer']} MCH-Transfer, {stats['root']} root control "
            f"bone(s) created; "
            f"{len(chains_data)} IK chain(s) and {len(tail_chains_data)} tail chain(s) processed "
            f"({tail_constraint_count} tail bridge bone(s) constrained); "
            f"{widget_stats['assigned']} custom shape(s) assigned"
            + (f" ({widget_stats['fallback']} via fallback)" if widget_stats["fallback"] else "")
            + (f", {widget_stats['missing']} widget(s) missing (see warnings))" if widget_stats["missing"] else "")
            + f"; {shape_switch_count} FK/IK shape-scale driver(s) set; "
            + f"{colored_count} bone(s) colored"
            + (f"; {stats['continuous_chain']} continuous-chain bone(s) redirected" if stats["continuous_chain"] else "")
            + (
                f"; Head Follow active (following '{stats['head_follow_source']}')" if stats["head_follow_active"]
                else "; Head Follow inactive (Tail/Head not aligned -- see Continuous Chain)"
            )
            + (f"; {joint_fix_count} IK joint fix(es) applied (rig template)." if joint_fix_count else "."),
        )
        return {"FINISHED"}

    def _apply_ik_joint_fixes(self, obj, chains_data):
        """Corrige a posição X de juntas específicas da cadeia IK (ver
        rig_template["ik_joint_x_overrides"]), só o eixo X. Cada rig
        template define os próprios valores calibrados. Só roda se
        armature.hytale_apply_ik_joint_fix estiver ligado. Precisa
        rodar em Edit Mode.

        Pra cada bone_name: seta o HEAD dele pro novo X, e acha o bone
        anterior na mesma cadeia pra também setar o TAIL (compartilham
        a mesma junta visualmente).

        Compensação de pole angle: mover o head do bone raiz da cadeia
        rotaciona o eixo X local, referencial que pole_angle_presets
        foi calibrado em cima -- mede o pole_angle antes/depois e
        guarda a diferença em pole_angle_joint_fix_delta;
        _build_pose_constraints soma esse delta no valor calibrado.

        Compensação de custom shape: mesmo princípio pra Translation/
        Rotation/Scale do widget (ver compute_widget_transform_correction),
        guardado em self._player_widget_transform_corrections."""
        armature = obj.data
        edit_bones = armature.edit_bones
        applied = 0
        self._player_widget_transform_corrections = {}

        rig_template = get_rig_template(getattr(armature, "hytale_active_rig_template", "")) or {}
        ik_joint_x_overrides = rig_template.get("ik_joint_x_overrides", {})
        widget_translation_x_overrides = rig_template.get("widget_translation_x_overrides", {})
        shape_template = get_shape_template(getattr(armature, "hytale_active_shape_template", "")) or {}
        shape_bones = shape_template.get("bones", {})

        def _snapshot(edit_bone):
            return (edit_bone.x_axis.copy(), edit_bone.y_axis.copy(), edit_bone.z_axis.copy()), edit_bone.length

        def _store_widget_correction(bone_name, old_snapshot, new_snapshot):
            override = shape_bones.get(bone_name)
            if not override or "translation" not in override or "rotation_deg" not in override or "scale" not in override:
                return  # sem os 3 valores calibrados, não tem o que corrigir
            (old_axes, old_length), (new_axes, new_length) = old_snapshot, new_snapshot
            old_rotation = tuple(math.radians(v) for v in override["rotation_deg"])
            translation, rotation, scale = compute_widget_transform_correction(
                old_axes, old_length, new_axes, new_length,
                tuple(override["translation"]), old_rotation, tuple(override["scale"]),
            )
            # Ajuste fino pontual -- só troca o X, Y/Z ficam calculados.
            fixed_x = widget_translation_x_overrides.get(bone_name)
            if fixed_x is not None:
                translation = (fixed_x, translation[1], translation[2])
            self._player_widget_transform_corrections[bone_name] = (translation, rotation, scale)

        for bone_name, new_x in ik_joint_x_overrides.items():
            bone = edit_bones.get(bone_name)
            if bone is None:
                self.report({"WARNING"}, f"'{bone_name}' not found -- skipping IK joint fix.")
                continue

            # Acha a cadeia inteira antes de mover, pra medir o
            # pole_angle "antes" com a geometria original.
            base_name = source_org_of(bone) if bone_name.endswith(SUFFIX_IK) else bone_name
            chain_data = None
            for data in chains_data:
                if base_name in data["org_names"]:
                    chain_data = data
                    break

            ik_root_bone = edit_bones.get(chain_data["ik_root"]) if chain_data else None
            pole_bone = edit_bones.get(chain_data["pole"]) if chain_data else None
            angle_before = (
                compute_pole_angle_edit(obj, ik_root_bone, pole_bone)
                if ik_root_bone is not None and pole_bone is not None
                else None
            )

            bone_snapshot_before = _snapshot(bone)
            prev_bone = None
            prev_snapshot_before = None
            if chain_data is not None:
                org_names = chain_data["org_names"]
                idx = org_names.index(base_name)
                if idx > 0:
                    prev_bone = edit_bones.get(control_name(armature, org_names[idx - 1], SUFFIX_IK))
                    if prev_bone is not None:
                        prev_snapshot_before = _snapshot(prev_bone)

            head = bone.head.copy()
            head.x = new_x
            bone.head = head
            applied += 1
            _store_widget_correction(bone_name, bone_snapshot_before, _snapshot(bone))

            if prev_bone is not None:
                tail = prev_bone.tail.copy()
                tail.x = new_x
                prev_bone.tail = tail
                applied += 1
                _store_widget_correction(prev_bone.name, prev_snapshot_before, _snapshot(prev_bone))

            if angle_before is not None:
                angle_after = compute_pole_angle_edit(obj, ik_root_bone, pole_bone)
                delta = angle_before - angle_after  # sinal invertido -- ver docstring
                chain_data["pole_angle_joint_fix_delta"] = (
                    chain_data.get("pole_angle_joint_fix_delta", 0.0) + delta
                )

        return applied

    def _build_custom_shapes(self, obj, chains_data):
        """Atribui pose_bone.custom_shape pros bones CTRL/CTRL-IK/
        ROOT-CTRL, usando as meshes de hytale_widgets.blend. Roda por
        último -- só depois que todos os bones já existem.

        Resolução em duas passadas: tenta o template preferido de cada
        bone (por papel); o que não existir cai pro WGT_DEFAULT_FALLBACK.
        Essas duas passadas só garantem que o TEMPLATE do papel existe
        (ensure_widget_objects); a atribuição final usa
        _ensure_bone_widget_copy, que duplica numa cópia única pra
        cada bone (nunca compartilhada).

        100% cosmético: se a biblioteca não existir, avisa e segue --
        os bones ficam com o octaedro padrão, o resto do rig funciona
        normalmente.

        Carrega o Shape Template ativo uma vez, guarda em
        self._shape_template_bones pra _apply_widget_transform_override reaproveitar."""
        armature = obj.data
        shape_template = get_shape_template(getattr(armature, "hytale_active_shape_template", "")) or {}
        self._shape_template_bones = shape_template.get("bones", {})

        pose_bones = obj.pose.bones
        ik_tip_names = {data["ik_tip"] for data in chains_data}
        head_ctrl_name = resolve_head_ctrl_name(armature)
        # Todo root (Origin principal + roots extras) usa o widget do
        # Origin -- os criados pelo rigger têm comprimento crescente por
        # slot, então os widgets ficam concêntricos.
        root_ctrl_names = {control_name(armature, name, SUFFIX_CTRL) for name in resolve_root_org_names(armature)}

        wanted = {}
        for pb in pose_bones:
            # layer pode vir None só se um bone entrar em
            # WIDGET_NAME_OVERRIDES sem nunca ter sido gerado por aqui
            # -- _widget_candidates_for_bone já lida com isso.
            layer = pb.bone.get(PROP_RIG_LAYER)
            candidates = _widget_candidates_for_bone(
                pb.name, layer, ik_tip_names, self._shape_template_bones, head_ctrl_name, root_ctrl_names
            )
            if candidates:
                wanted[pb.name] = candidates

        # Materializa/apenda de hytale_widgets.blend todo nome candidato
        # que apareça em qualquer cadeia, numa passada só. Nomes
        # por-bone/por-personagem (override de shape_template) nunca
        # batem com a biblioteca (que só entende nome de papel) --
        # isso é esperado: a resolução de verdade pra esses é o check
        # por-bone em _ensure_bone_widget_copy.
        all_candidate_names = {name for candidates in wanted.values() for name in candidates}
        ensure_widget_objects(all_candidate_names, obj)

        widgets_collection = get_or_create_widgets_collection(obj)
        assigned = 0
        used_fallback = 0
        left_default = []
        for bone_name, candidates in wanted.items():
            pb = pose_bones[bone_name]
            # Tenta cada candidato em ordem (mais específico primeiro) --
            # um override apagado ("Delete All") não deve pular direto
            # pro cubo genérico se o shape genérico do papel ainda
            # existir na biblioteca.
            #
            # O candidato de índice 0 só existe quando veio de
            # shape_overrides -- então a chave "mesh" desse bone, se
            # existir, só pode se referir a esse candidato (nunca ao
            # fallback genérico).
            bone_mesh_override = self._shape_template_bones.get(bone_name, {}).get("mesh")
            new_shape_obj = None
            resolved_name = None
            for index, candidate in enumerate(candidates):
                embedded_mesh = bone_mesh_override if index == 0 else None
                new_shape_obj = _ensure_bone_widget_copy(
                    candidate, obj, bone_name, widgets_collection, embedded_mesh=embedded_mesh,
                )
                if new_shape_obj is not None:
                    resolved_name = candidate
                    break
            if new_shape_obj is None:
                left_default.append(bone_name)
                continue
            if resolved_name == WGT_DEFAULT_FALLBACK:
                used_fallback += 1
            # Só reseta Translation/Rotation/Scale na PRIMEIRA vez que
            # este shape é atribuído a este bone -- reruns não apagam
            # ajustes já feitos.
            is_first_assignment = pb.custom_shape != new_shape_obj
            pb.custom_shape = new_shape_obj
            pb.use_custom_shape_bone_size = True
            pb.custom_shape_wire_width = WIDGET_WIRE_WIDTH
            if is_first_assignment:
                pb.custom_shape_scale_xyz = (1.0, 1.0, 1.0)
                pb.custom_shape_translation = (0.0, 0.0, 0.0)
                pb.custom_shape_rotation_euler = (0.0, 0.0, 0.0)
            self._apply_widget_transform_override(pb, bone_name)
            assigned += 1

        if left_default:
            # Diz se o problema é "arquivo .blend não encontrado" ou
            # "arquivo encontrado, mas nem o fallback existe dentro dele".
            lib_path = _widgets_library_path()
            if os.path.isfile(lib_path):
                available = list_widget_library_names()
                available_hint = ", ".join(sorted(available)) if available else "(none readable)"
                path_hint = (
                    f"library found at '{lib_path}', but not even '{WGT_DEFAULT_FALLBACK}' exists inside it "
                    f"-- library actually contains: {available_hint}"
                )
            else:
                path_hint = f"library file not found at '{lib_path}'"
            self.report(
                {"WARNING"},
                f"No widget shape could be resolved at all ({path_hint}) for {len(left_default)} bone(s): "
                f"{', '.join(sorted(left_default))} -- affected bone(s) left with Blender's default shape.",
            )
        elif used_fallback:
            self.report(
                {"INFO"},
                f"{used_fallback} bone(s) fell back to '{WGT_DEFAULT_FALLBACK}' -- their preferred shape "
                f"(character-specific override and/or the generic shape for their role) wasn't found. Check "
                f"the active Shape Template (Character Templates) and hytale_widgets.blend.",
            )

        # O custom shape de root.spine_CTRL usa Override Transform
        # apontando pro _CTRL do último bone configurado em SPINE --
        # continua desenhado na posição/tamanho do próprio
        # root.spine_CTRL, só a orientação segue o do último bone do
        # Spine. Roda depois do loop acima (precisa do custom_shape já
        # atribuído). None limpa o Override Transform.
        spine_ctrl_pose = pose_bones.get(BONE_ROOT_SPINE)
        if spine_ctrl_pose is not None:
            override_bone_name = _spine_ctrl_override_transform_bone_name(armature)
            spine_ctrl_pose.custom_shape_transform = (
                pose_bones.get(override_bone_name) if override_bone_name else None
            )

        return {
            "assigned": assigned,
            "fallback": used_fallback,
            "missing": len(left_default),
        }

    def _apply_widget_transform_override(self, pose_bone, bone_name):
        """Aplica o bone atual do Shape Template ativo, só nos campos
        (translation/rotation_deg/scale) presentes no .json -- campos
        omitidos ficam como já estavam. Roda toda vez que o rig é
        gerado: o template sempre "vence" em cada rerun.

        Exceção: se este bone tiver uma correção de _apply_ik_joint_fixes
        (self._player_widget_transform_corrections), ela vence os
        valores estáticos -- é a versão já compensada pra geometria nova.

        Bones com driver de FK/IK têm "scale" tratado como o tamanho
        cheio -- o driver assume custom_shape_scale_xyz depois.

        Attachments sem override de "scale" caem no
        ATTACHMENT_SHAPE_SCALE genérico -- um nome exato no template
        sempre vence essa regra genérica."""
        corrections = getattr(self, "_player_widget_transform_corrections", {})
        correction = corrections.get(bone_name)
        if correction is not None:
            translation, rotation, scale = correction
            pose_bone.custom_shape_translation = translation
            pose_bone.custom_shape_rotation_euler = rotation
            pose_bone.custom_shape_scale_xyz = scale
            return

        shape_bones = getattr(self, "_shape_template_bones", {})
        override = shape_bones.get(bone_name, {})
        if "translation" in override:
            pose_bone.custom_shape_translation = tuple(override["translation"])
        if "rotation_deg" in override:
            pose_bone.custom_shape_rotation_euler = tuple(math.radians(v) for v in override["rotation_deg"])
        if "scale" in override:
            pose_bone.custom_shape_scale_xyz = tuple(override["scale"])
        elif is_attachment_bone(pose_bone):
            pose_bone.custom_shape_scale_xyz = (ATTACHMENT_SHAPE_SCALE,) * 3

    def _build_ik_fk_shape_visibility(self, obj, chains_data):
        """Liga o Scale do custom shape de todos os bones _CTRL (FK) e
        _IK (IK) de cada segmento à custom property de FK/IK switch
        dessa cadeia (no bone PROPERTIES) -- quando um lado está ativo,
        o outro encolhe pra 0. Cobre a cadeia inteira. Pole_CTRL/
        Pole_Line também, mesmo driver que um bone "IK" normal (só
        fazem sentido existir em modo IK).

        O tamanho "cheio" vem do Shape Template ativo (chave "scale");
        default (1,1,1). Roda depois de _build_custom_shapes -- precisa
        do valor base já atribuído antes do driver assumir o controle.
        Bones corrigidos por _apply_ik_joint_fixes usam o scale já
        compensado, senão o driver reintroduziria o tamanho antigo."""
        pose_bones = obj.pose.bones
        corrections = getattr(self, "_player_widget_transform_corrections", {})
        shape_bones = getattr(self, "_shape_template_bones", {})

        def _scale_target(bone_name):
            correction = corrections.get(bone_name)
            if correction is not None:
                return correction[2]  # (translation, rotation, scale)
            scale = shape_bones.get(bone_name, {}).get("scale")
            return tuple(scale) if scale is not None else (1.0, 1.0, 1.0)

        applied = 0
        for data in chains_data:
            switch_prop = data["switch_property"]
            for org_name in data["org_names"]:
                fk_name = control_name(obj.data, org_name, SUFFIX_CTRL)
                ik_name = control_name(obj.data, org_name, SUFFIX_IK)

                fk_pb = pose_bones.get(fk_name)
                if fk_pb is not None:
                    target = _scale_target(fk_name)
                    add_custom_shape_scale_switch_driver(fk_pb, obj, BONE_PROPERTIES, switch_prop, target, mode="FK")
                    applied += 1

                ik_pb = pose_bones.get(ik_name)
                if ik_pb is not None:
                    target = _scale_target(ik_name)
                    add_custom_shape_scale_switch_driver(ik_pb, obj, BONE_PROPERTIES, switch_prop, target, mode="IK")
                    applied += 1

            # Pole_CTRL/Pole_Line nunca entram em org_names (não são
            # ORG/CTRL/IK de nenhum segmento) -- mesmo tratamento dos
            # bones IK acima: somem em FK, aparecem no tamanho cheio em IK.
            for key in ("pole", "pole_line"):
                name = data.get(key)
                pb = pose_bones.get(name) if name else None
                if pb is not None:
                    target = _scale_target(name)
                    add_custom_shape_scale_switch_driver(pb, obj, BONE_PROPERTIES, switch_prop, target, mode="IK")
                    applied += 1
        return applied

    def _bone_settings_color_map(self, armature_data, chains_data, tail_chains_data):
        """{nome do ORG: palette} a partir do que está MARCADO no Bone
        Settings -- independe do nome do bone (um braço "bone.002" marcado
        como Arm/Left fica vermelho igual a um "L-Arm").

        Três forças de atribuição, da mais forte pra mais fraca:
          - direta: o bone está num campo do Bone Settings (caminho
            Root->Tip de Arm/Leg com lado, Head, Neck 1..N, Pelvis/Spine
            1..N, cadeia Chain, Attachments, Root). Se o mesmo bone
            aparecer em duas entradas, vale a primeira nesta ordem: Root,
            Head, Attachments, Arm/Leg, Neck, Spine, Chain;
          - herdada: filhos de um bone de Arm/Leg (dedos, peças da mão
            etc.) recebem a cor do pai, descendo até achar um bone com
            atribuição direta própria. Attachments (nome com
            "attachment") nunca herdam -- continuam cinza;
          - Root Parent de Arm/Leg (ex. ombro): recebe a cor do lado da
            cadeia, a menos que o bone já tenha cor pelos casos acima ou
            seja Root Parent de cadeias de lados DIFERENTES (ex. um
            Pelvis compartilhado pelas duas pernas -- aí não pinta).

        Head/Spine/Chain NÃO passam cor pros filhos: o filho da Spine é
        o braço, o da cabeça são olhos/mandíbula -- esses seguem a
        própria entrada ou o fallback por nome."""
        side_palette = {"LEFT": BONE_COLOR_LEFT, "RIGHT": BONE_COLOR_RIGHT}
        items = list(getattr(armature_data, "hytale_ik_chains", []))
        direct = {}

        def claim(name, palette):
            if name and name not in direct:
                direct[name] = palette

        # Root (Origin + roots extras) -- amarelo, igual ao Origin_CTRL.
        for name in resolve_root_org_names(armature_data) if resolve_root_slots(armature_data) else ():
            claim(name, BONE_COLOR_ROOT_HEAD)
        # Head (todas as entradas HEAD -- criatura de várias cabeças).
        for item in items:
            if item.chain_type == "HEAD":
                claim(item.head_bone, BONE_COLOR_ROOT_HEAD)
        # Attachments.
        for item in items:
            if item.chain_type == "ATTACHMENTS":
                for name in _head_spine_bone_names(item):
                    claim(name, BONE_COLOR_ATTACHMENT)
        # Arm/Leg -- o caminho REAL que o gerador montou (chains_data),
        # não só root/tip: inclui todo bone do meio (antebraço etc.).
        limb_chains = []
        for data in chains_data:
            palette = side_palette.get(data.get("side"))
            if palette is None:
                continue  # lado "Center" -- sem cor de lado, cai no fallback
            for name in data.get("org_names", ()):
                claim(name, palette)
            limb_chains.append((data, palette))
        # Neck (1..neck_count de cada entrada HEAD).
        for item in items:
            if item.chain_type == "HEAD":
                neck_slots = [getattr(item, f"neck_bone_{i}", "") for i in range(1, 6)]
                for name in neck_slots[: item.neck_count]:
                    claim(name, BONE_COLOR_SPINE)
        # Spine (Pelvis + Spine 1..N).
        for item in items:
            if item.chain_type == "SPINE":
                for name in _head_spine_bone_names(item):
                    claim(name, BONE_COLOR_SPINE)
        # Chain -- o caminho inteiro montado pelo gerador.
        for data in tail_chains_data or ():
            for name in data.get("org_names", ()):
                claim(name, BONE_COLOR_SPINE)

        # Herança: descendentes ORG dos bones de Arm/Leg.
        inherited = {}
        bones = armature_data.bones
        for data, palette in limb_chains:
            stack = []
            for name in data.get("org_names", ()):
                bone = bones.get(name)
                if bone is not None:
                    stack.extend(bone.children)
            while stack:
                child = stack.pop()
                if child.get(PROP_RIG_LAYER) is not None:
                    continue  # bone gerado -- só anda pela árvore ORG
                if is_attachment_bone(child):
                    continue  # attachment fica cinza (fallback), e não repassa cor
                if child.name in direct:
                    continue  # tem papel próprio -- ele (e o que estiver abaixo) segue a entrada dele
                inherited.setdefault(child.name, palette)
                stack.extend(child.children)

        # Root Parent de Arm/Leg (ombro).
        root_parent_claims = {}
        for data, palette in limb_chains:
            name = (data.get("parent_override") or "").strip()
            if name.endswith(SUFFIX_CTRL):
                name = name[: -len(SUFFIX_CTRL)]
            # Root Parent pode vir como apelido de controle ("L-Shoulder"
            # de um ORG "torso") -- a cor é gravada pelo nome do ORG.
            name = normalize_org_name(armature_data.bones, name) if name else name
            candidates = parent_override_candidates(armature_data, name)
            if not name or not candidates or candidates[0] == BONE_ROOT_PELVIS:
                continue  # o Pelvis (-> root.pelvis_CTRL) não é bone do membro
            root_parent_claims.setdefault(name, set()).add(palette)

        result = dict(inherited)
        for name, palettes in root_parent_claims.items():
            if len(palettes) == 1 and name not in result:
                result[name] = next(iter(palettes))
        result.update(direct)
        return result

    def _build_bone_colors(self, obj, chains_data=(), tail_chains_data=None):
        """Pinta bone.color (Custom Color Set) por bone -- não tem nada a
        ver com custom shape, é a cor de exibição do bone em si (Bone
        Properties > Viewport Display > Color, ou o painel de Bone Color
        na sidebar). Aplicado ao Bone (obj.data.bones), não ao PoseBone --
        assim vale em Edit Mode e Pose Mode igual, sem precisar de duas
        atribuições.

        Ordem de decisão (a primeira que responder vence):
          1. BONE_COLOR_FIXED -- bones utilitários do rigger (root.*,
             Origin_CTRL, PROPERTIES);
          2. Bone Settings -- o ORG de onde o bone gerado nasceu (tira o
             sufixo _CTRL/_IK/_MCH/_Pole_CTRL...) está marcado em alguma
             entrada (ver _bone_settings_color_map). O NOME não importa
             aqui: "R-Arm" marcado como Arm/Left fica vermelho;
          3. fallback por nome, só pra quem não está no Bone Settings:
             BONE_COLOR_NAME_FALLBACK (Head_CTRL, Pelvis/Belly/Chest/
             Neck_CTRL) -> "attachment" no nome (cinza) -> token de lado
             no nome, prefixo OU sufixo (L-/R-, _left/_right, .L/.R...).
        Bone que não se encaixa em nada fica com a cor padrão do Blender.

        Bones ORG (sem PROP_RIG_LAYER -- os nomes originais do modelo
        importado) NUNCA recebem cor: ficam ocultos (collection ORG).
        Bones de UI do Texture Picker ("UI-CTRL") também ficam de fora --
        _build_texture_picker já pinta os dois com a cor dedicada deles."""
        role_palettes = self._bone_settings_color_map(obj.data, chains_data or (), tail_chains_data)
        colored = 0
        for bone in obj.data.bones:
            layer = bone.get(PROP_RIG_LAYER)
            if layer is None:
                # ORG nunca tem cor -- e se ficou colorido numa execução
                # ANTIGA (antes desta regra existir), reseta pro padrão do
                # Blender em vez de só pular (senão a cor errada nunca sai).
                if bone.color.palette == "CUSTOM":
                    bone.color.palette = "DEFAULT"
                continue
            if layer == "UI-CTRL":
                continue

            palette = BONE_COLOR_FIXED.get(bone.name)
            if palette is None:
                org_name = source_org_of(bone)
                if org_name is not None:
                    palette = role_palettes.get(org_name)
            if palette is None:
                palette = BONE_COLOR_NAME_FALLBACK.get(bone.name)
            if palette is None and is_attachment_bone(bone):
                # Attachment vence o lado no nome -- um bone tipo
                # "L-Eyebrow-Attachment_CTRL" começa com "L-", mas deve
                # ficar cinza (BONE_COLOR_ATTACHMENT), não vermelho.
                palette = BONE_COLOR_ATTACHMENT
            if palette is None:
                side = bone_side_prefix(bone.name)
                if side == "L":
                    palette = BONE_COLOR_LEFT
                elif side == "R":
                    palette = BONE_COLOR_RIGHT
            if palette is None:
                # Bone que perdeu o papel desde a última geração (ex.
                # saiu do Bone Settings) -- tira a cor ANTIGA do rigger,
                # mas só se ela for mesmo uma das cores do rigger (cor
                # pintada à mão pelo usuário não é tocada).
                if bone.color.palette == "CUSTOM" and _is_rigger_palette(bone.color.custom.normal):
                    bone.color.palette = "DEFAULT"
                continue
            normal, select, active = palette
            bone.color.palette = "CUSTOM"
            bone.color.custom.normal = normal
            bone.color.custom.select = select
            bone.color.custom.active = active
            colored += 1
        return colored

    def _apply_pole_childof_inverses(self, obj, chains_data, head_follow_built=False):
        """Roda o equivalente ao botão "Set Inverse" nos Child Of que
        dependem de posição -- os dois do pole (local e global), o
        Child Of_global novo do ik_tip (Hand_IK/Foot_IK), e (v0.13) o
        CONSTRAINT_HEAD_FOLLOW_ROT do Head_CTRL, se `head_follow_built`
        -- senão eles "pulam" de lugar assim que a influência for
        ligada (mesmo com influência 0, o Set Inverse precisa rodar
        logo na criação, já com a pose correta, ou o resultado fica
        errado quando alguém subir a influência depois). Usa o operator
        real do Blender (via context override) em vez de matriz manual.

        CONSTRAINT_HEAD_FOLLOW_LOC (Copy Location) NÃO entra aqui --
        Set Inverse só existe pro tipo Child Of; Copy Location não
        "pula" (é uma cópia contínua, sempre recalculada, sem estado
        próprio pra ficar desalinhado).

        v0.13.9 -- FIX (bug relatado pelo usuário): "Set Inverse" captura
        a diferença entre a matriz MUNDIAL atual do bone e a do target
        NO MOMENTO em que o operator roda -- se o armature já tinha uma
        Action carregada (fora da pose de descanso -- ex.: rodou "Remove
        Generated Bones" + "Create Rig" de novo com uma animação
        aplicada, current frame no meio dela), essa "diferença" fica
        calculada em cima da pose ANIMADA, não da pose de descanso. O
        Child Of guarda esse inverse errado pra sempre -- dali em diante
        os poles saem "tortos" em QUALQUER frame, incluindo o bind pose,
        até alguém repetir manualmente o fluxo "voltar pra pose padrão +
        clicar em Set Inverse nos poles" (exatamente o que o usuário
        relatou fazer).

        v0.13.10 -- CORRIGIDO DE VERDADE: a v0.13.9 só trocava
        `armature.pose_position` pra 'REST' antes do loop -- não
        resolveu (confirmado pelo usuário). Causa: qualquer avaliação de
        depsgraph entre trocar 'REST' e o operator ler as matrizes
        (inclusive a que o PRÓPRIO operator dispara internamente antes
        de agir) reavalia a Action/NLA por cima de qualquer coisa que
        'REST' tentasse esconder -- 'REST' controla como o Blender
        DESENHA a pose (e como o modifier Armature deforma a malha), não
        se a Action continua rodando por baixo -- então a pose "vista"
        podia voltar a ficar animada bem na hora que o operator
        calculava a diferença. A técnica que funciona de verdade é a que
        o usuário já fazia na mão: DESLIGAR a Action (e mutar NLA
        tracks, se houver) de verdade, e zerar o transform local
        (`matrix_basis`) de CADA pose bone -- assim não sobra NADA
        (Action, NLA, ou pose manual antiga) que uma reavaliação de
        depsgraph possa reaplicar por cima; o bind pose fica garantido
        não importa quantas vezes o Blender reavaliar no meio do
        caminho. Guarda a Action, o mute de cada NLA track, e a
        matrix_basis de CADA bone ANTES de mexer -- restaura os três
        exatamente como estavam no final (bloco finally), mesmo se algum
        Set Inverse individual falhar no meio do loop -- a animação
        volta inteira, sem precisar o usuário reaplicar nada."""
        prev_mode = obj.mode
        if obj.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")

        view_layer = bpy.context.view_layer
        prev_active = view_layer.objects.active
        view_layer.objects.active = obj

        # Desliga tudo que possa reaplicar uma pose animada por cima do
        # bind pose durante o loop: a Action ativa, e cada NLA track
        # (mute individual, sem apagar/desvincular nada).
        anim_data = obj.animation_data
        prev_action = anim_data.action if anim_data is not None else None
        if anim_data is not None and prev_action is not None:
            anim_data.action = None
        prev_track_mutes = []
        if anim_data is not None:
            for track in anim_data.nla_tracks:
                prev_track_mutes.append((track, track.mute))
                track.mute = True

        # Zera o transform local de cada pose bone -- captura o valor
        # atual primeiro (pra restaurar depois). matrix_basis cobre
        # loc/rot/scale numa propriedade só, não importa o rotation_mode.
        saved_pose = {pb.name: pb.matrix_basis.copy() for pb in obj.pose.bones}
        for pb in obj.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        view_layer.update()

        try:
            targets_by_bone = []
            for data in chains_data:
                targets_by_bone.append((data["pole"], (CONSTRAINT_CHILD_OF_LOCAL, CONSTRAINT_CHILD_OF_GLOBAL)))
                targets_by_bone.append((data["ik_tip"], (CONSTRAINT_CHILD_OF_GLOBAL,)))
            if head_follow_built:
                targets_by_bone.append((resolve_head_ctrl_name(obj.data), (CONSTRAINT_HEAD_FOLLOW_ROT,)))

            for bone_name, constraint_names in targets_by_bone:
                pose_bone = obj.pose.bones.get(bone_name)
                if pose_bone is None:
                    continue
                obj.data.bones.active = pose_bone.bone
                for cname in constraint_names:
                    if cname not in pose_bone.constraints:
                        continue
                    try:
                        with bpy.context.temp_override(object=obj, active_object=obj, active_pose_bone=pose_bone):
                            bpy.ops.constraint.childof_set_inverse(constraint=cname, owner="BONE")
                    except Exception as exc:
                        self.report(
                            {"WARNING"},
                            f"Could not auto Set Inverse for '{cname}' on '{bone_name}': {exc}. "
                            f"Set it manually in the constraint panel.",
                        )
        finally:
            # Restaura a pose PRIMEIRO -- antes de religar a Action,
            # senão seria imediatamente sobrescrita por ela.
            for pb in obj.pose.bones:
                mb = saved_pose.get(pb.name)
                if mb is not None:
                    pb.matrix_basis = mb
            for track, was_muted in prev_track_mutes:
                track.mute = was_muted
            if anim_data is not None and prev_action is not None:
                anim_data.action = prev_action
            view_layer.update()

        view_layer.objects.active = prev_active
        if obj.mode != prev_mode:
            bpy.ops.object.mode_set(mode=prev_mode)

    # ------------------------------------------------------------------
    # Etapa 1 (Edit Mode): collections + bones duplicados
    # ------------------------------------------------------------------

    def _create_rigger_root_bone(self, edit_bones, name, world_down_local, length):
        """Cria um bone "ORG" que não veio do modelo (Origin automático ou
        slot de Root com "New Bone"), sem parent, no centro do mundo --
        (0,0,0) em espaço local do armature (este arquivo assume que o
        Object do armature fica na origem do mundo). `tail` aponta pra
        cima só pra ter direção/comprimento sensatos. Marcado com
        BONE_RIGGER_CREATED_PROP: fica fora da collection de export (ver
        _build_edit_bones) e "Remove Generated" apaga ele junto."""
        bone = edit_bones.new(name)
        bone.head = Vector((0.0, 0.0, 0.0))
        down = world_down_local if world_down_local.length > 1e-9 else Vector((0.0, 0.0, -1.0))
        bone.tail = bone.head - down.normalized() * length
        bone.roll = 0.0
        bone.parent = None
        bone.use_deform = False
        bone[BONE_RIGGER_CREATED_PROP] = True
        return bone

    def _ensure_root_bones(self, armature, edit_bones, world_down_local):
        """Garante que os bones de root existam antes do loop genérico
        (entram no set normal de ORG bones e ganham _CTRL/MCH/etc. pelo
        caminho padrão).

        Com entrada ROOT válida (ver resolve_root_slots): cria só os
        slots marcados "New Bone" que ainda não existem -- comprimento
        crescente por slot, pros widgets ficarem concêntricos. Slot de
        bone do modelo que não existe só avisa.

        Sem entrada ROOT (legado): alguns modelos importados não trazem
        o ORG "Origin" (ver ORIGIN_ORG_NAME) -- sem ele, root.master_CTRL
        fica sem parent e todo pole target perde a opção de Child Of
        global -- então cria um. Esse Origin automático também fica fora
        do export (antes ele vazava pro .blockymodel/.blockyanim como um
        bone raiz a mais que o modelo original não tinha)."""
        slots = resolve_root_slots(armature)
        if not slots:
            if ORIGIN_ORG_NAME in edit_bones:
                return 0
            self._create_rigger_root_bone(edit_bones, ORIGIN_ORG_NAME, world_down_local, ORIGIN_FALLBACK_LENGTH)
            self.report(
                {"INFO"},
                f"No '{ORIGIN_ORG_NAME}' bone found on this armature -- created one at the world center so "
                f"'{ROOT_MASTER_PARENT}' and the rest of the rig can still be generated normally (Blender "
                f"only, not exported). Add a ROOT entry in Bone Settings to use one of the model's bones instead.",
            )
            return 1

        # Bones criados pelo rigger que NÃO estão mais em nenhum slot (ex.
        # o Origin automático de antes da entrada ROOT existir, ou um
        # Root "New Bone" que saiu da lista) -- removidos junto com as
        # camadas deles, senão ficariam dois "Origins" amarelos no rig
        # e só um funcionando. Só bones com BONE_RIGGER_CREATED_PROP --
        # bone do modelo nunca é tocado.
        wanted = {name for _slot, name, _create in slots}
        stale = [b.name for b in edit_bones if b.get(BONE_RIGGER_CREATED_PROP) and b.name not in wanted]
        for stale_name in stale:
            for suffix in ("", SUFFIX_CTRL, SUFFIX_MCH, SUFFIX_MCH_TRANSFER):
                bone = edit_bones.get(stale_name + suffix)
                if bone is not None:
                    edit_bones.remove(bone)
        if stale:
            self.report(
                {"INFO"},
                f"Removed {len(stale)} root bone(s) created by an earlier Create Rig that are no longer in the "
                f"Root entry: {', '.join(stale)}.",
            )

        created = 0
        for slot, name, create in slots:
            if name in edit_bones:
                continue
            if not create:
                self.report(
                    {"WARNING"},
                    f"Root {slot}: bone '{name}' not found -- pick an existing bone or turn on 'New Bone'.",
                )
                continue
            length = ORIGIN_FALLBACK_LENGTH * (1.0 + ROOT_CREATED_LENGTH_STEP * (slot - 1))
            self._create_rigger_root_bone(edit_bones, name, world_down_local, length)
            created += 1
        if created:
            self.report({"INFO"}, f"Created {created} root bone(s) (Blender only, not exported).")
        return created

    # Custom property no Armature: nomes ORG dos roots encadeados na
    # última geração, UM TEXTO só com um nome por linha -- ID property do
    # Blender não aceita lista de strings (TypeError), só de números/
    # dicts. Nome de bone nunca tem quebra de linha. Ver
    # _apply_root_chain_parents.
    _ROOT_CHAIN_APPLIED_PROP = "hytale_root_chain_applied"

    @staticmethod
    def _natural_ctrl_parent(edit_bones, ctrl):
        """Pai "natural" de um _CTRL -- o que o loop genérico daria,
        espelhando o ORG (o _CTRL do pai do ORG), ou None."""
        org = edit_bones.get(source_org_of(ctrl))
        if org is None or org.parent is None:
            return None
        return find_layer_bone(edit_bones, org.parent.name, SUFFIX_CTRL)

    def _reset_ctrl_to_natural_parent(self, edit_bones, ctrl):
        natural = self._natural_ctrl_parent(edit_bones, ctrl)
        if natural is None or not parent_would_loop(ctrl, natural):
            ctrl.parent = natural
            ctrl.use_connect = False

    def _apply_root_chain_parents(self, armature, edit_bones):
        """Root N > ... > Root 2 > Root 1 (Origin), na camada _CTRL: o
        _CTRL de cada root vira filho do _CTRL do root do slot seguinte.
        Tudo que já estava abaixo do Origin continua abaixo dele -- só o
        Origin (e cada root acima) ganha um pai novo. A hierarquia ORG
        (a que é exportada) não muda.

        Antes de aplicar, todo root encadeado na geração ANTERIOR (lista
        guardada no Armature) volta pro pai natural -- senão tirar a
        entrada ROOT, trocar um root ou diminuir a quantidade deixaria um
        _CTRL preso num root que não existe mais na configuração."""
        previous = armature.get(self._ROOT_CHAIN_APPLIED_PROP, "")
        previous_names = previous.split("\n") if isinstance(previous, str) else []
        for name in previous_names:
            if not name:
                continue
            ctrl = find_layer_bone(edit_bones, name, SUFFIX_CTRL)
            if ctrl is not None:
                self._reset_ctrl_to_natural_parent(edit_bones, ctrl)

        slots = resolve_root_slots(armature)
        ctrls = []
        for _slot, name, _create in slots:
            ctrl = find_layer_bone(edit_bones, name, SUFFIX_CTRL)
            if ctrl is not None:
                ctrls.append(ctrl)

        for child, parent in zip(ctrls, ctrls[1:]):
            if parent_would_loop(child, parent):
                self.report(
                    {"WARNING"},
                    f"Root '{parent.name}' is already below '{child.name}' in the hierarchy -- can't make it "
                    f"the parent (would create a loop), skipped.",
                )
                continue
            child.parent = parent
            child.use_connect = False

        applied = [source_org_of(c) for c in ctrls] if len(ctrls) > 1 else []
        if applied:
            armature[self._ROOT_CHAIN_APPLIED_PROP] = "\n".join(applied)
        elif self._ROOT_CHAIN_APPLIED_PROP in armature:
            del armature[self._ROOT_CHAIN_APPLIED_PROP]

    def _build_edit_bones(self, armature, world_down_local):
        coll_export = ensure_bone_collection(armature, COLL_HYTALE_EXPORT)
        coll_internal = ensure_bone_collection(armature, COLL_INTERNAL)
        coll_org = ensure_bone_collection(armature, COLL_ORG, parent=coll_internal)
        coll_mch = ensure_bone_collection(armature, COLL_MCH, parent=coll_internal)
        coll_mch_ik = ensure_bone_collection(armature, COLL_MCH_IK, parent=coll_internal)
        coll_ctrl = ensure_bone_collection(armature, COLL_CTRL, parent=coll_internal)
        coll_ctrl_ik = ensure_bone_collection(armature, COLL_CTRL_IK, parent=coll_internal)
        coll_attachments_imported = ensure_bone_collection(armature, COLL_ATTACHMENTS_IMPORTED, parent=coll_internal)

        edit_bones = armature.edit_bones
        self._ensure_root_bones(armature, edit_bones, world_down_local)

        org_bones = [b for b in edit_bones if PROP_RIG_LAYER not in b.keys()]
        org_by_name = {b.name: b for b in org_bones}
        ordered = self._order_top_down(org_bones, org_by_name)

        stats = {
            "mch": 0, "ctrl": 0, "ik": 0, "ik_mch": 0, "root": 0, "mch_transfer": 0, "continuous_chain": 0,
            "head_follow_active": False, "head_follow_source": None,
            "spine_ctrl_enabled": True,
        }

        for org in ordered:
            coll_org.assign(org)
            if org.get(BONE_RIGGER_CREATED_PROP):
                # Bone criado pelo rigger (Origin automático / Root "New
                # Bone") -- só controle no Blender, nunca exportado.
                # unassign() explícito corrige rigs em que ele já tinha
                # entrado na collection de export.
                coll_export.unassign(org)
            else:
                coll_export.assign(org)
            if is_attachment_bone(org):
                coll_attachments_imported.assign(org)

            parent_name = org.parent.name if (org.parent and org.parent.name in org_by_name) else None

            mch, is_new = create_bone_like(edit_bones, org, org.name + SUFFIX_MCH)
            mch[PROP_SOURCE_ORG] = org.name
            if is_new:
                mch.parent = find_layer_bone(edit_bones, parent_name, SUFFIX_MCH)
                mch.use_connect = bool(org.use_connect and mch.parent is not None)
                mch[PROP_RIG_LAYER] = "MCH"
                stats["mch"] += 1
            coll_mch.assign(mch)

            # Nome do _CTRL passa por control_name(): usa o apelido do ORG
            # (Rename "Only CTRL") se houver. PROP_SOURCE_ORG: caminho de
            # volta controle -> ORG, gravado toda vez (corrige rig antigo).
            ctrl, is_new = create_bone_like(edit_bones, org, control_name(armature, org.name, SUFFIX_CTRL))
            ctrl[PROP_SOURCE_ORG] = org.name
            if is_new:
                ctrl.parent = find_layer_bone(edit_bones, parent_name, SUFFIX_CTRL)
                ctrl.use_connect = bool(org.use_connect and ctrl.parent is not None)
                ctrl[PROP_RIG_LAYER] = "CTRL"
                stats["ctrl"] += 1
            coll_ctrl.assign(ctrl)

            # Bridge genérico -- rest = ORG original intocada, NUNCA
            # "connected" (sempre solto). Parent real no _CTRL desta
            # mesma iteração (não no bridge do org pai) -- desacopla a
            # rest do bridge (sempre limpa) da rest do _CTRL. Reatribuído
            # toda vez, corrige também um bone de execução anterior.
            transfer, is_new = create_bone_like(edit_bones, org, org.name + SUFFIX_MCH_TRANSFER)
            transfer[PROP_SOURCE_ORG] = org.name
            if is_new:
                transfer[PROP_RIG_LAYER] = "MCH-TRANSFER"
                stats["mch_transfer"] += 1
            transfer.parent = ctrl
            transfer.use_connect = False
            coll_mch_ik.assign(transfer)

        # Bones utilitários de controle geral -- precisam existir antes
        # da camada de IK e dos overrides de parent dos CTRL normais.
        #
        # root.spine_CTRL é opcional (checkbox na entrada SPINE) -- lê
        # a primeira entrada SPINE antes de criar; default True
        # preserva o comportamento de sempre. Guardado em stats pra
        # _build_spine_follow (Pose Mode, depois) saber se deve pular
        # os constraints de Spine Follow também.
        spine_item = next((it for it in armature.hytale_ik_chains if it.chain_type == "SPINE"), None)
        stats["spine_ctrl_enabled"] = spine_item.spine_ctrl_enabled if spine_item is not None else True
        stats["root"] += self._build_root_controls(armature, edit_bones, coll_ctrl, stats["spine_ctrl_enabled"])
        self._apply_ctrl_parent_overrides(armature, edit_bones)
        self._apply_root_chain_parents(armature, edit_bones)

        resolved_chains = self._resolve_chains(edit_bones, armature)
        chains_data = self._build_ik_layer(
            armature, edit_bones, coll_ctrl_ik, coll_mch_ik, resolved_chains, stats, world_down_local
        )

        resolved_tail_chains = self._resolve_tail_chains(edit_bones, armature)
        tail_chains_data = self._build_tail_layer(armature, edit_bones, resolved_tail_chains)

        # "Continuous Chain" (HEAD/SPINE) -- roda depois de tudo que
        # possa criar/reparentar um _CTRL de HEAD/SPINE. Só mexe no
        # TAIL de edit bones já existentes.
        stats["continuous_chain"] = self._apply_continuous_chain_redirect(armature, edit_bones)

        # "Head Follow" -- redirect independente do Continuous Chain
        # acima (só do Tail do predecessor imediato de "Head"). stats
        # guarda (bool, str|None), estado que atravessa de Edit Mode
        # (aqui) pra Pose Mode (_build_head_follow, chamado depois).
        stats["head_follow_active"], stats["head_follow_source"] = self._apply_head_follow_parent(
            armature, edit_bones
        )

        self._build_main_collections(armature, edit_bones)
        self._move_main_child_before(armature, COLL_MAIN_CHAIN, COLL_MAIN_ROOT)
        self._propagate_pole_and_tip_to_main_collections(edit_bones, chains_data)
        self._apply_bone_collection_overrides(armature, edit_bones, chains_data, tail_chains_data)
        # Reordena o painel nativo "Bone Collections" pra bater com
        # Collection Settings -- precisa rodar depois que TODAS as
        # collections (default + customizadas + Head/Spine) já existem.
        sync_bone_collection_order(armature)
        self._apply_collection_visibility(armature)

        return stats, chains_data, tail_chains_data

    def _resolve_chains(self, edit_bones, armature):
        """Lê armature.hytale_ik_chains e resolve cada item ARM/LEG num
        caminho real de edit bones ORG (root -> ... -> tip). Cadeias
        TAIL são resolvidas à parte, por _resolve_tail_chains -- não
        usam IK/pole nenhum. v0.9 (Etapa 2, ampliado na 2.7 pra incluir
        ATTACHMENTS; v0.10 pra incluir TEXTURE_PICKER): HEAD/SPINE/ATTACHMENTS/
        TEXTURE_PICKER também ficam de fora daqui -- não criam bone nenhum, não
        têm root/tip/pole (ver _head_spine_bone_names/
        _apply_bone_collection_overrides), então tentar resolvê-los
        como uma cadeia de IK quebraria (campos vazios/sem sentido pra
        eles)."""
        resolved = []
        for item in armature.hytale_ik_chains:
            if item.chain_type in ("CHAIN", "HEAD", "SPINE", "ATTACHMENTS", "TEXTURE_PICKER", "ROOT"):
                continue
            label = item.label or item.root_bone or "(sem nome)"
            if not item.root_bone or not item.tip_bone:
                self.report({"WARNING"}, f"IK chain '{label}': root/tip bone name is empty -- skipped.")
                continue
            root = edit_bones.get(item.root_bone)
            if root is None:
                self.report({"WARNING"}, f"IK chain '{label}': root bone '{item.root_bone}' not found -- skipped.")
                continue
            if edit_bones.get(item.tip_bone) is None:
                self.report({"WARNING"}, f"IK chain '{label}': tip bone '{item.tip_bone}' not found -- skipped.")
                continue
            path = find_org_path(root, item.tip_bone)
            if path is None:
                self.report(
                    {"WARNING"},
                    f"IK chain '{label}': no path from '{item.root_bone}' to '{item.tip_bone}' -- skipped.",
                )
                continue
            if len(path) < 3:
                self.report(
                    {"WARNING"},
                    f"IK chain '{label}' has only {len(path)} bone(s) -- for a proper 2-joint IK, root->tip "
                    f"should pass through at least one bone in between.",
                )
            pole_ref = edit_bones.get(item.pole_bone) if item.pole_bone else None
            if pole_ref is None:
                pole_ref = path[len(path) // 2]
            resolved.append({"item": item, "path": path, "pole_ref": pole_ref})
        return resolved

    def _resolve_tail_chains(self, edit_bones, armature):
        """Irmã de _resolve_chains, só pras entradas TAIL (v0.7): mesmo
        find_org_path (root -> ... -> tip andando pela hierarquia ORG),
        mas sem pole/lado/mínimo-de-3-bones -- uma cauda não faz IK, não
        tem "joelho" pra dobrar, então até um caminho de 2 bones (root
        direto no tip) é válido."""
        resolved = []
        for item in armature.hytale_ik_chains:
            if item.chain_type != "CHAIN":
                continue
            label = item.label or item.root_bone or "(sem nome)"
            if not item.root_bone or not item.tip_bone:
                self.report({"WARNING"}, f"Chain '{label}': root/tip bone name is empty -- skipped.")
                continue
            root = edit_bones.get(item.root_bone)
            if root is None:
                self.report({"WARNING"}, f"Chain '{label}': root bone '{item.root_bone}' not found -- skipped.")
                continue
            if edit_bones.get(item.tip_bone) is None:
                self.report({"WARNING"}, f"Chain '{label}': tip bone '{item.tip_bone}' not found -- skipped.")
                continue
            path = find_org_path(root, item.tip_bone)
            if path is None:
                self.report(
                    {"WARNING"},
                    f"Chain '{label}': no path from '{item.root_bone}' to '{item.tip_bone}' -- skipped.",
                )
                continue
            resolved.append({"item": item, "path": path})
        return resolved

    def _build_tail_layer(self, armature, edit_bones, resolved_tail_chains):
        """Pra cada cadeia CHAIN resolvida ("Chain" na UI e também no
        identificador interno desde v0.7.14 -- ERA "TAIL" nos dois até
        v0.7.13 (só o rótulo mudou primeiro, ver COLL_MAIN_CHAIN em
        constants.py) -- pedido explícito do usuário pra também trocar o
        identificador interno. SEM MIGRAÇÃO (mesma decisão de sempre):
        uma entrada salva com chain_type == "TAIL" de antes desta versão
        fica com o Type em branco/inválido no Bone Settings -- o usuário
        reseleciona "Chain" manualmente): quem forma a cadeia fisicamente
        contínua (posicionalmente -- não necessariamente "connected" no
        sentido do Blender, ver abaixo) são os próprios bones `_CTRL`
        (já criados pelo loop genérico em _build_edit_bones, ANTES desta
        etapa rodar) -- aqui só REDIRECIONA o tail de cada `_CTRL` da
        cauda pro head do próximo segmento (mesmo truque de
        _build_ik_layer: os ORG do Hytale vêm com o eixo Y apontando pra
        cima, não pro filho).

        v0.7.13 -- use_connect (Bone Properties > Relations > Connected)
        virou OPCIONAL (HytaleIKChainItem.tail_use_connect, desligado
        por padrão -- pedido explícito do usuário) nos segmentos
        INTERNOS da cadeia (i > 0, ver bloco abaixo) -- a posição já
        bate (tail de um == head do próximo) sem precisar da conexão
        "travada" do Blender, então por padrão continua desligada (o
        comportamento de sempre, permite reparent/offset livre, ex.
        parent_override). Ligar é útil quando o efeito visual de
        "grudado de verdade" importa (ex. uma orelha comprida). A RAIZ
        da cadeia (i == 0) nunca liga Connected, mesmo com o toggle
        ativo -- seu parent é EXTERNO à cadeia (o _CTRL do ORG pai real,
        ou um parent_override), sem garantia de que a posição bate.

        v0.13: o bridge dedicado `_Tail` (SUFFIX_TAIL) foi RETIRADO --
        Tail agora reaproveita o bridge GENÉRICO `_MCH_Transfer`
        (SUFFIX_MCH_TRANSFER) que o loop genérico de _build_edit_bones
        já cria pra TODO `_CTRL`, mesmo princípio exato do bridge
        `_MCH_IK_Transfer` da cadeia de IK: rest orientation do MCH (ou
        seja, a do ORG original, INTOCADA -- NÃO redirecionada, ao
        contrário do CTRL acima), filho REAL do `_CTRL` correspondente.
        Essa etapa aqui não CRIA mais o bridge (só o `.get()`, já criado
        antes) -- só precisa dele pra montar `tail_bones` (ver
        tail_chains_data abaixo, consumido por anim_importer.py). O MCH
        normal (FK_CopyRotation/FK_CopyScale/FK_CopyLocation) já mira
        nesse bridge desde o loop genérico (ver _build_pose_constraints)
        -- exatamente por que o bridge existe: copiar rotação em World
        Space de um bone cuja rest orientation foi alterada (o CTRL,
        aqui redirecionado) sai errado/invertido sem esse intermediário
        de rest "limpa".

        Hierarquia final por segmento:
            ORG -> (constraint) -> MCH -> (constraint) -> _MCH_Transfer (bridge)
            _MCH_Transfer (bridge) -- parent real -> _CTRL
            _CTRL -- parent real -> _CTRL anterior da cauda

        Collections: _CTRL (a cadeia real, editável) fica em Main/Tail,
        visível -- é nela que o usuário seleciona/anima e onde um addon
        de física deve prender os constraints. O bridge `_MCH_Transfer`
        fica em Internal/Specials (mesma collection do bridge
        `_MCH_IK_Transfer`, ver COLL_MCH_IK -- renomeada de "MCH-IK" pra
        "Specials" nesta versão), oculta por padrão -- é só mecanismo
        interno, nunca precisa ser selecionado."""
        coll_main = ensure_bone_collection(armature, COLL_MAIN)
        # Só cria Main/Tail se houver pelo menos uma cadeia de verdade
        # -- senão sobrava uma collection vazia à toa.
        coll_tail = ensure_bone_collection(armature, COLL_MAIN_CHAIN, parent=coll_main) if resolved_tail_chains else None

        tail_chains_data = []
        for resolved in resolved_tail_chains:
            chain = resolved["path"]
            item = resolved["item"]
            tip_index = len(chain) - 1

            # Bones _CTRL reais desta cadeia -- já existem (criados pelo
            # loop genérico antes). Se algum não existir, avisa e pula
            # a cadeia inteira em vez de quebrar.
            ctrl_bones = []
            for org in chain:
                ctrl = find_layer_bone(edit_bones, org.name, SUFFIX_CTRL)
                if ctrl is None:
                    self.report(
                        {"WARNING"},
                        f"Chain: CTRL bone '{control_name(armature, org.name, SUFFIX_CTRL)}' not found -- skipped.",
                    )
                    ctrl_bones = []
                    break
                ctrl_bones.append(ctrl)
            if not ctrl_bones:
                continue

            # Redireciona o tail de cada _CTRL pro head do próximo
            # segmento, toda vez. use_connect fica desligado de
            # propósito -- a posição já bate sem precisar da conexão
            # "travada" do Blender, os bones continuam livres pra ter
            # parent/offset reparentado. A ponta (sem próximo segmento)
            # sempre reseta pro tail/roll ORIGINAL do ORG primeiro
            # (idempotente) e só então aplica a rotação manual opcional.
            for i, ctrl in enumerate(ctrl_bones):
                if i < tip_index:
                    ctrl.tail = chain[i + 1].head.copy()
                    ctrl.align_roll(chain[i].z_axis)
                else:
                    ctrl.tail = chain[i].tail.copy()
                    ctrl.roll = chain[i].roll
                    rotate_edit_bone_local_axis(
                        ctrl, item.tail_tip_rotation_axis, item.tail_tip_rotation_deg
                    )
                # "Connected" só nos segmentos internos (i > 0, cujo
                # parent real é o _CTRL anterior desta cadeia, já
                # posicionado head-a-tail). O primeiro fica de fora --
                # o parent dele é externo, sem garantia de que a
                # posição bate; ligar "Connected" ali puxaria a cadeia
                # inteira pra colar no parent externo.
                if i > 0:
                    ctrl.use_connect = item.tail_use_connect
                coll_tail.assign(ctrl)

            # Parent override ("Attach To") -- aplica no _CTRL raiz da
            # cauda toda vez, sobrescrevendo o parent que o loop
            # genérico já deu, só se o usuário pediu explicitamente.
            if item.parent_override:
                override_parent = _resolve_parent_override(edit_bones, item.parent_override, armature)
                if override_parent is not None and parent_would_loop(ctrl_bones[0], override_parent):
                    self.report(
                        {"WARNING"},
                        f"Parent override '{item.parent_override}' for '{ctrl_bones[0].name}' is inside this "
                        f"same chain (would create a loop) -- left as-is.",
                    )
                elif override_parent is not None:
                    ctrl_bones[0].parent = override_parent
                    ctrl_bones[0].use_connect = False
                else:
                    self.report(
                        {"WARNING"},
                        f"Parent override '{item.parent_override}' not found for '{ctrl_bones[0].name}' -- "
                        f"left as-is.",
                    )

            # Bridge _MCH_Transfer por segmento -- já existe (loop
            # genérico cria um pra todo _CTRL antes de rodar aqui), só
            # busca. Se não achar, avisa e pula a cadeia.
            tail_bones = []
            missing_bridge = False
            for org in chain:
                bridge = edit_bones.get(org.name + SUFFIX_MCH_TRANSFER)
                if bridge is None:
                    self.report(
                        {"WARNING"},
                        f"Chain: bridge bone '{org.name + SUFFIX_MCH_TRANSFER}' not found -- skipped.",
                    )
                    missing_bridge = True
                    break
                tail_bones.append(bridge)
            if missing_bridge:
                continue

            tail_chains_data.append(
                {
                    "org_names": [b.name for b in chain],
                    "tail_bones": [b.name for b in tail_bones],
                    "ctrl_names": [b.name for b in ctrl_bones],
                    # "Auto" = fica em Main/Tail; um nome redireciona os
                    # _CTRL desta cauda (ver _apply_bone_collection_overrides).
                    "collection_override": item.collection_override,
                }
            )

        return tail_chains_data

    def _apply_continuous_chain_redirect(self, armature, edit_bones):
        """v0.13 -- "Continuous Chain" (ver HytaleIKChainItem.continuous_chain/
        continuous_chain_link_bone): generaliza pra HEAD e SPINE o MESMO
        truque que a cadeia TAIL já usa (ver _build_tail_layer) -- o
        `_CTRL` de cada bone listado (ver _head_spine_bone_names) tem o
        TAIL redirecionado pro HEAD do próximo da lista, formando uma
        cadeia visualmente contínua. O HEAD de cada bone NUNCA muda
        (fica sempre na posição original do ORG) -- só o TAIL se move.
        NÃO precisa de bridge próprio nem retarget de constraint nenhum:
        desde a v0.13, TODO `_CTRL` já tem um `_MCH_Transfer` com rest
        limpa (ver SUFFIX_MCH_TRANSFER/_build_edit_bones), que já é o
        alvo do FK_CopyRotation/_Scale/_Location do MCH -- mexer só no
        TAIL do `_CTRL` aqui já é suficiente, o resto do pipeline nem
        precisa saber que isso aconteceu.

        Roda em QUALQUER entrada HEAD/SPINE configurada, ligada ou não
        -- pra cada uma, primeiro RESETA o Tail/Roll de cada `_CTRL`
        listado pro original do próprio ORG (idempotente: permite
        ligar/desligar o toggle, ou trocar continuous_chain_link_bone,
        e "Create Rig" de novo sempre convergir pro estado certo, nunca
        acumular de uma execução anterior) -- só DEPOIS disso, se
        `continuous_chain` estiver ligado, aplica o redirect de verdade.

        O ÚLTIMO bone da lista é tratado à parte: se
        `continuous_chain_link_bone` apontar pra um bone ORG válido, o
        Tail dele é redirecionado pro HEAD desse alvo (permite, por
        exemplo, o último bone de uma cadeia SPINE -- ex. "Chest" --
        conectar no primeiro bone de uma cadeia HEAD -- ex. "Neck1"),
        mesmo sendo entradas SEPARADAS da lista; se o campo estiver
        vazio (ou não resolver), o último bone fica com o Tail/Roll
        original do próprio ORG (igual a ponta de uma cadeia TAIL).

        CAVEAT conhecido -- Hytale_SpineFollow (ver _build_spine_follow/
        SPINE_FOLLOW_BONES, hoje Belly_CTRL e Chest_CTRL): é um Copy
        Transforms em espaço LOCAL (relativo à PRÓPRIA rest do bone, ao
        contrário do World Space que o resto do rig usa) -- mudar o Tail
        de Belly_CTRL/Chest_CTRL aqui muda também os eixos locais deles,
        então o "empurrão" que esse constraint aplica quando o usuário
        move o root.spine_CTRL passa a se manifestar numa direção
        levemente diferente de antes. EM REPOUSO (root.spine_CTRL sem
        pose, o caso comum) isso não importa -- mix_mode=AFTER_FULL com
        alvo em identidade é sempre um no-op, então nada muda pra quem
        nunca mexe no root.spine_CTRL. Só afeta o "follow-through" de
        quem ativamente anima o root.spine_CTRL numa Spine com
        Continuous Chain ligado -- não tentei compensar isso aqui (seria
        um cálculo à parte, e o efeito é pequeno pros influence típicos,
        0.5/0.63); se algum dia isso incomodar visualmente, é aqui que
        precisa mexer."""
        applied = 0
        for item in armature.hytale_ik_chains:
            if item.chain_type not in ("HEAD", "SPINE"):
                continue

            names = [name for name in _head_spine_bone_names(item) if name]
            ctrl_bones = []
            for name in names:
                org = edit_bones.get(name)
                ctrl = find_layer_bone(edit_bones, name, SUFFIX_CTRL)
                if org is None or ctrl is None:
                    continue  # já reportado em outro lugar (RIG_OT_hytale_validate_rig) -- não duplica warning aqui
                ctrl_bones.append((org, ctrl))
                # Baseline idempotente -- ver docstring acima.
                ctrl.tail = org.tail.copy()
                ctrl.roll = org.roll

            # >= 1 (não >= 2): mesmo com só UM bone configurado nesta
            # entrada (ex.: HEAD sem Neck e sem Head End -- só "Head"),
            # o link pro continuous_chain_link_bone ainda faz sentido --
            # é só o loop de "meio da cadeia" logo abaixo (range(len-1))
            # que naturalmente não roda com 1 elemento só.
            if not item.continuous_chain or not ctrl_bones:
                continue

            for i in range(len(ctrl_bones) - 1):
                org_i, ctrl_i = ctrl_bones[i]
                next_org, _ = ctrl_bones[i + 1]
                ctrl_i.tail = next_org.head.copy()
                ctrl_i.align_roll(org_i.z_axis)
                applied += 1

            last_org, last_ctrl = ctrl_bones[-1]
            link_name = (item.continuous_chain_link_bone or "").strip()
            link_org = edit_bones.get(link_name) if link_name else None
            if link_org is not None:
                last_ctrl.tail = link_org.head.copy()
                last_ctrl.align_roll(last_org.z_axis)
                applied += 1
            elif link_name:
                self.report(
                    {"WARNING"},
                    f"{item.chain_type.title()} '{item.label or last_org.name}': continuous_chain connect "
                    f"target '{link_name}' not found -- last bone kept its own Tail.",
                )
        return applied

    def _build_tail_pose_constraints(self, obj, tail_chains_data):
        """Desde que Tail passou a reaproveitar o bridge genérico
        _MCH_Transfer, o loop genérico de _build_pose_constraints já
        deixa FK_Copy* (em MCH) mirando no subtarget certo pra bones de
        cauda também. Este método virou uma reafirmação idempotente,
        mantida pra clareza e pra continuar reportando
        tail_constraint_count no resumo. Bones de cauda não entram em
        chains_data, então o loop genérico já os deixa com
        influence=1.0 fixa (sem FK/IK)."""
        pose_bones = obj.pose.bones
        count = 0
        for data in tail_chains_data:
            for i, org_name in enumerate(data["org_names"]):
                bridge_name = data["tail_bones"][i]
                mch_name = org_name + SUFFIX_MCH
                if bridge_name not in pose_bones or mch_name not in pose_bones:
                    continue
                mch_pose = pose_bones[mch_name]
                for con_name in (CONSTRAINT_FK_ROT, CONSTRAINT_FK_SCALE, CONSTRAINT_FK_LOC):
                    con = mch_pose.constraints.get(con_name)
                    if con is not None:
                        con.target = obj
                        con.subtarget = bridge_name
                count += 1
        return count

    def _build_root_controls(self, armature, edit_bones, coll_ctrl, spine_ctrl_enabled=True):
        """Cria (se ainda não existirem) root.master_CTRL, root.spine_CTRL
        e root.pelvis_CTRL. Não derivam de nenhum ORG por sufixo -- usam
        bones de referência já existentes só pra posição/orientação
        inicial.

        `spine_ctrl_enabled=False` pula root.spine_CTRL inteiro -- e se
        rodar de novo depois de ter sido criado, não apaga o que já
        existe (não-destrutivo). root.pelvis_CTRL é independente."""
        created = 0
        # Papéis vindos do Bone Settings (entrada SPINE) -- "Belly" =
        # Spine 1, "Pelvis" = campo Pelvis. Sem entrada SPINE, os nomes
        # legados (ver helpers.resolve_*_org_name).
        master_source_name = resolve_master_source_org_name(armature)
        pelvis_name = resolve_pelvis_org_name(armature)
        master_source = edit_bones.get(master_source_name)
        belly_ctrl = find_layer_bone(edit_bones, master_source_name, SUFFIX_CTRL)
        pelvis_ctrl = find_layer_bone(edit_bones, pelvis_name, SUFFIX_CTRL)

        master = edit_bones.get(BONE_ROOT_MASTER)
        if master is None and master_source is not None:
            master, is_new = create_bone_like(edit_bones, master_source, BONE_ROOT_MASTER)
            if is_new:
                master[PROP_RIG_LAYER] = "ROOT-CTRL"
                created += 1
        elif master_source is None:
            self.report(
                {"WARNING"},
                f"'{master_source_name}' not found -- skipping {BONE_ROOT_MASTER}. Set the SPINE entry "
                f"(Pelvis/Spine 1) in Bone Settings to the character's real bones.",
            )
        if master is not None:
            # Pai = _CTRL do Origin principal (Root 1 da entrada ROOT, ou
            # "Origin_CTRL" legado). Reaplicado em TODA geração, não só
            # na criação -- trocar o Root 1 no Bone Settings tem que levar
            # o master junto.
            origin_ctrl_name = resolve_origin_ctrl_name(armature)
            origin_ctrl = edit_bones.get(origin_ctrl_name)
            if origin_ctrl is None:
                self.report(
                    {"WARNING"},
                    f"'{origin_ctrl_name}' not found -- {BONE_ROOT_MASTER} left without a parent.",
                )
                master.parent = None
            elif parent_would_loop(master, origin_ctrl):
                self.report(
                    {"WARNING"},
                    f"'{origin_ctrl_name}' is below {BONE_ROOT_MASTER} in the hierarchy -- can't be its "
                    f"parent (would create a loop). Pick a higher bone as Root 1 (Origin).",
                )
            else:
                master.parent = origin_ctrl
            master.use_connect = False
            coll_ctrl.assign(master)

        if master_source is not None and spine_ctrl_enabled:
            spine, is_new = create_bone_like(edit_bones, master_source, BONE_ROOT_SPINE)
            if is_new:
                spine.parent = master
                direction = spine.tail - spine.head
                if direction.length > 1e-9:
                    spine.tail = spine.head + direction.normalized() * ROOT_SPINE_LENGTH
                else:
                    spine.tail = spine.head + Vector((0.0, ROOT_SPINE_LENGTH, 0.0))
                spine[PROP_RIG_LAYER] = "ROOT-CTRL"
                created += 1
            coll_ctrl.assign(spine)

        if belly_ctrl is not None and pelvis_ctrl is not None:
            pelvis, is_new = create_bone_like(edit_bones, belly_ctrl, BONE_ROOT_PELVIS)
            if is_new:
                if (pelvis_ctrl.head - belly_ctrl.head).length > 1e-6:
                    # Normal (Player): do Spine 1 ("Belly") até o Pelvis.
                    pelvis.head = belly_ctrl.head.copy()
                    pelvis.tail = pelvis_ctrl.head.copy()
                else:
                    # SPINE só com Pelvis (Spine 1 = o próprio Pelvis, ou
                    # os dois no mesmo ponto) -- head->tail teria
                    # comprimento zero e o Blender apagaria o bone. Usa a
                    # forma do próprio Pelvis_CTRL.
                    pelvis.head = pelvis_ctrl.head.copy()
                    pelvis.tail = pelvis_ctrl.tail.copy()
                    pelvis.roll = pelvis_ctrl.roll
                pelvis.parent = master
                pelvis[PROP_RIG_LAYER] = "ROOT-CTRL"
                created += 1
            coll_ctrl.assign(pelvis)
        else:
            missing = [
                n for n, b in ((control_name(armature, master_source_name, SUFFIX_CTRL), belly_ctrl), (control_name(armature, pelvis_name, SUFFIX_CTRL), pelvis_ctrl))
                if b is None
            ]
            self.report(
                {"WARNING"},
                f"{' and '.join(dict.fromkeys(missing))} not found -- skipping {BONE_ROOT_PELVIS}. Set the "
                f"SPINE entry (Pelvis/Spine 1) in Bone Settings to the character's real bones.",
            )

        # PROPERTIES: acima da cabeça, parentado no _CTRL da cabeça
        # (resolvido a partir do head_bone configurado em HEAD -- não
        # mais hardcoded em "Head_CTRL", que quebrava em qualquer
        # personagem cujo ORG da cabeça não se chamasse "Head" com H
        # maiúsculo, ex. "head" minúsculo: PROPERTIES nunca era criado,
        # e sem ele nem os custom properties de FK/IK switch existem),
        # mesmo tamanho/eixo dele -- só guarda as custom properties de
        # FK/IK switch de todas as cadeias, longe do que o usuário for animar.
        head_ctrl_name = resolve_head_ctrl_name(armature)
        head_ctrl = edit_bones.get(head_ctrl_name)
        if head_ctrl is not None:
            properties_bone, is_new = create_bone_like(edit_bones, head_ctrl, BONE_PROPERTIES)
            if is_new:
                properties_bone.head = head_ctrl.head + Vector((0.0, PROPERTIES_BONE_OFFSET_Y, 0.0))
                properties_bone.tail = properties_bone.head + (head_ctrl.tail - head_ctrl.head)
                properties_bone.parent = head_ctrl
                properties_bone.use_connect = False
                properties_bone[PROP_RIG_LAYER] = "CTRL"
                created += 1
            coll_ctrl.assign(properties_bone)
        else:
            self.report(
                {"WARNING"},
                f"'{head_ctrl_name}' not found -- skipping {BONE_PROPERTIES}. Add a HEAD bone setting "
                f"pointing at the real head bone (Auto-Detect or manually) before Create Rig.",
            )

        return created

    def _resolve_ctrl_parent_overrides(self, armature, edit_bones):
        """{nome do _CTRL: bone que vira o parent dele} -- os parents
        forçados fora da hierarquia ORG, a partir do Bone Settings:
          - _CTRL do Pelvis (SPINE) -> root.pelvis_CTRL;
          - _CTRL do Spine 1 (o "Belly") -> root.master_CTRL;
          - _CTRL do Root Bone de cada LEG -> o mesmo "Root Parent" que
            o IK daquela perna usa (Player: "Pelvis" -> root.pelvis_CTRL;
            perna da frente de quadrúpede com Root Parent no peito -> o
            peito). Root Parent vazio = segue a hierarquia normal.
        Sem entrada SPINE, Pelvis/Spine 1 caem nos nomes legados
        ("Pelvis"/"Belly") -- dá o mesmo resultado do CTRL_PARENT_OVERRIDES
        antigo. Sem NENHUMA entrada LEG, vale a regra legada L-/R-Thigh."""
        overrides = {}
        pelvis_name = resolve_pelvis_org_name(armature)
        master_source_name = resolve_master_source_org_name(armature)

        pelvis_root = edit_bones.get(BONE_ROOT_PELVIS)
        master_root = edit_bones.get(BONE_ROOT_MASTER)
        if pelvis_root is not None:
            overrides[control_name(armature, pelvis_name, SUFFIX_CTRL)] = pelvis_root
        if master_root is not None and master_source_name != pelvis_name:
            overrides[control_name(armature, master_source_name, SUFFIX_CTRL)] = master_root

        leg_items = [
            it for it in getattr(armature, "hytale_ik_chains", [])
            if it.chain_type == "LEG" and (it.root_bone or "").strip()
        ]
        if leg_items:
            for item in leg_items:
                if not (item.parent_override or "").strip():
                    continue  # sem Root Parent -- coxa segue a hierarquia do modelo
                target = _resolve_parent_override(edit_bones, item.parent_override, armature)
                if target is None:
                    self.report(
                        {"WARNING"},
                        f"Leg '{item.label or item.root_bone}': Root Parent '{item.parent_override}' not found "
                        f"-- '{item.root_bone}{SUFFIX_CTRL}' keeps its normal parent.",
                    )
                    continue
                overrides[control_name(armature, item.root_bone.strip(), SUFFIX_CTRL)] = target
        else:
            for bone_name, parent_name in CTRL_PARENT_OVERRIDES.items():
                if "Thigh" in bone_name and edit_bones.get(parent_name) is not None:
                    overrides[bone_name] = edit_bones.get(parent_name)
        return overrides

    def _apply_ctrl_parent_overrides(self, armature, edit_bones):
        """Força o parent dos _CTRL listados por
        _resolve_ctrl_parent_overrides, sobrescrevendo o que o pipeline
        padrão (espelha a hierarquia ORG) teria escolhido. Roda toda vez
        -- não só quando o bone é criado agora. Pula (com aviso) um
        parent que criaria ciclo (bone apontando pra ele mesmo ou pra um
        descendente dele)."""
        for bone_name, parent in self._resolve_ctrl_parent_overrides(armature, edit_bones).items():
            bone = edit_bones.get(bone_name)
            if bone is None:
                continue
            if parent_would_loop(bone, parent):
                self.report(
                    {"WARNING"},
                    f"Parent '{parent.name}' for '{bone_name}' would create a loop (it's the bone itself or "
                    f"one of its children) -- skipped.",
                )
                continue
            bone.parent = parent
            bone.use_connect = False

    def _reparent_extra_children(self, edit_bones, org, mch, exclude_name=None):
        """Reparenta pro `mch` dado o _CTRL de todo filho ORG "extra" de
        `org` -- attachment e os demais (dedos, sockets, etc.), pra
        qualquer segmento da cadeia, não só a ponta. Sem isso, esses
        bones ficariam "descolados" quando a cadeia vai pra modo IK.
        `exclude_name`: usado pelos segmentos do meio (Arm/Forearm) pra
        excluir o próximo elo da própria cadeia (já tratado à parte).

        Roda toda vez, não só quando o bone é novo. Retorna a lista de
        _CTRL reparentados, pra alimentar
        chains_data["reparented_ctrl_roots"] -- reparentar pro _MCH
        tira esses _CTRL da árvore que o walk de Main/Arm-Leg percorre,
        precisam ser propagados de volta manualmente."""
        reparented = []
        extra_orgs = []
        attachment_org = find_attachment_child(org)
        if attachment_org is not None and attachment_org.name != exclude_name:
            extra_orgs.append(attachment_org)
        for child in find_non_attachment_children(org):
            if child.name == exclude_name:
                continue
            extra_orgs.append(child)
        for extra_org in extra_orgs:
            extra_ctrl = find_layer_bone(edit_bones, extra_org.name, SUFFIX_CTRL)
            if extra_ctrl is None:
                continue
            extra_ctrl.parent = mch
            extra_ctrl.use_connect = False
            reparented.append(extra_ctrl.name)
        return reparented

    @staticmethod
    def _order_top_down(org_bones, org_by_name):
        ordered = []
        visited = set()

        def visit(bone):
            if bone.name in visited:
                return
            visited.add(bone.name)
            ordered.append(bone)
            for child in bone.children:
                if child.name in org_by_name:
                    visit(child)

        roots = [b for b in org_bones if b.parent is None or b.parent.name not in org_by_name]
        for root in roots:
            visit(root)
        for b in org_bones:
            if b.name not in visited:
                ordered.append(b)
        return ordered

    def _build_ik_layer(self, armature, edit_bones, coll_ctrl_ik, coll_mch_ik, resolved_chains, stats, world_down_local):
        """Pra cada cadeia resolvida: um bone `_IK` por segmento (raiz/
        meio com parentesco real espelhando ORG, ou o parent_override
        do item; ponta solta + switch), um bone-ponte `_MCH_IK_Transfer`
        por segmento, e um pole target `_Pole_CTRL`."""
        chains_data = []

        for resolved in resolved_chains:
            chain = resolved["path"]
            item = resolved["item"]
            pole_ref = resolved["pole_ref"]

            tip_index = len(chain) - 1
            tip_org = chain[tip_index]
            # Attachments/dedos precisam seguir o resultado FINAL da
            # ponta (FK ou IK) -- não o ORG puro: anim_importer.py só
            # sabe projetar corretamente parents terminados em "_CTRL"
            # ou "_MCH"; um parent ORG cru cai no caso genérico e a
            # importação de animação sai errada. _MCH dá o mesmo
            # resultado visual e é reconhecido pelo importer.
            tip_mch = edit_bones.get(tip_org.name + SUFFIX_MCH) or tip_org
            reparented_ctrl_roots = self._reparent_extra_children(edit_bones, tip_org, tip_mch)
            attachment_org = find_attachment_child(tip_org)
            attachment_ctrl = find_layer_bone(edit_bones, attachment_org.name, SUFFIX_CTRL) if attachment_org else None

            # Segmentos do meio da cadeia (ex.: Arm/Forearm) têm o
            # mesmo problema/correção da ponta. exclude_name tira o
            # próximo elo da própria cadeia (tratamento dedicado abaixo).
            for mid_index in range(tip_index):
                mid_org = chain[mid_index]
                mid_mch = edit_bones.get(mid_org.name + SUFFIX_MCH)
                if mid_mch is None:
                    continue
                reparented_ctrl_roots.extend(
                    self._reparent_extra_children(
                        edit_bones, mid_org, mid_mch, exclude_name=chain[mid_index + 1].name
                    )
                )

            tip_length = (tip_org.tail - tip_org.head).length
            ik_bones = []

            for i, org in enumerate(chain):
                ik_bone, is_new = create_bone_like(edit_bones, org, control_name(armature, org.name, SUFFIX_IK))
                ik_bone[PROP_SOURCE_ORG] = org.name
                if is_new:
                    if i < tip_index:
                        # Os ORG do Hytale vêm com Y sempre pra cima
                        # (não pro filho na cadeia) -- quebra o solver
                        # de IK. Corrige o tail pro head do próximo bone.
                        ik_bone.tail = chain[i + 1].head.copy()
                    elif attachment_ctrl is not None:
                        # Ponta com socket de referência: tail fica no
                        # HEAD do "<attachment>_CTRL" correspondente.
                        ik_bone.tail = attachment_ctrl.head.copy()
                    elif tip_length > 1e-9:
                        # Sem socket de referência (ex.: pé): aponta pra
                        # baixo (mundo, convertido pro espaço local),
                        # preservando o comprimento original.
                        down = world_down_local if world_down_local.length > 1e-9 else Vector((0.0, 0.0, -1.0))
                        ik_bone.tail = ik_bone.head + down.normalized() * tip_length

                    ik_bone.align_roll(org.z_axis)  # alinha Z do "_IK" ao Z do ORG

                    if i == tip_index:
                        ik_bone.parent = None  # ponta solta -- alvo arrastável + switch
                        ik_bone.use_connect = False
                    elif i == 0:
                        # Todos os _CTRL normais e bones utilitários
                        # root.* já foram criados neste ponto -- seguro
                        # referenciar mesmo que o campo tenha sido
                        # preenchido antes de tudo existir.
                        # Alias primeiro ("Pelvis"/o Pelvis da SPINE ->
                        # root.pelvis_CTRL, mesmo já existindo o ORG),
                        # depois o _CTRL do bone marcado, por último o
                        # nome literal -- ver parent_override_candidates.
                        override_parent = _resolve_parent_override(edit_bones, item.parent_override, armature)
                        loops = override_parent is not None and parent_would_loop(ik_bone, override_parent)
                        if loops:
                            override_parent = None  # aviso de ciclo sai no bloco de correção logo abaixo
                        elif item.parent_override and override_parent is None:
                            self.report(
                                {"WARNING"},
                                f"Parent override '{item.parent_override}' not found for '{ik_bone.name}' -- "
                                f"left unparented.",
                            )
                        ik_bone.parent = override_parent
                        ik_bone.use_connect = False
                    else:
                        prev_ik = ik_bones[i - 1]
                        ik_bone.parent = prev_ik
                        ik_bone.use_connect = bool(org.use_connect and prev_ik is not None)
                    ik_bone[PROP_RIG_LAYER] = "CTRL-IK"
                    stats["ik"] += 1
                coll_ctrl_ik.assign(ik_bone)
                ik_bones.append(ik_bone)

            # Corrige o parent do bone raiz toda vez, não só quando
            # criado -- rigs de uma versão anterior (antes do fix do
            # alias acima) podem ter um "Thigh_IK" apontando pro ORG
            # errado; sem isso, rodar de novo não conserta bones já existentes.
            if ik_bones and item.parent_override:
                override_parent = _resolve_parent_override(edit_bones, item.parent_override, armature)
                if override_parent is not None and parent_would_loop(ik_bones[0], override_parent):
                    self.report(
                        {"WARNING"},
                        f"Parent override '{item.parent_override}' for '{ik_bones[0].name}' would create a "
                        f"loop -- left unparented.",
                    )
                elif override_parent is not None:
                    ik_bones[0].parent = override_parent
                    ik_bones[0].use_connect = False

            for i, org in enumerate(chain):
                bridge, is_new = create_bone_like(edit_bones, org, org.name + SUFFIX_MCH_IK_TRANSFER)
                if is_new:
                    bridge.parent = ik_bones[i]  # parentesco REAL, é o truque do bridge
                    bridge.use_connect = False
                    bridge[PROP_RIG_LAYER] = "MCH-IK"
                    stats["ik_mch"] += 1
                coll_mch_ik.assign(bridge)

            root_org = chain[0]
            pole, is_new_pole = create_bone_like(edit_bones, root_org, control_name(armature, root_org.name, SUFFIX_POLE))
            pole[PROP_SOURCE_ORG] = root_org.name
            if is_new_pole:
                pole.head, pole.tail = self._pole_position(pole_ref, item.pole_distance, item.pole_invert)
                # create_bone_like() copia o roll do root_org (ex.: Thigh) por
                # padrão -- mas o pole não tem relação nenhuma com esse roll
                # (não afeta o IK, que só usa a posição do pole target).
                # Zera pra deixar o bone centralizado/sem torção visual.
                pole.roll = 0.0
                pole.parent = None
                pole[PROP_RIG_LAYER] = "CTRL-IK"
            coll_ctrl_ik.assign(pole)

            # v0.8: bone puramente visual -- parent DIRETO no pole_ref (o
            # próprio ORG, ex.: Forearm/Calf; não no _IK nem no _CTRL
            # dele), esticado (Stretch To, ver _build_pose_constraints)
            # até o "_Pole_CTRL" acabado de criar/reaproveitar acima.
            # head = head do pole_ref (o "cotovelo"/"joelho"); tail =
            # head do pole (só o rest -- Stretch To recalcula a cada
            # frame, então não precisa ficar exato). hide_select=True:
            # 100% controlado pelo constraint, nada pra o usuário posar
            # nele.
            pole_line, is_new_pole_line = create_bone_like(
                edit_bones, pole_ref, control_name(armature, root_org.name, SUFFIX_POLE_LINE)
            )
            pole_line[PROP_SOURCE_ORG] = root_org.name
            if is_new_pole_line:
                pole_line.head = pole_ref.head.copy()
                pole_line.tail = pole.head.copy()
                pole_line.roll = 0.0
                pole_line.parent = pole_ref
                pole_line.use_connect = False
                pole_line[PROP_RIG_LAYER] = "CTRL-IK"
            pole_line.hide_select = True
            coll_ctrl_ik.assign(pole_line)

            chains_data.append(
                {
                    "org_names": [b.name for b in chain],
                    "ik_root": control_name(armature, chain[0].name, SUFFIX_IK),
                    "ik_solver_end": control_name(armature, chain[tip_index - 1].name, SUFFIX_IK),
                    "ik_tip": control_name(armature, chain[tip_index].name, SUFFIX_IK),
                    "pole": pole.name,
                    "pole_line": pole_line.name,
                    "side": item.side,
                    # Root Parent (ex. o ombro) -- lido por
                    # _bone_settings_color_map pra pintar o bone com a
                    # cor do lado desta cadeia.
                    "parent_override": item.parent_override,
                    # Só pra find_shared_pole_angle_preset_warnings checar
                    # se Arm e Leg estão sem querer usando o mesmo
                    # pole_angle_preset_name (indexado só por nome+side,
                    # não por chain_type). Não afeta a resolução do
                    # ângulo, só o aviso.
                    "chain_type": item.chain_type,
                    "pole_angle_mode": item.pole_angle_mode,
                    "pole_angle_preset_name": item.pole_angle_preset_name,
                    "pole_angle_manual": item.pole_angle_manual,
                    "pole_angle_fine_tune": item.pole_angle_fine_tune,
                    "switch_property": switch_property_name(chain[tip_index].name, item.side),
                    # _CTRL reparentados pro _MCH da ponta -- ficam fora
                    # da árvore que _build_main_collections percorre,
                    # precisam ser propagados manualmente.
                    "reparented_ctrl_roots": reparented_ctrl_roots,
                    # "Auto" = deixa a collection default; um nome
                    # redireciona os bones desta cadeia (ver
                    # _apply_bone_collection_overrides).
                    "collection_override": item.collection_override,
                }
            )

        return chains_data

    def _apply_head_follow_parent(self, armature, edit_bones):
        """Decide, em Edit Mode, se o sistema "Head Follow" deve existir
        nesta execução -- lendo o toggle "Head Free/Lock" de qualquer
        entrada HEAD que o tenha ligado.

        Precisa de um único redirect: o Tail do predecessor imediato de
        "Head" (Neck, se existir; Chest, se não) pro Head de "Head" --
        não da cadeia inteira, então "Head Free/Lock" faz esse redirect
        sozinho, sem depender de Continuous Chain configurado.

        Idempotente, roda sempre: se ligado, redireciona o Tail do
        predecessor e deixa Head_CTRL SEM parent nenhum (pronto pra
        _build_head_follow montar os constraints em Pose Mode -- Child
        Of/Copy Location já bastam sozinhos pra seguir `source`, um
        parent aqui duplicaria o movimento quando Origin/master se
        move); se desligado, reseta o Tail/Roll do predecessor pro
        original e garante que Head_CTRL volte pro parent natural (o
        `_CTRL` do pai real do ORG "Head").

        Retorna (bool, str|None): (True, nome do `_CTRL`-fonte) se
        ativo, (False, None) se não.

        TODO (v-futura, documentado a pedido do usuário -- ver o TODO
        maior em bone_settings.py, na definição de
        HytaleIKChainItem.head_follow_enabled, com o plano completo):
        esta função só processa resolve_head_chain_item(armature), ou
        seja, UMA cabeça só (a Main Head). "Head Free/Lock" ligado numa
        entrada HEAD secundária não tem efeito nenhum hoje -- limitação
        conhecida, não bug. Suporte a Head Follow independente por
        cabeça (personagem com 2+ cabeças) exige: iterar toda entrada
        HEAD com head_bone preenchido (não só a Main Head), um
        PROP_HEAD_FOLLOW_SWITCH por cabeça (nome derivado do head_bone,
        não mais uma constante fixa), e _build_head_follow/
        _apply_pole_childof_inverses passando a tratar uma LISTA de
        cabeças em vez de uma só."""
        # resolve_head_chain_item (não só o nome) -- personagem com mais
        # de uma entrada HEAD precisa ler head_follow_enabled da MESMA
        # entrada "principal" que decide head_org/head_ctrl aqui embaixo;
        # antes disso o toggle era checado com any() em TODAS as
        # entradas HEAD só que sempre aplicado na cabeça da PRIMEIRA --
        # bug real: Head Follow ligado numa entrada HEAD secundária
        # redirecionava a cabeça errada.
        head_item = resolve_head_chain_item(armature)
        if head_item is None:
            return False, None
        head_ctrl_name = control_name(armature, head_item.head_bone, SUFFIX_CTRL)
        head_org = edit_bones.get(head_item.head_bone)
        head_ctrl = edit_bones.get(head_ctrl_name)
        if head_org is None or head_ctrl is None or head_org.parent is None:
            return False, None

        source_org = head_org.parent  # EditBone direto -- é o pai real do ORG "Head"
        source_name = control_name(armature, source_org.name, SUFFIX_CTRL)
        source_ctrl = edit_bones.get(source_name)
        if source_ctrl is None:
            return False, None

        enabled = head_item.head_follow_enabled

        if not enabled:
            source_ctrl.tail = source_org.tail.copy()
            source_ctrl.roll = source_org.roll
            head_ctrl.parent = source_ctrl
            head_ctrl.use_connect = False
            return False, None

        # Redireciona o Tail do predecessor pro Head de "Head" -- mesmo
        # truque de _apply_continuous_chain_redirect (align_roll com o
        # eixo Z do PRÓPRIO org do predecessor, não o de "Head").
        source_ctrl.tail = head_org.head.copy()
        source_ctrl.align_roll(source_org.z_axis)

        # SEM parent nenhum (nem Origin_CTRL, nem o natural) -- os
        # constraints de _build_head_follow (Child Of mirando `source`
        # inteiro em switch=1, Copy Location em switch=0) já fazem
        # Head_CTRL seguir `source` inteiramente sozinhos. Parentar em
        # Origin_CTRL (comportamento de antes) duplicava o movimento:
        # `source` já herda a transform de Origin pela própria cadeia de
        # parent do corpo, então mover Origin/master movia a cabeça DUAS
        # vezes -- uma pelo parent direto daqui, outra pelo Child Of
        # herdando de `source`. Bug relatado pelo usuário, corrigido.
        head_ctrl.parent = None
        head_ctrl.use_connect = False
        return True, source_name

    @staticmethod
    def _pole_position(pole_ref, distance, invert):
        """Pole posicionado a partir do bone de referência (pole_ref, ex:
        Forearm/Calf): pega o eixo Z local dele (rest pose, ORG) e
        desloca nesse sentido -- negativo (pra trás, padrão) ou positivo
        (pra frente, se pole_invert estiver marcado)."""
        z_axis = pole_ref.z_axis
        z_axis = z_axis.normalized() if z_axis.length > 1e-9 else Vector((0.0, 0.0, 1.0))

        sign = 1.0 if invert else -1.0
        head = pole_ref.head.copy() + z_axis * (distance * sign)
        tail = head + Vector((0.0, 0.0, distance * 0.2))
        return head, tail

    def _build_main_collections(self, armature, edit_bones):
        """Organização de alto nível: Main + Attachments. Dentro de
        Main: Head/Spine/Body/Arm L/Arm R/Leg L/Leg R/Root (+ o que o
        usuário criar em Collection Settings). Bones de attachment
        nunca entram nessas -- só na Attachments."""
        coll_main = ensure_bone_collection(armature, COLL_MAIN)
        coll_attachments = ensure_bone_collection(armature, COLL_ATTACHMENTS, parent=coll_main)

        coll_head = ensure_bone_collection(armature, COLL_MAIN_HEAD, parent=coll_main)
        coll_spine = ensure_bone_collection(armature, COLL_MAIN_SPINE, parent=coll_main)
        coll_body = ensure_bone_collection(armature, COLL_MAIN_BODY, parent=coll_main)
        coll_arm_l = ensure_bone_collection(armature, COLL_MAIN_ARM_L, parent=coll_main)
        coll_arm_r = ensure_bone_collection(armature, COLL_MAIN_ARM_R, parent=coll_main)
        coll_leg_l = ensure_bone_collection(armature, COLL_MAIN_LEG_L, parent=coll_main)
        coll_leg_r = ensure_bone_collection(armature, COLL_MAIN_LEG_R, parent=coll_main)
        coll_root = ensure_bone_collection(armature, COLL_MAIN_ROOT, parent=coll_main)

        # Main acima de todas as outras collections de nível raiz --
        # melhor esforço: reordena entre elas. Se o Blender não deixar
        # (versão/API diferente), a organização funcional continua
        # correta, só a ordem visual na lista que pode precisar de um
        # arraste manual.
        self._move_collection_to_index(armature, coll_main, 0)

        # Attachments: reúne só os bones _CTRL (FK) cujo nome contenha a
        # dica de attachment -- ORG/MCH/CTRL-IK/MCH-IK do mesmo attachment
        # ficam de fora (o usuário só precisa controlar o CTRL; os outros
        # são mecanismo interno, já ocultos em Internal/*).
        #
        # unassign() explícito nos que NÃO são CTRL: sem isso, um bone que
        # foi parar aqui numa execução ANTIGA (antes desta regra existir,
        # quando QUALQUER camada entrava) fica preso pra sempre -- só
        # parar de adicionar novos não tira quem já está lá. Rigs gerados
        # com uma versão anterior do script podem ter ORG de attachment
        # (ex.: L-Eyebrow-Attachment, sem sufixo nenhum) ainda presos em
        # Attachments; isso limpa isso toda vez que "Create Rig" roda.
        for bone in edit_bones:
            if is_attachment_bone(bone):
                if bone.get(PROP_RIG_LAYER) == "CTRL":
                    coll_attachments.assign(bone)
                else:
                    coll_attachments.unassign(bone)

        def assign_descendants(coll, root_names):
            for root_name in root_names:
                for bone in collect_descendants_inclusive(
                    edit_bones, root_name, exclude_predicate=is_excluded_from_main_collections
                ):
                    coll.assign(bone)

        assign_descendants(coll_head, [resolve_head_ctrl_name(armature)])

        for name in SPINE_COLLECTION_BONES:
            bone = edit_bones.get(name)
            if bone is not None:
                coll_spine.assign(bone)

        for name in BODY_COLLECTION_BONES:
            bone = edit_bones.get(name)
            if bone is not None:
                coll_body.assign(bone)

        for name in ROOT_COLLECTION_BONES:
            bone = edit_bones.get(name)
            if bone is not None:
                coll_root.assign(bone)

        limb_roots = _resolve_main_limb_roots(armature, edit_bones)
        assign_descendants(coll_arm_l, limb_roots[COLL_MAIN_ARM_L])
        assign_descendants(coll_arm_r, limb_roots[COLL_MAIN_ARM_R])
        assign_descendants(coll_leg_l, limb_roots[COLL_MAIN_LEG_L])
        assign_descendants(coll_leg_r, limb_roots[COLL_MAIN_LEG_R])

    _MAIN_LIMB_COLLECTION_NAMES = {COLL_MAIN_ARM_L, COLL_MAIN_ARM_R, COLL_MAIN_LEG_L, COLL_MAIN_LEG_R}

    def _propagate_pole_and_tip_to_main_collections(self, edit_bones, chains_data):
        """Pole target, o "_IK" da ponta e o "_Pole_Line" ficam fora da
        árvore de parent que assign_descendants percorre (soltos, ou
        parentados num ORG) -- nunca alcançados pelo walk que monta Arm
        L/R e Leg L/R. Aqui, pra cada cadeia, descobre em qual
        sub-collection de Main o resto da cadeia já caiu, e replica pro
        pole, pole line, tip e todo _CTRL reparentado pro _MCH da ponta
        (mesmo motivo: fora da árvore normal, só que por reparenting)."""
        for data in chains_data:
            ref_bone = edit_bones.get(data["ik_root"])
            if ref_bone is None:
                continue
            member_colls = [c for c in ref_bone.collections if c.name in self._MAIN_LIMB_COLLECTION_NAMES]
            if not member_colls:
                continue
            for name in (data["pole"], data["pole_line"], data["ik_tip"]):
                bone = edit_bones.get(name)
                if bone is None:
                    continue
                for coll in member_colls:
                    coll.assign(bone)

            for root_name in data.get("reparented_ctrl_roots", ()):
                for bone in collect_descendants_inclusive(
                    edit_bones, root_name, exclude_predicate=is_excluded_from_main_collections
                ):
                    for coll in member_colls:
                        coll.assign(bone)

    @staticmethod
    def _move_collection_to_index(armature, coll, target_index):
        try:
            roots = list(armature.collections)
            current_index = roots.index(coll)
            if current_index != target_index:
                armature.collections.move(current_index, target_index)
        except Exception:
            pass  # cosmético -- não impede o rig de funcionar

    def _move_main_child_before(self, armature, child_name, before_name):
        """Reposiciona a bone collection `child_name` (filha de Main)
        pra ficar logo antes de `before_name` (mesmo parent).

        Usa `child_number` (índice dentro da lista de filhos do
        próprio parent) em vez do array flat do Armature -- que só
        enxerga collections de nível raiz, nunca filhas de Main (bug
        real corrigido: a versão anterior usava esse array flat e
        sempre lançava ValueError em silêncio, a collection nunca saía
        do lugar). Só funciona entre irmãos (mesmo parent).

        Ajuste de direção: setar child_number pra X reposiciona pra
        ficar na posição final X, empurrando o que já estava lá. Se
        `child` já vem antes de `target` (caso normal aqui), o valor
        certo pra terminar imediatamente antes é `target.child_number - 1`
        (a posição de target recua 1 depois que child sai de antes
        dela). Se `child` já vier depois, usa o valor original."""
        child = _find_bone_collection_anywhere(armature, child_name)
        target = _find_bone_collection_anywhere(armature, before_name)
        if child is None or target is None:
            self.report(
                {"WARNING"},
                f"Could not reorder bone collection '{child_name}' before '{before_name}' -- "
                f"'{child_name if child is None else before_name}' not found (purely cosmetic, rig still works).",
            )
            return
        if child.parent != target.parent:
            self.report(
                {"WARNING"},
                f"Could not reorder bone collection '{child_name}' before '{before_name}' -- they aren't "
                f"siblings (same parent collection) (purely cosmetic, rig still works).",
            )
            return
        try:
            current_number = child.child_number
            target_number = target.child_number
            new_number = target_number - 1 if current_number < target_number else target_number
            if current_number != new_number:
                child.child_number = new_number
        except Exception as exc:
            self.report(
                {"WARNING"},
                f"Could not reorder bone collection '{child_name}' before '{before_name}': {exc} "
                f"(purely cosmetic, rig still works).",
            )

    def _apply_bone_collection_overrides(self, armature, edit_bones, chains_data, tail_chains_data=()):
        """Roda depois de _build_main_collections/_build_tail_layer e
        _propagate_pole_and_tip_to_main_collections (que continuam
        responsáveis pelo default de Arm/Leg/Tail/Body/Root) -- aqui
        redireciona quem pediu um collection_override != "", e também
        faz a atribuição inteira de Head/Spine (sem mecanismo de
        default fora daqui)."""

        def _resolve_target(target_name, context_label):
            # Lógica em resolve_collection_override_target (nível de
            # módulo), reaproveitada também por _build_texture_picker.
            target_coll = resolve_collection_override_target(armature, target_name)
            if target_coll is None:
                self.report(
                    {"WARNING"},
                    f"Bone Settings: collection '{target_name}' not found in Collection Settings (may "
                    f"have been deleted/renamed) -- '{context_label}' kept in the default collection instead.",
                )
            return target_coll

        def _redirect(bone, target_coll):
            # Tira só das sub-collections default de Main (Head/Spine/
            # Body/Arm*/Leg*/Root/Tail) -- nunca de Internal/ORG/MCH/CTRL/
            # Attachments, que continuam existindo em paralelo (Main é só
            # organização visual por cima delas, não substitui).
            for coll in list(bone.collections):
                if coll.parent is not None and coll.parent.name == COLL_MAIN and coll.name != target_coll.name:
                    coll.unassign(bone)
            target_coll.assign(bone)

        # --- Arm/Leg (chains_data) ---------------------------------------
        for data in chains_data:
            target_name = (data.get("collection_override") or "").strip()
            if not target_name or target_name == COLLECTION_OVERRIDE_AUTO:
                continue  # Auto -- fica no default que _build_main_collections já montou

            target_coll = _resolve_target(target_name, data.get("ik_root", "?"))
            if target_coll is None:
                continue

            root_name = data.get("ik_root")
            if root_name is not None:
                for bone in collect_descendants_inclusive(
                    edit_bones, root_name, exclude_predicate=is_excluded_from_main_collections
                ):
                    _redirect(bone, target_coll)

            for name in (data.get("pole"), data.get("pole_line"), data.get("ik_tip")):
                bone = edit_bones.get(name) if name else None
                if bone is not None:
                    _redirect(bone, target_coll)

            for reparented_root in data.get("reparented_ctrl_roots", ()):
                for bone in collect_descendants_inclusive(
                    edit_bones, reparented_root, exclude_predicate=is_excluded_from_main_collections
                ):
                    _redirect(bone, target_coll)

        # --- Tail ---
        # Diferente de Arm/Leg, não precisa andar pela hierarquia -- os
        # _CTRL da cauda já estão em "ctrl_names", redireciona por nome.
        for data in tail_chains_data:
            target_name = (data.get("collection_override") or "").strip()
            if not target_name or target_name == COLLECTION_OVERRIDE_AUTO:
                continue  # Auto -- fica em Main/Tail, sem mudança

            target_coll = _resolve_target(target_name, data.get("ctrl_names", ["?"])[0])
            if target_coll is None:
                continue

            for name in data.get("ctrl_names", ()):
                bone = edit_bones.get(name)
                if bone is not None:
                    _redirect(bone, target_coll)

        # --- Head/Spine/Attachments ---
        # Não criam bone (não aparecem em chains_data/tail_chains_data)
        # -- lê direto de armature.hytale_ik_chains. "Auto" aqui quer
        # dizer "assina no default certo pro tipo", não "não faz nada".
        _organizational_defaults = {
            "HEAD": COLL_MAIN_HEAD, "SPINE": COLL_MAIN_SPINE, "ATTACHMENTS": COLL_ATTACHMENTS,
            "TEXTURE_PICKER": COLL_MAIN_TEXTURE_PICKER, "ROOT": COLL_MAIN_ROOT,
        }
        for item in armature.hytale_ik_chains:
            if item.chain_type not in _organizational_defaults:
                continue
            names = _head_spine_bone_names(item)
            if not names:
                continue  # nada configurado ainda -- nada pra fazer

            override = (item.collection_override or "").strip()
            if override and override != COLLECTION_OVERRIDE_AUTO:
                target_coll = _resolve_target(override, item.label or item.chain_type.title())
                if target_coll is None:
                    continue
            else:
                coll_main = ensure_bone_collection(armature, COLL_MAIN)
                target_coll = ensure_bone_collection(
                    armature, _organizational_defaults[item.chain_type], parent=coll_main
                )

            # Os campos guardam o nome do bone ORG -- quem precisa ir
            # pra collection é o _CTRL correspondente, não o ORG cru.
            for name in names:
                ctrl_name = control_name(armature, name, SUFFIX_CTRL)
                bone = edit_bones.get(ctrl_name)
                if bone is None:
                    self.report(
                        {"WARNING"},
                        f"{item.chain_type.title()} '{item.label or '?'}': control bone '{ctrl_name}' not "
                        f"found (expected an ORG bone named '{name}' with a matching '_CTRL') -- skipped.",
                    )
                    continue
                _redirect(bone, target_coll)

            # root.ui/cursor (Texture Picker) só são atribuídos uma vez
            # dentro de _build_texture_picker -- se o usuário trocar a
            # Collection depois de já ter clicado "Create Texture
            # Picker", os dois ficam presos na collection antiga pra
            # sempre. Redireciona aqui também se já existirem (não cria
            # nada novo, só corrige a collection de quem já existe).
            if item.chain_type == "TEXTURE_PICKER" and item.texture_picker_bone:
                for aux_name in (
                    _texture_picker_ui_root_name(item.texture_picker_bone),
                    _texture_picker_cursor_name(item.texture_picker_bone),
                ):
                    aux_bone = edit_bones.get(aux_name)
                    if aux_bone is not None:
                        _redirect(aux_bone, target_coll)

    def _apply_collection_visibility(self, armature):
        """Esconde tudo (Internal e todo o resto), deixando visível só
        Main (+ TODAS as sub-collections aninhadas, recursivamente --
        v0.9.6: Face deixou de ser uma raiz especial (hardcoded/auto-
        criada); qualquer collection do usuário, incluindo uma "Face"
        criada manualmente, já está aninhada em algum lugar dentro de
        Main, então cai nesta mesma recursão, sem precisar de caso
        especial. v0.9.7: Attachments também virou filha de Main -- ver
        _build_main_collections -- então também já cai na recursão
        sozinha; COLL_ATTACHMENTS continua no set inicial só por
        segurança/redundância, não faz diferença no resultado final)."""
        keep_visible = {COLL_MAIN, COLL_ATTACHMENTS}

        def add_children(c):
            keep_visible.add(c.name)
            for child in c.children:
                add_children(child)

        main_coll = _find_bone_collection_anywhere(armature, COLL_MAIN)
        if main_coll is not None:
            add_children(main_coll)

        set_bone_collection_visibility(armature, keep_visible)

    # ------------------------------------------------------------------
    # Etapa 2 (Pose/Object Mode): constraints, custom properties, drivers
    # ------------------------------------------------------------------

    def _warn_shared_pole_angle_presets(self, chains_data):
        """Sanity check, não muda nada no rig -- a detecção em si é
        find_shared_pole_angle_preset_warnings (função de módulo pura,
        reaproveitada por RIG_OT_hytale_validate_rig), este método só
        formata o aviso e chama self.report."""
        for name, types in find_shared_pole_angle_preset_warnings(chains_data):
            self.report(
                {"WARNING"},
                f"Pole angle preset '{name}' is used in PRESET mode by more than one chain type "
                f"({', '.join(types)}) -- they'll share the exact same calibrated angle per side. "
                f"If that's not intentional, give each chain type its own preset name.",
            )

    def _build_pose_constraints(self, obj, chains_data):
        pose_bones = obj.pose.bones
        # Alvo do Child Of "global" dos tips/poles de IK: o _CTRL do Origin
        # principal (Root 1 da entrada ROOT; legado "Origin_CTRL").
        child_of_global_target = resolve_origin_ctrl_name(obj.data)
        armature = obj.data

        marked_names = set()
        for data in chains_data:
            marked_names.update(data["org_names"])

        # Camada base: ORG segue MCH. MCH segue o bridge _MCH_Transfer
        # em World Space (Rotation/Scale sempre; Location sempre que o
        # bone não for conectado ao pai). O bridge é filho real do
        # CTRL com rest limpa -- deixa o CTRL livre pra reposicionar
        # sem que essa cópia em World Space saia torta.
        for bone in armature.bones:
            if PROP_RIG_LAYER in bone.keys():
                continue
            org_name = bone.name
            mch_name = org_name + SUFFIX_MCH
            ctrl_name = control_name(armature, org_name, SUFFIX_CTRL)
            transfer_name = org_name + SUFFIX_MCH_TRANSFER
            if mch_name not in pose_bones or ctrl_name not in pose_bones or transfer_name not in pose_bones:
                continue
            mch_pose = pose_bones[mch_name]

            ensure_copy_set(pose_bones[org_name], obj, mch_name, CONSTRAINT_ORG_TO_MCH)

            fk_rot = ensure_copy_constraint(
                mch_pose, obj, transfer_name, "ROTATION", CONSTRAINT_FK_ROT, space="WORLD"
            )
            fk_scale = ensure_copy_constraint(
                mch_pose, obj, transfer_name, "SCALE", CONSTRAINT_FK_SCALE, space="WORLD"
            )

            is_chain_bone = org_name in marked_names

            fk_loc = None
            if not bone.use_connect:
                fk_loc = ensure_copy_constraint(
                    mch_pose, obj, transfer_name, "LOCATION", CONSTRAINT_FK_LOC, space="WORLD"
                )
            else:
                old_loc = mch_pose.constraints.get(CONSTRAINT_FK_LOC)
                if old_loc is not None:
                    mch_pose.constraints.remove(old_loc)

            if not is_chain_bone:
                fk_rot.driver_remove("influence")
                fk_scale.driver_remove("influence")
                fk_rot.influence = 1.0
                fk_scale.influence = 1.0
                if fk_loc is not None:
                    fk_loc.driver_remove("influence")
                    fk_loc.influence = 1.0

        # Camada de IK, por cadeia.
        self._warn_shared_pole_angle_presets(chains_data)
        for data in chains_data:
            org_names = data["org_names"]
            ik_root = data["ik_root"]
            ik_solver_end = data["ik_solver_end"]
            ik_tip = data["ik_tip"]
            pole_name = data["pole"]
            switch_prop = data["switch_property"]

            if BONE_PROPERTIES in pose_bones:
                ensure_switch_property(pose_bones[BONE_PROPERTIES], switch_prop)
            else:
                self.report(
                    {"WARNING"},
                    f"'{BONE_PROPERTIES}' not found -- skipping FK/IK switch property '{switch_prop}' "
                    f"(and every driver that depends on it) for this chain.",
                )

            chain_count = len(org_names) - 1  # tudo menos a ponta (mão/pé)
            mode = data["pole_angle_mode"]
            if mode == "MANUAL":
                pole_angle = math.radians(data["pole_angle_manual"])
            elif mode == "PRESET":
                # Presets vêm do rig template ativo no Armature. O
                # lookup (rig_template -> pole_angle_presets -> nome ->
                # side) é resolve_pole_angle_preset_degrees (topo deste
                # arquivo), reaproveitado por RIG_OT_hytale_validate_rig
                # pra checar a mesma coisa sem duplicar a lógica.
                rig_template = get_rig_template(getattr(armature, "hytale_active_rig_template", ""))
                preset_deg = resolve_pole_angle_preset_degrees(
                    rig_template, data["pole_angle_preset_name"], data["side"],
                )
                if preset_deg is None:
                    self.report(
                        {"WARNING"},
                        f"No pole angle preset '{data['pole_angle_preset_name']}' for side '{data['side']}' "
                        f"in the active rig template -- falling back to Auto for '{pole_name}'.",
                    )
                    pole_angle = -compute_pole_angle(obj, ik_root, pole_name) + math.radians(
                        data["pole_angle_fine_tune"]
                    )
                else:
                    # + delta de compensação (0.0 se _apply_ik_joint_fixes
                    # não mexeu nesta cadeia).
                    pole_angle = math.radians(preset_deg) + data.get("pole_angle_joint_fix_delta", 0.0)
            else:
                # Sinal invertido: correção empírica (braço e perna
                # precisavam do sinal oposto ao que a fórmula portada
                # calcula).
                pole_angle = -compute_pole_angle(obj, ik_root, pole_name) + math.radians(
                    data["pole_angle_fine_tune"]
                )
            ensure_ik_constraint(pose_bones[ik_solver_end], obj, ik_tip, pole_name, chain_count, pole_angle)

            # Child Of no Origin_CTRL, na ponta da cadeia -- ativo por
            # padrão (influência 1.0), diferente do "Child Of_global"
            # do pole abaixo (que começa em 0). Set Inverse é aplicado
            # depois, em _apply_pole_childof_inverses.
            if child_of_global_target in pose_bones:
                ensure_child_of_constraint(
                    pose_bones[ik_tip], obj, child_of_global_target, CONSTRAINT_CHILD_OF_GLOBAL, 1.0
                )
            else:
                self.report(
                    {"WARNING"},
                    f"'{child_of_global_target}' not found -- skipping {CONSTRAINT_CHILD_OF_GLOBAL} on '{ik_tip}'.",
                )

            # Pole target: dois Child Of -- "local" segue a ponta da
            # própria cadeia (mão/pé), "global" fica preso no
            # CHILD_OF_GLOBAL_TARGET (Origin_CTRL). Só um fica ativo por
            # padrão (local); o outro fica disponível com influência 0.
            if pole_name in pose_bones:
                pole_pose = pose_bones[pole_name]
                ensure_child_of_constraint(pole_pose, obj, ik_tip, CONSTRAINT_CHILD_OF_LOCAL, 1.0)

                if child_of_global_target in pose_bones:
                    ensure_child_of_constraint(
                        pole_pose, obj, child_of_global_target, CONSTRAINT_CHILD_OF_GLOBAL, 0.0
                    )
                else:
                    self.report(
                        {"WARNING"},
                        f"'{child_of_global_target}' not found -- skipping {CONSTRAINT_CHILD_OF_GLOBAL} on "
                        f"'{pole_name}'.",
                    )

            # "_Pole_Line" -- Stretch To simples, sempre mirando no
            # "_Pole_CTRL" desta mesma cadeia/lado. 100% visual.
            pole_line_name = data.get("pole_line")
            if pole_line_name and pole_line_name in pose_bones and pole_name in pose_bones:
                ensure_stretch_to_constraint(
                    pose_bones[pole_line_name], obj, pole_name, CONSTRAINT_POLE_LINE_STRETCH
                )

            for org_name in org_names:
                mch_name = org_name + SUFFIX_MCH
                bridge_name = org_name + SUFFIX_MCH_IK_TRANSFER
                if mch_name not in pose_bones:
                    continue
                mch_pose = pose_bones[mch_name]

                fk_rot = mch_pose.constraints.get(CONSTRAINT_FK_ROT)
                fk_scale = mch_pose.constraints.get(CONSTRAINT_FK_SCALE)
                fk_loc = mch_pose.constraints.get(CONSTRAINT_FK_LOC)  # None se o bone for conectado ao pai
                if fk_rot is None or fk_scale is None:
                    continue

                # IK_CopyRotation/IK_CopyScale em World Space -- miram
                # no bridge (_MCH_IK_Transfer): mesma rest orientation
                # do MCH, garantindo que a cópia não saia invertida.
                ik_rot = ensure_copy_constraint(
                    mch_pose, obj, bridge_name, "ROTATION", CONSTRAINT_IK_ROT, space="WORLD"
                )
                ik_scale = ensure_copy_constraint(
                    mch_pose, obj, bridge_name, "SCALE", CONSTRAINT_IK_SCALE, space="WORLD"
                )

                add_switch_driver(fk_rot, obj, BONE_PROPERTIES, switch_prop, expression="1 - switch")
                add_switch_driver(ik_rot, obj, BONE_PROPERTIES, switch_prop, expression="switch")
                add_switch_driver(fk_scale, obj, BONE_PROPERTIES, switch_prop, expression="1 - switch")
                add_switch_driver(ik_scale, obj, BONE_PROPERTIES, switch_prop, expression="switch")
                if fk_loc is not None:
                    add_switch_driver(fk_loc, obj, BONE_PROPERTIES, switch_prop, expression="1 - switch")

                # IK_CopyLocation -- SEMPRE no primeiro bone da cadeia (Arm e
                # Leg), par do FK_CopyLocation acima. Sem ele, no modo IK o MCH
                # da raiz pegaria a posição do pai dele na hierarquia do
                # MODELO, enquanto o _IK segue o Root Parent -- se os dois
                # forem bones diferentes (ex. Root Parent = Pelvis da Spine ->
                # root.pelvis_CTRL, mas a coxa é filha de "body" no modelo),
                # mover o Root Parent desencaixa a perna/braço inteiro do IK.
                # Quando os dois coincidem, a cópia dá a mesma posição (no-op).
                # Os outros bones da cadeia herdam a posição do MCH anterior.
                # Raiz "connected" ao pai (fk_loc None) não tem posição livre
                # pra copiar -- fica sem, igual ao FK.
                if org_name == org_names[0] and fk_loc is not None:
                    ik_loc = ensure_copy_constraint(
                        mch_pose, obj, bridge_name, "LOCATION", CONSTRAINT_IK_LOC, space="WORLD"
                    )
                    add_switch_driver(ik_loc, obj, BONE_PROPERTIES, switch_prop, expression="switch")

    def _build_spine_follow(self, obj):
        """Os _CTRL de Spine 1..N (entrada SPINE do Bone Settings, acima do
        Pelvis -- no Player, Belly_CTRL e Chest_CTRL) seguem parcialmente
        o root.spine_CTRL via Copy Transforms (Local Space), influência
        fixa por posição (SPINE_FOLLOW_INFLUENCES: 0.5, 0.63, 0.76,
        0.89). Sem entrada SPINE, os nomes legados Belly/Chest. mix_mode
        = 'AFTER_FULL' (não o padrão 'REPLACE'): REPLACE interpolaria a
        pose já calculada (ex. de uma animação importada) EM DIREÇÃO à
        pose do root.spine_CTRL, puxando de volta pro repouso mesmo sem
        o animador pedir. Com AFTER_FULL, a pose calculada é aplicada
        primeiro e o root.spine_CTRL só soma um ajuste por cima.

        Bone que tinha Spine Follow de uma geração anterior e não está
        mais na lista (Spine trocada no Bone Settings) perde o constraint."""
        pose_bones = obj.pose.bones
        if SPINE_FOLLOW_TARGET not in pose_bones:
            self.report(
                {"WARNING"}, f"'{SPINE_FOLLOW_TARGET}' not found -- skipping spine-follow constraints."
            )
            return

        segment_names = resolve_spine_segment_org_names(obj.data)
        followers = {}
        for index, org_name in enumerate(segment_names):
            influence = SPINE_FOLLOW_INFLUENCES[min(index, len(SPINE_FOLLOW_INFLUENCES) - 1)]
            followers[control_name(obj.data, org_name, SUFFIX_CTRL)] = influence

        pelvis_ctrl_name = control_name(obj.data, resolve_pelvis_org_name(obj.data), SUFFIX_CTRL)
        followers.pop(pelvis_ctrl_name, None)  # Pelvis nunca segue o root.spine_CTRL

        for pb in pose_bones:
            if pb.name in followers:
                continue
            stale = pb.constraints.get(CONSTRAINT_SPINE_FOLLOW)
            if stale is not None:
                pb.constraints.remove(stale)

        for bone_name, influence in followers.items():
            if bone_name not in pose_bones:
                self.report({"WARNING"}, f"'{bone_name}' not found -- skipping spine-follow.")
                continue
            pb = pose_bones[bone_name]
            con = pb.constraints.get(CONSTRAINT_SPINE_FOLLOW)
            if con is None:
                con = pb.constraints.new("COPY_TRANSFORMS")
                con.name = CONSTRAINT_SPINE_FOLLOW
            con.target = obj
            con.subtarget = SPINE_FOLLOW_TARGET
            con.target_space = "LOCAL"
            con.owner_space = "LOCAL"
            con.mix_mode = "AFTER_FULL"
            con.driver_remove("influence")
            con.influence = influence

    def _build_head_follow(self, obj, active, source):
        """`active`/`source` já foram decididos em Edit Mode por
        _apply_head_follow_parent -- esta função só constrói (ou limpa)
        os constraints de acordo, sem recalcular geometria.

        Quando ativo (Head_CTRL já reparentado pro Origin_CTRL): dois
        constraints com papéis complementares, cada um dono da posição
        num estado do switch (nunca os dois disputando ao mesmo tempo,
        o que causava o bug de rotação local quando o Location do
        Child Of ficava desligado):
          1. CONSTRAINT_HEAD_FOLLOW_ROT (Child Of, Location+Rotation+
             Scale todos ligados) -- influência ligada a
             PROP_HEAD_FOLLOW_SWITCH, expression "switch" direta:
             switch=1 (default) segue posição/rotação/escala do
             `source` inteiro.
          2. CONSTRAINT_HEAD_FOLLOW_LOC (Copy Location, World Space,
             mira o TAIL do `source`) -- influência ligada ao mesmo
             switch, expression "not switch": só assume a posição
             quando o Child Of solta (switch=0), pra cabeça não ficar
             "flutuando" longe do source com a rotação livre.

        Ordem no stack importa: o Child Of (#1) precisa vir antes do
        Copy Location (#2), senão a cabeça aparece fora do lugar. Como
        ensure_*_constraint só reaproveita um constraint já existente
        pelo nome (não reordena sozinho), o reorder explícito no fim
        roda toda vez, idempotente -- corrige também um rig gerado com
        a ordem antiga.

        Quando inativo: limpa qualquer resquício de uma execução
        anterior (constraints + custom property) -- senão ficariam
        "órfãos", mirando um `source` que não corresponde mais.

        Set Inverse do Child Of acontece à parte, em
        _apply_pole_childof_inverses."""
        pose_bones = obj.pose.bones
        head_ctrl_name = resolve_head_ctrl_name(obj.data)
        if head_ctrl_name not in pose_bones:
            return False
        head_pose = pose_bones[head_ctrl_name]

        if not active or source is None or source not in pose_bones:
            # Limpeza idempotente -- ver docstring acima.
            for cname in (CONSTRAINT_HEAD_FOLLOW_ROT, CONSTRAINT_HEAD_FOLLOW_LOC):
                con = head_pose.constraints.get(cname)
                if con is not None:
                    head_pose.constraints.remove(con)
            if BONE_PROPERTIES in pose_bones:
                props_bone = pose_bones[BONE_PROPERTIES]
                if PROP_HEAD_FOLLOW_SWITCH in props_bone.keys():
                    del props_bone[PROP_HEAD_FOLLOW_SWITCH]
            return False

        if BONE_PROPERTIES not in pose_bones:
            self.report(
                {"WARNING"},
                f"'{BONE_PROPERTIES}' not found -- skipping Head Follow switch property "
                f"'{PROP_HEAD_FOLLOW_SWITCH}' (and its driver).",
            )
            return False

        ensure_switch_property(
            pose_bones[BONE_PROPERTIES],
            PROP_HEAD_FOLLOW_SWITCH,
            description=tr("rigger.runtime.head_follow_switch_description", get_language(bpy.context)).format(
                source=source
            ),
            default_value=1,
        )

        # Child Of primeiro -- ordem importa (ver docstring).
        rot_con = ensure_child_of_constraint(head_pose, obj, source, CONSTRAINT_HEAD_FOLLOW_ROT, 1.0)
        rot_con.use_location_x = rot_con.use_location_y = rot_con.use_location_z = True
        rot_con.use_rotation_x = rot_con.use_rotation_y = rot_con.use_rotation_z = True
        rot_con.use_scale_x = rot_con.use_scale_y = rot_con.use_scale_z = True
        add_switch_driver(rot_con, obj, BONE_PROPERTIES, PROP_HEAD_FOLLOW_SWITCH, expression="switch")

        loc_con = ensure_copy_constraint(
            head_pose, obj, source, "LOCATION", CONSTRAINT_HEAD_FOLLOW_LOC,
            space="WORLD", head_tail=HEAD_FOLLOW_LOC_HEAD_TAIL,
        )
        add_switch_driver(loc_con, obj, BONE_PROPERTIES, PROP_HEAD_FOLLOW_SWITCH, expression="not switch")

        # Reorder idempotente -- corrige também um rig gerado antes
        # desta correção, com o Copy Location antes do Child Of no stack.
        rot_index = head_pose.constraints.find(CONSTRAINT_HEAD_FOLLOW_ROT)
        loc_index = head_pose.constraints.find(CONSTRAINT_HEAD_FOLLOW_LOC)
        if rot_index != -1 and loc_index != -1 and loc_index < rot_index:
            head_pose.constraints.move(loc_index, rot_index)

        return True


