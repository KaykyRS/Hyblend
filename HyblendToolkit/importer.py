# ---------------------------------------------------------------------------
# Este arquivo é o submódulo IMPORTER do pacote HyblendToolkit.
# Metadados do addon (nome, versão, versão mínima do Blender, descrição)
# NÃO vivem mais aqui como `bl_info` -- vivem em blender_manifest.toml, na
# raiz do pacote (formato de Extension do Blender 4.5+, ver
# blender_manifest.toml pra fonte da verdade). Se você só recebeu ESTE
# arquivo pra atualizar, não precisa se preocupar com o manifest a menos
# que a mudança exija subir a versão -- ver DEVELOPER_NOTES.md.
# ---------------------------------------------------------------------------

import base64
import json
import math
import os
import tempfile

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import AddonPreferences, Operator
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler, Matrix, Vector

from .common import (
    ADDON_PACKAGE,
    BONE_ORIGINAL_NAME_PROP,
    BONE_SHAPE_OFFSET_PROP,
    UNIT_SCALE_DEFAULT,
    quat_xyzw,
    vec3,
)
from .translations import get_language, get_language_items, tr

# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------
#
# O dicionário de textos (LABELS/L) e o get_language() que moravam aqui
# viraram o pacote translations/ (idiomas plugáveis, um arquivo .py por
# idioma -- ver translations/__init__.py e translations/en.py pra
# detalhes). Este arquivo só chama tr("importer.<key>", lang) agora, do
# mesmo jeito que antes chamava L("<key>", lang) -- só o prefixo
# "importer." nas keys mudou, pra não colidir com as keys de
# interface.py (prefixo "panel.") dentro do mesmo dicionário compartilhado.
#
# Continua valendo a limitação de antes: o tooltip (hover) de um
# bpy.props.*Property (parâmetro description=) fica fixo em Inglês,
# porque o Blender resolve esse texto no registro da classe, não a cada
# redraw -- ver a nota grande sobre isso em translations/__init__.py.


class HytaleImporterPreferences(AddonPreferences):
    # Tem que ser o nome do PACOTE raiz (ver common.ADDON_PACKAGE), não
    # __name__ deste submódulo -- senão o Blender não acha essas
    # preferences em context.preferences.addons[...].
    bl_idname = ADDON_PACKAGE

    # items=get_language_items é uma FUNÇÃO (callback), não uma lista fixa
    # -- é o que permite qualquer arquivo novo dentro de translations/
    # aparecer aqui sem precisar editar este arquivo. Efeito colateral:
    # EnumProperty com items dinâmico não aceita default= (o Blender não
    # tem como saber o valor default antes de rodar o callback) -- por
    # isso não tem default= aqui; get_language() (translations/__init__.py)
    # já cai pro Inglês sozinho caso o valor salvo seja inválido/vazio.
    language: EnumProperty(
        name="Language / Idioma",
        description="Language used for labels in the panel and import dialogs (tooltips stay in English)",
        items=get_language_items,
    )

    def draw(self, context):
        lang = get_language(context)
        row = self.layout.row(align=True)
        row.prop(self, "language", text=tr("importer.prefs_language", lang))
        row.operator(
            "hytale.reload_translations",
            text=tr("importer.prefs_reload_translations", lang),
            icon="FILE_REFRESH",
        )


# ---------------------------------------------------------------------------
# Utilidades de conversão do JSON do .blockymodel / .blockymodel JSON helpers
# ---------------------------------------------------------------------------
#
# Cada nó do .blockymodel guarda "position" (translação) e "orientation"
# (quaternion x,y,z,w) RELATIVOS ao pai. A matriz de mundo de um nó é:
#
#   mundo(nó) = mundo(pai) @ Translacao(position) @ Rotacao(orientation)
#
# CONFIRMADO NUMERICAMENTE (contra .gltf exportado pelo Blockbench, 55/55
# nós batendo exatos, incluindo pernas/braços com rotação própria):
#
# 1) ESCALA: dividimos por 64 (UNIT_SCALE_DEFAULT) tudo que for uma medida
#    de comprimento (position, shape.offset, shape.settings.size), porque
#    o exportador de animação (Export_blockyanim.py, de Edrax) multiplica
#    por 64 ao gravar. "stretch" NÃO é escalado, é um fator adimensional.
#
# 2) TRANSLAÇÃO LOCAL = position(nó) + shape.offset(PAI). O próximo bone
#    começa de onde a caixa visual do pai termina, não de onde o pivô
#    abstrato do pai está. A rotação continua sendo aplicada normalmente
#    por cima via composição de matriz -- não é uma soma "pura" fora da
#    cadeia de rotação.
#
# 3) Quaternion (orientation): copiar x,y,z,w direto, sem inversão de sinal
#    ou permutação de eixo. Handedness testado e confirmado -- não precisa
#    reabrir essa questão (a antiga opção "mirror_axis" foi removida).

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


BONE_DISPLAY_LENGTH_GAME_UNITS = 4.0  # puramente estético, escalado igual ao resto

