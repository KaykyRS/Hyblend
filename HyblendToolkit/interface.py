"""
interface.py -- painel lateral (N-Panel) do HytaleBlockyToolkit.
==================================================================

Este submódulo NÃO tem lógica de import/export/rig nenhuma -- só desenha
botões que chamam os operadores que já existem em importer.py
(`import_scene.hytale_blockymodel`), exporter.py
(`export_scene.hytale_blockyanim`), rigger.py (geração de rig, cadeias
de IK) e templates/ (descoberta/reload de templates de personagem). Se
um botão precisar de um operador que ainda não existe, ele nasce no
arquivo correspondente (import -> importer.py, export -> exporter.py,
rig -> rigger.py, nem-um-nem-outro -> um submódulo novo), NÃO aqui --
ver DEVELOPER_NOTES.md, seção "Adicionando uma função totalmente nova".

Usa get_language()/tr() do pacote translations/ (mesmo sistema que
importer.py usa) pra que a preference de idioma
(HytaleImporterPreferences.language, definida em importer.py) afete o
painel inteiro, não só o diálogo de import. As keys de texto PRÓPRIAS
deste painel (botões/dicas que não existem em importer.py) vivem nos
arquivos de translations/ com o prefixo "panel." -- ver
translations/en.py pra a lista completa e translations/__init__.py pra
como o sistema funciona.

Nomes de aba (TAB_ITEMS) ficam só em inglês de propósito: são itens de
EnumProperty, fixados no registro da classe (mesma razão pela qual os
tooltips dos operadores também ficam em inglês -- ver o comentário sobre
isso no topo de importer.py).
"""

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Panel, WindowManager

from .exporter import EXPORT_OT_hytale_blockyanim
from .importer import IMPORT_OT_hytale_blockymodel, IMPORT_OT_hytale_bbmodel
from .anim_importer import IMPORT_OT_hytale_blockyanim
from .anim_tools import (
    ANIM_OT_hytale_set_fk_ik,
    ANIM_OT_hytale_snap_selected,
    ANIM_OT_hytale_toggle_collection_visibility,
    get_fk_ik_state,
)
from .common import HYTALE_OT_pick_bone_into_field
from .translations import get_language, tr
from .rigger import (
    RIG_MT_hytale_ik_chain_add_menu,
    RIG_OT_hytale_bone_collection_add,
    RIG_OT_hytale_bone_collection_load_defaults,
    RIG_OT_hytale_bone_collection_move,
    RIG_OT_hytale_bone_collection_remove,
    RIG_OT_hytale_bone_collection_reset_grid,
    RIG_OT_hytale_clear_generated,
    RIG_OT_hytale_collection_template_apply,
    RIG_OT_hytale_collection_template_delete,
    RIG_OT_hytale_collection_template_save,
    RIG_OT_hytale_generate_rig,
    RIG_OT_hytale_ik_chain_load_defaults,
    RIG_OT_hytale_ik_chain_move,
    RIG_OT_hytale_ik_chain_pick_bone,
    RIG_OT_hytale_ik_chain_remove,
    RIG_OT_hytale_mirror_shape,
    RIG_OT_hytale_rig_template_delete,
    RIG_OT_hytale_rig_template_save,
    RIG_OT_hytale_shape_edit_mode_enter,
    RIG_OT_hytale_shape_edit_mode_finish,
    RIG_OT_hytale_shape_template_apply,
    RIG_OT_hytale_shape_template_delete,
    RIG_OT_hytale_shape_template_save,
    RIG_OT_hytale_validate_rig,
    SUFFIX_CTRL,
    SUFFIX_IK,
    PARENT_COLLECTION_ROOT,
    _collection_sort_key,
)
from .templates import TEMPLATES_OT_open_user_folder, TEMPLATES_OT_reload

# RIG_UL_hytale_ik_chains não precisa de import -- template_list() abaixo
# referencia ela pelo nome da classe (string), igual o próprio rigger.py
# faz no RIG_PT_hytale_rigger.draw().

TAB_ITEMS = [
    ("IMPORT", "Import", "Import models and attachments", "IMPORT", 0),
    ("EXPORT", "Export", "Export animations", "EXPORT", 1),
    ("RIG", "Rig", "IK chains and rig generation", "CON_KINEMATIC", 2),
    ("ANIMATION", "Animation", "Bone collection visibility and FK/IK switches", "ANIM", 3),
]

# O dicionário PANEL_LABELS/PL que morava aqui virou o pacote
# translations/ (mesmo sistema que importer.py usa) -- as keys deste
# painel vivem lá com o prefixo "panel." (ver translations/en.py). Este
# arquivo só chama tr("panel.<key>", lang) abaixo, do mesmo jeito que
# antes chamava PL("<key>", lang).

