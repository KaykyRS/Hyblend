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

import os

import blf
import bpy
import bpy.utils.previews
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Panel, WindowManager

from .exporter import (
    EXPORT_OT_hytale_blockyanim,
    EXPORT_OT_texture_picker_export_add,
    EXPORT_OT_texture_picker_export_remove,
)
from .importer import IMPORT_OT_hytale_blockymodel, IMPORT_OT_hytale_bbmodel
from .anim_importer import IMPORT_OT_hytale_blockyanim
from .anim_tools import (
    ANIM_OT_hytale_keyframe_switch,
    ANIM_OT_hytale_set_fk_ik,
    ANIM_OT_hytale_set_head_follow,
    ANIM_OT_hytale_snap_selected,
    get_fk_ik_state,
    get_head_follow_state,
)
from .common import HYTALE_OT_pick_bone_into_field
from .translations import get_language, tr
from .rigger import (
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
)
from .templates import TEMPLATES_OT_open_user_folder, TEMPLATES_OT_reload

# ---------------------------------------------------------------------
# Aba "Info" -- créditos/links (ver _draw_info). Constantes soltas aqui
# de propósito: só link, não é configuração de usuário nem contrato
# com outro arquivo, então não precisa virar property/common.py -- só
# editar a string aqui quando os links existirem. String vazia = botão
# correspondente fica desabilitado no painel (ver _draw_info).
# ---------------------------------------------------------------------
HYBLEND_PATREON_URL = "https://www.patreon.com/c/kaayky"
# v0.15.x -- Nexus Mods/GitHub (Links box) e Patreon (agora dentro de
# Credits, ver _draw_info) -- Discord SAIU (pedido explícito, "podemos
# remover"), a constante nem existe mais. String vazia = botão
# desabilitado, mesma regra de sempre.
HYBLEND_NEXUSMODS_URL = "https://www.nexusmods.com/hytale/mods/164"
HYBLEND_GITHUB_URL = "https://github.com/KaykyRS/Hyblend"
# v0.15.x -- era o @handle ("@kaayky_r.s") -- virou nome de exibição
# (pedido explícito, layout "Created by: / Kaayky (Ká)") -- o @handle
# ainda aparece, só que dentro do próprio Instagram quando o usuário
# clica no ícone, não precisa repetir aqui.
HYBLEND_AUTHOR_NAME = "Kaayky (Ká)"
# v0.15.x -- era 1 handle/1 URL só (rede genérica) -- virou 3 redes
# separadas (pedido explícito: Instagram/Twitter//YouTube, ícone
# diferente em cada uma). Mesma regra: string vazia = botão
# desabilitado, sem precisar mexer em mais nada quando a URL chegar.
HYBLEND_AUTHOR_INSTAGRAM_URL = "https://www.instagram.com/kaayky_r.s/"
HYBLEND_AUTHOR_TWITTER_URL = "https://x.com/kaayky_anim"
HYBLEND_AUTHOR_YOUTUBE_URL = "https://www.youtube.com/@KaaykyRS"

# Site oficial do Hytale (Hypixel Studios) -- crédito de "pra que jogo
# isso serve", não patrocínio/afiliação (ver disclaimer em
# panel.info_credits_hytale_disclaimer). URL fixa, não é link de
# terceiro que pode mudar de mão como as redes sociais acima.
HYBLEND_HYTALE_URL = "https://hytale.com"

# ---------------------------------------------------------------------
# Ícones customizados (logo de verdade) -- Blender não tem ícone de
# marca no set embutido (por isso o fallback usa ícone genérico
# "parecido"). Carregados via bpy.utils.previews (jeito padrão do
# Blender pra ícone customizado em botão -- vira icon_value= em vez de
# icon=). Arquivo esperado por entrada -- **coloque os PNGs dentro de
# HyblendToolkit/assets/icons/** com ESSES nomes exatos:
#   assets/icons/instagram.png
#   assets/icons/twitter_x.png
#   assets/icons/youtube.png
#   assets/icons/hytale.png      (opcional -- logo do Hytale no botão)
#   assets/icons/patreon.png
#   assets/icons/nexus_mods.png
#   assets/icons/github.png
# Se um arquivo não existir ainda, _draw_info cai pro ícone genérico
# antigo pra esse botão específico (nada quebra, não precisa de todos
# de uma vez) -- ver _panel_icon_value().
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
    """Carrega os PNGs de assets/icons/ num preview collection -- chamado
    em register(). Silencioso se a pasta/arquivo não existir (permite
    trabalhar sem os ícones ainda, ver comentário acima)."""
    global _panel_icons_pcoll
    pcoll = bpy.utils.previews.new()
    icons_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")
    for key, filename in _PANEL_ICON_FILES.items():
        path = os.path.join(icons_dir, filename)
        if os.path.isfile(path):
            try:
                pcoll.load(key, path, "IMAGE")
            except Exception:
                # Arquivo existe mas o Blender não conseguiu ler (formato
                # inválido, corrompido etc.) -- ignora e deixa cair pro
                # ícone genérico, não trava o addon inteiro por causa
                # de um PNG ruim.
                pass
    _panel_icons_pcoll = pcoll


def _unload_panel_icons():
    global _panel_icons_pcoll
    if _panel_icons_pcoll is not None:
        bpy.utils.previews.remove(_panel_icons_pcoll)
        _panel_icons_pcoll = None


def _panel_icon_value(key):
    """Devolve o icon_id carregado pra `key` (ver _PANEL_ICON_FILES),
    ou None se o PNG correspondente não foi carregado (ainda não existe
    ou falhou) -- _draw_info usa isso pra decidir entre icon_value=
    (logo customizado) e icon= (fallback genérico)."""
    if _panel_icons_pcoll is not None and key in _panel_icons_pcoll:
        return _panel_icons_pcoll[key].icon_id
    return None


def _draw_wrapped_label(layout, context, text):
    """Desenha `text` quebrado em várias `label()` pra caber na largura
    ATUAL da N-Panel -- mede a largura real (em pixels) de cada palavra
    com blf.dimensions() (fonte da UI) em vez de quebra manual fixa
    (`\\n` fixo na string de tradução), que sobrava espaço numa linha e
    estourava em outra dependendo de quanto o usuário alargou a aba
    lateral. Só serve pro texto puro do disclaimer (aba Info) hoje --
    layout.label() sozinho nunca quebra linha (trunca com "..."),
    diferente de HTML/outros toolkits.

    `context.region.width` é a largura da REGIÃO inteira (a N-Panel
    toda), não da coluna/box atual -- por isso o desconto fixo
    (_WRAPPED_LABEL_MARGIN_PX) aproxima a margem de box()+coluna+
    padding do Blender. A API pública não expõe a largura de layout em
    pixels de verdade, então isso é estimativa -- boa o bastante pro
    texto não estourar, mesmo que sobre uns pixels de vez em quando.
    """
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


