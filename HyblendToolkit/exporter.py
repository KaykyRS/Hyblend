# ---------------------------------------------------------------------------
# Este arquivo é o submódulo EXPORTER do pacote HyblendToolkit.
# Metadados do addon (nome, versão, versão mínima do Blender, descrição)
# NÃO vivem mais aqui como `bl_info` -- vivem em blender_manifest.toml, na
# raiz do pacote (formato de Extension do Blender 4.5+, ver
# blender_manifest.toml pra fonte da verdade). Se você só recebeu ESTE
# arquivo pra atualizar, não precisa se preocupar com o manifest a menos
# que a mudança exija subir a versão -- ver DEVELOPER_NOTES.md.
# ---------------------------------------------------------------------------

import json
import os
import re

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Armature, Operator, PropertyGroup
from mathutils import Matrix, Quaternion, Vector

from .common import (
    ACTION_SOURCE_DURATION_PROP,
    ACTION_SOURCE_HOLD_LAST_KEYFRAME_PROP,
    BONE_ORIGINAL_NAME_PROP,
    FPS_HYTALE,
    SUFFIX_CTRL,
    SUFFIX_IK,
    SUFFIX_MCH,
    UNIT_SCALE_DEFAULT,
    quat_to_dict,
    vec_to_dict,
)

# ---------------------------------------------------------------------------
# Formato .blockyanim -- ver JannisX11/hytale-blockbench-plugin,
# src/blockyanim.ts (parseAnimationFile / compileAnimationFile), lido e
# confirmado numericamente contra o código-fonte real do plugin oficial:
#
#   {
#     "formatVersion": 1,
#     "duration": <int, em FRAMES a 60 FPS fixo -- NÃO o fps da cena>,
#     "holdLastKeyframe": bool,
#     "nodeAnimations": {
#       "<nome EXATO do bone, igual ao node.name do .blockymodel>": {
#         "position":    [{"time": <frame int>, "delta": {x,y,z},   "interpolationType": "smooth"|"linear"}],
#         "orientation": [{"time": <frame int>, "delta": {x,y,z,w}, "interpolationType": ...}],
#         "shapeStretch": [...]   # mesmo formato de position, opcional
#         "shapeUvOffset": [{"time": <frame int>, "delta": {x,y}, "interpolationType": ...}]
#       }
#     }
#   }
#
# "shapeUvOffset" -- CONFIRMADO num .blockyanim exportado de verdade pelo
# plugin oficial do Blockbench (não é chute): "delta" é só {x, y} (sem z),
# e os valores são PIXELS CRUS dentro do atlas de textura, NÃO uma fração
# de UV normalizada (0..1) -- diferente de como o importer calcula UV de
# repouso (u = px/atlas_w). Por isso o exporter NÃO precisa saber o
# tamanho do atlas pra escrever esse canal.
#
# "delta" é RELATIVO à pose de repouso (bind pose) do bone, não absoluto.
# Confirmado como delta local, não world: a única forma de "delta" bater
# com como o importer constrói a pose de repouso (world = parent_world @
# local, ver hytale_blockymodel_importer.py) é o inverso EXATO disso:
#
#   rest_local  = rest_matrix_do_pai⁻¹  @ rest_matrix_do_bone   (ou a própria
#                 rest_matrix se o bone não tiver pai -- pra bone raiz,
#                 "local" == "armature space", pela mesma razão que no
#                 import: world(raiz) = Identity @ local(raiz))
#   pose_local  = pose_matrix_do_pai⁻¹  @ pose_matrix_do_bone   (idem, com a
#                 matriz JÁ AVALIADA, ou seja, depois de resolver
#                 constraints -- é exatamente o que pose_bone.matrix
#                 devolve)
#   delta_local = rest_local⁻¹ @ pose_local
#
# Isso é o inverso matemático do node_local_matrix() do importer, então
# não precisamos "entender" a cadeia MCH->CTRL manualmente: como as
# constraints (COPY_TRANSFORMS/COPY_LOCATION/COPY_ROTATION etc.) já
# resolvem a pose do bone ORIGINAL automaticamente dentro do Blender,
# pose_bone.matrix do bone original já reflete o resultado final da
# cadeia inteira -- só precisamos ler.
#
# ESCALA: o importer divide todo comprimento por UNIT_SCALE (1/64) ao
# criar o rig. O compileAnimationFile do plugin oficial NÃO aplica
# nenhum fator de escala (grava a posição do jeito que o Blockbench guarda
# internamente, que é em unidades de jogo "cruas"). Por isso, aqui
# multiplicamos de volta por 1/UNIT_SCALE (=64) na hora de exportar --
# operação inversa exata da divisão feita no import.
#
# ROTAÇÃO: o Blockbench guarda rotação como Euler (ordem ZYX) na UI e só
# converte pra quaternion na hora de gravar o arquivo (setFromEuler ->
# quaternion). Aqui exportamos o quaternion do delta DIRETO, sem passar
# por Euler -- matematicamente é o mesmo quaternion final (mesma rotação),
# e evita qualquer risco de flip/gimbal que só existiria se fôssemos nós
# a fazer a ida e volta por Euler.
# ---------------------------------------------------------------------------

# --- Detecção de bones "originais" (os que existem de fato no jogo) ------
#
# Tentativa inicial: filtrar por sufixo de nome (_MCH/_CTRL/_IK). Isso
# falha em rigs reais, que tipicamente têm MUITO mais coisa do que só
# original/MCH/CTRL: pole targets (L-Calf_Pole), bones de controle do
# Rigify (root.master, c_spine_master.x, PROPERTIES), nomes duplicados que
# o Blender renomeia com ".001" etc. -- nenhum desses bate um sufixo fixo,
# e nem deveriam, porque são construções internas do rig, não bones do
# modelo do Hytale.
#
# Solução: em vez de adivinhar pelo nome, o export lê os bones de uma
# BONE COLLECTION explícita (Armature Properties > Bone Collections). Você
# cria uma coleção com esse nome e ARRASTA pra dentro só os bones
# originais (os que têm o mesmo nome exato dos nodes do .blockymodel).
# Isso funciona não importa o que mais existir no rig.
EXPORT_COLLECTION_NAME_DEFAULT = "Hytale Export"
UV_OFFSET_SOURCE_BONE_DEFAULT = "ui.texture_picker"
UV_OFFSET_TARGET_BONE_DEFAULT = ""

# Sufixos de fallback, usados SÓ se a Bone Collection acima não existir na
# armature (pra não travar o export de quem ainda não configurou a
# coleção) -- mesmo assim recomendamos fortemente configurar a coleção.
# Valores agora vêm de common.py (compartilhados com rigger.py, que é
# quem realmente cria os bones com esses sufixos) -- CONTROL_SUFFIXES em
# si continua só de uso local (is_original_bone_name), não é reexportado.
CONTROL_SUFFIXES = (SUFFIX_MCH, SUFFIX_CTRL, SUFFIX_IK)


def is_original_bone_name(name):
    return not any(name.endswith(suf) for suf in CONTROL_SUFFIXES)


# ---------------------------------------------------------------------------
# Configurações de export persistentes na Armature (Object Data) -- "Export
# Bone Collection" NÃO é mais property efêmera do diálogo do operador de
# export: é guardada aqui, no dado da própria Armature, e editada pelo
# painel do interface.py (aba Export), pra não precisar reconfigurar toda
# vez que você abre o diálogo de export.
#
# Registrada aqui (não em interface.py, nem em common.py) seguindo
# EXATAMENTE o mesmo padrão que rigger.py já usa pra hytale_ik_chains:
# quem é DONO da lógica registra o dado direto no tipo Armature;
# interface.py só desenha (igual ele já faz pra hytale_ik_chains, lendo
# armature.hytale_ik_chains sem redefinir nada). Ver DEVELOPER_NOTES.md.
#
# v0.12 -- ERA HYTALE_export_bone_settings, um PointerProperty (valor
# único) que também guardava export_uv_offset/uv_offset_source_bone/
# _target_bone(s_extra)/_step_x/_px_x/_step_y/_px_y -- funcionava pra UMA
# instância de Texture Picker só; rodar "Create Texture Picker" numa
# segunda entrada (chain_type TEXTURE_PICKER) sobrescrevia a calibração
# da primeira sem avisar (bone alvo errado ou conversão de pixel
# calibrada pro tamanho errado no export). Os campos de UV Offset saíram
# daqui e viraram HYTALE_texture_picker_export_item (ver abaixo),
# guardado numa CollectionProperty (armature.hytale_texture_picker_
# exports) -- uma entrada por instância, sem limite. Esta classe (agora
# HYTALE_export_settings) ficou só com o que é DE VERDADE global à
# Armature inteira (a Bone Collection de export -- não faz sentido "por
# instância", só existe UM conjunto de bones exportáveis).
class HYTALE_export_settings(PropertyGroup):
    export_collection_name: StringProperty(
        name="Export Bone Collection",
        description=(
            "Name of the Armature Bone Collection containing only the "
            "'original' game bones to export (Armature Data Properties > "
            "Bone Collections). If this collection doesn't exist on the "
            "armature, falls back to guessing by name suffix "
            "(_MCH/_CTRL/_IK), which is unreliable on complex rigs"
        ),
        default=EXPORT_COLLECTION_NAME_DEFAULT,
    )


