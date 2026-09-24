"""translations/__init__.py -- carregador de idiomas do HyblendToolkit.

Cada idioma é um arquivo .py separado nesta pasta (en.py, pt_br.py,
etc.) definindo LANGUAGE_CODE + LANGUAGE_NAME + TRANSLATIONS (dict
plano, chave -> texto). A pasta é escaneada em tempo de execução
(_discover()) -- duplicar um arquivo existente e traduzir os values é
suficiente pra criar um idioma novo, sem tocar em mais nada. Keys são
namespaced por arquivo dono do texto (prefixo "importer.", "panel.",
etc.) só por organização.

## Tooltips dinâmicos -- dois mecanismos diferentes

**1. Tooltip de botão** (`bl_description` de Operator) -- `tooltip(key)`.
O Blender chama `Operator.description(cls, context, properties)` a
cada hover, então isso já é dinâmico nativamente:

    description = tooltip("rigger.tooltip.mirror_shape")

**2. Tooltip de campo** (`description=` de bpy.props.*Property) --
`localized_props` + `register_localized_class`/`unregister_localized_class`.
Esse caso não tem hook nativo: o Blender resolve `description=` na
hora do `register_class()`, não a cada redraw. O único jeito de trocar
sem reiniciar o Blender é re-registrar a classe (mesma identidade de
objeto Python) com as properties reconstruídas no idioma novo -- isso
não perde dado salvo no .blend, já que o Blender guarda o valor pelo
nome/tipo da property, não pela instância de registro.

Todas as properties da classe (mesmo sem tooltip) vão dentro de uma
função `_props(lang)` que devolve o dict completo:

    def _mirror_shape_props(lang):
        return {"axis": EnumProperty(description=tr("rigger.prop.mirror_shape.axis", lang), ...)}

    @localized_props(_mirror_shape_props)
    class RIG_OT_hytale_mirror_shape(Operator):
        ...  # sem properties soltas no corpo

E trocar `bpy.utils.register_class`/`unregister_class` por
`register_localized_class`/`unregister_localized_class` no register()/
unregister() do arquivo (funciona também em classe sem o decorator,
vira um register_class puro).

Caso especial: se uma classe @localized_props for alvo de um `type=`
usado em outro lugar por atribuição direta fora do ciclo normal de
register_class (ex.: `Armature.minha_prop = PointerProperty(type=X)`
no register() de outro arquivo), registre essa atribuição também com
`register_refresh_hook()` -- senão ela fica apontando pro RNA struct
antigo depois de um refresh de idioma (ver exporter.py,
`_redo_armature_property_assignments`, pra um exemplo)."""
import importlib
import os

import bpy

from ..common import ADDON_PACKAGE

_PACKAGE = __package__
_DIR = os.path.dirname(__file__)

# Idioma de fallback quando uma key não existe no idioma escolhido.
# Único arquivo obrigatório (en.py) -- os outros são opcionais/plugáveis.
_FALLBACK_CODE = "EN"

# {code: {"name": .., "labels": {...}, "filename": ..}}
_languages = {}

# Lista de items já pronta pro EnumProperty -- cacheada num objeto
# estável (não reconstruída a cada chamada, ver get_language_items()).
_items_cache = []


def _rebuild_items_cache():
    global _items_cache
    codes = sorted(_languages.keys(), key=lambda c: (c != _FALLBACK_CODE, _languages[c]["name"]))
    _items_cache = [(code, _languages[code]["name"], "") for code in codes] or [("EN", "English", "")]


