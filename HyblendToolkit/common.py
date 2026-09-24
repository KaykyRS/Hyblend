"""common.py -- contrato entre importer e exporter sobre como converter
posição/rotação entre o espaço do Blender e o .blockymodel/.blockyanim.
Se um mudar essa conversão sem o outro saber, o round-trip quebra.
Qualquer mudança aqui afeta os dois lados ao mesmo tempo."""
from bpy.props import StringProperty
from bpy.types import Operator
from mathutils import Quaternion, Vector

# 1 unidade Blender = 1/64 unidade do jogo. O importer divide por 64 ao
# construir o rig; o exporter multiplica de volta por 64 no delta.
UNIT_SCALE_DEFAULT = 1.0 / 64.0

# Formato do modelo (Character vs Prop) -- mesmos ids/valores do plugin
# oficial do Blockbench (hytale-blockbench-plugin, src/formats.ts):
#   hytale_character: block_size 64  (personagens, criaturas, cosméticos,
#                     armas -- 64 unidades = 1 bloco, 64px por bloco)
#   hytale_prop:      block_size 32  (props, blocos, móveis -- 32 = 1 bloco)
# O .blockymodel grava isso na raiz como "format": "character"/"prop"
# (ausente = character, exceto arquivo dentro de uma pasta "Blocks" --
# mesma heurística do plugin). O .bbmodel grava em meta.model_format.
#
# Semântica do campo "Unit Scale" dos operadores: continua sendo a escala
# de um modelo CHARACTER (padrão 1/64 = 1 bloco vira 1 metro). Prop usa
# a MESMA relação bloco->metro, então a escala efetiva é ajustada pelo
# block_size (1/64 * 64/32 = 1/32) -- ver effective_unit_scale(). Assim
# prop e personagem ficam no mesmo tamanho relativo dentro do Blender.
MODEL_FORMAT_CHARACTER = "character"
MODEL_FORMAT_PROP = "prop"
BLOCK_SIZE_BY_MODEL_FORMAT = {MODEL_FORMAT_CHARACTER: 64, MODEL_FORMAT_PROP: 32}

# Gravada no OBJETO Armature pelo importer (.blockymodel/.bbmodel):
# "character"/"prop". Lida pelo exporter (campo "format" do .blockymodel
# + escala) e pelo anim_importer (escala do delta de posição). Ausente
# (rig importado antes disto) = character, que era o único comportamento.
ARMATURE_MODEL_FORMAT_PROP = "hytale_model_format"


def normalize_model_format(value):
    """Aceita "prop"/"character" (.blockymodel) ou "hytale_prop"/
    "hytale_character" (.bbmodel meta.model_format). Qualquer outra coisa
    (vazio, formato Bedrock etc.) = character."""
    value = (value or "").strip().lower()
    if value.startswith("hytale_"):
        value = value[len("hytale_"):]
    return MODEL_FORMAT_PROP if value == MODEL_FORMAT_PROP else MODEL_FORMAT_CHARACTER


def armature_model_format(armature_obj):
    """Formato gravado na Armature (ver ARMATURE_MODEL_FORMAT_PROP)."""
    if armature_obj is None:
        return MODEL_FORMAT_CHARACTER
    return normalize_model_format(armature_obj.get(ARMATURE_MODEL_FORMAT_PROP, MODEL_FORMAT_CHARACTER))


def effective_unit_scale(character_unit_scale, model_format):
    """Converte o "Unit Scale" do operador (definido pra Character, 64
    unidades/bloco) na escala real pro formato dado."""
    block_size = BLOCK_SIZE_BY_MODEL_FORMAT[normalize_model_format(model_format)]
    return character_unit_scale * BLOCK_SIZE_BY_MODEL_FORMAT[MODEL_FORMAT_CHARACTER] / block_size

ACTION_SOURCE_DURATION_PROP = "hytale_source_duration"
ACTION_SOURCE_HOLD_LAST_KEYFRAME_PROP = "hytale_source_hold_last_keyframe"

# O .blockyanim grava "duration"/"time" em frames a 60 FPS fixos,
# independente do FPS da cena do Blender.
FPS_HYTALE = 60

# Sufixos que marcam um bone como gerado pelo rigger (não original do
# jogo) -- usado por rigger.py pra criar esses bones e por exporter.py
# como fallback de detecção quando a Bone Collection "Hytale Export"
# ainda não existe (ver is_original_bone_name()).
SUFFIX_MCH = "_MCH"
SUFFIX_CTRL = "_CTRL"
SUFFIX_IK = "_IK"

# Custom property gravada em cada bone pelo importer, guardando o
# shape.offset (já escalado) do momento em que o bone foi criado.
# Usado hoje só pelo importer (reimport de attachments).
BONE_SHAPE_OFFSET_PROP = "hytale_shape_offset"

# Guarda o dict "shape" inteiro (type/settings/textureLayout/stretch/
# isPiece etc.) como veio no JSON, serializado via json.dumps -- gravado
# pelo importer quando o bone nasce de verdade (não em wrappers de
# attachment reaproveitado). Sem isto o exporter de .blockymodel não
# reconstrói type/tamanho/UV de um bone. Rigs importados antes desta
# mudança precisam ser reimportados uma vez pra ganhar esse suporte.
BONE_SHAPE_JSON_PROP = "hytale_shape_json"

