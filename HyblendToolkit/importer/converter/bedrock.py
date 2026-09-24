"""importer/converter/bedrock.py -- CONVERSÃO de modelo Bedrock (.json) do
Minecraft pro padrão do Hytale. Só conversão: puro Python, sem Blender (o
import em si -- janela de opções, textura, Armature -- mora em
importer/bedrock.py).

Modelo Bedrock = "minecraft:geometry" (format_version 1.12.0+) ou o formato
legado 1.8.0/1.10.0 (chaves "geometry.<nome>" na raiz). A convenção de nome
"<x>.geo.json" é só nome -- a extensão real é .json, então o tipo é
identificado pelo CONTEÚDO (ver detect_json_kind).

A saída é um dict no formato .bbmodel (groups/elements/outliner), que o
importer entrega pra bbmodel.import_bbmodel_data. A tradução reproduz a do
próprio Blockbench (codec js/formats/bedrock/bedrock.js + "Convert Project"
pra Hytale), validada elemento a elemento contra um arquivo convertido por
ele, e acrescenta a conversão pro padrão do Hytale:

1) Espelhamento em X (convenção do Blockbench pra Bedrock): pivot/origin
   com X negado, cubo from.x = -(origin.x + size.x), rotação (x, y) negadas.

2) Escala: Minecraft = 16 unidades por bloco; Hytale Character = 64,
   Prop = 32 (hytale-blockbench-plugin src/formats.ts, block_size). Tudo
   que é medida (posição, tamanho, inflate) e a UV em pixels são
   multiplicados por k = block_size/16 (x4 ou x2). O modelo mantém o
   tamanho que tinha no mundo do Minecraft, com unidade e densidade de
   textura do Hytale (1 unidade = 1 pixel). "resolution" também sai x k --
   quem importa amplia o PNG pra esse tamanho.

3) inflate -> stretch. O Hytale não tem inflate; stretch escala em torno do
   CENTRO da caixa (plugin src/element.ts: "center +- halfSize*stretch"),
   então stretch = (tamanho + 2*inflate)/tamanho reproduz o inflate sem
   mudar a UV. Pra isso o origin do cubo vai pro centro da caixa (com
   compensação de translação quando o cubo tem rotação própria, pra
   posição no mundo não mudar). Eixo de tamanho 0 (plano) fica com
   stretch 1 -- vira quad no Hytale, que não tem espessura.

4) Frente pro +Z. Modelo Bedrock olha pro -Z (a cabeça fica no -Z, a cauda
   no +Z); modelo do Hytale olha pro +Z -- o mesmo lado que o importer
   mostra de frente no Blender (Armature girado 90° em X: +Z do arquivo =
   -Y do Blender). Sem isto o modelo convertido ficava de costas, no
   Blender e no jogo depois de exportado. É uma ROTAÇÃO de 180° em torno do
   eixo vertical (não espelho): x e z trocam de sinal, rotações (rx, ry, rz)
   viram (-rx, ry, -rz) (conjugação por Ry(180°) da Euler Rz·Ry·Rx do
   Blockbench), e as faces trocam de nome north<->south, east<->west --
   a UV de cada face continua a mesma, ela só passa a apontar pro outro
   lado. Feita no FIM (ver _face_positive_z), por cima da tradução do
   Blockbench validada acima, que continua intacta.
"""

import math
import uuid

from ...common import BLOCK_SIZE_BY_MODEL_FORMAT

MINECRAFT_BLOCK_SIZE = 16
FACE_KEYS = ("north", "east", "south", "west", "up", "down")


# ---------------------------------------------------------------------------
# Detecção pelo conteúdo
# ---------------------------------------------------------------------------


def detect_json_kind(data):
    """Classifica um .json do Minecraft pelo conteúdo. Devolve um de:
    "bedrock_geometry", "bedrock_geometry_legacy", "bedrock_animation",
    "java_block_model", "unknown"."""
    if not isinstance(data, dict):
        return "unknown"
    if isinstance(data.get("minecraft:geometry"), list):
        return "bedrock_geometry"
    if any(k.startswith("geometry.") and isinstance(v, dict) for k, v in data.items()):
        return "bedrock_geometry_legacy"
    if isinstance(data.get("animations"), dict):
        return "bedrock_animation"
    if isinstance(data.get("elements"), list) or "parent" in data or "textures" in data:
        return "java_block_model"
    return "unknown"


