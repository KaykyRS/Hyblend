"""Auto-Rigger -- Bone Settings: HytaleIKChainItem e operadores de lista (add/remove/move/auto-detect/load defaults)."""

import re

from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Menu, Operator, PropertyGroup, UIList

from ..common import is_active_armature
from ..templates import (
    get_rig_template,
    get_shape_template,
)
from ..translations import localized_props, tooltip, tr

from .constants import (
    ATTACHMENTS_MAX_COUNT,
    ATTACHMENT_NAME_HINT,
    ROOT_MAX_COUNT,
    SUFFIX_CTRL,
    SUFFIX_IK,
    SUFFIX_MCH,
    TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT,
    _TEMPLATE_NONE,
)

from .helpers import _redraw_all_areas, normalize_org_name, split_side_token
from .rename import RENAME_MIDDLE_PROP, RENAME_TOGGLE_PROPS
from .bone_collections import COLLECTION_OVERRIDE_AUTO, _bone_collection_enum_items, _collection_override_get, _collection_override_set


# Campos de HytaleIKChainItem serializáveis pra JSON (usada por
# RIG_OT_hytale_ik_chain_load_defaults pra ler de volta). Um campo novo
# em HytaleIKChainItem SEMPRE precisa entrar aqui também, senão
# Save/Load Rig Template descarta o valor em silêncio -- já aconteceu
# mais de uma vez (Head/Spine, texture_picker_plane_scale,
# collection_override).
_IK_CHAIN_JSON_FIELDS = (
    "chain_type", "label", "root_bone", "tip_bone", "pole_bone", "parent_override", "side",
    "pole_invert", "pole_distance", "pole_angle_mode", "pole_angle_preset_name",
    "pole_angle_manual", "pole_angle_fine_tune", "tail_tip_rotation_axis", "tail_tip_rotation_deg",
    "tail_use_connect",  # exclusivo de CHAIN -- estava faltando aqui (Save/Load descartava em silêncio)
    "neck_count", "neck_bone_1", "neck_bone_2", "neck_bone_3", "neck_bone_4", "neck_bone_5",
    "head_is_main", "head_bone", "head_end_bone",
    "spine_count", "spine_ctrl_enabled", "pelvis_bone", "spine_bone_1", "spine_bone_2", "spine_bone_3", "spine_bone_4",
    "continuous_chain", "continuous_chain_link_bone",  # compartilhado por HEAD/SPINE; sem UI, mas ainda salvo
    "head_follow_enabled",  # exclusivo de HEAD
    "head_camera_enabled", "head_camera_parent_bone",
    "head_camera_offset_x", "head_camera_offset_y", "head_camera_offset_z",
    "head_camera_rotation_x", "head_camera_rotation_y", "head_camera_rotation_z",
    "head_camera_fov",
    "attachments_count", *(f"attachment_bone_{i}" for i in range(1, ATTACHMENTS_MAX_COUNT + 1)),
    "root_count",
    *(f"root_bone_{i}" for i in range(1, ROOT_MAX_COUNT + 1)),
    *(f"root_create_{i}" for i in range(1, ROOT_MAX_COUNT + 1)),
    # Parte 4 -- caixinhas de "Rename Bones" (uma por campo renomeável +
    # rename_chain_middle), ver rigger/rename.py.
    *RENAME_TOGGLE_PROPS,
    "texture_picker_bone", "texture_picker_ui_parent_bone", "texture_picker_plane_scale", "texture_picker_plane_offset_x", "texture_picker_plane_offset_y",
    "texture_picker_grid_cols", "texture_picker_grid_rows",
    "texture_picker_grid_cell_width", "texture_picker_grid_cell_height",
    "texture_picker_extra_bone_count", *(f"texture_picker_extra_bone_{i}" for i in range(1, TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT + 1)),
    # Guarda "collection_override_name" (o nome cru), não
    # "collection_override" (o Enum dinâmico) -- setar o Enum com um
    # nome que ainda não existe no personagem de destino lançaria erro.
    "collection_override_name",
)


def _head_is_main_update(self, context):
    """"Main Head" funciona como um radio button entre as entradas HEAD
    da mesma lista -- só faz sentido existir UMA cabeça "principal" por
    vez (é ela que resolve_head_ctrl_name/resolve_head_chain_item, em
    rigger/helpers.py, usa pra PROPERTIES/FK-IK switch, Head Follow, a
    bone collection Main/Head e o widget/cor dedicados de Head_CTRL --
    ver docstring lá pro bug original que motivou essa opção existir:
    um personagem com mais de uma entrada HEAD deixava esse escolha
    implícita e inconsistente entre as diferentes partes do código).

    Marcar aqui desmarca automaticamente qualquer outra entrada HEAD.
    Desmarcar a única marcada é permitido (fica sem nenhuma "principal"
    -- resolve_head_chain_item cai de volta pra "primeira entrada HEAD
    da lista", mesmo comportamento de antes desta opção existir)."""
    if not self.head_is_main:
        return
    obj = context.active_object
    if obj is None or obj.type != "ARMATURE":
        return
    self_ptr = self.as_pointer()
    for other in obj.data.hytale_ik_chains:
        if other.as_pointer() != self_ptr and other.chain_type == "HEAD" and other.head_is_main:
            other.head_is_main = False


