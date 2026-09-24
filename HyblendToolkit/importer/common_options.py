"""importer/common_options.py -- opções COMPARTILHADAS das janelas de import
(.blockymodel, .bbmodel, Bedrock) e os blocos de interface dessas opções.

Cada opção é definida UMA vez aqui (nome, default, limites); cada formato
só diz QUAIS opções usa e, quando o texto de ajuda precisa explicar algo
específico dele (ex: de onde vem o nome da Armature), qual key de tradução
usar. Sem key específica, vale a genérica "importer.prop.<opção>"."""

from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

from ..common import UNIT_SCALE_DEFAULT
from ..translations import tr

# Keys de tooltip específicas por formato -- o que não estiver aqui usa
# "importer.prop.<opção>" (texto igual pra todos os formatos).
TOOLTIP_KEYS = {
    "blockymodel": {
        "model_format": "importer.prop.blockymodel_model_format",
        "armature_name": "importer.prop.blockymodel_armature_name",
        "generate_reference_boxes": "importer.prop.blockymodel_generate_reference_boxes",
        "generate_uvs": "importer.prop.blockymodel_generate_uvs",
        "create_material": "importer.prop.blockymodel_create_material",
        "texture_mode": "importer.prop.blockymodel_texture_mode",
        "texture_filepath": "importer.prop.blockymodel_texture_filepath",
    },
    "bbmodel": {
        "model_format": "importer.prop.bbmodel_model_format",
        "armature_name": "importer.prop.bbmodel_armature_name",
        "generate_reference_boxes": "importer.prop.bbmodel_generate_reference_boxes",
        "generate_uvs": "importer.prop.bbmodel_generate_uvs",
        "create_material": "importer.prop.bbmodel_create_material",
    },
    "bedrock": {
        "model_format": "importer.prop.bedrock_model_format",
        "armature_name": "importer.prop.bedrock_armature_name",
        "texture_mode": "importer.prop.bedrock_texture_mode",
        "texture_filepath": "importer.prop.bedrock_texture_filepath",
    },
}


def _tooltip_key(fmt, option):
    return TOOLTIP_KEYS.get(fmt, {}).get(option, f"importer.prop.{option}")


def model_format_enum(lang, fmt, with_auto=True, labels=None, item_keys=None):
    """EnumProperty "Model Type" (Character 64/bloco vs Prop 32/bloco --
    ver MODEL_FORMAT_* em common.py). `with_auto`: formatos do Hytale
    sabem o próprio tipo (Auto-Detect); formatos de fora (Bedrock) não.
    `labels`/`item_keys`: troca rótulo/ajuda de Character/Prop."""
    labels = labels or {"CHARACTER": "Character (64/block)", "PROP": "Prop (32/block)"}
    item_keys = item_keys or {
        "CHARACTER": "importer.prop.model_format_item_character",
        "PROP": "importer.prop.model_format_item_prop",
    }
    items = []
    if with_auto:
        items.append(("AUTO", "Auto-Detect", tr("importer.prop.model_format_item_auto", lang)))
    items += [(key, labels[key], tr(item_keys[key], lang)) for key in ("CHARACTER", "PROP")]
    return EnumProperty(
        name="Model Type",
        description=tr(_tooltip_key(fmt, "model_format"), lang),
        items=items,
        default="AUTO" if with_auto else "CHARACTER",
    )


def _texture_mode_enum(lang, fmt):
    return EnumProperty(
        name="Texture Mode",
        description=tr(_tooltip_key(fmt, "texture_mode"), lang),
        items=[
            ("AUTO", "Automatic", tr(f"importer.prop.{fmt}_texture_mode_item_auto", lang)),
            ("MANUAL", "Manual", tr("importer.prop.texture_mode_item_manual", lang)),
        ],
        default="AUTO",
    )


