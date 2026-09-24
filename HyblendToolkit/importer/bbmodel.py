"""importer/bbmodel.py -- import de .bbmodel (projeto do Blockbench). Também
expõe import_bbmodel_data(), o núcleo reaproveitado por quem monta um dict
no formato .bbmodel em memória (importer/bedrock.py)."""

import base64
import json
import math
import os
import tempfile

import bmesh
import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler, Matrix, Vector

from ..common import (
    ARMATURE_MODEL_FORMAT_PROP,
    BONE_ORIGINAL_NAME_PROP,
    BONE_SHAPE_JSON_PROP,
    BONE_SHAPE_OFFSET_PROP,
    MODEL_FORMAT_CHARACTER,
    MODEL_FORMAT_PROP,
    effective_unit_scale,
    normalize_model_format,
)
from ..translations import (
    get_language,
    localized_props,
    tooltip,
    tr,
)
from .common_mesh import (
    BONE_DISPLAY_LENGTH_GAME_UNITS,
    BOX_FACES_LOOP_ORDER,
    BOX_FACE_BASE_SIGN,
    BOX_FACE_FIXED_AXIS,
    FACE_AXES_BY_FIXED_AXIS,
    build_character_collections,
    resolve_mesh_bone_collection,
    unique_bone_name,
)
from .common_options import (
    draw_mesh_section,
    draw_rig_section,
    import_option_props,
    model_format_enum,
)
from .textures import (
    stack_extra_texture_nodes,
    build_flat_material_from_image,
)


# ---------------------------------------------------------------------------
# Suporte a .bbmodel (projeto salvo do Blockbench)
# ---------------------------------------------------------------------------
#
# Diferente do .blockymodel (um "node" por peça, position RELATIVA ao pai +
# shape.offset, orientation em quaternion), o .bbmodel guarda a árvore em
# TRÊS listas separadas que precisam ser religadas por uuid:
#   - "elements": lista PLANA de cubos (from/to/origin, todos em coordenadas
#     ABSOLUTAS/"de repouso" -- mesmo espaço pra raiz e pra folha).
#   - "groups": lista PLANA de bones/pivôs (origin absoluto, rotation em
#     Euler XYZ em GRAUS -- não quaternion).
#   - "outliner": a árvore de verdade, um nó por group, cujos filhos podem
#     ser outro nó de group (dict) OU o uuid de um element (string) direto.
#
# MATEMÁTICA DA POSIÇÃO/ROTAÇÃO -- CONFIRMADA NUMERICAMENTE (não é chute):
# comparando a posição mundial de R-Forearm/R-Hand calculada a partir de um
# .blockymodel do MESMO personagem (via node_local_matrix, já validado)
# contra a calculada a partir do .bbmodel equivalente, erro < 4e-4 (a
# diferença esperada só do arredondamento de 3 casas decimais que o
# Blockbench grava no "rotation"). Isso confirma duas coisas que NÃO dá
# pra advinhar só olhando o formato (chegaram a existir fontes não-oficiais
# divergentes sobre a ordem dos eixos):
#
# 1) Cada group representa uma transformação "rotacionar ao redor do
#    próprio origin": M(group) = Translate(origin) @ Euler(rotation, 'XYZ')
#    @ Translate(-origin). A ordem 'XYZ' aqui é a ordem nativa do
#    mathutils.Euler do Blender (aplica X primeiro, Y depois, Z por último
#    -- equivale a multiplicar as matrizes Rz @ Ry @ Rx). O quaternion do
#    R-Arm no .blockymodel ({0.00266,-0.06099,-0.04354,w=0.99719})
#    convertido pra Euler nessa MESMA ordem bate com o rotation gravado no
#    .bbmodel ([0.613,-6.973,-5.037]).
#
# 2) A POSIÇÃO de um group/element é o `origin` do próprio arquivo
#    transformado pela cadeia de M(ancestral) de TODOS os ancestrais, SEM
#    incluir a própria rotação do nó (rotacionar um pivô ao redor dele
#    mesmo não move o pivô, só afeta os FILHOS). Por isso mantemos DOIS
#    acumuladores separados ao percorrer a árvore -- ver
#    build_bbmodel_recursive:
#      - `ancestor_pivot_matrix`: a cadeia completa
#        Translate(origin)@Rotate@Translate(-origin) de cada ancestral,
#        multiplicada em sequência -- usada só pra achar a POSIÇÃO de um
#        filho a partir do origin bruto dele (a translação resultante NÃO
#        é uma soma simples por causa do Translate(-origin) no meio).
#      - `ancestor_rotation_matrix`: só a composição das ROTAÇÕES em si
#        (sem a parte de pivô/translação) -- é o equivalente direto da
#        variável "world" (rotação acumulada) em build_bones_recursive, e
#        é o que vira a orientação de verdade do bone (importa pra
#        IK/torção na hora de animar).
#
# 3) is_piece (equivalente ao isPiece do .blockymodel) já vem, no .bbmodel,
#    como um GROUP NORMAL dentro da árvore -- o Blockbench já materializa
#    o bone "wrapper" (ex: "Eyes:R-Eye-Attachment") como um nó de verdade
#    no outliner na hora de salvar o projeto. Ou seja: um .bbmodel salvo já
#    É o personagem com os attachments FUNDIDOS -- diferente do fluxo de
#    vários .blockymodel separados (corpo + Eyes.blockymodel + ...) que o
#    modo "Attach to Existing" existe pra reconstruir. Por isso o import de
#    .bbmodel abaixo só tem um modo (sempre cria um Armature novo do
#    zero) -- não reaproveita bones de um Armature já existente. Se algum
#    dia isso for necessário (ex: anexar um .bbmodel de attachment feito à
#    parte num personagem já importado), é uma extensão futura -- avise se
#    precisar.
#
# 4) Cada element (cubo) também carrega um "stretch" [sx,sy,sz] -- fator de
#    escala ao redor do próprio origin, igual ao shape.stretch do
#    .blockymodel (comparar: R-Arm stretch.x=0.98 / L-Arm stretch.x=-0.98
#    em AMBOS os formatos -- literalmente os mesmos valores). É onde vive
#    o mecanismo de espelhamento de verdade: um stretch negativo produz
#    uma reflexão, não só uma translação -- SEM isso, uma peça do lado L
#    (mesmo com from/to já espelhados no arquivo) ainda fica com a
#    "lateralidade" da UV errada, porque só a posição espelha, a
#    geometria/UV local não. Ver make_bbmodel_cube_mesh pra os detalhes.
#
# MATEMÁTICA DO UV: reaproveita a MESMA lógica de BOX_FACE_BASE_SIGN
# (ancoragem de canto) e a MESMA permutação de rotação já usada em
# compute_face_uv (ver a nota grande lá, citando
# Preview_controller.updateUV do Blockbench -- é código genérico do app
# principal, não específico do .blockymodel, então vale igual aqui). A
# diferença é que o .bbmodel já grava o retângulo final em PIXELS direto
# em cada face ("uv": [x1,y1,x2,y2]), sem precisar derivar de
# offset/mirror/angle como o _blockbench_uv_rect faz pro .blockymodel --
# só falta plugar esse retângulo já pronto no lugar certo.
#
# AVISO: a parte de POSIÇÃO/ROTAÇÃO dos bones foi validada numericamente
# (ver acima). A parte de UV reaproveita lógica já validada (mesmo
# BOX_FACE_BASE_SIGN e mesma permutação de rotation), mas o CAMINHO
# específico "pegar o retângulo pixel do .bbmodel e jogar direto nesses
# mesmos cantos" não tem uma segunda fonte pra cross-check (o .blockymodel
# de comparação não tem textureLayout pra comparar 1:1). Se alguma face
# aparecer espelhada/rotacionada errado depois de importar, é aqui
# (bbmodel_compute_face_uv, logo abaixo) que precisa ajustar.
#
# HISTÓRICO: já apareceu um bug real disso -- não na fórmula de UV em si,
# mas no fato de eu ter esquecido de ler o campo "stretch" de cada element
# (ver nota 4, acima). Sem aplicar o stretch, peças do lado L apareciam com
# a UV "invertida" (confirmado visualmente comparando o mesmo .bbmodel
# aberto no Blockbench vs importado no Blender) porque a reflexão de
# verdade só acontece via o stretch negativo, não só pela posição já vir
# espelhada no from/to. Corrigido em make_bbmodel_cube_mesh.