# v0.12 -- item da lista armature.hytale_texture_picker_exports (uma
# entrada por instância de Texture Picker configurada no rigger --
# ver DEVELOPER_NOTES.md/prompt_uv_animate.md, ponto 2, "múltiplas
# instâncias independentes"). Cada entrada é totalmente independente:
# seu próprio bone de controle, seu próprio alvo (+ companions), sua
# própria calibração de grid -- exportar uma não interfere na outra.
# 'name' (StringProperty herdada de PropertyGroup, sempre existe)
# guarda o mesmo valor de uv_offset_target_bone, só pra UIList/
# template_list ter algo pra mostrar por padrão sem draw_item custom
# (ver HYTALE_UL_texture_picker_exports abaixo) -- mantida em sincronia
# sempre que uv_offset_target_bone muda (ver RIG_OT_hytale_texture_
# picker_create/_remove em rigger/rig.py, que são quem escreve aqui).
class HYTALE_texture_picker_export_item(PropertyGroup):
    uv_offset_source_bone: StringProperty(
        name="UV Control Bone",
        description=(
            "Name of the helper bone whose Location drives the atlas "
            "picker (e.g. 'ui.texture_picker'). This bone itself is NOT "
            "exported -- only its Location is sampled"
        ),
        default=UV_OFFSET_SOURCE_BONE_DEFAULT,
    )
    uv_offset_target_bone: StringProperty(
        name="Target Bone (shapeUvOffset)",
        description=(
            "Exact name of the real game bone to attach the "
            "'shapeUvOffset' channel to -- must be one of the exportable "
            "bones (e.g. 'Mouth', or any other atlas-driven part)"
        ),
        default=UV_OFFSET_TARGET_BONE_DEFAULT,
    )
    # v0.10.13 -- Companion targets (rigger's "Companion Bones Amount" --
    # HytaleIKChainItem.texture_picker_extra_bone_1..N in rigger/rig.py). Some
    # characters have their animated part (mouth, face, etc.) split across
    # more than one mesh/bone (e.g. mirrored L/R halves meeting in the
    # middle) that need the SAME expression change at the SAME time --
    # this field lets the SAME shapeUvOffset delta be written to more
    # bones besides the primary uv_offset_target_bone. Comma-separated
    # exact bone names (same name-space as uv_offset_target_bone -- raw
    # Blender bone names, matched against the exportable set the same
    # way). A name that isn't exportable is warned and skipped
    # individually -- it does NOT cancel the primary target or the other
    # companions (see sample_action()). Written automatically by 'Create
    # Texture Picker' (rigger/rig.py, _build_texture_picker) from the companion
    # bones configured on that entry -- normally you don't need to type
    # here by hand. Companion Bones stay WITHIN this same instance/entry --
    # they don't need their own list entry, they share this one's
    # calibration (see step_x/px_x/step_y/px_y below).
    uv_offset_target_bones_extra: StringProperty(
        name="Companion Target Bones (shapeUvOffset)",
        description=(
            "Comma-separated extra bone names that receive the exact same 'shapeUvOffset' data as "
            "Target Bone above -- for characters whose animated part is split across more than one "
            "mesh/bone (e.g. mirrored left/right halves) that must change expression together. Usually "
            "filled automatically by 'Create Texture Picker' from the Companion Bones configured on this "
            "entry, not typed here directly"
        ),
        default="",
    )
    # v0.6.5 -- MOVIDOS de EXPORT_OT_hytale_blockyanim pra cá (eram
    # Property de Operator, não persistiam com o arquivo -- resetavam
    # pro default toda vez que o diálogo de export abria, então o
    # Rigger (Texture Picker, "Create Texture Picker") não tinha como
    # pré-preencher isso de verdade). v0.12: junto com o resto desta
    # classe, movidos de novo -- da PointerProperty única (HYTALE_
    # export_bone_settings) pra este item de CollectionProperty, uma
    # calibração própria por instância. Ver sample_action(), que agora
    # itera armature.hytale_texture_picker_exports inteira em vez de ler
    # um conjunto fixo de campos.
    uv_offset_step_x: FloatProperty(
        name="Grid Step X",
        description=(
            "In Blender units: how far the control bone has to move on X "
            "for the mouth/face texture to shift by one step. Must match "
            "whatever your shader/driver setup actually uses -- this "
            "doesn't invent the behavior, it just has to describe it "
            "correctly"
        ),
        default=0.1,
    )
    uv_offset_px_x: FloatProperty(
        name="Pixels per Step X",
        description="How many raw texture pixels one X grid step represents in the file (the game expects raw pixel offsets, not a 0..1 fraction)",
        default=20.0,
    )
    uv_offset_step_y: FloatProperty(
        name="Grid Step Y",
        description="Same as Grid Step X, for the control bone's Y movement",
        default=-0.045,
    )
    uv_offset_px_y: FloatProperty(
        name="Pixels per Step Y",
        description="Same as Pixels per Step X, for Y",
        default=-10.0,
    )


def get_export_settings(armature_obj):
    """Atalho pra armature_obj.data.hytale_export_settings (o painel do
    interface.py lê/escreve o mesmo caminho direto, sem passar por esta
    função -- ela existe só pro lado do exporter.py, que MAIS de um lugar
    neste arquivo precisa ler). Fallback pro próprio default da
    PropertyGroup se, por algum motivo (addon-standalone sem o resto do
    pacote, ordem de registro), a Armature ainda não tiver esse dado --
    nunca trava o export por causa disso.

    v0.12 -- ERA get_export_bone_settings; renomeada porque só devolve
    export_collection_name agora (os campos de UV Offset saíram daqui,
    ver get_texture_picker_exports abaixo)."""
    data = getattr(armature_obj, "data", None)
    settings = getattr(data, "hytale_export_settings", None)
    if settings is None:
        # Instância "solta" (não vinculada a nenhuma Armature real) só
        # pra fornecer os defaults -- nunca é lida/gravada de verdade.
        settings = HYTALE_export_settings()
    return settings


def get_texture_picker_exports(armature_obj):
    """Atalho pra armature_obj.data.hytale_texture_picker_exports (a
    CollectionProperty de HYTALE_texture_picker_export_item -- uma
    entrada por instância de Texture Picker). Devolve uma lista/coleção
    vazia (nunca None) se a Armature ainda não tiver esse dado, mesmo
    espírito de get_export_settings -- chamador não precisa checar None
    antes de iterar."""
    data = getattr(armature_obj, "data", None)
    exports = getattr(data, "hytale_texture_picker_exports", None)
    return exports if exports is not None else []


# ---------------------------------------------------------------------------
# UIList + Add/Remove pra armature.hytale_texture_picker_exports (aba
# Export do interface.py) -- mesmo padrão que RIG_UL_hytale_ik_chains/
# RIG_OT_hytale_ik_chain_add/_remove já usam em rigger/rig.py pra
# hytale_ik_chains: quem é DONO do dado registra o UIList/operadores
# aqui, interface.py só desenha via template_list(). Normalmente esta
# lista é preenchida sozinha por "Create Texture Picker" (rigger/rig.py,
# _build_texture_picker) -- Add/Remove aqui existem pra ajuste manual
# (ex.: apontar uma instância pra um bone/armature externo que não passou
# pelo rigger) e pra sincronizar com "Remove Texture Picker"/"Remove
# Generated Bones" no lado do rigger.
# ---------------------------------------------------------------------------


class HYTALE_UL_texture_picker_exports(bpy.types.UIList):
    bl_idname = "HYTALE_UL_texture_picker_exports"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.uv_offset_target_bone or "(no target bone)", icon="IMAGE_DATA")


class EXPORT_OT_texture_picker_export_add(Operator):
    """Adiciona uma instância vazia à lista (uso manual -- normalmente
    'Create Texture Picker', no rigger, já adiciona/atualiza a entrada
    certa sozinho)."""

    bl_idname = "armature.hytale_texture_picker_export_add"
    bl_label = "Add Texture Picker Export"
    bl_description = "Add a manual Texture Picker export entry to the list"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        armature = context.active_object.data
        exports = armature.hytale_texture_picker_exports
        item = exports.add()
        item.uv_offset_source_bone = UV_OFFSET_SOURCE_BONE_DEFAULT
        armature.hytale_texture_picker_exports_index = len(exports) - 1
        return {"FINISHED"}


class EXPORT_OT_texture_picker_export_remove(Operator):
    """Remove uma instância da lista pelo índice (padrão: a ativa)."""

    bl_idname = "armature.hytale_texture_picker_export_remove"
    bl_label = "Remove Texture Picker Export"
    bl_description = "Remove the selected Texture Picker export entry from the list"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE" and len(obj.data.hytale_texture_picker_exports) > 0

    def execute(self, context):
        armature = context.active_object.data
        exports = armature.hytale_texture_picker_exports
        index = self.index if self.index >= 0 else armature.hytale_texture_picker_exports_index
        if 0 <= index < len(exports):
            exports.remove(index)
            armature.hytale_texture_picker_exports_index = max(0, min(armature.hytale_texture_picker_exports_index, len(exports) - 1))
        return {"FINISHED"}


def exported_bone_name(armature_obj, name):
    """Nome a gravar no arquivo de saída para o bone 'name'. Normalmente é
    o próprio bone.name -- mas se o importer precisou renomear esse bone
    por colisão de nome dentro do mesmo .blockymodel (duas pastas com o
    mesmo nome em galhos diferentes, algo que o Blockbench permite e o
    Blender não), o nome ORIGINAL (sem sufixo .dupNN) fica guardado na
    custom property BONE_ORIGINAL_NAME_PROP -- é esse valor que o jogo
    espera, não o nome interno do Blender. A maioria dos bones não tem
    essa property e cai no fallback (comportamento de sempre)."""
    bone = armature_obj.data.bones.get(name)
    if bone is None:
        return name
    return bone.get(BONE_ORIGINAL_NAME_PROP, name)


def bones_in_collection(armature_obj, collection_name):
    """Nomes dos bones que pertencem à Bone Collection com esse nome.
    Retorna None se a coleção não existir na armature (pra diferenciar de
    'existe mas está vazia')."""
    data = armature_obj.data
    collections = getattr(data, "collections", None)
    if collections is None or collection_name not in collections:
        return None
    coll = collections[collection_name]
    names = set()
    for bone in data.bones:
        if any(c.name == collection_name for c in bone.collections):
            names.add(bone.name)
    return names


def quantize_value(v, step):
    if step <= 0.0:
        return v
    return round(v / step) * step


def quantize_vector(v, step):
    if step <= 0.0:
        return v
    return Vector((quantize_value(v.x, step), quantize_value(v.y, step), quantize_value(v.z, step)))


def quantize_quaternion(q, step):
    """Arredonda cada componente pra um grid fixo e renormaliza -- suprime
    ruído de ponto flutuante que sobra em cima de rotação real, sem
    depender de a rotação ser (perto de) identidade."""
    if step <= 0.0:
        return q
    qq = Quaternion((
        quantize_value(q.w, step),
        quantize_value(q.x, step),
        quantize_value(q.y, step),
        quantize_value(q.z, step),
    ))
    if qq.magnitude < 1e-8:
        return q
    qq.normalize()
    return qq


