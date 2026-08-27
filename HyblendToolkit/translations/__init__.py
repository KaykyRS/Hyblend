"""
translations/__init__.py -- carregador de idiomas do HyblendToolkit.
======================================================================

Este pacote é o sistema de i18n do addon inteiro. Antes vivia espalhado
em duas cópias -- LABELS/get_language()/L() dentro de importer.py e
PANEL_LABELS/PL() dentro de interface.py, cada um cobrindo só o seu
próprio arquivo, com EN e PT_BR hardcoded direto no código Python.
Agora existe UM sistema só, orientado a arquivo em vez de a Enum fixo:

- Cada idioma é um ARQUIVO .py separado dentro desta pasta (en.py,
  pt_br.py, etc.), não uma entrada hardcoded numa lista. Duplicar um
  arquivo existente e traduzir só os VALUES do dicionário é suficiente
  pra criar um idioma novo -- ver o comentário no topo de en.py, que
  serve de template (é o idioma de referência, então é sempre o mais
  completo).
- Esta pasta é escaneada em tempo de execução (_discover(), abaixo):
  todo arquivo .py que não comece com "_" e que defina LANGUAGE_CODE +
  LANGUAGE_NAME + TRANSLATIONS vira uma opção no dropdown de idioma das
  Preferences do addon (HytaleImporterPreferences.language, em
  importer.py) automaticamente. Nenhum outro arquivo do addon precisa
  saber quantos ou quais idiomas existem -- é por isso que dá pra
  simplesmente duplicar um arquivo aqui dentro sem tocar em mais nada.
- As KEYS do dicionário TRANSLATIONS são namespaced por arquivo dono do
  texto (prefixo "importer." pras strings que vêm de importer.py,
  "panel." pras que vêm de interface.py, etc.) só por organização --
  pro sistema em si é tudo um dicionário plano só, chave -> texto.

## Usando isto de um submódulo que ainda não tem nenhuma string traduzida
(hoje: exporter.py, rigger.py, anim_importer.py)

1. `from .translations import tr, get_language`
2. No seu draw(), pegue `lang = get_language(context)` uma vez (mesmo
   padrão que importer.py e interface.py já usam) e troque texto fixo
   por `tr("exporter.minha_chave", lang)` -- escolha um prefixo próprio
   pro seu arquivo (ex.: "exporter.", "rigger."), pra não colidir com as
   keys de import/interface.
3. Adicione as keys novas em CADA arquivo de idioma que já existir hoje
   (en.py, pt_br.py) -- pelo menos em en.py, que é o fallback. Não
   precisa traduzir em todos de uma vez: tr() cai pro Inglês sozinho se
   a key não existir no idioma escolhido (ver docstring de tr() abaixo),
   então um idioma "incompleto" não quebra nada, só mostra mais texto em
   Inglês até alguém completar a tradução.
Isso é decisão de cada chat/arquivo, não precisa ser feito tudo de uma
vez -- migrar importer.py e interface.py pra esse sistema (o que este
chat já fez) não obriga os outros três a migrar junto.

## Tooltips dinâmicos (v0.14 -- resolve a limitação antiga, ver nota no fim)

Dois problemas diferentes, duas ferramentas diferentes -- os dois vivem
SÓ aqui (a "parte pesada"); cada arquivo dono de UI só chama a função
pronta, sem duplicar lógica nenhuma:

### 1. Tooltip de botão (bl_description de Operator) -- `tooltip(key)`

O Blender tem um hook nativo pra isso: um Operator pode definir
`description(cls, context, properties)` como classmethod, chamado a
CADA hover (dinâmico de verdade, sem re-registro, sem custo). `tooltip()`
devolve esse classmethod já pronto:

    from .translations import tooltip

    class RIG_OT_hytale_mirror_shape(Operator):
        bl_idname = "armature.hytale_mirror_shape"
        bl_label = "Mirror Shape"
        description = tooltip("rigger.tooltip.mirror_shape")
        ...

Não precisa mais de `bl_description = "..."` nenhum -- o texto (só em
Inglês é obrigatório; outros idiomas são opcionais, tr() cai pro
Inglês sozinho) mora exclusivamente na key nova em translations/en.py.

### 2. Tooltip de campo (description= de bpy.props.*Property) --
`localized_props` + `register_localized_class`/`unregister_localized_class`

Esse caso NÃO tem hook nativo -- o Blender resolve `description=` na
hora do `bpy.utils.register_class()`, não a cada redraw. O único jeito
real de mudar isso sem reiniciar o Blender é RE-REGISTRAR a classe
(unregister + register) toda vez que o idioma mudar, reconstruindo as
properties com o `tr()` do idioma novo. Isso NÃO perde nenhum dado já
salvo no `.blend` (inclusive listas como `hytale_ik_chains`) -- é a
mesma classe Python (mesma identidade de objeto) sendo re-registrada,
só a description muda; o Blender guarda o dado da property pelo
NOME/TIPO, não pela instância de registro.

Uso -- em vez de anotações soltas no corpo da classe, todas as
properties (mesmo as sem tooltip, tipo um EnumProperty com items fixos)
vão dentro de uma função `_props(lang)` que devolve o dict completo:

    from .translations import localized_props, tr

    def _mirror_shape_props(lang):
        return {
            "axis": EnumProperty(
                name="Axis",
                description=tr("rigger.prop.mirror_shape.axis", lang),
                items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
            ),
        }

    @localized_props(_mirror_shape_props)
    class RIG_OT_hytale_mirror_shape(Operator):
        ...  # SEM properties soltas no corpo -- todas vêm de _props()

E no register()/unregister() do arquivo, trocar
`bpy.utils.register_class(cls)`/`unregister_class(cls)` por
`translations.register_localized_class(cls)`/`unregister_localized_class(cls)`
-- pra TODA classe do arquivo, decorada ou não (funciona nos dois
casos; numa classe sem `@localized_props` vira só um register/unregister
normal por baixo dos panos, sem custo nem risco extra).

Isso vale tanto pra `PropertyGroup` quanto pra `Operator` (as
properties de um Operator também aparecem, com tooltip, no painel
"Adjust Last Operation" depois de rodar) e pra `AddonPreferences`.

## Como migrar um arquivo que ainda não usa nada disto

1. Trocar cada `bl_description = "..."` de Operator por
   `description = tooltip("<arquivo>.tooltip.<nome>")` (remove o
   `bl_description`, não precisa dos dois).
2. Pra cada property com `description=` texto fixo: mover a
   declaração inteira (e as vizinhas da mesma classe, mesmo sem
   tooltip) pra dentro de uma função `_algo_props(lang)`, decorar a
   classe com `@localized_props(_algo_props)`, trocar `description=`
   fixo por `tr("<arquivo>.prop.<nome>", lang)`.
3. Trocar as chamadas de `bpy.utils.register_class`/`unregister_class`
   dessas classes (só essas -- as que não têm nenhum tooltip pra
   traduzir podem continuar como estavam, ou também trocar por
   uniformidade, tanto faz) por
   `register_localized_class`/`unregister_localized_class`.
4. Adicionar as keys novas em `translations/en.py` (obrigatório,
   fallback) -- `pt_br.py` é opcional, cai pro Inglês sozinho.
5. Testar de verdade dentro do Blender: mudar o idioma nas Preferences
   do addon e conferir que o tooltip do botão/campo mudou SEM precisar
   de Reload Scripts.
6. CASO ESPECIAL -- se uma classe @localized_props for o alvo de um
   type= usado em outro lugar via atribuição direta fora do ciclo
   normal de register_class (ex.: `Armature.minha_prop =
   PointerProperty(type=MinhaClasse)` ou `CollectionProperty(type=...)`
   feito manualmente no register() do arquivo): extraia essa atribuição
   pra uma função nomeada, chame ela normalmente dentro do register()
   (como já era feito), e REGISTRE ela também com
   `register_refresh_hook(essa_funcao)`/`unregister_refresh_hook(...)`
   no register()/unregister() do arquivo -- ver exporter.py
   (`_redo_armature_property_assignments`) pra um exemplo completo.
   Sem isso, o refresh ainda re-registra a PropertyGroup em si
   corretamente, mas a atribuição EXTERNA (na Armature, no caso) pode
   ficar apontando pro RNA struct antigo.

## Nota histórica (resolvido nesta versão)

Até v0.13.x, tooltip de property ficava fixo em Inglês (limitação real
do Blender, não regressão) -- documentado aqui antes. `localized_props`
acima resolve isso via re-registro, mantendo o idioma deste addon
INDEPENDENTE do idioma geral do Blender (Edit > Preferences >
Interface > Language) -- de propósito, não migramos pro sistema nativo
`bpy.app.translations.register()`, que amarraria os dois.
"""
import importlib
import os

