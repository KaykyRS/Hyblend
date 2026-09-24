"""Auto-Rigger -- "Rename Bones": renomeia os bones marcados no Bone
Settings pro padrão de nomes do Hytale (Player), pra que o espelhamento
L-/R- (pose flip do Blender, Mirror Shape) funcione em modelos com nomes
fora do padrão (ex. "bone.002" marcado como Arm L vira "L-Arm").

Dois modos (Armature.hytale_rename_mode):

  "All Bones": renomeia o bone ORIGINAL; tudo que o Create Rig gera
  deriva dele (L-Arm_CTRL, L-Arm_IK...). O nome de antes fica guardado em
  BONE_RENAMED_FROM_PROP (common.py) -- o botão de reverter volta pra
  ele, a opção "Use Original Names" do export .blockymodel/.blockyanim
  escreve ele no arquivo, e o import de animação/Attach acham o bone por
  ele.

  "Only CTRL": o ORG, o _MCH e as pontes mantêm o nome original; só os
  bones de CONTROLE (_CTRL, _IK, _Pole_CTRL, _Pole_Line) ganham o nome
  padrão. O nome padrão vira um apelido gravado no ORG (PROP_CONTROL_NAME)
  e o Create Rig monta os controles com ele (ver control_name() em
  helpers.py). Campos do Bone Settings não mudam (continuam no ORG).

Trocar de modo limpa os apelidos: um "All Bones" apaga todos (o ORG já
tem o nome padrão), e um "Only CTRL" regrava todos do zero.

"Revert" (RIG_OT_hytale_revert_bone_names, botão ao lado do modo):
desfaz os dois de uma vez -- ORG volta pro BONE_RENAMED_FROM_PROP e os
apelidos são apagados.

Padrão de nomes (Player):
  Arm:   Root Parent -> <S>Shoulder, Root Bone -> <S>Arm,
         meio -> <S>Forearm, <S>Forearm2..., Tip -> <S>Hand
  Leg:   Root Bone -> <S>Thigh, meio -> <S>Calf, <S>Calf2..., Tip -> <S>Foot
         (Root Parent da perna costuma ser o Pelvis -- nunca renomeado aqui)
  Spine: Pelvis, Belly, Chest, Chest2, Chest3
  Head:  Neck, Neck2..., Head, Head-End
  Chain: <Label>1, <Label>2... (Label da entrada, espaços viram "-")
  Root:  Origin, Root2, Root3...
  <S> = "L-"/"R-" pelo Side da entrada ("Center" = sem prefixo).
Attachments e Texture Picker não são renomeados.

Cada campo tem uma caixinha (rename_<campo>, padrão ligado) -- desligada
= o bone mantém o nome original. Os bones do MEIO de Arm/Leg/Chain (que
não têm campo próprio) seguem rename_chain_middle."""

import bpy
from bpy.types import Operator

from ..common import BONE_RENAMED_FROM_PROP, BONE_RIGGER_CREATED_PROP, is_active_armature
from ..translations import tooltip, tr, get_language
from .constants import (
    ATTACHMENTS_MAX_COUNT,
    BONE_ROOT_PELVIS,
    PROP_CONTROL_NAME,
    PROP_RIG_LAYER,
    ROOT_MAX_COUNT,
    SUFFIX_CTRL,
    TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT,
)
from .helpers import (
    CONTROL_LAYER_SUFFIXES,
    _GENERATED_LAYER_SUFFIXES,
    _redraw_all_areas,
    control_base,
    find_org_path,
    normalize_org_name,
    parent_override_candidates,
)
from .widgets import _bone_widget_name

RENAME_MODE_ALL_BONES = "ALL_BONES"
RENAME_MODE_ONLY_CTRL = "ONLY_CTRL"


def rename_mode(armature_data):
    return getattr(armature_data, "hytale_rename_mode", RENAME_MODE_ALL_BONES) or RENAME_MODE_ALL_BONES


# --- Campos renomeáveis e suas caixinhas ------------------------------

RENAME_MIDDLE_PROP = "rename_chain_middle"

