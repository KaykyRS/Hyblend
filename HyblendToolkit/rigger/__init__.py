"""
rigger/__init__.py -- register()/unregister() do pacote Auto-Rigger +
reexport da API pública, pra `from .rigger import X` continuar
funcionando exatamente igual de fora do pacote (interface.py,
anim_importer.py) depois do split de rigger.py num pacote (Tarefa A --
ver DEVELOPER_NOTES.md). Nenhuma lógica própria aqui além de registro --
toda lógica real mora em rig.py (e as constantes puras, em constants.py).

bl_info abaixo é só documentação/versão -- este pacote não roda como
addon avulso do jeito que rigger.py rodava sozinho antes (ver
DEVELOPER_NOTES.md, "Preferences e __name__" e "Testando localmente");
mantido só pra continuar rastreável o "version" que os outros bl_info do
pacote (anim_importer.py) também têm.
"""

bl_info = {
    "name": "Hytale Blocky Rigger",
    "author": "Kaayky",
    "version": (0, 9, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Hytale Rigger",
    "description": "Auto-generate the ORG/MCH/CTRL/CTRL-IK/MCH-IK bone layers, constraints, "
    "IK/FK switch drivers, root control bones and Main/Face/Attachments collections "
    "for a Hytale character armature",
    "category": "Rigging",
}

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Armature, WindowManager

from ..templates import (
    collection_template_enum_items,
    rig_template_enum_items,
    shape_template_enum_items,
)
from ..translations import (
    get_language,
    register_localized_class,
    register_refresh_hook,
    tr,
    unregister_localized_class,
    unregister_refresh_hook,
)

# ---------------------------------------------------------------------------
# Reexport -- tudo que interface.py e anim_importer.py importavam de
# `.rigger` antes do split continua disponível daqui, sem precisar mudar
# nenhum import nesses dois arquivos. Ver DEVELOPER_NOTES.md pra lista
# completa do que cada chat consome.
#
# BONE_PROPERTIES e switch_property_name entraram aqui pro anim_tools.py
# (aba "Animation" -- toggle de FK/IK por cadeia): sem esses dois, ele
# teria que reconstruir na mão o nome do bone ("PROPERTIES") e a regra
# de nomenclatura da custom property (prefixo do tip_bone + sufixo L/R),
# duplicando lógica que já existe aqui -- mesmo motivo pelo qual
# common.py existe entre importer/exporter.
#
# find_org_path entrou junto (FK/IK Snap, mesmo anim_tools.py): recalcula
# em runtime o MESMO caminho root->tip (via armature.bones, não
# edit_bones -- a função não depende do tipo, só de .name/.children/
# .keys()) que "Create Rig" já andou uma vez em Edit Mode -- sem isso,
# o Snap teria sua própria cópia da lógica de "andar pela hierarquia
# ORG", podendo divergir do que o rig realmente gerado tem.
#
# SUFFIX_MCH_IK_TRANSFER entrou pelo mesmo motivo (FK/IK Snap): o bone
# `_IK` da PONTA de uma cadeia (ex. Hand_IK) tem uma rest orientation
# DIFERENTE do bridge `_MCH_IK_Transfer` correspondente (ver
# _build_ik_layer -- o `_IK` da ponta é reorientado, o bridge não),
# então o Snap precisa ler
# `bones[nome + SUFFIX_MCH_IK_TRANSFER].matrix_local` pra calcular esse
# offset e compensar -- sem isso, a rotação da ponta sai torta ao trocar
# pra IK. v0.13: renomeado de SUFFIX_IK_MCH -- anim_tools.py precisa
# trocar o import/uso pro nome novo.
#
# CONSTRAINT_CHILD_OF_LOCAL/GLOBAL entraram junto, mesmo motivo: tanto
# o pole target quanto o ik_tip têm uma Child Of ATIVA por padrão (ver
# _build_pose_constraints) -- `pose_bone.matrix = X` não é "ciente" de
# constraints ativas (o valor final acaba deslocado pela Child Of
# rodando de novo em cima do canal recém-escrito); o Snap precisa
# desativar a constraint pelo NOME antes de escrever a matrix, e
# reativar depois -- ver anim_tools.py.
#
# PROP_HEAD_FOLLOW_SWITCH entrou na v0.13.5 pro mesmo motivo de
# PROP_FK_IK_SWITCH: anim_tools.py (aba Animation) precisa ler/escrever
# a custom property de "Head Free/Lock" (ver HytaleIKChainItem.
# head_follow_enabled/_build_head_follow em rig.py) sem duplicar o
# nome dela na mão.
# ---------------------------------------------------------------------------
from .constants import (  # noqa: F401
    BONE_PROPERTIES,
    BONE_ROOT_MASTER,
    BONE_ROOT_PELVIS,
    CONSTRAINT_CHILD_OF_GLOBAL,
    CONSTRAINT_CHILD_OF_LOCAL,
    PROP_FK_IK_SWITCH,
    PROP_HEAD_FOLLOW_SWITCH,
    PROP_RIG_LAYER,
    SUFFIX_CTRL,
    SUFFIX_IK,
    SUFFIX_MCH,
    SUFFIX_MCH_IK_TRANSFER,
    SUFFIX_MCH_TRANSFER,
    SUFFIX_POLE,
)
from .rig import (  # noqa: F401
    HytaleBoneCollectionItem,
    HytaleIKChainItem,
    RIG_MT_hytale_clear_generated_menu,
    RIG_MT_hytale_ik_chain_add_menu,
    RIG_OT_hytale_bone_collection_add,
    RIG_OT_hytale_bone_collection_load_defaults,
    RIG_OT_hytale_bone_collection_move,
    RIG_OT_hytale_bone_collection_remove,
    RIG_OT_hytale_bone_collection_reset_grid,
    RIG_OT_hytale_camera_create,
    RIG_OT_hytale_camera_remove,
    RIG_OT_hytale_clear_generated,
    RIG_OT_hytale_collection_template_apply,
    RIG_OT_hytale_collection_template_delete,
    RIG_OT_hytale_collection_template_save,
    RIG_OT_hytale_generate_rig,
    RIG_OT_hytale_ik_chain_add,
    RIG_OT_hytale_ik_chain_auto_detect,
    RIG_OT_hytale_ik_chain_load_defaults,
    RIG_OT_hytale_ik_chain_move,
    RIG_OT_hytale_ik_chain_pick_bone,
    RIG_OT_hytale_ik_chain_remove,
    RIG_OT_hytale_ik_chain_set_count,
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
    RIG_UL_hytale_bone_collections,
    RIG_UL_hytale_ik_chains,
    SECTION_ROOT,
    _collection_sort_key,
    _iter_sections_in_order,
    _resolve_collection_parent,
    _resolve_collection_section_name,
    _section_sort_key,
    ensure_default_bone_collections,
    find_org_path,
    register_bone_collection_defaults_handler,
    register_shape_edit_border,
    resolve_collection_override_target,
    switch_property_name,
    unregister_bone_collection_defaults_handler,
    unregister_shape_edit_border,
)

# ---------------------------------------------------------------------------
# Ordem de registro -- MESMA ordem relativa que _CLASSES tinha no
# rigger.py monolítico (Blender às vezes depende disso pra tipos que se
# referenciam entre si). RIG_OT_hytale_validate_rig (Tarefa C) e
# RIG_OT_hytale_mirror_shape (Tarefa D) são NOVOS -- acrescentados no
# fim, depois de RIG_OT_hytale_generate_rig, por não terem nenhuma
# dependência de ordem conhecida com o resto.
# ---------------------------------------------------------------------------
_CLASSES = (
    HytaleIKChainItem,
    RIG_UL_hytale_ik_chains,
    RIG_OT_hytale_ik_chain_add,
    RIG_MT_hytale_ik_chain_add_menu,
    RIG_OT_hytale_ik_chain_remove,
    RIG_OT_hytale_ik_chain_set_count,
    RIG_OT_hytale_ik_chain_pick_bone,
    RIG_OT_hytale_ik_chain_load_defaults,
    RIG_OT_hytale_ik_chain_move,
    # Auto-Detect Bones (novo) -- sem dependência de ordem conhecida com
    # o resto da lista de cadeias (mesmo espírito de
    # RIG_OT_hytale_validate_rig/RIG_OT_hytale_mirror_shape mais abaixo)
    # -- só precisa vir depois de HytaleIKChainItem (já garantido, é o
    # primeiro item de _CLASSES).
    RIG_OT_hytale_ik_chain_auto_detect,
    # v0.9 -- Collection Settings (Etapa 1). HytaleBoneCollectionItem
    # precisa registrar ANTES de qualquer coisa que a referencie via
    # CollectionProperty(type=...) logo abaixo (mesmo motivo pelo qual
    # HytaleIKChainItem é o primeiro da lista).
    HytaleBoneCollectionItem,
    RIG_UL_hytale_bone_collections,
    RIG_OT_hytale_bone_collection_load_defaults,
    RIG_OT_hytale_bone_collection_reset_grid,
    RIG_OT_hytale_bone_collection_add,
    RIG_OT_hytale_bone_collection_remove,
    RIG_OT_hytale_bone_collection_move,
    RIG_OT_hytale_shape_template_apply,
    RIG_OT_hytale_rig_template_save,
    RIG_OT_hytale_rig_template_delete,
    RIG_OT_hytale_shape_template_save,
    RIG_OT_hytale_shape_template_delete,
    RIG_OT_hytale_collection_template_save,
    RIG_OT_hytale_collection_template_apply,
    RIG_OT_hytale_collection_template_delete,
    RIG_OT_hytale_clear_generated,
    RIG_MT_hytale_clear_generated_menu,
    RIG_OT_hytale_shape_edit_mode_enter,
    RIG_OT_hytale_shape_edit_mode_finish,
    # v0.16 -- Vertex Edit Mode, sub-modo de Shape Edit Mode -- registrados
    # logo depois de Enter/Finish, mesma ordem em que aparecem em rig.py
    # (dependem do modo "de fora" já estar ativo, ver poll de
    # RIG_OT_hytale_shape_vertex_edit_mode_enter).
    RIG_OT_hytale_shape_vertex_edit_mode_enter,
    RIG_OT_hytale_shape_vertex_edit_mode_finish,
    RIG_OT_hytale_generate_rig,
    RIG_OT_hytale_validate_rig,
    RIG_OT_hytale_mirror_shape,
    # Embutir malha nos Shape Templates (caso 2, "widget totalmente
    # próprio") -- mesma família de Mirror Shape/Vertex Edit Mode acima
    # (só ativo durante Shape Edit Mode), sem dependência de ordem
    # conhecida com o resto -- acrescentado logo depois delas.
    RIG_OT_hytale_use_selected_as_widget,
    # v0.10 -- Texture Picker (era "Mouth Atlas", generalizado na v0.11 pra
    # qualquer picker de atlas de textura, não só boca). Sem dependência
    # de ordem conhecida com o
    # resto (mesmo espírito de validate_rig/mirror_shape acima) --
    # acrescentados no fim.
    RIG_OT_hytale_texture_picker_create,
    RIG_OT_hytale_texture_picker_remove,
    # v0.15 -- First Person Camera, exclusivo de HEAD. Mesmo espírito de
    # Texture Picker acima -- sem dependência de ordem conhecida com o
    # resto, acrescentados no fim.
    RIG_OT_hytale_camera_create,
    RIG_OT_hytale_camera_remove,
)


def _assign_dynamic_properties(lang=None):
    """Atribui (ou REATRIBUI, no refresh de idioma) todas as properties
    dinâmicas deste pacote -- direto em Armature, fora do ciclo normal
    de register_class. Chamada uma vez em register() (idioma atual) e
    de novo, via register_refresh_hook, toda vez que o idioma do addon
    mudar (ver translations/__init__.py) -- cobre dois casos que
    exigem isso:

    1. Armature.hytale_ik_chains/hytale_bone_collections -- CollectionProperty
       cujo type= aponta pra HytaleIKChainItem/HytaleBoneCollectionItem
       (rig.py), que também usam @localized_props -- precisa ser
       refeita depois que elas forem re-registradas no idioma novo,
       senão a atribuição EXTERNA pode ficar apontando pro RNA struct
       antigo (mesmo motivo documentado em exporter.py,
       _redo_armature_property_assignments -- mesmo padrão aqui).
    2. As 6 properties "soltas" abaixo (Bool/StringProperty direto em
       Armature, sem PropertyGroup nenhum por trás) que têm description=
       própria -- essas não têm classe nenhuma pra decorar com
       @localized_props (só existe pra PropertyGroup/Operator/
       AddonPreferences), então a description= só pode ficar dinâmica
       REATRIBUINDO a property inteira aqui, do mesmo jeito.

    As 3 do WindowManager (seleção de template) ficam de fora de
    propósito -- não têm description= própria pra traduzir, só
    precisam existir uma vez (ver register()/unregister() abaixo)."""
    if lang is None:
        lang = get_language(bpy.context)

    Armature.hytale_ik_chains = CollectionProperty(type=HytaleIKChainItem)
    Armature.hytale_ik_chains_index = IntProperty(default=0)
    Armature.hytale_apply_ik_joint_fix = BoolProperty(
        name="Apply IK Joint Fix",
        description=tr("rigger.prop.armature_apply_ik_joint_fix", lang),
        default=False,
    )
    Armature.hytale_active_rig_template = StringProperty(
        name="Active Rig Template",
        description=tr("rigger.prop.armature_active_rig_template", lang),
        default="",
    )
    Armature.hytale_active_shape_template = StringProperty(
        name="Active Shape Template",
        description=tr("rigger.prop.armature_active_shape_template", lang),
        default="",
    )
    Armature.hytale_active_collection_template = StringProperty(
        name="Active Collection Template",
        description=tr("rigger.prop.armature_active_collection_template", lang),
        default="",
    )
    Armature.hytale_shape_edit_mode = BoolProperty(
        name="Shape Edit Mode",
        description=tr("rigger.prop.armature_shape_edit_mode", lang),
        default=False,
    )
    Armature.hytale_shape_vertex_edit_mode = BoolProperty(
        name="Shape Vertex Edit Mode",
        description=tr("rigger.prop.armature_shape_vertex_edit_mode", lang),
        default=False,
    )

    # v0.9 -- Collection Settings (Etapa 1-3). Lista editável de
    # collections (Main/Face), fonte do dropdown "Collection" em cada
    # entrada de hytale_ik_chains (ver HytaleIKChainItem.collection_override
    # em rig.py) e do que _apply_bone_collection_overrides cria de
    # verdade em "Create Rig". hytale_bone_collections_initialized
    # controla o seed único das 9 entradas default (Head/Spine/Body/
    # Arm L/Arm R/Leg L/Leg R/Root/Tail) -- ver ensure_default_bone_collections,
    # chamada de dentro de execute() de operador (RIG_OT_hytale_generate_rig,
    # RIG_OT_hytale_bone_collection_load_defaults) ou do handler automático
    # register_bone_collection_defaults_handler logo abaixo -- NUNCA de
    # dentro de draw() (ver docstring de ensure_default_bone_collections).
    # v0.7.7 -- lista UNIFICADA (Collection + Section, ver
    # HytaleBoneCollectionItem.entry_type em rig.py) -- ERA duas
    # CollectionProperty separadas (hytale_bone_collections +
    # hytale_bone_sections, v0.7.6), voltou a ser uma só.
    Armature.hytale_bone_collections = CollectionProperty(type=HytaleBoneCollectionItem)
    Armature.hytale_bone_collections_index = IntProperty(default=0)
    Armature.hytale_bone_collections_initialized = BoolProperty(default=False)


def register():
    # v0.14 -- register_localized_class() cuida das classes com
    # @localized_props (ver topo de rig.py) e funciona igual a
    # bpy.utils.register_class() pras outras -- ver translations/
    # __init__.py, seção "Tooltip de campo".
    for cls in _CLASSES:
        register_localized_class(cls)

    _assign_dynamic_properties()
    # Refaz as atribuições acima toda vez que o idioma do addon mudar
    # -- ver docstring de _assign_dynamic_properties.
    register_refresh_hook(_assign_dynamic_properties)

    # Seleção de template (Rig/Shape/Collection) do dropdown compacto da
    # box "Character Templates" do interface.py. No WindowManager (não no
    # Armature, como hytale_ik_chains) porque é a mesma lista de arquivos
    # em disco pra qualquer Armature ativa, não um dado por-personagem.
    WindowManager.hytale_rig_template_selected = EnumProperty(name="Rig Template", items=rig_template_enum_items)
    WindowManager.hytale_shape_template_selected = EnumProperty(
        name="Shape Template", items=shape_template_enum_items,
    )
    WindowManager.hytale_collection_template_selected = EnumProperty(
        name="Collection Template", items=collection_template_enum_items,
    )

    # v0.8 -- borda de Shape Edit Mode (ver register_shape_edit_border/
    # rig.py). Registrado uma vez por sessão do Blender aqui, não por
    # Armature -- o callback mesmo decide se desenha, olhando
    # hytale_shape_edit_mode do armature ativo a cada redraw.
    register_shape_edit_border()

    # v0.9.2 -- seed automático de hytale_bone_collections (Collection
    # Settings), sem precisar clicar em "Load Default Collections" --
    # mesmo espírito do handler acima, um handler de
    # depsgraph_update_post que roda de FORA de draw() (ver docstring
    # completa em register_bone_collection_defaults_handler/rig.py sobre
    # por que draw() não pode fazer isso direto).
    register_bone_collection_defaults_handler()


def unregister():
    unregister_bone_collection_defaults_handler()
    unregister_shape_edit_border()

    del WindowManager.hytale_collection_template_selected
    del WindowManager.hytale_shape_template_selected
    del WindowManager.hytale_rig_template_selected

    unregister_refresh_hook(_assign_dynamic_properties)
    del Armature.hytale_bone_collections_initialized
    del Armature.hytale_bone_collections_index
    del Armature.hytale_bone_collections
    del Armature.hytale_shape_vertex_edit_mode
    del Armature.hytale_shape_edit_mode
    del Armature.hytale_active_collection_template
    del Armature.hytale_active_shape_template
    del Armature.hytale_active_rig_template
    del Armature.hytale_apply_ik_joint_fix
    del Armature.hytale_ik_chains_index
    del Armature.hytale_ik_chains
    for cls in reversed(_CLASSES):
        unregister_localized_class(cls)
