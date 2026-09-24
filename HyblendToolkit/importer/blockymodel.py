"""importer/blockymodel.py -- import de .blockymodel (só o que é específico
do formato: nodes com position/orientation relativos, shape box/quad,
layout de UV por offset, attachments)."""

import json
import math
import os
import re

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
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
    armature_model_format,
    bone_file_name,
    effective_unit_scale,
    normalize_model_format,
    quat_xyzw,
    vec3,
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
    collect_object_names_recursive,
    find_attachments_collection,
    resolve_mesh_bone_collection,
    unique_bone_name,
)
from .common_options import (
    draw_mesh_section,
    draw_rig_section,
    draw_texture_options,
    import_option_props,
    model_format_enum,
)
from .textures import (
    texture_result_report,
    get_or_create_material,
    resolve_texture_filepaths,
)


# --- Utilidades de conversão do JSON do .blockymodel ---
#
# Cada nó guarda "position" (translação) e "orientation" (quaternion
# x,y,z,w) relativos ao pai. A matriz de mundo de um nó é:
#
#   mundo(nó) = mundo(pai) @ Translacao(position) @ Rotacao(orientation)
#
# Confirmado numericamente (contra .gltf exportado pelo Blockbench,
# 55/55 nós batendo exatos, incluindo pernas/braços com rotação própria):
#
# 1) Escala: dividimos por 64 (UNIT_SCALE_DEFAULT) tudo que for medida
#    de comprimento (position, shape.offset, shape.settings.size),
#    porque o exportador de animação (Export_blockyanim.py, de Edrax)
#    multiplica por 64 ao gravar. "stretch" não é escalado, é um fator
#    adimensional.
#
# 2) Translação local = position(nó) + shape.offset(pai). O próximo
#    bone começa de onde a caixa visual do pai termina, não de onde o
#    pivô abstrato do pai está. A rotação continua aplicada normalmente
#    por cima via composição de matriz -- não é uma soma "pura" fora da
#    cadeia de rotação.
#
# 3) Quaternion (orientation): copiar x,y,z,w direto, sem inversão de
#    sinal ou permutação de eixo. Handedness testado e confirmado.

def shape_offset_of(node, settings):
    """Retorna o shape.offset do próprio nó, já escalado por unit_scale.
    Se o nó não tiver "shape" ou não tiver "offset", retorna vetor zero."""
    offset = vec3(node.get("shape", {}).get("offset", {}))
    return offset * settings.unit_scale


def node_local_matrix(node, parent_shape_offset, settings):
    """Matriz local (relativa ao pai) deste nó. Ver nota grande acima do
    módulo: translação local = position(nó) + shape.offset(pai), rotação
    aplicada normalmente por cima."""
    pos = vec3(node.get("position", {}))
    rot = quat_xyzw(node.get("orientation", {"w": 1.0}))

    pos = pos * settings.unit_scale
    pos = pos + parent_shape_offset  # parent_shape_offset já vem escalado

    return Matrix.Translation(pos) @ rot.to_matrix().to_4x4()