# chain_type -> campos (StringProperty com nome de bone) que ganham
# caixinha de rename. A caixinha de cada um é f"rename_{campo}".
RENAMEABLE_FIELDS = {
    "ROOT": tuple(f"root_bone_{i}" for i in range(1, ROOT_MAX_COUNT + 1)),
    "HEAD": (*(f"neck_bone_{i}" for i in range(1, 6)), "head_bone", "head_end_bone"),
    "SPINE": ("pelvis_bone", *(f"spine_bone_{i}" for i in range(1, 5))),
    "ARM": ("parent_override", "root_bone", "tip_bone"),
    "LEG": ("root_bone", "tip_bone"),
    "CHAIN": ("root_bone", "tip_bone"),
}
# Tipos cujos bones "do meio" (entre Root e Tip) seguem a caixinha
# rename_chain_middle, desenhada ao lado do picker do Pole Reference. Na
# Chain (sem Pole) o meio segue a caixinha do Root (Start) -- uma
# corrente numerada não faz sentido renomeada pela metade.
MIDDLE_CHAIN_TYPES = ("ARM", "LEG")

# Todas as caixinhas (uma BoolProperty cada em HytaleIKChainItem, e
# também em _IK_CHAIN_JSON_FIELDS -- senão Save/Load de template as
# descarta em silêncio).
RENAME_TOGGLE_PROPS = tuple(
    dict.fromkeys(f"rename_{field}" for fields in RENAMEABLE_FIELDS.values() for field in fields)
) + (RENAME_MIDDLE_PROP,)

# Todos os campos de HytaleIKChainItem que guardam NOME DE BONE -- depois
# de renomear, qualquer um deles que aponte pro nome antigo é atualizado
# (inclusive Attachments/Texture Picker/câmera, que não são renomeados
# mas podem apontar pra um bone que foi).
BONE_NAME_FIELDS = (
    "root_bone", "tip_bone", "pole_bone", "parent_override",
    *(f"neck_bone_{i}" for i in range(1, 6)), "head_bone", "head_end_bone",
    "pelvis_bone", *(f"spine_bone_{i}" for i in range(1, 5)),
    "continuous_chain_link_bone", "head_camera_parent_bone",
    *(f"attachment_bone_{i}" for i in range(1, ATTACHMENTS_MAX_COUNT + 1)),
    "texture_picker_bone", "texture_picker_ui_parent_bone",
    *(f"texture_picker_extra_bone_{i}" for i in range(1, TEXTURE_PICKER_EXTRA_BONES_MAX_COUNT + 1)),
    *(f"root_bone_{i}" for i in range(1, ROOT_MAX_COUNT + 1)),
)

_LIMB_NAMES = {
    # (Root Bone, meio, Tip, Root Parent)
    "ARM": ("Arm", "Forearm", "Hand", "Shoulder"),
    "LEG": ("Thigh", "Calf", "Foot", None),
}
_SPINE_NAMES = ("Belly", "Chest", "Chest2", "Chest3")
_SIDE_PREFIX = {"LEFT": "L-", "RIGHT": "R-"}


# Campos que normalize_bone_fields NÃO toca: no Root Parent um "_CTRL"
# é legítimo (o template do Player usa "L-Shoulder_CTRL") e já resolve
# certo por parent_override_candidates.
_NORMALIZE_SKIP_FIELDS = ("parent_override",)


def normalize_bone_fields(armature_data):
    """Troca, em todo campo de nome de bone do Bone Settings, um bone
    GERADO (ex. "leg_front_right3_CTRL", pego pelo conta-gotas no Pose
    Mode) pelo ORG de onde ele nasceu. Devolve quantos campos mudaram.
    Rodado pelo Create Rig e pelo Rename (antes de apagar o rig -- depois
    disso o bone gerado não existe mais e o campo ficaria apontando pro
    nada, a cadeia inteira seria pulada)."""
    bones = armature_data.bones
    changed = 0
    for item in getattr(armature_data, "hytale_ik_chains", []):
        for field in BONE_NAME_FIELDS:
            if field in _NORMALIZE_SKIP_FIELDS:
                continue
            value = getattr(item, field, None)
            if not value:
                continue
            normalized = normalize_org_name(bones, value)
            if normalized != value:
                setattr(item, field, normalized)
                changed += 1
    return changed


