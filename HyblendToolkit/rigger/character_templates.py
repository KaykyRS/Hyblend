"""Auto-Rigger -- Character Templates: save/apply/delete de Rig/Shape/Collection Template."""

import math

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ..common import is_active_armature
from ..templates import (
    delete_collection_template,
    delete_rig_template,
    delete_shape_template,
    get_collection_template,
    get_shape_template,
    list_collection_templates,
    list_rig_templates,
    list_shape_templates,
    save_collection_template,
    save_rig_template,
    save_shape_template,
)
from ..translations import localized_props, tooltip, tr

from .constants import (
    BONE_ROOT_MASTER,
    BONE_ROOT_PELVIS,
    BONE_ROOT_SPINE,
    HEAD_COLLECTION_ROOT,
    PROP_RIG_LAYER,
    PROP_WIDGET_SOURCE_ROLE,
    RESERVED_MAIN_COLLECTION_NAMES,
    ROOT_MASTER_PARENT,
    WGT_DEFAULT_FALLBACK,
    _TEMPLATE_NONE,
)

from .helpers import _find_bone_collection_anywhere, _iter_all_collections, _redraw_all_areas, ensure_bone_collection
from .widgets import _mesh_object_to_dict, _widget_mesh_differs_from_template, resolve_custom_shape_scale
from .bone_collections import SECTION_ROOT, ensure_default_bone_collections, ensure_default_bone_section_backfill, sync_bone_collection_order
from .bone_settings import _IK_CHAIN_JSON_FIELDS


def _shape_template_apply_props(lang):
    return {
        "template": StringProperty(
            name="Shape Template",
            default="",
            description=tr("rigger.prop.shape_template_apply_template", lang),
        ),
    }


@localized_props(_shape_template_apply_props)
class RIG_OT_hytale_shape_template_apply(Operator):
    """Troca só o template de custom shapes ativo, sem mexer na lista de
    cadeias de IK -- útil pra testar shapes diferentes em cima do mesmo
    rig. Não reaplica sozinho num rig já gerado -- rode "Create Rig" de
    novo depois.

    "(none)" limpa o template ativo (grava "") em vez de avisar/
    cancelar -- volta os shapes pro genérico da biblioteca."""

    bl_idname = "armature.hytale_shape_template_apply"
    bl_label = "Set Hytale Shape Template"
    description = tooltip("rigger.tooltip.shape_template_apply")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def execute(self, context):
        template_name = self.template or context.window_manager.hytale_shape_template_selected
        if not template_name:
            self.report({"WARNING"}, "No shape template selected.")
            return {"CANCELLED"}
        if template_name == _TEMPLATE_NONE:
            # Só grava a property vazia -- não mexe em bone/widget já
            # gerado. Quem aplica de verdade é "Create Rig" rodado
            # depois, que sem override cai no papel genérico.
            context.active_object.data.hytale_active_shape_template = ""
            self.report(
                {"INFO"},
                "Active shape template cleared -- run 'Create Rig' again to build shapes from scratch, "
                "without any per-character override.",
            )
            return {"FINISHED"}
        if get_shape_template(template_name) is None:
            self.report({"WARNING"}, f"Unknown shape template '{template_name}'.")
            return {"CANCELLED"}
        context.active_object.data.hytale_active_shape_template = template_name
        self.report(
            {"INFO"}, f"Active shape template set to '{template_name}' -- run 'Create Rig' again to apply.",
        )
        return {"FINISHED"}


# Seleção de template (Rig/Shape/Collection) usada pela box "Character
# Templates" do interface.py -- EnumProperty no WindowManager. Escolher
# um item só grava a seleção; "Apply"/"Delete" (interface.py) leem e agem.
# _template_source() abaixo só diz se o item selecionado pode ser
# deletado (source "user") ou não (builtin).


def _template_source(list_func, name):
    """"builtin"/"user" do template `name` segundo `list_func()`, ou
    None se `name` não corresponder a nenhum template conhecido."""
    for entry in list_func():
        if entry["name"] == name:
            return entry["source"]
    return None