# Margem estimada (px) entre context.region.width (largura da N-Panel
# inteira) e a largura de texto disponível DENTRO de credits_box (box()
# > column() padrão) -- ver _draw_wrapped_label acima. Ajustado meio no
# olho (Blender não expõe isso), com folga pra sobrar em vez de faltar.
_WRAPPED_LABEL_MARGIN_PX = 40

# RIG_UL_hytale_ik_chains não precisa de import -- template_list() abaixo
# referencia ela pelo nome da classe (string), igual o próprio rigger.py
# faz no RIG_PT_hytale_rigger.draw().

# v0.14 -- TAB_ITEMS/RIG_SUBTAB_ITEMS viraram funções (items= dinâmico)
# em vez de listas fixas -- os tooltips (3º elemento de cada tupla)
# eram texto em inglês hardcoded, nunca passavam por tr(). Como um
# EnumProperty com items= FUNÇÃO é reavaliado pelo Blender a cada
# redraw (não só uma vez no registro), isso já resolve sozinho sem
# precisar de @localized_props/refresh hook -- troca de idioma reflete
# na hora, igual o resto do painel.
#
# CUIDADO Blender (mesmo aviso de _bone_collection_enum_items em
# rigger/rig.py): a função NÃO pode devolver uma lista nova a cada
# chamada -- o Blender só garante que as strings dos items ficam vivas
# enquanto o MESMO objeto list que as contém também ficar vivo;
# devolver `return [...]` recém-criado toda vez é a causa mais comum de
# crash com EnumProperty dinâmico. Por isso as duas reaproveitam
# (limpam + repopulam) o próprio cache module-level, em vez de criar
# uma lista nova.
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