BB_FACE_TO_HYTALE_FACE_KEY = {
    # Convenção de bússola do Minecraft/Blockbench (norte = -Z, sul = +Z,
    # leste = +X, oeste = -X, cima = +Y, baixo = -Y) mapeada pras mesmas
    # chaves de face que o resto do módulo já usa (BOX_FACES_LOOP_ORDER,
    # BOX_FACE_BASE_SIGN etc, vindas do .blockymodel) -- ver
    # NORMAL_TO_HYTALE_FACE_KEY, acima, pra a mesma correspondência de eixo.
    "north": "back",
    "south": "front",
    "west": "left",
    "east": "right",
    "up": "top",
    "down": "bottom",
}


def bb_euler_matrix(rotation_deg):
    """Matriz de rotação 4x4 a partir de [rx,ry,rz] em GRAUS, na mesma
    ordem 'XYZ' do mathutils.Euler (aplica X, depois Y, depois Z -- ver
    nota grande no topo desta seção pra a validação numérica dessa
    ordem)."""
    rx, ry, rz = rotation_deg
    return Euler((math.radians(rx), math.radians(ry), math.radians(rz)), "XYZ").to_matrix().to_4x4()


def bb_rotate_around_pivot(origin, rotation_deg):
    """Translate(origin) @ Rotate(rotation_deg) @ Translate(-origin) --
    a transformação que UM group/element do .bbmodel representa (ver nota
    grande acima). `origin` já deve vir escalado (unit_scale aplicado)."""
    R = bb_euler_matrix(rotation_deg)
    return Matrix.Translation(origin) @ R @ Matrix.Translation(-origin)


def bbmodel_compute_face_uv(local_co, neg_extent, pos_extent, axis_u, axis_v, hytale_face_key, rect, rotation_deg, atlas_w, atlas_h):
    """Equivalente a compute_face_uv, mas pro .bbmodel: `rect` já é o
    retângulo final em pixels (x1,y1,x2,y2) direto do arquivo (sem
    precisar de _blockbench_uv_rect), e a caixa pode ser ASSIMÉTRICA em
    relação à origem (neg_extent/pos_extent por eixo, em vez de um único
    half_extents -- ver make_bbmodel_cube_mesh)."""
    nu, pu = neg_extent[axis_u], pos_extent[axis_u]
    nv, pv = neg_extent[axis_v], pos_extent[axis_v]
    span_u = (pu - nu) or 1.0
    span_v = (pv - nv) or 1.0
    s = (local_co[axis_u] - nu) / span_u
    t = (local_co[axis_v] - nv) / span_v

    bs, bt = BOX_FACE_BASE_SIGN.get(hytale_face_key, (1, -1))
    s_bb = s if bs > 0 else 1.0 - s
    t_bb = t if bt > 0 else 1.0 - t

    # Mesma permutação de compute_face_uv, ver a nota grande lá.
    k = int(round((rotation_deg or 0) / 90.0)) % 4
    for _ in range(k):
        s_bb, t_bb = t_bb, 1.0 - s_bb

    x1, y1, x2, y2 = rect
    px = x1 + (x2 - x1) * s_bb
    py = y1 + (y2 - y1) * t_bb

    u = px / atlas_w
    v = 1.0 - (py / atlas_h)
    return u, v


_QUAD_AXIS_INFO = {
    # eixo ACHATADO ('from'==='to' nesse eixo) -> face bbmodel do lado
    # negativo/positivo desse eixo. Os 2 eixos que sobram (que viram
    # settings.size.x/settings.size.y do quad) NÃO são reinventados aqui
    # -- reaproveita FACE_AXES_BY_FIXED_AXIS (já definida acima, validada
    # por engenharia reversa numérica contra um .gltf real -- ver a nota
    # grande logo antes dela) pra pegar a MESMA ordem de eixos que o
    # resto do módulo já usa pra 'box'. Tentei uma ordem "por simetria"
    # nesta função antes de existir esta reutilização, e ela saiu ERRADA
    # pro eixo X (confirmado contra um arquivo oficial: 'HairTop' saiu
    # com size.x/size.y trocados) -- por isso agora usa a tabela já
    # validada em vez de adivinhar de novo.
    "x": ("west", "east"),
    "y": ("down", "up"),
    "z": ("north", "south"),
}


def _bbmodel_quad_shape(flat_axis, size_raw_3, offset_raw, stretch, faces):
    """Monta um shape 'quad' (plano achatado -- olho, pálpebra, sobrancelha,
    pelo facial, etc, qualquer element cujo from/to seja igual num eixo)
    -- ver bbmodel_element_to_shape, que chama isso quando detecta
    achatamento. settings.size só tem 2 eixos (a largura/altura do plano,
    NÃO o tamanho 3D todo, na MESMA ordem que FACE_AXES_BY_FIXED_AXIS já
    usa pro resto do módulo -- confirmado contra um arquivo oficial pros
    3 eixos: Z direto, X reaproveitando a tabela corrigiu um bug real) +
    'normal' (qual direção o plano encara, escolhida pela face bbmodel
    que TEM textura de verdade dos dois lados possíveis desse eixo)."""
    neg_face, pos_face = _QUAD_AXIS_INFO[flat_axis]
    i1, i2 = FACE_AXES_BY_FIXED_AXIS[flat_axis]
    size = {"x": size_raw_3[i1], "y": size_raw_3[i2]}
    axis_upper = flat_axis.upper()

    pos_info = faces.get(pos_face)
    neg_info = faces.get(neg_face)
    if pos_info is not None and pos_info.get("texture") is not None:
        normal, chosen = f"+{axis_upper}", pos_info
    elif neg_info is not None and neg_info.get("texture") is not None:
        normal, chosen = f"-{axis_upper}", neg_info
    else:
        normal, chosen = f"+{axis_upper}", None

    texture_layout = {}
    n_skipped = 0
    if chosen is not None:
        rotation_deg = chosen.get("rotation", 0)
        rect = chosen.get("uv")
        if rotation_deg:
            n_skipped = 1
        elif rect and len(rect) == 4:
            x1, y1, x2, y2 = rect
            texture_layout["front"] = {
                "offset": {"x": x1, "y": y1},
                "mirror": {"x": x2 < x1, "y": y2 < y1},
                "angle": 0,
            }

    shape = {
        "type": "quad",
        "offset": offset_raw,
        "stretch": {"x": stretch[0], "y": stretch[1], "z": stretch[2]},
        "settings": {"size": size, "normal": normal},
    }
    if texture_layout:
        shape["textureLayout"] = texture_layout
    return shape, n_skipped