def rename_toggle_prop(item, field):
    """Nome da caixinha de rename de `field` nesta entrada, ou None se
    o campo não é renomeável pro chain_type dela (UI usa pra decidir se
    desenha a caixinha ao lado do picker). Em Arm/Leg, a caixinha do
    Pole Reference é a rename_chain_middle -- controla o Pole e todos os
    bones do meio (Forearm/Calf...)."""
    if field == "pole_bone" and item.chain_type in ("ARM", "LEG"):
        return RENAME_MIDDLE_PROP
    if field in RENAMEABLE_FIELDS.get(item.chain_type, ()):
        return f"rename_{field}"
    return None


def _is_removed_by_clear(bone):
    """Bones que o "Remove Generated" apaga antes do rename (camadas
    geradas e roots criados pelo rigger) -- não são renomeados nem
    "seguram" um nome-alvo (o Create Rig recria os roots criados com o
    nome do campo)."""
    return bone.get(PROP_RIG_LAYER) is not None or bool(bone.get(BONE_RIGGER_CREATED_PROP))


def _numbered(base, index):
    """1º = base, 2º = base2, 3º = base3... (padrão do Player)."""
    return base if index == 1 else f"{base}{index}"


def _chain_label_base(item):
    label = (item.label or "").strip().replace(" ", "-")
    return label or "Chain"


def _strip_ctrl(name):
    name = (name or "").strip()
    return name[: -len(SUFFIX_CTRL)] if name.endswith(SUFFIX_CTRL) else name


def _enabled(item, field):
    return bool(getattr(item, f"rename_{field}", True))


def _limb_path(bones, item):
    """Caminho ORG Root->Tip (lista de nomes), ou só [root, tip] se não
    houver caminho (Validate/Create Rig já avisam disso)."""
    # normalize_org_name: o campo pode ainda apontar pra um bone gerado
    # (a prévia só lê -- quem corrige o campo é normalize_bone_fields).
    root_name = normalize_org_name(bones, item.root_bone)
    tip_name = normalize_org_name(bones, item.tip_bone)
    root = bones.get(root_name) if root_name else None
    if root is None:
        return []
    if not tip_name or bones.get(tip_name) is None:
        return [root.name]
    path = find_org_path(root, tip_name)
    if path is None:
        return [root.name, tip_name]
    return [b.name for b in path]