# Compartilhado pelos 3 operadores "Delete Template" abaixo (rig/shape/
# collection): mesmo poll() e execute(), só variando qual EnumProperty
# do WindowManager ler, qual list_func/delete_func chamar e o nome do
# tipo pras mensagens -- extraído pra não divergir com o tempo.
def _poll_user_template(context, wm_attr, list_func):
    name = getattr(context.window_manager, wm_attr)
    return bool(name) and _template_source(list_func, name) == "user"


def _execute_template_delete(operator, context, wm_attr, delete_func, kind_label):
    name = getattr(context.window_manager, wm_attr)
    if not delete_func(name):
        operator.report({"WARNING"}, f"Could not delete {kind_label} template '{name}' (builtin, or already gone).")
        return {"CANCELLED"}
    operator.report({"INFO"}, f"Deleted {kind_label} template '{name}'.")
    return {"FINISHED"}


# Compartilhado pelos 3 operadores "Save Template" abaixo (rig/shape/
# collection): mesmo invoke()/draw() (dialog com um campo de nome, só
# variando qual custom property de "template ativo" ler pra sugerir um
# nome padrão) e mesma validação de nome vazio no início do execute().
def _invoke_template_save_dialog(operator, context, active_template_attr):
    operator.template_name = getattr(context.active_object.data, active_template_attr) or "New Character"
    return context.window_manager.invoke_props_dialog(operator)


def _draw_template_save_dialog(operator, layout):
    layout.prop(operator, "template_name")


def _require_template_name(operator):
    if not operator.template_name.strip():
        operator.report({"WARNING"}, "Template name cannot be empty.")
        return False
    return True


# Bones utilitários (não derivam de nenhuma cadeia IK) que também
# recebem custom shape e fazem sentido salvar num template de shapes.
_UTILITY_SHAPE_BONES = (BONE_ROOT_MASTER, BONE_ROOT_SPINE, BONE_ROOT_PELVIS, HEAD_COLLECTION_ROOT, ROOT_MASTER_PARENT)


class RIG_OT_hytale_rig_template_save(Operator):
    """Salva a lista atual de armature.hytale_ik_chains (mais o toggle
    de correção de junta) como um template novo em Documentos/Hyblend/
    templates/rig/<nome>.json. Os campos avançados (pole_angle_presets/
    ik_joint_x_overrides/widget_translation_x_overrides) saem vazios --
    edite o .json na mão depois se precisar."""

    bl_idname = "armature.hytale_rig_template_save"
    bl_label = "Save Rig Template"
    description = tooltip("rigger.tooltip.rig_template_save")
    bl_options = {"REGISTER"}

    template_name: StringProperty(name="Template Name", default="")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and len(obj.data.hytale_ik_chains) > 0

    def invoke(self, context, event):
        return _invoke_template_save_dialog(self, context, "hytale_active_rig_template")

    def draw(self, context):
        _draw_template_save_dialog(self, self.layout)

    def execute(self, context):
        if not _require_template_name(self):
            return {"CANCELLED"}

        armature = context.active_object.data
        entries = []
        for item in armature.hytale_ik_chains:
            entries.append({field: getattr(item, field) for field in _IK_CHAIN_JSON_FIELDS})

        data = {
            "description": f"User-saved rig template ({len(entries)} IK chain(s)).",
            "shape_template": armature.hytale_active_shape_template or self.template_name,
            "ik_chains": entries,
            "pole_angle_presets": {},
            "apply_ik_joint_fix": bool(getattr(armature, "hytale_apply_ik_joint_fix", False)),
            "ik_joint_x_overrides": {},
            "widget_translation_x_overrides": {},
        }
        path = save_rig_template(self.template_name, data)
        armature.hytale_active_rig_template = self.template_name
        self.report({"INFO"}, f"Saved rig template '{self.template_name}' to '{path}'.")
        return {"FINISHED"}


class RIG_OT_hytale_rig_template_delete(Operator):
    """Apaga do disco o rig template selecionado -- só templates do
    usuário (source == "user"); um builtin nunca aparece deletável."""

    bl_idname = "armature.hytale_rig_template_delete"
    bl_label = "Delete Rig Template"
    description = tooltip("rigger.tooltip.rig_template_delete")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_user_template(context, "hytale_rig_template_selected", list_rig_templates)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        return _execute_template_delete(self, context, "hytale_rig_template_selected", delete_rig_template, "rig")


