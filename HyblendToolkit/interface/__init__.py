"""interface.py -- painel lateral (N-Panel) do HytaleBlockyToolkit.

Não tem lógica de import/export/rig nenhuma -- só desenha botões que
chamam os operadores que já existem em importer/, exporter/, rigger/ e
templates/. Se um botão precisar de um operador que ainda não existe,
ele nasce no arquivo correspondente, não aqui.

Usa get_language()/tr() de translations/ pra que a preference de idioma
afete o painel inteiro. Keys próprias deste painel vivem em
translations/*.py com o prefixo "panel.".

Nomes de aba (TAB_ITEMS) ficam só em inglês de propósito: são itens de
EnumProperty, fixados no registro da classe."""

import os

import blf
import bpy
import bpy.utils.previews
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Menu, Panel, WindowManager

from ..exporter import (
    EXPORT_OT_hytale_blockyanim,
    EXPORT_OT_hytale_blockymodel,
    EXPORT_OT_hytale_fbx_model,
    EXPORT_OT_hytale_fbx_anim,
    EXPORT_OT_texture_picker_export_add,
    EXPORT_OT_texture_picker_export_remove,
)
from ..importer import IMPORT_OT_hytale_bbmodel, IMPORT_OT_hytale_bedrock_model, IMPORT_OT_hytale_blockymodel
from ..anim import (
    ANIM_OT_hytale_keyframe_switch,
    ANIM_OT_hytale_set_fk_ik,
    ANIM_OT_hytale_set_head_follow,
    ANIM_OT_hytale_snap_selected,
    IMPORT_OT_hytale_blockyanim,
    get_fk_ik_state,
    get_head_follow_state,
)
from ..common import HYTALE_OT_pick_bone_into_field, is_active_armature
from ..translations import get_language, tr
from ..rigger.helpers import control_name
from ..rigger.rename import RIG_OT_hytale_rename_bones, RIG_OT_hytale_revert_bone_names, rename_toggle_prop
from ..rigger import (
    RIG_MT_hytale_clear_generated_menu,
    RIG_MT_hytale_ik_chain_add_menu,
    RIG_OT_hytale_bone_collection_add,
    RIG_OT_hytale_bone_collection_load_defaults,
    RIG_OT_hytale_bone_collection_move,
    RIG_OT_hytale_bone_collection_remove,
    RIG_OT_hytale_bone_collection_reset_grid,
    RIG_OT_hytale_camera_create,
    RIG_OT_hytale_camera_remove,
    RIG_OT_hytale_collection_template_apply,
    RIG_OT_hytale_collection_template_delete,
    RIG_OT_hytale_collection_template_save,
    RIG_OT_hytale_generate_rig,
    RIG_OT_hytale_ik_chain_auto_detect,
    RIG_OT_hytale_ik_chain_load_defaults,
    RIG_OT_hytale_ik_chain_move,
    RIG_OT_hytale_ik_chain_pick_bone,
    RIG_OT_hytale_ik_chain_remove,
    RIG_OT_hytale_mirror_shape,
    RIG_OT_hytale_texture_picker_create,
    RIG_OT_hytale_texture_picker_remove,
    RIG_OT_hytale_rig_template_delete,
    RIG_OT_hytale_rig_template_save,
    RIG_OT_hytale_shape_edit_mode_enter,
    RIG_OT_hytale_shape_edit_mode_finish,
    RIG_OT_hytale_shape_edit_mode_reselect,
    RIG_OT_hytale_shape_template_apply,
    RIG_OT_hytale_shape_template_delete,
    RIG_OT_hytale_shape_template_save,
    RIG_OT_hytale_shape_vertex_edit_mode_enter,
    RIG_OT_hytale_shape_vertex_edit_mode_finish,
    RIG_OT_hytale_use_selected_as_widget,
    RIG_OT_hytale_validate_rig,
    SUFFIX_CTRL,
    SUFFIX_IK,
    _collection_sort_key,
    _iter_sections_in_order,
    _resolve_collection_section_name,
    find_armature_stuck_in_shape_edit_mode,
)
from ..templates import TEMPLATES_OT_open_user_folder, TEMPLATES_OT_reload

# --- Aba "Info" -- créditos/links ---
# String vazia = botão correspondente fica desabilitado no painel (ver _draw_info).
HYBLEND_PATREON_URL = "https://www.patreon.com/cw/kaayky"
HYBLEND_NEXUSMODS_URL = "https://www.nexusmods.com/hytale/mods/164"
HYBLEND_GITHUB_URL = "https://github.com/KaykyRS/Hyblend"
HYBLEND_AUTHOR_NAME = "Kaayky (Ká)"
HYBLEND_AUTHOR_INSTAGRAM_URL = "https://www.instagram.com/kaayky_r.s/"
HYBLEND_AUTHOR_TWITTER_URL = "https://x.com/kaayky_anim"
HYBLEND_AUTHOR_YOUTUBE_URL = "https://www.youtube.com/@KaaykyRS"
# Site oficial do Hytale (Hypixel Studios) -- crédito, não patrocínio/afiliação.
HYBLEND_HYTALE_URL = "https://hytale.com"

# Ícones customizados -- Blender não tem ícone de marca no set embutido.
# Carregados via bpy.utils.previews (jeito padrão pra ícone customizado
# em botão, vira icon_value= em vez de icon=). Coloque os PNGs em
# HyblendToolkit/assets/icons/ com esses nomes exatos. Se um arquivo não
# existir, _draw_info cai pro ícone genérico pra esse botão (ver
# _panel_icon_value()).
_PANEL_ICON_FILES = {
    "instagram": "instagram.png",
    "twitter_x": "twitter_x.png",
    "youtube": "youtube.png",
    "hytale": "hytale.png",
    "patreon": "patreon.png",
    "nexus_mods": "nexus_mods.png",
    "github": "github.png",
}
_panel_icons_pcoll = None


def _load_panel_icons():
    """Carrega os PNGs de assets/icons/ num preview collection. Silencioso
    se a pasta/arquivo não existir (permite trabalhar sem os ícones ainda)."""
    global _panel_icons_pcoll
    pcoll = bpy.utils.previews.new()
    # assets/ fica na RAIZ do addon (irmã de interface/, rigger/, etc.),
    # não dentro de interface/ -- precisa subir um nível a partir deste
    # arquivo (interface/__init__.py) antes de descer em assets/icons/.
    addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    icons_dir = os.path.join(addon_root, "assets", "icons")
    for key, filename in _PANEL_ICON_FILES.items():
        path = os.path.join(icons_dir, filename)
        if os.path.isfile(path):
            try:
                pcoll.load(key, path, "IMAGE")
            except Exception:
                pass  # PNG existe mas o Blender não conseguiu ler -- cai pro ícone genérico
    _panel_icons_pcoll = pcoll


def _unload_panel_icons():
    global _panel_icons_pcoll
    if _panel_icons_pcoll is not None:
        bpy.utils.previews.remove(_panel_icons_pcoll)
        _panel_icons_pcoll = None


def _panel_icon_value(key):
    """icon_id carregado pra `key`, ou None se o PNG não foi carregado --
    _draw_info decide entre icon_value= (logo customizado) e icon= (fallback)."""
    if _panel_icons_pcoll is not None and key in _panel_icons_pcoll:
        return _panel_icons_pcoll[key].icon_id
    return None


def _draw_wrapped_label(layout, context, text):
    """Desenha `text` quebrado em várias label() pra caber na largura
    atual da N-Panel -- mede a largura real (px) de cada palavra com
    blf.dimensions() em vez de quebra manual fixa. layout.label() sozinho
    nunca quebra linha (trunca com "...").

    context.region.width é a largura da região inteira, não da coluna/
    box atual -- o desconto fixo (_WRAPPED_LABEL_MARGIN_PX) aproxima a
    margem de box()+coluna+padding. A API não expõe a largura de layout
    em pixels de verdade, é estimativa."""
    available_px = context.region.width - _WRAPPED_LABEL_MARGIN_PX
    font_id = 0
    line = ""
    for word in text.split(" "):
        candidate = f"{line} {word}".strip()
        width_px, _height_px = blf.dimensions(font_id, candidate)
        if width_px > available_px and line:
            layout.label(text=line)
            line = word
        else:
            line = candidate
    if line:
        layout.label(text=line)


# Margem estimada (px) entre context.region.width e a largura de texto
# disponível dentro de credits_box -- ajustado no olho (Blender não expõe isso).
_WRAPPED_LABEL_MARGIN_PX = 40

# TAB_ITEMS/RIG_SUBTAB_ITEMS são funções (items= dinâmico), não listas
# fixas -- EnumProperty com items= função é reavaliado a cada redraw,
# então troca de idioma reflete na hora sem precisar de refresh hook.
#
# CUIDADO: a função não pode devolver uma lista nova a cada chamada -- o
# Blender só garante que as strings dos items ficam vivas enquanto o
# mesmo objeto list também ficar vivo; devolver uma lista recém-criada
# toda vez é a causa mais comum de crash com EnumProperty dinâmico. Por
# isso reaproveitam (limpam + repopulam) o próprio cache module-level.
_TAB_ITEMS_CACHE = []
_RIG_SUBTAB_ITEMS_CACHE = []


def _tab_items(self, context):
    lang = get_language(context)
    _TAB_ITEMS_CACHE.clear()
    _TAB_ITEMS_CACHE.extend(
        [
            ("IMPORT", "Import", tr("panel.tab_import_tooltip", lang), "IMPORT", 0),
            ("EXPORT", "Export", tr("panel.tab_export_tooltip", lang), "EXPORT", 1),
            ("RIG", "Rig", tr("panel.tab_rig_tooltip", lang), "CON_KINEMATIC", 2),
            ("ANIMATION", "Animation", tr("panel.tab_animation_tooltip", lang), "ANIM", 3),
            ("INFO", "Info", tr("panel.tab_info_tooltip", lang), "INFO", 4),
        ]
    )
    return _TAB_ITEMS_CACHE


