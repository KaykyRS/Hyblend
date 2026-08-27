"""
rigger/constants.py -- todas as constantes de nomenclatura/convenção do
Auto-Rigger: nomes de bone collection, sufixos de camada (_MCH/_CTRL/
_IK/...), nomes de constraint, custom properties, overrides pontuais
(parent/widget/cor de bone) e a biblioteca de custom shapes (nomes
WGT_hytale_*). Zero lógica aqui -- só literais e pequenos dicts fixos,
lidos por rigger/rig.py e reexportados (os poucos usados fora do
pacote) por rigger/__init__.py.

Parte do split de rigger.py num pacote (Tarefa A) -- ver
DEVELOPER_NOTES.md. Corresponde ao antigo topo do arquivo (as seções de
constantes, antes de qualquer função/classe).
"""

# ---------------------------------------------------------------------------
# Contrato INTERNO deste módulo (não é common.py -- ver rationale no
# rigger.py anterior / DEVELOPER_NOTES.md).
# ---------------------------------------------------------------------------

COLL_HYTALE_EXPORT = "Hytale Export"
COLL_INTERNAL = "Internal"
COLL_ORG = "ORG"
COLL_MCH = "MCH"
# v0.7: renomeada de "MCH-IK" pra "Specials" -- deixou de guardar só os
# bridges _MCH_IK_Transfer da cadeia de IK, também guarda os bridges
# genéricos _MCH_Transfer (ver SUFFIX_MCH_TRANSFER em cima, e
# _build_edit_bones/_build_tail_layer) -- os dois são o mesmo tipo de
# coisa (bone "de mecanismo", só existe pra dar uma rest orientation
# "limpa" pra outro bone copiar, nunca selecionado/posado por quem
# anima), então dividem a MESMA bone collection interna/oculta em vez de
# cada tipo ganhar uma própria. O valor da custom property
# PROP_RIG_LAYER continua "MCH-IK" pros bridges de IK (não mexi nisso --
# é dado interno, independente do nome de exibição da collection, e
# independente do rename do sufixo em si) e agora "MCH-TRANSFER" pro
# bridge genérico (v0.13 -- substituiu "TAIL", que só existia pro extinto
# bridge dedicado da cadeia Tail; ver is_excluded_from_main_collections).
COLL_MCH_IK = "Specials"
COLL_CTRL = "CTRL"
COLL_CTRL_IK = "CTRL-IK"

# Filha de Internal -- guarda os bones ORG de attachments (qualquer bone
# cujo nome contenha ATTACHMENT_NAME_HINT), separados do resto dos ORG do
# corpo. Só organização/localização visual: um attachment anexado depois
# (via "Attach to Selected" do importer) já entra automaticamente aqui a
# próxima vez que "Create Rig" rodar -- não precisa de nenhum rastreamento
# de "isso é novo" -- roda toda vez, igual o resto das collections deste
# arquivo (ver DEVELOPER_NOTES.md/histórico do chat sobre essa decisão).
COLL_ATTACHMENTS_IMPORTED = "Attachments Imported"

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
COLL_MAIN_CHAIN = "Chain"  # v0.7.14 -- ERA COLL_MAIN_TAIL = "Tail" -- renomeado (NOME do símbolo Python E
# valor) junto com o rótulo E o identificador interno do chain_type "TAIL" -> "CHAIN" na UI/dados (pedido
# explícito do usuário: essa cadeia serve pra qualquer coisa que precise de bones "conectados" em sequência
# -- orelha comprida, cauda, o que for -- não só cauda). SEM MIGRAÇÃO (mesma decisão já tomada outras vezes
# neste arquivo): uma collection "Tail" de antes desta versão fica órfã, o usuário reorganiza manualmente
# se quiser; uma entrada salva com chain_type == "TAIL" fica com o Type em branco no Bone Settings, o
# usuário reseleciona "Chain" manualmente.
COLL_MAIN_TEXTURE_PICKER = "Texture Picker"  # v0.10 -- chain_type MOUTH, renomeado TEXTURE_PICKER na v0.11 (Texture Picker), mesmo espírito organizacional de COLL_MAIN_HEAD/SPINE

# Todo nome de bone collection que o PRÓPRIO "Create Rig" já cria/
# gerencia sozinho -- usado por RIG_OT_hytale_collection_template_save
# pra decidir o que É customização do usuário (entra no template) vs o
# que já é reproduzido automaticamente por outro caminho (entraria
# duplicado/redundante no .json, e o "Apply Collection Template" já não
# saberia o que fazer com um "Arm L" que também é gerenciado por
# _build_main_collections).
RESERVED_MAIN_COLLECTION_NAMES = {
    COLL_HYTALE_EXPORT, COLL_INTERNAL, COLL_ORG, COLL_MCH, COLL_MCH_IK, COLL_CTRL, COLL_CTRL_IK,
    COLL_ATTACHMENTS_IMPORTED, COLL_FACE, COLL_MAIN, COLL_ATTACHMENTS, COLL_MAIN_HEAD, COLL_MAIN_SPINE,
    COLL_MAIN_BODY, COLL_MAIN_ARM_L, COLL_MAIN_ARM_R, COLL_MAIN_LEG_L, COLL_MAIN_LEG_R, COLL_MAIN_ROOT,
    COLL_MAIN_CHAIN, COLL_MAIN_TEXTURE_PICKER,
}

# v0.9 (Tarefa B, split de rigger.py): SUFFIX_MCH/SUFFIX_CTRL/SUFFIX_IK
# deixaram de ser definidos aqui -- agora vêm de common.py, que também
# passou a ser a fonte da verdade pro exporter.py (antes cada lado tinha
# a própria cópia -- rigger.py com estes literais, exporter.py com
# CONTROL_SUFFIXES -- e só concordavam "por acaso"; ver DEVELOPER_NOTES.md,
# "Duplicação solta pra ficar de olho"). SUFFIX_MCH_IK_TRANSFER e
# SUFFIX_POLE CONTINUAM só aqui -- não são usados por mais ninguém fora
# do rigger (bom, quase -- ver nota abaixo), não precisam ir pra
# common.py (regra prática: common.py só compartilha o que realmente
# precisa ser idêntico dos dois lados).
from ..common import SUFFIX_CTRL, SUFFIX_IK, SUFFIX_MCH