def sample_uv_offset_px(control_pbone, opts):
    """Lê a Location (pose, local) do bone de controle (ex.: 'ui.texture_picker')
    e reproduz em Python a MESMA matemática de snap-to-grid que o driver do
    Mapping node do usuário já faz no shader -- só que devolvendo pixels
    crus (o que o .blockyanim espera pro shapeUvOffset), não a fração de UV
    que o driver usa internamente pro shader. 'round()' aqui é o Python
    nativo, mesma matemática que o 'round()' disponível nas expressões de
    Driver do Blender.

    Devolve INTEIROS (não float): confirmado que o parser do jogo lê
    'shapeUvOffset[].delta.x/y' como Int32 -- um float aqui (mesmo um
    valor "redondo" tipo 32.0, que o json.dump ainda escreve como
    "32.0") quebra a leitura do arquivo no jogo (erro reportado:
    "The JSON value could not be converted to System.Int32" apontando
    pra esse path exato). Isso é diferente de position/orientation/
    shapeStretch, que continuam genuinamente float -- só o UV do atlas é
    inteiro por natureza (pixel cru), então essa conversão fica isolada
    aqui, não em round_floats_for_output (que é genérico pros outros
    canais)."""
    loc = control_pbone.location
    step_x = opts.uv_offset_step_x
    step_y = opts.uv_offset_step_y
    px_x = round(loc.x / step_x) * opts.uv_offset_px_x if step_x != 0 else 0.0
    px_y = round(loc.y / step_y) * opts.uv_offset_px_y if step_y != 0 else 0.0
    # int(round(...)) em vez de int(...) puro: já vem "redondo" da
    # matemática de snap-to-grid acima, mas passar por round() de novo
    # evita truncar errado por ruído de ponto flutuante (ex.: 31.999999
    # virando 31 em vez de 32).
    return int(round(px_x)), int(round(px_y))


# ---------------------------------------------------------------------------
# Correção de sinal de quaternion (dupla cobertura) + redução de keyframes
# por Ramer-Douglas-Peucker (RDP). Duas melhorias relacionadas: RDP usa
# slerp como referência pra decidir o que descartar, e slerp só anda pelo
# caminho CURTO na esfera se os sinais forem consistentes -- por isso o
# sign-fix tem que rodar ANTES da redução (não depois, e não seria útil
# aplicado separadamente).
# ---------------------------------------------------------------------------


def fix_quaternion_sign(quat, prev_quat):
    """Quaternions têm dupla cobertura: q e -q representam exatamente a
    mesma rotação. Mas se o sinal 'vira' de um frame amostrado pro outro
    sem nenhum motivo geométrico (o que acontece livremente, já que cada
    frame deriva o quaternion de uma matriz de forma independente, sem
    continuidade garantida), duas coisas quebram: (1) o slerp no jogo
    interpola pelo caminho LONGO ao redor da esfera em vez do curto,
    produzindo um 'chacoalhão' visual mesmo a rotação matematicamente
    batendo em cada keyframe individual; (2) qualquer cálculo de distância
    entre quaternions consecutivos (dot product) fica errado, incluindo o
    da redução por RDP logo abaixo. Corrige escolhendo, a cada frame, o
    sinal mais próximo do frame anterior (via dot product); no primeiro
    frame de cada bone (prev_quat is None) canoniza pra w >= 0, só pra ter
    um ponto de partida determinístico."""
    if prev_quat is None:
        if quat.w < 0:
            return Quaternion((-quat.w, -quat.x, -quat.y, -quat.z))
        return quat
    if quat.dot(prev_quat) < 0:
        return Quaternion((-quat.w, -quat.x, -quat.y, -quat.z))
    return quat


def _rdp_distance_vec(t, v, t0, v0, tn, vn):
    """Distância (unidades de jogo) entre o valor REALMENTE amostrado em
    't' e o valor que uma interpolação linear simples entre os dois
    pontos-âncora (t0,v0) e (tn,vn) preveria pra esse mesmo instante --
    não é distância ponto-reta no espaço 3D pura, é 'o quanto o sample
    real se desvia de uma reta na CURVA AO LONGO DO TEMPO', que é o que
    keyframe redution quer preservar."""
    if tn == t0:
        return (v - v0).length
    frac = (t - t0) / (tn - t0)
    return (v - v0.lerp(vn, frac)).length


def _rdp_distance_quat(t, q, t0, q0, tn, qn):
    """Mesma ideia que _rdp_distance_vec, mas pra rotação: a 'reta' de
    referência é um slerp entre os dois quaternions-âncora (só funciona
    corretamente com sinais já consistentes -- ver fix_quaternion_sign), e
    a distância usa a MESMA métrica de produto escalar que
    'rotation_epsilon'/'rotation_zero_epsilon' já usam em todo o resto do
    arquivo, pra manter a mesma escala/intuição de tolerância."""
    if tn == t0:
        return 0.0
    frac = (t - t0) / (tn - t0)
    ref = q0.slerp(qn, frac)
    return abs(abs(q.dot(ref)) - 1.0)


def rdp_reduce_indices(samples, epsilon, distance_fn):
    """Ramer-Douglas-Peucker, versão ITERATIVA (pilha explícita, não
    recursão -- animações bakeadas longas podem ter profundidade de
    recursão patológica e estourar o limite do Python, então evitamos
    recursão de propósito). 'samples' é uma lista [(tempo, valor), ...]
    JÁ ORDENADA por tempo. Devolve o SET de índices (relativos a
    'samples') que devem ser mantidos como keyframe -- os extremos (0 e
    len-1) sempre entram.

    Diferença chave pro método antigo (comparar cada frame só com o
    ÚLTIMO FRAME ESCRITO): RDP olha o segmento INTEIRO entre dois pontos-
    âncora de cada vez, então um trecho longo e quase-linear (muitos
    frames intermediários) colapsa pra só os dois extremos de uma vez,
    mesmo que a soma de pequenos desvios frame-a-frame tivesse escapado
    de um epsilon local. Resultado: arquivos menores com a mesma
    fidelidade visual, principalmente em eases/curvas suaves com muitos
    frames amostrados no meio."""
    n = len(samples)
    if n == 0:
        return set()
    if n < 3:
        return set(range(n))

    keep = {0, n - 1}
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        t0, v0 = samples[start]
        tn, vn = samples[end]
        max_dist = -1.0
        max_idx = -1
        for i in range(start + 1, end):
            ti, vi = samples[i]
            d = distance_fn(ti, vi, t0, v0, tn, vn)
            if d > max_dist:
                max_dist = d
                max_idx = i
        if max_dist > epsilon:
            keep.add(max_idx)
            stack.append((start, max_idx))
            stack.append((max_idx, end))
    return keep


# Janela (em frames, unidades de hytale_time) pra considerar dois pontos
# significativos de BONES DIFERENTES como o mesmo 'evento' de troca de
# pose. Não é exposta na UI de propósito -- ver sync_nearby_keyframes().
SYNC_WINDOW_FRAMES = 3


def sync_nearby_keyframes(keep_by_bone, frame_times):
    """RDP roda por bone de forma independente, então bones diferentes
    podem escolher manter keyframes em tempos DIFERENTES pra descrever a
    MESMA troca de pose (torso reduzido a uma reta larga enquanto um
    braço mantém frames densos por um movimento rápido, por exemplo) --
    cada canal fica individualmente correto, mas o descompasso de tempo
    entre bones pode aparecer como tremedeira visual.

    Em vez de sincronizar TUDO contra TUDO na timeline inteira (testado:
    isso incha o arquivo várias vezes de tamanho, inclusive sincronizando
    bones que não têm nada a ver um com o outro num dado momento), aqui
    só juntamos pontos de bones DIFERENTES que já caem PRÓXIMOS no tempo
    entre si (dentro de SYNC_WINDOW_FRAMES) -- ou seja, só quando parece
    ser genuinamente o mesmo evento de pose acontecendo em mais de um
    bone ao mesmo tempo. Um bone com um movimento isolado, longe de
    qualquer outro evento, não é afetado e não ganha keyframes extras.

    'keep_by_bone': dict nome -> set de índices (já calculado por
    rdp_reduce_indices, pra UM tipo de canal). 'frame_times': lista de
    hytale_time por índice (a mesma pra todo bone, já que todos amostram
    exatamente os mesmos frames). Devolve um NOVO dict com os keep-sets
    expandidos onde necessário."""
    n = len(frame_times)

    # Extremos (0 e n-1) sempre estão em TODO bone -- não representam
    # 'eventos' de transição, e incluí-los aqui faria todo bone virar um
    # único cluster gigante através deles. Só agrupamos os pontos do
    # MEIO.
    events = sorted(
        (frame_times[i], name, i)
        for name, idxs in keep_by_bone.items()
        for i in idxs
        if 0 < i < n - 1
    )
    if not events:
        return keep_by_bone

    clusters = []
    current = [events[0]]
    for ev in events[1:]:
        if ev[0] - current[-1][0] <= SYNC_WINDOW_FRAMES:
            current.append(ev)
        else:
            clusters.append(current)
            current = [ev]
    clusters.append(current)

    result = {name: set(idxs) for name, idxs in keep_by_bone.items()}
    for cluster in clusters:
        bones_here = {name for _, name, _ in cluster}
        if len(bones_here) < 2:
            continue  # só um bone envolvido -- nada pra sincronizar
        indices_here = {i for _, _, i in cluster}
        for name in bones_here:
            result[name] |= indices_here
    return result


def local_matrix(matrix_by_bone, bone_name, parent_name):
    """Matriz relativa ao pai, dado um dict {nome: matriz em armature-space}.
    Bone sem pai: 'local' == 'armature space' (mesma convenção do import)."""
    m = matrix_by_bone[bone_name]
    if parent_name is None:
        return m
    return matrix_by_bone[parent_name].inverted() @ m


def rest_matrices(armature_obj):
    """Matriz de repouso (armature-space) de cada bone, a partir de
    Bone.matrix_local (não muda com a pose atual, não precisa de Edit Mode)."""
    out = {}
    for bone in armature_obj.data.bones:
        out[bone.name] = bone.matrix_local.copy()
    return out


def pose_matrices(armature_obj):
    """Matriz da pose ATUAL (já avaliada, pós-constraints), armature-space,
    de cada pose bone. Precisa ser chamado DEPOIS de scene.frame_set() +
    depsgraph atualizado."""
    out = {}
    for pbone in armature_obj.pose.bones:
        out[pbone.name] = pbone.matrix.copy()
    return out


def rest_local_positions(armature_obj, rest_by_bone, exportable_names, unit_scale):
    """v0.10.19 -- posição LOCAL (relativa ao pai) de cada bone exportável
    NA POSE DE REPOUSO (rest/bind pose), em unidades de jogo -- não muda
    entre frames (repouso é fixo), calculada uma vez só ANTES do loop de
    frames (diferente de compute_deltas, que roda todo frame). Usada só
    por Bake Parent Scale into Children (ver sample_action()), pra saber o
    quanto "puxar" o pivot de cada filho em direção ao pivot do pai quando
    o pai encolhe/cresce -- sem isso, o filho encolhe no PRÓPRIO lugar em
    vez de se aproximar/afastar do pai, ficando com aparência errada
    (gap/sobreposição) mesmo com o tamanho certo."""
    inv_scale = 1.0 / unit_scale
    out = {}
    for pbone in armature_obj.pose.bones:
        name = pbone.name
        if name not in exportable_names:
            continue
        parent_name = pbone.parent.name if pbone.parent else None
        rest_local = local_matrix(rest_by_bone, name, parent_name)
        out[name] = rest_local.to_translation() * inv_scale
    return out


