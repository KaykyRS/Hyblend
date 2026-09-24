"""importer/bedrock.py -- import de modelo Bedrock do Minecraft (.json).

Só o que é específico do Bedrock: a janela de opções (geometria, tipo
Character/Prop sem Auto-Detect, inflate, locators), a leitura/validação do
.json e o PNG ampliado pra densidade do Hytale. O resto é compartilhado:
  - conversão Bedrock -> estrutura .bbmodel: converter/bedrock.py
  - construção de Armature/malhas/UV/material: bbmodel.import_bbmodel_data
  - busca de textura, mensagens, ampliação do PNG: textures.py
  - opções/blocos de interface comuns: common_options.py
"""

import json
import os
import re

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from ..common import MODEL_FORMAT_CHARACTER, MODEL_FORMAT_PROP
from ..translations import get_language, localized_props, tooltip, tr
from .bbmodel import import_bbmodel_data
from .common_options import (
    draw_mesh_section,
    draw_rig_section,
    draw_texture_options,
    import_option_props,
    model_format_enum,
)
from .converter.bedrock import bedrock_to_bbmodel_data, detect_json_kind, list_geometries
from .textures import build_scaled_texture, resolve_texture_filepaths, texture_result_report


def bedrock_model_name(json_path):
    """Nome do modelo pra busca de textura: nome do arquivo sem ".json" e
    sem ".geo" (bulbasaur_male.geo.json -> bulbasaur_male) -- equivalente
    ao que o .blockymodel usa (nome do arquivo sem a extensão)."""
    stem = os.path.basename(json_path)
    stem = re.sub(r"\.json$", "", stem, flags=re.I)
    stem = re.sub(r"\.geo$", "", stem, flags=re.I)
    return stem


def _bedrock_import_props(lang):
    return {
        "filter_glob": StringProperty(default="*.json", options={"HIDDEN"}),
        "model_format": model_format_enum(
            lang, "bedrock", with_auto=False,
            labels={"CHARACTER": "Character (x4)", "PROP": "Prop (x2)"},
            item_keys={
                "CHARACTER": "importer.prop.bedrock_model_format_item_character",
                "PROP": "importer.prop.bedrock_model_format_item_prop",
            },
        ),
        "geometry_identifier": StringProperty(
            name="Geometry",
            description=tr("importer.prop.bedrock_geometry_identifier", lang),
            default="",
        ),
        "inflate_to_stretch": BoolProperty(
            name="Inflate to Stretch",
            description=tr("importer.prop.bedrock_inflate_to_stretch", lang),
            default=True,
        ),
        "drop_locator_bones": BoolProperty(
            name="Remove Locator Bones",
            description=tr("importer.prop.bedrock_drop_locator_bones", lang),
            default=False,
        ),
        **import_option_props(lang, "bedrock", (
            "armature_name", "orient_z_up", "unit_scale", "generate_reference_boxes", "flat_mesh_collections",
            "generate_uvs", "create_material", "texture_mode", "texture_filepath",
        )),
    }


def _pick_geometry(operator, geometries):
    """Geometria escolhida em "Geometry" (vazio = a primeira). Devolve None
    (e reporta o erro) se o nome não existir."""
    wanted = operator.geometry_identifier.strip()
    if wanted:
        matches = [g for g in geometries if g[0] in (wanted, "geometry." + wanted)]
        if not matches:
            available = ", ".join(g[0] for g in geometries)
            operator.report({"ERROR"}, f"Geometry '{wanted}' not found. Available: {available}")
            return None
        return matches[0]
    if len(geometries) > 1:
        others = ", ".join(g[0] for g in geometries[1:])
        operator.report({"INFO"}, f"File has {len(geometries)} geometries -- imported '{geometries[0][0]}'. Others: {others}")
    return geometries[0]


def _load_textures(operator, bb_data, scale_factor):
    """Resolve o PNG (mesma busca/Texture Mode de todos os importadores) e
    carrega principal + variantes AMPLIADOS pra densidade do Hytale
    ("resolution" do bb_data já vem x k). Devolve (preloaded, nota) no
    formato de import_bbmodel_data: {0: [principal, variantes...]}."""
    model_name = bedrock_model_name(operator.filepath)
    paths, tier = resolve_texture_filepaths(
        operator.filepath, operator.texture_mode, operator.texture_filepath, model_name
    )
    paths = [bpy.path.abspath(p) for p in paths]
    note = None
    texture_report = texture_result_report(operator.texture_mode, tier, paths, model_name)
    if operator.texture_mode == "MANUAL" and tier == "NONE":
        note = "Texture Mode is Manual but no file was set -- imported without texture."
    elif texture_report and texture_report[0] == "WARNING":
        operator.report({"WARNING"}, texture_report[1])
    elif texture_report:
        note = texture_report[1]
    if not paths or not os.path.isfile(paths[0]):
        return {}, note

    res = bb_data["resolution"]
    images = []
    for path in paths:
        image = build_scaled_texture(
            path, res["width"], res["height"],
            name=os.path.splitext(os.path.basename(path))[0] + f"_x{scale_factor:g}",
        )
        if image is None and not images:
            operator.report({"WARNING"}, f"Could not load the texture '{os.path.basename(path)}' -- imported without it.")
            return {}, note
        if image is not None:
            images.append(image)
    bb_data["textures"] = [{"name": images[0].name}]
    return {0: images}, note


