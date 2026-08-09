# ---------------------------------------------------------------------------
# Este arquivo é o submódulo RIGGER do pacote HyblendToolkit (ainda não
# integrado -- ver DEVELOPER_NOTES.md, seção "Adicionando uma função
# totalmente nova"). Ele não é nem import nem export: pega um Armature já
# importado pelo importer.py e monta em cima dele as camadas ORG/MCH/
# CTRL/CTRL-IK/MCH-IK, os constraints, os drivers de troca IK/FK, um
# conjunto de bones utilitários de controle geral (root.master_CTRL/
# root.spine_CTRL/root.pelvis_CTRL) e uma organização de bone collections
# de alto nível (Main/Face/Attachments) por cima de tudo.
#
# v0.5: o sistema de "marcar bones de IK selecionando no viewport" foi
# substituído por uma LISTA configurável (armature.hytale_ik_chains) --
# cada item descreve uma cadeia inteira por NOME de bone (root/tip/pole/
# parent override), pensada pra virar um picker/eyedropper na UI real
# (chat da interface.py). Isso substitui os dicts hardcoded que existiam
# antes (IK_ROOT_PARENT_OVERRIDES, POLE_ANGLE_OVERRIDES) -- agora tudo é
# editável por item, sem precisar tocar no código pra outro personagem.
#
# Arquitetura de constraints/camadas ORG-MCH-CTRL-IK segue validada contra
# os 4 scripts de referência do usuário (ver histórico do chat) -- não é
# invenção deste arquivo.
#
# bl_info abaixo é só pra rodar este arquivo como addon avulso (Edit >
# Preferences > Add-ons > Install) -- sem painel próprio (a UI já foi
# migrada pra aba "Rig" do interface.py). Ao colar de volta no pacote,
# remova o bl_info -- ver DEVELOPER_NOTES.md.
# ---------------------------------------------------------------------------

