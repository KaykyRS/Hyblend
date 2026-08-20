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
# DOIS modos de destino (target_mode, no operador
# IMPORT_OT_hytale_blockyanim) -- pensados como CAMADAS que se apoiam uma
# na outra, não caminhos paralelos independentes:
#
#   ORG  -- keyframa o bone ORIGINAL direto (mesmo nome do
#           .blockymodel/.blockyanim). Funciona em QUALQUER Armature que
#           tenha esses bones, rigada ou não -- é o modo genérico que
#           precisa funcionar pra QUALQUER personagem/criatura do Hytale,
#           não só o Player. Numa Armature COM rig gerado, os keyframes
#           não movem nada visualmente (o ORG está constrained -- ver
#           Hytale_ORG_to_MCH em rigger.py).
#   CTRL -- escreve nos bones "_CTRL"/"_IK"/pole (rigger.py) em vez do
#           ORG, calculando a pose de mundo pretendida (andando a
#           hierarquia ORG) e reprojetando no PAI REAL de cada bone no
#           Blender (pode ser diferente do pai ORG -- ver
#           CTRL_PARENT_OVERRIDES em rigger.py). Três sub-opções
#           INDEPENDENTES (ver _apply_ctrl_mode pra detalhes de cada
#           uma):
#             Spine -- Default (root.master_CTRL/root.pelvis_CTRL
#                      seguem o Pelvis, ver _apply_root_follow) ou
#                      Spine CTRL (ficam parados, root.spine_CTRL livre
#                      pra ajuste manual).
#             Arms/Legs (cada um independente, mesmas 3 opções) --
#                      Default (FK+IK), Control FK, ou Control IK (ver
#                      armature.hytale_ik_chains, rigger.py -- cada
#                      cadeia tem um "chain_type" ARM/LEG que diz a qual
#                      grupo ela pertence). Bones fora de cadeia nenhuma
#                      (torso, cabeça, dedos, cauda) sempre vão por FK,
#                      independente dessas opções.
#           O pole é posicionado replicando a MESMA fórmula geométrica
#           que o rigger.py usa na hora de gerar o rig (offset a partir
#           do eixo Z do bone do meio da cadeia), só que com a
#           orientação ANIMADA em vez da rest pose -- importante pra
#           bater com o pole_angle já calibrado. A ponta (_IK) precisa
#           de uma correção extra (_resolve_ik_tip_matrix_basis) porque
#           sua rest orientation é diferente da do ORG/bridge (rigger.py
#           ajusta tail/roll dela) -- ver o comentário grande ali se for
#           mexer nisso.
#
# Bones _CTRL com constraint extra (ex: Belly_CTRL/Chest_CTRL seguindo
# root.spine_CTRL via Hytale_SpineFollow) e os Child Of dos pole targets
# ficam ATIVOS por padrão durante o import (Target=Controllers), a menos
# que `keep_spine_follow=False` -- ver nota grande em _apply_ctrl_mode.
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
from collections import deque, namedtuple

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Quaternion, Vector

from .common import (
    ACTION_SOURCE_DURATION_PROP,
    ACTION_SOURCE_HOLD_LAST_KEYFRAME_PROP,
    FPS_HYTALE,
    UNIT_SCALE_DEFAULT,
    quat_xyzw,
    vec3,
)
from .rigger import (
    BONE_ROOT_MASTER,
    BONE_ROOT_PELVIS,
    PROP_FK_IK_SWITCH,
    PROP_RIG_LAYER,
    SUFFIX_CTRL,
    SUFFIX_IK,
    SUFFIX_MCH,
    SUFFIX_POLE,
    SUFFIX_TAIL,
)

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


def _bake_stretch_samples(samples, start_frame, fps, cyclic):
    """Mesmo motor Hermite/Catmull-Rom de _bake_position_samples, mas SEM
    aplicar UNIT_SCALE_DEFAULT -- 'shapeStretch' é um fator de escala
    ADIMENSIONAL (mesma natureza do 'stretch' de shape que importer.py já
    trata assim pro .bbmodel/.blockymodel, ver nota grande lá), não uma
    medida de comprimento. Eixo ausente no arquivo assume 1.0 (escala
    identidade), não 0.0 -- por isso o default= explícito no vec3()."""
    times = [s["time"] for s in samples]
    values = [vec3(s.get("delta", {}), default=1.0) for s in samples]
    return _hermite_resample(times, values, start_frame, fps, cyclic)


def _apply_stretch_channels(operator, armature_obj, action, node_animations, hold_last, duration, start_frame, fps, bake_mode):
    """Aplica o canal 'shapeStretch' (escala do bone), INDEPENDENTE do
    target_mode (ORG ou CTRL) -- chamada por AMBOS _apply_org_mode e
    _apply_ctrl_mode, sempre por último, escrevendo na MESMA action que
    cada um já criou.

    EM QUAL BONE ESCREVER (isso NÃO depende do target_mode escolhido, e
    sim de o RIG existir ou não nesta Armature): _build_pose_constraints
    (rigger.py) cria, pra cada bone com par MCH+CTRL, um trio Location/
    Rotation/**Scale** (ensure_copy_set(..., types=(...,"SCALE")),
    CONSTRAINT_ORG_TO_MCH) fazendo o ORG copiar a escala do MCH, que por
    sua vez copia a escala do _CTRL (FK_CopyScale). Ou seja: numa
    Armature rigada, escrever pbone.scale direto no ORG é sobrescrito
    pela constraint (some, some volta pra identidade) -- a escala "de
    verdade" mora no _CTRL. Por isso: se o bone tiver um `_CTRL`
    correspondente na Armature, escrevemos NELE; senão (bone sem rig
    nenhum em cima, ou Armature sem rig gerado), caímos pro bone ORG
    direto, que aí sim fica livre. É esse fallback que faz o import
    funcionar tanto numa Armature crua quanto numa já rigada, sem
    precisar saber de antemão qual das duas é.

    Faltava por completo antes desta função existir -- 'shapeStretch' não
    era lido em lugar nenhum deste módulo. É o que fazia, por exemplo,
    uma sobrancelha animada erguendo (shapeStretch.y indo de 1 pra 1.5)
    ficar com a posição/orientação certas mas sem o "esticar", porque só
    esses dois canais eram aplicados."""
    pose_bones = armature_obj.pose.bones
    written_names = []
    max_frame_seen = start_frame
    for name, channels in node_animations.items():
        target_name = name + SUFFIX_CTRL if (name + SUFFIX_CTRL) in pose_bones else name
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
            f'pose.bones["{target_name}"].scale',
            target_name,
            3,
            stretch_samples,
        )
        written_names.append(target_name)
        max_frame_seen = max(max_frame_seen, max(f for f, _, _ in stretch_samples))
    return written_names, max_frame_seen