def compute_deltas(armature_obj, rest_by_bone, pose_by_bone, exportable_names, unit_scale):
    """Para cada bone exportável, calcula (posição delta em unidades de
    jogo, quaternion delta, escala delta) na pose ATUAL vs repouso."""
    results = {}
    inv_scale = 1.0 / unit_scale
    for pbone in armature_obj.pose.bones:
        name = pbone.name
        if name not in exportable_names:
            continue
        parent_name = pbone.parent.name if pbone.parent else None

        rest_local = local_matrix(rest_by_bone, name, parent_name)
        pose_local = local_matrix(pose_by_bone, name, parent_name)

        delta = rest_local.inverted() @ pose_local
        pos, quat, scale = delta.decompose()

        results[name] = (pos * inv_scale, quat, scale)
    return results


# ---------------------------------------------------------------------------
# Amostragem de frames
# ---------------------------------------------------------------------------


def collect_all_keyframe_frames(action, frame_start, frame_end):
    """Modo 'preservar keyframes': junta os frames de TODO fcurve da Action
    inteira (qualquer bone, qualquer canal -- CTRL, IK, pole targets, MCH
    manualmente chaveado, o que for), dentro do range escolhido.

    Deliberadamente não tentamos adivinhar qual bone de controle anima qual
    bone original por convenção de nome -- seria frágil (pole targets, por
    exemplo, raramente seguem o padrão 'NomeOriginal_ALGO'). Em vez disso,
    qualquer frame onde QUALQUER coisa no rig tem um keyframe vira um ponto
    de amostragem pra TODOS os bones originais. Isso é uma simplificação:
    se você chavear controladores diferentes em frames diferentes (em vez
    de posar tudo junto), essa união ainda cobre certo, só que pode gerar
    alguns keyframes "redundantes" em bones que não mudaram naquele frame
    específico -- inofensivo, só deixa o arquivo um pouco maior."""
    frames = set()
    if action is None:
        return frames
    for fcurve in action.fcurves:
        for kp in fcurve.keyframe_points:
            f = kp.co.x
            if frame_start <= f <= frame_end:
                frames.add(round(f))
    return frames


def frame_to_hytale_time(frame, frame_start, fps):
    """Frame da timeline do Blender -> 'time' do .blockyanim (frame inteiro
    a 60 FPS, relativo ao INÍCIO do range exportado, ou seja o primeiro
    frame exportado sempre vira time=0)."""
    seconds = (frame - frame_start) / fps
    return round(seconds * FPS_HYTALE)


