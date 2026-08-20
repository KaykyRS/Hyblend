"""
common.py -- o "contrato" entre o importer e o exporter.
=========================================================

Este arquivo existe por UM motivo: o importer (importer.py) e o exporter
(exporter.py) precisam concordar, byte a byte, sobre como converter
posição/rotação entre o espaço do Blender e o espaço do .blockymodel /
.blockyanim. Se um dos dois mudar essa conversão sem o outro saber, o
round-trip quebra (o que você anima não é o que é exportado).

REGRA DE OURO PRA QUEM (ou qual chat) FOR MEXER AQUI:
Qualquer mudança neste arquivo afeta os dois lados (import E export) ao
mesmo tempo. Se você está trabalhando só no importer ou só no exporter,
normalmente NÃO deveria precisar tocar aqui -- é sinal de que a mudança é
maior do que parece. Ver DEVELOPER_NOTES.md, seção "Mexendo em common.py".

Cada addon (importer.py / exporter.py) importa daqui em vez de redefinir
localmente. Antes desta reorganização, cada script tinha sua própria cópia
de UNIT_SCALE_DEFAULT, vec3(), quat_xyzw() etc. -- funcionava, mas cada
chat de trabalho podia sem querer fazer as cópias divergirem.
"""
import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from mathutils import Quaternion, Vector

# ---------------------------------------------------------------------------
# Escala
# ---------------------------------------------------------------------------
#
# O importer divide toda medida de comprimento por 64 ao construir o rig
# (1 unidade Blender = 1/64 unidade do jogo). O exporter precisa multiplicar
# de volta por 64 (1/UNIT_SCALE_DEFAULT) na hora de gravar o delta. Ver as
# notas grandes no topo de importer.py e exporter.py para a validação
# numérica desse valor -- aqui só mora o número em si, pra nunca haver um
# 1/64 de um lado e um 1/65 do outro por acidente de digitação.
UNIT_SCALE_DEFAULT = 1.0 / 64.0

ACTION_SOURCE_DURATION_PROP = "hytale_source_duration"
ACTION_SOURCE_HOLD_LAST_KEYFRAME_PROP = "hytale_source_hold_last_keyframe"

# O .blockyanim grava "duration" e "time" em frames a 60 FPS FIXOS,
# independente do FPS da cena do Blender. Usado só pelo exporter hoje, mas
# fica aqui porque é uma constante do FORMATO do jogo, não uma escolha do
# addon -- mesma categoria de UNIT_SCALE_DEFAULT.
FPS_HYTALE = 60

# Sufixos que marcam um bone como GERADO pelo rigger (não original do
# jogo) -- convenção real de nomenclatura, usada por rigger.py pra criar
# esses bones e por exporter.py como fallback de detecção quando a Bone
# Collection "Hytale Export" ainda não existe na armature (ver
# is_original_bone_name() em exporter.py). Promovido de rigger.py pra cá
# porque os dois lados precisam concordar -- ver DEVELOPER_NOTES.md,
# seção "Duplicação solta pra ficar de olho".
SUFFIX_MCH = "_MCH"
SUFFIX_CTRL = "_CTRL"
SUFFIX_IK = "_IK"

# Nome da propriedade customizada gravada em cada bone pelo importer,
# guardando o shape.offset (já escalado) que aquele bone tinha no momento
# em que foi criado. Usado hoje só pelo importer (reimport de attachments),
# mas mora aqui porque é um "nome de contrato" que, se algum dia o exporter
# também precisar ler, tem que ser exatamente este mesmo texto.
BONE_SHAPE_OFFSET_PROP = "hytale_shape_offset"

# Nome da propriedade customizada gravada pelo importer num bone que teve
# nome duplicado DENTRO DO MESMO arquivo (ex: duas pastas "FernTop" em
# galhos diferentes -- permitido no Blockbench, mas o Blender não aceita
# dois bones com nome idêntico no mesmo Armature). Quando isso acontece, o
# importer renomeia o bone (ex: "FernTop.dup01") só pra existir dentro do
# Blender, e guarda aqui o nome ORIGINAL, sem sufixo, que é o que o jogo
# realmente espera. O exporter deve ler esta property (se existir) em vez
# do bone.name na hora de gravar o nome do bone no .blockyanim -- ver
# DEVELOPER_NOTES.md.
BONE_ORIGINAL_NAME_PROP = "hytale_original_name"