# Sub-abas dentro da aba Rig (ver _draw_rig): "Setup" é o fluxo do dia a
# dia; "Bone Settings" é a lista de cadeias/formulário; "Advanced" é
# configuração ocasional (Collection Settings, Character Templates).
def _rig_subtab_items(self, context):
    lang = get_language(context)
    _RIG_SUBTAB_ITEMS_CACHE.clear()
    _RIG_SUBTAB_ITEMS_CACHE.extend(
        [
            (
                "SETUP",
                tr("panel.rig_subtab_setup_label", lang),
                tr("panel.rig_subtab_setup_tooltip", lang),
                "TOOL_SETTINGS",
                0,
            ),
            (
                "BONE_SETTINGS",
                tr("panel.rig_subtab_bone_settings_label", lang),
                tr("panel.rig_subtab_bone_settings_tooltip", lang),
                "BONE_DATA",
                1,
            ),
            (
                "ADVANCED",
                tr("panel.rig_subtab_advanced_label", lang),
                tr("panel.rig_subtab_advanced_tooltip", lang),
                "PREFERENCES",
                2,
            ),
        ]
    )
    return _RIG_SUBTAB_ITEMS_CACHE


# ARM e LEG usam os mesmos 4 campos/lógica -- só o rótulo muda por tipo,
# pra refletir a nomenclatura de cada membro. TAIL não entra aqui -- tem
# campos totalmente diferentes, desenhado à parte (sem pole/side/
# pole_angle, que só fazem sentido pra uma cadeia com IK).
_LIMB_FIELD_LABELS = {
    "ARM": {
        "parent_override": "panel.field_arm_shoulder",
        "root_bone": "panel.field_arm_upper",
        "pole_bone": "panel.field_arm_forearm",
        "tip_bone": "panel.field_arm_hand",
    },
    "LEG": {
        "parent_override": "panel.field_leg_pelvis",
        "root_bone": "panel.field_leg_thigh",
        "pole_bone": "panel.field_leg_calf",
        "tip_bone": "panel.field_leg_foot",
    },
}


def _draw_template_picker(box, wm, selected_attr, apply_idname, delete_idname, save_idname, active_label, active_name, active_icon, load_label):
    """Um dos 3 pickers (Rig/Shape/Collection) da box "Character
    Templates": uma linha de status (template ativo) seguida de uma
    linha de ação (dropdown "Load" + Apply/Delete/Save). Escolher um
    item no dropdown só grava a seleção (property comum, não dispara
    nada); "Apply" aplica de fato, "Delete" apaga (desabilitado se o
    selecionado for builtin ou "(none)")."""
    box.label(text=f"{active_label} {active_name}", icon=active_icon)
    # split(factor=...) em vez de label()+prop() soltos -- num row()
    # comum eles disputam a largura igualmente, deixando "Load" ocupar
    # ~50% da linha à toa. split() força a proporção explícita.
    split = box.split(factor=0.14, align=True)
    split.label(text=load_label)
    row = split.row(align=True)
    row.prop(wm, selected_attr, text="")
    row.operator(apply_idname, text="", icon="IMPORT")
    row.operator(delete_idname, text="", icon="TRASH")
    row.operator(save_idname, text="", icon="EXPORT")


class HYTALE_MT_import_more_options(Menu):
    """Popup do botão "More Options" da aba Import -- um item por
    importador de formato de fora do Hytale (importer/<formato>.py). Formato novo =
    uma linha nova aqui."""

    bl_idname = "HYTALE_MT_import_more_options"
    bl_label = "More Options"

    def draw(self, context):
        lang = get_language(context)
        layout = self.layout
        # Menu aberto por wm.call_menu roda os operadores em modo EXEC por
        # padrão -- pularia o invoke() do ImportHelper (o file browser) e
        # o import rodaria com filepath vazio. INVOKE_DEFAULT abre o seletor.
        layout.operator_context = "INVOKE_DEFAULT"
        layout.operator(
            IMPORT_OT_hytale_bedrock_model.bl_idname,
            text=tr("panel.btn_import_bedrock", lang),
            icon="MESH_CUBE",
        )