class RIG_OT_hytale_shape_template_save(Operator):
    """Salva o custom shape atual (translation/rotation/scale/widget) de
    todo bone _CTRL/_CTRL-IK/utilitário como um template novo em
    Documentos/Hyblend/templates/shapes/<nome>.json.

    Embutir malha: cada bone genuinamente customizado (ver
    _widget_mesh_differs_from_template) também ganha uma chave "mesh"
    com a geometria em si -- assim a edição sobrevive a "Delete All",
    a reimportar em outro .blend, e dá pra compartilhar o template com
    a edição junto. Bones nunca customizados não ganham "mesh" --
    continuam recebendo remodelagens futuras de hytale_widgets.blend
    automaticamente."""

    bl_idname = "armature.hytale_shape_template_save"
    bl_label = "Save Shape Template"
    description = tooltip("rigger.tooltip.shape_template_save")
    bl_options = {"REGISTER"}

    template_name: StringProperty(name="Template Name", default="")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and obj.pose is not None

    def invoke(self, context, event):
        return _invoke_template_save_dialog(self, context, "hytale_active_shape_template")

    def draw(self, context):
        _draw_template_save_dialog(self, self.layout)

    def execute(self, context):
        if not _require_template_name(self):
            return {"CANCELLED"}

        obj = context.active_object
        bones = {}
        for pb in obj.pose.bones:
            layer = pb.bone.get(PROP_RIG_LAYER)
            if layer not in ("CTRL", "CTRL-IK") and pb.name not in _UTILITY_SHAPE_BONES:
                continue
            if pb.custom_shape is None:
                continue
            entry = {
                "translation": list(pb.custom_shape_translation),
                "rotation_deg": [math.degrees(v) for v in pb.custom_shape_rotation_euler],
                # resolve_custom_shape_scale() em vez de custom_shape_scale_xyz
                # direto -- o driver de FK/IK zera esse eixo quando o
                # modo oposto está ativo, senão salvar com IK ativo
                # gravaria 0 pro FK (e vice-versa).
                "scale": list(resolve_custom_shape_scale(pb)),
            }
            if pb.custom_shape.name not in (WGT_DEFAULT_FALLBACK,):
                entry["widget"] = pb.custom_shape.name

            # Só embute a geometria quando o bone estiver genuinamente
            # customizado. PROP_WIDGET_SOURCE_ROLE ausente ("Use
            # Selected Object as Widget", ou .blend antigo) conta como
            # "sem proveniência conhecida" e sempre embute -- não tem
            # template confiável pra comparar contra.
            if pb.custom_shape.type == "MESH":
                source_role = pb.custom_shape.get(PROP_WIDGET_SOURCE_ROLE)
                if source_role:
                    embed_mesh = _widget_mesh_differs_from_template(pb.custom_shape, source_role, obj.name)
                else:
                    embed_mesh = True
                if embed_mesh:
                    entry["mesh"] = _mesh_object_to_dict(pb.custom_shape.data)

            bones[pb.name] = entry

        if not bones:
            self.report({"WARNING"}, "No CTRL/CTRL-IK bone with a custom shape found -- nothing to save.")
            return {"CANCELLED"}

        data = {
            "description": f"User-saved shape template ({len(bones)} bone(s)).",
            "bones": bones,
        }
        path = save_shape_template(self.template_name, data)
        obj.data.hytale_active_shape_template = self.template_name
        self.report({"INFO"}, f"Saved shape template '{self.template_name}' ({len(bones)} bone(s)) to '{path}'.")
        return {"FINISHED"}


class RIG_OT_hytale_shape_template_delete(Operator):
    """Mesma ideia de RIG_OT_hytale_rig_template_delete, pra shapes/
    <nome>.json -- só templates do usuário, nunca builtin."""

    bl_idname = "armature.hytale_shape_template_delete"
    bl_label = "Delete Shape Template"
    description = tooltip("rigger.tooltip.shape_template_delete")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_user_template(context, "hytale_shape_template_selected", list_shape_templates)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        return _execute_template_delete(self, context, "hytale_shape_template_selected", delete_shape_template, "shape")