def bbmodel_element_to_shape(elem):
    """Converte um "element" (cubo) do .bbmodel pro dict "shape" do
    .blockymodel (mesmo formato que build_bones_recursive grava em
    BONE_SHAPE_JSON_PROP pro caminho .blockymodel). Existe pra dar
    suporte a exportar .blockymodel a partir de um personagem importado
    via .bbmodel, que não tinha esse dado salvo (o .bbmodel usa um
    formato de árvore bem diferente, sem "shape" por nó).

    Geometria (type/offset/settings.size) -- confiança alta: usa a
    mesma lógica de neg/pos que make_bbmodel_cube_mesh já usa pra
    construir a malha de referência (mesmo raciocínio, invertido pra
    achar offset=centro/size=extensão em vez de vértices).

    Duas correções confirmadas contra um arquivo real exportado pelo
    Blockbench oficial pro mesmo personagem (comparação node a node):

    1) "stretch" não é assado na geometria (offset/size vêm só de
       from/to/origin crus, sem multiplicar por stretch) -- é gravado
       como campo literal no shape, igual o .blockymodel nativo faz
       (confirmado: um elemento de pálpebra no arquivo de referência
       tem "stretch":{"y":0.1} preservado à parte, não embutido no
       tamanho -- esse tipo de valor normalmente é um canal animável
       depois, tipo abrir/fechar o olho). Também mais correto
       geometricamente pra espelhamento via stretch negativo, já que
       replica a mesma relação size×stretch que make_bbmodel_cube_mesh
       usa pra desenhar a malha de referência.

    2) type="quad" é detectado (from==to em algum eixo -> plano
       achatado) em vez de sempre sair "box" -- confirmado contra 2
       exemplos reais (olho, pálpebra). Ver _bbmodel_quad_shape(),
       acima, pro resto da conversão.

    TextureLayout (caso "box", sem achatamento) -- best effort, só pra
    faces com rotation==0 (a grande maioria na prática): o retângulo
    "uv" do .bbmodel já vem em pixels crus, então offset = primeiro
    canto do retângulo, mirror = sinal de (x2-x1)/(y2-y1). Faces com
    rotation!=0 são deliberadamente puladas (viram "sem textura" nessa
    face no .blockymodel exportado) -- inverter _blockbench_uv_rect
    direito pra angle=90/180/270 exigiria um .blockymodel de referência
    com faces rotacionadas pra cross-check numérico, que não tínhamos.

    Devolve (shape_dict, n_faces_skipped)."""
    from_v = elem.get("from", [0.0, 0.0, 0.0])
    to_v = elem.get("to", [0.0, 0.0, 0.0])
    origin_v = elem.get("origin", [0.0, 0.0, 0.0])
    stretch = elem.get("stretch", [1.0, 1.0, 1.0])
    faces = elem.get("faces", {}) or {}

    # Sem multiplicar por stretch aqui (ver docstring acima).
    neg = [min(from_v[i], to_v[i]) - origin_v[i] for i in range(3)]
    pos = [max(from_v[i], to_v[i]) - origin_v[i] for i in range(3)]
    size_raw_3 = [abs(pos[i] - neg[i]) for i in range(3)]
    offset_raw = {"x": (pos[0] + neg[0]) / 2.0, "y": (pos[1] + neg[1]) / 2.0, "z": (pos[2] + neg[2]) / 2.0}

    flat_axis = None
    for i, axis_name in enumerate(("x", "y", "z")):
        if abs(from_v[i] - to_v[i]) < 1e-6:
            flat_axis = axis_name
            break

    if flat_axis is not None:
        return _bbmodel_quad_shape(flat_axis, size_raw_3, offset_raw, stretch, faces)

    size_raw = {"x": size_raw_3[0], "y": size_raw_3[1], "z": size_raw_3[2]}

    texture_layout = {}
    n_skipped = 0
    for bb_key, hytale_key in BB_FACE_TO_HYTALE_FACE_KEY.items():
        info = faces.get(bb_key)
        if info is None or info.get("texture") is None:
            continue
        rotation_deg = info.get("rotation", 0)
        rect = info.get("uv")
        if rotation_deg or not rect or len(rect) != 4:
            if rotation_deg:
                n_skipped += 1
            continue
        x1, y1, x2, y2 = rect
        texture_layout[hytale_key] = {
            "offset": {"x": x1, "y": y1},
            "mirror": {"x": x2 < x1, "y": y2 < y1},
            "angle": 0,
        }

    shape = {
        "type": "box",
        "offset": offset_raw,
        "stretch": {"x": stretch[0], "y": stretch[1], "z": stretch[2]},
        "settings": {"size": size_raw},
    }
    if texture_layout:
        shape["textureLayout"] = texture_layout
    return shape, n_skipped


def bbmodel_element_local_transform(group_world_matrix, children_pivot_matrix, children_rotation_matrix, elem, unit_scale):
    """Devolve (position_raw, orientation_dict, is_identity) -- a
    transform local de um element (cubo) relativa ao bone (group) dono,
    calculada numericamente (matrizes de verdade, não fórmula na mão)
    com a mesma matemática que build_bbmodel_recursive já usa pra
    posicionar a malha de referência desse element no mundo -- só
    invertendo pelo world matrix do bone no fim, pra expressar isso
    relativo ao bone em vez de relativo à raiz.

    `children_pivot_matrix`/`children_rotation_matrix` são os mesmos
    valores que o group dono já calcula pra recursar nos próprios
    filhos -- o element usa a mesma fórmula de posicionamento que um
    group filho usaria, só que sem virar um bone novo.

    `position_raw` vem em unidades de jogo cruas (dividido por
    unit_scale) -- ainda sem a correção de "subtrair o offset do shape
    primário do bone" (feita depois, por quem chama, só depois de saber
    qual element virou o primário). `is_identity` é True quando a
    rotação própria do element é, na prática, a identidade --
    matematicamente garantido quando elem["rotation"] é 0/ausente (o
    caso comum), já que nesse caso a rotação do element acaba sendo
    exatamente igual à do bone dono. Usado por quem chama pra decidir
    se dá pra "dobrar" este element dentro do próprio shape do bone (só
    soma no offset) ou se precisa virar um node filho sintético à parte
    (rotação não identidade -- um shape não tem orientação própria, só
    um node tem)."""
    elem_origin_scaled = Vector(elem.get("origin", [0.0, 0.0, 0.0])) * unit_scale
    elem_rotation_deg = elem.get("rotation", [0.0, 0.0, 0.0])
    elem_world_pos = children_pivot_matrix @ elem_origin_scaled
    elem_own_rotation = children_rotation_matrix @ bb_euler_matrix(elem_rotation_deg)
    elem_world_matrix = Matrix.Translation(elem_world_pos) @ elem_own_rotation

    local_matrix = group_world_matrix.inverted() @ elem_world_matrix
    local_pos, local_rot, _scale = local_matrix.decompose()

    is_identity = (
        abs(local_rot.w) > 0.999999
        and abs(local_rot.x) < 0.001
        and abs(local_rot.y) < 0.001
        and abs(local_rot.z) < 0.001
    )
    position_raw = local_pos / unit_scale
    orientation_dict = {
        "x": round(local_rot.x, 6),
        "y": round(local_rot.y, 6),
        "z": round(local_rot.z, 6),
        "w": round(local_rot.w, 6),
    }
    return position_raw, orientation_dict, is_identity