def _ik_chain_item_props(lang):
    props = {
        # ARM/LEG/TAIL criam bone de verdade (mesma lógica de geração
        # da antiga "IK Chain" única, só o rótulo muda por tipo). HEAD/
        # SPINE/ATTACHMENTS/TEXTURE_PICKER não criam bone -- só
        # referenciam _CTRLs que já existem (organizacional/picker).
        "chain_type": EnumProperty(
            name="Type",
            description=tr("rigger.prop.ik_chain_chain_type", lang),
            items=[
                ("ARM", "Arm", tr("rigger.prop.ik_chain_chain_type_item_arm", lang)),
                ("LEG", "Leg", tr("rigger.prop.ik_chain_chain_type_item_leg", lang)),
                ("CHAIN", "Chain", tr("rigger.prop.ik_chain_chain_type_item_chain", lang)),
                ("HEAD", "Head", tr("rigger.prop.ik_chain_chain_type_item_head", lang)),
                ("SPINE", "Spine", tr("rigger.prop.ik_chain_chain_type_item_spine", lang)),
                ("ATTACHMENTS", "Attachments", tr("rigger.prop.ik_chain_chain_type_item_attachments", lang)),
                ("TEXTURE_PICKER", "Texture Picker", tr("rigger.prop.ik_chain_chain_type_item_texture_picker", lang)),
                # SEMPRE no fim: o .blend guarda o Enum pelo ÍNDICE do item
                # -- inserir no meio desloca os tipos de entradas já salvas
                # (um "ARM" antigo viraria outro tipo ao abrir o arquivo).
                ("ROOT", "Root", tr("rigger.prop.ik_chain_chain_type_item_root", lang)),
            ],
            default="ARM",
        ),
        "label": StringProperty(
            name="Label",
            description=tr("rigger.prop.ik_chain_label", lang),
            default="",
        ),
        "root_bone": StringProperty(
            name="Root Bone",
            description=tr("rigger.prop.ik_chain_root_bone", lang),
            default="",
        ),
        "tip_bone": StringProperty(
            name="Tip Bone",
            description=tr("rigger.prop.ik_chain_tip_bone", lang),
            default="",
        ),
        "pole_bone": StringProperty(
            name="Pole Reference",
            description=tr("rigger.prop.ik_chain_pole_bone", lang),
            default="",
        ),
        "parent_override": StringProperty(
            name="Root Parent",
            description=tr("rigger.prop.ik_chain_parent_override", lang),
            default="",
        ),
        "tail_tip_rotation_axis": EnumProperty(
            name="Tip Rotation Axis",
            description=tr("rigger.prop.ik_chain_tail_tip_rotation_axis", lang),
            items=[
                ("X", "X (Local)", tr("rigger.prop.ik_chain_tail_tip_rotation_axis_item_x", lang)),
                ("Y", "Y (Local)", tr("rigger.prop.ik_chain_tail_tip_rotation_axis_item_y", lang)),
                ("Z", "Z (Local)", tr("rigger.prop.ik_chain_tail_tip_rotation_axis_item_z", lang)),
            ],
            default="Z",
        ),
        "tail_tip_rotation_deg": FloatProperty(
            name="Tip Rotation (deg)",
            description=tr("rigger.prop.ik_chain_tail_tip_rotation_deg", lang),
            default=0.0,
        ),
        "tail_use_connect": BoolProperty(
            name="Connected",
            description=tr("rigger.prop.ik_chain_tail_use_connect", lang),
            default=False,
        ),
        "side": EnumProperty(
            name="Side",
            description=tr("rigger.prop.ik_chain_side", lang),
            items=[
                ("LEFT", "Left", ""),
                ("RIGHT", "Right", ""),
                ("CENTER", "Center", ""),
            ],
            default="CENTER",
        ),
        "pole_invert": BoolProperty(
            name="Pole in Front (+Z)",
            description=tr("rigger.prop.ik_chain_pole_invert", lang),
            default=False,
        ),
        "pole_distance": FloatProperty(
            name="Pole Distance",
            description=tr("rigger.prop.ik_chain_pole_distance", lang),
            default=0.35,
            min=0.001,
        ),
        "pole_angle_mode": EnumProperty(
            name="Pole Angle Mode",
            items=[
                ("AUTO", "Auto", tr("rigger.prop.ik_chain_pole_angle_mode_item_auto", lang)),
                ("PRESET", "Preset (from Template)", tr("rigger.prop.ik_chain_pole_angle_mode_item_preset", lang)),
                ("MANUAL", "Manual", tr("rigger.prop.ik_chain_pole_angle_mode_item_manual", lang)),
            ],
            default="AUTO",
        ),
        "pole_angle_preset_name": StringProperty(
            name="Pole Angle Preset",
            description=tr("rigger.prop.ik_chain_pole_angle_preset_name", lang),
            default="ARM",
        ),
        "pole_angle_manual": FloatProperty(
            name="Pole Angle (deg)",
            description=tr("rigger.prop.ik_chain_pole_angle_manual", lang),
            default=90.0,
        ),
        "pole_angle_fine_tune": FloatProperty(
            name="Pole Angle Fine-Tune (deg)",
            description=tr("rigger.prop.ik_chain_pole_angle_fine_tune", lang),
            default=0.0,
        ),
        "neck_count": IntProperty(
            name="Neck Bones Amount",
            description=tr("rigger.prop.ik_chain_neck_count", lang),
            default=1, min=0, max=5,
        ),
        "neck_bone_1": StringProperty(
            name="Neck", description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang), default=""
        ),
        "neck_bone_2": StringProperty(
            name="Neck 2", description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang), default=""
        ),
        "neck_bone_3": StringProperty(
            name="Neck 3", description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang), default=""
        ),
        "neck_bone_4": StringProperty(
            name="Neck 4", description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang), default=""
        ),
        "neck_bone_5": StringProperty(
            name="Neck 5", description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang), default=""
        ),
        "head_bone": StringProperty(
            name="Head",
            description=tr("rigger.prop.ik_chain_head_bone", lang),
            default="",
        ),
        "head_end_bone": StringProperty(
            name="Head End",
            description=tr("rigger.prop.ik_chain_head_end_bone", lang),
            default="",
        ),
        "spine_count": IntProperty(
            name="Spine Amount",
            description=tr("rigger.prop.ik_chain_spine_count", lang),
            default=3, min=1, max=5,
        ),
        # Liga/desliga root.spine_CTRL e os constraints de Spine Follow
        # que dependem dele. default=True preserva o comportamento de
        # quem já rodou "Create Rig" antes desta opção existir.
        "spine_ctrl_enabled": BoolProperty(
            name="Create root.spine_CTRL",
            description=tr("rigger.prop.ik_chain_spine_ctrl_enabled", lang),
            default=True,
        ),
        "pelvis_bone": StringProperty(
            name="Pelvis", description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang), default=""
        ),
        "spine_bone_1": StringProperty(
            name="Spine1", description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang), default=""
        ),
        "spine_bone_2": StringProperty(
            name="Spine2", description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang), default=""
        ),
        "spine_bone_3": StringProperty(
            name="Spine3", description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang), default=""
        ),
        "spine_bone_4": StringProperty(
            name="Spine4", description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang), default=""
        ),
        "continuous_chain": BoolProperty(
            name="Continuous Chain",
            description=tr("rigger.prop.ik_chain_continuous_chain", lang),
            default=False,
        ),
        "continuous_chain_link_bone": StringProperty(
            name="Connect Last Bone To",
            description=tr("rigger.prop.ik_chain_continuous_chain_link_bone", lang),
            default="",
        ),
        # Radio button entre entradas HEAD (ver _head_is_main_update) --
        # nasce True na primeira entrada HEAD adicionada (default do
        # campo) e False em qualquer HEAD seguinte, forçado
        # explicitamente por RIG_OT_hytale_ik_chain_add/_set_count
        # (default=True sozinho não bastaria: toda entrada NOVA nasceria
        # marcada, quebrando a exclusividade). Desenhada acima de "Head
        # Free/Lock" na UI (interface/__init__.py), pedido explícito do
        # usuário.
        "head_is_main": BoolProperty(
            name="Main Head",
            description=tr("rigger.prop.ik_chain_head_is_main", lang),
            default=True,
            update=_head_is_main_update,
        ),
        # TODO (v-futura, pedido explícito do usuário pra documentar
        # aqui e não implementar ainda): hoje "Head Free/Lock" só
        # funciona de verdade na entrada Main Head (ver head_is_main
        # acima) -- _apply_head_follow_parent/_build_head_follow (em
        # generate.py) só processam resolve_head_chain_item(armature),
        # que devolve UMA entrada só. Se o usuário ligar este toggle
        # numa entrada HEAD que NÃO é a Main Head, o checkbox fica
        # marcado na UI mas não tem NENHUM efeito -- é ignorado em
        # silêncio (parece quebrado, mas é limitação conhecida, não bug
        # novo). Motivo estrutural: o switch fica gravado como UM
        # custom property (PROP_HEAD_FOLLOW_SWITCH) no bone PROPERTIES,
        # compartilhado pelo rig inteiro -- não tem como duas cabeças
        # independentes disputarem a mesma chave.
        #
        # Plano pra quando for implementar de verdade (personagem com
        # 2+ cabeças, cada uma com Free/Lock próprio):
        #   1. _apply_head_follow_parent deixa de pegar só
        #      resolve_head_chain_item -- passa a iterar TODA entrada
        #      HEAD com head_bone preenchido (mesmo filtro de
        #      resolve_head_chain_item, sem escolher só uma), aplicando
        #      o redirect/parent=None por cabeça, independente.
        #   2. PROP_HEAD_FOLLOW_SWITCH vira um nome DERIVADO por cabeça
        #      (ex. f"{PROP_HEAD_FOLLOW_SWITCH}__{head_item.head_bone}"),
        #      não mais uma constante fixa -- assim cada cabeça grava a
        #      própria chave no mesmo bone PROPERTIES, sem colidir.
        #   3. _build_head_follow/_apply_pole_childof_inverses (ambos em
        #      generate.py) passam a receber uma LISTA de
        #      (active, source, head_ctrl_name, switch_prop_name) em vez
        #      de um tupla única -- constroem/limpam constraints e Set
        #      Inverse pra cada cabeça da lista, cada uma com nome de
        #      switch e bone-alvo próprios.
        #   4. anim/anim_tools.py (_resolve_switch_prop e afins) precisa
        #      saber qual PROP_HEAD_FOLLOW_SWITCH* pertence a qual
        #      Head_CTRL selecionado, já que deixa de haver uma chave
        #      fixa só -- provavelmente resolvendo o nome da chave a
        #      partir do bone ativo/selecionado em vez de uma constante.
        "head_follow_enabled": BoolProperty(
            name="Head Free/Lock",
            description=tr("rigger.prop.ik_chain_head_follow_enabled", lang),
            default=False,
        ),
        "head_camera_enabled": BoolProperty(
            name="Create First Person Camera",
            description=tr("rigger.prop.ik_chain_head_camera_enabled", lang),
            default=False,
        ),
        "head_camera_parent_bone": StringProperty(
            name="Camera Parent Bone",
            description=tr("rigger.prop.ik_chain_head_camera_parent_bone", lang),
            default="",
        ),
        "head_camera_offset_x": FloatProperty(
            name="Camera Offset X", default=0.0,
            description=tr("rigger.prop.ik_chain_head_camera_offset_x", lang),
        ),
        "head_camera_offset_y": FloatProperty(
            name="Camera Offset Y", default=0.0,
            description=tr("rigger.prop.ik_chain_head_camera_offset_y", lang),
        ),
        "head_camera_offset_z": FloatProperty(
            name="Camera Offset Z", default=0.0,
            description=tr("rigger.prop.ik_chain_head_camera_offset_z", lang),
        ),
        "head_camera_rotation_x": FloatProperty(
            name="Camera Rotation X (deg)", default=0.0,
            description=tr("rigger.prop.ik_chain_head_camera_rotation_x", lang),
        ),
        "head_camera_rotation_y": FloatProperty(
            name="Camera Rotation Y (deg)", default=180.0,
            description=tr("rigger.prop.ik_chain_head_camera_rotation_y", lang),
        ),
        "head_camera_rotation_z": FloatProperty(
            name="Camera Rotation Z (deg)", default=0.0,
            description=tr("rigger.prop.ik_chain_head_camera_rotation_z", lang),
        ),
        "head_camera_fov": FloatProperty(
            name="Camera FOV (deg)", default=90.0, min=1.0, max=179.0,
            description=tr("rigger.prop.ik_chain_head_camera_fov", lang),
        ),
        "attachments_count": IntProperty(
            name="Attachments Bones Amount",
            description=tr("rigger.prop.ik_chain_attachments_count", lang).format(max=ATTACHMENTS_MAX_COUNT),
            default=1, min=0, max=ATTACHMENTS_MAX_COUNT,
        ),
    }
    for _i in range(1, ATTACHMENTS_MAX_COUNT + 1):
        props[f"attachment_bone_{_i}"] = StringProperty(
            name="Attachment" if _i == 1 else f"Attachment {_i}",
            description=tr("rigger.prop.ik_chain_org_bone_name_hint", lang),
            default="",
        )
    # ROOT -- Root 1 = Origin principal (pai do root.master_CTRL, alvo do
    # Child Of global dos poles/tips); Root 2 vira pai do Root 1, Root 3
    # pai do Root 2... (só na camada _CTRL -- a hierarquia ORG exportada
    # não muda). "New Bone" cria o bone quando o modelo não tem um.
    props["root_count"] = IntProperty(
        name="Root Bones Amount",
        description=tr("rigger.prop.ik_chain_root_count", lang).format(max=ROOT_MAX_COUNT),
        default=1, min=1, max=ROOT_MAX_COUNT,
    )
    for _i in range(1, ROOT_MAX_COUNT + 1):
        props[f"root_bone_{_i}"] = StringProperty(
            name="Origin" if _i == 1 else f"Root {_i}",
            description=tr("rigger.prop.ik_chain_root_slot_bone", lang),
            default="",
        )
        props[f"root_create_{_i}"] = BoolProperty(
            name="New Bone",
            description=tr("rigger.prop.ik_chain_root_create", lang),
            default=False,
        )
    # "Rename Bones" -- caixinha por campo renomeável (ligada = o bone
    # ganha o nome padrão do Hytale; desligada = mantém o original).
    for _toggle in RENAME_TOGGLE_PROPS:
        props[_toggle] = BoolProperty(
            name="Rename",
            description=tr(
                "rigger.prop.ik_chain_rename_middle" if _toggle == RENAME_MIDDLE_PROP
                else "rigger.prop.ik_chain_rename_field",
                lang,
            ),
            default=True,
        )
    props.update({
        "texture_picker_bone": StringProperty(
            name="Target Bone",
            description=tr("rigger.prop.ik_chain_texture_picker_bone", lang),
            default="",
        ),
        "texture_picker_ui_parent_bone": StringProperty(
            name="Root Bone",
            description=tr("rigger.prop.ik_chain_texture_picker_ui_parent_bone", lang),
            default="",
        ),
        "texture_picker_plane_scale": FloatProperty(
            name="Atlas Plane Scale",
            description=tr("rigger.prop.ik_chain_texture_picker_plane_scale", lang),
            default=1.0, min=0.001,
        ),
        "texture_picker_plane_offset_x": FloatProperty(
            name="Atlas Plane Offset X", default=0.0,
            description=tr("rigger.prop.ik_chain_texture_picker_plane_offset_x", lang),
        ),
        "texture_picker_plane_offset_y": FloatProperty(
            name="Atlas Plane Offset Y", default=0.0,
            description=tr("rigger.prop.ik_chain_texture_picker_plane_offset_y", lang),
        ),
        "texture_picker_grid_cols": IntProperty(
            name="Grid Columns",
            description=tr("rigger.prop.ik_chain_texture_picker_grid_cols", lang),
            default=1, min=1,
        ),
        "texture_picker_grid_rows": IntProperty(
            name="Grid Rows",
            description=tr("rigger.prop.ik_chain_texture_picker_grid_rows", lang),
            default=1, min=1,
        ),
        "texture_picker_grid_cell_width": IntProperty(
            name="Cell Width",
            description=tr("rigger.prop.ik_chain_texture_picker_grid_cell_width", lang),
            default=16, min=1,
        ),
        "texture_picker_grid_cell_height": IntProperty(
            name="Cell Height",
            description=tr("rigger.prop.ik_chain_texture_picker_grid_cell_height", lang),
            default=16, min=1,
        ),
        "texture_picker_extra_bone_count": IntProperty(
            name="Companion Bones Amount",
            description=tr("rigger.prop.ik_chain_texture_picker_extra_bone_count", lang).format(
                max=TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT
            ),
            default=0, min=0, max=TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT,
        ),
    })
    for _i in range(1, TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT + 1):
        props[f"texture_picker_extra_bone_{_i}"] = StringProperty(
            name="Companion Bone" if _i == 1 else f"Companion Bone {_i}",
            description=tr("rigger.prop.ik_chain_texture_picker_extra_bone", lang),
            default="",
        )
    # Guarda o valor de verdade (nome, imune a reordenação de Collection
    # Settings -- ver _collection_override_get/_collection_override_set
    # em bone_collections.py). Nunca desenhada na UI.
    props["collection_override_name"] = StringProperty(
        name="Collection (internal)",
        description="Internal storage for the Collection override -- not shown in the UI.",
        default=COLLECTION_OVERRIDE_AUTO,
        options={"HIDDEN"},
    )
    props["collection_override"] = EnumProperty(
        name="Collection",
        description=tr("rigger.prop.ik_chain_collection_override", lang),
        items=_bone_collection_enum_items,
        get=_collection_override_get,
        set=_collection_override_set,
    )
    return props


