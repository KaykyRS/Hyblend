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
UV_OFFSET_SOURCE_BONE_DEFAULT = "ui.mouth_uv"
UV_OFFSET_TARGET_BONE_DEFAULT = "Mouth"

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
# Bone Collection" e "Export UV Offset" (on/off + quais bones) NÃO são mais
# properties efêmeras do diálogo do operador de export: são guardadas aqui,
# no dado da própria Armature, e editadas pelo painel do interface.py (aba
# Export), pra não precisar reconfigurar toda vez que você abre o diálogo
# de export.
#
# Registradas aqui (não em interface.py, nem em common.py) seguindo
# EXATAMENTE o mesmo padrão que rigger.py já usa pra hytale_ik_chains:
# quem é DONO da lógica registra o dado direto no tipo Armature;
# interface.py só desenha (igual ele já faz pra hytale_ik_chains, lendo
# armature.hytale_ik_chains sem redefinir nada). Ver DEVELOPER_NOTES.md.
class HYTALE_export_bone_settings(PropertyGroup):
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
    export_uv_offset: BoolProperty(
        name="Export UV Offset (atlas texture, e.g. Mouth)",
        description=(
            "Samples a control bone's Location each frame, snaps it to a "
            "grid, and writes the result as raw atlas-pixel deltas into "
            "the 'shapeUvOffset' channel of a target bone -- e.g. a Mouth "
            "bone driven by a texture-atlas UV picker rig. This does NOT "
            "read the material/shader -- it reproduces the same snap-to-"
            "grid math directly from the control bone's Location, so it "
            "must match whatever math your driver uses. The grid "
            "calibration itself (Grid Step/Pixels per Step) stays in the "
            "export dialog's Advanced Options"
        ),
        default=False,
    )
    uv_offset_source_bone: StringProperty(
        name="UV Control Bone",
        description=(
            "Name of the helper bone whose Location drives the atlas "
            "picker (e.g. 'ui.mouth_uv'). This bone itself is NOT "
            "exported -- only its Location is sampled"
        ),
        default=UV_OFFSET_SOURCE_BONE_DEFAULT,
    )
    uv_offset_target_bone: StringProperty(
        name="Target Bone (shapeUvOffset)",
        description=(
            "Exact name of the real game bone to attach the "
            "'shapeUvOffset' channel to -- must be one of the exportable "
            "bones (e.g. 'Mouth')"
        ),
        default=UV_OFFSET_TARGET_BONE_DEFAULT,
    )