def build_rename_plan(armature_data):
    """(plano, avisos). plano = [(nome_atual, nome_novo)] só dos bones
    que MUDAM de nome, na ordem em que foram reivindicados. Não mexe em
    nada -- o operador aplica.

    Regras:
      - só bones ORG (sem hytale_rig_layer) que existem no Armature;
      - o primeiro campo que reivindica um bone vence (ordem da lista
        do Bone Settings);
      - caixinha desligada = o bone nem entra no plano (mantém o nome);
      - nome-alvo já usado (por outro bone renomeado agora, ou por um
        bone que não está sendo renomeado) ganha número: Head -> Head2."""
    bones = armature_data.bones
    items = list(getattr(armature_data, "hytale_ik_chains", []))
    claims = {}  # nome atual -> nome-base desejado
    warnings = []
    # Root Parent (ombro) fica pro FIM e só vale se UMA entrada pedir o
    # bone -- um pai compartilhado pelos dois braços (ex. "arms" no
    # Rayquaza) não é ombro de ninguém e mantém o nome.
    parent_requests = {}  # nome do bone -> [nome-alvo por entrada]

    def claim(bone_name, target):
        bone_name = normalize_org_name(bones, _strip_ctrl(bone_name))
        if not bone_name or bone_name in claims:
            return
        bone = bones.get(bone_name)
        if bone is None or _is_removed_by_clear(bone):
            return
        claims[bone_name] = target

    for item in items:
        chain_type = item.chain_type
        if chain_type == "ROOT":
            for slot in range(1, min(item.root_count, ROOT_MAX_COUNT) + 1):
                field = f"root_bone_{slot}"
                if _enabled(item, field):
                    claim(getattr(item, field, ""), "Origin" if slot == 1 else f"Root{slot}")
        elif chain_type == "HEAD":
            for i in range(1, min(item.neck_count, 5) + 1):
                field = f"neck_bone_{i}"
                if _enabled(item, field):
                    claim(getattr(item, field, ""), _numbered("Neck", i))
            if _enabled(item, "head_bone"):
                claim(item.head_bone, "Head")
            if _enabled(item, "head_end_bone"):
                claim(item.head_end_bone, "Head-End")
        elif chain_type == "SPINE":
            if _enabled(item, "pelvis_bone"):
                claim(item.pelvis_bone, "Pelvis")
            for i in range(1, min(max(0, item.spine_count - 1), 4) + 1):
                field = f"spine_bone_{i}"
                if _enabled(item, field):
                    claim(getattr(item, field, ""), _SPINE_NAMES[i - 1])
        elif chain_type in ("ARM", "LEG"):
            root_name, middle_name, tip_name, parent_name = _LIMB_NAMES[chain_type]
            prefix = _SIDE_PREFIX.get(item.side, "")
            path = _limb_path(bones, item)
            middle_enabled = getattr(item, RENAME_MIDDLE_PROP, True)
            middle_count = 0
            for index, bone_name in enumerate(path):
                if index == 0:
                    if _enabled(item, "root_bone"):
                        claim(bone_name, prefix + root_name)
                elif index == len(path) - 1 and bone_name == normalize_org_name(bones, item.tip_bone):
                    if _enabled(item, "tip_bone"):
                        claim(bone_name, prefix + tip_name)
                else:
                    middle_count += 1
                    if middle_enabled:
                        claim(bone_name, prefix + _numbered(middle_name, index))
            # Pole Reference FORA do caminho Root->Tip (irmão, filho de
            # outro bone, ou cadeia que vai direto do Root pro Tip) -- mesma
            # caixinha dos bones do meio; ganha o próximo número livre.
            pole = normalize_org_name(bones, _strip_ctrl(item.pole_bone))
            if middle_enabled and pole and pole not in path:
                claim(pole, prefix + _numbered(middle_name, middle_count + 1))
            if parent_name and item.parent_override and _enabled(item, "parent_override"):
                candidates = parent_override_candidates(armature_data, item.parent_override)
                # Root Parent que resolve pro root.pelvis_CTRL é o Pelvis
                # (da Spine) -- nunca vira "Shoulder".
                if candidates and candidates[0] != BONE_ROOT_PELVIS:
                    parent_requests.setdefault(_strip_ctrl(item.parent_override), []).append(prefix + parent_name)
        elif chain_type == "CHAIN":
            base = _chain_label_base(item)
            path = _limb_path(bones, item)
            for index, bone_name in enumerate(path):
                if index == 0:
                    enabled = _enabled(item, "root_bone")
                elif index == len(path) - 1 and bone_name == normalize_org_name(bones, item.tip_bone):
                    enabled = _enabled(item, "tip_bone")
                else:
                    enabled = _enabled(item, "root_bone")  # meio da Chain segue o Start
                if enabled:
                    claim(bone_name, f"{base}{index + 1}")

    for bone_name, targets in parent_requests.items():
        if bone_name in claims:
            continue  # já tem papel próprio (ex. o Chest da Spine) -- esse nome vence, sem aviso
        if len(targets) == 1:
            claim(bone_name, targets[0])
        else:
            warnings.append(
                f"'{bone_name}' is the Root Parent of {len(targets)} entries -- kept its name (a shared "
                f"parent isn't one side's Shoulder)."
            )

    # Nomes finais únicos. Um bone que NÃO está sendo renomeado e já usa
    # o nome-alvo continua com ele -- o renomeado ganha número.
    kept_names = {b.name for b in bones if b.name not in claims and not _is_removed_by_clear(b)}
    used = set()
    plan = []
    for bone_name, base in claims.items():
        final = base
        counter = 2
        while final in used or final in kept_names:
            final = f"{base}{counter}"
            counter += 1
        if final != base:
            warnings.append(
                f"'{bone_name}' -> '{final}' (the standard name '{base}' is already taken by another bone)."
            )
        used.add(final)
        if final != bone_name:
            plan.append((bone_name, final))
    return plan, warnings


