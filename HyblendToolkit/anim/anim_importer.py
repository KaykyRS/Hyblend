"""Anim Importer -- lê um .blockyanim (mesmo formato que exporter.py
escreve) e aplica a animação numa Armature já existente. Diferente de
importer.py (que constrói o Armature do zero): aqui a geometria/
hierarquia já existe, só posamos nos frames certos.

Dois modos de destino (target_mode), pensados como camadas que se
apoiam uma na outra:

  ORG  -- keyframa o bone original direto (mesmo nome do
          .blockymodel/.blockyanim). Funciona em qualquer Armature que
          tenha esses bones, rigada ou não -- é o modo genérico que
          precisa funcionar pra qualquer criatura, não só o Player.
          Numa Armature com rig gerado, os keyframes não movem nada
          visualmente (o ORG está constrained no MCH).
  CTRL -- escreve nos bones "_CTRL"/"_IK"/pole em vez do ORG,
          calculando a pose de mundo pretendida (andando a hierarquia
          ORG) e reprojetando no pai real de cada bone no Blender
          (pode ser diferente do pai ORG -- ver CTRL_PARENT_OVERRIDES
          em rigger/constants.py). Três sub-opções independentes:
            Spine -- Default (root.master_CTRL/root.pelvis_CTRL seguem
                     o Pelvis) ou Spine CTRL (ficam parados, livre pra
                     ajuste manual).
            Arms/Legs (independentes, mesmas 3 opções) -- Default
                     (FK+IK), Control FK, ou Control IK -- cada cadeia
                     de armature.hytale_ik_chains tem um chain_type
                     ARM/LEG que diz a qual grupo pertence. Bones fora
                     de cadeia (torso, cabeça, dedos, cauda) sempre
                     vão por FK.
          O pole é posicionado replicando a mesma fórmula geométrica
          que o rigger usa na geração do rig (offset a partir do eixo
          Z do bone do meio da cadeia), com a orientação animada em
          vez da rest -- importante pra bater com o pole_angle
          calibrado. A ponta (_IK) precisa de correção extra (ver
          _resolve_ik_tip_matrix_basis) porque sua rest orientation é
          diferente da do ORG/bridge.

Bones _CTRL com constraint extra (ex.: Belly_CTRL/Chest_CTRL seguindo
root.spine_CTRL) e os Child Of dos pole targets ficam ativos por
padrão durante o import (Target=Controllers), a menos que
keep_spine_follow=False."""


import json
import os
from collections import deque, namedtuple

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Quaternion, Vector

from ..common import (
    ACTION_SOURCE_DURATION_PROP,
    ACTION_SOURCE_HOLD_LAST_KEYFRAME_PROP,
    BONE_RIGGER_CREATED_PROP,
    FPS_HYTALE,
    UNIT_SCALE_DEFAULT,
    armature_model_format,
    bone_file_name,
    effective_unit_scale,
    is_active_armature,
    quat_xyzw,
    vec3,
)
from ..rigger import (
    BONE_ROOT_MASTER,
    BONE_ROOT_PELVIS,
    PROP_FK_IK_SWITCH,
    PROP_RIG_LAYER,
    SUFFIX_CTRL,
    SUFFIX_IK,
    SUFFIX_MCH,
    SUFFIX_MCH_TRANSFER,
    SUFFIX_POLE,
    control_name,
    resolve_pelvis_org_name,
    source_org_of,
)
from ..translations import localized_props, register_localized_class, tr, unregister_localized_class

# Matemática de import -- espelho exato (invertido) de compute_deltas()/
# local_matrix() em exporter.py:
#   rest_local  = matrix_local(pai)⁻¹ @ matrix_local(bone)   [sem pai: rest_local = matrix_local(bone)]
#   delta_local = rest_local⁻¹ @ pose_local   (o que o exporter escreve, já em unidades de jogo)
#
# Pro modo ORG (sem constraint por cima), delta_local É EXATAMENTE
# pbone.matrix_basis -- ou seja, o que location/rotation_quaternion já
# representam por definição. Não precisamos de matriz de mundo nem de
# multiplicar por rest_local -- só desfazer a escala e reconstruir o
# quaternion, e jogar direto em pbone.location/rotation_quaternion
# (ver _apply_org_mode).
#
# Pro modo CTRL (o _CTRL pode ter um parent diferente do ORG), isso não
# basta -- precisa de matriz de mundo:
#   world_target = parent_world(ORG) @ rest_local(ORG) @ delta_local
#   ctrl_local   = parent_world(CTRL_real)⁻¹ @ world_target
#   ctrl_matrix_basis = rest_local(CTRL)⁻¹ @ ctrl_local


