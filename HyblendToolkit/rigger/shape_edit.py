"""Auto-Rigger -- Shape Edit Mode / Vertex Edit Mode / Mirror Shape / Use Selected as Widget."""

import bmesh
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from bpy.props import StringProperty
from bpy.types import Operator

from ..common import is_active_armature
from ..translations import tooltip

from .constants import (
    PROP_WIDGET_SOURCE_ROLE,
)

from .helpers import _redraw_all_areas
from .constraints import armature_has_generated_bones
from .widgets import _bone_widget_name, _compute_bone_widget_world_matrix, _mute_shape_scale_drivers, _restore_shape_scale_drivers, _set_collection_excluded, _unmute_shape_scale_drivers, get_or_create_widgets_collection


SHAPE_EDIT_BORDER_COLOR = (1.0, 0.85, 0.1, 0.9)
SHAPE_EDIT_BORDER_THICKNESS = 2
SHAPE_EDIT_BORDER_TEXT = "Shape Edit Mode"
SHAPE_VERTEX_EDIT_BORDER_TEXT = "Shape Vertex Edit Mode"
SHAPE_EDIT_BORDER_TEXT_SIZE = 16
SHAPE_EDIT_BORDER_TEXT_PADDING = 34
SHAPE_EDIT_BORDER_TEXT_SHADOW_COLOR = (0.0, 0.0, 0.0, 0.6)

_shape_edit_border_shader = None
_shape_edit_border_handler = None


def register_shape_edit_border():
    """Registra o draw_handler_add global, uma vez por sessão do
    Blender (não por Armature). Chamado por rigger/__init__.py."""
    global _shape_edit_border_handler
    if _shape_edit_border_handler is None:
        _shape_edit_border_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_shape_edit_border, (), "WINDOW", "POST_PIXEL"
        )


def unregister_shape_edit_border():
    global _shape_edit_border_handler, _shape_edit_border_shader
    if _shape_edit_border_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_shape_edit_border_handler, "WINDOW")
        _shape_edit_border_handler = None
    _shape_edit_border_shader = None


def _is_shape_edit_active():
    """Condição compartilhada por borda, dim overlay e o watchdog de
    lock: True enquanto o objeto ativo está em Shape Edit Mode "de
    fora" (Armature) ou em Vertex Edit Mode (malha do widget) -- os
    dois nunca coincidem ao mesmo tempo."""
    obj = bpy.context.active_object
    if obj is None:
        return False
    if obj.type == "MESH" and obj.get("hytale_vertex_edit_armature"):
        return True
    if obj.type == "ARMATURE" and getattr(obj.data, "hytale_shape_edit_mode", False):
        return True
    return False


def _draw_shape_edit_border():
    context = bpy.context
    obj = context.active_object
    if obj is None or not _is_shape_edit_active():
        return

    border_text = SHAPE_VERTEX_EDIT_BORDER_TEXT if obj.type == "MESH" else SHAPE_EDIT_BORDER_TEXT

    region = context.region
    if region is None or region.width <= 0 or region.height <= 0:
        return

    global _shape_edit_border_shader
    if _shape_edit_border_shader is None:
        _shape_edit_border_shader = gpu.shader.from_builtin("UNIFORM_COLOR")

    w, h = region.width, region.height
    t = SHAPE_EDIT_BORDER_THICKNESS
    # Quatro faixas formando uma moldura -- quads em vez de GL_LINE com
    # largura (não confiável em core profile).
    coords = [
        (0, 0), (w, 0), (w, t), (0, t),                  # baixo
        (0, h - t), (w, h - t), (w, h), (0, h),           # cima
        (0, 0), (t, 0), (t, h), (0, h),                   # esquerda
        (w - t, 0), (w, 0), (w, h), (w - t, h),           # direita
    ]
    indices = [
        (0, 1, 2), (0, 2, 3),
        (4, 5, 6), (4, 6, 7),
        (8, 9, 10), (8, 10, 11),
        (12, 13, 14), (12, 14, 15),
    ]
    batch = batch_for_shader(_shape_edit_border_shader, "TRIS", {"pos": coords}, indices=indices)

    gpu.state.blend_set("ALPHA")
    _shape_edit_border_shader.bind()
    _shape_edit_border_shader.uniform_float("color", SHAPE_EDIT_BORDER_COLOR)
    batch.draw(_shape_edit_border_shader)
    gpu.state.blend_set("NONE")

    _draw_shape_edit_border_text(w, h, t, border_text)