# Nota: BONE_SHAPE_OFFSET_PROP (nome da propriedade customizada usada para
# gravar, em CADA bone, o shape.offset já escalado que ele tinha no arquivo
# em que foi criado) agora vem de common.py -- ver o motivo lá. A lógica de
# uso dela (por que isso é necessário para anexar attachments, cabelo etc.
# corretamente, comparado com parseNode() do plugin oficial de Blockbench,
# JannisX11/hytale-blockbench-plugin) continua documentada dentro de
# build_bones_recursive, abaixo.


# ---------------------------------------------------------------------------
# Construção do Armature
# ---------------------------------------------------------------------------


def unique_bone_name(base_name, edit_bones):
    """Se `base_name` já existe em `edit_bones`, gera um nome novo e único
    usando um sufixo PRÓPRIO (".dupNN"), em vez de deixar o Blender resolver
    a colisão sozinho com ".001".

    Por que não usar o ".001" automático do Blender: o exporter precisaria
    então adivinhar/parsear esse sufixo pra saber o nome original a gravar,
    e ".001" não é um marcador confiável (nada impede um nome de arquivo de
    legitimamente terminar assim). Em vez disso, o nome original de
    verdade é guardado à parte, na custom property BONE_ORIGINAL_NAME_PROP
    (ver common.py) -- é ela, não este sufixo, que o exporter deve usar.
    Este sufixo aqui é só pra existir como nome único dentro do Blender."""
    if base_name not in edit_bones:
        return base_name
    n = 1
    while True:
        candidate = f"{base_name}.dup{n:02d}"
        if candidate not in edit_bones:
            return candidate
        n += 1


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
            wrapper_name = f"{attachment_stem}:{name}"
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


# ---------------------------------------------------------------------------
# Texture layout / UVs
# ---------------------------------------------------------------------------
#
# O .blockymodel guarda, por face de cada shape "box" (front/back/left/
# right/top/bottom) ou "quad" (normalmente só "front"), um "textureLayout"
# com offset em PIXELS dentro de um atlas de textura, mais mirror/angle.
# O tamanho do atlas (largura/altura totais em pixels) NÃO é guardado no
# arquivo -- então inferimos como o maior canto (offset + tamanho da face)
# usado por qualquer shape do modelo. É uma heurística: se estiver errada,
# só desalinha a escala do UV (a topologia/posição relativa continua
# certa), fácil de corrigir depois de importar a textura real.
#
# Cada face de uma box usa dois dos três eixos locais como "largura" e
# "altura" da textura (o terceiro eixo é o que fica fixo naquela face):
#   front/back (eixo fixo Z): largura = size.x, altura = size.y
#   top/bottom (eixo fixo Y): largura = size.x, altura = size.z
#   left/right (eixo fixo X): largura = size.z, altura = size.y
# Para "quad", o eixo fixo é o indicado por settings.normal.

FACE_AXES_BY_FIXED_AXIS = {
    "z": (0, 1),  # (axis_u, axis_v) = (x, y) -> front/back
    "y": (0, 2),  # (x, z) -> top/bottom
    "x": (2, 1),  # (z, y) -> left/right
}

BOX_FACE_FIXED_AXIS = {
    "front": "z",
    "back": "z",
    "top": "y",
    "bottom": "y",
    "left": "x",
    "right": "x",
}

BOX_FACES_LOOP_ORDER = [
    ("back", (0, 1, 2, 3)),
    ("front", (4, 7, 6, 5)),
    ("bottom", (0, 4, 5, 1)),
    ("right", (1, 5, 6, 2)),
    ("top", (2, 6, 7, 3)),
    ("left", (3, 7, 4, 0)),
]

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


# Sinal "base" (s,t -> pixel), SEM nenhuma rotação/espelho, de cada face.
#
# Descoberto por engenharia reversa numérica contra o Player_With_Face.gltf
# exportado pelo Blockbench (fonte da verdade): extraímos a posição de cada
# vértice + sua UV real do .gltf, casamos cada face com o offset/mirror/angle
# correspondente do .blockymodel, e resolvemos qual sinal cada eixo (s e t)
# precisa ter para reproduzir esses pixels. Validado contra as 64 faces
# "limpas" do arquivo (21 shapes, excluindo os ossos "L-*" cujo bone tem
# escala espelhada e por isso não servem de referência direta) -- 0
# divergências.
#
# 'back' e 'right' têm o eixo s invertido em relação a 'front'/'left' porque
# é assim que o Blockbench desenrola a caixa (cross-unwrap clássico estilo
# Minecraft) -- não é uma rotação, é a orientação nativa dessas duas faces.
# 'top' é a única face cujo eixo t NÃO é invertido.
BOX_FACE_BASE_SIGN = {
    "back": (-1, -1),
    "right": (-1, -1),
    "front": (+1, -1),
    "left": (+1, -1),
    "top": (+1, +1),
    "bottom": (+1, -1),
}


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


