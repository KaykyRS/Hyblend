"""anim/ -- pacote de Animação: anim_importer.py (.blockyanim -> Armature) + anim_tools.py (aba Animation)."""

from . import anim_importer, anim_tools

# Reexport pra `from ..anim import X` funcionar igual a `from ..rigger import X`.
from .anim_importer import IMPORT_OT_hytale_blockyanim  # noqa: F401
from .anim_tools import (  # noqa: F401
    ANIM_OT_hytale_keyframe_switch,
    ANIM_OT_hytale_set_fk_ik,
    ANIM_OT_hytale_set_head_follow,
    ANIM_OT_hytale_snap_selected,
    get_fk_ik_state,
    get_head_follow_state,
)

_MODULES = (anim_importer, anim_tools)


def register():
    for module in _MODULES:
        module.register()


def unregister():
    for module in reversed(_MODULES):
        module.unregister()
