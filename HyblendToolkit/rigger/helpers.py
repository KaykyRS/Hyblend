"""Auto-Rigger -- helpers genéricos de bone/collection/hierarquia, sem estado próprio."""

import math
import re
from collections import deque

from mathutils import Matrix

from .constants import (
    ARM_COLLECTION_ROOTS,
    ARM_COLLECTION_ROOTS_NO_SHOULDER,
    ATTACHMENT_NAME_HINT,
    BONE_ROOT_PELVIS,
    COLL_MAIN_ARM_L,
    COLL_MAIN_ARM_R,
    COLL_MAIN_LEG_L,
    COLL_MAIN_LEG_R,
    HEAD_COLLECTION_ROOT,
    LEG_COLLECTION_ROOTS,
    ORIGIN_ORG_NAME,
    PARENT_OVERRIDE_ALIASES,
    PROP_CONTROL_NAME,
    PROP_RIG_LAYER,
    PROP_SOURCE_ORG,
    ROOT_MASTER_PARENT,
    ROOT_MASTER_SOURCE,
    ROOT_MAX_COUNT,
    SPINE_FOLLOW_BONES,
    SUFFIX_CTRL,
    SUFFIX_IK,
    SUFFIX_MCH,
    SUFFIX_MCH_IK_TRANSFER,
    SUFFIX_MCH_TRANSFER,
    SUFFIX_POLE,
    SUFFIX_POLE_LINE,
)


def resolve_head_chain_item(armature):
    """Entrada HEAD "principal" de `armature.hytale_ik_chains` -- a
    usada por tudo que só faz sentido pra UMA cabeça por rig
    (PROPERTIES/FK-IK switch, Head Follow, a bone collection Main/Head,
    o widget/cor dedicados do Head_CTRL). Personagem com mais de uma
    entrada HEAD (criatura com várias cabeças) escolhe via o campo
    `head_is_main` (radio button entre as entradas HEAD -- ver
    _head_is_main_update em bone_settings.py, marcado True por padrão só
    na PRIMEIRA entrada HEAD adicionada). Se nenhuma estiver marcada
    (raro -- ex. template antigo salvo antes deste campo existir, ou o
    usuário desmarcou a única), cai na primeira entrada HEAD com
    head_bone preenchido, mesmo comportamento de antes desta opção
    existir. None se não houver entrada HEAD nenhuma com head_bone
    preenchido."""
    head_items = [
        item for item in getattr(armature, "hytale_ik_chains", [])
        if item.chain_type == "HEAD" and item.head_bone
    ]
    if not head_items:
        return None
    return next((item for item in head_items if getattr(item, "head_is_main", False)), head_items[0])


def resolve_head_ctrl_name(armature):
    """Nome do bone `_CTRL` da cabeça "principal" (ver
    resolve_head_chain_item), resolvido a partir do `head_bone`
    configurado nela -- em vez de assumir que o ORG da cabeça se chama
    literalmente "Head" (era exatamente isso que HEAD_COLLECTION_ROOT
    fazia antes, hardcoded).

    Bug real encontrado num personagem (Ponyta) cujo bone de cabeça é
    "head" minúsculo, não "Head": PROPERTIES nunca era criado (dependia
    de achar "Head_CTRL" nos edit bones), e com ele nem os custom
    properties de FK/IK switch -- resultado: rig gerado sem nenhum jeito
    de trocar FK/IK. O mesmo hardcode também quebrava, em silêncio, Head
    Follow (Free/Lock), a collection Main/Head e o widget/cor especiais
    do Head_CTRL.

    Cai no default legado HEAD_COLLECTION_ROOT ("Head_CTRL") se não
    houver entrada HEAD com head_bone preenchido -- mantém o
    comportamento de sempre pra quem ainda não configurou Bone Settings
    nenhum (ex.: primeiro "Create Rig" antes até de rodar Auto-Detect)."""
    item = resolve_head_chain_item(armature)
    if item is None:
        return HEAD_COLLECTION_ROOT
    return control_name(armature, item.head_bone, SUFFIX_CTRL)