class HYTALE_PT_main(Panel):
    """Painel principal do addon na N-Panel da Viewport 3D (aba 'Hyblend').
    Só orquestra botões -- toda a lógica real mora nos operadores."""

    bl_label = "Hyblend Toolkit"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Hyblend"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        lang = get_language(context)

        # prop_enum() desenha um botão por vez pra um valor específico
        # do Enum (diferente de prop(expand=True), que desenha todos numa
        # linha só) -- jeito padrão do Blender de montar um grid
        # customizado de botões de Enum. Cada row(align=True) já divide o
        # espaço igualmente entre os 2 botões que contém.
        tabs_col = layout.column(align=True)
        tabs_row1 = tabs_col.row(align=True)
        tabs_row1.scale_y = 1.3
        tabs_row1.prop_enum(wm, "hytale_active_tab", "IMPORT")
        tabs_row1.prop_enum(wm, "hytale_active_tab", "EXPORT")
        tabs_row2 = tabs_col.row(align=True)
        tabs_row2.scale_y = 1.3
        tabs_row2.prop_enum(wm, "hytale_active_tab", "RIG")
        tabs_row2.prop_enum(wm, "hytale_active_tab", "ANIMATION")
        # 3ª linha, só a aba "Info" -- sozinha na própria row dentro do
        # mesmo tabs_col, sai esticada pra largura toda. scale_y menor
        # (mais fina) que as duas de cima.
        tabs_row3 = tabs_col.row(align=True)
        tabs_row3.scale_y = 0.9
        tabs_row3.prop_enum(wm, "hytale_active_tab", "INFO")
        layout.separator()

        tab = wm.hytale_active_tab
        if tab == "IMPORT":
            self._draw_import(layout, context, lang)
        elif tab == "EXPORT":
            self._draw_export(layout, context, lang)
        elif tab == "RIG":
            self._draw_rig(layout, context, lang)
        elif tab == "ANIMATION":
            self._draw_animation(layout, context, lang)
        elif tab == "INFO":
            self._draw_info(layout, context, lang)

    # --- Import ---

    def _draw_import(self, layout, context, lang):
        # Duas fontes de "modelo novo": IMPORT_OT_hytale_blockymodel
        # (modo NEW_ARMATURE) e IMPORT_OT_hytale_bbmodel (sempre cria
        # Armature nova). Agrupados sob "New Model" -- duas portas de
        # entrada pro mesmo resultado.
        new_model_box = layout.box()
        new_model_box.label(text=tr("panel.new_model_header", lang), icon="ARMATURE_DATA")
        new_model_row = new_model_box.row(align=True)
        new_model_row.scale_y = 1.4
        new_model_row.operator(
            IMPORT_OT_hytale_blockymodel.bl_idname,
            text=tr("panel.btn_new_blockymodel", lang),
        ).import_mode = "NEW_ARMATURE"
        new_model_row.operator(
            IMPORT_OT_hytale_bbmodel.bl_idname,
            text=tr("panel.btn_new_bbmodel", lang),
        )
        # "More Options": botão fino, abre um popup (HYTALE_MT_import_more_options)
        # com importadores de formatos que não são do Hytale (ex: importer/bedrock.py).
        more_row = new_model_box.row()
        more_row.scale_y = 0.8
        more_row.operator(
            "wm.call_menu",
            text=tr("panel.btn_more_import_options", lang),
            icon="DOWNARROW_HLT",
        ).name = HYTALE_MT_import_more_options.bl_idname

        layout.separator()

        active = context.active_object
        is_armature = active is not None and active.type == "ARMATURE"

        box = layout.box()
        row = box.column(align=True)
        row.scale_y = 1.4
        # Travado (cinza) sem Armature ativa -- só feedback visual desta
        # box, não mexe no poll() do operador.
        row.enabled = is_armature
        op = row.operator(
            IMPORT_OT_hytale_blockymodel.bl_idname,
            text=tr("panel.btn_import_attach", lang),
            icon="IMPORT",
        )
        op.import_mode = "ATTACH_EXISTING"
        if is_armature:
            # Pré-preenche o alvo com o objeto ativo -- o diálogo ainda
            # deixa trocar, isso é só um atalho pro caso comum.
            op.target_armature_name = active.name

        hint = box.row()
        if is_armature:
            hint.label(text=f"{tr('panel.hint_import_attach_target', lang)} {active.name}", icon="ARMATURE_DATA")
        else:
            hint.label(text=tr("panel.hint_import_attach_none", lang), icon="INFO")

        layout.separator()

        # IMPORT_OT_hytale_blockyanim é ImportHelper com o próprio
        # draw() -- já desenha target_mode/action_name/etc. sozinho na
        # sidebar do file browser. Aqui só o botão + aviso de Armature ativa.
        anim_box = layout.box()
        anim_box.label(text=tr("panel.warn_anim_experimental", lang), icon="ERROR")
        anim_col = anim_box.column(align=True)
        anim_col.scale_y = 1.4
        anim_col.operator(
            IMPORT_OT_hytale_blockyanim.bl_idname,
            text=tr("panel.btn_import_anim", lang),
            icon="ANIM",
        )

        anim_hint = anim_box.row()
        if is_armature:
            anim_hint.label(text=f"{tr('panel.hint_import_anim_target', lang)} {active.name}", icon="ARMATURE_DATA")
        else:
            anim_hint.label(text=tr("panel.hint_import_anim_none", lang), icon="INFO")

    # --- Export ---

    def _draw_export(self, layout, context, lang):
        active = context.active_object
        is_armature = active is not None and active.type == "ARMATURE"

        box = layout.box()
        if is_armature:
            box.label(text=f"{tr('panel.hint_export_target', lang)} {active.name}", icon="ARMATURE_DATA")
        else:
            box.label(text=tr("panel.hint_export_none", lang), icon="ERROR")

        if is_armature:
            settings = active.data.hytale_export_settings
            armature_data = active.data

            settings_box = layout.box()
            settings_box.label(text=tr("panel.export_settings_box", lang), icon="TOOL_SETTINGS")
            # prop_search: dropdown/autocomplete com as Bone Collections
            # que já existem, em vez de exigir digitar o nome. Continua
            # StringProperty por baixo -- o default "Hytale Export"
            # aparece mesmo antes dessa collection existir de verdade.
            # collections_all (não só .collections) pra também listar
            # collections aninhadas, não só as de nível raiz.
            settings_box.prop_search(
                settings, "export_collection_name", armature_data, "collections_all",
                text=tr("panel.export_collection", lang),
            )

            # Normalmente preenchida sozinha por "Create Texture Picker"
            # (uma entrada por instância) -- Add/Remove aqui existem só
            # pra ajuste manual. Collapsible (fechada por padrão) --
            # maioria dos personagens nunca usa Texture Picker.
            wm = context.window_manager
            texture_picker_box = layout.box()
            texture_picker_header = texture_picker_box.row()
            texture_picker_header.prop(
                wm, "hytale_show_export_texture_picker",
                text=tr("panel.export_texture_picker", lang),
                icon="TRIA_DOWN" if wm.hytale_show_export_texture_picker else "TRIA_RIGHT",
                emboss=False,
            )
            wip_sub = texture_picker_header.row()
            wip_sub.alignment = "RIGHT"
            wip_sub.label(text=tr("panel.warn_texture_picker_wip_short", lang), icon="ERROR")

            if wm.hytale_show_export_texture_picker:
                list_row = texture_picker_box.row()
                list_row.template_list(
                    "HYTALE_UL_texture_picker_exports", "",
                    armature_data, "hytale_texture_picker_exports",
                    armature_data, "hytale_texture_picker_exports_index",
                )
                list_col = list_row.column(align=True)
                list_col.operator(EXPORT_OT_texture_picker_export_add.bl_idname, text="", icon="ADD")
                list_col.operator(EXPORT_OT_texture_picker_export_remove.bl_idname, text="", icon="REMOVE")

                exports = armature_data.hytale_texture_picker_exports
                index = armature_data.hytale_texture_picker_exports_index
                if exports and 0 <= index < len(exports):
                    active_export = exports[index]
                    sub = texture_picker_box.column(align=True)

                    def uv_picker_row(field_name, text=None):
                        r = sub.row(align=True)
                        if text is not None:
                            r.prop(active_export, field_name, text=text)
                        else:
                            r.prop(active_export, field_name)
                        op = r.operator(HYTALE_OT_pick_bone_into_field.bl_idname, text="", icon="EYEDROPPER")
                        # data_path indexado -- funciona porque
                        # path_resolve suporta colchetes em
                        # CollectionProperty. Índice fixado na hora de
                        # desenhar, então sempre aponta pro item certo
                        # mesmo trocando a seleção da lista depois.
                        op.data_path = f"data.hytale_texture_picker_exports[{index}]"
                        op.field = field_name

                    uv_picker_row("uv_offset_source_bone")
                    uv_picker_row("uv_offset_target_bone", text=tr("panel.texture_picker_target_bone", lang))
                    # Companion Target Bones: lista, sem picker de
                    # eyedropper -- preenchido sozinho por "Create
                    # Texture Picker", editável aqui só pra ajuste manual.
                    sub.prop(
                        active_export, "uv_offset_target_bones_extra",
                        text=tr("panel.texture_picker_extra_target_bones", lang),
                    )
                    # 4 campos de calibração -- normalmente preenchidos
                    # sozinhos por "Create Texture Picker".
                    calib_row1 = sub.row(align=True)
                    calib_row1.prop(active_export, "uv_offset_step_x")
                    calib_row1.prop(active_export, "uv_offset_px_x")
                    calib_row2 = sub.row(align=True)
                    calib_row2.prop(active_export, "uv_offset_step_y")
                    calib_row2.prop(active_export, "uv_offset_px_y")

        col = layout.column(align=True)
        col.scale_y = 1.4
        row = col.row()
        row.enabled = is_armature
        row.operator(
            EXPORT_OT_hytale_blockyanim.bl_idname,
            text=tr("panel.btn_export", lang),
            icon="EXPORT",
        )

        # .blockymodel fica junto do .blockyanim (fluxo nativo
        # principal), não dentro de "More Exports" -- diferente de FBX/
        # GLTF/VRM (interoperabilidade com outras ferramentas), é o
        # mesmo formato do jogo, só exportando o modelo em vez da animação.
        model_row = layout.row()
        model_row.enabled = is_armature
        model_row.operator(
            EXPORT_OT_hytale_blockymodel.bl_idname,
            text=tr("panel.btn_export_model", lang),
            icon="ARMATURE_DATA",
        )

        # "More Exports": formatos além do .blockyanim/.blockymodel
        # nativos (hoje: FBX). Separado do fluxo principal numa box
        # collapsible, fechada por padrão. Formatos futuros (GLTF, VRM)
        # entram aqui dentro também.
        wm = context.window_manager
        more_box = layout.box()
        more_box.prop(
            wm, "hytale_show_more_exports",
            text=tr("panel.more_exports", lang),
            icon="TRIA_DOWN" if wm.hytale_show_more_exports else "TRIA_RIGHT",
            emboss=False,
        )
        if wm.hytale_show_more_exports:
            more_box.label(text=tr("panel.hint_more_exports", lang), icon="INFO")

            fbx_col = more_box.column(align=True)
            fbx_col.enabled = is_armature
            fbx_col.label(text="FBX", icon="EXPORT")
            fbx_col.operator(
                EXPORT_OT_hytale_fbx_model.bl_idname,
                text=tr("panel.btn_export_fbx_model", lang),
                icon="MESH_DATA",
            )
            fbx_col.operator(
                EXPORT_OT_hytale_fbx_anim.bl_idname,
                text=tr("panel.btn_export_fbx_anim", lang),
                icon="ACTION",
            )

    # --- Rig ---

    def _draw_shape_vertex_edit_active(self, layout, context, lang, obj):
        """Desenhado no lugar do resto de _draw_rig enquanto o objeto
        ativo é a malha de um widget em Vertex Edit Mode -- nesse estado
        obj.type é 'MESH', não 'ARMATURE'. `obj` já é a malha (chamador
        confirma obj.type == 'MESH' e a custom property antes de chamar)."""
        box = layout.box()
        box.label(text=tr("panel.label_vertex_edit_active", lang), icon="EDITMODE_HLT")
        bone_name = obj.get("hytale_vertex_edit_bone", "")
        if bone_name:
            box.label(text=bone_name, icon="BONE_DATA")
        box.label(text=obj.name, icon="MESH_DATA")

        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator(
            RIG_OT_hytale_shape_vertex_edit_mode_finish.bl_idname,
            text=tr("panel.btn_shape_vertex_edit_finish", lang),
            icon="CHECKMARK",
        )

    def _draw_rig(self, layout, context, lang):
        obj = context.active_object

        # Vertex Edit Mode troca o objeto ativo pra malha do widget --
        # checa isso antes de tudo, senão o botão "Finish Vertex Edit"
        # ficaria inalcançável (obj.type != 'ARMATURE' cairia no hint
        # "nenhum Armature selecionado" abaixo).
        if obj is not None and obj.type == "MESH" and obj.get("hytale_vertex_edit_armature"):
            self._draw_shape_vertex_edit_active(layout, context, lang, obj)
            return

        layout.label(text=tr("panel.warn_rig_experimental", lang), icon="ERROR")

        is_armature = is_active_armature(context)

        if not is_armature:
            # v0.17 -- hytale_shape_edit_mode mora em Armature DATA, não
            # no Object ativo -- se o usuário trocou de objeto sem
            # perceber que uma Armature ainda está em Shape Edit Mode, o
            # hint "Select an Armature" sozinho escondia esse fato (ver
            # find_armature_stuck_in_shape_edit_mode/shape_edit.py).
            stuck_armature = find_armature_stuck_in_shape_edit_mode(context)
            if stuck_armature is not None:
                box = layout.box()
                box.label(
                    text=tr("panel.hint_shape_edit_active_elsewhere", lang).format(name=stuck_armature.name),
                    icon="INFO",
                )
                op = box.operator(
                    RIG_OT_hytale_shape_edit_mode_reselect.bl_idname,
                    text=tr("panel.btn_shape_edit_mode_reselect", lang),
                    icon="ARMATURE_DATA",
                )
                op.armature_name = stuck_armature.name
            else:
                layout.box().label(text=tr("panel.hint_rig_none", lang), icon="ERROR")
            return

        armature = obj.data
        wm = context.window_manager

        # Sub-abas dentro da aba Rig -- nomes só em inglês, mesmo
        # raciocínio do topo do arquivo.
        subtab_row = layout.row(align=True)
        subtab_row.prop(wm, "hytale_rig_subtab", expand=True)
        layout.separator()

        subtab = wm.hytale_rig_subtab
        if subtab == "SETUP":
            self._draw_rig_setup(layout, context, lang, armature)
        elif subtab == "BONE_SETTINGS":
            self._draw_rig_bone_settings(layout, context, lang, armature, wm)
        elif subtab == "ADVANCED":
            self._draw_rig_advanced(layout, context, lang, armature, wm)

    def _draw_rig_setup(self, layout, context, lang, armature):
        # "Create Rig" e "Check Rig" formam um bloco só (column(align=True)
        # gruda as rows) -- Create Rig mais alto/largo (ação principal),
        # Check Rig logo abaixo, menor. "Remove Generated Bones" é o
        # ícone de lixeira ao lado de Create Rig -- ação secundária
        # (destrutiva).
        col = layout.column(align=True)
        top_row = col.row(align=True)
        top_row.scale_y = 1.7
        top_row.operator(
            RIG_OT_hytale_generate_rig.bl_idname,
            text=tr("panel.btn_create_rig", lang),
            icon="ARMATURE_DATA",
        )
        # Menu popup (Only Rig / Delete All) -- "Only Rig" preserva
        # widgets editados à mão, "Delete All" também limpa Collection/
        # Bone Settings.
        top_row.menu(
            RIG_MT_hytale_clear_generated_menu.bl_idname,
            text="",
            icon="TRASH",
        )
        check_row = col.row(align=True)
        check_row.scale_y = 1.2
        check_row.operator(
            RIG_OT_hytale_validate_rig.bl_idname,
            text=tr("panel.btn_validate_rig", lang),
            icon="VIEWZOOM",
        )

        layout.separator()

        # Shape Edit Mode -- alterna entre os dois operadores conforme
        # armature.hytale_shape_edit_mode. O poll() de
        # RIG_OT_hytale_shape_edit_mode_enter já cobre "sem rig gerado
        # ainda" -- o Blender desabilita o botão sozinho.
        if armature.hytale_shape_edit_mode:
            # v0.17 -- caminho de recuperação: o objeto ativo é a
            # Armature (não a malha do widget), mas
            # hytale_shape_vertex_edit_mode ainda está True -- normalmente
            # só acontece se o widget foi deletado no meio da edição (ver
            # RIG_OT_hytale_shape_vertex_edit_mode_finish/shape_edit.py).
            # _self_heal_shape_edit_state já limpa isso sozinho na
            # maioria dos casos (load/undo/redo), mas esta box cobre o
            # instante entre o problema acontecer e o próximo desses
            # eventos rodar -- sem ela não existiria NENHUM botão capaz
            # de sair desse estado.
            if armature.hytale_shape_vertex_edit_mode:
                box = layout.box()
                box.label(text=tr("panel.hint_vertex_edit_orphaned", lang), icon="ERROR")
                box.operator(
                    RIG_OT_hytale_shape_vertex_edit_mode_finish.bl_idname,
                    text=tr("panel.btn_shape_vertex_edit_finish", lang),
                    icon="CHECKMARK",
                )
                return

            layout.operator(
                RIG_OT_hytale_shape_edit_mode_finish.bl_idname,
                text=tr("panel.btn_shape_edit_finish", lang),
                icon="CHECKMARK",
            )

            # Edição inline do custom shape do pose bone ativo --
            # translation/rotation/scale são properties nativas do
            # PoseBone. Mirror Shape/Edit Shape Vertices ficam cinza
            # sozinhos (poll()) quando não aplicável -- sempre
            # desenhados, sem duplicar a checagem aqui.
            active_pb = context.active_pose_bone
            box = layout.box()
            if active_pb is None:
                box.label(
                    text=tr("panel.hint_shape_edit_no_active_bone", lang),
                    icon="INFO",
                )
            else:
                box.label(text=active_pb.name, icon="BONE_DATA")
                box.operator(
                    RIG_OT_hytale_shape_vertex_edit_mode_enter.bl_idname,
                    text=tr("panel.btn_shape_vertex_edit_enter", lang),
                    icon="EDITMODE_HLT",
                )
                box.operator(
                    RIG_OT_hytale_mirror_shape.bl_idname,
                    text=tr("panel.btn_mirror_shape", lang),
                    icon="MOD_MIRROR",
                )
                # Embutir malha nos Shape Templates -- "widget totalmente
                # próprio". Fica cinza sozinho (poll()) sem exatamente 1
                # outro objeto de malha selecionado.
                box.operator(
                    RIG_OT_hytale_use_selected_as_widget.bl_idname,
                    text=tr("panel.btn_use_selected_as_widget", lang),
                    icon="MESH_DATA",
                )
                shape_col = box.column(align=True)
                shape_col.prop(
                    active_pb, "custom_shape_translation",
                    text=tr("panel.field_shape_translation", lang),
                )
                shape_col.prop(
                    active_pb, "custom_shape_rotation_euler",
                    text=tr("panel.field_shape_rotation", lang),
                )
                shape_col.prop(
                    active_pb, "custom_shape_scale_xyz",
                    text=tr("panel.field_shape_scale", lang),
                )
        else:
            layout.operator(
                RIG_OT_hytale_shape_edit_mode_enter.bl_idname,
                text=tr("panel.btn_shape_edit_enter", lang),
                icon="MOD_MESHDEFORM",
            )

    def _draw_rig_bone_settings(self, layout, context, lang, armature, wm):
        box = layout.box()
        box.label(text=tr("panel.ik_chains_box", lang), icon="CON_KINEMATIC")

        row = box.row()
        row.template_list(
            "RIG_UL_hytale_ik_chains", "",
            armature, "hytale_ik_chains",
            armature, "hytale_ik_chains_index",
        )
        col = row.column(align=True)
        # "+" abre um menu popup (que tipo: Arm/Leg/Tail/...) em vez de
        # adicionar uma cadeia genérica direto. col.menu() usa a
        # description() da própria classe Menu como tooltip do botão.
        col.menu(RIG_MT_hytale_ik_chain_add_menu.bl_idname, text="", icon="ADD")
        col.operator(RIG_OT_hytale_ik_chain_remove.bl_idname, text="", icon="REMOVE")
        col.separator()
        col.operator(RIG_OT_hytale_ik_chain_move.bl_idname, text="", icon="TRIA_UP").direction = "UP"
        col.operator(RIG_OT_hytale_ik_chain_move.bl_idname, text="", icon="TRIA_DOWN").direction = "DOWN"

        # Botão de largura cheia, fora da coluna estreita do +/-/mover
        # (ação "de uma vez só", não controle da lista em si).
        detect_row = box.row()
        detect_row.scale_y = 1.1
        detect_row.operator(
            RIG_OT_hytale_ik_chain_auto_detect.bl_idname,
            text=tr("panel.btn_auto_detect_bones", lang),
            icon="VIEWZOOM",
        )

        # "Load Preset" (Character Templates) liga/desliga esta opção
        # automaticamente conforme rig_template["apply_ik_joint_fix"];
        # fica aqui pra dar pra ajustar na mão. Só faz sentido mostrar se
        # já existe alguma entrada ARM/LEG -- Tail/Head/Spine não têm
        # IK/joint fix.
        has_limb_entry = any(c.chain_type in ("ARM", "LEG") for c in armature.hytale_ik_chains)
        if has_limb_entry:
            box.prop(
                armature,
                "hytale_apply_ik_joint_fix",
                text=tr("panel.apply_ik_joint_fix", lang),
            )

        index = armature.hytale_ik_chains_index
        if 0 <= index < len(armature.hytale_ik_chains):
            item = armature.hytale_ik_chains[index]
            col = box.column(align=True)

            rename_on = bool(getattr(armature, "hytale_rename_enabled", False))

            def _rename_checkbox_into(row, field_name):
                # "Rename Bones" ligado: caixinha ao lado do picker --
                # desmarcada = esse bone mantém o nome original.
                toggle = rename_toggle_prop(item, field_name) if rename_on else None
                if toggle:
                    row.prop(item, toggle, text="")

            def _picker_row_into(layout, field_name, text):
                r = layout.row(align=True)
                r.prop(item, field_name, text=text)
                op = r.operator(RIG_OT_hytale_ik_chain_pick_bone.bl_idname, text="", icon="EYEDROPPER")
                op.chain_index = index
                op.field = field_name
                _rename_checkbox_into(r, field_name)

            col.prop(item, "chain_type", text=tr("panel.field_chain_type", lang))

            if item.chain_type == "ROOT":
                # Root 1 = Origin principal; Root 2 controla o Root 1,
                # Root 3 controla o Root 2... Cada slot: bone do modelo
                # (eyedropper) OU "New Bone" (o rigger cria o bone, que
                # fica só no Blender -- nunca vai pro export).
                root_bones_box = col.box()
                root_bones_box.label(text=tr("panel.bone_settings_group_bones", lang), icon="BONE_DATA")
                root_bones_col = root_bones_box.column(align=True)
                root_bones_col.prop(item, "root_count", text=tr("panel.field_root_count", lang))
                for i in range(1, item.root_count + 1):
                    field_name = f"root_bone_{i}"
                    create_name = f"root_create_{i}"
                    label = tr("panel.field_root_origin", lang) if i == 1 else f"{tr('panel.field_root', lang)} {i}"
                    r = root_bones_col.row(align=True)
                    r.prop(item, field_name, text=label)
                    if not getattr(item, create_name):
                        op = r.operator(RIG_OT_hytale_ik_chain_pick_bone.bl_idname, text="", icon="EYEDROPPER")
                        op.chain_index = index
                        op.field = field_name
                    r.prop(item, create_name, text="", icon="ADD", toggle=True)
                    _rename_checkbox_into(r, field_name)
                col.label(text=tr("panel.hint_root_order", lang), icon="INFO")
                col.label(text=tr("panel.hint_root_new_bone", lang), icon="INFO")
                col.separator()
                col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
            elif item.chain_type == "CHAIN":
                # Tail não usa IK -- só o caminho root->tip e um parent
                # opcional. Sem pole/side/pole_angle, que só fazem
                # sentido pra uma cadeia com solver de IK.
                tail_bones_box = col.box()
                tail_bones_box.label(text=tr("panel.bone_settings_group_bones", lang), icon="BONE_DATA")
                tail_bones_col = tail_bones_box.column(align=True)
                _picker_row_into(tail_bones_col, "parent_override", tr("panel.field_tail_parent", lang))
                _picker_row_into(tail_bones_col, "root_bone", tr("panel.field_tail_start", lang))
                _picker_row_into(tail_bones_col, "tip_bone", tr("panel.field_tail_end", lang))

                row = col.row(align=True)
                row.prop(item, "tail_tip_rotation_axis", text=tr("panel.field_tail_tip_rotation_axis", lang))
                row.prop(item, "tail_tip_rotation_deg", text=tr("panel.field_tail_tip_rotation_deg", lang))
                # "Connected" -- liga/desliga bone.use_connect nos
                # segmentos internos da cadeia. Desligado por padrão.
                col.prop(item, "tail_use_connect", text=tr("panel.field_tail_use_connect", lang))
                col.label(text=tr("panel.hint_tail_no_ik", lang), icon="INFO")
                col.separator()
                col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
            elif item.chain_type == "HEAD":
                # Head não cria bone nenhum -- só identifica quais _CTRL
                # já existentes são o Neck/Head/Head End, pra organização
                # de collection. neck_count controla quantos dos 5 campos
                # de Neck aparecem -- Head/Head End ficam sempre visíveis.
                head_bones_box = col.box()
                head_bones_box.label(text=tr("panel.bone_settings_group_bones", lang), icon="BONE_DATA")
                head_bones_col = head_bones_box.column(align=True)
                head_bones_col.prop(item, "neck_count", text=tr("panel.field_neck_count", lang))
                neck_fields = ["neck_bone_1", "neck_bone_2", "neck_bone_3", "neck_bone_4", "neck_bone_5"]
                neck_labels = [
                    "panel.field_neck_1", "panel.field_neck_2", "panel.field_neck_3",
                    "panel.field_neck_4", "panel.field_neck_5",
                ]
                for field_name, label_key in list(zip(neck_fields, neck_labels))[: item.neck_count]:
                    _picker_row_into(head_bones_col, field_name, tr(label_key, lang))
                _picker_row_into(head_bones_col, "head_bone", tr("panel.field_head_bone", lang))
                _picker_row_into(head_bones_col, "head_end_bone", tr("panel.field_head_end_bone", lang))

                # "Main Head" -- radio button entre entradas HEAD (ver
                # _head_is_main_update em rigger/bone_settings.py):
                # decide qual cabeça é "a" principal (PROPERTIES/FK-IK
                # switch, Head Follow, collection Main/Head, widget/cor
                # do Head_CTRL) quando existe mais de uma entrada HEAD
                # (personagem com várias cabeças). Só aparece de fato
                # quando isso importa -- com uma única entrada HEAD fica
                # sempre marcada e não há o que escolher.
                if sum(1 for c in armature.hytale_ik_chains if c.chain_type == "HEAD") > 1:
                    col.prop(item, "head_is_main", text=tr("panel.field_head_is_main", lang))

                # "Head Free/Lock" -- um toggle só: redireciona sozinho
                # o Tail do predecessor imediato de "Head" pro Head do
                # Head_CTRL, deixa Head_CTRL sem parent nenhum (Child
                # Of/Copy Location já bastam sozinhos pra seguir o
                # predecessor -- um parent aqui duplicaria o movimento),
                # e monta os constraints de Child Of/Copy Location.
                col.separator()
                col.prop(item, "head_follow_enabled", text=tr("panel.field_head_follow_enabled", lang))
                col.separator()

                # "Create First Person Camera" -- caixa collapsible
                # própria, pra não poluir a entrada HEAD quando desligada.
                camera_box = col.box()
                camera_header = camera_box.row()
                camera_header.prop(
                    wm, "hytale_show_head_camera",
                    text=tr("panel.head_camera_section", lang),
                    icon="TRIA_DOWN" if wm.hytale_show_head_camera else "TRIA_RIGHT",
                    emboss=False,
                )
                if wm.hytale_show_head_camera:
                    camera_col = camera_box.column(align=True)
                    camera_col.prop(item, "head_camera_enabled", text=tr("panel.field_head_camera_enabled", lang))
                    if item.head_camera_enabled:
                        _picker_row_into(
                            camera_col, "head_camera_parent_bone", tr("panel.field_head_camera_parent_bone", lang)
                        )
                        camera_col.label(text=tr("panel.head_camera_offset_label", lang))
                        offset_row = camera_col.row(align=True)
                        offset_row.prop(item, "head_camera_offset_x", text=tr("panel.field_head_camera_offset_x", lang))
                        offset_row.prop(item, "head_camera_offset_y", text=tr("panel.field_head_camera_offset_y", lang))
                        offset_row.prop(item, "head_camera_offset_z", text=tr("panel.field_head_camera_offset_z", lang))
                        camera_col.label(text=tr("panel.head_camera_rotation_label", lang))
                        rotation_row = camera_col.row(align=True)
                        rotation_row.prop(
                            item, "head_camera_rotation_x", text=tr("panel.field_head_camera_rotation_x", lang)
                        )
                        rotation_row.prop(
                            item, "head_camera_rotation_y", text=tr("panel.field_head_camera_rotation_y", lang)
                        )
                        rotation_row.prop(
                            item, "head_camera_rotation_z", text=tr("panel.field_head_camera_rotation_z", lang)
                        )
                        # FOV ajustável antes de clicar "Create Camera"
                        # (idempotente -- rodar de novo atualiza o FOV).
                        camera_col.prop(item, "head_camera_fov", text=tr("panel.field_head_camera_fov", lang))
                        camera_col.label(text=tr("panel.hint_head_camera", lang), icon="INFO")
                    # Botões Create/Remove sempre visíveis nesta caixa
                    # (Remove funciona independente do toggle) -- senão
                    # desmarcar a checkbox depois de já ter criado a
                    # câmera escondia "Remove Camera" junto.
                    camera_col.separator()
                    camera_action_row = camera_col.row(align=True)
                    camera_action_row.operator(RIG_OT_hytale_camera_create.bl_idname, icon="CAMERA_DATA")
                    camera_action_row.operator(RIG_OT_hytale_camera_remove.bl_idname, icon="X", text="")

                col.separator()
                col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
            elif item.chain_type == "SPINE":
                # Mesmo espírito de Head: nenhum bone é criado, só
                # identificado. spine_count é o total incluindo o Pelvis
                # (1 = só Pelvis).
                spine_bones_box = col.box()
                spine_bones_box.label(text=tr("panel.bone_settings_group_bones", lang), icon="BONE_DATA")
                spine_bones_col = spine_bones_box.column(align=True)
                spine_bones_col.prop(item, "spine_count", text=tr("panel.field_spine_count", lang))
                _picker_row_into(spine_bones_col, "pelvis_bone", tr("panel.field_pelvis_bone", lang))
                spine_fields = ["spine_bone_1", "spine_bone_2", "spine_bone_3", "spine_bone_4"]
                spine_labels = [
                    "panel.field_spine_1", "panel.field_spine_2",
                    "panel.field_spine_3", "panel.field_spine_4",
                ]
                for field_name, label_key in list(zip(spine_fields, spine_labels))[: max(0, item.spine_count - 1)]:
                    _picker_row_into(spine_bones_col, field_name, tr(label_key, lang))

                # Liga/desliga a criação de root.spine_CTRL (e os
                # constraints de Spine Follow que dependem dele). Fora da
                # box "Bones" de propósito -- não é nome de bone, é
                # toggle de comportamento.
                col.prop(item, "spine_ctrl_enabled", text=tr("panel.field_spine_ctrl_enabled", lang))

                col.label(text=tr("panel.hint_spine_no_ik", lang), icon="INFO")
                col.separator()
                col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
            elif item.chain_type == "ATTACHMENTS":
                # Mesmo espírito de Head/Spine: nenhum bone é criado, só
                # identificado. attachments_count controla quantos campos
                # aparecem -- todos os slots são do mesmo tipo.
                attach_bones_box = col.box()
                attach_bones_box.label(text=tr("panel.bone_settings_group_bones", lang), icon="BONE_DATA")
                attach_bones_col = attach_bones_box.column(align=True)
                attach_bones_col.prop(item, "attachments_count", text=tr("panel.field_attachments_count", lang))
                attachment_base_label = tr("panel.field_attachment", lang)
                for i in range(1, item.attachments_count + 1):
                    label = attachment_base_label if i == 1 else f"{attachment_base_label} {i}"
                    _picker_row_into(attach_bones_col, f"attachment_bone_{i}", label)

                col.label(text=tr("panel.hint_attachments_no_ik", lang), icon="INFO")
                col.separator()
                col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
            elif item.chain_type == "TEXTURE_PICKER":
                # Texture Picker não cria bone de IK nenhum -- só
                # identifica qual bone original é o alvo, e dispara a
                # criação do atlas picker (root.ui/cursor derivado +
                # plane de referência + driver no material).
                tp_bones_box = col.box()
                tp_bones_box.label(text=tr("panel.bone_settings_group_bones", lang), icon="BONE_DATA")
                tp_bones_col = tp_bones_box.column(align=True)
                _picker_row_into(tp_bones_col, "texture_picker_bone", tr("panel.field_texture_picker_bone", lang))
                _picker_row_into(
                    tp_bones_col, "texture_picker_ui_parent_bone", tr("panel.field_texture_picker_ui_parent_bone", lang)
                )
                col.separator()

                plane_box = col.box()
                plane_header = plane_box.row()
                plane_header.prop(
                    wm, "hytale_show_texture_picker_plane",
                    text=tr("panel.texture_picker_section_plane", lang),
                    icon="TRIA_DOWN" if wm.hytale_show_texture_picker_plane else "TRIA_RIGHT",
                    emboss=False,
                )
                if wm.hytale_show_texture_picker_plane:
                    plane_col = plane_box.column(align=True)
                    plane_col.prop(item, "texture_picker_plane_scale", text=tr("panel.field_texture_picker_plane_scale", lang))
                    plane_row = plane_col.row(align=True)
                    plane_row.prop(
                        item, "texture_picker_plane_offset_x", text=tr("panel.field_texture_picker_plane_offset_x", lang)
                    )
                    plane_row.prop(
                        item, "texture_picker_plane_offset_y", text=tr("panel.field_texture_picker_plane_offset_y", lang)
                    )

                # Companion Bones: outras malhas/bones que compartilham
                # o atlas do target e trocam de expressão junto (ex.:
                # metades L/R espelhadas). Não criam bone -- só recebem
                # material+driver de UV.
                companion_box = col.box()
                companion_header = companion_box.row()
                companion_header.prop(
                    wm, "hytale_show_texture_picker_companions",
                    text=tr("panel.texture_picker_section_companions", lang),
                    icon="TRIA_DOWN" if wm.hytale_show_texture_picker_companions else "TRIA_RIGHT",
                    emboss=False,
                )
                if wm.hytale_show_texture_picker_companions:
                    companion_col = companion_box.column(align=True)
                    companion_col.prop(
                        item, "texture_picker_extra_bone_count", text=tr("panel.field_texture_picker_extra_count", lang)
                    )
                    companion_base_label = tr("panel.field_texture_picker_extra_bone", lang)
                    for i in range(1, item.texture_picker_extra_bone_count + 1):
                        label = companion_base_label if i == 1 else f"{companion_base_label} {i}"
                        _picker_row_into(companion_col, f"texture_picker_extra_bone_{i}", label)
                    if item.texture_picker_extra_bone_count == 0:
                        companion_col.label(text=tr("panel.hint_texture_picker_companions_empty", lang), icon="INFO")

                # Grid é sempre digitado manualmente (detecção automática
                # por alpha foi removida por se provar frágil).
                grid_box = col.box()
                grid_header = grid_box.row()
                grid_header.prop(
                    wm, "hytale_show_texture_picker_grid",
                    text=tr("panel.texture_picker_section_grid", lang),
                    icon="TRIA_DOWN" if wm.hytale_show_texture_picker_grid else "TRIA_RIGHT",
                    emboss=False,
                )
                if wm.hytale_show_texture_picker_grid:
                    grid_col = grid_box.column(align=True)
                    grid_row = grid_col.row(align=True)
                    grid_row.prop(
                        item, "texture_picker_grid_cols", text=tr("panel.field_texture_picker_grid_cols", lang)
                    )
                    grid_row.prop(
                        item, "texture_picker_grid_rows", text=tr("panel.field_texture_picker_grid_rows", lang)
                    )
                    grid_row = grid_col.row(align=True)
                    grid_row.prop(
                        item, "texture_picker_grid_cell_width",
                        text=tr("panel.field_texture_picker_grid_cell_width", lang),
                    )
                    grid_row.prop(
                        item, "texture_picker_grid_cell_height",
                        text=tr("panel.field_texture_picker_grid_cell_height", lang),
                    )

                col.separator()
                action_row = col.row(align=True)
                action_row.scale_y = 1.3
                action_row.operator(RIG_OT_hytale_texture_picker_create.bl_idname, icon="IMAGE_DATA")
                action_row.operator(RIG_OT_hytale_texture_picker_remove.bl_idname, icon="X", text="")
                col.label(text=tr("panel.hint_texture_picker_no_ik", lang), icon="INFO")
                col.separator()
                col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
            else:
                # ARM/LEG: Root Bone/Tip Bone cobrem cadeias com mais de
                # 2 segmentos sozinhos (o caminho do meio é resolvido
                # andando pela hierarquia, find_org_path) -- sem precisar
                # de campo extra. Fallback pra "ARM" cobre chain_type
                # desconhecido (ex. template externo com typo).
                labels = _LIMB_FIELD_LABELS.get(item.chain_type, _LIMB_FIELD_LABELS["ARM"])

                bones_box = col.box()
                bones_box.label(text=tr("panel.bone_settings_group_bones", lang), icon="BONE_DATA")
                bones_col = bones_box.column(align=True)
                _picker_row_into(bones_col, "parent_override", tr(labels["parent_override"], lang))
                _picker_row_into(bones_col, "root_bone", tr(labels["root_bone"], lang))
                _picker_row_into(bones_col, "pole_bone", tr(labels["pole_bone"], lang))
                _picker_row_into(bones_col, "tip_bone", tr(labels["tip_bone"], lang))
                bones_col.prop(item, "side", text=tr("panel.field_side", lang))

                # "Pole" é collapsible (fechada por padrão) -- ajuste
                # fino, só mexido quando o cotovelo/joelho sai torto.
                pole_box = col.box()
                pole_header = pole_box.row()
                pole_header.prop(
                    wm, "hytale_show_pole_settings",
                    text=tr("panel.bone_settings_group_pole", lang),
                    icon="TRIA_DOWN" if wm.hytale_show_pole_settings else "TRIA_RIGHT",
                    emboss=False,
                )
                if wm.hytale_show_pole_settings:
                    pole_col = pole_box.column(align=True)
                    pole_col.prop(item, "pole_distance", text=tr("panel.field_pole_distance", lang))
                    pole_col.prop(item, "pole_angle_mode", text=tr("panel.field_pole_angle_mode", lang))
                    if item.pole_angle_mode == "MANUAL":
                        pole_col.prop(item, "pole_angle_manual", text=tr("panel.field_pole_angle_manual", lang))
                    elif item.pole_angle_mode == "AUTO":
                        pole_col.prop(item, "pole_angle_fine_tune", text=tr("panel.field_pole_angle_fine_tune", lang))
                    elif item.pole_angle_mode == "PRESET":
                        # Nome do preset dentro de
                        # rig_template["pole_angle_presets"] -- o
                        # template ativo fornece os valores por side.
                        pole_col.prop(item, "pole_angle_preset_name", text=tr("panel.field_pole_angle_preset_name", lang))
                    pole_col.prop(item, "pole_invert", text=tr("panel.field_pole_in_front", lang))

                col.separator()
                col.prop(item, "collection_override", text=tr("panel.field_collection", lang))

        # "Rename Bones" -- no fim das opções do Bone Settings. Ligado:
        # mostra as caixinhas ao lado dos pickers e o botão que aplica.
        rename_box = box.box()
        rename_box.prop(armature, "hytale_rename_enabled", text=tr("panel.field_rename_enabled", lang))
        if armature.hytale_rename_enabled:
            # "All Bones" / "Only CTRL" -- ver rigger/rename.py. O botão
            # pequeno no fim volta os nomes originais (os dois modos).
            mode_row = rename_box.row(align=True)
            mode_row.prop(armature, "hytale_rename_mode", expand=True)
            mode_row.operator(RIG_OT_hytale_revert_bone_names.bl_idname, text="", icon="LOOP_BACK")
            hint_key = "panel.hint_rename_only_ctrl" if armature.hytale_rename_mode == "ONLY_CTRL" else "panel.hint_rename"
            rename_box.label(text=tr(hint_key, lang), icon="INFO")
            rename_row = rename_box.row()
            rename_row.scale_y = 1.2
            rename_row.operator(
                RIG_OT_hytale_rename_bones.bl_idname,
                text=tr("panel.btn_rename_bones", lang),
                icon="SORTALPHA",
            )

    def _draw_rig_advanced(self, layout, context, lang, armature, wm):
        layout.separator()

        # --- Collection Settings ---
        # Cada entrada é uma Collection (bone collection real) OU uma
        # Section (separador puramente visual da aba Animation) -- lista
        # unificada. O seletor "Type" na entrada selecionada decide qual
        # é qual.
        #
        # Não chama ensure_default_bone_collections() aqui: draw() não
        # pode escrever em dados de ID. O seed default só roda de dentro
        # de execute() -- automaticamente no primeiro "Create Rig", ou
        # manualmente via "Load Default Collections" (mostrado só
        # enquanto a lista ainda não foi inicializada).
        coll_header = layout.row()
        coll_header.prop(
            wm, "hytale_show_bone_collections",
            text=tr("panel.bone_collections_box", lang),
            icon="TRIA_DOWN" if wm.hytale_show_bone_collections else "TRIA_RIGHT",
            emboss=False,
        )

        if wm.hytale_show_bone_collections:
            box = layout.box()
            if not armature.hytale_bone_collections_initialized and len(armature.hytale_bone_collections) == 0:
                box.operator(
                    RIG_OT_hytale_bone_collection_load_defaults.bl_idname,
                    text=tr("panel.btn_load_default_collections", lang),
                    icon="IMPORT",
                )
            # Corrige entradas default criadas antes de Row/Column
            # existir (ficam travadas em 0/0). Sempre visível -- é pra
            # corrigir entradas que já existem, não popular lista vazia.
            if len(armature.hytale_bone_collections) > 0:
                box.operator(
                    RIG_OT_hytale_bone_collection_reset_grid.bl_idname,
                    text=tr("panel.btn_reset_bone_collection_grid", lang),
                    icon="FILE_REFRESH",
                )
            row = box.row()
            row.template_list(
                "RIG_UL_hytale_bone_collections", "",
                armature, "hytale_bone_collections",
                armature, "hytale_bone_collections_index",
            )
            col = row.column(align=True)
            col.operator(RIG_OT_hytale_bone_collection_add.bl_idname, text="", icon="ADD")
            col.operator(RIG_OT_hytale_bone_collection_remove.bl_idname, text="", icon="REMOVE")
            col.separator()
            col.operator(RIG_OT_hytale_bone_collection_move.bl_idname, text="", icon="TRIA_UP").direction = "UP"
            col.operator(RIG_OT_hytale_bone_collection_move.bl_idname, text="", icon="TRIA_DOWN").direction = "DOWN"

            # Opções da entrada selecionada -- "Parent" é o mesmo campo
            # pros dois tipos, só o rótulo muda ("Section" pra uma
            # Collection; "Parent" pra uma Section). "Show in Animation
            # Tab"/"Column" só fazem sentido pra Collection.
            index = armature.hytale_bone_collections_index
            if 0 <= index < len(armature.hytale_bone_collections):
                selected = armature.hytale_bone_collections[index]
                detail_box = box.box()
                detail_box.label(
                    text=tr("panel.bone_collection_options_for", lang).format(name=selected.name),
                    icon="OPTIONS",
                )
                detail_box.prop(selected, "entry_type", text=tr("panel.field_entry_type", lang))
                if selected.entry_type == "SECTION":
                    detail_box.prop(selected, "parent", text=tr("panel.field_parent", lang))
                    detail_box.prop(selected, "row", text=tr("panel.field_section_order", lang))
                else:
                    detail_box.prop(selected, "parent", text=tr("panel.field_section", lang))
                    detail_box.prop(selected, "show_in_animation_tab", text=tr("panel.field_show_in_animation", lang))
                    grid_row = detail_box.row(align=True)
                    grid_row.prop(selected, "row", text=tr("panel.field_grid_row", lang))
                    grid_row.prop(selected, "column", text=tr("panel.field_grid_column", lang))

            box.label(text=tr("panel.hint_bone_collections", lang), icon="INFO")

        layout.separator()

        # --- Character Templates (rig + custom shapes) ---
        # Ver templates/__init__.py pro schema/racional completo dos
        # .json -- esta box é só desenho.
        tmpl_header = layout.row()
        tmpl_header.prop(
            wm, "hytale_show_templates",
            text=tr("panel.templates_box", lang),
            icon="TRIA_DOWN" if wm.hytale_show_templates else "TRIA_RIGHT",
            emboss=False,
        )

        if wm.hytale_show_templates:
            tmpl_box = layout.box()

            _draw_template_picker(
                tmpl_box, wm,
                selected_attr="hytale_rig_template_selected",
                apply_idname=RIG_OT_hytale_ik_chain_load_defaults.bl_idname,
                delete_idname=RIG_OT_hytale_rig_template_delete.bl_idname,
                save_idname=RIG_OT_hytale_rig_template_save.bl_idname,
                active_label=tr("panel.active_rig_template", lang),
                active_name=armature.hytale_active_rig_template or tr("panel.template_none", lang),
                active_icon="ARMATURE_DATA",
                load_label=tr("panel.load_template_action", lang),
            )

            _draw_template_picker(
                tmpl_box, wm,
                selected_attr="hytale_shape_template_selected",
                apply_idname=RIG_OT_hytale_shape_template_apply.bl_idname,
                delete_idname=RIG_OT_hytale_shape_template_delete.bl_idname,
                save_idname=RIG_OT_hytale_shape_template_save.bl_idname,
                active_label=tr("panel.active_shape_template", lang),
                active_name=armature.hytale_active_shape_template or tr("panel.template_none", lang),
                active_icon="MESH_DATA",
                load_label=tr("panel.load_template_action", lang),
            )

            _draw_template_picker(
                tmpl_box, wm,
                selected_attr="hytale_collection_template_selected",
                apply_idname=RIG_OT_hytale_collection_template_apply.bl_idname,
                delete_idname=RIG_OT_hytale_collection_template_delete.bl_idname,
                save_idname=RIG_OT_hytale_collection_template_save.bl_idname,
                active_label=tr("panel.active_collection_template", lang),
                active_name=armature.hytale_active_collection_template or tr("panel.template_none", lang),
                active_icon="GROUP_BONE",
                load_label=tr("panel.load_template_action", lang),
            )

            utils_row = tmpl_box.row(align=True)
            utils_row.operator(
                TEMPLATES_OT_reload.bl_idname, text=tr("panel.btn_reload_templates", lang), icon="FILE_REFRESH",
            )
            utils_row.operator(
                TEMPLATES_OT_open_user_folder.bl_idname, text=tr("panel.btn_open_templates_folder", lang), icon="FILE_FOLDER",
            )

    # --- Animation ---

    def _draw_animation(self, layout, context, lang):
        obj = context.active_object
        is_armature = is_active_armature(context)

        if not is_armature:
            layout.box().label(text=tr("panel.hint_anim_none", lang), icon="ERROR")
            return

        armature = obj.data

        # --- Bone Collections ---
        # Collections não aninham entre si -- cada uma pertence a uma
        # Section (puramente visual), e são as Sections que aninham.
        # Cada Section vira um cabeçalho seguido do grid de botões das
        # collections que apontam pra ela (agrupado por row/column, mesma
        # lógica de sempre, relativa aos irmãos da mesma Section).
        # show_in_animation_tab pula só o botão -- a collection continua
        # existindo em todo o resto.
        #
        # Só mostra/esconde -- não cria nada; um botão só nasce se a
        # collection já existir de verdade nesse Armature.
        coll_box = layout.box()
        coll_box.label(text=tr("panel.anim_collections_box", lang), icon="OUTLINER_OB_ARMATURE")
        any_collection_found = False

        def toggle_button(target_row, name):
            # prop() direto na property nativa is_visible (não um
            # operator()) -- dois ganhos: arrastar o mouse sobre vários
            # botões desta row liga/desliga todos de uma vez
            # (comportamento nativo pra prop(toggle=True) em
            # row(align=True)); aceita botão direito -> "Insert Keyframe"
            # como qualquer campo do painel.
            nonlocal any_collection_found
            coll = armature.collections_all.get(name)
            if coll is None:
                return False
            any_collection_found = True
            target_row.prop(
                coll, "is_visible", text=name,
                icon="HIDE_OFF" if coll.is_visible else "HIDE_ON",
                toggle=True,
            )
            return True

        # Agrupa as collections por Section resolvida -- mesma lógica
        # reaproveitada em sync_bone_collection_order (rigger/bone_collections.py).
        by_section = {}
        for item in armature.hytale_bone_collections:
            if not item.name or item.entry_type != "COLLECTION":
                continue
            by_section.setdefault(_resolve_collection_section_name(armature, item), []).append(item)

        def render_section_collections(section_box, items, depth):
            """Desenha o grid de botões (agrupado por `row`, colunas
            lado a lado) das collections de uma Section. `depth` só
            indenta visualmente, não afeta agrupamento/ordem."""
            any_drawn = False
            current_row_value = None
            ui_row = None
            for item in sorted(items, key=_collection_sort_key):
                if not item.show_in_animation_tab:
                    continue
                if item.row != current_row_value or ui_row is None:
                    current_row_value = item.row
                    ui_row = section_box.row(align=True)
                    ui_row.scale_y = 1.2
                    if depth:
                        ui_row.separator(factor=2.0 * depth)
                if toggle_button(ui_row, item.name):
                    any_drawn = True
            return any_drawn

        # Qualquer chave de by_section sem Section correspondente (nome
        # apagado, ou usuário apagou todas as Sections) é desenhada por
        # último, sem cabeçalho -- grupo implícito "Root".
        visited_section_names = set()
        for sec, depth in _iter_sections_in_order(armature):
            items = by_section.get(sec.name, [])
            visited_section_names.add(sec.name)
            if not items:
                continue
            # Preview barato: só materializa o cabeçalho se pelo menos
            # uma das collections já existir de verdade no Armature --
            # senão sobraria um título sem nenhum botão embaixo.
            has_real_collection = any(
                item.show_in_animation_tab and armature.collections_all.get(item.name) is not None
                for item in items
            )
            if not has_real_collection:
                continue
            section_row = coll_box.row()
            if depth:
                section_row.separator(factor=2.0 * depth)
            section_row.label(text=sec.name, icon="OUTLINER_COLLECTION")
            render_section_collections(coll_box, items, depth)

        for section_name, items in by_section.items():
            if section_name in visited_section_names:
                continue
            render_section_collections(coll_box, items, 0)

        if not any_collection_found:
            coll_box.label(text=tr("panel.hint_anim_no_rig", lang), icon="INFO")

        layout.separator()

        # --- FK / IK ---
        # Uma linha por cadeia Arm/Leg que já tem o switch de verdade
        # gerado (get_fk_ik_state -- None pula a linha). Os botões FK/IK
        # da lista fazem uma troca crua (só a influência, sem mexer na
        # pose). "Snap FK/IK" acima da lista faz o trabalho dos dois
        # juntos (igualar a pose e trocar) pra uma cadeia só -- a do bone
        # ativo selecionado.
        fkik_box = layout.box()
        fkik_box.label(text=tr("panel.anim_fkik_box", lang), icon="CON_KINEMATIC")

        fkik_box.operator(
            ANIM_OT_hytale_snap_selected.bl_idname,
            text=tr("panel.btn_snap_selected", lang),
            icon="SNAP_ON",
        )

        # Reordena a lista pela collection real que cada cadeia caiu, na
        # ordem de "Collection Settings" -- lê direto a collection de
        # verdade que o bone raiz já está (ground truth), em vez de
        # reimplementar a lógica de lado/prefixo de bone em paralelo.
        # Testa root_bone e tip_bone, cada um com "_CTRL" e "_IK" --
        # o membro que carrega a membership de Main na prática varia
        # conforme o rig (ver _propagate_pole_and_tip_to_main_collections).
        def resolve_chain_collection_name(item):
            known_names = {c.name for c in armature.hytale_bone_collections if c.name}
            candidate_names = []
            for base in (item.root_bone, item.tip_bone):
                if base:
                    candidate_names.append(control_name(armature, base, SUFFIX_CTRL))
                    candidate_names.append(control_name(armature, base, SUFFIX_IK))
            for name in candidate_names:
                bone = armature.bones.get(name)
                if bone is None:
                    continue
                for coll in bone.collections:
                    if coll.name in known_names:
                        return coll.name
            return None

        # A "posição" de cada collection vem da grade (row, column, name)
        # de Collection Settings, não da ordem crua da lista.
        sorted_collections = sorted(
            (c for c in armature.hytale_bone_collections if c.name), key=_collection_sort_key
        )
        collection_order = {c.name: i for i, c in enumerate(sorted_collections)}
        # Row de cada collection -- usado só pra decidir agrupamento
        # visual (duas cadeias no mesmo Row viram colunas lado a lado,
        # mesma UI row). A ordenação em si continua por collection_order.
        collection_row = {c.name: c.row for c in armature.hytale_bone_collections if c.name}

        fkik_rows = []
        for index, item in enumerate(armature.hytale_ik_chains):
            state = get_fk_ik_state(obj, item)
            if state is None:
                continue
            coll_name = resolve_chain_collection_name(item)
            sort_key = collection_order.get(coll_name, len(collection_order))
            # Cadeia sem collection resolvida nunca agrupa com outra --
            # usa o próprio índice como bucket único.
            row_bucket = ("row", collection_row[coll_name]) if coll_name in collection_row else ("solo", index)
            fkik_rows.append((sort_key, index, item, state, row_bucket))
        # Índice original como desempate mantém estável a ordem entre
        # cadeias que caíram na mesma collection.
        fkik_rows.sort(key=lambda r: (r[0], r[1]))

        any_chain_found = False
        current_bucket = None
        ui_row = None
        for sort_key, index, item, state, row_bucket in fkik_rows:
            any_chain_found = True
            if row_bucket != current_bucket or ui_row is None:
                current_bucket = row_bucket
                ui_row = fkik_box.row(align=True)
            else:
                # Respiro visual entre duas cadeias que caem na mesma UI
                # row (compartilham Row).
                ui_row.separator(factor=3.0)
            # split(factor=...) fixa a proporção label/botões,
            # consistente pra qualquer texto de label -- um row() comum
            # dava vão inconsistente (nomes curtos como "Arm R" deixavam
            # espaço vazio grande antes dos botões).
            split = ui_row.split(factor=0.35, align=True)
            split.label(text=item.label or item.root_bone or "(?)")
            sub = split.row(align=True)
            op_fk = sub.operator(ANIM_OT_hytale_set_fk_ik.bl_idname, text="FK", depress=(state == 0))
            op_fk.chain_index = index
            op_fk.mode = "FK"
            op_ik = sub.operator(ANIM_OT_hytale_set_fk_ik.bl_idname, text="IK", depress=(state == 1))
            op_ik.chain_index = index
            op_ik.mode = "IK"
            key_op = sub.operator(ANIM_OT_hytale_keyframe_switch.bl_idname, text="", icon="KEY_HLT")
            key_op.switch = "FK_IK"
            key_op.chain_index = index
        if not any_chain_found:
            fkik_box.label(text=tr("panel.hint_anim_no_fkik", lang), icon="INFO")

        # --- Head Free/Lock ---
        # Mesmo espírito da box FK/IK, um switch só (existe um único
        # Head_CTRL no rig). None quando "Head Free/Lock" nunca foi
        # ligado -- a box nem aparece. Sem "Snap" equivalente (não haveria
        # "lado oposto" pra igualar do mesmo jeito).
        head_follow_state = get_head_follow_state(obj)
        if head_follow_state is not None:
            layout.separator()
            head_follow_box = layout.box()
            head_follow_box.label(text=tr("panel.anim_head_follow_box", lang), icon="CON_CHILDOF")
            row = head_follow_box.row(align=True)
            op_free = row.operator(
                ANIM_OT_hytale_set_head_follow.bl_idname, text="Free", depress=(head_follow_state == 0)
            )
            op_free.mode = "FREE"
            op_lock = row.operator(
                ANIM_OT_hytale_set_head_follow.bl_idname, text="Lock", depress=(head_follow_state == 1)
            )
            op_lock.mode = "LOCK"
            row.operator(
                ANIM_OT_hytale_keyframe_switch.bl_idname, text="", icon="KEY_HLT"
            ).switch = "HEAD_FOLLOW"

    # --- Info ---

    def _draw_info(self, layout, context, lang):
        """Sem lógica nenhuma, só créditos/links. URLs em branco por
        enquanto (HYBLEND_*_URL no topo) -- botão correspondente fica
        desabilitado em vez de sumir, já deixando o layout final montado.

        Usa o operador nativo wm.url_open pra abrir link externo."""
        # Crédito ao Hytale/Hypixel Studios: o addon existe pra servir o
        # jogo, sem participação da Hypixel Studios na criação -- vem com
        # disclaimer de não-afiliação junto.
        hypixel_box = layout.box()
        hypixel_col = hypixel_box.column(align=True)
        hytale_row = hypixel_col.row(align=True)
        hytale_row.label(text=tr("panel.info_credits_hytale_label", lang), icon="WORLD")
        hytale_sub = hytale_row.row(align=True)
        hytale_sub.alignment = "RIGHT"
        hytale_sub.enabled = bool(HYBLEND_HYTALE_URL)
        hytale_icon_value = _panel_icon_value("hytale")
        hytale_op = hytale_sub.operator(
            "wm.url_open",
            text="Hytale",
            **({"icon_value": hytale_icon_value} if hytale_icon_value else {}),
        )
        hytale_op.url = HYBLEND_HYTALE_URL or ""
        _draw_wrapped_label(hypixel_col, context, tr("panel.info_credits_hytale_disclaimer", lang))

        layout.separator()

        links_box = layout.box()
        links_box.label(text=tr("panel.info_links_label", lang), icon="URL")
        links_row = links_box.row(align=True)
        links_row.scale_y = 1.2
        nexusmods_col = links_row.row(align=True)
        nexusmods_col.enabled = bool(HYBLEND_NEXUSMODS_URL)
        nexusmods_icon_value = _panel_icon_value("nexus_mods")
        nexusmods_op = nexusmods_col.operator(
            "wm.url_open",
            text="Nexus Mods",
            **({"icon_value": nexusmods_icon_value} if nexusmods_icon_value else {"icon": "WORLD"}),
        )
        nexusmods_op.url = HYBLEND_NEXUSMODS_URL or ""
        github_col = links_row.row(align=True)
        github_col.enabled = bool(HYBLEND_GITHUB_URL)
        github_icon_value = _panel_icon_value("github")
        github_op = github_col.operator(
            "wm.url_open",
            text="GitHub",
            **({"icon_value": github_icon_value} if github_icon_value else {"icon": "COMMUNITY"}),
        )
        github_op.url = HYBLEND_GITHUB_URL or ""

        layout.separator()

        credits_box = layout.box()

        header_col = credits_box.column(align=True)
        header_col.label(text=tr("panel.info_credits_label", lang), icon="USER")
        header_col.label(text=tr("panel.info_credits_created_by_label", lang))
        credits_row = header_col.row(align=True)
        credits_row.label(text=HYBLEND_AUTHOR_NAME)
        icons_sub = credits_row.row(align=True)
        icons_sub.alignment = "RIGHT"

        patreon_col = icons_sub.row(align=True)
        patreon_col.enabled = bool(HYBLEND_PATREON_URL)
        patreon_icon_value = _panel_icon_value("patreon")
        patreon_op = patreon_col.operator(
            "wm.url_open",
            text="",
            **({"icon_value": patreon_icon_value} if patreon_icon_value else {"icon": "FUND"}),
        )
        patreon_op.url = HYBLEND_PATREON_URL or ""

        instagram_col = icons_sub.row(align=True)
        instagram_col.enabled = bool(HYBLEND_AUTHOR_INSTAGRAM_URL)
        instagram_icon_value = _panel_icon_value("instagram")
        instagram_op = instagram_col.operator(
            "wm.url_open",
            text="",
            **({"icon_value": instagram_icon_value} if instagram_icon_value else {"icon": "IMAGE_DATA"}),
        )
        instagram_op.url = HYBLEND_AUTHOR_INSTAGRAM_URL or ""

        twitter_col = icons_sub.row(align=True)
        twitter_col.enabled = bool(HYBLEND_AUTHOR_TWITTER_URL)
        twitter_icon_value = _panel_icon_value("twitter_x")
        twitter_op = twitter_col.operator(
            "wm.url_open",
            text="",
            **({"icon_value": twitter_icon_value} if twitter_icon_value else {"icon": "WORLD"}),
        )
        twitter_op.url = HYBLEND_AUTHOR_TWITTER_URL or ""

        youtube_col = icons_sub.row(align=True)
        youtube_col.enabled = bool(HYBLEND_AUTHOR_YOUTUBE_URL)
        youtube_icon_value = _panel_icon_value("youtube")
        youtube_op = youtube_col.operator(
            "wm.url_open",
            text="",
            **({"icon_value": youtube_icon_value} if youtube_icon_value else {"icon": "FILE_MOVIE"}),
        )
        youtube_op.url = HYBLEND_AUTHOR_YOUTUBE_URL or ""