# v0.13 (Bridge genérico -- "MCH_Transfer"): RENOMEADO de SUFFIX_IK_MCH
# ("_IK_MCH") pra bater com a convenção nova do bridge genérico logo
# abaixo (SUFFIX_MCH_TRANSFER) -- mesma coisa de sempre, só nome novo:
# bone-ponte por segmento da cadeia de IK, parent REAL (não constraint)
# no `_IK` do mesmo segmento, rest = a do MCH/ORG original, intocada --
# ver _build_ik_layer. RENOMEADO SEM MIGRAÇÃO (decisão consciente do
# usuário, mesmo espírito de MOUTH -> TEXTURE_PICKER, ver
# DEVELOPER_NOTES.md): rigs já gerados ficam com bones órfãos
# "_IK_MCH" até "Remove Generated Bones"/regenerar -- não tem mais
# nenhum código lendo esse nome antigo. IMPORTANTE: reexportado por
# rigger/__init__.py -- anim_tools.py (FK/IK Snap) importa este nome de
# lá; qualquer rename aqui precisa ser refletido nos dois.
SUFFIX_MCH_IK_TRANSFER = "_MCH_IK_Transfer"
SUFFIX_POLE = "_Pole_CTRL"

# v0.13 -- bridge GENÉRICO, mesmo princípio exato de SUFFIX_MCH_IK_TRANSFER
# acima, generalizado pra TODO bone `_CTRL` "normal" criado pelo loop
# genérico org -> _CTRL em _build_edit_bones (incluindo os que também
# fazem parte de uma cadeia IK ou Tail -- eles ganham ESTE bridge além
# do próprio, ver acima/abaixo). Também SUBSTITUI o extinto
# SUFFIX_TAIL/"_Tail" (mesma função, mesmo mecanismo -- ver
# _build_tail_layer, que agora reaproveita este bridge em vez de criar
# o próprio).
#
# Motivo de existir: o `_CTRL` é o bone que uma feature futura vai
# poder reposicionar livremente (Head no Tail do bone pai, por exemplo)
# -- mas FK_CopyRotation/_Scale/_Location (em MCH, World Space) precisam
# de uma rest "limpa" (a mesma do MCH/ORG original) pra não sair torto:
# constraint em World Space IGNORA a rest própria de quem ele copia, só
# copia a transform absoluta -- se a rest do alvo mudar, a rest NOVA
# vaza pro MCH como se fosse pose. Parentesco REAL (Blender) não tem
# esse problema -- a rest do FILHO (aqui, o bridge) sempre vale como
# baseline própria dele, e só a DELTA de pose do pai é herdada por cima
# -- por isso o bridge existe: rest = ORG original, intocada, filho
# real do `_CTRL` (que pode ter a rest que for). O MCH copia do
# bridge (não mais do `_CTRL` direto) -- ver _build_pose_constraints.
SUFFIX_MCH_TRANSFER = "_MCH_Transfer"

# v0.8: bone puramente visual (nunca posável -- hide_select=True),
# parentado DIRETO no bone de referência do pole (pole_ref, o mesmo
# usado por _pole_position pra calcular onde o pole target fica -- ver
# HytaleIKChainItem.pole_bone) -- não faz parte da árvore ORG/MCH/CTRL/
# IK "de verdade" (por isso _propagate_pole_and_tip_to_main_collections
# propaga ele manualmente pra Main/Arm-Leg, do mesmo jeito que pole/tip
# -- ver ali). Só existe pra dar feedback visual de pra onde o pole
# target está apontando (widget dedicado, WGT_hytale_pole_line -- ver
# WGT_POLE_LINE) -- o Stretch To (ver CONSTRAINT_POLE_LINE_STRETCH)
# faz o resto sozinho, sem nenhuma custom property nem driver.
SUFFIX_POLE_LINE = "_Pole_Line"

# v0.7 -- v0.13: SUFFIX_TAIL ("_Tail") existia aqui como o bridge
# DEDICADO de uma cadeia TAIL (mesmo princípio do bridge de IK, ver
# SUFFIX_MCH_TRANSFER acima). Na v0.13, retirado -- Tail passou a
# reaproveitar o bridge GENÉRICO (SUFFIX_MCH_TRANSFER), que já existe
# pra todo `_CTRL` de qualquer forma, em vez de criar um bridge próprio
# redundante. RETIRADO SEM MIGRAÇÃO (mesma decisão de SUFFIX_MCH_IK_TRANSFER,
# acima): rigs já gerados ficam com bones órfãos "_Tail" até "Remove
# Generated Bones"/regenerar. anim_importer.py também consumia este
# nome (via rigger/__init__.py) -- avisado separadamente, precisa trocar
# pra SUFFIX_MCH_TRANSFER (mesmo lugar, mesmo formato de correção, só o
# nome do sufixo muda -- ver _build_tail_layer pro novo funcionamento).

# Marca todo bone criado por este script (independente da camada). É isso
# -- não o nome -- que diferencia um bone ORG (original) de um gerado, e é
# a base da idempotência: rodar de novo só cria o que ainda não existe.
PROP_RIG_LAYER = "hytale_rig_layer"

# Custom property no bone _IK da ponta (mão/pé) de cada cadeia. Inteira,
# 0..1 -- 0 = FK, 1 = IK.
PROP_FK_IK_SWITCH = "fk_ik_switch"

# v0.13 -- "Head Follow" (ver CONSTRAINT_HEAD_FOLLOW_ROT/_LOC,
# _apply_head_follow_parent, _build_head_follow em rig.py). Switch ÚNICO
# (diferente de PROP_FK_IK_SWITCH -- não é "por cadeia/lado", só existe
# UM Head_CTRL no rig todo) -- mesmo bone PROPERTIES, mesmo mecanismo de
# driver (ver add_switch_driver). v0.13.1: 1 (default) = segue o Chest
# (expression "switch" direta no Child Of -- ver CONSTRAINT_HEAD_FOLLOW_ROT
# abaixo) -- um rig recém-gerado (ou regenerado) precisa continuar
# parecendo com o de antes por padrão (igual sempre foi via parentesco
# real, antes desta feature existir), sem exigir que o usuário ligue
# nada. 0 = rotação livre (Head_CTRL para de seguir a rotação/escala do
# Chest_CTRL -- a posição continua acompanhando, ver
# CONSTRAINT_HEAD_FOLLOW_LOC, que nunca tem toggle).
PROP_HEAD_FOLLOW_SWITCH = "head_follow_switch"