# --- Root/Origin a partir do Bone Settings ----------------------------
#
# Antes: o Origin era SEMPRE um ORG chamado literalmente "Origin" (criado
# no centro do mundo se faltasse). Agora a entrada ROOT diz qual bone é
# o Origin principal (Root 1) e quais roots ficam acima dele (Root 2 é
# pai do Root 1, Root 3 pai do Root 2...). Sem entrada ROOT (ou com o
# Root 1 vazio), vale o comportamento legado.


def resolve_root_item(armature):
    """Primeira entrada ROOT de `armature.hytale_ik_chains`, ou None."""
    return next((it for it in getattr(armature, "hytale_ik_chains", []) if it.chain_type == "ROOT"), None)


def default_root_bone_name(slot):
    """Nome usado por um slot "New Bone" com o campo vazio."""
    return ORIGIN_ORG_NAME if slot == 1 else f"Root{slot}"


def resolve_root_slots(armature):
    """[(slot, nome_org, criar)] dos slots de root VÁLIDOS da entrada
    ROOT, em ordem (slot 1 = Origin principal). Slot sem nome e sem
    "New Bone" é pulado. [] se não houver entrada ROOT, ou se o Root 1
    não estiver definido -- sem Origin principal a entrada inteira é
    ignorada e vale o comportamento legado (evita um Root 2 "órfão"
    virando Origin sem o usuário perceber)."""
    item = resolve_root_item(armature)
    if item is None:
        return []
    slots = []
    for slot in range(1, min(item.root_count, ROOT_MAX_COUNT) + 1):
        name = (getattr(item, f"root_bone_{slot}", "") or "").strip()
        create = bool(getattr(item, f"root_create_{slot}", False))
        if name.endswith(SUFFIX_CTRL):
            name = name[: -len(SUFFIX_CTRL)]
        if not name and create:
            name = default_root_bone_name(slot)
        if not name:
            if slot == 1:
                return []
            continue
        slots.append((slot, name, create))
    # O mesmo bone em dois slots faria ele virar pai dele mesmo -- mantém
    # só a primeira ocorrência.
    seen = set()
    unique = []
    for entry in slots:
        if entry[1] not in seen:
            seen.add(entry[1])
            unique.append(entry)
    return unique


def resolve_root_org_names(armature):
    """Nomes ORG dos roots, do Origin principal pra cima. Sem entrada
    ROOT válida: [ORIGIN_ORG_NAME] (legado)."""
    slots = resolve_root_slots(armature)
    if not slots:
        return [ORIGIN_ORG_NAME]
    return [name for _slot, name, _create in slots]


def resolve_origin_ctrl_name(armature):
    """_CTRL do Origin principal (Root 1) -- pai do root.master_CTRL e
    alvo do Child Of global dos poles/tips de IK. Sem entrada ROOT:
    "Origin_CTRL" (legado)."""
    slots = resolve_root_slots(armature)
    if not slots:
        return ROOT_MASTER_PARENT
    return control_name(armature, slots[0][1], SUFFIX_CTRL)


# --- Spine/Pelvis a partir do Bone Settings ---------------------------
#
# Antes: root.master_CTRL/root.spine_CTRL nasciam de um ORG chamado
# literalmente "Belly", root.pelvis_CTRL exigia "Belly" + "Pelvis",
# Pelvis_CTRL/Belly_CTRL tinham parent forçado por nome e o Spine Follow
# só existia em "Belly_CTRL"/"Chest_CTRL". Agora tudo sai da entrada
# SPINE (Pelvis + Spine 1..N). Sem entrada SPINE, cai nos nomes legados
# -- mesmo comportamento de sempre pro Player sem Bone Settings.
LEGACY_PELVIS_ORG = "Pelvis"


def resolve_spine_item(armature):
    """Primeira entrada SPINE de `armature.hytale_ik_chains`, ou None --
    mesmo critério que generate.py já usava pro spine_ctrl_enabled."""
    return next((it for it in getattr(armature, "hytale_ik_chains", []) if it.chain_type == "SPINE"), None)