# Índice de textura "sem textura atribuída" (face real, só sem "texture" no
# JSON) -- ver normalização em import_bbmodel_data. Negativo
# pra nunca colidir com um índice real da lista "textures" do .bbmodel.
BBMODEL_UNASSIGNED_TEXTURE = -1


def make_bbmodel_cube_mesh(name, from_scaled, to_scaled, origin_scaled, stretch, faces, atlas_by_texture_index, generate_uvs):
    """Cria a malha de um element 'cube' do .bbmodel. Diferente de
    make_box_mesh (caixa sempre CENTRADA na origem, pro .blockymodel),
    aqui a caixa pode ser ASSIMÉTRICA em relação ao pivô (`origin_scaled`
    não é necessariamente o centro geométrico de from/to -- ex: o pivô de
    um pé costuma ficar no tornozelo, não no meio da caixa do pé).

    `stretch`: [sx,sy,sz] -- fator de escala por eixo, ao redor do próprio
    origin. Existe em CADA element do .bbmodel (não só o que aparece
    selecionado no painel do Blockbench -- ficou fácil de não perceber
    porque o painel só mostra o elemento selecionado no momento). Faz
    duas coisas ao mesmo tempo, igual o "shape.stretch" já faz no
    .blockymodel (ver local_offset_scale em add_reference_visuals):
      1) Redimensiona a caixa de verdade (ex: L-Eyelid stretch=[1,0.1,1]
         -- achata a pálpebra a 10% no Y).
      2) Quando NEGATIVO num eixo (ex: R-Arm stretch=[0.98,1,1] vs
         L-Arm stretch=[-0.98,1,1] -- os MESMOS valores de magnitude do
         par R/L no .blockymodel!), produz uma reflexão de verdade --
         mesmo mecanismo do .blockymodel pro espelhamento do lado L, só
         que aqui aplicado direto nos vértices locais em vez de via
         transform do objeto. Aplicar em `neg`/`pos` ANTES de montar
         verts_co (abaixo) já garante isso -- ao multiplicar por um
         stretch negativo, `pos` fica NUMERICAMENTE MENOR que `neg`
         (a ordem inverte), e como AS MESMAS variáveis (já invertidas)
         são usadas tanto pros vértices quanto pra normalizar a UV (ver
         bbmodel_compute_face_uv abaixo), o espelhamento se propaga
         automaticamente pros dois -- geometria E UV -- sem precisar de
         nenhum caso especial pro lado L/R.

    `atlas_by_texture_index`: dict {índice da texture no .bbmodel: (atlas_w,
    atlas_h)} -- resolvido pelo chamador a partir das texturas já
    carregadas (ver decode_bbmodel_texture), pra saber contra qual tamanho
    de atlas normalizar a UV de cada face (uma mesma malha só referencia
    UM índice de texture nas suas faces definidas -- confirmado no
    arquivo de teste: faces sem texture ficam com valor None e são só
    faces internas/escondidas, sem UV pra gerar mesmo)."""
    sx, sy, sz = stretch
    neg = ((min(from_scaled.x, to_scaled.x) - origin_scaled.x) * sx,
           (min(from_scaled.y, to_scaled.y) - origin_scaled.y) * sy,
           (min(from_scaled.z, to_scaled.z) - origin_scaled.z) * sz)
    pos = ((max(from_scaled.x, to_scaled.x) - origin_scaled.x) * sx,
           (max(from_scaled.y, to_scaled.y) - origin_scaled.y) * sy,
           (max(from_scaled.z, to_scaled.z) - origin_scaled.z) * sz)

    verts_co = [
        (neg[0], neg[1], neg[2]),
        (pos[0], neg[1], neg[2]),
        (pos[0], pos[1], neg[2]),
        (neg[0], pos[1], neg[2]),
        (neg[0], neg[1], pos[2]),
        (pos[0], neg[1], pos[2]),
        (pos[0], pos[1], pos[2]),
        (neg[0], pos[1], pos[2]),
    ]

    mesh = bpy.data.meshes.new(name + "_mesh")
    bm = bmesh.new()
    bm_verts = [bm.verts.new(co) for co in verts_co]

    uv_layer = bm.loops.layers.uv.new() if generate_uvs else None

    for bb_key, idxs in BOX_FACES_LOOP_ORDER:
        # bb_key já é a chave "hytale" (front/back/...) -- BOX_FACES_LOOP_ORDER
        # é compartilhada com o .blockymodel. Achar a chave do .bbmodel
        # (north/south/...) equivalente pra ler o dict "faces" do arquivo.
        bb_face_name = next((k for k, v in BB_FACE_TO_HYTALE_FACE_KEY.items() if v == bb_key), None)
        info = faces.get(bb_face_name) if bb_face_name else None
        tex_index = info.get("texture") if info else None

        # IMPORTANTE: o Blockbench SEMPRE grava a chave "uv" pra toda face,
        # mesmo quando ela não existe de verdade (ex: os 5 lados "de
        # dentro" de um quad achatado, tipo R-Ear2/R-Ear3 -- só que com
        # "uv": [0,0,0,0]). O sinal de "essa face não existe" é
        # texture=None, NÃO a ausência da chave "uv". Se não checar isso
        # AQUI (antes de criar a face) em vez de só pular a atribuição de
        # UV, sobra uma face sem UV sobreposta à face de verdade -- que no
        # Blender aparece preta (sem UV válida) exatamente onde deveria
        # ser invisível. bug real encontrado com R-Ear2/R-Ear3 do arquivo
        # de teste -- ver DEVELOPER_NOTES/histórico da conversa.
        if tex_index is None:
            continue

        face = bm.faces.new([bm_verts[i] for i in idxs])
        if uv_layer is None:
            continue
        atlas = atlas_by_texture_index.get(tex_index)
        if atlas is None:
            # Texture referenciada de verdade, mas não foi carregada (ex:
            # usuário desmarcou "Create Materials") -- a face É real,
            # só fica sem UV atribuída.
            continue
        atlas_w, atlas_h = atlas
        rect = info["uv"]
        rotation_deg = info.get("rotation", 0)

        fixed_axis = BOX_FACE_FIXED_AXIS[bb_key]
        axis_u, axis_v = FACE_AXES_BY_FIXED_AXIS[fixed_axis]
        for loop in face.loops:
            local_co = loop.vert.co
            u, v = bbmodel_compute_face_uv(local_co, neg, pos, axis_u, axis_v, bb_key, rect, rotation_deg, atlas_w, atlas_h)
            loop[uv_layer].uv = (u, v)

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def decode_bbmodel_texture(texture_entry):
    """Decodifica o PNG embutido em base64 (`texture_entry["source"]`,
    formato "data:image/png;base64,...") pra uma bpy.data.images, e a
    empacota (pack) no .blend -- assim não fica dependendo de um arquivo
    temporário que pode não existir mais depois. Devolve None se a
    texture não tiver source embutido (não deveria acontecer com
    .bbmodel, que sempre embute, mas fica defensivo)."""
    source = texture_entry.get("source", "")
    if not source.startswith("data:image"):
        return None
    header, _, b64data = source.partition(",")
    try:
        raw_bytes = base64.b64decode(b64data)
    except Exception:
        return None

    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw_bytes)
        image = bpy.data.images.load(tmp_path, check_existing=False)
        image.name = texture_entry.get("name", "Hytale_Texture")
        image.pack()  # embute os pixels no .blend -- não depende mais do tmp_path
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    return image


