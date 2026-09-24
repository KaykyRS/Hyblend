"""templates/__init__.py -- carregador de templates de personagem
(rig + custom shapes + collections).

Cada personagem tem até três arquivos .json: rig/<nome>.json (cadeias
de IK + opções de geração), shapes/<nome>.json (transform + widget do
custom shape por bone) e collections/<nome>.json (organização de bone
collections). Duas fontes são escaneadas e mescladas: a pasta builtin
(dentro do addon) e a pasta do usuário, em Documentos/Hyblend/templates/
(ver user_templates_root()) -- um arquivo do usuário com o mesmo
template_name substitui o builtin.

Formato .json (não .py): mais fácil de editar na mão sem risco de rodar
código arbitrário. Ângulos sempre em GRAUS nos arquivos -- a conversão
pra radianos acontece só na hora de aplicar, em rigger/.

## Schema -- rig/<nome>.json

{
  "template_name": "Player",              // opcional -- se ausente, usa o nome do arquivo
  "description": "...",                    // opcional, só documentação/tooltip
  "shape_template": "Player",              // opcional -- shapes/ pra carregar junto (default: mesmo nome)
  "ik_chains": [                           // obrigatório -- um item por HytaleIKChainItem
    {
      "label": "Arm L",
      "root_bone": "L-Arm", "tip_bone": "L-Hand", "pole_bone": "L-Forearm",
      "parent_override": "L-Shoulder_CTRL",
      "side": "LEFT",                      // LEFT | RIGHT | CENTER
      "pole_invert": false,
      "pole_distance": 0.35,
      "pole_angle_mode": "PRESET",         // AUTO | PRESET | MANUAL
      "pole_angle_preset_name": "ARM",     // usado só em modo PRESET -- chave de pole_angle_presets abaixo
      "pole_angle_manual": 90.0,           // usado só em modo MANUAL
      "pole_angle_fine_tune": 0.0          // usado só em modo AUTO
    },
    {                                      // entrada ROOT (chain_type "ROOT") -- só os campos dela
      "label": "Root", "chain_type": "ROOT",
      "root_count": 2,                     // 1..ROOT_MAX_COUNT. Root 1 = Origin principal
      "root_bone_1": "Origin",             // nome do bone ORG; com root_create_N = true, nome do
      "root_create_1": false,              // bone a CRIAR (vazio = "Origin"/"Root<N>"). Bone criado
      "root_bone_2": "",                   // fica só no Blender (BONE_RIGGER_CREATED_PROP), nunca
      "root_create_2": true                // exportado. Root 2 vira pai do Root 1 (camada _CTRL).
    }
  ],
  "pole_angle_presets": {                  // opcional -- valores calibrados, por preset -> side.
    "ARM": {"LEFT": -91.25, "RIGHT": -88.76}   // Só usado por cadeias com pole_angle_mode = "PRESET".
  },
  // Indexado só por NOME DO PRESET + side, não por chain_type -- permite
  // reaproveitar entre tipos diferentes, mas também significa que nada
  // impede uma cadeia de braço e uma de perna de acabarem com o mesmo
  // nome por acidente, compartilhando o mesmo ângulo silenciosamente.
  // Convenção recomendada: um preset por chain_type (ARM/LEG/CHAIN).
  // rigger/generate.py avisa (WARNING) se detectar duas chain_type
  // usando o mesmo preset em modo PRESET, mas não corrige sozinho.
  "apply_ik_joint_fix": true,              // opcional (default false) -- liga a correção de posição de junta
  "ik_joint_x_overrides": {                // opcional -- ver _apply_ik_joint_fixes em rigger/generate.py.
    "R-Forearm_IK": -0.25796,              // chave = bone _IK do meio da cadeia, valor = novo X
    "L-Forearm_IK": 0.25796
  },
  "widget_translation_x_overrides": {      // opcional -- ajuste fino do X do custom shape depois
    "R-Forearm_IK": 0.0,                   // da correção automática de widget
    "L-Forearm_IK": 0.0
  }
}

## Schema -- shapes/<nome>.json

{
  "template_name": "Player",
  "description": "...",
  "bones": {
    "R-Hand_IK": {
      "widget": "WGT_hytale_ik_box",          // opcional -- nome na biblioteca (hytale_widgets.blend)
                                                // ou um nome por-personagem já gravado. Ausente = regra
                                                // genérica por papel (FK/IK/pole/etc.).
      "translation": [0.0, 0.078, 0.0],       // opcional -- campo ausente não é tocado
      "rotation_deg": [0.0, 0.0, 0.0],
      "scale": [0.89, 1.01, 1.19],
      "mesh": {                               // opcional -- geometria embutida do widget deste bone.
                                                // Só aparece pra bones genuinamente customizados (ver
                                                // _widget_mesh_differs_from_template) -- um bone com o
                                                // shape genérico intocado não ganha esta chave, pra
                                                // continuar recebendo remodelagens futuras da biblioteca.
        "vertices": [[0.1, 0.0, -0.1], [0.1, 0.0, 0.1]],  // [x, y, z] por vértice, arredondado
        "edges": [[0, 1]],                    // sempre gravado explícito -- necessário pra widgets
                                                // wireframe-só (sem face nenhuma)
        "faces": []                           // pode ficar vazia pra um widget wireframe-só
      }
    }
  }
}

## Schema -- collections/<nome>.json

{
  "template_name": "MyCustomCharacter",
  "description": "...",
  "collections": [                      // um item por bone collection custom (real, do Blender)
    {
      "name": "Tail",
      "parent": "Main",                 // parent REAL da bone collection (nome de outra deste
                                         // template, uma já existente, ou null) -- nada a ver com "section"
      "bones": ["Tail_CTRL", "Tail_CTRL.001"],
      "section": "Body",                // opcional -- em qual Section aparece na aba Animation
                                         // (Collection Settings, puramente visual). Ausente = Section "Main"
      "show_in_animation_tab": true,    // opcional, default true
      "row": 0, "column": 0             // opcional, default 0/0 -- posição no grid da Section
    }
  ],
  "sections": [                         // opcional -- um item por Section (sem bone collection real
                                         // por trás, só cabeçalho visual)
    {
      "name": "Body",
      "parent": "__SECTION_ROOT__",     // outra Section (aninhamento visual) ou o sentinel SECTION_ROOT
      "row": 0                          // ordem entre Sections irmãs
    }
  ]
}

Campos opcionais ausentes = template salvo antes de existirem, ou
nunca configurados -- carrega normalmente, sem migração (leitura por
.get()). Quem lê/escreve isso de fato é rigger/character_templates.py;
este módulo só faz I/O de arquivo.

## Adicionando um personagem novo

Sem tocar em código: duplique um arquivo em rig/ (e shapes/, se quiser),
ajuste os valores, dê um template_name novo (ou deixe vazio -- usa o
nome do arquivo). Aparece no dropdown depois de reabrir o Blender ou
clicar "Reload Templates".
"""
import json
import os