def discover_texture_paths(dirname, model_name):
    """Espelha discoverTexturePaths() do plugin oficial do Hytale pro
    Blockbench (src/blockymodel.ts) -- MESMA convenção, MESMA ordem de
    busca, confirmada lendo o código-fonte de verdade (não é uma tentativa
    nossa de adivinhar):
      1) Mesma pasta do .blockymodel: qualquer .png cujo nome COMEÇA com
         o nome do modelo (sem extensão), ou literalmente "Texture.png".
      2) Uma subpasta "{NomeDoModelo}_Textures/" com PNGs dentro.
    Devolve uma lista de caminhos absolutos (pode ter mais de um -- pastas
    de textura da Hytale costumam ter VARIANTES do mesmo personagem;
    carregamos TODAS as achadas, conectando só a preferida no material --
    ver resolve_texture_filepaths, logo abaixo)."""
    paths = []
    if not dirname or not os.path.isdir(dirname):
        return paths

    try:
        dir_entries = sorted(os.listdir(dirname))
    except OSError:
        dir_entries = []
    for fname in dir_entries:
        if fname.lower().endswith(".png") and (fname.startswith(model_name) or fname == "Texture.png"):
            paths.append(os.path.join(dirname, fname))

    textures_folder = os.path.join(dirname, f"{model_name}_Textures")
    if os.path.isdir(textures_folder):
        try:
            folder_entries = sorted(os.listdir(textures_folder))
        except OSError:
            folder_entries = []
        for fname in folder_entries:
            if fname.lower().endswith(".png"):
                paths.append(os.path.join(textures_folder, fname))

    # Remove duplicatas mantendo a ordem (dict preserva ordem de inserção
    # desde Python 3.7 -- mesmo efeito do "[...new Set(paths)]" do original).
    return list(dict.fromkeys(paths))


def discover_texture_paths_loose_fallback(dirname, model_name):
    """EXTRA nossa -- NÃO existe no plugin oficial (esse só teria mostrado
    o popup "No textures found" nesse caso). A convenção oficial exige que
    o nome da pasta/arquivo COMECE com o nome exato do .blockymodel -- mas
    isso falha em casos reais como "Player_With_Face.blockymodel" cuja
    textura mora em "Player_Textures/" (a Hypixel usa uma pasta
    compartilhada pra toda a família "Player", não por variante).

    Fallback: se a busca estrita (discover_texture_paths) não achou nada,
    procura qualquer pasta IRMÃ terminando em "_Textures" (nome ANTES do
    sufixo, ignorado -- só o sufixo importa aqui) e só usa se achar
    EXATAMENTE UMA -- múltiplas pastas candidatas é sinal de ambiguidade
    real, e nesse caso preferimos não adivinhar (cai no placeholder, igual
    sempre foi)."""
    paths = []
    if not dirname or not os.path.isdir(dirname):
        return paths

    try:
        sibling_entries = os.listdir(dirname)
    except OSError:
        return paths

    textures_folders = [
        os.path.join(dirname, entry)
        for entry in sibling_entries
        if entry.endswith("_Textures") and os.path.isdir(os.path.join(dirname, entry))
    ]
    if len(textures_folders) != 1:
        return paths

    try:
        folder_entries = sorted(os.listdir(textures_folders[0]))
    except OSError:
        folder_entries = []
    for fname in folder_entries:
        if fname.lower().endswith(".png"):
            paths.append(os.path.join(textures_folders[0], fname))
    return paths


def resolve_texture_filepaths(blockymodel_filepath, texture_mode, manual_path):
    """Decide QUAIS arquivos de textura carregar, de acordo com
    `texture_mode` (property "Texture Mode" do operator -- "AUTO" ou
    "MANUAL", explícito, não mais inferido de `manual_path` estar vazio
    ou não):
      - "MANUAL": usa `manual_path` (se vazio, não carrega textura nenhuma
        -- cai no placeholder cinza -- e NÃO tenta auto-descoberta, mesmo
        que ela achasse algo; é uma escolha explícita do usuário).
      - "AUTO": ignora `manual_path` completamente, corre atrás da
        descoberta automática (ver discover_texture_paths) e devolve
        TODOS os candidatos achados na mesma pasta/subpasta -- não só um
        -- porque pastas de textura da Hytale costumam ter VARIANTES do
        mesmo personagem (ex: Player_Greyscale.png,
        Player_Muscular_Greyscale.png, Outlander_1.png, todas na mesma
        "Player_Textures/"). Quem chama (ver get_or_create_material)
        carrega todas num bpy.data.images e empilha as extras como nodes
        soltos no material -- só conecta a PRIMEIRA da lista no shader.

    A lista devolvida vem com o candidato PREFERIDO (nome que começa com o
    nome do MODELO -- mesma preferência de loadTexturesFromPaths() no
    plugin oficial) na FRENTE, seguido dos outros na ordem que apareceram.
    Se a busca ESTRITA (fiel ao plugin oficial) não achar nada, tenta o
    fallback mais frouxo (ver discover_texture_paths_loose_fallback) antes
    de desistir.

    Devolve (lista_de_caminhos, camada), onde camada é "MANUAL", "STRICT"
    (achou pela convenção oficial), "LOOSE" (só achou pelo fallback extra
    nosso) ou "NONE" (nada encontrado -- cai no placeholder cinza, como
    sempre)."""
    if texture_mode == "MANUAL":
        manual_path = clean_texture_path(manual_path)
        if manual_path:
            return [manual_path], "MANUAL"
        return [], "NONE"

    dirname = os.path.dirname(blockymodel_filepath)
    model_name = derive_default_name(blockymodel_filepath)

    candidates = discover_texture_paths(dirname, model_name)
    tier = "STRICT"
    if not candidates:
        candidates = discover_texture_paths_loose_fallback(dirname, model_name)
        tier = "LOOSE"
    if not candidates:
        return [], "NONE"

    preferred = next(
        (p for p in candidates if os.path.splitext(os.path.basename(p))[0].startswith(model_name)),
        None,
    )
    if preferred and preferred in candidates:
        ordered = [preferred] + [p for p in candidates if p != preferred]
    else:
        ordered = candidates
    return ordered, tier