def build_bones_recursive(
    armature_data,
    node,
    parent_bone_name,
    parent_world_matrix,
    parent_shape_offset,
    world_matrices,
    node_id_to_bone_name,
    reusable_bone_names,
    settings,
):
    """Cria (ou reaproveita) o bone deste nó e recursivamente os dos filhos.

    `reusable_bone_names`: conjunto de nomes de bone que JÁ EXISTIAM no
    Armature ANTES desta chamada de import começar (snapshot tirado no
    início do execute()). Só esses nomes podem ser reaproveitados -- se o
    PRÓPRIO arquivo tiver nomes duplicados entre irmãos (ex: "FernTop"
    repetido no boss), o segundo NÃO está no snapshot, então vira um bone
    novo de verdade (o Blender renomeia sozinho pra "FernTop.001"), em vez
    de ser incorretamente fundido com o primeiro.

    Guarda em `world_matrices` e `node_id_to_bone_name`, indexados por
    id(node) (não pelo nome JSON!) -- necessário porque o nome real do
    bone no Blender pode diferir do nome no JSON (por causa do dedup
    automático), e diferentes ocorrências do mesmo nome (duplicatas) são
    nós Python DISTINTOS mesmo tendo o mesmo "name" no JSON."""
    name = node["name"]
    edit_bones = armature_data.edit_bones
    is_piece = bool((node.get("shape") or {}).get("settings", {}).get("isPiece"))
    # Candidato a "ponto de ancoragem": ou o arquivo marca explicitamente
    # (isPiece == true, igual o Blockbench oficial faz), ou é a RAIZ do
    # arquivo (parent_bone_name is None) -- que é sempre a intenção de um
    # attachment, mesmo nos arquivos que não marcam isPiece no JSON. Um nó
    # comum no MEIO da árvore (ex: "R-Eye-Background", filho do anchor)
    # nunca se qualifica, então nunca é candidato a reaproveitar um bone
    # que só por acaso já tenha esse nome.
    is_anchor_candidate = is_piece or parent_bone_name is None

    # IMPORTANTE: só reaproveita um bone existente se este nó for um
    # candidato a ponto de ancoragem (ver acima) -- é assim que o plugin
    # oficial de Blockbench decide isso também (blockymodel.ts,
    # parseNode(): `node.shape?.settings?.isPiece === true`), não por nome
    # batendo sozinho. Sem essa checagem extra, um bone COMUM dentro do
    # arquivo (ex: "R-Eye-Background", um filho do anchor
    # "R-Eye-Attachment") que por acaso já existisse no Armature -- por
    # exemplo, sobrando de um import ANTERIOR desse MESMO attachment (de
    # antes de algum bug ser corrigido) -- seria "reaproveitado" com a
    # posição VELHA/quebrada em vez de recalculado do zero a partir do
    # anchor correto. Foi exatamente isso que causou o olho R ficar preso
    # na origem do mundo mesmo depois do anchor (R-Eye-Attachment) já
    # estar correto: o filho dele (R-Eye-Background) tinha sobrado de uma
    # tentativa de import anterior, com a posição errada daquela vez, e
    # cada reimport devolvia essa mesma posição velha.
    wrapper_node_name = None  # só preenchido quando o anchor foi achado pelo nome original
    reuse = (
        settings.import_mode == "ATTACH_EXISTING"
        and is_anchor_candidate
        and name in reusable_bone_names
        and name in edit_bones
    )

    # Fallback tolerante: se o nome EXATO não bateu, tenta achar um único
    # candidato ignorando maiúscula/minúscula e espaços nas pontas (causa
    # comum de "bateu de um lado, não bateu do outro" ao editar o rig na
    # mão -- um espaço a mais, ou "R-Eye-Attachment" vs "r-eye-attachment").
    # Só usa se achar EXATAMENTE UM candidato, pra nunca mesclar com o bone
    # errado por engano. Continua exigindo ser candidato a anchor pelo
    # mesmo motivo acima.
    if not reuse and is_anchor_candidate and settings.import_mode == "ATTACH_EXISTING":
        needle = name.strip().lower()
        candidates = [n for n in reusable_bone_names if n.strip().lower() == needle and n in edit_bones]
        if len(candidates) == 1:
            name = candidates[0]
            reuse = True
        else:
            # Bone renomeado no Blender ("Rename Bones" do Bone Settings,
            # ou colisão resolvida no import) -- o nome do arquivo é o
            # ORIGINAL, guardado em BONE_ORIGINAL_NAME_PROP/
            # BONE_RENAMED_FROM_PROP (bone_file_name). Mesmo critério: só
            # um candidato, senão não arrisca.
            renamed = [
                n for n in reusable_bone_names
                if n in edit_bones and (bone_file_name(edit_bones[n]) or "").strip().lower() == needle
            ]
            if len(renamed) == 1:
                wrapper_node_name = name  # wrapper segue o nome do ARQUIVO, como no plugin oficial
                name = renamed[0]
                reuse = True

    # Aviso alto em vez de ficar quieto: um candidato a ancoragem que não
    # acha bone nenhum pra reaproveitar vira um bone novo, posicionado só
    # com as coordenadas LOCAIS do próprio arquivo (perto de {0,0,0} --
    # feitas pra serem somadas à posição de um bone existente, não pra
    # existir sozinhas). Isso é o que fazia um lado (ex: o olho R) "ir pro
    # centro do mundo" sem nenhum erro aparecer -- agora pelo menos avisa.
    # (Nós comuns, que não são candidatos a anchor, são pra ser criados do
    # zero mesmo -- não avisamos por eles.)
    if not reuse and is_anchor_candidate and parent_bone_name is None and settings.import_mode == "ATTACH_EXISTING":
        settings.report(
            {"WARNING"},
            f"'{name}' é um ponto de ancoragem (raiz do arquivo) mas não encontrou nenhum "
            f"bone existente com esse nome pra anexar -- foi criado como bone novo, na "
            f"posição bruta do arquivo (provavelmente perto da origem do mundo). Confira o "
            f"nome exato desse bone no seu Armature.",
        )

    if reuse:
        bone = edit_bones[name]
        world = bone.matrix.copy()

        # O plugin oficial de Blockbench, ao importar um attachment num
        # bone/pasta que JÁ EXISTE, não substitui nem funde direto nele --
        # ele cria um bone "wrapper" extra DENTRO do bone existente,
        # nomeado "{arquivo_sem_extensão}:{nome_do_nó}" (ex:
        # "Eyes:L-Eye-Attachment", vindo de um arquivo "Eyes.blockymodel"),
        # e é dentro desse wrapper que o resto do conteúdo do attachment
        # (Background, etc.) fica. Isso preserva o bone original intacto
        # entre reimports, e deixa rastreável de qual arquivo cada pedaço
        # veio. Reproduzimos aqui: o wrapper nasce na MESMA posição do
        # anchor reaproveitado (é só um agrupador, sem deslocamento
        # próprio), e os FILHOS deste nó (não o nó em si) passam a ser
        # parentados nele em vez de diretamente no anchor.
        children_parent_name = bone.name
        attachment_stem = getattr(settings, "attachment_stem", None)
        if attachment_stem:
            wrapper_name = f"{attachment_stem}:{wrapper_node_name or name}"
            wrapper = edit_bones.new(wrapper_name)
            wrapper.head = (0, 0, 0)
            wrapper.tail = (0, BONE_DISPLAY_LENGTH_GAME_UNITS * settings.unit_scale, 0)
            wrapper.matrix = world
            wrapper.parent = bone
            wrapper.use_connect = False
            children_parent_name = wrapper.name
    else:
        local = node_local_matrix(node, parent_shape_offset, settings)
        world = parent_world_matrix @ local

        bone_display_length = BONE_DISPLAY_LENGTH_GAME_UNITS * settings.unit_scale

        # Nomes duplicados DENTRO do mesmo arquivo: o Blockbench permite
        # duas pastas/bones com o mesmo nome (ex: dois "FernTop" em galhos
        # diferentes da árvore), mas o Blender não aceita dois bones com
        # nome idêntico no mesmo Armature. Sem tratamento, o Blender
        # resolveria a colisão sozinho renomeando o segundo pra
        # "FernTop.001" -- o que quebra o round-trip, porque o exporter
        # grava o NOME DO BONE NO BLENDER no .blockyanim, e o jogo espera
        # o nome original ("FernTop"), sem sufixo nenhum. Resolvemos a
        # colisão nós mesmos (ver unique_bone_name, acima) e guardamos o
        # nome original numa custom property pro exporter usar -- ver
        # BONE_ORIGINAL_NAME_PROP em common.py e DEVELOPER_NOTES.md.
        final_name = unique_bone_name(name, edit_bones)
        if final_name != name:
            settings.report(
                {"WARNING"},
                f"Duplicate bone name '{name}' inside this file -- renamed to "
                f"'{final_name}' in Blender. Original name preserved in the "
                f"'{BONE_ORIGINAL_NAME_PROP}' custom property for the exporter "
                f"to use.",
            )

        bone = edit_bones.new(final_name)
        bone.head = (0, 0, 0)
        bone.tail = (0, bone_display_length, 0)
        bone.matrix = world
        if final_name != name:
            bone[BONE_ORIGINAL_NAME_PROP] = name

        if parent_bone_name is not None and parent_bone_name in edit_bones:
            bone.parent = edit_bones[parent_bone_name]
            bone.use_connect = False

        children_parent_name = bone.name

    world_matrices[id(node)] = world.copy()
    node_id_to_bone_name[id(node)] = bone.name

    # Se o bone foi REAPROVEITADO (merge), o shape.offset que ESTE arquivo
    # descreve pra esse nó é de uma fonte "estranha" -- pertence à descrição
    # que o arquivo de attachment faz desse ponto, não ao corpo real que já
    # foi importado antes. Usar esse valor pra deslocar os filhos (ex: as
    # mechas de cabelo) causa deslocamentos errados quando esse offset não
    # é zero (confirmado: R-Eye-Attachment tinha offset zero, por isso
    # nunca deu problema; o Head do cabelo tem offset {0,15,3}, e usar isso
    # empurrava a mecha pra dentro do rosto).
    #
    # MAS zerar o offset é só "meio certo": comparando com o plugin oficial
    # de Blockbench (src/blockymodel.ts, parseNode + src/util.ts,
    # getMainShape), o ponto de ancoragem correto para os filhos de um
    # attachment não é o pivô puro do bone, e sim o CENTRO DA CAIXA VISUAL
    # do bone já existente -- ou seja, pivô do bone + shape.offset que ESSE
    # MESMO bone tinha no modelo principal (não o offset vindo do arquivo
    # de attachment, que de fato é de outra fonte e deve ser ignorado).
    #
    # Por isso guardamos o shape.offset de cada bone, como propriedade
    # customizada nele mesmo, no momento em que ele é criado pela primeira
    # vez (import do modelo principal) -- e o recuperamos aqui, em vez de
    # usar zero, quando o bone é reaproveitado num import de attachment.
    if reuse:
        stored_offset = bone.get(BONE_SHAPE_OFFSET_PROP)
        this_node_shape_offset = (
            Vector(stored_offset) if stored_offset is not None else Vector((0.0, 0.0, 0.0))
        )
    else:
        this_node_shape_offset = shape_offset_of(node, settings)
        bone[BONE_SHAPE_OFFSET_PROP] = tuple(this_node_shape_offset)
        # Embrulhado numa lista de 1 item ([shape], não só `shape`) pra
        # bater com o formato que o caminho .bbmodel usa (lista de
        # entradas -- ver bbmodel_element_local_transform) -- um node
        # de .blockymodel só tem no máximo 1 shape mesmo, mas o
        # exporter (build_export_node_tree) espera sempre uma lista.
        bone[BONE_SHAPE_JSON_PROP] = json.dumps([node.get("shape", {})])

    for child in node.get("children", []):
        build_bones_recursive(
            armature_data,
            child,
            children_parent_name,
            world,
            this_node_shape_offset,
            world_matrices,
            node_id_to_bone_name,
            reusable_bone_names,
            settings,
        )