def resolve_pelvis_org_name(armature):
    """Nome do ORG que faz o papel de Pelvis: o campo "Pelvis" da
    entrada SPINE; sem ele, o nome legado "Pelvis"."""
    item = resolve_spine_item(armature)
    if item is not None and (item.pelvis_bone or "").strip():
        return item.pelvis_bone.strip()
    return LEGACY_PELVIS_ORG


def resolve_spine_segment_org_names(armature):
    """Bones da coluna ACIMA do Pelvis (Spine 1..N, respeitando
    spine_count, só os preenchidos). Sem entrada SPINE: os nomes legados
    do Spine Follow ("Belly", "Chest")."""
    item = resolve_spine_item(armature)
    if item is None:
        return [name[: -len(SUFFIX_CTRL)] for name in SPINE_FOLLOW_BONES]
    slots = [getattr(item, f"spine_bone_{i}", "") for i in range(1, 5)]
    names = [(n or "").strip() for n in slots[: max(0, item.spine_count - 1)]]
    return [n for n in names if n]


def resolve_master_source_org_name(armature):
    """ORG usado como referência de posição do root.master_CTRL/
    root.spine_CTRL (papel do "Belly" no Player): o Spine 1 da entrada
    SPINE; se a SPINE só tiver Pelvis, o próprio Pelvis. Sem entrada
    SPINE: o nome legado ROOT_MASTER_SOURCE ("Belly")."""
    item = resolve_spine_item(armature)
    if item is None:
        return ROOT_MASTER_SOURCE
    segments = resolve_spine_segment_org_names(armature)
    if segments:
        return segments[0]
    return resolve_pelvis_org_name(armature)


def parent_override_candidates(armature, override_name):
    """Nomes candidatos (ordem de preferência) pra um "Root Parent"
    (parent_override) do Bone Settings -- quem chama usa o primeiro que
    existir. Regras:
      1. o Pelvis (o marcado na SPINE, ou o nome "Pelvis") vira
         root.pelvis_CTRL -- o bone utilitário só existe depois do
         Create Rig, então o usuário marca o ORG e isso resolve pra ele;
      2. PARENT_OVERRIDE_ALIASES (atalhos fixos que já existiam);
      3. o `_CTRL` do bone marcado -- qualquer bone, não só "L-Shoulder":
         parentar um controle no ORG cru prende ele no lugar errado
         (o ORG é dirigido pelo MCH; o anim_importer também só reprojeta
         parent terminado em _CTRL/_MCH);
      4. o nome literal, como último recurso.
    Sufixo "_CTRL" digitado no campo é ignorado ("L-Shoulder" e
    "L-Shoulder_CTRL" caem no mesmo lugar)."""
    name = (override_name or "").strip()
    if not name:
        return []
    if name.endswith(SUFFIX_CTRL):
        name = name[: -len(SUFFIX_CTRL)]
    candidates = []
    if armature is not None and name == resolve_pelvis_org_name(armature):
        candidates.append(BONE_ROOT_PELVIS)
    alias = PARENT_OVERRIDE_ALIASES.get(name)
    if alias:
        candidates.append(alias)
    # control_name: um ORG com apelido (Rename "Only CTRL") tem o _CTRL
    # com o nome do apelido.
    candidates.extend((control_name(armature, name, SUFFIX_CTRL), name + SUFFIX_CTRL, name))
    return list(dict.fromkeys(candidates))


def _resolve_parent_override(bones, override_name, armature=None):
    """Bone final de um "Root Parent" (ver parent_override_candidates),
    ou None. `bones` pode ser edit_bones ou armature.bones. `armature`
    omitido = tenta bones.id_data (a coleção sabe de qual Armature é)."""
    if armature is None:
        armature = getattr(bones, "id_data", None)
    for candidate in parent_override_candidates(armature, override_name):
        bone = bones.get(candidate)
        if bone is not None:
            return bone
    return None


def parent_would_loop(bone, parent):
    """True se `bone.parent = parent` criaria um ciclo na hierarquia
    (parent é o próprio bone ou um descendente dele). Compara com `==`
    (não `is`) -- o bpy devolve um wrapper Python novo a cada acesso, a
    igualdade é que compara o bone de verdade."""
    ancestor = parent
    while ancestor is not None:
        if ancestor == bone:
            return True
        ancestor = ancestor.parent
    return False