def clean_texture_path(path):
    """Remove aspas (simples ou duplas) e espaços nas pontas do caminho.
    Colar um caminho copiado do Explorer do Windows (Shift+Copiar como
    caminho) normalmente vem cercado de aspas duplas -- sem isso,
    bpy.data.images.load() falha silenciosamente (RuntimeError) e cai no
    placeholder cinza."""
    if not path:
        return path
    path = path.strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in ("\"", "'"):
        path = path[1:-1].strip()
    return path


def build_flat_material_from_image(image, material_name="Hytale_Material"):
    """Monta o material "flat" (Image Texture -> Base Color + Alpha, sem
    PBR) a partir de uma bpy.data.images já existente. Extraído de
    get_or_create_material pra ser reaproveitado também pelo import de
    .bbmodel (que decodifica a textura de um base64 embutido em vez de
    carregar de um caminho de arquivo -- ver decode_bbmodel_texture) sem
    duplicar a montagem do shader. Devolve (material, tex_node) -- o
    tex_node é devolvido pra quem chama poder posicionar nodes extras
    (ex: variantes de textura não conectadas) relativos a ele -- ver
    get_or_create_material."""
    mat = bpy.data.materials.new(name=material_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)

    tex_node = nodes.new("ShaderNodeTexImage")
    tex_node.image = image
    tex_node.interpolation = "Closest"  # sem blur -- textura pixel art
    tex_node.location = (bsdf.location.x - 300 if bsdf else -300, bsdf.location.y if bsdf else 0)

    if bsdf is not None:
        links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        if "Alpha" in bsdf.inputs:
            links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 1.0  # visual flat, sem highlight de PBR

    # Sem isso, o node Alpha fica conectado mas o material continua opaco
    # na viewport/render (EEVEE só respeita alpha se o blend_method permitir).
    # "HASHED" evita os problemas de ordenação de "BLEND" e lida bem com
    # transparência binária (cabelo, folhas etc) típica de pixel art.
    if hasattr(mat, "blend_method"):
        mat.blend_method = "HASHED"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "HASHED"

    return mat, tex_node


def get_or_create_material(atlas_w, atlas_h, texture_filepaths=None):
    """Cria um material único, com uma Image Texture -> Base Color + Alpha.
    O Hytale/Blockbench só guarda UMA textura flat por modelo (sem PBR, sem
    normal/roughness maps), então o material espelha isso: só Base Color +
    Alpha (a maioria das peças -- cabelo, roupas, etc -- depende de
    transparência real, não só de Base Color).

    `texture_filepaths` é uma LISTA (pode ter mais de um -- pastas de
    textura da Hytale costumam ter VARIANTES do mesmo personagem, ex:
    Player_Greyscale.png, Player_Muscular_Greyscale.png, Outlander_1.png,
    todas juntas na mesma pasta -- ver resolve_texture_filepaths). TODAS
    são carregadas em bpy.data.images -- a PRIMEIRA da lista vira o node
    de verdade, conectado no Base Color/Alpha; as outras entram como
    nodes Image Texture ADICIONAIS no mesmo material, empilhados
    visualmente ABAIXO do node principal, mas SEM NENHUMA conexão --
    ficam ali só pra você arrastar um link na mão se quiser trocar,
    sem precisar procurar o arquivo de novo nem sair do editor de shader.

    Se nenhum caminho carregar (lista vazia ou todos falharem), cria uma
    imagem em branco (cinza claro) do tamanho de atlas_w/atlas_h, como
    placeholder até você conectar uma textura de verdade.

    Devolve (material, imagem_principal, lista_de_todas_carregadas)."""
    texture_filepaths = texture_filepaths or []
    loaded_images = []
    for filepath in texture_filepaths:
        filepath = clean_texture_path(filepath)
        if not filepath:
            continue
        try:
            img = bpy.data.images.load(filepath, check_existing=True)
        except RuntimeError:
            continue
        loaded_images.append(img)

    if loaded_images:
        primary_image = loaded_images[0]
    else:
        primary_image = bpy.data.images.new(
            "Hytale_Placeholder_Texture",
            width=max(int(atlas_w), 1),
            height=max(int(atlas_h), 1),
            alpha=True,
        )
        primary_image.generated_color = (0.6, 0.6, 0.6, 1.0)

    mat, primary_tex_node = build_flat_material_from_image(primary_image)

    # Nodes de textura têm ~230px de altura por padrão (com o preview de
    # imagem aberto) -- 260 dá uma folguinha visual entre um e outro sem
    # ficarem colados.
    NODE_STACK_OFFSET_Y = 260
    for i, extra_image in enumerate(loaded_images[1:], start=1):
        extra_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        extra_node.image = extra_image
        extra_node.interpolation = "Closest"
        extra_node.label = extra_image.name
        extra_node.location = (
            primary_tex_node.location.x,
            primary_tex_node.location.y - NODE_STACK_OFFSET_Y * i,
        )

    return mat, primary_image, loaded_images


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
):
    """Percorre uma lista de filhos do outliner (mistura de dict = group e
    string = uuid de element) e constrói bones (groups) + meshes
    (elements), recursivamente. `ancestor_pivot_matrix` e
    `ancestor_rotation_matrix` -- ver a nota grande no topo desta seção
    pra o que cada um representa e por que são acumuladores SEPARADOS."""
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