import bpy

from ..translations import tooltip

_BUNDLED_ROOT = os.path.dirname(__file__)
_KIND_SUBDIR = {"rig": "rig", "shapes": "shapes", "collections": "collections"}


def _documents_dir():
    """Tenta achar a pasta "Documentos" do usuário -- nome varia por
    idioma do sistema. Tenta EN/PT-BR e cria "Documents" se nenhum existir."""
    home = os.path.expanduser("~")
    candidates = ["Documents", "Documentos"]
    for name in candidates:
        path = os.path.join(home, name)
        if os.path.isdir(path):
            return path
    return os.path.join(home, candidates[0])


def user_templates_root():
    """Pasta raiz dos templates do usuário: Documentos/Hyblend/templates.
    Não garante que exista -- quem grava cria com os.makedirs; quem só
    lê ignora silenciosamente se não existir ainda."""
    return os.path.join(_documents_dir(), "Hyblend", "templates")


def _bundled_dir(kind):
    return os.path.join(_BUNDLED_ROOT, _KIND_SUBDIR[kind])


def _user_dir(kind):
    return os.path.join(user_templates_root(), _KIND_SUBDIR[kind])


def _safe_filename(name):
    keep = "-_ "
    cleaned = "".join(c for c in name if c.isalnum() or c in keep).strip()
    cleaned = cleaned.replace(" ", "_")
    return cleaned.lower() or "template"