# --- Collection Templates ---
# Mesmo espírito de rig/shape, mas salva a organização de bone
# collections (nome + hierarquia + membros). O usuário cria as
# collections pelo painel nativo do Blender; Save tira uma "foto" de
# tudo, menos o que RESERVED_MAIN_COLLECTION_NAMES já cobre (gerado
# sozinho por "Create Rig").


def _apply_collection_template_entries(armature, edit_bones, entries, report):
    """Recria (idempotente) cada collection descrita em `entries` (lista
    de {"name", "parent", "bones"}) e reassina os bones listados.
    Resolve o parent em múltiplas passadas -- a API do Blender só deixa
    criar uma bone collection já com o pai definido, não dá pra
    reparentar depois. Uma entry cujo parent nunca resolve vira
    collection de nível raiz, com aviso -- não derruba a operação inteira."""
    created = {}
    remaining = list(entries)
    progress = True
    while remaining and progress:
        progress = False
        still = []
        for entry in remaining:
            name = entry.get("name")
            if not name:
                continue
            parent_name = entry.get("parent")
            parent_coll = None
            if parent_name:
                parent_coll = created.get(parent_name) or _find_bone_collection_anywhere(armature, parent_name)
                if parent_coll is None:
                    still.append(entry)
                    continue
            created[name] = ensure_bone_collection(armature, name, parent=parent_coll)
            progress = True
        remaining = still

    for entry in remaining:
        name = entry.get("name")
        if not name:
            continue
        created[name] = ensure_bone_collection(armature, name, parent=None)
        report(
            {"WARNING"},
            f"Collection template: parent '{entry.get('parent')}' not found for '{name}' -- created at top level.",
        )

    assigned = 0
    missing_bones = set()
    for entry in entries:
        coll = created.get(entry.get("name"))
        if coll is None:
            continue
        for bone_name in entry.get("bones", []):
            bone = edit_bones.get(bone_name)
            if bone is None:
                missing_bones.add(bone_name)
                continue
            coll.assign(bone)
            assigned += 1
    return assigned, missing_bones


def _ensure_collection_settings_entry(armature, name, entry_type, report):
    """Acha (por nome, na lista inteira) ou cria uma entrada nova em
    Collection Settings do tipo `entry_type` pedido.

    Se já existir uma entrada com esse nome mas do outro tipo (conflito
    de verdade), não sobrescreve o tipo (confundiria tudo que já
    depende dela) -- avisa e devolve None; o chamador pula essa
    entrada, sem derrubar o resto do Apply."""
    for item in armature.hytale_bone_collections:
        if item.name == name:
            if item.entry_type != entry_type:
                report(
                    {"WARNING"},
                    f"Collection template: '{name}' already exists as a {item.entry_type.title()} in "
                    f"Collection Settings on this armature -- skipped its {entry_type.title()} settings "
                    f"from the template.",
                )
                return None
            return item
    item = armature.hytale_bone_collections.add()
    item.name = name
    item.entry_type = entry_type
    return item


