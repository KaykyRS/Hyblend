"""
HyblendToolkit -- pacote raiz.
====================================

Este arquivo só faz UMA coisa: registrar/desregistrar os dois submódulos
(importer.py e exporter.py) juntos. Ele não deveria precisar de mudanças
quando você atualizar o importer OU o exporter isoladamente -- só se um dos
dois ganhar/perder uma classe nova de preferences, ou se um terceiro
submódulo for adicionado no futuro (ver DEVELOPER_NOTES.md).

Não existe `bl_info` aqui porque este é um addon no formato "Extension"
(Blender 4.2+) -- os metadados equivalentes vivem em blender_manifest.toml.
"""

from . import common, exporter, importer, anim_importer, interface, rigger

_MODULES = (common, importer, anim_importer, exporter, interface, rigger)


def register():
    for module in _MODULES:
        module.register()


def unregister():
    for module in reversed(_MODULES):
        module.unregister()


if __name__ == "__main__":
    register()