def _stamp_action_source_metadata(action, data):
    """Grava 'duration' e 'holdLastKeyframe' do ARQUIVO ORIGINAL como
    custom properties na Action recém-criada, pro exporter.py poder
    reescrever esses dois campos fielmente num reexport em vez de ter que
    reconstruí-los adivinhando a partir do estado atual da timeline/
    F-Curves do Blender (que pode divergir -- ex: 'duration' do arquivo
    pode ser maior que o último keyframe real de qualquer canal, algo
    que não dá pra recuperar só olhando os F-Curves depois do import).
    Ver DEVELOPER_NOTES.md / common.py para o nome exato dessas duas
    propriedades (ACTION_SOURCE_DURATION_PROP /
    ACTION_SOURCE_HOLD_LAST_KEYFRAME_PROP) -- o exporter.py PRECISA usar
    os MESMOS nomes pra este contrato funcionar."""
    duration = data.get("duration")
    if duration is not None:
        action[ACTION_SOURCE_DURATION_PROP] = duration
    action[ACTION_SOURCE_HOLD_LAST_KEYFRAME_PROP] = bool(data.get("holdLastKeyframe", False))


def _apply_org_mode(
    operator, context, armature_obj, data, start_frame, action_name, loop_mode, bake_mode, keep_spine_follow,
    spine_mode="DEFAULT", arms_mode="BOTH", legs_mode="BOTH",
):
    """Modo ORG: keyframa os bones originais direto, sem passar por
    nenhuma camada de controle. Ver nota grande no topo do módulo sobre
    por que delta_local == matrix_basis nesse caso (sem constraint por
    cima), e por isso não precisamos de rest_matrices/pose_matrices
    nenhuma aqui -- só desfazer a conversão que compute_deltas() fez.

    'keep_spine_follow' e os 3 argumentos de Target=Controllers
    (spine_mode/arms_mode/legs_mode) não se aplicam a este modo (não
    existe camada de controle/constraint nenhuma aqui, e
    root.master_CTRL/root.pelvis_CTRL/cadeias IK só existem na camada de
    controle) -- recebidos só pra manter a assinatura igual à de
    _apply_ctrl_mode, já que o dispatch em _MODE_HANDLERS chama todo
    handler com os MESMOS argumentos."""
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
    _warn_if_fps_mismatch(operator, fps)

    node_animations = data["nodeAnimations"]

    # loop_mode escolhido pelo usuário sobrescreve o que o ARQUIVO diz
    # (holdLastKeyframe) -- "AUTO" é o único que de fato lê o arquivo;
    # "CYCLE"/"ONE_SHOT" forçam o comportamento independente do que o
    # arquivo declara, pros casos em que o valor do arquivo está errado/
    # ausente ou o usuário simplesmente quer testar o outro modo.
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

    # A cena (Frame End da Timeline) pode estar mais curta do que a
    # animação recém-importada -- se a gente não esticar isso, o EXPORT
    # (que sampleia dentro do range da cena) corta o final da animação
    # sem avisar. Só estica, nunca encolhe (nunca mexe em frame_start:
    # como 'time' do arquivo nunca é negativo, o frame mínimo já é
    # sempre >= start_frame, então frame_start da cena não precisa mudar).
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


# ---------------------------------------------------------------------------
# Helpers compartilhados por CTRL_FK / IK / BOTH -- os três modos fazem
# exatamente a mesma preparação (checagem de FPS, resolução de loop,
# hierarquia ORG + delta_lookup, criação da Action), a mesma reprojeção de
# matriz por bone (parent real _CTRL/_MCH/utilitário) e o mesmo pós-
# processamento (escrever F-Curves, esticar Frame End, mutar/relatar
# constraints extras). Extraído aqui pra não manter três cópias quase
# idênticas -- cada modo só precisa fornecer a parte que É de fato
# diferente: QUAIS bones escreve e COMO calcula o world_matrix de cada um.
# ---------------------------------------------------------------------------


def _warn_if_fps_mismatch(operator, fps):
    """Aviso compartilhado pelos 4 modos (ORG incluso -- chamado à parte
    lá) -- ver a explicação completa dentro de _apply_org_mode (docstring
    histórica, mantida lá) sobre por que um FPS de cena != FPS_HYTALE
    ainda é matematicamente correto, só não é 1:1 com os números do
    arquivo."""
    if round(fps) != FPS_HYTALE:
        operator.report(
            {"WARNING"},
            f"Scene is at {fps:g} FPS, not {FPS_HYTALE}. The animation's timing will be scaled "
            f"to match real-world duration, but will occupy far fewer Blender frames than the "
            f"file's 'time' numbers suggest -- set Output Properties > Frame Rate to {FPS_HYTALE} "
            f"for an exact 1:1 match with the .blockyanim file.",
        )


def _resolve_loop_settings(data, loop_mode):
    """loop_mode escolhido pelo usuário sobrescreve o que o ARQUIVO diz
    (holdLastKeyframe) -- "AUTO" é o único que de fato lê o arquivo;
    "CYCLE"/"ONE_SHOT" forçam o comportamento independente do que o
    arquivo declara. Devolve (hold_last, duration, cyclic)."""
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
    """Preparação compartilhada por CTRL_FK/IK/BOTH: valida FPS, resolve
    hold_last/duration/cyclic, monta a hierarquia ORG + um lookup(frame)
    de delta_local por bone (mesmo _org_hierarchy/_bake_delta_lookup que
    cada modo usava separado), calcula end_frame e cria a Action de
    destino. Devolve None (já reportando {'ERROR'}) se nenhum bone do
    arquivo existir como ORG na armature -- chamador deve retornar
    {'CANCELLED'} nesse caso."""
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base
    _warn_if_fps_mismatch(operator, fps)

    node_animations = data["nodeAnimations"]
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
    """Anda a hierarquia ORG inteira (pai antes de filho, já garantido
    pela ordem de _org_hierarchy) pra um ÚNICO frame, devolvendo
    {nome_org: Matrix de mundo pretendida}. Mesma composição usada pelos
    três modos CTRL_FK/IK/BOTH."""
    world_target = {}
    for name, parent_name, rest_local in hierarchy:
        delta = delta_lookup[name](frame) if name in delta_lookup else Matrix.Identity(4)
        parent_world = world_target[parent_name] if parent_name is not None else Matrix.Identity(4)
        world_target[name] = parent_world @ rest_local @ delta
    return world_target


