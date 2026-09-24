"""importer/ -- pacote de Importação.

Um arquivo por formato, só com o que é específico dele; o que TODOS os
importadores usam por igual fica nos arquivos compartilhados:

  common_mesh.py     nome único de bone, tabelas de face/UV, collections
  common_options.py  opções das janelas de import + blocos de interface
  textures.py        busca do PNG (4 passos), material, variantes, ampliação
  preferences.py     preferências do addon (idioma)

  blockymodel.py     .blockymodel (Hytale)
  bbmodel.py         .bbmodel (Blockbench) + import_bbmodel_data(), o núcleo
                     reaproveitado por quem monta um dict .bbmodel em memória
  bedrock.py         modelo Bedrock do Minecraft (.json)

  converter/         SÓ conversão de formatos de fora pra estrutura que os
                     importadores constroem (puro Python, sem Blender)

Formato novo = um arquivo novo aqui (+ um conversor em converter/ se for de
fora do Hytale), registrado em _CLASSES e em menu_func_import.
"""

import bpy

from ..translations import register_localized_class, unregister_localized_class
from .bbmodel import IMPORT_OT_hytale_bbmodel, import_bbmodel_data  # noqa: F401
from .bedrock import IMPORT_OT_hytale_bedrock_model
from .blockymodel import IMPORT_OT_hytale_blockymodel
from .preferences import HytaleImporterPreferences
from .textures import (  # noqa: F401
    clean_texture_path,
    discover_texture_paths_parent_folder,
    resolve_texture_filepaths,
)

_CLASSES = (
    HytaleImporterPreferences,
    IMPORT_OT_hytale_blockymodel,
    IMPORT_OT_hytale_bbmodel,
    IMPORT_OT_hytale_bedrock_model,
)


def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_hytale_blockymodel.bl_idname, text="Hytale Model (.blockymodel)")
    self.layout.operator(IMPORT_OT_hytale_bbmodel.bl_idname, text="Hytale Model (Blockbench .bbmodel)")
    self.layout.operator(IMPORT_OT_hytale_bedrock_model.bl_idname, text="Minecraft Bedrock Model (.json)")


def register():
    for cls in _CLASSES:
        register_localized_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(_CLASSES):
        unregister_localized_class(cls)