def sanitize_filename(name):
    """Nomes de Action podem ter caracteres inválidos em nome de arquivo
    (: / \\ etc) -- troca por '_'."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    return cleaned or "animation"


def round_floats_for_output(obj, decimals):
    """Arredonda todo float da estrutura pra um número fixo de casas
    decimais, recursivamente. Só cosmético pra tamanho de arquivo -- NÃO
    remove nenhum keyframe, só encurta a representação em texto de cada
    número (evita algo tipo 0.30000000000000004 quando o valor real já foi
    quantizado/arredondado antes)."""
    if isinstance(obj, float):
        return round(obj, decimals)
    if isinstance(obj, dict):
        return {k: round_floats_for_output(v, decimals) for k, v in obj.items()}
    if isinstance(obj, list):
        return [round_floats_for_output(v, decimals) for v in obj]
    return obj


def _is_flat_dict(d):
    """True se 'd' só tem valores escalares (nada de dict/list dentro) --
    o caso de 'delta':{x,y,z,w} ou {x,y}. Usado por dump_pretty_blockyanim
    pra decidir o que colapsa numa linha só."""
    return isinstance(d, dict) and all(not isinstance(v, (dict, list)) for v in d.values())


def dump_pretty_blockyanim(content, indent=2):
    """Serializador PRÓPRIO pro modo Pretty Print (opts.pretty_print_json)
    -- NÃO usa json.dump(indent=2) puro. Motivo: o indent do Python expande
    QUALQUER dict aninhado recursivamente, uma linha por campo -- inclusive
    coisas tipo 'delta':{x,y,z,w}, que o Blockbench mantém numa linha só.
    Sem isso, o arquivo pretty-print sai bem maior que o do Blockbench
    (cada keyframe ganha ~5 linhas extras só pro 'delta'/'scale'), o que é
    exatamente a causa do arquivo pretty-print ter saído mais pesado que o
    reexport do Blockbench.

    Regra: qualquer dict cujos valores sejam TODOS escalares vira uma
    linha só (delta, scale etc.); dicts/listas com estrutura de verdade
    (arrays de keyframes, canais, nodeAnimations) continuam multi-linha,
    exatamente como um json.dump(indent=2) normal faria."""

    def encode(o, level):
        pad = " " * (indent * level)
        pad_in = " " * (indent * (level + 1))
        if isinstance(o, dict):
            if not o:
                return "{}"
            if _is_flat_dict(o):
                items = ", ".join(f"{json.dumps(k)}: {json.dumps(v)}" for k, v in o.items())
                return "{" + items + "}"
            lines = [f"{pad_in}{json.dumps(k)}: {encode(v, level + 1)}" for k, v in o.items()]
            return "{\n" + ",\n".join(lines) + "\n" + pad + "}"
        if isinstance(o, list):
            if not o:
                return "[]"
            lines = [f"{pad_in}{encode(v, level + 1)}" for v in o]
            return "[\n" + ",\n".join(lines) + "\n" + pad + "]"
        return json.dumps(o)

    return encode(content, 0)


# ---------------------------------------------------------------------------
# Amostragem de UMA Action -> node_animations. Extraído em função separada
# pra ser reaproveitado uma vez por Action marcada no export em lote.
# ---------------------------------------------------------------------------


def sample_action(context, obj, action, exportable_names, rest_by_bone, rest_local_pos, opts):
    """'opts' é o próprio operador (self) -- só lemos as Properties dele.
    Assume que obj.animation_data.action já foi setado pra 'action' antes
    de chamar. 'rest_local_pos' -- ver rest_local_positions(), só usado
    quando opts.bake_scale_hierarchy está ligado. Devolve (node_animations,
    frame_start, frame_end, fps)."""
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base

    frame_start = int(round(action.frame_range[0]))
    frame_end = int(round(action.frame_range[1]))
    if frame_end <= frame_start:
        frame_end = frame_start + 1

    if opts.bake_animation:
        frames = list(range(frame_start, frame_end + 1, opts.frame_step))
        if frames[-1] != frame_end:
            frames.append(frame_end)
        # Bake = dado denso, frame a frame -- 'smooth' (spline) por cima
        # disso só amplifica ruído sub-visível em vez de suavizar nada
        # (a curva já ESTÁ na resolução máxima). Por isso não é nem opção
        # aqui: é sempre 'linear' quando Bake Animation está ligado.
        interp = "linear"
    else:
        frames = sorted(collect_all_keyframe_frames(action, frame_start, frame_end))
        if opts.force_start_end_keying:
            frames = sorted(set(frames) | {frame_start, frame_end})
        if not frames:
            frames = [frame_start, frame_end]
        interp = opts.preserved_interpolation

    node_animations = {
        name: {
            "position": [],
            "orientation": [],
            "shapeStretch": [],
            # Sempre presentes (mesmo vazios) nos arquivos oficiais da
            # Hytale -- confirmado comparando com uma animação oficial
            # (Sit.blockyanim). "shapeVisible" nunca é populado (não temos
            # equivalente de visibilidade animada no pipeline do Blender),
            # mas o campo TEM que existir, mesmo vazio -- a ausência total
            # da chave é a suspeita mais forte pro import falhar dentro do
            # próprio jogo (o parser do Blockbench é tolerante a isso, o
            # do jogo pode não ser). "shapeUvOffset" É populado se este
            # bone for alvo de alguma entrada em hytale_texture_picker_
            # exports (ver sample_uv_offset_px, e o setup de uv_entries
            # logo abaixo).
            "shapeVisible": [],
            "shapeUvOffset": [],
        }
        for name in exportable_names
    }
    # Amostras acumuladas por bone/canal ANTES de qualquer redução -- RDP
    # precisa enxergar a curva inteira entre dois pontos-âncora pra decidir
    # o que descartar, então não dá pra escrever direto em node_animations
    # dentro do loop de frames como antes (isso só permitia comparar cada
    # frame com o último ESCRITO, que é o método mais fraco).
    pos_samples = {name: [] for name in exportable_names}
    quat_samples = {name: [] for name in exportable_names}
    scale_samples = {name: [] for name in exportable_names}

    last_raw_quat = {}
    zero_vec = Vector((0.0, 0.0, 0.0))
    identity_scale = Vector((1.0, 1.0, 1.0))
    identity_quat = Quaternion((1.0, 0.0, 0.0, 0.0))

    # v0.12 -- itera armature.hytale_texture_picker_exports inteira (uma
    # entrada por instância de Texture Picker, ver HYTALE_texture_picker_
    # export_item em cima) em vez de ler um conjunto fixo de campos de uma
    # PointerProperty única -- cada instância é resolvida/validada aqui
    # UMA vez (fora do loop de frames), com seu próprio control bone,
    # lista de target bones (principal + companions) e estado de dedupe
    # ("last_sampled"), pra várias instâncias independentes exportarem no
    # mesmo arquivo sem pisar uma na outra. Uma entrada com problema
    # (bone de controle ou alvo principal não encontrado) é avisada e
    # PULADA -- não cancela as outras entradas da lista.
    #
    # opts.export_texture_picker (checkbox por exportação, não persiste
    # com o arquivo -- ver EXPORT_OT_hytale_blockyanim.draw()): lista
    # VAZIA aqui, sem nem entrar no loop, se estiver desligado -- desliga
    # 'shapeUvOffset' pra ESTA exportação sem apagar nenhuma instância
    # configurada (as instâncias em si continuam salvas na Armature).
    uv_entries = []
    for uv_item in get_texture_picker_exports(obj) if opts.export_texture_picker else ():
        control_pbone = obj.pose.bones.get(uv_item.uv_offset_source_bone)
        if control_pbone is None:
            opts.report(
                {"WARNING"},
                f"Texture Picker: bone de controle '{uv_item.uv_offset_source_bone}' não "
                f"encontrado no Armature -- pulando esta instância (alvo "
                f"'{uv_item.uv_offset_target_bone}') na Action '{action.name}'.",
            )
            continue
        if uv_item.uv_offset_target_bone not in node_animations:
            opts.report(
                {"WARNING"},
                f"Texture Picker: bone alvo '{uv_item.uv_offset_target_bone}' não está "
                f"entre os bones exportáveis -- pulando esta instância na Action "
                f"'{action.name}'.",
            )
            continue
        # v0.10.13 -- Companion targets: mesmo delta gravado em mais de um
        # bone dentro da MESMA instância (ver comentário grande em
        # HYTALE_texture_picker_export_item.uv_offset_target_bones_extra).
        # Nome que não é exportável é avisado e IGNORADO individualmente --
        # não cancela o alvo principal nem os outros companions DESTA
        # instância (diferente do alvo principal, cuja ausência cancela a
        # instância inteira, ver acima).
        target_bones = [uv_item.uv_offset_target_bone]
        for extra_name in (uv_item.uv_offset_target_bones_extra or "").split(","):
            extra_name = extra_name.strip()
            if not extra_name or extra_name in target_bones:
                continue  # vazio, ou duplicado do principal/de outro companion já aceito
            if extra_name not in node_animations:
                opts.report(
                    {"WARNING"},
                    f"Texture Picker: bone extra '{extra_name}' não está entre os bones "
                    f"exportáveis -- pulando esse alvo (os outros continuam) na Action "
                    f"'{action.name}'.",
                )
                continue
            target_bones.append(extra_name)
        uv_entries.append({
            "control_pbone": control_pbone,
            "target_bones": target_bones,
            "settings": uv_item,  # sample_uv_offset_px só lê step_x/px_x/step_y/px_y -- o item já tem esses 4 campos
            "last_sampled": None,  # dedupe é POR INSTÂNCIA agora -- cada uma tem seu próprio último valor amostrado
        })

    for frame in frames:
        is_edge_frame = frame == frames[0] or frame == frames[-1]

        scene.frame_set(frame)
        context.view_layer.update()

        pose_by_bone = pose_matrices(obj)
        deltas = compute_deltas(obj, rest_by_bone, pose_by_bone, exportable_names, opts.unit_scale)
        hytale_time = frame_to_hytale_time(frame, frame_start, fps)

        # v0.10.18 -- Bake Parent Scale into Children: calcula, pra este
        # frame, o scale "em cascata" de cada bone (produto do próprio
        # scale LOCAL -- já em `deltas` -- com o de TODOS os ancestrais
        # exportáveis, subindo a hierarquia). Memoizado num dict só deste
        # frame (cascaded_scale_cache) -- cada bone calculado uma vez só,
        # mesmo se vários irmãos compartilharem o mesmo ancestral. Só
        # existe se o toggle estiver ligado -- custo zero quando desligado.
        cascaded_scale_cache = {}

        def _cascaded_scale(bone_name):
            if bone_name in cascaded_scale_cache:
                return cascaded_scale_cache[bone_name]
            own_scale = deltas[bone_name][2] if bone_name in deltas else Vector((1.0, 1.0, 1.0))
            pbone = obj.pose.bones.get(bone_name)
            if pbone is not None and pbone.parent is not None and pbone.parent.name in exportable_names:
                parent_scale = _cascaded_scale(pbone.parent.name)
                result = Vector((
                    own_scale.x * parent_scale.x,
                    own_scale.y * parent_scale.y,
                    own_scale.z * parent_scale.z,
                ))
            else:
                result = own_scale
            cascaded_scale_cache[bone_name] = result
            return result

        for name, (pos, quat, scale) in deltas.items():
            # Correção de sinal (dupla cobertura, q == -q) -- ANTES de
            # quantizar e ANTES de acumular pra RDP, pra continuidade
            # correta nos dois. Ver fix_quaternion_sign().
            quat = fix_quaternion_sign(quat, last_raw_quat.get(name))
            last_raw_quat[name] = quat

            # v0.10.19 -- também exige opts.export_scale, não só o próprio
            # toggle: a UI deixa "Bake Parent Scale into Children" cinza/
            # travado quando "Export Scale" está desligado, mas isso só
            # bloqueia interação, não reseta o VALOR guardado -- sem essa
            # checagem aqui, um usuário que ligou o Bake e depois desligou
            # o Export Scale (deixando o Bake True por baixo) exportaria
            # a POSIÇÃO dos filhos corrigida como se o pai tivesse
            # encolhido, mas o shapeStretch do PRÓPRIO pai nunca sairia no
            # arquivo -- o pai renderiza no tamanho normal, os filhos
            # ficam deslocados como se ele tivesse encolhido. Sem sentido
            # bakear posição em cima de uma escala que nem vai existir no
            # export.
            if opts.bake_scale_hierarchy and opts.export_scale:
                scale = _cascaded_scale(name)
                # v0.10.19 -- corrige o PIVOT do filho junto com o tamanho
                # (ver rest_local_positions() e a descrição do campo
                # bake_scale_hierarchy pro motivo -- sem isso, o filho
                # encolhe no PRÓPRIO lugar em vez de se aproximar/afastar
                # do pivot do pai, causando gap/sobreposição visual mesmo
                # com o tamanho certo). Fórmula (por eixo): nova_posição =
                # posição_de_repouso * (escala_do_pai - 1) + posição_
                # própria_atual * escala_do_pai -- reconstrói o que a
                # composição de matriz de verdade faria (child_world =
                # parent_world @ child_local), já que Hytale NÃO faz essa
                # composição sozinho (ver teste ao vivo do usuário: pai
                # escalado não move os filhos no Blockbench).
                pbone_current = obj.pose.bones.get(name)
                if pbone_current is not None and pbone_current.parent is not None \
                        and pbone_current.parent.name in exportable_names:
                    parent_scale = _cascaded_scale(pbone_current.parent.name)
                    rest_pos = rest_local_pos.get(name, Vector((0.0, 0.0, 0.0)))
                    pos = Vector((
                        rest_pos.x * (parent_scale.x - 1.0) + pos.x * parent_scale.x,
                        rest_pos.y * (parent_scale.y - 1.0) + pos.y * parent_scale.y,
                        rest_pos.z * (parent_scale.z - 1.0) + pos.z * parent_scale.z,
                    ))

            if opts.quantize_values:
                pos = quantize_vector(pos, opts.position_quantize_step)
                quat = quantize_quaternion(quat, opts.rotation_quantize_step)
                scale = quantize_vector(scale, opts.scale_quantize_step)

            # NÃO zeramos aqui (frame a frame) -- ver o comentário grande
            # logo após este loop ("Noise floor: canal inteiro, não frame a
            # frame"). Zerar um frame isolado quando ele calha de estar
            # perto da identidade não distingue ruído estático real de uma
            # ease genuína que só COMEÇA perto de zero, e produzia um pulo
            # visual bem no início dela (bug corrigido).

            pos_samples[name].append((hytale_time, pos))
            quat_samples[name].append((hytale_time, quat))
            if opts.export_scale:
                scale_samples[name].append((hytale_time, scale))

        # v0.12 -- itera TODAS as instâncias resolvidas (uv_entries, ver
        # setup acima) -- cada uma lê seu PRÓPRIO control_pbone e escreve
        # no(s) seu(s) PRÓPRIO(s) target_bones, com dedupe independente
        # (uv_entry["last_sampled"]) por instância. Antes (v0.11 e antes)
        # só existia UMA instância possível por armature, então isso era
        # um bloco único fora de loop -- ver DEVELOPER_NOTES.md.
        for uv_entry in uv_entries:
            # v0.6.5 -- 'settings' (não 'opts'/self do Operator): os 4
            # campos de calibração moraram no Operator antes, depois
            # numa PointerProperty única na Armature; agora moram no
            # item da CollectionProperty desta instância -- ver
            # HYTALE_texture_picker_export_item.
            px_x, px_y = sample_uv_offset_px(uv_entry["control_pbone"], uv_entry["settings"])

            # Dedupe por igualdade EXATA (não por epsilon/RDP) -- o valor
            # já é discreto (snap-to-grid), então dois frames iguais em
            # sequência são 100% redundantes, nunca uma transição lenta
            # real sendo cortada. RDP assume uma curva contínua
            # interpolável (lerp/slerp) entre âncoras, o que não faz
            # sentido pra um offset de atlas em degraus -- por isso esse
            # canal continua com seu próprio dedupe simples, independente.
            #
            # v0.10.13 -- dedupe é UM valor só por instância (não por bone
            # alvo dentro dela): todo bone em target_bones desta instância
            # lê do MESMO control_pbone, então o valor amostrado é
            # idêntico pra todos no mesmo frame -- se não mudou pro
            # principal, não mudou pra nenhum companion dele também, não
            # faz sentido rastrear por bone. v0.12: o dedupe em si passou
            # a viver DENTRO do dict de cada uv_entry (uv_entry[
            # "last_sampled"]) em vez de um dict global só -- cada
            # instância tem sua própria "última amostra", senão a
            # instância B "roubaria" o dedupe da instância A no mesmo
            # frame (bug ficaria: mudar só a boca não escreveria o
            # primeiro frame da mão se os dois valores calharem iguais).
            write_uv = True
            if not is_edge_frame and uv_entry["last_sampled"] == (px_x, px_y):
                write_uv = False
            uv_entry["last_sampled"] = (px_x, px_y)
            if write_uv:
                for target_name in uv_entry["target_bones"]:
                    node_animations[target_name]["shapeUvOffset"].append(
                        {
                            "time": hytale_time,
                            "delta": {"x": px_x, "y": px_y},
                            "interpolationType": interp,
                        }
                    )

    # -----------------------------------------------------------------
    # Noise floor: canal inteiro, não frame a frame.
    #
    # BUG HISTÓRICO (corrigido aqui): a versão anterior aplicava
    # position_zero_epsilon/scale_zero_epsilon/rotation_zero_epsilon
    # dentro do loop de frames, testando CADA AMOSTRA isoladamente contra
    # a identidade. Isso funciona bem pro caso que motivou
    # rotation_zero_epsilon (ruído de IK: um desvio praticamente
    # CONSTANTE, presente em TODOS os frames, tipicamente idêntico ou
    # quase idêntico do primeiro ao último) -- mas quebra qualquer ease
    # genuína cujos primeiros frames comecem, por natureza, bem perto de
    # zero/identidade: esses frames iniciais eram zerados à força, e o
    # frame em que o movimento real finalmente ultrapassava o epsilon
    # "aparecia" sem transição -- exatamente o soco/tremedeira visto no
    # começo de algumas animações.
    #
    # A distinção que realmente importa: "esse canal NUNCA sai da
    # vizinhança da identidade em NENHUM frame amostrado" (ruído estático
    # de verdade, o canal inteiro é lixo e pode virar identidade) é bem
    # diferente de "esse frame específico calha de estar perto da
    # identidade" (pode ser só o início de um movimento real). Por isso a
    # checagem roda aqui, depois de já termos TODAS as amostras do bone
    # pra esse canal -- só zeramos o canal inteiro (todo frame, não só
    # alguns) se ELE NUNCA, em nenhum ponto da animação, sair do epsilon.
    # Caso contrário, nenhum frame é tocado -- inclusive os que
    # isoladamente estariam "perto o suficiente" de zero.
    for name in exportable_names:
        samples_p = pos_samples[name]
        if samples_p and all(v.length < opts.position_zero_epsilon for _, v in samples_p):
            pos_samples[name] = [(t, zero_vec) for t, _ in samples_p]

        samples_s = scale_samples[name]
        if samples_s and all((v - identity_scale).length < opts.scale_zero_epsilon for _, v in samples_s):
            scale_samples[name] = [(t, identity_scale) for t, _ in samples_s]

        samples_q = quat_samples[name]
        if samples_q and all(
            abs(abs(q.dot(identity_quat)) - 1.0) < opts.rotation_zero_epsilon for _, q in samples_q
        ):
            quat_samples[name] = [(t, identity_quat) for t, _ in samples_q]

    # Redução de keyframes (RDP) + escrita final de position/orientation/
    # shapeStretch. Quando 'skip_redundant_frames' está desligado, mantém
    # TODAS as amostras (mesmo comportamento de sempre, sem redução).
    if opts.skip_redundant_frames:
        keep_p_by_bone = {
            name: rdp_reduce_indices(pos_samples[name], opts.position_epsilon, _rdp_distance_vec)
            for name in exportable_names
        }
        keep_q_by_bone = {
            name: rdp_reduce_indices(quat_samples[name], opts.rotation_epsilon, _rdp_distance_quat)
            for name in exportable_names
        }
        keep_s_by_bone = {
            name: rdp_reduce_indices(scale_samples[name], opts.position_epsilon, _rdp_distance_vec)
            for name in exportable_names
        }

        # Sempre ativo (sem opção separada pra lembrar) -- sincroniza só
        # os bones cujos pontos significativos já caem próximos no tempo
        # entre si (mesmo evento de troca de pose). Ver
        # sync_nearby_keyframes() pra por que não sincronizamos TUDO
        # contra TUDO na timeline inteira (custo de arquivo alto demais
        # pra ser padrão).
        frame_times = [t for t, _ in next(iter(pos_samples.values()))] if pos_samples else []
        if frame_times:
            keep_p_by_bone = sync_nearby_keyframes(keep_p_by_bone, frame_times)
            keep_q_by_bone = sync_nearby_keyframes(keep_q_by_bone, frame_times)
            keep_s_by_bone = sync_nearby_keyframes(keep_s_by_bone, frame_times)

        keep_by_bone = {
            name: (keep_p_by_bone[name], keep_q_by_bone[name], keep_s_by_bone[name])
            for name in exportable_names
        }
    else:
        keep_by_bone = {
            name: (
                range(len(pos_samples[name])),
                range(len(quat_samples[name])),
                range(len(scale_samples[name])),
            )
            for name in exportable_names
        }

    for name in exportable_names:
        samples_p = pos_samples[name]
        samples_q = quat_samples[name]
        samples_s = scale_samples[name]
        keep_p, keep_q, keep_s = keep_by_bone[name]

        for i in sorted(keep_p):
            t, pos = samples_p[i]
            node_animations[name]["position"].append(
                {"time": t, "delta": vec_to_dict(pos), "interpolationType": interp}
            )
        for i in sorted(keep_q):
            t, quat = samples_q[i]
            node_animations[name]["orientation"].append(
                {"time": t, "delta": quat_to_dict(quat), "interpolationType": interp}
            )
        for i in sorted(keep_s):
            t, scale = samples_s[i]
            node_animations[name]["shapeStretch"].append(
                {"time": t, "delta": vec_to_dict(scale), "interpolationType": interp}
            )

    # Limpeza: canal todo-zero (posição), todo-identidade (rotação/escala)
    # vira array vazio; bone sem NENHUM dado em nenhum canal é descartado.
    cleaned = {}
    for name, chans in node_animations.items():
        pos_kfs = chans["position"]
        if pos_kfs and all(
            kf["delta"]["x"] == 0.0 and kf["delta"]["y"] == 0.0 and kf["delta"]["z"] == 0.0
            for kf in pos_kfs
        ):
            chans["position"] = []

        orient_kfs = chans["orientation"]
        if orient_kfs and all(
            kf["delta"]["x"] == 0.0 and kf["delta"]["y"] == 0.0 and kf["delta"]["z"] == 0.0 and kf["delta"]["w"] == 1.0
            for kf in orient_kfs
        ):
            chans["orientation"] = []

        scale_kfs = chans["shapeStretch"]
        if scale_kfs and all(
            kf["delta"]["x"] == 1.0 and kf["delta"]["y"] == 1.0 and kf["delta"]["z"] == 1.0
            for kf in scale_kfs
        ):
            chans["shapeStretch"] = []

        if chans["position"] or chans["orientation"] or chans["shapeStretch"] or chans["shapeUvOffset"]:
            cleaned[exported_bone_name(obj, name)] = chans

    return cleaned, frame_start, frame_end, fps


# ---------------------------------------------------------------------------
# Lista de Actions no painel de export, estilo Auto Rig Pro: checkbox por
# Action + Select All / Deselect All.
# ---------------------------------------------------------------------------


class HYTALE_action_export_item(PropertyGroup):
    action_name: StringProperty()
    export: BoolProperty(default=False)


class HYTALE_UL_action_export_list(bpy.types.UIList):
    bl_idname = "HYTALE_UL_action_export_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row(align=True)
        row.prop(item, "export", text="")
        row.label(text=item.action_name)


class HYTALE_OT_select_all_actions(Operator):
    """Marca/desmarca todas as Actions da lista de export (botões dentro
    do painel do export -- só funciona enquanto o diálogo de export está
    aberto, via context.active_operator)."""

    bl_idname = "hytale.select_all_actions"
    bl_label = "Select/Deselect All"
    bl_options = {"INTERNAL"}

    value: BoolProperty(default=True)

    def execute(self, context):
        op = context.active_operator
        if op is None or not hasattr(op, "action_items"):
            self.report({"WARNING"}, "Export dialog isn't open.")
            return {"CANCELLED"}
        for item in op.action_items:
            item.export = self.value
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Operador de export -- em lote: 1 arquivo .blockyanim por Action marcada,
# escritos numa pasta escolhida (não um único arquivo).
# ---------------------------------------------------------------------------


class EXPORT_OT_hytale_blockyanim(Operator):
    """Batch-export one or more Actions of the selected/active Armature to Hytale's .blockyanim format -- one file per Action, into a chosen folder"""

    bl_idname = "export_scene.hytale_blockyanim"
    bl_label = "Export Hytale Animations (.blockyanim)"
    bl_options = {"REGISTER"}

    directory: StringProperty(subtype="DIR_PATH")

    action_items: CollectionProperty(type=HYTALE_action_export_item)
    action_items_index: IntProperty()

    # ---------------- Geral (sempre visível) ----------------

    bake_animation: BoolProperty(
        name="Bake Every Frame",
        description=(
            "ON (recommended): samples the final pose at every single "
            "frame, exactly as it looks in the viewport (IK, constraints, "
            "everything). Always safe, but makes bigger files. OFF: only "
            "samples frames that actually have a keyframe -- smaller "
            "files, but can look wrong if your rig uses IK, since IK "
            "poses aren't simple straight lines between keyframes"
        ),
        default=True,
    )

    is_loop: BoolProperty(
        name="Loop?",
        description=(
            "ON: the animation eases back to its starting pose at the "
            "end, so it can repeat seamlessly (walk, run, idle). OFF: the "
            "animation just stops and holds its last pose (attacks, "
            "deaths, one-off actions). This setting applies to every file "
            "in this export, EXCEPT Actions re-exported with 'Keep "
            "Imported Timing' ON (Advanced Options > Re-Export), which use "
            "their own original value instead"
        ),
        default=False,
    )

    force_start_end_keying: BoolProperty(
        name="Keep First & Last Frame",
        description=(
            "Only matters when 'Bake Every Frame' is OFF: makes sure the "
            "very first and last frame of each Action always get written, "
            "even if nothing was explicitly keyed exactly there. Without "
            "this, the exported clip could start or end a few frames "
            "early/late. Always on automatically when 'Bake Every Frame' "
            "is ON"
        ),
        default=True,
    )

    show_optimization: BoolProperty(name="Optimization", default=False)
    show_stretch: BoolProperty(name="Stretch Animation", default=False)
    show_uv: BoolProperty(name="Texture Picker", default=False)
    show_rig: BoolProperty(name="Rig Setup", default=False)
    show_format: BoolProperty(name="File Format", default=False)
    show_reexport: BoolProperty(name="Re-Export", default=False)
    # v0.12.2 -- checkbox por exportação (não persiste com o arquivo --
    # mesmo espírito de 'Bake Parent Scale into Children' dentro de
    # Stretch Animation). Fica DENTRO da caixa colapsável show_uv (ver
    # draw()) -- configurar as instâncias em si fica na aba Export do
    # Object Properties; este liga/desliga só decide se ESTA exportação
    # inclui shapeUvOffset ou não, sem apagar nenhuma instância.
    export_texture_picker: BoolProperty(
        name="Export Texture Picker",
        description=(
            "Include 'shapeUvOffset' data for every configured Texture "
            "Picker instance (see the 'Hytale Export' panel in Object "
            "Properties to add/edit/remove instances). Turn off to skip "
            "this channel for this export only, without deleting any "
            "configured instance"
        ),
        default=True,
    )

    # ---------------- Avançado (cada categoria colapsa por conta própria,
    # ver draw() -- não existe mais um "Advanced Options" único envolvendo
    # todas elas) ----------------

    frame_step: IntProperty(
        name="Frame Step",
        description=(
            "Only used when 'Bake Every Frame' is ON: 1 writes every "
            "single frame (safest). A higher number skips frames to save "
            "space, at the cost of smoothness -- only raise this if file "
            "size is a real problem"
        ),
        default=1,
        min=1,
    )

    preserved_interpolation: EnumProperty(
        name="Curve Style",
        description=(
            "Only used when 'Bake Every Frame' is OFF: how the game "
            "should smoothly move between two keyframes. Blockyanim only "
            "understands two styles (not full Bezier handles like "
            "Blender), so this one style is used for every keyframe"
        ),
        items=[
            ("smooth", "Smooth", "Eases in and out between keyframes -- closest to Blender's default curves"),
            ("linear", "Linear", "Moves at a constant speed between keyframes, no easing"),
        ],
        default="smooth",
    )

    quantize_values: BoolProperty(
        name="Snap to Grid",
        description=(
            "ON (recommended): rounds every written number to a fixed "
            "precision (see the three Step values below), which cleans up "
            "invisible floating-point jitter that Blender's math produces "
            "even for a bone that looks perfectly still. OFF: writes "
            "numbers exactly as Blender computed them, decimals and all"
        ),
        default=True,
    )

    position_quantize_step: FloatProperty(
        name="Position Step",
        description="Smallest position change 'Snap to Grid' will keep, in game units. Smaller = more precise, larger file",
        default=0.0001,
        min=0.0,
    )
    rotation_quantize_step: FloatProperty(
        name="Rotation Step",
        description="Smallest rotation change 'Snap to Grid' will keep. Smaller = more precise, larger file",
        default=0.00001,
        min=0.0,
    )
    scale_quantize_step: FloatProperty(
        name="Stretch Step",
        description="Smallest stretch/scale change 'Snap to Grid' will keep. Smaller = more precise, larger file",
        default=0.0001,
        min=0.0,
    )

    position_zero_epsilon: FloatProperty(
        name="Position Noise Floor",
        description=(
            "A bone that should be perfectly still can still end up with "
            "a microscopic position value due to floating-point math -- "
            "in-game this can look like tiny, invisible-in-Blender "
            "shaking. Any position smaller than this (in game units) gets "
            "snapped to exactly zero instead"
        ),
        default=0.001,
        min=0.0,
    )

    rotation_zero_epsilon: FloatProperty(
        name="Rotation Noise Floor",
        description=(
            "Same idea as Position Noise Floor, but for rotation: a bone "
            "that should be perfectly still can end up with a "
            "microscopic rotation instead of none at all (very common on "
            "IK legs/arms, where the solver rarely lands on an EXACT "
            "answer). Any rotation closer to 'no rotation at all' than "
            "this gets snapped to exactly zero"
        ),
        default=0.0001,
        min=0.0,
    )

    skip_redundant_frames: BoolProperty(
        name="Remove Extra Frames",
        description=(
            "OFF (default): writes every sampled frame, guaranteeing an "
            "exact match to what you see in Blender. ON: additionally "
            "drops frames that don't add any real information -- for "
            "example, a long straight stretch of motion doesn't need a "
            "point every single frame if a few points already describe "
            "the same curve. This makes the file noticeably smaller but "
            "is LOSSY (can very slightly change the curve) -- only turn "
            "it on if file size is still a problem after 'Snap to Grid' "
            "and compact JSON formatting, which already help for free"
        ),
        default=False,
    )

    position_epsilon: FloatProperty(
        name="Position Tolerance",
        description=(
            "Only used when 'Remove Extra Frames' is ON: how far (in game "
            "units) a position/stretch frame is allowed to drift from a "
            "straight line before it's considered necessary to keep. "
            "Higher = more frames removed, less precise"
        ),
        default=0.001,
        min=0.0,
    )
    rotation_epsilon: FloatProperty(
        name="Rotation Tolerance",
        description=(
            "Only used when 'Remove Extra Frames' is ON: how far a "
            "rotation frame is allowed to drift from a smooth curve "
            "before it's considered necessary to keep. Higher = more "
            "frames removed, less precise"
        ),
        default=0.0001,
        min=0.0,
    )

    export_scale: BoolProperty(
        name="Export Stretch (Scale)",
        description=(
            "ON (recommended): includes bone scale/stretch animation in "
            "the file (the 'shapeStretch' channel -- e.g. an eyebrow "
            "squashing/stretching). Turn OFF only if this rig never "
            "animates stretch and you want to skip sampling it entirely"
        ),
        default=True,
    )

    scale_zero_epsilon: FloatProperty(
        name="Stretch Noise Floor",
        description="Same idea as Position Noise Floor, but for stretch: any scale closer to 1.0 (no stretch) than this on every axis gets snapped to exactly 1.0",
        default=0.001,
        min=0.0,
    )

    # v0.10.18 -- diferente de Blender (onde escalar um bone pai encolhe os
    # filhos JUNTO na viewport por padrão -- "Inherit Scale"), o Hytale/
    # Blockbench NÃO herda escala pela hierarquia: cada bone tem seu
    # 'shapeStretch' totalmente independente (confirmado ao vivo pelo
    # usuário -- escalar um bone pai dentro do próprio Blockbench não
    # afeta os filhos). Sem esse toggle, uma animação que só escala o bone
    # PAI no Blender (esperando que os filhos encolham visualmente junto,
    # como aparece na viewport) exporta um shapeStretch que só existe no
    # pai -- os filhos saem parados em 1.0, e no Blockbench/jogo eles NÃO
    # encolhem (só o pai). Ligado, cada bone exportável recebe o produto
    # do seu próprio scale local com o de TODOS os ancestrais exportáveis
    # (mesmo espírito do "Inherit Scale: Full" do Blender) -- calculado só
    # na hora de amostrar pro export (ver sample_action()), sem alterar
    # nenhum keyframe de verdade na Action.
    #
    # v0.10.19 -- CORRIGIDO: só o tamanho (shapeStretch) não bastava --
    # relatado ao vivo pelo usuário depois de testar a v0.10.18 (os filhos
    # encolhiam, mas cada um em torno do PRÓPRIO pivot, em vez de se
    # aproximar do pivot do pai, como a composição de matriz de verdade do
    # Blender faz). Agora também corrige a POSIÇÃO de cada filho (ver
    # rest_local_positions() + fórmula em sample_action()), puxando o
    # pivot dele em direção ao pivot do pai proporcionalmente à escala em
    # cascata -- reconstrói o efeito completo de "child_world = parent_
    # world @ child_local" que o Hytale não faz sozinho.
    bake_scale_hierarchy: BoolProperty(
        name="Bake Parent Scale into Children",
        description=(
            "Hytale/Blockbench bones don't inherit scale from their parent the way Blender's viewport "
            "does -- if you only keyframed scale on a parent bone (e.g. shrinking it to hide it, expecting "
            "children inside it to shrink and move closer together), the children would export with no "
            "scale/position change at all and stay full-size, spread out, in Blockbench/the game. Turn "
            "this ON to bake the parent's scale into every child's exported 'shapeStretch' AND pull each "
            "child's pivot toward the parent's, matching what you see in the Blender viewport. Only "
            "affects the exported file -- doesn't touch your actual keyframes"
        ),
        default=False,
    )

    # v0.6.5 -- uv_offset_step_x/px_x/step_y/px_y MOVIDOS pra
    # HYTALE_export_bone_settings (persistido na Armature) -- eram
    # Property de Operator aqui, resetavam pro default toda vez que
    # este diálogo abria (não persistiam com o arquivo), o que
    # impedia o Rigger (Texture Picker) de pré-preencher isso de verdade.
    # v0.12 -- moveram de novo, agora pra HYTALE_texture_picker_export_item
    # (uma calibração por INSTÂNCIA, dentro de armature.hytale_texture_
    # picker_exports). draw() abaixo mostra os 4 campos da entrada ATIVA
    # da lista (hytale_texture_picker_exports_index); sample_action() já
    # itera a lista inteira sozinho.

    unit_scale: FloatProperty(
        name="Blender Units per Game Unit",
        description=(
            "MUST match the exact value used when this character was "
            "imported (Hytale Blockymodel Importer) -- if they don't "
            "match, every position in the exported file will be wrong by "
            "a consistent scale factor. When in doubt, leave this at the "
            "default"
        ),
        default=UNIT_SCALE_DEFAULT,
        min=0.0001,
        max=10.0,
    )

    output_decimal_places: IntProperty(
        name="Decimal Places",
        description=(
            "How many digits after the decimal point to keep for every "
            "number in the file. Purely cosmetic and doesn't drop any "
            "keyframes -- just keeps the file from being full of numbers "
            "like 0.30000000000000004"
        ),
        default=6,
        min=1,
        max=12,
    )

    pretty_print_json: BoolProperty(
        name="Readable JSON",
        description=(
            "OFF (default): writes the file as one compact line -- "
            "smaller, and nothing normally needs to read it by hand. ON: "
            "writes it nicely indented across many lines instead, purely "
            "so a human can open and read/compare it (roughly doubles "
            "file size; the game and Blockbench read either format "
            "identically)"
        ),
        default=False,
    )

    use_source_metadata: BoolProperty(
        name="Keep Imported Timing",
        description=(
            "Only matters for an Action that was imported by 'Import "
            "Hytale Animation' and hasn't been edited since. ON: reuse "
            "that file's exact original Duration/Loop values instead of "
            "the 'Loop?' option above and the current timeline length -- "
            "useful for a verification export, to check that reimporting "
            "an unedited file gives back exactly the same file. OFF "
            "(default, and what you want for normal editing work): always "
            "compute Duration/Loop fresh from the current timeline and "
            "the 'Loop?' option above. Leave this OFF whenever you've "
            "actually changed the animation, or a stale imported Duration "
            "shorter than your edit could silently cut off frames in the "
            "exported file"
        ),
        default=False,
    )


    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "ARMATURE"

    def invoke(self, context, event):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            self.report({"ERROR"}, "Select/activate the Armature you want to export first.")
            return {"CANCELLED"}

        current_action_name = None
        if obj.animation_data and obj.animation_data.action:
            current_action_name = obj.animation_data.action.name

        self.action_items.clear()
        for action in sorted(bpy.data.actions, key=lambda a: a.name.lower()):
            item = self.action_items.add()
            item.action_name = action.name
            item.export = action.name == current_action_name

        self.directory = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        layout = self.layout

        actions_box = layout.box()
        actions_box.label(text="Actions to Export", icon="ACTION")
        row = actions_box.row(align=True)
        op_all = row.operator(HYTALE_OT_select_all_actions.bl_idname, text="Select All")
        op_all.value = True
        op_none = row.operator(HYTALE_OT_select_all_actions.bl_idname, text="Deselect All")
        op_none.value = False
        actions_box.template_list(
            "HYTALE_UL_action_export_list", "",
            self, "action_items",
            self, "action_items_index",
            rows=8,
        )
        n_selected = sum(1 for it in self.action_items if it.export)
        actions_box.label(text=f"{n_selected} action(s) selected")

        general_box = layout.box()
        general_box.prop(self, "bake_animation")
        general_box.prop(self, "is_loop")
        fsub = general_box.column()
        fsub.enabled = not self.bake_animation
        fsub.prop(self, "force_start_end_keying")

        layout.prop(
            self, "show_optimization",
            icon="TRIA_DOWN" if self.show_optimization else "TRIA_RIGHT",
            emboss=False,
        )
        if self.show_optimization:
            opt_box = layout.box()

            step_col = opt_box.column()
            step_col.enabled = self.bake_animation
            step_col.prop(self, "frame_step")

            interp_col = opt_box.column()
            interp_col.enabled = not self.bake_animation
            interp_col.prop(self, "preserved_interpolation")

            opt_box.separator()
            opt_box.prop(self, "quantize_values")
            quant_col = opt_box.column()
            quant_col.enabled = self.quantize_values
            quant_col.prop(self, "position_quantize_step")
            quant_col.prop(self, "rotation_quantize_step")
            quant_col.prop(self, "scale_quantize_step")

            opt_box.separator()
            opt_box.prop(self, "position_zero_epsilon")
            opt_box.prop(self, "rotation_zero_epsilon")

            opt_box.separator()
            opt_box.prop(self, "skip_redundant_frames")
            skip_col = opt_box.column()
            skip_col.enabled = self.skip_redundant_frames
            skip_col.prop(self, "position_epsilon")
            skip_col.prop(self, "rotation_epsilon")

        layout.prop(
            self, "show_stretch",
            icon="TRIA_DOWN" if self.show_stretch else "TRIA_RIGHT",
            emboss=False,
        )
        if self.show_stretch:
            stretch_box = layout.box()
            stretch_box.prop(self, "export_scale")
            scale_col = stretch_box.column()
            scale_col.enabled = self.export_scale
            scale_col.prop(self, "scale_zero_epsilon")
            scale_col.prop(self, "bake_scale_hierarchy")

        # v0.12 -- CORRIGIDO (feedback do usuário, testando o painel de
        # verdade): antes esta seção era uma caixa colapsável mostrando
        # os 4 campos de calibração da entrada ATIVA de armature.hytale_
        # texture_picker_exports (por índice) -- com múltiplas instâncias
        # isso ficou confuso (o usuário não tem como saber, só olhando
        # este diálogo, qual instância está "ativa" sem ir conferir a
        # aba Export do Object Properties antes). Os 4 campos (Grid
        # Step/Pixels per Step) MUDARAM de lugar -- moraram aqui (v0.6.5),
        # depois em HYTALE_export_bone_settings persistido na Armature
        # (v0.10.10), agora vivem 100% na aba Export do Object
        # Properties (interface.py), junto com o resto dos campos de
        # CADA instância (Source/Target/Companion Bones) -- um lugar só
        # por instância, sem ambiguidade de "qual está selecionada".
        #
        # v0.12.2 -- CORRIGIDO de novo (feedback do usuário, mesma
        # sessão): a primeira tentativa de correção acima trocou a
        # caixa colapsável por um único checkbox solto -- destoava
        # visualmente do resto do diálogo (Optimization/Stretch
        # Animation/Rig Setup/File Format/Re-Export são TODAS caixas
        # colapsáveis, um checkbox solto no meio delas quebrava o
        # padrão). Voltou a ser colapsável (mesma estrutura exata das
        # outras -- layout.prop com TRIA_DOWN/TRIA_RIGHT + box()), só
        # que o conteúdo de dentro ficou simples: o checkbox por
        # exportação (mesmo espírito de 'Bake Parent Scale into
        # Children' dentro de Stretch Animation acima) + um label
        # pequeno com a contagem, em vez da contagem ir dentro do
        # texto do próprio checkbox.
        layout.prop(
            self, "show_uv",
            icon="TRIA_DOWN" if self.show_uv else "TRIA_RIGHT",
            emboss=False,
        )
        if self.show_uv:
            uv_box = layout.box()
            configured_count = (
                len(get_texture_picker_exports(context.active_object))
                if context.active_object is not None and context.active_object.type == "ARMATURE"
                else 0
            )
            uv_box.prop(self, "export_texture_picker")
            count_row = uv_box.row()
            count_row.label(text=f"{configured_count} instance(s) configured.")

        layout.prop(
            self, "show_rig",
            icon="TRIA_DOWN" if self.show_rig else "TRIA_RIGHT",
            emboss=False,
        )
        if self.show_rig:
            rig_box = layout.box()
            rig_box.prop(self, "unit_scale")

        layout.prop(
            self, "show_format",
            icon="TRIA_DOWN" if self.show_format else "TRIA_RIGHT",
            emboss=False,
        )
        if self.show_format:
            format_box = layout.box()
            format_box.prop(self, "output_decimal_places")
            format_box.prop(self, "pretty_print_json")

        layout.prop(
            self, "show_reexport",
            icon="TRIA_DOWN" if self.show_reexport else "TRIA_RIGHT",
            emboss=False,
        )
        if self.show_reexport:
            reexport_box = layout.box()
            reexport_box.prop(self, "use_source_metadata")

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            self.report({"ERROR"}, "Select/activate the Armature you want to export first.")
            return {"CANCELLED"}
        if obj.animation_data is None:
            obj.animation_data_create()

        selected_items = [it for it in self.action_items if it.export]
        if not selected_items:
            self.report({"ERROR"}, "No Action selected -- check at least one in the list.")
            return {"CANCELLED"}

        if not self.directory:
            self.report({"ERROR"}, "No output folder selected.")
            return {"CANCELLED"}
        os.makedirs(self.directory, exist_ok=True)

        export_settings = get_export_settings(obj)
        collection_name = export_settings.export_collection_name

        collection_names = bones_in_collection(obj, collection_name)
        if collection_names is not None:
            exportable_names = collection_names
            if not exportable_names:
                self.report(
                    {"ERROR"},
                    f"Bone Collection '{collection_name}' exists but has "
                    f"no bones assigned to it.",
                )
                return {"CANCELLED"}
        else:
            exportable_names = {b.name for b in obj.data.bones if is_original_bone_name(b.name)}
            self.report(
                {"WARNING"},
                f"Bone Collection '{collection_name}' not found -- "
                f"falling back to guessing bones by name suffix (_MCH/_CTRL/_IK). "
                f"Set it in the 'Hytale Export' panel (Object Properties).",
            )
            if not exportable_names:
                self.report({"ERROR"}, "No 'original' (suffix-less) bones found.")
                return {"CANCELLED"}

        rest_by_bone = rest_matrices(obj)
        # v0.10.19 -- só usado por Bake Parent Scale into Children (ver
        # rest_local_positions()) -- calculado aqui, uma vez só pra toda a
        # sessão de export (repouso é fixo, não muda por Action/frame).
        rest_local_pos = rest_local_positions(obj, rest_by_bone, exportable_names, self.unit_scale)

        original_action = obj.animation_data.action
        original_frame = context.scene.frame_current

        exported_files = []
        try:
            for item in selected_items:
                action = bpy.data.actions.get(item.action_name)
                if action is None:
                    self.report({"WARNING"}, f"Action '{item.action_name}' not found anymore, skipping.")
                    continue

                obj.animation_data.action = action
                node_animations, frame_start, frame_end, fps = sample_action(
                    context, obj, action, exportable_names, rest_by_bone, rest_local_pos, self
                )

                duration_seconds = (frame_end - frame_start) / fps
                computed_duration = max(1, round(duration_seconds * FPS_HYTALE))

                # Se este Action veio do anim_importer.py e ainda carrega os
                # valores originais do arquivo (ver _stamp_action_source_metadata
                # em anim_importer.py), preferir eles em vez do que acabamos de
                # recalcular a partir do frame range atual -- ver
                # use_source_metadata, acima, pra quando isso NÃO é desejado.
                duration_value = computed_duration
                hold_last_value = not self.is_loop
                if self.use_source_metadata:
                    stamped_duration = action.get(ACTION_SOURCE_DURATION_PROP)
                    if stamped_duration is not None:
                        duration_value = max(1, int(round(stamped_duration)))
                    stamped_hold_last = action.get(ACTION_SOURCE_HOLD_LAST_KEYFRAME_PROP)
                    if stamped_hold_last is not None:
                        hold_last_value = bool(stamped_hold_last)

                content = {
                    "formatVersion": 1,
                    "duration": duration_value,
                    "holdLastKeyframe": hold_last_value,
                    "nodeAnimations": node_animations,
                }

                filename = sanitize_filename(action.name) + ".blockyanim"
                filepath = os.path.join(self.directory, filename)
                # newline="\n" é proposital nos dois modos: sem isso, o
                # Python no Windows converte cada "\n" que escrevermos pra
                # "\r\n" (modo texto padrão do SO) -- no modo Pretty Print
                # (que tem uma linha por campo) isso sozinho já adiciona um
                # byte extra por linha (~65KB num arquivo deste tamanho),
                # sem ganhar nada em troca. O Blockbench/o jogo leem "\n"
                # puro sem problema.
                with open(filepath, "w", encoding="utf-8", newline="\n") as f:
                    rounded = round_floats_for_output(content, self.output_decimal_places)
                    if self.pretty_print_json:
                        f.write(dump_pretty_blockyanim(rounded))
                    else:
                        json.dump(rounded, f, separators=(",", ":"))
                exported_files.append(filename)
        finally:
            obj.animation_data.action = original_action
            context.scene.frame_set(original_frame)
            context.view_layer.update()

        if not exported_files:
            self.report({"ERROR"}, "Nothing was exported.")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Exported {len(exported_files)} file(s) to '{self.directory}': " + ", ".join(exported_files),
        )
        return {"FINISHED"}