OPPOSITE_FACE = {
    "front": "back", "back": "front",
    "top": "bottom", "bottom": "top",
    "left": "right", "right": "left",
}


# Pra shapes tipo "quad": o Blockbench só guarda offset/mirror/angle sob a
# chave "front" do textureLayout (settings.normal é que diz pra qual lado
# essa face realmente aponta). Mas a face GEOMÉTRICA de verdade -- usada
# pra saber a correspondência vértice<->canto do retângulo de UV (ver
# BOX_FACE_BASE_SIGN) -- é a que corresponde ao normal, não sempre "front".
# Ex: normal "-Z" -> geometricamente é a face "back" (mesmo a textura
# vindo de "front"). Ver blockymodel.ts, parseNode(), linhas ~666-673
# (`normal_faces` + o bloco que força `uv_source = textureLayout['front']`
# mas ainda escreve o resultado na face REAL apontada pelo normal).
NORMAL_TO_HYTALE_FACE_KEY = {
    "+Z": "front", "-Z": "back",
    "+X": "right", "-X": "left",
    "+Y": "top", "-Y": "bottom",
}


def face_size_raw(size_raw, fixed_axis):
    """Largura/altura (em unidades de jogo, NÃO escaladas) da face cujo
    eixo fixo é `fixed_axis` ('x'/'y'/'z')."""
    au, av = FACE_AXES_BY_FIXED_AXIS[fixed_axis]
    comps = (size_raw.x, size_raw.y, size_raw.z)
    return comps[au], comps[av]


def _blockbench_uv_rect(fw, fh, angle, mirror, offset):
    """Retângulo [x1, y1, x2, y2] em PIXELS (podendo vir "invertido", isto
    é x1>x2 e/ou y1>y2, representando espelhamento) que o textureLayout de
    UMA face descreve.

    Port FIEL do algoritmo do plugin OFICIAL Blockbench<->Hytale
    (JannisX11/hytale-blockbench-plugin, src/blockymodel.ts, dentro de
    parseNode(), bloco "// UV", ~linhas 656-756 -- é a direção de PARSE,
    arquivo -> Blockbench, a mesma direção que este addon precisa). `fw`/
    `fh` já devem vir com a troca left/right (usa size.z como largura) e
    top/bottom (usa size.z como altura) aplicada -- ver face_size_raw /
    BOX_FACE_FIXED_AXIS, que já reproduz exatamente os `case 'left': ...`
    etc. do arquivo original.

    Isso substitui a heurística anterior (reverse-engineering numérico
    contra um único arquivo, o Player) por uma tradução direta do código
    fonte real -- a heurística cobria bem os casos que apareciam no Player,
    mas tinha lacunas admitidas (ex: nenhuma amostra confirmava mirror.y
    combinado com ângulos pares) que causavam UV errada em outras
    criaturas cujas combinações de angle/mirror não apareciam no Player.
    """
    ux = offset.get("x", 0.0)
    uy = offset.get("y", 0.0)
    uv_size = [fw, fh]
    mx = bool(mirror.get("x"))
    my = bool(mirror.get("y"))
    uv_mirror = [-1.0 if mx else 1.0, -1.0 if my else 1.0]
    k = angle or 0

    if k == 90:
        uv_size[0], uv_size[1] = uv_size[1], uv_size[0]
        uv_mirror[0], uv_mirror[1] = uv_mirror[1], uv_mirror[0]
        uv_mirror[0] *= -1
        x1, y1 = ux, uy + uv_size[1] * uv_mirror[1]
        x2, y2 = ux + uv_size[0] * uv_mirror[0], uy
    elif k == 270:
        uv_size[0], uv_size[1] = uv_size[1], uv_size[0]
        uv_mirror[0], uv_mirror[1] = uv_mirror[1], uv_mirror[0]
        uv_mirror[1] *= -1
        x1, y1 = ux + uv_size[0] * uv_mirror[0], uy
        x2, y2 = ux, uy + uv_size[1] * uv_mirror[1]
    elif k == 180:
        uv_mirror[0] *= -1
        uv_mirror[1] *= -1
        x1, y1 = ux + uv_size[0] * uv_mirror[0], uy + uv_size[1] * uv_mirror[1]
        x2, y2 = ux, uy
    else:
        # 0 graus -- e também fallback pra qualquer ângulo fora de
        # {0,90,180,270}: o Blockbench oficial (JS) simplesmente deixa a
        # UV zerada nesse caso (nenhum branch do switch bate), o que
        # geraria um "buraco" visual; aqui preferimos cair no caso 0 como
        # fallback seguro em vez de zerar.
        x1, y1 = ux, uy
        x2, y2 = ux + uv_size[0] * uv_mirror[0], uy + uv_size[1] * uv_mirror[1]

    return x1, y1, x2, y2


def compute_atlas_size(root_nodes):
    """Percorre a árvore inteira e infere o tamanho do atlas de textura
    (largura/altura não são guardadas no .blockymodel). Usa a MESMA
    matemática de compute_face_uv (incluindo troca de dimensões em
    rotações de 90/270 e ancoragem de canto) para achar o menor retângulo
    que contém todas as faces -- por ser só um limite inferior, pode ficar
    1-2px menor que a textura real caso sobre uma margem não usada nela
    (foi o caso da altura no Player_With_Face: infere 127, textura real é
    128). Prefira usar a opção "Atlas Size" do importador quando souber o
    tamanho exato do arquivo de textura."""
    max_x, max_y = 1.0, 1.0

    def visit(node):
        nonlocal max_x, max_y
        shape = node.get("shape", {})
        shape_type = shape.get("type")
        size = shape.get("settings", {}).get("size", {})
        size_raw = vec3(size, default=1.0)
        tex_layout = shape.get("textureLayout", {})

        for face_key, info in tex_layout.items():
            if shape_type == "box":
                fixed_axis = BOX_FACE_FIXED_AXIS.get(face_key)
                if fixed_axis is None:
                    continue
                fw, fh = face_size_raw(size_raw, fixed_axis)
            else:
                # quad: usa o próprio settings.size (2D) direto; sem
                # referência de ground-truth para quads rotacionados,
                # tratamos como uma face "front" (comportamento anterior).
                fw, fh = size_raw.x, size_raw.y
                face_key = "front"

            off = info.get("offset", {})
            mirror = info.get("mirror", {})
            angle = info.get("angle", 0)
            x1, y1, x2, y2 = _blockbench_uv_rect(fw, fh, angle, mirror, off)
            max_x = max(max_x, x1, x2)
            max_y = max(max_y, y1, y2)

        for child in node.get("children", []):
            visit(child)

    for root_node in root_nodes:
        visit(root_node)
    return max_x, max_y


