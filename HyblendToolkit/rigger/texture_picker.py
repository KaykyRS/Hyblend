"""Auto-Rigger -- Texture Picker: picker de UV por atlas de textura (múltiplas instâncias por Armature)."""

import math

import bmesh
import bpy
from bpy.types import Operator
from mathutils import Euler, Matrix

from ..common import is_active_armature
from ..translations import tooltip

from .constants import (
    BONE_COLOR_UI_CURSOR,
    BONE_COLOR_UI_ROOT,
    BONE_TEXTURE_PICKER_CURSOR_PREFIX,
    BONE_TEXTURE_PICKER_CURSOR_SUFFIX,
    BONE_UI_ROOT_PREFIX,
    COLL_MAIN,
    COLL_MAIN_TEXTURE_PICKER,
    CONSTRAINT_TEXTURE_PICKER_LIMIT,
    PROP_RIG_LAYER,
    PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL,
    SUFFIX_CTRL,
    TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT,
    TEXTURE_PICKER_MAPPING_NODE_NAME,
    TEXTURE_PICKER_MATERIAL_SUFFIX,
    TEXTURE_PICKER_PLANE_SUFFIX,
    TEXTURE_PICKER_UI_OFFSET_X,
    TEXTURE_PICKER_UI_OFFSET_Y,
    TEXTURE_PICKER_UVMAP_NODE_NAME,
    WGT_TEXTURE_PICKER_CURSOR,
    WGT_UI_ROOT,
)

from .helpers import control_name, create_bone_like, ensure_bone_collection
from .widgets import _ensure_bone_widget_copy, ensure_widget_objects, get_or_create_widgets_collection
from .bone_collections import COLLECTION_OVERRIDE_AUTO, resolve_collection_override_target


def _texture_picker_ui_root_name(texture_picker_bone_name):
    """Nome do bone root.ui desta instância, derivado do bone alvo (único por natureza)."""
    return f"{BONE_UI_ROOT_PREFIX}{texture_picker_bone_name}"


def _texture_picker_cursor_name(texture_picker_bone_name):
    """Nome do bone cursor (o que o usuário arrasta) desta instância."""
    return f"{BONE_TEXTURE_PICKER_CURSOR_PREFIX}{texture_picker_bone_name}{BONE_TEXTURE_PICKER_CURSOR_SUFFIX}"


def _find_texture_picker_mesh_object(armature_obj, texture_picker_bone_name):
    """Acha o Object de malha alvo pelo Vertex Group (nomeado igual ao
    bone original) + modifier Armature apontando pra este Armature --
    não pelo nome do objeto, que pode ter sido renomeado/duplicado."""
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if texture_picker_bone_name not in obj.vertex_groups:
            continue
        if any(mod.type == "ARMATURE" and mod.object == armature_obj for mod in obj.modifiers):
            return obj
    return None


def _find_image_texture_node(material):
    """Primeiro node Image Texture com imagem carregada -- prioriza o
    que estiver ligado ao Base Color do Principled BSDF."""
    if material is None or material.node_tree is None:
        return None
    nodes = material.node_tree.nodes
    bsdf = nodes.get("Principled BSDF") or next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is not None and "Base Color" in bsdf.inputs and bsdf.inputs["Base Color"].is_linked:
        from_node = bsdf.inputs["Base Color"].links[0].from_node
        if from_node.type == "TEX_IMAGE" and from_node.image is not None:
            return from_node
    return next((n for n in nodes if n.type == "TEX_IMAGE" and n.image is not None), None)