def _draw_shape_edit_border_text(w, h, border_thickness, text):
    """Desenha `text` centralizado, logo abaixo da faixa de cima."""
    font_id = 0
    blf.size(font_id, SHAPE_EDIT_BORDER_TEXT_SIZE)
    text_width, text_height = blf.dimensions(font_id, text)
    text_x = round((w - text_width) / 2.0)
    text_y = h - border_thickness - SHAPE_EDIT_BORDER_TEXT_PADDING - text_height

    blf.color(font_id, *SHAPE_EDIT_BORDER_TEXT_SHADOW_COLOR)
    blf.position(font_id, text_x - 1, text_y - 1, 0)
    blf.draw(font_id, text)

    blf.color(font_id, *SHAPE_EDIT_BORDER_COLOR)
    blf.position(font_id, text_x, text_y, 0)
    blf.draw(font_id, text)


class RIG_OT_hytale_shape_edit_mode_enter(Operator):
    """Muta todo driver de shape scale do armature ativo, resolvido pro
    tamanho cheio -- libera redimensionar qualquer custom shape sem o
    driver de FK/IK sobrescrevendo. Troca pra Pose Mode se preciso."""

    bl_idname = "armature.hytale_shape_edit_mode_enter"
    bl_label = "Shape Edit Mode"
    description = tooltip("rigger.tooltip.shape_edit_mode_enter")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        armature = obj.data
        if not armature_has_generated_bones(armature):
            cls.poll_message_set("Run 'Create Rig' first -- there's no generated rig on this armature yet.")
            return False
        if getattr(armature, "hytale_shape_edit_mode", False):
            cls.poll_message_set("Already in Shape Edit Mode.")
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        armature = obj.data

        if obj.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")

        muted = _mute_shape_scale_drivers(obj)

        armature.hytale_shape_edit_mode = True
        _redraw_all_areas(context)
        if muted:
            self.report(
                {"INFO"},
                f"Shape Edit Mode on -- {muted} shape-scale driver channel(s) muted at full size. Resize custom "
                f"shapes freely, then use 'Finish Shape Edit Mode' to save.",
            )
        else:
            self.report(
                {"INFO"},
                "Shape Edit Mode on -- this armature has no FK/IK shape-scale drivers, so every custom shape was "
                "already freely editable. Use 'Finish Shape Edit Mode' when done.",
            )
        # v0.17 -- hytale_shape_edit_mode mora em Armature DATA, não no
        # Object -- um Alt+D com dado ligado (linked duplicate) faz
        # todo Object que usa esse mesmo datablock "entrar" junto.
        # Aviso só, não bloqueia -- não é um bug, é a semântica normal
        # de dado ligado no Blender.
        if armature.users > 1:
            self.report(
                {"WARNING"},
                f"This Armature's data is shared by {armature.users} object(s) (linked duplicate) -- Shape Edit "
                f"Mode is now active on all of them, since the flag lives on the shared data, not on this object.",
            )
        return {"FINISHED"}


class RIG_OT_hytale_shape_edit_mode_finish(Operator):
    """Contrário de Enter: pra cada driver mutado, grava o valor atual
    do pose bone como novo tamanho cheio na expressão, depois desmuta.
    Não força volta de modo."""

    bl_idname = "armature.hytale_shape_edit_mode_finish"
    bl_label = "Finish Shape Edit Mode"
    description = tooltip("rigger.tooltip.shape_edit_mode_finish")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        if not getattr(obj.data, "hytale_shape_edit_mode", False):
            cls.poll_message_set("Not currently in Shape Edit Mode.")
            return False
        if getattr(obj.data, "hytale_shape_vertex_edit_mode", False):
            cls.poll_message_set("Finish Vertex Edit Mode first.")
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        armature = obj.data

        restored = _restore_shape_scale_drivers(obj)

        armature.hytale_shape_edit_mode = False
        _redraw_all_areas(context)
        self.report(
            {"INFO"},
            f"Shape Edit Mode off -- {restored} shape-scale driver channel(s) restored, new size(s) saved as "
            f"the max value.",
        )
        return {"FINISHED"}