def _get_rest_local(pbone, rest_cache):
    """Cache compartilhado de _rest_local_matrix, indexado por NOME de
    pose bone -- funciona igual pra bone _CTRL, _IK da ponta, ou pole,
    já que cada um tem um nome único na Armature."""
    if pbone.name not in rest_cache:
        rest_cache[pbone.name] = _rest_local_matrix(pbone)
    return rest_cache[pbone.name]


def _resolve_parent_world(parent, world_target, rest_cache, pose_bones):
    """Matriz de mundo do PARENT REAL (no Blender) de um bone de
    controle/pole/ik-tip, pra reprojeção genérica de _resolve_matrix_basis
    -- ver a derivação completa no comentário grande "Modo CTRL_FK" logo
    acima de _rest_local_matrix.

    Três casos, nessa ordem:
      1) Parent termina em SUFFIX_CTRL e o bone ORG correspondente está
         no world_target deste frame -- usa a pose ANIMADA desse ORG.
         v0.6 (revisão): SE esse `_CTRL` pai tiver um bridge `_Tail`
         (cadeia TAIL -- ver _build_tail_layer, rigger.py), a pose real
         dele NÃO é `world_target[org_name]` -- é esse valor com a MESMA
         correção de _resolve_ctrl_matrix_basis aplicada (ver lá a
         derivação completa). Sem isso, cada segmento de uma cauda
         encadeada (Tail2_CTRL filho de Tail_CTRL, filho de Tail_CTRL...)
         herdava a referência ERRADA do segmento anterior e o erro ia
         se acumulando bone a bone -- é exatamente por isso que só
         corrigir a equação de CADA bone individualmente (a versão
         anterior desta função) não bastava.
      2) Parent termina em SUFFIX_MCH (idem, sem essa correção -- MCH
         nunca é escrito diretamente por este importador, converge pro
         world_target via constraint em tempo de execução, não por um
         matrix_basis que a gente calcula aqui) -- caso de attachments/
         filhos de ponta de cadeia que o rigger.py reparenta pro _MCH em
         vez do _CTRL da ponta (ex: dedos, sockets de arma na mão): _MCH
         é quem reflete o resultado final tanto em FK quanto em IK,
         diferente do _CTRL da ponta (que só se move em FK).
      3) Nenhum dos dois bateu (bone utilitário como root.pelvis_CTRL, ou
         _CTRL/_MCH de um bone ORG que não está neste arquivo) -- assume
         que não está sendo animado por NADA neste import, e usa a pose
         ATUAL dele no Blender como referência fixa.
    """
    if parent is None:
        return Matrix.Identity(4)
    for suffix in (SUFFIX_CTRL, SUFFIX_MCH):
        if parent.name.endswith(suffix):
            org_name = parent.name[: -len(suffix)]
            if org_name in world_target:
                target = world_target[org_name]
                if suffix == SUFFIX_CTRL:
                    bridge_pbone = pose_bones.get(org_name + SUFFIX_TAIL)
                    if bridge_pbone is not None:
                        bridge_rest = _get_rest_local(bridge_pbone, rest_cache)
                        return target @ bridge_rest.inverted()
                return target
    return parent.matrix.copy()


def _resolve_matrix_basis(pbone, world_matrix, world_target, rest_cache, pose_bones):
    """matrix_basis (o que pbone.location/rotation_quaternion representam)
    que faz `pbone` ocupar `world_matrix` no espaço de mundo, reprojetando
    através do PARENT REAL dele no Blender -- ver _resolve_parent_world.
    NÃO usar pra ik_tip (mão/pé de uma cadeia) -- ver
    _resolve_ik_tip_matrix_basis, motivo explicado lá."""
    rest_local = _get_rest_local(pbone, rest_cache)
    parent_world = _resolve_parent_world(pbone.parent, world_target, rest_cache, pose_bones)
    local = parent_world.inverted() @ world_matrix
    return rest_local.inverted() @ local


def _resolve_ctrl_matrix_basis(ctrl_pbone, org_name, world_matrix, world_target, rest_cache, pose_bones):
    """Wrapper de _resolve_matrix_basis pra um bone `_CTRL` -- igual à
    versão genérica na grande maioria dos casos, EXCETO quando esse
    `_CTRL` tem um bridge `_Tail` como filho de verdade (rigger.py,
    HytaleIKChainItem.chain_type == 'TAIL', ver _build_tail_layer): nesse
    caso, o rest do `_CTRL` foi deliberadamente desviado do rest do ORG
    (redirecionado pro head do próximo segmento da cauda -- ver
    SUFFIX_TAIL/_build_tail_layer, rigger.py), e é o BRIDGE quem
    realmente precisa bater com a pose-alvo (é ele que o MCH copia, não
    o `_CTRL` -- ver _build_tail_pose_constraints, rigger.py). Mesmo
    princípio exato de _resolve_ik_tip_matrix_basis (mesmo comentário:
    "aquela fórmula assume implicitamente que a rest do bone bate com a
    orientação do que ele representa visualmente, o que não é verdade
    aqui") -- só que aqui o bone com a rest "correta" (a do ORG) é um
    FILHO do bone que estamos escrevendo, não o próprio.

    Derivação (mesma notação de _resolve_ik_tip_matrix_basis, tudo em
    espaço de armature): bridge.matrix = ctrl.matrix @ rest_local(bridge)
    (bridge não tem pose própria, matrix_basis dele é sempre identidade),
    e ctrl.matrix = parent_world @ rest_local(ctrl) @ matrix_basis.
    Querendo bridge.matrix == world_matrix:

        matrix_basis = rest_local(ctrl)⁻¹ @ parent_world⁻¹ @ world_matrix
                        @ rest_local(bridge)⁻¹

    Que é EXATAMENTE a fórmula genérica de _resolve_matrix_basis com um
    "@ rest_local(bridge)⁻¹" a mais no final -- faz sentido: sem bridge
    nenhum (a maioria dos `_CTRL` do rig), essa correção não existe e as
    duas fórmulas são a mesma coisa. IMPORTANTE: como esse `_CTRL` mesmo
    NÃO fica em `world_matrix` (só o bridge fica), qualquer FILHO deste
    `_CTRL` (o próximo segmento da cauda) precisa saber disso também ao
    calcular SUA PRÓPRIA referência de pai -- ver a mesma correção
    espelhada em _resolve_parent_world."""
    bridge_pbone = pose_bones.get(org_name + SUFFIX_TAIL)
    if bridge_pbone is None:
        return _resolve_matrix_basis(ctrl_pbone, world_matrix, world_target, rest_cache, pose_bones)
    ctrl_rest = _get_rest_local(ctrl_pbone, rest_cache)
    parent_world = _resolve_parent_world(ctrl_pbone.parent, world_target, rest_cache, pose_bones)
    bridge_rest = _get_rest_local(bridge_pbone, rest_cache)
    local = parent_world.inverted() @ world_matrix
    return ctrl_rest.inverted() @ local @ bridge_rest.inverted()