import bpy

from ..common import ADDON_PACKAGE

_PACKAGE = __package__
_DIR = os.path.dirname(__file__)

# Código do idioma que serve de fallback quando uma key não existe no
# idioma escolhido pelo usuário. Também é o único arquivo que É OBRIGADO
# a existir (en.py) -- os outros são opcionais/plugáveis.
_FALLBACK_CODE = "EN"

# {code: {"name": .., "labels": {...}, "filename": ..}}
_languages = {}

# Lista de items já pronta pro EnumProperty -- ver comentário em
# get_language_items() sobre por que isso precisa ser cacheado num
# objeto estável em vez de reconstruído a cada chamada.
_items_cache = []


def _rebuild_items_cache():
    global _items_cache
    codes = sorted(_languages.keys(), key=lambda c: (c != _FALLBACK_CODE, _languages[c]["name"]))
    _items_cache = [(code, _languages[code]["name"], "") for code in codes] or [("EN", "English", "")]


def _discover():
    """Escaneia translations/*.py e reconstrói o registro de idiomas do
    zero. Chamado uma vez na importação deste módulo (ver fundo do
    arquivo) e de novo por TRANSLATIONS_OT_reload (botão "Reload
    Translations" nas Preferences do addon) -- útil pra testar um
    arquivo de idioma novo/editado sem reiniciar o Blender inteiro."""
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
    """Callback de items= pro EnumProperty de idioma
    (importer.HytaleImporterPreferences.language). Tem que devolver
    sempre o MESMO objeto de lista cacheado (_items_cache) em vez de
    construir uma lista nova a cada chamada -- é um bug conhecido de
    EnumProperty dinâmico no Blender/Python: se as strings dos items não
    tiverem uma referência viva em algum lugar fora desta função, o
    Blender pode crashar ao tentar ler um item depois que o Python já
    coletou a lista antiga como lixo."""
    if not _languages:
        _discover()
    return _items_cache