def _apply_collection_settings_entries(armature, collection_entries, section_entries, report):
    """Aplica a parte "Collection Settings" (entry_type/parent visual/
    show_in_animation_tab/row/column) de um Collection Template --
    metade que _apply_collection_template_entries nunca toca.

    1. Recria/atualiza cada Section de `section_entries` -- sem
       dependência de ordem (uma Section é só uma entrada solta
       referenciando outra pelo nome, não uma bone collection real).
    2. Pra cada entrada de `collection_entries` com pelo menos um campo
       opcional "section"/"show_in_animation_tab"/"row"/"column" (só
       embutidos quando a collection também estava cadastrada em
       Collection Settings no save), cria/atualiza a entrada
       correspondente. Uma entry sem esses campos não mexe em nada.

    Idempotente/aditivo: nunca remove uma entrada existente. Devolve
    quantas entradas foram criadas/atualizadas."""
    ensure_default_bone_collections(armature)
    ensure_default_bone_section_backfill(armature)

    touched = 0
    for entry in section_entries:
        name = entry.get("name")
        if not name:
            continue
        item = _ensure_collection_settings_entry(armature, name, "SECTION", report)
        if item is None:
            continue
        try:
            item.parent = entry.get("parent") or SECTION_ROOT
            item.row = int(entry.get("row", 0))
        except (TypeError, ValueError):
            pass  # campo corrompido num .json editado à mão -- não derruba o Apply
        touched += 1

    settings_fields = ("section", "show_in_animation_tab", "row", "column")
    for entry in collection_entries:
        name = entry.get("name")
        if not name or not any(field in entry for field in settings_fields):
            continue
        item = _ensure_collection_settings_entry(armature, name, "COLLECTION", report)
        if item is None:
            continue
        try:
            if "section" in entry:
                item.parent = entry.get("section") or SECTION_ROOT
            if "show_in_animation_tab" in entry:
                item.show_in_animation_tab = bool(entry.get("show_in_animation_tab", True))
            if "row" in entry:
                item.row = int(entry.get("row", 0))
            if "column" in entry:
                item.column = int(entry.get("column", 0))
        except (TypeError, ValueError):
            pass
        touched += 1

    return touched


class RIG_OT_hytale_collection_template_save(Operator):
    """Salva todas as bone collections do Armature ativo que não
    pertencem ao conjunto que "Create Rig" já gerencia sozinho (ver
    RESERVED_MAIN_COLLECTION_NAMES) como um template novo. Funciona em
    Object/Pose Mode -- não precisa de Edit Mode só pra salvar.

    Também salva a metade "Collection Settings": cada Section vira uma
    entrada em "sections"; pra cada bone collection real que também
    estiver cadastrada lá, os campos "section"/"show_in_animation_tab"/
    "row"/"column" são embutidos na entrada dela em "collections"."""

    bl_idname = "armature.hytale_collection_template_save"
    bl_label = "Save Collection Template"
    description = tooltip("rigger.tooltip.collection_template_save")
    bl_options = {"REGISTER"}

    template_name: StringProperty(name="Template Name", default="")

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def invoke(self, context, event):
        return _invoke_template_save_dialog(self, context, "hytale_active_collection_template")

    def draw(self, context):
        _draw_template_save_dialog(self, self.layout)

    def execute(self, context):
        if not _require_template_name(self):
            return {"CANCELLED"}

        armature = context.active_object.data
        custom_colls = [c for c in _iter_all_collections(armature) if c.name not in RESERVED_MAIN_COLLECTION_NAMES]
        section_settings = [
            item for item in armature.hytale_bone_collections if item.entry_type == "SECTION" and item.name
        ]
        if not custom_colls and not section_settings:
            self.report(
                {"WARNING"},
                "No custom bone collection or section found (only the auto-generated ones exist) -- nothing "
                "to save. Create one first in the Armature Data Properties > Bone Collections panel, or add a "
                "Section in Collection Settings.",
            )
            return {"CANCELLED"}

        custom_names = {c.name for c in custom_colls}
        bones_by_coll = {c.name: [] for c in custom_colls}
        for bone in armature.bones:
            for coll in bone.collections:
                if coll.name in custom_names:
                    bones_by_coll[coll.name].append(bone.name)

        # Collection Settings pode não ter entrada pra toda bone
        # collection real -- índice só entre entry_type == "COLLECTION"
        # (defensivo contra colisão de nome com uma Section).
        settings_by_name = {
            item.name: item for item in armature.hytale_bone_collections if item.entry_type == "COLLECTION"
        }

        entries = []
        for coll in custom_colls:
            entry = {
                "name": coll.name,
                "parent": coll.parent.name if coll.parent is not None else None,
                "bones": bones_by_coll[coll.name],
            }
            settings_item = settings_by_name.get(coll.name)
            if settings_item is not None:
                entry["section"] = settings_item.parent
                entry["show_in_animation_tab"] = settings_item.show_in_animation_tab
                entry["row"] = settings_item.row
                entry["column"] = settings_item.column
            entries.append(entry)

        section_entries = [
            {"name": item.name, "parent": item.parent, "row": item.row} for item in section_settings
        ]

        data = {
            "description": (
                f"User-saved collection template ({len(entries)} collection(s), "
                f"{len(section_entries)} section(s))."
            ),
            "collections": entries,
            "sections": section_entries,
        }
        path = save_collection_template(self.template_name, data)
        armature.hytale_active_collection_template = self.template_name
        self.report(
            {"INFO"},
            f"Saved collection template '{self.template_name}' ({len(entries)} collection(s), "
            f"{len(section_entries)} section(s)) to '{path}'.",
        )
        return {"FINISHED"}


