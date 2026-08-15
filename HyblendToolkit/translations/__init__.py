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

## Limitação conhecida (herdada do sistema antigo, não é regressão)

O tooltip (hover) de uma bpy.props.*Property -- o parâmetro
`description=` -- fica fixo em Inglês, porque o Blender resolve esse
texto no momento em que a CLASSE é registrada, não a cada redraw do
painel. Só o texto visível (label de botão, cabeçalho de box, hint,
mensagem de self.report()) troca de idioma dinamicamente, porque esses
passam de novo por draw()/execute() a cada interação do usuário.
Contornar isso de verdade exigiria migrar pro sistema
`bpy.app.translations.register()` nativo do Blender, que amarra no
idioma GERAL da interface do Blender (Edit > Preferences > Interface >
Language) -- ficou de fora de propósito, pra manter o idioma deste
addon independente do idioma do Blender como um todo. Se um dia isso
for decidido, avise explicitamente: é mudança que afeta todos os
arquivos de uma vez, do mesmo jeito que mudar `common.py`.
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