def get_or_create_child_collection(parent_collection, name):
    """Reaproveita a child collection com esse nome exato dentro de
    `parent_collection` se já existir (comparação percorrendo os filhos
    diretos, não bpy.data.collections global -- duas collections podem
    ter nomes parecidos em partes diferentes da cena); senão cria e
    linka como filha de `parent_collection`."""
    for child in parent_collection.children:
        if child.name == name:
            return child
    new_coll = bpy.data.collections.new(name)
    parent_collection.children.link(new_coll)
    return new_coll


def build_character_collections(context, armature_name):
    """Monta (pro modo NEW_ARMATURE) a estrutura de collections do
    personagem:

        <armature_name>                                 (collection "pai")
        ├── Rig - <armature_name>                        (o Armature entra aqui)
        └── Meshes - <armature_name>
            ├── Main - <armature_name>                    (meshes do arquivo principal)
            └── Mesh Attachments - <armature_name>          (meshes de "Attach to Existing")

    Devolve (rig_collection, main_collection, attachments_collection).

    O sufixo "- <armature_name>" em TODA sub-collection é pedido
    explícito do usuário: sem ele, importar mais de um personagem faria
    o Blender empilhar ".001"/".002" em cima de nomes genéricos ("Rig",
    "Meshes"...), tornando difícil saber de qual personagem cada
    collection é só de olhar a lista. `armature_name` aqui já é o nome
    FINAL do objeto Armature (depois do Blender já ter resolvido
    qualquer colisão sozinho), pra manter os nomes correlacionados."""
    character_collection = bpy.data.collections.new(armature_name)
    context.scene.collection.children.link(character_collection)

    rig_collection = get_or_create_child_collection(character_collection, f"Rig - {armature_name}")
    meshes_collection = get_or_create_child_collection(character_collection, f"Meshes - {armature_name}")
    main_collection = get_or_create_child_collection(meshes_collection, f"Main - {armature_name}")
    attachments_collection = get_or_create_child_collection(
        meshes_collection, f"Mesh Attachments - {armature_name}"
    )
    return rig_collection, main_collection, attachments_collection


def find_attachments_collection(context, armature_obj):
    """Pro modo ATTACH_EXISTING: acha a collection 'Mesh Attachments -
    <nome>' já associada a essa Armature, guardada como custom property
    na hora em que ela foi criada (hytale_meshes_attachments_collection)
    -- garante que anexar vários attachments ao longo do tempo sempre
    caia na MESMA collection, em vez de criar uma nova a cada import.

    Se a Armature foi criada por uma versão mais antiga do importer (sem
    essa property -- ex: antes desta reorganização de collections),
    cria uma collection de fallback e avisa o chamador (segundo valor
    devolvido = True), linkada na mesma collection de cena onde a
    Armature já está (ou na Scene Collection raiz, se ela não estiver em
    nenhuma)."""
    stored_name = armature_obj.get("hytale_meshes_attachments_collection")
    if stored_name:
        existing = bpy.data.collections.get(stored_name)
        if existing is not None:
            return existing, False

    fallback_name = f"Mesh Attachments - {armature_obj.name}"
    parent = armature_obj.users_collection[0] if armature_obj.users_collection else context.scene.collection
    attachments_collection = get_or_create_child_collection(parent, fallback_name)
    armature_obj["hytale_meshes_attachments_collection"] = attachments_collection.name
    return attachments_collection, True


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
    existing_ref_names_before = set(boxes_collection.objects.keys())

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
        boxes_collection.objects.link(obj)

        if material is not None:
            obj.data.materials.append(material)

        node_world = world_matrices[id(node)]
        bone_name = node_id_to_bone_name[id(node)]
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
    import os

    base = os.path.basename(filepath)
    if base.lower().endswith(".blockymodel"):
        base = base[: -len(".blockymodel")]
    return base or "Hytale_Rig"


# ---------------------------------------------------------------------------
# Operador de import
# ---------------------------------------------------------------------------