@localized_props(_ik_chain_item_props)
class HytaleIKChainItem(PropertyGroup):
    pass


# --- Operadores: gerenciar a lista de Bone Settings ---


def _unique_bone_setting_label(chains, base_label, ignore_index=None):
    """Devolve `base_label` sozinho se nenhum item da lista (fora
    `ignore_index`, usado quando já existe um item sendo re-rotulado) já
    tiver exatamente esse label -- só acrescenta um sufixo (".001",
    ".002", ...) quando já existe colisão, mesma convenção que o próprio
    Blender usa pra nomes duplicados de objeto/collection/etc. Antes
    disso, todo item novo nascia como "Head 3", "Arm 5" etc. (o índice
    cru dentro da lista, sempre crescente mesmo depois de remover itens
    do meio) -- pedido explícito do usuário pra só aparecer sufixo quando
    for necessário pra desambiguar de verdade."""
    existing = {
        item.label
        for i, item in enumerate(chains)
        if item.label and i != ignore_index
    }
    if base_label not in existing:
        return base_label
    n = 1
    while True:
        candidate = f"{base_label}.{n:03d}"
        if candidate not in existing:
            return candidate
        n += 1


def _init_head_is_main(item, chains):
    """Chamada logo depois de `item.chain_type = "HEAD"` ser atribuído,
    nos 3 lugares que criam entradas novas (Add, Set Count,
    Auto-Detect) -- decide o valor inicial de head_is_main: True só se
    esta for a ÚNICA entrada HEAD da lista no momento, False se já
    existir outra. O default=True do próprio campo (ver
    _ik_chain_item_props) não bastaria sozinho -- toda entrada NOVA
    nasceria marcada, quebrando a exclusividade de "uma cabeça
    principal por vez" (ver _head_is_main_update)."""
    item_ptr = item.as_pointer()
    has_other_head = any(
        c.as_pointer() != item_ptr and c.chain_type == "HEAD" for c in chains
    )
    item.head_is_main = not has_other_head


