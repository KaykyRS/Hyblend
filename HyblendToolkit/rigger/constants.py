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
# bridges _IK_MCH da cadeia de IK, também guarda os bridges _Tail da
# cadeia de Tail (ver _build_tail_layer) -- os dois são o mesmo tipo de
# coisa (bone "de mecanismo", só existe pra dar uma rest orientation
# "limpa" pra outro bone copiar, nunca selecionado/posado por quem
# anima), então dividem a MESMA bone collection interna/oculta em vez de
# cada cadeia ganhar uma própria. O valor da custom property
# PROP_RIG_LAYER continua "MCH-IK" pros bridges de IK (não mexi nisso --
# é dado interno, independente do nome de exibição da collection) e
# "TAIL" pros bridges de Tail (ver is_excluded_from_main_collections).
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
COLL_MAIN_TAIL = "Tail"  # v0.7 -- bones _Tail (ver SUFFIX_TAIL), sempre visível (mesmo espírito de Arm/Leg/etc.)

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
    COLL_MAIN_TAIL,
}

# v0.9 (Tarefa B, split de rigger.py): SUFFIX_MCH/SUFFIX_CTRL/SUFFIX_IK
# deixaram de ser definidos aqui -- agora vêm de common.py, que também
# passou a ser a fonte da verdade pro exporter.py (antes cada lado tinha
# a própria cópia -- rigger.py com estes literais, exporter.py com
# CONTROL_SUFFIXES -- e só concordavam "por acaso"; ver DEVELOPER_NOTES.md,
# "Duplicação solta pra ficar de olho"). SUFFIX_IK_MCH e SUFFIX_POLE
# CONTINUAM só aqui -- não são usados por mais ninguém fora do rigger,
# não precisam ir pra common.py (regra prática: common.py só compartilha
# o que realmente precisa ser idêntico dos dois lados).
from ..common import SUFFIX_CTRL, SUFFIX_IK, SUFFIX_MCH

SUFFIX_IK_MCH = "_IK_MCH"  # bone-ponte por segmento, parentado ao _IK do mesmo segmento
SUFFIX_POLE = "_Pole_CTRL"

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

# v0.7: bone-ponte por segmento de uma cadeia TAIL (ver HytaleIKChainItem.
# chain_type e _build_tail_layer) -- MESMO princípio do bridge _IK_MCH:
# mantém a rest orientation "real" (a do ORG original, intocada) separada
# do bone que o usuário efetivamente anima (aqui, o próprio _CTRL -- não
# um bone à parte). É o _CTRL da cauda que recebe o redirect de tail
# (aponta pro head do próximo segmento) pra formar a cadeia sempre
# conectada (use_connect=True) que addons de física esperam; o `_Tail`
# só existe pra dar ao MCH uma fonte de rotação/escala/posição com rest
# "limpa" (sem o redirect), do mesmo jeito que o `_IK_MCH` existe pro MCH
# de uma cadeia de IK (ver _build_tail_pose_constraints).
SUFFIX_TAIL = "_Tail"

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
# Os objetos widget NÃO são linkados em nenhuma collection de cena (mesma
# técnica do Rigify) -- ficam "órfãos" de propósito: pose_bone.custom_shape
# já conta como usuário do datablock (não somem ao salvar), mas também não
# aparecem soltos no viewport/outliner pra alguém selecionar sem querer.
# ---------------------------------------------------------------------------

WIDGETS_LIBRARY_SUBDIR = "assets"
WIDGETS_LIBRARY_FILENAME = "hytale_widgets.blend"
WIDGETS_NAME_PREFIX = "WGT_hytale_"  # prefixo comum de TODOS os WGT_* abaixo -- usado pra purgar em massa (ver RIG_OT_hytale_clear_generated)

WGT_DEFAULT_FALLBACK = "WGT_hytale_default"  # usado quando o shape "preferido" abaixo não existe ainda
WIDGET_WIRE_WIDTH = 2.0  # custom_shape_wire_width -- espessura de linha, igual pra TODOS os bones com shape
ATTACHMENT_SHAPE_SCALE = 0.3  # scale genérico pra QUALQUER attachment sem override de "scale" específico

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
# no *_IK_MCH (bridge) -- só nos bones _IK "de verdade" (CTRL-IK).

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
