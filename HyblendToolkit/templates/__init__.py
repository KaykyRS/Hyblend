"""
templates/__init__.py -- carregador de templates de personagem do
HyblendToolkit (rig + custom shapes).
======================================================================

Antes vivia tudo hardcoded dentro de rigger.py: HYTALE_RIG_PRESETS
(cadeias de IK por personagem), WIDGET_TRANSFORM_OVERRIDES (tamanho/
posição/rotação do custom shape por bone), ARM_POLE_ANGLE_PRESET,
PLAYER_IK_JOINT_X_OVERRIDES e PLAYER_WIDGET_TRANSLATION_X_OVERRIDES
(calibração exclusiva do personagem "Player"). Agora existe UM sistema
plugável, orientado a arquivo, no mesmo espírito do pacote translations/
(ver esse __init__.py pra comparar):

- Cada personagem/criatura tem até DOIS arquivos .json, em pastas
  separadas: `rig/<nome>.json` (cadeias de IK + opções de geração) e
  `shapes/<nome>.json` (transform + widget do custom shape por bone).
  Separados de propósito (pedido explícito): o mesmo "rig" pode ser
  testado com shapes diferentes sem duplicar a lista de cadeias, e
  vice-versa.
- Duas fontes são escaneadas e mescladas: a pasta BUILTIN (dentro do
  addon, `templates/rig/` e `templates/shapes/`, ao lado deste arquivo)
  e a pasta do USUÁRIO, em Documentos/Hyblend/templates/rig/ e
  .../shapes/ (ver user_templates_root()). Um arquivo do usuário com o
  mesmo `template_name` de um builtin SUBSTITUI o builtin (permite
  "customizar" o Player sem precisar editar nada dentro do addon).
- Formato .json (não .py como translations/) -- decisão explícita: é o
  formato mais fácil de um usuário sem experiência em programação abrir
  num editor de texto qualquer e editar na mão, sem risco de rodar
  código arbitrário.
- Ângulos em GRAUS nos arquivos (`rotation_deg`, `pole_angle_presets`,
  etc.), nunca radianos -- é o que o usuário lê no painel do Blender.
  A conversão pra radianos acontece só na hora de aplicar (rigger.py).

## Schema -- rig/<nome>.json

{
  "template_name": "Player",              // opcional -- se ausente, usa o nome do arquivo
  "description": "...",                    // opcional, só documentação/tooltip
  "shape_template": "Player",              // opcional -- nome do template de shapes/ pra carregar
                                            // junto automaticamente (default: mesmo nome deste arquivo)
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
      "pole_angle_fine_tune": 0.0,         // usado só em modo AUTO
      "extra_ik_location": false
    }
  ],
  "pole_angle_presets": {                  // opcional -- valores calibrados de pole_angle, por
    "ARM": {"LEFT": -91.25, "RIGHT": -88.76}   // preset (nome livre) -> por side. Só usado por
  },                                            // cadeias com pole_angle_mode = "PRESET".
  // ATENÇÃO: indexado só por NOME DO PRESET + side -- NÃO por chain_type
  // (ARM/LEG/TAIL). É intencional (deixa reaproveitar o mesmo preset
  // entre tipos diferentes, se a geometria for parecida o bastante) --
  // mas também significa que NADA impede uma cadeia de braço e uma de
  // perna de acabarem com o MESMO pole_angle_preset_name por acidente
  // (copiar/colar um item da lista e esquecer de trocar o nome, ou só
  // digitar "ARM" em tudo por hábito) -- nesse caso elas passam a
  // compartilhar o MESMO ângulo calibrado, silenciosamente, o que quase
  // sempre é errado (cotovelo e joelho raramente têm a mesma geometria).
  // Convenção recomendada: um preset por chain_type (ex.: "ARM"/"LEG"/
  // "TAIL"), nunca o mesmo nome pros dois, a menos que você tenha
  // verificado que o ângulo realmente bate pros dois. rigger.py (v0.8,
  // ver _warn_shared_pole_angle_presets) avisa com um WARNING, na hora
  // de gerar o rig, se detectar mais de um chain_type usando o mesmo
  // nome de preset em modo PRESET -- mas só detecta, não impede/corrige
  // nada sozinho.
  "apply_ik_joint_fix": true,              // opcional (default false) -- liga a correção de
                                            // posição de junta abaixo automaticamente ao carregar
  "ik_joint_x_overrides": {                // opcional -- ver _apply_ik_joint_fixes em rigger.py.
    "R-Forearm_IK": -0.25796,              // chave = bone _IK do MEIO da cadeia, valor = novo X
    "L-Forearm_IK": 0.25796
  },
  "widget_translation_x_overrides": {      // opcional -- ajuste fino do X do custom shape DEPOIS
    "R-Forearm_IK": 0.0,                   // da correção automática de widget (mesmos bones de
    "L-Forearm_IK": 0.0                    // ik_joint_x_overrides, normalmente)
  }
}

## Schema -- shapes/<nome>.json

{
  "template_name": "Player",
  "description": "...",
  "bones": {
    "R-Hand_IK": {
      "widget": "WGT_hytale_ik_box",          // opcional -- nome do objeto na biblioteca
                                                // (assets/hytale_widgets.blend). Ausente = usa a
                                                // regra genérica por papel (FK/IK/pole/etc.).
      "translation": [0.0, 0.078, 0.0],       // opcional -- qualquer campo ausente NÃO é
      "rotation_deg": [0.0, 0.0, 0.0],        // tocado (fica como já estava no bone)
      "scale": [0.89, 1.01, 1.19]
    }
  }
}

## Adicionando um personagem novo

Sem tocar em nenhum código: duplique um arquivo em rig/ e (se quiser
formas customizadas) em shapes/, ajuste os valores, dê um
`template_name` novo (ou deixe vazio -- usa o nome do arquivo). Aparece
sozinho no dropdown de "Load Hytale IK Chain Preset" na próxima vez que
o Blender reler esta pasta (reabrir o Blender, ou botão "Reload
Templates" -- ver TEMPLATES_OT_reload).

## Pasta do usuário (Documentos/Hyblend/templates/)

Pensada pra quem quer manter os PRÓPRIOS templates sem misturar com os
que vêm no addon (que podem ser sobrescritos numa atualização do addon).
`RIG_OT_hytale_rig_template_save` / `RIG_OT_hytale_shape_template_save`
(em rigger.py) escrevem SEMPRE aqui, nunca dentro da pasta do addon.
`user_templates_root()` resolve "Documentos" tentando alguns nomes
comuns (inglês e português) -- ver essa função pra detalhes.
"""
import json
import os