def prescan_bbmodel_mesh_groups(outliner_roots, groups_by_uuid):
    """Anda a árvore do outliner ANTES de criar bone/malha nenhuma, só pra
    responder duas perguntas adiantado (em espaço de uuid do JSON, não de
    nome de bone -- nomes de bone só existem depois de dedup, na hora de
    verdade da criação):

    - `uuids_with_direct_mesh`: quais groups têm pelo menos 1 element
      FILHO DIRETO (não contando elements de sub-groups).
    - `uuid_parent_map`: uuid do group -> uuid do group PAI (ou None se
      for raiz do outliner).

    Precisa ser um pré-scan (não dá pra descobrir isso "ao vivo" durante
    a construção de verdade) porque `children` mistura elements e
    sub-groups NA ORDEM DO ARQUIVO -- um group pode ter seu próprio
    element DEPOIS de um sub-group na lista, e o aninhamento do
    sub-group já precisa saber se esse group é "dono de malha" desde
    ANTES de descer nele. Ver bbmodel_ancestor_fn/resolve_mesh_bone_collection
    pra como isso é usado."""
    uuids_with_direct_mesh = set()
    uuid_parent_map = {}

    def walk(children, current_group_uuid):
        for child in children:
            if isinstance(child, str):
                if current_group_uuid is not None:
                    uuids_with_direct_mesh.add(current_group_uuid)
                continue
            group = groups_by_uuid.get(child.get("uuid"))
            if group is None:
                continue
            uuid_parent_map[child["uuid"]] = current_group_uuid
            walk(child.get("children", []), child["uuid"])

    walk(outliner_roots, None)
    return uuids_with_direct_mesh, uuid_parent_map


def make_bbmodel_ancestor_fn(mesh_build_context):
    """Devolve a função `nearest_ancestor_fn` (ver
    resolve_mesh_bone_collection) pro caminho .bbmodel -- traduz o
    caminho de uuids do pré-scan (prescan_bbmodel_mesh_groups) pra nomes
    de bone de verdade via mesh_build_context["group_uuid_to_bone_name"]
    (só populado durante a construção real, mas SEMPRE já disponível pra
    qualquer ancestral no momento em que um descendente precisa dele --
    bone pai sempre nasce antes de recursar pros filhos).

    Se `flat_mesh_collections` estiver ligado no operador, devolve uma
    função que sempre responde None (nenhum ancestral) -- é assim que o
    modo flat desliga o aninhamento sem precisar de um caminho de código
    separado em resolve_mesh_bone_collection."""
    if mesh_build_context["settings"].flat_mesh_collections:
        return lambda bone_name: None

    uuid_parent_map = mesh_build_context["uuid_parent_map"]
    uuids_with_direct_mesh = mesh_build_context["uuids_with_direct_mesh"]
    group_uuid_to_bone_name = mesh_build_context["group_uuid_to_bone_name"]
    bone_name_to_group_uuid = mesh_build_context["bone_name_to_group_uuid"]

    def ancestor_fn(bone_name):
        uuid = bone_name_to_group_uuid.get(bone_name)
        if uuid is None:
            return None
        parent_uuid = uuid_parent_map.get(uuid)
        while parent_uuid is not None:
            if parent_uuid in uuids_with_direct_mesh:
                return group_uuid_to_bone_name.get(parent_uuid)
            parent_uuid = uuid_parent_map.get(parent_uuid)
        return None

    return ancestor_fn