def _resolve_ik_tip_matrix_basis(ik_pbone, org_rest_world, world_matrix, rest_cache):
    """A ponta de uma cadeia IK (_IK) tem uma rest orientation PRÓPRIA,
    diferente da do bone ORG correspondente (rigger.py ajusta o
    tail/roll dela pra apontar pra baixo, ou pro socket de attachment,
    em vez de manter a orientação original do ORG -- ver o comentário em
    _build_pose_constraints, rigger.py, sobre por que o bridge/_IK_MCH
    usa a rest do ORG/MCH, não a do _IK, 'pra cópia não sair invertida').
    Por isso NÃO dá pra reprojetar a pose-alvo direto nela com
    _resolve_matrix_basis -- aquela fórmula assume implicitamente que a
    rest do bone bate com a orientação do que ele representa
    visualmente, o que não é verdade aqui.

    A ponte real (bridge, _IK_MCH) é filha DE VERDADE do _IK (parent
    real, não constraint), mas com a REST do ORG (por construção -- ver
    create_bone_like em rigger.py/_build_ik_layer). Isso introduz uma
    conjugação entre as duas rests que precisa ser desfeita aqui, ou o
    resultado final sai visualmente girado errado. Derivação: querendo
    que bridge.world == world_matrix, e sabendo que
    bridge.world = ik.world @ (ik_rest⁻¹ @ org_rest_world) e
    ik.world = ik_rest @ matrix_basis (sem parent), chega-se em:
    matrix_basis = ik_rest⁻¹ @ world_matrix @ org_rest_world⁻¹ @ ik_rest."""
    ik_rest = _get_rest_local(ik_pbone, rest_cache)  # sem parent -- já é a rest de mundo
    return ik_rest.inverted() @ world_matrix @ org_rest_world.inverted() @ ik_rest


def _compute_pole_world_matrix(chain, world_target):
    """Réplica da MESMA fórmula geométrica que rigger.py usa pra
    posicionar o pole na hora de gerar o rig (offset a partir do eixo Z
    do bone de referência do meio da cadeia), só que usando a orientação
    de mundo ANIMADA (world_target) em vez da rest pose -- ver a nota
    grande no topo do arquivo (seção "CTRL" -- Arms/Legs) pra por que essa
    convenção importa (pole_angle calibrado em cima dela). Devolve None
    se o bone de referência não está no world_target deste frame."""
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
    """Força rotation_mode='QUATERNION' (necessário pra escrever
    rotation_quaternion) e avisa UMA VEZ por bone (via `warned_set`
    compartilhado entre frames/bones do mesmo import) se o bone estava
    em outro modo -- muda como qualquer OUTRA Action nesse bone é posada,
    então vale avisar."""
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
    """Muta toda constraint ainda ATIVA em cada pbone de `pbones`,
    registrando (nome_do_bone, nome_da_constraint) em `muted_constraints`
    -- genérico (não hardcoding nomes conhecidos do rigger.py), pra
    continuar funcionando mesmo que o rig mude no futuro. Usado tanto
    pra bones _CTRL com constraint extra (ex: Belly_CTRL/Chest_CTRL
    seguindo root.spine_CTRL) quanto pros Child Of dos pole targets --
    ver a nota grande "Modo CTRL_FK" acima de _rest_local_matrix
    pro motivo de mutar em vez de deixar ativo."""
    for pbone in pbones:
        if pbone is None:
            continue
        for con in pbone.constraints:
            if not con.mute:
                con.mute = True
                muted_constraints.append((pbone.name, con.name))


def _write_pose_samples(action, target_values):
    """Escreve, pra cada bone em `target_values`
    ({bone_name: [(frame, loc_ou_None, quat_ou_None), ...]}), as F-Curves
    de location (se houver amostra de posição) e rotation_quaternion (se
    houver amostra de rotação) -- um pole target, por exemplo, só tem
    loc (quat=None em toda amostra seguindo _resolve_matrix_basis, que
    não é chamada pra rotação de pole)."""
    for bone_name, samples in target_values.items():
        pos_samples = [(f, loc, "linear") for f, loc, _q in samples if loc is not None]
        rot_samples = [(f, quat, "linear") for f, _loc, quat in samples if quat is not None]
        if pos_samples:
            _write_channel(action, f'pose.bones["{bone_name}"].location', bone_name, 3, pos_samples)
        if rot_samples:
            _write_channel(action, f'pose.bones["{bone_name}"].rotation_quaternion', bone_name, 4, rot_samples)


def _extend_scene_frame_end(operator, scene, end_frame):
    """A cena (Frame End da Timeline) pode estar mais curta do que a
    animação recém-importada -- se a gente não esticar isso, o EXPORT
    (que sampleia dentro do range da cena) corta o final da animação sem
    avisar. Só estica, nunca encolhe."""
    if scene.frame_end < end_frame:
        old_end = scene.frame_end
        scene.frame_end = end_frame
        operator.report(
            {"INFO"},
            f"Scene Frame End was {old_end}, extended to {end_frame} to fit the imported animation.",
        )


def _report_muted_constraints(operator, muted_constraints, note):
    """Relatório final de quais constraints extras foram mutadas (ver
    _mute_constraints_on) -- `note` é o parêntese que diferencia o motivo
    entre os modos (CTRL_FK só tem spine-follow; IK/BOTH também têm o
    Child Of dos poles)."""
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


