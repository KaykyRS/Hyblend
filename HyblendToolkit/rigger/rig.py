"""
rigger/rig.py -- o Auto-Rigger inteiro (exceto as constantes puras, que
moram em rigger/constants.py, e o register()/unregister(), em
rigger/__init__.py): helpers de bone collection/constraint/driver/pole
angle, custom shapes + Shape Edit Mode + Mirror Shape, HytaleIKChainItem
e os operadores de lista de cadeias IK, Validate Rig, "Create Rig"/
"Remove Generated Bones", e os operadores de save/delete/apply de rig/
shape/collection template.

Corresponde ao que já foi rigger.py (agora dividido em pacote -- ver
DEVELOPER_NOTES.md, Tarefa A) menos as constantes puras. Ficou um
arquivo só (em vez de vários) por decisão explícita: a divisão em mais
pedaços criava fronteiras de import um tanto artificiais entre partes
que sempre se chamam mutuamente (ex.: geração de rig precisa de shapes,
Shape Edit Mode precisa de helpers genéricos) -- juntar tudo aqui evita
esse acoplamento cruzado sem esconder a organização em si, que continua
marcada pelos comentários de seção abaixo (Helpers, Shapes, IK Chains,
Generate, Template Ops), na mesma ordem em que apareciam no rigger.py
monolítico.

RIG_OT_hytale_validate_rig (Tarefa C, novo) mora na seção de IK Chains,
perto de find_shared_pole_angle_preset_warnings/
resolve_pole_angle_preset_degrees (também novas -- extraídas de dentro
de RIG_OT_hytale_generate_rig pra ele poder reaproveitar a MESMA lógica
sem duplicar, ver comentário ali). RIG_OT_hytale_mirror_shape (Tarefa D,
novo) mora na seção de Shapes, logo depois de Shape Edit Mode Enter/
Finish, de quem ele depende (só funciona com o modo ativo).
"""
import math
import os
import re
from collections import deque

import bpy
import blf
import gpu
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Menu, Operator, PropertyGroup, UIList
from gpu_extras.batch import batch_for_shader
from mathutils import Euler, Matrix, Vector

from ..templates import (
    collection_template_enum_items,
    delete_collection_template,
    delete_rig_template,
    delete_shape_template,
    get_collection_template,
    get_rig_template,
    get_shape_template,
    list_collection_templates,
    list_rig_templates,
    list_shape_templates,
    save_collection_template,
    save_rig_template,
    save_shape_template,
)
# Constantes puras (rigger/constants.py) -- wildcard de propósito: este
# arquivo usa a grande maioria delas (é o "coração do pipeline" que a
# Tarefa A já previa), então uma lista explícita de import só cresceria
# sem ganhar legibilidade. Nomes com "_" NA FRENTE (ex.: _TEMPLATE_NONE,
# _COPY_CONSTRAINT_TYPES) não entram num `import *` -- por isso os dois
# são importados à parte, explicitamente, logo abaixo.
from .constants import *  # noqa: F401,F403
from .constants import _COPY_CONSTRAINT_TYPES, _TEMPLATE_NONE


# ARM_COLLECTION_ROOTS/LEG_COLLECTION_ROOTS acima são nomes FIXOS --
# cobrem o Player (e qualquer personagem com a mesma convenção de nome).
# _resolve_main_limb_roots complementa isso (nunca substitui) de duas
# formas: (1) checando o esqueleto de VERDADE (edit_bones) -- se
# "L-Shoulder_CTRL" não existir nesse personagem, troca pra
# ARM_COLLECTION_ROOTS_NO_SHOULDER automaticamente, sem depender de
# nenhum texto digitado em lugar nenhum; (2) usando a cadeia de IK REAL
# já configurada em armature.hytale_ik_chains pra cobrir nomes de bone
# totalmente customizados (nem Shoulder nem Arm) -- essa segunda parte
# olha item.chain_type ("ARM"/"LEG") + item.side ("LEFT"/"RIGHT")
# diretamente (v0.6 -- antes disso existir, tentava adivinhar pelo texto
# livre do campo `label`, um dicionário de palavras-chave tipo
# "arm"/"braço" -- removido: chain_type é um campo estruturado de
# verdade agora, não precisa mais adivinhar por texto, e o método antigo
# falhava silenciosamente sempre que o label ficava com o nome padrão
# tipo "Chain 1" em vez de conter "arm"/"braço" -- ver histórico do
# chat). Nunca remove nada do que já foi resolvido no item (1).


def _resolve_parent_override(edit_bones, override_name):
    """Resolve o texto de item.parent_override pro edit bone final:
    tenta PARENT_OVERRIDE_ALIASES primeiro (bones utilitários que só
    existem depois de gerados, ex. 'Pelvis' -> 'root.pelvis_CTRL' --
    tem que vir ANTES do nome literal, senão um ORG chamado igual ao
    alias -- ex. o próprio 'Pelvis' -- rouba a resolução, ver comentário
    histórico em _build_ik_layer sobre esse bug), senão tenta o nome
    literal. Retorna None se não encontrar nada -- o chamador decide se
    avisa. Usado por _build_ik_layer (cadeias Arm/Leg) e _build_tail_layer
    (cadeias Tail) -- mesmo campo (`parent_override`), mesma regra.

    v0.6: se o texto digitado já vier com o sufixo "_CTRL" (ex.:
    'L-Shoulder_CTRL', copiado de algum lugar ou digitado por hábito),
    o sufixo é removido ANTES de qualquer resolução -- não existe mais
    reconhecimento "por acaso" de um nome de bone _CTRL literal (que só
    funcionava porque, na hora em que isso roda, o _CTRL já foi criado
    nesta mesma execução -- mas não é algo que devesse ser digitado,
    já que não existe no momento em que o usuário está configurando a
    cadeia). Com isso, 'L-Shoulder' e 'L-Shoulder_CTRL' sempre resolvem
    pro MESMO lugar, através do MESMO alias -- um único caminho de
    resolução, sem comportamento diferente por coincidência de nome."""
    if not override_name:
        return None
    if override_name.endswith(SUFFIX_CTRL):
        override_name = override_name[: -len(SUFFIX_CTRL)]
    alias = PARENT_OVERRIDE_ALIASES.get(override_name)
    if alias:
        return edit_bones.get(alias)
    return edit_bones.get(override_name)


def _classify_chain_limb(item):
    """Classifica uma HytaleIKChainItem (rigger.py) como braço ou perna
    (v0.6: direto de item.chain_type, campo estruturado -- ver
    HytaleIKChainItem). Retorna 'ARM'/'LEG'/None (qualquer outro tipo,
    ex. 'TAIL', não deve ser forçado em nenhuma das duas)."""
    return item.chain_type if item.chain_type in ("ARM", "LEG") else None


_LIMB_SIDE_TO_COLLECTION = {
    ("ARM", "LEFT"): COLL_MAIN_ARM_L,
    ("ARM", "RIGHT"): COLL_MAIN_ARM_R,
    ("LEG", "LEFT"): COLL_MAIN_LEG_L,
    ("LEG", "RIGHT"): COLL_MAIN_LEG_R,
}


def _resolve_main_limb_roots(armature, edit_bones):
    """Monta a versão final (fixa + determinística + dinâmica) das
    raízes de Arm L/R e Leg L/R pra ESTE Armature:

    1. Começa de ARM_COLLECTION_ROOTS/LEG_COLLECTION_ROOTS (nomes fixos,
       cobrem o Player).
    2. Pra cada lado de Arm: se "<L/R>-Shoulder_CTRL" não existir em
       `edit_bones` (personagem sem bone de ombro -- a cadeia de braço
       começa direto no Arm), troca a raiz fixa pelas duas de
       ARM_COLLECTION_ROOTS_NO_SHOULDER ("<L/R>-Arm_CTRL" +
       "<L/R>-Arm_IK"). Checagem determinística no esqueleto de
       verdade -- não depende de nenhum texto digitado em lugar nenhum.
    3. ACRESCENTA a raiz real (root_bone + _CTRL, root_bone + _IK) de
       toda cadeia em armature.hytale_ik_chains cujo item.chain_type seja
       ARM ou LEG (ver _classify_chain_limb) -- cobre nome de bone
       totalmente customizado (nem Shoulder nem Arm/Thigh), automático,
       sem precisar digitar nada em lugar nenhum: Arm + Left -> Main/Arm
       L, Leg + Right -> Main/Leg R, direto de chain_type + side. Nunca
       remove nada do que já foi resolvido nos passos 1-2."""
    roots = {name: list(bones) for name, bones in {**ARM_COLLECTION_ROOTS, **LEG_COLLECTION_ROOTS}.items()}

    for coll_name, shoulder_roots in ARM_COLLECTION_ROOTS.items():
        shoulder_name = shoulder_roots[0]
        if edit_bones.get(shoulder_name) is None:
            for candidate in ARM_COLLECTION_ROOTS_NO_SHOULDER[coll_name]:
                if candidate not in roots[coll_name]:
                    roots[coll_name].append(candidate)

    for item in getattr(armature, "hytale_ik_chains", []):
        if not item.root_bone or item.side not in ("LEFT", "RIGHT"):
            continue
        limb = _classify_chain_limb(item)
        if limb is None:
            continue
        coll_name = _LIMB_SIDE_TO_COLLECTION.get((limb, item.side))
        if coll_name is None:
            continue
        for candidate in (item.root_bone + SUFFIX_CTRL, item.root_bone + SUFFIX_IK):
            if candidate not in roots[coll_name]:
                roots[coll_name].append(candidate)
    return roots

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


def _redraw_all_areas(context):
    """Força o redraw de TODA área de TODA janela aberta -- usado pelos
    operadores que mexem em armature.hytale_ik_chains (add/remove/
    set_count, ver seção "Operadores: gerenciar a lista de cadeias IK"
    logo abaixo). Sem isso, um operador chamado a partir de um POPUP
    MENU (o menu "+" -> Arm/Leg/Tail, ver RIG_MT_hytale_ik_chain_add_menu)
    executa normalmente (o item já foi criado de verdade, undo/redo
    funcionam certinho) mas o Blender não redesenha sozinho a UIList da
    aba Rig na hora -- só quando QUALQUER outro evento (mover o mouse pra
    dentro da viewport, por exemplo) força um redraw geral por outro
    motivo. É uma limitação conhecida do Blender com popups (não tem a
    ver com a lógica do operador em si) -- forçar o redraw explicitamente
    aqui é o jeito padrão de contornar."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


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


def rotate_edit_bone_local_axis(edit_bone, axis_letter, degrees):
    """Rotaciona um edit bone em torno de um dos próprios eixos LOCAIS
    (X, Y ou Z do bone -- não do Armature) por `degrees` graus -- head e
    comprimento preservados, só a direção do tail (e o roll, recalculado
    junto pra acompanhar a rotação) mudam. Usado pelo ajuste manual da
    ponta de uma cadeia Tail (ver HytaleIKChainItem.tail_tip_rotation_*/
    _build_tail_layer): o último bone de uma cauda não tem próximo
    segmento pra apontar, então fica com a direção ORIGINAL do ORG (eixo
    Y do Hytale, pra cima) -- este helper deixa corrigir manualmente,
    tipo dobrar uma dobradiça num dos 3 eixos do próprio bone (qual eixo
    resolve o problema depende de como o bone específico ficou orientado
    -- por isso é escolhível, não fixo em X)."""
    if abs(degrees) < 1e-6:
        return
    axis = {"X": edit_bone.x_axis, "Y": edit_bone.y_axis, "Z": edit_bone.z_axis}.get(axis_letter)
    if axis is None or axis.length < 1e-9:
        return
    axis = axis.normalized()
    old_z = edit_bone.z_axis
    rot = Matrix.Rotation(math.radians(degrees), 4, axis)
    direction = edit_bone.tail - edit_bone.head
    edit_bone.tail = edit_bone.head + (rot @ direction)
    # X e Z são perpendiculares à direção do bone (Y) -- girar em torno
    # de qualquer um dos dois "dobra" o tail (o caso comum, pra corrigir
    # a ponta que não tem próximo segmento pra apontar). Y é a própria
    # direção do bone -- girar em torno dele só muda o roll (spin),
    # tail fica no lugar; align_roll(rot @ old_z) cobre os 3 casos.
    edit_bone.align_roll(rot @ old_z)


def find_layer_bone(edit_bones, org_name, suffix):
    if org_name is None:
        return None
    return edit_bones.get(org_name + suffix)


def is_attachment_bone(bone):
    return ATTACHMENT_NAME_HINT in bone.name.lower()


def is_excluded_from_main_collections(bone):
    """Bones que NÃO devem entrar nas collections Head/Spine/Body/Arm/
    Leg/Root (dentro de Main): bones de attachment (vão só pra
    Attachments) e bones das camadas MCH/MCH-IK/TAIL (Main só quer CTRL e
    CTRL-IK, FK ou IK -- os bones "internos" de mecanismo, incluindo os
    bridges _Tail (ver COLL_MCH_IK/"Specials"), ficam de fora)."""
    if is_attachment_bone(bone):
        return True
    return bone.get(PROP_RIG_LAYER) in ("MCH", "MCH-IK", "TAIL")


def find_attachment_child(org_bone):
    """Procura, entre os filhos (edit bones) de `org_bone`, um cujo nome
    contenha ATTACHMENT_NAME_HINT (case-insensitive). Retorna o edit bone
    ORG (não o _CTRL) ou None."""
    for child in org_bone.children:
        if is_attachment_bone(child):
            return child
    return None


def find_non_attachment_children(org_bone):
    """Irmã de find_attachment_child: retorna TODOS os filhos ORG (edit
    bones) de `org_bone` que NÃO são attachment -- ex.: dedos da mão/pé,
    ou qualquer outro bone do próprio personagem (não um socket
    plugável) que more diretamente sob a ponta de uma cadeia de IK
    (Hand/Foot). Usada em _build_ik_layer pra dar o mesmo tratamento de
    reparent que os attachments já recebem (ver comentário lá)."""
    return [child for child in org_bone.children if not is_attachment_bone(child)]


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


def ensure_stretch_to_constraint(pose_bone, armature_obj, subtarget_name, name):
    """Stretch To simples, sempre esticando pro subtarget -- usado só
    pelo bone "_Pole_Line" (ver SUFFIX_POLE_LINE), mirando no
    "_Pole_CTRL" do mesmo lado/cadeia. rest_length=0 deixa o Blender
    usar o comprimento de rest do próprio bone (o que ele já tinha ao
    ser criado, apontando pro pole -- ver _build_ik_layer) como
    referência, sem precisar recalcular nada aqui."""
    con = pose_bone.constraints.get(name)
    if con is None:
        con = pose_bone.constraints.new("STRETCH_TO")
        con.name = name
    con.target = armature_obj
    con.subtarget = subtarget_name
    con.rest_length = 0.0
    return con


def switch_property_name(tip_org_name, side):
    """Nome da custom property de FK/IK switch pra uma cadeia, agora TODA
    guardada no bone PROPERTIES (ver BONE_PROPERTIES) em vez de uma
    property igual em cada _IK -- precisa de prefixo (mão/pé, tirado do
    nome do ORG da ponta, ex.: "L-Hand" -> "hand") + sufixo (L/R, tirado
    de item.side) pra não colidir (antes, "fk_ik_switch" existia
    IDÊNTICO em L-Hand_IK e L-Foot_IK -- cada um na sua PROPRIA pose bone,
    então não colidia; agora que todos moram no MESMO bone, colidiria sem
    isso). Ex.: "L-Hand" + "LEFT" -> "hand_fk_ik_switch_L"."""
    base = tip_org_name
    for prefix in ("L-", "R-"):
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    prefix_word = base.lower()
    suffix = "L" if side == "LEFT" else "R"
    return f"{prefix_word}_{PROP_FK_IK_SWITCH}_{suffix}"


def ensure_fk_ik_switch_property(pose_bone, prop_name):
    if prop_name not in pose_bone.keys():
        pose_bone[prop_name] = 0
    try:
        ui = pose_bone.id_properties_ui(prop_name)
        ui.update(min=0, max=1, default=0, description="0 = FK, 1 = IK")
    except Exception:
        pass


def add_switch_driver(constraint, armature_obj, switch_bone_name, switch_prop_name, expression="switch"):
    """Liga constraint.influence à custom property de FK/IK switch do
    bone PROPERTIES (ver switch_property_name -- cada cadeia tem a sua
    própria property lá, não mais uma por bone _IK). `expression` é
    "switch" (segue o IK) ou "1 - switch" (segue o FK)."""
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
    """Liga custom_shape_scale_xyz (os 3 eixos) à custom property de
    FK/IK switch do bone PROPERTIES -- mesmo princípio do
    add_switch_driver acima, mas numa propriedade vetorial (precisa de um
    driver por índice, 0/1/2, não um só). `target_scale` é o valor
    "cheio" (modo ativo) desse bone especificamente -- fica embutido como
    número literal na expressão de CADA driver, então bones diferentes
    podem ter tamanhos-alvo totalmente diferentes sem nenhum cálculo
    compartilhado entre eles (ex.: Hand_IK pode ir a 7 enquanto
    Forearm_CTRL vai a 4 -- cada driver só conhece o próprio número).

    `mode`: "IK" -> visível (scale = target) quando switch=1, some quando
    switch=0. "FK" -> o oposto (visível quando switch=0)."""
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
    """True se "Create Rig" já rodou pelo menos uma vez neste armature
    (algum bone carrega PROP_RIG_LAYER). Usado pelo poll() dos operadores
    de Shape Edit Mode abaixo -- entrar no modo não faz sentido antes de
    existir nenhum CTRL gerado pra editar -- e também é o que
    interface.py deve chamar pra apagar o botão (ver aviso no fim da
    resposta sobre o que fazer em interface.py). `armature.bones` (não
    `edit_bones`) funciona em qualquer modo -- IDs de bone custom
    property setadas em Edit Mode continuam visíveis em Object/Pose
    Mode."""
    return any(PROP_RIG_LAYER in b.keys() for b in armature.bones)

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

def compute_pole_angle_edit(armature_obj, base_bone, pole_bone):
    """Mesma matemática de compute_pole_angle() (mesmo resultado, mesma
    convenção de sinal -- o CHAMADOR também precisa inverter o sinal
    igual lá), só que operando em EDIT BONES (head/tail/x_axis, já em
    world space direto) em vez do datablock Bone -- não precisa sair do
    Edit Mode pra recalcular depois de mover um bone. Usado só pra medir
    a DIFERENÇA (delta) de pole_angle causada por reposicionar um bone,
    não pro cálculo normal do modo AUTO (esse continua usando
    compute_pole_angle, fora do Edit Mode, como sempre)."""
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



_SHAPE_SCALE_DRIVER_VALUE_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*\*")


def _format_shape_scale_literal(value):
    """Formata um float como o literal decimal simples que
    _SHAPE_SCALE_DRIVER_VALUE_RE sabe reler depois (sem notação
    científica -- repr()/str() caem pra "1e-05" em valores bem pequenos,
    o que a regex acima NÃO reconhece). Usado só por
    RIG_OT_hytale_shape_edit_mode_finish, pra regravar a expressão do
    driver com o tamanho novo que o usuário deixou."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text and text != "-" else "0"


def resolve_custom_shape_scale(pose_bone):
    """Valor "real" (tamanho cheio, sem o driver de troca FK/IK) do
    custom_shape_scale_xyz de um pose bone -- pra usar ao SALVAR um
    shape template. Ler pb.custom_shape_scale_xyz direto retorna o valor
    JÁ AVALIADO pelo driver de add_custom_shape_scale_switch_driver
    (0 se o modo oposto -- FK ou IK -- estiver ativo NO MOMENTO do
    save), não o alvo configurado; salvar esse valor faria o template
    gravar 0 pra qualquer bone cujo modo oposto estivesse ativo ao
    salvar (ver DEVELOPER_NOTES.md/histórico do chat).

    Em vez de reavaliar o driver com o switch forçado (mexeria no rig
    do usuário só pra ler um valor), extrai o alvo direto da EXPRESSÃO
    do driver em cada eixo (o número embutido antes do "*" -- ver
    _SHAPE_SCALE_DRIVER_VALUE_RE), que é sempre o "tamanho cheio"
    independente do estado atual do switch. Eixo sem driver (bone fora
    de cadeia IK, ex.: root.master_CTRL) usa o valor direto -- não tem
    diferença nenhuma pra esses."""
    scale = list(pose_bone.custom_shape_scale_xyz)
    obj = pose_bone.id_data
    anim_data = getattr(obj, "animation_data", None)
    if anim_data is None:
        return tuple(scale)

    data_path = f'pose.bones["{pose_bone.name}"].custom_shape_scale_xyz'
    for i in range(3):
        fcurve = anim_data.drivers.find(data_path, index=i)
        if fcurve is None or fcurve.driver is None:
            continue
        match = _SHAPE_SCALE_DRIVER_VALUE_RE.match(fcurve.driver.expression or "")
        if match:
            scale[i] = float(match.group(1))
    return tuple(scale)


def _iter_shape_scale_drivers(obj):
    """Gera (pose_bone, axis_index, fcurve) pra cada driver de
    custom_shape_scale_xyz que hoje existe nos pose bones de `obj` --
    ou seja, só os bones/eixos que passaram por
    add_custom_shape_scale_switch_driver (bones dentro de uma cadeia
    IK/FK -- ver _build_ik_fk_shape_visibility). Bones fora de cadeia
    IK (ex.: root.master_CTRL, Spine_CTRL) não aparecem aqui -- o scale
    deles já é um valor estático, sem driver, já livremente editável a
    qualquer momento; Shape Edit Mode não tem nada a fazer com eles.

    Base pros dois operadores de Shape Edit Mode abaixo (Enter muta cada
    driver encontrado aqui, Finish só reativa os que encontrar mutados)."""
    anim_data = getattr(obj, "animation_data", None)
    if anim_data is None:
        return
    for pb in obj.pose.bones:
        data_path = f'pose.bones["{pb.name}"].custom_shape_scale_xyz'
        for i in range(3):
            fcurve = anim_data.drivers.find(data_path, index=i)
            if fcurve is not None and fcurve.driver is not None:
                yield pb, i, fcurve


def _widgets_library_path():
    """Caminho absoluto pro hytale_widgets.blend, resolvido em relação à
    RAIZ do pacote (HyblendToolkit/), não a este arquivo -- funciona tanto
    instalado como Extension quanto rodado como addon avulso, desde que a
    pasta assets/ esteja ao lado de blender_manifest.toml/__init__.py.

    v0.9 (Tarefa A, split de rigger.py): ANTES este arquivo era rigger.py,
    direto dentro de HyblendToolkit/, então um `os.path.dirname` só já
    bastava. Agora é rigger/rig.py, um nível mais fundo -- precisa de
    um `os.path.dirname` A MAIS pra voltar até HyblendToolkit/ (onde
    assets/ realmente mora). Ajuste mecânico exigido pela nova
    profundidade de pasta, não uma mudança de comportamento."""
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(package_root, WIDGETS_LIBRARY_SUBDIR, WIDGETS_LIBRARY_FILENAME)


def ensure_widget_objects(names):
    """Garante que cada nome em `names` exista em bpy.data.objects,
    fazendo append (cópia, não link) de hytale_widgets.blend só pros que
    ainda faltam -- idempotente, igual o resto do pipeline: rodar de novo
    não duplica nada (objeto já existente com aquele nome é reaproveitado
    como está, mesmo que o usuário tenha editado o shape manualmente
    depois).

    Retorna o conjunto de nomes que NÃO foi possível resolver (arquivo
    hytale_widgets.blend ausente, ou nome que não existe dentro dele) --
    o chamador decide como avisar o usuário; isso nunca levanta exceção,
    porque custom shape é 100% cosmético e não deve travar a geração do
    resto do rig."""
    missing = {name for name in names if name not in bpy.data.objects}
    if not missing:
        return set()

    filepath = _widgets_library_path()
    if not os.path.isfile(filepath):
        return missing

    with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
        data_to.objects = [name for name in data_from.objects if name in missing]

    loaded_names = {obj.name for obj in data_to.objects if obj is not None}
    return missing - loaded_names