def compute_face_uv(local_co, half_extents, axis_u, axis_v, face_key, tex_offset, face_w, face_h, mirror, angle, atlas_w, atlas_h):
    """Calcula a UV de um vértice de uma face, a partir da sua posição
    local (no espaço da própria caixa, centrada na origem), mapeando pro
    retângulo dessa face dentro do atlas de textura (ver
    _face_uv_offsets_and_axes para a matemática validada de rotação/
    espelho/ancoragem de canto)."""
    hu = half_extents[axis_u] or 1.0
    hv = half_extents[axis_v] or 1.0
    s = (local_co[axis_u] + hu) / (2.0 * hu)
    t = (local_co[axis_v] + hv) / (2.0 * hv)

    # bs/bt (BOX_FACE_BASE_SIGN) dizem, pra essa face, se o eixo local s/t
    # (nosso, geométrico) anda na MESMA direção que o eixo s/t que o
    # Blockbench usa internamente pra desenrolar a caixa, ou na direção
    # OPOSTA. Isso é 100% geometria (ordem dos vértices da caixa) e não
    # depende de angle/mirror -- por isso continua vindo da tabela
    # validada numericamente contra o Player, mesmo agora que o resto da
    # matemática (offset/tamanho/ângulo/espelho -> retângulo em pixels)
    # vem direto do código fonte oficial do Blockbench.
    bs, bt = BOX_FACE_BASE_SIGN.get(face_key, (1, -1))
    s_bb = s if bs > 0 else 1.0 - s
    t_bb = t if bt > 0 else 1.0 - t

    # SEGUNDA rotação, separada da que já está embutida em
    # _blockbench_uv_rect: o Blockbench guarda o mesmo `angle` como
    # `face.rotation` e, na hora de desenhar a malha de verdade (não no
    # plugin do Hytale -- isso é do app PRINCIPAL do Blockbench,
    # js/outliner/types/cube.js, Preview_controller.updateUV, ~linha 1390),
    # permuta ciclicamente os 4 cantos da UV uma vez pra cada 90° de
    # `face.rotation`:
    #
    #   let rot = face.rotation
    #   while (rot > 0) {
    #       let a = arr[0]; arr[0]=arr[2]; arr[2]=arr[3]; arr[3]=arr[1]; arr[1]=a;
    #       rot = rot - 90;
    #   }
    #
    # Resolvendo essa permutação algebricamente pros 4 cantos (arr[0..3] =
    # (s_bb,t_bb) em (0,0)/(1,0)/(0,1)/(1,1)), ela equivale a rotacionar o
    # PONTO (s_bb, t_bb) dentro do quadrado unitário, uma vez por passo de
    # 90°: (s, t) -> (t, 1 - s). Sem isso, ângulos de 0°/180° podiam
    # "acertar por coincidência" em vários casos, mas 90°/270° saíam
    # sempre errados -- exatamente o padrão relatado (faces giradas 90 ou
    # -90 do que deveriam).
    k = int(round((angle or 0) / 90.0)) % 4
    for _ in range(k):
        s_bb, t_bb = t_bb, 1.0 - s_bb

    x1, y1, x2, y2 = _blockbench_uv_rect(face_w, face_h, angle, mirror, tex_offset)
    px = x1 + (x2 - x1) * s_bb
    py = y1 + (y2 - y1) * t_bb

    u = px / atlas_w
    v = 1.0 - (py / atlas_h)
    return u, v


# ---------------------------------------------------------------------------
# Geração de meshes de referência (box / quad)
# ---------------------------------------------------------------------------


def collect_visual_shape_nodes(node, out):
    """Percorre a árvore e junta nós com shape 'box' ou 'quad' (o que sabemos
    desenhar). Nós 'none' são só pivôs/attachments, sem visual."""
    shape_type = node.get("shape", {}).get("type")
    if shape_type in ("box", "quad"):
        out.append(node)
    for child in node.get("children", []):
        collect_visual_shape_nodes(child, out)