def list_geometries(data):
    """Lista normalizada [(identifier, texture_w, texture_h, bones, parent_id)]
    dos dois formatos de geometria Bedrock."""
    kind = detect_json_kind(data)
    out = []
    if kind == "bedrock_geometry":
        for geo in data["minecraft:geometry"]:
            desc = geo.get("description", {}) or {}
            out.append((
                desc.get("identifier", "geometry.unknown"),
                desc.get("texture_width", 16),
                desc.get("texture_height", 16),
                geo.get("bones", []) or [],
                None,
            ))
    elif kind == "bedrock_geometry_legacy":
        for key, geo in data.items():
            if not key.startswith("geometry.") or not isinstance(geo, dict):
                continue
            identifier, _, parent_id = key.partition(":")
            out.append((
                identifier,
                geo.get("texturewidth", 16),
                geo.get("textureheight", 16),
                geo.get("bones", []) or [],
                parent_id or None,
            ))
    return out


# ---------------------------------------------------------------------------
# Tradução Bedrock -> estrutura .bbmodel (puro Python, sem bpy)
# ---------------------------------------------------------------------------


def _vec(v, default=0.0):
    v = list(v or [])
    return [float(v[i]) if i < len(v) else default for i in range(3)]


def _rot_matrix_bb(rot_deg):
    """Matriz 3x3 da rotação de um cubo/group do Blockbench (Euler 'ZYX'
    do three.js = Rz * Ry * Rx), em graus."""
    rx, ry, rz = (math.radians(a) for a in rot_deg)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    Rx = ((1, 0, 0), (0, cx, -sx), (0, sx, cx))
    Ry = ((cy, 0, sy), (0, 1, 0), (-sy, 0, cy))
    Rz = ((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))

    def mul(a, b):
        return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))

    return mul(mul(Rz, Ry), Rx)


def _box_uv_rects(uv, size, mirror):
    """Retângulos por face (pixels) do layout "box UV" -- mesmo layout do
    Blockbench (Cube.updateUV, box_uv), conferido contra o arquivo
    convertido. Tamanho arredondado pra baixo, como o Minecraft faz."""
    u, v = uv
    sx, sy, sz = (math.floor(s + 1e-6) for s in size)
    rects = {
        "east": [u, v + sz, u + sz, v + sz + sy],
        "north": [u + sz, v + sz, u + sz + sx, v + sz + sy],
        "west": [u + sz + sx, v + sz, u + sz + sx + sz, v + sz + sy],
        "south": [u + 2 * sz + sx, v + sz, u + 2 * sz + 2 * sx, v + sz + sy],
        "up": [u + sz + sx, v + sz, u + sz, v],
        "down": [u + sz + 2 * sx, v, u + sz + sx, v + sz],
    }
    if mirror:
        rects["east"], rects["west"] = rects["west"], rects["east"]
        for r in rects.values():
            r[0], r[2] = r[2], r[0]
    return rects


def _face_dimensions(size):
    """Largura/altura (pixels) de cada face de um cubo -- usado quando a
    face não tem "uv_size" (o Blockbench faz o mesmo: mapAutoUV)."""
    sx, sy, sz = (abs(c) for c in size)
    return {
        "north": (sx, sy), "south": (sx, sy),
        "east": (sz, sy), "west": (sz, sy),
        "up": (sx, sz), "down": (sx, sz),
    }


def _per_face_uv_rects(uv_dict, size):
    """UV por face do Bedrock ({face: {uv, uv_size, uv_rotation}}). Face
    ausente = sem textura (null explícito -> face escondida). Mesma leitura
    do codec do Blockbench (js/formats/bedrock/bedrock.js, parseCube)."""
    rects, rotations = {}, {}
    dims = _face_dimensions(size)
    for key in FACE_KEYS:
        info = uv_dict.get(key)
        if not isinstance(info, dict) or "uv" not in info:
            rects[key] = None
            continue
        u, v = info["uv"][:2]
        w, h = (info.get("uv_size") or dims[key])[:2]
        if key in ("up", "down"):
            # Bedrock grava up/down com o retângulo invertido em relação ao
            # Blockbench (mesma inversão que o codec do Blockbench desfaz).
            rects[key] = [u + w, v + h, u, v]
        else:
            rects[key] = [u, v, u + w, v + h]
        if info.get("uv_rotation"):
            rotations[key] = int(info["uv_rotation"]) % 360
    return rects, rotations