def find_armature_stuck_in_shape_edit_mode(context):
    """v0.17 -- não é bug, mas é a fonte mais comum de "achei que fiquei
    travado": hytale_shape_edit_mode mora em Armature DATA, então
    trocar o objeto ativo pra outra coisa faz o botão "Finish Shape
    Edit Mode" sumir/desabilitar (poll exige a MESMA Armature ativa),
    sem nenhuma dica visível de qual Armature ainda está esperando.
    Usado por interface.py pra mostrar essa dica + um botão de volta
    (RIG_OT_hytale_shape_edit_mode_reselect) quando o objeto ativo não
    é (mais) aquela Armature. Devolve o primeiro Object encontrado
    cujo .data.hytale_shape_edit_mode é True, ou None."""
    active = context.active_object
    for obj in context.view_layer.objects:
        if obj.type == "ARMATURE" and getattr(obj.data, "hytale_shape_edit_mode", False):
            if obj is not active:
                return obj
    return None


class RIG_OT_hytale_shape_edit_mode_reselect(Operator):
    """Atalho de um clique pra voltar a selecionar/ativar a Armature
    que ficou em Shape Edit Mode enquanto o usuário mexia em outro
    objeto -- ver find_armature_stuck_in_shape_edit_mode."""

    bl_idname = "armature.hytale_shape_edit_mode_reselect"
    bl_label = "Select Armature in Shape Edit Mode"
    description = tooltip("rigger.tooltip.shape_edit_mode_reselect")
    bl_options = {"REGISTER", "UNDO"}

    armature_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return find_armature_stuck_in_shape_edit_mode(context) is not None

    def execute(self, context):
        armature_obj = bpy.data.objects.get(self.armature_name)
        if armature_obj is None:
            self.report({"WARNING"}, f"Armature '{self.armature_name}' not found (renamed/deleted?).")
            return {"CANCELLED"}
        for other_obj in context.view_layer.objects:
            other_obj.select_set(False)
        armature_obj.select_set(True)
        context.view_layer.objects.active = armature_obj
        return {"FINISHED"}


# --- Vertex Edit Mode: edita a malha do widget por vértice, por-bone (nunca compartilhada) ---
#
# O Blender guarda .mode por OBJETO, não globalmente -- trocar o objeto
# ativo pra malha do widget e chamar mode_set(EDIT) não tira o Armature
# do Pose Mode "por baixo". interface.py trata isso com um branch
# especial (obj.type == 'MESH' + 'hytale_vertex_edit_armature').
#
# v0.17 -- FIX (bugs de travamento relatados por usuário real, "fiquei
# preso no Shape Edit Mode e não sei por quê"): revisão encontrou duas
# causas concretas, cobertas pelo que vem a seguir.
#
# 1. `hytale_vertex_edit_armature` (custom property de STRING com o
#    NOME do Armature) quebra se o Armature for renomeado durante a
#    edição -- `bpy.data.objects.get(nome_antigo)` falha, e o Finish
#    Vertex Edit Mode não tinha nenhum jeito de achar o dono de volta
#    (só dava WARNING e deixava o flag preso pra sempre). Trocado pela
#    fonte de verdade: `Object.hytale_vertex_edit_armature_ptr`
#    (PointerProperty pro Armature direto, registrado em
#    rigger/__init__.py) -- referência de datablock sobrevive a
#    qualquer rename. A property de string antiga continua sendo
#    gravada só como fallback de leitura de dado salvo ANTES desta
#    versão (arquivo salvo com uma versão anterior do addon).
# 2. Se o widget (a malha) for apagado NO MEIO da edição (Outliner,
#    Undo, "Remove Generated Bones" sem terminar antes...), não sobra
#    nenhum objeto MESH pra carregar a property -- o Finish Vertex
#    Edit Mode não tinha como aparecer/rodar nunca mais.
#    RIG_OT_hytale_shape_vertex_edit_mode_finish agora aceita rodar
#    com o ARMATURE ativo (não só a malha) como caminho de
#    recuperação, e _self_heal_shape_edit_state() (chamada em
#    load_post/undo_post/redo_post, ver register() abaixo) limpa
#    sozinha qualquer flag "órfão" que sobrar mesmo sem o usuário
#    clicar em nada -- rede de segurança pro caso de Undo parcial
#    (bpy.ops.object.mode_set() chamado de dentro de execute() empurra
#    seu PRÓPRIO passo de undo, separado das mudanças de property do
#    mesmo execute() -- um Ctrl+Z do usuário pode desfazer só a troca
# de modo e deixar o resto do estado inconsistente).