class IMPORT_OT_hytale_blockymodel(Operator, ImportHelper):
    """Import a Hytale .blockymodel as an Armature (correct rest pose)"""

    bl_idname = "import_scene.hytale_blockymodel"
    bl_label = "Import .blockymodel"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".blockymodel"
    filter_glob: StringProperty(default="*.blockymodel", options={"HIDDEN"})

    import_mode: EnumProperty(
        name="Import Mode",
        description=(
            "NEW: creates a brand new Armature + reference-mesh collection. "
            "ATTACH: merges this file's bones into an Armature that's already "
            "in the scene (e.g. an attachment/prop file like eyes, meant to "
            "plug into an existing character's attachment-point bones)"
        ),
        items=[
            ("NEW_ARMATURE", "Create New Armature", "Creates a new Armature and reference-mesh collection"),
            (
                "ATTACH_EXISTING",
                "Attach to Existing Armature",
                "Merges into an Armature already in the scene, reusing any bone/mesh that already has a matching name",
            ),
        ],
        default="NEW_ARMATURE",
    )

    target_armature_name: StringProperty(
        name="Target Armature",
        description=(
            "Name of the existing Armature (in this .blend file) to attach "
            "this file's bones to. If a bone with a given name already exists "
            "there, it's reused as-is (NOT recreated/renamed with .001) -- "
            "e.g. an eye-attachment file plugs its bones under the "
            "character's existing 'R-Eye-Attachment' bone instead of "
            "duplicating it. Same for the reference-mesh collection: reused "
            "instead of creating a new one"
        ),
        default="",
    )

    armature_name: StringProperty(
        name="Armature Name",
        description=(
            "Name for the new Armature and its reference-mesh collection. "
            "Leave empty to fall back to the .blockymodel filename -- note "
            "the file itself doesn't store a character/creature name (only "
            "bone/piece names), so for files like 'Model.blockymodel' that "
            "don't match the character's real name (e.g. a boss), type the "
            "name you actually want here"
        ),
        default="",
    )

    generate_reference_boxes: BoolProperty(
        name="Generate Reference Meshes",
        description=(
            "Creates a simple mesh (box or quad) for each visual shape in the "
            "model, parented to the Armature and skinned (100% weight) to its "
            "bone via a Vertex Group + Armature modifier. Useful as a visual "
            "reference while animating, and already deformable/paintable"
        ),
        default=True,
    )

    generate_uvs: BoolProperty(
        name="Generate UVs",
        description=(
            "Generates UV coordinates for the reference meshes from the "
            "model's texture layout data (per-face pixel offsets). The "
            "original texture image size isn't stored in the file, so unless "
            "'Set Atlas Size Manually' is enabled below, the canvas size is "
            "INFERRED from the layout data itself -- this is only a lower "
            "bound (it can come out a few pixels short on width/height if "
            "the real texture has unused padding), so if you know the actual "
            "texture's pixel dimensions, set them manually for an exact match"
        ),
        default=True,
    )

    missing_face_mode: EnumProperty(
        name="Faces Missing Texture Data",
        description=(
            "What to do with a box face that has no entry in the model's "
            "texture layout. CONFIRMED against the official Hytale "
            "Blockbench plugin's own source (blockymodel.ts): a missing "
            "entry ALWAYS means that face had no texture assigned in "
            "Blockbench -- there's no 'implicitly hidden by another piece' "
            "case. So 'Skip' below is the behavior that faithfully matches "
            "Blockbench itself (reloading the file there shows the same "
            "empty face). 'Reuse Opposite Face' is a cosmetic-only override "
            "for when you'd rather see some texture than a hole, even "
            "knowing it doesn't match the source file"
        ),
        items=[
            (
                "SKIP",
                "Skip (leave empty) -- matches Blockbench",
                "Don't create geometry for that face. Faithful to what "
                "Blockbench itself would show -- a missing texture layout "
                "entry always means the face was genuinely untextured",
            ),
            (
                "OPPOSITE_FALLBACK",
                "Reuse Opposite Face's Texture (cosmetic)",
                "Create the face and reuse the texture from the opposite "
                "side of the same box. Does NOT match what Blockbench "
                "itself would show -- purely a visual patch to avoid holes, "
                "can paste the wrong-looking texture onto a visible face",
            ),
        ],
        default="SKIP",
    )

    override_atlas_size: BoolProperty(
        name="Set Atlas Size Manually",
        description=(
            "Use the exact pixel dimensions of your texture file instead of "
            "guessing them from the layout data. Recommended: open your "
            "texture (e.g. in Blockbench or an image viewer) and enter its "
            "width/height here"
        ),
        default=False,
    )

    atlas_width: FloatProperty(
        name="Atlas Width (px)",
        description="Exact width, in pixels, of the texture atlas image",
        default=256.0,
        min=1.0,
    )

    atlas_height: FloatProperty(
        name="Atlas Height (px)",
        description="Exact height, in pixels, of the texture atlas image",
        default=128.0,
        min=1.0,
    )

    create_material: BoolProperty(
        name="Create Material",
        description=(
            "Creates one shared material wired into Base Color through the "
            "generated UVs, applied to every reference mesh. Hytale/Blockbench "
            "models only use a single flat texture (no PBR maps), so this "
            "mirrors that. If 'Texture Image' below is set, loads that image "
            "and uses its real pixel dimensions for the UV layout (overriding "
            "'Set Atlas Size Manually' above, if also enabled); otherwise "
            "creates a blank placeholder sized from the atlas size in use"
        ),
        default=True,
    )

    texture_mode: EnumProperty(
        name="Texture Mode",
        description=(
            "'Automatic' finds the texture PNG on disk using the same "
            "convention as the official Hytale Blockbench plugin (same "
            "folder as the model, or a '<ModelName>_Textures' subfolder). "
            "'Manual' lets you point to a specific file instead, ignoring "
            "auto-detection entirely"
        ),
        items=[
            (
                "AUTO",
                "Automatic",
                "Auto-detect the texture PNG next to the model (same "
                "convention as the official Hytale plugin)",
            ),
            (
                "MANUAL",
                "Manual",
                "Pick the texture PNG yourself -- auto-detection is skipped entirely",
            ),
        ],
        default="AUTO",
    )

    texture_filepath: StringProperty(
        name="Texture Image",
        description=(
            "The model's texture PNG. The .blockymodel file only stores "
            "per-face pixel offsets, not the texture itself or its canvas "
            "size -- pointing this at the real file gives exact UVs using "
            "its actual dimensions (takes priority over 'Set Atlas Size "
            "Manually' above). Only used when 'Texture Mode' above is set "
            "to 'Manual'"
        ),
        default="",
        subtype="FILE_PATH",
    )

    orient_z_up: BoolProperty(
        name="Orient to Z-up (visual only)",
        description=(
            "Hytale uses Y as the 'up' axis; Blender uses Z. This rotates "
            "ONLY the Armature object as a whole (not individual bones) so "
            "the character stands upright in Blender's default view. Doesn't "
            "affect pose/animation values, which stay in each bone's local space"
        ),
        default=True,
    )

    unit_scale: FloatProperty(
        name="Scale (Blender units per game unit)",
        description=(
            "The animation exporter (Export_blockyanim.py) multiplies "
            "position by 64 when saving. This only matches up if the rig "
            "here was built at 1/64 scale. Don't change this unless you're "
            "sure of a different value"
        ),
        default=UNIT_SCALE_DEFAULT,
        min=0.0001,
        max=10.0,
    )

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

        rig_box = layout.box()
        rig_box.label(text=tr("importer.section_rig", lang))
        rig_row = rig_box.column()
        rig_row.enabled = self.import_mode == "NEW_ARMATURE"
        rig_row.prop(self, "orient_z_up", text=tr("importer.orient_z_up", lang))
        rig_box.prop(self, "unit_scale", text=tr("importer.unit_scale", lang))

        vis_box = layout.box()
        vis_box.label(text=tr("importer.section_visuals", lang))
        vis_box.prop(self, "generate_reference_boxes", text=tr("importer.generate_reference_boxes", lang))

        sub = vis_box.column()
        sub.enabled = self.generate_reference_boxes
        sub.prop(self, "generate_uvs", text=tr("importer.generate_uvs", lang))
        sub.prop(self, "create_material", text=tr("importer.create_material", lang))

        atlas_sub = sub.column()
        atlas_sub.enabled = self.generate_uvs
        atlas_sub.prop(self, "missing_face_mode", text=tr("importer.missing_face_mode", lang))
        atlas_sub.prop(self, "override_atlas_size", text=tr("importer.override_atlas_size", lang))
        atlas_row = atlas_sub.row()
        atlas_row.enabled = self.override_atlas_size
        atlas_row.prop(self, "atlas_width", text=tr("importer.atlas_width", lang))
        atlas_row.prop(self, "atlas_height", text=tr("importer.atlas_height", lang))

        tex_row = sub.column()
        tex_row.enabled = self.generate_reference_boxes and self.create_material
        tex_row.prop(self, "texture_mode", text=tr("importer.texture_mode", lang))
        manual_row = tex_row.column()
        manual_row.enabled = self.texture_mode == "MANUAL"
        manual_row.prop(self, "texture_filepath", text=tr("importer.texture_filepath", lang))

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
                    self,
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
                resolved_texture_filepaths, tier = resolve_texture_filepaths(
                    self.filepath, self.texture_mode, self.texture_filepath
                )
                if resolved_texture_filepaths:
                    primary_name = os.path.basename(resolved_texture_filepaths[0])
                    if tier == "STRICT":
                        self.report(
                            {"INFO"},
                            f"Texture auto-detected: '{primary_name}' (same folder/naming "
                            f"convention as the official Hytale plugin). Set 'Texture Image' "
                            f"manually to override.",
                        )
                    elif tier == "LOOSE":
                        self.report(
                            {"INFO"},
                            f"Texture auto-detected: '{primary_name}' (found via a single "
                            f"sibling '*_Textures' folder that didn't match the model's exact "
                            f"name -- NOT the official plugin's own convention, just a looser "
                            f"fallback we added). Set 'Texture Image' manually to override.",
                        )

            add_reference_visuals(
                armature_obj,
                root_nodes,
                world_matrices,
                node_id_to_bone_name,
                self,
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
            f"Imported {len(node_id_to_bone_name)} node(s) from '{root_names}' {mode_desc} (scale={self.unit_scale:.5f}).",
        )
        return {"FINISHED"}