def _is_descendant(candidate, ancestor, bones, indices_by_lower):
    """True se `candidate` descende de `ancestor` pela cadeia de "parent"
    -- evita ciclo (A pai de B, B pai de A), que sumiria com os dois."""
    seen = set()
    current = candidate
    while current is not None and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        parent = bones[current].get("parent")
        cands = [c for c in indices_by_lower.get(parent.lower(), []) if c != current] if isinstance(parent, str) else []
        before = [c for c in cands if c < current]
        current = before[-1] if before else (cands[0] if cands else None)
    return False


_FACE_SWAP_Y180 = {"north": "south", "south": "north", "east": "west", "west": "east", "up": "up", "down": "down"}


def _rotate_point_y180(point):
    return [-point[0], point[1], -point[2]]


def _face_positive_z(data):
    """Gira o dict .bbmodel convertido 180° em torno do eixo Y (ver item 4
    do docstring do módulo). Mexe em `data` no lugar."""
    for element in data["elements"]:
        frm, to = element["from"], element["to"]
        # x e z trocam de sinal -- from/to trocam de papel nesses eixos
        # pra continuar from <= to.
        element["from"] = [-to[0], frm[1], -to[2]]
        element["to"] = [-frm[0], to[1], -frm[2]]
        element["origin"] = _rotate_point_y180(element["origin"])
        if "rotation" in element:
            rx, ry, rz = element["rotation"]
            element["rotation"] = [-rx, ry, -rz]
        element["faces"] = {_FACE_SWAP_Y180[key]: face for key, face in element["faces"].items()}
    for group in data["groups"]:
        group["origin"] = _rotate_point_y180(group["origin"])
        rx, ry, rz = group["rotation"]
        group["rotation"] = [-rx, ry, -rz]