def _widget_name_for_bone(bone_name, layer, ik_tip_names, shape_overrides=None):
    """Decide qual widget (nome PREFERIDO na biblioteca) um bone deve
    usar, ou None se esse bone não deve ganhar custom shape nenhum
    (MCH/MCH-IK/ORG). TODOS os bones CTRL/CTRL-IK/ROOT-CTRL ganham shape
    -- inclusive os segmentos do MEIO de uma cadeia IK (ex.: Arm_IK,
    Forearm_IK), não só a ponta -- porque o driver de FK/IK
    (_build_ik_fk_shape_visibility) já cobre a cadeia inteira, e esses
    bones do meio também são visíveis/selecionáveis durante animação.
    Attachments (nome contém ATTACHMENT_NAME_HINT) ganham um widget
    próprio (WGT_ATTACHMENT), vencendo o genérico WGT_FK_RING -- mesmo
    princípio de BONE_COLOR_ATTACHMENT/ATTACHMENT_SHAPE_SCALE.

    Ordem de prioridade: (1) campo "widget" do bone no TEMPLATE DE SHAPES
    ativo (shape_overrides -- ver shape_template["bones"][bone_name] em
    templates/shapes/*.json), pra qualquer personagem poder escolher um
    shape diferente por bone sem tocar em código; (2) WIDGET_NAME_OVERRIDES
    fixo (bones utilitários que existem em TODO personagem -- root
    master/spine/pelvis, Head_CTRL, Origin_CTRL -- não são "calibração de
    personagem", são convenção estrutural do próprio pipeline); (3) a
    regra genérica por layer/papel, abaixo.

    "Preferido" porque não garante que esse nome exista na biblioteca
    ainda -- _build_custom_shapes cai pro WGT_DEFAULT_FALLBACK se não
    existir (ver comentário perto de WGT_DEFAULT_FALLBACK, no topo do
    arquivo)."""
    if shape_overrides:
        template_widget = shape_overrides.get(bone_name, {}).get("widget")
        if template_widget:
            return template_widget
    override = WIDGET_NAME_OVERRIDES.get(bone_name)
    if override:
        return override
    if layer is None:
        return None
    if bone_name.endswith(SUFFIX_POLE_LINE):
        return WGT_POLE_LINE
    if bone_name.endswith(SUFFIX_POLE):
        return WGT_POLE
    if ATTACHMENT_NAME_HINT in bone_name.lower():
        return WGT_ATTACHMENT
    if layer == "CTRL-IK":
        return WGT_IK_BOX
    if layer in ("CTRL", "ROOT-CTRL"):
        return WGT_FK_RING
    return None


def compute_widget_transform_correction(old_axes, old_length, new_axes, new_length, old_translation, old_rotation, old_scale):
    """Corrige Translation/Rotation/Scale do custom shape depois que a
    geometria (head/tail) de UM BONE ESPECÍFICO mudou -- mesmo espírito
    do compute_pole_angle_edit (mede "antes" e "depois", aplica a
    diferença), só que aqui a "diferença" é uma transformação completa
    (rotação do referencial local + mudança de comprimento), não um
    ângulo só.

    Premissas (confirmadas na documentação oficial do Blender -- Bone >
    Viewport Display > Custom Shape): a origem do shape é o HEAD do bone;
    o eixo Y do shape segue o eixo Y do bone; com "Scale to Bone Length"
    ligado (use_custom_shape_bone_size = True, que é como este script
    sempre deixa -- ver _build_custom_shapes), TUDO (Translation E Scale)
    é multiplicado pelo comprimento do bone. Rotation não depende do
    comprimento, só da orientação dos eixos.

    `old_axes`/`new_axes`: tupla (x_axis, y_axis, z_axis) do EDIT BONE,
    antes e depois da mudança (mathutils.Vector, espaço do armature).
    `old_length`/`new_length`: comprimento do bone, antes e depois.
    `old_translation`/`old_rotation`/`old_scale`: os 3 valores calibrados
    ANTIGOS (do bone no template de shapes ativo -- rotation já em
    radianos, convertida a partir de "rotation_deg" pelo chamador).

    Retorna (nova_translation, nova_rotation, nova_scale), cada um uma
    tupla de 3 floats -- mesmo formato (translation/rotation em radianos/
    scale) que o chamador (_store_widget_correction, em
    _apply_ik_joint_fixes) já espera.

    ⚠️ Verificado contra a documentação oficial, mas NÃO testado dentro
    do Blender de verdade (diferente do compute_pole_angle_edit, que se
    apoia numa fórmula já portada/testada) -- confira visualmente depois
    de gerar."""
    length_ratio = (old_length / new_length) if new_length > 1e-9 else 1.0

    # Matriz de rotação local, montada com os 3 eixos como COLUNAS.
    r_old = Matrix((old_axes[0], old_axes[1], old_axes[2])).transposed()
    r_new = Matrix((new_axes[0], new_axes[1], new_axes[2])).transposed()
    # Mapeia um vetor expresso no referencial ANTIGO pro referencial NOVO.
    r_delta = r_new.transposed() @ r_old  # r_new^-1 == r_new.transposed() (matriz ortogonal)

    new_translation = length_ratio * (r_delta @ Vector(old_translation))
    new_scale = tuple(s * length_ratio for s in old_scale)

    old_rot_matrix = Euler(old_rotation, "XYZ").to_matrix()
    new_rot_matrix = r_delta @ old_rot_matrix
    new_rotation = tuple(new_rot_matrix.to_euler("XYZ"))

    return tuple(new_translation), new_rotation, new_scale


SHAPE_EDIT_BORDER_COLOR = (1.0, 0.85, 0.1, 0.9)  # amarelo -- ver comentário acima pra trocar
SHAPE_EDIT_BORDER_THICKNESS = 2  # pixels -- v0.8: 4px ficou grosso demais (ver print do usuário), AniMatePro
# (referência de estilo, borda vermelha do Auto Keying) usa uma linha bem mais fina que isso.

# v0.9 -- texto "Shape Edit Mode" no topo da viewport, mesma cor da
# borda, pra reforçar visualmente o estado sem precisar olhar o painel
# lateral. Desenhado com blf (texto 2D da própria API do Blender, não
# geometria) DENTRO da region "WINDOW" do SpaceView3D -- a MESMA region
# em que a borda já é desenhada (ver register_shape_edit_border, mais
# abaixo: draw_handler_add(..., "WINDOW", "POST_PIXEL")). O header do
# viewport (onde ficam os menus View/Select/Add, o dropdown de modo
# etc.) é uma region SEPARADA ("HEADER"), não sobreposta à "WINDOW" no
# sistema de layout do Blender -- então não tem como este texto, desenhado
# só dentro dos limites de region.width/region.height da "WINDOW",
# desenhar por cima do header, mesmo com o header no topo (posição
# padrão) ou embaixo (se o usuário tiver movido). Sombra sutil (texto
# preto 1px atrás do amarelo) só pra manter legibilidade em fundos claros.
SHAPE_EDIT_BORDER_TEXT = "Shape Edit Mode"
SHAPE_EDIT_BORDER_TEXT_SIZE = 16  # pt
SHAPE_EDIT_BORDER_TEXT_PADDING = 34  # pixels entre a borda de cima e o texto -- ver
# comentário em _draw_shape_edit_border_text: mesmo o header NUNCA sendo desenhado
# por cima (region diferente, ver comentário grande acima), 10px (valor anterior)
# deixava o texto visualmente "colado" na linha do header, sem respiro nenhum --
# 34px dá uma folga real, suficiente pra qualquer tema/escala de UI comum.
SHAPE_EDIT_BORDER_TEXT_SHADOW_COLOR = (0.0, 0.0, 0.0, 0.6)

_shape_edit_border_shader = None
_shape_edit_border_handler = None


def register_shape_edit_border():
    """Registra o draw_handler_add global (uma vez por SESSÃO do
    Blender, não por Armature -- ver comentário grande acima sobre o
    porquê) -- chamado por rigger/__init__.py.register(). Fica como
    função aqui (em vez de __init__.py mexer direto nos globals
    _shape_edit_border_* de fora) pra não expor esse estado interno do
    módulo pra quem registra o pacote."""
    global _shape_edit_border_handler
    if _shape_edit_border_handler is None:
        _shape_edit_border_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_shape_edit_border, (), "WINDOW", "POST_PIXEL"
        )


def unregister_shape_edit_border():
    """Contrário de register_shape_edit_border() -- chamado por
    rigger/__init__.py.unregister()."""
    global _shape_edit_border_handler, _shape_edit_border_shader
    if _shape_edit_border_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_shape_edit_border_handler, "WINDOW")
        _shape_edit_border_handler = None
    _shape_edit_border_shader = None


def _draw_shape_edit_border():
    context = bpy.context
    obj = context.active_object
    if obj is None or obj.type != "ARMATURE" or not getattr(obj.data, "hytale_shape_edit_mode", False):
        return
    region = context.region
    if region is None or region.width <= 0 or region.height <= 0:
        return

    global _shape_edit_border_shader
    if _shape_edit_border_shader is None:
        _shape_edit_border_shader = gpu.shader.from_builtin("UNIFORM_COLOR")

    w, h = region.width, region.height
    t = SHAPE_EDIT_BORDER_THICKNESS
    # Quatro faixas (baixo/cima/esquerda/direita) formando uma moldura --
    # evita GL_LINE com largura (não confiável em core profile/todo
    # driver) em favor de quads preenchidos, cada um como 2 triângulos.
    coords = [
        (0, 0), (w, 0), (w, t), (0, t),                  # baixo
        (0, h - t), (w, h - t), (w, h), (0, h),           # cima
        (0, 0), (t, 0), (t, h), (0, h),                   # esquerda
        (w - t, 0), (w, 0), (w, h), (w - t, h),           # direita
    ]
    indices = [
        (0, 1, 2), (0, 2, 3),
        (4, 5, 6), (4, 6, 7),
        (8, 9, 10), (8, 10, 11),
        (12, 13, 14), (12, 14, 15),
    ]
    batch = batch_for_shader(_shape_edit_border_shader, "TRIS", {"pos": coords}, indices=indices)

    gpu.state.blend_set("ALPHA")
    _shape_edit_border_shader.bind()
    _shape_edit_border_shader.uniform_float("color", SHAPE_EDIT_BORDER_COLOR)
    batch.draw(_shape_edit_border_shader)
    gpu.state.blend_set("NONE")

    _draw_shape_edit_border_text(w, h, t)


def _draw_shape_edit_border_text(w, h, border_thickness):
    """Desenha SHAPE_EDIT_BORDER_TEXT centralizado horizontalmente, logo
    abaixo da faixa de cima da borda amarela -- ver comentário grande
    perto de SHAPE_EDIT_BORDER_TEXT sobre por que isso nunca cobre o
    header do viewport (region diferente). Chamado só por
    _draw_shape_edit_border, depois de desenhar a borda em si."""
    font_id = 0
    blf.size(font_id, SHAPE_EDIT_BORDER_TEXT_SIZE)
    text_width, text_height = blf.dimensions(font_id, SHAPE_EDIT_BORDER_TEXT)
    text_x = round((w - text_width) / 2.0)
    text_y = h - border_thickness - SHAPE_EDIT_BORDER_TEXT_PADDING - text_height

    # Sombra 1px (offset -1,-1) antes do texto real -- só legibilidade,
    # não é um segundo elemento visual por si (mesmo espírito do resto
    # do arquivo: cosmético, nunca essencial pra entender o estado).
    blf.color(font_id, *SHAPE_EDIT_BORDER_TEXT_SHADOW_COLOR)
    blf.position(font_id, text_x - 1, text_y - 1, 0)
    blf.draw(font_id, SHAPE_EDIT_BORDER_TEXT)

    blf.color(font_id, *SHAPE_EDIT_BORDER_COLOR)
    blf.position(font_id, text_x, text_y, 0)
    blf.draw(font_id, SHAPE_EDIT_BORDER_TEXT)