def _classify_chain_limb(item):
    """'ARM'/'LEG'/None a partir de item.chain_type."""
    return item.chain_type if item.chain_type in ("ARM", "LEG") else None


_LIMB_SIDE_TO_COLLECTION = {
    ("ARM", "LEFT"): COLL_MAIN_ARM_L,
    ("ARM", "RIGHT"): COLL_MAIN_ARM_R,
    ("LEG", "LEFT"): COLL_MAIN_LEG_L,
    ("LEG", "RIGHT"): COLL_MAIN_LEG_R,
}


def _resolve_main_limb_roots(armature, edit_bones):
    """Raízes de Arm L/R e Leg L/R pra este Armature: parte dos nomes
    fixos (ARM/LEG_COLLECTION_ROOTS), troca pra variante sem ombro se o
    personagem não tiver esse bone, e acrescenta a raiz real de
    qualquer cadeia ARM/LEG customizada em hytale_ik_chains."""
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
        for candidate in (
            control_name(armature, item.root_bone, SUFFIX_CTRL),
            control_name(armature, item.root_bone, SUFFIX_IK),
        ):
            if candidate not in roots[coll_name]:
                roots[coll_name].append(candidate)
    return roots


# --- Edit Mode: collections e edit bones ---


def _find_bone_collection_anywhere(armature, name):
    """Procura uma bone collection em qualquer nível de aninhamento --
    armature.collections só enxerga o nível raiz."""
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
    """Deixa visível só as collections cujo nome está em visible_names."""
    for coll in _iter_all_collections(armature):
        coll.is_visible = coll.name in visible_names


def ensure_bone_collection(armature, name, parent=None):
    existing = _find_bone_collection_anywhere(armature, name)
    if existing is not None:
        return existing
    return armature.collections.new(name=name, parent=parent)