# ---------------------------------------------------------------------------
# root.master_CTRL / root.pelvis_CTRL (rigger.py) são bones UTILITÁRIOS --
# não derivam de nenhum bone ORG por sufixo (ver _build_root_controls,
# rigger.py), então NUNCA aparecem em `world_target` (que só tem entradas
# pra bones da hierarquia ORG -- ver _org_hierarchy/_compute_world_targets)
# e por consequência sempre caem no fallback "pose ATUAL/estática" de
# _resolve_parent_world. Como as animações originais do Hytale só mexem em
# Pelvis/Belly/Chest (nunca em nenhum bone "root.*"), isso significa que
# root.master_CTRL/root.pelvis_CTRL ficam PARADOS durante o import inteiro
# -- e tudo que pende deles de verdade no Blender (Pelvis_CTRL via
# CTRL_PARENT_OVERRIDES, L-Thigh_CTRL, R-Thigh_CTRL, e Belly_CTRL no caso
# do master) reprojeta contra essa base estática errada sempre que o
# personagem se desloca (ex.: anda pra frente) -- o corpo inteiro fica
# "preso" na origem em vez de andar junto com o Pelvis.
#
# Fix (v0.7, controlado por 3 checkboxes independentes na UI --
# root_master_follow_loc/root_master_follow_rot/root_pelvis_follow_rot):
# faz Pelvis "emprestar" sua pose de mundo ANIMADA (já calculada em
# world_target["Pelvis"], de graça, todo frame) pros bones raiz escolhidos
# -- injetando ela em `world_target` sob a MESMA chave que
# _resolve_parent_world já sabe procurar (nome do bone sem o "_CTRL").
#
# v0.7 (revisão -- fix da propagação): a v0.7 original só injetava
# "root.master" (quando master seguia o Pelvis), mas NUNCA "root.pelvis"
# -- então quando root.master_CTRL passava a se mover, root.pelvis_CTRL
# (filho REAL dele, SEM keyframe próprio) também passava a se mover NA
# PRÁTICA (herda rigidamente a pose do pai, no Blender de verdade), mas
# nosso CÁLCULO de Pelvis_CTRL/L-Thigh_CTRL/R-Thigh_CTRL (filhos de
# root.pelvis_CTRL) continuava assumindo que ele ficava PARADO -- um
# descompasso entre "o que calculamos" e "o que vai acontecer de verdade
# na hora de tocar a Action" que fazia esses bones saírem
# deslocados/amplificados (a base se moveu, mas a conta achou que não).
#
# A correção: SEMPRE que root.master_CTRL efetivamente muda de pose
# (por qualquer um dos dois toggles), propagamos esse efeito pra
# root.pelvis_CTRL TAMBÉM (mesmo que ele não receba keyframe próprio --
# ver _propagate_root_pelvis abaixo), computando a pose EFETIVA que ele
# vai ter na prática (herdada rigidamente do master) e injetando ELA em
# world_target. Isso garante que QUALQUER bone que reprojete contra
# root.pelvis_CTRL (via _resolve_parent_world, que só olha o NOME/chave
# em world_target, sem saber se veio de keyframe próprio ou de herança)
# sempre bata com o que vai acontecer de verdade no Blender -- e por uma
# identidade básica de álgebra linear (A @ (A⁻¹ @ B) = B, pra QUALQUER A
# invertível), isso garante matematicamente que Pelvis_CTRL sempre acabe
# ocupando world_target["Pelvis"] EXATAMENTE, sem duplicar/amplificar
# nada -- não precisa (e não deve) zerar location manualmente em nenhum
# desses bones, o valor correto já sai certo da conta.
#
# Pra qualquer outra função do arquivo, root.master_CTRL/root.pelvis_CTRL
# passam a se comportar EXATAMENTE como se fossem o "_CTRL" de um bone ORG
# animado -- nenhuma outra função (_resolve_parent_world,
# _resolve_matrix_basis, _resolve_ctrl_matrix_basis) precisa saber disso;
# elas continuam olhando só pro nome do parent real no Blender.
# ---------------------------------------------------------------------------


def _pelvis_delta(pelvis_world, pelvis_rest_world):
    """Delta (translação + rotação) que o Pelvis sofreu desde a PRÓPRIA
    rest dele neste frame -- decompõe world_target["Pelvis"] de volta pra
    'o quanto ele se moveu', descartando a posição ABSOLUTA da rest do
    Pelvis (que é bem mais baixa que a de root.master_CTRL -- ele nasce
    na altura do "Belly", ver ROOT_MASTER_SOURCE em rigger.py). Aplicar
    esse delta em cima da rest de QUALQUER outro bone preserva o offset
    original entre os dois -- é isso que faz o "T-Pose" (delta zero,
    "nodeAnimations" vazio) resultar em NENHUMA mudança pros bones raiz.

    v0.7 (revisão -- fix da altura): a versão anterior usava a pose de
    mundo ABSOLUTA do Pelvis como alvo direto de root.master_CTRL --
    matematicamente isso ainda deixava Pelvis_CTRL/Belly_CTRL/etc.
    corretos (ver nota grande acima de _apply_root_follow: qualquer bone
    que reprojeta contra outro sempre bate no próprio alvo, não importa
    que valor a gente escolha pro parent, DESDE QUE seja o MESMO usado
    pra keyframar o parent) -- só que o PRÓPRIO root.master_CTRL acabava
    visualmente errado (a rest dele fica na altura do Belly, bem acima
    da rest do Pelvis -- usar a pose ABSOLUTA do Pelvis como alvo fazia
    ele 'cair' pra altura do Pelvis mesmo numa animação com Y=0, isto é,
    mesmo sem NENHUM movimento, ver T-Pose.blockyanim, que tem
    "nodeAnimations" vazio). Usar o DELTA em vez da pose absoluta resolve
    isso: T-Pose (delta identidade) não move nenhum bone raiz."""
    return pelvis_rest_world.inverted() @ pelvis_world


def _compose_delta_world(rest_world, delta, use_loc, use_rot):
    """rest_world @ delta, com a TRANSLAÇÃO e/ou ROTAÇÃO do delta
    zeradas conforme os toggles -- pra dar pra escolher independentemente
    se cada componente do movimento (do Pelvis, ou já herdado de outro
    bone raiz) é de fato aplicado."""
    d_loc, d_quat, _d_scale = delta.decompose()
    loc = d_loc if use_loc else Vector((0.0, 0.0, 0.0))
    quat = d_quat if use_rot else Quaternion()
    return rest_world @ (Matrix.Translation(loc) @ quat.to_matrix().to_4x4())