def make_box_mesh(name, size_scaled, size_raw, shape, atlas_w, atlas_h, generate_uvs, missing_face_mode="SKIP"):
    """Cria uma malha de caixa CENTRADA NA ORIGEM com as dimensões exatas
    de size_scaled (x,y,z). Se generate_uvs, também mapeia UVs por face a
    partir do textureLayout da shape.

    `missing_face_mode` decide o que fazer quando uma face NÃO tem entrada
    no textureLayout. CONFIRMADO lendo o código-fonte do plugin oficial do
    Hytale pro Blockbench (ver nota grande dentro do loop abaixo): isso
    SEMPRE significa que a face não tinha textura no Blockbench -- não
    existe caso de "encoberta por outra peça, mas com textura própria".
      - "SKIP" (padrão): não cria a face. Fiel ao que o Blockbench mostraria
        se você reabrisse o mesmo arquivo lá.
      - "OPPOSITE_FALLBACK": cria a face e reaproveita a textura da face
        OPOSTA da mesma caixa (comportamento antigo, anterior a esta
        correção). NÃO reproduz o Blockbench de verdade -- é só um patch
        cosmético pra quem prefere ver alguma textura a um buraco.
    """
    hx, hy, hz = size_scaled.x / 2.0, size_scaled.y / 2.0, size_scaled.z / 2.0
    # IMPORTANTE: os vértices da malha (verts_co abaixo) são construídos em
    # unidades ESCALADAS (hx,hy,hz). O half_extents usado dentro de
    # compute_face_uv pra normalizar local_co (s = (local_co+hu)/(2*hu))
    # precisa estar NAS MESMAS UNIDADES -- senão a razão fica sempre perto
    # de 0.5 (um "pontinho" perto do centro da face) em vez de variar 0..1
    # ao longo dela. face_w/face_h (fw,fh abaixo) continuam vindo de
    # size_raw, pois representam o tamanho em PIXELS da região no atlas,
    # que é independente da escala do mesh.
    half_extents = (hx, hy, hz)

    verts_co = [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ]

    mesh = bpy.data.meshes.new(name + "_mesh")
    bm = bmesh.new()
    bm_verts = [bm.verts.new(co) for co in verts_co]

    uv_layer = bm.loops.layers.uv.new() if generate_uvs else None
    tex_layout = shape.get("textureLayout", {})

    for face_key, idxs in BOX_FACES_LOOP_ORDER:
        # face_key ausente do textureLayout -- CONFIRMADO lendo o código-fonte
        # do próprio plugin oficial do Hytale pro Blockbench
        # (JannisX11/hytale-blockbench-plugin, src/blockymodel.ts):
        #   - Na EXPORTAÇÃO (Blockbench -> .blockymodel): `if (face.texture
        #     == null) continue;` -- só pula gravar a chave quando a face
        #     não tinha textura NENHUMA no Blockbench.
        #   - Na IMPORTAÇÃO (.blockymodel -> Blockbench): `if (!uv_source) {
        #     resetFace(face_name); continue; }` -- ausência de chave vira
        #     literalmente `texture: null` na hora de reconstruir o cubo no
        #     Blockbench.
        # Ou seja: NÃO existe um caso de "face implicitamente encoberta por
        # outra peça, mas com textura própria escondida" -- ausência de
        # chave SEMPRE significa "sem textura mesmo", ponto. SKIP é o
        # comportamento FIEL ao que o Blockbench mostraria se você reabrisse
        # o mesmo arquivo lá. Se uma face que parece precisar de textura
        # (tipo o "top" do Jaw, visível quando a boca abre) ficar sem
        # textura, isso é uma característica do .blockymodel de origem (o
        # artista deixou aquela face sem pintar), não um bug do importer --
        # nem um "buraco escondido por engano" pra tentar detectar
        # geometricamente. OPPOSITE_FALLBACK continua existindo como
        # escape hatch puramente cosmético (não reproduz o Blockbench de
        # verdade) pra quem preferir ver alguma textura a um buraco.
        lookup_key = face_key
        if face_key not in tex_layout:
            if missing_face_mode == "OPPOSITE_FALLBACK":
                lookup_key = OPPOSITE_FACE.get(face_key)
                if lookup_key not in tex_layout:
                    continue
            else:
                continue

        face = bm.faces.new([bm_verts[i] for i in idxs])
        if uv_layer is not None:
            info = tex_layout[lookup_key]
            fixed_axis = BOX_FACE_FIXED_AXIS[face_key]
            axis_u, axis_v = FACE_AXES_BY_FIXED_AXIS[fixed_axis]
            fw, fh = face_size_raw(size_raw, fixed_axis)
            tex_offset = info.get("offset", {})
            mirror = info.get("mirror", {})
            angle = info.get("angle", 0)
            for loop in face.loops:
                local_co = loop.vert.co
                u, v = compute_face_uv(
                    local_co, half_extents, axis_u, axis_v, face_key, tex_offset, fw, fh, mirror, angle, atlas_w, atlas_h
                )
                loop[uv_layer].uv = (u, v)

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def make_quad_mesh(name, shape, size_scaled_2d, size_raw_2d, atlas_w, atlas_h, generate_uvs):
    """Cria uma malha plana (1 ou 2 faces, se doubleSided) pro shape tipo
    'quad', orientada conforme settings.normal ('+X'/'-X'/'+Y'/... etc)."""
    normal = shape.get("settings", {}).get("normal", "+Z")
    axis_letter = normal[-1].lower() if normal else "z"
    fixed_axis = axis_letter if axis_letter in ("x", "y", "z") else "z"
    axis_u, axis_v = FACE_AXES_BY_FIXED_AXIS[fixed_axis]
    # Chave "geométrica" real dessa face (pra achar o sinal-base correto em
    # BOX_FACE_BASE_SIGN) -- ver nota em NORMAL_TO_HYTALE_FACE_KEY. Pode
    # ser diferente da chave usada pra LER os dados do textureLayout
    # (essa continua vindo de `face_key` abaixo, quase sempre "front").
    geom_face_key = NORMAL_TO_HYTALE_FACE_KEY.get(normal, "front")

    hu, hv = size_scaled_2d.x / 2.0, size_scaled_2d.y / 2.0
    # Mesmo cuidado do make_box_mesh: half_extents precisa estar nas MESMAS
    # unidades dos vértices da malha (escaladas), não nas unidades brutas.
    half_extents = [0.0, 0.0, 0.0]
    half_extents[axis_u] = hu or 1.0
    half_extents[axis_v] = hv or 1.0

    def assemble(val_u, val_v):
        co = [0.0, 0.0, 0.0]
        co[axis_u] = val_u
        co[axis_v] = val_v
        return tuple(co)

    verts_co = [
        assemble(-hu, -hv),
        assemble(hu, -hv),
        assemble(hu, hv),
        assemble(-hu, hv),
    ]

    mesh = bpy.data.meshes.new(name + "_mesh")
    bm = bmesh.new()

    uv_layer = bm.loops.layers.uv.new() if generate_uvs else None
    tex_layout = shape.get("textureLayout", {})
    # quads normalmente só têm uma face definida em textureLayout (ex: "front")
    face_key = next(iter(tex_layout.keys()), None)

    def build_face(vert_order):
        # IMPORTANTE: bmesh identifica uma face pelo CONJUNTO de vértices,
        # não pela ordem/direção -- reaproveitar os mesmos 4 vértices pra
        # desenhar a face "de trás" (só invertendo a ordem) dá
        # "face already exists". Por isso cada face usa seu PRÓPRIO
        # conjunto de vértices (mesmas coordenadas, objetos diferentes).
        verts = [bm.verts.new(verts_co[i]) for i in vert_order]
        face = bm.faces.new(verts)
        if uv_layer is not None and face_key is not None:
            info = tex_layout[face_key]
            tex_offset = info.get("offset", {})
            mirror = info.get("mirror", {})
            angle = info.get("angle", 0)
            for loop in face.loops:
                local_co = loop.vert.co
                u, v = compute_face_uv(
                    local_co, tuple(half_extents), axis_u, axis_v, geom_face_key, tex_offset,
                    size_raw_2d.x, size_raw_2d.y, mirror, angle, atlas_w, atlas_h,
                )
                loop[uv_layer].uv = (u, v)

    # Ordem dos vértices decide pra que lado a normal da face aponta. Uma
    # face única (não doubleSided) precisa "olhar" pro lado indicado por
    # settings.normal -- senão fica de costas (invisível/culled do lado
    # certo). Se for doubleSided, as duas ordens são desenhadas de qualquer
    # forma, então a escolha da primeira não importa.
    default_order = (0, 1, 2, 3)
    flipped_order = (3, 2, 1, 0)
    primary_order = flipped_order if (normal and normal.startswith("-")) else default_order

    build_face(primary_order)
    if shape.get("doubleSided"):
        build_face(flipped_order if primary_order is default_order else default_order)

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def add_reference_visuals(
    armature_obj, root_nodes, world_matrices, node_id_to_bone_name, settings, atlas_w, atlas_h, target_collection,
    texture_filepaths=None,
):
    """Cria malhas de referência visual (box/quad), presas ao bone
    correspondente via parenting real + modifier Armature + Vertex Group
    com peso 1.0 (equivalente, na bind pose, ao antigo esquema de
    constraint Child Of, mas agora com weight painting de verdade
    disponível pro usuário -- ver nota grande dentro do loop, abaixo).
    `root_nodes` é uma LISTA
    (um .blockymodel pode ter mais de uma raiz -- ex: attachments como
    Eyes.blockymodel, que trazem R-Eye-Attachment e L-Eye-Attachment como
    dois nós de topo independentes). `target_collection` já vem resolvida
    pelo chamador (execute()) -- 'Main - X' pra NEW_ARMATURE, 'Mesh
    Attachments - X' pra ATTACH_EXISTING (ver build_character_collections/
    find_attachments_collection). `texture_filepaths` já vem RESOLVIDA
    pelo chamador (ver resolve_texture_filepaths, em execute()) -- prioriza
    o que o usuário digitou manualmente (um único caminho, nesse caso) e
    só recorre à auto-descoberta (discover_texture_paths, mesma convenção
    do plugin oficial) se ele tiver deixado em branco -- podendo trazer
    MAIS de um caminho (variantes de textura da mesma pasta, ex:
    Player_Greyscale.png + Player_Muscular_Greyscale.png + Outlander_1.png).
    Não lemos settings.texture_filepath diretamente aqui pra não confundir
    "o que o usuário digitou" com "o que o import decidiu usar de fato"."""
    shape_nodes = []
    for root_node in root_nodes:
        collect_visual_shape_nodes(root_node, shape_nodes)

    boxes_collection = target_collection

    material = None
    if settings.create_material:
        material, loaded_image, all_loaded_images = get_or_create_material(atlas_w, atlas_h, texture_filepaths)
        if loaded_image is not None and loaded_image.size[0] > 0 and loaded_image.size[1] > 0:
            # Textura real carregada -- usa as dimensões DELA pro cálculo de
            # UV em vez do valor inferido/manual (é a fonte mais confiável
            # que existe: o arquivo de pixels de verdade).
            atlas_w, atlas_h = loaded_image.size[0], loaded_image.size[1]
        if len(all_loaded_images) > 1:
            other_names = ", ".join(img.name for img in all_loaded_images[1:])
            settings.report(
                {"INFO"},
                f"{len(all_loaded_images) - 1} additional texture variant(s) loaded (not "
                f"connected, available for quick swap in the Image Texture node's browser): "
                f"{other_names}.",
            )


    # Snapshot dos nomes que JÁ existiam na collection ANTES desta chamada
    # de import -- só esses contam como "importado numa passada anterior" e
    # devem ser pulados. Comparar ao vivo contra boxes_collection.objects
    # (que cresce a cada iteração DESTE MESMO loop) fazia dois nós do MESMO
    # arquivo com o mesmo nome (permitido no Blockbench -- ex: duas pastas
    # "FernTop" em galhos diferentes) resultarem no segundo sendo
    # incorretamente tratado como duplicata de uma passada anterior e
    # pulado, sumindo com a malha de referência dele. Mesma lógica de
    # `reusable_bone_names`, em execute(), acima.
    #
    # RECURSIVO (collect_object_names_recursive, não só
    # boxes_collection.objects.keys()) desde que as malhas passaram a
    # morar dentro de uma sub-collection por bone (ver
    # resolve_mesh_bone_collection, abaixo) -- boxes_collection em si não
    # tem mais objeto NENHUM linkado direto, só sub-collections.
    existing_ref_names_before = set()
    collect_object_names_recursive(boxes_collection, existing_ref_names_before)

    # Cache local (uma vida só desta chamada) pra resolve_mesh_bone_collection
    # não reescanear as collections a cada malha do mesmo bone.
    bone_collection_cache = {}

    # nearest_ancestor_fn pro modo aninhado (padrão): bones_with_mesh é o
    # conjunto de bones que são donos de pelo menos 1 shape DIRETA -- só
    # esses ganham collection própria (mesma regra "só cria quando tem
    # malha dentro" de antes). A cadeia de pais já está inteira disponível
    # aqui (armature_obj.data.bones, Object Mode -- todos os bones do
    # arquivo já foram commitados antes desta função ser chamada), então
    # não precisa de pré-scan feito à parte, diferente do caminho .bbmodel
    # (onde bone e malha nascem juntos, na mesma passada -- ver
    # prescan_bbmodel_mesh_groups). Modo flat (settings.flat_mesh_collections)
    # simplesmente nunca devolve ancestral nenhum.
    if settings.flat_mesh_collections:
        ancestor_fn = lambda bone_name: None
    else:
        bones_with_mesh = {node_id_to_bone_name[id(n)] for n in shape_nodes}
        bones_data = armature_obj.data.bones

        def ancestor_fn(bone_name):
            bone = bones_data.get(bone_name)
            if bone is None:
                return None
            parent = bone.parent
            while parent is not None:
                if parent.name in bones_with_mesh:
                    return parent.name
                parent = parent.parent
            return None

    for node in shape_nodes:
        name = node["name"]
        obj_name = name + "_ref"

        if settings.import_mode == "ATTACH_EXISTING" and obj_name in existing_ref_names_before:
            # Já existia antes desta chamada de import -- não duplica.
            continue

        shape = node["shape"]
        shape_type = shape.get("type")

        size_raw = vec3(shape.get("settings", {}).get("size", {"x": 1, "y": 1, "z": 1}), default=1.0)
        size_scaled = size_raw * settings.unit_scale
        offset = vec3(shape.get("offset", {})) * settings.unit_scale
        stretch = vec3(shape.get("stretch", {"x": 1, "y": 1, "z": 1}), default=1.0)

        if shape_type == "box":
            mesh = make_box_mesh(
                name, size_scaled, size_raw, shape, atlas_w, atlas_h, settings.generate_uvs, settings.missing_face_mode
            )
        else:  # "quad"
            mesh = make_quad_mesh(name, shape, size_scaled, size_raw, atlas_w, atlas_h, settings.generate_uvs)

        obj = bpy.data.objects.new(obj_name, mesh)

        # Sub-collection pro bone dono desta malha (nome = "{bone} -
        # {armature}", mesmo padrão de "Main - X"/"Rig - X" -- ver
        # resolve_mesh_bone_collection sobre por que o sufixo do
        # personagem é obrigatório), aninhada (ou não -- ver
        # flat_mesh_collections/ancestor_fn acima) dentro de
        # boxes_collection (Main/Mesh Attachments) -- só criada aqui
        # (nunca antecipada) porque é exatamente aqui que sabemos que
        # existe uma malha de verdade pra colocar dentro.
        bone_name = node_id_to_bone_name[id(node)]
        mesh_collection = resolve_mesh_bone_collection(
            bone_collection_cache, boxes_collection, armature_obj.name, bone_name, ancestor_fn
        )
        mesh_collection.objects.link(obj)

        if material is not None:
            obj.data.materials.append(material)

        node_world = world_matrices[id(node)]
        local_offset_scale = Matrix.Translation(offset) @ Matrix.Diagonal(
            (stretch.x, stretch.y, stretch.z, 1.0)
        )
        # IMPORTANTE: node_world está no espaço LOCAL do Armature (matriz do
        # edit-bone), não no espaço de mundo. No modo "Create New Armature"
        # isso não dava problema porque a rotação Z-up só é aplicada DEPOIS
        # de posicionar as malhas (armature_obj.matrix_world ainda era
        # identidade nesse ponto). Mas no modo "Attach to Existing", o
        # Armature alvo JÁ pode estar rotacionado (ex: o Player, com
        # orient_z_up aplicado antes) -- por isso precisa multiplicar por
        # armature_obj.matrix_world aqui também, senão a malha nasce no
        # espaço "deitado" (sem a rotação) e só a bone em si aparece certa
        # (bones herdam a rotação do objeto automaticamente na exibição,
        # mas objetos de malha avulsos como esse não).
        desired_world = armature_obj.matrix_world @ node_world @ local_offset_scale

        # Antes: a mesh ficava presa RIGIDAMENTE a um único bone via
        # constraint "Child Of" -- simples e correto pra visual estático,
        # mas não permite pintura de peso (weight painting) nem deform
        # suave entre bones, o que é necessário pra animar de verdade
        # (torções, blends de cotovelo/joelho etc.) fora do Blockbench.
        #
        # Agora: parent real no objeto Armature + modifier "Armature" +
        # um Vertex Group nomeado EXATAMENTE como o bone (bone_name -- já
        # é o nome FINAL do bone no Blender, pós-dedup, o mesmo usado
        # antes como subtarget da constraint), com peso 1.0 em TODOS os
        # vértices da mesh. O .blockymodel não descreve nenhum peso por
        # vértice -- então "100% nesse bone" é o único valor que faz
        # sentido inferir, e reproduz exatamente o mesmo visual rígido de
        # antes na bind pose. A diferença é que agora o usuário pode
        # repintar manualmente os pesos depois (ex: fazer uma manga
        # deformar suavemente entre Shoulder e Elbow), sem precisar
        # desfazer/trocar o esquema de anexo.
        #
        # obj.parent (em vez de só o modifier) garante que a mesh também
        # acompanhe transformações do OBJETO Armature como um todo (ex: a
        # rotação "Orient to Z-up", aplicada depois, mais abaixo em
        # execute()) -- mesmo comportamento que a constraint Child Of já
        # dava antes, mas agora via parenting de verdade.
        obj.parent = armature_obj
        obj.matrix_world = desired_world

        vgroup = obj.vertex_groups.new(name=bone_name)
        vgroup.add(range(len(mesh.vertices)), 1.0, "REPLACE")

        armature_mod = obj.modifiers.new(name="Armature", type="ARMATURE")
        armature_mod.object = armature_obj