# ---------------------------------------------------------------------------
# Conversões JSON <-> mathutils
# ---------------------------------------------------------------------------
#
# vec3/quat_xyzw = direção arquivo -> Blender (usadas pelo importer).
# vec_to_dict/quat_to_dict = direção Blender -> arquivo (usadas pelo
# exporter). É o MESMO par x,y,z(,w) dos dois lados -- ver a nota grande em
# exporter.py sobre por que o quaternion é escrito direto, sem passar por
# Euler.


def vec3(d, default=0.0):
    """Converte {'x':.., 'y':.., 'z':..} (formato do .blockymodel) em
    mathutils.Vector."""
    return Vector((d.get("x", default), d.get("y", default), d.get("z", default)))


def quat_xyzw(d):
    """Converte {'x':,'y':,'z':,'w':} (ordem do .blockymodel) em
    mathutils.Quaternion (que internamente é w,x,y,z -- só a ordem de
    construção muda, os valores não)."""
    return Quaternion((d.get("w", 1.0), d.get("x", 0.0), d.get("y", 0.0), d.get("z", 0.0)))


def vec_to_dict(v):
    """Converte mathutils.Vector em {'x':,'y':,'z':} (formato do
    .blockyanim)."""
    return {"x": v.x, "y": v.y, "z": v.z}


def quat_to_dict(q):
    """Converte mathutils.Quaternion (w,x,y,z) em {'x':,'y':,'z':,'w':}
    (ordem do arquivo, igual quat_xyzw espera de volta)."""
    return {"x": q.x, "y": q.y, "z": q.z, "w": q.w}


# ---------------------------------------------------------------------------
# Identidade do addon
# ---------------------------------------------------------------------------
#
# AddonPreferences.bl_idname precisa ser o nome do PACOTE raiz (o que o
# Blender usa como chave em context.preferences.addons[...]), não o nome do
# submódulo onde a classe é declarada. Cada submódulo (importer.py,
# exporter.py) referencia isto em vez de usar `__name__` local -- ver
# DEVELOPER_NOTES.md, seção "Preferences e __name__" para o motivo.
ADDON_PACKAGE = __package__

class HYTALE_OT_pick_bone_into_field(Operator):
    """Copia o nome do bone atualmente ativo (Edit Mode, Pose Mode, ou o
    último selecionado no Object Mode) pra uma StringProperty qualquer,
    em qualquer datablock ligado ao Armature ativo. Genérico de
    propósito -- reutilizável por qualquer submódulo que precise de um
    botão "pegar bone selecionado" (usado hoje pela aba Export do
    interface.py; rigger.py mantém seu próprio hytale_ik_chain_pick_bone
    separado porque precisa indexar um item de lista, caso que este
    operador não cobre)."""

    bl_idname = "hytale.pick_bone_into_field"
    bl_label = "Pick Bone From Selection"
    bl_options = {"REGISTER", "UNDO"}

    data_path: StringProperty(
        description="Caminho, relativo ao objeto ativo, até o datablock "
        "dono do campo (ex: 'data.hytale_export_settings')"
    )
    field: StringProperty(description="Nome da StringProperty a preencher")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

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

        try:
            target = obj.path_resolve(self.data_path) if self.data_path else obj
        except ValueError:
            self.report({"WARNING"}, f"Invalid data_path '{self.data_path}'.")
            return {"CANCELLED"}

        if not hasattr(target, self.field):
            self.report({"WARNING"}, f"Unknown field '{self.field}'.")
            return {"CANCELLED"}

        setattr(target, self.field, bone_name)
        self.report({"INFO"}, f"{self.field} = '{bone_name}'.")
        return {"FINISHED"}


_CLASSES = (HYTALE_OT_pick_bone_into_field,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)