# Custom property no OBJECT do widget por-bone (ver _ensure_bone_widget_copy
# em rig.py), gravada só quando a cópia é duplicada de um TEMPLATE de papel
# de verdade (ex.: "WGT_hytale_fk_ring") -- guarda o base_name de origem,
# pra RIG_OT_hytale_shape_template_save saber contra qual template comparar
# na hora de decidir se embute a malha editada no .json (ver "mesh" no
# schema de shapes/<nome>.json, em templates/__init__.py -- feature de
# embutir malha nos Shape Templates). Ausente = sem proveniência conhecida
# -- objeto atribuído por fora do pipeline normal (ex.: "Use Selected
# Object as Widget") ou vindo de um .blend salvo antes desta property
# existir -- nesses casos o save SEMPRE embute a malha (não tem contra o
# que comparar, mesmo espírito "sem migração" do resto do addon).
PROP_WIDGET_SOURCE_ROLE = "hytale_widget_source_role"

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
# v0.13 -- "Head Follow" (ver PROP_HEAD_FOLLOW_SWITCH acima). Dois
# constraints em Head_CTRL, papéis bem separados -- ver _build_head_follow.
# ORDEM no stack importa (v0.13.1, pedido explícito): _ROT (Child Of)
# precisa vir ANTES de _LOC (Copy Location) -- _build_head_follow cria
# nessa ordem E reordena explicitamente toda vez (idempotente, corrige
# também um rig já gerado com a ordem antiga).
#   _ROT (Child Of, só canais de Rotation/Scale -- Location DESLIGADO de
#       propósito, senão brigaria com o _LOC abaixo) -- influência ligada
#       ao PROP_HEAD_FOLLOW_SWITCH via driver, expression "switch" DIRETA
#       (v0.13.1 -- ANTES era "1 - switch", invertida): switch=1
#       (default) -> influência 1 -> segue. Cuida só da ROTAÇÃO/ESCALA --
#       é essa que o switch liga/desliga.
#   _LOC (Copy Location, World Space, head_tail=1.0 no target -- mira a
#       PONTA/Tail do Chest_CTRL, não o Head) -- SEMPRE ativo, sem
#       driver/switch nenhum. Cuida só da POSIÇÃO (o "arco" de seguir o
#       tronco quando ele se move/rotaciona) -- independente do switch,
#       sempre liga.
CONSTRAINT_HEAD_FOLLOW_ROT = "Hytale_HeadFollow_Rot"
CONSTRAINT_HEAD_FOLLOW_LOC = "Hytale_HeadFollow_Loc"
# v0.8: Stretch To do bone "_Pole_Line" (ver SUFFIX_POLE_LINE), mirando
# sempre no "_Pole_CTRL" do mesmo lado/cadeia -- ver ensure_stretch_to_constraint.
CONSTRAINT_POLE_LINE_STRETCH = "PoleLine_StretchTo"
# Tail (v0.7) NÃO cria constraints com nome próprio -- reaproveita/
# retargeta FK_CopyRotation/FK_CopyScale/FK_CopyLocation (as constantes
# acima) que o loop genérico de _build_pose_constraints já cria no MCH,
# só trocando o subtarget pro bridge _Tail (ver _build_tail_pose_constraints).

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
    # v0.13.4 -- "Head_CTRL": "Origin_CTRL" (Head Follow) SAIU daqui --
    # esse override virou CONDICIONAL, não incondicional como o resto
    # deste dict (ver _apply_head_follow_parent em rig.py, e
    # HytaleIKChainItem.head_follow_enabled/"Head Free/Lock"): só
    # reparenta Head_CTRL se o toggle "Head Free/Lock" estiver ligado
    # -- senão Head_CTRL fica com o parent NATURAL (Neck ou Chest, o
    # que o loop genérico já teria escolhido sozinho).
}

# Bones utilitários de controle geral (não derivam de nenhum ORG por
# sufixo -- são posicionados a partir de bones de referência já
# existentes, mas têm nome próprio).
BONE_ROOT_MASTER = "root.master_CTRL"
BONE_ROOT_SPINE = "root.spine_CTRL"
BONE_ROOT_PELVIS = "root.pelvis_CTRL"
ROOT_MASTER_SOURCE = "Belly"        # bone ORG usado como referência de posição do master/spine
ORIGIN_ORG_NAME = "Origin"          # bone ORG esperado no modelo importado -- ver _ensure_origin_bone (v0.8)
ROOT_MASTER_PARENT = ORIGIN_ORG_NAME + SUFFIX_CTRL  # "Origin_CTRL" -- parent do master, gerado do ORG acima
ROOT_SPINE_LENGTH = 0.5             # comprimento (head->tail) do root.spine_CTRL
ORIGIN_FALLBACK_LENGTH = 0.3        # comprimento do ORG "Origin" quando precisa ser criado -- ver _ensure_origin_bone