# Uma fábrica por opção -- (lang, fmt) -> Property.
_OPTION_FACTORIES = {
    "armature_name": lambda lang, fmt: StringProperty(
        name="Armature Name", description=tr(_tooltip_key(fmt, "armature_name"), lang), default="",
    ),
    "orient_z_up": lambda lang, fmt: BoolProperty(
        name="Orient to Z-up (visual only)", description=tr(_tooltip_key(fmt, "orient_z_up"), lang), default=True,
    ),
    "unit_scale": lambda lang, fmt: FloatProperty(
        name="Scale (Blender units per game unit)",
        description=tr(_tooltip_key(fmt, "unit_scale"), lang),
        default=UNIT_SCALE_DEFAULT,
        min=0.0001,
        max=10.0,
    ),
    "generate_reference_boxes": lambda lang, fmt: BoolProperty(
        name="Generate Reference Meshes",
        description=tr(_tooltip_key(fmt, "generate_reference_boxes"), lang),
        default=True,
    ),
    "flat_mesh_collections": lambda lang, fmt: BoolProperty(
        name="Flat Mesh Collections", description=tr(_tooltip_key(fmt, "flat_mesh_collections"), lang), default=False,
    ),
    "generate_uvs": lambda lang, fmt: BoolProperty(
        name="Generate UVs", description=tr(_tooltip_key(fmt, "generate_uvs"), lang), default=True,
    ),
    "create_material": lambda lang, fmt: BoolProperty(
        name="Create Material", description=tr(_tooltip_key(fmt, "create_material"), lang), default=True,
    ),
    "texture_mode": _texture_mode_enum,
    "texture_filepath": lambda lang, fmt: StringProperty(
        name="Texture Image",
        description=tr(_tooltip_key(fmt, "texture_filepath"), lang),
        default="",
        subtype="FILE_PATH",
    ),
}


def import_option_props(lang, fmt, options):
    """Dict {nome: Property} das opções compartilhadas pedidas, pro
    formato `fmt` ("blockymodel"/"bbmodel"/"bedrock"). Cada formato junta
    isto com as opções só dele no próprio _xxx_import_props()."""
    return {option: _OPTION_FACTORIES[option](lang, fmt) for option in options}


# ---------------------------------------------------------------------------
# Blocos de interface (draw) -- mesma ordem/visual em todos os importadores
# ---------------------------------------------------------------------------


def draw_rig_section(layout, op, lang, orient_enabled=True, show_model_format=True):
    """Caixa "Rig": Z-up, tipo Character/Prop, escala. `show_model_format`
    False quando o formato mostra o tipo em outra caixa (Bedrock: faz
    parte da conversão)."""
    rig_box = layout.box()
    rig_box.label(text=tr("importer.section_rig", lang))
    orient_row = rig_box.column()
    orient_row.enabled = orient_enabled
    orient_row.prop(op, "orient_z_up", text=tr("importer.orient_z_up", lang))
    if show_model_format:
        rig_box.prop(op, "model_format", text=tr("importer.model_format", lang))
    rig_box.prop(op, "unit_scale", text=tr("importer.unit_scale", lang))
    return rig_box


def draw_mesh_section(layout, op, lang):
    """Caixa "Visuals": gerar malhas, collections, UV, material. Devolve a
    coluna interna (ativa só com "Generate Reference Meshes") pra quem
    chama acrescentar o que é só dele (atlas, textura)."""
    vis_box = layout.box()
    vis_box.label(text=tr("importer.section_visuals", lang))
    vis_box.prop(op, "generate_reference_boxes", text=tr("importer.generate_reference_boxes", lang))
    sub = vis_box.column()
    sub.enabled = op.generate_reference_boxes
    sub.prop(op, "flat_mesh_collections", text=tr("importer.flat_mesh_collections", lang))
    sub.prop(op, "generate_uvs", text=tr("importer.generate_uvs", lang))
    sub.prop(op, "create_material", text=tr("importer.create_material", lang))
    return sub


def draw_texture_options(layout, op, lang):
    """Texture Mode + caminho manual (ativo só em Manual). Fica ativo só
    com "Create Material" ligado."""
    tex = layout.column()
    tex.enabled = op.generate_reference_boxes and op.create_material
    tex.prop(op, "texture_mode", text=tr("importer.texture_mode", lang))
    manual_row = tex.column()
    manual_row.enabled = op.texture_mode == "MANUAL"
    manual_row.prop(op, "texture_filepath", text=tr("importer.texture_filepath", lang))
    return tex
