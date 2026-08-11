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
# v0.6: toda calibração POR PERSONAGEM que ainda estava hardcoded aqui
# (HYTALE_RIG_PRESETS, WIDGET_TRANSFORM_OVERRIDES, ARM_POLE_ANGLE_PRESET,
# PLAYER_IK_JOINT_X_OVERRIDES, PLAYER_WIDGET_TRANSLATION_X_OVERRIDES) foi
# extraída pra arquivos .json plugáveis, dentro do pacote novo
# `templates/` (rig/ + shapes/, builtin + Documentos/Hyblend/templates/
# do usuário) -- ver templates/__init__.py pro schema completo e o
# racional. rigger.py agora só sabe COMO montar um rig a partir de um
# template; QUAL personagem virou dado externo, não código.
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
    "version": (0, 6, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Hytale Rigger",
    "description": "Auto-generate the ORG/MCH/CTRL/CTRL-IK/MCH-IK bone layers, constraints, "
    "IK/FK switch drivers, root control bones and Main/Face/Attachments collections "
    "for a Hytale character armature",
    "category": "Rigging",
}

import math
import os
import re
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
from bpy.types import Armature, Operator, PropertyGroup, UIList, WindowManager
from mathutils import Euler, Matrix, Vector

from .templates import (
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
    rig_template_enum_items,
    save_collection_template,
    save_rig_template,
    save_shape_template,
    shape_template_enum_items,
)

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
}

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
WGT_ROOT_MASTER = "WGT_hytale_root_master"  # root.master_CTRL
WGT_ROOT_SPINE = "WGT_hytale_root_spine"    # root.spine_CTRL
WGT_ROOT_PELVIS = "WGT_hytale_root_pelvis"  # root.pelvis_CTRL
WGT_HEAD = "WGT_hytale_head"                # Head_CTRL
WGT_ORIGIN = "WGT_hytale_origin"            # Origin_CTRL (gerado do ORG "Origin" pelo loop padrão -- ver override abaixo)
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
WIDGET_NAME_OVERRIDES = {
    BONE_ROOT_MASTER: WGT_ROOT_MASTER,
    BONE_ROOT_SPINE: WGT_ROOT_SPINE,
    BONE_ROOT_PELVIS: WGT_ROOT_PELVIS,
    HEAD_COLLECTION_ROOT: WGT_HEAD,
    ROOT_MASTER_PARENT: WGT_ORIGIN,
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

# ARM_COLLECTION_ROOTS/LEG_COLLECTION_ROOTS acima são nomes FIXOS --
# cobrem o Player (e qualquer personagem com a mesma convenção de nome).
# _resolve_main_limb_roots complementa isso (nunca substitui) de duas
# formas: (1) checando o esqueleto de VERDADE (edit_bones) -- se
# "L-Shoulder_CTRL" não existir nesse personagem, troca pra
# ARM_COLLECTION_ROOTS_NO_SHOULDER automaticamente, sem depender de
# nenhum texto digitado em lugar nenhum; (2) usando a cadeia de IK REAL
# já configurada em armature.hytale_ik_chains pra cobrir nomes de bone
# totalmente customizados (nem Shoulder nem Arm) -- essa segunda parte
# ainda tenta classificar a cadeia como braço/perna pelo texto livre do
# campo `label` (_classify_chain_limb), o que é só um best-effort
# complementar -- NUNCA é o único mecanismo pro caso comum (Player-like
# sem Shoulder), que já é resolvido de forma confiável pelo item (1)
# acima. Ver histórico do chat: a versão anterior dependia só do label
# pra isso, e falhava silenciosamente quando o label vinha vazio ou
# escrito diferente.
_LIMB_LABEL_KEYWORDS = {
    "ARM": ("arm", "braco"),   # "braço" comparado sem acento -- ver _classify_chain_limb
    "LEG": ("leg", "perna"),
}


def _classify_chain_limb(item):
    """Tenta classificar uma HytaleIKChainItem (rigger.py) como braço ou
    perna, só pelo texto livre do campo `label` (ex.: 'Arm L', 'Leg R',
    'Perna R' -- o próprio tooltip do campo já sugere esse padrão,
    'e.g. Arm L'). Case-insensitive, sem acento. Retorna 'ARM'/'LEG'/None
    (label não reconhecido -- ex.: uma cadeia de cauda/orelha custom,
    que não deve ser forçada em nenhuma das duas)."""
    label = (item.label or "").lower().replace("ç", "c").replace("ã", "a")
    for limb, keywords in _LIMB_LABEL_KEYWORDS.items():
        if any(keyword in label for keyword in keywords):
            return limb
    return None


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
       verdade -- não depende de nenhum texto digitado em lugar nenhum,
       então funciona mesmo se a cadeia de IK correspondente não tiver
       `label` nenhum preenchido.
    3. ACRESCENTA a raiz real (root_bone + _CTRL, root_bone + _IK) de
       toda cadeia em armature.hytale_ik_chains cujo label dê pra
       classificar como braço/perna (ver _classify_chain_limb) -- só
       best-effort complementar, pra cobrir nome de bone totalmente
       customizado (nem Shoulder nem Arm/Thigh). Nunca remove nada do
       que já foi resolvido nos passos 1-2."""
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


# Casa com o `template` de add_custom_shape_scale_switch_driver acima
# ("{v}*switch" / "{v}*(1 - switch)") -- captura só o número literal do
# começo da expressão, que é o `target_scale[i]` original (o "tamanho
# cheio", modo ativo) embutido em cada driver.
_SHAPE_SCALE_DRIVER_VALUE_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*\*")


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


def _widgets_library_path():
    """Caminho absoluto pro hytale_widgets.blend, resolvido em relação a
    ESTE arquivo (rigger.py) -- funciona tanto instalado como Extension
    (pasta HyblendToolkit/ dentro do perfil do Blender) quanto rodado como
    addon avulso, desde que a pasta assets/ esteja ao lado deste .py."""
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(addon_dir, WIDGETS_LIBRARY_SUBDIR, WIDGETS_LIBRARY_FILENAME)


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
    if bone_name.endswith(SUFFIX_POLE):
        return WGT_POLE
    if ATTACHMENT_NAME_HINT in bone_name.lower():
        return WGT_ATTACHMENT
    if layer == "CTRL-IK":
        return WGT_IK_BOX
    if layer in ("CTRL", "ROOT-CTRL"):
        return WGT_FK_RING
    return None


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


# ---------------------------------------------------------------------------
# PropertyGroup: um item = uma cadeia de IK inteira, referenciada por nome
# ---------------------------------------------------------------------------


class HytaleIKChainItem(PropertyGroup):
    label: StringProperty(
        name="Label",
        description="Free-form name just to identify this chain in the list (e.g. Arm L)",
        default="",
    )
    root_bone: StringProperty(
        name="Root Bone",
        description="First bone of the chain (e.g. L-Arm, L-Thigh)",
        default="",
    )
    tip_bone: StringProperty(
        name="Tip Bone",
        description="Last bone of the chain -- the target/effector (e.g. L-Hand, L-Foot)",
        default="",
    )
    pole_bone: StringProperty(
        name="Pole Reference",
        description="Bone used as the position/orientation reference for the pole target (e.g. L-Forearm). "
        "Empty = automatically uses the middle bone of the root->tip path",
        default="",
    )
    parent_override: StringProperty(
        name="Root Parent",
        description="Optional bone that becomes the parent of this chain's root _IK (e.g. L-Shoulder_CTRL, "
        "Pelvis). Empty = left unparented. Some names are automatically resolved to utility bones that only "
        "exist after generation (see PARENT_OVERRIDE_ALIASES) -- e.g. typing 'Pelvis' resolves to "
        "'root.pelvis_CTRL'.",
        default="",
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


# ---------------------------------------------------------------------------
# Operadores: gerenciar a lista de cadeias IK
# ---------------------------------------------------------------------------


class RIG_OT_hytale_ik_chain_add(Operator):
    """Adiciona uma cadeia de IK vazia à lista (preencha os nomes dos
    bones depois -- ou via um picker, quando a UI real estiver pronta)."""

    bl_idname = "armature.hytale_ik_chain_add"
    bl_label = "Add Hytale IK Chain"
    bl_description = "Add an empty IK chain to the list"
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
        return {"FINISHED"}


class RIG_OT_hytale_ik_chain_set_count(Operator):
    """Ajusta a lista de cadeias de IK pra ter exatamente `count` itens --
    adiciona vazias no fim ou remove do fim, sem tocar nas do meio."""

    bl_idname = "armature.hytale_ik_chain_set_count"
    bl_label = "Set Hytale IK Chain Count"
    bl_description = "Set the exact number of IK chains in the list, adding or removing at the end"
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
        if self.field not in {"root_bone", "tip_bone", "pole_bone", "parent_override"}:
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
            "label", "root_bone", "tip_bone", "pole_bone", "parent_override", "side",
            "pole_invert", "pole_distance", "pole_angle_mode", "pole_angle_preset_name",
            "pole_angle_manual", "pole_angle_fine_tune", "extra_ik_location",
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
            f"Removed {removed} generated bone(s); purged {purged} cached widget object(s) "
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
            joint_fix_count = 0
            if getattr(armature, "hytale_apply_ik_joint_fix", False):
                joint_fix_count = self._apply_ik_joint_fixes(obj, chains_data)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

        self._build_pose_constraints(obj, chains_data)
        self._build_spine_follow(obj)
        self._apply_pole_childof_inverses(obj, chains_data)
        widget_stats = self._build_custom_shapes(obj, chains_data)
        shape_switch_count = self._build_ik_fk_shape_visibility(obj, chains_data)
        colored_count = self._build_bone_colors(obj)

        if prev_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=prev_mode)

        self.report(
            {"INFO"},
            f"Rig ready: {stats['mch']} MCH, {stats['ctrl']} CTRL, {stats['ik']} CTRL-IK, "
            f"{stats['ik_mch']} MCH-IK, {stats['root']} root control bone(s) created; "
            f"{len(chains_data)} IK chain(s) processed; "
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
        não só a ponta.

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
        return applied

    def _build_bone_colors(self, obj):
        """Pinta bone.color (Custom Color Set) por bone -- não tem nada a
        ver com custom shape, é a cor de exibição do bone em si (Bone
        Properties > Viewport Display > Color, ou o painel de Bone Color
        na sidebar). Aplicado ao Bone (obj.data.bones), não ao PoseBone --
        assim vale em Edit Mode e Pose Mode igual, sem precisar de duas
        atribuições.

        Regra: BONE_COLOR_OVERRIDES (nome exato) vence; senão, attachment
        (is_attachment_bone) vence o prefixo L-/R- (BONE_COLOR_ATTACHMENT);
        senão, prefixo L-/R- decide (BONE_COLOR_LEFT/BONE_COLOR_RIGHT);
        bones que não se encaixam em nenhum caso ficam com a cor padrão
        do Blender (não mexe).

        Bones ORG (sem PROP_RIG_LAYER -- nunca passaram por este script,
        são os nomes originais do modelo importado, ex.:
        L-Eyebrow-Attachment) NUNCA recebem cor, mesmo tendo prefixo
        L-/R-: eles ficam ocultos (collection ORG) e não fazem sentido
        coloridos -- só os bones gerados (MCH/CTRL/CTRL-IK/MCH-IK/
        ROOT-CTRL) entram na regra."""
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

        org_bones = [b for b in edit_bones if PROP_RIG_LAYER not in b.keys()]
        org_by_name = {b.name: b for b in org_bones}
        ordered = self._order_top_down(org_bones, org_by_name)

        stats = {"mch": 0, "ctrl": 0, "ik": 0, "ik_mch": 0, "root": 0}

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
            reparented_ctrl_roots = []
            attachment_org = find_attachment_child(tip_org)
            attachment_ctrl = edit_bones.get(attachment_org.name + SUFFIX_CTRL) if attachment_org else None
            if attachment_ctrl is not None:
                # O _CTRL do attachment (ex.: socket de arma na mão) é
                # criado pelo loop padrão com parent = tip_org_CTRL (ex.:
                # Hand_CTRL) -- mas Hand_CTRL é só o controle FK, que NÃO
                # se move quando o braço está em modo IK. O attachment
                # precisa seguir o resultado FINAL (ORG, que já é
                # constrained pra seguir FK OU IK conforme o switch), não
                # só o FK. Roda TODA VEZ (não só "if is_new"): corrige
                # também attachments já existentes de execuções antigas.
                attachment_ctrl.parent = tip_org
                attachment_ctrl.use_connect = False
                reparented_ctrl_roots.append(attachment_ctrl.name)

            # Mesmo problema do attachment acima, mas pra filhos ORG
            # "normais" da ponta da cadeia -- o caso mais comum é dedo
            # (Toe* sob Foot, ou dedo de mão sob Hand): o _CTRL desses
            # bones nasce parentado no _CTRL da ponta (Foot_CTRL/
            # Hand_CTRL) pelo pipeline padrão de _build_edit_bones, mas
            # esse _CTRL é só a versão FK -- não se move quando a cadeia
            # está em modo IK, então o dedo "descola" do pé/mão nesse
            # modo. Reparenta pro ORG da ponta (tip_org), que já é
            # constrained pra seguir FK OU IK (CONSTRAINT_ORG_TO_MCH),
            # do mesmo jeito que o attachment. Roda toda vez (não só
            # "if is_new"), corrigindo também rigs já gerados antes
            # dessa mudança.
            for extra_child in find_non_attachment_children(tip_org):
                extra_ctrl = edit_bones.get(extra_child.name + SUFFIX_CTRL)
                if extra_ctrl is None:
                    continue
                extra_ctrl.parent = tip_org
                extra_ctrl.use_connect = False
                reparented_ctrl_roots.append(extra_ctrl.name)

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

            chains_data.append(
                {
                    "org_names": [b.name for b in chain],
                    "ik_root": chain[0].name + SUFFIX_IK,
                    "ik_solver_end": chain[tip_index - 1].name + SUFFIX_IK,
                    "ik_tip": chain[tip_index].name + SUFFIX_IK,
                    "pole": pole.name,
                    "side": item.side,
                    "pole_angle_mode": item.pole_angle_mode,
                    "pole_angle_preset_name": item.pole_angle_preset_name,
                    "pole_angle_manual": item.pole_angle_manual,
                    "pole_angle_fine_tune": item.pole_angle_fine_tune,
                    "extra_ik_location": item.extra_ik_location,
                    # Nome da custom property de FK/IK switch DESTA cadeia,
                    # dentro do bone PROPERTIES (não mais uma property por
                    # bone _IK) -- ver switch_property_name.
                    "switch_property": switch_property_name(chain[tip_index].name, item.side),
                    # Bones _CTRL reparentados pro ORG da ponta (ver acima:
                    # attachment_ctrl + find_non_attachment_children) --
                    # ficam FORA da árvore de parent que assign_descendants
                    # caminha em _build_main_collections, então precisam
                    # ser propagados manualmente pra mesma collection do
                    # resto da cadeia (ver _propagate_pole_and_tip_to_main_collections).
                    "reparented_ctrl_roots": reparented_ctrl_roots,
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
        walk de descendentes que monta Arm L/R e Leg L/R. Aqui, pra cada
        cadeia, descobre em qual sub-collection de Main o resto da cadeia
        (o "_IK" raiz) já caiu, e replica pro pole, pro tip e pra todo
        _CTRL reparentado pro ORG da ponta (attachment_ctrl/dedos -- ver
        reparented_ctrl_roots em _build_ik_layer -- esses também ficam
        fora da árvore de parent normal do walk, do mesmo jeito que o
        pole/tip, só que por reparenting em vez de nascerem sem parent)."""
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
                rig_template = get_rig_template(getattr(armature, "hytale_active_rig_template", ""))
                presets = rig_template.get("pole_angle_presets", {}) if rig_template else {}
                preset_deg = presets.get(data["pole_angle_preset_name"], {}).get(data["side"])
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


# ---------------------------------------------------------------------------
# UIList reutilizável pela aba "Rig" do interface.py (registrada aqui
# porque descreve como desenhar um item de armature.hytale_ik_chains --
# é dado/lógica deste módulo, não layout de painel).
# ---------------------------------------------------------------------------


class RIG_UL_hytale_ik_chains(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "label", text="", emboss=False, icon="BONE_DATA")


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


# "(none)" -- sentinel de UI que _rebuild_items_cache() (templates/__init__.py)
# sempre injeta como primeira opção dos 3 dropdowns (wm.hytale_*_template_selected,
# ver interface.py) pra dar pra desmarcar a seleção de propósito. NUNCA é
# um template de verdade -- list_*_templates()/get_*_template() nunca o
# incluem/resolvem, então checar contra ele é sempre explícito aqui.
_TEMPLATE_NONE = "NONE"


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
# Operadores: salvar o estado atual como um template NOVO do usuário
# (sempre em Documentos/Hyblend/templates/ -- ver templates/__init__.py).
# Os dois pedem o nome via invoke_props_dialog (popup simples, 1 campo).
# ---------------------------------------------------------------------------

# Campos de HytaleIKChainItem serializáveis pra JSON (mesma lista usada
# por RIG_OT_hytale_ik_chain_load_defaults pra ler de volta).
_IK_CHAIN_JSON_FIELDS = (
    "label", "root_bone", "tip_bone", "pole_bone", "parent_override", "side",
    "pole_invert", "pole_distance", "pole_angle_mode", "pole_angle_preset_name",
    "pole_angle_manual", "pole_angle_fine_tune", "extra_ik_location",
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


_CLASSES = (
    HytaleIKChainItem,
    RIG_UL_hytale_ik_chains,
    RIG_OT_hytale_ik_chain_add,
    RIG_OT_hytale_ik_chain_remove,
    RIG_OT_hytale_ik_chain_set_count,
    RIG_OT_hytale_ik_chain_pick_bone,
    RIG_OT_hytale_ik_chain_load_defaults,
    RIG_OT_hytale_shape_template_apply,
    RIG_OT_hytale_rig_template_save,
    RIG_OT_hytale_rig_template_delete,
    RIG_OT_hytale_shape_template_save,
    RIG_OT_hytale_shape_template_delete,
    RIG_OT_hytale_collection_template_save,
    RIG_OT_hytale_collection_template_apply,
    RIG_OT_hytale_collection_template_delete,
    RIG_OT_hytale_clear_generated,
    RIG_OT_hytale_generate_rig,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    Armature.hytale_ik_chains = CollectionProperty(type=HytaleIKChainItem)
    Armature.hytale_ik_chains_index = IntProperty(default=0)
    Armature.hytale_apply_ik_joint_fix = BoolProperty(
        name="Apply IK Joint Fix",
        description=(
            "Corrects the X position of specific IK chain joints, using the values defined by the active "
            "rig template (see 'ik_joint_x_overrides' in templates/rig/*.json) -- leave off for a template "
            "that hasn't defined/calibrated these values yet"
        ),
        default=False,
    )
    Armature.hytale_active_rig_template = StringProperty(
        name="Active Rig Template",
        description="Name of the rig template (templates/rig/*.json) currently loaded on this armature -- "
        "set automatically by 'Load Hytale IK Chain Preset', used to resolve pole_angle_presets/"
        "ik_joint_x_overrides/widget_translation_x_overrides at generation time",
        default="",
    )
    Armature.hytale_active_shape_template = StringProperty(
        name="Active Shape Template",
        description="Name of the shape template (templates/shapes/*.json) currently active for this "
        "armature's custom shapes -- set automatically together with the rig template (or manually via "
        "'Set Hytale Shape Template')",
        default="",
    )
    Armature.hytale_active_collection_template = StringProperty(
        name="Active Collection Template",
        description="Name of the collection template (templates/collections/*.json) most recently saved to "
        "or applied on this armature -- purely informational (unlike the rig/shape templates, this one is "
        "never auto-applied by 'Create Rig')",
        default="",
    )

    # Seleção de template (Rig/Shape/Collection) do dropdown compacto da
    # box "Character Templates" do interface.py -- ver comentário acima
    # de _template_source(). No WindowManager (não no Armature, como
    # hytale_ik_chains) porque é a mesma lista de arquivos em disco pra
    # qualquer Armature ativa, não um dado por-personagem; mesma pasta
    # (WindowManager) que interface.py já usa pro estado de UI
    # (hytale_active_tab, hytale_show_templates etc.). items= dinâmico
    # (rig_template_enum_items/shape_template_enum_items/
    # collection_template_enum_items, de templates/__init__.py) -- por
    # ser reavaliado a cada desenho do dropdown, reflete Save/Delete/
    # "Reload Templates" sozinho, sem precisar de nenhuma sincronização
    # manual.
    WindowManager.hytale_rig_template_selected = EnumProperty(name="Rig Template", items=rig_template_enum_items)
    WindowManager.hytale_shape_template_selected = EnumProperty(name="Shape Template", items=shape_template_enum_items)
    WindowManager.hytale_collection_template_selected = EnumProperty(
        name="Collection Template", items=collection_template_enum_items,
    )


def unregister():
    del WindowManager.hytale_collection_template_selected
    del WindowManager.hytale_shape_template_selected
    del WindowManager.hytale_rig_template_selected
    del Armature.hytale_active_collection_template
    del Armature.hytale_active_shape_template
    del Armature.hytale_active_rig_template
    del Armature.hytale_apply_ik_joint_fix
    del Armature.hytale_ik_chains_index
    del Armature.hytale_ik_chains
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