class RIG_OT_hytale_ik_chain_add(Operator):
    """Adiciona uma entrada vazia à lista (preencha os nomes dos bones
    depois -- ou via um picker). v0.7: recebe `chain_type` (ARM/LEG/
    TAIL) -- quem decide QUAL tipo adicionar é o menu popup
    RIG_MT_hytale_ik_chain_add_menu (clicado a partir do botão "+" em
    interface.py), não mais um clique direto neste operador."""

    bl_idname = "armature.hytale_ik_chain_add"
    bl_label = "Add Hytale Bone Setting"
    description = tooltip("rigger.tooltip.ik_chain_add")
    bl_options = {"REGISTER", "UNDO"}

    chain_type: StringProperty(default="ARM")

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        item = chains.add()
        # Valida contra os tipos conhecidos -- o menu popup manda uma
        # string crua, nunca deixa a entrada num estado inválido.
        item.chain_type = self.chain_type if self.chain_type in {"ROOT", "ARM", "LEG", "CHAIN", "HEAD", "SPINE", "ATTACHMENTS", "TEXTURE_PICKER"} else "ARM"
        if item.chain_type == "HEAD":
            _init_head_is_main(item, chains)
        prefix = {"ROOT": "Root", "ARM": "Arm", "LEG": "Leg", "CHAIN": "Chain", "HEAD": "Head", "SPINE": "Spine", "ATTACHMENTS": "Attachments", "TEXTURE_PICKER": "Texture Picker"}.get(item.chain_type, "Chain")
        item.label = _unique_bone_setting_label(chains, prefix)
        # Nasce coerente com o próprio chain_type em vez de sempre "ARM"
        # (default do campo) -- só um nome, não precisa existir de
        # verdade em pole_angle_presets até o modo Preset ser usado.
        item.pole_angle_preset_name = item.chain_type
        armature.hytale_ik_chains_index = len(chains) - 1
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_MT_hytale_ik_chain_add_menu(Menu):
    """Menu popup do "+" da lista -- pergunta que tipo adicionar antes
    de criar o item. Cada opção só chama armature.hytale_ik_chain_add
    com um chain_type diferente, nenhuma lógica própria."""

    bl_idname = "RIG_MT_hytale_ik_chain_add_menu"
    bl_label = "Add Bone Setting"
    description = tooltip("rigger.tooltip.ik_chain_add_menu")

    def draw(self, context):
        layout = self.layout
        # Ordem pedida explicitamente: Head -> Spine -> Arm -> Leg ->
        # Chain -> Root -> Attachments -> Texture Picker.
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Head", icon="USER"
        ).chain_type = "HEAD"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Spine", icon="BONE_DATA"
        ).chain_type = "SPINE"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Arm", icon="CON_KINEMATIC"
        ).chain_type = "ARM"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Leg", icon="CON_KINEMATIC"
        ).chain_type = "LEG"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Chain", icon="PHYSICS"
        ).chain_type = "CHAIN"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Root", icon="OBJECT_ORIGIN"
        ).chain_type = "ROOT"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Attachments", icon="LINKED"
        ).chain_type = "ATTACHMENTS"
        layout.operator(
            RIG_OT_hytale_ik_chain_add.bl_idname, text="Texture Picker", icon="IMAGE_DATA"
        ).chain_type = "TEXTURE_PICKER"


class RIG_OT_hytale_ik_chain_remove(Operator):
    """Remove uma cadeia da lista pelo índice (padrão: a ativa)."""

    bl_idname = "armature.hytale_ik_chain_remove"
    bl_label = "Remove Hytale IK Chain"
    description = tooltip("rigger.tooltip.ik_chain_remove")
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and len(obj.data.hytale_ik_chains) > 0

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        index = self.index if self.index >= 0 else armature.hytale_ik_chains_index
        if 0 <= index < len(chains):
            chains.remove(index)
            armature.hytale_ik_chains_index = max(0, min(armature.hytale_ik_chains_index, len(chains) - 1))
        _redraw_all_areas(context)
        return {"FINISHED"}


def _ik_chain_move_props(lang):
    return {
        "direction": EnumProperty(
            items=(
                ("UP", "Up", tr("rigger.prop.ik_chain_move_direction_item_up", lang)),
                ("DOWN", "Down", tr("rigger.prop.ik_chain_move_direction_item_down", lang)),
            ),
            default="UP",
        ),
    }