# v0.10 -- Texture Picker (chain_type TEXTURE_PICKER, era MOUTH até v0.10).
# BONE_UI_ROOT_PREFIX é o prefixo do pai de qualquer bone "de interface"
# (não deforma malha nenhuma, não existe no jogo, só existe pra dar ao
# usuário um jeito visual de escolher algo) -- hoje só o cursor do
# Texture Picker usa, mas o prefixo já é genérico o bastante pra outro
# picker parecido no futuro (ex.: um atlas de sobrancelha) reusar a
# mesma convenção sem precisar de outro esquema de nome "root.*"
# dedicado.
#
# v0.12 -- ERAM strings FIXAS (BONE_UI_ROOT = "root.ui", BONE_
# TEXTURE_PICKER_CURSOR = "ui.texture_picker") -- funcionava pra UMA
# instância de Texture Picker só; uma segunda entrada reaproveitava o
# MESMO bone físico em vez de criar o seu próprio (bug real, ver
# DEVELOPER_NOTES.md/prompt_uv_animate.md ponto 2). Agora só os
# PREFIXO/SUFIXO ficam fixos aqui -- o nome de verdade é montado por
# instância em rig.py (_texture_picker_ui_root_name/_texture_picker_
# cursor_name), usando o nome do texture_picker_bone (o bone alvo, que
# já É único por definição -- é um bone real da armature) como parte do
# nome. Parentado direto no `<texture_picker_bone>_CTRL` (não deriva de
# nenhum ORG por sufixo, mesmo espírito de BONE_ROOT_MASTER acima) --
# ver _build_texture_picker.
BONE_UI_ROOT_PREFIX = "root.ui."
# Cursor que o usuário arrasta sobre o Texture Picker Plane -- a Location
# dele (local, dentro do root.ui desta instância) dirige o driver do
# Mapping node do target E é reamostrada pelo exporter.py pra escrever
# 'shapeUvOffset' (ver UV_OFFSET_SOURCE_BONE_DEFAULT em exporter.py --
# esse default só cobre o caso sem nenhuma instância ainda configurada;
# cada instância de verdade grava o PRÓPRIO nome derivado em
# HYTALE_texture_picker_export_item.uv_offset_source_bone).
BONE_TEXTURE_PICKER_CURSOR_PREFIX = "ui."
BONE_TEXTURE_PICKER_CURSOR_SUFFIX = ".picker"
# Offset (Blender units, ao longo do eixo LOCAL X do texture_picker_ctrl) que
# root.ui recebe na hora de ser criado, pra não nascer bem em cima do
# target -- mesma escala de "0.5" já usada em outro bone utilitário deste
# arquivo (ver ROOT_SPINE_LENGTH), testado/confirmado no Blender.
TEXTURE_PICKER_UI_OFFSET_X = 0.5
# v0.10.2 -- testado no Blender: root.ui também precisa subir/afastar
# no eixo local Y do bone (comprimento do texture_picker_ctrl), além do X --
# um offset só não bastava.
TEXTURE_PICKER_UI_OFFSET_Y = 0.2
# Sufixo do objeto de malha (plane de referência) e do material dedicado
# criados por _build_texture_picker -- nunca aparecem sozinhos, sempre
# prefixados pelo nome do texture_picker_bone (ex.: "Mouth_Atlas_Plane" pra
# um bone chamado "Mouth").
TEXTURE_PICKER_PLANE_SUFFIX = "_Atlas_Plane"
TEXTURE_PICKER_MATERIAL_SUFFIX = "_Atlas_Reference_MAT"
# v0.10.16 -- sufixo da CÓPIA que _ensure_texture_picker_material_uv_offset faz
# do material real do target, quando ele está compartilhado (material.
# users > 1) -- sem isso, Blender nomeia a cópia sozinho com o sufixo
# genérico ".001", difícil de identificar depois só olhando a lista de
# materiais. Prefixado pelo nome do material ORIGINAL (ex.:
# "dark_bunny.mouth_TexturePickerCopy"). PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL é a
# custom property (no material da CÓPIA) que guarda o nome do material
# ORIGINAL de onde ela veio -- é assim que "Remove Texture Picker" sabe
# pra qual material voltar e que a cópia pode ser apagada (ver
# _revert_texture_picker_material_uv_offset em rig.py).
TEXTURE_PICKER_MATERIAL_COPY_SUFFIX = "_TexturePickerCopy"
PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL = "hytale_texture_picker_original_material"
# Nomes fixos dos nodes injetados no material REAL do target (não no plane
# de referência, que usa um material próprio simples/sem Mapping) --
# procurados por nome (nodes.get(...)) pra idempotência, mesmo espírito
# de CONSTRAINT_FK_ROT etc. acima.
TEXTURE_PICKER_MAPPING_NODE_NAME = "Hytale_Texture_Picker_Mapping"
TEXTURE_PICKER_UVMAP_NODE_NAME = "Hytale_Texture_Picker_UV_Map"
# Limit Location do bone cursor (nome derivado por instância -- ver
# _texture_picker_cursor_name em rig.py) -- trava o arrasto dentro da área
# do grid informado (0..num_cols-1 células em X, 0..num_rows-1 em Y).
CONSTRAINT_TEXTURE_PICKER_LIMIT = "Hytale_Texture_Picker_Limit"

# v0.15 -- "Create First Person Camera", exclusivo de HEAD (ver
# HytaleIKChainItem.head_camera_enabled/rig.py, _build_first_person_camera).
# Sufixo do Object Camera criado -- prefixado pelo NOME DO ARMATURE (não
# por um bone, diferente de TEXTURE_PICKER_PLANE_SUFFIX), porque só existe
# UMA câmera de primeira pessoa esperada por personagem/armature (não é
# multi-instância como Texture Picker) -- garante nome único mesmo com
# vários personagens na mesma cena.
FIRST_PERSON_CAMERA_SUFFIX = "_FirstPerson_CAM"

# Bone utilitário que guarda TODAS as custom properties de FK/IK switch
# (uma por cadeia -- ver _switch_property_name) -- fica acima da cabeça,
# parentado no Head_CTRL, mesmo tamanho/eixo dele. Não deriva de nenhum
# ORG por sufixo, mesmo espírito de BONE_ROOT_MASTER etc.
BONE_PROPERTIES = "PROPERTIES"
PROPERTIES_BONE_OFFSET_Y = 0.7  # metros acima do Head_CTRL (mesmo espaço/eixo Y do armature)

# Belly_CTRL/Chest_CTRL seguem parcialmente o root.spine_CTRL via um
# constraint de Copy Transforms (Local Space), com influência fixa.
SPINE_FOLLOW_TARGET = BONE_ROOT_SPINE
SPINE_FOLLOW_BONES = {
    "Belly_CTRL": 0.5,
    "Chest_CTRL": 0.63,
}