def _apply_root_follow(
    operator, frame, pose_bones, world_target, rest_cache, target_values, warned_rotation_mode,
    root_master_follow_loc, root_master_follow_rot, root_pelvis_follow_rot,
):
    """Chamada UMA VEZ por frame, logo depois de `world_target` ser
    calculado e ANTES do loop principal que escreve os `_CTRL` -- pra
    quando esse loop chegar em Pelvis_CTRL/Belly_CTRL/L-Thigh_CTRL/
    R-Thigh_CTRL (cujo parent REAL no Blender é root.pelvis_CTRL ou
    root.master_CTRL -- ver CTRL_PARENT_OVERRIDES em rigger.py), a
    injeção já esteja em `world_target` e a reprojeção genérica saia
    certa sozinha. Ver a nota grande acima pra explicação completa.

      root_master_follow_loc/root_master_follow_rot -- independentes:
          root.master_CTRL passa a somar o DELTA de translação/rotação
          do Pelvis (ver _pelvis_delta) em cima da PRÓPRIA rest dele
          (o componente desligado fica parado na própria rest -- nunca
          na do Pelvis). Escreve keyframe em root.master_CTRL só se PELO
          MENOS UM dos dois estiver ligado.
      root_pelvis_follow_rot -- root.pelvis_CTRL soma a ROTAÇÃO (delta)
          do Pelvis em cima de onde quer que já tenha herdado do master
          (rigidamente, via _compose_delta_world) -- NÃO existe opção de
          location pra este bone (o pedido original já era só de rotação
          aqui) -- se quiser posição do Pelvis nesta parte da cadeia, use
          os toggles de master acima.

    Devolve True se conseguiu injetar/escrever alguma coisa neste frame
    (bone raiz encontrado e "Pelvis" presente no world_target), False
    caso contrário -- usado pelo chamador pra decidir se vale reportar um
    aviso no final (bone raiz ausente no rig, ou arquivo sem "Pelvis")."""
    pelvis_world = world_target.get("Pelvis")
    pelvis_pbone = pose_bones.get("Pelvis")
    if pelvis_world is None or pelvis_pbone is None:
        return False  # rig/arquivo sem bone "Pelvis" -- nada a fazer
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
        # Pose EFETIVA que root.pelvis_CTRL vai ter na prática, herdando
        # rigidamente do parent real dele (que É root.master_CTRL neste
        # rig -- ver _build_root_controls, rigger.py -- mas resolve
        # genérico via _resolve_parent_world como salvaguarda, caso um
        # rig futuro mude isso) -- SEM nenhuma pose própria ainda.
        if master_target_world is not None and pelvis_ctrl_pbone.parent is master_pbone:
            parent_world_for_pelvis = master_target_world
        else:
            parent_world_for_pelvis = _resolve_parent_world(
                pelvis_ctrl_pbone.parent, world_target, rest_cache, pose_bones
            )
        pelvis_ctrl_rest_local = _get_rest_local(pelvis_ctrl_pbone, rest_cache)
        inherited_world = parent_world_for_pelvis @ pelvis_ctrl_rest_local

        if root_pelvis_follow_rot:
            # Soma só a ROTAÇÃO (delta) do Pelvis em cima do que já foi
            # herdado acima -- nunca a rotação ABSOLUTA dele, pelo mesmo
            # motivo de _pelvis_delta (preservar a orientação própria
            # que root.pelvis_CTRL já tinha herdado, em vez de saltar
            # pra a do Pelvis).
            pelvis_ctrl_target_world = _compose_delta_world(inherited_world, pelvis_delta, False, True)
        else:
            pelvis_ctrl_target_world = inherited_world

        world_target[BONE_ROOT_PELVIS[: -len(SUFFIX_CTRL)]] = pelvis_ctrl_target_world

        if root_pelvis_follow_rot:
            # Só precisa de keyframe PRÓPRIO se tem uma pose própria de
            # verdade (rotação extra) -- se for só herança rígida do
            # master (root_pelvis_follow_rot=False), matrix_basis fica
            # identidade e o Blender já resolve certo via parent real,
            # sem precisar escrever nada aqui.
            matrix_basis = _resolve_matrix_basis(
                pelvis_ctrl_pbone, pelvis_ctrl_target_world, world_target, rest_cache, pose_bones
            )
            quat = matrix_basis.decompose()[1]
            _ensure_quaternion_rotation(operator, pelvis_ctrl_pbone, warned_rotation_mode)
            target_values.setdefault(pelvis_ctrl_pbone.name, []).append((frame, None, quat))
        fired = True

    return fired


def _report_root_follow(operator, root_follow_enabled, root_follow_fired):
    """Aviso final se algum toggle de Root Follow estava ligado mas nunca
    chegou a injetar/escrever nada em NENHUM frame (bone raiz ausente no
    rig -- ex.: rig gerado com uma versão antiga do rigger.py -- ou
    arquivo sem bone "Pelvis")."""
    if not root_follow_enabled or root_follow_fired:
        return
    operator.report(
        {"WARNING"},
        f"Root Follow was enabled but '{BONE_ROOT_MASTER}'/'{BONE_ROOT_PELVIS}' and/or 'Pelvis' "
        f"weren't found -- skipped, no keyframes written for the root control bone(s). Was the "
        f"rig generated with a version of rigger.py that has root.master_CTRL/root.pelvis_CTRL?",
    )


# Spine "Default (Root CTRL)" vs "Spine CTRL" (UI, IMPORT_OT_hytale_blockyanim.spine_mode)
# traduz direto pros 3 toggles de _apply_root_follow -- (loc, rot, pelvis_rot).
# "DEFAULT" é a combinação validada como a melhor em testes reais no
# Blender (root.master_CTRL segue loc+rot do Pelvis; root.pelvis_CTRL sem
# rotação própria extra); "MANUAL" desliga tudo (root.master_CTRL/
# root.pelvis_CTRL ficam parados, root.spine_CTRL livre pra ajuste manual
# -- ver descrição da propriedade).
_SPINE_MODE_ROOT_FOLLOW = {
    "DEFAULT": (True, True, False),
    "MANUAL": (False, False, False),
}


