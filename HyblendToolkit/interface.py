"""
interface.py -- painel lateral (N-Panel) do HyblendToolkit.
==================================================================

Este submódulo NÃO tem lógica de import/export nenhuma -- só desenha
botões que chamam os operadores que já existem em importer.py
(`import_scene.hytale_blockymodel`) e exporter.py
(`export_scene.hytale_blockyanim`). Se um botão precisar de um operador
que ainda não existe, ele nasce no arquivo correspondente (import ->
importer.py, export -> exporter.py, nem-um-nem-outro -> um submódulo
novo), NÃO aqui -- ver DEVELOPER_NOTES.md, seção "Adicionando uma função
totalmente nova".

Reaproveita get_language()/L() de importer.py (em vez de duplicar um
segundo sistema de i18n) só pra que a preference de idioma
(HytaleImporterPreferences.language) afete o painel inteiro, não só o
diálogo de import. PANEL_LABELS abaixo é o dicionário de textos PRÓPRIO
deste painel (botões/dicas que não existem em importer.py) -- segue a
mesma convenção EN/PT_BR por consistência, não porque importer.py exija.

Nomes de aba (TAB_ITEMS) ficam só em inglês de propósito: são itens de
EnumProperty, fixados no registro da classe (mesma razão pela qual os
tooltips dos operadores também ficam em inglês -- ver o comentário sobre
isso no topo de importer.py).
"""

import bpy
from bpy.props import EnumProperty
from bpy.types import Panel, WindowManager

from .exporter import EXPORT_OT_hytale_blockyanim
from .importer import IMPORT_OT_hytale_blockymodel, L, get_language
from .anim_importer import IMPORT_OT_hytale_blockyanim
from .common import HYTALE_OT_pick_bone_into_field
from .rigger import (
    RIG_OT_hytale_clear_generated,
    RIG_OT_hytale_generate_rig,
    RIG_OT_hytale_ik_chain_add,
    RIG_OT_hytale_ik_chain_load_defaults,
    RIG_OT_hytale_ik_chain_pick_bone,
    RIG_OT_hytale_ik_chain_remove,
)

# RIG_UL_hytale_ik_chains não precisa de import -- template_list() abaixo
# referencia ela pelo nome da classe (string), igual o próprio rigger.py
# faz no RIG_PT_hytale_rigger.draw().

TAB_ITEMS = [
    ("IMPORT", "Import", "Import models and attachments", "IMPORT", 0),
    ("EXPORT", "Export", "Export animations", "EXPORT", 1),
    ("RIG", "Rig", "IK chains and rig generation", "CON_KINEMATIC", 2),
]

PANEL_LABELS = {
    "btn_import_new": {"EN": "New Model", "PT_BR": "Novo Modelo"},
    "btn_import_attach": {"EN": "Attach to Selected", "PT_BR": "Anexar ao Selecionado"},
    "hint_import_attach_none": {
        "EN": "Select the target Armature first",
        "PT_BR": "Selecione a Armature de destino primeiro",
    },
    "hint_import_attach_target": {
        "EN": "Armature:",
        "PT_BR": "Armature:",
    },
    "btn_import_anim": {
        "EN": "Import Animation",
        "PT_BR": "Importar Animação",
    },
    "hint_import_anim_none": {
        "EN": "Select the target Armature first",
        "PT_BR": "Selecione a Armature de destino primeiro",
    },
    "hint_import_anim_target": {
        "EN": "Armature:",
        "PT_BR": "Armature:",
    },
    "btn_export": {"EN": "Export Animations", "PT_BR": "Exportar Animações"},
    "hint_export_none": {
        "EN": "Select/activate an Armature to export",
        "PT_BR": "Selecione/ative uma Armature para exportar",
    },
    "hint_export_target": {
        "EN": "Exporting from:",
        "PT_BR": "Exportando de:",
    },
    "export_settings_box": {
        "EN": "Export Settings",
        "PT_BR": "Configurações de Export",
    },
    "mouth_animation": {
        "EN": "Mouth Animation",
        "PT_BR": "Animação da Boca",
    },
    "export_collection": {
        "EN": "Export Collection",
        "PT_BR": "Coleção de Export",
    },
    "mouth_bone": {
        "EN": "Mouth Bone",
        "PT_BR": "Bone da Boca",
    },
    "hint_rig_none": {
        "EN": "Select an Armature.",
        "PT_BR": "Selecione uma Armature.",
    },
    "ik_chains_box": {"EN": "IK Chains", "PT_BR": "Cadeias de IK"},
    "load_preset": {"EN": "Load Preset...", "PT_BR": "Carregar Preset..."},
    "btn_create_rig": {"EN": "Create Rig", "PT_BR": "Criar Rig"},
    "btn_remove_generated": {"EN": "Remove Generated Bones", "PT_BR": "Remover Bones Gerados"},
}