def get_language(context):
    """Lê a preference de idioma do addon
    (context.preferences.addons[ADDON_PACKAGE].preferences.language),
    com fallback pro Inglês se a preference não existir ainda (addon
    recém-instalado) ou apontar pra um código de idioma que não existe
    mais (ex.: usuário tinha um arquivo de idioma customizado e
    apagou/renomeou ele)."""
    if not _languages:
        _discover()
    try:
        prefs = context.preferences.addons[ADDON_PACKAGE].preferences
        lang = prefs.language
    except Exception:
        return _FALLBACK_CODE
    return lang if lang in _languages else _FALLBACK_CODE


def tr(key, lang):
    """Traduz `key` pro idioma `lang`. Se a key não existir no idioma
    pedido, cai pro Inglês (_FALLBACK_CODE). Se nem o Inglês tiver essa
    key, devolve a própria key crua -- fica óbvio no painel que falta
    registrar/traduzir aquele texto, em vez de mostrar em branco ou
    quebrar o draw()."""
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
    """Devolve um classmethod `description(cls, context, properties)`
    pronto pra usar como `description = tooltip("arquivo.tooltip.foo")`
    dentro do corpo de um Operator -- ver seção "Tooltip de botão" no
    topo deste arquivo. Roda a CADA hover (hook nativo do Blender,
    `Operator.description`), então é dinâmico de verdade, sem precisar
    de re-registro nenhum -- diferente de `localized_props` abaixo, que
    existe só porque bpy.props.*Property (campo, não botão) NÃO tem
    esse hook."""

    def _description(cls, context, properties):
        return tr(key, get_language(context))

    return classmethod(_description)