# v0.7: cada item da lista agora tem um item.chain_type (ARM/LEG/TAIL --
# ver HytaleIKChainItem em rigger.py). ARM e LEG usam os MESMOS 4 campos
# de sempre (root_bone/tip_bone/pole_bone/parent_override) -- só o
# RÓTULO exibido muda, pra refletir a nomenclatura de cada membro (ex.:
# "Root Bone" vira "Arm" pro tipo Arm, "Thigh" pro tipo Leg). Chave de
# tradução (não texto cru) -- cada valor aqui é uma key de translations/,
# resolvida via tr() no ponto de uso (mesmo padrão do resto do arquivo).
# TAIL não entra aqui -- tem um conjunto de campos totalmente diferente,
# desenhado à parte em _draw_rig (sem pole/side/pole_angle, que só fazem
# sentido pra uma cadeia com IK).
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
    Templates": UMA linha de status (nome da categoria + template
    ATIVO no armature, ex. "Rig Template: Player") seguida de UMA linha
    de ação (dropdown "Load" + Apply/Delete/Save) -- o nome da
    categoria só aparece uma vez (na linha de status), a linha de baixo
    só descreve a AÇÃO ("Load"), não repete "Rig Template"/etc de novo.
    Escolher um item no dropdown só GRAVA a seleção (é uma property
    comum -- abrir o dropdown e clicar num item não dispara nada
    sozinho, ao contrário do antigo operator_menu_enum); "Apply" é quem
    de fato aplica o template selecionado, "Delete" quem apaga
    (desabilitado -- poll() do operador -- se o selecionado for builtin
    ou "(none)")."""
    box.label(text=f"{active_label} {active_name}", icon=active_icon)
    # split(factor=...) em vez de row.label()+row.prop() soltos -- dentro
    # de um row() comum, label() e prop() disputam a largura igualmente
    # entre si (cada item "flexível" recebe uma fatia igual), o que
    # deixava o texto "Load" ocupando ~50% da linha à toa. split() força
    # a proporção explícita: uma fatia pequena e fixa pro label, o resto
    # (dropdown + os 3 botões, agrupados no sub-row seguinte) pega o
    # resto todo.
    split = box.split(factor=0.14, align=True)
    split.label(text=load_label)
    row = split.row(align=True)
    row.prop(wm, selected_attr, text="")
    row.operator(apply_idname, text="", icon="IMPORT")
    row.operator(delete_idname, text="", icon="TRASH")
    row.operator(save_idname, text="", icon="EXPORT")



class HYTALE_PT_main(Panel):
    """Painel principal do addon na N-Panel da Viewport 3D (aba lateral
    'Hyblend'). Só orquestra botões -- toda a lógica real mora nos
    operadores de importer.py / exporter.py."""

    bl_label = "Hyblend Toolkit"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Hyblend"

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
        elif tab == "ANIMATION":
            self._draw_animation(layout, context, lang)

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def _draw_import(self, layout, context, lang):
        # Duas fontes de "modelo novo" agora: IMPORT_OT_hytale_blockymodel
        # (modo NEW_ARMATURE) e IMPORT_OT_hytale_bbmodel (só tem um modo,
        # sempre cria Armature nova -- ver comentário em importer.py,
        # seção "Suporte a .bbmodel"). Agrupados sob um cabeçalho comum
        # "New Model" pra deixar claro que são duas portas de entrada
        # pro mesmo resultado (Armature nova), não duas features
        # diferentes.
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

        layout.separator()

        active = context.active_object
        is_armature = active is not None and active.type == "ARMATURE"

        box = layout.box()
        row = box.column(align=True)
        row.scale_y = 1.4
        op = row.operator(
            IMPORT_OT_hytale_blockymodel.bl_idname,
            text=tr("panel.btn_import_attach", lang),
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
            hint.label(text=f"{tr('panel.hint_import_attach_target', lang)} {active.name}", icon="ARMATURE_DATA")
        else:
            hint.label(text=tr("panel.hint_import_attach_none", lang), icon="INFO")

        layout.separator()

        # IMPORT_OT_hytale_blockyanim é ImportHelper com seu próprio
        # draw() -- ele já desenha target_mode/action_name/start_frame/
        # loop_mode/bake_mode/keep_spine_follow (condicional) sozinho na
        # sidebar do file browser. Aqui só o botão que dispara ele +
        # aviso de Armature ativa (mesmo poll() que já existe no
        # operador, isso é só feedback visual antecipado).
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

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _draw_export(self, layout, context, lang):
        active = context.active_object
        is_armature = active is not None and active.type == "ARMATURE"

        box = layout.box()
        if is_armature:
            box.label(text=f"{tr('panel.hint_export_target', lang)} {active.name}", icon="ARMATURE_DATA")
        else:
            box.label(text=tr("panel.hint_export_none", lang), icon="ERROR")

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
            settings_box.label(text=tr("panel.export_settings_box", lang), icon="TOOL_SETTINGS")
            settings_box.prop(settings, "export_collection_name", text=tr("panel.export_collection", lang))

            mouth_row = settings_box.row(align=True)
            mouth_row.prop(settings, "export_uv_offset", text=tr("panel.mouth_animation", lang))
            wip_sub = mouth_row.row()
            wip_sub.alignment = "RIGHT"
            wip_sub.label(text=tr("panel.warn_mouth_wip_short", lang), icon="ERROR")

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
                uv_picker_row("uv_offset_target_bone", text=tr("panel.mouth_bone", lang))

        col = layout.column(align=True)
        col.scale_y = 1.4
        row = col.row()
        # export_scene.hytale_blockyanim já tem seu próprio poll()
        # exigindo Armature ativo (ver exporter.py) -- isso aqui é só
        # feedback visual antecipado, não substitui o poll.
        row.enabled = is_armature
        row.operator(
            EXPORT_OT_hytale_blockyanim.bl_idname,
            text=tr("panel.btn_export", lang),
            icon="EXPORT",
        )

    # ------------------------------------------------------------------
    # Rig
    # ------------------------------------------------------------------

    def _draw_rig(self, layout, context, lang):
        layout.label(text=tr("panel.warn_rig_experimental", lang), icon="ERROR")

        obj = context.active_object
        is_armature = obj is not None and obj.type == "ARMATURE"

        if not is_armature:
            layout.box().label(text=tr("panel.hint_rig_none", lang), icon="ERROR")
            return

        armature = obj.data
        wm = context.window_manager

        # Ação principal primeiro (pedido explícito: os dois botões ficam
        # acima de tudo, "IK Chains" e "Character Templates" -- o fluxo
        # comum do dia a dia é só clicar "Create Rig" de novo depois de
        # anexar um attachment; as seções de configuração ficam
        # collapsed abaixo, fora do caminho).
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator(
            RIG_OT_hytale_generate_rig.bl_idname,
            text=tr("panel.btn_create_rig", lang),
            icon="ARMATURE_DATA",
        )

        layout.separator()

        # Shape Edit Mode -- alterna entre os dois operadores conforme
        # armature.hytale_shape_edit_mode (registrado em rigger.py). O
        # poll() de RIG_OT_hytale_shape_edit_mode_enter já cobre "sem
        # rig gerado ainda" (armature_has_generated_bones) -- não
        # precisamos checar nada aqui, o Blender desabilita o botão
        # sozinho quando poll() volta False.
        if armature.hytale_shape_edit_mode:
            layout.operator(
                RIG_OT_hytale_shape_edit_mode_finish.bl_idname,
                text=tr("panel.btn_shape_edit_finish", lang),
                icon="CHECKMARK",
            )

            # Edição inline do custom shape do pose bone ativo --
            # translation/rotation/scale são properties NATIVAS do
            # PoseBone (custom_shape_translation/_rotation_euler/
            # _scale_xyz), sem registro novo -- rigger.py já lê/escreve
            # essas mesmas properties (Shape Edit Mode Enter/Finish,
            # Mirror Shape). Mirror Shape fica cinza sozinho (poll())
            # quando o bone ativo não começa com "L-"/"R-" -- sempre
            # desenhamos o botão quando há um bone ativo, sem duplicar
            # essa checagem aqui.
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
                    RIG_OT_hytale_mirror_shape.bl_idname,
                    text=tr("panel.btn_mirror_shape", lang),
                    icon="MOD_MIRROR",
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

        layout.separator()
        layout.operator(
            RIG_OT_hytale_clear_generated.bl_idname,
            text=tr("panel.btn_remove_generated", lang),
            icon="TRASH",
        )

        layout.separator()

        # Validate Rig ("Check Rig" na UI) -- diagnóstico puro
        # (bl_options = {"REGISTER"}, sem UNDO -- não muda nada no
        # armature). Fica no final do bloco de ações principais,
        # abaixo de Remove Generated Bones. O operador já tem um
        # default sensato pra sua StringProperty própria
        # (export_collection_name) -- não precisamos desenhar nenhum
        # campo pra ela, só chamar o operador puro.
        layout.operator(
            RIG_OT_hytale_validate_rig.bl_idname,
            text=tr("panel.btn_validate_rig", lang),
            icon="VIEWZOOM",
        )

        layout.separator()

        # ------------------------------------------------------------
        # IK Chains -- collapsible (fechada por padrão, ver
        # hytale_show_ik_chains registrada no fim deste arquivo).
        # O truque do "header clicável" é um único prop() de bool com
        # texto + ícone de seta e emboss=False -- sem isso, teria que
        # desenhar um botão E um label separados (mais verboso, mesmo
        # resultado visual).
        # ------------------------------------------------------------
        # v0.7: a box deixou de ser só sobre IK (agora cobre Arm/Leg/Tail
        # -- ver _LIMB_FIELD_LABELS acima) -- a KEY continua "panel.
        # ik_chains_box" (não renomeei pra não duplicar texto em
        # translations/), só o TEXTO que ela resolve precisa mudar pra
        # algo mais genérico (ex. "Bone Settings") -- ver aviso no fim da
        # resposta sobre o que precisa mudar em translations/en.py (e
        # pt_br.py).
        ik_header = layout.row()
        ik_header.prop(
            wm, "hytale_show_ik_chains",
            text=tr("panel.ik_chains_box", lang),
            icon="TRIA_DOWN" if wm.hytale_show_ik_chains else "TRIA_RIGHT",
            emboss=False,
        )

        if wm.hytale_show_ik_chains:
            box = layout.box()

            row = box.row()
            row.template_list(
                "RIG_UL_hytale_ik_chains", "",
                armature, "hytale_ik_chains",
                armature, "hytale_ik_chains_index",
            )
            col = row.column(align=True)
            # v0.7: "+" não adiciona mais uma cadeia genérica direto --
            # abre o menu popup (RIG_MT_hytale_ik_chain_add_menu, em
            # rigger.py) perguntando o tipo (Arm/Leg/Tail) primeiro.
            # wm.call_menu é o operador genérico do Blender pra abrir
            # QUALQUER Menu registrado pelo bl_idname -- não precisamos
            # de um operador próprio só pra isso.
            col.operator("wm.call_menu", text="", icon="ADD").name = RIG_MT_hytale_ik_chain_add_menu.bl_idname
            col.operator(RIG_OT_hytale_ik_chain_remove.bl_idname, text="", icon="REMOVE")
            # Setinhas de reordenar -- mesma coluna alinhada do +/-, com
            # um separator() pra dar uma respiradinha visual entre os
            # dois grupos (add/remove vs mover), convenção comum em
            # UILists do próprio Blender (ex. Modifiers, Vertex Groups).
            col.separator()
            col.operator(RIG_OT_hytale_ik_chain_move.bl_idname, text="", icon="TRIA_UP").direction = "UP"
            col.operator(RIG_OT_hytale_ik_chain_move.bl_idname, text="", icon="TRIA_DOWN").direction = "DOWN"

            # armature.hytale_apply_ik_joint_fix é BoolProperty
            # (Armature.hytale_apply_ik_joint_fix, registrada em
            # rigger.py -- renomeada de hytale_apply_player_arm_ik_fix na
            # v0.6, quando os valores de correção de junta deixaram de
            # ser exclusivos do Player e passaram a vir de
            # rig_template["ik_joint_x_overrides"] -- ver
            # templates/__init__.py). O rótulo aqui usa text=tr(...) pra
            # ficar traduzido -- o TOOLTIP continua vindo do bl_description
            # fixo em inglês em rigger.py (ver comentário no topo de
            # translations/__init__.py sobre por que isso não passa por
            # tr()). O "Load Preset" (dentro da box de Character
            # Templates, abaixo) liga/desliga essa opção automaticamente
            # conforme rig_template["apply_ik_joint_fix"] do template
            # escolhido; fica aqui pra dar pra desligar/ligar na mão sem
            # recarregar o template inteiro.
            # Só faz sentido mostrar isso se já existe alguma entrada
            # ARM/LEG na lista -- a opção afeta bones de cadeias com IK,
            # entradas TAIL não usam nada disso (ver rigger.py).
            # v0.9 (Etapa 2) -- HEAD/SPINE não têm IK/joint fix igual
            # Tail já não tinha -- checa só ARM/LEG explicitamente agora,
            # em vez de "!= TAIL" (que antes cobria tudo que não era
            # Tail, quando só existiam ARM/LEG/TAIL).
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

                def picker_row(field_name, text):
                    r = col.row(align=True)
                    r.prop(item, field_name, text=text)
                    op = r.operator(RIG_OT_hytale_ik_chain_pick_bone.bl_idname, text="", icon="EYEDROPPER")
                    op.chain_index = index
                    op.field = field_name

                col.prop(item, "chain_type", text=tr("panel.field_chain_type", lang))

                if item.chain_type == "TAIL":
                    # v0.7: Tail não usa IK -- só o caminho root->tip (ver
                    # _build_tail_layer em rigger.py) e um parent opcional
                    # pra anexar a cauda no corpo. Sem pole/side/
                    # pole_angle/extra_ik_location, que só fazem sentido
                    # pra uma cadeia com solver de IK.
                    picker_row("parent_override", tr("panel.field_tail_parent", lang))
                    picker_row("root_bone", tr("panel.field_tail_start", lang))
                    picker_row("tip_bone", tr("panel.field_tail_end", lang))
                    row = col.row(align=True)
                    row.prop(item, "tail_tip_rotation_axis", text=tr("panel.field_tail_tip_rotation_axis", lang))
                    row.prop(item, "tail_tip_rotation_deg", text=tr("panel.field_tail_tip_rotation_deg", lang))
                    col.label(text=tr("panel.hint_tail_no_ik", lang), icon="INFO")
                    # v0.9 (Etapa 3) -- Tail também ganha o dropdown de
                    # Collection agora (antes ficava fixo em Main/Tail --
                    # pedido explícito: nenhum tipo deve ficar travado).
                    # "" (Auto) continua caindo em Main/Tail, sem mudar o
                    # comportamento de quem nunca mexer nisso.
                    col.separator()
                    col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
                elif item.chain_type == "HEAD":
                    # v0.9 (Etapa 2) -- Head não cria bone nenhum (ver
                    # _resolve_chains/_head_spine_bone_names em rigger.py)
                    # -- só identifica quais bones _CTRL já existentes são
                    # o Neck/Head/Head End, pra organização de collection.
                    # neck_count controla quantos dos 5 campos de Neck
                    # aparecem -- Head/Head End ficam sempre visíveis.
                    col.prop(item, "neck_count", text=tr("panel.field_neck_count", lang))
                    neck_fields = ["neck_bone_1", "neck_bone_2", "neck_bone_3", "neck_bone_4", "neck_bone_5"]
                    neck_labels = [
                        "panel.field_neck_1", "panel.field_neck_2", "panel.field_neck_3",
                        "panel.field_neck_4", "panel.field_neck_5",
                    ]
                    for field_name, label_key in list(zip(neck_fields, neck_labels))[: item.neck_count]:
                        picker_row(field_name, tr(label_key, lang))
                    picker_row("head_bone", tr("panel.field_head_bone", lang))
                    picker_row("head_end_bone", tr("panel.field_head_end_bone", lang))
                    col.label(text=tr("panel.hint_head_no_ik", lang), icon="INFO")
                    col.separator()
                    col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
                elif item.chain_type == "SPINE":
                    # v0.9 (Etapa 2) -- mesmo espírito de Head: nenhum bone
                    # é criado, só identificado. spine_count é o TOTAL de
                    # bones incluindo o Pelvis (1 = só Pelvis) -- Pelvis
                    # sempre visível, Spine1..4 conforme spine_count - 1.
                    col.prop(item, "spine_count", text=tr("panel.field_spine_count", lang))
                    picker_row("pelvis_bone", tr("panel.field_pelvis_bone", lang))
                    spine_fields = ["spine_bone_1", "spine_bone_2", "spine_bone_3", "spine_bone_4"]
                    spine_labels = [
                        "panel.field_spine_1", "panel.field_spine_2",
                        "panel.field_spine_3", "panel.field_spine_4",
                    ]
                    for field_name, label_key in list(zip(spine_fields, spine_labels))[: max(0, item.spine_count - 1)]:
                        picker_row(field_name, tr(label_key, lang))
                    col.label(text=tr("panel.hint_spine_no_ik", lang), icon="INFO")
                    col.separator()
                    col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
                elif item.chain_type == "ATTACHMENTS":
                    # v0.9.7 -- mesmo espírito de Head/Spine: nenhum bone é
                    # criado, só identificado. attachments_count controla
                    # quantos campos aparecem -- diferente de Head (que tem
                    # 2 campos "sempre visíveis" além do amount), aqui
                    # TODOS os slots são do mesmo tipo, então não tem
                    # nenhum campo fixo fora da contagem.
                    #
                    # v0.9.8 -- ERA uma lista de 5 nomes de campo + 5 keys
                    # de tradução escritas na mão -- teto subiu pra
                    # ATTACHMENTS_MAX_COUNT (25, ver rigger/constants.py),
                    # e escrever 25 keys de tradução (Attachment 6..25 etc.)
                    # seria só ruído. Em vez disso usa UMA key só
                    # ("Attachment", traduzível) e monta o número em
                    # código -- mesma ideia de "Neck 2"/"Spine2" que já
                    # existiam, só que sem precisar de uma key por número.
                    col.prop(item, "attachments_count", text=tr("panel.field_attachments_count", lang))
                    attachment_base_label = tr("panel.field_attachment", lang)
                    for i in range(1, item.attachments_count + 1):
                        label = attachment_base_label if i == 1 else f"{attachment_base_label} {i}"
                        picker_row(f"attachment_bone_{i}", label)
                    col.label(text=tr("panel.hint_attachments_no_ik", lang), icon="INFO")
                    col.separator()
                    col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
                else:
                    # ARM e LEG usam os MESMOS 4 campos/mesma lógica de
                    # sempre (ver rigger.py) -- só o RÓTULO muda por tipo
                    # (fallback pra "ARM" cobre qualquer chain_type
                    # desconhecido, ex. um template externo com typo, sem
                    # nunca quebrar a UI). Root Bone/Tip Bone continuam
                    # cobrindo cadeias com MAIS de 2 segmentos (ex. uma
                    # perna Thigh/Calf/Heel/Foot) sozinhos -- basta apontar
                    # as duas pontas, o caminho do meio é resolvido andando
                    # pela hierarquia (find_org_path, em rigger.py), sem
                    # precisar de um campo extra pra isso.
                    labels = _LIMB_FIELD_LABELS.get(item.chain_type, _LIMB_FIELD_LABELS["ARM"])
                    picker_row("parent_override", tr(labels["parent_override"], lang))
                    picker_row("root_bone", tr(labels["root_bone"], lang))
                    picker_row("pole_bone", tr(labels["pole_bone"], lang))
                    picker_row("tip_bone", tr(labels["tip_bone"], lang))

                    col.prop(item, "side", text=tr("panel.field_side", lang))
                    row = col.row(align=True)
                    row.prop(item, "pole_invert", text=tr("panel.field_pole_in_front", lang))
                    row.prop(item, "extra_ik_location", text=tr("panel.field_copy_location_ik", lang))
                    col.prop(item, "pole_distance", text=tr("panel.field_pole_distance", lang))
                    col.prop(item, "pole_angle_mode", text=tr("panel.field_pole_angle_mode", lang))
                    if item.pole_angle_mode == "MANUAL":
                        col.prop(item, "pole_angle_manual", text=tr("panel.field_pole_angle_manual", lang))
                    elif item.pole_angle_mode == "AUTO":
                        col.prop(item, "pole_angle_fine_tune", text=tr("panel.field_pole_angle_fine_tune", lang))
                    elif item.pole_angle_mode == "PRESET":
                        # Nome do preset dentro de rig_template["pole_angle_presets"]
                        # (ver active_rig_name na box de Character Templates
                        # abaixo -- é o template ATIVO que fornece os valores
                        # por side; troca de personagem, troca de preset
                        # disponível, sem mexer em código).
                        col.prop(item, "pole_angle_preset_name", text=tr("panel.field_pole_angle_preset_name", lang))

                    # v0.9 -- Collection Settings (Etapa 1/3). Arm/Leg
                    # ganham o mesmo dropdown que Tail (ver bloco "if
                    # item.chain_type == 'TAIL'" acima) -- "" (Auto) =
                    # comportamento antigo (Arm L/Arm R/Leg L/Leg R), sem
                    # mudança nenhuma pra quem nunca abrir essa opção.
                    col.separator()
                    col.prop(item, "collection_override", text=tr("panel.field_collection", lang))

        layout.separator()

        # ------------------------------------------------------------
        # Collection Settings (v0.9, Etapa 1) -- entre Bone Settings e
        # Character Templates, pedido explícito. Mesmo padrão de header
        # clicável + box collapsible que a box de Bone Settings acima já
        # usa (ver hytale_show_ik_chains) -- aqui com hytale_show_bone_collections,
        # também fechada por padrão.
        #
        # v0.9.1 -- NÃO chama ensure_default_bone_collections() aqui:
        # draw() não pode escrever em dados de ID (Blender levanta
        # "Writing to ID classes in this context is not allowed" --
        # aconteceu literalmente com essa linha, ver changelog). O seed
        # das 8 collections default agora só roda de dentro de um
        # execute() de operador: automaticamente no primeiro "Create
        # Rig" (ver RIG_OT_hytale_generate_rig), ou manualmente aqui via
        # o botão "Load Default Collections" (RIG_OT_hytale_bone_collection_
        # load_defaults), mostrado só enquanto a lista ainda não foi
        # inicializada nenhuma vez pra este armature.
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
            # v0.9.9 -- corrige entradas default (Head/Spine/Arm L/etc.)
            # criadas ANTES de Row/Column existir como campo -- ficam
            # travadas em row=0/column=0 pra sempre (ensure_default_bone_
            # collections só semeia UMA vez, guardado por hytale_bone_
            # collections_initialized) -- sintoma: ordenação da aba
            # Animation parece "sem efeito" (tudo empatado em 0/0, cai
            # pra ordem alfabética). Sempre visível (não só quando a
            # lista está vazia, diferente do botão acima) -- é pra
            # corrigir entradas que JÁ EXISTEM, não pra popular uma
            # lista vazia.
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

            # v0.9.6 -- opções da entrada SELECIONADA na lista acima
            # (mesmo padrão de "clica na lista, aparecem as opções dela
            # embaixo" que Bone Settings já usa pra cada IK chain):
            # Parent (aninhamento livre -- qualquer collection da lista
            # pode ser parent de qualquer outra, "Main (root)" = direto
            # embaixo de Main), "Show in Animation Tab" (pedido
            # explícito: some só o BOTÃO na aba Animation, a collection
            # continua existindo normalmente em todo o resto) e por
            # último Row/Column (grade -- ver _collection_sort_key em
            # rigger.py). ▲▼ acima continuam reordenando só a LISTA em
            # si (mais fácil de navegar) -- não afetam o layout final,
            # isso é 100% Parent + Row/Column.
            index = armature.hytale_bone_collections_index
            if 0 <= index < len(armature.hytale_bone_collections):
                selected = armature.hytale_bone_collections[index]
                detail_box = box.box()
                detail_box.label(
                    text=tr("panel.bone_collection_options_for", lang).format(name=selected.name),
                    icon="OPTIONS",
                )
                detail_box.prop(selected, "parent", text=tr("panel.field_parent", lang))
                detail_box.prop(selected, "show_in_animation_tab", text=tr("panel.field_show_in_animation", lang))
                grid_row = detail_box.row(align=True)
                grid_row.prop(selected, "row", text=tr("panel.field_grid_row", lang))
                grid_row.prop(selected, "column", text=tr("panel.field_grid_column", lang))

            box.label(text=tr("panel.hint_bone_collections", lang), icon="INFO")

        layout.separator()

        # ------------------------------------------------------------
        # Character Templates (rig + custom shapes) -- collapsible
        # (fechada por padrão, ver hytale_show_templates), abaixo de
        # tudo (inclusive dos botões e da box de IK Chains -- pedido
        # explícito: é configuração ocasional, não o fluxo do dia a dia).
        # Ver templates/__init__.py pro schema/racional completo dos
        # .json -- esta box é só desenho, toda a lógica de descoberta/
        # leitura/gravação mora em templates/__init__.py e rigger.py,
        # aqui só chama os operadores já registrados por eles.
        # ------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    # v0.9 (Etapa 3) -- ERA uma lista fixa de pares (nome, ícone) aqui,
    # hardcoded na mesma ordem/agrupamento que _build_main_collections
    # sempre usou (Head, Spine, Body, Arm R/Arm L lado a lado, Leg R/
    # Leg L lado a lado, Root, Tail, Face, Attachments) -- sem nenhuma
    # relação com a ordem real do personagem em "Collection Settings".
    # Removida: _draw_animation agora lê armature.hytale_bone_collections
    # (a MESMA lista editável/reordenável de "Collection Settings" --
    # ver rigger.py) direto, então mover algo lá também reordena esta
    # box, sem precisar duplicar/manter esta lista em sincronia na mão.
    # O `icon` de cada tupla nunca era usado de verdade no loop antigo
    # (o botão sempre mostrava HIDE_OFF/HIDE_ON, não esses ícones) --
    # não é perda nenhuma não recriar esse mapeamento aqui.

    def _draw_animation(self, layout, context, lang):
        obj = context.active_object
        is_armature = obj is not None and obj.type == "ARMATURE"

        if not is_armature:
            layout.box().label(text=tr("panel.hint_anim_none", lang), icon="ERROR")
            return

        armature = obj.data

        # --- Bone Collections --------------------------------------
        # v0.9.6 -- ERA "MAIN" e "FACE" como as duas únicas raízes
        # possíveis (Face era hardcoded/auto-criada) -- Face deixou de
        # existir como caso especial (pedido explícito: "remover a
        # collection Face... caso algum usuário queira, ele cria
        # separadamente"). Agora renderiza a ÁRVORE INTEIRA de
        # armature.hytale_bone_collections recursivamente, seguindo
        # `item.parent` (qualquer collection pode estar aninhada dentro
        # de qualquer outra -- ver HytaleBoneCollectionItem.parent) --
        # funciona pra qualquer profundidade, sem precisar saber de
        # antemão quantos níveis existem. Dentro de cada nível, agrupa
        # por `row` (via _collection_sort_key, que já ordena por (row,
        # column, name)) -- cada grupo de `row` igual vira UMA linha de
        # UI só, com um botão por coluna, lado a lado (ex. "Arm R" |
        # "Arm L"). `show_in_animation_tab` (pedido explícito) pula o
        # botão -- mas os FILHOS dele continuam sendo considerados
        # normalmente (esconder o pai não esconde os filhos na árvore).
        #
        # Só mostra/esconde -- não cria nada; um botão só nasce se a
        # collection já existir de verdade nesse Armature
        # (armature.collections_all, que enxerga aninhadas). Um item de
        # Collection Settings nunca materializado (ainda não rodou
        # "Create Rig") simplesmente não gera botão nenhum, sem erro.
        #
        # v0.9.7 -- "Attachments" também é uma entrada normal de
        # hytale_bone_collections agora (era uma raiz separada, fora do
        # Collection Settings por completo -- ver ensure_default_bone_collections
        # em rigger.py) -- já cai na árvore recursiva abaixo como
        # qualquer outra, sem tratamento especial.
        coll_box = layout.box()
        coll_box.label(text=tr("panel.anim_collections_box", lang), icon="OUTLINER_OB_ARMATURE")
        any_collection_found = False

        def toggle_button(target_row, name):
            nonlocal any_collection_found
            coll = armature.collections_all.get(name)
            if coll is None:
                return
            any_collection_found = True
            op = target_row.operator(
                ANIM_OT_hytale_toggle_collection_visibility.bl_idname,
                text=name,
                icon="HIDE_OFF" if coll.is_visible else "HIDE_ON",
                depress=coll.is_visible,
            )
            op.collection_name = name

        def item_parent_key(item):
            p = (item.parent or "").strip()
            return "Main" if (not p or p == PARENT_COLLECTION_ROOT) else p

        def render_children(parent_name, indent_level):
            children = sorted(
                (i for i in armature.hytale_bone_collections if i.name and item_parent_key(i) == parent_name),
                key=_collection_sort_key,
            )
            current_row_value = None
            ui_row = None
            for item in children:
                if not item.show_in_animation_tab:
                    continue
                if item.row != current_row_value or ui_row is None:
                    current_row_value = item.row
                    ui_row = coll_box.row(align=True)
                    ui_row.scale_y = 1.2
                    if indent_level:
                        ui_row.separator(factor=2.0 * indent_level)
                toggle_button(ui_row, item.name)
            # Desce um nível pros filhos de CADA item deste nível, na
            # ordem em que já foram processados (mesmo que um item tenha
            # sido pulado por show_in_animation_tab -- os filhos dele
            # ainda podem querer aparecer).
            for item in children:
                render_children(item.name, indent_level + 1)

        # v0.9.7 -- ERA um botão fixo extra aqui pra "Attachments" (bug:
        # aparecia DUAS VEZES na UI -- render_children já desenha ela
        # sozinha, já que Attachments virou uma collection normal dentro
        # de armature.hytale_bone_collections, filha de Main, igual
        # Head/Spine/etc.; antes disso, quando Attachments era uma raiz
        # separada FORA de hytale_bone_collections, esta linha extra era
        # necessária -- ficou pra trás depois da mudança e passou a
        # duplicar o mesmo botão. Removida.
        render_children("Main", 0)

        if not any_collection_found:
            coll_box.label(text=tr("panel.hint_anim_no_rig", lang), icon="INFO")

        layout.separator()

        # --- FK / IK --------------------------------------------------
        # Uma linha por cadeia Arm/Leg de armature.hytale_ik_chains que
        # já tem o switch de verdade gerado (ver get_fk_ik_state, em
        # anim_tools.py -- None pula a linha: cadeia Tail, rig nunca
        # gerado, ou entrada adicionada à lista depois do último
        # "Create Rig"). Os botões FK/IK da lista (por índice de cadeia)
        # fazem uma troca CRUA -- só a influência, sem mexer na pose
        # (ver ANIM_OT_hytale_set_fk_ik). O botão "Snap FK/IK" acima da
        # lista faz o trabalho dos dois juntos (igualar a pose E trocar)
        # pra UMA cadeia só -- a do bone ATIVO selecionado no momento.
        fkik_box = layout.box()
        fkik_box.label(text=tr("panel.anim_fkik_box", lang), icon="CON_KINEMATIC")

        # Snap FK/IK -- olha o bone ATIVO selecionado
        # (context.active_pose_bone), não passa por índice de cadeia (o
        # próprio operador resolve isso -- ver identify_chain_from_bone
        # em anim_tools.py). poll() do operador já cobre "sem bone
        # ativo"/"não é Armature" -- o botão fica cinza sozinho nesses
        # casos, sem precisar checar aqui.
        fkik_box.operator(
            ANIM_OT_hytale_snap_selected.bl_idname,
            text=tr("panel.btn_snap_selected", lang),
            icon="SNAP_ON",
        )

        # v0.9 (Etapa 3) -- reordena a lista pela collection REAL que
        # cada cadeia caiu (Auto -> Arm L/Arm R/Leg L/Leg R por lado, ou
        # a collection escolhida em "Collection", ver HytaleIKChainItem.
        # collection_override em rigger.py), na ordem de "Collection
        # Settings" -- em vez de recalcular a lógica de lado/prefixo de
        # bone que decide Arm L vs Arm R (ARM_COLLECTION_ROOTS, bem mais
        # complexa -- ver rigger/constants.py), lê direto a collection
        # de VERDADE que o bone raiz da cadeia já está, depois do
        # último "Create Rig" -- sempre bate com o resultado real,
        # nunca diverge (ground truth, não reimplementação em paralelo).
        #
        # v0.9.9 -- FIX: checava só root_bone + "_CTRL", e isso sempre
        # devolvia None (bug relatado: "não parece estar surgindo
        # efeito" -- a ordem ficava idêntica à de Bone Settings, porque
        # TODA cadeia caía no mesmo fallback). Causa: o "_CTRL" nem
        # sempre é o bone que carrega a membership de Main na prática --
        # ver _propagate_pole_and_tip_to_main_collections (rigger.py),
        # que usa o "_IK" da raiz (chain[0].name + SUFFIX_IK) como
        # referência, não o "_CTRL" -- em cadeias sem Shoulder (ver
        # ARM_COLLECTION_ROOTS_NO_SHOULDER/rigger/constants.py), é
        # justamente o "_IK" que é um dos ROOTS do walk que monta Arm L/
        # Arm R/Leg L/Leg R, enquanto o "_CTRL" pode não ser alcançado
        # da mesma forma. Em vez de tentar adivinhar qual dos dois é o
        # certo pra cada caso, testa os DOIS (root_bone e tip_bone, cada
        # um com "_CTRL" e "_IK") e usa o primeiro que encontrar
        # membership numa collection conhecida -- cobre qualquer uma das
        # combinações de parenting que o rig realmente usar.
        def resolve_chain_collection_name(item):
            known_names = {c.name for c in armature.hytale_bone_collections if c.name}
            candidate_names = []
            for base in (item.root_bone, item.tip_bone):
                if base:
                    candidate_names.append(base + SUFFIX_CTRL)
                    candidate_names.append(base + SUFFIX_IK)
            for name in candidate_names:
                bone = armature.bones.get(name)
                if bone is None:
                    continue
                for coll in bone.collections:
                    if coll.name in known_names:
                        return coll.name
            return None

        # v0.9.5 -- a "posição" de cada collection agora vem da grade
        # (row, column, name) de Collection Settings (ver
        # _collection_sort_key/HytaleBoneCollectionItem.row/column em
        # rigger.py), não mais da ordem crua da lista.
        sorted_collections = sorted(
            (c for c in armature.hytale_bone_collections if c.name), key=_collection_sort_key
        )
        collection_order = {c.name: i for i, c in enumerate(sorted_collections)}
        # v0.9.9 -- Row de cada collection (não só a posição linear) --
        # usado só pra decidir AGRUPAMENTO visual (duas cadeias cujas
        # collections compartilham o mesmo Row viram colunas lado a
        # lado, mesma UI row -- pedido explícito, mesmo espírito da
        # grade que a box "Bone Collections" já usa). A ORDENAÇÃO em si
        # continua sendo por collection_order (row, column, name juntos)
        # -- isso aqui só agrupa visualmente quem já ficou adjacente.
        collection_row = {c.name: c.row for c in armature.hytale_bone_collections if c.name}

        fkik_rows = []
        for index, item in enumerate(armature.hytale_ik_chains):
            state = get_fk_ik_state(obj, item)
            if state is None:
                continue
            coll_name = resolve_chain_collection_name(item)
            sort_key = collection_order.get(coll_name, len(collection_order))
            # Bucket de agrupamento -- cadeia SEM collection resolvida
            # (coll_name None/desconhecida) nunca agrupa com outra: usa
            # o próprio índice como bucket único, então sempre vira sua
            # própria linha (evita juntar duas cadeias "sem posição"
            # por coincidência).
            row_bucket = ("row", collection_row[coll_name]) if coll_name in collection_row else ("solo", index)
            fkik_rows.append((sort_key, index, item, state, row_bucket))
        # Ordena por (posição da collection em "Collection Settings", índice
        # original) -- o índice original como desempate mantém estável a
        # ordem entre cadeias que caíram na MESMA collection.
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
                # v0.9.9 -- respiro visual entre DUAS cadeias que caem na
                # MESMA UI row (compartilham Row) -- sem isso, o botão IK
                # da cadeia anterior ficava colado no label da próxima
                # (bug relatado: "Arm R  FK/IK Arm L  FK/IK", sem
                # separação nenhuma entre a IK de uma e o nome da outra).
                # v0.9.10: factor reduzido pra 0.8 quando o split interno
                # ficou mais justo -- v0.9.11: subiu de novo pra 3.0
                # (pedido explícito: o vão INTERNO -- label pros próprios
                # botões -- já ficou bom com split(factor=0.35); o que
                # precisava crescer era só o vão ENTRE cadeias -- botão
                # IK de uma pro texto da próxima).
                ui_row.separator(factor=3.0)
            # v0.9.9 -- ERA column(align=True) -- o label esticava pra
            # preencher o espaço todo antes dos botões (sem proporção
            # fixa), deixando o vão entre nome e FK/IK enorme e
            # inconsistente entre cadeias com nomes de tamanhos
            # diferentes. split(factor=...) fixa a proporção label/
            # botões -- consistente pra QUALQUER texto de label, curto
            # ou longo.
            #
            # v0.9.10 -- FIX: factor=0.55 reservava mais da metade de
            # CADA coluna só pro texto -- como "Arm R"/"Leg L" etc. são
            # curtos, sobrava um vão vazio grande antes dos botões (bug
            # relatado: aumentou o espaço nos dois lados, não só entre
            # cadeias). O Blender não mede a largura real do texto pra
            # decidir a proporção do split -- é sempre uma fração FIXA
            # da largura disponível, então baixar o factor pra algo mais
            # compatível com nomes curtos aperta o vão sem quebrar nomes
            # mais longos (que só ficam truncados/elípticos, não
            # sobrepostos).
            split = ui_row.split(factor=0.35, align=True)
            split.label(text=item.label or item.root_bone or "(?)")
            sub = split.row(align=True)
            op_fk = sub.operator(ANIM_OT_hytale_set_fk_ik.bl_idname, text="FK", depress=(state == 0))
            op_fk.chain_index = index
            op_fk.mode = "FK"
            op_ik = sub.operator(ANIM_OT_hytale_set_fk_ik.bl_idname, text="IK", depress=(state == 1))
            op_ik.chain_index = index
            op_ik.mode = "IK"
        if not any_chain_found:
            fkik_box.label(text=tr("panel.hint_anim_no_fkik", lang), icon="INFO")


def register():
    WindowManager.hytale_active_tab = EnumProperty(items=TAB_ITEMS, default="IMPORT")
    # Estado (aberta/fechada) das seções collapsible da aba Rig -- só UI,
    # não é dado do personagem/rig em si (por isso mora no WindowManager,
    # igual hytale_active_tab, não no Armature). Default False = fechada
    # (pedido explícito: as duas começam collapsed, o fluxo comum do dia
    # a dia é só "Create Rig", sem precisar abrir nenhuma delas).
    WindowManager.hytale_show_ik_chains = BoolProperty(default=False)
    WindowManager.hytale_show_bone_collections = BoolProperty(default=False)
    WindowManager.hytale_show_templates = BoolProperty(default=False)
    bpy.utils.register_class(HYTALE_PT_main)


def unregister():
    bpy.utils.unregister_class(HYTALE_PT_main)
    del WindowManager.hytale_show_templates
    del WindowManager.hytale_show_bone_collections
    del WindowManager.hytale_show_ik_chains
    del WindowManager.hytale_active_tab