def _org_path(hierarchy, root_name, tip_name):
    """Caminho (lista de NOMES, root->tip) andando a hierarquia ORG --
    mesma ideia de find_org_path() em rigger.py (usada lá pra gerar o
    rig, sobre edit bones), só que aqui sobre `hierarchy` (a mesma
    estrutura que _org_hierarchy() já devolve), pra não precisar de Edit
    Mode nenhum durante o import.

    NOTA: esta função tinha sido apagada por acidente numa edição em
    bloco anterior (mesmo acidente de _resolve_ik_chains, ver nota lá) --
    restaurada aqui."""
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
    precisamos de Edit Mode aqui, só ler o que já existe).

    Só entradas ARM/LEG (item.chain_type) -- cadeias TAIL não têm IK
    nenhum (não existe bone "_IK" nem "_Pole_CTRL" pra elas -- ver
    _build_tail_layer, rigger.py), então tratá-las aqui geraria nomes de
    bone que nunca existem. Cadeias TAIL sempre passam pelo caminho
    _CTRL normal (ver _resolve_ctrl_matrix_basis), em QUALQUER
    configuração de Arms/Legs -- essas opções só decidem isso pra bones
    que estão de fato numa cadeia de IK.

    `"group"` ("ARM"/"LEG", direto de item.chain_type) é o que permite a
    UI configurar Arms e Legs INDEPENDENTEMENTE (ver _apply_ctrl_mode) --
    cada cadeia usa o modo do PRÓPRIO grupo, não um modo global único
    pra tudo.

    NOTA: esta função tinha sido apagada por acidente numa edição em
    bloco anterior (estava fisicamente entre as antigas
    _apply_ctrl_fk_mode/_apply_ik_mode, faixa de linhas substituída de
    uma vez só por _apply_ctrl_mode) -- restaurada aqui."""
    chains = []
    for item in armature_obj.data.hytale_ik_chains:
        if item.chain_type == "TAIL":
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
                "ik_tip": path[-1] + SUFFIX_IK,
                "pole": path[0] + SUFFIX_POLE,
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
    """Target = Controllers -- unifica o que antes eram três modos
    globais separados (CTRL_FK/IK/BOTH) numa função só, porque agora
    Arms e Legs podem estar em modos DIFERENTES ao mesmo tempo (ex.:
    braço em Control IK, perna em Default FK+IK) -- não faz mais sentido
    ter uma cadeia "de modo global" quando cada GRUPO de cadeia decide o
    próprio comportamento (ver `chain["group"]`, _resolve_ik_chains).

    spine_mode -- "DEFAULT" ou "MANUAL" (ver _SPINE_MODE_ROOT_FOLLOW
        logo abaixo) -- controla só como root.master_CTRL/
        root.pelvis_CTRL se comportam (ver _apply_root_follow). Pelvis/
        Belly/Chest são sempre keyframados normalmente, nos dois casos.
    arms_mode/legs_mode -- "BOTH" (Default FK+IK), "CTRL_FK" (Control
        FK) ou "IK" (Control IK) -- aplicado independentemente às
        cadeias de cada grupo (chain["group"] == "ARM"/"LEG"):
          "BOTH"    -- cadeia recebe FK (_CTRL por segmento, INCLUSIVE
                       os da cadeia) E IK (ponta + pole) ao mesmo tempo;
                       fk_ik_switch fica fixo em FK (0), trocável depois.
          "CTRL_FK" -- só FK (_CTRL por segmento) -- fk_ik_switch não é
                       tocado (a cadeia nem recebe bone "_IK" nenhum).
          "IK"      -- só IK (ponta + pole) -- os _CTRL dos segmentos
                       da cadeia são PULADOS (não recebem keyframe);
                       fk_ik_switch fica fixo em IK (1).
    Bones fora de qualquer cadeia (torso, cabeça, dedos, cauda etc.)
    sempre recebem FK via _CTRL, independente de qualquer uma dessas
    3 opções -- elas só afetam braços/pernas/raiz."""
    setup = _prepare_reprojection_setup(operator, context, armature_obj, data, start_frame, action_name, loop_mode)
    if setup is None:
        return {"CANCELLED"}
    scene, fps, hierarchy, delta_lookup, end_frame, action, pose_bones = setup
    _stamp_action_source_metadata(action, data)

    chains = _resolve_ik_chains(armature_obj, hierarchy)
    group_mode = {"ARM": arms_mode, "LEG": legs_mode}
    for chain in chains:
        chain["mode"] = group_mode.get(chain["group"], "BOTH")

    # Cadeias 100% IK pulam o loop de FK (_CTRL por segmento); as outras
    # (BOTH/CTRL_FK) passam por ele normalmente, igual bone fora de
    # cadeia nenhuma.
    chain_bone_names_skip_fk = {
        name for chain in chains if chain["mode"] == "IK" for name in chain["org_names"]
    }
    # Só cadeias BOTH/IK recebem ponta (_IK) + pole.
    ik_chains = [chain for chain in chains if chain["mode"] in ("BOTH", "IK")]

    target_values = {}  # {bone_name: [(frame, loc_or_None, quat_or_None), ...]}
    rest_cache = {}
    warned_rotation_mode = set()

    # Muta constraints extras nos bones que vamos escrever via FK (mesma
    # lógica de sempre -- ver nota grande acima de _apply_root_follow):
    # bones fora das cadeias 100% IK (ex: Belly/Chest + SpineFollow), e
    # os poles de toda cadeia que vai receber IK (Child Of local/global).
    muted_constraints = []
    if not keep_spine_follow:
        _mute_constraints_on(
            (
                pose_bones.get(name + SUFFIX_CTRL)
                for name, _parent_name, _rest_local in hierarchy
                if name not in chain_bone_names_skip_fk
            ),
            muted_constraints,
        )
    _mute_constraints_on((pose_bones.get(chain["pole"]) for chain in ik_chains), muted_constraints)

    # fk_ik_switch: IK-only -> fixo em 1; BOTH -> fixo em 0 (default FK,
    # trocável depois); CTRL_FK-only nem entra em `ik_chains`, então nem
    # recebe bone "_IK" nenhum -- não há switch pra tocar.
    tip_org_rest_world = {}
    for chain in ik_chains:
        ik_pbone = pose_bones.get(chain["ik_tip"])
        if ik_pbone is not None:
            ik_pbone[PROP_FK_IK_SWITCH] = 1 if chain["mode"] == "IK" else 0
            tip_org_rest_world[chain["ik_tip"]] = pose_bones[chain["org_names"][-1]].bone.matrix_local.copy()

    root_master_follow_loc, root_master_follow_rot, root_pelvis_follow_rot = _SPINE_MODE_ROOT_FOLLOW[spine_mode]

    root_follow_fired = False
    for frame in range(start_frame, end_frame + 1):
        world_target = _compute_world_targets(hierarchy, delta_lookup, frame)

        if _apply_root_follow(
            operator, frame, pose_bones, world_target, rest_cache, target_values, warned_rotation_mode,
            root_master_follow_loc, root_master_follow_rot, root_pelvis_follow_rot,
        ):
            root_follow_fired = True

        # FK: todo bone FORA das cadeias 100% IK (torso/cabeça/dedos/
        # cauda sempre passam por aqui, e também os segmentos de
        # cadeias BOTH/CTRL_FK).
        for name, _parent_name, _rest_local in hierarchy:
            if name in chain_bone_names_skip_fk:
                continue
            ctrl_pbone = pose_bones.get(name + SUFFIX_CTRL)
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

    _write_pose_samples(action, target_values)

    # shapeStretch não faz parte da reprojeção FK/IK acima (ver docstring
    # de _apply_stretch_channels) -- precisa só de hold_last/duration, que
    # _prepare_reprojection_setup já calculou mas não devolveu no
    # namedtuple; recalcular aqui é uma chamada pura e barata (mesmos
    # argumentos), não vale mudar o contrato do namedtuple só por isso.
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




# ---------------------------------------------------------------------------
# Dispatch de modo -- os dois modos (ORG/CTRL) já implementados.
# ---------------------------------------------------------------------------

_MODE_HANDLERS = {
    "ORG": _apply_org_mode,
    "CTRL": _apply_ctrl_mode,
}

# Presets de "Frame Rate" (import_fps_preset) -> (fps, fps_base), MESMOS
# valores que Blender usa nos próprios presets de Output Properties >
# Frame Rate -- os "quebrados" (23.98/29.97/59.94, convenção NTSC) não são
# o número redondo em si, e sim fps/fps_base -- ex.: 23.98 é na verdade
# 24000/1001 = 23.976023...
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
                "CTRL",
                "Controllers",
                "Writes onto the '_CTRL'/'_IK'/pole bones generated by the auto-rig tool "
                "(rigger.py), so the imported animation stays editable through the control rig -- "
                "configure Spine/Arms/Legs below",
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
    import_fps_preset: EnumProperty(
        name="Frame Rate",
        description="Target scene FPS for this import. If the scene isn't already at this FPS, "
        "it gets changed automatically before importing -- .blockyanim files are authored at "
        "60 FPS (FPS_HYTALE), so keeping this at 60 avoids the 'timing looks compressed' issue "
        "from importing into a lower-FPS scene. Same list as Blender's own Output Properties > "
        "Frame Rate -- pick 'Custom' to set FPS/Base separately, same as there",
        items=[
            ("6", "6", "6 fps"),
            ("8", "8", "8 fps"),
            ("12", "12", "12 fps"),
            ("23.98", "23.98", "23.976 fps (24000 / 1001, NTSC film)"),
            ("24", "24", "24 fps"),
            ("25", "25", "25 fps"),
            ("29.97", "29.97", "29.97 fps (30000 / 1001, NTSC)"),
            ("30", "30", "30 fps"),
            ("50", "50", "50 fps"),
            ("59.94", "59.94", "59.94 fps (60000 / 1001, NTSC)"),
            ("60", "60", "60 fps"),
            ("120", "120", "120 fps"),
            ("240", "240", "240 fps"),
            ("CUSTOM", "Custom", "Set FPS and Base separately below"),
        ],
        default="60",
    )
    import_fps_custom_fps: IntProperty(
        name="FPS",
        description="Custom Frame Rate 'Frame Rate' is set to 'Custom' -- same field as Output "
        "Properties > Frame Rate > FPS in Blender's own UI. Effective rate is FPS / Base",
        default=FPS_HYTALE,  # já importado no topo do arquivo, de common.py
        min=1,
        soft_max=240,
    )
    import_fps_custom_base: FloatProperty(
        name="Base",
        description="Custom Frame Rate 'Frame Rate' is set to 'Custom' -- same field as Output "
        "Properties > Frame Rate > Base in Blender's own UI. Effective rate is FPS / Base",
        default=1.0,
        min=0.001,
        soft_max=120.0,
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
            "keyframes (common in this format). Recommended for Cycle imports. Affects "
            "position/rotation on 'Original Bones' and shape stretch on both targets -- "
            "'Control Bones (FK)' position/rotation always bakes every frame regardless"
        ),
        default=False,
    )
    keep_spine_follow: BoolProperty(
        name="Keep Spine-Follow Active",
        description=(
            "Control FK, Control IK and Default (FK + IK) only: by default, this stays ACTIVE -- "
            "any extra constraint on a control bone (ex: Belly_CTRL/Chest_CTRL partially following "
            "root.spine_CTRL) keeps blending in during import, and in modes that write IK, each "
            "pole target's Child Of constraints also stay active. Disable this to mute those "
            "constraints instead, making the imported pose match the source file exactly on the "
            "affected bones -- at the cost of root.spine_CTRL (and the poles' Child Of) no longer "
            "being usable as fine-tuning tools on top of the imported animation"
        ),
        default=True,
    )
    spine_mode: EnumProperty(
        name="Spine",
        description="Controllers only: how the rig's utility root bones (root.master_CTRL/"
        "root.pelvis_CTRL, rigger.py) behave. The source animation only ever moves Pelvis/Belly/"
        "Chest -- these root bones never move on their own, so they need this to travel with the "
        "animation (ex: walk/run cycles) instead of staying frozen near the origin",
        items=[
            (
                "DEFAULT",
                "Default (Root CTRL)",
                "root.master_CTRL follows the Pelvis's animated position and rotation every frame "
                "-- root.pelvis_CTRL and Belly_CTRL (real children of root.master_CTRL) travel "
                "along automatically. Recommended -- matches the source animation's root motion",
            ),
            (
                "MANUAL",
                "Spine CTRL",
                "root.master_CTRL/root.pelvis_CTRL stay frozen at rest -- Pelvis/Belly/Chest are "
                "still keyframed normally, but the character won't travel with root motion (ex: "
                "walking will look like walking in place). Leaves root.spine_CTRL free as a manual "
                "fine-tuning handle on top of the imported animation instead",
            ),
        ],
        default="DEFAULT",
    )
    arms_mode: EnumProperty(
        name="Arms",
        description="Controllers only: how 'Arm'-type chains (armature.hytale_ik_chains, "
        "rigger.py) are keyframed",
        items=[
            (
                "BOTH",
                "Default (FK + IK)",
                "Writes both at once -- every arm segment gets its FK '_CTRL' AND the chain's IK "
                "tip (hand) + pole also get keyframed. fk_ik_switch defaults to FK (0); toggle it "
                "any time afterward, per chain, to preview or use the IK version instead -- no "
                "need to reimport",
            ),
            (
                "CTRL_FK",
                "Control FK",
                "Only the per-segment '_CTRL' bones -- fk_ik_switch is left untouched (the chain "
                "doesn't receive any '_IK'/pole keyframes at all)",
            ),
            (
                "IK",
                "Control IK",
                "Only the '_IK' tip (hand) + pole target -- per-segment '_CTRL' bones are skipped, "
                "and fk_ik_switch is set to IK (1)",
            ),
        ],
        default="BOTH",
    )
    legs_mode: EnumProperty(
        name="Legs",
        description="Controllers only: how 'Leg'-type chains (armature.hytale_ik_chains, "
        "rigger.py) are keyframed -- same 3 options as Arms, applied independently",
        items=[
            (
                "BOTH",
                "Default (FK + IK)",
                "Writes both at once -- every leg segment gets its FK '_CTRL' AND the chain's IK "
                "tip (foot) + pole also get keyframed. fk_ik_switch defaults to FK (0); toggle it "
                "any time afterward, per chain, to preview or use the IK version instead -- no "
                "need to reimport",
            ),
            (
                "CTRL_FK",
                "Control FK",
                "Only the per-segment '_CTRL' bones -- fk_ik_switch is left untouched (the chain "
                "doesn't receive any '_IK'/pole keyframes at all)",
            ),
            (
                "IK",
                "Control IK",
                "Only the '_IK' tip (foot) + pole target -- per-segment '_CTRL' bones are skipped, "
                "and fk_ik_switch is set to IK (1)",
            ),
        ],
        default="BOTH",
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
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