@localized_props(_bedrock_import_props)
class IMPORT_OT_hytale_bedrock_model(Operator, ImportHelper):
    """Import a Minecraft Bedrock model (.json) converted to the Hytale standard"""

    bl_idname = "import_scene.hytale_bedrock_model"
    bl_label = "Import Bedrock Model (.json)"
    description = tooltip("importer.tooltip.bedrock_model")
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".json"

    def draw(self, context):
        layout = self.layout
        lang = get_language(context)

        target_box = layout.box()
        target_box.label(text=tr("importer.section_target", lang))
        target_box.prop(self, "armature_name", text=tr("importer.armature_name", lang))
        target_box.prop(self, "geometry_identifier", text=tr("importer.bedrock_geometry_identifier", lang))

        conv_box = layout.box()
        conv_box.label(text=tr("importer.bedrock_section_conversion", lang))
        conv_box.prop(self, "model_format", text=tr("importer.model_format", lang))
        conv_box.prop(self, "inflate_to_stretch", text=tr("importer.bedrock_inflate_to_stretch", lang))
        conv_box.prop(self, "drop_locator_bones", text=tr("importer.bedrock_drop_locator_bones", lang))

        draw_rig_section(layout, self, lang, show_model_format=False)
        sub = draw_mesh_section(layout, self, lang)
        draw_texture_options(sub, self, lang)

    def execute(self, context):
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({"ERROR"}, "No file selected -- choose a Bedrock model (.json).")
            return {"CANCELLED"}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            self.report({"ERROR"}, f"Could not read '{os.path.basename(self.filepath)}' as JSON: {exc}")
            return {"CANCELLED"}

        kind = detect_json_kind(data)
        if kind == "bedrock_animation":
            self.report({"ERROR"}, "This is a Bedrock ANIMATION file, not a model (animation import is not supported yet).")
            return {"CANCELLED"}
        if kind == "java_block_model":
            self.report({"ERROR"}, "This looks like a Java Edition block/item model -- not supported yet (only Bedrock models).")
            return {"CANCELLED"}
        if kind not in ("bedrock_geometry", "bedrock_geometry_legacy"):
            self.report({"ERROR"}, "Unrecognized .json -- expected a Bedrock model (\"minecraft:geometry\").")
            return {"CANCELLED"}

        geometries = list_geometries(data)
        if not geometries:
            self.report({"ERROR"}, "No geometry found in the file.")
            return {"CANCELLED"}
        geometry = _pick_geometry(self, geometries)
        if geometry is None:
            return {"CANCELLED"}

        model_format = MODEL_FORMAT_PROP if self.model_format == "PROP" else MODEL_FORMAT_CHARACTER
        bb_data, conv = bedrock_to_bbmodel_data(geometry, model_format, self.inflate_to_stretch, self.drop_locator_bones)
        if not bb_data["outliner"]:
            self.report({"ERROR"}, "The geometry has no bones.")
            return {"CANCELLED"}

        preloaded, texture_note = {}, None
        if self.generate_reference_boxes and self.create_material:
            preloaded, texture_note = _load_textures(self, bb_data, conv["scale_factor"])

        result, armature_obj = import_bbmodel_data(self, context, bb_data, self.filepath, model_format, preloaded)
        if armature_obj is None:
            return result
        armature_obj["hytale_source_format"] = "bedrock"
        armature_obj["hytale_source_geometry"] = geometry[0]

        notes = [f"Converted from Minecraft (x{conv['scale_factor']:g}, {model_format})."]
        if conv["inflated"]:
            notes.append(f"{conv['inflated']} inflated cube(s) converted to stretch.")
        if conv["dropped_locators"]:
            notes.append(f"{conv['dropped_locators']} locator bone(s) removed.")
        if texture_note:
            notes.append(texture_note)
        self.report({"INFO"}, " ".join(notes))
        for key, what in (("texture_meshes", "texture_meshes"), ("poly_mesh", "poly_mesh")):
            if conv[key]:
                self.report({"WARNING"}, f"{conv[key]} bone(s) use {what}, which Hytale doesn't support -- skipped.")
        if conv["missing_parents"]:
            self.report({"WARNING"}, f"{conv['missing_parents']} bone(s) point to a parent that doesn't exist -- placed at the root.")
        if conv["parent_geometry"]:
            self.report({"WARNING"}, f"Geometry inherits from '{conv['parent_geometry']}' -- inherited bones are not imported.")
        return result
