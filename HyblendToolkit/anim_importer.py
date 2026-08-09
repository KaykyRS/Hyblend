# ---------------------------------------------------------------------------
# Este arquivo é o submódulo ANIM IMPORTER do pacote HyblendToolkit.
# Todos os modos estão prontos e validados -- painel de teste standalone
# (que existia só pra validar isolado) foi removido; a UI agora é
# responsabilidade da aba "Import" do interface.py, igual ao rigger.py já
# fez com sua própria aba "Rig" (ver DEVELOPER_NOTES.md, seção
# "Adicionando uma função totalmente nova").
#
# O que este módulo faz: lê um .blockyanim (mesmo formato que o
# exporter.py escreve -- ver o cabeçalho de exporter.py pra spec completa)
# e aplica a animação numa Armature JÁ EXISTENTE no Blender. Isso é
# fundamentalmente diferente do importer.py (que CONSTRÓI um Armature do
# zero a partir de um .blockymodel) -- aqui a geometria/hierarquia já
# existe, só precisamos posá-la nos frames certos.
#
# QUATRO modos de destino (target_mode, no operador
# IMPORT_OT_hytale_blockyanim), pensados como CAMADAS que se apoiam uma na
# outra -- cada uma reaproveita o resultado da anterior, não são caminhos
# paralelos independentes:
#
#   ORG      -- keyframa o bone ORIGINAL direto (mesmo nome do
#               .blockymodel/.blockyanim). Funciona em QUALQUER Armature
#               que tenha esses bones, rigada ou não -- é o modo genérico
#               que precisa funcionar pra QUALQUER personagem/criatura do
#               Hytale, não só o Player. Numa Armature COM rig gerado, os
#               keyframes não movem nada visualmente (o ORG está
#               constrained -- ver Hytale_ORG_to_MCH em rigger.py).
#   CTRL_FK  -- escreve no bone "_CTRL" (rigger.py) em vez do ORG,
#               calculando a pose de mundo pretendida (andando a
#               hierarquia ORG) e reprojetando no PAI REAL do _CTRL no
#               Blender (pode ser diferente do pai ORG -- ver
#               CTRL_PARENT_OVERRIDES em rigger.py). Sempre gera keyframe
#               denso (um por frame) -- não tem versão esparsa.
#   IK       -- igual o CTRL_FK pra bones fora de cadeia; bones de
#               braço/perna (armature.hytale_ik_chains, rigger.py) vão
#               pro "_IK" da ponta (mão/pé) + pole target em vez do
#               "_CTRL" por segmento. O pole é posicionado replicando a
#               MESMA fórmula geométrica que o rigger.py usa na hora de
#               gerar o rig (offset a partir do eixo Z do bone do meio da
#               cadeia), só que com a orientação ANIMADA em vez da rest
#               pose -- importante pra bater com o pole_angle já
#               calibrado. A ponta (_IK) precisa de uma correção extra
#               (_resolve_ik_tip_matrix_basis) porque sua rest orientation
#               é diferente da do ORG/bridge (rigger.py ajusta tail/roll
#               dela) -- ver o comentário grande ali se for mexer nisso.
#   BOTH     -- CTRL_FK + IK juntos, na mesma passada -- todo bone recebe
#               seu "_CTRL" (cadeia inclusive) E cada cadeia também recebe
#               "_IK"+pole. fk_ik_switch fica em FK (0) por padrão; o
#               animador troca por cadeia, a qualquer momento, sem
#               reimportar.
#
# Bones _CTRL com constraint extra (ex: Belly_CTRL/Chest_CTRL seguindo
# root.spine_CTRL via Hytale_SpineFollow) e os Child Of dos pole targets
# são MUTADOS durante o import (nos modos CTRL_FK/IK/BOTH), a menos que
# `keep_spine_follow=True` -- ver nota grande em _apply_ctrl_fk_mode.
# ---------------------------------------------------------------------------

bl_info = {
    "name": "Hytale Blocky Anim Importer",
    "author": "Kaayky",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Hytale Anim (test)",
    "description": "Import a .blockyanim file onto an existing armature (original bones, "
    "control bones, or IK limbs)",
    "category": "Animation",
}

import json
import os
from collections import deque

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Quaternion, Vector

from .common import FPS_HYTALE, UNIT_SCALE_DEFAULT, quat_xyzw, vec3
from .rigger import PROP_FK_IK_SWITCH, PROP_RIG_LAYER, SUFFIX_CTRL, SUFFIX_IK, SUFFIX_POLE

# ---------------------------------------------------------------------------
# Matemática de import -- espelho EXATO (invertido) de compute_deltas() /
# local_matrix() em exporter.py. Ver o comentário grande no topo de
# exporter.py pra derivação completa; aqui só o resumo do que importa pra
# entender o código abaixo:
#
#   rest_local  = matrix_local(pai)⁻¹ @ matrix_local(bone)   [bone sem pai:
#                 rest_local = matrix_local(bone), mesma convenção do
#                 export/import de modelo]
#   delta_local = rest_local⁻¹ @ pose_local   (isso é o que o exporter
#                 escreve no arquivo, já convertido pra unidades de jogo)
#
# A parte boa pro import: delta_local, sem nenhuma constraint envolvida
# (bone ORG "solto", sem Hytale_ORG_to_MCH por cima), É EXATAMENTE
# pbone.matrix_basis -- ou seja, é o que pbone.location/rotation_quaternion
# JÁ representam por definição (delta em relação ao rest, no espaço do
# próprio bone). Isso significa que NÃO precisamos calcular matriz de
# mundo nem multiplicar por rest_local nenhuma -- só desfazer a escala do
# "position" e reconstruir o quaternion do "orientation", e jogar direto
# em pbone.location / pbone.rotation_quaternion. Ver _apply_org_mode().
#
# Isso só é verdade pro modo ORG (bone sem constraint por cima). Pro modo
# CTRL_FK (fase 2), o CTRL pode ter um PARENT diferente do ORG
# (CTRL_PARENT_OVERRIDES em rigger.py) -- nesse caso search por matriz de
# mundo (rest_local @ delta_local, convertido pro espaço local do parent
# REAL do CTRL) volta a ser necessário. Deixado comentado aqui como
# referência pra quando formos escrever esse modo:
#
#   world_target = parent_world(ORG) @ rest_local(ORG) @ delta_local
#   ctrl_local   = parent_world(CTRL_real)⁻¹ @ world_target
#   ctrl_matrix_basis = rest_local(CTRL)⁻¹ @ ctrl_local
# ---------------------------------------------------------------------------