@localized_props(_ik_chain_move_props)
class RIG_OT_hytale_ik_chain_move(Operator):
    """Reordena uma entrada da lista (armature.hytale_ik_chains) uma
    posição pra cima ou pra baixo, via CollectionProperty.move() --
    mesmo padrão que interface.py já usa pro par Add/Remove, só que
    aqui é um único operador com um `direction` (UP/DOWN) em vez de dois
    operadores separados, já que a lógica dos dois lados é idêntica
    (só troca o delta do índice). Reordenar é puramente cosmético/
    organizacional -- não afeta geração de rig nenhuma (RIG_OT_hytale_
    generate_rig lê hytale_ik_chains percorrendo a coleção inteira, sem
    depender de ordem -- ver _build_edit_bones), só a ordem em que as
    entradas aparecem na UIList."""

    bl_idname = "armature.hytale_ik_chain_move"
    bl_label = "Move Hytale Bone Setting"
    description = tooltip("rigger.tooltip.ik_chain_move")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and len(obj.data.hytale_ik_chains) > 1

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        index = armature.hytale_ik_chains_index
        target = index - 1 if self.direction == "UP" else index + 1
        if not (0 <= target < len(chains)):
            return {"CANCELLED"}
        chains.move(index, target)
        armature.hytale_ik_chains_index = target
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_OT_hytale_ik_chain_set_count(Operator):
    """Ajusta a lista de cadeias de IK pra ter exatamente `count` itens --
    adiciona vazias no fim ou remove do fim, sem tocar nas do meio. Não é
    chamado de lugar nenhum em interface.py hoje (a lista lá usa só Add/
    Remove, um item de cada vez, via RIG_OT_hytale_ik_chain_add/_remove) --
    existe pra uso via script/console externo, quando é mais prático setar
    a quantidade de uma vez. `chain_type` (v0.8) alinha o que este
    operador cria com RIG_MT_hytale_ik_chain_add_menu/RIG_OT_hytale_ik_chain_add
    acima: mesma validação (cai pra "ARM" se vier algo fora de ARM/LEG/
    CHAIN) e mesmo prefixo de label por tipo ("Arm N"/"Leg N"/"Chain N",
    identificador CHAIN -- ver v0.7.14 no changelog, ERA "TAIL" -- não
    mais um "Chain N" genérico de antes usado pra QUALQUER tipo, que
    também nunca setava chain_type nenhum -- item novo ficava com o
    default ARM do Enum, mas rotulado "Chain", inconsistente com o
    próprio tipo que acabou de receber)."""

    bl_idname = "armature.hytale_ik_chain_set_count"
    bl_label = "Set Hytale IK Chain Count"
    description = tooltip("rigger.tooltip.ik_chain_set_count")
    bl_options = {"REGISTER", "UNDO"}

    count: IntProperty(name="Amount", default=1, min=0)
    chain_type: StringProperty(default="ARM")

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        chain_type = self.chain_type if self.chain_type in {"ROOT", "ARM", "LEG", "CHAIN", "HEAD", "SPINE", "ATTACHMENTS", "TEXTURE_PICKER"} else "ARM"
        prefix = {"ROOT": "Root", "ARM": "Arm", "LEG": "Leg", "CHAIN": "Chain", "HEAD": "Head", "SPINE": "Spine", "ATTACHMENTS": "Attachments", "TEXTURE_PICKER": "Texture Picker"}.get(chain_type, "Chain")
        while len(chains) < self.count:
            item = chains.add()
            item.chain_type = chain_type
            if chain_type == "HEAD":
                _init_head_is_main(item, chains)
            # v0.13 -- mesmo fix de RIG_OT_hytale_ik_chain_add: sufixo só
            # quando já existe outro item com esse label exato.
            item.label = _unique_bone_setting_label(chains, prefix)
            item.pole_angle_preset_name = chain_type  # v0.8 -- mesmo fix de RIG_OT_hytale_ik_chain_add acima
        while len(chains) > self.count:
            chains.remove(len(chains) - 1)
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_OT_hytale_ik_chain_pick_bone(Operator):
    """Copia o nome do bone atualmente ativo (Edit Mode, Pose Mode, ou o
    último selecionado no Object Mode) pro campo indicado do item de
    cadeia IK indicado. Não é a UI de picker em si (isso é botão/ícone,
    trabalho do chat da interface.py) -- é só a lógica que o botão de
    eyedropper vai chamar: selecione o bone no viewport, então rode este
    operador com `chain_index` e `field` apontando pro campo certo
    ("root_bone", "tip_bone", "pole_bone" ou "parent_override")."""

    bl_idname = "armature.hytale_ik_chain_pick_bone"
    bl_label = "Pick Bone From Selection"
    description = tooltip("rigger.tooltip.ik_chain_pick_bone")
    bl_options = {"REGISTER", "UNDO"}

    chain_index: IntProperty(default=-1)
    field: StringProperty(default="root_bone")

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def execute(self, context):
        obj = context.active_object
        bone_name = None
        if context.mode == "EDIT_ARMATURE" and context.active_bone is not None:
            bone_name = context.active_bone.name
        elif context.mode == "POSE" and context.active_pose_bone is not None:
            bone_name = context.active_pose_bone.name
        elif obj.data.bones.active is not None:
            bone_name = obj.data.bones.active.name

        if not bone_name:
            self.report({"WARNING"}, "No active bone to pick -- select one in Edit or Pose Mode first.")
            return {"CANCELLED"}

        chains = obj.data.hytale_ik_chains
        index = self.chain_index if self.chain_index >= 0 else obj.data.hytale_ik_chains_index
        if not (0 <= index < len(chains)):
            self.report({"WARNING"}, "Invalid IK chain index.")
            return {"CANCELLED"}
        allowed_fields = {
            "root_bone", "tip_bone", "pole_bone", "parent_override",
            "neck_bone_1", "neck_bone_2", "neck_bone_3", "neck_bone_4", "neck_bone_5",
            "head_bone", "head_end_bone",
            "pelvis_bone", "spine_bone_1", "spine_bone_2", "spine_bone_3", "spine_bone_4",
            "continuous_chain_link_bone",
            *{f"attachment_bone_{i}" for i in range(1, ATTACHMENTS_MAX_COUNT + 1)},
            *{f"root_bone_{i}" for i in range(1, ROOT_MAX_COUNT + 1)},
            "texture_picker_bone",
            "texture_picker_ui_parent_bone",
            "head_camera_parent_bone",
            *{f"texture_picker_extra_bone_{i}" for i in range(1, TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT + 1)},
        }
        if self.field not in allowed_fields:
            self.report({"WARNING"}, f"Unknown field '{self.field}'.")
            return {"CANCELLED"}

        # No Pose Mode (rig gerado) o bone ativo costuma ser o _CTRL -- os
        # ORG ficam escondidos. O campo guarda o ORG de onde ele nasceu;
        # no Root Parent o _CTRL é legítimo e fica como está.
        if self.field != "parent_override":
            bone_name = normalize_org_name(obj.data.bones, bone_name)
        setattr(chains[index], self.field, bone_name)
        self.report({"INFO"}, f"{self.field} = '{bone_name}'.")
        return {"FINISHED"}


# --- Auto-Detect Bones: heurística de nomenclatura, sem depender de rig template ---
#
# Complementa Load Defaults ("sei exatamente que personagem é esse")
# com "não sei, tenta adivinhar". Só os 6 slots mais previsíveis por
# nome (Head, Spine, Arm L/R, Leg L/R) -- Tail/Attachments/Texture
# Picker dependem demais do personagem, ficam de fora de propósito.