# v0.13.4 -- "Head Follow" (ver CTRL_PARENT_OVERRIDES/PROP_HEAD_FOLLOW_SWITCH/
# CONSTRAINT_HEAD_FOLLOW_LOC/_ROT acima, _apply_head_follow_parent/
# _build_head_follow em rig.py). O bone-alvo (source) NÃO É uma string
# fixa (era "Chest_CTRL" até v0.13.1) -- personagens com Neck entre
# Chest e Head (o caso comum) tinham Head_CTRL "grudado" errado, mirando
# o Tail do Chest em vez do último Neck. Resolvido dinamicamente,
# lendo o pai REAL do ORG "Head" na hierarquia original do modelo (só
# personagens SEM nenhum Neck resolvem pro Chest mesmo).
#
# v0.13.4: a feature INTEIRA (reparent + os dois constraints) é
# controlada por UM ÚNICO toggle explícito -- "Head Free/Lock"
# (HytaleIKChainItem.head_follow_enabled, exclusivo de HEAD). v0.13.3
# tentou resolver isso SEM toggle nenhum (media se a geometria já
# estava alinhada, dependendo do usuário ter configurado "Continuous
# Chain" na cadeia certa) -- funcionava, mas ficava confuso saber QUAL
# combinação (HEAD com Neck encadeado, OU SPINE cruzando pra HEAD sem
# Neck) fazia o alinhamento acontecer. Como só precisamos de UM
# redirect (o Tail do predecessor IMEDIATO de "Head", não a cadeia
# inteira), "Head Free/Lock" faz esse redirect sozinho -- sem depender
# de mais nada configurado em outra entrada.

# head_tail do Copy Location (CONSTRAINT_HEAD_FOLLOW_LOC) -- 1.0 = mira
# o TAIL do bone resolvido (a "ponta de cima" dele, onde o Head começa
# de verdade), não o Head dele (0.0). Ver
# bpy.types.CopyLocationConstraint.head_tail na documentação do Blender.
HEAD_FOLLOW_LOC_HEAD_TAIL = 1.0

# Alvo do "Child Of_global" em todo pole target -- o mesmo bone usado como
# parent do root.master_CTRL.
CHILD_OF_GLOBAL_TARGET = ROOT_MASTER_PARENT

# Valores calibrados de pole_angle por preset (ex.: "ARM") e por lado
# (item.side) -- ANTES vinham de um dict fixo (ARM_POLE_ANGLE_PRESET),
# exclusivo do personagem "Player". Agora vêm de
# rig_template["pole_angle_presets"] (ver templates/__init__.py e
# templates/rig/player.json) -- cada template de personagem define os
# próprios presets; pole_angle_mode="PRESET" numa cadeia (ver
# HytaleIKChainItem) lê o preset indicado em item.pole_angle_preset_name
# dentro do template ATIVO no momento (armature.hytale_active_rig_template
# -- setado por RIG_OT_hytale_ik_chain_load_defaults). Ver
# _resolve_pole_angle_presets, chamado por _build_pose_constraints.

# Quando o nome digitado/selecionado em "Root Parent" (parent_override)
# não existe como bone, tenta resolver por este dicionário antes de
# desistir -- útil pra bones utilitários (root.pelvis_CTRL etc.) que só
# passam a existir DEPOIS de gerar o rig, então não dá pra selecioná-los
# via eyedropper no momento de configurar a cadeia. O usuário seleciona o
# bone ORG que já existe (ex.: "Pelvis") e isso resolve pro bone final.
PARENT_OVERRIDE_ALIASES = {
    "Pelvis": BONE_ROOT_PELVIS,
    # v0.6: sem isso, digitar "L-Shoulder" (nome ORG literal, sem sufixo
    # -- o padrão natural de se escrever aqui, igual "Pelvis") resolvia
    # pro bone ORG cru em vez do "L-Shoulder_CTRL" gerado -- a cadeia de
    # braço ficava parentada no lugar errado e nunca aparecia em
    # Main/Arm L/R (só em CTRL-IK), porque ARM_COLLECTION_ROOTS caminha
    # a partir de "L-Shoulder_CTRL" esperando achar o braço como
    # descendente dele.
    "L-Shoulder": "L-Shoulder" + SUFFIX_CTRL,
    "R-Shoulder": "R-Shoulder" + SUFFIX_CTRL,
}

# ---------------------------------------------------------------------------
# Custom shapes (widgets) -- biblioteca externa hytale_widgets.blend, no
# mesmo espírito do Auto-Rig Pro (cs.blend): formas fixas, pré-modeladas
# fora do addon, carregadas via append (cópia, não link) e reaproveitadas
# entre execuções -- nunca geradas ao vivo via bmesh dentro do rigger.py.
#
# WGT_DEFAULT_FALLBACK existe pra fase de transição: enquanto a biblioteca
# ainda não tem um shape específico modelado pra cada papel (FK/IK/pole/
# root/head), qualquer bone cujo shape "preferido" não seja encontrado usa
# esse fallback no lugar do octaedro padrão do Blender -- desde que
# WGT_DEFAULT_FALLBACK exista na biblioteca. Assim que você modelar um
# shape específico com o nome certo (ex.: WGT_hytale_fk_ring), ele passa a
# ser usado automaticamente pros bones daquele papel, sem precisar mudar
# nada aqui -- o fallback só entra pros papéis que ainda não têm shape
# próprio.
#
# O arquivo em si (binário, não dá pra escrever aqui) é gerado/editado por
# você diretamente no Blender -- ver build_hytale_widgets.py (fora do
# pacote do addon) pra um ponto de partida com formas básicas.
#
# v0.16 -- os objetos widget são CÓPIAS POR-PERSONAGEM (ver
# _widget_instance_name/ensure_widget_objects/get_or_create_widgets_collection
# em rig.py), linkadas na collection 'WGT - <nome>' dentro de
# 'Rig - <nome>'. ANTES desta versão era um único objeto GLOBAL
# compartilhado entre todo Armature do .blend, sem link em collection
# nenhuma (mesma técnica do Rigify, "órfão" de propósito) -- isso
# impedia editar o shape por vértice (Vertex Edit Mode) sem afetar
# outros personagens. A collection 'WGT - <nome>' fica EXCLUÍDA da View
# Layer por padrão (mesmo efeito prático de antes: pose_bone.custom_shape
# já conta como usuário do datablock, não some ao salvar, mas também não
# aparece solto no viewport/Outliner à toa) -- só é reincluída
# temporariamente durante Vertex Edit Mode.
# ---------------------------------------------------------------------------