def menu_func_export(self, context):
    self.layout.operator(EXPORT_OT_hytale_blockyanim.bl_idname, text="Hytale Animations (.blockyanim)")


classes = (
    HYTALE_export_settings,
    HYTALE_texture_picker_export_item,
    HYTALE_UL_texture_picker_exports,
    EXPORT_OT_texture_picker_export_add,
    EXPORT_OT_texture_picker_export_remove,
    HYTALE_action_export_item,
    HYTALE_UL_action_export_list,
    HYTALE_OT_select_all_actions,
    EXPORT_OT_hytale_blockyanim,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    Armature.hytale_export_settings = PointerProperty(type=HYTALE_export_settings)
    # v0.12 -- CollectionProperty (uma entrada por instância de Texture
    # Picker) + índice do item ativo -- mesmo padrão de
    # Armature.hytale_ik_chains/_index em rigger/rig.py. Ver
    # HYTALE_texture_picker_export_item e get_texture_picker_exports.
    Armature.hytale_texture_picker_exports = CollectionProperty(type=HYTALE_texture_picker_export_item)
    Armature.hytale_texture_picker_exports_index = IntProperty(default=0)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    del Armature.hytale_texture_picker_exports_index
    del Armature.hytale_texture_picker_exports
    del Armature.hytale_export_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