# "L-"/"R-" é a convenção oficial; os outros tokens são fallback pra
# mods que não seguem essa convenção. Ordem importa (mais específico primeiro).
def _auto_detect_split_side(bone_name):
    """(side, base) -- base é o nome sem o token de lado, em minúsculo,
    só pra comparar (o nome ORIGINAL entra inteiro nos campos do
    item). Ex.: "L-Forearm" -> ("LEFT", "forearm"). Tokens aceitos
    vivem em helpers.py (SIDE_PREFIX_TOKENS/SIDE_SUFFIX_TOKENS) --
    mesma fonte do fallback de cor por nome em _build_bone_colors."""
    return split_side_token(bone_name)


def _auto_detect_is_excluded_bone(name):
    """True pra bone que NUNCA deve entrar como candidato de Bone
    Settings -- já gerado por um "Create Rig" anterior (sufixo _CTRL/
    _MCH/_IK) ou attachment (ATTACHMENT_NAME_HINT no nome). Usada tanto
    por _auto_detect_candidates (varredura plana) quanto por
    _auto_detect_walk_down/_walk_up (varredura de hierarquia) -- as
    duas precisam da MESMA regra de exclusão, senão a varredura de
    hierarquia (que anda em bone.children/.parent direto, não na lista
    já filtrada) acaba puxando um attachment pendurado no meio da
    coluna/pescoço pra dentro da cadeia (ex.: um "ChestplateAttachment"
    filho de Chest vira "spine_bone_3" por engano)."""
    lower = name.lower()
    if name.endswith(SUFFIX_CTRL) or name.endswith(SUFFIX_MCH) or name.endswith(SUFFIX_IK):
        return True
    return ATTACHMENT_NAME_HINT in lower


def _auto_detect_candidates(armature_data):
    """Varre armature_data.bones (só ORG -- ver
    _auto_detect_is_excluded_bone) e devolve uma lista de (bone_name,
    side, base) -- base já passou por _auto_detect_split_side, pronta
    pra bater contra palavra-chave via `in`."""
    out = []
    for bone in armature_data.bones:
        name = bone.name
        if _auto_detect_is_excluded_bone(name):
            continue
        side, base = _auto_detect_split_side(name)
        out.append((name, side, base))
    return out


def _auto_detect_pick(candidates, keywords, exclude_keywords=(), side=None):
    """Primeiro candidato cujo `base` contenha alguma palavra de
    `keywords` (e NENHUMA de `exclude_keywords`) -- side=None casa
    candidato de QUALQUER lado (inclusive sem lado nenhum -- usado pra
    bones tipo Pelvis/Head, que normalmente não têm token de lado).
    Prioriza candidato cujo `base` seja EXATAMENTE a keyword (match mais
    limpo, ex. "arm") antes de aceitar substring solta (ex.
    "upperarmtwist") -- assim um nome mais "normal" sempre vence um
    nome mais estranho quando os dois batem."""
    exact = None
    loose = None
    for name, cand_side, base in candidates:
        if side is not None and cand_side != side:
            continue
        if any(bad in base for bad in exclude_keywords):
            continue
        for kw in keywords:
            if base == kw:
                if exact is None:
                    exact = name
                break
            if kw in base:
                if loose is None:
                    loose = name
                break
    return exact or loose


def _auto_detect_pick_multi(candidates, keywords, exclude_keywords=(), side=None):
    """Todos os candidatos que batem (mesma regra de _auto_detect_pick),
    nomes só, sem duplicar -- usado como FALLBACK pra Neck/Spine quando
    a varredura de hierarquia (_auto_detect_walk_up/_down, abaixo) não
    encontra nada (esqueleto sem o parentesco esperado)."""
    found = []
    seen = set()
    for name, cand_side, base in candidates:
        if side is not None and cand_side != side:
            continue
        if any(bad in base for bad in exclude_keywords):
            continue
        if any(kw in base for kw in keywords) and name not in seen:
            found.append(name)
            seen.add(name)
    return found


def _auto_detect_natural_sort_key(name):
    """"Spine2" antes de "Spine10" (não como string pura) -- usado só
    pelo fallback de nome (_auto_detect_pick_multi), quando a varredura
    de hierarquia não achou nada pra ordenar de verdade."""
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r"(\d+)", name)]


def _auto_detect_walk_down(bone, keywords, exclude_keywords=()):
    """A partir de `bone` (NÃO incluído no resultado), desce filho a
    filho sempre escolhendo o primeiro filho cujo nome bata com
    `keywords` (e nenhuma de `exclude_keywords`) -- pra cadeias
    lineares tipo Pelvis -> Belly -> Chest. Devolve a lista de nomes na
    ordem raiz -> ponta (a ordem que spine_bone_1/2/3/4 espera). Muito
    mais confiável que ordenar por texto quando o personagem não numera
    os bones (ex. "Belly"/"Chest" sem número nenhum)."""
    out = []
    node = bone
    while node is not None:
        nxt = None
        for child in node.children:
            if _auto_detect_is_excluded_bone(child.name):
                continue
            child_base = child.name.lower()
            if any(bad in child_base for bad in exclude_keywords):
                continue
            if any(kw in child_base for kw in keywords):
                nxt = child
                break
        if nxt is None:
            break
        out.append(nxt.name)
        node = nxt
    return out


def _auto_detect_walk_up(bone, keywords, exclude_keywords=()):
    """Espelho de _auto_detect_walk_down, subindo por .parent em vez de
    descer por .children -- a partir do PAI de `bone` (não inclui
    `bone` em si), sobe enquanto o nome do pai bater com `keywords`.
    Usada pra Neck: sobe a partir do Head até parar de achar "neck",
    depois inverte pra devolver na ordem raiz -> ponta (o Neck mais
    perto do peito primeiro, o mais perto da cabeça por último)."""
    out = []
    node = bone.parent if bone is not None else None
    while node is not None:
        if _auto_detect_is_excluded_bone(node.name):
            break
        base = node.name.lower()
        if any(bad in base for bad in exclude_keywords):
            break
        if not any(kw in base for kw in keywords):
            break
        out.append(node.name)
        node = node.parent
    out.reverse()
    return out