class RIG_OT_hytale_shape_edit_mode_enter(Operator):
    """Muta todo driver de custom_shape_scale_xyz do armature ativo (ver
    _iter_shape_scale_drivers) depois de resolver cada eixo mutado pro
    "tamanho cheio" (o alvo hoje embutido na expressão, não o valor
    avaliado no momento) -- deixa livre pro usuário redimensionar
    qualquer custom shape em Pose Mode sem o driver de FK/IK
    sobrescrevendo o valor. Troca pra Pose Mode automaticamente se o
    armature não estiver nele ainda (é onde o Item/Bone panel expõe
    Custom Shape > Scale pra edição)."""

    bl_idname = "armature.hytale_shape_edit_mode_enter"
    bl_label = "Shape Edit Mode"
    bl_description = (
        "Mute the FK/IK shape-scale drivers so you can freely resize each control's custom shape -- use "
        "'Finish Shape Edit Mode' afterwards to lock in the new size as the driver's new max value"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            return False
        armature = obj.data
        if not armature_has_generated_bones(armature):
            cls.poll_message_set("Run 'Create Rig' first -- there's no generated rig on this armature yet.")
            return False
        if getattr(armature, "hytale_shape_edit_mode", False):
            cls.poll_message_set("Already in Shape Edit Mode.")
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        armature = obj.data

        if obj.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")

        muted = 0
        for pb, i, fcurve in _iter_shape_scale_drivers(obj):
            driver = fcurve.driver
            match = _SHAPE_SCALE_DRIVER_VALUE_RE.match(driver.expression or "")
            if match:
                pb.custom_shape_scale_xyz[i] = float(match.group(1))
            fcurve.mute = True
            muted += 1

        armature.hytale_shape_edit_mode = True
        _redraw_all_areas(context)  # v0.8 -- pra borda amarela (ver _draw_shape_edit_border) aparecer na hora
        if muted:
            self.report(
                {"INFO"},
                f"Shape Edit Mode on -- {muted} shape-scale driver channel(s) muted at full size. Resize custom "
                f"shapes freely, then use 'Finish Shape Edit Mode' to save.",
            )
        else:
            self.report(
                {"INFO"},
                "Shape Edit Mode on -- this armature has no FK/IK shape-scale drivers, so every custom shape was "
                "already freely editable. Use 'Finish Shape Edit Mode' when done.",
            )
        return {"FINISHED"}


class RIG_OT_hytale_shape_edit_mode_finish(Operator):
    """Contrário de RIG_OT_hytale_shape_edit_mode_enter: pra cada driver
    de custom_shape_scale_xyz que ESTE armature tem hoje mutado (ver
    _iter_shape_scale_drivers + o guard `if not fcurve.mute: continue`
    -- nunca mexe num driver que não foi mutado por Enter), lê o valor
    que o usuário deixou no pose bone e o grava como o novo "tamanho
    cheio" na expressão (substitui só o número, mantém "*switch" ou
    "*(1 - switch)" como estava), depois desmuta. Não força volta de
    modo -- o usuário provavelmente ainda quer continuar em Pose Mode
    depois de terminar."""

    bl_idname = "armature.hytale_shape_edit_mode_finish"
    bl_label = "Finish Shape Edit Mode"
    bl_description = (
        "Lock in the custom shape sizes set while in Shape Edit Mode as the new max size, and restore the "
        "FK/IK shape-scale drivers"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            return False
        if not getattr(obj.data, "hytale_shape_edit_mode", False):
            cls.poll_message_set("Not currently in Shape Edit Mode.")
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        armature = obj.data

        restored = 0
        for pb, i, fcurve in _iter_shape_scale_drivers(obj):
            driver = fcurve.driver
            if not fcurve.mute:
                # Não foi este Enter que mutou (ex.: "Create Rig" rodou de novo no meio do Shape Edit Mode e
                # recriou o driver do zero, já desmutado -- ver aviso sobre o poll de RIG_OT_hytale_generate_rig
                # logo abaixo; isso não deveria mais acontecer, mas o guard fica por segurança).
                continue
            new_value = _format_shape_scale_literal(float(pb.custom_shape_scale_xyz[i]))
            if "(1 - switch)" in (driver.expression or ""):
                driver.expression = f"{new_value}*(1 - switch)"
            else:
                driver.expression = f"{new_value}*switch"
            fcurve.mute = False
            restored += 1

        armature.hytale_shape_edit_mode = False
        _redraw_all_areas(context)  # v0.8 -- pra borda amarela (ver _draw_shape_edit_border) sumir na hora
        self.report(
            {"INFO"},
            f"Shape Edit Mode off -- {restored} shape-scale driver channel(s) restored, new size(s) saved as "
            f"the max value.",
        )
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Operador: Mirror Shape (Tarefa D -- feature nova)
#
# Copia custom_shape_translation/_rotation_euler/_scale_xyz do bone ATIVO
# pro bone do lado oposto (L- <-> R-), só disponível durante Shape Edit
# Mode (mesmo poll "tem que estar em Shape Edit Mode" das outras
# operações desta família -- editar o scale fora do modo mexeria no
# valor JÁ AVALIADO pelo driver de FK/IK, não no alvo "cheio", e o
# resultado dependeria de qual lado do switch estava ativo no momento;
# ver resolve_custom_shape_scale()/RIG_OT_hytale_shape_edit_mode_enter
# acima pro mesmo cuidado com esse valor).
# ---------------------------------------------------------------------------


def _mirrored_bone_name(name):
    """Troca o prefixo 'L-' por 'R-' (ou vice-versa) no INÍCIO do nome --
    mesma convenção L-/R- que o resto do addon já usa (ver
    PARENT_OVERRIDE_ALIASES, ARM_COLLECTION_ROOTS etc. em constants.py,
    e _classify_chain_limb/side, na seção de Helpers deste arquivo) pra
    identificar o lado de um bone. Retorna None se `name` não começar
    com nenhum dos dois prefixos -- não tenta adivinhar nada além disso
    (bones sem lado, como root.master_CTRL ou Head_CTRL, não têm
    "oposto" nenhum).

    Não havia nenhuma função pronta de "nome espelhado" em rigger.py
    antes desta Tarefa -- os outros lugares que precisam do lado
    (_LIMB_SIDE_TO_COLLECTION, PARENT_OVERRIDE_ALIASES) trabalham a
    partir de item.side (um Enum já resolvido), não do texto do nome do
    bone, então não havia nada pra reaproveitar; esta é nova, mas segue a
    MESMA convenção de prefixo já usada em todo o resto do arquivo."""
    if name.startswith("L-"):
        return "R-" + name[len("L-"):]
    if name.startswith("R-"):
        return "L-" + name[len("R-"):]
    return None


class RIG_OT_hytale_mirror_shape(Operator):
    """Copia o custom shape (translation/rotation/scale) do bone ativo pro
    bone do lado oposto (L-/R-), invertendo só o eixo X da translation --
    mesma convenção de mirror em X que o resto do addon usa pra L-/R.
    Rotation e scale são copiados DIRETO, sem inverter nada: um custom
    shape não tem handedness (ao contrário de uma transform completa de
    edit bone), então não existe "espelhar rotação/escala" aqui -- só a
    POSIÇÃO em X muda de lado."""

    bl_idname = "armature.hytale_mirror_shape"
    bl_label = "Mirror Shape"
    bl_description = "Copy this bone's custom shape transform to its L-/R- opposite, mirrored on X"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            return False
        if not getattr(obj.data, "hytale_shape_edit_mode", False):
            cls.poll_message_set("Only available during Shape Edit Mode.")
            return False
        active_pb = context.active_pose_bone
        if active_pb is None or _mirrored_bone_name(active_pb.name) is None:
            cls.poll_message_set("Active bone must start with 'L-' or 'R-' to have a mirror target.")
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        source = context.active_pose_bone
        target_name = _mirrored_bone_name(source.name)
        target = obj.pose.bones.get(target_name)
        if target is None:
            self.report({"WARNING"}, f"Mirror target '{target_name}' not found on this armature.")
            return {"CANCELLED"}

        src_translation = source.custom_shape_translation
        target.custom_shape_translation = (
            -src_translation[0], src_translation[1], src_translation[2],
        )
        target.custom_shape_rotation_euler = tuple(source.custom_shape_rotation_euler)
        target.custom_shape_scale_xyz = tuple(source.custom_shape_scale_xyz)

        self.report({"INFO"}, f"Mirrored '{source.name}' custom shape onto '{target_name}'.")
        return {"FINISHED"}



# ---------------------------------------------------------------------------
# PropertyGroup: uma entrada de "Collection Settings" (v0.9, Etapa 1) --
# nome livre + em qual das duas raízes fixas (Main ou Face) ela mora.
# Puramente organizacional: existe pra alimentar (1) o dropdown
# "Collection" de HytaleIKChainItem logo abaixo, e (2) a criação/
# atribuição da collection de bones DE VERDADE em
# _apply_bone_collection_overrides, quando "Create Rig" roda -- até lá é
# só um nome numa lista, igual hytale_ik_chains já funciona pro resto do
# Bone Settings. Não guarda NENHUMA referência a bone -- quem entra em
# qual collection é decidido de novo a cada "Create Rig", olhando pro
# `collection_override` de cada item de hytale_ik_chains (ou nada, se o
# usuário deixou "Auto").
# ---------------------------------------------------------------------------
def _on_collection_grid_update(self, context):
    """update= de HytaleBoneCollectionItem.row/column -- roda toda vez
    que o usuário edita um desses dois campos direto na UI (o dropdown
    "Collection" de "Collection Settings", ver interface.py). Resolve
    `sync_bone_collection_order` só POR NOME (não por import direto no
    topo do arquivo) porque essa função só é definida mais abaixo neste
    mesmo módulo -- Python resolve isso na hora de EXECUTAR a função,
    não na hora de definir HytaleBoneCollectionItem, então não é um
    problema de ordem (mesmo motivo pelo qual RIG_OT_hytale_bone_
    collection_add/remove/move, também definidos antes, já conseguem
    chamar sync_bone_collection_order sem problema)."""
    obj = context.active_object
    if obj is not None and obj.type == "ARMATURE":
        sync_bone_collection_order(obj.data)
        _redraw_all_areas(context)


# v0.9.6 -- identificador reservado pro item "Main (root)" do dropdown
# de Parent (ver _parent_collection_enum_items/HytaleBoneCollectionItem.
# parent abaixo) -- "não tem parent" = fica direto embaixo de Main, a
# ÚNICA raiz fixa que sobrou (Face deixou de ser hardcoded -- pedido
# explícito: "remover a collection Face", ver changelog). Feio de
# propósito (duplo underscore) pra não colidir por acaso com um nome
# de collection que o usuário digitar.
PARENT_COLLECTION_ROOT = "__MAIN_ROOT__"

# Cache reaproveitado por _parent_collection_enum_items, mesmo motivo
# de _bone_collection_enum_cache logo abaixo (bug conhecido do Blender
# com EnumProperty(items=<função>) que devolve lista nova a cada
# chamada).
_parent_collection_enum_cache = []


def _parent_collection_enum_items(self, context):
    """items= de HytaleBoneCollectionItem.parent E do `parent` do
    operador RIG_OT_hytale_bone_collection_add (mesma função pros dois
    -- ver lá) -- lista TODAS as outras entradas de armature.hytale_
    bone_collections como opção de parent (permite aninhar QUALQUER
    collection dentro de qualquer outra, pedido explícito: "usar o Head
    como parent" de uma nova collection), mais o sentinel
    PARENT_COLLECTION_ROOT ("Main (root)") pra quem não quer aninhar em
    nada -- vai direto embaixo de Main.

    `getattr(self, "name", None)` exclui o PRÓPRIO item da lista (uma
    collection não pode ser parent de si mesma) quando `self` é um
    HytaleBoneCollectionItem de verdade sendo editado; quando `self` é
    o operador Add (criando uma entrada NOVA, que ainda nem tem nome
    na lista), isso simplesmente não exclui nada -- sem erro, mesmo
    código pros dois casos.

    NÃO detecta ciclos mais profundos (A -> B -> A) aqui -- isso é
    responsabilidade de _resolve_collection_parent (que tem uma guarda
    de `visited` e cai pra Main como fallback seguro se topar com um
    ciclo em tempo de "Create Rig"); police isso na hora de MONTAR a
    lista seria caro (teria que andar a árvore inteira a cada redraw) e
    a guarda de resolução já cobre o caso de quebrar, então não trava o
    Blender de jeito nenhum, só cai pro fallback.

    Mesma proteção de contexto=None que _bone_collection_enum_items já
    tem (ver comentário lá) -- Blender chama isto com self=None,
    context=None em tempo de registro pra validar o `default=0`."""
    armature = None
    edit_obj = getattr(context, "edit_object", None)
    if edit_obj is not None and edit_obj.type == "ARMATURE":
        armature = edit_obj.data
    if armature is None:
        obj = getattr(context, "active_object", None)
        if obj is not None and obj.type == "ARMATURE":
            armature = obj.data

    exclude_name = getattr(self, "name", None)

    _parent_collection_enum_cache.clear()
    _parent_collection_enum_cache.append(
        (PARENT_COLLECTION_ROOT, "Main (root)", "No parent -- goes directly under 'Main'")
    )
    if armature is not None:
        for item in armature.hytale_bone_collections:
            if not item.name or item.name == exclude_name:
                continue
            _parent_collection_enum_cache.append(
                (item.name, item.name, f"Nest under '{item.name}'")
            )
    return _parent_collection_enum_cache


class HytaleBoneCollectionItem(PropertyGroup):
    name: StringProperty(
        name="Name",
        description="Bone collection name, as it will appear both here and in the real Blender bone "
        "collections list after 'Create Rig'",
        default="Collection",
    )
    # v0.9.6 -- ERA um EnumProperty fixo (Main/Face) -- agora qualquer
    # collection criada aqui pode ser o parent de qualquer outra
    # (aninhamento livre, pedido explícito), com "Main" como a única
    # raiz que sempre existe. Ver _resolve_collection_parent pra como
    # isso vira uma bone collection REAL (com toda a cadeia de
    # ancestrais) em "Create Rig".
    parent: EnumProperty(
        name="Parent",
        description="Which other collection (created here) this one is nested under -- 'Main (root)' "
        "means no parent, straight under 'Main'",
        items=_parent_collection_enum_items,
        default=0,
    )
    # v0.9.6 -- controla só se aparece um botão de mostrar/esconder pra
    # esta collection na box "Bone Collections" da aba Animation (pedido
    # explícito: "às vezes queremos criar uma collection, mas ela não
    # apareça na UI"). NÃO afeta nada mais -- a collection continua
    # sendo criada normalmente em "Create Rig", continua disponível no
    # dropdown "Collection" de Bone Settings, continua aparecendo no
    # painel nativo "Bone Collections" do Blender (isso é controlado
    # pelo próprio Blender, fora do nosso alcance) -- só o BOTÃO nesta
    # box nossa que some.
    show_in_animation_tab: BoolProperty(
        name="Show in Animation Tab",
        description="Whether a visibility toggle button for this collection appears in the Animation "
        "tab's 'Bone Collections' box. Off just hides the button here -- the collection itself is "
        "unaffected everywhere else",
        default=True,
    )
    # v0.9.5 -- layout em grade (pedido explícito, pra poder pôr duas
    # collections lado a lado -- ex. "Arm R"/"Arm L" na mesma linha --
    # em vez de uma embaixo da outra). row = linha (0 = topo, quanto
    # maior, mais pra baixo); column = coluna (0 = mais à esquerda,
    # quanto maior, mais à direita). Duas entradas com o MESMO row
    # aparecem lado a lado, ordenadas por column; column empatada
    # desempata por ordem alfabética do nome (`name`) -- ver
    # _collection_sort_key. Essa ordenação (row, column, name) SUBSTITUI
    # a ordem "crua" da lista (a que os botões ▲▼ do Collection Settings
    # movem) como fonte de verdade pra tudo que É desenhado a partir daqui
    # (painel nativo "Bone Collections", as duas boxes da aba Animation)
    # -- ▲▼ continuam existindo só pra reorganizar a lista em si (edição
    # mais fácil), não têm mais efeito sobre o layout final. v0.9.6: row/
    # column são relativos aos IRMÃOS (mesmo parent), não à lista
    # inteira -- dois itens com parents diferentes podem ter o mesmo
    # (row, column) sem conflito nenhum (cada nível da árvore tem sua
    # própria grade).
    row: IntProperty(
        name="Row",
        description="Vertical position among siblings (0 = top, higher = further down). Siblings sharing "
        "the same Row are placed side by side on the same line, ordered by Column",
        default=0, min=0,
        update=_on_collection_grid_update,
    )
    column: IntProperty(
        name="Column",
        description="Horizontal position within the Row (0 = leftmost, higher = further right). Entries "
        "with the same Row AND Column are ordered alphabetically",
        default=0, min=0,
        update=_on_collection_grid_update,
    )


# Cache reaproveitado por _bone_collection_enum_items -- ver comentário
# em HytaleIKChainItem.collection_override sobre por que isso não pode
# virar uma lista nova a cada chamada (bug conhecido do Blender com
# EnumProperty(items=<função>)).
_bone_collection_enum_cache = []

# v0.9.3 -- identificador do item "Auto" do dropdown de Collection.
# ERA "" (string vazia) -- Blender tem um bug/quirk conhecido em
# EnumProperty com `items` dinâmico onde um item cujo IDENTIFICADOR é
# string vazia faz o próprio BOTÃO do dropdown mostrar EM BRANCO (sem
# texto nenhum) em vez do label "Auto (default)" -- foi exatamente o
# bug relatado: "quando está vazio, fica literalmente vazio". Trocar
# pra um identificador de verdade ("AUTO") resolve -- todo código que
# LÊ collection_override precisa comparar contra COLLECTION_OVERRIDE_AUTO
# (não contra "" nem contra falsy), ver _apply_bone_collection_overrides.
COLLECTION_OVERRIDE_AUTO = "AUTO"


def _bone_collection_enum_items(self, context):
    # v0.9.4 -- FIX registration crash: quando a EnumProperty declara
    # `default=` (ver collection_override abaixo), o Blender chama ESTA
    # função uma vez em tempo de REGISTRO pra validar que o default
    # existe entre os items -- e passa `context=None` nessa chamada (não
    # tem um context de UI de verdade ainda). A versão anterior fazia
    # `context.active_object` direto, sem checar None antes -> AttributeError
    # ("'NoneType' object has no attribute 'active_object'"), que o
    # Blender reporta só como "EnumProperty could not register (see
    # previous error)" -- o erro de verdade fica um pouco acima no
    # console. `getattr(context, ..., None)` em vez de acesso direto
    # resolve pros dois casos (context=None em registro, context real
    # depois em draw()).
    armature = None
    edit_obj = getattr(context, "edit_object", None)
    if edit_obj is not None and edit_obj.type == "ARMATURE":
        armature = edit_obj.data
    if armature is None:
        obj = getattr(context, "active_object", None)
        if obj is not None and obj.type == "ARMATURE":
            armature = obj.data

    _bone_collection_enum_cache.clear()
    _bone_collection_enum_cache.append(
        (COLLECTION_OVERRIDE_AUTO, "Auto (default)",
         "Use the built-in collection for this chain type (Arm L/Arm R/Leg L/Leg R/Head/Spine/Main-Tail)")
    )
    if armature is not None:
        for item in armature.hytale_bone_collections:
            if not item.name:
                continue
            parent_label = "Main" if item.parent in ("", PARENT_COLLECTION_ROOT) else item.parent
            _bone_collection_enum_cache.append(
                (item.name, item.name, f"Assign to '{item.name}' (under {parent_label})")
            )
    return _bone_collection_enum_cache


# v0.9.9 -- extraído de dentro de ensure_default_bone_collections pra
# virar uma constante reutilizável em nível de módulo -- usada tanto lá
# (seed inicial) quanto em RIG_OT_hytale_bone_collection_reset_grid
# (botão "Reset Row/Column to Defaults", pra corrigir armatures que já
# tinham essas 10 entradas de ANTES do Row/Column existir como campo --
# nesse caso elas ficaram travadas em row=0/column=0 pra sempre, já que
# o seed só roda uma vez -- ver hytale_bone_collections_initialized).
# (nome, row, column) -- mesmo agrupamento visual que a aba Animation
# sempre teve por padrão, só que agora é DADO em vez de código fixo.
_DEFAULT_BONE_COLLECTION_GRID = (
    (COLL_MAIN_HEAD, 0, 0),
    (COLL_MAIN_SPINE, 1, 0),
    (COLL_MAIN_BODY, 2, 0),
    (COLL_MAIN_ARM_R, 3, 0),
    (COLL_MAIN_ARM_L, 3, 1),
    (COLL_MAIN_LEG_R, 4, 0),
    (COLL_MAIN_LEG_L, 4, 1),
    (COLL_MAIN_ROOT, 5, 0),
    (COLL_MAIN_TAIL, 6, 0),
    (COLL_ATTACHMENTS, 7, 0),
)


def ensure_default_bone_collections(armature):
    """Semeia armature.hytale_bone_collections com as 10 entradas que
    hoje são fixas em código (COLL_MAIN_HEAD/SPINE/BODY/ARM_L/ARM_R/
    LEG_L/LEG_R/ROOT/TAIL/COLL_ATTACHMENTS -- ver constants.py) -- só na
    PRIMEIRA vez que a box "Collection Settings" é desenhada pra este
    armature (guardado em hytale_bone_collections_initialized). Depois
    disso o usuário pode apagar/renomear/reordenar/reparent à vontade
    sem que essas 10 voltem sozinhas -- ver DEVELOPER_NOTES.md sobre
    esse fluxo. Chamada de dentro de um execute() de operador
    (RIG_OT_hytale_generate_rig, RIG_OT_hytale_bone_collection_load_defaults)
    ou do handler automático abaixo -- NUNCA de dentro de draw()
    (Blender recusa escrever em dados de ID nesse contexto -- ver
    _seed_active_armature_bone_collections).

    v0.9.5 -- row/column também semeados aqui, reproduzindo o layout que
    era hardcoded em _ANIM_COLLECTION_ROWS (interface.py) antes da
    grade virar configurável: Arm R/Arm L na mesma linha, Leg R/Leg L
    na mesma linha, resto uma coluna só. v0.9.7 -- Attachments entrou
    nessa lista (antes era uma raiz separada, fora de Main e fora de
    Collection Settings por completo -- pedido explícito: "precisa ser
    criada dentro do Main e aparecer como aquelas collections
    defaults... configurável"), na última row (abaixo de Tail)."""
    if armature.hytale_bone_collections_initialized:
        return
    for name, row, column in _DEFAULT_BONE_COLLECTION_GRID:
        item = armature.hytale_bone_collections.add()
        item.name = name
        item.parent = PARENT_COLLECTION_ROOT
        item.row = row
        item.column = column
    armature.hytale_bone_collections_initialized = True


def _collection_sort_key(item):
    """v0.9.5 -- chave de ordenação (row, column, name) usada em TODO
    lugar que precisa decidir a ordem/posição de exibição de uma
    collection a partir daqui (painel nativo "Bone Collections" via
    sync_bone_collection_order, as duas boxes da aba Animation em
    interface.py) -- ver HytaleBoneCollectionItem.row/column pra regra
    completa. Centralizada aqui pra nunca divergir entre os três
    lugares que ordenam por ela. v0.9.6: row/column agora são relativos
    aos IRMÃOS (mesmo parent) -- ver sync_bone_collection_order, que já
    agrupa por parent ANTES de aplicar esta chave dentro de cada grupo."""
    return (item.row, item.column, item.name)


def _resolve_collection_parent(armature, item, visited=None):
    """v0.9.6 -- devolve a bone collection REAL (já criada, com
    ensure_bone_collection) que deve ser o PARENT de `item`, criando
    toda a cadeia de ancestrais que faltar no caminho (recursivo -- se
    o parent de `item` também não existir de verdade ainda, cria o
    parent DELE primeiro). PARENT_COLLECTION_ROOT (ou vazio, por
    segurança com dado antigo) = Main direto, a única raiz fixa que
    sobrou (Face deixou de ser hardcoded -- pedido explícito).

    `visited` protege contra ciclo (A -> B -> A, ou mais longo) que a
    UI não impede na hora de escolher o parent (ver
    _parent_collection_enum_items) -- se detectar que já passou por
    esse nome nesta MESMA chamada, cai pra Main como fallback seguro
    em vez de estourar recursão infinita. Mesmo tratamento pra um
    `parent` que aponta pra um nome que não existe mais na lista
    (renomeado/apagado) -- cai pra Main também, sem erro."""
    if visited is None:
        visited = set()
    parent_name = (item.parent or "").strip()
    if not parent_name or parent_name == PARENT_COLLECTION_ROOT:
        return ensure_bone_collection(armature, COLL_MAIN)
    if parent_name in visited:
        return ensure_bone_collection(armature, COLL_MAIN)  # ciclo detectado -- fallback seguro
    visited.add(parent_name)
    parent_item = next((c for c in armature.hytale_bone_collections if c.name == parent_name), None)
    if parent_item is None:
        return ensure_bone_collection(armature, COLL_MAIN)  # nome órfão (renomeado/apagado) -- fallback
    grandparent = _resolve_collection_parent(armature, parent_item, visited)
    return ensure_bone_collection(armature, parent_item.name, parent=grandparent)


def _head_spine_bone_names(item):
    """v0.9 (Etapa 2, ampliado na 2.7 pra ATTACHMENTS). Devolve a lista
    de nomes de bone configurados numa entrada HEAD, SPINE ou
    ATTACHMENTS (só os campos preenchidos, respeitando neck_count/
    spine_count/attachments_count -- ver HytaleIKChainItem) -- [] pra
    qualquer outro chain_type ou entrada sem nada preenchido ainda.
    Usada por _apply_bone_collection_overrides pra saber quais bones
    atribuir à collection (Head/Spine/Attachments por padrão, ou a
    escolhida em collection_override)."""
    if item.chain_type == "HEAD":
        slots = [item.neck_bone_1, item.neck_bone_2, item.neck_bone_3, item.neck_bone_4, item.neck_bone_5]
        names = slots[: item.neck_count] + [item.head_bone, item.head_end_bone]
    elif item.chain_type == "SPINE":
        slots = [item.spine_bone_1, item.spine_bone_2, item.spine_bone_3, item.spine_bone_4]
        names = [item.pelvis_bone] + slots[: max(0, item.spine_count - 1)]
    elif item.chain_type == "ATTACHMENTS":
        # v0.9.8 -- ERA uma lista de 5 nomes escritos na mão -- agora
        # lê só até item.attachments_count (nunca mais que isso, então
        # nem precisa checar getattr pros slots além dele -- os campos
        # attachment_bone_(count+1)..ATTACHMENTS_MAX_COUNT podem até
        # estar preenchidos de uma edição anterior com um count maior,
        # mas continuam ignorados aqui, igual já acontecia com HEAD/SPINE
        # e os slots que sobram além do count escolhido).
        names = [getattr(item, f"attachment_bone_{i}") for i in range(1, item.attachments_count + 1)]
    else:
        return []
    return [n for n in names if n]


def sync_bone_collection_order(armature):
    """v0.9 (Etapa 2, pedido explícito) -- reordena as bone collections
    REAIS do Blender (armature.collections, o que aparece no painel
    'Bone Collections' de Object Data Properties) pra bater com a
    árvore de armature.hytale_bone_collections (a lista editável de
    "Collection Settings" -- ver HytaleBoneCollectionItem.parent). Usa
    `child_number` (índice de uma bone collection DENTRO da lista de
    filhos do próprio parent -- mesma API que _move_main_child_before
    já usa, ver docstring lá pra detalhe de como setar child_number
    reposiciona) -- só reordena entradas que JÁ EXISTEM de verdade
    nesse armature; entradas que só existem na lista de config (nunca
    materializadas por um 'Create Rig') são ignoradas, sem erro.

    v0.9.5 -- a "ordem" vem de _collection_sort_key (row, column, name
    -- ver HytaleBoneCollectionItem), não mais da ordem crua da lista
    (a que os botões ▲▼ movem). O painel nativo do Blender não tem
    conceito de "coluna" -- é sempre uma lista vertical -- então aqui a
    grade (row, column) simplesmente vira uma ordem linear (row major,
    column como desempate), igual uma leitura de cima pra baixo e
    esquerda pra direita.

    v0.9.6 -- ERA hardcoded em só duas raízes (Main/Face) -- agora
    agrupa DINAMICAMENTE por parent resolvido (item.parent, ou "Main"
    se vazio/sentinel/órfão -- ver _resolve_collection_parent), então
    funciona pra qualquer profundidade de aninhamento (uma collection
    dentro de outra dentro de outra...) sem precisar saber de antemão
    quantos níveis existem. row/column de cada item são relativos aos
    IRMÃOS (mesmo grupo/parent), não à lista inteira -- por isso ordena
    DENTRO de cada grupo separadamente, não a lista toda de uma vez.

    Chamada em dois lugares: (1) sempre no fim de 'Create Rig' (idempotente),
    e (2) direto pelos operadores Add/Remove/Move/de Row/Column de
    Collection Settings (RIG_OT_hytale_bone_collection_*), pra a
    reordenação no painel nativo acontecer NA HORA, sem precisar rodar
    'Create Rig' de novo -- só afeta collections que já existem; se o
    personagem nunca gerou rig nenhum ainda, não há nada pra reordenar
    (sem erro, sem-op)."""
    groups = {}  # nome do parent resolvido -> [HytaleBoneCollectionItem, ...]
    for item in armature.hytale_bone_collections:
        if not item.name:
            continue
        parent_name = (item.parent or "").strip()
        if not parent_name or parent_name == PARENT_COLLECTION_ROOT:
            parent_name = COLL_MAIN
        groups.setdefault(parent_name, []).append(item)

    for parent_name, children in groups.items():
        parent_coll = _find_bone_collection_anywhere(armature, parent_name)
        if parent_coll is None:
            continue  # parent ainda não materializado de verdade -- nada a reordenar aqui
        for target_index, child_item in enumerate(sorted(children, key=_collection_sort_key)):
            child = next((c for c in parent_coll.children if c.name == child_item.name), None)
            if child is None:
                continue  # este filho ainda não materializado de verdade -- nada a reordenar
            try:
                if child.child_number != target_index:
                    child.child_number = target_index
            except Exception:
                pass  # cosmético -- não impede o rig de funcionar



# ---------------------------------------------------------------------------
# v0.9.2 -- seed automático de hytale_bone_collections, sem precisar de
# clique no botão "Load Default Collections". draw() não pode escrever
# em dados de ID (ver changelog/erro real: "Writing to ID classes in
# this context is not allowed"), então o seed precisa rodar de fora de
# qualquer draw() -- um handler de bpy.app.handlers.depsgraph_update_post
# é o jeito padrão do Blender de rodar código com permissão de escrita
# de forma automática/silenciosa, sem o usuário precisar clicar em nada.
#
# Custo: depsgraph_update_post dispara com MUITA frequência (qualquer
# mudança na cena) -- por isso o handler abaixo é propositalmente
# barato: só olha pro objeto ATIVO (não escaneia todo bpy.data.armatures
# a cada chamada), e a primeira linha de ensure_default_bone_collections
# já sai fora se hytale_bone_collections_initialized for True -- ou
# seja, depois da primeira vez que um dado Armature aparece como ativo,
# vira só uma leitura de bool, praticamente grátis.
# ---------------------------------------------------------------------------
def _seed_active_armature_bone_collections(scene=None, depsgraph=None):
    obj = bpy.context.active_object
    if obj is None or obj.type != "ARMATURE":
        return
    armature = obj.data
    if armature.hytale_bone_collections_initialized:
        return
    ensure_default_bone_collections(armature)


def register_bone_collection_defaults_handler():
    """Registra o handler acima (uma vez por SESSÃO do Blender, mesmo
    espírito de register_shape_edit_border) -- chamado por
    rigger/__init__.py.register()."""
    if _seed_active_armature_bone_collections not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_seed_active_armature_bone_collections)


def unregister_bone_collection_defaults_handler():
    """Contrário de register_bone_collection_defaults_handler() --
    chamado por rigger/__init__.py.unregister()."""
    if _seed_active_armature_bone_collections in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_seed_active_armature_bone_collections)


# ---------------------------------------------------------------------------
# PropertyGroup: um item = uma cadeia de IK inteira, referenciada por nome
# ---------------------------------------------------------------------------


