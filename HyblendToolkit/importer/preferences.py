"""importer/preferences.py -- Preferences do addon (idioma da interface).

bl_idname aponta pra ADDON_PACKAGE (pacote raiz), não __name__ -- ver
DEVELOPER_NOTES, seção "Preferences e __name__"."""


import bpy
from bpy.props import EnumProperty
from bpy.types import AddonPreferences

from ..common import (
    ADDON_PACKAGE,
)
from ..translations import (
    get_language,
    get_language_items,
    localized_props,
    refresh_localized_properties,
    tr,
)


def _on_language_update(self, context):
    """update= de HytaleImporterPreferences.language -- dispara o
    re-registro de toda classe @localized_props (de qualquer arquivo do
    addon) no idioma novo (ver refresh_localized_properties em
    translations/__init__.py pro porquê tooltip de property não é
    dinâmico por redraw como o de botão).

    Agendado via bpy.app.timers em vez de chamado direto: estamos
    dentro do update() da property "language", que pertence à própria
    HytaleImporterPreferences -- e essa classe também está em
    @localized_props, então refresh_localized_properties vai
    desregistrar/re-registrar ela mesma. Fazer isso síncrono, ainda
    dentro do callback disparado pela escrita dessa mesma property, é
    reentrância arriscada -- por isso adiamos pro próximo tick do loop
    de eventos."""

    def _do_refresh():
        refresh_localized_properties(bpy.context)
        return None  # não repete (timer de disparo único)

    bpy.app.timers.register(_do_refresh, first_interval=0.0)


def _importer_preferences_props(lang):
    return {
        # items=get_language_items é uma FUNÇÃO (callback), não uma lista
        # fixa -- é o que permite qualquer arquivo novo dentro de
        # translations/ aparecer aqui sem precisar editar este arquivo.
        # Efeito colateral: EnumProperty com items dinâmico não aceita
        # default= (o Blender não tem como saber o valor default antes
        # de rodar o callback) -- por isso não tem default= aqui;
        # get_language() (translations/__init__.py) já cai pro Inglês
        # sozinho caso o valor salvo seja inválido/vazio.
        "language": EnumProperty(
            name="Language / Idioma",
            description=tr("importer.prefs_language_tooltip", lang),
            items=get_language_items,
            update=_on_language_update,
        ),
    }


@localized_props(_importer_preferences_props)
class HytaleImporterPreferences(AddonPreferences):
    # Tem que ser o nome do PACOTE raiz (ver common.ADDON_PACKAGE), não
    # __name__ deste submódulo -- senão o Blender não acha essas
    # preferences em context.preferences.addons[...].
    bl_idname = ADDON_PACKAGE

    def draw(self, context):
        lang = get_language(context)
        row = self.layout.row(align=True)
        row.prop(self, "language", text=tr("importer.prefs_language", lang))
        row.operator(
            "hytale.reload_translations",
            text=tr("importer.prefs_reload_translations", lang),
            icon="FILE_REFRESH",
        )