# {"rig": {name: {"data":..., "source": "builtin"|"user", "path":...}}, "shapes": {...}, "collections": {...}}
_cache = {"rig": {}, "shapes": {}, "collections": {}}

# Listas prontas pro EnumProperty -- cacheadas num objeto estável (não
# reconstruídas a cada chamada do callback, mesmo motivo de translations/).
_items_cache = {"rig": [], "shapes": [], "collections": []}


def _load_json_dir(directory, source_label, registry):
    if not os.path.isdir(directory):
        return
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json") or filename.startswith("_"):
            continue
        path = os.path.join(directory, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"[HyblendToolkit] Falha ao ler template '{filename}' ({source_label}): {exc}")
            continue
        if not isinstance(data, dict):
            print(f"[HyblendToolkit] '{filename}' ({source_label}) não é um objeto JSON válido -- ignorado.")
            continue
        name = data.get("template_name") or os.path.splitext(filename)[0]
        registry[name] = {"data": data, "source": source_label, "path": path}


def _rebuild_items_cache(kind):
    """"(none)" sempre em primeiro -- pra dar pro usuário desmarcar a
    seleção de propósito, em vez do dropdown cair sozinho no primeiro
    template real. "NONE" nunca aparece em list_*_templates() nem é
    resolvido por get_*_template() -- é só sentinel de UI (ver
    _TEMPLATE_NONE em rigger/constants.py)."""
    entries = sorted(_cache[kind].items())
    items = [("NONE", "(none)", "No template selected")]
    items += [
        (name, name, entry["data"].get("description", "") or "")
        for name, entry in entries
    ]
    _items_cache[kind] = items


def _discover(kind):
    registry = {}
    _load_json_dir(_bundled_dir(kind), "builtin", registry)
    _load_json_dir(_user_dir(kind), "user", registry)  # usuário sobrescreve builtin de mesmo nome
    _cache[kind] = registry
    _rebuild_items_cache(kind)


def reload():
    """Reescaneia as três pastas, builtin + usuário. Chamado na
    importação deste módulo e de novo por TEMPLATES_OT_reload."""
    _discover("rig")
    _discover("shapes")
    _discover("collections")


def _ensure_loaded(kind):
    if not _cache[kind]:
        _discover(kind)


def list_rig_templates():
    """[{"name":..., "description":..., "source": "builtin"|"user"}, ...]"""
    _ensure_loaded("rig")
    return [
        {"name": name, "description": entry["data"].get("description", ""), "source": entry["source"]}
        for name, entry in sorted(_cache["rig"].items())
    ]


def get_rig_template(name):
    _ensure_loaded("rig")
    entry = _cache["rig"].get(name)
    return entry["data"] if entry else None


def list_shape_templates():
    _ensure_loaded("shapes")
    return [
        {"name": name, "description": entry["data"].get("description", ""), "source": entry["source"]}
        for name, entry in sorted(_cache["shapes"].items())
    ]


def get_shape_template(name):
    _ensure_loaded("shapes")
    entry = _cache["shapes"].get(name)
    return entry["data"] if entry else None


def rig_template_enum_items(self, context):
    """Callback de items= pro EnumProperty de preset em
    RIG_OT_hytale_ik_chain_load_defaults."""
    if not _cache["rig"]:
        _discover("rig")
    return _items_cache["rig"]


def shape_template_enum_items(self, context):
    if not _cache["shapes"]:
        _discover("shapes")
    return _items_cache["shapes"]


