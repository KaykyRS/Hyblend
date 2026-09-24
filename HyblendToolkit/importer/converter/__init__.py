"""importer/converter/ -- CONVERSÃO de formatos de fora do Hytale pra
estrutura que os importadores já sabem construir. Só conversão (puro
Python, sem Blender, sem operador); o import de cada formato mora em
importer/<formato>.py. Hoje: modelo Bedrock do Minecraft (bedrock.py)."""

from .bedrock import (  # noqa: F401
    bedrock_to_bbmodel_data,
    detect_json_kind,
    list_geometries,
)