# --- Operador ----------------------------------------------------------

_PREVIEW_MAX_LINES = 25
_TEMP_PREFIX = "__hyblend_rename_"


def _rig_is_generated(armature_data):
    return any(_is_removed_by_clear(b) for b in armature_data.bones)


def _update_bone_fields(armature_data, mapping):
    """Troca, em TODA entrada do Bone Settings, qualquer campo de nome de
    bone que aponte pra um nome antigo (inclusive com "_CTRL" no fim,
    ex. Root Parent "L-Shoulder_CTRL")."""
    changed = 0
    for item in armature_data.hytale_ik_chains:
        for field in BONE_NAME_FIELDS:
            value = getattr(item, field, None)
            if not value:
                continue
            stripped = value.strip()
            new_value = None
            if stripped in mapping:
                new_value = mapping[stripped]
            elif stripped.endswith(SUFFIX_CTRL) and stripped[: -len(SUFFIX_CTRL)] in mapping:
                new_value = mapping[stripped[: -len(SUFFIX_CTRL)]] + SUFFIX_CTRL
            if new_value is not None and new_value != value:
                setattr(item, field, new_value)
                changed += 1
    return changed


def _rename_mesh_collections(armature_obj, mapping):
    """O importer separa as malhas por bone em sub-collections
    "<bone> - <armature>" -- acompanha o nome novo (cosmético)."""
    renamed = 0
    for old, new in mapping.items():
        coll = bpy.data.collections.get(f"{old} - {armature_obj.name}")
        if coll is not None:
            coll.name = f"{new} - {armature_obj.name}"
            renamed += 1
    return renamed


def _rename_widget_objects(armature_obj, mapping, suffixes=None):
    """As cópias de widget por personagem se chamam
    "WGT - <armature> - <bone gerado>" (ex. "... - arm_left_CTRL") e
    guardam as edições do Vertex Edit Mode. Sem acompanhar o nome novo,
    o Create Rig não acharia a cópia, criaria outra a partir do padrão e
    a edição do usuário se perderia (sobrando o objeto antigo). Renomeia
    a cópia de TODA camada gerada do bone (_CTRL, _IK, _Pole_CTRL...).
    Se já existir um objeto com o nome novo, não mexe (evita .001)."""
    renamed = 0
    for old, new in mapping.items():
        for suffix in (suffixes or _GENERATED_LAYER_SUFFIXES):
            widget = bpy.data.objects.get(_bone_widget_name(armature_obj.name, old + suffix))
            if widget is None:
                continue
            target = _bone_widget_name(armature_obj.name, new + suffix)
            if bpy.data.objects.get(target) is not None:
                continue
            widget.name = target
            renamed += 1
    return renamed


def _rename_org_bones(armature_data, plan, warnings, remember_old):
    """Aplica [(nome_atual, nome_novo)] nos bones ORG. Devolve
    {nome_antigo: nome_final}. remember_old=True (Rename): grava o nome
    de antes em BONE_RENAMED_FROM_PROP (só no primeiro rename -- o de
    verdade é o mais antigo). Um bone que termina com o próprio nome
    guardado (revert, ou rename que voltou ao original) perde a marca."""
    bones = armature_data.bones
    # Fase 1: nome temporário único -- permite TROCAR nomes entre dois
    # bones (ex. "R-Arm" marcado como Arm L e "L-Arm" como Arm R) sem um
    # roubar o nome do outro no meio do caminho.
    for index, (old, _new) in enumerate(plan):
        bone = bones[old]
        if remember_old and BONE_RENAMED_FROM_PROP not in bone.keys():
            bone[BONE_RENAMED_FROM_PROP] = old
        bone.name = f"{_TEMP_PREFIX}{index}"
    # Fase 2: nome final. Bone.name dispara o rename interno do Blender,
    # que também atualiza vertex groups das malhas, parent de objetos
    # presos no bone, constraints e caminhos de animação.
    mapping = {}
    for index, (old, new) in enumerate(plan):
        bone = bones[f"{_TEMP_PREFIX}{index}"]
        bone.name = new
        if bone.name != new:
            warnings.append(f"'{old}' ended up as '{bone.name}' (Blender kept '{new}' for another bone).")
        if bone.get(BONE_RENAMED_FROM_PROP) == bone.name:
            del bone[BONE_RENAMED_FROM_PROP]
        mapping[old] = bone.name
    return mapping