def _save_template(kind, name, data):
    """Grava `data` como Documentos/Hyblend/templates/<kind>/<name>.json.
    Sempre na pasta do usuário -- nunca sobrescreve um builtin. Retorna
    o caminho final e redescobre os templates de `kind`. Mesmo padrão de
    _delete_template() abaixo: uma função genérica + wrappers finos por
    tipo (save_rig_template/save_shape_template/save_collection_template)."""
    directory = _user_dir(kind)
    os.makedirs(directory, exist_ok=True)
    data = dict(data)
    data["template_name"] = name
    path = os.path.join(directory, _safe_filename(name) + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _discover(kind)
    return path


def save_rig_template(name, data):
    """Grava `data` como Documentos/Hyblend/templates/rig/<name>.json.
    Sempre na pasta do usuário -- nunca sobrescreve um builtin. Retorna
    o caminho final e redescobre os templates de rig/."""
    return _save_template("rig", name, data)


def save_shape_template(name, data):
    """Mesma ideia de save_rig_template(), pra shapes/<name>.json."""
    return _save_template("shapes", name, data)


def list_collection_templates():
    """[{"name":..., "description":..., "source": "builtin"|"user"}, ...]"""
    _ensure_loaded("collections")
    return [
        {"name": name, "description": entry["data"].get("description", ""), "source": entry["source"]}
        for name, entry in sorted(_cache["collections"].items())
    ]


def get_collection_template(name):
    _ensure_loaded("collections")
    entry = _cache["collections"].get(name)
    return entry["data"] if entry else None


def collection_template_enum_items(self, context):
    if not _cache["collections"]:
        _discover("collections")
    return _items_cache["collections"]


def save_collection_template(name, data):
    """Mesma ideia de save_shape_template(), pra collections/<name>.json."""
    return _save_template("collections", name, data)


def _delete_template(kind, name):
    """Só apaga templates da pasta do usuário -- um builtin nunca é
    removível por aqui (ver poll() dos operadores Delete em
    rigger/character_templates.py, que já bloqueia a UI; esta função é
    a segunda linha de defesa)."""
    _ensure_loaded(kind)
    entry = _cache[kind].get(name)
    if entry is None or entry["source"] != "user":
        return False
    try:
        os.remove(entry["path"])
    except OSError:
        return False
    _discover(kind)
    return True


def delete_rig_template(name):
    return _delete_template("rig", name)


def delete_shape_template(name):
    return _delete_template("shapes", name)


def delete_collection_template(name):
    return _delete_template("collections", name)


class TEMPLATES_OT_reload(bpy.types.Operator):
    """Reescaneia as pastas de templates (builtin + Documentos/Hyblend/
    templates/) sem precisar reiniciar o Blender."""

    bl_idname = "hytale.reload_templates"
    bl_label = "Reload Templates"
    description = tooltip("templates.tooltip.reload")
    bl_options = {"REGISTER"}

    def execute(self, context):
        reload()
        rig_names = ", ".join(sorted(_cache["rig"].keys())) or "-"
        shape_names = ", ".join(sorted(_cache["shapes"].keys())) or "-"
        coll_names = ", ".join(sorted(_cache["collections"].keys())) or "-"
        self.report(
            {"INFO"},
            f"HyblendToolkit: {len(_cache['rig'])} rig template(s) [{rig_names}], "
            f"{len(_cache['shapes'])} shape template(s) [{shape_names}], "
            f"{len(_cache['collections'])} collection template(s) [{coll_names}].",
        )
        return {"FINISHED"}


class TEMPLATES_OT_open_user_folder(bpy.types.Operator):
    """Abre (ou cria) Documentos/Hyblend/templates/ no explorador de
    arquivos do sistema."""

    bl_idname = "hytale.open_templates_folder"
    bl_label = "Open Templates Folder"
    description = tooltip("templates.tooltip.open_user_folder")
    bl_options = {"REGISTER"}

    def execute(self, context):
        root = user_templates_root()
        os.makedirs(os.path.join(root, "rig"), exist_ok=True)
        os.makedirs(os.path.join(root, "shapes"), exist_ok=True)
        os.makedirs(os.path.join(root, "collections"), exist_ok=True)
        try:
            bpy.ops.wm.path_open(filepath=root)
        except Exception as exc:
            self.report({"WARNING"}, f"Could not open '{root}' automatically: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


_CLASSES = (TEMPLATES_OT_reload, TEMPLATES_OT_open_user_folder)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


# Escaneia já na importação do módulo -- os dropdowns precisam ter algo
# pra mostrar assim que o painel desenhar pela primeira vez, sem esperar register().
reload()