def register():
    _load_panel_icons()
    WindowManager.hytale_active_tab = EnumProperty(items=_tab_items, default=0)
    WindowManager.hytale_rig_subtab = EnumProperty(items=_rig_subtab_items, default=0)
    # Estado (aberta/fechada) das seções collapsible -- só UI, não dado
    # do rig, por isso mora no WindowManager. Default False = fechada.
    WindowManager.hytale_show_bone_collections = BoolProperty(default=False)
    WindowManager.hytale_show_pole_settings = BoolProperty(default=False)
    WindowManager.hytale_show_templates = BoolProperty(default=False)
    WindowManager.hytale_show_texture_picker_plane = BoolProperty(default=False)
    WindowManager.hytale_show_texture_picker_companions = BoolProperty(default=False)
    WindowManager.hytale_show_texture_picker_grid = BoolProperty(default=False)
    WindowManager.hytale_show_export_texture_picker = BoolProperty(default=False)
    WindowManager.hytale_show_more_exports = BoolProperty(default=False)
    WindowManager.hytale_show_head_camera = BoolProperty(default=False)
    bpy.utils.register_class(HYTALE_MT_import_more_options)
    bpy.utils.register_class(HYTALE_PT_main)


def unregister():
    bpy.utils.unregister_class(HYTALE_PT_main)
    bpy.utils.unregister_class(HYTALE_MT_import_more_options)
    del WindowManager.hytale_show_head_camera
    del WindowManager.hytale_show_more_exports
    del WindowManager.hytale_show_export_texture_picker
    del WindowManager.hytale_show_texture_picker_grid
    del WindowManager.hytale_show_texture_picker_companions
    del WindowManager.hytale_show_texture_picker_plane
    del WindowManager.hytale_show_templates
    del WindowManager.hytale_show_bone_collections
    del WindowManager.hytale_show_pole_settings
    del WindowManager.hytale_rig_subtab
    del WindowManager.hytale_active_tab
    _unload_panel_icons()
