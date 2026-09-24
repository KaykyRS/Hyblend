"""Auto-Rigger -- biblioteca de custom shapes (widgets): criação, cópia por-personagem, shape scale drivers."""

import os
import re

import bpy
from mathutils import Euler, Matrix, Vector

from .constants import (
    ATTACHMENT_NAME_HINT,
    PROP_WIDGET_SOURCE_ROLE,
    SUFFIX_POLE,
    SUFFIX_POLE_LINE,
    WGT_ATTACHMENT,
    WGT_DEFAULT_FALLBACK,
    WGT_FK_RING,
    WGT_HEAD,
    WGT_ORIGIN,
    WGT_IK_BOX,
    WGT_POLE,
    WGT_POLE_LINE,
    WIDGETS_LIBRARY_FILENAME,
    WIDGETS_LIBRARY_SUBDIR,
    WIDGET_NAME_OVERRIDES,
)


_SHAPE_SCALE_DRIVER_VALUE_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*\*")


def _format_shape_scale_literal(value):
    """Formata um float como literal decimal simples (sem notação
    científica, que a regex acima não reconhece)."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text and text != "-" else "0"


def resolve_custom_shape_scale(pose_bone):
    """Tamanho "cheio" (sem o driver de troca FK/IK) do
    custom_shape_scale_xyz -- pra usar ao salvar um shape template. Ler
    o valor direto retornaria 0 se o modo oposto estivesse ativo no
    momento; em vez disso extrai o alvo da EXPRESSÃO do driver em cada
    eixo, que é sempre o tamanho cheio independente do switch."""
    scale = list(pose_bone.custom_shape_scale_xyz)
    obj = pose_bone.id_data
    anim_data = getattr(obj, "animation_data", None)
    if anim_data is None:
        return tuple(scale)

    data_path = f'pose.bones["{pose_bone.name}"].custom_shape_scale_xyz'
    for i in range(3):
        fcurve = anim_data.drivers.find(data_path, index=i)
        if fcurve is None or fcurve.driver is None:
            continue
        match = _SHAPE_SCALE_DRIVER_VALUE_RE.match(fcurve.driver.expression or "")
        if match:
            scale[i] = float(match.group(1))
    return tuple(scale)


def _iter_shape_scale_drivers(obj):
    """Gera (pose_bone, axis_index, fcurve) de todo driver de
    custom_shape_scale_xyz de `obj` -- só bones dentro de uma cadeia
    IK/FK têm esse driver. Base de mute/unmute/restore abaixo."""
    anim_data = getattr(obj, "animation_data", None)
    if anim_data is None:
        return
    for pb in obj.pose.bones:
        data_path = f'pose.bones["{pb.name}"].custom_shape_scale_xyz'
        for i in range(3):
            fcurve = anim_data.drivers.find(data_path, index=i)
            if fcurve is not None and fcurve.driver is not None:
                yield pb, i, fcurve


def _mute_shape_scale_drivers(obj):
    """Muta cada driver de shape scale, aplicando antes o tamanho cheio
    (da expressão) -- libera redimensionar o custom shape sem o driver
    de FK/IK sobrescrevendo. Devolve quantos canais foram mutados."""
    muted = 0
    for pb, i, fcurve in _iter_shape_scale_drivers(obj):
        driver = fcurve.driver
        match = _SHAPE_SCALE_DRIVER_VALUE_RE.match(driver.expression or "")
        if match:
            pb.custom_shape_scale_xyz[i] = float(match.group(1))
        fcurve.mute = True
        muted += 1
    return muted


def _unmute_shape_scale_drivers(obj):
    """Desmuta sem regravar a expressão -- toggle temporário do Vertex
    Edit Mode. Diferente de _restore_shape_scale_drivers (que grava o
    valor atual como novo tamanho permanente): usar _restore aqui
    bakearia o valor de TODO bone do armature, não só do que está
    sendo editado -- bug real já encontrado em revisão."""
    unmuted = 0
    for pb, i, fcurve in _iter_shape_scale_drivers(obj):
        if fcurve.mute:
            fcurve.mute = False
            unmuted += 1
    return unmuted


def _restore_shape_scale_drivers(obj):
    """Desmuta e regrava o valor atual do pose bone como novo tamanho
    cheio na expressão -- contrário de _mute_shape_scale_drivers."""
    restored = 0
    for pb, i, fcurve in _iter_shape_scale_drivers(obj):
        driver = fcurve.driver
        if not fcurve.mute:
            continue
        new_value = _format_shape_scale_literal(float(pb.custom_shape_scale_xyz[i]))
        if "(1 - switch)" in (driver.expression or ""):
            driver.expression = f"{new_value}*(1 - switch)"
        else:
            driver.expression = f"{new_value}*switch"
        fcurve.mute = False
        restored += 1
    return restored


def _widgets_library_path():
    """Caminho absoluto pro hytale_widgets.blend, relativo à raiz do
    pacote (não a este arquivo)."""
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(package_root, WIDGETS_LIBRARY_SUBDIR, WIDGETS_LIBRARY_FILENAME)


def _widget_instance_name(base_name, armature_name):
    """Nome do objeto TEMPLATE por-personagem/por-papel, ex.
    'WGT_hytale_fk_ring - Steve' -- nomes de Object são únicos
    globalmente, então dois personagens não podem compartilhar o
    objeto cru vindo da biblioteca."""
    return f"{base_name} - {armature_name}"


def _find_layer_collection(layer_collection, name):
    """Busca recursiva por LayerCollection cujo .collection.name bata
    com `name` -- '.exclude' mora no LayerCollection, não na Collection."""
    if layer_collection.collection.name == name:
        return layer_collection
    for child in layer_collection.children:
        found = _find_layer_collection(child, name)
        if found is not None:
            return found
    return None


def _set_collection_excluded(collection, excluded):
    """Liga/desliga 'Exclude from View Layer' de `collection` na View
    Layer ativa -- mesma técnica do Rigify pra manter widgets fora do
    caminho sem mexer em hide_viewport de cada objeto."""
    layer_coll = _find_layer_collection(bpy.context.view_layer.layer_collection, collection.name)
    if layer_coll is not None:
        layer_coll.exclude = excluded


def _find_rig_collection(armature_obj):
    """Acha a collection 'Rig - <nome>' que importer.py cria."""
    expected_name = f"Rig - {armature_obj.name}"
    for coll in armature_obj.users_collection:
        if coll.name == expected_name:
            return coll
    return bpy.data.collections.get(expected_name)


def _unlink_and_remove_collection(collection):
    """Deslinka `collection` de qualquer pai e apaga o datablock. Só
    deve ser chamado com a collection já vazia."""
    def _unlink_from(parent):
        for child in list(parent.children):
            if child == collection:
                parent.children.unlink(collection)
                return True
            if _unlink_from(child):
                return True
        return False

    _unlink_from(bpy.context.scene.collection)
    bpy.data.collections.remove(collection)


def _find_widgets_collection(armature_obj):
    """Variante read-only de get_or_create_widgets_collection -- nunca
    cria nada, devolve None se "Create Rig" nunca rodou neste armature."""
    stored_name = armature_obj.get("hytale_widgets_collection")
    if stored_name:
        collection = bpy.data.collections.get(stored_name)
        if collection is not None:
            return collection
    rig_collection = _find_rig_collection(armature_obj)
    if rig_collection is not None:
        name = f"WGT - {armature_obj.name}"
        for child in rig_collection.children:
            if child.name == name:
                return child
    return None


def get_or_create_widgets_collection(armature_obj):
    """Coleção 'WGT - <nome>', onde moram as cópias locais dos custom
    shapes. Nasce dentro de 'Rig - <nome>' quando existe, senão cai
    pra Scene Collection. Guarda o nome em
    armature_obj['hytale_widgets_collection'] pra sobreviver a um
    rename do Armature. Fica excluída da View Layer ativa toda vez
    (Vertex Edit Mode reinclui temporariamente por conta própria)."""
    collection = _find_widgets_collection(armature_obj)
    if collection is None:
        name = f"WGT - {armature_obj.name}"
        rig_collection = _find_rig_collection(armature_obj)
        parent_collection = rig_collection if rig_collection is not None else bpy.context.scene.collection
        collection = bpy.data.collections.new(name)
        parent_collection.children.link(collection)
    armature_obj["hytale_widgets_collection"] = collection.name
    _set_collection_excluded(collection, True)
    return collection


def ensure_widget_objects(names, armature_obj):
    """Garante que o template por-personagem de cada base name exista,
    apendando (cópia, não link) de hytale_widgets.blend só o que falta.
    Idempotente. Este template nunca é atribuído a bone nenhum
    diretamente -- serve só de fonte pras cópias por-bone
    (_ensure_bone_widget_copy).

    Cada nome é apendado num bpy.data.libraries.load() isolado (um
    arquivo reaberto por widget) -- pedir vários nomes de uma vez só
    resolvia parte deles, de forma inconsistente entre execuções.

    Nunca levanta exceção -- custom shape é cosmético e não deve
    travar a geração do rig. Devolve os base names que não foi
    possível resolver."""
    widgets_collection = get_or_create_widgets_collection(armature_obj)

    to_append = []
    for base_name in names:
        target_name = _widget_instance_name(base_name, armature_obj.name)
        obj = bpy.data.objects.get(target_name)
        if obj is not None:
            if obj.name not in widgets_collection.objects:
                widgets_collection.objects.link(obj)
            obj.hide_render = True
            continue
        to_append.append(base_name)

    if not to_append:
        return set()

    filepath = _widgets_library_path()
    if not os.path.isfile(filepath):
        return set(to_append)

    still_missing = set()
    for base_name in to_append:
        try:
            with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
                data_to.objects = [base_name] if base_name in data_from.objects else []
        except Exception:
            still_missing.add(base_name)
            continue

        loaded = data_to.objects[0] if data_to.objects else None
        if loaded is None:
            still_missing.add(base_name)
            continue
        loaded.name = _widget_instance_name(base_name, armature_obj.name)
        loaded.hide_render = True
        widgets_collection.objects.link(loaded)

    return still_missing


def list_widget_library_names():
    """Todos os nomes de Object dentro de hytale_widgets.blend, sem
    apendar nada -- só pra diagnóstico do aviso "Widget not found"."""
    filepath = _widgets_library_path()
    if not os.path.isfile(filepath):
        return []
    try:
        with bpy.data.libraries.load(filepath, link=False) as (data_from, _data_to):
            return list(data_from.objects)
    except Exception:
        return []


def _bone_widget_name(armature_name, bone_name):
    """Nome do custom shape único de um bone -- não inclui o base_name/
    papel de propósito, pra não estourar o limite de ~63 caracteres de
    nome de Object do Blender."""
    return f"WGT - {armature_name} - {bone_name}"


def _mesh_dict_to_pydata(mesh_data):
    """Converte {"vertices","edges","faces"} (schema da chave "mesh" em
    shapes/<nome>.json) pras três listas que Mesh.from_pydata espera.
    edges/faces ausentes viram lista vazia -- widgets só-wireframe
    (ex. WGT_POLE_LINE) precisam das edges gravadas, não dá pra
    reconstruir a partir de faces que não existem."""
    vertices = [tuple(v) for v in mesh_data.get("vertices", [])]
    edges = [tuple(e) for e in mesh_data.get("edges", [])]
    faces = [tuple(f) for f in mesh_data.get("faces", [])]
    return vertices, edges, faces


def _mesh_object_to_dict(mesh, precision=6):
    """Inverso de _mesh_dict_to_pydata -- serializa um Mesh pro mesmo
    schema, coordenadas arredondadas (evita ruído de ponto flutuante
    no .json). Não grava UV/material/normal."""
    return {
        "vertices": [[round(c, precision) for c in v.co] for v in mesh.vertices],
        "edges": [list(e.vertices) for e in mesh.edges],
        "faces": [list(p.vertices) for p in mesh.polygons],
    }


def _build_widget_object_from_mesh_data(name, mesh_data):
    """Reconstrói um Object+Mesh (não linkado ainda) a partir da malha
    embutida num Shape Template, via Mesh.from_pydata. Devolve None
    (nunca levanta exceção) se os dados estiverem vazios/corrompidos --
    o chamador cai pro resto da cadeia de candidatos."""
    try:
        vertices, edges, faces = _mesh_dict_to_pydata(mesh_data)
        if not vertices:
            return None
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, edges, faces)
        mesh.update()
        return bpy.data.objects.new(name, mesh)
    except Exception:
        return None


def _widget_mesh_differs_from_template(shape_obj, base_name, armature_name, precision=6):
    """True se a malha de `shape_obj` divergir geometricamente do
    template do papel `base_name` -- usado por
    RIG_OT_hytale_shape_template_save pra decidir se embute a malha no
    .json (se não customizada, continua recebendo remodelagens
    futuras da biblioteca automaticamente). True também se o template
    não existir mais pra comparar -- mais seguro preservar a edição."""
    template = bpy.data.objects.get(_widget_instance_name(base_name, armature_name))
    if template is None or template.type != "MESH":
        return True

    mesh_a, mesh_b = shape_obj.data, template.data
    if (
        len(mesh_a.vertices) != len(mesh_b.vertices)
        or len(mesh_a.edges) != len(mesh_b.edges)
        or len(mesh_a.polygons) != len(mesh_b.polygons)
    ):
        return True

    for va, vb in zip(mesh_a.vertices, mesh_b.vertices):
        for ca, cb in zip(va.co, vb.co):
            if round(ca, precision) != round(cb, precision):
                return True
    return False


def _ensure_bone_widget_copy(base_name, armature_obj, bone_name, widgets_collection, embedded_mesh=None):
    """Cópia única (Object E Mesh independentes) do custom shape de
    `bone_name`, duplicada do template do papel `base_name` na
    primeira vez. Object.copy() + Object.data.copy() -- só a segunda
    parte garante uma Mesh de verdade independente. Idempotente:
    reruns reaproveitam a cópia já existente, preservando edições.

    `embedded_mesh`: dict de _mesh_dict_to_pydata, usado só quando nem
    a cópia local nem o template existem -- cobre "Delete All" ter
    apagado a cópia editada, mas a edição sobreviveu embutida no
    template salvo. Devolve None se nada resolver."""
    target_name = _bone_widget_name(armature_obj.name, bone_name)
    obj = bpy.data.objects.get(target_name)
    if obj is not None:
        if obj.name not in widgets_collection.objects:
            widgets_collection.objects.link(obj)
        obj.hide_render = True
        return obj

    template = bpy.data.objects.get(_widget_instance_name(base_name, armature_obj.name))
    if template is None:
        if embedded_mesh:
            obj = _build_widget_object_from_mesh_data(target_name, embedded_mesh)
            if obj is not None:
                obj.hide_render = True
                widgets_collection.objects.link(obj)
                return obj
        return None

    obj = template.copy()
    obj.data = template.data.copy()
    obj.name = target_name
    obj.data.name = target_name
    obj.hide_render = True
    obj[PROP_WIDGET_SOURCE_ROLE] = base_name
    widgets_collection.objects.link(obj)
    return obj


def _compute_bone_widget_world_matrix(armature_obj, pose_bone):
    """Matriz mundial que reproduz onde o Blender desenha o custom
    shape de `pose_bone` em Pose Mode: origem no head do bone, eixo Y
    do shape = eixo Y do bone, tudo escalado pelo comprimento do bone
    (Scale to Bone Length). Usado por Vertex Edit Mode Enter pra
    posicionar o objeto do widget em cima do bone antes de editar."""
    bone_length = pose_bone.bone.length if pose_bone.use_custom_shape_bone_size else 1.0
    scale_matrix = Matrix.Diagonal((bone_length, bone_length, bone_length, 1.0))

    shape_translation = Matrix.Translation(pose_bone.custom_shape_translation)
    shape_rotation = Euler(pose_bone.custom_shape_rotation_euler, "XYZ").to_matrix().to_4x4()
    shape_scale = Matrix.Diagonal((*pose_bone.custom_shape_scale_xyz, 1.0))
    shape_transform = shape_translation @ shape_rotation @ shape_scale

    return armature_obj.matrix_world @ pose_bone.matrix @ scale_matrix @ shape_transform


def _widget_candidates_for_bone(bone_name, layer, ik_tip_names, shape_overrides=None, head_ctrl_name=None, root_ctrl_names=()):
    """Lista ordenada de nomes de widget candidatos pra um bone (mais
    preferido primeiro), [] se o bone não deve ganhar shape nenhum
    (MCH/MCH-IK/ORG). Ordem: (1) override do Shape Template ativo, (2)
    WIDGET_NAME_OVERRIDES fixo, (2.5) `head_ctrl_name` resolvido em
    runtime (cobre o bone da cabeça quando o ORG dele não se chama
    "Head" -- ver resolve_head_ctrl_name/helpers.py -- já que
    WIDGET_NAME_OVERRIDES só bate com o nome literal "Head_CTRL"), (3)
    regra genérica por layer/papel, (4) WGT_DEFAULT_FALLBACK como último
    recurso.

    Devolve a cadeia inteira, não só o primeiro nível que bate -- se
    o nível mais específico foi apagado (ex. "Delete All"), o bone
    ainda cai no shape genérico do papel em vez de pular direto pro
    cubo (bug relatado corrigido)."""
    candidates = []

    if shape_overrides:
        template_widget = shape_overrides.get(bone_name, {}).get("widget")
        if template_widget:
            candidates.append(template_widget)

    fixed_override = WIDGET_NAME_OVERRIDES.get(bone_name)
    if fixed_override:
        candidates.append(fixed_override)
    elif head_ctrl_name and bone_name == head_ctrl_name:
        candidates.append(WGT_HEAD)
    elif bone_name in root_ctrl_names:
        # Roots da entrada ROOT (Origin principal + extras) -- mesmo
        # widget do Origin_CTRL legado (WIDGET_NAME_OVERRIDES só bate com
        # o nome literal "Origin_CTRL").
        candidates.append(WGT_ORIGIN)

    if layer is not None:
        if bone_name.endswith(SUFFIX_POLE_LINE):
            candidates.append(WGT_POLE_LINE)
        elif bone_name.endswith(SUFFIX_POLE):
            candidates.append(WGT_POLE)
        elif ATTACHMENT_NAME_HINT in bone_name.lower():
            candidates.append(WGT_ATTACHMENT)
        elif layer == "CTRL-IK":
            candidates.append(WGT_IK_BOX)
        elif layer in ("CTRL", "ROOT-CTRL"):
            candidates.append(WGT_FK_RING)

    if not candidates:
        return []  # bone não elegível pra widget nenhum

    candidates.append(WGT_DEFAULT_FALLBACK)

    seen = set()
    ordered = []
    for name in candidates:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


def compute_widget_transform_correction(old_axes, old_length, new_axes, new_length, old_translation, old_rotation, old_scale):
    """Corrige Translation/Rotation/Scale do custom shape depois que a
    geometria (head/tail) de um bone mudou -- mede "antes" e "depois",
    aplica a diferença (rotação do referencial local + mudança de
    comprimento).

    Premissas (doc oficial do Blender): origem do shape = head do
    bone; eixo Y do shape = eixo Y do bone; com Scale to Bone Length
    ligado, Translation e Scale são multiplicados pelo comprimento;
    Rotation não depende do comprimento.

    `old_axes`/`new_axes`: (x_axis, y_axis, z_axis) do edit bone antes/
    depois. Retorna (nova_translation, nova_rotation, nova_scale).

    Verificado contra a documentação oficial, mas não testado dentro
    do Blender de verdade -- confira visualmente depois de gerar."""
    length_ratio = (old_length / new_length) if new_length > 1e-9 else 1.0

    r_old = Matrix((old_axes[0], old_axes[1], old_axes[2])).transposed()
    r_new = Matrix((new_axes[0], new_axes[1], new_axes[2])).transposed()
    r_delta = r_new.transposed() @ r_old  # r_new^-1 == r_new.transposed() (matriz ortogonal)

    new_translation = length_ratio * (r_delta @ Vector(old_translation))
    new_scale = tuple(s * length_ratio for s in old_scale)

    old_rot_matrix = Euler(old_rotation, "XYZ").to_matrix()
    new_rot_matrix = r_delta @ old_rot_matrix
    new_rotation = tuple(new_rot_matrix.to_euler("XYZ"))

    return tuple(new_translation), new_rotation, new_scale