class HytaleIKChainItem(PropertyGroup):
    # v0.7: cada item da lista agora descreve um "tipo" de bone/estrutura,
    # não só uma cadeia de IK genérica -- ARM e LEG usam EXATAMENTE a
    # mesma lógica de geração que a antiga "IK Chain" única (mesmos
    # campos root_bone/tip_bone/pole_bone/parent_override, mesmo
    # _build_ik_layer/_build_pose_constraints); a única diferença hoje é
    # o RÓTULO desses campos na UI, por tipo (ver interface.py). TAIL é
    # o primeiro tipo genuinamente diferente: sem IK, sem pole/lado --
    # ver _build_tail_layer/_build_tail_pose_constraints. Novos tipos
    # (orelha, asa, etc.) entram aqui no futuro do mesmo jeito.
    #
    # v0.9 (Etapa 2) -- HEAD e SPINE são o segundo tipo genuinamente
    # diferente: NÃO criam bone nenhum (diferente de Arm/Leg/Tail) --
    # só REFERENCIAM bones _CTRL que já existem (o loop genérico cria um
    # _CTRL por bone ORG, sempre; ver _build_edit_bones), pra dar nome
    # explícito e configurável a quem antes era hardcoded (HEAD_COLLECTION_
    # ROOT/SPINE_COLLECTION_BONES, ver constants.py). Puramente
    # organizacional -- ver _head_spine_bone_names/_apply_bone_collection_
    # overrides. O comportamento HARDCODED antigo continua rodando
    # também (_build_main_collections, sem mudança nenhuma) -- uma
    # entrada HEAD/SPINE é um jeito OPCIONAL de apontar bones adicionais
    # (ou com nomenclatura diferente da 'Player') pra essas collections,
    # não uma substituição obrigatória.
    chain_type: EnumProperty(
        name="Type",
        description="What this entry configures. 'Arm'/'Leg' behave exactly like the old generic IK chain "
        "(root/tip/pole path -> switchable FK/IK chain) -- only the field labels differ today. 'Tail' has "
        "no IK: it builds a continuous '_Tail' bridge chain (always connected, no gap between segments) "
        "meant to be hooked into physics add-ons. 'Head'/'Spine'/'Attachments' create no bones at all -- "
        "they just identify existing control bones, for collection organization",
        items=[
            ("ARM", "Arm", "Two-segment limb (shoulder-arm-forearm-hand pattern) -- IK/FK-switchable chain"),
            ("LEG", "Leg", "Two-segment limb (pelvis-thigh-calf-foot pattern) -- IK/FK-switchable chain"),
            ("TAIL", "Tail", "Chain of bones from root to tip, no IK -- continuous bridge chain for physics"),
            ("HEAD", "Head", "Identifies the Neck (1-5 bones) + Head + Head End control bones -- no IK, "
             "organizational only"),
            ("SPINE", "Spine", "Identifies the Pelvis + Spine (1-4 bones) control bones -- no IK, "
             "organizational only"),
            ("ATTACHMENTS", "Attachments", "Identifies specific Attachment control bones (1-5) by name -- "
             "no IK, organizational only. Separate from (and in addition to) the automatic name-based "
             "attachment detection that already happens regardless of this entry"),
        ],
        default="ARM",
    )
    label: StringProperty(
        name="Label",
        description="Free-form name just to identify this entry in the list (e.g. Arm L)",
        default="",
    )
    root_bone: StringProperty(
        name="Root Bone",
        description="First bone of the chain (e.g. L-Arm, L-Thigh, or the first tail bone). For a chain with "
        "more than 2 segments in between (e.g. a 4-bone leg: Thigh/Calf/Heel/Foot), just point Root/Tip at "
        "the two ends -- the bones in between are resolved automatically by walking the skeleton",
        default="",
    )
    tip_bone: StringProperty(
        name="Tip Bone",
        description="Last bone of the chain -- the target/effector for Arm/Leg (e.g. L-Hand, L-Foot), or "
        "the last tail bone for Tail",
        default="",
    )
    pole_bone: StringProperty(
        name="Pole Reference",
        description="Arm/Leg only. Bone used as the position/orientation reference for the pole target "
        "(e.g. L-Forearm). Empty = automatically uses the middle bone of the root->tip path",
        default="",
    )
    parent_override: StringProperty(
        name="Root Parent",
        description="Optional bone that becomes the parent of this chain's root (e.g. L-Shoulder_CTRL, "
        "Pelvis -- also used by Tail, to attach it to the body). Empty = left unparented. Some names are "
        "automatically resolved to utility bones that only exist after generation (see "
        "PARENT_OVERRIDE_ALIASES) -- e.g. typing 'Pelvis' resolves to 'root.pelvis_CTRL'.",
        default="",
    )
    tail_tip_rotation_axis: EnumProperty(
        name="Tip Rotation Axis",
        description="Tail only. Which LOCAL axis of the last bone the Tip Rotation angle rotates around -- "
        "X and Z bend the tail direction (perpendicular to the bone itself), Y just spins the roll in place. "
        "Which one lines up with the correction you want depends on how this specific bone's roll came out",
        items=[
            ("X", "X (Local)", "Local X axis"),
            ("Y", "Y (Local)", "Local Y axis (the bone's own direction -- spins roll only, doesn't bend it)"),
            ("Z", "Z (Local)", "Local Z axis"),
        ],
        default="Z",
    )
    tail_tip_rotation_deg: FloatProperty(
        name="Tip Rotation (deg)",
        description="Tail only. Extra rotation (degrees, around Tip Rotation Axis, LOCAL to the last bone) "
        "applied to its rest pose. The tip has no next segment to point its tail at, so by default it keeps "
        "the ORG's original (untouched) direction -- use this to manually angle it so it lines up visually "
        "with the rest of the chain",
        default=0.0,
    )
    side: EnumProperty(
        name="Side",
        description="Body side of this chain -- used by pole_angle presets (e.g. Arm mode) that need a "
        "different value per side",
        items=[
            ("LEFT", "Left", ""),
            ("RIGHT", "Right", ""),
            ("CENTER", "Center", ""),
        ],
        default="CENTER",
    )
    pole_invert: BoolProperty(
        name="Pole in Front (+Z)",
        description="Pole in front (positive Z axis of the reference bone) instead of behind (default, -Z)",
        default=False,
    )
    pole_distance: FloatProperty(
        name="Pole Distance",
        description="Distance from the pole target to the reference bone (pole_bone)",
        default=0.35,
        min=0.001,
    )
    pole_angle_mode: EnumProperty(
        name="Pole Angle Mode",
        items=[
            ("AUTO", "Auto", "Calculates pole_angle automatically from the rest pose -- works for ANY "
             "character, the safe starting point for a template that hasn't been calibrated yet"),
            ("PRESET", "Preset (from Template)", "Uses a calibrated value defined by the active rig "
             "template (see 'Pole Angle Preset' field below and the template's pole_angle_presets, keyed "
             "by the Side field) -- only makes sense if a template that actually defines that preset name "
             "was loaded via 'Load Hytale IK Chain Preset'. For a character with no calibrated preset yet, "
             "use Auto or Manual instead"),
            ("MANUAL", "Manual", "Uses the value typed in Pole Angle directly, without calculating anything "
             "-- the right way to hand-tune the pole for a character with no calibrated preset"),
        ],
        default="AUTO",
    )
    pole_angle_preset_name: StringProperty(
        name="Pole Angle Preset",
        description="Name of the entry (as defined in the active rig template's pole_angle_presets, e.g. "
        "'ARM') to use when Pole Angle Mode = Preset. Ignored in Auto/Manual mode",
        default="ARM",
    )
    pole_angle_manual: FloatProperty(
        name="Pole Angle (deg)",
        description="Final pole_angle value, used only in Manual mode. Suggested starting point: 90 or "
        "-90 (typical elbow/knee) -- adjust the sign/value visually until the pole centers",
        default=90.0,
    )
    pole_angle_fine_tune: FloatProperty(
        name="Pole Angle Fine-Tune (deg)",
        description="Added to the automatically calculated value -- used only in Auto mode",
        default=0.0,
    )
    extra_ik_location: BoolProperty(
        name="Also Copy Location on IK (root)",
        description="Adds IK_CopyLocation (with switch) to the MCH of this chain's root bone, in addition "
        "to Rotation/Scale. Needed when the root doesn't follow the normal ORG hierarchy (e.g. Thigh, "
        "parented to a shared root.pelvis_CTRL).",
        default=False,
    )
    # v0.9 (Etapa 2) -- campos exclusivos de HEAD. neck_count controla
    # quantos dos 5 slots neck_bone_1..5 aparecem na UI (0 = pescoço
    # direto no corpo, sem bone de neck nenhum) -- head_bone/head_end_bone
    # ficam sempre visíveis, fora da contagem (mesmo padrão do
    # "Neck Bones Amount" separado de "Head"/"Head End" no Auto Rig Pro,
    # referência usada pra esta feature).
    #
    # v0.9.3 -- IMPORTANTE: todos os campos abaixo (neck_bone_*/head_bone/
    # head_end_bone) esperam o nome do bone ORG (ex. "Head", "Neck"), a
    # MESMA convenção de root_bone/tip_bone em Arm/Leg -- NÃO o "_CTRL".
    # _apply_bone_collection_overrides soma SUFFIX_CTRL sozinho na hora
    # de decidir qual bone de verdade vai pra collection (é o _CTRL que
    # o usuário anima, não o ORG) -- ver bugfix no changelog.
    _HEAD_SPINE_FIELD_HINT = (
        " -- type/pick the ORIGINAL bone name (e.g. 'Head'), not '_CTRL': the matching control bone is "
        "resolved automatically"
    )
    neck_count: IntProperty(
        name="Neck Bones Amount",
        description="How many Neck bone fields to show below (0-5). Head/Head End are separate, always shown",
        default=1, min=0, max=5,
    )
    neck_bone_1: StringProperty(name="Neck", description="Original bone name" + _HEAD_SPINE_FIELD_HINT, default="")
    neck_bone_2: StringProperty(name="Neck 2", description="Original bone name" + _HEAD_SPINE_FIELD_HINT, default="")
    neck_bone_3: StringProperty(name="Neck 3", description="Original bone name" + _HEAD_SPINE_FIELD_HINT, default="")
    neck_bone_4: StringProperty(name="Neck 4", description="Original bone name" + _HEAD_SPINE_FIELD_HINT, default="")
    neck_bone_5: StringProperty(name="Neck 5", description="Original bone name" + _HEAD_SPINE_FIELD_HINT, default="")
    head_bone: StringProperty(
        name="Head",
        description="Head original bone (defaults to the same bone HEAD_COLLECTION_ROOT already points to "
        "for the 'Player' rig, minus the '_CTRL' suffix -- see constants.py)" + _HEAD_SPINE_FIELD_HINT,
        default="",
    )
    head_end_bone: StringProperty(
        name="Head End",
        description="Optional bone at the very tip of the head (e.g. a jaw/chin end bone) -- leave empty "
        "if this rig doesn't have one" + _HEAD_SPINE_FIELD_HINT,
        default="",
    )
    # v0.9 (Etapa 2) -- campos exclusivos de SPINE. spine_count é o total
    # DE BONES DA CADEIA, Pelvis incluso (1 = só Pelvis, sem nenhum
    # Spine1/2/3/4) -- pelvis_bone sempre visível, spine_bone_1..4
    # mostrados conforme spine_count - 1 (mesmo padrão de "Spine Amount"
    # do Auto Rig Pro). Mesma convenção de nome ORG que HEAD, acima.
    spine_count: IntProperty(
        name="Spine Amount",
        description="Total number of bones in this spine, including Pelvis (1-5). E.g. 3 = Pelvis + Spine1 + Spine2",
        default=3, min=1, max=5,
    )
    pelvis_bone: StringProperty(name="Pelvis", description="Original bone name" + _HEAD_SPINE_FIELD_HINT, default="")
    spine_bone_1: StringProperty(name="Spine1", description="Original bone name" + _HEAD_SPINE_FIELD_HINT, default="")
    spine_bone_2: StringProperty(name="Spine2", description="Original bone name" + _HEAD_SPINE_FIELD_HINT, default="")
    spine_bone_3: StringProperty(name="Spine3", description="Original bone name" + _HEAD_SPINE_FIELD_HINT, default="")
    spine_bone_4: StringProperty(name="Spine4", description="Original bone name" + _HEAD_SPINE_FIELD_HINT, default="")
    # v0.9.7 -- campos exclusivos de ATTACHMENTS. Mesmo padrão de
    # HEAD/SPINE (amount + N campos de bone ORG) -- attachments_count é
    # simplesmente quantos dos slots attachment_bone_N aparecem na UI
    # (não tem um "sempre visível" tipo Head/Head End -- aqui todos os
    # slots são do mesmo tipo). Separado (e adicional a) a detecção
    # automática por nome que já roda sempre (is_attachment_bone, ver
    # _build_main_collections) -- serve pra apontar bones que não seguem
    # a convenção de nome esperada, ou só pra ter controle explícito de
    # quais vão pra qual collection via o dropdown "Collection" abaixo.
    #
    # v0.9.8 -- ERA só 5 slots fixos (attachment_bone_1..5, escritos na
    # mão igual neck_bone_1..5/spine_bone_1..4 acima) -- pedido
    # explícito pra um teto bem mais alto (25) sem precisar escrever 25
    # linhas repetidas nem ficar recontando toda vez que o número mudar.
    # ATTACHMENTS_MAX_COUNT (rigger/constants.py) é a ÚNICA fonte da
    # verdade pra esse teto -- pra mudar, edita só o número lá; nada
    # aqui (nem em interface.py, que também lê a mesma constante)
    # precisa mudar.
    #
    # Blender NÃO tem um "CampoDeTextoInfinito" de verdade dentro de um
    # PropertyGroup -- cada StringProperty precisa existir como um campo
    # de verdade, declarado como ANOTAÇÃO da classe (`nome: Tipo(...)`,
    # não atribuição direta -- Blender recusa registrar atribuição
    # direta nas versões atuais). O truque abaixo gera essas anotações
    # NUM LOOP em vez de escrever uma linha por campo: `__annotations__`
    # já existe neste ponto do corpo da classe (Python cria esse dict
    # sozinho assim que a PRIMEIRA anotação `campo: Tipo` aparece em
    # QUALQUER lugar do corpo -- e isso já aconteceu muito antes daqui,
    # com `label:` etc.) -- então só precisa inserir mais entradas nesse
    # MESMO dict, o que tem exatamente o mesmo efeito de ter escrito
    # `attachment_bone_7: StringProperty(...)` à mão, só que 25 vezes
    # automaticamente. `del _i` no final evita que a variável do loop
    # vaze como se fosse mais um campo da classe.
    attachments_count: IntProperty(
        name="Attachments Bones Amount",
        description=f"How many Attachment bone fields to show below (0-{ATTACHMENTS_MAX_COUNT})",
        default=1, min=0, max=ATTACHMENTS_MAX_COUNT,
    )
    for _i in range(1, ATTACHMENTS_MAX_COUNT + 1):
        __annotations__[f"attachment_bone_{_i}"] = StringProperty(
            name="Attachment" if _i == 1 else f"Attachment {_i}",
            description="Original bone name" + _HEAD_SPINE_FIELD_HINT,
            default="",
        )
    del _i
    # v0.9 -- Collection Settings (Etapa 1, Tail incluído na Etapa 3 --
    # nenhum tipo fica travado numa collection fixa, pedido explícito).
    # EnumProperty com `items` dinâmico (função, não lista fixa) --
    # populado a partir de armature.hytale_bone_collections (a lista
    # editável da nova box "Collection Settings"), pra sempre refletir o
    # que existe HOJE nesse armature, sem precisar duplicar/sincronizar
    # nomes na mão. Identificador COLLECTION_OVERRIDE_AUTO ("AUTO") =
    # comportamento antigo (cai na collection fixa Arm L/Arm R/Leg L/
    # Leg R/Main/Tail, exatamente como antes desta feature existir) --
    # ver _apply_bone_collection_overrides. v0.9.3: era string VAZIA
    # ("") antes -- trocado porque um item de EnumProperty dinâmico com
    # identificador "" faz o próprio botão do dropdown mostrar em
    # branco no Blender (bug relatado: "quando está vazio, fica
    # literalmente vazio").
    #
    # ATENÇÃO Blender: a função abaixo NÃO pode devolver uma lista nova
    # a cada chamada -- o Blender só garante que as strings dos itens
    # ficam vivas enquanto o mesmo objeto Python list que as contém
    # também ficar vivo; devolver uma lista recém-criada toda vez é a
    # causa mais comum de crash com EnumProperty dinâmico. Por isso
    # _bone_collection_enum_items reaproveita (limpa + repopula) o MESMO
    # objeto _bone_collection_enum_cache, em vez de `return [...]`.
    #
    # v0.9.4 -- FIX registro: "default" de um EnumProperty com `items`
    # DINÂMICO (função) só pode ser ÍNDICE (int), NUNCA string --
    # limitação documentada da própria API do Blender ("Strings cannot
    # be specified for dynamic enums"). Passar default=COLLECTION_OVERRIDE_AUTO
    # (string) foi exatamente a causa do erro "'collection_override'
    # EnumProperty could not register" -- default=0 funciona porque
    # _bone_collection_enum_items SEMPRE devolve COLLECTION_OVERRIDE_AUTO
    # como primeiro item (índice 0), então o efeito é idêntico.
    collection_override: EnumProperty(
        name="Collection",
        description="Which bone collection this chain's bones go into (Main or Face, as organized in "
        "'Collection Settings'). 'Auto (default)' keeps the built-in behavior -- Arm L/Arm R/Leg L/Leg R",
        items=_bone_collection_enum_items,
        default=0,
    )



# ---------------------------------------------------------------------------
# Operadores: gerenciar a lista de cadeias IK
# ---------------------------------------------------------------------------


class RIG_OT_hytale_ik_chain_add(Operator):
    """Adiciona uma entrada vazia à lista (preencha os nomes dos bones
    depois -- ou via um picker). v0.7: recebe `chain_type` (ARM/LEG/
    TAIL) -- quem decide QUAL tipo adicionar é o menu popup
    RIG_MT_hytale_ik_chain_add_menu (clicado a partir do botão "+" em
    interface.py), não mais um clique direto neste operador."""

    bl_idname = "armature.hytale_ik_chain_add"
    bl_label = "Add Hytale Bone Setting"
    bl_description = "Add an empty entry (Arm/Leg/Tail/Head/Spine) to the list"
    bl_options = {"REGISTER", "UNDO"}

    chain_type: StringProperty(default="ARM")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        item = chains.add()
        # String crua (não EnumProperty) no operador -- vem do menu popup
        # como texto fixo; valida contra os valores conhecidos do Enum
        # real (item.chain_type) antes de atribuir, pra nunca deixar a
        # entrada num estado inválido se o menu mandar algo inesperado.
        item.chain_type = self.chain_type if self.chain_type in {"ARM", "LEG", "TAIL", "HEAD", "SPINE", "ATTACHMENTS"} else "ARM"
        prefix = {"ARM": "Arm", "LEG": "Leg", "TAIL": "Tail", "HEAD": "Head", "SPINE": "Spine", "ATTACHMENTS": "Attachments"}.get(item.chain_type, "Chain")
        item.label = f"{prefix} {len(chains)}"
        # v0.8: pole_angle_preset_name (StringProperty) nasce com default=
        # "ARM" fixo na PROPRIA definição do campo (ver HytaleIKChainItem)
        # -- sem esta linha, TODO item novo (mesmo um Leg ou um Tail)
        # herdava literalmente o texto "ARM" no painel, mesmo sem nenhum
        # template carregado, e sem nenhuma relação com pole_angle_presets
        # de verdade nenhum -- só o valor cru do Enum/StringProperty. Seta
        # explícito pro nome do PRÓPRIO chain_type (mesma convenção usada
        # em templates/rig/rig_player.json -- ver _warn_shared_pole_angle_presets
        # acima) -- ainda é só um NOME (não precisa existir de verdade em
        # nenhum pole_angle_presets até o usuário realmente usar modo
        # Preset), mas pelo menos já nasce coerente com o tipo da cadeia,
        # em vez de sempre "ARM" nas pernas/caudas.
        item.pole_angle_preset_name = item.chain_type
        armature.hytale_ik_chains_index = len(chains) - 1
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_MT_hytale_ik_chain_add_menu(Menu):
    """Menu popup mostrado ao clicar o "+" da lista (ver interface.py) --
    pergunta QUE TIPO adicionar antes de criar o item, em vez de
    adicionar uma cadeia genérica direto (comportamento anterior a esta
    feature, v0.7). Cada opção só chama armature.hytale_ik_chain_add com
    um chain_type diferente -- nenhuma lógica própria, mesmo espírito de
    "interface.py só desenha" só que este menu mora aqui (não lá) porque
    é o rigger.py que sabe quais tipos existem hoje (ver
    HytaleIKChainItem.chain_type) -- adicionar um tipo novo no futuro é
    só acrescentar uma linha aqui, no Enum, e no dict de labels de
    interface.py."""

    bl_idname = "RIG_MT_hytale_ik_chain_add_menu"
    bl_label = "Add Bone Setting"

    def draw(self, context):
        layout = self.layout
        # v0.9.3 -- ordem pedida explicitamente: Head -> Spine -> Arm ->
        # Leg -> Tail (era Arm/Leg/Tail/Head/Spine, ordem de quando cada
        # tipo foi adicionado -- não tinha significado nenhum). v0.9.7:
        # Attachments entrou no fim, depois de Tail (pedido explícito).
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Head", icon="USER"
        ).chain_type = "HEAD"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Spine", icon="BONE_DATA"
        ).chain_type = "SPINE"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Arm", icon="CON_KINEMATIC"
        ).chain_type = "ARM"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Leg", icon="CON_KINEMATIC"
        ).chain_type = "LEG"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Tail", icon="PHYSICS"
        ).chain_type = "TAIL"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Attachments", icon="LINKED"
        ).chain_type = "ATTACHMENTS"


class RIG_OT_hytale_ik_chain_remove(Operator):
    """Remove uma cadeia da lista pelo índice (padrão: a ativa)."""

    bl_idname = "armature.hytale_ik_chain_remove"
    bl_label = "Remove Hytale IK Chain"
    bl_description = "Remove the selected IK chain from the list"
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
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_OT_hytale_ik_chain_move(Operator):
    """Reordena uma entrada da lista (armature.hytale_ik_chains) uma
    posição pra cima ou pra baixo, via CollectionProperty.move() --
    mesmo padrão que interface.py já usa pro par Add/Remove, só que
    aqui é um único operador com um `direction` (UP/DOWN) em vez de dois
    operadores separados, já que a lógica dos dois lados é idêntica
    (só troca o delta do índice). Reordenar é puramente cosmético/
    organizacional -- não afeta geração de rig nenhuma (RIG_OT_hytale_
    generate_rig lê hytale_ik_chains percorrendo a coleção inteira, sem
    depender de ordem -- ver _build_edit_bones), só a ordem em que as
    entradas aparecem na UIList."""

    bl_idname = "armature.hytale_ik_chain_move"
    bl_label = "Move Hytale Bone Setting"
    bl_description = "Move the selected entry up or down in the list"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=(
            ("UP", "Up", "Move the entry one position up"),
            ("DOWN", "Down", "Move the entry one position down"),
        ),
        default="UP",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE" and len(obj.data.hytale_ik_chains) > 1

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        index = armature.hytale_ik_chains_index
        target = index - 1 if self.direction == "UP" else index + 1
        if not (0 <= target < len(chains)):
            return {"CANCELLED"}
        chains.move(index, target)
        armature.hytale_ik_chains_index = target
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_OT_hytale_ik_chain_set_count(Operator):
    """Ajusta a lista de cadeias de IK pra ter exatamente `count` itens --
    adiciona vazias no fim ou remove do fim, sem tocar nas do meio. Não é
    chamado de lugar nenhum em interface.py hoje (a lista lá usa só Add/
    Remove, um item de cada vez, via RIG_OT_hytale_ik_chain_add/_remove) --
    existe pra uso via script/console externo, quando é mais prático setar
    a quantidade de uma vez. `chain_type` (v0.8) alinha o que este
    operador cria com RIG_MT_hytale_ik_chain_add_menu/RIG_OT_hytale_ik_chain_add
    acima: mesma validação (cai pra "ARM" se vier algo fora de ARM/LEG/
    TAIL) e mesmo prefixo de label ("Arm N"/"Leg N"/"Tail N", não mais o
    "Chain N" genérico de antes, que também nunca setava chain_type
    nenhum -- item novo ficava com o default ARM do Enum, mas rotulado
    "Chain", inconsistente com o próprio tipo que acabou de receber)."""

    bl_idname = "armature.hytale_ik_chain_set_count"
    bl_label = "Set Hytale IK Chain Count"
    bl_description = "Set the exact number of IK chains in the list, adding or removing at the end"
    bl_options = {"REGISTER", "UNDO"}

    count: IntProperty(name="Amount", default=1, min=0)
    chain_type: StringProperty(default="ARM")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        chain_type = self.chain_type if self.chain_type in {"ARM", "LEG", "TAIL", "HEAD", "SPINE", "ATTACHMENTS"} else "ARM"
        prefix = {"ARM": "Arm", "LEG": "Leg", "TAIL": "Tail", "HEAD": "Head", "SPINE": "Spine", "ATTACHMENTS": "Attachments"}.get(chain_type, "Chain")
        while len(chains) < self.count:
            item = chains.add()
            item.chain_type = chain_type
            item.label = f"{prefix} {len(chains)}"
            item.pole_angle_preset_name = chain_type  # v0.8 -- mesmo fix de RIG_OT_hytale_ik_chain_add acima
        while len(chains) > self.count:
            chains.remove(len(chains) - 1)
        _redraw_all_areas(context)
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
    bl_description = "Copy the currently selected bone's name into this field"
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
        allowed_fields = {
            "root_bone", "tip_bone", "pole_bone", "parent_override",
            # v0.9 (Etapa 2/2.7) -- campos de HEAD/SPINE/ATTACHMENTS, mesmo picker genérico
            "neck_bone_1", "neck_bone_2", "neck_bone_3", "neck_bone_4", "neck_bone_5",
            "head_bone", "head_end_bone",
            "pelvis_bone", "spine_bone_1", "spine_bone_2", "spine_bone_3", "spine_bone_4",
            # v0.9.8 -- gerado a partir de ATTACHMENTS_MAX_COUNT (constants.py)
            # em vez de 5 nomes escritos na mão -- acompanha o teto
            # automaticamente se ele mudar.
            *{f"attachment_bone_{i}" for i in range(1, ATTACHMENTS_MAX_COUNT + 1)},
        }
        if self.field not in allowed_fields:
            self.report({"WARNING"}, f"Unknown field '{self.field}'.")
            return {"CANCELLED"}

        setattr(chains[index], self.field, bone_name)
        self.report({"INFO"}, f"{self.field} = '{bone_name}'.")
        return {"FINISHED"}