# Classes decoradas com @localized_props, na ordem em que foram
# registradas -- refresh_localized_properties() percorre esta lista
# quando o idioma muda. Guardamos a CLASSE em si (não só o builder),
# porque é ela que precisa ser unregister/register de novo.
_localized_classes = []


def localized_props(builder):
    """Decorator pra Operator/PropertyGroup/AddonPreferences que tem
    pelo menos um campo com tooltip traduzido. `builder(lang)` deve
    devolver o dict COMPLETO de properties da classe (mesmo as sem
    tooltip -- ver exemplo na seção "Tooltip de campo" no topo deste
    arquivo), porque `register_localized_class()`/
    `refresh_localized_properties()` substituem `cls.__annotations__`
    inteiro por esse dict a cada (re)registro. Não registra nada
    sozinho -- só marca a classe; quem registra de verdade é
    `register_localized_class()`."""

    def _decorator(cls):
        cls._i18n_props_builder = staticmethod(builder)
        return cls

    return _decorator


def register_localized_class(cls):
    """Substitui bpy.utils.register_class(cls) em qualquer arquivo que
    tenha ao menos uma classe usando @localized_props -- funciona
    também pra classe SEM o decorator (vira um register_class() puro,
    sem custo/risco extra), então um arquivo pode trocar TODAS as
    chamadas por esta de uma vez, por uniformidade, sem precisar
    separar "quais classes têm tooltip traduzido" na hora de
    registrar."""
    builder = getattr(cls, "_i18n_props_builder", None)
    if builder is not None:
        cls.__annotations__ = dict(builder(get_language(bpy.context)))
        if cls not in _localized_classes:
            _localized_classes.append(cls)
    bpy.utils.register_class(cls)


def unregister_localized_class(cls):
    """Contraparte de register_localized_class() -- sempre em par,
    mesma ordem invertida que bpy.utils.unregister_class já pede
    normalmente."""
    bpy.utils.unregister_class(cls)
    if cls in _localized_classes:
        _localized_classes.remove(cls)


def refresh_localized_properties(context):
    """Chamado pelo update= da property de idioma
    (HytaleImporterPreferences.language, em importer.py) toda vez que o
    usuário troca o idioma do addon nas Preferences -- e também pelo
    botão "Reload Translations" (TRANSLATIONS_OT_reload, abaixo), pra
    um tooltip editado num arquivo de idioma aparecer sem reiniciar o
    Blender. Re-registra (unregister + register, na hora, mesma
    identidade de classe Python) toda classe marcada com
    @localized_props no idioma NOVO -- é o único jeito real de mudar um
    tooltip de property sem reiniciar o Blender (ver "Tooltip de campo"
    no topo deste arquivo pro motivo). Não apaga dado nenhum já salvo
    no .blend: o Blender guarda o valor de uma property pelo NOME/TIPO,
    não pela instância de registro, então uma CollectionProperty com
    dado real (ex.: armature.hytale_ik_chains) sobrevive intacta.

    Depois de re-registrar todas as classes, roda os _post_refresh_hooks
    (ver register_refresh_hook abaixo) -- necessário pra classe
    @localized_props que é alvo de um type= usado em OUTRO lugar via
    atribuição direta (ex.: exporter.py:
    `Armature.hytale_export_settings = PointerProperty(type=HYTALE_export_settings)`,
    feita manualmente no register() do arquivo dono, fora do ciclo
    normal de register_class/unregister_class)."""
    lang = get_language(context)
    for cls in list(_localized_classes):
        builder = getattr(cls, "_i18n_props_builder", None)
        if builder is None:
            continue
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            # Já desregistrada (ex.: addon sendo desligado no meio de
            # um refresh) -- ignora e tenta registrar de novo mesmo
            # assim, não deveria acontecer em uso normal.
            pass
        cls.__annotations__ = dict(builder(lang))
        bpy.utils.register_class(cls)

    for hook in list(_post_refresh_hooks):
        try:
            hook()
        except Exception as exc:
            print(f"[HyblendToolkit] Erro num refresh hook de tradução ({hook}): {exc}")