def build_bbmodel_recursive(
    armature_data,
    outliner_children,
    parent_bone_name,
    ancestor_pivot_matrix,
    ancestor_rotation_matrix,
    groups_by_uuid,
    elements_by_uuid,
    unit_scale,
    stats,
    mesh_build_context,
    parent_group_uuid=None,
):
    """Percorre uma lista de filhos do outliner (mistura de dict = group e
    string = uuid de element) e constrói bones (groups) + meshes
    (elements), recursivamente. `ancestor_pivot_matrix` e
    `ancestor_rotation_matrix` -- ver a nota grande no topo desta seção
    pra o que cada um representa e por que são acumuladores SEPARADOS.
    `parent_group_uuid`: uuid (no JSON, não nome de bone) do group ATUAL
    dono destes `outliner_children` -- None na raiz do outliner. Só serve
    pra resolver aninhamento de mesh collection (ver
    mesh_build_context["group_uuid_to_bone_name"]/bbmodel_ancestor_fn,
    abaixo) -- é uma identidade ESTÁVEL (uuid do arquivo) que não depende
    do nome final do bone no Blender (que pode levar dedup)."""
    edit_bones = armature_data.edit_bones

    for child in outliner_children:
        if isinstance(child, str):
            # Leaf: uuid de um element (cube) -- vira uma mesh, parentada
            # no bone ATUAL (parent_bone_name), não um bone novo.
            if not mesh_build_context["generate_meshes"]:
                continue
            elem = elements_by_uuid.get(child)
            if elem is None:
                continue
            elem_origin = Vector(elem.get("origin", [0, 0, 0])) * unit_scale
            elem_rotation = elem.get("rotation", [0, 0, 0])
            world_pos = ancestor_pivot_matrix @ elem_origin
            own_rotation = ancestor_rotation_matrix @ bb_euler_matrix(elem_rotation)
            obj_matrix = Matrix.Translation(world_pos) @ own_rotation

            from_scaled = Vector(elem.get("from", [0, 0, 0])) * unit_scale
            to_scaled = Vector(elem.get("to", [0, 0, 0])) * unit_scale
            stretch = elem.get("stretch", [1, 1, 1])
            faces = elem.get("faces", {}) or {}
            mesh = make_bbmodel_cube_mesh(
                elem.get("name", "Element"),
                from_scaled,
                to_scaled,
                elem_origin,
                stretch,
                faces,
                mesh_build_context["atlas_by_texture_index"],
                mesh_build_context["generate_uvs"],
            )
            obj = bpy.data.objects.new(elem.get("name", "Element") + "_ref", mesh)

            # Sub-collection pro group (bone) dono deste element (nome =
            # "{bone} - {armature}" -- ver resolve_mesh_bone_collection
            # sobre por que o sufixo do personagem é obrigatório),
            # aninhada (ou não -- ver flat_mesh_collections) dentro de
            # "Main - X". Se o element não tem group ancestral nenhum
            # (parent_bone_name is None, caso raro tratado no `else`
            # abaixo), não tem por qual bone separar -- fica solto direto
            # em target_collection, igual antes.
            if parent_bone_name is not None:
                mesh_collection = resolve_mesh_bone_collection(
                    mesh_build_context["bone_collection_cache"],
                    mesh_build_context["target_collection"],
                    mesh_build_context["armature_obj"].name,
                    parent_bone_name,
                    mesh_build_context["ancestor_fn"],
                )
                mesh_collection.objects.link(obj)
            else:
                mesh_build_context["target_collection"].objects.link(obj)

            tex_index = next((f.get("texture") for f in faces.values() if f.get("texture") is not None), None)
            material = mesh_build_context["material_by_texture_index"].get(tex_index)
            if material is not None:
                obj.data.materials.append(material)

            armature_obj = mesh_build_context["armature_obj"]
            if parent_bone_name is not None:
                obj.parent = armature_obj
                obj.matrix_world = armature_obj.matrix_world @ obj_matrix

                vgroup = obj.vertex_groups.new(name=parent_bone_name)
                vgroup.add(range(len(mesh.vertices)), 1.0, "REPLACE")

                armature_mod = obj.modifiers.new(name="Armature", type="ARMATURE")
                armature_mod.object = armature_obj
            else:
                # Caso raro: element sem NENHUM group ancestral (a raiz do
                # outliner é, no arquivo real que validamos, sempre um
                # group -- "Origin"). Sem bone pra parentar/pintar peso,
                # só posiciona a malha (sem deform, objeto solto).
                obj.matrix_world = armature_obj.matrix_world @ obj_matrix
                mesh_build_context["settings"].report(
                    {"WARNING"},
                    f"'{elem.get('name', 'Element')}' is a root-level element with no "
                    f"owning bone -- imported as a static mesh (not skinned).",
                )

            stats["meshes"] += 1
            continue

        # Não-string: nó de group de verdade, com seus próprios filhos.
        group = groups_by_uuid.get(child["uuid"])
        if group is None:
            continue

        name = group.get("name", "Bone")
        origin = Vector(group.get("origin", [0, 0, 0])) * unit_scale
        rotation_deg = group.get("rotation", [0, 0, 0])

        world_pos = ancestor_pivot_matrix @ origin
        own_rotation = ancestor_rotation_matrix @ bb_euler_matrix(rotation_deg)

        final_name = unique_bone_name(name, edit_bones)
        if final_name != name:
            mesh_build_context["settings"].report(
                {"WARNING"},
                f"Duplicate bone name '{name}' inside this .bbmodel -- renamed to "
                f"'{final_name}' in Blender. Original name preserved in the "
                f"'{BONE_ORIGINAL_NAME_PROP}' custom property for the exporter to use.",
            )

        bone = edit_bones.new(final_name)
        bone.head = (0, 0, 0)
        bone.tail = (0, BONE_DISPLAY_LENGTH_GAME_UNITS * unit_scale, 0)
        bone.matrix = Matrix.Translation(world_pos) @ own_rotation
        if final_name != name:
            bone[BONE_ORIGINAL_NAME_PROP] = name

        if parent_bone_name is not None and parent_bone_name in edit_bones:
            bone.parent = edit_bones[parent_bone_name]
            bone.use_connect = False

        stats["bones"] += 1

        # BONE_SHAPE_JSON_PROP guarda uma lista de "entradas de shape",
        # não um dict único (mesmo formato usado no caminho .blockymodel,
        # que embrulha num [shape] de 1 item -- ver
        # exporter.build_export_node_tree, que lê essa lista).
        #
        # Motivo: um personagem real revelou dois problemas que essa
        # mudança resolve:
        #   1) O "offset" de um element era calculado só relativo ao
        #      próprio origin dele -- mas origin do element quase nunca
        #      bate com o origin do group dono (confirmado numa amostra
        #      real: 83 de 105 elements tinham origin diferente do
        #      group), então o offset saía sistematicamente errado.
        #   2) Um group pode ter vários elements diretos (roupa em
        #      camada, orelhas em partes) -- .blockymodel só tem espaço
        #      pra 1 shape por node, então só o primeiro cubo era
        #      mantido, o resto descartado no export.
        #
        # Solução: pra cada element direto deste group, calcula a
        # transform local dele relativa ao bone (via matrizes, ver
        # bbmodel_element_local_transform). Um element cuja rotação
        # própria é identidade (o caso comum) "dobra" dentro do shape do
        # próprio bone (offset = offset da caixa + posição local do
        # origin do element). Um element com rotação própria de verdade
        # (confirmados 27 casos reais -- orelhas anguladas, por exemplo)
        # OU qualquer cubo além do primeiro sem-rotação, vira um node
        # filho sintético no .blockymodel exportado (com sua própria
        # position/orientation), já que um shape sozinho não tem
        # orientação independente. Formato da lista salva:
        #   [ {shape do próprio bone, offset já corrigido}   (ou {} se nenhum element virou primário)
        #   , {"shape":..., "position":{x,y,z}, "orientation":{x,y,z,w}}   (extra 1)
        #   , ...
        #   ]
        direct_element_uuids = [c for c in child.get("children", []) if isinstance(c, str)]
        if direct_element_uuids:
            group_world_matrix = bone.matrix.copy()
            children_pivot_matrix = ancestor_pivot_matrix @ bb_rotate_around_pivot(origin, rotation_deg)
            children_rotation_matrix = own_rotation

            primary_shape = None
            extra_entries = []
            total_uv_skipped = 0
            for elem_uuid in direct_element_uuids:
                elem = elements_by_uuid.get(elem_uuid)
                if elem is None:
                    continue
                shape, n_uv_skipped = bbmodel_element_to_shape(elem)
                total_uv_skipped += n_uv_skipped
                local_pos_raw, local_orient, is_identity = bbmodel_element_local_transform(
                    group_world_matrix, children_pivot_matrix, children_rotation_matrix, elem, unit_scale,
                )
                if primary_shape is None and is_identity:
                    shape["offset"] = {
                        "x": round(shape["offset"]["x"] + local_pos_raw.x, 6),
                        "y": round(shape["offset"]["y"] + local_pos_raw.y, 6),
                        "z": round(shape["offset"]["z"] + local_pos_raw.z, 6),
                    }
                    primary_shape = shape
                else:
                    extra_entries.append({
                        "shape": shape,
                        "position": {"x": round(local_pos_raw.x, 6), "y": round(local_pos_raw.y, 6), "z": round(local_pos_raw.z, 6)},
                        "orientation": local_orient,
                    })

            # As posições dos "extras" acima são relativas ao PIVÔ do
            # bone -- mas o .blockymodel soma o shape.offset do PAI na
            # hora de posicionar um filho (mesma regra document em
            # exporter.build_export_node_tree/node_local_matrix aqui em
            # cima). Como o "pai" desses filhos sintéticos é este PRÓPRIO
            # bone, subtraímos o offset primário AGORA (import), assim o
            # exporter não precisa saber nada sobre essa correção depois
            # -- só usa a position guardada direto.
            primary_offset = primary_shape["offset"] if primary_shape else {"x": 0.0, "y": 0.0, "z": 0.0}
            for entry in extra_entries:
                entry["position"] = {
                    "x": round(entry["position"]["x"] - primary_offset["x"], 6),
                    "y": round(entry["position"]["y"] - primary_offset["y"], 6),
                    "z": round(entry["position"]["z"] - primary_offset["z"], 6),
                }

            shapes_list = [primary_shape if primary_shape is not None else {}] + extra_entries
            bone[BONE_SHAPE_JSON_PROP] = json.dumps(shapes_list)
            offset_scaled = Vector((primary_offset["x"], primary_offset["y"], primary_offset["z"])) * unit_scale
            bone[BONE_SHAPE_OFFSET_PROP] = tuple(offset_scaled)

            if total_uv_skipped:
                mesh_build_context["settings"].report(
                    {"WARNING"},
                    f"'{bone.name}': {total_uv_skipped} face(s) with a texture rotation "
                    f"weren't converted for .blockymodel export (only unrotated faces "
                    f"are supported yet) -- those faces will import with no texture if "
                    f"you later export/reimport a .blockymodel from this rig.",
                )
        else:
            bone[BONE_SHAPE_JSON_PROP] = json.dumps([])

        # Registra a identidade uuid(JSON) -> nome final do bone no
        # Blender ASSIM QUE o bone nasce -- é o que permite
        # bbmodel_ancestor_fn (ver mais abaixo) traduzir um uuid de
        # ancestral achado no pré-scan pro nome de bone de verdade, e
        # sempre vai estar disponível a tempo pra qualquer descendente
        # (bones pai são sempre criados ANTES de recursar pros filhos).
        mesh_build_context["group_uuid_to_bone_name"][child["uuid"]] = bone.name
        mesh_build_context["bone_name_to_group_uuid"][bone.name] = child["uuid"]

        child_ancestor_pivot = ancestor_pivot_matrix @ bb_rotate_around_pivot(origin, rotation_deg)
        build_bbmodel_recursive(
            armature_data,
            child.get("children", []),
            bone.name,
            child_ancestor_pivot,
            own_rotation,
            groups_by_uuid,
            elements_by_uuid,
            unit_scale,
            stats,
            mesh_build_context,
            parent_group_uuid=child["uuid"],
        )