def derive_default_name(filepath):
    """Nome padrão pra Armature/Collection quando o usuário não digitou um
    manualmente: o nome do arquivo, sem extensão. NÃO é confiável pra
    identificar o personagem de verdade -- o .blockymodel não guarda
    nenhum campo tipo "characterName" (só nomes de bones/peças) --, então
    isso é só um fallback razoável, não uma detecção de verdade. Ex:
    "Model.blockymodel" vira "Model", mesmo que o personagem seja outra
    coisa (ex: um boss) -- nesses casos, prefira digitar o nome manualmente."""
    base = os.path.basename(filepath)
    if base.lower().endswith(".blockymodel"):
        base = base[: -len(".blockymodel")]
    return base or "Hytale_Rig"


def resolve_blockymodel_format(choice, data, filepath, attach_armature=None):
    """Resolve Character/Prop pra um .blockymodel. Ordem (mesma do plugin
    oficial, hytale-blockbench-plugin src/blockymodel.ts load()):
      1) escolha manual (choice != AUTO);
      2) campo "format" na raiz do arquivo;
      3) [só Attach] formato já gravado na Armature alvo -- um attachment
         sem "format" herda do corpo onde vai ser encaixado;
      4) arquivo dentro de uma pasta "Blocks" -> prop;
      5) character."""
    if choice != "AUTO":
        return MODEL_FORMAT_PROP if choice == "PROP" else MODEL_FORMAT_CHARACTER
    if data.get("format"):
        return normalize_model_format(data["format"])
    if attach_armature is not None and ARMATURE_MODEL_FORMAT_PROP in attach_armature:
        return armature_model_format(attach_armature)
    segments = re.split(r"[\\/]", os.path.normpath(filepath))
    if "Blocks" in segments[:-1]:
        return MODEL_FORMAT_PROP
    return MODEL_FORMAT_CHARACTER