def PL(key, lang):
    """Mesma ideia da L() de importer.py, mas pro dicionário de textos
    deste painel (PANEL_LABELS em vez de LABELS)."""
    return PANEL_LABELS.get(key, {}).get(lang, key)


class HYTALE_PT_main(Panel):
    """Painel principal do addon na N-Panel da Viewport 3D (aba lateral
    'Hytale'). Só orquestra botões -- toda a lógica real mora nos
    operadores de importer.py / exporter.py."""

    bl_label = "Hyblend Toolkit"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Hytale"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        lang = get_language(context)

        layout.row(align=True).prop(wm, "hytale_active_tab", expand=True)

        tab = wm.hytale_active_tab
        if tab == "IMPORT":
            self._draw_import(layout, context, lang)
        elif tab == "EXPORT":
            self._draw_export(layout, context, lang)
        elif tab == "RIG":
            self._draw_rig(layout, context, lang)

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def _draw_import(self, layout, context, lang):
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator(
            IMPORT_OT_hytale_blockymodel.bl_idname,
            text=PL("btn_import_new", lang),
            icon="ARMATURE_DATA",
        ).import_mode = "NEW_ARMATURE"

        layout.separator()

        active = context.active_object
        is_armature = active is not None and active.type == "ARMATURE"

        box = layout.box()
        row = box.column(align=True)
        row.scale_y = 1.4
        op = row.operator(
            IMPORT_OT_hytale_blockymodel.bl_idname,
            text=PL("btn_import_attach", lang),
            icon="IMPORT",
        )
        op.import_mode = "ATTACH_EXISTING"
        if is_armature:
            # Pré-preenche o alvo com o objeto ativo -- o diálogo de
            # import ainda deixa trocar (prop_search), isso é só um
            # atalho pro caso comum (usuário já selecionou a Armature
            # certa antes de clicar).
            op.target_armature_name = active.name

        hint = box.row()
        if is_armature:
            hint.label(text=f"{PL('hint_import_attach_target', lang)} {active.name}", icon="ARMATURE_DATA")
        else:
            hint.label(text=PL("hint_import_attach_none", lang), icon="INFO")

        layout.separator()

        # IMPORT_OT_hytale_blockyanim é ImportHelper com seu próprio
        # draw() -- ele já desenha target_mode/action_name/start_frame/
        # loop_mode/bake_mode/keep_spine_follow (condicional) sozinho na
        # sidebar do file browser. Aqui só o botão que dispara ele +
        # aviso de Armature ativa (mesmo poll() que já existe no
        # operador, isso é só feedback visual antecipado).
        anim_box = layout.box()
        anim_col = anim_box.column(align=True)
        anim_col.scale_y = 1.4
        anim_col.operator(
            IMPORT_OT_hytale_blockyanim.bl_idname,
            text=PL("btn_import_anim", lang),
            icon="ANIM",
        )

        anim_hint = anim_box.row()
        if is_armature:
            anim_hint.label(text=f"{PL('hint_import_anim_target', lang)} {active.name}", icon="ARMATURE_DATA")
        else:
            anim_hint.label(text=PL("hint_import_anim_none", lang), icon="INFO")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _draw_export(self, layout, context, lang):
        active = context.active_object
        is_armature = active is not None and active.type == "ARMATURE"

        box = layout.box()
        if is_armature:
            box.label(text=f"{PL('hint_export_target', lang)} {active.name}", icon="ARMATURE_DATA")
        else:
            box.label(text=PL("hint_export_none", lang), icon="ERROR")

        if is_armature:
            # active.data.hytale_export_settings é PointerProperty ->
            # HYTALE_export_bone_settings, registrada por exporter.py
            # (mesmo padrão do hytale_ik_chains do rigger.py: quem é
            # dono da lógica registra o dado em Armature, aqui só
            # desenha). Não passa por get_export_bone_settings() -- essa
            # função é só um atalho interno do exporter.py, o painel lê
            # o caminho direto (ver comentário dele em exporter.py).
            settings = active.data.hytale_export_settings

            settings_box = layout.box()
            settings_box.label(text=PL("export_settings_box", lang), icon="TOOL_SETTINGS")
            settings_box.prop(settings, "export_collection_name", text=PL("export_collection", lang))
            settings_box.prop(settings, "export_uv_offset", text=PL("mouth_animation", lang))
            if settings.export_uv_offset:
                sub = settings_box.column(align=True)

                def uv_picker_row(field_name, text=None):
                    r = sub.row(align=True)
                    if text is not None:
                        r.prop(settings, field_name, text=text)
                    else:
                        r.prop(settings, field_name)
                    op = r.operator(HYTALE_OT_pick_bone_into_field.bl_idname, text="", icon="EYEDROPPER")
                    op.data_path = "data.hytale_export_settings"
                    op.field = field_name

                uv_picker_row("uv_offset_source_bone")
                uv_picker_row("uv_offset_target_bone", text=PL("mouth_bone", lang))

        col = layout.column(align=True)
        col.scale_y = 1.4
        row = col.row()
        # export_scene.hytale_blockyanim já tem seu próprio poll()
        # exigindo Armature ativo (ver exporter.py) -- isso aqui é só
        # feedback visual antecipado, não substitui o poll.
        row.enabled = is_armature
        row.operator(
            EXPORT_OT_hytale_blockyanim.bl_idname,
            text=PL("btn_export", lang),
            icon="EXPORT",
        )

    # ------------------------------------------------------------------
    # Rig
    # ------------------------------------------------------------------

    def _draw_rig(self, layout, context, lang):
        obj = context.active_object
        is_armature = obj is not None and obj.type == "ARMATURE"

        if not is_armature:
            layout.box().label(text=PL("hint_rig_none", lang), icon="ERROR")
            return

        armature = obj.data

        box = layout.box()
        box.label(text=PL("ik_chains_box", lang), icon="BONE_DATA")

        row = box.row()
        row.template_list(
            "RIG_UL_hytale_ik_chains", "",
            armature, "hytale_ik_chains",
            armature, "hytale_ik_chains_index",
        )
        col = row.column(align=True)
        col.operator(RIG_OT_hytale_ik_chain_add.bl_idname, text="", icon="ADD")
        col.operator(RIG_OT_hytale_ik_chain_remove.bl_idname, text="", icon="REMOVE")

        box.operator_menu_enum(
            RIG_OT_hytale_ik_chain_load_defaults.bl_idname,
            "preset",
            text=PL("load_preset", lang),
            icon="IMPORT",
        )

        index = armature.hytale_ik_chains_index
        if 0 <= index < len(armature.hytale_ik_chains):
            item = armature.hytale_ik_chains[index]
            col = box.column(align=True)

            def picker_row(field_name):
                r = col.row(align=True)
                r.prop(item, field_name)
                op = r.operator(RIG_OT_hytale_ik_chain_pick_bone.bl_idname, text="", icon="EYEDROPPER")
                op.chain_index = index
                op.field = field_name

            picker_row("root_bone")
            picker_row("tip_bone")
            picker_row("pole_bone")
            picker_row("parent_override")

            col.prop(item, "side")
            row = col.row(align=True)
            row.prop(item, "pole_invert")
            row.prop(item, "extra_ik_location")
            col.prop(item, "pole_distance")
            col.prop(item, "pole_angle_mode")
            if item.pole_angle_mode == "MANUAL":
                col.prop(item, "pole_angle_manual")
            elif item.pole_angle_mode == "AUTO":
                col.prop(item, "pole_angle_fine_tune")
            # modo "ARM" não tem campo extra -- usa ARM_POLE_ANGLE_PRESET[side]
            # (ver rigger.py, é o mesmo comportamento do painel de referência dele)

        layout.separator()

        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator(
            RIG_OT_hytale_generate_rig.bl_idname,
            text=PL("btn_create_rig", lang),
            icon="ARMATURE_DATA",
        )

        layout.separator()
        layout.operator(
            RIG_OT_hytale_clear_generated.bl_idname,
            text=PL("btn_remove_generated", lang),
            icon="TRASH",
        )


def register():
    WindowManager.hytale_active_tab = EnumProperty(items=TAB_ITEMS, default="IMPORT")
    bpy.utils.register_class(HYTALE_PT_main)


def unregister():
    bpy.utils.unregister_class(HYTALE_PT_main)
    del WindowManager.hytale_active_tab