import bpy

# ---------------------------------------------------------------------------
# Localização das pastas (builtin + usuário)
# ---------------------------------------------------------------------------

_BUNDLED_ROOT = os.path.dirname(__file__)
_KIND_SUBDIR = {"rig": "rig", "shapes": "shapes", "collections": "collections"}


def _documents_dir():
    """Tenta achar a pasta "Documentos" do usuário -- nome varia por
    idioma do sistema operacional. Tenta os nomes mais comuns (EN/PT-BR)
    e cai pra criar "Documents" (inglês) se nenhum existir ainda."""
    home = os.path.expanduser("~")
    candidates = ["Documents", "Documentos"]
    for name in candidates:
        path = os.path.join(home, name)
        if os.path.isdir(path):
            return path
    return os.path.join(home, candidates[0])


def user_templates_root():
    """Pasta raiz dos templates do usuário: Documentos/Hyblend/templates.
    Não garante que ela exista -- quem grava (save_rig_template /
    save_shape_template) cria com os.makedirs; quem só lê (discover)
    ignora silenciosamente se não existir ainda (usuário nunca salvou
    nada customizado)."""
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


# ---------------------------------------------------------------------------
# Discovery -- escaneia builtin + usuário, mescla (usuário vence em caso
# de template_name duplicado), cacheia em memória.
# ---------------------------------------------------------------------------

# {"rig": {name: {"data":..., "source": "builtin"|"user", "path":...}}, "shapes": {...}, "collections": {...}}
_cache = {"rig": {}, "shapes": {}, "collections": {}}

# Listas já prontas pro EnumProperty (ver comentário em
# translations/__init__.py sobre por que isso precisa ser cacheado num
# objeto estável em vez de reconstruído a cada chamada do callback).
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
    """"(none)" SEMPRE em primeiro -- não só quando a pasta está vazia
    -- pra dar pro usuário desmarcar a seleção de propósito (ex.: não
    quer aplicar nenhum template agora, só ver o dropdown "limpo"), em
    vez do dropdown cair sozinho no primeiro template real que existir.
    "NONE" nunca aparece em list_rig_templates()/list_shape_templates()/
    list_collection_templates() nem é resolvido por get_*_template() --
    é só um sentinel de UI, tratado explicitamente pelos operadores de
    Apply/Delete em rigger.py (ver _TEMPLATE_NONE lá)."""
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
    """Reescaneia as três pastas (rig/, shapes/ e collections/), builtin
    + usuário. Chamado uma vez na importação deste módulo e de novo por
    TEMPLATES_OT_reload (botão "Reload Templates")."""
    _discover("rig")
    _discover("shapes")
    _discover("collections")


def _ensure_loaded(kind):
    if not _cache[kind]:
        _discover(kind)


