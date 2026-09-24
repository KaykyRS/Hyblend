"""anim_tools.py -- Auxiliares de Animação (aba "Animation" do N-Panel).

Não desenha nada -- só registra os operadores (e funções de leitura
pura) que a aba "Animation" do interface.py usa.

Cobre: FK/IK switch cru por índice de cadeia (ANIM_OT_hytale_set_fk_ik)
e "Snap FK/IK" que iguala a pose do lado oposto ao selecionado antes de
trocar (ANIM_OT_hytale_snap_selected, ver identify_chain_from_bone/
snap_chain_pose); "Head Free/Lock" (mesmo espírito cru, sem Snap
equivalente -- Head_CTRL não tem duas poses paralelas pra igualar);
ANIM_OT_hytale_keyframe_switch, que insere keyframe na custom property
crua por trás dos dois switches acima -- necessário porque os botões de
troca são operadores (nunca keyframeable pelo Blender), não
`layout.prop()`.

CAVEAT -- Pole Local/Global: o pole target tem dois Child Of no rig
("Local" mirando a ponta da cadeia, ativo por padrão; "Global" no
Origin_CTRL, influência 0), mas nenhum tem switch pra trocar entre eles
hoje. snap_chain_pose() calcula a matrix corrigida pra qualquer Child
Of ativa (via _snap_matrix_through_constraints), então funciona
independente de qual estiver ativa.

Visibilidade das Bone Collections é lida/escrita via
armature.collections_all (API nativa, plana) -- não precisa importar
nomes de collection de rigger/constants.py, recebe o nome já pronto de
quem desenha (interface.py)."""

from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator
from mathutils import Vector

from ..common import is_active_armature
from ..translations import localized_props, register_localized_class, tooltip, tr, unregister_localized_class
from ..rigger import (
    BONE_PROPERTIES,
    CONSTRAINT_CHILD_OF_GLOBAL,
    CONSTRAINT_CHILD_OF_LOCAL,
    PROP_HEAD_FOLLOW_SWITCH,
    SUFFIX_CTRL,
    SUFFIX_IK,
    SUFFIX_MCH,
    SUFFIX_MCH_IK_TRANSFER,
    SUFFIX_POLE,
    control_name,
    find_org_path,
    switch_property_name,
)