def _find_vertex_edit_widget(armature_obj):
    """Acha a malha que está em Vertex Edit Mode pra este Armature --
    ver docstring da seção acima. PointerProperty primeiro (sobrevive
    a rename), nome de string como fallback pra dado salvo antes da
    v0.17. Devolve None se nenhuma malha bater (widget deletado no
    meio da edição)."""
    for obj in bpy.data.objects:
        if obj.type == "MESH" and getattr(obj, "hytale_vertex_edit_armature_ptr", None) == armature_obj:
            return obj
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.get("hytale_vertex_edit_armature") == armature_obj.name:
            return obj
    return None


def _clear_vertex_edit_properties(target_obj):
    """Limpa da malha as duas properties de Vertex Edit Mode (string
    antiga + pointer novo), sem mexer no modo dela."""
    if "hytale_vertex_edit_armature" in target_obj:
        del target_obj["hytale_vertex_edit_armature"]
    if "hytale_vertex_edit_bone" in target_obj:
        del target_obj["hytale_vertex_edit_bone"]
    target_obj.hytale_vertex_edit_armature_ptr = None


def _self_heal_shape_edit_state():
    """Rede de segurança contra os dois estados órfãos que já causaram
    travamento real (ver docstring da seção acima) -- chamada em
    load_post/undo_post/redo_post e uma vez no register(), NUNCA de
    dentro de draw() (mesmo motivo de ensure_default_bone_collections
    em rig.py: um handler que roda fora do ciclo de desenho).

    Nunca levanta exceção pra fora -- um erro aqui não pode quebrar
    Undo/Load do arquivo inteiro do usuário."""
    try:
        # Caso 1: Armature preso em Vertex Edit Mode sem nenhuma malha
        # viva correspondente (widget deletado no meio da edição).
        for obj in list(bpy.data.objects):
            if obj.type != "ARMATURE":
                continue
            armature = obj.data
            if not getattr(armature, "hytale_shape_vertex_edit_mode", False):
                continue
            if _find_vertex_edit_widget(obj) is None:
                armature.hytale_shape_vertex_edit_mode = False
                get_or_create_widgets_collection(obj)  # já reexcluída
                _mute_shape_scale_drivers(obj)

        # Caso 2: malha com a property de Vertex Edit Mode "presa" cujo
        # Armature já não está mais marcado (Undo parcial -- ver
        # docstring da seção acima).
        for obj in list(bpy.data.objects):
            if obj.type != "MESH":
                continue
            has_ptr = getattr(obj, "hytale_vertex_edit_armature_ptr", None) is not None
            has_legacy = bool(obj.get("hytale_vertex_edit_armature"))
            if not has_ptr and not has_legacy:
                continue
            armature_obj = obj.hytale_vertex_edit_armature_ptr
            if armature_obj is None:
                armature_obj = bpy.data.objects.get(obj.get("hytale_vertex_edit_armature", ""))
            still_valid = armature_obj is not None and getattr(
                armature_obj.data, "hytale_shape_vertex_edit_mode", False
            )
            if still_valid:
                continue
            if obj.mode == "EDIT" and bpy.ops.object.mode_set.poll():
                prev_active = bpy.context.view_layer.objects.active
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode="OBJECT")
                if prev_active is not None:
                    bpy.context.view_layer.objects.active = prev_active
            _clear_vertex_edit_properties(obj)
    except Exception as exc:
        print(f"[HyblendToolkit] Shape Edit self-heal failed: {exc}")