# v0.7.5 -- sub-abas DENTRO da aba Rig (ver _draw_rig) -- mesmo espírito
# de TAB_ITEMS acima. "Setup" é o fluxo do dia a dia; "Bone Settings" é
# só a lista de cadeias/formulário (a seção que mais recebia queixa de
# bagunça); "Advanced" é configuração ocasional (Collection Settings,
# Character Templates).
#
# v0.14.1 -- o RÓTULO (2º elemento da tupla) também passa por tr()
# agora, não só o tooltip -- pedido explícito do usuário: quer a
# OPÇÃO de traduzir os três, mas no pt_br.py só "Advanced" -> "Avançado"
# de fato ("Setup"/"Bone Settings" ficam com o mesmo texto em inglês
# nas duas chaves, de propósito -- termos curtos que o usuário prefere
# manter). Isso é uma decisão de CONTEÚDO (o que cada tradução diz),
# não de código -- outro idioma pode traduzir os três livremente.
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

        # v0.7.5 -- ERA layout.row(align=True).prop(..., expand=True), os
        # 4 botoes numa linha so -- ficavam espremidos demais pro nome de
        # cada aba caber (pedido explicito do usuario: quebrar em 2x2).
        # prop_enum() desenha UM botao por vez pra um valor especifico do
        # Enum (ao contrario de prop(expand=True), que desenha TODOS de
        # uma vez numa linha so) -- e o jeito padrao do Blender de montar
        # um grid customizado de botoes de Enum. Cada row(align=True)
        # ja divide o espaco igualmente entre os 2 botoes que contem,
        # entao o resultado ja sai "centralizado" (cada botao ocupa
        # metade da largura do painel) sem precisar de split extra.
        tabs_col = layout.column(align=True)
        tabs_row1 = tabs_col.row(align=True)
        tabs_row1.scale_y = 1.3
        tabs_row1.prop_enum(wm, "hytale_active_tab", "IMPORT")
        tabs_row1.prop_enum(wm, "hytale_active_tab", "EXPORT")
        tabs_row2 = tabs_col.row(align=True)
        tabs_row2.scale_y = 1.3
        tabs_row2.prop_enum(wm, "hytale_active_tab", "RIG")
        tabs_row2.prop_enum(wm, "hytale_active_tab", "ANIMATION")
        # v0.15.x -- 3ª linha, só a aba "Info" (créditos/links, ver
        # _draw_info) -- sozinha na própria row(align=True) dentro do
        # MESMO tabs_col ela já sai esticada pra largura toda (mesma
        # lógica que faz IMPORT/EXPORT ficarem "centralizados": um
        # único botão numa row ocupa 100% da row). scale_y menor que as
        # duas de cima (pedido explícito: mais fina que Import/Export/
        # Rig/Animation, mas alinhada em largura com elas -- align=True
        # no tabs_col cuida do alinhamento horizontal sozinho).
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
        # v0.7.5 -- travado (cinza) sem Armature ativa, pedido explicito
        # -- so feedback visual desta box, nao mexe no poll() do
        # operador (que continua podendo rodar em modo NEW_ARMATURE a
        # partir do outro botao).
        row.enabled = is_armature
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
            # HYTALE_export_settings, registrada por exporter.py (mesmo
            # padrão do hytale_ik_chains do rigger.py: quem é dono da
            # lógica registra o dado em Armature, aqui só desenha). Não
            # passa por get_export_settings() -- essa função é só um
            # atalho interno do exporter.py, o painel lê o caminho
            # direto (ver comentário dele em exporter.py).
            settings = active.data.hytale_export_settings
            armature_data = active.data

            settings_box = layout.box()
            settings_box.label(text=tr("panel.export_settings_box", lang), icon="TOOL_SETTINGS")
            # prop_search em vez de prop(): mostra um dropdown/autocomplete
            # com as Bone Collections que JÁ EXISTEM na Armature (mesmo
            # padrão já usado em importer.py pra target_armature_name),
            # em vez de exigir digitar o nome de cabeça. Continua sendo um
            # StringProperty por baixo (não vira PointerProperty) -- então
            # o valor default "Hytale Export" continua aparecendo mesmo
            # antes dessa collection existir de verdade (o usuário ainda
            # pode digitar/editar livremente, o dropdown é só um atalho).
            # armature_data.collections_all (não só .collections) pra
            # também listar Bone Collections aninhadas dentro de outra,
            # não só as de nível raiz -- ver rigger/rig.py sobre a
            # diferença entre os dois.
            settings_box.prop_search(
                settings, "export_collection_name", armature_data, "collections_all",
                text=tr("panel.export_collection", lang),
            )

            # v0.12 -- armature.hytale_export_settings.export_uv_offset
            # (toggle único) + os campos de UV Offset viraram armature.
            # hytale_texture_picker_exports (CollectionProperty, uma
            # entrada por instância -- ver exporter.py, HYTALE_texture_
            # picker_export_item) -- múltiplas instâncias independentes
            # agora exportam corretamente no mesmo arquivo, sem uma
            # sobrescrever a calibração da outra (bug real com o toggle
            # único antigo). Normalmente esta lista é preenchida sozinha
            # por "Create Texture Picker" (aba Rig, uma entrada TEXTURE_
            # PICKER por instância) -- Add/Remove aqui existem só pra
            # ajuste manual.
            #
            # v0.12.1 -- CORRIGIDO (feedback do usuário testando o painel
            # de verdade): esta caixa aparecia sempre, mesmo sem NENHUMA
            # instância configurada -- a maioria dos personagens nunca usa
            # Texture Picker, então virava poluição visual permanente na
            # aba Export. Agora é collapsible, mesmo padrão exato de
            # Reference Image/Companion Bones/Grid (aba Rig, dentro de uma
            # entrada TEXTURE_PICKER) -- toggle próprio no WindowManager
            # (hytale_show_export_texture_picker), fechado por padrão.
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
                        # v0.12 -- data_path indexado (funciona porque
                        # obj.path_resolve suporta sintaxe com colchetes em
                        # CollectionProperty) -- o índice é fixado NA HORA DE
                        # DESENHAR, então sempre aponta pro item certo mesmo
                        # que o usuário troque a seleção da lista depois de
                        # abrir o painel, sem precisar de um operador dedicado
                        # com IntProperty (diferente de RIG_OT_hytale_ik_
                        # chain_pick_bone, em rigger/rig.py, que precisa disso
                        # porque hytale_ik_chains é editado de vários lugares
                        # ao mesmo tempo -- aqui um data_path simples já basta).
                        op.data_path = f"data.hytale_texture_picker_exports[{index}]"
                        op.field = field_name

                    uv_picker_row("uv_offset_source_bone")
                    uv_picker_row("uv_offset_target_bone", text=tr("panel.texture_picker_target_bone", lang))
                    # v0.10.13 -- Companion Target Bones: lista (não um bone
                    # só), então sem o picker de eyedropper de uv_picker_row
                    # acima -- normalmente preenchido sozinho por "Create
                    # Texture Picker" a partir dos Companion Bones da entrada
                    # TEXTURE_PICKER (aba Rig), editável aqui só pra ajuste manual.
                    sub.prop(
                        active_export, "uv_offset_target_bones_extra",
                        text=tr("panel.texture_picker_extra_target_bones", lang),
                    )
                    # v0.12.1 -- os 4 campos de calibração (Grid Step/
                    # Pixels per Step) MUDARAM de lugar de novo (ver
                    # histórico em exporter.py, EXPORT_OT_hytale_
                    # blockyanim.draw()) -- moram aqui agora, junto do
                    # resto dos campos DESTA instância, em vez de ficarem
                    # escondidos atrás de um índice separado no diálogo
                    # de Export Animations. Normalmente preenchidos
                    # sozinhos por "Create Texture Picker" -- editar aqui
                    # é só pra ajuste fino manual.
                    calib_row1 = sub.row(align=True)
                    calib_row1.prop(active_export, "uv_offset_step_x")
                    calib_row1.prop(active_export, "uv_offset_px_x")
                    calib_row2 = sub.row(align=True)
                    calib_row2.prop(active_export, "uv_offset_step_y")
                    calib_row2.prop(active_export, "uv_offset_px_y")

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

    def _draw_shape_vertex_edit_active(self, layout, context, lang, obj):
        """Desenhado no lugar do resto de _draw_rig enquanto o objeto
        ATIVO é a malha de um widget em Vertex Edit Mode (ver
        RIG_OT_hytale_shape_vertex_edit_mode_enter/finish em rigger/
        rig.py) -- nesse estado obj.type é 'MESH', não 'ARMATURE', então
        o resto de _draw_rig (que sempre espera um Armature ativo) não
        desenharia nada útil aqui, só o hint de "nenhum Armature
        selecionado". `obj` já é a malha (chamador confirma obj.type ==
        'MESH' e a custom property antes de chamar isto)."""
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

        # v0.16 -- Vertex Edit Mode (ver RIG_OT_hytale_shape_vertex_edit_mode_enter
        # em rigger/rig.py) troca o objeto ATIVO pra malha do widget
        # (obj.type == 'MESH'), não o Armature -- o resto desta função
        # sempre espera um Armature ativo, então checamos esse estado
        # ANTES de tudo, senão o botão de "Finish Vertex Edit" ficaria
        # inalcançável enquanto a malha está em Edit Mode (obj.type !=
        # 'ARMATURE' cairia direto no hint "nenhum Armature selecionado"
        # logo abaixo).
        if obj is not None and obj.type == "MESH" and obj.get("hytale_vertex_edit_armature"):
            self._draw_shape_vertex_edit_active(layout, context, lang, obj)
            return

        layout.label(text=tr("panel.warn_rig_experimental", lang), icon="ERROR")

        is_armature = obj is not None and obj.type == "ARMATURE"

        if not is_armature:
            layout.box().label(text=tr("panel.hint_rig_none", lang), icon="ERROR")
            return

        armature = obj.data
        wm = context.window_manager

        # v0.7.5 -- sub-abas dentro da aba Rig (pedido explicito do
        # usuario: a aba tinha varias secoes empilhadas na mesma coluna,
        # dificil de escanear). EnumProperty igual TAB_ITEMS (nomes so
        # em ingles de proposito, mesmo raciocinio do topo do arquivo)
        # -- "Setup" e o fluxo do dia a dia (Create Rig e as acoes que
        # giram em torno dele), "Bone Settings" e so a lista de cadeias
        # + formulario do item selecionado (a maior fonte de bagunca
        # relatada), "Advanced" e configuracao ocasional (Collection
        # Settings, Character Templates) -- ver register() no fim deste
        # arquivo pra hytale_rig_subtab.
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
        # v0.7.5 -- reorganizado (pedido explícito do usuário: os botões
        # ficavam todos empilhados, um embaixo do outro, sem hierarquia
        # visual nenhuma). "Create Rig" e "Check Rig" agora formam um
        # bloco só (column(align=True) gruda as duas rows sem gap entre
        # elas) -- Create Rig mais alto/largo (é a ação principal, roda
        # de novo toda vez que o usuário anexa um attachment), Check Rig
        # colado logo abaixo, um pouco menor. "Remove Generated Bones"
        # saiu de botão próprio e virou o ícone de lixeira ao lado de
        # Create Rig -- mesma linha, mesma altura, ação secundária
        # (destrutiva) que não precisa do mesmo destaque.
        col = layout.column(align=True)
        top_row = col.row(align=True)
        top_row.scale_y = 1.7
        top_row.operator(
            RIG_OT_hytale_generate_rig.bl_idname,
            text=tr("panel.btn_create_rig", lang),
            icon="ARMATURE_DATA",
        )
        # v0.7.10 -- ERA um operator() direto (sempre "Delete All" no
        # comportamento antigo) -- virou um menu() popup (Only Rig /
        # Delete All, ver RIG_MT_hytale_clear_generated_menu em
        # rigger/rig.py) -- pedido explícito: "Only Rig" preserva
        # widgets editados à mão (Shape Edit Mode/Vertex Edit), "Delete
        # All" é o comportamento antigo (também limpa Collection/Bone
        # Settings, mais agressivo que antes).
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
            # essa checagem aqui. Edit Shape Vertices (v0.16) segue o
            # mesmo espírito: fica cinza sozinho quando o bone ativo não
            # tem custom shape nenhum (poll() de RIG_OT_hytale_shape_
            # vertex_edit_mode_enter) -- pedido explícito do usuário pra
            # ficar ACIMA de Mirror Shape.
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
                # Embutir malha nos Shape Templates -- caso 2 ("widget
                # totalmente próprio", ver RIG_OT_hytale_use_selected_as_
                # widget em rigger/rig.py). Fica cinza sozinho (poll())
                # quando não há exatamente 1 outro objeto de malha
                # selecionado além do Armature -- mesmo espírito de Mirror
                # Shape/Edit Shape Vertices acima, sempre desenhado, nunca
                # escondido condicionalmente daqui.
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
        # v0.7.5 -- ERA uma box collapsible (hytale_show_ik_chains,
        # fechada por padrao) dentro da coluna unica da aba Rig -- virou
        # sua PROPRIA sub-aba (ver _draw_rig acima), entao nao faz mais
        # sentido collapsible: a sub-aba inteira JA E "Bone Settings",
        # nao tem nada mais pra esconder embaixo. hytale_show_ik_chains
        # saiu do register()/unregister() (nao e mais lida em lugar
        # nenhum).
        #
        # v0.7: a box deixou de ser so sobre IK (agora cobre Arm/Leg/
        # Tail/Head/Spine/Attachments/Texture Picker -- ver
        # _LIMB_FIELD_LABELS acima) -- a KEY continua "panel.
        # ik_chains_box" (nao renomeei pra nao duplicar texto em
        # translations/), so o TEXTO que ela resolve mudou pra algo mais
        # generico ("Bone Settings").
        box = layout.box()
        box.label(text=tr("panel.ik_chains_box", lang), icon="CON_KINEMATIC")

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
        # v0.14 -- col.menu() no lugar de col.operator("wm.call_menu",
        # ...).name = ... -- o operador nativo wm.call_menu tinha
        # tooltip genérico do próprio Blender, não controlável por
        # este addon; col.menu() desenha o mesmo botão de abrir o menu,
        # mas usa o bl_description/description() da PRÓPRIA classe
        # Menu (ver RIG_MT_hytale_ik_chain_add_menu em rigger/rig.py,
        # tooltip() -- v0.14) como tooltip do botão.
        col.menu(RIG_MT_hytale_ik_chain_add_menu.bl_idname, text="", icon="ADD")
        col.operator(RIG_OT_hytale_ik_chain_remove.bl_idname, text="", icon="REMOVE")
        # Setinhas de reordenar -- mesma coluna alinhada do +/-, com
        # um separator() pra dar uma respiradinha visual entre os
        # dois grupos (add/remove vs mover), convenção comum em
        # UILists do próprio Blender (ex. Modifiers, Vertex Groups).
        col.separator()
        col.operator(RIG_OT_hytale_ik_chain_move.bl_idname, text="", icon="TRIA_UP").direction = "UP"
        col.operator(RIG_OT_hytale_ik_chain_move.bl_idname, text="", icon="TRIA_DOWN").direction = "DOWN"

        # Auto-Detect Bones (novo) -- botão de largura cheia, não fica na
        # coluna estreita do +/-/mover (é uma ação "de uma vez só", não um
        # controle da lista em si) -- mesmo padrão visual do botão "Check
        # Rig" (RIG_OT_hytale_validate_rig, ver _draw_rig acima).
        detect_row = box.row()
        detect_row.scale_y = 1.1
        detect_row.operator(
            RIG_OT_hytale_ik_chain_auto_detect.bl_idname,
            text=tr("panel.btn_auto_detect_bones", lang),
            icon="VIEWZOOM",
        )

        # armature.hytale_apply_ik_joint_fix é BoolProperty
        # (Armature.hytale_apply_ik_joint_fix, registrada em
        # rigger/__init__.py -- renomeada de hytale_apply_player_arm_ik_fix
        # na v0.6, quando os valores de correção de junta deixaram de
        # ser exclusivos do Player e passaram a vir de
        # rig_template["ik_joint_x_overrides"] -- ver
        # templates/__init__.py). O rótulo aqui usa text=tr(...) pra
        # ficar traduzido -- o TOOLTIP também (v0.14): a description=
        # dessa property é reatribuída via tr() em
        # rigger/__init__.py._assign_dynamic_properties(), chamada de
        # novo toda vez que o idioma do addon muda (ver
        # translations/__init__.py, "Tooltip de campo"). O "Load
        # Preset" (dentro da box de Character
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

            # v0.7.5 -- ERA duas funções aqui (picker_row, que só
            # desenhava direto em `col`, e _picker_row_into, que aceita
            # qualquer layout) -- picker_row foi removida: TODO tipo de
            # cadeia passou a agrupar seus pickers numa box "Bones"
            # (ver blocos TAIL/HEAD/SPINE/ATTACHMENTS/TEXTURE_PICKER/
            # Arm-Leg abaixo), então só _picker_row_into (que desenha
            # num layout específico, não sempre em `col`) continua
            # sendo necessária.
            def _picker_row_into(layout, field_name, text):
                r = layout.row(align=True)
                r.prop(item, field_name, text=text)
                op = r.operator(RIG_OT_hytale_ik_chain_pick_bone.bl_idname, text="", icon="EYEDROPPER")
                op.chain_index = index
                op.field = field_name


            col.prop(item, "chain_type", text=tr("panel.field_chain_type", lang))

            if item.chain_type == "CHAIN":
                # v0.7: Tail não usa IK -- só o caminho root->tip (ver
                # _build_tail_layer em rigger.py) e um parent opcional
                # pra anexar a cauda no corpo. Sem pole/side/
                # pole_angle/extra_ik_location, que só fazem sentido
                # pra uma cadeia com solver de IK.
                #
                # v0.7.5 -- pickers agrupados numa box "Bones", mesmo
                # padrão visual que o Arm/Leg passou a usar (ver
                # _LIMB_FIELD_LABELS acima) -- consistência entre os
                # tipos de cadeia, mesma key de tradução ("Bones" já
                # serve pra qualquer grupo de bone pickers).
                tail_bones_box = col.box()
                tail_bones_box.label(text=tr("panel.bone_settings_group_bones", lang), icon="BONE_DATA")
                tail_bones_col = tail_bones_box.column(align=True)
                _picker_row_into(tail_bones_col, "parent_override", tr("panel.field_tail_parent", lang))
                _picker_row_into(tail_bones_col, "root_bone", tr("panel.field_tail_start", lang))
                _picker_row_into(tail_bones_col, "tip_bone", tr("panel.field_tail_end", lang))

                row = col.row(align=True)
                row.prop(item, "tail_tip_rotation_axis", text=tr("panel.field_tail_tip_rotation_axis", lang))
                row.prop(item, "tail_tip_rotation_deg", text=tr("panel.field_tail_tip_rotation_deg", lang))
                # v0.7.13 -- "Connected" (pedido explícito do usuário) --
                # liga/desliga bone.use_connect nos segmentos internos
                # da cadeia (ver HytaleIKChainItem.tail_use_connect/
                # _build_tail_layer em rigger.py). Desligado por padrão.
                col.prop(item, "tail_use_connect", text=tr("panel.field_tail_use_connect", lang))
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
                #
                # v0.7.5 -- agrupado numa box "Bones" (mesmo padrão do
                # Arm/Leg/Tail acima).
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

                # v0.7.5 -- ERA um hint "Organizational only" aqui --
                # removido, pedido explícito do usuário: diferente de
                # Spine/Attachments (que são SÓ organizacionais), Head
                # também tem Head Free/Lock e First Person Camera logo
                # abaixo, que não são organizacionais.
                # v0.13.4 -- "Head Free/Lock" (era "Continuous Chain"
                # até v0.13.3, removido daqui -- ver comentário em
                # HytaleIKChainItem.continuous_chain, rigger/rig.py).
                # Um toggle só: redireciona sozinho o Tail do
                # predecessor imediato de "Head" (Neck ou Chest, o
                # que existir) pro Head do Head_CTRL, reparenta pro
                # Origin_CTRL, e monta os constraints de Child
                # Of/Copy Location -- sem precisar configurar nada
                # em outra entrada.
                col.separator()
                col.prop(item, "head_follow_enabled", text=tr("panel.field_head_follow_enabled", lang))
                col.separator()

                # v0.15 -- "Create First Person Camera" (pedido
                # explícito do usuário). Mesmo padrão collapsible
                # das seções do Texture Picker (Reference Image/
                # Companion Bones/Grid) -- caixa própria só pra não
                # poluir a entrada HEAD sempre que a opção estiver
                # desligada (comportamento padrão).
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
                        # v0.15.1 -- FOV agora é campo de verdade
                        # (pedido explícito do usuário), pra dar pra
                        # ajustar ANTES de clicar "Create Camera"
                        # (idempotente -- rodar de novo também
                        # atualiza o FOV de uma câmera já criada).
                        camera_col.prop(item, "head_camera_fov", text=tr("panel.field_head_camera_fov", lang))
                        camera_col.label(text=tr("panel.hint_head_camera", lang), icon="INFO")
                    # v0.15.1 -- CORRIGIDO: os botões Create/Remove
                    # ficavam DENTRO do "if item.head_camera_enabled"
                    # acima -- desmarcar a checkbox depois de já ter
                    # criado a câmera escondia o botão "Remove
                    # Camera" junto, sem jeito fácil de limpar uma
                    # câmera órfã sem reativar a opção ou rodar
                    # "Remove Generated Bones" (que apaga o rig
                    # inteiro). Botões agora ficam SEMPRE visíveis
                    # nesta caixa (Remove funciona independente do
                    # toggle -- ver RIG_OT_hytale_camera_remove.poll);
                    # "Create" continua desabilitado sozinho (poll)
                    # se a opção estiver desligada ou faltar bone.
                    camera_col.separator()
                    camera_action_row = camera_col.row(align=True)
                    camera_action_row.operator(RIG_OT_hytale_camera_create.bl_idname, icon="CAMERA_DATA")
                    camera_action_row.operator(RIG_OT_hytale_camera_remove.bl_idname, icon="X", text="")

                col.separator()
                col.prop(item, "collection_override", text=tr("panel.field_collection", lang))
            elif item.chain_type == "SPINE":
                # v0.9 (Etapa 2) -- mesmo espírito de Head: nenhum bone
                # é criado, só identificado. spine_count é o TOTAL de
                # bones incluindo o Pelvis (1 = só Pelvis) -- Pelvis
                # sempre visível, Spine1..4 conforme spine_count - 1.
                #
                # v0.7.5 -- agrupado numa box "Bones" (mesmo padrão do
                # Arm/Leg/Tail/Head acima).
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

                # v0.13.12 -- pedido do usuário: liga/desliga a criação
                # de root.spine_CTRL (e os constraints de Spine Follow em
                # Belly_CTRL/Chest_CTRL que dependem dele -- ver
                # _build_root_controls/_build_spine_follow em rig.py)
                # inteira. Fora da box "Bones" de propósito -- não é um
                # nome de bone, é um toggle de comportamento do rig.
                col.prop(item, "spine_ctrl_enabled", text=tr("panel.field_spine_ctrl_enabled", lang))

                col.label(text=tr("panel.hint_spine_no_ik", lang), icon="INFO")
                # v0.13.4 -- "Continuous Chain" removido daqui (era
                # exibido aqui até v0.13.3) -- ver comentário em
                # HytaleIKChainItem.continuous_chain, rigger/rig.py.
                # A Spine não tem mais nenhuma opção equivalente a
                # "Head Free/Lock" (só faz sentido pra Head hoje).
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
                #
                # v0.7.5 -- agrupado numa box "Bones" (mesmo padrão do
                # Arm/Leg/Tail/Head/Spine acima).
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
                # v0.10 -- Texture Picker não cria bone de IK nenhum -- só
                # identifica QUAL bone original é o alvo, e dispara
                # a criação do atlas picker (par root.ui/cursor derivado +
                # plane de referência + driver no material -- ver
                # rigger/rig.py, _build_texture_picker).
                #
                # v0.10.14 -- reorganizado em seções (pedido
                # explícito do usuário: layout anterior ficava tudo
                # "achatado" numa coluna só) -- só as seções realmente
                # OPCIONAIS (Reference Image, Companion Bones, Grid)
                # ganham box + collapsible. Rótulos/hints encurtados --
                # explicação técnica completa continua nos comentários
                # de código e nas tooltips (hover).
                #
                # v0.7.5 -- Target Bone/Picker Parent agrupados numa box
                # "Bones", mesmo padrão que Arm/Leg/Tail/Head/Spine/
                # Attachments passaram a usar (ERA "soltos, sem box" --
                # comentário antigo dizia isso de propósito na época,
                # mas o padrão mudou pra consistência visual entre TODOS
                # os tipos de cadeia).
                tp_bones_box = col.box()
                tp_bones_box.label(text=tr("panel.bone_settings_group_bones", lang), icon="BONE_DATA")
                tp_bones_col = tp_bones_box.column(align=True)
                _picker_row_into(tp_bones_col, "texture_picker_bone", tr("panel.field_texture_picker_bone", lang))
                _picker_row_into(
                    tp_bones_col, "texture_picker_ui_parent_bone", tr("panel.field_texture_picker_ui_parent_bone", lang)
                )
                col.separator()

                # v0.10.15 -- collapsible SEM trava: rodada anterior
                # forçava aberto se já tinha companion configurado
                # (pra não "esconder" dado em uso) -- pedido explícito
                # do usuário pra tirar isso, deixar o toggle igual
                # aos outros (usuário decide, sem comportamento
                # especial por trás).
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

                # v0.10.13 -- Companion Bones: outras malhas/bones
                # que compartilham o atlas do target e devem trocar
                # de expressão JUNTO com Target Bone (ex.: metades
                # L/R espelhadas) -- mesmo padrão de lista em loop
                # que Attachments (attachments_count acima), teto
                # bem menor (ver TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT em
                # rigger/constants.py). Não criam bone nenhum --
                # só recebem material+driver de UV, ver
                # _apply_texture_picker_to_companion em rigger/rig.py.
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

                # v0.11 -- auto-detecção por alpha removida por
                # completo (se provou frágil -- atlas embutido numa
                # textura maior sempre dava 1x1, ícones com largura
                # visual desigual dentro de células uniformes davam
                # medição errada -- ver DEVELOPER_NOTES.md). Grid
                # agora é sempre digitado manualmente (números que o
                # usuário já vê no Blockbench) -- collapsible mantido,
                # mesmo padrão das duas seções acima, mas sem toggle
                # nem branch: os 4 campos ficam sempre visíveis aqui
                # dentro.
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
                #
                # v0.7.5 -- REORGANIZADO em grupos visuais (Bones/Pole),
                # pedido explícito do usuário (era o formulário mais
                # confuso do addon: 4 pickers de bone + Side + 2
                # checkboxes soltos + 3 campos de pole + o dropdown de
                # collection, tudo numa coluna só sem separação
                # nenhuma). Nenhum nome de property mudou -- só o
                # AGRUPAMENTO visual e os RÓTULOS de pole_invert/
                # extra_ik_location (ver translations/en.py -- mesma
                # key, texto mais direto).
                #
                # v0.7.5.1 -- "Pole" virou collapsible (hytale_show_
                # pole_settings, fechada por padrão -- mesmo padrão das
                # seções do Texture Picker abaixo). Pedido explícito:
                # "Bones" (que bone é qual) é a única coisa realmente
                # essencial pra montar a cadeia -- fica sempre visível.
                # Ajuste fino de pole (distância/ângulo/inversão) é
                # secundário, só mexido quando o cotovelo/joelho sai
                # torto -- não precisa competir por espaço o tempo
                # todo. "Organization" NÃO virou box/collapsible --
                # voltou a ser um campo solto (mesmo padrão que Tail/
                # Head/Spine/Attachments/Texture Picker já usam pro
                # dropdown de Collection): um campo só não justifica uma
                # caixa própria.
                labels = _LIMB_FIELD_LABELS.get(item.chain_type, _LIMB_FIELD_LABELS["ARM"])

                bones_box = col.box()
                bones_box.label(text=tr("panel.bone_settings_group_bones", lang), icon="BONE_DATA")
                bones_col = bones_box.column(align=True)
                _picker_row_into(bones_col, "parent_override", tr(labels["parent_override"], lang))
                _picker_row_into(bones_col, "root_bone", tr(labels["root_bone"], lang))
                _picker_row_into(bones_col, "pole_bone", tr(labels["pole_bone"], lang))
                _picker_row_into(bones_col, "tip_bone", tr(labels["tip_bone"], lang))
                bones_col.prop(item, "side", text=tr("panel.field_side", lang))

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
                        # Nome do preset dentro de rig_template["pole_angle_presets"]
                        # (ver active_rig_name na box de Character Templates
                        # -- é o template ATIVO que fornece os valores por
                        # side; troca de personagem, troca de preset
                        # disponível, sem mexer em código).
                        pole_col.prop(item, "pole_angle_preset_name", text=tr("panel.field_pole_angle_preset_name", lang))
                    pole_row = pole_col.row(align=True)
                    pole_row.prop(item, "pole_invert", text=tr("panel.field_pole_in_front", lang))
                    pole_row.prop(item, "extra_ik_location", text=tr("panel.field_copy_location_ik", lang))

                # v0.9 -- Collection Settings (Etapa 1/3). Arm/Leg
                # ganham o mesmo dropdown que Tail (ver bloco "if
                # item.chain_type == 'TAIL'" acima) -- "" (Auto) =
                # comportamento antigo (Arm L/Arm R/Leg L/Leg R), sem
                # mudança nenhuma pra quem nunca abrir essa opção.
                col.separator()
                col.prop(item, "collection_override", text=tr("panel.field_collection", lang))

    def _draw_rig_advanced(self, layout, context, lang, armature, wm):
        layout.separator()

        # ------------------------------------------------------------
        # Collection Settings (v0.9, Etapa 1) -- entre Bone Settings e
        # Character Templates, pedido explícito. Mesmo padrão de header
        # clicável + box collapsible (hytale_show_bone_collections)
        # também fechada por padrão.
        #
        # v0.7.7 -- LISTA UNIFICADA: cada entrada é uma Collection (bone
        # collection real) OU uma Section (separador puramente visual da
        # aba Animation, ver rigger/rig.py) -- ERA duas listas/boxes
        # separadas (v0.7.6) -- pedido explícito do usuário: "o Section
        # ainda é relacionado as collections", uma lista só. O seletor
        # "Type" na entrada selecionada (abaixo) decide qual é qual; os
        # campos do painel de detalhe mudam conforme o tipo.
        #
        # v0.9.1 -- NÃO chama ensure_default_bone_collections() aqui:
        # draw() não pode escrever em dados de ID (Blender levanta
        # "Writing to ID classes in this context is not allowed" --
        # aconteceu literalmente com essa linha, ver changelog). O seed
        # default (Section "Main" + as 10 collections) agora só roda de
        # dentro de um execute() de operador: automaticamente no
        # primeiro "Create Rig" (ver RIG_OT_hytale_generate_rig), ou
        # manualmente aqui via o botão "Load Default Collections"
        # (RIG_OT_hytale_bone_collection_load_defaults), mostrado só
        # enquanto a lista ainda não foi inicializada nenhuma vez pra
        # este armature.
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

            # v0.7.7 -- opções da entrada SELECIONADA na lista acima
            # (mesmo padrão de "clica na lista, aparecem as opções dela
            # embaixo" que Bone Settings já usa pra cada IK chain) --
            # "Type" sempre visível (Collection/Section); o resto muda
            # conforme o tipo. "Parent" é o MESMO campo pros dois (ver
            # HytaleBoneCollectionItem.parent em rigger/rig.py), só o
            # RÓTULO muda ("Section" pra uma Collection -- onde o botão
            # dela aparece na aba Animation; "Parent" pra uma Section --
            # dentro de qual outra ela está aninhada). "Show in
            # Animation Tab" e "Column" só fazem sentido pra Collection
            # (uma Section não tem botão de visibilidade próprio, e só
            # empilha verticalmente, nunca lado a lado). ▲▼ acima
            # continuam reordenando só a LISTA em si (mais fácil de
            # navegar) -- não afetam o layout final, isso é 100% Parent/
            # Section + Row/Column.
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
        # v0.7.6 -- REESCRITO: ERA uma árvore recursiva de collection-
        # dentro-de-collection (item.parent apontando pra OUTRA
        # collection -- ver changelog). Collections não aninham mais
        # entre si -- cada uma pertence a uma SECTION (puramente
        # visual, ver HytaleBoneSectionItem/_resolve_collection_section_
        # name em rigger/rig.py), e são as SECTIONS que aninham (Sections
        # dentro de Sections, ver resposta do usuário). Cada Section vira
        # um cabeçalho (label com o nome) seguido do grid de botões das
        # collections que apontam pra ela -- mesmo agrupamento por `row`/
        # `column` de sempre (via _collection_sort_key), só que agora
        # relativo aos irmãos da MESMA Section, não de um parent de
        # collection. `show_in_animation_tab` (pedido explícito) pula só
        # o BOTÃO -- a collection continua existindo em todo o resto.
        #
        # Só mostra/esconde -- não cria nada; um botão só nasce se a
        # collection já existir de verdade nesse Armature
        # (armature.collections_all). Um item de Collection Settings
        # nunca materializado (ainda não rodou "Create Rig") simplesmente
        # não gera botão nenhum, sem erro. Mesma regra pra uma Section
        # sem NENHUMA collection materializada dentro -- o header dela
        # nem chega a ser desenhado (ver any_in_section abaixo).
        coll_box = layout.box()
        coll_box.label(text=tr("panel.anim_collections_box", lang), icon="OUTLINER_OB_ARMATURE")
        any_collection_found = False

        def toggle_button(target_row, name):
            # v0.7.5 -- ERA target_row.operator(ANIM_OT_hytale_toggle_
            # collection_visibility, ...) -- virou um prop() direto na
            # property nativa is_visible (bpy.types.BoneCollection).
            # Dois ganhos pedidos pelo usuario: (1) arrastar o mouse
            # sobre varios botoes desta ROW liga/desliga todos de uma
            # vez -- comportamento nativo do Blender pra prop(toggle=
            # True) em row(align=True), que um operator() nunca tem;
            # (2) por ser uma property de verdade, passa a aceitar
            # botao direito -> "Insert Keyframe" como qualquer outro
            # campo do painel.
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

        # Agrupa as collections (entry_type == "COLLECTION" -- lista
        # unificada agora, ver rigger/rig.py) por Section resolvida --
        # uma passada só, reaproveitada tanto aqui (aba Animation)
        # quanto em sync_bone_collection_order (rigger/rig.py), mesma
        # lógica.
        by_section = {}
        for item in armature.hytale_bone_collections:
            if not item.name or item.entry_type != "COLLECTION":
                continue
            by_section.setdefault(_resolve_collection_section_name(armature, item), []).append(item)

        def render_section_collections(section_box, items, depth):
            """Desenha o grid de botões (agrupado por `row`, colunas
            lado a lado) das collections de UMA Section -- mesma lógica
            de sempre, só que sem recursão (collection não aninha mais
            em collection nenhuma). `depth` só indenta visualmente (mesmo
            recuo do cabeçalho da Section, ver loop abaixo) -- puramente
            cosmético, não afeta agrupamento/ordem."""
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

        # v0.7.9 -- coleta os nomes de Section REALMENTE visitados acima
        # -- qualquer chave de by_section que sobrar (nenhuma Section com
        # esse nome existe -- normal se o usuário apagou TODAS as
        # Sections, agora permitido, ver RIG_OT_hytale_bone_collection_remove)
        # é desenhada por último, sem cabeçalho nenhum -- um grupo
        # implícito "Root", em vez de essas collections simplesmente
        # sumirem da aba Animation.
        visited_section_names = set()
        for sec, depth in _iter_sections_in_order(armature):
            items = by_section.get(sec.name, [])
            visited_section_names.add(sec.name)
            if not items:
                continue
            # "Preview" barato antes de desenhar nada: só materializa o
            # cabeçalho da Section se pelo menos UMA das suas collections
            # já existir de verdade no Armature -- senão sobraria um
            # título "Face" sem nenhum botão embaixo (rig ainda não
            # gerado, ou nenhuma delas com show_in_animation_tab).
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
            # v0.7.5 -- botao de keyframe explicito (pedido explicito:
            # nao dava pra animar FK/IK antes -- ver ANIM_OT_hytale_
            # keyframe_switch em anim_tools.py pro motivo tecnico).
            key_op = sub.operator(ANIM_OT_hytale_keyframe_switch.bl_idname, text="", icon="KEY_HLT")
            key_op.switch = "FK_IK"
            key_op.chain_index = index
        if not any_chain_found:
            fkik_box.label(text=tr("panel.hint_anim_no_fkik", lang), icon="INFO")

        # --- Head Free/Lock -------------------------------------------
        # v0.13.5 -- mesmo espírito da box FK/IK acima, só que UM switch
        # SÓ (não por índice de cadeia -- só existe UM Head_CTRL no rig
        # inteiro). get_head_follow_state (anim_tools.py) devolve None
        # quando "Head Free/Lock" (HytaleIKChainItem.head_follow_enabled,
        # painel Bone Settings) nunca foi ligado em nenhuma entrada HEAD,
        # ou o rig nunca foi gerado -- a box inteira nem aparece nesse
        # caso (nada pra trocar), só o hint. Nenhum "Snap" equivalente
        # ao FK/IK (não pedido, e não haveria "lado oposto" pra igualar
        # do mesmo jeito -- ver docstring do módulo em anim_tools.py).
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
            # v0.7.5 -- mesmo botao de keyframe explicito do FK/IK acima.
            row.operator(
                ANIM_OT_hytale_keyframe_switch.bl_idname, text="", icon="KEY_HLT"
            ).switch = "HEAD_FOLLOW"

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def _draw_info(self, layout, context, lang):
        """Aba "Info" -- sem lógica nenhuma, só créditos/links (pedido
        explícito do usuário). URLs em branco por enquanto (ver
        HYBLEND_*_URL no topo do arquivo) -- botão correspondente fica
        desabilitado (`row.enabled = False`) em vez de sumir, pra já
        deixar o layout final montado e só precisar colar a URL depois,
        sem mexer em mais nada.

        Usa o operador nativo `wm.url_open` (mesmo padrão do Blender
        pra abrir link externo) -- não precisou de operador próprio.

        v0.15.x -- ordem das 3 caixas mudou (pedido explícito): Hypixel
        Studios primeiro, depois Links, depois Credits -- era Links/
        Credits/Hypixel Studios."""
        # v0.15.x -- crédito ao Hytale/Hypixel Studios (pedido explícito
        # do usuário): o addon existe pra servir o jogo, mesmo sem
        # nenhuma participação da Hypixel Studios na criação dele --
        # por isso vem com disclaimer de não-afiliação junto (protege
        # os dois lados: deixa claro que o addon não é produto oficial
        # nem endossado, e ainda credita a origem).
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
        # _draw_wrapped_label mede a largura real em pixels (blf) em vez
        # de quebra manual fixa -- ver comentário na função. Desenhado
        # no MESMO hypixel_col (align=True) que a row acima, pra ficar
        # colado sem o espaçamento padrão do Blender entre widgets.
        _draw_wrapped_label(hypixel_col, context, tr("panel.info_credits_hytale_disclaimer", lang))

        layout.separator()

        # v0.15.x -- ERA Patreon/Discord -- virou Nexus Mods/GitHub
        # (pedido explícito). Patreon não sumiu, só mudou de lugar (ver
        # credits_box abaixo, ícone antes do Instagram). Discord saiu
        # de vez, sem substituto direto nesta caixa -- GitHub ocupa o
        # lugar dele na linha, mas é um link novo, não um "Discord
        # renomeado".
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

        # v0.15.x -- "Credits" e "Created by:" (+ nome/ícones) juntos
        # no MESMO column(align=True) -- align=True é o que faz o
        # Blender desenhar itens consecutivos colados, sem o
        # espaçamento padrão entre widgets.
        header_col = credits_box.column(align=True)
        header_col.label(text=tr("panel.info_credits_label", lang), icon="USER")
        header_col.label(text=tr("panel.info_credits_created_by_label", lang))
        credits_row = header_col.row(align=True)
        credits_row.label(text=HYBLEND_AUTHOR_NAME)
        icons_sub = credits_row.row(align=True)
        icons_sub.alignment = "RIGHT"

        # v0.15.x -- Patreon entrou aqui, ANTES do Instagram (pedido
        # explícito) -- saiu da caixa "Links" (ver acima), ícone
        # customizado próprio (fallback "FUND" -- livre agora que
        # "Credits" (acima) usa "USER", sem risco do ícone duplicado
        # que o usuário reclamou antes).
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
    # v0.7.5 -- estado da sub-aba dentro da aba Rig (ver RIG_SUBTAB_ITEMS
    # acima) -- mesmo padrão de hytale_active_tab, só que escopado à
    # aba Rig. "Setup" como default: é a tela que o usuário quer ver
    # primeiro ao abrir o painel (Create Rig e as ações do dia a dia).
    WindowManager.hytale_rig_subtab = EnumProperty(items=_rig_subtab_items, default=0)
    # Estado (aberta/fechada) das seções collapsible da aba Rig -- só UI,
    # não é dado do personagem/rig em si (por isso mora no WindowManager,
    # igual hytale_active_tab, não no Armature). Default False = fechada
    # (pedido explícito: as duas começam collapsed, o fluxo comum do dia
    # a dia é só "Create Rig", sem precisar abrir nenhuma delas).
    # v0.7.5 -- hytale_show_ik_chains REMOVIDA daqui: "Bone Settings"
    # virou sua própria sub-aba (RIG_SUBTAB_ITEMS acima), não faz mais
    # sentido collapsible (ver comentário em _draw_rig_bone_settings).
    WindowManager.hytale_show_bone_collections = BoolProperty(default=False)
    # v0.7.5 -- collapsible da box "Pole" dentro do formulário Arm/Leg
    # (ver _draw_rig_bone_settings) -- mesmo padrão das seções do
    # Texture Picker abaixo. Fechada por padrão: é ajuste fino, não a
    # configuração essencial (essa é "Bones", sempre visível).
    WindowManager.hytale_show_pole_settings = BoolProperty(default=False)
    WindowManager.hytale_show_templates = BoolProperty(default=False)
    # v0.10.14/v0.10.15 -- seções opcionais dentro de uma entrada TEXTURE_PICKER
    # (Reference Image, Companion Bones, Grid) -- mesmo
    # espírito das três acima (só estado de UI, não dado do rig), mas
    # globais entre TODAS as entradas TEXTURE_PICKER/armaturas (não por item da
    # lista -- é só "estou olhando esse tipo de ajuste ou não" no
    # momento). Default False = fechada. Sem trava/auto-abrir nenhuma
    # (pedido explícito do usuário -- v0.10.14 tinha isso só pra
    # Companion Bones, removido na v0.10.15: usuário decide sozinho,
    # sem comportamento especial por trás).
    WindowManager.hytale_show_texture_picker_plane = BoolProperty(default=False)
    WindowManager.hytale_show_texture_picker_companions = BoolProperty(default=False)
    WindowManager.hytale_show_texture_picker_grid = BoolProperty(default=False)
    # v0.12.1 -- caixa da aba Export (Object Properties), não da aba Rig
    # (as três acima) -- mesmo padrão collapsible, chave separada porque
    # é uma seção diferente do painel (não fica dentro de uma entrada
    # TEXTURE_PICKER específica). Fechada por padrão -- a maioria dos
    # personagens não usa Texture Picker, não faz sentido a lista
    # aparecer sempre expandida.
    WindowManager.hytale_show_export_texture_picker = BoolProperty(default=False)
    # v0.15 -- caixa collapsible da seção "First Person Camera" dentro
    # de uma entrada HEAD -- mesmo espírito das do Texture Picker acima
    # (só estado de UI). Fechada por padrão.
    WindowManager.hytale_show_head_camera = BoolProperty(default=False)
    bpy.utils.register_class(HYTALE_PT_main)


def unregister():
    bpy.utils.unregister_class(HYTALE_PT_main)
    del WindowManager.hytale_show_head_camera
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
