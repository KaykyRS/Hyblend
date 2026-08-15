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
from .common import HYTALE_OT_pick_bone_into_field
from .translations import get_language, tr
from .rigger import (
    RIG_MT_hytale_ik_chain_add_menu,
    RIG_OT_hytale_clear_generated,
    RIG_OT_hytale_collection_template_apply,
    RIG_OT_hytale_collection_template_delete,
    RIG_OT_hytale_collection_template_save,
    RIG_OT_hytale_generate_rig,
    RIG_OT_hytale_ik_chain_load_defaults,
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
)
from .templates import TEMPLATES_OT_open_user_folder, TEMPLATES_OT_reload

# RIG_UL_hytale_ik_chains não precisa de import -- template_list() abaixo
# referencia ela pelo nome da classe (string), igual o próprio rigger.py
# faz no RIG_PT_hytale_rigger.draw().

TAB_ITEMS = [
    ("IMPORT", "Import", "Import models and attachments", "IMPORT", 0),
    ("EXPORT", "Export", "Export animations", "EXPORT", 1),
    ("RIG", "Rig", "IK chains and rig generation", "CON_KINEMATIC", 2),
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
    'Hytale'). Só orquestra botões -- toda a lógica real mora nos
    operadores de importer.py / exporter.py."""

    bl_label = "Hytale Blocky Toolkit"
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
            has_limb_entry = any(c.chain_type != "TAIL" for c in armature.hytale_ik_chains)
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


def register():
    WindowManager.hytale_active_tab = EnumProperty(items=TAB_ITEMS, default="IMPORT")
    # Estado (aberta/fechada) das seções collapsible da aba Rig -- só UI,
    # não é dado do personagem/rig em si (por isso mora no WindowManager,
    # igual hytale_active_tab, não no Armature). Default False = fechada
    # (pedido explícito: as duas começam collapsed, o fluxo comum do dia
    # a dia é só "Create Rig", sem precisar abrir nenhuma delas).
    WindowManager.hytale_show_ik_chains = BoolProperty(default=False)
    WindowManager.hytale_show_templates = BoolProperty(default=False)
    bpy.utils.register_class(HYTALE_PT_main)


def unregister():
    bpy.utils.unregister_class(HYTALE_PT_main)
    del WindowManager.hytale_show_templates
    del WindowManager.hytale_show_ik_chains
    del WindowManager.hytale_active_tab