def _self_heal_shape_edit_state_handler(*_args, **_kwargs):
    _self_heal_shape_edit_state()


def register_shape_edit_self_heal():
    """Registra o handler nas 3 listas relevantes (load/undo/redo) e
    roda uma vez de imediato -- cobre um arquivo que já estava aberto
    (com estado órfão salvo, ou legitimamente em Shape Edit Mode) antes
    do addon ser (re)ativado."""
    for handler_list in (bpy.app.handlers.load_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _self_heal_shape_edit_state_handler not in handler_list:
            handler_list.append(_self_heal_shape_edit_state_handler)
    _self_heal_shape_edit_state()


def unregister_shape_edit_self_heal():
    for handler_list in (bpy.app.handlers.load_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _self_heal_shape_edit_state_handler in handler_list:
            handler_list.remove(_self_heal_shape_edit_state_handler)


class RIG_OT_hytale_shape_vertex_edit_mode_enter(Operator):
    """Entra em Edit Mode direto na malha do custom shape do bone
    ativo. Esconde todo outro widget deste Armature, move o objeto pra
    cima do bone (senão apareceria longe, na posição de quando foi
    apendado) e desmuta os drivers de FK/IK -- Shape Edit Mode "de
    fora" deixa tudo em tamanho cheio, o que sobreporia FK e IK; aqui
    o resto volta a respeitar o switch normalmente enquanto dura a
    edição, sem perder nenhuma calibração em andamento em outro bone.
    Só disponível dentro do Shape Edit Mode externo."""

    bl_idname = "armature.hytale_shape_vertex_edit_mode_enter"
    bl_label = "Edit Shape Vertices"
    description = tooltip("rigger.tooltip.shape_vertex_edit_mode_enter")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        if not getattr(obj.data, "hytale_shape_edit_mode", False):
            cls.poll_message_set("Only available during Shape Edit Mode.")
            return False
        if getattr(obj.data, "hytale_shape_vertex_edit_mode", False):
            cls.poll_message_set("Already editing a shape's vertices -- use 'Finish Vertex Edit' first.")
            return False
        active_pb = context.active_pose_bone
        if active_pb is None or active_pb.custom_shape is None:
            cls.poll_message_set("Active bone must have a custom shape assigned.")
            return False
        return True

    def execute(self, context):
        armature_obj = context.active_object
        active_pb = context.active_pose_bone
        target_obj = active_pb.custom_shape

        widgets_collection = get_or_create_widgets_collection(armature_obj)
        _set_collection_excluded(widgets_collection, False)

        for wgt_obj in widgets_collection.objects:
            wgt_obj.hide_select = False
            wgt_obj.hide_set(wgt_obj is not target_obj)

        # Rede de segurança: se o custom shape não vier da collection
        # WGT (override manual apontando pra fora), garante visível
        # mesmo assim -- senão o mode_set(EDIT) abaixo falha em silêncio.
        target_obj.hide_select = False
        target_obj.hide_set(False)

        target_obj.matrix_world = _compute_bone_widget_world_matrix(armature_obj, active_pb)

        # Desmuta DEPOIS de posicionar -- a posição usou o valor "cheio"
        # de antes de desmutar, fica estável mesmo que o driver reavalie.
        restored = _unmute_shape_scale_drivers(armature_obj)

        # API direta em vez de bpy.ops.object.select_all -- esse
        # operator pode falhar com "context is incorrect" dependendo
        # de como o botão foi clicado (relatado por usuário real).
        for other_obj in context.view_layer.objects:
            other_obj.select_set(False)
        target_obj.select_set(True)
        context.view_layer.objects.active = target_obj

        bpy.ops.object.mode_set(mode="EDIT")

        # `hytale_vertex_edit_armature` (nome em string) fica só de
        # exibição/compat com dado salvo antes da v0.17 -- a fonte de
        # verdade pra achar o dono de volta é o PointerProperty abaixo,
        # que sobrevive a um rename do Armature (ver docstring da seção).
        target_obj["hytale_vertex_edit_armature"] = armature_obj.name
        target_obj["hytale_vertex_edit_bone"] = active_pb.name
        target_obj.hytale_vertex_edit_armature_ptr = armature_obj
        armature_obj.data.hytale_shape_vertex_edit_mode = True

        self.report(
            {"INFO"},
            f"Editing vertices of '{target_obj.name}' (bone '{active_pb.name}') -- other widgets of this "
            f"character are hidden, and {restored} FK/IK shape-scale driver(s) unmuted (no calibrated size was "
            f"changed). Use 'Finish Vertex Edit' when done.",
        )
        return {"FINISHED"}


class RIG_OT_hytale_shape_vertex_edit_mode_finish(Operator):
    """Contrário de Enter: sai do Edit Mode, re-esconde a collection
    WGT inteira, muta de novo os drivers de FK/IK e devolve o Armature
    como ativo -- ele nunca saiu do Pose Mode "por baixo", então a
    viewport volta sozinha.

    v0.17 -- também aceita rodar com o ARMATURE ativo (não só a malha
    do widget) como caminho de RECUPERAÇÃO: cobre o widget ter sido
    deletado no meio da edição, caso em que a malha original não
    existe mais pra oferecer o botão de Finish normal (ver docstring
    da seção "Vertex Edit Mode" acima). `_find_vertex_edit_widget`
    acha a malha certa mesmo assim, se ela ainda existir."""

    bl_idname = "armature.hytale_shape_vertex_edit_mode_finish"
    bl_label = "Finish Vertex Edit"
    description = tooltip("rigger.tooltip.shape_vertex_edit_mode_finish")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is not None and obj.type == "MESH" and obj.get("hytale_vertex_edit_armature"):
            return True
        if obj is not None and obj.type == "ARMATURE" and getattr(
            obj.data, "hytale_shape_vertex_edit_mode", False
        ):
            return True
        cls.poll_message_set("Only available while editing a custom shape's vertices.")
        return False

    def execute(self, context):
        obj = context.active_object
        if obj.type == "MESH":
            armature_obj = obj.hytale_vertex_edit_armature_ptr
            if armature_obj is None:
                # Fallback pra dado salvo antes da v0.17 (só nome) --
                # ver docstring da seção "Vertex Edit Mode".
                armature_obj = bpy.data.objects.get(obj.get("hytale_vertex_edit_armature", ""))
            return self._finish(context, armature_obj, obj)
        # obj.type == "ARMATURE" -- caminho de recuperação, ver docstring.
        return self._finish(context, obj, _find_vertex_edit_widget(obj))

    def _finish(self, context, armature_obj, target_obj):
        bone_name = target_obj.get("hytale_vertex_edit_bone", "") if target_obj is not None else ""

        if target_obj is not None:
            if target_obj.mode == "EDIT":
                # Pode ter sido chamado com o Armature ativo (caminho
                # de recuperação) -- mode_set() age sobre o objeto
                # ATIVO, então garante que seja a malha antes de trocar.
                if context.view_layer.objects.active != target_obj:
                    context.view_layer.objects.active = target_obj
                bpy.ops.object.mode_set(mode="OBJECT")
            _clear_vertex_edit_properties(target_obj)

        if armature_obj is not None:
            get_or_create_widgets_collection(armature_obj)  # já reexcluída
            armature_obj.data.hytale_shape_vertex_edit_mode = False
            _mute_shape_scale_drivers(armature_obj)

            for other_obj in context.view_layer.objects:
                other_obj.select_set(False)
            armature_obj.select_set(True)
            context.view_layer.objects.active = armature_obj

            if target_obj is None:
                self.report(
                    {"WARNING"},
                    f"The widget mesh being edited on '{armature_obj.name}' was not found (deleted mid-edit?) "
                    f"-- Vertex Edit Mode was cleared anyway, other widgets are hidden again.",
                )
            else:
                self.report(
                    {"INFO"},
                    f"Finished editing '{target_obj.name}'" + (f" (bone '{bone_name}')." if bone_name else "."),
                )
        else:
            self.report(
                {"WARNING"},
                "Could not find the armature this shape belongs to (renamed/deleted mid-edit?) -- the widgets "
                "collection wasn't re-hidden automatically, hide it manually in the Outliner if needed.",
            )

        return {"FINISHED"}


# --- Mirror Shape: copia translation/rotation/scale (e a malha) pro bone do lado oposto ---


def _mirrored_bone_name(name):
    """Troca "L-" por "R-" (ou vice-versa) no início do nome. None se
    não começar com nenhum dos dois."""
    if name.startswith("L-"):
        return "R-" + name[len("L-"):]
    if name.startswith("R-"):
        return "L-" + name[len("R-"):]
    return None


def _mirror_mesh_data_x(mesh):
    """Espelha os vértices no eixo X local e inverte a ordem de cada
    face -- mirror num único eixo sempre inverte o winding/handedness,
    senão as normais ficam de dentro pra fora. Opera direto no
    datablock, que precisa já ser uma cópia exclusiva."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    for v in bm.verts:
        v.co.x = -v.co.x
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


class RIG_OT_hytale_mirror_shape(Operator):
    """Espelha a malha do custom shape do bone ativo pro bone oposto
    (L-/R-), junto com Translation/Rotation/Scale. Remove primeiro
    qualquer shape próprio já atribuído ao alvo (nunca deixa órfão),
    duplica a malha de origem, espelha em X e atribui ao bone oposto.
    Translation espelha em X; Rotation/Scale são copiados direto (não
    têm handedness)."""

    bl_idname = "armature.hytale_mirror_shape"
    bl_label = "Mirror Shape"
    description = tooltip("rigger.tooltip.mirror_shape")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        if not getattr(obj.data, "hytale_shape_edit_mode", False):
            cls.poll_message_set("Only available during Shape Edit Mode.")
            return False
        active_pb = context.active_pose_bone
        if active_pb is None or _mirrored_bone_name(active_pb.name) is None:
            cls.poll_message_set("Active bone must start with 'L-' or 'R-' to have a mirror target.")
            return False
        if active_pb is not None and active_pb.custom_shape is None:
            cls.poll_message_set("Active bone must have a custom shape assigned to mirror.")
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        source = context.active_pose_bone
        source_obj = source.custom_shape
        target_name = _mirrored_bone_name(source.name)
        target = obj.pose.bones.get(target_name)
        if target is None:
            self.report({"WARNING"}, f"Mirror target '{target_name}' not found on this armature.")
            return {"CANCELLED"}

        widgets_collection = get_or_create_widgets_collection(obj)

        old_target_obj = target.custom_shape
        if old_target_obj is not None and old_target_obj != source_obj:
            old_mesh = old_target_obj.data
            bpy.data.objects.remove(old_target_obj, do_unlink=True)
            if old_mesh is not None and old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh, do_unlink=True)

        target_widget_name = _bone_widget_name(obj.name, target.name)

        # Rede de segurança: libera o nome canônico antes de renomear a
        # cópia -- um objeto órfão com esse nome faria o Blender sufixar
        # ".001" sozinho, e chamadas futuras de _ensure_bone_widget_copy
        # (que procuram pelo nome exato) perderiam o mirror.
        stale_obj = bpy.data.objects.get(target_widget_name)
        if stale_obj is not None and stale_obj != source_obj:
            stale_mesh = stale_obj.data
            bpy.data.objects.remove(stale_obj, do_unlink=True)
            if stale_mesh is not None and stale_mesh.users == 0:
                bpy.data.meshes.remove(stale_mesh, do_unlink=True)

        new_obj = source_obj.copy()
        new_obj.data = source_obj.data.copy()
        new_obj.name = target_widget_name
        new_obj.data.name = target_widget_name
        new_obj.hide_render = True
        # Object.copy() também copia custom properties -- não deve
        # herdar marcadores de uma sessão de Vertex Edit interrompida.
        if "hytale_vertex_edit_armature" in new_obj:
            del new_obj["hytale_vertex_edit_armature"]
        if "hytale_vertex_edit_bone" in new_obj:
            del new_obj["hytale_vertex_edit_bone"]
        widgets_collection.objects.link(new_obj)

        _mirror_mesh_data_x(new_obj.data)

        target.custom_shape = new_obj
        target.use_custom_shape_bone_size = source.use_custom_shape_bone_size
        target.custom_shape_wire_width = source.custom_shape_wire_width

        src_translation = source.custom_shape_translation
        target.custom_shape_translation = (
            -src_translation[0], src_translation[1], src_translation[2],
        )
        target.custom_shape_rotation_euler = tuple(source.custom_shape_rotation_euler)
        target.custom_shape_scale_xyz = tuple(source.custom_shape_scale_xyz)

        self.report({"INFO"}, f"Mirrored '{source.name}' shape mesh onto '{target_name}'.")
        return {"FINISHED"}


class RIG_OT_hytale_use_selected_as_widget(Operator):
    """Copia a geometria de um objeto de malha selecionado (junto com o
    Armature) pro CONTEÚDO da cópia por-bone já existente do bone pose
    ativo -- não troca o Object atribuído, só a Mesh, pra continuar
    reconhecido como "gerenciado" pelo resto do sistema. Fluxo:
    selecionar a fonte -> Shift+clique no Armature -> clicar aqui, com
    Shape Edit Mode ligado.

    Copia só a geometria em espaço local, nunca a matrix_world do
    objeto-fonte -- senão a escala/rotação dele vazaria pro "shape
    space" do bone; avisa se houver transform não aplicado, mas segue
    em frente mesmo assim. Não mexe no objeto-fonte."""

    bl_idname = "armature.hytale_use_selected_as_widget"
    bl_label = "Use Selected Object as Widget"
    description = tooltip("rigger.tooltip.use_selected_as_widget")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        if not getattr(obj.data, "hytale_shape_edit_mode", False):
            cls.poll_message_set("Only available during Shape Edit Mode.")
            return False
        active_pb = context.active_pose_bone
        if active_pb is None or active_pb.custom_shape is None:
            cls.poll_message_set("Active bone must have a custom shape assigned.")
            return False
        source_candidates = [
            o for o in context.selected_objects if o.type == "MESH" and o is not active_pb.custom_shape
        ]
        if len(source_candidates) != 1:
            cls.poll_message_set(
                "Select exactly one other mesh object (besides the armature) to use as the widget.",
            )
            return False
        return True

    def execute(self, context):
        active_pb = context.active_pose_bone
        target_obj = active_pb.custom_shape
        source_obj = next(
            o for o in context.selected_objects if o.type == "MESH" and o is not target_obj
        )

        bm = bmesh.new()
        bm.from_mesh(source_obj.data)
        bm.to_mesh(target_obj.data)
        bm.free()
        target_obj.data.update()

        # Sem proveniência conhecida a partir de agora, ver
        # _widget_mesh_differs_from_template.
        if PROP_WIDGET_SOURCE_ROLE in target_obj:
            del target_obj[PROP_WIDGET_SOURCE_ROLE]

        has_transform = (
            tuple(source_obj.scale) != (1.0, 1.0, 1.0)
            or tuple(source_obj.rotation_euler) != (0.0, 0.0, 0.0)
        )
        message = (
            f"Copied geometry from '{source_obj.name}' into the widget of bone '{active_pb.name}' "
            f"('{target_obj.name}')."
        )
        if has_transform:
            message += (
                " Note: the source object had a non-applied scale/rotation -- only its raw local-space "
                "geometry was copied (Object > Apply > All Transforms on the source first if the shape "
                "looks off)."
            )
        self.report({"INFO"}, message)
        return {"FINISHED"}