def parse_blockyanim(filepath):
    """Lê e valida minimamente um .blockyanim. Levanta ValueError com uma
    mensagem legível se o arquivo não bater com o formato esperado (ver
    cabeçalho de exporter.py) -- o operador captura isso e reporta como
    erro em vez de deixar o traceback cru estourar pro usuário."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "nodeAnimations" not in data:
        raise ValueError("Missing 'nodeAnimations' -- this doesn't look like a .blockyanim file.")

    return data


def hytale_time_to_frame(time, start_frame, fps):
    """Inverso exato de frame_to_hytale_time() em exporter.py: 'time' do
    arquivo (frame inteiro a FPS_HYTALE fixo, relativo ao início) -> frame
    da timeline do Blender (na fps DA CENA, deslocado por start_frame)."""
    seconds = time / FPS_HYTALE
    return start_frame + round(seconds * fps)


def collect_target_bone_names(armature_obj, node_animations):
    """Separa os nomes de nodeAnimations em (existentes, ausentes) contra
    os pose bones da armature ativa. 'Ausentes' é esperado e normal --
    nem toda criatura tem os mesmos bones que o Player (ex: Cape, Hair-*)
    -- por isso isso vira um aviso agregado, não erro, e não interrompe o
    resto do import (ver DEVELOPER_NOTES.md sobre o objetivo de funcionar
    em qualquer criatura)."""
    pose_bones = armature_obj.pose.bones
    existing = [name for name in node_animations if name in pose_bones]
    missing = [name for name in node_animations if name not in pose_bones]
    return existing, missing


# Mapeia o "interpolationType" do arquivo pro tipo de interpolação de
# F-Curve do Blender mais próximo. "smooth" no Blockbench não é
# matematicamente idêntico a BEZIER do Blender (curvas diferentes por
# baixo), mas é a aproximação visual mais razoável disponível nativamente
# -- resultado nunca deveria ficar "errado", só levemente diferente do
# Blockbench em curvas com poucos keyframes espaçados.
INTERPOLATION_MAP = {"smooth": "BEZIER", "linear": "LINEAR"}
INTERPOLATION_DEFAULT = "BEZIER"

# Default pro CAMPO 'interpolationType' do arquivo em si (espaço
# "arquivo": "smooth"/"linear") -- diferente de INTERPOLATION_DEFAULT
# acima (espaço "Blender": nome de enum de kp.interpolation). Usado só
# onde precisamos inventar/copiar um interpolationType a partir de dados
# do arquivo (ex: _looped_samples) -- nunca misturar os dois.
RAW_INTERPOLATION_DEFAULT = "smooth"


def _get_or_create_fcurve(action, data_path, index, group_name):
    fcurve = action.fcurves.find(data_path, index=index)
    if fcurve is None:
        fcurve = action.fcurves.new(data_path, index=index, action_group=group_name)
    return fcurve


def _write_channel(action, data_path, group_name, components, samples):
    """Escreve `samples` (lista de (frame, valor_completo, interp), já
    convertida em unidades do Blender -- ver _apply_org_mode) num conjunto
    de F-Curves, uma por componente (ex: location -> x,y,z / índices
    0,1,2), cuidando da interpolação por keyframe."""
    if not samples:
        return

    fcurves = [_get_or_create_fcurve(action, data_path, i, group_name) for i in range(components)]

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
    """Se a animação for cíclica (holdLastKeyframe == False, ver doc do
    formato -- 'Whether to hold at final position') e o arquivo declarar
    'duration', adiciona uma amostra SINTÉTICA no final do canal (tempo =
    duration) com o MESMO valor da PRIMEIRA amostra do canal.

    Por quê: sem isso, cada bone fica preso (extrapolação constante do
    Blender) na pose do SEU PRÓPRIO último keyframe -- e como bones
    diferentes têm keyframes em tempos diferentes (ex: L-Thigh termina em
    22, R-Thigh em 18), o resultado depois do keyframe mais cedo é uma
    combinação de poses que nunca existiu de verdade na animação
    original: no Blockbench/jogo, um clipe com holdLastKeyframe=false
    fecha o ciclo voltando suavemente pra pose inicial, não congela.
    Adicionar esse ponto de wrap reproduz esse fechamento de loop.

    Não faz nada se: hold_last for True (o arquivo realmente quer
    congelar -- comportamento padrão do Blender já faz isso sozinho),
    não houver 'duration' no arquivo, o canal estiver vazio, ou o último
    tempo real já for >= duration (nada a fechar)."""
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


# ---------------------------------------------------------------------------
# Modo Bake: avalia o canal NÓS MESMOS (fora do sistema de F-Curve do
# Blender), em cada unidade INTEIRA de tempo do arquivo, usando uma
# Hermite cúbica com tangentes tipo Catmull-Rom.
#
# Por que NÃO um simples ease-in/out por trecho (versão anterior deste
# módulo): um ease-in/out sempre zera a VELOCIDADE nas duas pontas de
# CADA trecho -- ou seja, em TODO keyframe, a animação "para" por um
# instante antes de acelerar de novo pro próximo. Isso é sutil no meio
# do clipe (pode até passar por uma "pose de destaque" natural), mas fica
# muito óbvio bem na costura de um loop, porque ali você espera
# continuidade total -- é exatamente o "trava no final" reportado.
#
# A correção: a tangente em cada ponto INTERNO é calculada olhando os
# DOIS vizinhos (diferença central, com o espaçamento de tempo REAL entre
# eles, que raramente é uniforme nesse formato) -- isso mantém velocidade
# contínua (geralmente != 0) atravessando cada keyframe. Pra um canal
# CÍCLICO (ver _looped_samples), a costura (primeiro ponto == último
# ponto, mesma pose) é tratada como só mais um ponto INTERNO, usando o
# penúltimo e o segundo ponto como vizinhos (o relógio "desdobra" através
# da costura) -- fechando o loop com velocidade contínua também ali, não
# só com o valor batendo. Pontas de um trecho NÃO cíclico ficam com
# tangente zero de propósito (desacelera até parar -- correto pra um
# clipe que realmente começa/termina, ex: um ataque).
#
# Isso também resolve, de quebra, o problema de rotation_quaternion no
# Blender ser 4 F-Curves independentes (w,x,y,z) interpoladas por
# componente, sem noção de que é uma rotação (não é o mesmo que girar
# suavemente de uma orientação pra outra) -- aqui fazemos a mesma conta
# de Hermite tratando (w,x,y,z) como um Vector 4D, o que não é uma
# "geodésica" perfeita (o correto matematicamente seria Squad, a versão
# pra quaternions de uma spline Hermite -- mais complexo, não implementado
# aqui), mas já é consistente com/melhora sobre o que o Blender faria
# sozinho, E com continuidade de velocidade corrigida na costura.
# ---------------------------------------------------------------------------


def _sign_consistent_quats(samples):
    """Lê 'delta' de cada sample como Quaternion e corrige o problema do
    'duplo-cover' (q e -q representam a MESMA rotação, mas interpolar
    entre eles sem alinhar o sinal faz o caminho pegar a volta longa):
    inverte o sinal de cada quaternion se ele estiver do lado "errado" em
    relação ao anterior. Devolve como Vector 4D (w,x,y,z) -- forma
    genérica que a matemática de Hermite abaixo (compartilhada com
    posição) sabe manipular sem precisar saber que é uma rotação."""
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
    """Tangente (derivada) em CADA ponto de controle -- None nas pontas
    de um trecho não cíclico (vira tangente zero em _hermite_resample).

    A costura de um trecho CÍCLICO (índice 0 e índice -1: MESMA pose, ver
    _looped_samples) usa uma ÚNICA fórmula compartilhada pros dois, com o
    tempo desdobrado por só UM período (`span`) de cada vez -- não dois
    (um erro fácil de cometer aqui: deslocar os DOIS vizinhos ao mesmo
    tempo dobra o `span` no denominador por engano). Como consequência
    direta de usar a mesma fórmula pros dois lados, a tangente na costura
    fica IDÊNTICA nos dois lados por construção -- é isso que garante
    continuidade de velocidade ali, não só o valor batendo."""
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
    """Hermite cúbico padrão -- m0/m1 são tangentes 'por unidade de
    tempo do arquivo' (ver _catmull_rom_tangents), escaladas aqui por
    `dt` (duração real deste trecho específico) pra virar o formato que
    a base de Hermite espera (tangente 'por trecho inteiro')."""
    t2, t3 = t * t, t * t * t
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    return p0 * h00 + m0 * (dt * h10) + p1 * h01 + m1 * (dt * h11)


def _hermite_resample(times, values, start_frame, fps, cyclic):
    """Reamostra (times, values) em CADA unidade inteira de tempo do
    arquivo, retornando [(frame, valor, 'linear'), ...] pronto pra virar
    pos_samples/rot_samples. `values` já deve estar no espaço certo
    (Vector em unidades do Blender pra posição; Vector 4D w,x,y,z já com
    sinal corrigido pra orientação -- ver _sign_consistent_quats)."""
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


def _bake_position_samples(samples, start_frame, fps, cyclic):
    times = [s["time"] for s in samples]
    values = [vec3(s.get("delta", {})) * UNIT_SCALE_DEFAULT for s in samples]
    return _hermite_resample(times, values, start_frame, fps, cyclic)


def _bake_orientation_samples(samples, start_frame, fps, cyclic):
    times = [s["time"] for s in samples]
    values = _sign_consistent_quats(samples)
    baked = _hermite_resample(times, values, start_frame, fps, cyclic)
    return [(frame, _vec4_to_quat(v), interp) for frame, v, interp in baked]


def _apply_org_mode(
    operator, context, armature_obj, data, start_frame, action_name, loop_mode, bake_mode, keep_spine_follow
):
    """Modo ORG: keyframa os bones originais direto, sem passar por
    nenhuma camada de controle. Ver nota grande no topo do módulo sobre
    por que delta_local == matrix_basis nesse caso (sem constraint por
    cima), e por isso não precisamos de rest_matrices/pose_matrices
    nenhuma aqui -- só desfazer a conversão que compute_deltas() fez.

    'keep_spine_follow' não se aplica a este modo (não existe camada de
    controle/constraint nenhuma aqui) -- recebido só pra manter a
    assinatura igual à de _apply_ctrl_fk_mode, já que o dispatch em
    _MODE_HANDLERS chama todo handler com os MESMOS argumentos."""
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base

    # O .blockyanim é fixo em FPS_HYTALE (60), independente da cena. A
    # conversão pra frame do Blender é matematicamente correta em
    # qualquer FPS (preserva a duração em tempo REAL), mas só é
    # LOSSLESS/1:1 com os números do arquivo quando a cena também está a
    # 60 FPS -- em qualquer FPS menor, a animação (que pode ter só
    # poucos frames de duração) acaba cabendo num espaço bem menor de
    # frames do Blender do que os números do arquivo fazem parecer (ex:
    # uma animação de 30 "frames" de jogo vira só ~11 frames do Blender a
    # 24 FPS), o que costuma parecer "a animação ficou cortada/faltando o
    # resto" quando na verdade só ficou compactada. Avisamos aqui pra não
    # precisar descobrir isso na unha toda vez.
    if round(fps) != FPS_HYTALE:
        operator.report(
            {"WARNING"},
            f"Scene is at {fps:g} FPS, not {FPS_HYTALE}. The animation's timing will be scaled "
            f"to match real-world duration, but will occupy far fewer Blender frames than the "
            f"file's 'time' numbers suggest -- set Output Properties > Frame Rate to {FPS_HYTALE} "
            f"for an exact 1:1 match with the .blockyanim file.",
        )

    node_animations = data["nodeAnimations"]

    # loop_mode escolhido pelo usuário sobrescreve o que o ARQUIVO diz
    # (holdLastKeyframe) -- "AUTO" é o único que de fato lê o arquivo;
    # "CYCLE"/"ONE_SHOT" forçam o comportamento independente do que o
    # arquivo declara, pros casos em que o valor do arquivo está errado/
    # ausente ou o usuário simplesmente quer testar o outro modo.
    if loop_mode == "CYCLE":
        hold_last = False
    elif loop_mode == "ONE_SHOT":
        hold_last = True
    else:  # "AUTO"
        hold_last = bool(data.get("holdLastKeyframe", False))
    duration = data.get("duration")

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

    pose_bones = armature_obj.pose.bones
    bones_with_rotation = set()
    max_frame_seen = start_frame

    for name in existing_names:
        channels = node_animations[name]
        pbone = pose_bones[name]
        group_name = name

        pos_raw = _looped_samples(channels.get("position", []), hold_last, duration)
        if pos_raw:
            if bake_mode:
                pos_samples = _bake_position_samples(pos_raw, start_frame, fps, cyclic=not hold_last)
            else:
                pos_samples = [
                    (
                        hytale_time_to_frame(s["time"], start_frame, fps),
                        vec3(s.get("delta", {})) * UNIT_SCALE_DEFAULT,
                        s.get("interpolationType", INTERPOLATION_DEFAULT),
                    )
                    for s in pos_raw
                ]
            _write_channel(
                action,
                f'pose.bones["{name}"].location',
                group_name,
                3,
                pos_samples,
            )
            max_frame_seen = max(max_frame_seen, max(f for f, _, _ in pos_samples))

        rot_raw = _looped_samples(channels.get("orientation", []), hold_last, duration)
        if rot_raw:
            # rotation_quaternion precisa desse modo pra as F-Curves w,x,y,z
            # baterem com o que estamos escrevendo -- forçamos aqui e
            # avisamos se o bone estava em outro modo (Euler/Axis Angle),
            # porque isso muda como o bone é posado em qualquer outra
            # Action que já exista nele.
            if pbone.rotation_mode != "QUATERNION":
                operator.report(
                    {"WARNING"},
                    f"Bone '{name}' rotation mode was '{pbone.rotation_mode}' -- switched to "
                    f"'QUATERNION' to import orientation keyframes.",
                )
                pbone.rotation_mode = "QUATERNION"
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
                f'pose.bones["{name}"].rotation_quaternion',
                group_name,
                4,
                rot_samples,
            )
            max_frame_seen = max(max_frame_seen, max(f for f, _, _ in rot_samples))

    # A cena (Frame End da Timeline) pode estar mais curta do que a
    # animação recém-importada -- se a gente não esticar isso, o EXPORT
    # (que sampleia dentro do range da cena) corta o final da animação
    # sem avisar. Só estica, nunca encolhe (nunca mexe em frame_start:
    # como 'time' do arquivo nunca é negativo, o frame mínimo já é
    # sempre >= start_frame, então frame_start da cena não precisa mudar).
    if scene.frame_end < max_frame_seen:
        old_end = scene.frame_end
        scene.frame_end = max_frame_seen
        operator.report(
            {"INFO"},
            f"Scene Frame End was {old_end}, extended to {max_frame_seen} to fit the imported "
            f"animation.",
        )

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
        f"({len(bones_with_rotation)} with rotation).",
    )
    return {"FINISHED"}


# ---------------------------------------------------------------------------
# Modo CTRL_FK: diferente do modo ORG, aqui o bone de destino (_CTRL) pode
# ter um PARENT diferente do bone ORG correspondente (ver
# CTRL_PARENT_OVERRIDES em rigger.py -- ex: Pelvis_CTRL não é filho do
# que seria o "pai ORG" natural). Por causa disso, delta_local NÃO é
# suficiente sozinho (ao contrário do modo ORG) -- precisamos calcular a
# matriz de MUNDO pretendida de cada bone ORG (andando a hierarquia ORG
# inteira, pai por pai) e depois reprojetar isso no espaço local do PAI
# REAL do _CTRL no Blender (lido direto do rig já gerado -- não
# precisamos saber as regras do CTRL_PARENT_OVERRIDES aqui, só
# `pose_bone.parent`).
#
#   world_target(bone)  = world_target(pai ORG) @ rest_local(bone) @ delta_local(bone)
#   ctrl_local           = world_target(pai REAL do _CTRL)⁻¹ @ world_target(bone)
#   ctrl_matrix_basis     = rest_local(_CTRL)⁻¹ @ ctrl_local
#
# Isso só faz sentido calculado UM FRAME INTEIRO DE CADA VEZ (a composição
# pai->filho depende do frame) -- por isso este modo sempre gera
# keyframes densos (um por frame), reaproveitando o MESMO motor Hermite/
# Catmull-Rom do modo Bake (ver _bake_position_samples/
# _bake_orientation_samples) só que agora pra resolver um VALOR por vez
# em cada frame, não uma curva inteira de uma vez. O toggle "Bake to
# Every Frame" da UI não se aplica aqui (fica sem efeito) -- não existe
# versão "esparsa" deste modo, é sempre denso por construção.
# ---------------------------------------------------------------------------


def _rest_local_matrix(pbone):
    """Matriz de repouso (LOCAL, relativa ao pai) de um pose bone --
    mesma convenção usada no exporter.py (local_matrix): bone sem pai,
    local == armature space."""
    bone = pbone.bone
    if pbone.parent is None:
        return bone.matrix_local.copy()
    return pbone.parent.bone.matrix_local.inverted() @ bone.matrix_local


def _org_hierarchy(armature_obj):
    """Lista de (nome, nome_do_pai_ORG_ou_None, rest_local) de TODOS os
    bones ORG da armature -- identificados por NÃO terem a custom
    property PROP_RIG_LAYER (é isso, não o nome, que o rigger.py usa pra
    diferenciar ORG de bone gerado -- ver rigger.py). Devolvida em ordem
    de PROFUNDIDADE (pai sempre antes do filho), pra dar pra calcular a
    matriz de mundo de cada um percorrendo a lista uma única vez."""
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


def _bake_delta_lookup(pos_raw, rot_raw, start_frame, fps, cyclic):
    """Pré-calcula, pra UM bone, uma função lookup(frame) -> Matrix do
    delta_local (posição+rotação combinadas) -- fora do range coberto
    por cada canal, mantém constante o valor da ponta mais próxima (mesma
    extrapolação 'constante' de sempre, fora do primeiro/último
    keyframe). Reaproveita o motor de bake Hermite/Catmull-Rom já
    existente (ver nota grande acima de _sign_consistent_quats) -- é o
    mesmo cálculo do modo ORG com Bake ligado, só que aqui é sempre
    obrigatório (ver nota grande acima do bloco CTRL_FK).

    Usa um dict (não uma lista indexada por posição) porque a conversão
    tempo-do-arquivo -> frame do Blender só é 1-pra-1 contígua quando a
    cena está a 60 FPS -- em qualquer outro FPS, hytale_time_to_frame
    pode pular frames (FPS > 60) ou colapsar vários tempos no mesmo frame
    (FPS < 60), e uma indexação por posição de lista quebraria (índice
    errado ou fora do range) nesses casos."""
    pos_list = _bake_position_samples(pos_raw, start_frame, fps, cyclic) if pos_raw else []
    rot_list = _bake_orientation_samples(rot_raw, start_frame, fps, cyclic) if rot_raw else []
    pos_by_frame = {f: v for f, v, _ in pos_list}
    rot_by_frame = {f: v for f, v, _ in rot_list}
    pos_bounds = (pos_list[0][0], pos_list[-1][0]) if pos_list else None
    rot_bounds = (rot_list[0][0], rot_list[-1][0]) if rot_list else None

    def _nearest(by_frame, frame):
        value = by_frame.get(frame)
        if value is not None:
            return value
        # FPS da cena != 60: este frame específico pode não coincidir com
        # nenhuma amostra bakeada (FPS > 60 pula frames) -- usa a mais
        # próxima disponível em vez de estourar KeyError.
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


def _apply_ctrl_fk_mode(
    operator, context, armature_obj, data, start_frame, action_name, loop_mode, bake_mode, keep_spine_follow
):
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base

    if round(fps) != FPS_HYTALE:
        operator.report(
            {"WARNING"},
            f"Scene is at {fps:g} FPS, not {FPS_HYTALE}. The animation's timing will be scaled "
            f"to match real-world duration, but will occupy far fewer Blender frames than the "
            f"file's 'time' numbers suggest -- set Output Properties > Frame Rate to {FPS_HYTALE} "
            f"for an exact 1:1 match with the .blockyanim file.",
        )

    node_animations = data["nodeAnimations"]
    if loop_mode == "CYCLE":
        hold_last = False
    elif loop_mode == "ONE_SHOT":
        hold_last = True
    else:  # "AUTO"
        hold_last = bool(data.get("holdLastKeyframe", False))
    duration = data.get("duration")
    cyclic = not hold_last

    hierarchy = _org_hierarchy(armature_obj)
    org_names_in_file = [name for name, _, _ in hierarchy if name in node_animations]
    if not org_names_in_file:
        operator.report(
            {"ERROR"},
            "None of the bones in this .blockyanim exist as original (ORG) bones on this "
            "armature -- wrong file, wrong armature, or the rig hasn't been generated yet?",
        )
        return {"CANCELLED"}

    # Lookup(frame) -> Matrix do delta_local, por bone ORG do arquivo, e o
    # frame mais alto realmente coberto por CADA UM (pro cálculo do range
    # global abaixo).
    delta_lookup = {}
    max_time = 0
    for name in org_names_in_file:
        channels = node_animations[name]
        for ch in ("position", "orientation"):
            for s in channels.get(ch, []):
                max_time = max(max_time, s["time"])
        pos_raw = _looped_samples(channels.get("position", []), hold_last, duration)
        rot_raw = _looped_samples(channels.get("orientation", []), hold_last, duration)
        delta_lookup[name] = _bake_delta_lookup(pos_raw, rot_raw, start_frame, fps, cyclic)
    if cyclic and duration is not None:
        max_time = max(max_time, duration)
    end_frame = hytale_time_to_frame(max_time, start_frame, fps)

    action = bpy.data.actions.new(action_name)
    anim_data = armature_obj.animation_data_create()
    anim_data.action = action

    pose_bones = armature_obj.pose.bones
    ctrl_values = {}  # {ctrl_name: [(frame, loc_Vector, quat_Quaternion), ...]}
    ctrl_rest_cache = {}
    warned_rotation_mode = set()

    # Alguns bones _CTRL (ex: Belly_CTRL/Chest_CTRL, ver SPINE_FOLLOW_BONES
    # em rigger.py) têm constraints EXTRAS por cima da hierarquia FK pura
    # (ex: Copy Transforms parcial seguindo root.spine_CTRL, pensado pra
    # facilitar posar à mão -- mexe na espinha e o peito/barriga
    # acompanham sozinhos). O Blender aplica essas constraints DEPOIS de
    # resolver matrix_basis, então o resultado final da pose vira uma
    # MISTURA do que calculamos aqui (composição hierárquica pura) com o
    # que a constraint está fazendo por cima -- o valor final não bate
    # com o arquivo original. Por padrão (keep_spine_follow=False)
    # silenciamos QUALQUER constraint nos bones _CTRL que vamos escrever
    # (não hardcoding os nomes conhecidos do rigger.py -- genérico,
    # funciona mesmo que o rig mude no futuro), já que o objetivo aqui é
    # reproduzir fielmente a animação importada. Se keep_spine_follow for
    # True, o usuário está escolhendo abrir mão dessa fidelidade em troca
    # de manter o root.spine_CTRL como ferramenta de ajuste fino
    # utilizável em cima da animação importada -- nesse caso não mexemos
    # em constraint nenhuma.
    muted_constraints = []
    if not keep_spine_follow:
        for name, _parent_name, _rest_local in hierarchy:
            ctrl_pbone = pose_bones.get(name + SUFFIX_CTRL)
            if ctrl_pbone is None:
                continue
            for con in ctrl_pbone.constraints:
                if not con.mute:
                    con.mute = True
                    muted_constraints.append((ctrl_pbone.name, con.name))

    for frame in range(start_frame, end_frame + 1):
        world_target = {}
        for name, parent_name, rest_local in hierarchy:
            delta = delta_lookup[name](frame) if name in delta_lookup else Matrix.Identity(4)
            parent_world = world_target[parent_name] if parent_name is not None else Matrix.Identity(4)
            world_target[name] = parent_world @ rest_local @ delta

        for name, _parent_name, _rest_local in hierarchy:
            ctrl_name = name + SUFFIX_CTRL
            ctrl_pbone = pose_bones.get(ctrl_name)
            if ctrl_pbone is None:
                continue

            if ctrl_name not in ctrl_rest_cache:
                ctrl_rest_cache[ctrl_name] = _rest_local_matrix(ctrl_pbone)
            ctrl_rest_local = ctrl_rest_cache[ctrl_name]

            ctrl_parent = ctrl_pbone.parent
            if ctrl_parent is None:
                ctrl_parent_world = Matrix.Identity(4)
            elif ctrl_parent.name.endswith(SUFFIX_CTRL) and ctrl_parent.name[: -len(SUFFIX_CTRL)] in world_target:
                ctrl_parent_world = world_target[ctrl_parent.name[: -len(SUFFIX_CTRL)]]
            else:
                # Bone utilitário (ex: root.pelvis_CTRL) ou _CTRL de um
                # bone ORG que não está neste arquivo -- assumimos que
                # não está sendo animado por NADA neste import, então a
                # pose ATUAL dele no Blender serve como referência fixa
                # (ver nota grande acima do bloco CTRL_FK).
                ctrl_parent_world = ctrl_parent.matrix.copy()

            ctrl_local = ctrl_parent_world.inverted() @ world_target[name]
            matrix_basis = ctrl_rest_local.inverted() @ ctrl_local
            loc, quat, _scale = matrix_basis.decompose()

            if ctrl_pbone.rotation_mode != "QUATERNION":
                if ctrl_name not in warned_rotation_mode:
                    operator.report(
                        {"WARNING"},
                        f"Bone '{ctrl_name}' rotation mode was '{ctrl_pbone.rotation_mode}' -- "
                        f"switched to 'QUATERNION' to import orientation keyframes.",
                    )
                    warned_rotation_mode.add(ctrl_name)
                ctrl_pbone.rotation_mode = "QUATERNION"

            ctrl_values.setdefault(ctrl_name, []).append((frame, loc, quat))

    for ctrl_name, samples in ctrl_values.items():
        pos_samples = [(f, loc, "linear") for f, loc, _q in samples]
        rot_samples = [(f, quat, "linear") for f, _loc, quat in samples]
        _write_channel(action, f'pose.bones["{ctrl_name}"].location', ctrl_name, 3, pos_samples)
        _write_channel(
            action, f'pose.bones["{ctrl_name}"].rotation_quaternion', ctrl_name, 4, rot_samples
        )

    if scene.frame_end < end_frame:
        old_end = scene.frame_end
        scene.frame_end = end_frame
        operator.report(
            {"INFO"}, f"Scene Frame End was {old_end}, extended to {end_frame} to fit the imported animation."
        )

    if muted_constraints:
        affected_bones = sorted({bone_name for bone_name, _con_name in muted_constraints})
        operator.report(
            {"WARNING"},
            f"Muted {len(muted_constraints)} extra constraint(s) on {len(affected_bones)} control "
            f"bone(s) so the imported pose isn't blended with anything else (ex: spine-follow "
            f"helpers) -- left muted after import; re-enable manually in Bone Constraint "
            f"Properties if you want that behavior back for hand-animating: "
            f"{', '.join(affected_bones[:8])}" + ("..." if len(affected_bones) > 8 else ""),
        )
    elif keep_spine_follow:
        operator.report(
            {"INFO"},
            "Kept spine-follow (and any other extra control-bone constraints) active, as requested "
            "-- the imported pose on affected bones (ex: Belly/Chest) will differ slightly from the "
            "source file wherever those constraints blend in root.spine_CTRL's current pose.",
        )

# ---------------------------------------------------------------------------
# Modo IK: idêntico ao CTRL_FK pra bones que NÃO fazem parte de uma cadeia
# de IK (tronco, cabeça, dedos etc. -- mesmo _CTRL, mesma composição de
# hierarquia) -- a diferença é só nos bones de braço/perna, que em vez de
# escrever em cada "_CTRL" por segmento, escrevem em DOIS bones só por
# cadeia: a ponta (mão/pé, "_IK") e o pole target ("_Pole_CTRL").
#
# A ponta é direta: o world_target que já calculamos pro bone ORG da mão
# (mesmo world_target usado no modo CTRL_FK) é exatamente onde o "_IK" da
# ponta precisa estar (a constraint IK do rig, já configurada pelo
# rigger.py com use_tail=True, copia a orientação do alvo pro solver).
#
# O pole target é a parte que precisava de matemática nova: NÃO dá pra
# copiar rotação nenhuma (o solver de IK não usa a rotação do pole, só a
# posição, pra definir o plano de dobra do cotovelo/joelho). Em vez
# disso, replicamos a MESMA fórmula geométrica que o rigger.py usa pra
# posicionar o pole na hora de gerar o rig (_pole_position: desloca a
# partir do eixo Z do bone de referência do meio da cadeia -- ex:
# Forearm/Calf -- por uma distância fixa, pra frente ou pra trás), só que
# usando a orientação de mundo ANIMADA (world_target) desse bone em vez
# da rest pose. Isso é importante: o pole_angle de cada cadeia já foi
# calculado (uma vez, na hora de gerar o rig) especificamente pra
# compensar ESSA convenção -- usar outra fórmula (ex: perpendicular à
# linha ombro-mão) deixaria o cotovelo girado errado em torno do próprio
# eixo, mesmo com o pole numa posição "razoável".
#
# O pole target (e o "_IK" da ponta) não têm parent nenhum no Blender
# ("ponta solta", ver rigger.py) -- então a reprojeção genérica que já
# usamos no CTRL_FK simplifica sozinha pra esses dois (parent_world =
# Identity). O pole também tem constraints "Child Of" (local, seguindo a
# mão; global, seguindo um bone fixo) que, exatamente como o
# Hytale_SpineFollow do Belly/Chest, atrapalhariam se deixadas ativas --
# mutamos elas do mesmo jeito.
# ---------------------------------------------------------------------------


def _org_path(hierarchy, root_name, tip_name):
    """Caminho (lista de NOMES, root->tip) andando a hierarquia ORG --
    mesma ideia de find_org_path() em rigger.py (usada lá pra gerar o
    rig, sobre edit bones), só que aqui sobre `hierarchy` (a mesma
    estrutura que _org_hierarchy() já devolve), pra não precisar de Edit
    Mode nenhum durante o import."""
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
    """Lê armature.hytale_ik_chains e resolve cada item nos nomes de bone
    REAIS que vamos precisar -- mesma resolução que rigger.py faz na hora
    de gerar o rig (_resolve_chains), mas devolvendo só nomes/valores (não
    precisamos de Edit Mode aqui, só ler o que já existe)."""
    chains = []
    for item in armature_obj.data.hytale_ik_chains:
        if not item.root_bone or not item.tip_bone:
            continue
        path = _org_path(hierarchy, item.root_bone, item.tip_bone)
        if not path or len(path) < 2:
            continue
        pole_ref_name = item.pole_bone if item.pole_bone else path[len(path) // 2]
        chains.append(
            {
                "label": item.label or item.root_bone,
                "org_names": path,
                "ik_tip": path[-1] + SUFFIX_IK,
                "pole": path[0] + SUFFIX_POLE,
                "pole_ref": pole_ref_name,
                "pole_distance": item.pole_distance,
                "pole_invert": item.pole_invert,
            }
        )
    return chains


def _apply_ik_mode(
    operator, context, armature_obj, data, start_frame, action_name, loop_mode, bake_mode, keep_spine_follow
):
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base

    if round(fps) != FPS_HYTALE:
        operator.report(
            {"WARNING"},
            f"Scene is at {fps:g} FPS, not {FPS_HYTALE}. The animation's timing will be scaled "
            f"to match real-world duration, but will occupy far fewer Blender frames than the "
            f"file's 'time' numbers suggest -- set Output Properties > Frame Rate to {FPS_HYTALE} "
            f"for an exact 1:1 match with the .blockyanim file.",
        )

    node_animations = data["nodeAnimations"]
    if loop_mode == "CYCLE":
        hold_last = False
    elif loop_mode == "ONE_SHOT":
        hold_last = True
    else:  # "AUTO"
        hold_last = bool(data.get("holdLastKeyframe", False))
    duration = data.get("duration")
    cyclic = not hold_last

    hierarchy = _org_hierarchy(armature_obj)
    org_names_in_file = [name for name, _, _ in hierarchy if name in node_animations]
    if not org_names_in_file:
        operator.report(
            {"ERROR"},
            "None of the bones in this .blockyanim exist as original (ORG) bones on this "
            "armature -- wrong file, wrong armature, or the rig hasn't been generated yet?",
        )
        return {"CANCELLED"}

    chains = _resolve_ik_chains(armature_obj, hierarchy)
    chain_bone_names = {name for chain in chains for name in chain["org_names"]}

    delta_lookup = {}
    max_time = 0
    for name in org_names_in_file:
        channels = node_animations[name]
        for ch in ("position", "orientation"):
            for s in channels.get(ch, []):
                max_time = max(max_time, s["time"])
        pos_raw = _looped_samples(channels.get("position", []), hold_last, duration)
        rot_raw = _looped_samples(channels.get("orientation", []), hold_last, duration)
        delta_lookup[name] = _bake_delta_lookup(pos_raw, rot_raw, start_frame, fps, cyclic)
    if cyclic and duration is not None:
        max_time = max(max_time, duration)
    end_frame = hytale_time_to_frame(max_time, start_frame, fps)

    action = bpy.data.actions.new(action_name)
    anim_data = armature_obj.animation_data_create()
    anim_data.action = action

    pose_bones = armature_obj.pose.bones
    target_values = {}  # {bone_name: [(frame, loc_or_None, quat_or_None), ...]}
    target_rest_cache = {}
    warned_rotation_mode = set()

    def _rest_local(name):
        if name not in target_rest_cache:
            target_rest_cache[name] = _rest_local_matrix(pose_bones[name])
        return target_rest_cache[name]

    def _resolve_matrix_basis(pbone, world_matrix):
        """Mesma reprojeção genérica do CTRL_FK (ver nota grande lá em
        cima) -- funciona igual pra bone _CTRL ou pole, porque só depende
        do parent REAL do bone no Blender. NÃO usar pra ik_tip (mão/pé) --
        ver _resolve_ik_tip_matrix_basis logo abaixo, motivo explicado
        lá."""
        rest_local = _rest_local(pbone.name)
        parent = pbone.parent
        if parent is None:
            parent_world = Matrix.Identity(4)
        elif parent.name.endswith(SUFFIX_CTRL) and parent.name[: -len(SUFFIX_CTRL)] in world_target:
            parent_world = world_target[parent.name[: -len(SUFFIX_CTRL)]]
        else:
            parent_world = parent.matrix.copy()
        local = parent_world.inverted() @ world_matrix
        return rest_local.inverted() @ local

    def _resolve_ik_tip_matrix_basis(ik_pbone, org_rest_world, world_matrix):
        """A ponta de uma cadeia IK (_IK) tem uma rest orientation
        PRÓPRIA, diferente da do bone ORG correspondente (rigger.py
        ajusta o tail/roll do '_IK' da ponta pra apontar pra baixo, ou
        pro socket de attachment, em vez de manter a orientação original
        do ORG -- ver o comentário em _build_pose_constraints sobre por
        que o bridge/_IK_MCH usa a rest do ORG/MCH, não a do _IK, 'pra
        cópia não sair invertida'). Por isso NÃO dá pra reprojetar a
        pose-alvo direto nele com _resolve_matrix_basis -- aquela fórmula
        assume implicitamente que a rest do bone bate com a orientação do
        que ele representa visualmente, o que não é verdade aqui.

        A ponte real (bridge, _IK_MCH) é filha DE VERDADE do _IK (parent
        real, não constraint), mas com a REST do ORG (por construção --
        ver create_bone_like em rigger.py/_build_ik_layer). Isso introduz
        uma conjugação entre as duas rests que precisa ser desfeita aqui,
        ou o resultado final sai visualmente girado errado -- exatamente
        o 'invertido, Y pra baixo' reportado. Derivação: querendo que
        bridge.world == world_matrix, e sabendo que
        bridge.world = ik.world @ (ik_rest⁻¹ @ org_rest_world) e
        ik.world = ik_rest @ matrix_basis (sem parent), chega-se em:
        matrix_basis = ik_rest⁻¹ @ world_matrix @ org_rest_world⁻¹ @ ik_rest."""
        ik_rest = _rest_local(ik_pbone.name)  # sem parent -- já é a rest de mundo
        return ik_rest.inverted() @ world_matrix @ org_rest_world.inverted() @ ik_rest

    # Muta constraints extras nos bones que vamos escrever (mesma lógica
    # do CTRL_FK -- ver nota grande lá): bones NÃO-cadeia via _CTRL
    # (ex: Belly/Chest + SpineFollow), e agora também os poles (Child Of
    # local/global, ver nota grande deste bloco).
    muted_constraints = []
    if not keep_spine_follow:
        for name, _parent_name, _rest_local_mat in hierarchy:
            if name in chain_bone_names:
                continue  # esses não recebem _CTRL neste modo -- ver abaixo
            ctrl_pbone = pose_bones.get(name + SUFFIX_CTRL)
            if ctrl_pbone is None:
                continue
            for con in ctrl_pbone.constraints:
                if not con.mute:
                    con.mute = True
                    muted_constraints.append((ctrl_pbone.name, con.name))
    for chain in chains:
        pole_pbone = pose_bones.get(chain["pole"])
        if pole_pbone is None:
            continue
        for con in pole_pbone.constraints:
            if not con.mute:
                con.mute = True
                muted_constraints.append((pole_pbone.name, con.name))

    # Liga o switch FK/IK de cada cadeia pro modo IK -- valor FIXO, não
    # animado por frame (ver relatório final).
    tip_org_rest_world = {}
    for chain in chains:
        ik_pbone = pose_bones.get(chain["ik_tip"])
        if ik_pbone is not None:
            ik_pbone[PROP_FK_IK_SWITCH] = 1
            tip_org_rest_world[chain["ik_tip"]] = pose_bones[chain["org_names"][-1]].bone.matrix_local.copy()

    for frame in range(start_frame, end_frame + 1):
        world_target = {}
        for name, parent_name, rest_local in hierarchy:
            delta = delta_lookup[name](frame) if name in delta_lookup else Matrix.Identity(4)
            parent_world = world_target[parent_name] if parent_name is not None else Matrix.Identity(4)
            world_target[name] = parent_world @ rest_local @ delta

        # Bones fora de qualquer cadeia: exatamente o modo CTRL_FK.
        for name, _parent_name, _rest_local_mat in hierarchy:
            if name in chain_bone_names:
                continue
            ctrl_pbone = pose_bones.get(name + SUFFIX_CTRL)
            if ctrl_pbone is None:
                continue
            matrix_basis = _resolve_matrix_basis(ctrl_pbone, world_target[name])
            loc, quat, _scale = matrix_basis.decompose()
            if ctrl_pbone.rotation_mode != "QUATERNION":
                if ctrl_pbone.name not in warned_rotation_mode:
                    operator.report(
                        {"WARNING"},
                        f"Bone '{ctrl_pbone.name}' rotation mode was '{ctrl_pbone.rotation_mode}' -- "
                        f"switched to 'QUATERNION' to import orientation keyframes.",
                    )
                    warned_rotation_mode.add(ctrl_pbone.name)
                ctrl_pbone.rotation_mode = "QUATERNION"
            target_values.setdefault(ctrl_pbone.name, []).append((frame, loc, quat))

        # Cadeias: ponta (mão/pé) + pole.
        for chain in chains:
            tip_org_name = chain["org_names"][-1]
            ik_pbone = pose_bones.get(chain["ik_tip"])
            if ik_pbone is not None:
                matrix_basis = _resolve_ik_tip_matrix_basis(
                    ik_pbone, tip_org_rest_world[chain["ik_tip"]], world_target[tip_org_name]
                )
                loc, quat, _scale = matrix_basis.decompose()
                if ik_pbone.rotation_mode != "QUATERNION":
                    if ik_pbone.name not in warned_rotation_mode:
                        operator.report(
                            {"WARNING"},
                            f"Bone '{ik_pbone.name}' rotation mode was '{ik_pbone.rotation_mode}' -- "
                            f"switched to 'QUATERNION' to import orientation keyframes.",
                        )
                        warned_rotation_mode.add(ik_pbone.name)
                    ik_pbone.rotation_mode = "QUATERNION"
                target_values.setdefault(ik_pbone.name, []).append((frame, loc, quat))

            pole_pbone = pose_bones.get(chain["pole"])
            if pole_pbone is not None:
                pole_ref_world = world_target.get(chain["pole_ref"])
                if pole_ref_world is not None:
                    z_axis_world = pole_ref_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
                    if z_axis_world.length < 1e-9:
                        z_axis_world = Vector((0.0, 0.0, 1.0))
                    z_axis_world.normalize()
                    sign = 1.0 if chain["pole_invert"] else -1.0
                    pole_world_pos = pole_ref_world.translation + z_axis_world * (chain["pole_distance"] * sign)
                    pole_world_matrix = Matrix.Translation(pole_world_pos)
                    matrix_basis = _resolve_matrix_basis(pole_pbone, pole_world_matrix)
                    loc = matrix_basis.decompose()[0]
                    # Só posição importa pro pole (o solver de IK usa a
                    # localização dele, não a rotação) -- não mexemos em
                    # rotation_quaternion, só location.
                    target_values.setdefault(pole_pbone.name, []).append((frame, loc, None))

    for bone_name, samples in target_values.items():
        pos_samples = [(f, loc, "linear") for f, loc, _q in samples if loc is not None]
        rot_samples = [(f, quat, "linear") for f, _loc, quat in samples if quat is not None]
        if pos_samples:
            _write_channel(action, f'pose.bones["{bone_name}"].location', bone_name, 3, pos_samples)
        if rot_samples:
            _write_channel(
                action, f'pose.bones["{bone_name}"].rotation_quaternion', bone_name, 4, rot_samples
            )

    if scene.frame_end < end_frame:
        old_end = scene.frame_end
        scene.frame_end = end_frame
        operator.report(
            {"INFO"}, f"Scene Frame End was {old_end}, extended to {end_frame} to fit the imported animation."
        )

    if muted_constraints:
        affected_bones = sorted({bone_name for bone_name, _con_name in muted_constraints})
        operator.report(
            {"WARNING"},
            f"Muted {len(muted_constraints)} extra constraint(s) on {len(affected_bones)} bone(s) "
            f"(control bones with extra blend constraints, and IK pole targets' Child Of) so the "
            f"imported pose isn't blended with anything else -- left muted after import; "
            f"re-enable manually if you want that behavior back: "
            f"{', '.join(affected_bones[:8])}" + ("..." if len(affected_bones) > 8 else ""),
        )

    if not chains:
        operator.report(
            {"WARNING"},
            "No IK chains found on this armature (armature.hytale_ik_chains is empty) -- imported "
            "everything via FK control bones instead, same as Control Bones (FK) mode.",
        )

    non_chain_ctrl_count = sum(
        1 for name in target_values if not any(name == chain["ik_tip"] or name == chain["pole"] for chain in chains)
    )
    operator.report(
        {"INFO"},
        f"Imported '{action.name}' -- {len(chains)} IK chain(s) (hand/foot + pole), "
        f"{non_chain_ctrl_count} other control bone(s), {end_frame - start_frame + 1} frame(s) "
        f"each. fk_ik_switch was set to 1 (IK) on affected chains -- not keyframed, just set as a "
        f"fixed value.",
    )
    return {"FINISHED"}


# ---------------------------------------------------------------------------
# Modo BOTH: literalmente CTRL_FK + IK juntos, na MESMA passada (evita
# andar a hierarquia duas vezes). Escreve _CTRL em TODO bone -- inclusive
# os de cadeia (diferente do modo IK puro, que pula eles) -- E TAMBÉM a
# ponta/pole de cada cadeia. Os dois conjuntos de keyframe ficam
# presentes ao mesmo tempo; fk_ik_switch de cada cadeia fica em FK (0)
# por padrão, e o animador troca (por cadeia, a qualquer momento) pra
# usar a versão IK -- sem precisar reimportar nada.
# ---------------------------------------------------------------------------


def _apply_both_mode(
    operator, context, armature_obj, data, start_frame, action_name, loop_mode, bake_mode, keep_spine_follow
):
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base

    if round(fps) != FPS_HYTALE:
        operator.report(
            {"WARNING"},
            f"Scene is at {fps:g} FPS, not {FPS_HYTALE}. The animation's timing will be scaled "
            f"to match real-world duration, but will occupy far fewer Blender frames than the "
            f"file's 'time' numbers suggest -- set Output Properties > Frame Rate to {FPS_HYTALE} "
            f"for an exact 1:1 match with the .blockyanim file.",
        )

    node_animations = data["nodeAnimations"]
    if loop_mode == "CYCLE":
        hold_last = False
    elif loop_mode == "ONE_SHOT":
        hold_last = True
    else:  # "AUTO"
        hold_last = bool(data.get("holdLastKeyframe", False))
    duration = data.get("duration")
    cyclic = not hold_last

    hierarchy = _org_hierarchy(armature_obj)
    org_names_in_file = [name for name, _, _ in hierarchy if name in node_animations]
    if not org_names_in_file:
        operator.report(
            {"ERROR"},
            "None of the bones in this .blockyanim exist as original (ORG) bones on this "
            "armature -- wrong file, wrong armature, or the rig hasn't been generated yet?",
        )
        return {"CANCELLED"}

    chains = _resolve_ik_chains(armature_obj, hierarchy)

    delta_lookup = {}
    max_time = 0
    for name in org_names_in_file:
        channels = node_animations[name]
        for ch in ("position", "orientation"):
            for s in channels.get(ch, []):
                max_time = max(max_time, s["time"])
        pos_raw = _looped_samples(channels.get("position", []), hold_last, duration)
        rot_raw = _looped_samples(channels.get("orientation", []), hold_last, duration)
        delta_lookup[name] = _bake_delta_lookup(pos_raw, rot_raw, start_frame, fps, cyclic)
    if cyclic and duration is not None:
        max_time = max(max_time, duration)
    end_frame = hytale_time_to_frame(max_time, start_frame, fps)

    action = bpy.data.actions.new(action_name)
    anim_data = armature_obj.animation_data_create()
    anim_data.action = action

    pose_bones = armature_obj.pose.bones
    target_values = {}  # {bone_name: [(frame, loc_or_None, quat_or_None), ...]}
    target_rest_cache = {}
    warned_rotation_mode = set()

    def _rest_local(name):
        if name not in target_rest_cache:
            target_rest_cache[name] = _rest_local_matrix(pose_bones[name])
        return target_rest_cache[name]

    def _resolve_matrix_basis(pbone, world_matrix):
        rest_local = _rest_local(pbone.name)
        parent = pbone.parent
        if parent is None:
            parent_world = Matrix.Identity(4)
        elif parent.name.endswith(SUFFIX_CTRL) and parent.name[: -len(SUFFIX_CTRL)] in world_target:
            parent_world = world_target[parent.name[: -len(SUFFIX_CTRL)]]
        else:
            parent_world = parent.matrix.copy()
        local = parent_world.inverted() @ world_matrix
        return rest_local.inverted() @ local

    def _resolve_ik_tip_matrix_basis(ik_pbone, org_rest_world, world_matrix):
        # Ver a explicação completa da conjugação bridge/_IK em
        # _apply_ik_mode -- mesma fórmula, mesma razão.
        ik_rest = _rest_local(ik_pbone.name)
        return ik_rest.inverted() @ world_matrix @ org_rest_world.inverted() @ ik_rest

    # Muta constraints extras em TODO _CTRL -- inclusive os de cadeia,
    # já que aqui eles TAMBÉM recebem keyframe (diferente do modo IK
    # puro, que pula eles) -- + Child Of dos poles. Mesma lógica de
    # sempre, ver nota grande em _apply_ctrl_fk_mode/_apply_ik_mode.
    muted_constraints = []
    if not keep_spine_follow:
        for name, _parent_name, _rest_local_mat in hierarchy:
            ctrl_pbone = pose_bones.get(name + SUFFIX_CTRL)
            if ctrl_pbone is None:
                continue
            for con in ctrl_pbone.constraints:
                if not con.mute:
                    con.mute = True
                    muted_constraints.append((ctrl_pbone.name, con.name))
    for chain in chains:
        pole_pbone = pose_bones.get(chain["pole"])
        if pole_pbone is None:
            continue
        for con in pole_pbone.constraints:
            if not con.mute:
                con.mute = True
                muted_constraints.append((pole_pbone.name, con.name))

    # fk_ik_switch de cada cadeia fica em FK (0) por padrão -- os dois
    # conjuntos de keyframe já estão presentes e prontos; o animador
    # troca manualmente (por cadeia) pra ver/usar a versão IK.
    tip_org_rest_world = {}
    for chain in chains:
        ik_pbone = pose_bones.get(chain["ik_tip"])
        if ik_pbone is not None:
            ik_pbone[PROP_FK_IK_SWITCH] = 0
            tip_org_rest_world[chain["ik_tip"]] = pose_bones[chain["org_names"][-1]].bone.matrix_local.copy()

    for frame in range(start_frame, end_frame + 1):
        world_target = {}
        for name, parent_name, rest_local in hierarchy:
            delta = delta_lookup[name](frame) if name in delta_lookup else Matrix.Identity(4)
            parent_world = world_target[parent_name] if parent_name is not None else Matrix.Identity(4)
            world_target[name] = parent_world @ rest_local @ delta

        # FK: TODO bone, inclusive os de cadeia, via _CTRL.
        for name, _parent_name, _rest_local_mat in hierarchy:
            ctrl_pbone = pose_bones.get(name + SUFFIX_CTRL)
            if ctrl_pbone is None:
                continue
            matrix_basis = _resolve_matrix_basis(ctrl_pbone, world_target[name])
            loc, quat, _scale = matrix_basis.decompose()
            if ctrl_pbone.rotation_mode != "QUATERNION":
                if ctrl_pbone.name not in warned_rotation_mode:
                    operator.report(
                        {"WARNING"},
                        f"Bone '{ctrl_pbone.name}' rotation mode was '{ctrl_pbone.rotation_mode}' -- "
                        f"switched to 'QUATERNION' to import orientation keyframes.",
                    )
                    warned_rotation_mode.add(ctrl_pbone.name)
                ctrl_pbone.rotation_mode = "QUATERNION"
            target_values.setdefault(ctrl_pbone.name, []).append((frame, loc, quat))

        # IK: ponta (mão/pé) + pole de cada cadeia, ALÉM do FK acima.
        for chain in chains:
            tip_org_name = chain["org_names"][-1]
            ik_pbone = pose_bones.get(chain["ik_tip"])
            if ik_pbone is not None:
                matrix_basis = _resolve_ik_tip_matrix_basis(
                    ik_pbone, tip_org_rest_world[chain["ik_tip"]], world_target[tip_org_name]
                )
                loc, quat, _scale = matrix_basis.decompose()
                if ik_pbone.rotation_mode != "QUATERNION":
                    if ik_pbone.name not in warned_rotation_mode:
                        operator.report(
                            {"WARNING"},
                            f"Bone '{ik_pbone.name}' rotation mode was '{ik_pbone.rotation_mode}' -- "
                            f"switched to 'QUATERNION' to import orientation keyframes.",
                        )
                        warned_rotation_mode.add(ik_pbone.name)
                    ik_pbone.rotation_mode = "QUATERNION"
                target_values.setdefault(ik_pbone.name, []).append((frame, loc, quat))

            pole_pbone = pose_bones.get(chain["pole"])
            if pole_pbone is not None:
                pole_ref_world = world_target.get(chain["pole_ref"])
                if pole_ref_world is not None:
                    z_axis_world = pole_ref_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
                    if z_axis_world.length < 1e-9:
                        z_axis_world = Vector((0.0, 0.0, 1.0))
                    z_axis_world.normalize()
                    sign = 1.0 if chain["pole_invert"] else -1.0
                    pole_world_pos = pole_ref_world.translation + z_axis_world * (chain["pole_distance"] * sign)
                    pole_world_matrix = Matrix.Translation(pole_world_pos)
                    matrix_basis = _resolve_matrix_basis(pole_pbone, pole_world_matrix)
                    loc = matrix_basis.decompose()[0]
                    target_values.setdefault(pole_pbone.name, []).append((frame, loc, None))

    for bone_name, samples in target_values.items():
        pos_samples = [(f, loc, "linear") for f, loc, _q in samples if loc is not None]
        rot_samples = [(f, quat, "linear") for f, _loc, quat in samples if quat is not None]
        if pos_samples:
            _write_channel(action, f'pose.bones["{bone_name}"].location', bone_name, 3, pos_samples)
        if rot_samples:
            _write_channel(
                action, f'pose.bones["{bone_name}"].rotation_quaternion', bone_name, 4, rot_samples
            )

    if scene.frame_end < end_frame:
        old_end = scene.frame_end
        scene.frame_end = end_frame
        operator.report(
            {"INFO"}, f"Scene Frame End was {old_end}, extended to {end_frame} to fit the imported animation."
        )

    if muted_constraints:
        affected_bones = sorted({bone_name for bone_name, _con_name in muted_constraints})
        operator.report(
            {"WARNING"},
            f"Muted {len(muted_constraints)} extra constraint(s) on {len(affected_bones)} bone(s) "
            f"(control bones with extra blend constraints, and IK pole targets' Child Of) so the "
            f"imported pose isn't blended with anything else -- left muted after import; "
            f"re-enable manually if you want that behavior back: "
            f"{', '.join(affected_bones[:8])}" + ("..." if len(affected_bones) > 8 else ""),
        )

    non_chain_ctrl_count = sum(
        1 for name in target_values if not any(name == chain["ik_tip"] or name == chain["pole"] for chain in chains)
    )
    operator.report(
        {"INFO"},
        f"Imported '{action.name}' -- wrote BOTH Control FK ({non_chain_ctrl_count} control bone(s), "
        f"including chain segments) AND Control IK ({len(chains)} chain(s): hand/foot + pole), "
        f"{end_frame - start_frame + 1} frame(s) each. fk_ik_switch defaults to 0 (FK) on every "
        f"chain -- toggle per chain, any time, to preview/use the IK version instead.",
    )
    return {"FINISHED"}


# ---------------------------------------------------------------------------
# Dispatch de modo -- os quatro modos (ORG/CTRL_FK/IK/BOTH) já implementados.
# ---------------------------------------------------------------------------

_MODE_HANDLERS = {
    "ORG": _apply_org_mode,
    "CTRL_FK": _apply_ctrl_fk_mode,
    "IK": _apply_ik_mode,
    "BOTH": _apply_both_mode,
}


class IMPORT_OT_hytale_blockyanim(Operator, ImportHelper):
    """Import a .blockyanim file onto the active armature"""

    bl_idname = "import_scene.hytale_blockyanim"
    bl_label = "Import Hytale Animation"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".blockyanim"
    filter_glob: StringProperty(default="*.blockyanim", options={"HIDDEN"})

    target_mode: EnumProperty(
        name="Target",
        description="Which bone layer to write the imported animation onto",
        items=[
            (
                "ORG",
                "Original Bones",
                "Keyframe the original game bones directly. Works on ANY armature -- rigged or "
                "not -- but on a rig with an FK/IK control layer on top, these keyframes won't "
                "move anything (the original bones are constrained to follow the control layer)",
            ),
            (
                "BOTH",
                "Default (FK + IK)",
                "Writes Control FK and Control IK at the same time -- every bone gets its FK "
                "'_CTRL' (chain segments included) AND every chain's IK tip + pole also get "
                "keyframed, in the same pass. fk_ik_switch defaults to FK (0) on every chain; "
                "toggle it any time afterward, per chain, to preview or use the IK version "
                "instead -- no need to reimport",
            ),
            (
                "CTRL_FK",
                "Control FK",
                "Writes onto the '_CTRL' bones generated by the auto-rig tool (rigger.py), so the "
                "imported animation stays editable through the control rig. Always writes a dense "
                "keyframe on every frame (the 'Bake to Every Frame' toggle doesn't apply here -- "
                "see anim_importer.py notes). Arm/leg chain bones are written via their per-segment "
                "_CTRL too, with the fk_ik_switch left on FK -- use 'Control IK' instead to drive "
                "those through IK",
            ),
            (
                "IK",
                "Control IK",
                "Same as Control FK for everything outside a chain (torso, head, fingers etc.) -- "
                "arm/leg chains are retargeted onto the '_IK' tip (hand/foot) and pole target "
                "instead of their per-segment '_CTRL', and fk_ik_switch is set to IK. Reads "
                "armature.hytale_ik_chains (rigger.py) to find the chains -- falls back to "
                "Control FK behavior entirely if that list is empty",
            ),
        ],
        default="ORG",
    )
    action_name: StringProperty(
        name="Action Name",
        description="Leave empty to use the file name",
        default="",
    )
    start_frame: IntProperty(
        name="Start Frame",
        description="Blender frame where time=0 of the animation file lands",
        default=1,
    )
    loop_mode: EnumProperty(
        name="Looping",
        description="Whether this clip should close into a seamless loop",
        items=[
            (
                "AUTO",
                "Auto (from file)",
                "Use the file's own 'holdLastKeyframe' flag: false = cycle (loop), true = "
                "start & end (hold last pose)",
            ),
            (
                "CYCLE",
                "Cycle (loop)",
                "Force this clip to close into a loop: adds a closing pose at 'duration' that "
                "matches each channel's first keyframe, so it flows back into itself -- use for "
                "walk/run/idle cycles",
            ),
            (
                "ONE_SHOT",
                "Start & End (no loop)",
                "Force this clip to just hold its last pose at the end -- use for non-looping "
                "actions (attacks, deaths, one-off gestures)",
            ),
        ],
        default="AUTO",
    )
    bake_mode: BoolProperty(
        name="Bake to Every Frame",
        description=(
            "Compute the exact pose at every frame directly from the file's raw keyframes "
            "(proper spherical interpolation for rotation), instead of relying on Blender's own "
            "per-component Bezier F-Curves. Produces far more keyframes, but avoids rotation "
            "interpolation artifacts -- especially noticeable with few, far-apart orientation "
            "keyframes (common in this format). Recommended for Cycle imports. Only affects "
            "'Original Bones' -- 'Control Bones (FK)' always bakes every frame regardless"
        ),
        default=False,
    )
    keep_spine_follow: BoolProperty(
        name="Keep Spine-Follow Active",
        description=(
            "Control FK, Control IK and Default (FK + IK) only: by default, any extra constraint "
            "on a control bone (ex: Belly_CTRL/Chest_CTRL partially following root.spine_CTRL) is "
            "muted during import, so the imported pose matches the source file exactly -- in modes "
            "that write IK, each pole target's Child Of constraints are also muted for the same "
            "reason. Enable this to leave those constraints active instead, keeping "
            "root.spine_CTRL (and the poles' Child Of) usable as fine-tuning tools on top of the "
            "imported animation -- at the cost of the affected bones no longer matching the source "
            "file exactly"
        ),
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def invoke(self, context, event):
        # Pré-preenche o nome da Action com o nome do arquivo antes de abrir
        # o file browser -- ImportHelper só sabe o filepath depois que o
        # usuário escolhe, então o campo fica vazio até a primeira escolha
        # e só usamos o fallback (nome do arquivo) no execute() mesmo.
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
        )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "target_mode")
        layout.prop(self, "action_name")
        layout.prop(self, "start_frame")
        layout.prop(self, "loop_mode")
        layout.prop(self, "bake_mode")
        if self.target_mode in {"CTRL_FK", "IK", "BOTH"}:
            layout.prop(self, "keep_spine_follow")


def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_hytale_blockyanim.bl_idname, text="Hytale Animation (.blockyanim)")


_CLASSES = (IMPORT_OT_hytale_blockyanim,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