def _finish_org_rename(armature_obj, armature_data, mapping, prev_bases):
    """Depois de renomear ORGs: campos do Bone Settings, collections das
    malhas e cópias de widget (que estavam com o nome-base ANTIGO dos
    controles -- apelido, se havia, ou o nome antigo do ORG). Devolve
    quantos campos do Bone Settings mudaram."""
    fields_changed = _update_bone_fields(armature_data, mapping)
    _rename_mesh_collections(armature_obj, mapping)
    widget_mapping = {}
    for org, prev in prev_bases.items():
        new_base = mapping.get(org, org)
        if prev != new_base:
            widget_mapping[prev] = new_base
    _rename_widget_objects(armature_obj, widget_mapping)
    return fields_changed


def _clear_aliases(armature_data):
    """Apaga todo apelido de controle (Only CTRL). Devolve quantos havia."""
    count = 0
    for bone in armature_data.bones:
        if PROP_CONTROL_NAME in bone.keys():
            del bone[PROP_CONTROL_NAME]
            count += 1
    return count


def _clear_rig_for_rename(operator, armature_data):
    """Passo comum do Rename e do Revert: campo apontando pra bone gerado
    vira o ORG (ANTES de apagar o rig) e o rig gerado sai -- mesmo
    caminho do botão "Remove Generated" -> Only Rig."""
    normalized = normalize_bone_fields(armature_data)
    if normalized:
        operator.report(
            {"INFO"}, f"{normalized} Bone Settings field(s) pointed at control bones -- switched to the original bones."
        )
    if _rig_is_generated(armature_data):
        bpy.ops.armature.hytale_clear_generated_rig(mode="ONLY_RIG")