def derive_default_bbmodel_name(filepath, data):
    """Nome padrão pra Armature/Collection: o campo "name" do próprio
    arquivo (Blockbench sempre preenche isso com o nome do projeto), com
    fallback pro nome do arquivo sem extensão -- mesma lógica de
    derive_default_name, abaixo, mas o .bbmodel tem essa informação
    melhor que o .blockymodel (que não guarda nome de personagem
    nenhum)."""
    name = (data.get("name") or "").strip()
    if name:
        return name
    base = os.path.basename(filepath)
    if base.lower().endswith(".bbmodel"):
        base = base[: -len(".bbmodel")]
    return base or "Hytale_Rig"


def resolve_bbmodel_format(choice, data):
    """Resolve Character/Prop pra um .bbmodel (meta.model_format =
    "hytale_character"/"hytale_prop"; qualquer outro formato de projeto do
    Blockbench -- Bedrock, Java etc. -- cai em character, igual antes)."""
    if choice != "AUTO":
        return MODEL_FORMAT_PROP if choice == "PROP" else MODEL_FORMAT_CHARACTER
    return normalize_model_format((data.get("meta") or {}).get("model_format"))


# ---------------------------------------------------------------------------
# Operator: import de .bbmodel
# ---------------------------------------------------------------------------
#
# Só tem modo "criar Armature novo" -- ver a nota grande no topo da seção
# "Suporte a .bbmodel" pra o motivo (um .bbmodel salvo já vem com os
# attachments fundidos na árvore, não precisa reconstruir isso na
# importação como o modo "Attach to Existing" do .blockymodel faz).


def _bbmodel_import_props(lang):
    return {
        "filter_glob": StringProperty(default="*.bbmodel", options={"HIDDEN"}),
        "model_format": model_format_enum(lang, "bbmodel"),
        **import_option_props(lang, "bbmodel", (
            "armature_name", "orient_z_up", "unit_scale", "generate_reference_boxes", "flat_mesh_collections",
            "generate_uvs", "create_material",
        )),
    }