# Guarda o nome ORIGINAL (sem sufixo) de um bone que o importer teve
# que renomear por colisão de nome dentro do mesmo arquivo (ex.: duas
# pastas "FernTop" em galhos diferentes -- permitido no Blockbench, mas
# o Blender não aceita dois bones com nome idêntico no mesmo Armature).
# O exporter deve ler esta property (se existir) em vez de bone.name.
BONE_ORIGINAL_NAME_PROP = "hytale_original_name"

# Nome que o bone tinha ANTES do "Rename Bones" (modo All Bones) --
# gravado só no primeiro rename (renomear de novo não sobrescreve). Usado
# pelo botão de reverter (volta pra este nome), pela opção "Use Original
# Names" do export (.blockymodel/.blockyanim) e pelo import de animação/
# Attach (acham o bone renomeado pelo nome do arquivo). Separado de
# BONE_ORIGINAL_NAME_PROP de propósito: a colisão do importer SEMPRE
# exporta o nome original (o ".dupNN" não existe no jogo); o rename só
# quando a opção de export estiver ligada.
BONE_RENAMED_FROM_PROP = "hytale_renamed_from"


def bone_file_name(bone):
    """Nome do bone no ARQUIVO de onde ele veio (ou None se é o próprio
    bone.name): o original da colisão do importer, senão o nome de antes
    do Rename Bones."""
    original = bone.get(BONE_ORIGINAL_NAME_PROP) or bone.get(BONE_RENAMED_FROM_PROP)
    return original if original and original != bone.name else None

# Marca um bone "ORG" (sem hytale_rig_layer) que NÃO veio do modelo -- foi
# criado pelo Auto-Rigger (Origin automático quando o modelo não tem um,
# ou um slot de Root marcado como "New Bone" no Bone Settings). Existe só
# como controle dentro do Blender: fica FORA da collection de export, o
# exporter ignora ele mesmo no fallback por nome, e "Remove Generated"
# apaga ele junto dos outros bones gerados.
BONE_RIGGER_CREATED_PROP = "hytale_rigger_created"

# vec3/quat_xyzw = direção arquivo -> Blender (importer). vec_to_dict/
# quat_to_dict = direção Blender -> arquivo (exporter). Mesmo par
# x,y,z(,w) dos dois lados.


def vec3(d, default=0.0):
    """Converte {'x':,'y':,'z':} (.blockymodel) em mathutils.Vector."""
    return Vector((d.get("x", default), d.get("y", default), d.get("z", default)))


def quat_xyzw(d):
    """Converte {'x':,'y':,'z':,'w':} (ordem do .blockymodel) em
    mathutils.Quaternion (internamente w,x,y,z -- só a ordem de
    construção muda)."""
    return Quaternion((d.get("w", 1.0), d.get("x", 0.0), d.get("y", 0.0), d.get("z", 0.0)))


def vec_to_dict(v):
    """Converte mathutils.Vector em {'x':,'y':,'z':} (.blockyanim)."""
    return {"x": v.x, "y": v.y, "z": v.z}


def quat_to_dict(q):
    """Converte mathutils.Quaternion em {'x':,'y':,'z':,'w':} (ordem do arquivo)."""
    return {"x": q.x, "y": q.y, "z": q.z, "w": q.w}


def is_active_armature(context):
    """True se o objeto ativo existir e for um Armature. Idiom repetido
    em poll()/execute() por quase todo submódulo (rigger, exporter,
    importer, anim, interface) -- centralizado aqui pra não divergir."""
    obj = context.active_object
    return obj is not None and obj.type == "ARMATURE"


# AddonPreferences.bl_idname precisa ser o nome do pacote raiz (chave em
# context.preferences.addons[...]), não o __name__ do submódulo onde a
# classe é declarada -- cada submódulo referencia isto em vez de usar
# __name__ local.
ADDON_PACKAGE = __package__

# Import posicionado aqui (depois de ADDON_PACKAGE definido), não no
# topo -- translations/__init__.py importa ADDON_PACKAGE deste módulo,
# então um import de .translations antes disso criaria um ciclo.
from .translations import localized_props, register_localized_class, tooltip, tr, unregister_localized_class


def _pick_bone_into_field_props(lang):
    return {
        "data_path": StringProperty(
            description=tr("common.prop.pick_bone_data_path", lang),
        ),
        "field": StringProperty(description=tr("common.prop.pick_bone_field", lang)),
    }


@localized_props(_pick_bone_into_field_props)
class HYTALE_OT_pick_bone_into_field(Operator):
    """Copia o nome do bone ativo (Edit/Pose/último selecionado em
    Object Mode) pra uma StringProperty qualquer, em qualquer datablock
    ligado ao Armature ativo. Genérico -- reutilizável por qualquer
    submódulo que precise de um botão "pegar bone selecionado"."""

    bl_idname = "hytale.pick_bone_into_field"
    bl_label = "Pick Bone From Selection"
    description = tooltip("common.tooltip.pick_bone_into_field")
    bl_options = {"REGISTER", "UNDO"}

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
        register_localized_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        unregister_localized_class(cls)