def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_hytale_blockymodel.bl_idname, text="Hytale Model (.blockymodel)")
    self.layout.operator(IMPORT_OT_hytale_bbmodel.bl_idname, text="Hytale Model (Blockbench .bbmodel)")


# ---------------------------------------------------------------------------
# Operator: import de .bbmodel
# ---------------------------------------------------------------------------
#
# Só tem modo "criar Armature novo" -- ver a nota grande no topo da seção
# "Suporte a .bbmodel" pra o motivo (um .bbmodel salvo já vem com os
# attachments fundidos na árvore, não precisa reconstruir isso na
# importação como o modo "Attach to Existing" do .blockymodel faz).


class IMPORT_OT_hytale_bbmodel(Operator, ImportHelper):
    """Import a Hytale character/creature from a Blockbench project (.bbmodel)"""

    bl_idname = "import_scene.hytale_bbmodel"
    bl_label = "Import Hytale Model (.bbmodel)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".bbmodel"
    filter_glob: StringProperty(default="*.bbmodel", options={"HIDDEN"})

    armature_name: StringProperty(
        name="Armature Name",
        description=(
            "Name for the new Armature and its collection. Leave empty to "
            "fall back to the project's own name (stored inside the "
            ".bbmodel), or to the filename if that's also empty"
        ),
        default="",
    )

    orient_z_up: BoolProperty(
        name="Orient to Z-up (visual only)",
        description=(
            "Rotate the Armature object 90 degrees so it displays upright "
            "in Blender's Z-up viewport. Purely a display rotation on the "
            "Armature object itself -- bone data underneath is untouched"
        ),
        default=True,
    )

    unit_scale: FloatProperty(
        name="Scale (Blender units per game unit)",
        description="Same meaning as in the .blockymodel importer -- see UNIT_SCALE_DEFAULT in common.py",
        default=UNIT_SCALE_DEFAULT,
        min=0.0001,
    )

    generate_reference_boxes: BoolProperty(
        name="Generate Reference Meshes",
        description=(
            "Creates a mesh for each cube element in the project, parented "
            "to the Armature and skinned (100% weight) to its owning bone "
            "via a Vertex Group + Armature modifier"
        ),
        default=True,
    )

    generate_uvs: BoolProperty(
        name="Generate UVs",
        description=(
            "Generates UV coordinates for the reference meshes from each "
            "face's pixel rectangle, already stored directly in the "
            ".bbmodel (no inference needed, unlike the .blockymodel path)"
        ),
        default=True,
    )

    create_material: BoolProperty(
        name="Create Materials",
        description=(
            "Decodes the texture(s) embedded in the .bbmodel itself "
            "(base64 PNG data) and creates one material per texture used, "
            "wired into Base Color/Alpha through the generated UVs -- no "
            "external texture file needed, everything is self-contained "
            "in the .bbmodel"
        ),
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        lang = get_language(context)

        target_box = layout.box()
        target_box.label(text=tr("importer.section_target", lang))
        target_box.prop(self, "armature_name", text=tr("importer.armature_name", lang))

        rig_box = layout.box()
        rig_box.label(text=tr("importer.section_rig", lang))
        rig_box.prop(self, "orient_z_up", text=tr("importer.orient_z_up", lang))
        rig_box.prop(self, "unit_scale", text=tr("importer.unit_scale", lang))

        vis_box = layout.box()
        vis_box.label(text=tr("importer.section_visuals", lang))
        vis_box.prop(self, "generate_reference_boxes", text=tr("importer.generate_reference_boxes", lang))

        sub = vis_box.column()
        sub.enabled = self.generate_reference_boxes
        sub.prop(self, "generate_uvs", text=tr("importer.generate_uvs", lang))
        sub.prop(self, "create_material", text=tr("importer.create_material", lang))

    def execute(self, context):
        with open(self.filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        outliner_roots = data.get("outliner", [])
        if not outliner_roots:
            self.report({"ERROR"}, "No outliner data found in the file (.bbmodel is empty or invalid).")
            return {"CANCELLED"}

        groups_by_uuid = {g["uuid"]: g for g in data.get("groups", [])}
        elements_by_uuid = {e["uuid"]: e for e in data.get("elements", [])}

        resolved_name = self.armature_name.strip() or derive_default_bbmodel_name(self.filepath, data)
        armature_data = bpy.data.armatures.new(resolved_name)
        armature_obj = bpy.data.objects.new(resolved_name, armature_data)
        rig_collection, main_collection, attachments_collection = build_character_collections(
            context, armature_obj.name
        )
        rig_collection.objects.link(armature_obj)
        armature_obj["hytale_meshes_main_collection"] = main_collection.name
        armature_obj["hytale_meshes_attachments_collection"] = attachments_collection.name

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
                image = decode_bbmodel_texture(tex_entry)
                if image is None:
                    continue
                atlas_by_texture_index[idx] = (image.size[0], image.size[1])
                material, _tex_node = build_flat_material_from_image(
                    image, material_name=tex_entry.get("name", "Hytale_Material")
                )
                material_by_texture_index[idx] = material

        mesh_build_context = {
            "target_collection": main_collection,
            "armature_obj": armature_obj,
            "atlas_by_texture_index": atlas_by_texture_index,
            "material_by_texture_index": material_by_texture_index,
            "generate_meshes": self.generate_reference_boxes,
            "generate_uvs": self.generate_reference_boxes and self.generate_uvs,
            "settings": self,
        }

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
                self.unit_scale,
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
            f"(scale={self.unit_scale:.5f}).",
        )
        return {"FINISHED"}


def register():
    bpy.utils.register_class(HytaleImporterPreferences)
    bpy.utils.register_class(IMPORT_OT_hytale_blockymodel)
    bpy.utils.register_class(IMPORT_OT_hytale_bbmodel)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(IMPORT_OT_hytale_bbmodel)
    bpy.utils.unregister_class(IMPORT_OT_hytale_blockymodel)
    bpy.utils.unregister_class(HytaleImporterPreferences)


if __name__ == "__main__":
    register()
