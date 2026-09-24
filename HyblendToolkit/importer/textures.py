"""importer/textures.py -- textura, COMPARTILHADA por todos os importadores:
busca automática do PNG (os 4 passos), limpeza de caminho colado, material
"flat", variantes empilhadas no material."""

import os

import bpy
import numpy as np


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


# Limite de arquivos olhados no 4º passo (pasta "texture*" acima do modelo
# pode ser uma pasta grande de resource pack).
PARENT_TEXTURE_SEARCH_MAX_FILES = 20000


def _texture_name_prefixes(model_name):
    """Prefixos aceitos no 4º passo, do mais pro menos específico: o nome
    inteiro do modelo, depois cortando o último pedaço "_xxx" de cada vez
    (bulbasaur_male -> bulbasaur). Cobre o caso comum de várias geometrias/
    variantes (macho/fêmea) usarem a MESMA textura base."""
    parts = model_name.split("_")
    return ["_".join(parts[: len(parts) - cut]) for cut in range(len(parts)) if parts[: len(parts) - cut]]


def discover_texture_paths_parent_folder(dirname, model_name):
    """EXTRA nossa, ÚLTIMO passo da busca automática (só roda se os passos
    na própria pasta do modelo não acharem nada). Estrutura comum:

        Personagem/
        ├─ model/      <- .blockymodel / .geo.json aqui
        └─ textures/   <- PNGs aqui

    Sobe UM nível e olha toda pasta irmã cujo nome CONTÉM "texture"
    (qualquer maiúscula: textures, Texture, Bulbasaur_Textures...),
    incluindo subpastas dela. Aceita PNG cujo nome COMEÇA com o nome do
    modelo; se nenhum, tenta de novo cortando o último "_xxx" do nome do
    modelo (ver _texture_name_prefixes) -- o nível mais específico que
    achar algo vence, e TODOS os PNGs desse nível voltam (variantes, ex:
    bulbasaur.png + bulbasaur_shiny.png), igual os outros passos. PNG sem
    relação com o nome (ex: ivysaur.png) nunca é usado."""
    if not dirname or not model_name:
        return []
    here = os.path.normpath(os.path.abspath(dirname))
    parent = os.path.dirname(here)
    if not parent or parent == here:
        return []
    try:
        siblings = sorted(os.listdir(parent))
    except OSError:
        return []
    texture_dirs = [
        os.path.join(parent, entry)
        for entry in siblings
        if "texture" in entry.lower()
        and os.path.isdir(os.path.join(parent, entry))
        and os.path.normpath(os.path.join(parent, entry)) != here
    ]
    return match_pngs_by_model_name(collect_pngs_recursive(texture_dirs), model_name)


def collect_pngs_recursive(folders):
    """Todos os .png dentro de `folders` e das subpastas delas, em ordem
    de nome (determinística). Para depois de PARENT_TEXTURE_SEARCH_MAX_FILES
    arquivos olhados -- pasta de resource pack pode ser enorme."""
    pngs = []
    seen = 0
    for folder in folders:
        for dirpath, dirnames, files in os.walk(folder):
            dirnames.sort()
            for fname in sorted(files):
                seen += 1
                if fname.lower().endswith(".png"):
                    pngs.append(os.path.join(dirpath, fname))
            if seen > PARENT_TEXTURE_SEARCH_MAX_FILES:
                return pngs
    return pngs


def match_pngs_by_model_name(pngs, model_name):
    """O FILTRO por nome da busca de textura -- o mesmo pro 4º passo do
    Automático e pro Manual apontando uma pasta. Aceita PNG cujo nome
    COMEÇA com o nome do modelo; se nenhum, corta o último "_xxx" do nome
    e tenta de novo (bulbasaur_male -> bulbasaur) -- o nível mais
    específico que achar algo vence, e TODOS os PNGs desse nível voltam
    (variantes). PNG sem relação com o nome nunca entra. Nome exato do
    prefixo (bulbasaur.png) vem na frente -- o primeiro vira a textura
    ligada no material."""
    for prefix in _texture_name_prefixes(model_name):
        prefix_lower = prefix.lower()
        matches = [p for p in pngs if os.path.basename(p).lower().startswith(prefix_lower)]
        if matches:
            exact = [p for p in matches if os.path.splitext(os.path.basename(p))[0].lower() == prefix_lower]
            return exact + [p for p in matches if p not in exact]
    return []