WIDGETS_LIBRARY_SUBDIR = "assets"
WIDGETS_LIBRARY_FILENAME = "hytale_widgets.blend"
WIDGETS_NAME_PREFIX = "WGT_hytale_"  # prefixo comum de TODOS os WGT_* abaixo (nome-BASE, dentro de hytale_widgets.blend -- ver _widget_instance_name em rig.py pro nome final por-personagem que efetivamente aparece em bpy.data.objects)

WGT_DEFAULT_FALLBACK = "WGT_hytale_default"  # usado quando o shape "preferido" abaixo não existe ainda
WIDGET_WIRE_WIDTH = 2.0  # custom_shape_wire_width -- espessura de linha, igual pra TODOS os bones com shape
ATTACHMENT_SHAPE_SCALE = 0.3  # scale genérico pra QUALQUER attachment sem override de "scale" específico

# v0.9.7 -- teto único do "Attachments Bones Amount" (ver HytaleIKChainItem
# em rig.py, chain_type == "ATTACHMENTS"). Blender não permite uma lista
# de campos GENUINAMENTE ilimitada dentro de um PropertyGroup (cada
# StringProperty precisa existir como um campo declarado) -- por isso
# os campos attachment_bone_1..N são gerados NUM LOOP em tempo de
# definição da classe, usando este número. Pra aumentar/diminuir o
# limite, só mude este valor aqui -- rig.py e interface.py leem daqui,
# nenhum outro lugar tem o número "25" hardcoded.
ATTACHMENTS_MAX_COUNT = 25

# v0.10.13 -- mesmo mecanismo/motivo de ATTACHMENTS_MAX_COUNT acima
# (Blender não permite lista genuinamente ilimitada de StringProperty
# dentro de um PropertyGroup -- os campos texture_picker_extra_bone_1..N em
# rig.py são gerados num loop usando este número), mas pra "Companion
# Bones Amount" do chain_type TEXTURE_PICKER -- bones extras que compartilham o
# mesmo atlas/cursor de UV que o Target Bone principal e devem se mexer
# JUNTOS (ex.: metades L/R espelhadas). Teto bem menor que Attachments
# de propósito -- o alvo animado raramente é feito de mais de 2-3 malhas
# separadas, diferente de attachment points (que podem ser muitos).
TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT = 8

WGT_FK_RING = "WGT_hytale_fk_ring"          # bones _CTRL genéricos (FK)
WGT_IK_BOX = "WGT_hytale_ik_box"            # ponta de cadeia IK (mão/pé -- o _IK que tem o switch)
WGT_POLE = "WGT_hytale_pole"                # *_Pole_CTRL
WGT_POLE_LINE = "WGT_hytale_pole_line"      # *_Pole_Line (v0.8 -- bone visual, ver SUFFIX_POLE_LINE)
WGT_ROOT_MASTER = "WGT_hytale_root_master"  # root.master_CTRL
WGT_ROOT_SPINE = "WGT_hytale_root_spine"    # root.spine_CTRL
WGT_ROOT_PELVIS = "WGT_hytale_root_pelvis"  # root.pelvis_CTRL
WGT_HEAD = "WGT_hytale_head"                # Head_CTRL
WGT_ORIGIN = "WGT_hytale_origin"            # Origin_CTRL (gerado do ORG "Origin" pelo loop padrão -- ver override abaixo)
WGT_PROPERTIES = "WGT_hytale_properties"    # bone PROPERTIES (ver BONE_PROPERTIES) -- override abaixo
WGT_ATTACHMENT = "WGT_hytale_attachment"    # qualquer _CTRL de attachment (is_attachment_bone) -- antes caía no WGT_FK_RING genérico
WGT_TEXTURE_PICKER_CURSOR = "WGT_hytale_texture_picker_cursor"  # v0.10 -- mira achatada, widget dedicado do bone cursor (nome derivado por instância, ver rig.py)
WGT_UI_ROOT = "WGT_hytale_ui_root"  # v0.10.4 -- widget do bone root.ui (nome derivado por instância, ver rig.py) -- hoje só o Texture Picker usa

# WIDGET_NAME_OVERRIDES fica definido mais abaixo, depois de
# HEAD_COLLECTION_ROOT (ele referencia essa constante -- ver o comentário
# perto de HEAD_COLLECTION_ROOT pra não repetir a definição fora de ordem).

# Presets de cadeias de IK, por nome de personagem/criatura -- ANTES um
# dict fixo aqui (HYTALE_RIG_PRESETS), agora vêm de templates/rig/*.json
# (builtin, ex.: templates/rig/player.json) + Documentos/Hyblend/
# templates/rig/*.json (usuário) -- ver templates/__init__.py pro schema
# completo. RIG_OT_hytale_ik_chain_load_defaults lista automaticamente
# todo template descoberto como opção; pra adicionar um personagem novo
# não precisa mais tocar em código nenhum, só criar um .json.

# ---------------------------------------------------------------------------
# Correção de posição (só eixo X) de juntas específicas da cadeia IK, e
# ajuste fino da Translation X do custom shape correspondente -- ANTES
# dois dicts fixos aqui (PLAYER_IK_JOINT_X_OVERRIDES/
# PLAYER_WIDGET_TRANSLATION_X_OVERRIDES), calibrados só pro "Player".
# Agora vêm de rig_template["ik_joint_x_overrides"] /
# rig_template["widget_translation_x_overrides"] (ver
# templates/rig/player.json) -- cada personagem calibrado define os
# próprios valores; nenhum é aplicado se o template ativo
# (armature.hytale_active_rig_template) não os definir. Aplicado só se
# Armature.hytale_apply_ik_joint_fix estiver ligado (default False,
# registrado no fim do arquivo) -- RIG_OT_hytale_ik_chain_load_defaults
# liga esse toggle automaticamente conforme
# rig_template["apply_ik_joint_fix"], mas continua ajustável manualmente
# depois. Ver _apply_ik_joint_fixes.
#
# Y/Z NUNCA são tocados nos bones de ik_joint_x_overrides, só X. NÃO mexe
# no *_MCH_IK_Transfer (bridge) -- só nos bones _IK "de verdade" (CTRL-IK).