def get_export_bone_settings(armature_obj):
    """Atalho pra armature_obj.data.hytale_export_settings (o painel do
    interface.py lê/escreve o mesmo caminho direto, sem passar por esta
    função -- ela existe só pro lado do exporter.py, que MAIS de um lugar
    neste arquivo precisa ler). Fallback pro próprio default da
    PropertyGroup se, por algum motivo (addon-standalone sem o resto do
    pacote, ordem de registro), a Armature ainda não tiver esse dado --
    nunca trava o export por causa disso."""
    data = getattr(armature_obj, "data", None)
    settings = getattr(data, "hytale_export_settings", None)
    if settings is None:
        # Instância "solta" (não vinculada a nenhuma Armature real) só
        # pra fornecer os defaults -- nunca é lida/gravada de verdade.
        settings = HYTALE_export_bone_settings()
    return settings


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
    """Lê a Location (pose, local) do bone de controle (ex.: 'ui.mouth_uv')
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


def sample_action(context, obj, action, exportable_names, rest_by_bone, opts):
    """'opts' é o próprio operador (self) -- só lemos as Properties dele.
    Assume que obj.animation_data.action já foi setado pra 'action' antes
    de chamar. Devolve (node_animations, frame_start, frame_end, fps)."""
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
            # do jogo pode não ser). "shapeUvOffset" É populado quando
            # Export UV Offset está ligado (ver sample_uv_offset_px).
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

    last_sampled_uv = {}
    last_raw_quat = {}
    zero_vec = Vector((0.0, 0.0, 0.0))
    identity_scale = Vector((1.0, 1.0, 1.0))
    identity_quat = Quaternion((1.0, 0.0, 0.0, 0.0))

    bone_settings = get_export_bone_settings(obj)

    uv_control_pbone = None
    if bone_settings.export_uv_offset:
        uv_control_pbone = obj.pose.bones.get(bone_settings.uv_offset_source_bone)
        if uv_control_pbone is None:
            opts.report(
                {"WARNING"},
                f"UV Offset: bone de controle '{bone_settings.uv_offset_source_bone}' não "
                f"encontrado no Armature -- pulando shapeUvOffset na Action "
                f"'{action.name}'.",
            )
        elif bone_settings.uv_offset_target_bone not in node_animations:
            opts.report(
                {"WARNING"},
                f"UV Offset: bone alvo '{bone_settings.uv_offset_target_bone}' não está "
                f"entre os bones exportáveis -- pulando shapeUvOffset na Action "
                f"'{action.name}'.",
            )
            uv_control_pbone = None

    for frame in frames:
        is_edge_frame = frame == frames[0] or frame == frames[-1]

        scene.frame_set(frame)
        context.view_layer.update()

        pose_by_bone = pose_matrices(obj)
        deltas = compute_deltas(obj, rest_by_bone, pose_by_bone, exportable_names, opts.unit_scale)
        hytale_time = frame_to_hytale_time(frame, frame_start, fps)

        for name, (pos, quat, scale) in deltas.items():
            # Correção de sinal (dupla cobertura, q == -q) -- ANTES de
            # quantizar e ANTES de acumular pra RDP, pra continuidade
            # correta nos dois. Ver fix_quaternion_sign().
            quat = fix_quaternion_sign(quat, last_raw_quat.get(name))
            last_raw_quat[name] = quat

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

        if uv_control_pbone is not None:
            px_x, px_y = sample_uv_offset_px(uv_control_pbone, opts)

            # Dedupe por igualdade EXATA (não por epsilon/RDP) -- o valor
            # já é discreto (snap-to-grid), então dois frames iguais em
            # sequência são 100% redundantes, nunca uma transição lenta
            # real sendo cortada. RDP assume uma curva contínua
            # interpolável (lerp/slerp) entre âncoras, o que não faz
            # sentido pra um offset de atlas em degraus -- por isso esse
            # canal continua com seu próprio dedupe simples, independente.
            write_uv = True
            if not is_edge_frame:
                prev_uv = last_sampled_uv.get(bone_settings.uv_offset_target_bone)
                if prev_uv == (px_x, px_y):
                    write_uv = False
            last_sampled_uv[bone_settings.uv_offset_target_bone] = (px_x, px_y)
            if write_uv:
                node_animations[bone_settings.uv_offset_target_bone]["shapeUvOffset"].append(
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
        name="Bake Animation",
        description=(
            "ON: samples the fully-resolved pose (IK, constraints, "
            "everything) at every frame -- most robust, recommended "
            "whenever IK is involved. Always writes Linear interpolation "
            "(no Smooth option here -- see the Advanced section for why). "
            "OFF: tries to preserve as much as possible by only sampling "
            "at frames where SOMETHING in the rig has a keyframe"
        ),
        default=True,
    )

    hold_last_keyframe: BoolProperty(
        name="Hold Last Keyframe (no loop)",
        description=(
            "Applies to every file exported in this batch. ON: animation "
            "stops and holds its last pose. OFF: animation loops back to "
            "the start"
        ),
        default=False,
    )

    force_start_end_keying: BoolProperty(
        name="Force Start/End Keying",
        description=(
            "Only matters when Bake Animation is OFF: guarantees the first "
            "and last frame of each Action's own range gets sampled, even "
            "if there's no literal keyframe exactly there. With Bake "
            "Animation ON this is always true anyway (every frame is "
            "sampled regardless)"
        ),
        default=True,
    )

    show_advanced: BoolProperty(name="Advanced Options", default=False)

    # ---------------- Avançado (recolhido por padrão) ----------------

    frame_step: IntProperty(
        name="Frame Step",
        description="Only used when Bake Animation is ON -- 1 samples every frame",
        default=1,
        min=1,
    )

    preserved_interpolation: EnumProperty(
        name="Interpolation (Bake Animation OFF)",
        description=(
            "Blockyanim only supports 'linear' or 'smooth' per keyframe "
            "(not full bezier handles), so this is applied uniformly"
        ),
        items=[
            ("smooth", "Smooth (Catmull-Rom)", "Closer to Blender's default Bezier handles"),
            ("linear", "Linear", ""),
        ],
        default="smooth",
    )

    unit_scale: FloatProperty(
        name="Scale (Blender units per game unit)",
        description=(
            "MUST match the value used when this rig was imported by the "
            "Hytale Blockymodel Importer -- positions are multiplied by "
            "1/this value to convert back to game units"
        ),
        default=UNIT_SCALE_DEFAULT,
        min=0.0001,
        max=10.0,
    )

    export_scale: BoolProperty(
        name="Export Scale (shapeStretch)",
        description=(
            "Also export the bone's scale relative to rest as the "
            "'shapeStretch' channel. 1.0 on all axes = no stretch"
        ),
        default=True,
    )

    scale_zero_epsilon: FloatProperty(
        name="Scale Noise Floor (distance from 1.0)",
        description="Same idea as the position noise floor, but around identity scale (1,1,1) instead of zero",
        default=0.001,
        min=0.0,
    )

    uv_offset_step_x: FloatProperty(
        name="Grid Step X (Blender units)",
        description=(
            "Divisor used to snap the control bone's Location X to a grid "
            "-- must match the divisor in your Mapping node driver's X "
            "expression (e.g. round(location/0.1)*... -> 0.1 goes here)"
        ),
        default=0.1,
    )

    uv_offset_px_x: FloatProperty(
        name="Pixels per Step X",
        description=(
            "Raw atlas pixels moved per grid step on X, written directly "
            "into shapeUvOffset -- the game expects raw pixel offsets, "
            "not normalized UV (0..1)"
        ),
        default=20.0,
    )

    uv_offset_step_y: FloatProperty(
        name="Grid Step Y (Blender units)",
        description="Same idea as Grid Step X, applied to the control bone's Location Y",
        default=-0.045,
    )

    uv_offset_px_y: FloatProperty(
        name="Pixels per Step Y",
        description="Same idea as Pixels per Step X, applied to Y",
        default=-10.0,
    )

    quantize_values: BoolProperty(
        name="Quantize Values (snap to grid)",
        description=(
            "Rounds every written position/rotation/scale component to a "
            "fixed step. Suppresses tiny floating-point jitter riding on "
            "top of real motion, even with no constraints involved at all"
        ),
        default=True,
    )

    position_quantize_step: FloatProperty(name="Position Quantize Step (game units)", default=0.0001, min=0.0)
    rotation_quantize_step: FloatProperty(name="Rotation Quantize Step (quaternion component)", default=0.00001, min=0.0)
    scale_quantize_step: FloatProperty(name="Scale Quantize Step", default=0.0001, min=0.0)

    position_zero_epsilon: FloatProperty(
        name="Position Noise Floor (game units)",
        description=(
            "Any position delta smaller than this is treated as EXACTLY "
            "zero. Floating-point matrix math produces tiny non-zero noise "
            "even for bones that should never translate -- left unclamped, "
            "that noise reads as micro-shake in-game"
        ),
        default=0.001,
        min=0.0,
    )

    rotation_zero_epsilon: FloatProperty(
        name="Rotation Noise Floor (dot product)",
        description=(
            "Same idea as the position noise floor, but for rotation: any "
            "orientation delta whose dot product with the identity "
            "quaternion is within this distance of 1.0 is snapped to "
            "EXACTLY identity. Matters most on IK bones -- the IK solver "
            "is iterative, so even a target sitting exactly at the rest "
            "position can converge to a solution a tiny fraction off from "
            "the bind pose, baking a constant 'phantom' rotation into "
            "every single frame (Thigh/Foot on an IK leg are the classic "
            "case; the mid-chain Calf/Shin usually isn't affected)"
        ),
        default=0.0001,
        min=0.0,
    )

    skip_redundant_frames: BoolProperty(
        name="Skip Redundant Frames (RDP)",
        description=(
            "OFF by default: writes every sampled frame, guaranteeing an "
            "exact match to what you see in Blender. Note that compact "
            "formatting + rounding (below) already does most of the file-"
            "size work losslessly -- this option is a further, LOSSY "
            "reduction on top of that, so only turn it on if file size is "
            "still a problem after that. Uses Ramer-Douglas-Peucker per "
            "bone per channel: instead of only comparing each frame to the "
            "last one WRITTEN, it looks at the whole run of samples "
            "between two keyframes and drops the ones that are already "
            "well-approximated by a straight line/slerp between the "
            "endpoints -- catches long near-linear stretches (e.g. a slow "
            "ease) that a neighbor-only comparison would miss. Bones that "
            "keep DIFFERENT reduced keyframes near the same moment (e.g. "
            "during a fast multi-bone pose change) are automatically "
            "synced to a shared set of times in that window, so a pose "
            "change always lands on the same frame across the whole rig "
            "-- this is always on when this option is on, there's no "
            "separate switch for it, and no need to know in advance "
            "whether a given animation needs it"
        ),
        default=False,
    )


    position_epsilon: FloatProperty(
        name="Position Epsilon (game units)",
        description=(
            "RDP tolerance for 'Skip Redundant Frames' on position and "
            "shapeStretch (scale): a sample is dropped if it's within this "
            "distance of the straight line connecting its two neighboring "
            "keyframes"
        ),
        default=0.001,
        min=0.0,
    )
    rotation_epsilon: FloatProperty(
        name="Rotation Epsilon (dot product)",
        description=(
            "RDP tolerance for 'Skip Redundant Frames' on orientation: a "
            "sample is dropped if it's within this distance (1.0 minus "
            "quaternion dot product) of the slerp connecting its two "
            "neighboring keyframes"
        ),
        default=0.0001,
        min=0.0,
    )

    output_decimal_places: IntProperty(
        name="Output Decimal Places",
        description=(
            "Numbers in the written file are rounded to this many decimal "
            "places -- purely cosmetic/file-size, doesn't drop any "
            "keyframes, just shortens each number's text representation "
            "(e.g. avoids things like 0.30000000000000004)"
        ),
        default=6,
        min=1,
        max=12,
    )

    pretty_print_json: BoolProperty(
        name="Pretty Print (indented JSON)",
        description=(
            "Off by default: the file is written as a single compact line "
            "(smaller file, and nothing normally reads it by hand). Turn "
            "this on to write indented, multi-line JSON instead -- purely "
            "for manually opening/comparing/diffing the file (e.g. against "
            "a Blockbench re-export), roughly doubles file size and "
            "changes nothing the game/Blockbench actually reads"
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
        general_box.prop(self, "hold_last_keyframe")
        fsub = general_box.column()
        fsub.enabled = not self.bake_animation
        fsub.prop(self, "force_start_end_keying")

        layout.prop(
            self, "show_advanced",
            icon="TRIA_DOWN" if self.show_advanced else "TRIA_RIGHT",
            emboss=False,
        )
        if self.show_advanced:
            adv = layout.box()

            step_col = adv.column()
            step_col.enabled = self.bake_animation
            step_col.prop(self, "frame_step")

            interp_col = adv.column()
            interp_col.enabled = not self.bake_animation
            interp_col.prop(self, "preserved_interpolation")

            adv.separator()
            adv.prop(self, "unit_scale")

            adv.separator()
            adv.prop(self, "export_scale")
            scale_col = adv.column()
            scale_col.enabled = self.export_scale
            scale_col.prop(self, "scale_zero_epsilon")

            # Export Bone Collection e Export UV Offset (toggle + qual bone
            # é fonte/alvo) saíram deste diálogo -- agora ficam no painel
            # "Hytale Export" (Object Properties da Armature), editado pelo
            # interface.py. Aqui sobra só a calibração numérica do grid de
            # UV, que é OUTRO tipo de dado (constantes de conversão
            # px<->unidade Blender, não "qual bone"/"ligado ou não") -- por
            # isso não faz sentido mover pra lá junto. Ver DEVELOPER_NOTES.md.
            adv.separator()
            uv_col = adv.column()
            uv_col.label(
                text="UV Offset grid calibration (on/off + bones: Hytale Export panel)",
                icon="INFO",
            )
            uv_row1 = uv_col.row(align=True)
            uv_row1.prop(self, "uv_offset_step_x")
            uv_row1.prop(self, "uv_offset_px_x")
            uv_row2 = uv_col.row(align=True)
            uv_row2.prop(self, "uv_offset_step_y")
            uv_row2.prop(self, "uv_offset_px_y")

            adv.separator()
            adv.prop(self, "quantize_values")
            quant_col = adv.column()
            quant_col.enabled = self.quantize_values
            quant_col.prop(self, "position_quantize_step")
            quant_col.prop(self, "rotation_quantize_step")
            quant_col.prop(self, "scale_quantize_step")

            adv.separator()
            adv.prop(self, "position_zero_epsilon")
            adv.prop(self, "rotation_zero_epsilon")

            adv.separator()
            adv.prop(self, "skip_redundant_frames")
            skip_col = adv.column()
            skip_col.enabled = self.skip_redundant_frames
            skip_col.prop(self, "position_epsilon")
            skip_col.prop(self, "rotation_epsilon")

            adv.separator()
            adv.prop(self, "output_decimal_places")
            adv.prop(self, "pretty_print_json")

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

        bone_settings = get_export_bone_settings(obj)
        collection_name = bone_settings.export_collection_name

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
                    context, obj, action, exportable_names, rest_by_bone, self
                )

                duration_seconds = (frame_end - frame_start) / fps
                content = {
                    "formatVersion": 1,
                    "duration": max(1, round(duration_seconds * FPS_HYTALE)),
                    "holdLastKeyframe": self.hold_last_keyframe,
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
    HYTALE_export_bone_settings,
    HYTALE_action_export_item,
    HYTALE_UL_action_export_list,
    HYTALE_OT_select_all_actions,
    EXPORT_OT_hytale_blockyanim,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    Armature.hytale_export_settings = PointerProperty(type=HYTALE_export_bone_settings)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    del Armature.hytale_export_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