def resolve_texture_filepaths(model_filepath, texture_mode, manual_path, model_name):
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

    Se nada disso achar, o ÚLTIMO passo olha pastas "texture*" UM nível
    acima (ver discover_texture_paths_parent_folder).

    MANUAL com uma PASTA no lugar do arquivo: procura PNGs nela e nas
    subpastas, com o mesmo filtro por nome do Automático -> camada
    "MANUAL_FOLDER" (ou "MANUAL_FOLDER_EMPTY" se nenhum PNG bater).

    Devolve (lista_de_caminhos, camada), onde camada é "MANUAL", "STRICT"
    (achou pela convenção oficial), "LOOSE" (só achou pelo fallback extra
    nosso), "PARENT" (só achou na pasta "texture*" acima do modelo) ou
    "NONE" (nada encontrado -- cai no placeholder cinza, como sempre).

    `model_name`: nome do modelo usado na busca, calculado por quem chama
    (cada formato tira do nome do arquivo do seu jeito -- ex: .blockymodel
    tira ".blockymodel", Bedrock tira ".geo.json")."""
    if texture_mode == "MANUAL":
        manual_path = clean_texture_path(manual_path)
        if not manual_path:
            return [], "NONE"
        # Pasta em vez de arquivo: PNGs dela + subpastas, com o MESMO
        # filtro por nome do Automático (match_pngs_by_model_name).
        folder = bpy.path.abspath(manual_path)
        if os.path.isdir(folder):
            found = match_pngs_by_model_name(collect_pngs_recursive([folder]), model_name)
            return (found, "MANUAL_FOLDER") if found else ([], "MANUAL_FOLDER_EMPTY")
        return [manual_path], "MANUAL"

    dirname = os.path.dirname(model_filepath)

    candidates = discover_texture_paths(dirname, model_name)
    tier = "STRICT"
    if not candidates:
        candidates = discover_texture_paths_loose_fallback(dirname, model_name)
        tier = "LOOSE"
    if not candidates:
        # Último passo: pasta "texture*" UM nível acima (já volta ordenada
        # pela própria função -- não passa pela preferência abaixo).
        candidates = discover_texture_paths_parent_folder(dirname, model_name)
        return (candidates, "PARENT") if candidates else ([], "NONE")

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
    stack_extra_texture_nodes(mat, primary_tex_node, loaded_images[1:])

    return mat, primary_image, loaded_images


def stack_extra_texture_nodes(mat, primary_tex_node, extra_images):
    """Empilha `extra_images` (variantes da textura) como nodes Image
    Texture ABAIXO do node principal, SEM conexão -- ficam no material só
    pra você arrastar um link na mão se quiser trocar. Usado pelo import de
    .blockymodel (get_or_create_material) e pelo converter/bedrock.py."""
    # Nodes de textura têm ~230px de altura por padrão (com o preview de
    # imagem aberto) -- 260 dá uma folguinha visual entre um e outro sem
    # ficarem colados.
    NODE_STACK_OFFSET_Y = 260
    for i, extra_image in enumerate(extra_images, start=1):
        extra_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        extra_node.image = extra_image
        extra_node.interpolation = "Closest"
        extra_node.label = extra_image.name
        extra_node.location = (
            primary_tex_node.location.x,
            primary_tex_node.location.y - NODE_STACK_OFFSET_Y * i,
        )


def texture_detection_message(tier, paths, model_name):
    """Mensagem pro usuário depois da busca de textura -- a MESMA em todos
    os importadores. `tier`/`paths` = retorno de resolve_texture_filepaths.
    Devolve None quando não há o que dizer (MANUAL com arquivo válido).
    Pra "NONE" em modo Manual (campo vazio), quem chama decide se fala algo
    -- ver texture_report_level."""
    extra = len(paths) - 1
    variants = f" {extra} more variant(s) added to the material, unconnected." if extra > 0 else ""
    primary = os.path.basename(paths[0]) if paths else ""
    override = " Set Texture Mode to Manual to override."
    if tier == "STRICT":
        return (
            f"Texture auto-detected: '{primary}' (same folder/naming convention as the official "
            f"Hytale plugin).{variants}{override}"
        )
    if tier == "LOOSE":
        return (
            f"Texture auto-detected: '{primary}' (found via a single sibling '*_Textures' folder "
            f"that didn't match the model's exact name -- NOT the official plugin's own convention, "
            f"just a looser fallback we added).{variants}{override}"
        )
    if tier == "PARENT":
        return (
            f"Texture auto-detected: '{primary}' (found in a 'texture' folder one level above the "
            f"model).{variants}{override}"
        )
    if tier == "MANUAL_FOLDER":
        return f"Texture from the chosen folder: '{primary}'.{variants}"
    if tier == "MANUAL_FOLDER_EMPTY":
        return (
            f"No PNG in the chosen folder (or its subfolders) matches the model name '{model_name}' "
            f"-- imported without texture."
        )
    if tier == "MANUAL" and paths and not os.path.isfile(bpy.path.abspath(paths[0])):
        return f"Texture file not found: '{paths[0]}' -- imported without texture."
    if tier == "NONE":
        return (
            f"No texture found (next to the model or in a 'texture' folder one level above; expected "
            f"a PNG starting with '{model_name}'). Set Texture Mode to Manual to pick one."
        )
    return None


def build_scaled_texture(png_path, target_w, target_h, name):
    """Carrega o PNG e devolve uma imagem NOVA (empacotada no .blend) de
    target_w x target_h, ampliada com nearest-neighbor -- pixel art
    continua nítida. O arquivo original não é tocado. Usado quando a
    densidade de textura da origem é diferente da do Hytale (ex: modelo
    do Minecraft, 16px por bloco -> 64/32). Devolve None se não carregar."""
    try:
        src = bpy.data.images.load(png_path, check_existing=False)
    except RuntimeError:
        return None
    try:
        w, h = src.size
        if w == 0 or h == 0:
            return None
        pixels = np.empty(w * h * 4, dtype=np.float32)
        src.pixels.foreach_get(pixels)
        pixels = pixels.reshape(h, w, 4)
        ys = (np.arange(target_h) * h // target_h).clip(0, h - 1)
        xs = (np.arange(target_w) * w // target_w).clip(0, w - 1)
        scaled = pixels[ys][:, xs]
        image = bpy.data.images.new(name, width=target_w, height=target_h, alpha=True)
        image.pixels.foreach_set(scaled.ravel())
        image.pack()
        return image
    finally:
        bpy.data.images.remove(src)


def texture_report_level(tier, paths):
    """Nível do report pra mensagem de texture_detection_message: WARNING
    quando o usuário apontou algo (Manual) e não deu pra usar, INFO no
    resto."""
    if tier == "MANUAL_FOLDER_EMPTY":
        return "WARNING"
    if tier == "MANUAL" and paths and not os.path.isfile(bpy.path.abspath(paths[0])):
        return "WARNING"
    return "INFO"


def texture_result_report(texture_mode, tier, paths, model_name):
    """(nível, mensagem) pro resultado da busca de textura, ou None quando
    não há o que dizer -- usado por TODOS os importadores. Manual com o
    campo vazio não gera mensagem aqui (cada formato decide)."""
    if texture_mode == "MANUAL" and tier == "NONE":
        return None
    message = texture_detection_message(tier, paths, model_name)
    if not message:
        return None
    return texture_report_level(tier, paths), message