# ---------------------------------------------------------------------------
# API pública -- consumida por rigger.py
# ---------------------------------------------------------------------------


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
    RIG_OT_hytale_ik_chain_load_defaults (rigger.py)."""
    if not _cache["rig"]:
        _discover("rig")
    return _items_cache["rig"]


def shape_template_enum_items(self, context):
    """Mesma ideia, pro seletor de template de custom shape (usado por
    quem chamar -- hoje só a UI real, quando o chat da interface.py
    ligar um dropdown nele; RIG_OT_hytale_ik_chain_load_defaults já
    seleciona um shape template sozinho via armature.hytale_active_shape_template,
    sem precisar desse dropdown pro uso básico)."""
    if not _cache["shapes"]:
        _discover("shapes")
    return _items_cache["shapes"]


def save_rig_template(name, data):
    """Grava `data` (dict, mesmo schema de rig/<nome>.json) como
    Documentos/Hyblend/templates/rig/<name>.json. SEMPRE na pasta do
    usuário -- nunca sobrescreve um arquivo builtin (dentro do addon).
    Retorna o caminho final. Redescobre os templates de rig/ depois de
    salvar, pra aparecer no dropdown na hora."""
    directory = _user_dir("rig")
    os.makedirs(directory, exist_ok=True)
    data = dict(data)
    data["template_name"] = name
    path = os.path.join(directory, _safe_filename(name) + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _discover("rig")
    return path


def save_shape_template(name, data):
    """Mesma ideia de save_rig_template(), pra shapes/<name>.json."""
    directory = _user_dir("shapes")
    os.makedirs(directory, exist_ok=True)
    data = dict(data)
    data["template_name"] = name
    path = os.path.join(directory, _safe_filename(name) + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _discover("shapes")
    return path


# ---------------------------------------------------------------------------
# Collection Templates -- terceiro "kind" (rig/shapes/collections), mesmo
# padrão dos dois de cima. Schema -- collections/<name>.json:
#
# {
#   "template_name": "MyCustomCharacter",
#   "description": "...",
#   "collections": [                      // um item por bone collection CUSTOM
#     {
#       "name": "Tail",
#       "parent": "Main",                 // nome de outra collection deste mesmo
#                                          // template, de uma já existente no
#                                          // armature-alvo, ou null (nível raiz)
#       "bones": ["Tail_CTRL", "Tail_CTRL.001"]
#     }
#   ]
# }
#
# Ver RIG_OT_hytale_collection_template_save/_apply (rigger.py) pra quem
# lê/escreve isso de fato -- este módulo só faz I/O de arquivo, igual
# rig/shapes.
# ---------------------------------------------------------------------------


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
    directory = _user_dir("collections")
    os.makedirs(directory, exist_ok=True)
    data = dict(data)
    data["template_name"] = name
    path = os.path.join(directory, _safe_filename(name) + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _discover("collections")
    return path


# ---------------------------------------------------------------------------
# Delete -- comum aos três kinds. Só apaga templates da pasta do USUÁRIO;
# um builtin (dentro do addon) nunca é removível por aqui, pra não sumir
# sozinho numa atualização do addon nem precisar reinstalar pra
# recuperar (ver poll() dos operadores RIG_OT_hytale_*_template_delete
# em rigger.py, que já bloqueia a UI pra isso antes mesmo de chegar
# aqui -- esta função é a segunda linha de defesa).
# ---------------------------------------------------------------------------


def _delete_template(kind, name):
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


# ---------------------------------------------------------------------------
# Operadores utilitários (reload / abrir pasta) -- registrados por este
# próprio pacote, do mesmo jeito que translations/ registra
# TRANSLATIONS_OT_reload.
# ---------------------------------------------------------------------------


class TEMPLATES_OT_reload(bpy.types.Operator):
    """Reescaneia as pastas templates/rig/ e templates/shapes/ (builtin +
    Documentos/Hyblend/templates/) sem precisar reiniciar o Blender --
    útil enquanto você está editando/criando um template .json na mão e
    quer ver o resultado no dropdown na hora."""

    bl_idname = "hytale.reload_templates"
    bl_label = "Reload Templates"
    bl_description = "Rescan the templates folders for new or edited .json files"
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
    """Abre (ou cria, se ainda não existir) a pasta
    Documentos/Hyblend/templates/ no explorador de arquivos do sistema --
    pra facilitar editar/adicionar um .json na mão sem precisar procurar
    o caminho manualmente."""

    bl_idname = "hytale.open_templates_folder"
    bl_label = "Open Templates Folder"
    bl_description = "Open your Documents/Hyblend/templates folder in the file explorer"
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


# Escaneia já na importação do módulo, pelo mesmo motivo que
# translations/__init__.py faz isso -- os dropdowns (preset de IK chain,
# etc.) precisam ter algo pra mostrar assim que o painel desenhar pela
# primeira vez, sem esperar register().
reload()