class RIG_OT_hytale_ik_chain_load_defaults(Operator):
    """Preenche a lista com um template de cadeias de IK já calibradas
    (ver templates/rig/*.json, builtin + Documentos/Hyblend/templates/
    rig/*.json do usuário -- schema completo em templates/__init__.py).
    Substitui a lista atual. Pra adicionar um template de outra
    criatura/personagem, não precisa mexer em código: basta criar um
    .json novo em uma dessas pastas (e rodar "Reload Templates" se o
    Blender já estava aberto) -- a lista de opções abaixo é gerada
    automaticamente a partir dos templates descobertos."""

    bl_idname = "armature.hytale_ik_chain_load_defaults"
    bl_label = "Load Hytale IK Chain Preset"
    bl_description = "Load a calibrated rig template, replacing the current IK chain list"
    bl_options = {"REGISTER", "UNDO"}

    preset: StringProperty(
        name="Preset",
        default="",
        description="Rig template name to load -- leave empty to use whatever is currently selected in the "
        "Character Templates dropdown (wm.hytale_rig_template_selected, see interface.py)",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        preset_name = self.preset or context.window_manager.hytale_rig_template_selected
        if not preset_name or preset_name == _TEMPLATE_NONE:
            self.report({"WARNING"}, "No rig template selected.")
            return {"CANCELLED"}

        template = get_rig_template(preset_name)
        entries = template.get("ik_chains") if template else None
        if not entries:
            self.report({"WARNING"}, f"Unknown or empty rig template '{preset_name}'.")
            return {"CANCELLED"}

        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        chains.clear()
        chain_fields = {
            "chain_type", "label", "root_bone", "tip_bone", "pole_bone", "parent_override", "side",
            "pole_invert", "pole_distance", "pole_angle_mode", "pole_angle_preset_name",
            "pole_angle_manual", "pole_angle_fine_tune", "extra_ik_location", "tail_tip_rotation_axis", "tail_tip_rotation_deg",
        }
        for entry in entries:
            item = chains.add()
            for key, value in entry.items():
                if key not in chain_fields:
                    continue  # campo desconhecido no .json (typo, versão futura) -- ignora em vez de quebrar
                # Compatibilidade com templates antigos/exportados de uma
                # versão anterior desta função, que ainda usam "ARM" como
                # valor cru de pole_angle_mode em vez do genérico "PRESET".
                if key == "pole_angle_mode" and value == "ARM":
                    value = "PRESET"
                setattr(item, key, value)
            if "chain_type" not in entry:
                # Migração pra templates salvos ANTES do chain_type existir
                # (ex.: templates/rig/rig_player.json, a versão que ainda
                # está no addon) -- sem isso, TODA cadeia carrega como
                # "ARM" (default do Enum), e uma perna salva numa versão
                # anterior passa a cair em Main/Arm em vez de Main/Leg (ver
                # _classify_chain_limb, que agora usa chain_type direto em
                # vez de adivinhar pelo label). Só best-effort no texto do
                # label/root_bone (mesma ideia da heurística antiga que
                # classificava por texto) -- daqui pra frente, todo save
                # novo já grava chain_type de verdade (ver
                # _IK_CHAIN_JSON_FIELDS), então isso só entra em ação pra
                # templates legados que nunca mais forem re-salvos.
                guess = (item.label or item.root_bone or "").lower().replace("ç", "c").replace("ã", "a")
                if "leg" in guess or "perna" in guess or "thigh" in guess:
                    item.chain_type = "LEG"
                elif "tail" in guess or "cauda" in guess:
                    item.chain_type = "TAIL"
                # senão fica em "ARM" (default do Enum) -- mesmo
                # comportamento de sempre pra cadeias que já eram braço
                # ou que não dá pra classificar por texto nenhum.

        # Amarra o toggle da correção de junta ao que o TEMPLATE pede (ver
        # rig_template["apply_ik_joint_fix"] -- ANTES isso era hardcoded
        # "só liga pro Player"; agora qualquer template pode ligar/desligar
        # isso conforme a própria calibração). Continua ajustável
        # manualmente depois.
        armature.hytale_apply_ik_joint_fix = bool(template.get("apply_ik_joint_fix", False))
        armature.hytale_active_rig_template = preset_name

        # Carrega junto o template de shapes com o mesmo "nome de família"
        # (rig_template["shape_template"], default = mesmo nome do rig
        # template) -- só se ele realmente existir; senão deixa em branco
        # (bones ficam sem override de shape, mas o resto do rig funciona
        # normalmente -- 100% cosmético).
        shape_name = template.get("shape_template", preset_name)
        if shape_name and get_shape_template(shape_name) is not None:
            armature.hytale_active_shape_template = shape_name
        else:
            armature.hytale_active_shape_template = ""
            if shape_name:
                self.report(
                    {"INFO"},
                    f"Rig template '{preset_name}' points to shape template '{shape_name}', which was not "
                    f"found -- bones will use default/generic custom shapes only.",
                )

        self.report({"INFO"}, f"Loaded rig template '{preset_name}' ({len(entries)} chain(s)).")
        return {"FINISHED"}




# ---------------------------------------------------------------------------
# UIList reutilizável pela aba "Rig" do interface.py (registrada aqui
# porque descreve como desenhar um item de armature.hytale_ik_chains --
# é dado/lógica deste módulo, não layout de painel).
# ---------------------------------------------------------------------------


_CHAIN_TYPE_ICON = {
    "ARM": "CON_KINEMATIC", "LEG": "CON_KINEMATIC", "TAIL": "PHYSICS",
    "HEAD": "USER", "SPINE": "BONE_DATA", "ATTACHMENTS": "LINKED",
}


class RIG_UL_hytale_ik_chains(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(
            item, "label", text="", emboss=False,
            icon=_CHAIN_TYPE_ICON.get(item.chain_type, "BONE_DATA"),
        )


# ---------------------------------------------------------------------------
# Collection Settings (v0.9, Etapa 1) -- lista editável de
# armature.hytale_bone_collections, mesmo padrão Add/Remove/Move/UIList
# que hytale_ik_chains já usa acima. Fica numa box própria em
# interface.py, entre "Bone Settings" e "Character Templates" (ver
# DEVELOPER_NOTES.md).
# ---------------------------------------------------------------------------
class RIG_OT_hytale_bone_collection_load_defaults(Operator):
    """v0.9 -- Etapa 1. Só chama ensure_default_bone_collections() de
    dentro de um execute() (contexto onde escrever em armature.data é
    permitido -- ver AttributeError que draw() dá se tentar isso direto,
    'Writing to ID classes in this context is not allowed'). Botão
    mostrado em interface.py só enquanto a lista ainda não foi
    inicializada nenhuma vez pra este armature -- depois disso ela pode
    ficar vazia de propósito (usuário apagou tudo) sem esse botão voltar
    a aparecer sozinho."""

    bl_idname = "armature.hytale_bone_collection_load_defaults"
    bl_label = "Load Default Collections"
    bl_description = "Populate the list with the built-in collections (Head/Spine/Body/Arm L/Arm R/Leg L/Leg R/Root)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE" and not obj.data.hytale_bone_collections_initialized

    def execute(self, context):
        ensure_default_bone_collections(context.active_object.data)
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_OT_hytale_bone_collection_reset_grid(Operator):
    """v0.9.9 -- corrige armatures cujas 10 entradas default (Head/
    Spine/Body/Arm L/Arm R/Leg L/Leg R/Root/Tail/Attachments) foram
    criadas ANTES de Row/Column existirem como campo (ex.: quem testou
    "Collection Settings" nas primeiras versões desta feature, antes da
    grade ficar configurável) -- nesses casos, a lista já está com
    hytale_bone_collections_initialized=True (então o seed normal --
    ensure_default_bone_collections -- nunca roda de novo), e as
    entradas antigas ficam TRAVADAS em row=0/column=0 pra sempre (o
    valor default do IntProperty pra um campo que não existia quando o
    item foi criado). Sintoma relatado: a ordem do FK/IK na aba
    Animation "não parece ter efeito" -- é porque TODAS as collections
    caem em row=0/column=0, então a ordenação vira puramente alfabética
    por nome, que por coincidência pode bater com a ordem antiga do
    Bone Settings.

    Este botão só REESCREVE row/column (e SÓ pras entradas cujo NOME
    bate com um dos 10 defaults -- COLL_MAIN_HEAD etc., ver
    _DEFAULT_BONE_COLLECTION_GRID) pro valor de grade esperado -- nunca
    mexe em parent, nunca cria/apaga entradas, e NUNCA toca em
    collections com nome custom (criadas pelo usuário) -- só corrige o
    que já era pra ser "default" e ficou desatualizado."""

    bl_idname = "armature.hytale_bone_collection_reset_grid"
    bl_label = "Reset Row/Column to Defaults"
    bl_description = (
        "Fix Row/Column for the built-in collections (Head/Spine/Body/Arm L/Arm R/Leg L/Leg R/Root/Tail/"
        "Attachments) back to their default grid position -- useful if these entries were created before "
        "Row/Column existed, leaving them all stuck at Row 0/Column 0 (which makes ordering fall back to "
        "alphabetical). Custom collections are never touched"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE" and len(obj.data.hytale_bone_collections) > 0

    def execute(self, context):
        armature = context.active_object.data
        grid_by_name = {name: (row, column) for name, row, column in _DEFAULT_BONE_COLLECTION_GRID}
        fixed = 0
        for item in armature.hytale_bone_collections:
            grid = grid_by_name.get(item.name)
            if grid is None:
                continue  # nome custom -- não é um dos 10 defaults, não mexe
            item.row, item.column = grid
            fixed += 1
        sync_bone_collection_order(armature)
        _redraw_all_areas(context)
        self.report({"INFO"}, f"Reset Row/Column on {fixed} built-in collection(s).")
        return {"FINISHED"}


class RIG_OT_hytale_bone_collection_add(Operator):
    """Abre um dialog (nome + Parent) e adiciona uma entrada nova.
    Diferente de RIG_OT_hytale_ik_chain_add (que só recebe um
    chain_type fixo do menu popup, sem digitar nada) -- aqui o NOME é
    livre, então precisa de um invoke_props_dialog em vez de rodar
    direto no clique."""

    bl_idname = "armature.hytale_bone_collection_add"
    bl_label = "Add Bone Collection"
    bl_description = "Add a new named bone collection, nested under Main or another collection"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty(name="Name", default="Collection")
    # v0.9.6 -- ERA um EnumProperty fixo (Main/Face) -- reusa a MESMA
    # função de items dinâmica que HytaleBoneCollectionItem.parent usa
    # (ver _parent_collection_enum_items) -- lista qualquer collection
    # já existente na lista como opção de parent, mais "Main (root)".
    # `default=0` (índice, não string) -- mesma lição aprendida com
    # collection_override: Blender não aceita string como default pra
    # EnumProperty com `items` dinâmico (ver changelog).
    parent: EnumProperty(
        name="Parent",
        items=_parent_collection_enum_items,
        default=0,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "collection_name")
        layout.prop(self, "parent")

    def execute(self, context):
        armature = context.active_object.data
        name = self.collection_name.strip()
        if not name:
            self.report({"ERROR"}, "Name can't be empty.")
            return {"CANCELLED"}
        # v0.9.3 -- "AUTO" é o identificador reservado do item "Auto
        # (default)" do dropdown de Collection (ver COLLECTION_OVERRIDE_AUTO)
        # -- uma collection de verdade com esse nome colidiria com ele.
        if name.upper() == COLLECTION_OVERRIDE_AUTO:
            self.report({"ERROR"}, f"'{name}' is a reserved name (used internally for 'Auto (default)') -- pick another.")
            return {"CANCELLED"}
        # v0.9.6 -- mesma ideia, pro sentinel do dropdown de Parent.
        if name == PARENT_COLLECTION_ROOT:
            self.report({"ERROR"}, f"'{name}' is a reserved name -- pick another.")
            return {"CANCELLED"}
        if any(c.name == name for c in armature.hytale_bone_collections):
            self.report({"ERROR"}, f"A collection named '{name}' already exists in this list.")
            return {"CANCELLED"}
        ensure_default_bone_collections(armature)  # garante que a lista já foi semeada antes de adicionar
        item = armature.hytale_bone_collections.add()
        item.name = name
        item.parent = self.parent
        armature.hytale_bone_collections_index = len(armature.hytale_bone_collections) - 1
        sync_bone_collection_order(armature)  # v0.9 (Etapa 2) -- reflete no painel nativo na hora, se já existir
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_OT_hytale_bone_collection_remove(Operator):
    """Remove uma entrada pelo índice (padrão: a ativa). Só tira da
    LISTA de configuração -- se essa collection já existir de verdade no
    armature (de um 'Create Rig' anterior), ela e os bones nela
    continuam lá; só deixa de ser uma opção no dropdown 'Collection' de
    Bone Settings, e cadeias que já apontavam pra ela caem de volta no
    default (Auto) no próximo 'Create Rig' -- ver
    _apply_bone_collection_overrides."""

    bl_idname = "armature.hytale_bone_collection_remove"
    bl_label = "Remove Bone Collection"
    bl_description = "Remove the selected entry from the list"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE" and len(obj.data.hytale_bone_collections) > 0

    def execute(self, context):
        armature = context.active_object.data
        collections = armature.hytale_bone_collections
        index = self.index if self.index >= 0 else armature.hytale_bone_collections_index
        if 0 <= index < len(collections):
            collections.remove(index)
            armature.hytale_bone_collections_index = max(0, min(armature.hytale_bone_collections_index, len(collections) - 1))
        sync_bone_collection_order(armature)  # v0.9 (Etapa 2) -- reflete no painel nativo na hora, se já existir
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_OT_hytale_bone_collection_move(Operator):
    """Mesmo padrão de RIG_OT_hytale_ik_chain_move -- reordena uma
    posição pra cima/baixo na lista inteira (Main e Face juntas, sem
    separação forçada). v0.9 (Etapa 2): a ordem aqui agora reflete
    IMEDIATAMENTE no painel nativo "Bone Collections" (Object Data
    Properties), se essa collection já existir de verdade -- ver
    sync_bone_collection_order -- além de continuar sendo a ordem usada
    quando 'Create Rig' as cria do zero."""

    bl_idname = "armature.hytale_bone_collection_move"
    bl_label = "Move Bone Collection"
    bl_description = "Move the selected entry up or down in the list"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=(
            ("UP", "Up", "Move the entry one position up"),
            ("DOWN", "Down", "Move the entry one position down"),
        ),
        default="UP",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE" and len(obj.data.hytale_bone_collections) > 1

    def execute(self, context):
        armature = context.active_object.data
        collections = armature.hytale_bone_collections
        index = armature.hytale_bone_collections_index
        target = index - 1 if self.direction == "UP" else index + 1
        if not (0 <= target < len(collections)):
            return {"CANCELLED"}
        collections.move(index, target)
        armature.hytale_bone_collections_index = target
        sync_bone_collection_order(armature)  # v0.9 (Etapa 2) -- reflete no painel nativo na hora, se já existir
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_UL_hytale_bone_collections(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="GROUP_BONE")
        # v0.9.6 -- mostra o parent resolvido (qualquer collection da
        # lista, ou "Main" pro sentinel/vazio) -- ver
        # HytaleBoneCollectionItem.parent/PARENT_COLLECTION_ROOT.
        parent_label = "Main" if item.parent in ("", PARENT_COLLECTION_ROOT) else item.parent
        row.label(text=parent_label)


# ---------------------------------------------------------------------------
# Tarefa C -- duas funções puras extraídas do meio de
# RIG_OT_hytale_generate_rig (ver comentário em
# RIG_OT_hytale_generate_rig._warn_shared_pole_angle_presets e no branch
# PRESET de _build_pose_constraints, mais abaixo) pra que
# RIG_OT_hytale_validate_rig, logo depois, possa reaproveitar a MESMA
# lógica de checagem/lookup em vez de duplicá-la. Pequeno refactor
# comportamental-neutro feito EM SERVIÇO da Tarefa C (não faz parte da
# Tarefa A, que foi reorganização pura) -- resultado idêntico ao que
# estava inline antes, só que agora chamável de dois lugares.
# ---------------------------------------------------------------------------


def resolve_pole_angle_preset_degrees(rig_template, preset_name, side):
    """rig_template['pole_angle_presets'][preset_name][side] (graus), ou
    None se o rig_template for falsy ou o preset/side não estiver
    definido nele. Mesmo lookup que RIG_OT_hytale_generate_rig.
    _build_pose_constraints já fazia inline no branch PRESET -- ver ali."""
    if not rig_template:
        return None
    return rig_template.get("pole_angle_presets", {}).get(preset_name, {}).get(side)


def find_shared_pole_angle_preset_warnings(chains_data):
    """Pra cada nome de pole_angle_preset usado em modo PRESET por mais
    de um chain_type, devolve (nome, [chain_types ordenados]). Mesma
    checagem que RIG_OT_hytale_generate_rig._warn_shared_pole_angle_presets
    já fazia (ver docstring completa lá, sobre por que isso importa --
    pole_angle_presets é indexado só por nome + side, NÃO por chain_type,
    então braço e perna podem acabar compartilhando o mesmo preset por
    acidente). `chains_data` é qualquer lista de dict-like com as chaves
    "pole_angle_mode"/"pole_angle_preset_name"/"chain_type" -- tanto a
    lista rica que _build_edit_bones monta quanto uma lista simples
    montada direto de armature.hytale_ik_chains (ver
    RIG_OT_hytale_validate_rig) servem igual."""
    preset_chain_types = {}
    for data in chains_data:
        if data.get("pole_angle_mode") != "PRESET":
            continue
        name = data.get("pole_angle_preset_name")
        chain_type = data.get("chain_type")
        if not name or not chain_type:
            continue
        preset_chain_types.setdefault(name, set()).add(chain_type)
    return [(name, sorted(types)) for name, types in preset_chain_types.items() if len(types) > 1]


class RIG_OT_hytale_validate_rig(Operator):
    """Tarefa C -- diagnóstico, não muda NADA no rig/armature. Roda 4
    checagens (ver DEVELOPER_NOTES.md/histórico do chat pra lista
    completa) e relata cada problema como um WARNING via self.report, ou
    um único INFO "tudo certo" se nada for encontrado:

    1. root_bone/tip_bone/pole_bone/parent_override de cada item de
       armature.hytale_ik_chains apontando pra um nome que não existe
       neste armature (typo, ou template de outro personagem aplicado
       por engano). parent_override reaproveita _resolve_parent_override
       (mesma resolução de alias que "Create Rig" usa), passando
       armature.bones em vez de edit_bones -- funciona em qualquer modo,
       não precisa entrar em Edit Mode só pra validar. v0.9 (Etapa 2):
       mesma checagem pros campos de Head/Spine (neck_bone_*/head_bone/
       head_end_bone/pelvis_bone/spine_bone_*), via _head_spine_bone_names.
    2. Itens em modo PRESET cujo pole_angle_preset_name não existe em
       pole_angle_presets do rig template ativo -- reaproveita
       resolve_pole_angle_preset_degrees (acima), o MESMO lookup que
       "Create Rig" usa de verdade na hora de gerar.
    3. Mais de um chain_type usando o mesmo pole_angle_preset_name em
       modo PRESET -- reaproveita find_shared_pole_angle_preset_warnings
       (acima), a mesma checagem que "Create Rig" já roda sozinho.
    4. Bones "originais" (sem PROP_RIG_LAYER -- ou seja, sem sufixo
       _MCH/_CTRL/_IK, o critério real que o resto do arquivo já usa pra
       diferenciar ORG de gerado) que NÃO estão na bone collection
       "Hytale Export" (nome configurável via export_collection_name,
       default "Hytale Export" -- mesmo nome que exporter.py usa por
       padrão, mas SEM importar nada de lá, pra não criar uma dependência
       rigger->exporter que hoje não existe). Se a collection nem existir
       no armature, avisa uma vez só (em vez de listar todo bone como
       "faltando") -- provavelmente só significa que ela ainda não foi
       criada/renomeada."""

    bl_idname = "armature.hytale_validate_rig"
    bl_label = "Validate Rig"
    bl_description = "Check the IK chain list and export bone collection for common mistakes (report-only)"
    bl_options = {"REGISTER"}

    export_collection_name: StringProperty(
        name="Export Collection",
        default="Hytale Export",
        description="Bone collection name that original (non-generated) bones are expected to be in -- same "
        "name exporter.py uses by default; change only if you've renamed that collection",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        armature = context.active_object.data
        bones = armature.bones  # funciona em qualquer modo -- não precisa de Edit Mode só pra validar
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
            # v0.9 (Etapa 2, ampliado na 2.7 pra ATTACHMENTS) -- mesma
            # checagem, pros nomes configurados numa entrada Head/Spine/
            # Attachments (ver _head_spine_bone_names). v0.9.3: checa
            # TAMBÉM o "_CTRL" correspondente, que é o bone que
            # realmente é usado por _apply_bone_collection_overrides (ver
            # fix "bug: ia o bone original, tinha que ir o _CTRL").
            if item.chain_type in ("HEAD", "SPINE", "ATTACHMENTS"):
                for name in _head_spine_bone_names(item):
                    if bones.get(name) is None:
                        problems.append(f"{item.chain_type.title()} '{label}': bone '{name}' not found on this armature.")
                    elif bones.get(name + SUFFIX_CTRL) is None:
                        problems.append(
                            f"{item.chain_type.title()} '{label}': '{name}' exists, but its control bone "
                            f"'{name + SUFFIX_CTRL}' doesn't -- Create Rig hasn't run yet, or this bone is "
                            f"excluded from the generic ORG->CTRL loop."
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
            # bug fix: bone.collections (bpy_prop_collection de
            # BoneCollection) só aceita STRING no `in` (__contains__),
            # não o objeto BoneCollection em si -- ao contrário de
            # outras coleções do Blender. `export_coll in b.collections`
            # sempre estourava TypeError em runtime (não pegava em
            # ast.parse/pyflakes, só executando de verdade). Comparação
            # por nome, igual o resto do arquivo já faz em casos
            # parecidos (ver RIG_OT_hytale_collection_template_save,
            # mais abaixo).
            export_members = {
                b.name for b in bones
                if any(c.name == export_coll.name for c in b.collections)
            }
            for bone in bones:
                if PROP_RIG_LAYER in bone.keys():
                    continue  # só bones ORG (sem PROP_RIG_LAYER) entram nesta checagem
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



# ---------------------------------------------------------------------------
# Operador: remover bones gerados (útil pra iterar durante o desenvolvimento)
# ---------------------------------------------------------------------------


class RIG_OT_hytale_clear_generated(Operator):
    """Apaga todo bone criado por este script (MCH, CTRL, CTRL-IK,
    MCH-IK/bridge, Pole, e os bones utilitários root.*), deixando só os
    bones ORG originais. Não mexe na lista hytale_ik_chains -- rodar
    "Create Rig" de novo depois reconstrói tudo igual.

    Também purga os objetos WGT_hytale_* cacheados em bpy.data -- sem
    isso, depois de editar/atualizar hytale_widgets.blend (ex.: remodelar
    um shape existente), "Create Rig" continuava usando a cópia antiga
    que já estava carregada na cena (ensure_widget_objects só faz append
    do que ainda NÃO existe em bpy.data.objects -- um objeto com o mesmo
    nome já presente nunca é atualizado sozinho). Rodar este botão força
    um append fresco da biblioteca na próxima geração.

    CUIDADO se você tiver MAIS DE UM personagem/armature no mesmo arquivo
    .blend compartilhando os mesmos widgets: purgar aqui remove os
    objetos pra TODOS eles (bpy.data é global, não por-armature) -- os
    outros rigs voltam a usar o octaedro padrão até rodarem "Create Rig"
    de novo também."""

    bl_idname = "armature.hytale_clear_generated_rig"
    bl_label = "Remove Generated Hytale Rig Bones"
    bl_description = "Delete all generated bones, keeping only the original ones"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
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

        # v0.9 -- apaga a bone collection REAL de Main (e tudo aninhado
        # dentro dela, recursivamente -- Head/Spine/Body/Arm L/Arm R/
        # Leg L/Leg R/Root/Tail/Attachments e qualquer collection custom
        # que o usuário tenha criado em "Collection Settings" e que já
        # tenha sido materializada num "Create Rig" anterior -- v0.9.6:
        # Main é a ÚNICA raiz de organização do usuário agora, Face
        # deixou de ser hardcoded/auto-criada -- ver _build_main_collections;
        # uma "Face" que o usuário tenha criado manualmente já está
        # aninhada em algum lugar dentro de Main, então cai nesta
        # varredura recursiva do mesmo jeito, sem precisar de caso
        # especial. v0.9.7: Attachments também virou filha de Main (era
        # uma raiz separada, ficava de fora desta limpeza de propósito
        # -- agora é removida e recriada normalmente, igual Head/Spine/
        # etc., já que também é parte de Collection Settings agora).
        # Internal/ORG/MCH/CTRL/CTRL-IK/Specials/Attachments Imported/
        # Hytale Export ficam de fora, de propósito (nenhuma delas é
        # "regenerada do zero" por hytale_bone_collections -- são
        # internas do rig, não organização do usuário).
        #
        # NÃO mexe em armature.hytale_bone_collections (a LISTA de
        # configuração, em "Collection Settings") -- só nas collections
        # de VERDADE do Blender. É por isso que a lista continua com o
        # mesmo plano de organização pro próximo "Create Rig", em vez de
        # o usuário ter que recriar tudo na mão de novo.
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
        for wgt_name in [o.name for o in bpy.data.objects if o.name.startswith(WIDGETS_NAME_PREFIX)]:
            wgt_obj = bpy.data.objects.get(wgt_name)
            if wgt_obj is None:
                continue
            mesh = wgt_obj.data
            bpy.data.objects.remove(wgt_obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh, do_unlink=True)
            purged += 1

        self.report(
            {"INFO"},
            f"Removed {removed} generated bone(s) and {removed_collections} bone collection(s) under "
            f"Main; purged {purged} cached widget object(s) "
            f"(next 'Create Rig' re-loads them from {WIDGETS_LIBRARY_FILENAME}).",
        )
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
    bl_description = "Create or update the rig layers, constraints and custom shapes"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
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
        self._build_spine_follow(obj)
        self._apply_pole_childof_inverses(obj, chains_data)
        widget_stats = self._build_custom_shapes(obj, chains_data)
        shape_switch_count = self._build_ik_fk_shape_visibility(obj, chains_data)
        colored_count = self._build_bone_colors(obj, tail_chains_data)

        if prev_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=prev_mode)

        self.report(
            {"INFO"},
            f"Rig ready: {stats['mch']} MCH, {stats['ctrl']} CTRL, {stats['ik']} CTRL-IK, "
            f"{stats['ik_mch']} MCH-IK, {stats['tail']} Tail, {stats['root']} root control bone(s) created; "
            f"{len(chains_data)} IK chain(s) and {len(tail_chains_data)} tail chain(s) processed "
            f"({tail_constraint_count} tail bridge bone(s) constrained); "
            f"{widget_stats['assigned']} custom shape(s) assigned"
            + (f" ({widget_stats['fallback']} via fallback)" if widget_stats["fallback"] else "")
            + (f", {widget_stats['missing']} widget(s) missing (see warnings))" if widget_stats["missing"] else "")
            + f"; {shape_switch_count} FK/IK shape-scale driver(s) set; "
            + f"{colored_count} bone(s) colored"
            + (f"; {joint_fix_count} IK joint fix(es) applied (rig template)." if joint_fix_count else "."),
        )
        return {"FINISHED"}

    def _apply_ik_joint_fixes(self, obj, chains_data):
        """Corrige a posição X de juntas específicas da cadeia IK (ver
        rig_template["ik_joint_x_overrides"]) -- só o eixo X, Y/Z ficam
        INTOCADOS. Cada rig template define os próprios valores
        calibrados (ANTES era um dict fixo, PLAYER_IK_JOINT_X_OVERRIDES,
        exclusivo do personagem "Player"); só roda se
        armature.hytale_apply_ik_joint_fix estiver ligado (setado
        automaticamente a partir de rig_template["apply_ik_joint_fix"]
        ao carregar o template, ver RIG_OT_hytale_ik_chain_load_defaults).

        Precisa rodar em EDIT MODE (mexe em edit_bones.head/tail
        diretamente) -- chamado de dentro do bloco `try` do execute(),
        antes de voltar pro Object Mode. Retroativo por natureza: não
        checa "is_new" nenhum, então corrige um bone que já existia de
        uma execução anterior igual a um recém-criado.

        Pra cada bone_name em ik_joint_x_overrides: seta o HEAD dele pro
        novo X, E acha o bone ANTERIOR na mesma cadeia (via
        chains_data/org_names) pra também setar o TAIL dele -- os dois
        compartilham a mesma junta visualmente, então precisam se mover
        juntos. NÃO mexe no *_IK_MCH (bridge) -- só nos bones _IK reais
        (CTRL-IK).

        COMPENSAÇÃO DE POLE ANGLE: mover o head do bone RAIZ da cadeia
        (ik_root, ex.: R-Arm_IK -- é o tail dele que muda aqui) rotaciona
        o eixo X local dele, que é exatamente o referencial que
        pole_angle_presets foi calibrado em cima -- sem compensar, o pole
        descentraliza. Mede o pole_angle "cru" (mesma fórmula de
        compute_pole_angle, só que em Edit Mode via compute_pole_angle_edit)
        ANTES e DEPOIS de mover o bone, e guarda a DIFERENÇA em
        chains_data[...]["pole_angle_joint_fix_delta"] -- _build_pose_constraints
        soma esse delta em cima do valor calibrado na hora de montar o
        constraint de IK (ver o branch "PRESET" lá). O sinal é invertido
        (angle_before - angle_after, não o contrário) porque o pole_angle
        REALMENTE aplicado no constraint é o NEGATIVO do valor cru desta
        fórmula (mesma inversão empírica que o branch AUTO já faz).

        COMPENSAÇÃO DE CUSTOM SHAPE: mesmo princípio, só que pra
        Translation/Rotation/Scale do widget -- ver
        compute_widget_transform_correction. Lê o valor calibrado "antigo"
        do TEMPLATE DE SHAPES ativo (armature.hytale_active_shape_template)
        em vez do dict fixo de antes. Guarda o resultado em
        self._player_widget_transform_corrections (bone_name -> (t, r, s)),
        consumido depois por _apply_widget_transform_override (que
        prioriza essa correção sobre o valor estático do template, só
        pros bones afetados aqui)."""
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
            # Ajuste fino pontual (ver rig_template["widget_translation_x_overrides"])
            # -- só troca o X, Y/Z ficam com o valor calculado acima.
            fixed_x = widget_translation_x_overrides.get(bone_name)
            if fixed_x is not None:
                translation = (fixed_x, translation[1], translation[2])
            self._player_widget_transform_corrections[bone_name] = (translation, rotation, scale)

        for bone_name, new_x in ik_joint_x_overrides.items():
            bone = edit_bones.get(bone_name)
            if bone is None:
                self.report({"WARNING"}, f"'{bone_name}' not found -- skipping IK joint fix.")
                continue

            # Acha a cadeia inteira ANTES de mover qualquer coisa, pra dar
            # pra medir o pole_angle "antes" com a geometria original.
            base_name = bone_name[: -len(SUFFIX_IK)] if bone_name.endswith(SUFFIX_IK) else bone_name
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
                    prev_bone = edit_bones.get(org_names[idx - 1] + SUFFIX_IK)
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
        ROOT-CTRL, usando as meshes de hytale_widgets.blend (ver
        ensure_widget_objects / _widget_name_for_bone). Roda por último --
        só depois que TODOS os bones já existem, então dá pra decidir
        "esse bone é a ponta de uma cadeia IK?" com base em chains_data
        sem se preocupar com ordem.

        Resolução em duas passadas: primeiro tenta o widget PREFERIDO de
        cada bone (por papel -- FK/IK/pole/root/head); o que não existir
        ainda na biblioteca cai pro WGT_DEFAULT_FALLBACK (se ele existir).
        Isso deixa usar só 1-2 shapes modelados por enquanto -- assim que
        um shape específico for adicionado à biblioteca com o nome certo,
        ele passa a valer automaticamente pro papel dele, sem tocar em
        código.

        100% cosmético: se a biblioteca ainda não foi gerada/colocada em
        assets/hytale_widgets.blend, avisa e segue em frente -- os bones
        ficam com o octaedro padrão do Blender, o resto do rig
        (constraints, drivers, IK) funciona normalmente.

        Carrega o TEMPLATE DE SHAPES ativo (armature.hytale_active_shape_template
        -- ver templates/shapes/*.json) uma vez só, no início, e guarda em
        self._shape_template_bones pra _apply_widget_transform_override
        (chamado abaixo, por bone) reaproveitar sem reler o dict de novo a
        cada bone."""
        armature = obj.data
        shape_template = get_shape_template(getattr(armature, "hytale_active_shape_template", "")) or {}
        self._shape_template_bones = shape_template.get("bones", {})

        pose_bones = obj.pose.bones
        ik_tip_names = {data["ik_tip"] for data in chains_data}

        wanted = {}
        for pb in pose_bones:
            # layer normalmente existe (bones gerados por este script);
            # pode vir None só se um bone entrar em WIDGET_NAME_OVERRIDES
            # (ou no campo "widget" do template de shapes) sem nunca ter
            # sido gerado por aqui -- _widget_name_for_bone já lida com
            # isso (override sempre vence, mesmo com layer None). Não é o
            # caso do Origin_CTRL hoje (ele tem layer= "CTRL" normalmente
            # -- ver comentário perto do dict).
            layer = pb.bone.get(PROP_RIG_LAYER)
            widget_name = _widget_name_for_bone(pb.name, layer, ik_tip_names, self._shape_template_bones)
            if widget_name:
                wanted[pb.name] = widget_name

        # Passada 1: shapes preferidos (por papel).
        preferred_names = set(wanted.values())
        still_missing = ensure_widget_objects(preferred_names)

        # Passada 2: fallback só pros bones cujo preferido não existe.
        needs_fallback = {b for b, w in wanted.items() if w in still_missing}
        fallback_available = False
        if needs_fallback:
            fallback_missing = ensure_widget_objects({WGT_DEFAULT_FALLBACK})
            fallback_available = WGT_DEFAULT_FALLBACK not in fallback_missing

        if still_missing and not fallback_available:
            self.report(
                {"WARNING"},
                f"Widget shape(s) not found in '{WIDGETS_LIBRARY_FILENAME}': {', '.join(sorted(still_missing))} "
                f"(and no '{WGT_DEFAULT_FALLBACK}' fallback available either) -- affected bone(s) left with the "
                f"default shape.",
            )
        elif still_missing:
            self.report(
                {"INFO"},
                f"Widget shape(s) not found yet: {', '.join(sorted(still_missing))} -- using "
                f"'{WGT_DEFAULT_FALLBACK}' as fallback for those roles.",
            )

        assigned = 0
        used_fallback = 0
        for bone_name, widget_name in wanted.items():
            if widget_name in still_missing:
                if not fallback_available:
                    continue
                widget_name = WGT_DEFAULT_FALLBACK
                used_fallback += 1
            pb = pose_bones[bone_name]
            new_shape_obj = bpy.data.objects[widget_name]
            # Só reseta Translation/Rotation/Scale pro default na PRIMEIRA
            # vez que ESTE shape é atribuído a ESTE bone -- reruns não
            # apagam ajustes já feitos (template de shapes ativo, ver
            # _apply_widget_transform_override, ou até um ajuste manual no
            # painel de constraints/item). Sem
            # isso, todo "Create Rig" de novo resetava tudo pra (1,1,1)/
            # (0,0,0), destruindo qualquer trabalho fino de scale/posição.
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

        return {
            "assigned": assigned,
            "fallback": used_fallback,
            "missing": 0 if fallback_available else len(still_missing),
        }

    def _apply_widget_transform_override(self, pose_bone, bone_name):
        """Aplica o bone atual do TEMPLATE DE SHAPES ativo
        (self._shape_template_bones, montado por _build_custom_shapes a
        partir de armature.hytale_active_shape_template -- ver
        templates/shapes/*.json), SÓ nos campos (translation/rotation_deg/
        scale) que estiverem explicitamente no .json -- campos omitidos
        ficam como já estavam (não são tocados). Roda toda vez que o rig
        é gerado: o template é a fonte da verdade a partir daqui, não a
        UI -- então valores definidos nele sempre "vencem" em cada rerun
        (determinístico, sem surpresa).

        EXCEÇÃO: se este bone tiver uma correção calculada por
        _apply_ik_joint_fixes (self._player_widget_transform_corrections
        -- só existe se armature.hytale_apply_ik_joint_fix estiver ligado,
        e só pros bones listados em
        rig_template["ik_joint_x_overrides"]), ela vence os 3 valores
        estáticos do template -- é a versão já compensada pra geometria
        nova.

        Bones que também recebem o driver de FK/IK (ver
        _build_ik_fk_shape_visibility) têm o campo "scale" tratado como o
        tamanho "cheio" (modo ativo) -- o driver, adicionado DEPOIS deste
        método rodar, assume o controle de custom_shape_scale_xyz e
        multiplica esse valor por 0 ou 1; o que é atribuído aqui vira só o
        fallback caso o driver seja removido manualmente.

        Attachments (is_attachment_bone) sem override de "scale"
        específico caem no ATTACHMENT_SHAPE_SCALE genérico -- não precisa
        listar cada attachment (Eyebrow, Ear, socket de mão, etc.) um por
        um; um nome-exato no template de shapes sempre vence essa regra
        genérica, igual o mesmo princípio de BONE_COLOR_OVERRIDES x
        BONE_COLOR_ATTACHMENT."""
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
        """Liga o Scale do custom shape de TODOS os bones _CTRL (FK) e
        _IK (IK) de cada segmento de cada cadeia à custom property de
        FK/IK switch DESSA cadeia (agora no bone PROPERTIES, não mais no
        próprio _IK -- ver switch_property_name) -- quando um lado está
        ativo, o outro encolhe pra 0 (some do viewport sem precisar mexer
        em visibilidade de collection, então continua selecionável só
        quando faz sentido). Cobre a cadeia inteira (raiz, meio, ponta),
        não só a ponta. v0.8: Pole_CTRL e Pole_Line (ver data["pole"]/
        data["pole_line"]) também -- mesmo driver que um bone "IK"
        normal (mode="IK"), já que só fazem sentido existir quando a
        cadeia está em modo IK; antes ficavam com o scale ESTÁTICO
        (sempre no tamanho cheio, inclusive em FK, onde não tinham
        motivo pra estar visíveis).

        O tamanho "cheio" de cada bone vem do TEMPLATE DE SHAPES ativo
        (self._shape_template_bones, chave "scale"); default (1,1,1) pros
        que ainda não têm valor definido. Roda DEPOIS de
        _build_custom_shapes -- precisa que custom_shape_scale_xyz já
        tenha um valor base atribuído antes do driver assumir o controle
        (e que self._shape_template_bones já tenha sido montado por
        _build_custom_shapes). Bones corrigidos por _apply_ik_joint_fixes
        (self._player_widget_transform_corrections) usam o scale JÁ
        COMPENSADO em vez do valor estático -- senão o driver
        reintroduziria o tamanho antigo (não compensado) assim que o modo
        IK for ativado."""
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
                fk_name = org_name + SUFFIX_CTRL
                ik_name = org_name + SUFFIX_IK

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

            # v0.8: Pole_CTRL e Pole_Line (ver SUFFIX_POLE/SUFFIX_POLE_LINE)
            # nunca entram em data["org_names"] (não são ORG/CTRL/IK de
            # nenhum segmento -- são bones à parte, ver _build_ik_layer)
            # -- por isso ficavam de fora do loop acima e nunca ganhavam
            # driver nenhum: continuavam com o custom_shape_scale_xyz
            # ESTÁTICO (tamanho cheio o tempo todo), mesmo em modo FK,
            # onde não fazem sentido nenhum (não existe pole target
            # ativo fora de IK). Mesmo tratamento dos bones "IK" acima
            # (mode="IK") -- somem (encolhem a 0) quando a cadeia está em
            # FK, aparecem no tamanho cheio só quando em IK.
            for key in ("pole", "pole_line"):
                name = data.get(key)
                pb = pose_bones.get(name) if name else None
                if pb is not None:
                    target = _scale_target(name)
                    add_custom_shape_scale_switch_driver(pb, obj, BONE_PROPERTIES, switch_prop, target, mode="IK")
                    applied += 1
        return applied

    def _build_bone_colors(self, obj, tail_chains_data=None):
        """Pinta bone.color (Custom Color Set) por bone -- não tem nada a
        ver com custom shape, é a cor de exibição do bone em si (Bone
        Properties > Viewport Display > Color, ou o painel de Bone Color
        na sidebar). Aplicado ao Bone (obj.data.bones), não ao PoseBone --
        assim vale em Edit Mode e Pose Mode igual, sem precisar de duas
        atribuições.

        Regra: BONE_COLOR_OVERRIDES (nome exato) vence; senão, os _CTRL
        de uma cadeia TAIL (tail_chains_data, v0.7 -- pedido explícito
        pra ficarem verdes, mesma cor da Spine) vencem também; senão,
        attachment (is_attachment_bone) vence o prefixo L-/R-
        (BONE_COLOR_ATTACHMENT); senão, prefixo L-/R- decide
        (BONE_COLOR_LEFT/BONE_COLOR_RIGHT); bones que não se encaixam em
        nenhum caso ficam com a cor padrão do Blender (não mexe).

        Bones ORG (sem PROP_RIG_LAYER -- nunca passaram por este script,
        são os nomes originais do modelo importado, ex.:
        L-Eyebrow-Attachment) NUNCA recebem cor, mesmo tendo prefixo
        L-/R-: eles ficam ocultos (collection ORG) e não fazem sentido
        coloridos -- só os bones gerados (MCH/CTRL/CTRL-IK/MCH-IK/
        ROOT-CTRL/TAIL) entram na regra."""
        tail_ctrl_names = {
            name for data in (tail_chains_data or []) for name in data.get("ctrl_names", ())
        }
        colored = 0
        for bone in obj.data.bones:
            if bone.get(PROP_RIG_LAYER) is None:
                # ORG nunca tem cor -- e se ficou colorido numa execução
                # ANTIGA (antes desta regra existir), reseta pro padrão do
                # Blender em vez de só pular (senão a cor errada nunca sai).
                if bone.color.palette == "CUSTOM":
                    bone.color.palette = "DEFAULT"
                continue
            palette = BONE_COLOR_OVERRIDES.get(bone.name)
            if palette is None and bone.name in tail_ctrl_names:
                palette = BONE_COLOR_SPINE
            if palette is None and is_attachment_bone(bone):
                # Attachment vence o prefixo L-/R- -- um bone tipo
                # "L-Eyebrow-Attachment_CTRL" começa com "L-", mas deve
                # ficar cinza (BONE_COLOR_ATTACHMENT), não vermelho.
                palette = BONE_COLOR_ATTACHMENT
            if palette is None:
                if bone.name.startswith("L-"):
                    palette = BONE_COLOR_LEFT
                elif bone.name.startswith("R-"):
                    palette = BONE_COLOR_RIGHT
            if palette is None:
                continue
            normal, select, active = palette
            bone.color.palette = "CUSTOM"
            bone.color.custom.normal = normal
            bone.color.custom.select = select
            bone.color.custom.active = active
            colored += 1
        return colored

    def _apply_pole_childof_inverses(self, obj, chains_data):
        """Roda o equivalente ao botão "Set Inverse" nos Child Of que
        dependem de posição -- os dois do pole (local e global) e o
        Child Of_global novo do ik_tip (Hand_IK/Foot_IK) -- senão eles
        "pulam" de lugar assim que a influência for ligada (mesmo com
        influência 0, o Set Inverse precisa rodar logo na criação, já
        com a pose correta, ou o resultado fica errado quando alguém
        subir a influência depois). Usa o operator real do Blender (via
        context override) em vez de matriz manual."""
        prev_mode = obj.mode
        if obj.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")

        view_layer = bpy.context.view_layer
        prev_active = view_layer.objects.active
        view_layer.objects.active = obj

        for data in chains_data:
            targets = [
                (data["pole"], (CONSTRAINT_CHILD_OF_LOCAL, CONSTRAINT_CHILD_OF_GLOBAL)),
                (data["ik_tip"], (CONSTRAINT_CHILD_OF_GLOBAL,)),
            ]
            for bone_name, constraint_names in targets:
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

        view_layer.objects.active = prev_active
        if obj.mode != prev_mode:
            bpy.ops.object.mode_set(mode=prev_mode)

    # ------------------------------------------------------------------
    # Etapa 1 (Edit Mode): collections + bones duplicados
    # ------------------------------------------------------------------

    def _ensure_origin_bone(self, edit_bones, world_down_local):
        """v0.8 -- alguns modelos importados não trazem o ORG "Origin"
        (ver ORIGIN_ORG_NAME). Sem ele, o loop padrão de ORG->CTRL logo
        abaixo nem chega a gerar "Origin_CTRL" (ROOT_MASTER_PARENT/
        CHILD_OF_GLOBAL_TARGET) -- e sem Origin_CTRL, root.master_CTRL
        fica sem parent (ver o WARNING "'Origin_CTRL' not found" em
        _build_root_controls) e todo pole target perde a opção de
        Child Of global (ver "Child Of_global" em _build_pose_
        constraints).

        Se "Origin" não existir, cria um ORG novo, sem parent, no centro
        do mundo -- (0, 0, 0) em espaço local do armature. Este arquivo
        nunca converte POSIÇÃO entre espaço local e mundial em lugar
        nenhum (só a DIREÇÃO "down", ver world_down_local, que é
        rotação, não translação) -- assume, como o resto do arquivo já
        assume implicitamente, que o Object do armature fica na origem
        do mundo (convenção normal de importação de rig de personagem).
        `tail` aponta pra CIMA (-world_down_local) a partir de head, só
        pra ter uma direção/comprimento sensata (ORIGIN_FALLBACK_LENGTH)
        -- não afeta nada funcionalmente, é só o rest da CTRL que sai
        dele.

        Criado ANTES do resto do loop (chamado no topo de
        _build_edit_bones, antes de `org_bones` ser calculado) --
        assim ele entra no set normal de ORG bones e ganha Origin_CTRL/
        MCH/etc. pelo caminho padrão, com o mesmo widget/cor que
        Origin_CTRL sempre teve (ver WGT_ORIGIN/BONE_COLOR_ROOT_HEAD nos
        dicts de override, mais acima no arquivo) -- não precisa de
        nenhum tratamento especial daqui pra frente."""
        if ORIGIN_ORG_NAME in edit_bones:
            return False
        origin = edit_bones.new(ORIGIN_ORG_NAME)
        origin.head = Vector((0.0, 0.0, 0.0))
        down = world_down_local if world_down_local.length > 1e-9 else Vector((0.0, 0.0, -1.0))
        origin.tail = origin.head - down.normalized() * ORIGIN_FALLBACK_LENGTH
        origin.roll = 0.0
        origin.parent = None
        self.report(
            {"INFO"},
            f"No '{ORIGIN_ORG_NAME}' bone found on this armature -- created one at the world center so "
            f"'{ROOT_MASTER_PARENT}' and the rest of the rig can still be generated normally.",
        )
        return True

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
        self._ensure_origin_bone(edit_bones, world_down_local)

        org_bones = [b for b in edit_bones if PROP_RIG_LAYER not in b.keys()]
        org_by_name = {b.name: b for b in org_bones}
        ordered = self._order_top_down(org_bones, org_by_name)

        stats = {"mch": 0, "ctrl": 0, "ik": 0, "ik_mch": 0, "root": 0, "tail": 0}

        for org in ordered:
            coll_org.assign(org)
            coll_export.assign(org)
            if is_attachment_bone(org):
                coll_attachments_imported.assign(org)

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

        resolved_tail_chains = self._resolve_tail_chains(edit_bones, armature)
        tail_chains_data = self._build_tail_layer(armature, edit_bones, resolved_tail_chains, stats)

        self._build_main_collections(armature, edit_bones)
        self._move_main_child_before(armature, COLL_MAIN_TAIL, COLL_MAIN_ROOT)
        self._propagate_pole_and_tip_to_main_collections(edit_bones, chains_data)
        self._apply_bone_collection_overrides(armature, edit_bones, chains_data, tail_chains_data)
        # v0.9 (Etapa 2) -- reordena o painel nativo "Bone Collections"
        # pra bater com a ordem de "Collection Settings" (ver sync_bone_
        # collection_order). Precisa rodar DEPOIS de _apply_bone_collection_
        # overrides -- é só nesse ponto que TODAS as collections (default
        # + customizadas + Head/Spine) já existem de verdade.
        sync_bone_collection_order(armature)
        self._apply_collection_visibility(armature)

        return stats, chains_data, tail_chains_data

    def _resolve_chains(self, edit_bones, armature):
        """Lê armature.hytale_ik_chains e resolve cada item ARM/LEG num
        caminho real de edit bones ORG (root -> ... -> tip). Cadeias
        TAIL são resolvidas à parte, por _resolve_tail_chains -- não
        usam IK/pole nenhum. v0.9 (Etapa 2, ampliado na 2.7 pra incluir
        ATTACHMENTS): HEAD/SPINE/ATTACHMENTS também ficam de fora
        daqui -- não criam bone nenhum, não têm root/tip/pole (ver
        _head_spine_bone_names/_apply_bone_collection_overrides), então
        tentar resolvê-los como uma cadeia de IK quebraria (campos
        vazios/sem sentido pra eles)."""
        resolved = []
        for item in armature.hytale_ik_chains:
            if item.chain_type in ("TAIL", "HEAD", "SPINE", "ATTACHMENTS"):
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
            if item.chain_type != "TAIL":
                continue
            label = item.label or item.root_bone or "(sem nome)"
            if not item.root_bone or not item.tip_bone:
                self.report({"WARNING"}, f"Tail '{label}': root/tip bone name is empty -- skipped.")
                continue
            root = edit_bones.get(item.root_bone)
            if root is None:
                self.report({"WARNING"}, f"Tail '{label}': root bone '{item.root_bone}' not found -- skipped.")
                continue
            if edit_bones.get(item.tip_bone) is None:
                self.report({"WARNING"}, f"Tail '{label}': tip bone '{item.tip_bone}' not found -- skipped.")
                continue
            path = find_org_path(root, item.tip_bone)
            if path is None:
                self.report(
                    {"WARNING"},
                    f"Tail '{label}': no path from '{item.root_bone}' to '{item.tip_bone}' -- skipped.",
                )
                continue
            resolved.append({"item": item, "path": path})
        return resolved

    def _build_tail_layer(self, armature, edit_bones, resolved_tail_chains, stats):
        """Pra cada cadeia TAIL resolvida (v0.7, revisado): quem forma a
        cadeia fisicamente contínua (posicionalmente -- não "connected"
        no sentido do Blender, ver abaixo) são os próprios bones `_CTRL`
        (já criados pelo loop genérico em _build_edit_bones, ANTES desta
        etapa rodar) -- aqui só REDIRECIONA o tail de cada `_CTRL` da
        cauda pro head do próximo segmento (mesmo truque de
        _build_ik_layer: os ORG do Hytale vêm com o eixo Y apontando pra
        cima, não pro filho). use_connect fica DESLIGADO de propósito --
        a posição já bate (tail de um == head do próximo) sem precisar
        da conexão "travada" do Blender, que prenderia o bone e
        impediria reparent/offset (ex.: parent_override). É essa
        continuidade posicional, no bone que o usuário efetivamente
        anima (_CTRL), que deixa a cauda pronta pra um addon de física
        (spring bone, rigid body constraint etc.) hookar de um segmento
        pro próximo sem gap.

        O bone `_Tail` (SUFFIX_TAIL) é um BRIDGE, mesmo princípio exato
        do `_IK_MCH` da cadeia de IK: mesma rest orientation do MCH (ou
        seja, a do ORG original, INTOCADA -- NÃO redirecionada, ao
        contrário do CTRL acima), e filho REAL do `_CTRL` correspondente
        (não do bridge anterior). O MCH normal (criado pelo pipeline
        genérico, já com FK_CopyRotation/FK_CopyScale/FK_CopyLocation
        mirando no CTRL) tem esses MESMOS constraints RETARGETADOS pro
        bridge em vez do CTRL direto (ver _build_tail_pose_constraints)
        -- exatamente por que o `_IK_MCH` existe: copiar rotação em World
        Space de um bone cuja rest orientation foi alterada (o CTRL,
        agora redirecionado) sai errado/invertido sem esse intermediário
        de rest "limpa".

        Hierarquia final por segmento:
            ORG -> (constraint) -> MCH -> (constraint) -> _Tail (bridge)
            _Tail (bridge) -- parent real -> _CTRL
            _CTRL -- parent real -> _CTRL anterior da cauda

        Collections: _CTRL (a cadeia real, editável) fica em Main/Tail,
        visível -- é nela que o usuário seleciona/anima e onde um addon
        de física deve prender os constraints. O bridge _Tail fica em
        Internal/Specials (mesma collection do bridge _IK_MCH, ver
        COLL_MCH_IK -- renomeada de "MCH-IK" pra "Specials" nesta
        versão), oculta por padrão -- é só mecanismo interno, nunca
        precisa ser selecionado."""
        coll_internal = ensure_bone_collection(armature, COLL_INTERNAL)
        coll_specials = ensure_bone_collection(armature, COLL_MCH_IK, parent=coll_internal)
        coll_main = ensure_bone_collection(armature, COLL_MAIN)
        coll_tail = ensure_bone_collection(armature, COLL_MAIN_TAIL, parent=coll_main)

        tail_chains_data = []
        for resolved in resolved_tail_chains:
            chain = resolved["path"]
            item = resolved["item"]
            tip_index = len(chain) - 1

            # 1) Bones _CTRL reais desta cadeia -- já existem (criados
            # pelo loop genérico ANTES de _resolve_tail_chains/
            # _build_tail_layer rodarem, ver _build_edit_bones). Se
            # algum não existir (não deveria acontecer no fluxo normal),
            # avisa e pula a cadeia inteira em vez de quebrar.
            ctrl_bones = []
            for org in chain:
                ctrl = edit_bones.get(org.name + SUFFIX_CTRL)
                if ctrl is None:
                    self.report(
                        {"WARNING"},
                        f"Tail: CTRL bone '{org.name + SUFFIX_CTRL}' not found -- skipped.",
                    )
                    ctrl_bones = []
                    break
                ctrl_bones.append(ctrl)
            if not ctrl_bones:
                continue

            # 2) Redireciona o tail de cada _CTRL pro head do próximo
            # segmento -- toda vez (não só quando criados agora), pra
            # corrigir também cadeias configuradas antes desta revisão
            # ou depois de o usuário mexer nos bones à mão. use_connect
            # fica DESLIGADO de propósito (pedido explícito): a posição
            # já bate (tail de um == head do próximo, calculado abaixo)
            # sem precisar da conexão "travada" do Blender -- os bones
            # continuam livres pra ter parent/offset reparentado (ex.:
            # parent_override) sem o comportamento de "connected bone".
            # A PONTA (último bone, sem próximo segmento pra apontar) é
            # tratada à parte: sempre reseta pro tail/roll ORIGINAL do
            # ORG primeiro (idempotente -- nunca incrementa em cima do
            # que já está no bone, senão rodar "Create Rig" de novo
            # dobraria a rotação a cada vez) e só então aplica a rotação
            # manual opcional (item.tail_tip_rotation_deg, em graus, no
            # eixo LOCAL escolhido em item.tail_tip_rotation_axis -- ver
            # rotate_edit_bone_local_axis).
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
                coll_tail.assign(ctrl)

            # Parent override (campo "Attach To") -- aplica no _CTRL
            # RAIZ da cauda, toda vez (mesmo princípio do fix de
            # parent_override da cadeia de IK): sobrescreve o parent que
            # o loop genérico já deu (o _CTRL do pai ORG real) só se o
            # usuário pediu explicitamente.
            if item.parent_override:
                override_parent = _resolve_parent_override(edit_bones, item.parent_override)
                if override_parent is not None:
                    ctrl_bones[0].parent = override_parent
                    ctrl_bones[0].use_connect = False
                else:
                    self.report(
                        {"WARNING"},
                        f"Parent override '{item.parent_override}' not found for '{ctrl_bones[0].name}' -- "
                        f"left as-is.",
                    )

            # 3) Bridge _Tail por segmento -- rest = ORG original
            # (create_bone_like não redireciona nada), filho REAL do
            # _CTRL correspondente (não do bridge anterior). Vai pra
            # Internal/Specials, não Main/Tail (ver docstring acima).
            tail_bones = []
            for i, org in enumerate(chain):
                bridge, is_new = create_bone_like(edit_bones, org, org.name + SUFFIX_TAIL)
                if is_new:
                    bridge[PROP_RIG_LAYER] = "TAIL"
                    stats["tail"] += 1
                bridge.parent = ctrl_bones[i]  # toda vez -- corrige cadeias de uma revisão anterior também
                bridge.use_connect = False
                coll_specials.assign(bridge)
                tail_bones.append(bridge)

            tail_chains_data.append(
                {
                    "org_names": [b.name for b in chain],
                    "tail_bones": [b.name for b in tail_bones],
                    "ctrl_names": [b.name for b in ctrl_bones],
                    # v0.9 -- Collection Settings (Etapa 1/3). Mesmo mecanismo
                    # do Arm/Leg (ver HytaleIKChainItem.collection_override) --
                    # "Auto" = fica em Main/Tail (coll_tail acima, sem
                    # mudança nenhuma); um nome = _apply_bone_collection_overrides
                    # redireciona os _CTRL desta cauda pra lá.
                    "collection_override": item.collection_override,
                }
            )

        return tail_chains_data

    def _build_tail_pose_constraints(self, obj, tail_chains_data):
        """Pose Mode: retargeta, pro bridge `_Tail`, os MESMOS constraints
        que o loop genérico de _build_pose_constraints já criou no MCH
        mirando no CTRL (FK_CopyRotation/FK_CopyScale/FK_CopyLocation --
        ensure_copy_constraint() só troca o `subtarget`, não recria
        nada). Precisa rodar DEPOIS de _build_pose_constraints. Nenhum
        driver de switch envolvido -- bones de cauda não entram em
        chains_data (só Arm/Leg entram lá), então o loop genérico já os
        deixa com influence=1.0 fixa (sem FK/IK, sempre "ligado"), exatamente
        o que a cauda precisa."""
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

        # PROPERTIES: acima da cabeça, parentado no Head_CTRL, mesmo
        # tamanho/eixo dele -- só existe pra guardar as custom properties
        # de FK/IK switch de todas as cadeias (ver switch_property_name /
        # _build_pose_constraints), longe de qualquer bone que o usuário
        # for de fato animar/posar.
        head_ctrl = edit_bones.get(HEAD_COLLECTION_ROOT)
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
            self.report({"WARNING"}, f"'{HEAD_COLLECTION_ROOT}' not found -- skipping {BONE_PROPERTIES}.")

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

    def _reparent_extra_children(self, edit_bones, org, mch, exclude_name=None):
        """v0.8 -- generaliza o reparent que já existia só pra ponta
        (dedos sob Hand/Foot, sockets de attachment) pra QUALQUER
        segmento da cadeia, incluindo os do meio (ex.: um bone extra
        pendurado em Arm ou Forearm -- alguns modelos trazem isso, e
        antes desse fix esses bones ficavam "descolados" quando a
        cadeia ia pra modo IK, exatamente como um dedo ficaria se não
        fosse reparentado pro _MCH da mão).

        Reparenta pro `mch` dado o _CTRL de todo filho ORG "extra" de
        `org` -- attachment (ver find_attachment_child) e os demais (ver
        find_non_attachment_children). `exclude_name`: usado pelos
        segmentos do MEIO da cadeia (Arm/Forearm) pra excluir o PRÓXIMO
        elo da própria cadeia -- ex.: Forearm É filho de Arm na
        hierarquia crua do ORG, mas já tem seu próprio _IK/_MCH tratado
        à parte logo abaixo, não é um "extra" (reparentar ele aqui por
        engano quebraria a cadeia). A ponta (tip) não passa
        `exclude_name` -- não tem "próximo elo" depois dela.

        Roda toda vez (não só quando o bone é novo) -- corrige rigs já
        gerados antes desta função existir também. Retorna a lista de
        nomes de _CTRL reparentados, pra alimentar
        chains_data["reparented_ctrl_roots"] (ver
        _propagate_pole_and_tip_to_main_collections -- reparentar pro
        _MCH tira esses _CTRL da árvore que o walk de Main/Arm-Leg
        percorre, então precisam ser propagados de volta pra lá
        manualmente, do mesmo jeito que pole/tip/attachment já eram)."""
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
            extra_ctrl = edit_bones.get(extra_org.name + SUFFIX_CTRL)
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
            # Attachments/dedos precisam seguir o resultado FINAL da
            # ponta (FK ou IK, conforme o switch) -- não o ORG puro:
            # reparentar neles funciona ao vivo (ORG == MCH em World
            # Space, sempre, via CONSTRAINT_ORG_TO_MCH), mas o
            # anim_importer.py só sabe projetar corretamente parents
            # terminados em "_CTRL" ou "_MCH" (ver SUFFIX_MCH lá) -- um
            # parent ORG cru cai no caso genérico "bone não animado" e a
            # importação de animação desses bones sai errada. _MCH dá o
            # mesmo resultado visual E é reconhecido pelo importer.
            tip_mch = edit_bones.get(tip_org.name + SUFFIX_MCH) or tip_org
            # v0.8: tip + segmentos do meio (Arm/Forearm) tratados pelo
            # mesmo helper -- ver _reparent_extra_children logo acima.
            reparented_ctrl_roots = self._reparent_extra_children(edit_bones, tip_org, tip_mch)
            attachment_org = find_attachment_child(tip_org)
            attachment_ctrl = edit_bones.get(attachment_org.name + SUFFIX_CTRL) if attachment_org else None

            # Segmentos do MEIO da cadeia (tudo antes da ponta -- ex.:
            # Arm/Forearm de um braço IK): mesmo problema que a ponta já
            # tinha, mesma correção. `exclude_name` tira o PRÓXIMO elo da
            # própria cadeia (ele já tem tratamento dedicado no loop de
            # `ik_bones` logo abaixo -- não é um "extra").
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
                        override_parent = None
                        if override_name:
                            # Alias PRIMEIRO: "Pelvis" tem que resolver pra
                            # "root.pelvis_CTRL", mesmo que já exista um
                            # bone ORG chamado literalmente "Pelvis" na
                            # armature (que quase sempre existe -- é dele
                            # que "Pelvis_CTRL" é gerado). Bug anterior:
                            # o código tentava edit_bones.get(override_name)
                            # PRIMEIRO, e como "Pelvis" (ORG) já existe
                            # desde o import, o alias nunca era consultado
                            # -- Thigh_IK ficava parentado no ORG errado
                            # em vez de root.pelvis_CTRL.
                            alias = PARENT_OVERRIDE_ALIASES.get(override_name)
                            if alias:
                                override_parent = edit_bones.get(alias)
                            else:
                                override_parent = edit_bones.get(override_name)
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

            # Corrige o parent do bone RAIZ da cadeia (índice 0) TODA VEZ,
            # não só quando ele é criado -- rigs gerados com uma versão
            # anterior deste script (antes do fix do alias logo acima)
            # podem ter um "Thigh_IK" (etc.) apontando pro ORG "Pelvis"
            # errado; sem isso, rodar "Create Rig" de novo não conserta
            # bones que já existem (mesmo bone já existente = "if is_new"
            # não roda de novo). Mesmo princípio do
            # _apply_ctrl_parent_overrides, só que pro bone raiz IK.
            if ik_bones and item.parent_override:
                override_name = item.parent_override
                alias = PARENT_OVERRIDE_ALIASES.get(override_name)
                override_parent = edit_bones.get(alias) if alias else edit_bones.get(override_name)
                if override_parent is not None:
                    ik_bones[0].parent = override_parent
                    ik_bones[0].use_connect = False

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

            # v0.8: bone puramente visual -- parent DIRETO no pole_ref (o
            # próprio ORG, ex.: Forearm/Calf; não no _IK nem no _CTRL
            # dele), esticado (Stretch To, ver _build_pose_constraints)
            # até o "_Pole_CTRL" acabado de criar/reaproveitar acima.
            # head = head do pole_ref (o "cotovelo"/"joelho"); tail =
            # head do pole (só o rest -- Stretch To recalcula a cada
            # frame, então não precisa ficar exato). hide_select=True:
            # 100% controlado pelo constraint, nada pra o usuário posar
            # nele.
            pole_line, is_new_pole_line = create_bone_like(edit_bones, pole_ref, root_org.name + SUFFIX_POLE_LINE)
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
                    "ik_root": chain[0].name + SUFFIX_IK,
                    "ik_solver_end": chain[tip_index - 1].name + SUFFIX_IK,
                    "ik_tip": chain[tip_index].name + SUFFIX_IK,
                    "pole": pole.name,
                    "pole_line": pole_line.name,
                    "side": item.side,
                    # v0.8 -- só pra _warn_shared_pole_angle_presets (ver
                    # _build_pose_constraints) checar se uma cadeia de Arm
                    # e uma de Leg estão sem querer usando o MESMO
                    # pole_angle_preset_name (pole_angle_presets é indexado
                    # só por nome+side, não por chain_type -- ver comentário
                    # lá e em templates/__init__.py). Não afeta a resolução
                    # do ângulo em si, só o aviso.
                    "chain_type": item.chain_type,
                    "pole_angle_mode": item.pole_angle_mode,
                    "pole_angle_preset_name": item.pole_angle_preset_name,
                    "pole_angle_manual": item.pole_angle_manual,
                    "pole_angle_fine_tune": item.pole_angle_fine_tune,
                    "extra_ik_location": item.extra_ik_location,
                    # Nome da custom property de FK/IK switch DESTA cadeia,
                    # dentro do bone PROPERTIES (não mais uma property por
                    # bone _IK) -- ver switch_property_name.
                    "switch_property": switch_property_name(chain[tip_index].name, item.side),
                    # Bones _CTRL reparentados pro _MCH da ponta (ver
                    # acima: attachment_ctrl + find_non_attachment_children)
                    # -- ficam FORA da árvore de parent que assign_descendants
                    # caminha em _build_main_collections, então precisam
                    # ser propagados manualmente pra mesma collection do
                    # resto da cadeia (ver _propagate_pole_and_tip_to_main_collections).
                    "reparented_ctrl_roots": reparented_ctrl_roots,
                    # v0.9 -- Collection Settings (Etapa 1). "Auto" = deixa a
                    # collection default que _build_main_collections já montou;
                    # um nome = _apply_bone_collection_overrides redireciona os
                    # bones desta cadeia pra lá depois (ver método).
                    "collection_override": item.collection_override,
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
        """Organização de alto nível por cima de tudo: Main (v0.9.6: era
        Face + Main, nessa ordem -- Face deixou de ser criada
        automaticamente, pedido explícito: "remover a collection Face,
        ela não faz nada... caso algum usuário queira, ele cria
        separadamente" -- ver Collection Settings, onde o usuário pode
        criar uma "Face" (ou qualquer nome) manualmente, aninhada onde
        quiser) + Attachments. Dentro de Main: Head/Spine/Body/Arm L/
        Arm R/Leg L/Leg R/Root (+ o que o usuário tiver criado em
        Collection Settings). Bones de attachment NUNCA entram nessas
        -- só na Attachments."""
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

        limb_roots = _resolve_main_limb_roots(armature, edit_bones)
        assign_descendants(coll_arm_l, limb_roots[COLL_MAIN_ARM_L])
        assign_descendants(coll_arm_r, limb_roots[COLL_MAIN_ARM_R])
        assign_descendants(coll_leg_l, limb_roots[COLL_MAIN_LEG_L])
        assign_descendants(coll_leg_r, limb_roots[COLL_MAIN_LEG_R])

    _MAIN_LIMB_COLLECTION_NAMES = {COLL_MAIN_ARM_L, COLL_MAIN_ARM_R, COLL_MAIN_LEG_L, COLL_MAIN_LEG_R}

    def _propagate_pole_and_tip_to_main_collections(self, edit_bones, chains_data):
        """O pole target e o "_IK" da ponta (mão/pé) ficam SOLTOS na
        hierarquia (sem parent) -- por isso nunca são alcançados pelo
        walk de descendentes que monta Arm L/R e Leg L/R. O "_Pole_Line"
        (v0.8) tem parent, mas é o pole_ref -- um bone ORG, fora da
        árvore _CTRL/_IK que o walk (assign_descendants, em
        _build_main_collections) percorre -- também nunca é alcançado
        por ali. Aqui, pra cada cadeia, descobre em qual sub-collection
        de Main o resto da cadeia (o "_IK" raiz) já caiu, e replica pro
        pole, pro pole line, pro tip e pra todo _CTRL reparentado pro
        _MCH da ponta (attachment_ctrl/dedos -- ver reparented_ctrl_roots
        em _build_ik_layer -- esses também ficam fora da árvore de
        parent normal do walk, do mesmo jeito que o pole/tip, só que por
        reparenting em vez de nascerem sem parent/parentados num ORG)."""
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
        """Reposiciona a bone collection `child_name` (filha de Main) pra
        ficar logo ANTES de `before_name` (outra filha de Main, MESMO
        parent) na lista -- usado pra colocar "Tail" depois de "Leg R" e
        antes de "Root" (v0.7).

        v0.8 -- bug real corrigido aqui (não só o WARNING): a versão
        anterior calculava os índices em `list(armature.collections)`,
        igual _move_collection_to_index faz pra Face/Main -- só que
        Face/Main são collections de NÍVEL RAIZ, e `armature.collections`
        só enxerga collections de nível raiz (ver docstring de
        _find_bone_collection_anywhere, logo acima) -- Tail e Root são
        FILHAS de Main, nunca aparecem nessa lista. `flat.index(child)`
        lançava ValueError toda vez, caía no antigo `except: pass`, e a
        Tail nunca saía do lugar onde nasceu (criada em _build_tail_layer,
        ANTES de Head/Spine/Body/Arm/Leg/Root em _build_main_collections
        -- por isso sempre aparecia no TOPO de Main, não só "não antes de
        Root").

        Correção: usa `child_number` (índice de um bone collection DENTRO
        da lista de filhos do PRÓPRIO parent -- API dedicada exatamente
        pra isso, documentada pela Blender Foundation) em vez do array
        flat inteiro do Armature. Só funciona entre irmãos (mesmo
        parent) -- daí o guard `child.parent != target.parent` abaixo.

        Ajuste de direção: setar child_number pra um valor X reposiciona
        o item pra ficar na posição final X (empurrando o que já estava
        lá pra frente) -- então, se `child` já vem ANTES de `target` na
        lista (current < target.child_number, o caso normal aqui: Tail
        nasce antes de Root), o valor certo pra terminar IMEDIATAMENTE
        ANTES de `target` é `target.child_number - 1` (a posição de
        Root ANTES do reposicionamento vira -1 depois que Tail sai de
        antes dela -- setar direto pro child_number original de Root
        colocaria Tail DEPOIS dela, não antes). Se `child` já vier DEPOIS
        de `target`, não tem esse deslocamento -- usa o valor original.
        """
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
        """v0.9 -- Collection Settings (Etapa 1, ampliado nas Etapas 2/3
        pra cobrir Head/Spine e Tail também -- nenhum tipo fica travado
        numa collection fixa). Roda DEPOIS de _build_main_collections/
        _build_tail_layer e _propagate_pole_and_tip_to_main_collections
        (que continuam responsáveis pelo default de Arm/Leg/Tail/Body/
        Root, sem nenhuma mudança) -- aqui REDIRECIONA quem pediu um
        `collection_override` != "" (ver HytaleIKChainItem.collection_override/
        interface.py), e TAMBÉM faz a atribuição inteira de Head/Spine
        (que não têm nenhum mecanismo de default fora daqui -- ver bloco
        abaixo)."""

        def _resolve_target(target_name, context_label):
            settings_item = next(
                (c for c in armature.hytale_bone_collections if c.name == target_name), None
            )
            if settings_item is None:
                self.report(
                    {"WARNING"},
                    f"Bone Settings: collection '{target_name}' not found in Collection Settings (may "
                    f"have been deleted/renamed) -- '{context_label}' kept in the default collection instead.",
                )
                return None
            # v0.9.6 -- ERA "Face ou Main" fixo -- agora anda a cadeia de
            # parents de verdade (aninhamento livre, ver
            # _resolve_collection_parent), criando qualquer ancestral que
            # ainda não exista no caminho.
            parent = _resolve_collection_parent(armature, settings_item)
            return ensure_bone_collection(armature, target_name, parent=parent)

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

        # --- Tail (tail_chains_data) --------------------------------------
        # Diferente de Arm/Leg, não precisa andar pela hierarquia
        # (collect_descendants_inclusive) -- os bones _CTRL da cauda já
        # estão listados prontos em "ctrl_names" (ver _build_tail_layer),
        # então redireciona direto por nome.
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

        # --- Head/Spine/Attachments (armature.hytale_ik_chains diretamente) -----------
        # Diferente de Arm/Leg/Tail: HEAD/SPINE/ATTACHMENTS não criam
        # bone nenhum (ver _resolve_chains, que já pula esses três
        # chain_type) e não aparecem em chains_data/tail_chains_data --
        # lê direto de armature.hytale_ik_chains. Também diferente no
        # fallback: "Auto" NÃO significa "não faz nada" (não existe
        # nenhum mecanismo antigo que já assine os bones CONFIGURADOS
        # aqui pra lugar nenhum, diferente de Arm/Leg/Tail, que têm
        # _build_main_collections/_build_tail_layer cobrindo o default)
        # -- "Auto" aqui quer dizer "assina no default certo pro tipo"
        # (Head, Spine ou Attachments).
        _organizational_defaults = {
            "HEAD": COLL_MAIN_HEAD, "SPINE": COLL_MAIN_SPINE, "ATTACHMENTS": COLL_ATTACHMENTS,
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

            # v0.9.3 -- FIX: os campos (head_bone/pelvis_bone/etc.) guardam
            # o nome do bone ORG (mesma convenção de root_bone/tip_bone em
            # Arm/Leg -- ver _resolve_chains) -- quem precisa ir pra
            # collection é o _CTRL correspondente (o que o usuário
            # seleciona/anima de verdade), não o ORG cru. Bug relatado:
            # "os bones selecionados... vão os bones originais, mas
            # precisa ir os bones de CTRL".
            for name in names:
                ctrl_name = name + SUFFIX_CTRL
                bone = edit_bones.get(ctrl_name)
                if bone is None:
                    self.report(
                        {"WARNING"},
                        f"{item.chain_type.title()} '{item.label or '?'}': control bone '{ctrl_name}' not "
                        f"found (expected an ORG bone named '{name}' with a matching '_CTRL') -- skipped.",
                    )
                    continue
                _redirect(bone, target_coll)

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
        """v0.8 -- sanity check, não muda nada no rig (ver docstring
        completa em find_shared_pole_angle_preset_warnings, no topo deste
        arquivo -- v0.9/Tarefa C extraiu a detecção em si pra uma função
        de módulo pura, reaproveitada por RIG_OT_hytale_validate_rig em
        diagnostics.py, pra não ter duas cópias da mesma checagem
        divergindo; este método só formata o aviso e chama self.report,
        que só um Operator tem)."""
        for name, types in find_shared_pole_angle_preset_warnings(chains_data):
            self.report(
                {"WARNING"},
                f"Pole angle preset '{name}' is used in PRESET mode by more than one chain type "
                f"({', '.join(types)}) -- they'll share the exact same calibrated angle per side. "
                f"If that's not intentional, give each chain type its own preset name.",
            )

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
        self._warn_shared_pole_angle_presets(chains_data)
        for data in chains_data:
            org_names = data["org_names"]
            ik_root = data["ik_root"]
            ik_solver_end = data["ik_solver_end"]
            ik_tip = data["ik_tip"]
            pole_name = data["pole"]
            switch_prop = data["switch_property"]

            if BONE_PROPERTIES in pose_bones:
                ensure_fk_ik_switch_property(pose_bones[BONE_PROPERTIES], switch_prop)
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
                # Presets vêm do rig template ATIVO no Armature (ver
                # armature.hytale_active_rig_template, setado por
                # RIG_OT_hytale_ik_chain_load_defaults) -- ANTES vinham só
                # de ARM_POLE_ANGLE_PRESET, fixo/exclusivo do Player.
                # v0.9/Tarefa C: o lookup em si (rig_template ->
                # pole_angle_presets -> nome -> side) virou a função de
                # módulo resolve_pole_angle_preset_degrees (topo deste
                # arquivo), reaproveitada por RIG_OT_hytale_validate_rig
                # (diagnostics.py) pra checar a MESMA coisa sem duplicar
                # a lógica -- resultado idêntico ao que estava inline aqui.
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
                    # não mexeu nesta cadeia) -- ver docstring desse método
                    # pra entender de onde vem e por que o sinal já está
                    # certo pra somar direto aqui.
                    pole_angle = math.radians(preset_deg) + data.get("pole_angle_joint_fix_delta", 0.0)
            else:
                # Sinal invertido: correção empírica (braço e perna
                # precisavam do sinal oposto ao que a fórmula portada
                # calcula).
                pole_angle = -compute_pole_angle(obj, ik_root, pole_name) + math.radians(
                    data["pole_angle_fine_tune"]
                )
            ensure_ik_constraint(pose_bones[ik_solver_end], obj, ik_tip, pole_name, chain_count, pole_angle)

            # Child Of no Origin_CTRL, na ponta da cadeia (Hand_IK/Foot_IK)
            # -- ATIVO por padrão (influência 1.0), diferente do "Child
            # Of_global" do pole logo abaixo (que começa em 0). Set
            # Inverse é aplicado depois, em _apply_pole_childof_inverses
            # (mesmo mecanismo do pole), senão o bone pularia de lugar na
            # hora que o constraint entrasse em vigor.
            if CHILD_OF_GLOBAL_TARGET in pose_bones:
                ensure_child_of_constraint(
                    pose_bones[ik_tip], obj, CHILD_OF_GLOBAL_TARGET, CONSTRAINT_CHILD_OF_GLOBAL, 1.0
                )
            else:
                self.report(
                    {"WARNING"},
                    f"'{CHILD_OF_GLOBAL_TARGET}' not found -- skipping {CONSTRAINT_CHILD_OF_GLOBAL} on '{ik_tip}'.",
                )

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

            # v0.8: "_Pole_Line" -- Stretch To simples, sempre mirando no
            # "_Pole_CTRL" desta MESMA cadeia/lado (pole_name já resolvido
            # acima). 100% visual -- não depende de switch FK/IK nem de
            # nenhuma outra property.
            pole_line_name = data.get("pole_line")
            if pole_line_name and pole_line_name in pose_bones and pole_name in pose_bones:
                ensure_stretch_to_constraint(
                    pose_bones[pole_line_name], obj, pole_name, CONSTRAINT_POLE_LINE_STRETCH
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

                add_switch_driver(fk_rot, obj, BONE_PROPERTIES, switch_prop, expression="1 - switch")
                add_switch_driver(ik_rot, obj, BONE_PROPERTIES, switch_prop, expression="switch")
                add_switch_driver(fk_scale, obj, BONE_PROPERTIES, switch_prop, expression="1 - switch")
                add_switch_driver(ik_scale, obj, BONE_PROPERTIES, switch_prop, expression="switch")
                if fk_loc is not None:
                    add_switch_driver(fk_loc, obj, BONE_PROPERTIES, switch_prop, expression="1 - switch")

                # IK_CopyLocation extra -- só se o item pediu (ex.: Thigh,
                # cuja raiz é parentada fora da hierarquia ORG normal).
                if data["extra_ik_location"] and org_name == org_names[0] and fk_loc is not None:
                    ik_loc = ensure_copy_constraint(
                        mch_pose, obj, bridge_name, "LOCATION", CONSTRAINT_IK_LOC, space="WORLD"
                    )
                    add_switch_driver(ik_loc, obj, BONE_PROPERTIES, switch_prop, expression="switch")

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


class RIG_OT_hytale_shape_template_apply(Operator):
    """Troca só o template de custom shapes ativo
    (armature.hytale_active_shape_template), sem mexer na lista de
    cadeias de IK -- útil pra testar shapes diferentes em cima do mesmo
    rig, ou quando o rig template carregado não tem um shape_template
    correspondente. Não reaplica shapes num rig já gerado sozinho -- rode
    "Create Rig" de novo depois (idempotente, seguro de repetir) pra
    aplicar."""

    bl_idname = "armature.hytale_shape_template_apply"
    bl_label = "Set Hytale Shape Template"
    bl_description = "Set the active custom shape template (run 'Create Rig' again to apply)"
    bl_options = {"REGISTER", "UNDO"}

    template: StringProperty(
        name="Shape Template",
        default="",
        description="Shape template name to activate -- leave empty to use whatever is currently selected in "
        "the Character Templates dropdown (wm.hytale_shape_template_selected, see interface.py)",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        template_name = self.template or context.window_manager.hytale_shape_template_selected
        if not template_name or template_name == _TEMPLATE_NONE:
            self.report({"WARNING"}, "No shape template selected.")
            return {"CANCELLED"}
        if get_shape_template(template_name) is None:
            self.report({"WARNING"}, f"Unknown shape template '{template_name}'.")
            return {"CANCELLED"}
        context.active_object.data.hytale_active_shape_template = template_name
        self.report(
            {"INFO"}, f"Active shape template set to '{template_name}' -- run 'Create Rig' again to apply.",
        )
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Seleção de template (Rig/Shape/Collection) usada pela box "Character
# Templates" do interface.py -- UM EnumProperty compacto por tipo, no
# WindowManager (wm.hytale_rig_template_selected etc., registrados no
# fim deste arquivo com items=rig_template_enum_items/
# shape_template_enum_items/collection_template_enum_items, de
# templates/__init__.py). Clicar no dropdown mostra a lista (igual o
# antigo operator_menu_enum já fazia) -- a DIFERENÇA é que escolher um
# item aqui só GRAVA a seleção (é uma property comum, não um operador),
# sem aplicar nada sozinho; "Apply"/"Delete" (botões ao lado, no
# interface.py) é que leem essa seleção e agem. _template_source()
# abaixo é só pra saber se o item selecionado pode ser deletado (source
# "user") ou não (builtin).
# ---------------------------------------------------------------------------




def _template_source(list_func, name):
    """"builtin"/"user" do template `name` segundo `list_func()`
    (list_rig_templates/list_shape_templates/list_collection_templates),
    ou None se `name` não corresponder a nenhum template conhecido (nada
    selecionado ainda, ou o sentinel "NONE" que os *_enum_items() de
    templates/__init__.py devolvem quando a pasta está vazia)."""
    for entry in list_func():
        if entry["name"] == name:
            return entry["source"]
    return None# ---------------------------------------------------------------------------


# Campos de HytaleIKChainItem serializáveis pra JSON (mesma lista usada
# por RIG_OT_hytale_ik_chain_load_defaults pra ler de volta).
_IK_CHAIN_JSON_FIELDS = (
    "chain_type", "label", "root_bone", "tip_bone", "pole_bone", "parent_override", "side",
    "pole_invert", "pole_distance", "pole_angle_mode", "pole_angle_preset_name",
    "pole_angle_manual", "pole_angle_fine_tune", "extra_ik_location", "tail_tip_rotation_axis", "tail_tip_rotation_deg",
)

# Bones utilitários (não derivam de nenhuma cadeia IK) que também
# recebem custom shape e fazem sentido salvar num template de shapes --
# ver WIDGET_NAME_OVERRIDES/BONE_ROOT_* no topo do arquivo.
_UTILITY_SHAPE_BONES = (BONE_ROOT_MASTER, BONE_ROOT_SPINE, BONE_ROOT_PELVIS, HEAD_COLLECTION_ROOT, ROOT_MASTER_PARENT)


class RIG_OT_hytale_rig_template_save(Operator):
    """Salva a lista ATUAL de armature.hytale_ik_chains (mais o toggle de
    correção de junta) como um template novo em Documentos/Hyblend/
    templates/rig/<nome>.json -- não mexe em nenhum arquivo builtin do
    addon. Os campos avançados (pole_angle_presets/ik_joint_x_overrides/
    widget_translation_x_overrides) saem vazios -- edite o .json na mão
    depois se este personagem precisar deles (ver schema em
    templates/__init__.py)."""

    bl_idname = "armature.hytale_rig_template_save"
    bl_label = "Save Rig Template"
    bl_description = "Save the current IK chain list as a new template in your Documents/Hyblend folder"
    bl_options = {"REGISTER"}

    template_name: StringProperty(name="Template Name", default="")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE" and len(obj.data.hytale_ik_chains) > 0

    def invoke(self, context, event):
        self.template_name = context.active_object.data.hytale_active_rig_template or "New Character"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "template_name")

    def execute(self, context):
        if not self.template_name.strip():
            self.report({"WARNING"}, "Template name cannot be empty.")
            return {"CANCELLED"}

        armature = context.active_object.data
        entries = []
        for item in armature.hytale_ik_chains:
            entries.append({field: getattr(item, field) for field in _IK_CHAIN_JSON_FIELDS})

        data = {
            "description": f"User-saved rig template ({len(entries)} IK chain(s)).",
            "shape_template": armature.hytale_active_shape_template or self.template_name,
            "ik_chains": entries,
            "pole_angle_presets": {},
            "apply_ik_joint_fix": bool(getattr(armature, "hytale_apply_ik_joint_fix", False)),
            "ik_joint_x_overrides": {},
            "widget_translation_x_overrides": {},
        }
        path = save_rig_template(self.template_name, data)
        armature.hytale_active_rig_template = self.template_name
        self.report({"INFO"}, f"Saved rig template '{self.template_name}' to '{path}'.")
        return {"FINISHED"}


class RIG_OT_hytale_rig_template_delete(Operator):
    """Apaga (do disco, em Documentos/Hyblend/templates/rig/) o rig
    template selecionado no dropdown da box "Character Templates" -- só
    funciona pra templates do USUÁRIO (source == "user", ver poll()); um
    builtin (dentro da pasta do addon) nunca aparece deletável daqui, pra
    não sumir sozinho numa atualização do addon nem precisar reinstalar
    pra recuperar."""

    bl_idname = "armature.hytale_rig_template_delete"
    bl_label = "Delete Rig Template"
    bl_description = "Delete the selected rig template from your Documents/Hyblend folder (user templates only)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        name = context.window_manager.hytale_rig_template_selected
        return bool(name) and _template_source(list_rig_templates, name) == "user"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        name = context.window_manager.hytale_rig_template_selected
        if not delete_rig_template(name):
            self.report({"WARNING"}, f"Could not delete rig template '{name}' (builtin, or already gone).")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Deleted rig template '{name}'.")
        return {"FINISHED"}


class RIG_OT_hytale_shape_template_save(Operator):
    """Salva o custom shape ATUAL (translation/rotation/scale/widget) de
    todo bone _CTRL/_CTRL-IK/utilitário do Armature ativo como um
    template novo em Documentos/Hyblend/templates/shapes/<nome>.json --
    útil depois de ajustar os shapes na mão no viewport e querer guardar
    esse resultado como ponto de partida reutilizável, sem mexer em
    nenhum arquivo builtin do addon."""

    bl_idname = "armature.hytale_shape_template_save"
    bl_label = "Save Shape Template"
    bl_description = "Save the current custom shapes as a new template in your Documents/Hyblend folder"
    bl_options = {"REGISTER"}

    template_name: StringProperty(name="Template Name", default="")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE" and obj.pose is not None

    def invoke(self, context, event):
        self.template_name = context.active_object.data.hytale_active_shape_template or "New Character"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "template_name")

    def execute(self, context):
        if not self.template_name.strip():
            self.report({"WARNING"}, "Template name cannot be empty.")
            return {"CANCELLED"}

        obj = context.active_object
        bones = {}
        for pb in obj.pose.bones:
            layer = pb.bone.get(PROP_RIG_LAYER)
            if layer not in ("CTRL", "CTRL-IK") and pb.name not in _UTILITY_SHAPE_BONES:
                continue
            if pb.custom_shape is None:
                continue
            entry = {
                "translation": list(pb.custom_shape_translation),
                "rotation_deg": [math.degrees(v) for v in pb.custom_shape_rotation_euler],
                # resolve_custom_shape_scale() em vez de custom_shape_scale_xyz
                # direto -- o driver de FK/IK zera esse eixo quando o modo
                # oposto está ativo (ver função pra detalhes); sem isso, salvar
                # com o IK ativo gravaria 0 pro FK (e vice-versa).
                "scale": list(resolve_custom_shape_scale(pb)),
            }
            if pb.custom_shape.name not in (WGT_DEFAULT_FALLBACK,):
                entry["widget"] = pb.custom_shape.name
            bones[pb.name] = entry

        if not bones:
            self.report({"WARNING"}, "No CTRL/CTRL-IK bone with a custom shape found -- nothing to save.")
            return {"CANCELLED"}

        data = {
            "description": f"User-saved shape template ({len(bones)} bone(s)).",
            "bones": bones,
        }
        path = save_shape_template(self.template_name, data)
        obj.data.hytale_active_shape_template = self.template_name
        self.report({"INFO"}, f"Saved shape template '{self.template_name}' ({len(bones)} bone(s)) to '{path}'.")
        return {"FINISHED"}


class RIG_OT_hytale_shape_template_delete(Operator):
    """Mesma ideia de RIG_OT_hytale_rig_template_delete, pra shapes/
    <nome>.json -- só templates do usuário, nunca builtin."""

    bl_idname = "armature.hytale_shape_template_delete"
    bl_label = "Delete Shape Template"
    bl_description = "Delete the selected shape template from your Documents/Hyblend folder (user templates only)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        name = context.window_manager.hytale_shape_template_selected
        return bool(name) and _template_source(list_shape_templates, name) == "user"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        name = context.window_manager.hytale_shape_template_selected
        if not delete_shape_template(name):
            self.report({"WARNING"}, f"Could not delete shape template '{name}' (builtin, or already gone).")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Deleted shape template '{name}'.")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Collection Templates -- mesmo espírito de rig/shape acima, mas salva a
# ORGANIZAÇÃO de bone collections (nome + hierarquia de parent + membros)
# em vez de cadeias de IK ou custom shapes. O usuário cria as collections
# e associa bones a elas pelo painel NATIVO de Bone Collections do
# Blender (Armature Data Properties -- decisão explícita, ver histórico
# do chat: reaproveita uma UI que o Blender já tem em vez de duplicar
# dentro do addon); Save aqui só tira uma "foto" de tudo que existir
# nessa hora, MENOS o que RESERVED_MAIN_COLLECTION_NAMES já cobre (essas
# são geradas sozinhas por "Create Rig", salvá-las de novo seria
# redundante e o Apply não saberia o que fazer com uma "Arm L" duplicada).
# ---------------------------------------------------------------------------


def _apply_collection_template_entries(armature, edit_bones, entries, report):
    """Recria (idempotente, via ensure_bone_collection) cada collection
    descrita em `entries` (lista de {"name", "parent", "bones"} -- ver
    schema de collections/<nome>.json em templates/__init__.py) e
    reassina os bones listados. Resolve o parent em múltiplas passadas --
    a ORDEM das entries no .json não precisa ser pai-antes-do-filho,
    porque a API do Blender só deixa criar uma bone collection já com o
    pai definido (não dá pra reparentar depois de criada, ao contrário
    de mover/renomear). Uma entry cujo parent nunca resolve (nome que não
    bate com nenhuma outra entry nem com uma collection já existente no
    armature) vira collection de nível raiz, com aviso -- uma entry mal
    formada nunca derruba a operação inteira."""
    created = {}
    remaining = list(entries)
    progress = True
    while remaining and progress:
        progress = False
        still = []
        for entry in remaining:
            name = entry.get("name")
            if not name:
                continue
            parent_name = entry.get("parent")
            parent_coll = None
            if parent_name:
                parent_coll = created.get(parent_name) or _find_bone_collection_anywhere(armature, parent_name)
                if parent_coll is None:
                    still.append(entry)
                    continue
            created[name] = ensure_bone_collection(armature, name, parent=parent_coll)
            progress = True
        remaining = still

    for entry in remaining:
        name = entry.get("name")
        if not name:
            continue
        created[name] = ensure_bone_collection(armature, name, parent=None)
        report(
            {"WARNING"},
            f"Collection template: parent '{entry.get('parent')}' not found for '{name}' -- created at top level.",
        )

    assigned = 0
    missing_bones = set()
    for entry in entries:
        coll = created.get(entry.get("name"))
        if coll is None:
            continue
        for bone_name in entry.get("bones", []):
            bone = edit_bones.get(bone_name)
            if bone is None:
                missing_bones.add(bone_name)
                continue
            coll.assign(bone)
            assigned += 1
    return assigned, missing_bones


class RIG_OT_hytale_collection_template_save(Operator):
    """Salva TODAS as bone collections do Armature ativo que NÃO
    pertencem ao conjunto que "Create Rig" já gerencia sozinho (ver
    RESERVED_MAIN_COLLECTION_NAMES) como um template novo em Documentos/
    Hyblend/templates/collections/<nome>.json. Lê a membership direto de
    armature.bones[...].collections -- funciona em Object/Pose Mode, não
    precisa entrar em Edit Mode só pra salvar (ao contrário do Apply, que
    precisa pra poder chamar coll.assign())."""

    bl_idname = "armature.hytale_collection_template_save"
    bl_label = "Save Collection Template"
    bl_description = (
        "Save the armature's custom bone collections (created via Blender's native Bone Collections panel) "
        "as a new template in your Documents/Hyblend folder"
    )
    bl_options = {"REGISTER"}

    template_name: StringProperty(name="Template Name", default="")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def invoke(self, context, event):
        self.template_name = context.active_object.data.hytale_active_collection_template or "New Character"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "template_name")

    def execute(self, context):
        if not self.template_name.strip():
            self.report({"WARNING"}, "Template name cannot be empty.")
            return {"CANCELLED"}

        armature = context.active_object.data
        custom_colls = [c for c in _iter_all_collections(armature) if c.name not in RESERVED_MAIN_COLLECTION_NAMES]
        if not custom_colls:
            self.report(
                {"WARNING"},
                "No custom bone collection found (only the auto-generated ones exist) -- nothing to save. "
                "Create one first in the Armature Data Properties > Bone Collections panel.",
            )
            return {"CANCELLED"}

        custom_names = {c.name for c in custom_colls}
        bones_by_coll = {c.name: [] for c in custom_colls}
        for bone in armature.bones:
            for coll in bone.collections:
                if coll.name in custom_names:
                    bones_by_coll[coll.name].append(bone.name)

        entries = [
            {
                "name": coll.name,
                "parent": coll.parent.name if coll.parent is not None else None,
                "bones": bones_by_coll[coll.name],
            }
            for coll in custom_colls
        ]

        data = {
            "description": f"User-saved collection template ({len(entries)} collection(s)).",
            "collections": entries,
        }
        path = save_collection_template(self.template_name, data)
        armature.hytale_active_collection_template = self.template_name
        self.report(
            {"INFO"},
            f"Saved collection template '{self.template_name}' ({len(entries)} collection(s)) to '{path}'.",
        )
        return {"FINISHED"}


class RIG_OT_hytale_collection_template_apply(Operator):
    """Aplica o template de collections selecionado na lista da box
    "Character Templates": cria (ou reaproveita) cada bone collection
    descrita nele e reassina os bones listados -- ADITIVO, nunca remove
    uma collection nem desassocia um bone que já estava lá por outro
    motivo (mesmo espírito idempotente do resto do pipeline, ver
    _build_main_collections). Entra e sai do Edit Mode sozinho (precisa
    dele pra chamar coll.assign()), restaura o modo anterior no final."""

    bl_idname = "armature.hytale_collection_template_apply"
    bl_label = "Apply Collection Template"
    bl_description = "Apply the selected collection template to the active armature"
    bl_options = {"REGISTER", "UNDO"}

    template_name: StringProperty(
        name="Template",
        default="",
        description="Collection template name to apply -- leave empty to use whatever is currently selected "
        "in the Character Templates dropdown (wm.hytale_collection_template_selected, see interface.py)",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        name = self.template_name or context.window_manager.hytale_collection_template_selected
        if not name or name == _TEMPLATE_NONE:
            self.report({"WARNING"}, "No collection template selected.")
            return {"CANCELLED"}

        data = get_collection_template(name)
        entries = data.get("collections") if data else None
        if not entries:
            self.report({"WARNING"}, f"Unknown or empty collection template '{name}'.")
            return {"CANCELLED"}

        obj = context.active_object
        armature = obj.data
        prev_mode = obj.mode
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            assigned, missing_bones = _apply_collection_template_entries(
                armature, armature.edit_bones, entries, self.report,
            )
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
            if prev_mode != "OBJECT":
                bpy.ops.object.mode_set(mode=prev_mode)

        armature.hytale_active_collection_template = name
        msg = f"Applied collection template '{name}': {assigned} bone assignment(s) across {len(entries)} collection(s)."
        if missing_bones:
            msg += f" {len(missing_bones)} bone(s) not found on this armature (skipped)."
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class RIG_OT_hytale_collection_template_delete(Operator):
    """Mesma ideia de RIG_OT_hytale_rig_template_delete, pra collections/
    <nome>.json -- só templates do usuário, nunca builtin."""

    bl_idname = "armature.hytale_collection_template_delete"
    bl_label = "Delete Collection Template"
    bl_description = (
        "Delete the selected collection template from your Documents/Hyblend folder (user templates only)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        name = context.window_manager.hytale_collection_template_selected
        return bool(name) and _template_source(list_collection_templates, name) == "user"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        name = context.window_manager.hytale_collection_template_selected
        if not delete_collection_template(name):
            self.report({"WARNING"}, f"Could not delete collection template '{name}' (builtin, or already gone).")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Deleted collection template '{name}'.")
        return {"FINISHED"}