def parse_blockyanim(filepath):
    """Lê e valida minimamente um .blockyanim. Levanta ValueError com
    mensagem legível se o arquivo não bater com o formato esperado."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "nodeAnimations" not in data:
        raise ValueError("Missing 'nodeAnimations' -- this doesn't look like a .blockyanim file.")

    return data


def hytale_time_to_frame(time, start_frame, fps):
    """Inverso exato de frame_to_hytale_time() em exporter.py: 'time'
    do arquivo (frame a FPS_HYTALE fixo, relativo ao início) -> frame
    da timeline do Blender (na fps da cena, deslocado por start_frame)."""
    seconds = time / FPS_HYTALE
    return start_frame + round(seconds * fps)


def _remap_renamed_bone_names(armature_obj, node_animations):
    """O .blockyanim usa os nomes ORIGINAIS dos bones (os do jogo). Um
    bone renomeado no Blender ("Rename Bones" do Bone Settings, ou colisão
    de nome resolvida pelo importer) guarda o original em
    BONE_RENAMED_FROM_PROP/BONE_ORIGINAL_NAME_PROP (bone_file_name) -- aqui cada nome do arquivo que não existe
    como bone é trocado pelo bone cujo original é esse nome, desde que
    seja um só (ambíguo = fica como está, mesmo comportamento de antes).
    Nome que já existe como bone nunca é trocado."""
    bones = armature_obj.data.bones
    by_original = {}
    for bone in bones:
        original = bone_file_name(bone)
        if original:
            by_original.setdefault(original, []).append(bone.name)
    if not by_original:
        return node_animations
    # Nome exato sempre vence: primeiro reserva todo nome do arquivo que
    # já existe como bone; só depois traduz os outros, e só pra um bone
    # que ninguém reservou (nunca funde dois nomes do arquivo num bone).
    remapped = {name: channels for name, channels in node_animations.items() if bones.get(name) is not None}
    for name, channels in node_animations.items():
        if name in remapped:
            continue
        candidates = by_original.get(name, ())
        target = candidates[0] if len(candidates) == 1 else name
        if target in remapped:
            target = name
        remapped[target] = channels
    return remapped


def collect_target_bone_names(armature_obj, node_animations):
    """Separa os nomes de nodeAnimations em (existentes, ausentes)
    contra os pose bones da armature. "Ausentes" é esperado e normal --
    nem toda criatura tem os mesmos bones que o Player -- vira aviso
    agregado, não erro."""
    pose_bones = armature_obj.pose.bones
    existing = [name for name in node_animations if name in pose_bones]
    missing = [name for name in node_animations if name not in pose_bones]
    return existing, missing


# Mapeia "interpolationType" do arquivo pro tipo de F-Curve do Blender
# mais próximo. "smooth" no Blockbench não é matematicamente idêntico a
# BEZIER, mas é a aproximação visual mais razoável disponível nativamente.
INTERPOLATION_MAP = {"smooth": "BEZIER", "linear": "LINEAR"}
INTERPOLATION_DEFAULT = "BEZIER"

# Default pro campo "interpolationType" do arquivo em si (espaço
# "arquivo"), diferente de INTERPOLATION_DEFAULT (espaço "Blender").
# Usado só onde precisamos inventar/copiar um interpolationType.
RAW_INTERPOLATION_DEFAULT = "smooth"


def _assign_fcurve_group_legacy(action, datablock, fcurve, group_name):
    """4.4/4.5: põe `fcurve` no grupo `group_name` (cria se preciso)
    dentro do channelbag do slot que anima `datablock`. Só organização
    visual no Dope Sheet/Graph Editor -- falha silenciosa não afeta a
    animação."""
    try:
        slot = datablock.animation_data.action_slot
        for layer in action.layers:
            for strip in layer.strips:
                channelbag = strip.channelbag(slot)
                if channelbag is None:
                    continue
                group = channelbag.groups.get(group_name) or channelbag.groups.new(group_name)
                fcurve.group = group
                return
    except (AttributeError, RuntimeError, TypeError):
        pass


def _get_or_create_fcurve(action, datablock, data_path, index, group_name):
    """Compat 4.5/5.0+: Action.fcurves (API "legacy", ignora Action
    Slots) foi removida no Blender 5.0 -- bpy.types.Action Removed:
    fcurves/groups/id_root. Em 5.0+ o caminho correto é
    action.fcurve_ensure_for_datablock(), que resolve slot/layer/strip
    sozinho a partir do datablock (aqui, sempre a Armature Object).
    fcurve_ensure_for_datablock() existe desde o 4.4 (o addon exige
    4.5+), então é o caminho PREFERIDO em qualquer versão: no 4.5, o
    caminho legacy (action.fcurves.new numa Action já atribuída e ainda
    vazia) criava um slot "XXLegacy Slot" que NUNCA era ligado à
    Armature (animation_data.action_slot = None) -- keyframes existiam,
    mas nada animava. O legacy fica só como fallback defensivo."""
    if hasattr(action, "fcurve_ensure_for_datablock"):
        try:
            return action.fcurve_ensure_for_datablock(
                datablock, data_path, index=index, group_name=group_name
            )
        except TypeError:
            # 4.4/4.5: sem o parâmetro group_name (entrou no 5.0) --
            # cria sem grupo e agrupa na mão pelo channelbag do slot.
            fcurve = action.fcurve_ensure_for_datablock(datablock, data_path, index=index)
            if group_name and fcurve.group is None:
                _assign_fcurve_group_legacy(action, datablock, fcurve, group_name)
            return fcurve
    if hasattr(action, "fcurves"):
        fcurve = action.fcurves.find(data_path, index=index)
        if fcurve is None:
            fcurve = action.fcurves.new(data_path, index=index, action_group=group_name)
        return fcurve
    return action.fcurve_ensure_for_datablock(
        datablock, data_path, index=index, group_name=group_name
    )


def _write_channel(action, datablock, data_path, group_name, components, samples):
    """Escreve `samples` (lista de (frame, valor_completo, interp), já
    em unidades do Blender) num conjunto de F-Curves, uma por
    componente (ex.: location -> x,y,z / índices 0,1,2)."""
    if not samples:
        return

    fcurves = [
        _get_or_create_fcurve(action, datablock, data_path, i, group_name) for i in range(components)
    ]

    for frame, value, interp_key in samples:
        blender_interp = INTERPOLATION_MAP.get(interp_key, INTERPOLATION_DEFAULT)
        for i, fcurve in enumerate(fcurves):
            kp = fcurve.keyframe_points.insert(frame, value[i], options={"FAST"})
            kp.interpolation = blender_interp
            if blender_interp == "BEZIER":
                kp.handle_left_type = "AUTO_CLAMPED"
                kp.handle_right_type = "AUTO_CLAMPED"

    for fcurve in fcurves:
        fcurve.update()


def _looped_samples(raw_samples, hold_last, duration):
    """Se a animação for cíclica (holdLastKeyframe == False) e o
    arquivo declarar "duration", adiciona uma amostra sintética no
    final do canal (tempo = duration) com o mesmo valor da primeira
    amostra.

    Sem isso, cada bone fica preso (extrapolação constante) na pose do
    seu próprio último keyframe -- e como bones diferentes terminam em
    tempos diferentes, o resultado é uma combinação de poses que nunca
    existiu de verdade: um clipe com holdLastKeyframe=false deve fechar
    o ciclo voltando suavemente pra pose inicial, não congelar.

    No-op se: hold_last for True, não houver "duration", o canal
    estiver vazio, ou o último tempo real já for >= duration."""
    if hold_last or not raw_samples or duration is None:
        return raw_samples
    if raw_samples[-1]["time"] >= duration:
        return raw_samples
    wrap_sample = {
        "time": duration,
        "delta": raw_samples[0]["delta"],
        "interpolationType": raw_samples[0].get("interpolationType", RAW_INTERPOLATION_DEFAULT),
    }
    return raw_samples + [wrap_sample]


# --- Modo Bake: avalia o canal fora do sistema de F-Curve do Blender ---
#
# Reamostra em cada unidade inteira de tempo do arquivo usando uma
# Hermite cúbica com tangentes tipo Catmull-Rom. Um simples ease-in/out
# por trecho (versão anterior) zera a velocidade nas duas pontas de
# cada trecho -- a animação "para" um instante em todo keyframe, o que
# fica muito óbvio na costura de um loop, onde se espera continuidade
# total.
#
# A correção: a tangente em cada ponto interno olha os dois vizinhos
# (diferença central, com o espaçamento real de tempo entre eles) --
# mantém velocidade contínua atravessando cada keyframe. Num canal
# cíclico, a costura (primeiro ponto == último ponto) é tratada como só
# mais um ponto interno, usando o penúltimo e o segundo ponto como
# vizinhos -- fecha o loop com velocidade contínua também ali. Pontas
# de um trecho não cíclico ficam com tangente zero (desacelera até
# parar -- correto pra um clipe que realmente começa/termina).
#
# Também resolve, de quebra, rotation_quaternion ser 4 F-Curves
# independentes (w,x,y,z) interpoladas por componente no Blender, sem
# noção de rotação -- aqui a mesma conta de Hermite trata (w,x,y,z)
# como um Vector 4D, não uma geodésica perfeita (o correto seria Squad,
# não implementado aqui), mas já melhora sobre o comportamento nativo,
# com continuidade de velocidade corrigida na costura.


def _sign_consistent_quats(samples):
    """Lê "delta" de cada sample como Quaternion e corrige o problema
    do "duplo-cover" (q e -q representam a mesma rotação, mas
    interpolar sem alinhar o sinal pega a volta longa): inverte o sinal
    se estiver do lado errado em relação ao anterior. Devolve como
    Vector 4D (w,x,y,z) -- forma genérica que a matemática de Hermite
    abaixo (compartilhada com posição) sabe manipular."""
    quats = [quat_xyzw(s.get("delta", {"w": 1.0})) for s in samples]
    for i in range(1, len(quats)):
        if quats[i].dot(quats[i - 1]) < 0:
            quats[i] = Quaternion((-quats[i].w, -quats[i].x, -quats[i].y, -quats[i].z))
    return [Vector((q.w, q.x, q.y, q.z)) for q in quats]


def _vec4_to_quat(v):
    q = Quaternion((v[0], v[1], v[2], v[3]))
    q.normalize()
    return q


def _catmull_rom_tangents(times, values, cyclic):
    """Tangente em cada ponto de controle -- None nas pontas de um
    trecho não cíclico (vira tangente zero em _hermite_resample).

    A costura de um trecho cíclico (índice 0 e -1: mesma pose) usa uma
    única fórmula compartilhada pros dois, com o tempo desdobrado por
    só um período (`span`) de cada vez -- não dois (deslocar os dois
    vizinhos ao mesmo tempo dobraria o span no denominador). Usar a
    mesma fórmula pros dois lados garante tangente idêntica na costura,
    por construção -- é isso que garante continuidade de velocidade
    ali, não só o valor batendo."""
    n = len(values)
    tangents = [None] * n
    for i in range(1, n - 1):
        dt = times[i + 1] - times[i - 1]
        if dt != 0:
            tangents[i] = (values[i + 1] - values[i - 1]) * (1.0 / dt)
    if cyclic and n > 2:
        span = times[-1] - times[0]
        dt = (times[1] + span) - times[-2]
        if dt != 0:
            edge_tangent = (values[1] - values[-2]) * (1.0 / dt)
            tangents[0] = edge_tangent
            tangents[-1] = edge_tangent
    return tangents


def _hermite(p0, p1, m0, m1, dt, t):
    """Hermite cúbico padrão -- m0/m1 são tangentes "por unidade de
    tempo do arquivo", escaladas aqui por `dt` (duração real deste
    trecho) pra virar "por trecho inteiro"."""
    t2, t3 = t * t, t * t * t
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    return p0 * h00 + m0 * (dt * h10) + p1 * h01 + m1 * (dt * h11)


def _hermite_resample(times, values, start_frame, fps, cyclic):
    """Reamostra (times, values) em cada unidade inteira de tempo do
    arquivo, retornando [(frame, valor, 'linear'), ...]. `values` já
    deve estar no espaço certo (Vector em unidades Blender pra posição;
    Vector 4D já com sinal corrigido pra orientação)."""
    if not values:
        return []
    if len(values) == 1:
        return [(hytale_time_to_frame(times[0], start_frame, fps), values[0], "linear")]

    tangents = _catmull_rom_tangents(times, values, cyclic)
    zero = values[0] * 0.0
    tangents = [zero if m is None else m for m in tangents]

    t0, t1 = times[0], times[-1]
    result = []
    seg = 0
    for t in range(t0, t1 + 1):
        while seg < len(times) - 2 and t > times[seg + 1]:
            seg += 1
        a, b = seg, seg + 1
        dt = times[b] - times[a]
        local_t = 0.0 if dt == 0 else (t - times[a]) / dt
        value = _hermite(values[a], values[b], tangents[a], tangents[b], dt, local_t)
        result.append((hytale_time_to_frame(t, start_frame, fps), value, "linear"))
    return result


def _armature_unit_scale(armature_obj):
    """Escala do delta de posição pra ESTA Armature -- Prop (32/bloco)
    usa o dobro de Character (64/bloco), mesmo contrato do importer/
    exporter (ver MODEL_FORMAT_* / effective_unit_scale em common.py)."""
    return effective_unit_scale(UNIT_SCALE_DEFAULT, armature_model_format(armature_obj))


def _bake_position_samples(samples, start_frame, fps, cyclic, unit_scale=UNIT_SCALE_DEFAULT):
    times = [s["time"] for s in samples]
    values = [vec3(s.get("delta", {})) * unit_scale for s in samples]
    return _hermite_resample(times, values, start_frame, fps, cyclic)


def _bake_orientation_samples(samples, start_frame, fps, cyclic):
    times = [s["time"] for s in samples]
    values = _sign_consistent_quats(samples)
    baked = _hermite_resample(times, values, start_frame, fps, cyclic)
    return [(frame, _vec4_to_quat(v), interp) for frame, v, interp in baked]


def _bake_stretch_samples(samples, start_frame, fps, cyclic):
    """Mesmo motor Hermite/Catmull-Rom, mas sem aplicar
    UNIT_SCALE_DEFAULT -- "shapeStretch" é um fator de escala
    adimensional, não uma medida de comprimento. Eixo ausente assume
    1.0 (identidade), não 0.0."""
    times = [s["time"] for s in samples]
    values = [vec3(s.get("delta", {}), default=1.0) for s in samples]
    return _hermite_resample(times, values, start_frame, fps, cyclic)


def _apply_stretch_channels(operator, armature_obj, action, node_animations, hold_last, duration, start_frame, fps, bake_mode):
    """Aplica o canal "shapeStretch" (escala do bone), independente do
    target_mode -- chamada por ambos _apply_org_mode e _apply_ctrl_mode,
    sempre por último, na mesma action.

    Em qual bone escrever não depende do target_mode, e sim de o rig
    existir ou não: _build_pose_constraints (rigger) faz o ORG copiar a
    escala do MCH, que copia a escala do _CTRL -- numa Armature rigada,
    escrever pbone.scale direto no ORG é sobrescrito pela constraint. Se
    o bone tiver um `_CTRL` correspondente, escrevemos nele; senão
    caímos pro ORG direto. Esse fallback faz o import funcionar tanto
    numa Armature crua quanto numa já rigada."""
    pose_bones = armature_obj.pose.bones
    written_names = []
    max_frame_seen = start_frame
    for name, channels in node_animations.items():
        ctrl_name = control_name(armature_obj.data, name, SUFFIX_CTRL)
        target_name = ctrl_name if ctrl_name in pose_bones else name
        pbone = pose_bones.get(target_name)
        if pbone is None:
            continue
        stretch_raw = _looped_samples(channels.get("shapeStretch", []), hold_last, duration)
        if not stretch_raw:
            continue

        if bake_mode:
            stretch_samples = _bake_stretch_samples(stretch_raw, start_frame, fps, cyclic=not hold_last)
        else:
            stretch_samples = [
                (
                    hytale_time_to_frame(s["time"], start_frame, fps),
                    vec3(s.get("delta", {}), default=1.0),
                    s.get("interpolationType", INTERPOLATION_DEFAULT),
                )
                for s in stretch_raw
            ]
        _write_channel(
            action,
            armature_obj,
            f'pose.bones["{target_name}"].scale',
            target_name,
            3,
            stretch_samples,
        )
        written_names.append(target_name)
        max_frame_seen = max(max_frame_seen, max(f for f, _, _ in stretch_samples))
    return written_names, max_frame_seen


def _stamp_action_source_metadata(action, data):
    """Grava "duration" e "holdLastKeyframe" do arquivo original como
    custom properties na Action, pro exporter.py poder reescrever esses
    campos fielmente num reexport, em vez de adivinhar a partir do
    estado atual da timeline/F-Curves (que pode divergir)."""
    duration = data.get("duration")
    if duration is not None:
        action[ACTION_SOURCE_DURATION_PROP] = duration
    action[ACTION_SOURCE_HOLD_LAST_KEYFRAME_PROP] = bool(data.get("holdLastKeyframe", False))


def _apply_org_mode(
    operator, context, armature_obj, data, start_frame, action_name, loop_mode, bake_mode, keep_spine_follow,
    spine_mode="DEFAULT", arms_mode="BOTH", legs_mode="BOTH",
):
    """Modo ORG: keyframa os bones originais direto, sem passar por
    nenhuma camada de controle -- delta_local == matrix_basis nesse
    caso (sem constraint por cima), então só desfazemos a conversão que
    compute_deltas() fez, sem precisar de rest_matrices/pose_matrices.

    keep_spine_follow e os 3 argumentos de Target=Controllers não se
    aplicam a este modo -- recebidos só pra manter a assinatura igual à
    de _apply_ctrl_mode (o dispatch chama todo handler com os mesmos
    argumentos)."""
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base

    # O .blockyanim é fixo em FPS_HYTALE (60). A conversão é
    # matematicamente correta em qualquer FPS da cena (preserva a
    # duração real), mas só é 1:1 com os números do arquivo a 60 FPS --
    # em FPS menor, a animação acaba cabendo num espaço bem menor de
    # frames do Blender do que os números do arquivo sugerem (parece
    # "cortada", mas só ficou compactada).
    _warn_if_fps_mismatch(operator, fps)

    node_animations = _remap_renamed_bone_names(armature_obj, data["nodeAnimations"])
    hold_last, duration, _cyclic = _resolve_loop_settings(data, loop_mode)

    existing_names, missing_names = collect_target_bone_names(armature_obj, node_animations)

    if not existing_names:
        operator.report(
            {"ERROR"},
            "None of the bones in this .blockyanim exist on the selected armature -- wrong file or "
            "wrong armature?",
        )
        return {"CANCELLED"}

    action = bpy.data.actions.new(action_name)
    anim_data = armature_obj.animation_data_create()
    anim_data.action = action
    _stamp_action_source_metadata(action, data)

    pose_bones = armature_obj.pose.bones
    unit_scale = _armature_unit_scale(armature_obj)
    bones_with_rotation = set()
    max_frame_seen = start_frame
    warned_rotation_mode = set()

    for name in existing_names:
        channels = node_animations[name]
        pbone = pose_bones[name]
        group_name = name

        pos_raw = _looped_samples(channels.get("position", []), hold_last, duration)
        if pos_raw:
            if bake_mode:
                pos_samples = _bake_position_samples(
                    pos_raw, start_frame, fps, cyclic=not hold_last, unit_scale=unit_scale
                )
            else:
                pos_samples = [
                    (
                        hytale_time_to_frame(s["time"], start_frame, fps),
                        vec3(s.get("delta", {})) * unit_scale,
                        s.get("interpolationType", INTERPOLATION_DEFAULT),
                    )
                    for s in pos_raw
                ]
            _write_channel(
                action,
                armature_obj,
                f'pose.bones["{name}"].location',
                group_name,
                3,
                pos_samples,
            )
            max_frame_seen = max(max_frame_seen, max(f for f, _, _ in pos_samples))

        rot_raw = _looped_samples(channels.get("orientation", []), hold_last, duration)
        if rot_raw:
            # rotation_quaternion precisa desse modo pra as F-Curves
            # w,x,y,z baterem -- avisa se o bone estava noutro modo
            # (Euler/Axis Angle), já que isso muda como o bone é posado
            # em qualquer outra Action que já exista nele.
            _ensure_quaternion_rotation(operator, pbone, warned_rotation_mode)
            bones_with_rotation.add(name)

            if bake_mode:
                rot_samples = _bake_orientation_samples(rot_raw, start_frame, fps, cyclic=not hold_last)
            else:
                rot_samples = [
                    (
                        hytale_time_to_frame(s["time"], start_frame, fps),
                        quat_xyzw(s.get("delta", {"w": 1.0})),
                        s.get("interpolationType", INTERPOLATION_DEFAULT),
                    )
                    for s in rot_raw
                ]
            _write_channel(
                action,
                armature_obj,
                f'pose.bones["{name}"].rotation_quaternion',
                group_name,
                4,
                rot_samples,
            )
            max_frame_seen = max(max_frame_seen, max(f for f, _, _ in rot_samples))

    stretch_names, stretch_max_frame = _apply_stretch_channels(
        operator, armature_obj, action, node_animations, hold_last, duration, start_frame, fps, bake_mode
    )
    max_frame_seen = max(max_frame_seen, stretch_max_frame)

    _extend_scene_frame_end(operator, scene, max_frame_seen)

    if missing_names:
        operator.report(
            {"WARNING"},
            f"{len(missing_names)} bone(s) from the file don't exist on this armature and were "
            f"skipped (expected when importing onto a different creature/character): "
            f"{', '.join(sorted(missing_names)[:8])}"
            + ("..." if len(missing_names) > 8 else ""),
        )

    operator.report(
        {"INFO"},
        f"Imported '{action.name}' onto {len(existing_names)} bone(s) "
        f"({len(bones_with_rotation)} with rotation, {len(stretch_names)} with shape stretch).",
    )
    return {"FINISHED"}


# --- Modo CTRL_FK ---
#
# Diferente do modo ORG, aqui o _CTRL pode ter um parent diferente do
# ORG correspondente (CTRL_PARENT_OVERRIDES) -- delta_local sozinho não
# basta. Precisamos calcular a matriz de mundo pretendida de cada bone
# ORG (andando a hierarquia ORG, pai por pai) e reprojetar no espaço
# local do pai real do _CTRL no Blender (lido de pose_bone.parent, sem
# precisar saber as regras de CTRL_PARENT_OVERRIDES aqui):
#
#   world_target(bone)  = world_target(pai ORG) @ rest_local(bone) @ delta_local(bone)
#   ctrl_local           = world_target(pai REAL do _CTRL)⁻¹ @ world_target(bone)
#   ctrl_matrix_basis     = rest_local(_CTRL)⁻¹ @ ctrl_local
#
# Só faz sentido calculado um frame inteiro de cada vez (a composição
# pai->filho depende do frame) -- por isso este modo sempre gera
# keyframes densos (um por frame), reaproveitando o mesmo motor
# Hermite/Catmull-Rom do modo Bake, mas resolvendo um valor por vez em
# cada frame. "Bake to Every Frame" não se aplica aqui -- não existe
# versão esparsa deste modo.


def _rest_local_matrix(pbone):
    """Matriz de repouso (local, relativa ao pai) de um pose bone --
    mesma convenção do exporter.py: bone sem pai, local == armature space."""
    bone = pbone.bone
    if pbone.parent is None:
        return bone.matrix_local.copy()
    return pbone.parent.bone.matrix_local.inverted() @ bone.matrix_local


def _org_hierarchy(armature_obj):
    """Lista de (nome, nome_do_pai_ORG_ou_None, rest_local) de todos os
    bones ORG (identificados por não terem PROP_RIG_LAYER), em ordem de
    profundidade (pai sempre antes do filho)."""
    pose_bones = armature_obj.pose.bones
    org_names = {pb.name for pb in pose_bones if PROP_RIG_LAYER not in pb.bone.keys()}

    entries = {}
    for name in org_names:
        pb = pose_bones[name]
        parent_name = pb.parent.name if (pb.parent is not None and pb.parent.name in org_names) else None
        entries[name] = (parent_name, _rest_local_matrix(pb))

    depth = {}

    def get_depth(name):
        if name in depth:
            return depth[name]
        parent_name = entries[name][0]
        d = 0 if parent_name is None else get_depth(parent_name) + 1
        depth[name] = d
        return d

    for name in entries:
        get_depth(name)

    return [(name, entries[name][0], entries[name][1]) for name in sorted(entries, key=lambda n: depth[n])]


def _bake_delta_lookup(pos_raw, rot_raw, start_frame, fps, cyclic, unit_scale=UNIT_SCALE_DEFAULT):
    """Pré-calcula, pra um bone, uma função lookup(frame) -> Matrix do
    delta_local (posição+rotação) -- fora do range coberto por cada
    canal, mantém constante o valor da ponta mais próxima. Reaproveita
    o motor de bake (mesmo cálculo do modo ORG com Bake ligado, aqui
    sempre obrigatório).

    Usa um dict (não lista indexada) porque tempo-do-arquivo -> frame
    do Blender só é 1-pra-1 contíguo a 60 FPS -- em outro FPS,
    hytale_time_to_frame pode pular frames (FPS > 60) ou colapsar
    vários tempos no mesmo frame (FPS < 60)."""
    pos_list = _bake_position_samples(pos_raw, start_frame, fps, cyclic, unit_scale) if pos_raw else []
    rot_list = _bake_orientation_samples(rot_raw, start_frame, fps, cyclic) if rot_raw else []
    pos_by_frame = {f: v for f, v, _ in pos_list}
    rot_by_frame = {f: v for f, v, _ in rot_list}
    pos_bounds = (pos_list[0][0], pos_list[-1][0]) if pos_list else None
    rot_bounds = (rot_list[0][0], rot_list[-1][0]) if rot_list else None

    def _nearest(by_frame, frame):
        value = by_frame.get(frame)
        if value is not None:
            return value
        # FPS da cena != 60: este frame pode não coincidir com nenhuma
        # amostra bakeada -- usa a mais próxima em vez de KeyError.
        nearest_frame = min(by_frame, key=lambda k: abs(k - frame))
        return by_frame[nearest_frame]

    def lookup(frame):
        pos = Vector((0.0, 0.0, 0.0))
        if pos_bounds:
            clamped = min(max(frame, pos_bounds[0]), pos_bounds[1])
            pos = _nearest(pos_by_frame, clamped)
        quat = Quaternion((1.0, 0.0, 0.0, 0.0))
        if rot_bounds:
            clamped = min(max(frame, rot_bounds[0]), rot_bounds[1])
            quat = _nearest(rot_by_frame, clamped)
        return Matrix.Translation(pos) @ quat.to_matrix().to_4x4()

    return lookup


# --- Helpers compartilhados por CTRL_FK/IK/BOTH ---
# Os três modos fazem a mesma preparação (FPS, loop, hierarquia ORG +
# delta_lookup, Action), a mesma reprojeção por bone e o mesmo pós-
# processamento -- extraído aqui pra não manter cópias quase idênticas.


def _warn_if_fps_mismatch(operator, fps):
    """Aviso compartilhado pelos 4 modos -- um FPS de cena != FPS_HYTALE
    ainda é matematicamente correto, só não é 1:1 com os números do arquivo."""
    if round(fps) != FPS_HYTALE:
        operator.report(
            {"WARNING"},
            f"Scene is at {fps:g} FPS, not {FPS_HYTALE}. The animation's timing will be scaled "
            f"to match real-world duration, but will occupy far fewer Blender frames than the "
            f"file's 'time' numbers suggest -- set Output Properties > Frame Rate to {FPS_HYTALE} "
            f"for an exact 1:1 match with the .blockyanim file.",
        )


def _resolve_loop_settings(data, loop_mode):
    """loop_mode escolhido pelo usuário sobrescreve o que o arquivo diz
    (holdLastKeyframe) -- "AUTO" é o único que lê o arquivo;
    "CYCLE"/"ONE_SHOT" forçam independente do que o arquivo declara.
    Devolve (hold_last, duration, cyclic)."""
    if loop_mode == "CYCLE":
        hold_last = False
    elif loop_mode == "ONE_SHOT":
        hold_last = True
    else:  # "AUTO"
        hold_last = bool(data.get("holdLastKeyframe", False))
    duration = data.get("duration")
    return hold_last, duration, not hold_last


_ReprojectionSetup = namedtuple(
    "_ReprojectionSetup",
    ["scene", "fps", "hierarchy", "delta_lookup", "end_frame", "action", "pose_bones"],
)


def _prepare_reprojection_setup(operator, context, armature_obj, data, start_frame, action_name, loop_mode):
    """Preparação compartilhada por CTRL_FK/IK/BOTH: valida FPS,
    resolve hold_last/duration/cyclic, monta a hierarquia ORG + um
    lookup(frame) de delta_local por bone, calcula end_frame e cria a
    Action. Devolve None (já reportando ERROR) se nenhum bone do
    arquivo existir como ORG."""
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base
    _warn_if_fps_mismatch(operator, fps)

    node_animations = _remap_renamed_bone_names(armature_obj, data["nodeAnimations"])
    hold_last, duration, cyclic = _resolve_loop_settings(data, loop_mode)

    hierarchy = _org_hierarchy(armature_obj)
    org_names_in_file = [name for name, _, _ in hierarchy if name in node_animations]
    if not org_names_in_file:
        operator.report(
            {"ERROR"},
            "None of the bones in this .blockyanim exist as original (ORG) bones on this "
            "armature -- wrong file, wrong armature, or the rig hasn't been generated yet?",
        )
        return None

    # Lookup(frame) -> Matrix do delta_local, por bone ORG do arquivo, e
    # o frame mais alto coberto por cada um (pro range global).
    delta_lookup = {}
    max_time = 0
    for name in org_names_in_file:
        channels = node_animations[name]
        for ch in ("position", "orientation"):
            for s in channels.get(ch, []):
                max_time = max(max_time, s["time"])
        pos_raw = _looped_samples(channels.get("position", []), hold_last, duration)
        rot_raw = _looped_samples(channels.get("orientation", []), hold_last, duration)
        delta_lookup[name] = _bake_delta_lookup(
            pos_raw, rot_raw, start_frame, fps, cyclic, _armature_unit_scale(armature_obj)
        )
    if cyclic and duration is not None:
        max_time = max(max_time, duration)
    end_frame = hytale_time_to_frame(max_time, start_frame, fps)

    action = bpy.data.actions.new(action_name)
    anim_data = armature_obj.animation_data_create()
    anim_data.action = action

    return _ReprojectionSetup(
        scene=scene,
        fps=fps,
        hierarchy=hierarchy,
        delta_lookup=delta_lookup,
        end_frame=end_frame,
        action=action,
        pose_bones=armature_obj.pose.bones,
    )


def _compute_world_targets(hierarchy, delta_lookup, frame):
    """Anda a hierarquia ORG inteira (pai antes de filho) pra um único
    frame, devolvendo {nome_org: Matrix de mundo pretendida}."""
    world_target = {}
    for name, parent_name, rest_local in hierarchy:
        delta = delta_lookup[name](frame) if name in delta_lookup else Matrix.Identity(4)
        parent_world = world_target[parent_name] if parent_name is not None else Matrix.Identity(4)
        world_target[name] = parent_world @ rest_local @ delta
    return world_target


def _get_rest_local(pbone, rest_cache):
    """Cache compartilhado de _rest_local_matrix, indexado por nome de
    pose bone."""
    if pbone.name not in rest_cache:
        rest_cache[pbone.name] = _rest_local_matrix(pbone)
    return rest_cache[pbone.name]


def _resolve_parent_world(parent, world_target, rest_cache, pose_bones):
    """Matriz de mundo do parent real (no Blender) de um bone de
    controle/pole/ik-tip, pra reprojeção genérica de
    _resolve_matrix_basis. Três casos:

    1) Parent termina em SUFFIX_CTRL e o ORG correspondente está no
       world_target -- usa a pose animada desse ORG. Se esse _CTRL pai
       tiver um bridge `_MCH_Transfer` (todo _CTRL tem um hoje), a pose
       real dele não é world_target[org_name] direto -- é esse valor
       com a mesma correção "@ bridge_rest.inverted()" de
       _resolve_ctrl_matrix_basis (ver lá a derivação). Pra um _CTRL
       "normal" (rest igual à do bridge), essa correção vira Identity
       e não muda nada -- só onde a rest do _CTRL foi desviada da rest
       do bridge (hoje, só a cadeia Tail) o termo faz diferença. Sem
       isso, cada segmento de uma cauda encadeada herdaria a
       referência errada do segmento anterior e o erro se acumularia
       bone a bone.
    2) Parent termina em SUFFIX_MCH (idem, sem essa correção -- o MCH
       nunca é escrito direto por este importador, converge pro
       world_target via constraint em runtime) -- caso de attachments/
       filhos de ponta de cadeia que o rigger reparenta pro _MCH em vez
       do _CTRL (dedos, sockets de arma): _MCH reflete o resultado
       final tanto em FK quanto em IK.
    3) Nenhum dos dois bateu (bone utilitário como root.pelvis_CTRL, ou
       _CTRL/_MCH de um bone ORG fora do arquivo) -- assume que não
       está sendo animado por nada neste import, usa a pose atual dele
       no Blender como referência fixa."""
    if parent is None:
        return Matrix.Identity(4)
    for suffix in (SUFFIX_CTRL, SUFFIX_MCH):
        if parent.name.endswith(suffix):
            # source_org_of: o _CTRL pode ter nome de APELIDO (Rename "Only
            # CTRL") -- a marca de origem diz o ORG de verdade; sem marca
            # (rig antigo, root.pelvis_CTRL) cai pro nome sem sufixo.
            org_name = source_org_of(parent)
            if org_name in world_target:
                target = world_target[org_name]
                if suffix == SUFFIX_CTRL:
                    bridge_pbone = pose_bones.get(org_name + SUFFIX_MCH_TRANSFER)
                    if bridge_pbone is not None:
                        bridge_rest = _get_rest_local(bridge_pbone, rest_cache)
                        return target @ bridge_rest.inverted()
                return target
    return parent.matrix.copy()


def _resolve_matrix_basis(pbone, world_matrix, world_target, rest_cache, pose_bones):
    """matrix_basis que faz `pbone` ocupar `world_matrix` no espaço de
    mundo, reprojetando através do parent real dele no Blender. Não
    usar pra ik_tip -- ver _resolve_ik_tip_matrix_basis."""
    rest_local = _get_rest_local(pbone, rest_cache)
    parent_world = _resolve_parent_world(pbone.parent, world_target, rest_cache, pose_bones)
    local = parent_world.inverted() @ world_matrix
    return rest_local.inverted() @ local


def _resolve_ctrl_matrix_basis(ctrl_pbone, org_name, world_matrix, world_target, rest_cache, pose_bones):
    """Wrapper de _resolve_matrix_basis pra um bone `_CTRL` -- igual à
    versão genérica na maioria dos casos, exceto quando esse _CTRL tem
    um bridge `_MCH_Transfer` como filho real com rest DESVIADA da
    própria (hoje só acontece na cadeia Tail, redirecionada pro head do
    próximo segmento) -- nesse caso é o bridge quem precisa bater com a
    pose-alvo (é ele que o MCH copia, não o _CTRL direto). Mesmo
    princípio de _resolve_ik_tip_matrix_basis: aquela fórmula genérica
    assume que a rest do bone bate com a orientação do que ele
    representa visualmente, o que não é verdade aqui.

    Derivação (espaço de armature): bridge.matrix = ctrl.matrix @
    rest_local(bridge) (bridge sem pose própria), e ctrl.matrix =
    parent_world @ rest_local(ctrl) @ matrix_basis. Querendo
    bridge.matrix == world_matrix:

        matrix_basis = rest_local(ctrl)⁻¹ @ parent_world⁻¹ @ world_matrix @ rest_local(bridge)⁻¹

    É a fórmula genérica de _resolve_matrix_basis com "@ rest_local(bridge)⁻¹"
    a mais. Pra um _CTRL "normal" (rest igual à do bridge), esse termo
    dá Identity e a correção vira no-op. Importante: como esse _CTRL
    mesmo não fica em world_matrix nos casos onde a rest diverge
    (Tail), qualquer filho dele (próximo segmento) precisa saber disso
    também ao calcular sua própria referência de pai -- ver a mesma
    correção espelhada em _resolve_parent_world."""
    bridge_pbone = pose_bones.get(org_name + SUFFIX_MCH_TRANSFER)
    if bridge_pbone is None:
        return _resolve_matrix_basis(ctrl_pbone, world_matrix, world_target, rest_cache, pose_bones)
    ctrl_rest = _get_rest_local(ctrl_pbone, rest_cache)
    parent_world = _resolve_parent_world(ctrl_pbone.parent, world_target, rest_cache, pose_bones)
    bridge_rest = _get_rest_local(bridge_pbone, rest_cache)
    local = parent_world.inverted() @ world_matrix
    return ctrl_rest.inverted() @ local @ bridge_rest.inverted()


def _resolve_ik_tip_matrix_basis(ik_pbone, org_rest_world, world_matrix, rest_cache):
    """A ponta de uma cadeia IK (_IK) tem rest orientation própria,
    diferente da do ORG correspondente (o rigger ajusta tail/roll dela
    pra apontar pra baixo ou pro socket de attachment). Por isso não dá
    pra reprojetar direto com _resolve_matrix_basis -- aquela fórmula
    assume que a rest do bone bate com a orientação que ele representa,
    o que não é verdade aqui.

    A ponte real (bridge, _MCH_IK_Transfer) é filha de verdade do _IK
    (parent real), mas com a rest do ORG -- introduz uma conjugação
    entre as duas rests que precisa ser desfeita. Derivação: querendo
    bridge.world == world_matrix, com bridge.world = ik.world @
    (ik_rest⁻¹ @ org_rest_world) e ik.world = ik_rest @ matrix_basis
    (sem parent):

        matrix_basis = ik_rest⁻¹ @ world_matrix @ org_rest_world⁻¹ @ ik_rest"""
    ik_rest = _get_rest_local(ik_pbone, rest_cache)  # sem parent -- já é a rest de mundo
    return ik_rest.inverted() @ world_matrix @ org_rest_world.inverted() @ ik_rest


def _compute_pole_world_matrix(chain, world_target):
    """Réplica da mesma fórmula geométrica que o rigger usa pra
    posicionar o pole na geração do rig (offset a partir do eixo Z do
    bone de referência do meio da cadeia), com a orientação animada em
    vez da rest (pole_angle calibrado em cima dela). None se o bone de
    referência não estiver no world_target deste frame."""
    pole_ref_world = world_target.get(chain["pole_ref"])
    if pole_ref_world is None:
        return None
    z_axis_world = pole_ref_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
    if z_axis_world.length < 1e-9:
        z_axis_world = Vector((0.0, 0.0, 1.0))
    z_axis_world.normalize()
    sign = 1.0 if chain["pole_invert"] else -1.0
    pole_world_pos = pole_ref_world.translation + z_axis_world * (chain["pole_distance"] * sign)
    return Matrix.Translation(pole_world_pos)


def _ensure_quaternion_rotation(operator, pbone, warned_set):
    """Força rotation_mode='QUATERNION' e avisa uma vez por bone se
    estava em outro modo -- muda como qualquer outra Action nesse bone
    é posada, vale avisar."""
    if pbone.rotation_mode == "QUATERNION":
        return
    if pbone.name not in warned_set:
        operator.report(
            {"WARNING"},
            f"Bone '{pbone.name}' rotation mode was '{pbone.rotation_mode}' -- switched to "
            f"'QUATERNION' to import orientation keyframes.",
        )
        warned_set.add(pbone.name)
    pbone.rotation_mode = "QUATERNION"


def _mute_constraints_on(pbones, muted_constraints):
    """Muta toda constraint ainda ativa em cada pbone -- genérico (não
    hardcoding nomes conhecidos do rigger), pra continuar funcionando
    mesmo que o rig mude. Usado tanto pra bones _CTRL com constraint
    extra (Belly_CTRL/Chest_CTRL seguindo root.spine_CTRL) quanto pros
    Child Of dos pole targets."""
    for pbone in pbones:
        if pbone is None:
            continue
        for con in pbone.constraints:
            if not con.mute:
                con.mute = True
                muted_constraints.append((pbone.name, con.name))


def _write_pose_samples(action, armature_obj, target_values):
    """Escreve, pra cada bone em `target_values`
    ({bone_name: [(frame, loc_ou_None, quat_ou_None), ...]}), as
    F-Curves de location e/ou rotation_quaternion -- um pole target,
    por exemplo, só tem loc (quat=None sempre, não passa por
    _resolve_matrix_basis pra rotação)."""
    for bone_name, samples in target_values.items():
        pos_samples = [(f, loc, "linear") for f, loc, _q in samples if loc is not None]
        rot_samples = [(f, quat, "linear") for f, _loc, quat in samples if quat is not None]
        if pos_samples:
            _write_channel(action, armature_obj, f'pose.bones["{bone_name}"].location', bone_name, 3, pos_samples)
        if rot_samples:
            _write_channel(
                action, armature_obj, f'pose.bones["{bone_name}"].rotation_quaternion', bone_name, 4, rot_samples
            )


def _extend_scene_frame_end(operator, scene, end_frame):
    """A cena (Frame End) pode estar mais curta que a animação
    importada -- sem esticar, o export (que sampleia dentro do range da
    cena) corta o final sem avisar. Só estica, nunca encolhe."""
    if scene.frame_end < end_frame:
        old_end = scene.frame_end
        scene.frame_end = end_frame
        operator.report(
            {"INFO"},
            f"Scene Frame End was {old_end}, extended to {end_frame} to fit the imported animation.",
        )


def _report_muted_constraints(operator, muted_constraints, note):
    """Relatório final de quais constraints extras foram mutadas."""
    if not muted_constraints:
        return
    affected_bones = sorted({bone_name for bone_name, _con_name in muted_constraints})
    operator.report(
        {"WARNING"},
        f"Muted {len(muted_constraints)} extra constraint(s) on {len(affected_bones)} bone(s) "
        f"{note} so the imported pose isn't blended with anything else -- left muted after "
        f"import; re-enable manually if you want that behavior back: "
        f"{', '.join(affected_bones[:8])}" + ("..." if len(affected_bones) > 8 else ""),
    )


# --- root.master_CTRL / root.pelvis_CTRL não derivam de nenhum ORG ---
#
# Não aparecem em world_target (só tem entradas pra bones da hierarquia
# ORG) e caem no fallback "pose atual/estática" de _resolve_parent_world.
# Como as animações do Hytale só mexem em Pelvis/Belly/Chest (nunca em
# nenhum "root.*"), root.master_CTRL/root.pelvis_CTRL ficam parados
# durante o import -- e tudo que pende deles (Pelvis_CTRL, L/R-Thigh_CTRL,
# Belly_CTRL) reprojeta contra essa base estática errada sempre que o
# personagem se desloca: o corpo fica "preso" na origem em vez de andar
# junto com o Pelvis.
#
# Fix (3 checkboxes independentes na UI): faz Pelvis "emprestar" sua
# pose de mundo animada (já em world_target["Pelvis"]) pros bones raiz
# escolhidos -- injetando ela em world_target sob a mesma chave que
# _resolve_parent_world já procura (nome do bone sem "_CTRL").
#
# Importante: quando root.master_CTRL efetivamente muda de pose,
# root.pelvis_CTRL (filho real dele, sem keyframe próprio) também se
# move na prática (herda rigidamente do pai) -- então o cálculo de
# Pelvis_CTRL/L-Thigh_CTRL/R-Thigh_CTRL (filhos de root.pelvis_CTRL)
# precisa assumir isso, não que ele fica parado, senão saem deslocados/
# amplificados. A correção: sempre que root.master_CTRL muda,
# propagamos o efeito pra root.pelvis_CTRL também, computando a pose
# efetiva que ele vai ter na prática e injetando ela em world_target
# (ver _propagate_root_pelvis abaixo). Por uma identidade básica de
# álgebra linear (A @ (A⁻¹ @ B) = B), isso garante que Pelvis_CTRL
# sempre acabe ocupando world_target["Pelvis"] exatamente.
#
# Pra qualquer outra função, root.master_CTRL/root.pelvis_CTRL passam a
# se comportar exatamente como o "_CTRL" de um bone ORG animado --
# nenhuma outra função precisa saber disso, só olham o nome do parent real.


def _pelvis_delta(pelvis_world, pelvis_rest_world):
    """Delta (translação + rotação) que o Pelvis sofreu desde a própria
    rest neste frame -- decompõe world_target["Pelvis"] de volta pra
    "o quanto ele se moveu", descartando a posição absoluta da rest do
    Pelvis (bem mais baixa que a de root.master_CTRL, que nasce na
    altura do Belly). Aplicar esse delta em cima da rest de qualquer
    outro bone preserva o offset original entre os dois -- é isso que
    faz um T-Pose (delta zero) não mudar nada nos bones raiz."""
    return pelvis_rest_world.inverted() @ pelvis_world


def _compose_delta_world(rest_world, delta, use_loc, use_rot):
    """rest_world @ delta, com a translação e/ou rotação do delta
    zeradas conforme os toggles."""
    d_loc, d_quat, _d_scale = delta.decompose()
    loc = d_loc if use_loc else Vector((0.0, 0.0, 0.0))
    quat = d_quat if use_rot else Quaternion()
    return rest_world @ (Matrix.Translation(loc) @ quat.to_matrix().to_4x4())


def _apply_root_follow(
    operator, frame, pose_bones, world_target, rest_cache, target_values, warned_rotation_mode,
    root_master_follow_loc, root_master_follow_rot, root_pelvis_follow_rot,
):
    """Chamada uma vez por frame, logo depois de `world_target` ser
    calculado e antes do loop que escreve os `_CTRL` -- pra quando o
    loop chegar em Pelvis_CTRL/Belly_CTRL/L-Thigh_CTRL/R-Thigh_CTRL
    (parent real root.pelvis_CTRL ou root.master_CTRL), a injeção já
    esteja em world_target e a reprojeção genérica saia certa sozinha.

      root_master_follow_loc/root_master_follow_rot -- independentes:
          root.master_CTRL soma o delta de translação/rotação do
          Pelvis em cima da própria rest (componente desligado fica na
          própria rest). Escreve keyframe só se pelo menos um dos dois
          estiver ligado.
      root_pelvis_follow_rot -- root.pelvis_CTRL soma a rotação (delta)
          do Pelvis em cima do que já herdou do master -- não existe
          opção de location pra este bone.

    Devolve True se conseguiu injetar/escrever algo neste frame."""
    # Pelvis = o bone marcado em "Pelvis" na entrada SPINE do Bone
    # Settings (o mesmo que o rigger usou pra montar root.pelvis_CTRL);
    # sem entrada SPINE, o nome legado "Pelvis".
    pelvis_name = resolve_pelvis_org_name(pose_bones.id_data.data)
    pelvis_world = world_target.get(pelvis_name)
    pelvis_pbone = pose_bones.get(pelvis_name)
    if pelvis_world is None or pelvis_pbone is None:
        return False  # rig/arquivo sem esse bone de Pelvis -- nada a fazer
    pelvis_delta = _pelvis_delta(pelvis_world, pelvis_pbone.bone.matrix_local)

    fired = False
    master_pbone = pose_bones.get(BONE_ROOT_MASTER)
    master_target_world = None  # None == master não foi tocado (fica na própria rest)

    if master_pbone is not None and (root_master_follow_loc or root_master_follow_rot):
        master_rest_world = master_pbone.bone.matrix_local
        master_target_world = _compose_delta_world(
            master_rest_world, pelvis_delta, root_master_follow_loc, root_master_follow_rot
        )
        world_target[BONE_ROOT_MASTER[: -len(SUFFIX_CTRL)]] = master_target_world
        matrix_basis = _resolve_matrix_basis(master_pbone, master_target_world, world_target, rest_cache, pose_bones)
        loc, quat, _scale = matrix_basis.decompose()
        _ensure_quaternion_rotation(operator, master_pbone, warned_rotation_mode)
        target_values.setdefault(master_pbone.name, []).append((frame, loc, quat))
        fired = True

    pelvis_ctrl_pbone = pose_bones.get(BONE_ROOT_PELVIS)
    if pelvis_ctrl_pbone is not None and (master_target_world is not None or root_pelvis_follow_rot):
        # Pose efetiva que root.pelvis_CTRL vai ter na prática, herdando
        # rigidamente do parent real (root.master_CTRL neste rig --
        # resolve genérico via _resolve_parent_world como salvaguarda).
        if master_target_world is not None and pelvis_ctrl_pbone.parent is master_pbone:
            parent_world_for_pelvis = master_target_world
        else:
            parent_world_for_pelvis = _resolve_parent_world(
                pelvis_ctrl_pbone.parent, world_target, rest_cache, pose_bones
            )
        pelvis_ctrl_rest_local = _get_rest_local(pelvis_ctrl_pbone, rest_cache)
        inherited_world = parent_world_for_pelvis @ pelvis_ctrl_rest_local

        if root_pelvis_follow_rot:
            # Soma só a rotação (delta) do Pelvis em cima do que já foi
            # herdado -- nunca a rotação absoluta, mesmo motivo de
            # _pelvis_delta (preservar a orientação já herdada em vez
            # de saltar pra a do Pelvis).
            pelvis_ctrl_target_world = _compose_delta_world(inherited_world, pelvis_delta, False, True)
        else:
            pelvis_ctrl_target_world = inherited_world

        world_target[BONE_ROOT_PELVIS[: -len(SUFFIX_CTRL)]] = pelvis_ctrl_target_world

        if root_pelvis_follow_rot:
            # Só precisa de keyframe próprio se tem pose própria de
            # verdade -- se for só herança rígida (root_pelvis_follow_rot=False),
            # matrix_basis fica identidade e o Blender já resolve certo.
            matrix_basis = _resolve_matrix_basis(
                pelvis_ctrl_pbone, pelvis_ctrl_target_world, world_target, rest_cache, pose_bones
            )
            quat = matrix_basis.decompose()[1]
            _ensure_quaternion_rotation(operator, pelvis_ctrl_pbone, warned_rotation_mode)
            target_values.setdefault(pelvis_ctrl_pbone.name, []).append((frame, None, quat))
        fired = True

    return fired


def _report_root_follow(operator, root_follow_enabled, root_follow_fired):
    """Aviso final se algum toggle de Root Follow estava ligado mas
    nunca chegou a injetar/escrever nada em nenhum frame."""
    if not root_follow_enabled or root_follow_fired:
        return
    operator.report(
        {"WARNING"},
        f"Root Follow was enabled but '{BONE_ROOT_MASTER}'/'{BONE_ROOT_PELVIS}' and/or the Pelvis bone "
        f"weren't found -- skipped, no keyframes written for the root control bone(s). Was the "
        f"rig generated with a version of rigger.py that has root.master_CTRL/root.pelvis_CTRL?",
    )


# Spine "Default (Root CTRL)" vs "Spine CTRL" traduz direto pros 3
# toggles de _apply_root_follow -- (loc, rot, pelvis_rot). "DEFAULT" é
# a combinação validada como melhor em testes reais; "MANUAL" desliga
# tudo (root.master_CTRL/root.pelvis_CTRL ficam parados, root.spine_CTRL
# livre pra ajuste manual).
_SPINE_MODE_ROOT_FOLLOW = {
    "DEFAULT": (True, True, False),
    "MANUAL": (False, False, False),
}


def _org_path(hierarchy, root_name, tip_name):
    """Caminho (lista de nomes, root->tip) andando a hierarquia ORG --
    mesma ideia de find_org_path() em rigger/helpers.py, só que sobre
    `hierarchy` (a mesma estrutura de _org_hierarchy()), sem precisar
    de Edit Mode durante o import."""
    if root_name == tip_name:
        return None
    children = {}
    for name, parent_name, _rest in hierarchy:
        if parent_name is not None:
            children.setdefault(parent_name, []).append(name)

    queue = deque([[root_name]])
    visited = {root_name}
    while queue:
        path = queue.popleft()
        node = path[-1]
        for child in children.get(node, []):
            if child in visited:
                continue
            new_path = path + [child]
            if child == tip_name:
                return new_path
            visited.add(child)
            queue.append(new_path)
    return None


def _resolve_ik_chains(armature_obj, hierarchy):
    """Lê armature.hytale_ik_chains e resolve cada item nos nomes de
    bone reais que vamos precisar -- mesma resolução que o rigger faz
    na geração do rig, devolvendo só nomes/valores (sem precisar de
    Edit Mode aqui).

    Só entradas ARM/LEG -- cadeias TAIL não têm IK nenhum (sem bone
    "_IK" nem "_Pole_CTRL"), sempre passam pelo caminho _CTRL normal,
    em qualquer configuração de Arms/Legs.

    `"group"` ("ARM"/"LEG") é o que permite a UI configurar Arms e Legs
    independentemente -- cada cadeia usa o modo do próprio grupo."""
    chains = []
    for item in armature_obj.data.hytale_ik_chains:
        if item.chain_type == "CHAIN":
            continue
        if not item.root_bone or not item.tip_bone:
            continue
        path = _org_path(hierarchy, item.root_bone, item.tip_bone)
        if not path or len(path) < 2:
            continue
        pole_ref_name = item.pole_bone if item.pole_bone else path[len(path) // 2]
        chains.append(
            {
                "label": item.label or item.root_bone,
                "group": "LEG" if item.chain_type == "LEG" else "ARM",
                "org_names": path,
                "ik_tip": control_name(armature_obj.data, path[-1], SUFFIX_IK),
                "pole": control_name(armature_obj.data, path[0], SUFFIX_POLE),
                "pole_ref": pole_ref_name,
                "pole_distance": item.pole_distance,
                "pole_invert": item.pole_invert,
            }
        )
    return chains


def _apply_ctrl_mode(
    operator, context, armature_obj, data, start_frame, action_name, loop_mode, bake_mode, keep_spine_follow,
    spine_mode="DEFAULT", arms_mode="BOTH", legs_mode="BOTH",
):
    """Target = Controllers -- Arms e Legs podem estar em modos
    diferentes ao mesmo tempo (ex.: braço em Control IK, perna em
    Default), cada grupo decide o próprio comportamento (chain["group"]).

    spine_mode -- "DEFAULT" ou "MANUAL" (ver _SPINE_MODE_ROOT_FOLLOW) --
        controla só root.master_CTRL/root.pelvis_CTRL. Pelvis/Belly/
        Chest são sempre keyframados normalmente.
    arms_mode/legs_mode -- "BOTH" (Default FK+IK), "CTRL_FK" (Control
        FK) ou "IK" (Control IK), aplicado independentemente por grupo:
          "BOTH"    -- cadeia recebe FK (todos os segmentos) e IK (ponta
                       + pole) ao mesmo tempo; fk_ik_switch fixo em FK.
          "CTRL_FK" -- só FK -- a cadeia nem recebe bone "_IK" nenhum.
          "IK"      -- só IK -- os _CTRL dos segmentos são pulados;
                       fk_ik_switch fixo em IK.
    Bones fora de qualquer cadeia sempre recebem FK, independente
    dessas 3 opções."""
    setup = _prepare_reprojection_setup(operator, context, armature_obj, data, start_frame, action_name, loop_mode)
    if setup is None:
        return {"CANCELLED"}
    scene, fps, hierarchy, delta_lookup, end_frame, action, pose_bones = setup
    _stamp_action_source_metadata(action, data)

    chains = _resolve_ik_chains(armature_obj, hierarchy)
    group_mode = {"ARM": arms_mode, "LEG": legs_mode}
    for chain in chains:
        chain["mode"] = group_mode.get(chain["group"], "BOTH")

    # Cadeias 100% IK pulam o loop de FK; as outras (BOTH/CTRL_FK)
    # passam por ele normalmente, igual bone fora de cadeia nenhuma.
    chain_bone_names_skip_fk = {
        name for chain in chains if chain["mode"] == "IK" for name in chain["org_names"]
    }
    # Só cadeias BOTH/IK recebem ponta (_IK) + pole.
    ik_chains = [chain for chain in chains if chain["mode"] in ("BOTH", "IK")]

    target_values = {}  # {bone_name: [(frame, loc_or_None, quat_or_None), ...]}
    rest_cache = {}
    warned_rotation_mode = set()

    # Muta constraints extras nos bones que vamos escrever via FK: bones
    # fora das cadeias 100% IK (ex.: Belly/Chest + SpineFollow), e os
    # poles de toda cadeia que vai receber IK (Child Of local/global).
    muted_constraints = []
    if not keep_spine_follow:
        _mute_constraints_on(
            (
                pose_bones.get(control_name(armature_obj.data, name, SUFFIX_CTRL))
                for name, _parent_name, _rest_local in hierarchy
                if name not in chain_bone_names_skip_fk
            ),
            muted_constraints,
        )
    _mute_constraints_on((pose_bones.get(chain["pole"]) for chain in ik_chains), muted_constraints)

    # fk_ik_switch: IK-only -> fixo em 1; BOTH -> fixo em 0 (default FK,
    # trocável depois); CTRL_FK-only nem entra em ik_chains.
    tip_org_rest_world = {}
    for chain in ik_chains:
        ik_pbone = pose_bones.get(chain["ik_tip"])
        if ik_pbone is not None:
            ik_pbone[PROP_FK_IK_SWITCH] = 1 if chain["mode"] == "IK" else 0
            tip_org_rest_world[chain["ik_tip"]] = pose_bones[chain["org_names"][-1]].bone.matrix_local.copy()

    root_master_follow_loc, root_master_follow_rot, root_pelvis_follow_rot = _SPINE_MODE_ROOT_FOLLOW[spine_mode]

    rigger_created_names = {
        name for name, _parent_name, _rest_local in hierarchy
        if pose_bones[name].bone.get(BONE_RIGGER_CREATED_PROP)
    }

    root_follow_fired = False
    for frame in range(start_frame, end_frame + 1):
        world_target = _compute_world_targets(hierarchy, delta_lookup, frame)

        if _apply_root_follow(
            operator, frame, pose_bones, world_target, rest_cache, target_values, warned_rotation_mode,
            root_master_follow_loc, root_master_follow_rot, root_pelvis_follow_rot,
        ):
            root_follow_fired = True

        # FK: todo bone fora das cadeias 100% IK.
        for name, _parent_name, _rest_local in hierarchy:
            if name in chain_bone_names_skip_fk:
                continue
            if name in rigger_created_names:
                # Root criado pelo Auto-Rigger (Origin automático / Root
                # "New Bone") nunca existe num .blockyanim -- sem keyframe,
                # fica livre como controle do usuário (world_target dele
                # continua valendo a rest pro cálculo dos filhos).
                continue
            ctrl_pbone = pose_bones.get(control_name(armature_obj.data, name, SUFFIX_CTRL))
            if ctrl_pbone is None:
                continue
            matrix_basis = _resolve_ctrl_matrix_basis(ctrl_pbone, name, world_target[name], world_target, rest_cache, pose_bones)
            loc, quat, _scale = matrix_basis.decompose()
            _ensure_quaternion_rotation(operator, ctrl_pbone, warned_rotation_mode)
            target_values.setdefault(ctrl_pbone.name, []).append((frame, loc, quat))

        # IK: ponta (mão/pé) + pole, só das cadeias BOTH/IK.
        for chain in ik_chains:
            tip_org_name = chain["org_names"][-1]
            ik_pbone = pose_bones.get(chain["ik_tip"])
            if ik_pbone is not None:
                matrix_basis = _resolve_ik_tip_matrix_basis(
                    ik_pbone, tip_org_rest_world[chain["ik_tip"]], world_target[tip_org_name], rest_cache
                )
                loc, quat, _scale = matrix_basis.decompose()
                _ensure_quaternion_rotation(operator, ik_pbone, warned_rotation_mode)
                target_values.setdefault(ik_pbone.name, []).append((frame, loc, quat))

            pole_pbone = pose_bones.get(chain["pole"])
            if pole_pbone is not None:
                pole_world_matrix = _compute_pole_world_matrix(chain, world_target)
                if pole_world_matrix is not None:
                    matrix_basis = _resolve_matrix_basis(pole_pbone, pole_world_matrix, world_target, rest_cache, pose_bones)
                    loc = matrix_basis.decompose()[0]
                    target_values.setdefault(pole_pbone.name, []).append((frame, loc, None))

    _write_pose_samples(action, armature_obj, target_values)

    # shapeStretch não faz parte da reprojeção FK/IK -- precisa só de
    # hold_last/duration, recalculado aqui (chamada pura e barata).
    hold_last, duration, _cyclic = _resolve_loop_settings(data, loop_mode)
    stretch_names, stretch_max_frame = _apply_stretch_channels(
        operator, armature_obj, action, data["nodeAnimations"], hold_last, duration, start_frame, fps, bake_mode
    )
    end_frame = max(end_frame, stretch_max_frame)

    _extend_scene_frame_end(operator, scene, end_frame)
    _report_muted_constraints(
        operator, muted_constraints, "(control bones with extra blend constraints, and IK pole targets' Child Of)"
    )
    _report_root_follow(operator, spine_mode == "DEFAULT", root_follow_fired)

    arm_chains = [chain for chain in chains if chain["group"] == "ARM"]
    leg_chains = [chain for chain in chains if chain["group"] == "LEG"]
    if arms_mode in ("BOTH", "IK") and not arm_chains:
        operator.report(
            {"WARNING"},
            "Arms is set to use IK, but no 'Arm'-type chain was found on this armature "
            "(armature.hytale_ik_chains) -- nothing written for arms via IK.",
        )
    if legs_mode in ("BOTH", "IK") and not leg_chains:
        operator.report(
            {"WARNING"},
            "Legs is set to use IK, but no 'Leg'-type chain was found on this armature "
            "(armature.hytale_ik_chains) -- nothing written for legs via IK.",
        )

    non_chain_ctrl_count = sum(
        1 for name in target_values if not any(name == chain["ik_tip"] or name == chain["pole"] for chain in chains)
    )
    mode_label = {"BOTH": "FK+IK", "CTRL_FK": "FK only", "IK": "IK only"}
    operator.report(
        {"INFO"},
        f"Imported '{action.name}' -- Spine: {'root controllers follow Pelvis' if spine_mode == 'DEFAULT' else 'Pelvis/Belly/Chest only, root.spine_CTRL free for manual tweaks'}; "
        f"Arms: {mode_label[arms_mode]} ({len(arm_chains)} chain(s)); "
        f"Legs: {mode_label[legs_mode]} ({len(leg_chains)} chain(s)); "
        f"{non_chain_ctrl_count} other control bone(s); {len(stretch_names)} bone(s) with shape "
        f"stretch; {end_frame - start_frame + 1} frame(s) each.",
    )
    return {"FINISHED"}


_MODE_HANDLERS = {
    "ORG": _apply_org_mode,
    "CTRL": _apply_ctrl_mode,
}

# Presets de "Frame Rate" -> (fps, fps_base), mesmos valores dos
# presets nativos do Blender -- os "quebrados" (23.98/29.97/59.94,
# convenção NTSC) não são o número redondo, e sim fps/fps_base (ex.:
# 23.98 é 24000/1001 = 23.976023...).
_FPS_PRESET_VALUES = {
    "6": (6, 1.0),
    "8": (8, 1.0),
    "12": (12, 1.0),
    "23.98": (24000, 1001.0),
    "24": (24, 1.0),
    "25": (25, 1.0),
    "29.97": (30000, 1001.0),
    "30": (30, 1.0),
    "50": (50, 1.0),
    "59.94": (60000, 1001.0),
    "60": (60, 1.0),
    "120": (120, 1.0),
    "240": (240, 1.0),
}


def _blockyanim_import_props(lang):
    return {
        "filter_glob": StringProperty(default="*.blockyanim", options={"HIDDEN"}),
        "target_mode": EnumProperty(
            name="Target",
            description=tr("anim_importer.prop.target_mode", lang),
            items=[
                (
                    "ORG",
                    "Original Bones",
                    tr("anim_importer.prop.target_mode_item_org", lang),
                ),
                (
                    "CTRL",
                    "Controllers",
                    tr("anim_importer.prop.target_mode_item_ctrl", lang),
                ),
            ],
            default="ORG",
        ),
        "action_name": StringProperty(
            name="Action Name",
            description=tr("anim_importer.prop.action_name", lang),
            default="",
        ),
        "start_frame": IntProperty(
            name="Start Frame",
            description=tr("anim_importer.prop.start_frame", lang),
            default=1,
        ),
        "import_fps_preset": EnumProperty(
            name="Frame Rate",
            description=tr("anim_importer.prop.import_fps_preset", lang),
            items=[
                ("6", "6", tr("anim_importer.prop.import_fps_preset_item_6", lang)),
                ("8", "8", tr("anim_importer.prop.import_fps_preset_item_8", lang)),
                ("12", "12", tr("anim_importer.prop.import_fps_preset_item_12", lang)),
                ("23.98", "23.98", tr("anim_importer.prop.import_fps_preset_item_23_98", lang)),
                ("24", "24", tr("anim_importer.prop.import_fps_preset_item_24", lang)),
                ("25", "25", tr("anim_importer.prop.import_fps_preset_item_25", lang)),
                ("29.97", "29.97", tr("anim_importer.prop.import_fps_preset_item_29_97", lang)),
                ("30", "30", tr("anim_importer.prop.import_fps_preset_item_30", lang)),
                ("50", "50", tr("anim_importer.prop.import_fps_preset_item_50", lang)),
                ("59.94", "59.94", tr("anim_importer.prop.import_fps_preset_item_59_94", lang)),
                ("60", "60", tr("anim_importer.prop.import_fps_preset_item_60", lang)),
                ("120", "120", tr("anim_importer.prop.import_fps_preset_item_120", lang)),
                ("240", "240", tr("anim_importer.prop.import_fps_preset_item_240", lang)),
                ("CUSTOM", "Custom", tr("anim_importer.prop.import_fps_preset_item_custom", lang)),
            ],
            default="60",
        ),
        "import_fps_custom_fps": IntProperty(
            name="FPS",
            description=tr("anim_importer.prop.import_fps_custom_fps", lang),
            default=FPS_HYTALE,
            min=1,
            soft_max=240,
        ),
        "import_fps_custom_base": FloatProperty(
            name="Base",
            description=tr("anim_importer.prop.import_fps_custom_base", lang),
            default=1.0,
            min=0.001,
            soft_max=120.0,
        ),
        "loop_mode": EnumProperty(
            name="Looping",
            description=tr("anim_importer.prop.loop_mode", lang),
            items=[
                (
                    "AUTO",
                    "Auto (from file)",
                    tr("anim_importer.prop.loop_mode_item_auto", lang),
                ),
                (
                    "CYCLE",
                    "Cycle (loop)",
                    tr("anim_importer.prop.loop_mode_item_cycle", lang),
                ),
                (
                    "ONE_SHOT",
                    "Start & End (no loop)",
                    tr("anim_importer.prop.loop_mode_item_one_shot", lang),
                ),
            ],
            default="AUTO",
        ),
        "bake_mode": BoolProperty(
            name="Bake to Every Frame",
            description=tr("anim_importer.prop.bake_mode", lang),
            default=False,
        ),
        "keep_spine_follow": BoolProperty(
            name="Keep Spine-Follow Active",
            description=tr("anim_importer.prop.keep_spine_follow", lang),
            default=True,
        ),
        "spine_mode": EnumProperty(
            name="Spine",
            description=tr("anim_importer.prop.spine_mode", lang),
            items=[
                (
                    "DEFAULT",
                    "Default (Root CTRL)",
                    tr("anim_importer.prop.spine_mode_item_default", lang),
                ),
                (
                    "MANUAL",
                    "Spine CTRL",
                    tr("anim_importer.prop.spine_mode_item_manual", lang),
                ),
            ],
            default="DEFAULT",
        ),
        "arms_mode": EnumProperty(
            name="Arms",
            description=tr("anim_importer.prop.arms_mode", lang),
            items=[
                (
                    "BOTH",
                    "Default (FK + IK)",
                    tr("anim_importer.prop.arms_mode_item_both", lang),
                ),
                (
                    "CTRL_FK",
                    "Control FK",
                    tr("anim_importer.prop.arms_mode_item_ctrl_fk", lang),
                ),
                (
                    "IK",
                    "Control IK",
                    tr("anim_importer.prop.arms_mode_item_ik", lang),
                ),
            ],
            default="BOTH",
        ),
        "legs_mode": EnumProperty(
            name="Legs",
            description=tr("anim_importer.prop.legs_mode", lang),
            items=[
                (
                    "BOTH",
                    "Default (FK + IK)",
                    tr("anim_importer.prop.legs_mode_item_both", lang),
                ),
                (
                    "CTRL_FK",
                    "Control FK",
                    tr("anim_importer.prop.legs_mode_item_ctrl_fk", lang),
                ),
                (
                    "IK",
                    "Control IK",
                    tr("anim_importer.prop.legs_mode_item_ik", lang),
                ),
            ],
            default="BOTH",
        ),
    }


@localized_props(_blockyanim_import_props)
class IMPORT_OT_hytale_blockyanim(Operator, ImportHelper):
    """Import a .blockyanim file onto the active armature"""

    bl_idname = "import_scene.hytale_blockyanim"
    bl_label = "Import Hytale Animation"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".blockyanim"

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def invoke(self, context, event):
        return super().invoke(context, event)

    def execute(self, context):
        obj = context.active_object

        try:
            data = parse_blockyanim(self.filepath)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            self.report({"ERROR"}, f"Could not read '{self.filepath}': {e}")
            return {"CANCELLED"}

        handler = _MODE_HANDLERS.get(self.target_mode)
        if handler is None:
            self.report(
                {"ERROR"},
                f"Target mode '{self.target_mode}' isn't implemented yet -- use 'Original Bones' "
                f"for now.",
            )
            return {"CANCELLED"}

        action_name = self.action_name.strip() or os.path.splitext(os.path.basename(self.filepath))[0]

        if self.import_fps_preset == "CUSTOM":
            target_fps_int, target_fps_base = self.import_fps_custom_fps, self.import_fps_custom_base
        else:
            target_fps_int, target_fps_base = _FPS_PRESET_VALUES[self.import_fps_preset]
        target_fps = target_fps_int / target_fps_base

        current_fps = context.scene.render.fps / context.scene.render.fps_base
        if abs(target_fps - current_fps) > 1e-6:
            context.scene.render.fps = target_fps_int
            context.scene.render.fps_base = target_fps_base
            self.report(
                {"INFO"},
                f"Scene FPS changed from {current_fps:g} to {target_fps:g} for this import.",
            )

        return handler(
            self,
            context,
            obj,
            data,
            self.start_frame,
            action_name,
            self.loop_mode,
            self.bake_mode,
            self.keep_spine_follow,
            self.spine_mode,
            self.arms_mode,
            self.legs_mode,
        )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "target_mode")
        if self.target_mode == "CTRL":
            box = layout.box()
            box.prop(self, "spine_mode")
            box.prop(self, "arms_mode")
            box.prop(self, "legs_mode")
        layout.prop(self, "action_name")
        layout.prop(self, "start_frame")
        layout.prop(self, "import_fps_preset")
        if self.import_fps_preset == "CUSTOM":
            col = layout.column(align=True)
            col.prop(self, "import_fps_custom_fps")
            col.prop(self, "import_fps_custom_base")
        layout.prop(self, "loop_mode")
        layout.prop(self, "bake_mode")
        if self.target_mode == "CTRL":
            layout.prop(self, "keep_spine_follow")


def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_hytale_blockyanim.bl_idname, text="Hytale Animation (.blockyanim)")


_CLASSES = (IMPORT_OT_hytale_blockyanim,)


def register():
    for cls in _CLASSES:
        register_localized_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(_CLASSES):
        unregister_localized_class(cls)


if __name__ == "__main__":
    register()