def _collection_template_apply_props(lang):
    return {
        "template_name": StringProperty(
            name="Template",
            default="",
            description=tr("rigger.prop.collection_template_apply_template_name", lang),
        ),
    }


@localized_props(_collection_template_apply_props)
class RIG_OT_hytale_collection_template_apply(Operator):
    """Aplica o template de collections selecionado: cria (ou
    reaproveita) cada bone collection descrita e reassina os bones
    listados -- aditivo, nunca remove uma collection nem desassocia um
    bone que já estava lá por outro motivo. Entra e sai do Edit Mode
    sozinho (precisa dele pra chamar coll.assign()).

    Também aplica a metade "Collection Settings" do template, depois
    de sair do Edit Mode, e força um redraw/sync.

    "(none)" limpa só o ponteiro (hytale_active_collection_template =
    "") -- como aplicar é aditivo por natureza, não existe operação
    inversa segura; use a lista "Bone Collections" (Remove) pra
    remover collections/Sections de verdade."""

    bl_idname = "armature.hytale_collection_template_apply"
    bl_label = "Apply Collection Template"
    description = tooltip("rigger.tooltip.collection_template_apply")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def execute(self, context):
        name = self.template_name or context.window_manager.hytale_collection_template_selected
        if not name:
            self.report({"WARNING"}, "No collection template selected.")
            return {"CANCELLED"}
        if name == _TEMPLATE_NONE:
            context.active_object.data.hytale_active_collection_template = ""
            self.report(
                {"INFO"},
                "Active collection template cleared -- existing bone collections/assignments were not "
                "removed (use the Bone Collections list above to remove them manually).",
            )
            return {"FINISHED"}

        data = get_collection_template(name)
        entries = data.get("collections") if data else None
        if not entries:
            self.report({"WARNING"}, f"Unknown or empty collection template '{name}'.")
            return {"CANCELLED"}
        section_entries = data.get("sections", [])

        obj = context.active_object
        armature = obj.data
        prev_mode = obj.mode
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            assigned, missing_bones = _apply_collection_template_entries(
                armature, armature.edit_bones, entries, self.report,
            )
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
            if prev_mode != "OBJECT":
                bpy.ops.object.mode_set(mode=prev_mode)

        settings_touched = _apply_collection_settings_entries(armature, entries, section_entries, self.report)
        sync_bone_collection_order(armature)  # reflete a ordem/seção no painel nativo na hora
        _redraw_all_areas(context)

        armature.hytale_active_collection_template = name
        msg = f"Applied collection template '{name}': {assigned} bone assignment(s) across {len(entries)} collection(s)."
        if settings_touched:
            msg += (
                f" Collection Settings updated for {settings_touched} entr"
                f"{'y' if settings_touched == 1 else 'ies'} ({len(section_entries)} section(s))."
            )
        if missing_bones:
            msg += f" {len(missing_bones)} bone(s) not found on this armature (skipped)."
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class RIG_OT_hytale_collection_template_delete(Operator):
    """Mesma ideia de RIG_OT_hytale_rig_template_delete, pra collections/
    <nome>.json -- só templates do usuário, nunca builtin."""

    bl_idname = "armature.hytale_collection_template_delete"
    bl_label = "Delete Collection Template"
    description = tooltip("rigger.tooltip.collection_template_delete")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_user_template(context, "hytale_collection_template_selected", list_collection_templates)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        return _execute_template_delete(
            self, context, "hytale_collection_template_selected", delete_collection_template, "collection"
        )