bl_info = {
    "name": "Hytale Blocky Rigger",
    "author": "Kaayky",
    "version": (0, 5, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Hytale Rigger",
    "description": "Auto-generate the ORG/MCH/CTRL/CTRL-IK/MCH-IK bone layers, constraints, "
    "IK/FK switch drivers, root control bones and Main/Face/Attachments collections "
    "for a Hytale character armature",
    "category": "Rigging",
}

import math
from collections import deque

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Armature, Operator, PropertyGroup, UIList
from mathutils import Vector

# ---------------------------------------------------------------------------
# Contrato INTERNO deste módulo (não é common.py -- ver rationale no
# rigger.py anterior / DEVELOPER_NOTES.md).
# ---------------------------------------------------------------------------

COLL_HYTALE_EXPORT = "Hytale Export"
COLL_INTERNAL = "Internal"
COLL_ORG = "ORG"
COLL_MCH = "MCH"
COLL_MCH_IK = "MCH-IK"
COLL_CTRL = "CTRL"
COLL_CTRL_IK = "CTRL-IK"

# Collections de alto nível, acima de tudo (Face e Main, nessa ordem) +
# Attachments -- essas 3 (e as sub-collections de Main) ficam VISÍVEIS
# depois de gerar o rig; todo o resto (Internal e tudo dentro dele) fica
# oculto.
COLL_FACE = "Face"
COLL_MAIN = "Main"
COLL_ATTACHMENTS = "Attachments"
COLL_MAIN_HEAD = "Head"
COLL_MAIN_SPINE = "Spine"
COLL_MAIN_BODY = "Body"
COLL_MAIN_ARM_L = "Arm L"
COLL_MAIN_ARM_R = "Arm R"
COLL_MAIN_LEG_L = "Leg L"
COLL_MAIN_LEG_R = "Leg R"
COLL_MAIN_ROOT = "Root"

SUFFIX_MCH = "_MCH"
SUFFIX_CTRL = "_CTRL"
SUFFIX_IK = "_IK"          # bone por segmento (raiz/meio: hierarquia real; ponta: solto + switch)
SUFFIX_IK_MCH = "_IK_MCH"  # bone-ponte por segmento, parentado ao _IK do mesmo segmento
SUFFIX_POLE = "_Pole_CTRL"

# Marca todo bone criado por este script (independente da camada). É isso
# -- não o nome -- que diferencia um bone ORG (original) de um gerado, e é
# a base da idempotência: rodar de novo só cria o que ainda não existe.
PROP_RIG_LAYER = "hytale_rig_layer"

# Custom property no bone _IK da ponta (mão/pé) de cada cadeia. Inteira,
# 0..1 -- 0 = FK, 1 = IK.
PROP_FK_IK_SWITCH = "fk_ik_switch"

# Nomes de constraint iguais aos dos scripts de referência (facilita
# comparar/depurar um rig gerado por este script com um feito à mão).
CONSTRAINT_FK_ROT = "FK_CopyRotation"
CONSTRAINT_FK_SCALE = "FK_CopyScale"
CONSTRAINT_FK_LOC = "FK_CopyLocation"
CONSTRAINT_IK_ROT = "IK_CopyRotation"
CONSTRAINT_IK_SCALE = "IK_CopyScale"
CONSTRAINT_IK_LOC = "IK_CopyLocation"
CONSTRAINT_IK = "IK"
CONSTRAINT_ORG_TO_MCH = "Hytale_ORG_to_MCH"  # trio Location/Rotation/Scale -- convenção própria deste addon
CONSTRAINT_SPINE_FOLLOW = "Hytale_SpineFollow"
CONSTRAINT_CHILD_OF_LOCAL = "Child Of_local"
CONSTRAINT_CHILD_OF_GLOBAL = "Child Of_global"

_COPY_CONSTRAINT_TYPES = {
    "LOCATION": "COPY_LOCATION",
    "ROTATION": "COPY_ROTATION",
    "SCALE": "COPY_SCALE",
}

# ---------------------------------------------------------------------------
# Overrides pontuais que NÃO viraram campo editável por cadeia (são sobre
# bones fora do sistema de IK chains -- reparenting geral de CTRL e a
# organização das collections Main). Edite aqui conforme o rig for mudando.
# ---------------------------------------------------------------------------

# Nome de um bone _CTRL já gerado normalmente pelo pipeline (a partir de
# um ORG) -> nome do bone que deve virar o parent dele, sobrescrevendo o
# que o pipeline padrão (espelha hierarquia ORG) teria escolhido. Aplicado
# em TODA execução (não só quando o bone é criado agora).
CTRL_PARENT_OVERRIDES = {
    "Pelvis_CTRL": "root.pelvis_CTRL",
    "Belly_CTRL": "root.master_CTRL",
    "L-Thigh" + SUFFIX_CTRL: "root.pelvis_CTRL",
    "R-Thigh" + SUFFIX_CTRL: "root.pelvis_CTRL",
}

# Bones utilitários de controle geral (não derivam de nenhum ORG por
# sufixo -- são posicionados a partir de bones de referência já
# existentes, mas têm nome próprio).
BONE_ROOT_MASTER = "root.master_CTRL"
BONE_ROOT_SPINE = "root.spine_CTRL"
BONE_ROOT_PELVIS = "root.pelvis_CTRL"
ROOT_MASTER_SOURCE = "Belly"        # bone ORG usado como referência de posição do master/spine
ROOT_MASTER_PARENT = "Origin_CTRL"  # bone já existente (fora deste script) usado como parent do master
ROOT_SPINE_LENGTH = 0.5             # comprimento (head->tail) do root.spine_CTRL

# Belly_CTRL/Chest_CTRL seguem parcialmente o root.spine_CTRL via um
# constraint de Copy Transforms (Local Space), com influência fixa.
SPINE_FOLLOW_TARGET = BONE_ROOT_SPINE
SPINE_FOLLOW_BONES = {
    "Belly_CTRL": 0.5,
    "Chest_CTRL": 0.63,
}

# Alvo do "Child Of_global" em todo pole target -- o mesmo bone usado como
# parent do root.master_CTRL.
CHILD_OF_GLOBAL_TARGET = ROOT_MASTER_PARENT

# Valores calibrados de pole_angle pro preset "Arm" (ver HytaleIKChainItem
# .pole_angle_mode == "ARM"), por lado (item.side). Esquerdo e direito
# precisam de valores diferentes -- o cálculo automático não bate 100%
# pro braço deste personagem. Adicione mais entradas aqui (ex.: "CENTER")
# ou um dict novo (ex. LEG_POLE_ANGLE_PRESET) se surgir outro caso assim.
ARM_POLE_ANGLE_PRESET = {
    "LEFT": -91.25,
    "RIGHT": -88.76,
}

# Quando o nome digitado/selecionado em "Root Parent" (parent_override)
# não existe como bone, tenta resolver por este dicionário antes de
# desistir -- útil pra bones utilitários (root.pelvis_CTRL etc.) que só
# passam a existir DEPOIS de gerar o rig, então não dá pra selecioná-los
# via eyedropper no momento de configurar a cadeia. O usuário seleciona o
# bone ORG que já existe (ex.: "Pelvis") e isso resolve pro bone final.
PARENT_OVERRIDE_ALIASES = {
    "Pelvis": BONE_ROOT_PELVIS,
}

# Presets de cadeias de IK, por nome de personagem/criatura -- cada valor
# é uma lista de dicts com os mesmos campos de HytaleIKChainItem. Pra
# adicionar um preset novo (outra criatura), basta adicionar uma entrada
# nova aqui; o operador RIG_OT_hytale_ik_chain_load_defaults lista
# automaticamente todas as chaves deste dict como opções.
HYTALE_RIG_PRESETS = {
    "Player": [
        dict(
            label="Arm L", root_bone="L-Arm", tip_bone="L-Hand", pole_bone="L-Forearm",
            parent_override="L-Shoulder" + SUFFIX_CTRL, pole_invert=False, side="LEFT",
            pole_angle_mode="ARM",
        ),
        dict(
            label="Arm R", root_bone="R-Arm", tip_bone="R-Hand", pole_bone="R-Forearm",
            parent_override="R-Shoulder" + SUFFIX_CTRL, pole_invert=False, side="RIGHT",
            pole_angle_mode="ARM",
        ),
        dict(
            label="Leg L", root_bone="L-Thigh", tip_bone="L-Foot", pole_bone="L-Calf",
            parent_override="Pelvis", pole_invert=True, side="LEFT",
            pole_angle_mode="AUTO", extra_ik_location=True,
        ),
        dict(
            label="Leg R", root_bone="R-Thigh", tip_bone="R-Foot", pole_bone="R-Calf",
            parent_override="Pelvis", pole_invert=True, side="RIGHT",
            pole_angle_mode="AUTO", extra_ik_location=True,
        ),
    ],
}

# Dica de nome pra encontrar o bone-filho usado como referência de
# orientação da ponta da cadeia (ex.: "L-Attachment", filho de "L-Hand").
# Case-insensitive, substring. Também usada pra identificar QUALQUER bone
# relacionado a attachment (em qualquer camada -- ORG/MCH/CTRL/IK) pra
# jogar na collection "Attachments" e excluir das collections Main/*.
ATTACHMENT_NAME_HINT = "attachment"

# Bones específicos das collections Main/* (ver _build_main_collections).
HEAD_COLLECTION_ROOT = "Head" + SUFFIX_CTRL
SPINE_COLLECTION_BONES = ["Pelvis" + SUFFIX_CTRL, "Belly" + SUFFIX_CTRL, "Chest" + SUFFIX_CTRL]
BODY_COLLECTION_BONES = [BONE_ROOT_SPINE, BONE_ROOT_MASTER, BONE_ROOT_PELVIS]
ROOT_COLLECTION_BONES = [ROOT_MASTER_PARENT]
ARM_COLLECTION_ROOTS = {
    COLL_MAIN_ARM_L: ["L-Shoulder" + SUFFIX_CTRL],
    COLL_MAIN_ARM_R: ["R-Shoulder" + SUFFIX_CTRL],
}
# Pernas precisam dos DOIS ramos explicitamente (FK e IK não têm um
# ancestral comum dentro da própria perna -- ambos são filhos diretos de
# root.pelvis_CTRL, que é compartilhado pelas duas pernas).
LEG_COLLECTION_ROOTS = {
    COLL_MAIN_LEG_L: ["L-Thigh" + SUFFIX_CTRL, "L-Thigh" + SUFFIX_IK],
    COLL_MAIN_LEG_R: ["R-Thigh" + SUFFIX_CTRL, "R-Thigh" + SUFFIX_IK],
}


# ---------------------------------------------------------------------------
# Helpers -- Edit Mode (collections e edit bones)
# ---------------------------------------------------------------------------


def _find_bone_collection_anywhere(armature, name):
    """Procura uma bone collection pelo nome em QUALQUER nível de
    aninhamento. `armature.collections` só enxerga collections de nível
    raiz -- MCH/CTRL/MCH-IK/CTRL-IK/ORG (aninhadas dentro de "Internal")
    ou Head/Spine/etc. (aninhadas dentro de "Main") nunca apareceriam numa
    checagem só nas raízes."""
    all_colls = getattr(armature, "collections_all", None)
    if all_colls is not None:
        return all_colls.get(name)

    def search(colls):
        for c in colls:
            if c.name == name:
                return c
            found = search(c.children)
            if found is not None:
                return found
        return None

    return search([c for c in armature.collections if c.parent is None])


def _iter_all_collections(armature):
    all_colls = getattr(armature, "collections_all", None)
    if all_colls is not None:
        return list(all_colls)

    result = []

    def gather(colls):
        for c in colls:
            result.append(c)
            gather(c.children)

    gather([c for c in armature.collections if c.parent is None])
    return result


def set_bone_collection_visibility(armature, visible_names):
    """Deixa visível SÓ as collections cujo nome está em `visible_names`
    (todas as outras ficam ocultas). Usado tanto depois de gerar o rig
    (Main/Face/Attachments visíveis) quanto depois de "Remove Generated
    Bones" (só Internal/ORG visíveis, pra sobrar só os bones originais à
    mostra sem precisar ativar nada manualmente)."""
    for coll in _iter_all_collections(armature):
        coll.is_visible = coll.name in visible_names


def ensure_bone_collection(armature, name, parent=None):
    existing = _find_bone_collection_anywhere(armature, name)
    if existing is not None:
        return existing
    return armature.collections.new(name=name, parent=parent)


def create_bone_like(edit_bones, source, new_name):
    """Cria (ou reaproveita, se já existir) um edit bone chamado `new_name`
    com a mesma transform (head/tail/roll) de `source`. Retorna
    (bone, foi_criado_agora) -- bone já existente não é tocado (parent,
    transform etc. ficam como estavam)."""
    existing = edit_bones.get(new_name)
    if existing is not None:
        return existing, False
    new_bone = edit_bones.new(new_name)
    new_bone.head = source.head.copy()
    new_bone.tail = source.tail.copy()
    new_bone.roll = source.roll
    new_bone.use_connect = False
    new_bone.use_deform = False  # só ORG deforma a malha
    return new_bone, True


def find_layer_bone(edit_bones, org_name, suffix):
    if org_name is None:
        return None
    return edit_bones.get(org_name + suffix)


def is_attachment_bone(bone):
    return ATTACHMENT_NAME_HINT in bone.name.lower()


def is_excluded_from_main_collections(bone):
    """Bones que NÃO devem entrar nas collections Head/Spine/Body/Arm/
    Leg/Root (dentro de Main): bones de attachment (vão só pra
    Attachments) e bones das camadas MCH/MCH-IK (Main só quer CTRL e
    CTRL-IK, FK ou IK -- os bones "internos" de mecanismo ficam de fora)."""
    if is_attachment_bone(bone):
        return True
    return bone.get(PROP_RIG_LAYER) in ("MCH", "MCH-IK")


def find_attachment_child(org_bone):
    """Procura, entre os filhos (edit bones) de `org_bone`, um cujo nome
    contenha ATTACHMENT_NAME_HINT (case-insensitive). Retorna o edit bone
    ORG (não o _CTRL) ou None."""
    for child in org_bone.children:
        if is_attachment_bone(child):
            return child
    return None


def find_org_path(root_bone, tip_name):
    """Acha o caminho (lista de edit bones, root->tip) descendo pela
    hierarquia de bones ORG (ignora qualquer bone já gerado por este
    script). Retorna None se tip_name não for descendente de root_bone."""
    if root_bone.name == tip_name:
        return None
    queue = deque([[root_bone]])
    visited = {root_bone.name}
    while queue:
        path = queue.popleft()
        node = path[-1]
        for child in node.children:
            if PROP_RIG_LAYER in child.keys():
                continue  # só anda por bones ORG
            if child.name in visited:
                continue
            new_path = path + [child]
            if child.name == tip_name:
                return new_path
            visited.add(child.name)
            queue.append(new_path)
    return None


def collect_descendants_inclusive(edit_bones, root_name, exclude_predicate=None):
    """Retorna [root] + todos os descendentes (edit bones), pulando
    qualquer bone (e sua própria entrada, mas não necessariamente os
    filhos dele) pro qual exclude_predicate(bone) seja True."""
    root = edit_bones.get(root_name)
    if root is None:
        return []
    result = []
    stack = [root]
    while stack:
        bone = stack.pop()
        stack.extend(bone.children)
        if exclude_predicate is not None and exclude_predicate(bone):
            continue
        result.append(bone)
    return result


# ---------------------------------------------------------------------------
# Helpers -- Pose Mode (constraints, custom properties, drivers)
# ---------------------------------------------------------------------------


def ensure_copy_constraint(pose_bone, target_obj, subtarget_name, copy_type, name, space="LOCAL"):
    con = pose_bone.constraints.get(name)
    if con is None:
        con = pose_bone.constraints.new(_COPY_CONSTRAINT_TYPES[copy_type])
        con.name = name
    con.target = target_obj
    con.subtarget = subtarget_name
    con.target_space = space
    con.owner_space = space
    con.mute = False
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


def ensure_fk_ik_switch_property(pose_bone):
    if PROP_FK_IK_SWITCH not in pose_bone.keys():
        pose_bone[PROP_FK_IK_SWITCH] = 0
    try:
        ui = pose_bone.id_properties_ui(PROP_FK_IK_SWITCH)
        ui.update(min=0, max=1, default=0, description="0 = FK, 1 = IK")
    except Exception:
        pass


def add_switch_driver(constraint, armature_obj, switch_bone_name, expression="switch"):
    """Liga constraint.influence à fk_ik_switch do bone _IK da ponta
    (mão/pé) correspondente. `expression` é "switch" (segue o IK) ou
    "1 - switch" (segue o FK)."""
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
    target.data_path = f'pose.bones["{switch_bone_name}"]["{PROP_FK_IK_SWITCH}"]'


def _angle_on_plane(plane, vec1, vec2):
    """Ângulo entre dois vetores projetados num plano. Portado do
    Text.py de referência -- mesma fórmula, sem alterações de lógica."""
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


def compute_pole_angle(armature_obj, base_bone_name, pole_bone_name):
    """Calcula o pole_angle "cru" pra rest pose atual. Portado do Text.py
    de referência (get_pole_angle). O CHAMADOR inverte o sinal do
    resultado (ver _build_pose_constraints) -- correção empírica."""
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


# ---------------------------------------------------------------------------
# PropertyGroup: um item = uma cadeia de IK inteira, referenciada por nome
# ---------------------------------------------------------------------------


class HytaleIKChainItem(PropertyGroup):
    label: StringProperty(
        name="Label",
        description="Nome livre só pra identificar esta cadeia na lista (ex: Arm L)",
        default="",
    )
    root_bone: StringProperty(
        name="Root Bone",
        description="Primeiro bone da cadeia (ex: L-Arm, L-Thigh)",
        default="",
    )
    tip_bone: StringProperty(
        name="Tip Bone",
        description="Último bone da cadeia -- o alvo/efetor (ex: L-Hand, L-Foot)",
        default="",
    )
    pole_bone: StringProperty(
        name="Pole Reference",
        description="Bone usado como referência de posição/orientação do pole target (ex: L-Forearm). "
        "Vazio = usa automaticamente o bone do meio do caminho root->tip",
        default="",
    )
    parent_override: StringProperty(
        name="Root Parent",
        description="Bone opcional que vira o parent do _IK raiz desta cadeia (ex: L-Shoulder_CTRL, Pelvis). "
        "Vazio = fica solto. Alguns nomes são traduzidos automaticamente pra bones utilitários que só "
        "existem depois de gerar (ver PARENT_OVERRIDE_ALIASES) -- ex.: digitar 'Pelvis' resolve pra "
        "'root.pelvis_CTRL'.",
        default="",
    )
    side: EnumProperty(
        name="Side",
        description="Lado do corpo desta cadeia -- usado por presets de pole_angle (ex.: modo Arm) que "
        "precisam de um valor diferente por lado",
        items=[
            ("LEFT", "Left", ""),
            ("RIGHT", "Right", ""),
            ("CENTER", "Center", ""),
        ],
        default="CENTER",
    )
    pole_invert: BoolProperty(
        name="Pole in Front (+Z)",
        description="Pole na frente (eixo Z positivo do bone de referência) em vez de atrás (padrão, -Z)",
        default=False,
    )
    pole_distance: FloatProperty(
        name="Pole Distance",
        description="Distância do pole target ao bone de referência (pole_bone)",
        default=0.35,
        min=0.001,
    )
    pole_angle_mode: EnumProperty(
        name="Pole Angle Mode",
        items=[
            ("AUTO", "Auto", "Calcula o pole_angle automaticamente a partir da rest pose"),
            ("ARM", "Arm Preset", "Usa o valor calibrado conhecido pra braço, de acordo com o campo Side "
             "(ver ARM_POLE_ANGLE_PRESET no topo do arquivo)"),
            ("MANUAL", "Manual", "Usa o valor digitado em Pole Angle diretamente, sem calcular nada"),
        ],
        default="AUTO",
    )
    pole_angle_manual: FloatProperty(
        name="Pole Angle (deg)",
        description="Valor final do pole_angle, usado só no modo Manual",
        default=0.0,
    )
    pole_angle_fine_tune: FloatProperty(
        name="Pole Angle Fine-Tune (deg)",
        description="Somado ao valor calculado automaticamente -- usado só no modo Auto",
        default=0.0,
    )
    extra_ik_location: BoolProperty(
        name="Also Copy Location on IK (root)",
        description="Adiciona IK_CopyLocation (com switch) no MCH do bone raiz desta cadeia, além de "
        "Rotation/Scale. Precisa quando a raiz não segue a hierarquia ORG normal (ex.: Thigh, parentado "
        "num root.pelvis_CTRL compartilhado).",
        default=False,
    )


# ---------------------------------------------------------------------------
# Operadores: gerenciar a lista de cadeias IK
# ---------------------------------------------------------------------------


class RIG_OT_hytale_ik_chain_add(Operator):
    """Adiciona uma cadeia de IK vazia à lista (preencha os nomes dos
    bones depois -- ou via um picker, quando a UI real estiver pronta)."""

    bl_idname = "armature.hytale_ik_chain_add"
    bl_label = "Add Hytale IK Chain"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        item = chains.add()
        item.label = f"Chain {len(chains)}"
        armature.hytale_ik_chains_index = len(chains) - 1
        return {"FINISHED"}


class RIG_OT_hytale_ik_chain_remove(Operator):
    """Remove uma cadeia da lista pelo índice (padrão: a ativa)."""

    bl_idname = "armature.hytale_ik_chain_remove"
    bl_label = "Remove Hytale IK Chain"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE" and len(obj.data.hytale_ik_chains) > 0

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        index = self.index if self.index >= 0 else armature.hytale_ik_chains_index
        if 0 <= index < len(chains):
            chains.remove(index)
            armature.hytale_ik_chains_index = max(0, min(armature.hytale_ik_chains_index, len(chains) - 1))
        return {"FINISHED"}


class RIG_OT_hytale_ik_chain_set_count(Operator):
    """Ajusta a lista de cadeias de IK pra ter exatamente `count` itens --
    adiciona vazias no fim ou remove do fim, sem tocar nas do meio."""

    bl_idname = "armature.hytale_ik_chain_set_count"
    bl_label = "Set Hytale IK Chain Count"
    bl_options = {"REGISTER", "UNDO"}

    count: IntProperty(name="Amount", default=1, min=0)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        while len(chains) < self.count:
            item = chains.add()
            item.label = f"Chain {len(chains)}"
        while len(chains) > self.count:
            chains.remove(len(chains) - 1)
        return {"FINISHED"}


class RIG_OT_hytale_ik_chain_pick_bone(Operator):
    """Copia o nome do bone atualmente ativo (Edit Mode, Pose Mode, ou o
    último selecionado no Object Mode) pro campo indicado do item de
    cadeia IK indicado. Não é a UI de picker em si (isso é botão/ícone,
    trabalho do chat da interface.py) -- é só a lógica que o botão de
    eyedropper vai chamar: selecione o bone no viewport, então rode este
    operador com `chain_index` e `field` apontando pro campo certo
    ("root_bone", "tip_bone", "pole_bone" ou "parent_override")."""

    bl_idname = "armature.hytale_ik_chain_pick_bone"
    bl_label = "Pick Bone From Selection"
    bl_options = {"REGISTER", "UNDO"}

    chain_index: IntProperty(default=-1)
    field: StringProperty(default="root_bone")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        obj = context.active_object
        bone_name = None
        if context.mode == "EDIT_ARMATURE" and context.active_bone is not None:
            bone_name = context.active_bone.name
        elif context.mode == "POSE" and context.active_pose_bone is not None:
            bone_name = context.active_pose_bone.name
        elif obj.data.bones.active is not None:
            bone_name = obj.data.bones.active.name

        if not bone_name:
            self.report({"WARNING"}, "No active bone to pick -- select one in Edit or Pose Mode first.")
            return {"CANCELLED"}

        chains = obj.data.hytale_ik_chains
        index = self.chain_index if self.chain_index >= 0 else obj.data.hytale_ik_chains_index
        if not (0 <= index < len(chains)):
            self.report({"WARNING"}, "Invalid IK chain index.")
            return {"CANCELLED"}
        if self.field not in {"root_bone", "tip_bone", "pole_bone", "parent_override"}:
            self.report({"WARNING"}, f"Unknown field '{self.field}'.")
            return {"CANCELLED"}

        setattr(chains[index], self.field, bone_name)
        self.report({"INFO"}, f"{self.field} = '{bone_name}'.")
        return {"FINISHED"}


class RIG_OT_hytale_ik_chain_load_defaults(Operator):
    """Preenche a lista com um preset de cadeias de IK já calibradas (ver
    HYTALE_RIG_PRESETS no topo do arquivo). Substitui a lista atual --
    útil pra não perder o trabalho de calibração já feito enquanto a UI
    definitiva (picker) não está pronta. Pra adicionar presets de outras
    criaturas, edite HYTALE_RIG_PRESETS; a lista de opções abaixo é
    gerada automaticamente a partir das chaves desse dict."""

    bl_idname = "armature.hytale_ik_chain_load_defaults"
    bl_label = "Load Hytale IK Chain Preset"
    bl_options = {"REGISTER", "UNDO"}

    def _preset_items(self, context):
        return [(name, name, f"Carrega o preset '{name}'") for name in HYTALE_RIG_PRESETS.keys()]

    preset: EnumProperty(name="Preset", items=_preset_items)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        entries = HYTALE_RIG_PRESETS.get(self.preset)
        if not entries:
            self.report({"WARNING"}, f"Unknown preset '{self.preset}'.")
            return {"CANCELLED"}

        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        chains.clear()
        for entry in entries:
            item = chains.add()
            for key, value in entry.items():
                setattr(item, key, value)

        self.report({"INFO"}, f"Loaded preset '{self.preset}' ({len(entries)} chain(s)).")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Operador: remover bones gerados (útil pra iterar durante o desenvolvimento)
# ---------------------------------------------------------------------------


class RIG_OT_hytale_clear_generated(Operator):
    """Apaga todo bone criado por este script (MCH, CTRL, CTRL-IK,
    MCH-IK/bridge, Pole, e os bones utilitários root.*), deixando só os
    bones ORG originais. Não mexe na lista hytale_ik_chains -- rodar
    "Create Rig" de novo depois reconstrói tudo igual."""

    bl_idname = "armature.hytale_clear_generated_rig"
    bl_label = "Remove Generated Hytale Rig Bones"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        obj = context.active_object
        prev_mode = obj.mode
        bpy.ops.object.mode_set(mode="EDIT")
        removed = 0
        for bone in list(obj.data.edit_bones):
            if PROP_RIG_LAYER in bone.keys():
                obj.data.edit_bones.remove(bone)
                removed += 1
        # Volta a visibilidade pro estado "original": só Internal + ORG
        # visíveis, pra sobrar só os bones ORG à mostra sem precisar
        # ativar nada manualmente.
        set_bone_collection_visibility(obj.data, {COLL_INTERNAL, COLL_ORG})
        bpy.ops.object.mode_set(mode="OBJECT")
        if prev_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=prev_mode)
        self.report({"INFO"}, f"Removed {removed} generated bone(s).")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Operador principal: gera/atualiza as camadas do rig