class RIG_OT_hytale_rename_bones(Operator):
    """Renomeia os bones marcados no Bone Settings pro padrão de nomes do
    Hytale (ver docstring do módulo). Se o rig já foi gerado, remove os
    bones gerados antes (mesmo que "Remove Generated" -> Only Rig) --
    depois é só rodar o Create Rig. Desfazível com Ctrl+Z."""

    bl_idname = "armature.hytale_rename_bones"
    bl_label = "Rename Bones"
    description = tooltip("rigger.tooltip.rename_bones")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        if getattr(obj.data, "hytale_shape_edit_mode", False):
            cls.poll_message_set("Finish Shape Edit Mode first.")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        lang = get_language(context)
        layout = self.layout
        # Recalculado a cada draw (barato) -- o Blender não garante que
        # a instância do operador seja a mesma entre invoke() e draw().
        armature_data = context.active_object.data
        only_ctrl = rename_mode(armature_data) == RENAME_MODE_ONLY_CTRL
        preview, _warnings = build_rename_plan(armature_data)
        if not preview:
            layout.label(text=tr("panel.rename_nothing", lang), icon="INFO")
            return
        title_key = "panel.rename_preview_title_ctrl" if only_ctrl else "panel.rename_preview_title"
        layout.label(text=tr(title_key, lang).format(count=len(preview)), icon="SORTALPHA")
        col = layout.column(align=True)
        for old, new in preview[:_PREVIEW_MAX_LINES]:
            # Only CTRL: o ORG fica igual -- mostra o nome do controle.
            shown = f"{new}_CTRL" if only_ctrl else new
            col.label(text=f"{old}  \u2192  {shown}")
        if len(preview) > _PREVIEW_MAX_LINES:
            col.label(text=tr("panel.rename_preview_more", lang).format(count=len(preview) - _PREVIEW_MAX_LINES))
        if _rig_is_generated(armature_data):
            layout.separator()
            layout.label(text=tr("panel.rename_will_clear", lang), icon="ERROR")

    def execute(self, context):
        obj = context.active_object
        armature_data = obj.data
        prev_mode = obj.mode
        only_ctrl = rename_mode(armature_data) == RENAME_MODE_ONLY_CTRL

        # Bones gerados, collections sob Main, Texture Picker e câmera
        # saem; Bone Settings/Collection Settings/widgets ficam.
        _clear_rig_for_rename(self, armature_data)
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bones = armature_data.bones
        # Nome-base ATUAL dos controles de cada ORG (apelido ou o próprio
        # nome) -- as cópias de widget por personagem estão com esse nome.
        prev_bases = {b.name: control_base(armature_data, b.name) for b in bones if not _is_removed_by_clear(b)}
        plan, warnings = build_rename_plan(armature_data)

        if only_ctrl:
            result = self._apply_only_ctrl(obj, armature_data, plan, prev_bases)
        else:
            result = self._apply_all_bones(obj, armature_data, plan, prev_bases, warnings)
        if result is None:
            self.report({"INFO"}, "Rename Bones: nothing to rename -- the marked bones already use the standard names.")
            self._restore_mode(obj, prev_mode)
            return {"FINISHED"}

        for warning in warnings:
            self.report({"WARNING"}, warning)
        self.report({"INFO"}, result)
        self._restore_mode(obj, prev_mode)
        _redraw_all_areas(context)
        return {"FINISHED"}

    def _apply_only_ctrl(self, obj, armature_data, plan, prev_bases):
        """Grava os apelidos. Zera TODOS antes (os que saíram do plano --
        caixinha desmarcada, entrada removida -- voltam pro nome do ORG)."""
        bones = armature_data.bones
        had_alias = any(b.get(PROP_CONTROL_NAME) for b in bones)
        if not plan and not had_alias:
            return None
        for bone in bones:
            if PROP_CONTROL_NAME in bone.keys():
                del bone[PROP_CONTROL_NAME]
        for org_name, alias in plan:
            bones[org_name][PROP_CONTROL_NAME] = alias
        widget_mapping = {
            prev: control_base(armature_data, org)
            for org, prev in prev_bases.items()
            if prev != control_base(armature_data, org)
        }
        _rename_widget_objects(obj, widget_mapping, CONTROL_LAYER_SUFFIXES)
        return (
            f"{len(plan)} bone(s) will get Hytale-named controls (e.g. '{plan[0][1]}_CTRL'); the original bones "
            f"keep their names. Run Create Rig to build the rig."
            if plan else "Control-name aliases cleared. Run Create Rig to build the rig."
        )

    def _apply_all_bones(self, obj, armature_data, plan, prev_bases, warnings):
        bones = armature_data.bones
        had_alias = any(b.get(PROP_CONTROL_NAME) for b in bones)
        # Trocar pra All Bones limpa os apelidos: o ORG passa a ter o nome
        # padrão, os controles seguem ele.
        for bone in bones:
            if PROP_CONTROL_NAME in bone.keys():
                del bone[PROP_CONTROL_NAME]
        if not plan:
            if had_alias:
                widget_mapping = {prev: org for org, prev in prev_bases.items() if prev != org}
                _rename_widget_objects(obj, widget_mapping, CONTROL_LAYER_SUFFIXES)
                return "Control-name aliases cleared (All Bones mode). Run Create Rig to build the rig."
            return None

        mapping = _rename_org_bones(armature_data, plan, warnings, remember_old=True)
        fields_changed = _finish_org_rename(obj, armature_data, mapping, prev_bases)
        return (
            f"Renamed {len(mapping)} bone(s) and updated {fields_changed} Bone Settings field(s). The old names "
            f"are remembered (revert button / 'Use Original Names' on export). Run Create Rig to build the rig "
            f"with the new names."
        )

    @staticmethod
    def _restore_mode(obj, prev_mode):
        if prev_mode in ("POSE", "EDIT") and obj.mode != prev_mode:
            bpy.ops.object.mode_set(mode=prev_mode)


# --- Revert --------------------------------------------------------------


def build_revert_plan(armature_data):
    """(renomes, apelidos) do que o Revert desfaz:
    renomes = [(nome_atual, nome_original)] dos ORG renomeados no modo
    All Bones; apelidos = [(nome_do_ORG, apelido)] do modo Only CTRL."""
    renames = []
    aliases = []
    for bone in armature_data.bones:
        if _is_removed_by_clear(bone):
            continue
        original = bone.get(BONE_RENAMED_FROM_PROP)
        if original and original != bone.name:
            renames.append((bone.name, original))
        alias = bone.get(PROP_CONTROL_NAME)
        if alias:
            aliases.append((bone.name, alias))
    return renames, aliases