def _auto_detect_bone_settings(armature_data):
    """Devolve um dict com o melhor palpite pra cada slot reconhecido --
    chaves "HEAD"/"SPINE" (sem lado) ou ("ARM"/"LEG", "LEFT"/"RIGHT")
    (por lado) -- cada valor é um dict {nome_do_campo: valor} pronto pra
    jogar em setattr(item, campo, valor). Só inclui uma entrada se o
    bone PRINCIPAL daquele slot foi encontrado (head_bone pra Head,
    pelvis e/ou 1 segmento de coluna pra Spine, root+tip pra Arm/Leg) --
    nunca devolve uma entrada vazia. Pura leitura (não mexe em
    armature.hytale_ik_chains nenhum) -- quem decide o que fazer com o
    resultado é o Operator abaixo."""
    candidates = _auto_detect_candidates(armature_data)
    bones = armature_data.bones
    results = {}

    # --- Head / Neck --------------------------------------------------
    head_name = _auto_detect_pick(candidates, ("head",), exclude_keywords=("forehead",))
    if head_name:
        entry = {"head_bone": head_name}
        head_bone_obj = bones.get(head_name)
        neck_names = _auto_detect_walk_up(head_bone_obj, ("neck",)) if head_bone_obj else []
        if not neck_names:
            neck_names = sorted(
                _auto_detect_pick_multi(candidates, ("neck",)),
                key=_auto_detect_natural_sort_key,
            )
        for i, n in enumerate(neck_names[:5], start=1):
            entry[f"neck_bone_{i}"] = n
        if neck_names:
            entry["neck_count"] = min(len(neck_names), 5)
        results["HEAD"] = entry

    # --- Spine ----------------------------------------------------------
    pelvis_name = _auto_detect_pick(candidates, ("pelvis", "hips", "hip"))
    spine_names = []
    if pelvis_name:
        pelvis_obj = bones.get(pelvis_name)
        if pelvis_obj is not None:
            spine_names = _auto_detect_walk_down(pelvis_obj, ("spine", "belly", "chest", "torso"))
    if not spine_names:
        spine_names = sorted(
            _auto_detect_pick_multi(candidates, ("spine", "belly", "chest", "torso")),
            key=_auto_detect_natural_sort_key,
        )
    if pelvis_name or spine_names:
        entry = {}
        if pelvis_name:
            entry["pelvis_bone"] = pelvis_name
        for i, n in enumerate(spine_names[:4], start=1):
            entry[f"spine_bone_{i}"] = n
        if pelvis_name or spine_names:
            # Conta o Pelvis junto: 1 (se achado) + segmentos, teto 5.
            entry["spine_count"] = max(1, (1 if pelvis_name else 0) + min(len(spine_names), 4))
        results["SPINE"] = entry

    # --- Arm / Leg, por lado ---
    # exclude_keywords também evita que um bone de equipamento (ex.
    # "L-Handle" de arma) roube a vaga de um match solto quando não
    # existe (ainda) um "Hand"/"Arm" exato pra ganhar por prioridade.
    for side in ("LEFT", "RIGHT"):
        forearm = _auto_detect_pick(candidates, ("forearm", "lowerarm"), side=side)
        hand = _auto_detect_pick(candidates, ("hand",), exclude_keywords=("handle",), side=side)
        arm = _auto_detect_pick(
            candidates, ("upperarm", "arm"),
            exclude_keywords=("forearm", "lowerarm", "armor", "armour"), side=side,
        )
        if arm and hand:
            entry = {"root_bone": arm, "tip_bone": hand, "side": side}
            if forearm:
                entry["pole_bone"] = forearm
            shoulder = _auto_detect_pick(candidates, ("shoulder", "clavicle"), side=side)
            if shoulder:
                entry["parent_override"] = shoulder
            results[("ARM", side)] = entry

        calf = _auto_detect_pick(candidates, ("calf", "shin", "lowerleg", "knee"), side=side)
        foot = _auto_detect_pick(candidates, ("foot", "feet"), side=side)
        thigh = _auto_detect_pick(
            candidates, ("thigh", "upperleg", "leg"),
            exclude_keywords=("calf", "shin", "lowerleg"), side=side,
        )
        if thigh and foot:
            entry = {"root_bone": thigh, "tip_bone": foot, "side": side}
            if calf:
                entry["pole_bone"] = calf
            if pelvis_name:
                entry["parent_override"] = pelvis_name  # nome ORG puro, sem "_CTRL"
            results[("LEG", side)] = entry

    return results


class RIG_OT_hytale_ik_chain_auto_detect(Operator):
    """Varre os bones ORG do armature ativo e tenta preencher Bone
    Settings sozinho pros 6 slots mais comuns (Head, Spine, Arm L/R, Leg
    L/R), usando palavras-chave de nomenclatura comuns (Head/Neck;
    Pelvis/Spine/Belly/Chest; Shoulder/Arm/Forearm/Hand;
    Thigh/Calf/Foot) + prefixo/sufixo de lado ("L-"/"R-" é o principal,
    ver SIDE_PREFIX_TOKENS em helpers.py, com alguns fallbacks pra mods que
    nomeiam diferente). Puramente heurístico -- não substitui revisão
    manual, só poupa digitação no caso comum; sempre confira os campos
    preenchidos antes de "Create Rig". NUNCA sobrescreve uma entrada já
    existente do mesmo tipo (e do mesmo lado, pra Arm/Leg) -- roda de
    novo com segurança depois de ajustes manuais, só preenche o que
    ainda falta."""

    bl_idname = "armature.hytale_ik_chain_auto_detect"
    bl_label = "Auto-Detect Bone Settings"
    description = tooltip("rigger.tooltip.ik_chain_auto_detect")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def execute(self, context):
        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        detected = _auto_detect_bone_settings(armature)

        existing_head = any(c.chain_type == "HEAD" for c in chains)
        existing_spine = any(c.chain_type == "SPINE" for c in chains)
        existing_sides = {
            (c.chain_type, c.side) for c in chains if c.chain_type in ("ARM", "LEG")
        }

        added = []
        skipped = []

        def _add_entry(chain_type, label_prefix, fields):
            item = chains.add()
            item.chain_type = chain_type
            if chain_type == "HEAD":
                _init_head_is_main(item, chains)
            item.label = _unique_bone_setting_label(chains, label_prefix)
            # Mesmo fix de RIG_OT_hytale_ik_chain_add -- pole_angle_preset_name
            # nasce coerente com o chain_type, em vez do default "ARM" cru.
            item.pole_angle_preset_name = chain_type
            for key, value in fields.items():
                setattr(item, key, value)
            armature.hytale_ik_chains_index = len(chains) - 1
            added.append(item.label)

        if "HEAD" in detected:
            if existing_head:
                skipped.append("Head")
            else:
                _add_entry("HEAD", "Head", detected["HEAD"])

        if "SPINE" in detected:
            if existing_spine:
                skipped.append("Spine")
            else:
                _add_entry("SPINE", "Spine", detected["SPINE"])

        side_suffix = {"LEFT": "L", "RIGHT": "R"}
        for chain_type, limb_label in (("ARM", "Arm"), ("LEG", "Leg")):
            for side in ("LEFT", "RIGHT"):
                key = (chain_type, side)
                if key not in detected:
                    continue
                if (chain_type, side) in existing_sides:
                    skipped.append(f"{limb_label} {side_suffix[side]}")
                    continue
                _add_entry(chain_type, f"{limb_label} {side_suffix[side]}", detected[key])

        _redraw_all_areas(context)

        if not added and not skipped:
            self.report(
                {"WARNING"},
                "Could not recognize any Head/Spine/Arm/Leg bones on this armature -- "
                "the bone names may not follow a supported naming convention.",
            )
            return {"CANCELLED"}

        msg_parts = []
        if added:
            msg_parts.append(f"added {', '.join(added)}")
        if skipped:
            msg_parts.append(f"already had {', '.join(skipped)} (skipped)")
        self.report({"INFO"}, "Auto-Detect Bone Settings: " + "; ".join(msg_parts) + ".")
        return {"FINISHED"}


def _ik_chain_load_defaults_props(lang):
    return {
        "preset": StringProperty(
            name="Preset",
            default="",
            description=tr("rigger.prop.ik_chain_load_defaults_preset", lang),
        ),
    }