def _redraw_all_areas(context):
    """Força redraw de toda área/janela -- escrever a custom property
    recalcula o driver na hora, mas o Blender não redesenha a viewport
    sozinho por causa disso."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


# --- FK/IK Switch + Snap, por cadeia (armature.hytale_ik_chains) ---


def get_fk_ik_state(obj, item):
    """Leitura pura: 0 (FK), 1 (IK), ou None se esse switch ainda não
    existe (chain_type CHAIN, rig não gerado, ou entrada nova). Usada
    pelo interface.py só pra saber qual botão desenhar destacado."""
    if item.chain_type == "CHAIN":
        return None
    pose = obj.pose
    if pose is None:
        return None
    props_bone = pose.bones.get(BONE_PROPERTIES)
    if props_bone is None:
        return None
    prop_name = switch_property_name(item.tip_bone, item.side)
    value = props_bone.get(prop_name)
    if value is None:
        return None
    return 1 if value else 0


def get_head_follow_state(obj):
    """Leitura pura, mesmo espírito de get_fk_ik_state pro switch único
    "Head Free/Lock" (só existe um Head_CTRL no rig). 1 (Lock) ou 0
    (Free), ou None se o switch ainda não existe."""
    pose = obj.pose
    if pose is None:
        return None
    props_bone = pose.bones.get(BONE_PROPERTIES)
    if props_bone is None:
        return None
    value = props_bone.get(PROP_HEAD_FOLLOW_SWITCH)
    if value is None:
        return None
    return 1 if value else 0


def _snap_matrix_through_constraints(context, pose_bone, target_matrix, constraint_names):
    """Escreve `target_matrix` em `pose_bone.matrix` compensando uma
    Child Of ativa (`constraint_names`, por nome -- a primeira com
    influência > 0 e subtarget válido é usada).

    `pose_bone.matrix = valor` sozinho não é "ciente" de constraints:
    calcula matrix_basis assumindo que nada mais vai mexer no bone
    depois, mas a Child Of roda de novo assim que o depsgraph reavalia.

    Fórmula da Child Of (com Set Inverse aplicado):
        final = target.matrix @ con.inverse_matrix @ rest_matrix @ matrix_basis
    Queremos final == target_matrix. Isolando o valor a escrever pra que,
    depois da Child Of rodar em cima, o resultado bata:
        X = (target.matrix @ con.inverse_matrix).inverted() @ target_matrix
    Sem precisar desativar/reativar a constraint -- escreve direto, já compensado."""
    active_con = None
    for name in constraint_names:
        con = pose_bone.constraints.get(name)
        if con is not None and con.type == "CHILD_OF" and not con.mute and con.influence > 0.0 and con.subtarget:
            active_con = con
            break  # as duas (Local/Global) nunca deveriam estar ativas ao mesmo tempo

    if active_con is None:
        pose_bone.matrix = target_matrix
        return

    target_pb = pose_bone.id_data.pose.bones.get(active_con.subtarget)
    if target_pb is None:
        pose_bone.matrix = target_matrix
        return

    pose_bone.matrix = (target_pb.matrix @ active_con.inverse_matrix).inverted() @ target_matrix
    context.view_layer.update()


def snap_chain_pose(context, obj, item, target_mode):
    """Iguala a pose dos controles do modo de destino (target_mode) à
    pose atualmente visível da cadeia, pra trocar o switch sem "pulo".
    Não mexe no switch em si -- ver ANIM_OT_hytale_set_fk_ik.

    A leitura é sempre a mesma, não importa o modo atual: `_MCH` de
    cada segmento ORG é a única fonte de verdade da pose visível (é
    quem recebe o blend das duas camadas via driver) -- não precisa
    saber em qual modo a cadeia está agora.

    target_mode == "FK": copia matrix (armature space) de cada
    `<org>_MCH` pro `<org>_CTRL`, raiz->ponta, com view_layer.update()
    entre cada um (o próximo _CTRL é filho deste, precisa do valor novo
    do pai já calculado).

    target_mode == "IK": só 2 bones são realmente controláveis --
      1. `<tip>_IK` recebe o matrix de `<tip>_MCH`, compensado por um
         offset fixo de rest (a ponta foi reorientada na criação do
         rig -- ver comentário no bloco IK abaixo).
      2. O pole target é reposicionado com a mesma fórmula que
         _pole_position usa na criação, só que lendo o eixo Z da pose
         atual (via `<pole_ref>_MCH.matrix`) em vez do rest.
    O alvo IK e o pole já têm Child Of ativas por padrão -- as duas
    escritas passam por _snap_matrix_through_constraints.

    Retorna (True, None) ou (False, "motivo") se algum bone necessário
    não existir."""
    pose_bones = obj.pose.bones
    bones = obj.data.bones

    root_bone = bones.get(item.root_bone)
    if root_bone is None:
        return False, f"root bone '{item.root_bone}' not found"
    path = find_org_path(root_bone, item.tip_bone)
    if not path:
        return False, f"no bone path from '{item.root_bone}' to '{item.tip_bone}'"

    if target_mode == "FK":
        for org_bone in path:
            mch_pb = pose_bones.get(org_bone.name + SUFFIX_MCH)
            ctrl_pb = pose_bones.get(control_name(obj.data, org_bone.name, SUFFIX_CTRL))
            if mch_pb is None or ctrl_pb is None:
                continue  # bone sem MCH/CTRL (ex. attachment) -- pula, não é erro
            ctrl_pb.matrix = mch_pb.matrix.copy()
            context.view_layer.update()
        return True, None

    if target_mode == "IK":
        tip_org = path[-1]
        tip_mch_pb = pose_bones.get(tip_org.name + SUFFIX_MCH)
        ik_tip_name = control_name(obj.data, tip_org.name, SUFFIX_IK)
        ik_tip_pb = pose_bones.get(ik_tip_name)
        ik_tip_bone = bones.get(ik_tip_name)
        bridge_bone = bones.get(tip_org.name + SUFFIX_MCH_IK_TRANSFER)
        if tip_mch_pb is None or ik_tip_pb is None or ik_tip_bone is None or bridge_bone is None:
            return False, f"'{tip_org.name}{SUFFIX_MCH}'/'{ik_tip_name}' bones not found"

        # O `_IK` da ponta foi reorientado na criação do rig (rest
        # diferente do bridge `_MCH_IK_Transfer`, que mantém a rest do
        # ORG intocada). Copiar tip_mch.matrix direto ignoraria essa
        # diferença -- ao entrar em IK o Blender aplicaria o mesmo
        # offset de novo (via bridge) em cima de um valor já sem
        # compensação, e a mão sairia torta.
        #
        # offset = rest do `_IK` pra rest do bridge (armature space).
        # Com bridge.matrix (mundo) = ik_tip.matrix (mundo) @ offset, e
        # querendo bridge.matrix == tip_mch.matrix, resolvendo pra ik_tip:
        #     ik_tip.matrix = tip_mch.matrix @ offset.inverted()
        offset = ik_tip_bone.matrix_local.inverted() @ bridge_bone.matrix_local
        _snap_matrix_through_constraints(
            context, ik_tip_pb, tip_mch_pb.matrix @ offset.inverted(), [CONSTRAINT_CHILD_OF_GLOBAL]
        )

        # Necessário antes de mexer no pole: ele tem Child Of mirando
        # neste mesmo ik_tip, senão resolveria com o valor pré-snap.
        context.view_layer.update()

        pole_ref_name = item.pole_bone or path[len(path) // 2].name
        pole_ref_mch_pb = pose_bones.get(pole_ref_name + SUFFIX_MCH)
        pole_pb = pose_bones.get(control_name(obj.data, path[0].name, SUFFIX_POLE))
        if pole_ref_mch_pb is not None and pole_pb is not None:
            ref_matrix = pole_ref_mch_pb.matrix
            z_axis = ref_matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))
            z_axis = z_axis.normalized() if z_axis.length > 1e-9 else Vector((0.0, 0.0, 1.0))
            sign = 1.0 if item.pole_invert else -1.0
            target_head = ref_matrix.translation + z_axis * (item.pole_distance * sign)

            new_matrix = pole_pb.matrix.copy()
            new_matrix.translation = target_head
            _snap_matrix_through_constraints(
                context, pole_pb, new_matrix, [CONSTRAINT_CHILD_OF_LOCAL, CONSTRAINT_CHILD_OF_GLOBAL]
            )
        # Sem pole_ref/pole bone -- não é fatal (o alvo IK já foi
        # posicionado); só o ângulo do cotovelo/joelho pode não bater perfeitamente.

        context.view_layer.update()
        return True, None

    return False, f"unknown target_mode '{target_mode}'"


def _resolve_switch_prop(obj, item):
    """Acha (props_bone, prop_name) da custom property de FK/IK switch
    desta cadeia, ou (None, None, "motivo") se não existir ainda.
    Compartilhado por ANIM_OT_hytale_set_fk_ik e
    ANIM_OT_hytale_snap_selected."""
    props_bone = obj.pose.bones.get(BONE_PROPERTIES)
    if props_bone is None:
        return None, None, "rig not generated yet -- there's no FK/IK switch to set"
    prop_name = switch_property_name(item.tip_bone, item.side)
    if prop_name not in props_bone.keys():
        return None, None, (
            f"'{prop_name}' not found on the {BONE_PROPERTIES} bone -- generate/regenerate the rig first "
            "(this chain may have been added to the list after the last 'Create Rig')"
        )
    return props_bone, prop_name, None


def _write_fk_ik_switch(context, obj, props_bone, prop_name, mode):
    """Escreve 0/1 na custom property já resolvida e força o
    recálculo/redraw."""
    props_bone[prop_name] = 1 if mode == "IK" else 0
    obj.update_tag()
    context.view_layer.update()
    _redraw_all_areas(context)


def _set_fk_ik_props(lang):
    return {
        "chain_index": IntProperty(description=tr("anim_tools.prop.set_fk_ik_chain_index", lang)),
        "mode": EnumProperty(items=[("FK", "FK", ""), ("IK", "IK", "")]),
    }


@localized_props(_set_fk_ik_props)
class ANIM_OT_hytale_set_fk_ik(Operator):
    """Troca a cadeia (por índice) pra FK ou IK -- só a influência
    (custom property no bone PROPERTIES). Não iguala a pose -- isso é
    ANIM_OT_hytale_snap_selected, separado de propósito."""

    bl_idname = "pose.hytale_set_fk_ik"
    bl_label = "Set FK/IK"
    description = tooltip("anim_tools.tooltip.set_fk_ik")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and obj.pose is not None

    def execute(self, context):
        obj = context.active_object
        armature = obj.data
        chains = armature.hytale_ik_chains
        if not (0 <= self.chain_index < len(chains)):
            self.report({"WARNING"}, "Invalid chain index.")
            return {"CANCELLED"}

        item = chains[self.chain_index]
        if item.chain_type == "CHAIN":
            self.report({"WARNING"}, "Chain entries don't have an FK/IK switch.")
            return {"CANCELLED"}

        props_bone, prop_name, reason = _resolve_switch_prop(obj, item)
        if props_bone is None:
            self.report({"WARNING"}, reason)
            return {"CANCELLED"}

        _write_fk_ik_switch(context, obj, props_bone, prop_name, self.mode)
        return {"FINISHED"}


class ANIM_OT_hytale_set_head_follow(Operator):
    """Troca o switch único "Head Free/Lock" -- só a custom property,
    mesmo espírito cru de ANIM_OT_hytale_set_fk_ik."""

    bl_idname = "pose.hytale_set_head_follow"
    bl_label = "Set Head Free/Lock"
    description = tooltip("anim_tools.tooltip.set_head_follow")
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(items=[("FREE", "Free", ""), ("LOCK", "Lock", "")])

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and obj.pose is not None

    def execute(self, context):
        obj = context.active_object
        props_bone = obj.pose.bones.get(BONE_PROPERTIES)
        if props_bone is None or PROP_HEAD_FOLLOW_SWITCH not in props_bone.keys():
            self.report(
                {"WARNING"},
                f"'{PROP_HEAD_FOLLOW_SWITCH}' not found on the {BONE_PROPERTIES} bone -- enable 'Head "
                "Free/Lock' on the HEAD entry (Bone Settings) and run 'Create Rig' first.",
            )
            return {"CANCELLED"}

        props_bone[PROP_HEAD_FOLLOW_SWITCH] = 1 if self.mode == "LOCK" else 0
        obj.update_tag()
        context.view_layer.update()
        _redraw_all_areas(context)
        return {"FINISHED"}


def _keyframe_switch_props(lang):
    return {
        "switch": EnumProperty(items=[("FK_IK", "FK/IK", ""), ("HEAD_FOLLOW", "Head Follow", "")]),
        "chain_index": IntProperty(
            default=-1, description=tr("anim_tools.prop.keyframe_switch_chain_index", lang)
        ),
    }


@localized_props(_keyframe_switch_props)
class ANIM_OT_hytale_keyframe_switch(Operator):
    """Insere um keyframe, no frame atual, no valor cru (0/1) por trás
    de um switch FK/IK (por índice) ou do Head Free/Lock -- reaproveita
    _resolve_switch_prop pra achar a mesma property que os botões de
    troca leem/escrevem."""

    bl_idname = "pose.hytale_keyframe_switch"
    bl_label = "Insert Switch Keyframe"
    description = tooltip("anim_tools.tooltip.keyframe_switch")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and obj.pose is not None

    def execute(self, context):
        obj = context.active_object

        if self.switch == "FK_IK":
            chains = obj.data.hytale_ik_chains
            if not (0 <= self.chain_index < len(chains)):
                self.report({"WARNING"}, "Invalid chain index.")
                return {"CANCELLED"}
            props_bone, prop_name, reason = _resolve_switch_prop(obj, chains[self.chain_index])
            if props_bone is None:
                self.report({"WARNING"}, reason)
                return {"CANCELLED"}
        else:
            props_bone = obj.pose.bones.get(BONE_PROPERTIES)
            prop_name = PROP_HEAD_FOLLOW_SWITCH
            if props_bone is None or prop_name not in props_bone.keys():
                self.report(
                    {"WARNING"},
                    f"'{prop_name}' not found on the {BONE_PROPERTIES} bone -- enable 'Head Free/Lock' "
                    "on the HEAD entry (Bone Settings) and run 'Create Rig' first.",
                )
                return {"CANCELLED"}

        # Sintaxe padrão do Blender pra apontar uma custom (ID)
        # property (mesma de "Copy Data Path" no painel Item).
        try:
            props_bone.keyframe_insert(data_path=f'["{prop_name}"]', frame=context.scene.frame_current)
        except TypeError as exc:
            self.report({"ERROR"}, f"Couldn't insert keyframe for '{prop_name}': {exc}")
            return {"CANCELLED"}

        _redraw_all_areas(context)
        self.report({"INFO"}, f"Keyframed '{prop_name}' at frame {context.scene.frame_current}.")
        return {"FINISHED"}


def identify_chain_from_bone(obj, bone_name):
    """Dado o nome de um bone, acha em qual cadeia ARM/LEG ele
    participa e de qual lado (FK ou IK) -- olhando os bones reais (via
    find_org_path), não o nome cru: cobre CTRL de qualquer segmento, o
    `_IK` da ponta e o Pole Target. Retorna (index, item, side) ou
    (None, None, None) se não pertencer a nenhuma cadeia.

    `side` é o lado onde o bone selecionado está agora --
    ANIM_OT_hytale_snap_selected usa o lado oposto como target_mode."""
    armature = obj.data
    bones = armature.bones
    for index, item in enumerate(armature.hytale_ik_chains):
        if item.chain_type == "CHAIN" or not item.root_bone or not item.tip_bone:
            continue
        root_bone = bones.get(item.root_bone)
        if root_bone is None:
            continue
        path = find_org_path(root_bone, item.tip_bone)
        if not path:
            continue

        if bone_name == control_name(armature, path[0].name, SUFFIX_POLE):
            return index, item, "IK"
        if bone_name == control_name(armature, path[-1].name, SUFFIX_IK):
            return index, item, "IK"
        for org_bone in path:
            if bone_name == control_name(armature, org_bone.name, SUFFIX_CTRL):
                return index, item, "FK"
    return None, None, None


class ANIM_OT_hytale_snap_selected(Operator):
    """Snap + Switch baseado no bone selecionado: descobre a cadeia e
    de que lado ele está (ver identify_chain_from_bone), iguala a pose
    do lado oposto e já troca o switch pra esse lado -- ex.: seleciona
    um _CTRL (FK) -> iguala o IK e troca pra IK.

    Diferente de ANIM_OT_hytale_set_fk_ik (só troca a influência): este
    faz igualar + trocar de uma vez, pra uma cadeia (a do bone selecionado)."""

    bl_idname = "pose.hytale_snap_fk_ik_selected"
    bl_label = "Snap FK/IK"
    description = tooltip("anim_tools.tooltip.snap_selected")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "ARMATURE"
            and obj.pose is not None
            and context.active_pose_bone is not None
        )

    def execute(self, context):
        obj = context.active_object
        active_bone = context.active_pose_bone
        index, item, side = identify_chain_from_bone(obj, active_bone.name)
        if item is None:
            self.report(
                {"WARNING"},
                f"'{active_bone.name}' doesn't belong to any Arm/Leg chain -- select a chain's FK "
                "control, IK target, or Pole Target first.",
            )
            return {"CANCELLED"}

        props_bone, prop_name, reason = _resolve_switch_prop(obj, item)
        if props_bone is None:
            self.report({"WARNING"}, reason)
            return {"CANCELLED"}

        target_mode = "FK" if side == "IK" else "IK"
        ok, reason = snap_chain_pose(context, obj, item, target_mode)
        if not ok:
            self.report({"WARNING"}, f"Snap failed ({reason}) -- switching without matching the pose.")

        _write_fk_ik_switch(context, obj, props_bone, prop_name, target_mode)
        self.report({"INFO"}, f"Snapped and switched '{item.label or item.root_bone}' to {target_mode}.")
        return {"FINISHED"}


_CLASSES = (
    ANIM_OT_hytale_set_fk_ik,
    ANIM_OT_hytale_set_head_follow,
    ANIM_OT_hytale_snap_selected,
    ANIM_OT_hytale_keyframe_switch,
)


def register():
    for cls in _CLASSES:
        register_localized_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        unregister_localized_class(cls)