class _ScaledSettings:
    """Proxy do operador passado como `settings` pras funções de
    construção (build_bones_recursive, add_reference_visuals...), com
    `unit_scale` trocado pela escala EFETIVA do formato. Não dá pra só
    reatribuir self.unit_scale no execute(): o Blender lembra o último
    valor de property de operador, e o próximo import de personagem
    herdaria a escala de prop."""

    def __init__(self, operator, unit_scale):
        object.__setattr__(self, "_operator", operator)
        object.__setattr__(self, "unit_scale", unit_scale)

    def __getattr__(self, name):
        return getattr(self._operator, name)

    def __setattr__(self, name, value):
        setattr(self._operator, name, value)


def _blockymodel_import_props(lang):
    return {
        **import_option_props(lang, "blockymodel", (
            "armature_name", "orient_z_up", "unit_scale", "generate_reference_boxes", "flat_mesh_collections",
            "generate_uvs", "create_material", "texture_mode", "texture_filepath",
        )),
        "model_format": model_format_enum(lang, "blockymodel"),
        "filter_glob": StringProperty(default="*.blockymodel", options={"HIDDEN"}),
        "import_mode": EnumProperty(
            name="Import Mode",
            description=tr("importer.prop.blockymodel_import_mode", lang),
            items=[
                (
                    "NEW_ARMATURE",
                    "Create New Armature",
                    tr("importer.prop.blockymodel_import_mode_item_new", lang),
                ),
                (
                    "ATTACH_EXISTING",
                    "Attach to Existing Armature",
                    tr("importer.prop.blockymodel_import_mode_item_attach", lang),
                ),
            ],
            default="NEW_ARMATURE",
        ),
        "target_armature_name": StringProperty(
            name="Target Armature",
            description=tr("importer.prop.blockymodel_target_armature_name", lang),
            default="",
        ),
        "missing_face_mode": EnumProperty(
            name="Faces Missing Texture Data",
            description=tr("importer.prop.blockymodel_missing_face_mode", lang),
            items=[
                (
                    "SKIP",
                    "Skip (leave empty) -- matches Blockbench",
                    tr("importer.prop.blockymodel_missing_face_mode_item_skip", lang),
                ),
                (
                    "OPPOSITE_FALLBACK",
                    "Reuse Opposite Face's Texture (cosmetic)",
                    tr("importer.prop.blockymodel_missing_face_mode_item_opposite", lang),
                ),
            ],
            default="SKIP",
        ),
        "override_atlas_size": BoolProperty(
            name="Set Atlas Size Manually",
            description=tr("importer.prop.blockymodel_override_atlas_size", lang),
            default=False,
        ),
        "atlas_width": FloatProperty(
            name="Atlas Width (px)",
            description=tr("importer.prop.blockymodel_atlas_width", lang),
            default=256.0,
            min=1.0,
        ),
        "atlas_height": FloatProperty(
            name="Atlas Height (px)",
            description=tr("importer.prop.blockymodel_atlas_height", lang),
            default=128.0,
            min=1.0,
        ),
    }