@localized_props(_ik_chain_load_defaults_props)
class RIG_OT_hytale_ik_chain_load_defaults(Operator):
    """Preenche a lista com um template de cadeias de IK já calibradas
    (ver templates/rig/*.json, builtin + Documentos/Hyblend/templates/
    rig/*.json do usuário -- schema completo em templates/__init__.py).
    Substitui a lista atual. Pra adicionar um template de outra
    criatura/personagem, não precisa mexer em código: basta criar um
    .json novo em uma dessas pastas (e rodar "Reload Templates" se o
    Blender já estava aberto) -- a lista de opções abaixo é gerada
    automaticamente a partir dos templates descobertos.

    Selecionar "(none)" (_TEMPLATE_NONE) no dropdown e clicar Load LIMPA
    a lista de cadeias de IK e o rig template ativo (mesmo espírito do
    fix equivalente em RIG_OT_hytale_shape_template_apply) -- útil pra
    começar do zero sem nenhuma cadeia pré-calibrada, sem precisar
    remover uma por uma na mão. NÃO mexe no shape template ativo (esse é
    um picker independente, com o próprio "(none)" na box de Character
    Templates) nem em hytale_apply_ik_joint_fix (fica como já estava --
    não é algo que "pertença" a nenhum template, é ajustável direto)."""

    bl_idname = "armature.hytale_ik_chain_load_defaults"
    bl_label = "Load Hytale IK Chain Preset"
    description = tooltip("rigger.tooltip.ik_chain_load_defaults")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def execute(self, context):
        preset_name = self.preset or context.window_manager.hytale_rig_template_selected
        if not preset_name:
            self.report({"WARNING"}, "No rig template selected.")
            return {"CANCELLED"}
        if preset_name == _TEMPLATE_NONE:
            # Limpa a lista de cadeias e o rig template ativo em vez de
            # só avisar/cancelar. Não mexe em hytale_apply_ik_joint_fix
            # nem no shape template ativo (não "pertencem" a este picker).
            armature = context.active_object.data
            chain_count = len(armature.hytale_ik_chains)
            armature.hytale_ik_chains.clear()
            armature.hytale_active_rig_template = ""
            self.report(
                {"INFO"},
                f"Rig template cleared -- removed {chain_count} IK chain(s). "
                f"Add chains manually or load a template to start again.",
            )
            return {"FINISHED"}

        template = get_rig_template(preset_name)
        entries = template.get("ik_chains") if template else None
        if not entries:
            self.report({"WARNING"}, f"Unknown or empty rig template '{preset_name}'.")
            return {"CANCELLED"}

        armature = context.active_object.data
        chains = armature.hytale_ik_chains
        chains.clear()
        # Referencia a mesma tupla que Save usa -- só um lugar pra
        # atualizar quando um chain_type novo ganhar campos próprios.
        chain_fields = set(_IK_CHAIN_JSON_FIELDS)
        for entry in entries:
            item = chains.add()
            for key, value in entry.items():
                if key not in chain_fields:
                    continue  # campo desconhecido no .json (typo, versão futura) -- ignora em vez de quebrar
                # Compatibilidade com templates antigos/exportados de uma
                # versão anterior desta função, que ainda usam "ARM" como
                # valor cru de pole_angle_mode em vez do genérico "PRESET".
                if key == "pole_angle_mode" and value == "ARM":
                    value = "PRESET"
                setattr(item, key, value)
            if "chain_type" not in entry:
                # Migração pra templates salvos antes de chain_type
                # existir -- sem isso toda cadeia carregaria como "ARM"
                # (default do Enum). Best-effort no texto do label/root_bone.
                guess = (item.label or item.root_bone or "").lower().replace("ç", "c").replace("ã", "a")
                if "leg" in guess or "perna" in guess or "thigh" in guess:
                    item.chain_type = "LEG"
                elif "tail" in guess or "cauda" in guess:
                    item.chain_type = "CHAIN"

        # Normaliza head_is_main pra no máximo UMA entrada HEAD marcada
        # -- necessário pra templates salvos ANTES deste campo existir
        # (a chave "head_is_main" nem aparece no .json, então o loop
        # acima nunca dá setattr nela; toda entrada HEAD nova nasce no
        # default=True do campo, sem o update() de exclusividade
        # disparar porque não houve atribuição de verdade). Mantém a
        # primeira entrada HEAD da lista marcada, desmarca o resto --
        # mesmo critério de fallback de resolve_head_chain_item.
        seen_main_head = False
        for item in chains:
            if item.chain_type != "HEAD":
                continue
            if item.head_is_main and not seen_main_head:
                seen_main_head = True
            elif item.head_is_main:
                item.head_is_main = False

        # Amarra o toggle da correção de junta ao que o template pede --
        # continua ajustável manualmente depois.
        armature.hytale_apply_ik_joint_fix = bool(template.get("apply_ik_joint_fix", False))
        armature.hytale_active_rig_template = preset_name

        # Carrega junto o shape template de mesmo "nome de família", só
        # se existir de verdade -- senão fica em branco (cosmético).
        shape_name = template.get("shape_template", preset_name)
        if shape_name and get_shape_template(shape_name) is not None:
            armature.hytale_active_shape_template = shape_name
        else:
            armature.hytale_active_shape_template = ""
            if shape_name:
                self.report(
                    {"INFO"},
                    f"Rig template '{preset_name}' points to shape template '{shape_name}', which was not "
                    f"found -- bones will use default/generic custom shapes only.",
                )

        self.report({"INFO"}, f"Loaded rig template '{preset_name}' ({len(entries)} chain(s)).")
        return {"FINISHED"}


_CHAIN_TYPE_ICON = {
    "ROOT": "OBJECT_ORIGIN",
    "ARM": "CON_KINEMATIC", "LEG": "CON_KINEMATIC", "CHAIN": "PHYSICS",
    "HEAD": "USER", "SPINE": "BONE_DATA", "ATTACHMENTS": "LINKED",
    "TEXTURE_PICKER": "IMAGE_DATA",
}


class RIG_UL_hytale_ik_chains(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(
            item, "label", text="", emboss=False,
            icon=_CHAIN_TYPE_ICON.get(item.chain_type, "BONE_DATA"),
        )


def resolve_pole_angle_preset_degrees(rig_template, preset_name, side):
    """rig_template['pole_angle_presets'][preset_name][side] (graus), ou
    None se o rig_template for falsy ou o preset/side não estiver
    definido nele. Mesmo lookup que RIG_OT_hytale_generate_rig.
    _build_pose_constraints já fazia inline no branch PRESET -- ver ali."""
    if not rig_template:
        return None
    return rig_template.get("pole_angle_presets", {}).get(preset_name, {}).get(side)


def find_shared_pole_angle_preset_warnings(chains_data):
    """Pra cada nome de pole_angle_preset usado em modo PRESET por mais
    de um chain_type, devolve (nome, [chain_types ordenados]). Mesma
    checagem que RIG_OT_hytale_generate_rig._warn_shared_pole_angle_presets
    já fazia (ver docstring completa lá, sobre por que isso importa --
    pole_angle_presets é indexado só por nome + side, NÃO por chain_type,
    então braço e perna podem acabar compartilhando o mesmo preset por
    acidente). `chains_data` é qualquer lista de dict-like com as chaves
    "pole_angle_mode"/"pole_angle_preset_name"/"chain_type" -- tanto a
    lista rica que _build_edit_bones monta quanto uma lista simples
    montada direto de armature.hytale_ik_chains (ver
    RIG_OT_hytale_validate_rig) servem igual."""
    preset_chain_types = {}
    for data in chains_data:
        if data.get("pole_angle_mode") != "PRESET":
            continue
        name = data.get("pole_angle_preset_name")
        chain_type = data.get("chain_type")
        if not name or not chain_type:
            continue
        preset_chain_types.setdefault(name, set()).add(chain_type)
    return [(name, sorted(types)) for name, types in preset_chain_types.items() if len(types) > 1]