def _ensure_texture_picker_material_uv_offset(mesh_obj, label):
    """Garante 'UV Map -> Mapping -> Image Texture' no material real do
    alvo, devolve o node Mapping pronto pra receber os drivers.

    Se o material for compartilhado (users > 1) e ainda não for uma
    cópia rastreada nossa, copia antes de mexer -- senão o offset de UV
    vazaria pra outros meshes usando o mesmo material. A cópia recebe
    nome legível ("<original>_<Label>") e uma custom property
    (PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL) marcando o material de
    origem, pra "Remove" saber restaurar depois.

    A condição de cópia exige "users>1 E ainda não é cópia nossa" --
    sem o segundo check, um Companion Bone compartilhando a MESMA cópia
    do principal (users>1 de propósito) faria esta função copiar de
    novo a cada "Create Texture Picker", gerando ".001"/".002" sem fim.
    Também procura por uma cópia já existente com o nome exato antes de
    copiar de novo -- evita colisão quando um Companion cujo material
    "resultaria" no mesmo nome de cópia já existente (bug real
    corrigido: gerava ".001" pra cada Companion).

    Devolve (mapping_node, image) ou (None, None)."""
    if not mesh_obj.data.materials or mesh_obj.data.materials[0] is None:
        return None, None
    material = mesh_obj.data.materials[0]
    if material.users > 1 and PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL not in material.keys():
        original_name = material.name
        copy_name = f"{original_name}_{label}"
        existing_copy = bpy.data.materials.get(copy_name)
        if existing_copy is not None and existing_copy.get(PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL) == original_name:
            material = existing_copy
        else:
            material = material.copy()
            material.name = copy_name
            material[PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL] = original_name
        mesh_obj.data.materials[0] = material

    tex_node = _find_image_texture_node(material)
    if tex_node is None:
        return None, None
    image = tex_node.image

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    mapping_node = nodes.get(TEXTURE_PICKER_MAPPING_NODE_NAME)
    if mapping_node is None:
        mapping_node = nodes.new("ShaderNodeMapping")
        mapping_node.name = TEXTURE_PICKER_MAPPING_NODE_NAME
        mapping_node.label = "Hytale Texture Picker Offset"
    mapping_node.location = (tex_node.location.x - 300, tex_node.location.y)

    uv_node = nodes.get(TEXTURE_PICKER_UVMAP_NODE_NAME)
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = TEXTURE_PICKER_UVMAP_NODE_NAME
    uv_node.location = (mapping_node.location.x - 200, mapping_node.location.y)
    if mesh_obj.data.uv_layers:
        uv_node.uv_map = mesh_obj.data.uv_layers[0].name

    links.new(uv_node.outputs["UV"], mapping_node.inputs["Vector"])
    links.new(mapping_node.outputs["Vector"], tex_node.inputs["Vector"])

    return mapping_node, image


def _apply_texture_picker_driver(mapping_node, axis_index, armature_obj, step, px_per_step, atlas_size_px, cursor_bone_name):
    """Driver de Mapping.inputs['Location'][axis_index] -- mesma fórmula
    que exporter.py usa em sample_uv_offset_px (round(loc/step)*px),
    dividindo por atlas_size_px pra virar fração de UV em vez de pixel
    cru. Precisa bater exatamente com o exporter (não usar floor())."""
    socket = mapping_node.inputs["Location"]
    socket.driver_remove("default_value", axis_index)
    fcurve = socket.driver_add("default_value", axis_index)
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    driver.expression = f"round(loc / {step}) * {px_per_step} / {atlas_size_px}"
    for existing_var in list(driver.variables):
        driver.variables.remove(existing_var)
    var = driver.variables.new()
    var.name = "loc"
    var.type = "SINGLE_PROP"
    target = var.targets[0]
    target.id_type = "OBJECT"
    target.id = armature_obj
    target.data_path = f'pose.bones["{cursor_bone_name}"].location[{axis_index}]'


def _apply_texture_picker_to_companion(
    armature_obj, companion_bone_name, grid, step_x, step_y, primary_material, cursor_bone_name, label
):
    """Aplica o mesmo tratamento de material do Target Bone principal a
    uma malha Companion (ex. metade R de uma boca dividida em L/R).
    Reaproveita grid/step já calculados pro principal -- os dois lados
    precisam concordar no mesmo grid pra se mexerem em sincronia.

    Se o material do companion for o mesmo que o principal tinha ANTES
    de copiar, reaproveita a cópia já resolvida (zero cópia nova, zero
    driver duplicado -- compartilhar o datablock já basta pros dois se
    mexerem juntos). Só entra em cópia própria se a textura for
    genuinamente diferente.

    Devolve (True, None) ou (False, mensagem não-fatal)."""
    mesh_obj = _find_texture_picker_mesh_object(armature_obj, companion_bone_name)
    if mesh_obj is None:
        return False, (
            f"companion bone '{companion_bone_name}': no mesh found with a matching vertex group + "
            f"Armature modifier -- is it imported and attached?"
        )
    if not mesh_obj.data.materials or mesh_obj.data.materials[0] is None:
        return False, f"companion bone '{companion_bone_name}': '{mesh_obj.name}' has no material."

    current_material = mesh_obj.data.materials[0]
    if current_material is primary_material:
        return True, None  # já resolvido numa passada anterior

    primary_original_name = primary_material.get(PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL, primary_material.name)
    if current_material.name == primary_original_name:
        mesh_obj.data.materials[0] = primary_material
        return True, None

    mapping_node, image = _ensure_texture_picker_material_uv_offset(
        mesh_obj, f"{label}_{companion_bone_name}"
    )
    if mapping_node is None or image is None:
        return False, f"companion bone '{companion_bone_name}': '{mesh_obj.name}' has no Image Texture material."
    if tuple(image.size) != (grid["atlas_w"], grid["atlas_h"]):
        # step_x/step_y foram calculados em pixels/proporção da imagem
        # do principal -- aplicar numa imagem de tamanho diferente sem
        # reconverter daria offset errado.
        return False, (
            f"companion bone '{companion_bone_name}': texture '{image.name}' is "
            f"{image.size[0]}x{image.size[1]}px, but Target Bone's texture is "
            f"{grid['atlas_w']}x{grid['atlas_h']}px -- skipping (companion must use the same texture/size)."
        )
    _apply_texture_picker_driver(mapping_node, 0, armature_obj, step_x, grid["cell_w_px"], grid["atlas_w"], cursor_bone_name)
    _apply_texture_picker_driver(mapping_node, 1, armature_obj, step_y, -grid["cell_h_px"], grid["atlas_h"], cursor_bone_name)
    return True, None


