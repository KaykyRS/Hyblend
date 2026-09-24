"""importer/common_mesh.py -- peças COMPARTILHADAS por todos os importadores
(.blockymodel, .bbmodel, Bedrock): nome único de bone, tabelas de face/eixo
usadas pela UV dos dois formatos, e as collections (Rig/Main/Attachments +
collection por bone). Nada aqui é específico de um formato."""


import bpy



BONE_DISPLAY_LENGTH_GAME_UNITS = 4.0  # puramente estético, escalado igual ao resto


# --- Construção do Armature ---


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


def resolve_mesh_bone_collection(cache, top_collection, armature_name, bone_name, nearest_ancestor_fn):
    """Devolve (criando se preciso) a collection de malhas do bone
    `bone_name`, resolvendo recursivamente ONDE ela deve morar:

    - `nearest_ancestor_fn(bone_name)` devolve o nome do bone ANCESTRAL
      mais próximo que também é dono de malha direta, ou None se não
      achar nenhum (ou se o import estiver em modo flat -- ver as duas
      implementações concretas, `blockymodel_ancestor_fn`/
      `bbmodel_ancestor_fn`, que já devolvem sempre None quando
      `flat_mesh_collections` está ligado no operador).
    - Se achou um ancestral, a collection de `bone_name` nasce DENTRO da
      collection do ancestral (resolvida recursivamente -- pode ter mais
      de um nível: A dentro de B dentro de C, se B e C também forem donos
      de malha) -- é assim que o modo aninhado (padrão) mirrora a
      hierarquia de bones/groups só nos pontos que realmente têm malha,
      pulando bones puramente organizacionais no meio (que nunca ganham
      collection própria -- só quando têm malha DIRETA).
    - Se não achou (bone raiz do lado de malha, ou modo flat), a
      collection nasce direto dentro de `top_collection` (Main -
      <armature_name> / Mesh Attachments - <armature_name>).

    O nome final de cada collection leva `" - {armature_name}"` no fim
    (mesmo sufixo que `build_character_collections` já usa em "Rig - X"/
    "Main - X"), NÃO só `bone_name` puro -- nomes de bone como "Head"/
    "Pelvis"/"Origin"/"Chest" são comuns a praticamente todo personagem, e
    nomes de Collection são ÚNICOS GLOBALMENTE em bpy.data.collections
    (não só dentro do parent). Sem o sufixo, importar um SEGUNDO
    personagem faria o Blender renomear a collection colidente sozinho
    pra "Head.001" (a criação teria "sucesso" sem erro nenhum, mas
    silenciosamente errado), e cada reimport posterior criaria mais uma.

    `cache`: dict {(id(top_collection), bone_name): collection}, mantido
    pelo CHAMADOR (uma vida por chamada de add_reference_visuals/
    build_bbmodel_recursive) -- também serve pra cortar a recursão assim
    que uma collection já resolvida antes é encontrada de novo (ex: dois
    irmãos com o mesmo ancestral dono de malha)."""
    key = (id(top_collection), bone_name)
    coll = cache.get(key)
    if coll is not None:
        return coll

    ancestor_name = nearest_ancestor_fn(bone_name)
    if ancestor_name is not None and ancestor_name != bone_name:
        parent_collection = resolve_mesh_bone_collection(
            cache, top_collection, armature_name, ancestor_name, nearest_ancestor_fn
        )
    else:
        parent_collection = top_collection

    coll = get_or_create_child_collection(parent_collection, f"{bone_name} - {armature_name}")
    cache[key] = coll
    return coll


def collect_object_names_recursive(collection, names_out):
    """Preenche `names_out` (um set) com os nomes de TODOS os objetos
    dentro de `collection`, incluindo os que moram em sub-collections dela
    (recursivo, qualquer profundidade -- necessário desde que o modo
    aninhado/padrão pode empilhar collection dentro de collection). Usado
    só pro snapshot "o que já existia antes desta chamada de import"
    (ATTACH_EXISTING, pra não duplicar malha em reimport -- ver
    add_reference_visuals)."""
    names_out.update(collection.objects.keys())
    for child in collection.children:
        collect_object_names_recursive(child, names_out)


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
