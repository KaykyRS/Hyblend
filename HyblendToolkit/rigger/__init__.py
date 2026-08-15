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

# ---------------------------------------------------------------------------
# Reexport -- tudo que interface.py e anim_importer.py importavam de
# `.rigger` antes do split continua disponível daqui, sem precisar mudar
# nenhum import nesses dois arquivos. Ver DEVELOPER_NOTES.md pra lista
# completa do que cada chat consome.
# ---------------------------------------------------------------------------
from .constants import (  # noqa: F401
    BONE_ROOT_MASTER,
    BONE_ROOT_PELVIS,
    PROP_FK_IK_SWITCH,
    PROP_RIG_LAYER,
    SUFFIX_CTRL,
    SUFFIX_IK,
    SUFFIX_MCH,
    SUFFIX_POLE,
    SUFFIX_TAIL,
)
from .rig import (  # noqa: F401
    HytaleIKChainItem,
    RIG_MT_hytale_ik_chain_add_menu,
    RIG_OT_hytale_clear_generated,
    RIG_OT_hytale_collection_template_apply,
    RIG_OT_hytale_collection_template_delete,
    RIG_OT_hytale_collection_template_save,
    RIG_OT_hytale_generate_rig,
    RIG_OT_hytale_ik_chain_add,
    RIG_OT_hytale_ik_chain_load_defaults,
    RIG_OT_hytale_ik_chain_pick_bone,
    RIG_OT_hytale_ik_chain_remove,
    RIG_OT_hytale_ik_chain_set_count,
    RIG_OT_hytale_mirror_shape,
    RIG_OT_hytale_rig_template_delete,
    RIG_OT_hytale_rig_template_save,
    RIG_OT_hytale_shape_edit_mode_enter,
    RIG_OT_hytale_shape_edit_mode_finish,
    RIG_OT_hytale_shape_template_apply,
    RIG_OT_hytale_shape_template_delete,
    RIG_OT_hytale_shape_template_save,
    RIG_OT_hytale_validate_rig,
    RIG_UL_hytale_ik_chains,
    register_shape_edit_border,
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
    RIG_OT_hytale_shape_template_apply,
    RIG_OT_hytale_rig_template_save,
    RIG_OT_hytale_rig_template_delete,
    RIG_OT_hytale_shape_template_save,
    RIG_OT_hytale_shape_template_delete,
    RIG_OT_hytale_collection_template_save,
    RIG_OT_hytale_collection_template_apply,
    RIG_OT_hytale_collection_template_delete,
    RIG_OT_hytale_clear_generated,
    RIG_OT_hytale_shape_edit_mode_enter,
    RIG_OT_hytale_shape_edit_mode_finish,
    RIG_OT_hytale_generate_rig,
    RIG_OT_hytale_validate_rig,
    RIG_OT_hytale_mirror_shape,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    Armature.hytale_ik_chains = CollectionProperty(type=HytaleIKChainItem)
    Armature.hytale_ik_chains_index = IntProperty(default=0)
    Armature.hytale_apply_ik_joint_fix = BoolProperty(
        name="Apply IK Joint Fix",
        description=(
            "Corrects the X position of specific IK chain joints, using the values defined by the active "
            "rig template (see 'ik_joint_x_overrides' in templates/rig/*.json) -- leave off for a template "
            "that hasn't defined/calibrated these values yet"
        ),
        default=False,
    )
    Armature.hytale_active_rig_template = StringProperty(
        name="Active Rig Template",
        description="Name of the rig template (templates/rig/*.json) currently loaded on this armature -- "
        "set automatically by 'Load Hytale IK Chain Preset', used to resolve pole_angle_presets/"
        "ik_joint_x_overrides/widget_translation_x_overrides at generation time",
        default="",
    )
    Armature.hytale_active_shape_template = StringProperty(
        name="Active Shape Template",
        description="Name of the shape template (templates/shapes/*.json) currently active for this "
        "armature's custom shapes -- set automatically together with the rig template (or manually via "
        "'Set Hytale Shape Template')",
        default="",
    )
    Armature.hytale_active_collection_template = StringProperty(
        name="Active Collection Template",
        description="Name of the collection template (templates/collections/*.json) most recently saved to "
        "or applied on this armature -- purely informational (unlike the rig/shape templates, this one is "
        "never auto-applied by 'Create Rig')",
        default="",
    )
    Armature.hytale_shape_edit_mode = BoolProperty(
        name="Shape Edit Mode",
        description="True while RIG_OT_hytale_shape_edit_mode_enter's mute is in effect on this armature's "
        "FK/IK shape-scale drivers -- set/cleared automatically by 'Enter'/'Finish Shape Edit Mode', read by "
        "interface.py to decide which of the two buttons to show and by 'Create Rig'/'Remove Generated Hytale "
        "Rig Bones' to refuse running mid-edit",
        default=False,
    )

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


def unregister():
    unregister_shape_edit_border()

    del WindowManager.hytale_collection_template_selected
    del WindowManager.hytale_shape_template_selected
    del WindowManager.hytale_rig_template_selected
    del Armature.hytale_shape_edit_mode
    del Armature.hytale_active_collection_template
    del Armature.hytale_active_shape_template
    del Armature.hytale_active_rig_template
    del Armature.hytale_apply_ik_joint_fix
    del Armature.hytale_ik_chains_index
    del Armature.hytale_ik_chains
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