def _discover():
    """Escaneia translations/*.py e reconstrói o registro do zero.
    Chamado na importação deste módulo e de novo por
    TRANSLATIONS_OT_reload."""
    global _languages
    _languages = {}

    if os.path.isdir(_DIR):
        for filename in sorted(os.listdir(_DIR)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            modname = filename[:-3]
            try:
                module = importlib.import_module(f".{modname}", _PACKAGE)
                module = importlib.reload(module)
            except Exception as exc:
                print(f"[HyblendToolkit] Falha ao carregar '{filename}' em translations/: {exc}")
                continue

            code = getattr(module, "LANGUAGE_CODE", None)
            name = getattr(module, "LANGUAGE_NAME", None)
            labels = getattr(module, "TRANSLATIONS", None)
            if not code or not name or not isinstance(labels, dict):
                print(
                    f"[HyblendToolkit] '{filename}' em translations/ não define "
                    "LANGUAGE_CODE/LANGUAGE_NAME/TRANSLATIONS válidos -- ignorado."
                )
                continue

            _languages[code] = {"name": name, "labels": labels, "filename": filename}

    if _FALLBACK_CODE not in _languages:
        print(
            f"[HyblendToolkit] Aviso: nenhum arquivo com LANGUAGE_CODE = "
            f"'{_FALLBACK_CODE}' encontrado em translations/ -- keys ausentes "
            "em outros idiomas vão aparecer cruas em vez de cair pro Inglês."
        )

    _rebuild_items_cache()


def get_language_items(self, context):
    """Callback de items= pro EnumProperty de idioma. Devolve sempre o
    mesmo objeto de lista cacheado -- bug conhecido de EnumProperty
    dinâmico: sem uma referência viva fora desta função, o Blender pode
    crashar ao ler um item depois do Python coletar a lista como lixo."""
    if not _languages:
        _discover()
    return _items_cache


def get_language(context):
    """Lê a preference de idioma do addon, com fallback pro Inglês se
    não existir ainda ou apontar pra um código que não existe mais."""
    if not _languages:
        _discover()
    try:
        prefs = context.preferences.addons[ADDON_PACKAGE].preferences
        lang = prefs.language
    except Exception:
        return _FALLBACK_CODE
    return lang if lang in _languages else _FALLBACK_CODE


def tr(key, lang):
    """Traduz `key` pro idioma `lang`. Cai pro Inglês se a key não
    existir nesse idioma; devolve a própria key crua se nem o Inglês
    tiver -- fica óbvio no painel que falta traduzir, em vez de quebrar."""
    if not _languages:
        _discover()

    entry = _languages.get(lang)
    if entry and key in entry["labels"]:
        return entry["labels"][key]

    fallback = _languages.get(_FALLBACK_CODE)
    if fallback and key in fallback["labels"]:
        return fallback["labels"][key]

    return key


def tooltip(key):
    """Devolve um classmethod description(cls, context, properties)
    pronto pra `description = tooltip("arquivo.tooltip.foo")` num
    Operator. Roda a cada hover (hook nativo do Blender)."""

    def _description(cls, context, properties):
        return tr(key, get_language(context))

    return classmethod(_description)


# Classes decoradas com @localized_props, na ordem em que foram
# registradas -- refresh_localized_properties() percorre esta lista.
_localized_classes = []


def localized_props(builder):
    """Decorator pra Operator/PropertyGroup/AddonPreferences com pelo
    menos um campo com tooltip traduzido. `builder(lang)` devolve o
    dict completo de properties da classe -- register_localized_class()/
    refresh_localized_properties() substituem cls.__annotations__
    inteiro por esse dict a cada (re)registro. Não registra nada
    sozinho, só marca a classe."""

    def _decorator(cls):
        cls._i18n_props_builder = staticmethod(builder)
        return cls

    return _decorator


def register_localized_class(cls):
    """Substitui bpy.utils.register_class(cls) -- funciona também numa
    classe sem @localized_props (vira um register_class puro)."""
    builder = getattr(cls, "_i18n_props_builder", None)
    if builder is not None:
        cls.__annotations__ = dict(builder(get_language(bpy.context)))
        if cls not in _localized_classes:
            _localized_classes.append(cls)
    bpy.utils.register_class(cls)


def unregister_localized_class(cls):
    bpy.utils.unregister_class(cls)
    if cls in _localized_classes:
        _localized_classes.remove(cls)


def refresh_localized_properties(context):
    """Chamado quando o usuário troca o idioma nas Preferences (e por
    "Reload Translations"). Re-registra toda classe @localized_props no
    idioma novo -- único jeito de trocar um tooltip de property sem
    reiniciar o Blender. Não apaga dado salvo (o Blender guarda pelo
    nome/tipo da property, não pela instância de registro).

    Depois de re-registrar, roda os _post_refresh_hooks -- necessário
    pra uma classe @localized_props que é alvo de um type= usado em
    outro lugar por atribuição direta fora do ciclo normal de
    register_class (ver register_refresh_hook)."""
    lang = get_language(context)
    for cls in list(_localized_classes):
        builder = getattr(cls, "_i18n_props_builder", None)
        if builder is None:
            continue
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass  # já desregistrada (ex.: addon sendo desligado no meio de um refresh)
        cls.__annotations__ = dict(builder(lang))
        bpy.utils.register_class(cls)

    for hook in list(_post_refresh_hooks):
        try:
            hook()
        except Exception as exc:
            print(f"[HyblendToolkit] Erro num refresh hook de tradução ({hook}): {exc}")


# Callables sem argumento, chamados no fim de refresh_localized_properties().
_post_refresh_hooks = []


def register_refresh_hook(fn):
    """Registra `fn` (sem argumentos) pra rodar toda vez que
    refresh_localized_properties() termina de re-registrar as classes.
    Existe pra quando uma classe @localized_props é alvo de um type=
    usado em outro lugar por atribuição direta (ex.:
    `Armature.hytale_export_settings = PointerProperty(type=X)` em
    exporter.py) -- só re-registrar a PropertyGroup pode não bastar pra
    essa atribuição externa continuar apontando pro RNA struct certo.
    Chame de dentro do register() do arquivo dono."""
    if fn not in _post_refresh_hooks:
        _post_refresh_hooks.append(fn)


def unregister_refresh_hook(fn):
    if fn in _post_refresh_hooks:
        _post_refresh_hooks.remove(fn)


def available_languages():
    """{code: nome_de_exibição} de todo idioma carregado."""
    if not _languages:
        _discover()
    return {code: info["name"] for code, info in _languages.items()}


class TRANSLATIONS_OT_reload(bpy.types.Operator):
    """Reescaneia a pasta translations/ sem precisar reiniciar o Blender."""

    bl_idname = "hytale.reload_translations"
    bl_label = "Reload Translations"
    bl_options = {"REGISTER"}

    def execute(self, context):
        _discover()
        # Também re-registra toda classe @localized_props no idioma
        # atual, senão editar um tooltip de campo não apareceria aqui
        # (só os tooltips de botão já eram dinâmicos sem isso).
        refresh_localized_properties(context)
        names = ", ".join(sorted(info["name"] for info in _languages.values())) or "-"
        self.report({"INFO"}, f"HyblendToolkit: {len(_languages)} idioma(s) carregado(s) -- {names}")
        return {"FINISHED"}


_CLASSES = (TRANSLATIONS_OT_reload,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


# Escaneia já na importação -- get_language_items() precisa ter algo
# pra mostrar assim que o painel de Preferences desenhar, sem esperar register().
_discover()