def bedrock_to_bbmodel_data(geometry, model_format, inflate_to_stretch=True, drop_locator_bones=False):
    """Traduz UMA geometria (item de list_geometries) pra um dict no
    formato .bbmodel aceito por importer.import_bbmodel_data. Devolve
    (data, report) -- report = dict de contagens/avisos pro operador."""
    identifier, tex_w, tex_h, bones, parent_id = geometry
    k = BLOCK_SIZE_BY_MODEL_FORMAT[model_format] / MINECRAFT_BLOCK_SIZE
    report = {
        "scale_factor": k, "inflated": 0, "poly_mesh": 0, "texture_meshes": 0,
        "dropped_locators": 0, "missing_parents": 0, "parent_geometry": parent_id,
    }

    def scaled(v):
        return [c * k for c in v]

    # Hierarquia por ÍNDICE (não por nome): nome repetido é permitido (o
    # Blockbench renomeia; aqui o próprio importer desambigua depois, com
    # BONE_ORIGINAL_NAME_PROP). "parent" é comparado sem diferenciar
    # maiúsculas, igual o Blockbench, e pode apontar pra um bone que só
    # aparece depois no arquivo. Com nome repetido, vale o último definido
    # ANTES do filho (senão o primeiro depois dele).
    bones = [b for b in bones if isinstance(b, dict) and b.get("name")]
    indices_by_lower = {}
    for i, bone in enumerate(bones):
        indices_by_lower.setdefault(bone["name"].lower(), []).append(i)
    children = {i: [] for i in range(len(bones))}
    roots = []
    for i, bone in enumerate(bones):
        parent = bone.get("parent")
        candidates = indices_by_lower.get(parent.lower(), []) if isinstance(parent, str) else []
        candidates = [c for c in candidates if c != i]
        before = [c for c in candidates if c < i]
        parent_index = before[-1] if before else (candidates[0] if candidates else None)
        if parent_index is not None and not _is_descendant(parent_index, i, bones, indices_by_lower):
            children[parent_index].append(i)
        else:
            if isinstance(parent, str) and parent_index is None:
                report["missing_parents"] += 1
            roots.append(i)

    def is_locator_only(i):
        bone = bones[i]
        return (
            "locators" in bone
            and not bone.get("cubes")
            and all(is_locator_only(c) for c in children[i])
        )

    groups, elements = [], []

    def make_element(bone, cube):
        size = _vec(cube.get("size"))
        origin = _vec(cube.get("origin"))
        inflate = float(cube.get("inflate", bone.get("inflate", 0.0)) or 0.0)
        mirror = bool(cube.get("mirror", bone.get("mirror", False)))
        rotation = _vec(cube.get("rotation"))
        pivot = cube.get("pivot")

        # Espelhamento em X (convenção do Blockbench pra Bedrock).
        frm = [-(origin[0] + size[0]), origin[1], origin[2]]
        to = [frm[0] + size[0], frm[1] + size[1], frm[2] + size[2]]
        rot = [-rotation[0], -rotation[1], rotation[2]]
        if pivot is not None:
            pivot = _vec(pivot)
            el_origin = [-pivot[0], pivot[1], pivot[2]]
        else:
            el_origin = [0.0, 0.0, 0.0]

        element = {
            "name": bone["name"],
            "type": "cube",
            "uuid": str(uuid.uuid4()),
            "box_uv": not isinstance(cube.get("uv"), dict),
        }

        # UV em pixels do Minecraft, depois escalada por k.
        uv = cube.get("uv", [0, 0])
        if isinstance(uv, dict):
            rects, uv_rotations = _per_face_uv_rects(uv, size)
        else:
            rects, uv_rotations = _box_uv_rects(_vec(uv)[:2], size, mirror), {}
        faces = {}
        for key in FACE_KEYS:
            rect = rects.get(key)
            if rect is None:
                faces[key] = {"uv": [0, 0, 0, 0], "texture": None}
                continue
            face = {"uv": [c * k for c in rect]}
            if key in uv_rotations:
                face["rotation"] = uv_rotations[key]
            faces[key] = face
        element["faces"] = faces

        stretch = [1.0, 1.0, 1.0]
        if inflate and inflate_to_stretch:
            report["inflated"] += 1
            center = [(frm[i] + to[i]) / 2 for i in range(3)]
            if any(rot):
                # Mantém a posição no mundo ao trocar o pivô de rotação
                # pro centro: desloca a caixa por d = R(c-o) - (c-o).
                R = _rot_matrix_bb(rot)
                co = [center[i] - el_origin[i] for i in range(3)]
                Rco = [sum(R[i][j] * co[j] for j in range(3)) for i in range(3)]
                d = [Rco[i] - co[i] for i in range(3)]
                frm = [frm[i] + d[i] for i in range(3)]
                to = [to[i] + d[i] for i in range(3)]
                center = [center[i] + d[i] for i in range(3)]
            el_origin = center
            stretch = [(abs(s) + 2 * inflate) / abs(s) if abs(s) > 1e-6 else 1.0 for s in size]

        element["from"] = scaled(frm)
        element["to"] = scaled(to)
        element["origin"] = scaled(el_origin)
        if any(rot):
            element["rotation"] = rot
        if stretch != [1.0, 1.0, 1.0]:
            element["stretch"] = stretch
        if mirror:
            element["mirror_uv"] = True
        return element

    def build(index):
        bone = bones[index]
        name = bone["name"]
        pivot = _vec(bone.get("pivot"))
        rotation = _vec(bone.get("rotation"))
        group = {
            "name": name,
            "uuid": str(uuid.uuid4()),
            "origin": scaled([-pivot[0], pivot[1], pivot[2]]),
            "rotation": [-rotation[0], -rotation[1], rotation[2]],
        }
        groups.append(group)
        node = {"name": name, "uuid": group["uuid"], "children": []}
        for cube in bone.get("cubes", []) or []:
            element = make_element(bone, cube)
            elements.append(element)
            node["children"].append(element["uuid"])
        if bone.get("poly_mesh"):
            report["poly_mesh"] += 1
        if bone.get("texture_meshes"):
            report["texture_meshes"] += 1
        for child in children[index]:
            if drop_locator_bones and is_locator_only(child):
                report["dropped_locators"] += 1
                continue
            node["children"].append(build(child))
        return node

    outliner = []
    for root in roots:
        if drop_locator_bones and is_locator_only(root):
            report["dropped_locators"] += 1
            continue
        outliner.append(build(root))

    short_name = identifier[len("geometry."):] if identifier.startswith("geometry.") else identifier
    data = {
        "meta": {"format_version": "5.0", "model_format": f"hytale_{model_format}", "box_uv": True},
        "name": short_name,
        "resolution": {"width": int(round(tex_w * k)), "height": int(round(tex_h * k))},
        "elements": elements,
        "groups": groups,
        "outliner": outliner,
        "textures": [],
    }
    _face_positive_z(data)
    return data, report