def _strip_texture_picker_material_nodes(material):
    """Remove os nodes Mapping/UV Map injetados, relincando o Image
    Texture direto no Base Color -- caso "material editado direto, sem
    cópia" (users==1 desde o início). Quando houve cópia,
    _revert_texture_picker_material_uv_offset descarta a cópia inteira
    em vez de desfazer os nodes. Devolve True se algo foi removido."""
    if material is None or material.node_tree is None:
        return False
    did_something = False
    nodes = material.node_tree.nodes
    mapping_node = nodes.get(TEXTURE_PICKER_MAPPING_NODE_NAME)
    uv_node = nodes.get(TEXTURE_PICKER_UVMAP_NODE_NAME)
    if mapping_node is not None:
        tex_node = _find_image_texture_node(material)
        if tex_node is not None:
            bsdf = nodes.get("Principled BSDF") or next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf is not None:
                material.node_tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        nodes.remove(mapping_node)
        did_something = True
    if uv_node is not None:
        nodes.remove(uv_node)
        did_something = True
    return did_something


def _revert_texture_picker_material_uv_offset(mesh_obj):
    """Contrário de _ensure_texture_picker_material_uv_offset. Se o
    material atual é uma cópia rastreada (PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL),
    restaura o slot pro original e apaga a cópia se ficar com 0 users.
    Senão, só desfaz os nodes. Seguro chamar em qualquer malha, mesmo
    que nunca tenha passado por esse sistema (no-op). Devolve True se
    algo foi revertido."""
    if not mesh_obj.data.materials:
        return False
    material = mesh_obj.data.materials[0]
    if material is None:
        return False

    original_name = material.get(PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL)
    if original_name:
        original_material = bpy.data.materials.get(original_name)
        if original_material is not None:
            mesh_obj.data.materials[0] = original_material
            if material.users == 0:
                bpy.data.materials.remove(material, do_unlink=True)
            return True
        # Original sumiu -- remove a property órfã e cai pro caso "só desfaz os nodes".
        del material[PROP_TEXTURE_PICKER_MATERIAL_ORIGINAL]

    return _strip_texture_picker_material_nodes(material)


def _apply_texture_picker_visibility_driver(plane_obj, armature_obj, collection_name):
    """Driver em hide_viewport do plane de referência, ligado à
    visibilidade da bone collection real que root.ui/cursor usam --
    desativar a collection (via "Bone Collections" na aba Animation)
    esconde o plane junto. hide_viewport é o inverso de is_visible."""
    plane_obj.driver_remove("hide_viewport")
    fcurve = plane_obj.driver_add("hide_viewport")
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    driver.expression = "not texture_picker_coll_visible"
    for existing_var in list(driver.variables):
        driver.variables.remove(existing_var)
    var = driver.variables.new()
    var.name = "texture_picker_coll_visible"
    var.type = "SINGLE_PROP"
    target = var.targets[0]
    target.id_type = "ARMATURE"
    target.id = armature_obj.data
    target.data_path = f'collections_all["{collection_name}"].is_visible'


def _get_texture_picker_mesh_rest_uv(mesh_obj):
    """UV "de repouso" que a malha alvo já tinha antes de qualquer
    Mapping node (a que o .blockymodel/.bbmodel trouxe, geralmente a
    célula de referência do atlas) -- média de todos os loops de UV.
    (0.0, 1.0) [canto superior esquerdo] se a malha não tiver UV."""
    if not mesh_obj.data.uv_layers:
        return (0.0, 1.0)
    uv_layer = mesh_obj.data.uv_layers.active or mesh_obj.data.uv_layers[0]
    coords = [loop_uv.uv for loop_uv in uv_layer.data]
    if not coords:
        return (0.0, 1.0)
    return (sum(c.x for c in coords) / len(coords), sum(c.y for c in coords) / len(coords))