class RIG_OT_hytale_revert_bone_names(Operator):
    """Desfaz o "Rename Bones" nos dois modos de uma vez: ORG renomeado
    (All Bones) volta pro BONE_RENAMED_FROM_PROP, apelidos de controle
    (Only CTRL) são apagados. Mesmo preparo do Rename (rig gerado sai
    antes; depois é só rodar o Create Rig). Desfazível com Ctrl+Z."""

    bl_idname = "armature.hytale_revert_bone_names"
    bl_label = "Revert Bone Names"
    description = tooltip("rigger.tooltip.revert_bone_names")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not is_active_armature(context):
            return False
        if getattr(obj.data, "hytale_shape_edit_mode", False):
            cls.poll_message_set("Finish Shape Edit Mode first.")
            return False
        renames, aliases = build_revert_plan(obj.data)
        if not renames and not aliases:
            cls.poll_message_set("Nothing to revert -- no bone was renamed.")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        lang = get_language(context)
        layout = self.layout
        armature_data = context.active_object.data
        renames, aliases = build_revert_plan(armature_data)
        lines = [(current, original) for current, original in renames]
        lines += [(f"{alias}{SUFFIX_CTRL}", f"{org}{SUFFIX_CTRL}") for org, alias in aliases]
        if not lines:
            layout.label(text=tr("panel.revert_nothing", lang), icon="INFO")
            return
        layout.label(text=tr("panel.revert_preview_title", lang).format(count=len(lines)), icon="LOOP_BACK")
        col = layout.column(align=True)
        for current, original in lines[:_PREVIEW_MAX_LINES]:
            col.label(text=f"{current}  →  {original}")
        if len(lines) > _PREVIEW_MAX_LINES:
            col.label(text=tr("panel.rename_preview_more", lang).format(count=len(lines) - _PREVIEW_MAX_LINES))
        if _rig_is_generated(armature_data):
            layout.separator()
            layout.label(text=tr("panel.rename_will_clear", lang), icon="ERROR")

    def execute(self, context):
        obj = context.active_object
        armature_data = obj.data
        prev_mode = obj.mode

        _clear_rig_for_rename(self, armature_data)
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bones = armature_data.bones
        prev_bases = {b.name: control_base(armature_data, b.name) for b in bones if not _is_removed_by_clear(b)}
        renames, _aliases = build_revert_plan(armature_data)
        aliases_cleared = _clear_aliases(armature_data)
        # Marca que sobrou apontando pro próprio nome -- só limpeza.
        for bone in bones:
            if bone.get(BONE_RENAMED_FROM_PROP) == bone.name:
                del bone[BONE_RENAMED_FROM_PROP]

        warnings = []
        mapping = _rename_org_bones(armature_data, renames, warnings, remember_old=False)
        # Nome original ocupado por outro bone (Blender deu ".001"): a
        # marca continua, pra um próximo Revert tentar de novo.
        for old, final in mapping.items():
            bone = bones.get(final)
            original = dict(renames).get(old)
            if bone is not None and original and final != original:
                bone[BONE_RENAMED_FROM_PROP] = original
        fields_changed = _finish_org_rename(obj, armature_data, mapping, prev_bases)

        for warning in warnings:
            self.report({"WARNING"}, warning)
        parts = []
        if mapping:
            parts.append(f"{len(mapping)} bone(s) back to their original names ({fields_changed} Bone Settings field(s) updated)")
        if aliases_cleared:
            parts.append(f"{aliases_cleared} control-name alias(es) cleared")
        self.report({"INFO"}, ("; ".join(parts) or "Nothing to revert") + ". Run Create Rig to build the rig.")
        if prev_mode in ("POSE", "EDIT") and obj.mode != prev_mode:
            bpy.ops.object.mode_set(mode=prev_mode)
        _redraw_all_areas(context)
        return {"FINISHED"}