@localized_props(_bbmodel_import_props)
class IMPORT_OT_hytale_bbmodel(Operator, ImportHelper):
    """Import a Hytale character/creature from a Blockbench project (.bbmodel)"""

    bl_idname = "import_scene.hytale_bbmodel"
    bl_label = "Import Hytale Model (.bbmodel)"
    description = tooltip("importer.tooltip.bbmodel")
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".bbmodel"

    def draw(self, context):
        layout = self.layout
        lang = get_language(context)

        target_box = layout.box()
        target_box.label(text=tr("importer.section_target", lang))
        target_box.prop(self, "armature_name", text=tr("importer.armature_name", lang))

        draw_rig_section(layout, self, lang)
        draw_mesh_section(layout, self, lang)

    def execute(self, context):
        with open(self.filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        model_format = resolve_bbmodel_format(self.model_format, data)
        result, _armature_obj = import_bbmodel_data(self, context, data, self.filepath, model_format)
        return result


def import_bbmodel_data(operator, context, data, filepath, model_format, preloaded_images=None):
    """Núcleo do import de .bbmodel, separado do operador pra poder ser
    reaproveitado por quem MONTA um dict no formato .bbmodel em memória
    (ex: converter/bedrock.py, que traduz o .json do Bedrock pra esta
    estrutura e chama aqui -- mesmo Armature/malha/UV/BONE_SHAPE_JSON_PROP).

    `operator`: qualquer objeto com armature_name, orient_z_up,
    unit_scale, generate_reference_boxes, create_material,
    flat_mesh_collections, generate_uvs e report() -- normalmente o
    próprio operador. `model_format`: "character"/"prop" já resolvido.
    `preloaded_images`: {índice em data["textures"]: bpy Image ou LISTA
    [principal, variantes...]} pra texturas que o chamador já carregou
    (pula decode_bbmodel_texture). Variantes entram no mesmo material,
    empilhadas e sem conexão (stack_extra_texture_nodes) -- mesmo visual
    do import de .blockymodel.

    Devolve ({"FINISHED"}|{"CANCELLED"}, armature_obj|None)."""
    self = operator
    outliner_roots = data.get("outliner", [])
    if not outliner_roots:
        self.report({"ERROR"}, "No outliner data found in the file (.bbmodel is empty or invalid).")
        return {"CANCELLED"}, None

    groups_by_uuid = {g["uuid"]: g for g in data.get("groups", [])}
    elements_by_uuid = {e["uuid"]: e for e in data.get("elements", [])}

    # Face SEM a chave "texture" != face com "texture": null. No
    # Blockbench, null explícito = face escondida de propósito (ex: os
    # lados internos de um quad achatado -- é o que o resto do módulo
    # usa como sinal de "essa face não existe"); chave AUSENTE = face
    # real, só sem textura atribuída (Face.texture === false, que o
    # Blockbench nem grava). Acontece em modelo convertido de outro
    # formato (ex: .geo.json do Bedrock -> "Convert Project" pro
    # Hytale), que chega sem nenhuma textura embutida. Sem normalizar
    # aqui, TODAS as faces eram descartadas (malha com 8 vértices e 0
    # faces) e a captura de shape pro export saía sem UV. Com 1 textura
    # só no arquivo, a face "sem atribuição" usa ela (igual o
    # Blockbench mostra); senão vira o sentinel, que só ganha UV
    # (normalizada pela "resolution" do projeto), sem material.
    project_textures = data.get("textures", [])
    unassigned_tex_index = 0 if len(project_textures) == 1 else BBMODEL_UNASSIGNED_TEXTURE
    for element in elements_by_uuid.values():
        for face_info in (element.get("faces") or {}).values():
            if isinstance(face_info, dict) and "texture" not in face_info:
                face_info["texture"] = unassigned_tex_index

    resolved_name = self.armature_name.strip() or derive_default_bbmodel_name(filepath, data)
    armature_data = bpy.data.armatures.new(resolved_name)
    armature_obj = bpy.data.objects.new(resolved_name, armature_data)
    rig_collection, main_collection, attachments_collection = build_character_collections(
        context, armature_obj.name
    )
    rig_collection.objects.link(armature_obj)
    armature_obj["hytale_meshes_main_collection"] = main_collection.name
    armature_obj["hytale_meshes_attachments_collection"] = attachments_collection.name

    # Character (64/bloco) vs Prop (32/bloco) -- ver MODEL_FORMAT_* em common.py.
    armature_obj[ARMATURE_MODEL_FORMAT_PROP] = model_format
    scale = effective_unit_scale(self.unit_scale, model_format)

    context.view_layer.objects.active = armature_obj
    armature_obj.select_set(True)

    # Decodifica as texturas embutidas (base64) ANTES de entrar em Edit
    # Mode -- criação de imagem/material não depende do modo do
    # Armature, e assim já temos os tamanhos de atlas prontos pra
    # passar pra build_bbmodel_recursive (que roda dentro do Edit Mode
    # junto com a criação dos bones).
    atlas_by_texture_index = {}
    material_by_texture_index = {}
    if self.generate_reference_boxes and self.create_material:
        for idx, tex_entry in enumerate(data.get("textures", [])):
            preloaded = (preloaded_images or {}).get(idx)
            images = list(preloaded) if isinstance(preloaded, (list, tuple)) else [preloaded]
            images = [img for img in images if img is not None]
            if not images:
                decoded = decode_bbmodel_texture(tex_entry)
                images = [decoded] if decoded is not None else []
            if not images:
                continue
            image = images[0]
            atlas_by_texture_index[idx] = (image.size[0], image.size[1])
            material, tex_node = build_flat_material_from_image(
                image, material_name=tex_entry.get("name", "Hytale_Material")
            )
            stack_extra_texture_nodes(material, tex_node, images[1:])
            material_by_texture_index[idx] = material
    # Atlas do sentinel "sem textura atribuída" (ver normalização acima):
    # tamanho declarado do projeto, pra UV já sair certa quando o
    # usuário plugar a textura depois.
    resolution = data.get("resolution") or {}
    atlas_by_texture_index[BBMODEL_UNASSIGNED_TEXTURE] = (
        resolution.get("width", 16) or 16,
        resolution.get("height", 16) or 16,
    )

    # Pré-scan (só quando modo aninhado está ligado -- ver
    # make_bbmodel_ancestor_fn) pra saber ADIANTADO quais groups têm
    # malha DIRETA e qual é o group pai de cada group, em espaço de
    # uuid do JSON -- não dá pra descobrir isso "ao vivo" durante a
    # construção real porque elements/sub-groups vêm misturados na
    # ordem do arquivo (ver prescan_bbmodel_mesh_groups).
    if self.flat_mesh_collections:
        uuids_with_direct_mesh, uuid_parent_map = set(), {}
    else:
        uuids_with_direct_mesh, uuid_parent_map = prescan_bbmodel_mesh_groups(outliner_roots, groups_by_uuid)

    mesh_build_context = {
        "target_collection": main_collection,
        "armature_obj": armature_obj,
        "atlas_by_texture_index": atlas_by_texture_index,
        "material_by_texture_index": material_by_texture_index,
        "generate_meshes": self.generate_reference_boxes,
        "generate_uvs": self.generate_reference_boxes and self.generate_uvs,
        "settings": self,
        # Cache de resolve_mesh_bone_collection (uma vida só desta
        # chamada de import) -- separa as malhas por bone/group dono
        # dentro de "Main - X", aninhado ou flat conforme
        # flat_mesh_collections -- ver build_bbmodel_recursive.
        "bone_collection_cache": {},
        # uuid(JSON) <-> nome final do bone -- group_uuid_to_bone_name
        # é populado AO VIVO conforme os bones nascem (ver
        # build_bbmodel_recursive); bone_name_to_group_uuid é o
        # inverso, preenchido junto, usado por make_bbmodel_ancestor_fn
        # pra converter um bone_name de volta pro espaço de uuid antes
        # de andar uuid_parent_map.
        "group_uuid_to_bone_name": {},
        "bone_name_to_group_uuid": {},
        "uuids_with_direct_mesh": uuids_with_direct_mesh,
        "uuid_parent_map": uuid_parent_map,
    }
    # ancestor_fn só pode ser montada DEPOIS do dict acima existir --
    # ela fecha sobre mesh_build_context (lê group_uuid_to_bone_name/
    # bone_name_to_group_uuid, que só terminam de ser populados
    # durante build_bbmodel_recursive, mas sempre a tempo pra qualquer
    # ancestral -- ver make_bbmodel_ancestor_fn).
    mesh_build_context["ancestor_fn"] = make_bbmodel_ancestor_fn(mesh_build_context)

    # Mesma cautela do import de .blockymodel -- ver a nota grande em
    # IMPORT_OT_hytale_blockymodel.execute() sobre X-Axis Mirror.
    original_use_mirror_x = armature_data.use_mirror_x
    if original_use_mirror_x:
        armature_data.use_mirror_x = False

    stats = {"bones": 0, "meshes": 0}
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        build_bbmodel_recursive(
            armature_data,
            outliner_roots,
            None,
            Matrix.Identity(4),
            Matrix.Identity(4),
            groups_by_uuid,
            elements_by_uuid,
            scale,
            stats,
            mesh_build_context,
        )
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        if original_use_mirror_x:
            armature_data.use_mirror_x = original_use_mirror_x

    if self.orient_z_up:
        armature_obj.rotation_euler = Euler((math.radians(90.0), 0.0, 0.0), "XYZ")

    context.view_layer.update()

    self.report(
        {"INFO"},
        f"Imported {stats['bones']} bone(s) and {stats['meshes']} mesh(es) from '{resolved_name}' "
        f"({model_format}, scale={scale:.5f}).",
    )
    return {"FINISHED"}, armature_obj