def _redraw_all_areas(context):
    """Força redraw de toda área/janela -- operadores chamados a partir
    de um popup menu (ex. RIG_MT_hytale_ik_chain_add_menu) não fazem a
    UIList redesenhar sozinha, limitação conhecida do Blender."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def create_bone_like(edit_bones, source, new_name):
    """Cria (ou reaproveita) um edit bone com a mesma transform de
    source. Retorna (bone, foi_criado_agora)."""
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
    """Rotaciona um edit bone em torno de um dos próprios eixos locais.
    Usado pelo ajuste manual da ponta de uma cadeia Tail, que não tem
    próximo segmento pra apontar sozinha."""
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
    edit_bone.align_roll(rot @ old_z)


def find_layer_bone(edit_bones, org_name, suffix):
    if org_name is None:
        return None
    return edit_bones.get(control_name(getattr(edit_bones, "id_data", None), org_name, suffix))


def is_attachment_bone(bone):
    return ATTACHMENT_NAME_HINT in bone.name.lower()


# Tokens de lado reconhecidos no NOME de um bone (comparação em
# minúsculo). Fonte ÚNICA -- usada tanto pelo Auto-Detect do Bone
# Settings (bone_settings.py) quanto pelo fallback de cor por nome
# (_build_bone_colors), pra os dois nunca discordarem sobre o lado de
# um bone (antes a cor só entendia prefixo "L-"/"L_", o Auto-Detect
# entendia também "_left", ".L" etc. -- um braço "arm_left" era
# detectado, mas ficava sem cor).
SIDE_PREFIX_TOKENS = (
    ("l-", "LEFT"), ("r-", "RIGHT"),
    ("left_", "LEFT"), ("right_", "RIGHT"),
    ("left-", "LEFT"), ("right-", "RIGHT"),
    ("l_", "LEFT"), ("r_", "RIGHT"),
)
SIDE_SUFFIX_TOKENS = (
    ("_left", "LEFT"), ("_right", "RIGHT"),
    (".l", "LEFT"), (".r", "RIGHT"),
    ("_l", "LEFT"), ("_r", "RIGHT"),
)


def split_side_token(bone_name):
    """(side, base) -- side = "LEFT"/"RIGHT"/None; base = o nome sem o
    token de lado, em minúsculo (só pra comparar). Ex.: "L-Forearm" ->
    ("LEFT", "forearm"); "arm_left2" -> (None, "arm_left2") (o token
    precisa estar na ponta do nome)."""
    lower = bone_name.lower()
    for token, side in SIDE_PREFIX_TOKENS:
        if lower.startswith(token):
            return side, lower[len(token):]
    for token, side in SIDE_SUFFIX_TOKENS:
        if lower.endswith(token):
            return side, lower[: -len(token)]
    return None, lower


# Sufixos que o rigger acrescenta ao nome do ORG pra criar cada camada.
# Ordem do MAIS LONGO pro mais curto -- "_Pole_CTRL" tem que ser testado
# antes de "_CTRL", "_MCH_IK_Transfer" antes de "_MCH" etc.
_GENERATED_LAYER_SUFFIXES = tuple(
    sorted(
        (SUFFIX_MCH_IK_TRANSFER, SUFFIX_MCH_TRANSFER, SUFFIX_POLE_LINE, SUFFIX_POLE, SUFFIX_CTRL, SUFFIX_IK, SUFFIX_MCH),
        key=len,
        reverse=True,
    )
)


def source_org_name(generated_name):
    """Nome do ORG de onde um bone gerado nasceu (tira o sufixo de
    camada: "_CTRL", "_IK", "_MCH", "_MCH_Transfer", "_MCH_IK_Transfer",
    "_Pole_CTRL", "_Pole_Line"). None se o nome não termina com nenhum
    deles (ex. root.master_CTRL termina com "_CTRL" e devolve
    "root.master" -- quem chama decide se esse ORG existe/importa)."""
    for suffix in _GENERATED_LAYER_SUFFIXES:
        if generated_name.endswith(suffix) and len(generated_name) > len(suffix):
            return generated_name[: -len(suffix)]
    return None


_TRAILING_NUMBER_RE = re.compile(r"[._-]?\d+$")


# --- Nome dos bones de controle (apelido do Rename "Only CTRL") --------

# Camadas que usam o apelido do ORG. ORG/_MCH/pontes usam sempre o nome
# do ORG.
CONTROL_LAYER_SUFFIXES = (SUFFIX_CTRL, SUFFIX_IK, SUFFIX_POLE, SUFFIX_POLE_LINE)


def control_base(armature, org_name):
    """Nome-base dos bones de controle de um ORG: o apelido gravado nele
    (PROP_CONTROL_NAME, Rename "Only CTRL") ou o próprio nome do ORG.
    `armature` é o bpy.types.Armature (armature.bones funciona em qualquer
    modo); None = sem apelido."""
    if not org_name or armature is None:
        return org_name
    bones = getattr(armature, "bones", None)
    bone = bones.get(org_name) if bones is not None else None
    alias = bone.get(PROP_CONTROL_NAME) if bone is not None else None
    return alias or org_name


def control_name(armature, org_name, suffix):
    """Nome do bone gerado de `org_name` na camada `suffix`. Camadas de
    controle (_CTRL/_IK/_Pole_CTRL/_Pole_Line) usam o apelido do ORG, se
    houver; as outras (_MCH, pontes) usam sempre o nome do ORG. É o ÚNICO
    jeito certo de montar esse nome -- não concatene org + sufixo direto."""
    if suffix in CONTROL_LAYER_SUFFIXES:
        return control_base(armature, org_name) + suffix
    return org_name + suffix


def source_org_of(bone):
    """ORG de onde um bone gerado nasceu: a marca PROP_SOURCE_ORG (gravada
    pelo Create Rig), ou -- rig gerado antes da marca existir, ou bone
    utilitário tipo root.pelvis_CTRL -- o nome sem o sufixo de camada.
    `bone` pode ser Bone, EditBone ou PoseBone."""
    data = getattr(bone, "bone", bone)  # PoseBone -> Bone
    source = data.get(PROP_SOURCE_ORG) if data is not None else None
    if source:
        return source
    return source_org_name(bone.name)


def _org_by_alias(bones, base):
    """ORG cujo apelido (PROP_CONTROL_NAME) é `base`, se for um só."""
    matches = [b.name for b in bones if b.get(PROP_RIG_LAYER) is None and b.get(PROP_CONTROL_NAME) == base]
    return matches[0] if len(matches) == 1 else None


def normalize_org_name(bones, name):
    """Nome de bone ORIGINAL pra um campo do Bone Settings. Se `name` é
    um bone GERADO pelo rigger (tem hytale_rig_layer -- ex. o
    "leg_front_right3_CTRL" que o conta-gotas pega no Pose Mode, onde os
    ORG ficam escondidos), devolve o ORG de onde ele nasceu, se existir.
    Senão devolve `name` como veio (sem espaços nas pontas)."""
    name = (name or "").strip()
    bone = bones.get(name) if name else None
    if bone is None or bone.get(PROP_RIG_LAYER) is None:
        if bone is None and name:
            # Bone gerado que já não existe (ex. o rig foi apagado): pelo
            # sufixo, e se o resto for um apelido, pelo ORG dono dele.
            source = source_org_name(name)
            source_bone = bones.get(source) if source else None
            if source_bone is not None and source_bone.get(PROP_RIG_LAYER) is None:
                return source
            if source:
                owner = _org_by_alias(bones, source)
                if owner:
                    return owner
            # Nome sem sufixo que é o APELIDO de um ORG ("R-Arm" digitado
            # num campo, com o ORG ainda chamado "leg_front_right").
            owner = _org_by_alias(bones, name)
            if owner:
                return owner
        return name
    source = source_org_of(bone)
    source_bone = bones.get(source) if source else None
    if source_bone is not None and source_bone.get(PROP_RIG_LAYER) is None:
        return source
    return name


def bone_side_prefix(name):
    """Lado ("L"/"R"/None) pelo NOME do bone -- só fallback cosmético
    (cor), pra bone que não está em nenhuma entrada do Bone Settings.
    Aceita prefixo ou sufixo (ver SIDE_PREFIX_TOKENS/SIDE_SUFFIX_TOKENS)
    e ignora o sufixo de camada do rigger antes de olhar o fim do nome
    ("arm_left_CTRL" -> "arm_left" -> "L")."""
    base = source_org_name(name) or name
    side, _ = split_side_token(base)
    if side is None:
        # Número no fim esconde o token de lado: "arm_left2",
        # "arm_left_3", "Hand.L.001" (duplicata do Blender). Só aqui, no
        # fallback de cor -- o Auto-Detect continua exigindo o token na
        # ponta do nome.
        trimmed = _TRAILING_NUMBER_RE.sub("", base)
        if trimmed and trimmed != base:
            side, _ = split_side_token(trimmed)
    if side == "LEFT":
        return "L"
    if side == "RIGHT":
        return "R"
    return None


def is_excluded_from_main_collections(bone):
    """Bones que não entram nas collections Head/Spine/Body/Arm/Leg/Root
    dentro de Main: attachments e as camadas internas MCH/MCH-IK/
    MCH-TRANSFER."""
    if is_attachment_bone(bone):
        return True
    return bone.get(PROP_RIG_LAYER) in ("MCH", "MCH-IK", "MCH-TRANSFER")


def find_attachment_child(org_bone):
    """Primeiro filho ORG cujo nome contém ATTACHMENT_NAME_HINT, ou None."""
    for child in org_bone.children:
        if is_attachment_bone(child):
            return child
    return None


def find_non_attachment_children(org_bone):
    """Irmã de find_attachment_child: todos os filhos ORG que NÃO são attachment."""
    return [child for child in org_bone.children if not is_attachment_bone(child)]


def find_org_path(root_bone, tip_name):
    """Caminho (root->tip) descendo pela hierarquia ORG, ignorando bones
    já gerados. None se tip_name não for descendente de root_bone."""
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
    """[root] + todos os descendentes, pulando bones pros quais
    exclude_predicate(bone) seja True."""
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