# Dica de nome pra encontrar o bone-filho usado como referência de
# orientação da ponta da cadeia (ex.: "L-Attachment", filho de "L-Hand").
# Case-insensitive, substring. Também usada pra identificar QUALQUER bone
# relacionado a attachment (em qualquer camada -- ORG/MCH/CTRL/IK) pra
# jogar na collection "Attachments" e excluir das collections Main/*.
ATTACHMENT_NAME_HINT = "attachment"

# Bones específicos das collections Main/* (ver _build_main_collections).
HEAD_COLLECTION_ROOT = "Head" + SUFFIX_CTRL

# Overrides pontuais -- bone (nome exato) -> nome do widget na biblioteca,
# pros bones utilitários/especiais que não seguem a regra genérica por
# layer (ver _widget_name_for_bone). Mesmo espírito de CTRL_PARENT_OVERRIDES
# acima -- adicione mais entradas aqui se algum _CTRL específico merecer um
# shape diferente do genérico (WGT_FK_RING). Fica aqui (não junto dos WGT_*
# acima) porque depende de HEAD_COLLECTION_ROOT, definida nesta linha.
#
# Origin_CTRL: apesar do nome sugerir bone raiz/utilitário, ele É um _CTRL
# comum -- gerado pelo loop padrão (org->_CTRL) a partir de um ORG chamado
# "Origin" que já vem no modelo importado, então JÁ tem PROP_RIG_LAYER =
# "CTRL" antes mesmo de _build_root_controls rodar (é por isso que dá pra
# usá-lo como parent do root.master_CTRL -- ver ROOT_MASTER_PARENT -- ele
# já existe nesse ponto da MESMA execução, não "de fora" do script). Sem
# este override ele já cairia no branch genérico (layer == "CTRL" ->
# WGT_FK_RING); a entrada abaixo só troca pra um shape dedicado.
#
# PROPERTIES: mesmo caso de Origin_CTRL -- criado com PROP_RIG_LAYER =
# "CTRL" (ver _build_root_controls) apesar de não ser um _CTRL normal
# (guarda só as custom properties de FK/IK switch, não é pra ser
# animado/posado -- ver BONE_PROPERTIES). Sem este override, caía no
# mesmo WGT_FK_RING genérico de qualquer outro _CTRL.
WIDGET_NAME_OVERRIDES = {
    BONE_ROOT_MASTER: WGT_ROOT_MASTER,
    BONE_ROOT_SPINE: WGT_ROOT_SPINE,
    BONE_ROOT_PELVIS: WGT_ROOT_PELVIS,
    HEAD_COLLECTION_ROOT: WGT_HEAD,
    ROOT_MASTER_PARENT: WGT_ORIGIN,
    BONE_PROPERTIES: WGT_PROPERTIES,
    # v0.10 -- Texture Picker: _build_texture_picker cria/atribui esses dois bones
    # fora do loop genérico org->_CTRL, então nunca passam por este dict
    # de qualquer forma (o widget é atribuído direto lá).
    #
    # v0.12 -- as entradas BONE_TEXTURE_PICKER_CURSOR/BONE_UI_ROOT que
    # existiam aqui foram REMOVIDAS: os dois nomes agora são DERIVADOS
    # por instância (um bone por entrada, ver _texture_picker_ui_root_
    # name/_texture_picker_cursor_name em rig.py), então uma chave FIXA
    # aqui nunca bateria com o nome de verdade do bone -- ficaria morta,
    # nunca lida por nenhum lookup por nome exato. _build_texture_picker
    # já não dependia deste dict pra esses dois bones (atribuição direta,
    # ver comentário acima) -- então removê-las não muda comportamento
    # nenhum, só tira uma entrada que nunca mais faria sentido existir.
}

# Ajustes finos de Translation/Rotation/Scale do custom shape, por bone --
# ANTES um dict fixo aqui (WIDGET_TRANSFORM_OVERRIDES), com um personagem
# só (Player) hardcoded. Agora vêm de shape_template["bones"] (ver
# templates/shapes/player.json e o schema completo em
# templates/__init__.py) -- cada bone só precisa ter as chaves que
# fizerem sentido ("scale", "translation", "rotation_deg"); as que não
# aparecem ficam do jeito que já estão (não são resetadas). Rotação no
# arquivo é em GRAUS (rotation_deg) -- a conversão pra radianos acontece
# em _apply_widget_transform_override, na hora de aplicar.
#
# Bones dentro de uma cadeia IK (os que têm o driver de troca FK/IK -- ver
# _build_ik_fk_shape_visibility): "scale" aqui é o tamanho "cheio" (modo
# ativo), não o valor bruto salvo no bone -- o driver multiplica esse
# número por 0 ou 1 dependendo do fk_ik_switch. Pra bones fora de
# qualquer cadeia (a maioria dos _CTRL do corpo), "scale" é aplicado
# direto, sem driver.
#
# Qual TEMPLATE de shapes está ativo pra um Armature é
# armature.hytale_active_shape_template (StringProperty, registrado no
# fim do arquivo) -- setado automaticamente por
# RIG_OT_hytale_ik_chain_load_defaults (usa rig_template["shape_template"],
# ou o mesmo nome do rig template se esse campo não existir), e também
# ajustável manualmente (ver RIG_OT_hytale_shape_template_apply).
SPINE_COLLECTION_BONES = ["Pelvis" + SUFFIX_CTRL, "Belly" + SUFFIX_CTRL, "Chest" + SUFFIX_CTRL]