# ---------------------------------------------------------------------------


class RIG_OT_hytale_generate_rig(Operator):
    """Cria/atualiza as camadas ORG/MCH/CTRL/CTRL-IK/MCH-IK, os bones
    utilitários de controle geral e as collections Main/Face/Attachments
    do Armature ativo, lendo as cadeias de IK definidas em
    armature.hytale_ik_chains. Seguro pra rodar de novo depois de
    adicionar attachments novos: só cria o que ainda não existe."""

    bl_idname = "armature.hytale_generate_rig"
    bl_label = "Create Rig"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        obj = context.active_object
        armature = obj.data

        # "Pra baixo" (usado no fallback do Foot_IK) precisa ser
        # convertido do espaço mundo pro espaço local do Armature -- as
        # coordenadas dos edit bones NÃO são world space.
        world_down_local = obj.matrix_world.inverted().to_3x3() @ Vector((0.0, 0.0, -1.0))

        prev_mode = obj.mode
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            stats, chains_data = self._build_edit_bones(armature, world_down_local)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

        self._build_pose_constraints(obj, chains_data)
        self._build_spine_follow(obj)
        self._apply_pole_childof_inverses(obj, chains_data)

        if prev_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=prev_mode)

        self.report(
            {"INFO"},
            f"Rig ready: {stats['mch']} MCH, {stats['ctrl']} CTRL, {stats['ik']} CTRL-IK, "
            f"{stats['ik_mch']} MCH-IK, {stats['root']} root control bone(s) created; "
            f"{len(chains_data)} IK chain(s) processed.",
        )
        return {"FINISHED"}

    def _apply_pole_childof_inverses(self, obj, chains_data):
        """Roda o equivalente ao botão "Set Inverse" nos dois Child Of de
        cada pole (local e global), senão o pole pula de lugar assim que
        o constraint entra em vigor. Usa o operator real do Blender (via
        context override) em vez de matriz manual."""
        prev_mode = obj.mode
        if obj.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")

        view_layer = bpy.context.view_layer
        prev_active = view_layer.objects.active
        view_layer.objects.active = obj

        for data in chains_data:
            pose_bone = obj.pose.bones.get(data["pole"])
            if pose_bone is None:
                continue
            obj.data.bones.active = pose_bone.bone
            for cname in (CONSTRAINT_CHILD_OF_LOCAL, CONSTRAINT_CHILD_OF_GLOBAL):
                if cname not in pose_bone.constraints:
                    continue
                try:
                    with bpy.context.temp_override(object=obj, active_object=obj, active_pose_bone=pose_bone):
                        bpy.ops.constraint.childof_set_inverse(constraint=cname, owner="BONE")
                except Exception as exc:
                    self.report(
                        {"WARNING"},
                        f"Could not auto Set Inverse for '{cname}' on '{data['pole']}': {exc}. "
                        f"Set it manually in the constraint panel.",
                    )

        view_layer.objects.active = prev_active
        if obj.mode != prev_mode:
            bpy.ops.object.mode_set(mode=prev_mode)

    # ------------------------------------------------------------------
    # Etapa 1 (Edit Mode): collections + bones duplicados
    # ------------------------------------------------------------------

    def _build_edit_bones(self, armature, world_down_local):
        coll_export = ensure_bone_collection(armature, COLL_HYTALE_EXPORT)
        coll_internal = ensure_bone_collection(armature, COLL_INTERNAL)
        coll_org = ensure_bone_collection(armature, COLL_ORG, parent=coll_internal)
        coll_mch = ensure_bone_collection(armature, COLL_MCH, parent=coll_internal)
        coll_mch_ik = ensure_bone_collection(armature, COLL_MCH_IK, parent=coll_internal)
        coll_ctrl = ensure_bone_collection(armature, COLL_CTRL, parent=coll_internal)
        coll_ctrl_ik = ensure_bone_collection(armature, COLL_CTRL_IK, parent=coll_internal)

        edit_bones = armature.edit_bones

        org_bones = [b for b in edit_bones if PROP_RIG_LAYER not in b.keys()]
        org_by_name = {b.name: b for b in org_bones}
        ordered = self._order_top_down(org_bones, org_by_name)

        stats = {"mch": 0, "ctrl": 0, "ik": 0, "ik_mch": 0, "root": 0}

        for org in ordered:
            coll_org.assign(org)
            coll_export.assign(org)

            parent_name = org.parent.name if (org.parent and org.parent.name in org_by_name) else None

            mch, is_new = create_bone_like(edit_bones, org, org.name + SUFFIX_MCH)
            if is_new:
                mch.parent = find_layer_bone(edit_bones, parent_name, SUFFIX_MCH)
                mch.use_connect = bool(org.use_connect and mch.parent is not None)
                mch[PROP_RIG_LAYER] = "MCH"
                stats["mch"] += 1
            coll_mch.assign(mch)

            ctrl, is_new = create_bone_like(edit_bones, org, org.name + SUFFIX_CTRL)
            if is_new:
                ctrl.parent = find_layer_bone(edit_bones, parent_name, SUFFIX_CTRL)
                ctrl.use_connect = bool(org.use_connect and ctrl.parent is not None)
                ctrl[PROP_RIG_LAYER] = "CTRL"
                stats["ctrl"] += 1
            coll_ctrl.assign(ctrl)

        # Bones utilitários de controle geral -- precisam existir ANTES da
        # camada de IK (overrides de parent podem apontar pra eles) e dos
        # overrides de parent dos CTRL normais.
        stats["root"] += self._build_root_controls(edit_bones, coll_ctrl)
        self._apply_ctrl_parent_overrides(edit_bones)

        resolved_chains = self._resolve_chains(edit_bones, armature)
        chains_data = self._build_ik_layer(
            edit_bones, coll_ctrl_ik, coll_mch_ik, resolved_chains, stats, world_down_local
        )

        self._build_main_collections(armature, edit_bones)
        self._propagate_pole_and_tip_to_main_collections(edit_bones, chains_data)
        self._apply_collection_visibility(armature)

        return stats, chains_data

    def _resolve_chains(self, edit_bones, armature):
        """Lê armature.hytale_ik_chains e resolve cada item num caminho
        real de edit bones ORG (root -> ... -> tip)."""
        resolved = []
        for item in armature.hytale_ik_chains:
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

    def _build_root_controls(self, edit_bones, coll_ctrl):
        """Cria (se ainda não existirem) root.master_CTRL, root.spine_CTRL
        e root.pelvis_CTRL. Não derivam de nenhum ORG por sufixo -- usam
        bones de referência já existentes só pra posição/orientação
        inicial."""
        created = 0
        master_source = edit_bones.get(ROOT_MASTER_SOURCE)
        belly_ctrl = edit_bones.get("Belly" + SUFFIX_CTRL)
        pelvis_ctrl = edit_bones.get("Pelvis" + SUFFIX_CTRL)

        master = edit_bones.get(BONE_ROOT_MASTER)
        if master is None and master_source is not None:
            master, is_new = create_bone_like(edit_bones, master_source, BONE_ROOT_MASTER)
            if is_new:
                master.parent = edit_bones.get(ROOT_MASTER_PARENT)
                if master.parent is None:
                    self.report(
                        {"WARNING"},
                        f"'{ROOT_MASTER_PARENT}' not found -- {BONE_ROOT_MASTER} created without a parent.",
                    )
                master[PROP_RIG_LAYER] = "ROOT-CTRL"
                created += 1
        elif master_source is None:
            self.report({"WARNING"}, f"'{ROOT_MASTER_SOURCE}' not found -- skipping {BONE_ROOT_MASTER}.")
        if master is not None:
            coll_ctrl.assign(master)

        if master_source is not None:
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
                pelvis.head = belly_ctrl.head.copy()
                pelvis.tail = pelvis_ctrl.head.copy()
                pelvis.parent = master
                pelvis[PROP_RIG_LAYER] = "ROOT-CTRL"
                created += 1
            coll_ctrl.assign(pelvis)
        else:
            missing = [n for n, b in (("Belly_CTRL", belly_ctrl), ("Pelvis_CTRL", pelvis_ctrl)) if b is None]
            self.report({"WARNING"}, f"{' and '.join(missing)} not found -- skipping {BONE_ROOT_PELVIS}.")

        return created

    def _apply_ctrl_parent_overrides(self, edit_bones):
        """Força o parent de bones _CTRL específicos (ver
        CTRL_PARENT_OVERRIDES), sobrescrevendo o que o pipeline padrão
        (espelha a hierarquia ORG) teria escolhido. Roda toda vez -- não
        só quando o bone é criado agora."""
        for bone_name, parent_name in CTRL_PARENT_OVERRIDES.items():
            bone = edit_bones.get(bone_name)
            if bone is None:
                continue
            parent = edit_bones.get(parent_name)
            if parent is None:
                self.report(
                    {"WARNING"}, f"Override parent '{parent_name}' not found for '{bone_name}' -- skipped."
                )
                continue
            bone.parent = parent
            bone.use_connect = False

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

    def _build_ik_layer(self, edit_bones, coll_ctrl_ik, coll_mch_ik, resolved_chains, stats, world_down_local):
        """Pra cada cadeia resolvida (ver _resolve_chains): um bone `_IK`
        por segmento (raiz/meio com parentesco real espelhando ORG -- ou
        o parent_override do item; ponta solta + switch), um bone-ponte
        `_IK_MCH` por segmento, e um pole target `_Pole_CTRL`."""
        chains_data = []

        for resolved in resolved_chains:
            chain = resolved["path"]
            item = resolved["item"]
            pole_ref = resolved["pole_ref"]

            tip_index = len(chain) - 1
            tip_org = chain[tip_index]
            attachment_org = find_attachment_child(tip_org)
            attachment_ctrl = edit_bones.get(attachment_org.name + SUFFIX_CTRL) if attachment_org else None
            tip_length = (tip_org.tail - tip_org.head).length
            ik_bones = []

            for i, org in enumerate(chain):
                ik_bone, is_new = create_bone_like(edit_bones, org, org.name + SUFFIX_IK)
                if is_new:
                    if i < tip_index:
                        # Os bones ORG do Hytale vêm todos com o eixo Y
                        # apontando pra cima (não pro filho na cadeia) --
                        # isso quebra o solver de IK. Corrige o tail
                        # (aponta pro head do próximo bone da cadeia).
                        ik_bone.tail = chain[i + 1].head.copy()
                    elif attachment_ctrl is not None:
                        # Ponta com socket de referência (ex.: mão ->
                        # Attachment_CTRL): tail do "_IK" fica no HEAD do
                        # "<attachment>_CTRL" correspondente.
                        ik_bone.tail = attachment_ctrl.head.copy()
                    elif tip_length > 1e-9:
                        # Sem socket de referência (ex.: pé): aponta pra
                        # baixo (mundo, convertido pro espaço local do
                        # Armature), preservando o comprimento original.
                        down = world_down_local if world_down_local.length > 1e-9 else Vector((0.0, 0.0, -1.0))
                        ik_bone.tail = ik_bone.head + down.normalized() * tip_length

                    # Roll: alinha o eixo Z do "_IK" o mais perto possível
                    # do eixo Z do ORG correspondente.
                    ik_bone.align_roll(org.z_axis)

                    if i == tip_index:
                        ik_bone.parent = None  # ponta solta -- alvo arrastável + switch
                        ik_bone.use_connect = False
                    elif i == 0:
                        # Neste ponto do pipeline, TODOS os _CTRL normais
                        # e os bones utilitários root.* já foram criados
                        # (base loop + _build_root_controls rodam antes
                        # da camada de IK) -- então referenciar
                        # "L-Shoulder_CTRL" ou "root.pelvis_CTRL" aqui é
                        # seguro, mesmo que o usuário tenha digitado o
                        # nome ANTES de qualquer coisa existir: o que
                        # importa é a ordem de execução, não a ordem em
                        # que o campo foi preenchido.
                        override_name = item.parent_override
                        override_parent = edit_bones.get(override_name) if override_name else None
                        if override_name and override_parent is None:
                            alias = PARENT_OVERRIDE_ALIASES.get(override_name)
                            if alias:
                                override_parent = edit_bones.get(alias)
                        if item.parent_override and override_parent is None:
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

            for i, org in enumerate(chain):
                bridge, is_new = create_bone_like(edit_bones, org, org.name + SUFFIX_IK_MCH)
                if is_new:
                    bridge.parent = ik_bones[i]  # parentesco REAL, é o truque do bridge
                    bridge.use_connect = False
                    bridge[PROP_RIG_LAYER] = "MCH-IK"
                    stats["ik_mch"] += 1
                coll_mch_ik.assign(bridge)

            root_org = chain[0]
            pole, is_new_pole = create_bone_like(edit_bones, root_org, root_org.name + SUFFIX_POLE)
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

            chains_data.append(
                {
                    "org_names": [b.name for b in chain],
                    "ik_root": chain[0].name + SUFFIX_IK,
                    "ik_solver_end": chain[tip_index - 1].name + SUFFIX_IK,
                    "ik_tip": chain[tip_index].name + SUFFIX_IK,
                    "pole": pole.name,
                    "side": item.side,
                    "pole_angle_mode": item.pole_angle_mode,
                    "pole_angle_manual": item.pole_angle_manual,
                    "pole_angle_fine_tune": item.pole_angle_fine_tune,
                    "extra_ik_location": item.extra_ik_location,
                }
            )

        return chains_data

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
        """Organização de alto nível por cima de tudo: Face e Main (nessa
        ordem, acima das demais na lista de collections) + Attachments.
        Dentro de Main: Head/Spine/Body/Arm L/Arm R/Leg L/Leg R/Root.
        Bones de attachment NUNCA entram nessas -- só na Attachments."""
        coll_face = ensure_bone_collection(armature, COLL_FACE)
        coll_main = ensure_bone_collection(armature, COLL_MAIN)
        coll_attachments = ensure_bone_collection(armature, COLL_ATTACHMENTS)

        coll_head = ensure_bone_collection(armature, COLL_MAIN_HEAD, parent=coll_main)
        coll_spine = ensure_bone_collection(armature, COLL_MAIN_SPINE, parent=coll_main)
        coll_body = ensure_bone_collection(armature, COLL_MAIN_BODY, parent=coll_main)
        coll_arm_l = ensure_bone_collection(armature, COLL_MAIN_ARM_L, parent=coll_main)
        coll_arm_r = ensure_bone_collection(armature, COLL_MAIN_ARM_R, parent=coll_main)
        coll_leg_l = ensure_bone_collection(armature, COLL_MAIN_LEG_L, parent=coll_main)
        coll_leg_r = ensure_bone_collection(armature, COLL_MAIN_LEG_R, parent=coll_main)
        coll_root = ensure_bone_collection(armature, COLL_MAIN_ROOT, parent=coll_main)

        # Face e Main acima de todas as outras (nessa ordem) -- melhor
        # esforço: reordena entre as collections de nível raiz. Se o
        # Blender não deixar (versão/API diferente), a organização
        # funcional continua correta, só a ordem visual na lista que pode
        # precisar de um arraste manual.
        self._move_collection_to_index(armature, coll_face, 0)
        self._move_collection_to_index(armature, coll_main, 1)

        # Attachments: reúne QUALQUER bone (qualquer camada) cujo nome
        # contenha a dica de attachment.
        for bone in edit_bones:
            if is_attachment_bone(bone):
                coll_attachments.assign(bone)

        def assign_descendants(coll, root_names):
            for root_name in root_names:
                for bone in collect_descendants_inclusive(
                    edit_bones, root_name, exclude_predicate=is_excluded_from_main_collections
                ):
                    coll.assign(bone)

        assign_descendants(coll_head, [HEAD_COLLECTION_ROOT])

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

        assign_descendants(coll_arm_l, ARM_COLLECTION_ROOTS[COLL_MAIN_ARM_L])
        assign_descendants(coll_arm_r, ARM_COLLECTION_ROOTS[COLL_MAIN_ARM_R])
        assign_descendants(coll_leg_l, LEG_COLLECTION_ROOTS[COLL_MAIN_LEG_L])
        assign_descendants(coll_leg_r, LEG_COLLECTION_ROOTS[COLL_MAIN_LEG_R])

    _MAIN_LIMB_COLLECTION_NAMES = {COLL_MAIN_ARM_L, COLL_MAIN_ARM_R, COLL_MAIN_LEG_L, COLL_MAIN_LEG_R}

    def _propagate_pole_and_tip_to_main_collections(self, edit_bones, chains_data):
        """O pole target e o "_IK" da ponta (mão/pé) ficam SOLTOS na
        hierarquia (sem parent) -- por isso nunca são alcançados pelo
        walk de descendentes que monta Arm L/R e Leg L/R. Aqui, pra cada
        cadeia, descobre em qual sub-collection de Main o resto da cadeia
        (o "_IK" raiz) já caiu, e replica pro pole e pro tip."""
        for data in chains_data:
            ref_bone = edit_bones.get(data["ik_root"])
            if ref_bone is None:
                continue
            member_colls = [c for c in ref_bone.collections if c.name in self._MAIN_LIMB_COLLECTION_NAMES]
            if not member_colls:
                continue
            for name in (data["pole"], data["ik_tip"]):
                bone = edit_bones.get(name)
                if bone is None:
                    continue
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

    def _apply_collection_visibility(self, armature):
        """Esconde tudo (Internal e todo o resto), deixando visível só
        Main (+ sub-collections), Face e Attachments."""
        keep_visible = {COLL_MAIN, COLL_FACE, COLL_ATTACHMENTS}
        main_coll = _find_bone_collection_anywhere(armature, COLL_MAIN)
        if main_coll is not None:
            def add_children(c):
                keep_visible.add(c.name)
                for child in c.children:
                    add_children(child)
            add_children(main_coll)

        set_bone_collection_visibility(armature, keep_visible)

    # ------------------------------------------------------------------
    # Etapa 2 (Pose/Object Mode): constraints, custom properties, drivers
    # ------------------------------------------------------------------

    def _build_pose_constraints(self, obj, chains_data):
        pose_bones = obj.pose.bones
        armature = obj.data

        marked_names = set()
        for data in chains_data:
            marked_names.update(data["org_names"])

        # Camada base: ORG segue MCH. MCH segue CTRL em World Space
        # (Rotation/Scale sempre; Location sempre que o bone não for
        # conectado ao pai).
        for bone in armature.bones:
            if PROP_RIG_LAYER in bone.keys():
                continue
            org_name = bone.name
            mch_name = org_name + SUFFIX_MCH
            ctrl_name = org_name + SUFFIX_CTRL
            if mch_name not in pose_bones or ctrl_name not in pose_bones:
                continue
            mch_pose = pose_bones[mch_name]

            ensure_copy_set(pose_bones[org_name], obj, mch_name, CONSTRAINT_ORG_TO_MCH)

            fk_rot = ensure_copy_constraint(mch_pose, obj, ctrl_name, "ROTATION", CONSTRAINT_FK_ROT, space="WORLD")
            fk_scale = ensure_copy_constraint(mch_pose, obj, ctrl_name, "SCALE", CONSTRAINT_FK_SCALE, space="WORLD")

            is_chain_bone = org_name in marked_names

            fk_loc = None
            if not bone.use_connect:
                fk_loc = ensure_copy_constraint(
                    mch_pose, obj, ctrl_name, "LOCATION", CONSTRAINT_FK_LOC, space="WORLD"
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
        for data in chains_data:
            org_names = data["org_names"]
            ik_root = data["ik_root"]
            ik_solver_end = data["ik_solver_end"]
            ik_tip = data["ik_tip"]
            pole_name = data["pole"]

            ensure_fk_ik_switch_property(pose_bones[ik_tip])

            chain_count = len(org_names) - 1  # tudo menos a ponta (mão/pé)
            mode = data["pole_angle_mode"]
            if mode == "MANUAL":
                pole_angle = math.radians(data["pole_angle_manual"])
            elif mode == "ARM":
                preset_deg = ARM_POLE_ANGLE_PRESET.get(data["side"])
                if preset_deg is None:
                    self.report(
                        {"WARNING"},
                        f"No Arm Preset pole angle for side '{data['side']}' -- falling back to Auto for "
                        f"'{pole_name}'.",
                    )
                    pole_angle = -compute_pole_angle(obj, ik_root, pole_name) + math.radians(
                        data["pole_angle_fine_tune"]
                    )
                else:
                    pole_angle = math.radians(preset_deg)
            else:
                # Sinal invertido: correção empírica (braço e perna
                # precisavam do sinal oposto ao que a fórmula portada
                # calcula).
                pole_angle = -compute_pole_angle(obj, ik_root, pole_name) + math.radians(
                    data["pole_angle_fine_tune"]
                )
            ensure_ik_constraint(pose_bones[ik_solver_end], obj, ik_tip, pole_name, chain_count, pole_angle)

            # Pole target: dois Child Of -- "local" segue a ponta da
            # própria cadeia (mão/pé), "global" fica preso no
            # CHILD_OF_GLOBAL_TARGET (Origin_CTRL). Só um fica ativo por
            # padrão (local); o outro fica disponível com influência 0.
            if pole_name in pose_bones:
                pole_pose = pose_bones[pole_name]
                ensure_child_of_constraint(pole_pose, obj, ik_tip, CONSTRAINT_CHILD_OF_LOCAL, 1.0)

                if CHILD_OF_GLOBAL_TARGET in pose_bones:
                    ensure_child_of_constraint(
                        pole_pose, obj, CHILD_OF_GLOBAL_TARGET, CONSTRAINT_CHILD_OF_GLOBAL, 0.0
                    )
                else:
                    self.report(
                        {"WARNING"},
                        f"'{CHILD_OF_GLOBAL_TARGET}' not found -- skipping {CONSTRAINT_CHILD_OF_GLOBAL} on "
                        f"'{pole_name}'.",
                    )

            for org_name in org_names:
                mch_name = org_name + SUFFIX_MCH
                bridge_name = org_name + SUFFIX_IK_MCH
                if mch_name not in pose_bones:
                    continue
                mch_pose = pose_bones[mch_name]

                fk_rot = mch_pose.constraints.get(CONSTRAINT_FK_ROT)
                fk_scale = mch_pose.constraints.get(CONSTRAINT_FK_SCALE)
                fk_loc = mch_pose.constraints.get(CONSTRAINT_FK_LOC)  # None se o bone for conectado ao pai
                if fk_rot is None or fk_scale is None:
                    continue

                # IK_CopyRotation/IK_CopyScale em World Space -- miram no
                # bridge (_IK_MCH): tem a MESMA rest orientation do MCH
                # (o _IK não tem mais, desde que ganhou tail/roll
                # corrigidos), garantindo que a cópia não saia invertida.
                ik_rot = ensure_copy_constraint(
                    mch_pose, obj, bridge_name, "ROTATION", CONSTRAINT_IK_ROT, space="WORLD"
                )
                ik_scale = ensure_copy_constraint(
                    mch_pose, obj, bridge_name, "SCALE", CONSTRAINT_IK_SCALE, space="WORLD"
                )

                add_switch_driver(fk_rot, obj, ik_tip, expression="1 - switch")
                add_switch_driver(ik_rot, obj, ik_tip, expression="switch")
                add_switch_driver(fk_scale, obj, ik_tip, expression="1 - switch")
                add_switch_driver(ik_scale, obj, ik_tip, expression="switch")
                if fk_loc is not None:
                    add_switch_driver(fk_loc, obj, ik_tip, expression="1 - switch")

                # IK_CopyLocation extra -- só se o item pediu (ex.: Thigh,
                # cuja raiz é parentada fora da hierarquia ORG normal).
                if data["extra_ik_location"] and org_name == org_names[0] and fk_loc is not None:
                    ik_loc = ensure_copy_constraint(
                        mch_pose, obj, bridge_name, "LOCATION", CONSTRAINT_IK_LOC, space="WORLD"
                    )
                    add_switch_driver(ik_loc, obj, ik_tip, expression="switch")

    def _build_spine_follow(self, obj):
        """Belly_CTRL e Chest_CTRL seguem parcialmente o root.spine_CTRL
        via Copy Transforms (Local Space), influência fixa. mix_mode =
        'AFTER_FULL' (em vez do padrão 'REPLACE'): com REPLACE, a
        constraint interpola a pose já calculada do bone (ex.: por uma
        animação importada) EM DIREÇÃO à pose do root.spine_CTRL,
        proporcional à influência -- puxando de volta pro repouso mesmo
        sem o animador pedir nada. Com AFTER_FULL, a pose calculada é
        aplicada primeiro e o root.spine_CTRL só soma um ajuste por cima;
        com ele no repouso (identidade), isso não altera nada, e qualquer
        ajuste manual continua funcionando como extra genuíno."""
        pose_bones = obj.pose.bones
        if SPINE_FOLLOW_TARGET not in pose_bones:
            self.report(
                {"WARNING"}, f"'{SPINE_FOLLOW_TARGET}' not found -- skipping spine-follow constraints."
            )
            return
        for bone_name, influence in SPINE_FOLLOW_BONES.items():
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


# ---------------------------------------------------------------------------
# UIList reutilizável pela aba "Rig" do interface.py (registrada aqui
# porque descreve como desenhar um item de armature.hytale_ik_chains --
# é dado/lógica deste módulo, não layout de painel).
# ---------------------------------------------------------------------------


class RIG_UL_hytale_ik_chains(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "label", text="", emboss=False, icon="BONE_DATA")


_CLASSES = (
    HytaleIKChainItem,
    RIG_UL_hytale_ik_chains,
    RIG_OT_hytale_ik_chain_add,
    RIG_OT_hytale_ik_chain_remove,
    RIG_OT_hytale_ik_chain_set_count,
    RIG_OT_hytale_ik_chain_pick_bone,
    RIG_OT_hytale_ik_chain_load_defaults,
    RIG_OT_hytale_clear_generated,
    RIG_OT_hytale_generate_rig,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    Armature.hytale_ik_chains = CollectionProperty(type=HytaleIKChainItem)
    Armature.hytale_ik_chains_index = IntProperty(default=0)


def unregister():
    del Armature.hytale_ik_chains_index
    del Armature.hytale_ik_chains
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