# Callables sem argumento, chamados no fim de refresh_localized_properties()
# -- ver register_refresh_hook() abaixo.
_post_refresh_hooks = []


def register_refresh_hook(fn):
    """Registra `fn` (sem argumentos) pra rodar toda vez que
    refresh_localized_properties() terminar de re-registrar as classes
    @localized_props. Existe pra quando uma classe @localized_props é o
    ALVO de um type= usado em outro lugar via atribuição direta fora do
    ciclo normal de register_class/unregister_class -- ex.:
    `Armature.hytale_export_settings = PointerProperty(type=HYTALE_export_settings)`
    (exporter.py) ou uma CollectionProperty equivalente em rigger/rig.py.
    Só re-registrar a PropertyGroup em si (unregister_class +
    register_class) pode não bastar pra essa atribuição EXTERNA
    continuar apontando pro RNA struct certo -- refazer essa atribuição
    aqui garante que sim, sem o arquivo dono da classe precisar saber
    QUANDO um refresh de idioma acontece. Chame de dentro do register()
    do arquivo, com a MESMA função usada lá pra fazer a atribuição a
    primeira vez (ver exporter.py pra um exemplo completo)."""
    if fn not in _post_refresh_hooks:
        _post_refresh_hooks.append(fn)


def unregister_refresh_hook(fn):
    """Contraparte de register_refresh_hook() -- chamar no unregister()
    do arquivo, com a MESMA referência de função passada antes."""
    if fn in _post_refresh_hooks:
        _post_refresh_hooks.remove(fn)


def available_languages():
    """{code: nome_de_exibição} de todo idioma carregado -- pra quem
    precisar listar idiomas fora do dropdown (log, mensagem de erro)."""
    if not _languages:
        _discover()
    return {code: info["name"] for code, info in _languages.items()}


class TRANSLATIONS_OT_reload(bpy.types.Operator):
    """Reescaneia a pasta translations/ sem precisar reiniciar o Blender
    nem rodar Reload Scripts do addon inteiro -- útil enquanto você está
    duplicando/editando um arquivo de idioma novo e quer ver o resultado
    no painel na hora."""

    bl_idname = "hytale.reload_translations"
    bl_label = "Reload Translations"
    bl_options = {"REGISTER"}

    def execute(self, context):
        _discover()
        # v0.14 -- também re-registra toda classe @localized_props no
        # idioma atual, senão editar um tooltip de CAMPO (property) num
        # arquivo de idioma e clicar aqui não mostraria a mudança (só
        # os tooltips de BOTÃO, via tooltip()/description(), já eram
        # dinâmicos sem precisar disto).
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


# Escaneia a pasta já na importação do módulo, pra get_language_items()
# ter algo pra mostrar assim que o Blender desenhar o painel de
# Preferences pela primeira vez (não dá pra esperar register(), que só
# roda depois -- e nem faria diferença, register() aqui só cuida do
# operador de reload).
_discover()