def _build_texture_picker_plane_mesh(mesh_name, plane_w, plane_h, rest_uv):
    """Plane de referência: um quad, UV 0..1 cobrindo o atlas inteiro
    sem offset (mapa visual pra escolher a célula). A origem (0,0,0) da
    malha fica exatamente em cima de `rest_uv` (a célula que a malha
    real já mostra em repouso), não no canto cru da imagem -- é o que
    faz Location=(0,0) do cursor coincidir visualmente com o ponto
    certo pra qualquer personagem, sem ajuste manual (o canto cru só
    bateria por coincidência).

    Plano construído no eixo local X/Z do bone (Y perpendicular à
    tela) -- eixo mais provável pra um plane "de frente" nesta
    convenção, mas pode precisar de ajuste conforme o personagem."""
    rest_u, rest_v = rest_uv
    origin_x = rest_u * plane_w
    origin_z = -(1.0 - rest_v) * plane_h
    mesh = bpy.data.meshes.new(mesh_name)
    bm = bmesh.new()
    v00 = bm.verts.new((0.0 - origin_x, 0.0, 0.0 - origin_z))
    v10 = bm.verts.new((plane_w - origin_x, 0.0, 0.0 - origin_z))
    v11 = bm.verts.new((plane_w - origin_x, 0.0, -plane_h - origin_z))
    v01 = bm.verts.new((0.0 - origin_x, 0.0, -plane_h - origin_z))
    face = bm.faces.new((v00, v10, v11, v01))
    uv_layer = bm.loops.layers.uv.new()
    uv_by_vert = {v00: (0.0, 1.0), v10: (1.0, 1.0), v11: (1.0, 0.0), v01: (0.0, 0.0)}
    for loop in face.loops:
        loop[uv_layer].uv = uv_by_vert[loop.vert]
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _ensure_texture_picker_reference_material(material_name, image):
    """Material simples (sem Mapping/drivers) só pra mostrar o atlas
    inteiro no plane de referência. Idempotente: reaproveita o
    material se já existir com esse nome."""
    material = bpy.data.materials.get(material_name)
    if material is not None:
        tex_node = _find_image_texture_node(material)
        if tex_node is not None:
            tex_node.image = image
        return material

    material = bpy.data.materials.new(name=material_name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    bsdf = nodes.get("Principled BSDF") or next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    tex_node = nodes.new("ShaderNodeTexImage")
    tex_node.image = image
    tex_node.interpolation = "Closest"
    tex_node.location = (bsdf.location.x - 300 if bsdf else -300, bsdf.location.y if bsdf else 0)
    if bsdf is not None:
        links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        if "Alpha" in bsdf.inputs:
            links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 1.0
    if hasattr(material, "blend_method"):
        material.blend_method = "HASHED"
    if hasattr(material, "shadow_method"):
        material.shadow_method = "HASHED"
    return material


def _build_texture_picker(context, armature_obj, item):
    """Núcleo de "Create Texture Picker": lê o grid da textura (Manual
    Grid, único caminho -- detecção automática por transparência foi
    removida por ser frágil), cria root.ui/cursor desta instância, o
    plane de referência, e injeta o driver de UV no material real do
    alvo. Idempotente. Precisa ser chamado em Object Mode."""
    texture_picker_bone_name = (item.texture_picker_bone or "").strip()
    if not texture_picker_bone_name:
        return False, "No Target Bone set on this entry."
    ui_root_name = _texture_picker_ui_root_name(texture_picker_bone_name)
    cursor_name = _texture_picker_cursor_name(texture_picker_bone_name)
    # O bone que o root.ui é parentado pode ser diferente do bone que
    # tem a malha/textura -- vazio cai pro texture_picker_bone_name.
    ui_parent_bone_name = (item.texture_picker_ui_parent_bone or "").strip() or texture_picker_bone_name
    texture_picker_ctrl_name = control_name(armature_obj.data, ui_parent_bone_name, SUFFIX_CTRL)
    if armature_obj.data.bones.get(texture_picker_ctrl_name) is None:
        return False, f"'{texture_picker_ctrl_name}' not found -- run 'Create Rig' first."

    mesh_obj = _find_texture_picker_mesh_object(armature_obj, texture_picker_bone_name)
    if mesh_obj is None:
        return False, (
            f"No mesh found with a '{texture_picker_bone_name}' vertex group + Armature modifier on this "
            f"Armature -- is the attachment/mesh imported and attached?"
        )

    texture_picker_label = (item.label or "").strip() or texture_picker_bone_name
    mapping_node, image = _ensure_texture_picker_material_uv_offset(mesh_obj, texture_picker_label)
    if mapping_node is None or image is None:
        return False, f"'{mesh_obj.name}' has no material with an Image Texture -- nothing to drive."
    primary_material = mesh_obj.data.materials[0]

    grid = {
        "atlas_w": image.size[0], "atlas_h": image.size[1],
        "num_cols": item.texture_picker_grid_cols, "num_rows": item.texture_picker_grid_rows,
        "cell_w_px": item.texture_picker_grid_cell_width, "cell_h_px": item.texture_picker_grid_cell_height,
    }

    plane_w = item.texture_picker_plane_scale
    plane_h = plane_w * (grid["atlas_h"] / grid["atlas_w"])
    # O passo do cursor usa cell_w_px/cell_h_px (pixel detectado de
    # verdade), não plane_w/num_cols (divisão limpa) -- o grid não
    # divide a imagem uniformemente, confirmado testando no Blender.
    units_per_px = plane_w / grid["atlas_w"]
    step_x = grid["cell_w_px"] * units_per_px
    step_y = -(grid["cell_h_px"] * units_per_px)  # negativo -- linha seguinte = Location mais negativa

    # --- Edit Mode: root.ui / cursor ---
    prev_mode = armature_obj.mode
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature_obj.data.edit_bones
    texture_picker_ctrl = edit_bones.get(texture_picker_ctrl_name)
    if texture_picker_ctrl is None:
        bpy.ops.object.mode_set(mode="OBJECT")
        if prev_mode not in ("OBJECT", "EDIT"):
            bpy.ops.object.mode_set(mode=prev_mode)
        return False, f"'{texture_picker_ctrl_name}' not found in Edit Mode -- unexpected, please report this."

    ui_root, ui_root_is_new = create_bone_like(edit_bones, texture_picker_ctrl, ui_root_name)
    if ui_root_is_new:
        ui_root.parent = texture_picker_ctrl
        ui_root.use_connect = False
        # Sem esse offset, root.ui nasce em cima do target -- desloca
        # HEAD/TAIL pelo eixo local X (preserva comprimento/orientação).
        local_x = ui_root.matrix.to_3x3().col[0].normalized()
        local_y = ui_root.matrix.to_3x3().col[1].normalized()
        offset = local_x * TEXTURE_PICKER_UI_OFFSET_X + local_y * TEXTURE_PICKER_UI_OFFSET_Y
        ui_root.head += offset
        ui_root.tail += offset
        ui_root[PROP_RIG_LAYER] = "UI-CTRL"

    cursor, cursor_is_new = create_bone_like(edit_bones, ui_root, cursor_name)
    if cursor_is_new:
        cursor.parent = ui_root
        cursor.use_connect = False
        # Bone curto -- só existe pra ter uma Location arrastável.
        direction = (cursor.tail - cursor.head)
        length = direction.length or 1.0
        cursor.tail = cursor.head + (direction / length) * min(0.05, plane_w * 0.15)
        cursor[PROP_RIG_LAYER] = "UI-CTRL"

    # Com collection_override configurado (!= Auto), tenta resolver pra
    # essa collection primeiro -- só cai pro default "Texture Picker"
    # se o override não existir mais ou estiver em Auto (bug real
    # corrigido: antes ignorava collection_override por completo).
    target_name = (item.collection_override or "").strip()
    coll_texture_picker = None
    if target_name and target_name != COLLECTION_OVERRIDE_AUTO:
        coll_texture_picker = resolve_collection_override_target(armature_obj.data, target_name)
    if coll_texture_picker is None:
        coll_texture_picker = ensure_bone_collection(
            armature_obj.data, COLL_MAIN_TEXTURE_PICKER, parent=ensure_bone_collection(armature_obj.data, COLL_MAIN)
        )
    coll_texture_picker.assign(ui_root)
    coll_texture_picker.assign(cursor)

    bpy.ops.object.mode_set(mode="OBJECT")

    # --- Cor + Limit Location + widget ---
    for name, palette in ((ui_root_name, BONE_COLOR_UI_ROOT), (cursor_name, BONE_COLOR_UI_CURSOR)):
        bone = armature_obj.data.bones.get(name)
        if bone is not None:
            normal, select, active = palette
            bone.color.palette = "CUSTOM"
            bone.color.custom.normal = normal
            bone.color.custom.select = select
            bone.color.custom.active = active

    pose_cursor = armature_obj.pose.bones.get(cursor_name)
    if pose_cursor is not None:
        con = pose_cursor.constraints.get(CONSTRAINT_TEXTURE_PICKER_LIMIT)
        if con is None:
            con = pose_cursor.constraints.new("LIMIT_LOCATION")
            con.name = CONSTRAINT_TEXTURE_PICKER_LIMIT
        con.owner_space = "LOCAL"
        # Linhas = Location Y (não Z -- confirmado testando no Blender,
        # a orientação real deste rig não bate com "comprimento sempre
        # ao longo de Y"). Colunas = X. Z fica travado em 0.
        end_x = (grid["num_cols"] - 1) * step_x
        end_y = (grid["num_rows"] - 1) * step_y
        con.use_min_x, con.use_max_x = True, True
        con.min_x, con.max_x = min(0.0, end_x), max(0.0, end_x)
        con.use_min_y, con.use_max_y = True, True
        con.min_y, con.max_y = min(0.0, end_y), max(0.0, end_y)
        con.use_min_z, con.use_max_z = True, True
        con.min_z = con.max_z = 0.0
        # Affect Transform: sem isso, arrastar pelo gizmo ignora os
        # limites (só a avaliação final respeitava).
        con.use_transform_limit = True

        widgets_collection = get_or_create_widgets_collection(armature_obj)
        missing_widgets = ensure_widget_objects({WGT_TEXTURE_PICKER_CURSOR, WGT_UI_ROOT}, armature_obj)
        if WGT_TEXTURE_PICKER_CURSOR not in missing_widgets:
            pose_cursor.custom_shape = _ensure_bone_widget_copy(
                WGT_TEXTURE_PICKER_CURSOR, armature_obj, cursor_name, widgets_collection
            )
            pose_cursor.use_custom_shape_bone_size = False
            pose_cursor.custom_shape_scale_xyz = (
                min(0.05, plane_w * 0.15), min(0.05, plane_w * 0.15), min(0.05, plane_w * 0.15),
            )
            pose_cursor.custom_shape_wire_width = 2.0

        pose_ui_root = armature_obj.pose.bones.get(ui_root_name)
        if pose_ui_root is not None and WGT_UI_ROOT not in missing_widgets:
            pose_ui_root.custom_shape = _ensure_bone_widget_copy(
                WGT_UI_ROOT, armature_obj, ui_root_name, widgets_collection
            )
            pose_ui_root.use_custom_shape_bone_size = False
            pose_ui_root.custom_shape_scale_xyz = (
                min(0.08, plane_w * 0.25), min(0.08, plane_w * 0.25), min(0.08, plane_w * 0.25),
            )
            pose_ui_root.custom_shape_wire_width = 2.0

    # --- Plane de referência ---
    plane_name = texture_picker_bone_name + TEXTURE_PICKER_PLANE_SUFFIX
    material_name = texture_picker_bone_name + TEXTURE_PICKER_MATERIAL_SUFFIX
    reference_material = _ensure_texture_picker_reference_material(material_name, image)
    rest_uv = _get_texture_picker_mesh_rest_uv(mesh_obj)
    rest_u, rest_v = rest_uv

    plane_obj = bpy.data.objects.get(plane_name)
    if plane_obj is None:
        mesh = _build_texture_picker_plane_mesh(plane_name + "_mesh", plane_w, plane_h, rest_uv)
        plane_obj = bpy.data.objects.new(plane_name, mesh)
        for coll in mesh_obj.users_collection or [context.collection]:
            coll.objects.link(plane_obj)
        plane_obj.data.materials.append(reference_material)
    else:
        old_mesh = plane_obj.data
        plane_obj.data = _build_texture_picker_plane_mesh(plane_name + "_mesh", plane_w, plane_h, rest_uv)
        if old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        if not plane_obj.data.materials:
            plane_obj.data.materials.append(reference_material)

    # Bone-parenting nativo (não vertex-group+modifier -- aquilo é pra
    # DEFORMAR através de vários bones; aqui é um Object rígido
    # seguindo um bone só). Blender posiciona relativo à TAIL, não ao
    # head -- compensa com Translation(0, -length, 0) (sinal já
    # invertido errado uma vez: +length dobra o deslocamento em vez de
    # cancelá-lo).
    ui_root_data_bone = armature_obj.data.bones.get(ui_root_name)
    plane_obj.parent = armature_obj
    plane_obj.parent_type = "BONE"
    plane_obj.parent_bone = ui_root_name
    if ui_root_data_bone is not None:
        plane_obj.matrix_parent_inverse = Matrix.Translation((0.0, -ui_root_data_bone.length, 0.0))
    plane_obj.location = (item.texture_picker_plane_offset_x, item.texture_picker_plane_offset_y, 0.0)
    plane_obj.rotation_euler = Euler((math.radians(-90.0), 0.0, 0.0), "XYZ")
    plane_obj.scale = (1.0, 1.0, 1.0)
    plane_obj.visible_shadow = False  # referência visual, não deve sombrear
    _apply_texture_picker_visibility_driver(plane_obj, armature_obj, coll_texture_picker.name)

    # --- Drivers de UV no material real do alvo ---
    _apply_texture_picker_driver(mapping_node, 0, armature_obj, step_x, grid["cell_w_px"], grid["atlas_w"], cursor_name)
    _apply_texture_picker_driver(mapping_node, 1, armature_obj, step_y, -grid["cell_h_px"], grid["atlas_h"], cursor_name)

    # --- Companion Bones: outras malhas que trocam de expressão junto ---
    # Best-effort: um companion que falhar vira aviso na mensagem
    # final, nunca cancela o resto.
    configured_companions = [
        raw_name.strip() for i in range(1, item.texture_picker_extra_bone_count + 1)
        if (raw_name := getattr(item, f"texture_picker_extra_bone_{i}", "")).strip()
    ]
    companion_warnings = []
    for companion_name in configured_companions:
        ok_companion, warn_msg = _apply_texture_picker_to_companion(
            armature_obj, companion_name, grid, step_x, step_y, primary_material, cursor_name, texture_picker_label
        )
        if not ok_companion:
            companion_warnings.append(warn_msg)

    # --- Calibração automática do exporter ---
    # Só escreve VALORES aqui -- a lógica de múltiplos target bones
    # (uv_offset_target_bones_extra) mora em exporter.py, sample_action().
    exports = armature_obj.data.hytale_texture_picker_exports
    export_entry = None
    for existing_entry in exports:
        if existing_entry.uv_offset_target_bone == texture_picker_bone_name:
            export_entry = existing_entry
            break
    if export_entry is None:
        export_entry = exports.add()
        armature_obj.data.hytale_texture_picker_exports_index = len(exports) - 1
    export_entry.uv_offset_source_bone = cursor_name
    export_entry.uv_offset_target_bone = texture_picker_bone_name
    export_entry.uv_offset_target_bones_extra = ",".join(configured_companions)
    export_entry.uv_offset_step_x = step_x
    export_entry.uv_offset_px_x = grid["cell_w_px"]
    export_entry.uv_offset_step_y = step_y
    export_entry.uv_offset_px_y = -grid["cell_h_px"]

    if prev_mode not in ("OBJECT", "EDIT"):
        bpy.ops.object.mode_set(mode=prev_mode)

    message = (
        f"Texture Picker ready: {grid['num_cols']}x{grid['num_rows']} grid on '{image.name}' "
        f"({grid['atlas_w']}x{grid['atlas_h']}px atlas, {grid['cell_w_px']:.0f}x{grid['cell_h_px']:.0f}px "
        f"per cell), rest UV=({rest_uv[0]:.4f}, {rest_uv[1]:.4f}). Export calibration written "
        f"automatically (Grid Step X={step_x:.6f}, Y={step_y:.6f}). Drag '{cursor_name}' in Pose "
        f"Mode over the reference plane to pick a cell."
    )
    if configured_companions:
        applied_count = len(configured_companions) - len(companion_warnings)
        message += f" {applied_count}/{len(configured_companions)} companion bone(s) wired."
    if companion_warnings:
        message += " Warnings: " + " | ".join(companion_warnings)
    return True, message


def _remove_texture_picker(armature_obj, item):
    """Desfaz _build_texture_picker pra esta entrada -- remove root.ui/
    cursor, o plane de referência, e os nodes injetados no material
    real (relinka Image Texture direto no Base Color). Idempotente.
    Devolve True se algo foi removido."""
    texture_picker_bone_name = (item.texture_picker_bone or "").strip()
    if not texture_picker_bone_name:
        return False
    did_something = False
    ui_root_name = _texture_picker_ui_root_name(texture_picker_bone_name)
    cursor_name = _texture_picker_cursor_name(texture_picker_bone_name)

    if armature_obj.data.bones.get(ui_root_name) is not None or armature_obj.data.bones.get(cursor_name) is not None:
        prev_mode = armature_obj.mode
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = armature_obj.data.edit_bones
        for name in (cursor_name, ui_root_name):  # filho antes do pai
            bone = edit_bones.get(name)
            if bone is not None:
                edit_bones.remove(bone)
                did_something = True
        bpy.ops.object.mode_set(mode="OBJECT")
        if prev_mode not in ("OBJECT", "EDIT"):
            bpy.ops.object.mode_set(mode=prev_mode)

    plane_name = texture_picker_bone_name + TEXTURE_PICKER_PLANE_SUFFIX
    plane_obj = bpy.data.objects.get(plane_name)
    if plane_obj is not None:
        mesh = plane_obj.data
        bpy.data.objects.remove(plane_obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh, do_unlink=True)
        did_something = True

    mesh_obj = _find_texture_picker_mesh_object(armature_obj, texture_picker_bone_name)
    if mesh_obj is not None and mesh_obj.data.materials:
        if _revert_texture_picker_material_uv_offset(mesh_obj):
            did_something = True

    # Varre TODOS os slots (1..MAX), não só até o count atual -- se o
    # usuário reduziu o count depois de criar, os companions extras
    # ainda têm driver sobrando (o campo continua preenchido, só sai
    # da UI). Reverter é no-op em material nunca tratado, seguro/barato.
    #
    # Ordem importa: principal sempre revertido ANTES do loop de
    # companions -- desde que companions podem compartilhar o mesmo
    # datablock de material, reverter o principal primeiro só reatribui
    # o slot dele (users > 0 ainda, companions seguram a referência); a
    # cópia só é apagada quando o ÚLTIMO a soltar a referência roda,
    # por contagem de referência natural, sem lógica especial aqui.
    for i in range(1, TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT + 1):
        companion_name = (getattr(item, f"texture_picker_extra_bone_{i}", "") or "").strip()
        if not companion_name:
            continue
        companion_mesh = _find_texture_picker_mesh_object(armature_obj, companion_name)
        if companion_mesh is not None and companion_mesh.data.materials:
            if _revert_texture_picker_material_uv_offset(companion_mesh):
                did_something = True

    exports = armature_obj.data.hytale_texture_picker_exports
    for export_index, export_entry in enumerate(exports):
        if export_entry.uv_offset_target_bone == texture_picker_bone_name:
            exports.remove(export_index)
            armature_obj.data.hytale_texture_picker_exports_index = max(
                0, min(armature_obj.data.hytale_texture_picker_exports_index, len(exports) - 1)
            )
            did_something = True
            break

    return did_something


class RIG_OT_hytale_texture_picker_create(Operator):
    """Botão "Create Texture Picker" -- opera sobre a entrada
    TEXTURE_PICKER ativa da lista."""

    bl_idname = "armature.hytale_texture_picker_create"
    bl_label = "Create Texture Picker"
    description = tooltip("rigger.tooltip.texture_picker_create")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        armature = obj.data
        index = armature.hytale_ik_chains_index
        if not (0 <= index < len(armature.hytale_ik_chains)):
            return False
        item = armature.hytale_ik_chains[index]
        if item.chain_type != "TEXTURE_PICKER" or not item.texture_picker_bone:
            cls.poll_message_set("Set a Target Bone on this entry first.")
            return False
        ui_parent_bone_name = (item.texture_picker_ui_parent_bone or "").strip() or item.texture_picker_bone.strip()
        ctrl_name = control_name(armature, ui_parent_bone_name, SUFFIX_CTRL)
        if armature.bones.get(ctrl_name) is None:
            cls.poll_message_set(f"'{ctrl_name}' not found -- run 'Create Rig' first.")
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        armature = obj.data
        item = armature.hytale_ik_chains[armature.hytale_ik_chains_index]
        ok, message = _build_texture_picker(context, obj, item)
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class RIG_OT_hytale_texture_picker_remove(Operator):
    """Botão ao lado de "Create Texture Picker" -- desfaz pra esta entrada."""

    bl_idname = "armature.hytale_texture_picker_remove"
    bl_label = "Remove Texture Picker"
    description = tooltip("rigger.tooltip.texture_picker_remove")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        armature = obj.data
        index = armature.hytale_ik_chains_index
        return 0 <= index < len(armature.hytale_ik_chains) and armature.hytale_ik_chains[index].chain_type == "TEXTURE_PICKER"

    def execute(self, context):
        obj = context.active_object
        armature = obj.data
        item = armature.hytale_ik_chains[armature.hytale_ik_chains_index]
        removed = _remove_texture_picker(obj, item)
        self.report({"INFO"}, "Texture Picker removed." if removed else "Nothing to remove.")
        return {"FINISHED"}