# ---------------------------------------------------------------------------
# Bone Color (Custom Color Set) -- pintura dos bones no viewport, separada
# de tudo que é custom shape. Cada "palette" é uma tupla de 3 cores RGB
# (0-1, não 0-255): (normal, select, active) -- exatamente os 3 estados que
# o Blender usa em bone.color.custom (ver _build_bone_colors). "normal" é
# a cor base (bone não selecionado), "select" quando está entre vários
# bones selecionados, "active" quando é O bone selecionado no momento.
# ---------------------------------------------------------------------------
BONE_COLOR_LEFT = ((0.9412, 0.0, 0.0), (1.0, 0.3216, 0.3216), (1.0, 0.3961, 0.3961))
BONE_COLOR_RIGHT = ((0.0, 0.349, 1.0), (0.298, 0.5412, 1.0), (0.4471, 0.6784, 1.0))
BONE_COLOR_ROOT_HEAD = ((1.0, 0.8706, 0.0), (1.0, 0.8824, 0.2157), (1.0, 0.8863, 0.4353))
BONE_COLOR_SPINE = ((0.0, 0.7961, 0.0), (0.0, 0.8471, 0.0), (0.5765, 1.0, 0.498))
BONE_COLOR_ATTACHMENT = ((0.8471, 0.8471, 0.8471), (0.898, 0.898, 0.898), (1.0, 1.0, 1.0))
BONE_COLOR_PROPERTIES = ((0.1451, 0.5137, 1.0), (0.1608, 0.4667, 1.0), (0.3373, 0.502, 1.0))  # #2583FF / #2977FF / #5680FF
# v0.10.7 -- cores dedicadas pedidas pelo usuário (hex convertido pra
# 0..1): root.ui = amarelo, cursor = vermelho -- diferente uma da
# outra de propósito (cursor precisa se destacar do "quadro" que ele
# fica dentro). Substituem o antigo BONE_COLOR_UI (magenta único pros
# dois).
BONE_COLOR_UI_ROOT = ((1.0, 0.8706, 0.0), (1.0, 0.8824, 0.2157), (1.0, 0.8824, 0.2157))  # #FFDE00 / #FFE137 / #FFE137
BONE_COLOR_UI_CURSOR = ((0.8392, 0.0, 0.0), (1.0, 0.2784, 0.2784), (1.0, 0.0, 0.0))  # #D60000 / #FF4747 / #FF0000

# Overrides pontuais -- bone (nome exato) -> palette acima. Vence a regra
# genérica de prefixo L-/R- (ver _build_bone_colors). SPINE_COLLECTION_BONES
# (Pelvis_CTRL/Belly_CTRL/Chest_CTRL) reaproveitada -- já existe acima.
BONE_COLOR_OVERRIDES = {
    BONE_ROOT_MASTER: BONE_COLOR_ROOT_HEAD,
    BONE_ROOT_SPINE: BONE_COLOR_ROOT_HEAD,
    BONE_ROOT_PELVIS: BONE_COLOR_ROOT_HEAD,
    HEAD_COLLECTION_ROOT: BONE_COLOR_ROOT_HEAD,
    ROOT_MASTER_PARENT: BONE_COLOR_ROOT_HEAD,  # Origin_CTRL
    **{name: BONE_COLOR_SPINE for name in SPINE_COLLECTION_BONES},
    "Neck" + SUFFIX_CTRL: BONE_COLOR_SPINE,  # Neck_CTRL -- só entrou no grupo verde nesta atualização
    BONE_PROPERTIES: BONE_COLOR_PROPERTIES,
    # v0.12 -- BONE_UI_ROOT/BONE_TEXTURE_PICKER_CURSOR REMOVIDAS daqui
    # (mesmo motivo do comentário em WIDGET_NAME_OVERRIDES, acima): os
    # dois nomes agora são derivados por instância, uma chave fixa nunca
    # bateria com o bone de verdade. _build_texture_picker já colore
    # esses dois bones direto (BONE_COLOR_UI_ROOT/BONE_COLOR_UI_CURSOR),
    # sem depender deste dict.
}
BODY_COLLECTION_BONES = [BONE_ROOT_SPINE, BONE_ROOT_MASTER, BONE_ROOT_PELVIS]
ROOT_COLLECTION_BONES = [ROOT_MASTER_PARENT]
ARM_COLLECTION_ROOTS = {
    COLL_MAIN_ARM_L: ["L-Shoulder" + SUFFIX_CTRL],
    COLL_MAIN_ARM_R: ["R-Shoulder" + SUFFIX_CTRL],
}
# Fallback determinístico pra personagem SEM bone de ombro (a cadeia de
# braço começa direto no Arm -- existe pelo menos um mod assim, ver
# DEVELOPER_NOTES.md/histórico do chat). Precisa dos DOIS ramos
# explicitamente (CTRL e IK), mesmo motivo de LEG_COLLECTION_ROOTS logo
# abaixo: o "_IK" da raiz da cadeia (ex. "L-Arm_IK") nasce SEM parent
# quando não há um Shoulder_CTRL pro parent_override resolver (ver
# aviso "Parent override ... left unparented" em _build_ik_layer) --
# fica solto na hierarquia, então andar a árvore a partir de
# "L-Arm_CTRL" não é suficiente pra alcançá-lo; precisa entrar como raiz
# própria do walk.
ARM_COLLECTION_ROOTS_NO_SHOULDER = {
    COLL_MAIN_ARM_L: ["L-Arm" + SUFFIX_CTRL, "L-Arm" + SUFFIX_IK],
    COLL_MAIN_ARM_R: ["R-Arm" + SUFFIX_CTRL, "R-Arm" + SUFFIX_IK],
}
# Pernas precisam dos DOIS ramos explicitamente (FK e IK não têm um
# ancestral comum dentro da própria perna -- ambos são filhos diretos de
# root.pelvis_CTRL, que é compartilhado pelas duas pernas).
LEG_COLLECTION_ROOTS = {
    COLL_MAIN_LEG_L: ["L-Thigh" + SUFFIX_CTRL, "L-Thigh" + SUFFIX_IK],
    COLL_MAIN_LEG_R: ["R-Thigh" + SUFFIX_CTRL, "R-Thigh" + SUFFIX_IK],
}


# ---------------------------------------------------------------------------
# Sentinel de UI (movido pra cá no split -- Tarefa A -- porque é usado
# em mais de uma seção de rig.py, tanto pelos operadores de lista de IK
# chains quanto pelos de template; antes vivia junto de
# _template_source(), que continua só na seção de Template Ops).
# ---------------------------------------------------------------------------

# "(none)" -- sentinel de UI que _rebuild_items_cache() (templates/__init__.py)
# sempre injeta como primeira opção dos 3 dropdowns (wm.hytale_*_template_selected,
# ver interface.py) pra dar pra desmarcar a seleção de propósito. NUNCA é
# um template de verdade -- list_*_templates()/get_*_template() nunca o
# incluem/resolvem, então checar contra ele é sempre explícito aqui.
_TEMPLATE_NONE = "NONE"