@localized_props(_blockymodel_import_props)
class IMPORT_OT_hytale_blockymodel(Operator, ImportHelper):
    """Import a Hytale .blockymodel as an Armature (correct rest pose)"""

    bl_idname = "import_scene.hytale_blockymodel"
    bl_label = "Import .blockymodel"
    description = tooltip("importer.tooltip.blockymodel")
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".blockymodel"

    def draw(self, context):
        lang = get_language(context)
        layout = self.layout

        target_box = layout.box()
        target_box.label(text=tr("importer.section_target", lang))
        target_box.prop(self, "import_mode", text=tr("importer.import_mode", lang))
        if self.import_mode == "ATTACH_EXISTING":
            target_box.prop_search(
                self, "target_armature_name", bpy.data, "objects", text=tr("importer.target_armature", lang)
            )
        else:
            target_box.prop(self, "armature_name", text=tr("importer.armature_name", lang))

        draw_rig_section(layout, self, lang, orient_enabled=self.import_mode == "NEW_ARMATURE")
        sub = draw_mesh_section(layout, self, lang)

        atlas_sub = sub.column()
        atlas_sub.enabled = self.generate_uvs
        atlas_sub.prop(self, "missing_face_mode", text=tr("importer.missing_face_mode", lang))
        atlas_sub.prop(self, "override_atlas_size", text=tr("importer.override_atlas_size", lang))
        atlas_row = atlas_sub.row()
        atlas_row.enabled = self.override_atlas_size
        atlas_row.prop(self, "atlas_width", text=tr("importer.atlas_width", lang))
        atlas_row.prop(self, "atlas_height", text=tr("importer.atlas_height", lang))

        draw_texture_options(sub, self, lang)

    def execute(self, context):
        with open(self.filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        root_nodes = data.get("nodes", [])
        if not root_nodes:
            self.report({"ERROR"}, "No nodes found in the file (.blockymodel is empty or invalid).")
            return {"CANCELLED"}

        # Nome do arquivo sem extensão (ex: "Eyes.blockymodel" -> "Eyes"),
        # usado como prefixo do bone "wrapper" quando um attachment é
        # anexado dentro de um bone que já existe -- ver a nota grande em
        # build_bones_recursive sobre por que isso reproduz o comportamento
        # do Blockbench oficial ("Eyes:L-Eye-Attachment").
        self.attachment_stem = os.path.splitext(os.path.basename(self.filepath))[0]

        if self.import_mode == "ATTACH_EXISTING":
            armature_obj = bpy.data.objects.get(self.target_armature_name)
            if armature_obj is None:
                self.report({"ERROR"}, f"No object named '{self.target_armature_name}' found in this file.")
                return {"CANCELLED"}
            if armature_obj.type != "ARMATURE":
                self.report({"ERROR"}, f"'{self.target_armature_name}' is not an Armature.")
                return {"CANCELLED"}
            armature_data = armature_obj.data
            # Nomes que já existiam ANTES desta chamada -- só esses podem
            # ser reaproveitados (ver build_bones_recursive). Se o PRÓPRIO
            # arquivo tiver nomes duplicados entre si, o segundo não está
            # aqui e vira um bone novo de verdade, não uma fusão incorreta.
            reusable_bone_names = set(armature_data.bones.keys())

            target_collection, used_fallback_collection = find_attachments_collection(context, armature_obj)
            if used_fallback_collection:
                self.report(
                    {"WARNING"},
                    f"'{armature_obj.name}' didn't have Mesh Attachments collection info (older import?) "
                    f"-- created '{target_collection.name}' as a fallback.",
                )
        else:
            resolved_name = self.armature_name.strip() or derive_default_name(self.filepath)
            armature_data = bpy.data.armatures.new(resolved_name)
            armature_obj = bpy.data.objects.new(resolved_name, armature_data)
            rig_collection, main_collection, attachments_collection = build_character_collections(
                context, armature_obj.name
            )
            rig_collection.objects.link(armature_obj)
            armature_obj["hytale_meshes_main_collection"] = main_collection.name
            armature_obj["hytale_meshes_attachments_collection"] = attachments_collection.name
            target_collection = main_collection
            reusable_bone_names = set()

        # Character (64/bloco) vs Prop (32/bloco) -- ver MODEL_FORMAT_* em
        # common.py. `settings` substitui `self` nas chamadas de construção
        # abaixo só pra levar a escala efetiva (ver _ScaledSettings).
        attach_target = armature_obj if self.import_mode == "ATTACH_EXISTING" else None
        model_format = resolve_blockymodel_format(self.model_format, data, self.filepath, attach_target)
        if attach_target is not None:
            target_format = armature_model_format(attach_target)
            if model_format != target_format:
                self.report(
                    {"WARNING"},
                    f"'{os.path.basename(self.filepath)}' is a {model_format} model but "
                    f"'{attach_target.name}' is a {target_format} -- the attachment will not match in scale.",
                )
        else:
            armature_obj[ARMATURE_MODEL_FORMAT_PROP] = model_format
        scale = effective_unit_scale(self.unit_scale, model_format)
        settings = _ScaledSettings(self, scale)

        context.view_layer.objects.active = armature_obj
        armature_obj.select_set(True)

        # IMPORTANTE: "X-Axis Mirror" (armature_data.use_mirror_x) tenta
        # sincronizar automaticamente bones cujo nome bate com um padrao
        # de espelhamento reconhecido pelo Blender (ex: prefixo "R-"/"L-").
        # Isso e o que causava attachments do lado R irem pro centro do
        # mundo: no JSON, o node R vem ANTES do L -- entao quando o bone R
        # e criado (commitado no Edit->Object), o par "L" espelhado ainda
        # nao existe, e o Blender reseta a posicao dele. Confirmado com
        # reproducao minima isolada (o bug so aparece com use_mirror_x=True,
        # e so no lado processado primeiro). Desligamos aqui e restauramos
        # no final, pra nao mudar a preferencia de edicao do usuario.
        original_use_mirror_x = armature_data.use_mirror_x
        if original_use_mirror_x:
            armature_data.use_mirror_x = False

        bpy.ops.object.mode_set(mode="EDIT")
        world_matrices = {}
        node_id_to_bone_name = {}
        try:
            for root_node in root_nodes:
                build_bones_recursive(
                    armature_data,
                    root_node,
                    None,
                    Matrix.Identity(4),
                    Vector((0.0, 0.0, 0.0)),
                    world_matrices,
                    node_id_to_bone_name,
                    reusable_bone_names,
                    settings,
                )
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
            # Restaura a preferencia original de X-Axis Mirror do usuario
            # (ver nota grande acima, onde desligamos antes de entrar em
            # Edit Mode) -- so mexemos nela pra evitar o bug do commit, nao
            # pra mudar a preferencia de edicao do usuario a longo prazo.
            # Fica num "finally" pra restaurar mesmo se o import falhar no
            # meio do caminho.
            if original_use_mirror_x:
                armature_data.use_mirror_x = original_use_mirror_x

        if self.generate_reference_boxes:
            if self.override_atlas_size:
                atlas_w, atlas_h = self.atlas_width, self.atlas_height
            else:
                atlas_w, atlas_h = compute_atlas_size(root_nodes)

            resolved_texture_filepaths = []
            if self.create_material:
                model_name = derive_default_name(self.filepath)
                resolved_texture_filepaths, tier = resolve_texture_filepaths(
                    self.filepath, self.texture_mode, self.texture_filepath, model_name
                )
                texture_report = texture_result_report(
                    self.texture_mode, tier, resolved_texture_filepaths, model_name
                )
                if texture_report:
                    self.report({texture_report[0]}, texture_report[1])

            add_reference_visuals(
                armature_obj,
                root_nodes,
                world_matrices,
                node_id_to_bone_name,
                settings,
                atlas_w,
                atlas_h,
                target_collection,
                resolved_texture_filepaths,
            )

        if self.import_mode == "NEW_ARMATURE" and self.orient_z_up:
            armature_obj.rotation_euler = Euler((math.radians(90.0), 0.0, 0.0), "XYZ")

        context.view_layer.update()

        root_names = ", ".join(r.get("name", "?") for r in root_nodes)
        mode_desc = f"attached to '{armature_obj.name}'" if self.import_mode == "ATTACH_EXISTING" else f"as '{armature_obj.name}'"
        self.report(
            {"INFO"},
            f"Imported {len(node_id_to_bone_name)} node(s) from '{root_names}' {mode_desc} "
            f"({model_format}, scale={scale:.5f}).",
        )
        return {"FINISHED"}
