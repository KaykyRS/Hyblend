"""Auto-Rigger -- Collection Settings: bone collections + sections editáveis (HytaleBoneCollectionItem e operadores de lista)."""

from collections import deque

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList

from ..common import is_active_armature
from ..translations import localized_props, tooltip, tr

from .constants import (
    COLL_ATTACHMENTS,
    COLL_MAIN,
    COLL_MAIN_ARM_L,
    COLL_MAIN_ARM_R,
    COLL_MAIN_BODY,
    COLL_MAIN_CHAIN,
    COLL_MAIN_HEAD,
    COLL_MAIN_LEG_L,
    COLL_MAIN_LEG_R,
    COLL_MAIN_ROOT,
    COLL_MAIN_SPINE,
    COLL_MAIN_TEXTURE_PICKER,
    SUFFIX_CTRL,
)

from .helpers import _find_bone_collection_anywhere, _redraw_all_areas, control_name, default_root_bone_name, ensure_bone_collection


def _on_collection_name_update(self, context):
    """Renomear uma entrada mantém tudo em sincronia: atualiza qualquer
    `collection_override_name` (Bone Settings) que apontava pro nome
    antigo, e renomeia a bone collection REAL junto (se já existir) --
    sem isso, o real ficava órfão com o nome antigo enquanto o próximo
    "Create Rig" criava uma collection nova e vazia com o nome
    atualizado, e os bones pareciam "sumir" (bug real relatado). Se já
    existir outra collection real com o nome novo, não força o rename
    (evita colisão silenciosa), só avisa no console."""
    old_name = self.get("previous_name", "")
    new_name = self.name
    if old_name and old_name != new_name and self.entry_type == "COLLECTION":
        obj = context.active_object
        armature = obj.data if is_active_armature(context) else None
        if armature is not None:
            renamed = 0
            for chain_item in getattr(armature, "hytale_ik_chains", []):
                if chain_item.get("collection_override_name", None) == old_name:
                    chain_item["collection_override_name"] = new_name
                    renamed += 1
            real_coll = _find_bone_collection_anywhere(armature, old_name)
            if real_coll is not None:
                colliding = _find_bone_collection_anywhere(armature, new_name)
                if colliding is not None and colliding.name != real_coll.name:
                    print(
                        f"[Hyblend] Collection Settings: renamed '{old_name}' to '{new_name}', but a real bone "
                        f"collection named '{new_name}' already exists on '{armature.name}' -- couldn't rename "
                        f"the real collection automatically (would collide). Merge or pick another name by hand."
                    )
                else:
                    real_coll.name = new_name
            if renamed or real_coll is not None:
                _redraw_all_areas(context)
    self["previous_name"] = new_name


def _on_collection_grid_update(self, context):
    obj = context.active_object
    if is_active_armature(context):
        sync_bone_collection_order(obj.data)
        _redraw_all_areas(context)


# "Section" é um TIPO de entrada dentro da mesma lista de Collection
# Settings (não uma lista separada). `entry_type` decide o que a
# entrada é; `parent` é o mesmo campo pras duas (Section pai pra uma
# Collection, ou Section-mãe pra outra Section). SECTION_ROOT é o
# sentinel de "nível raiz"/"não escolhida".
SECTION_ROOT = "__SECTION_ROOT__"

# Bug real corrigido ("passar o mouse muda a Bone Collection sozinho"):
# o Blender só guarda um ponteiro cru pras strings do último `items`
# computado de um EnumProperty dinâmico -- devolver uma lista NOVA a
# cada chamada e deixá-la ser coletada pelo GC antes do Blender acabar
# de usá-la é use-after-free. A correção óbvia (mutar uma ÚNICA lista
# compartilhada no lugar) criava outro bug: várias dropdowns
# desenhadas ao mesmo tempo liam a MESMA lista, e um redraw de uma
# (até por hover, pra tooltip) trocava o conteúdo debaixo da outra.
# Fix: pool com janela deslizante (deque) mantendo várias listas
# NOVAS vivas ao mesmo tempo, nenhuma delas nunca mutada depois de
# criada.
_collection_parent_enum_cache_pool = deque(maxlen=128)


def _resolve_armature_for_enum_context(context):
    """Resolve o Armature (dado edit_object > active_object) a partir de um
    `context` que pode ser None (chamado em tempo de registro, pra validar
    default= de EnumProperty) -- daí os getattr(..., None) defensivos, em
    vez de context.edit_object/active_object direto. Compartilhado pelos
    dois callbacks items= de EnumProperty abaixo."""
    armature = None
    edit_obj = getattr(context, "edit_object", None)
    if edit_obj is not None and edit_obj.type == "ARMATURE":
        armature = edit_obj.data
    if armature is None:
        obj = getattr(context, "active_object", None)
        if obj is not None and obj.type == "ARMATURE":
            armature = obj.data
    return armature


def _collection_parent_enum_items(self, context):
    """items= de HytaleBoneCollectionItem.parent -- só outras Sections,
    mais o sentinel SECTION_ROOT. Nunca lista uma Collection (Collection
    não aninha em Collection, ver _resolve_collection_parent). Chamado
    com self=None/context=None em tempo de registro, pra validar
    default=0 -- daí os getattr(..., None) abaixo."""
    armature = _resolve_armature_for_enum_context(context)

    exclude_name = getattr(self, "name", None)

    items = [
        (SECTION_ROOT, "Root / None", "Top level (for a Section) or falls back to 'Main' (for a Collection)")
    ]
    if armature is not None:
        for entry in armature.hytale_bone_collections:
            if not entry.name or entry.name == exclude_name or entry.entry_type != "SECTION":
                continue
            items.append((entry.name, entry.name, f"Show under '{entry.name}'"))
    _collection_parent_enum_cache_pool.append(items)
    return items


def _section_sort_key(entry):
    """Ordem entre Sections irmãs (mesmo parent) -- sem `column`,
    Sections só empilham verticalmente."""
    return (entry.row, entry.name)


def _iter_sections_in_order(armature):
    """Percorre as Sections em ordem de árvore (depth-first): raízes
    primeiro por _section_sort_key, cada uma seguida das próprias
    filhas. Guarda contra ciclo. Devolve (section, depth) -- depth só
    é usado por interface.py pra indentar visualmente."""
    by_parent = {}
    for entry in armature.hytale_bone_collections:
        if entry.entry_type != "SECTION" or not entry.name:
            continue
        parent_name = (entry.parent or "").strip()
        if not parent_name or parent_name == SECTION_ROOT:
            parent_name = SECTION_ROOT
        by_parent.setdefault(parent_name, []).append(entry)

    def walk(parent_name, visited, depth):
        for sec in sorted(by_parent.get(parent_name, []), key=_section_sort_key):
            if sec.name in visited:
                continue  # ciclo detectado
            yield (sec, depth)
            yield from walk(sec.name, visited | {sec.name}, depth + 1)

    yield from walk(SECTION_ROOT, frozenset(), 0)


def _resolve_collection_section_name(armature, item):
    """Section onde `item` deve aparecer na aba Animation: item.parent
    se apontar pra uma Section que existe, senão a Section "Main" (por
    NOME, não por ordem -- fix de bug real: o fallback antigo era "a
    primeira Section por ordem", o que fazia qualquer Section nova ou
    reordenada "roubar" collections não atribuídas explicitamente).
    Só cai pra "primeira por ordem" se nem "Main" existir mais."""
    name = (item.parent or "").strip()
    if name and name != SECTION_ROOT and any(
        e.name == name and e.entry_type == "SECTION" for e in armature.hytale_bone_collections
    ):
        return name
    default_section = next(
        (e for e in armature.hytale_bone_collections if e.entry_type == "SECTION" and e.name == COLL_MAIN), None
    )
    if default_section is not None:
        return default_section.name
    sections = sorted(
        (e for e in armature.hytale_bone_collections if e.entry_type == "SECTION"), key=_section_sort_key
    )
    return sections[0].name if sections else COLL_MAIN


def _bone_collection_item_props(lang):
    return {
        "name": StringProperty(
            name="Name",
            description=tr("rigger.prop.bone_collection_item_name", lang),
            default="Collection",
            update=_on_collection_name_update,
        ),
        # Campo-sombra escondido: guarda o nome ANTES do rename, já que
        # update= de uma StringProperty só recebe o valor novo.
        "previous_name": StringProperty(
            name="Name (previous, internal)",
            description="Internal -- tracks the name before a rename, so cross-references can follow along. Not shown in the UI.",
            default="",
            options={"HIDDEN"},
        ),
        "entry_type": EnumProperty(
            name="Type",
            items=[
                (
                    "COLLECTION",
                    "Collection",
                    tr("rigger.prop.bone_collection_item_entry_type_item_collection", lang),
                ),
                (
                    "SECTION",
                    "Section",
                    tr("rigger.prop.bone_collection_item_entry_type_item_section", lang),
                ),
            ],
            default="COLLECTION",
        ),
        "parent": EnumProperty(
            name="Parent",
            description=tr("rigger.prop.bone_collection_item_parent", lang),
            items=_collection_parent_enum_items,
            default=0,
        ),
        # Só controla se o botão de mostrar/esconder aparece na aba
        # Animation -- não afeta a collection em si.
        "show_in_animation_tab": BoolProperty(
            name="Show in Animation Tab",
            description=tr("rigger.prop.bone_collection_item_show_in_animation_tab", lang),
            default=True,
        ),
        # Layout em grade: mesmo row = lado a lado, ordenado por column
        # (empate desempata por nome). Relativos aos IRMÃOS (mesmo
        # parent), não à lista inteira. Pra uma Section só row importa.
        "row": IntProperty(
            name="Row",
            description=tr("rigger.prop.bone_collection_item_row", lang),
            default=0, min=0,
            update=_on_collection_grid_update,
        ),
        "column": IntProperty(
            name="Column",
            description=tr("rigger.prop.bone_collection_item_column", lang),
            default=0, min=0,
            update=_on_collection_grid_update,
        ),
    }


@localized_props(_bone_collection_item_props)
class HytaleBoneCollectionItem(PropertyGroup):
    pass


# Mesmo bug/fix do pool de _collection_parent_enum_cache_pool acima.
_bone_collection_enum_cache_pool = deque(maxlen=128)

# Identificador do item "Auto" do dropdown de Collection. Precisa ser
# um valor de verdade, não "" -- EnumProperty com item de identificador
# vazio faz o próprio botão do dropdown mostrar em branco (bug/quirk
# conhecido do Blender, foi exatamente o sintoma relatado). Todo código
# que lê collection_override compara contra esta constante.
COLLECTION_OVERRIDE_AUTO = "AUTO"


def _bone_collection_enum_items(self, context):
    # context=None em tempo de registro (ver EnumProperty default=) --
    # getattr(..., None) evita AttributeError nesse momento.
    armature = _resolve_armature_for_enum_context(context)

    items = [
        (COLLECTION_OVERRIDE_AUTO, "Auto (default)",
         "Use the built-in collection for this chain type (Arm L/Arm R/Leg L/Leg R/Head/Spine/Main-Tail)")
    ]
    if armature is not None:
        for item in armature.hytale_bone_collections:
            if not item.name or item.entry_type != "COLLECTION":
                continue
            section_label = _resolve_collection_section_name(armature, item)
            items.append(
                (item.name, item.name, f"Assign to '{item.name}' (in Section '{section_label}')")
            )
    _bone_collection_enum_cache_pool.append(items)
    return items


def _collection_override_get(self):
    """Bug real corrigido: o valor guardado de verdade num EnumProperty
    com `items` dinâmico é a POSIÇÃO NUMÉRICA na lista, não o
    identificador -- inserir uma collection nova antes de "Head Left"
    na lista empurrava a posição salva pra outra collection, sem
    aviso. Fix: guarda o NOME de verdade numa StringProperty escondida
    (collection_override_name); o índice pro Enum é recalculado na
    hora, contra a lista atual."""
    items = _bone_collection_enum_items(self, bpy.context)
    stored = self.get("collection_override_name", None)
    if stored is None:
        # Migração best-effort pra entradas salvas antes desta correção
        # -- só existe o índice cru antigo.
        legacy_index = self.get("collection_override", 0)
        stored = items[legacy_index][0] if 0 <= legacy_index < len(items) else COLLECTION_OVERRIDE_AUTO
    for index, entry in enumerate(items):
        if entry[0] == stored:
            return index
    return 0  # nome guardado não existe mais -- cai em "Auto (default)"


def _collection_override_set(self, value):
    items = _bone_collection_enum_items(self, bpy.context)
    self["collection_override_name"] = items[value][0] if 0 <= value < len(items) else COLLECTION_OVERRIDE_AUTO


# (nome, row, column) -- layout default da aba Animation, como dado em
# vez de código fixo. Também usado por "Reset Row/Column to Defaults".
_DEFAULT_BONE_COLLECTION_GRID = (
    (COLL_MAIN_HEAD, 0, 0),
    (COLL_MAIN_SPINE, 1, 0),
    (COLL_MAIN_BODY, 2, 0),
    (COLL_MAIN_ARM_R, 3, 0),
    (COLL_MAIN_ARM_L, 3, 1),
    (COLL_MAIN_LEG_R, 4, 0),
    (COLL_MAIN_LEG_L, 4, 1),
    (COLL_MAIN_ROOT, 5, 0),
    (COLL_MAIN_CHAIN, 6, 0),
    (COLL_ATTACHMENTS, 7, 0),
    # COLL_MAIN_TEXTURE_PICKER de propósito NÃO está aqui: diferente
    # dos outros (estrutura básica de todo personagem), Texture Picker
    # é opt-in -- só deve aparecer se houver de fato uma cadeia
    # TEXTURE_PICKER configurada (ver ensure_texture_picker_collection_entry,
    # única fonte de verdade pra essa entrada). Bug real corrigido:
    # incluir aqui fazia TODO personagem ganhar a entrada à toa.
)


def ensure_default_bone_collections(armature):
    """Semeia hytale_bone_collections com as 10 entradas fixas (Head/
    Spine/Body/Arm L/R/Leg L/R/Root/Tail/Attachments) + a Section
    "Main" -- só na primeira vez (hytale_bone_collections_initialized).
    Depois disso o usuário pode apagar/reordenar à vontade sem que
    voltem sozinhas. Chamada de dentro de execute() de operador ou do
    handler automático -- nunca de draw() (Blender recusa escrever em
    dados de ID nesse contexto)."""
    if armature.hytale_bone_collections_initialized:
        return
    main_section = armature.hytale_bone_collections.add()
    main_section.name = "Main"
    main_section.entry_type = "SECTION"
    main_section.parent = SECTION_ROOT
    main_section.row = 0
    for name, row, column in _DEFAULT_BONE_COLLECTION_GRID:
        item = armature.hytale_bone_collections.add()
        item.name = name
        item.row = row
        item.column = column
    armature.hytale_bone_collections_initialized = True


def ensure_texture_picker_collection_entry(armature):
    """Backfill pra armatures que já existiam antes de Texture Picker
    virar opt-in: adiciona a entrada só se (a) existir alguma cadeia
    TEXTURE_PICKER usando a collection default de verdade (não
    redirecionada por collection_override) e (b) a entrada ainda não
    existir. Sempre um append no fim, idempotente. Chamada logo depois
    de ensure_default_bone_collections em RIG_OT_hytale_generate_rig."""
    has_texture_picker_chain = any(
        getattr(item, "chain_type", None) == "TEXTURE_PICKER"
        and (getattr(item, "collection_override", "") or "").strip() in ("", COLLECTION_OVERRIDE_AUTO)
        for item in getattr(armature, "hytale_ik_chains", [])
    )
    if not has_texture_picker_chain:
        return
    already_present = any(
        item.name == COLL_MAIN_TEXTURE_PICKER and item.entry_type == "COLLECTION"
        for item in armature.hytale_bone_collections
    )
    if already_present:
        return
    item = armature.hytale_bone_collections.add()
    item.name = COLL_MAIN_TEXTURE_PICKER
    item.row = 8
    item.column = 0


def ensure_default_bone_section_backfill(armature):
    """Backfill pra armatures que já tinham Collection Settings
    inicializado antes de "Section" virar um tipo de entrada nesta
    mesma lista -- sem nenhuma Section "Main", o fallback de
    _resolve_collection_section_name cai pra "a primeira Section por
    ordem", e a única existente (criada na mão pelo usuário) "rouba"
    tudo que devia estar em Main. Só adiciona se não existir NENHUMA
    Section ainda; insere no topo da lista (clareza visual)."""
    has_section = any(e.entry_type == "SECTION" for e in armature.hytale_bone_collections)
    if has_section:
        return
    item = armature.hytale_bone_collections.add()
    item.name = "Main"
    item.entry_type = "SECTION"
    item.parent = SECTION_ROOT
    item.row = 0
    armature.hytale_bone_collections.move(len(armature.hytale_bone_collections) - 1, 0)


def ensure_default_bone_collection_entries(armature):
    """Backfill pra quando o usuário apagou uma das 10 entradas default
    de Collection Settings (só a config -- a collection real de bones
    continua sendo recriada normalmente em "Create Rig" de qualquer
    jeito, o que sumia era só o BOTÃO na aba Animation). Só adiciona o
    que falta, nunca mexe no row/column de quem já existe (diferente
    de "Reset Row/Column to Defaults", que é ação explícita e pode
    sobrescrever). Exclui Texture Picker (tratado à parte, opt-in).
    Devolve quantas entradas foram adicionadas."""
    existing_names = {item.name for item in armature.hytale_bone_collections}
    added = 0
    for name, row, column in _DEFAULT_BONE_COLLECTION_GRID:
        if name == COLL_MAIN_TEXTURE_PICKER:
            continue
        if name in existing_names:
            continue
        item = armature.hytale_bone_collections.add()
        item.name = name
        item.row = row
        item.column = column
        added += 1
    return added


def _collection_sort_key(item):
    """(row, column, name) -- ordenação centralizada, usada em todo
    lugar que decide a posição de exibição de uma collection (painel
    nativo via sync_bone_collection_order, as duas boxes da aba
    Animation). Relativa aos irmãos (mesmo parent)."""
    return (item.row, item.column, item.name)


def _resolve_collection_parent(armature, item=None, visited=None):
    """Aninhamento real de bone collection não existe mais -- vira
    puramente "Sections", visual só na aba Animation. Toda collection
    criada por Collection Settings fica sempre plana, direto embaixo
    de Main de verdade. `item`/`visited` continuam nos parâmetros só
    por compatibilidade com quem já chama, nenhum dos dois é usado."""
    return ensure_bone_collection(armature, COLL_MAIN)


def resolve_collection_override_target(armature, target_name):
    """Resolve `target_name` (nome de uma entrada de Collection
    Settings) pra uma bone collection real, só se existir e for do
    tipo Collection. None se não corresponder a nada válido -- o
    chamador decide o fallback."""
    settings_item = next(
        (c for c in armature.hytale_bone_collections if c.name == target_name and c.entry_type == "COLLECTION"),
        None,
    )
    if settings_item is None:
        return None
    parent = _resolve_collection_parent(armature, settings_item)
    return ensure_bone_collection(armature, target_name, parent=parent)


def _head_spine_bone_names(item):
    """Nomes de bone configurados numa entrada HEAD/SPINE/ATTACHMENTS/
    ROOT/TEXTURE_PICKER (só os campos preenchidos, respeitando os *_count) --
    [] pra qualquer outro chain_type."""
    if item.chain_type == "HEAD":
        slots = [item.neck_bone_1, item.neck_bone_2, item.neck_bone_3, item.neck_bone_4, item.neck_bone_5]
        names = slots[: item.neck_count] + [item.head_bone, item.head_end_bone]
    elif item.chain_type == "SPINE":
        slots = [item.spine_bone_1, item.spine_bone_2, item.spine_bone_3, item.spine_bone_4]
        names = [item.pelvis_bone] + slots[: max(0, item.spine_count - 1)]
    elif item.chain_type == "ATTACHMENTS":
        names = [getattr(item, f"attachment_bone_{i}") for i in range(1, item.attachments_count + 1)]
    elif item.chain_type == "ROOT":
        # Slot "New Bone" com o campo vazio usa o nome padrão -- é com
        # esse nome que o bone é criado (ver resolve_root_slots).
        names = []
        for slot in range(1, item.root_count + 1):
            name = (getattr(item, f"root_bone_{slot}", "") or "").strip()
            if name.endswith(SUFFIX_CTRL):
                name = name[: -len(SUFFIX_CTRL)]
            if not name and getattr(item, f"root_create_{slot}", False):
                name = default_root_bone_name(slot)
            names.append(name)
    elif item.chain_type == "TEXTURE_PICKER":
        extra_slots = [getattr(item, f"texture_picker_extra_bone_{i}") for i in range(1, item.texture_picker_extra_bone_count + 1)]
        names = [item.texture_picker_bone, item.texture_picker_ui_parent_bone] + extra_slots
    else:
        return []
    return list(dict.fromkeys(n for n in names if n))


def _spine_ctrl_override_transform_bone_name(armature):
    """Nome do bone _CTRL do último bone preenchido na entrada SPINE,
    pra servir de Override Transform do custom shape de
    root.spine_CTRL -- o widget continua na posição/tamanho de sempre,
    só a orientação passa a copiar a do último bone do Spine. None se
    não houver SPINE configurada."""
    spine_item = next((it for it in armature.hytale_ik_chains if it.chain_type == "SPINE"), None)
    if spine_item is None:
        return None
    names = _head_spine_bone_names(spine_item)
    if not names:
        return None
    return control_name(armature, names[-1], SUFFIX_CTRL)


def sync_bone_collection_order(armature):
    """Reordena as bone collections REAIS do Blender pra bater com a
    ordem de Collection Settings, via child_number. Aninhamento real
    não existe mais -- a ordem vem da árvore de Sections (decide o
    bloco) + _collection_sort_key dentro de cada bloco; o resultado
    plano vira o child_number sequencial de Main. Só reordena entradas
    que já existem de verdade (sem erro se "Create Rig" nunca rodou).
    Chamada no fim de "Create Rig" e direto pelos operadores Add/
    Remove/Move, pra refletir no painel nativo na hora."""
    main_coll = _find_bone_collection_anywhere(armature, COLL_MAIN)
    if main_coll is None:
        return  # rig ainda não gerado

    by_section = {}
    for item in armature.hytale_bone_collections:
        if not item.name or item.entry_type != "COLLECTION":
            continue
        section_name = _resolve_collection_section_name(armature, item)
        by_section.setdefault(section_name, []).append(item)

    ordered_items = []
    for sec, _depth in _iter_sections_in_order(armature):
        ordered_items.extend(sorted(by_section.get(sec.name, []), key=_collection_sort_key))
    # Rede de segurança pro caso raro de uma collection não bater com
    # nenhuma Section percorrida -- entra no fim, na ordem que já estava.
    seen_names = {i.name for i in ordered_items}
    for names in by_section.values():
        for item in names:
            if item.name not in seen_names:
                ordered_items.append(item)
                seen_names.add(item.name)

    for target_index, child_item in enumerate(ordered_items):
        child = next((c for c in main_coll.children if c.name == child_item.name), None)
        if child is None:
            continue  # ainda não materializado de verdade
        try:
            if child.child_number != target_index:
                child.child_number = target_index
        except Exception:
            pass  # cosmético -- não impede o rig de funcionar


# Seed automático via handler de depsgraph_update_post, porque draw()
# não pode escrever em dados de ID ("Writing to ID classes in this
# context is not allowed"). Propositalmente barato: só olha o objeto
# ATIVO, e a primeira linha de ensure_default_bone_collections já sai
# fora se já inicializado -- praticamente grátis depois da 1ª vez.


def _seed_active_armature_bone_collections(scene=None, depsgraph=None):
    obj = bpy.context.active_object
    if not is_active_armature(bpy.context):
        return
    armature = obj.data
    if not armature.hytale_bone_collections_initialized:
        ensure_default_bone_collections(armature)


def register_bone_collection_defaults_handler():
    if _seed_active_armature_bone_collections not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_seed_active_armature_bone_collections)


def unregister_bone_collection_defaults_handler():
    if _seed_active_armature_bone_collections in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_seed_active_armature_bone_collections)


class RIG_OT_hytale_bone_collection_load_defaults(Operator):
    """Chama ensure_default_bone_collections() de dentro de execute()
    (draw() não pode escrever em dados de ID). Botão só aparece
    enquanto a lista nunca foi inicializada pra este armature."""

    bl_idname = "armature.hytale_bone_collection_load_defaults"
    bl_label = "Load Default Collections"
    description = tooltip("rigger.tooltip.bone_collection_load_defaults")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and not obj.data.hytale_bone_collections_initialized

    def execute(self, context):
        ensure_default_bone_collections(context.active_object.data)
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_OT_hytale_bone_collection_reset_grid(Operator):
    """Corrige armatures cujas 10 entradas default foram criadas antes
    de Row/Column existir como campo (ficam travadas em 0/0 pra
    sempre). Reescreve row/column de quem já existe E re-adiciona
    (via ensure_default_bone_collection_entries) qualquer default que
    tenha sido apagado -- nunca mexe em entradas custom."""

    bl_idname = "armature.hytale_bone_collection_reset_grid"
    bl_label = "Reset Row/Column to Defaults"
    description = tooltip("rigger.tooltip.bone_collection_reset_grid")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and len(obj.data.hytale_bone_collections) > 0

    def execute(self, context):
        armature = context.active_object.data
        grid_by_name = {name: (row, column) for name, row, column in _DEFAULT_BONE_COLLECTION_GRID}
        fixed = 0
        for item in armature.hytale_bone_collections:
            grid = grid_by_name.get(item.name)
            if grid is None:
                continue  # nome custom -- não mexe
            item.row, item.column = grid
            fixed += 1
        added = ensure_default_bone_collection_entries(armature)
        # Texture Picker tratado à parte -- só volta se houver de fato
        # uma cadeia TEXTURE_PICKER configurada.
        before = len(armature.hytale_bone_collections)
        ensure_texture_picker_collection_entry(armature)
        if len(armature.hytale_bone_collections) > before:
            added += 1
        sync_bone_collection_order(armature)
        _redraw_all_areas(context)
        self.report({"INFO"}, f"Reset Row/Column on {fixed} built-in collection(s), re-added {added} missing.")
        return {"FINISHED"}


def _bone_collection_add_props(lang):
    return {
        "collection_name": StringProperty(name="Name", default="Collection"),
        "entry_type": EnumProperty(
            name="Type",
            items=[
                (
                    "COLLECTION",
                    "Collection",
                    tr("rigger.prop.bone_collection_add_entry_type_item_collection", lang),
                ),
                (
                    "SECTION",
                    "Section",
                    tr("rigger.prop.bone_collection_add_entry_type_item_section", lang),
                ),
            ],
            default="COLLECTION",
        ),
        "parent": EnumProperty(
            name="Parent",
            items=_collection_parent_enum_items,
            default=0,
        ),
    }


@localized_props(_bone_collection_add_props)
class RIG_OT_hytale_bone_collection_add(Operator):
    """Abre um dialog (nome + Type + Parent) e adiciona uma entrada
    nova -- Collection ou Section, mesma lista."""

    bl_idname = "armature.hytale_bone_collection_add"
    bl_label = "Add Bone Collection / Section"
    description = tooltip("rigger.tooltip.bone_collection_add")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return is_active_armature(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "collection_name")
        layout.prop(self, "entry_type")
        layout.prop(self, "parent")

    def execute(self, context):
        armature = context.active_object.data
        name = self.collection_name.strip()
        if not name:
            self.report({"ERROR"}, "Name can't be empty.")
            return {"CANCELLED"}
        if name.upper() == COLLECTION_OVERRIDE_AUTO:
            self.report({"ERROR"}, f"'{name}' is a reserved name (used internally for 'Auto (default)') -- pick another.")
            return {"CANCELLED"}
        if name == SECTION_ROOT:
            self.report({"ERROR"}, f"'{name}' is a reserved name -- pick another.")
            return {"CANCELLED"}
        if any(c.name == name for c in armature.hytale_bone_collections):
            self.report({"ERROR"}, f"An entry named '{name}' already exists in this list.")
            return {"CANCELLED"}
        ensure_default_bone_collections(armature)
        ensure_default_bone_section_backfill(armature)
        item = armature.hytale_bone_collections.add()
        item.name = name
        item.entry_type = self.entry_type
        item.parent = self.parent
        armature.hytale_bone_collections_index = len(armature.hytale_bone_collections) - 1
        sync_bone_collection_order(armature)
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_OT_hytale_bone_collection_remove(Operator):
    """Remove uma entrada pelo índice (padrão: a ativa). Só tira da
    lista de config -- a collection real (se já materializada) e os
    bones nela continuam intactos; cadeias que apontavam pra ela caem
    de volta pro default (Auto) no próximo "Create Rig". Apagar a
    última Section restante é permitido -- sem nenhuma, toda Collection
    cai num grupo "Root" implícito na aba Animation."""

    bl_idname = "armature.hytale_bone_collection_remove"
    bl_label = "Remove Bone Collection"
    description = tooltip("rigger.tooltip.bone_collection_remove")
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and len(obj.data.hytale_bone_collections) > 0

    def execute(self, context):
        armature = context.active_object.data
        collections = armature.hytale_bone_collections
        index = self.index if self.index >= 0 else armature.hytale_bone_collections_index
        if 0 <= index < len(collections):
            collections.remove(index)
            armature.hytale_bone_collections_index = max(0, min(armature.hytale_bone_collections_index, len(collections) - 1))
        sync_bone_collection_order(armature)
        _redraw_all_areas(context)
        return {"FINISHED"}


def _bone_collection_move_props(lang):
    return {
        "direction": EnumProperty(
            items=(
                ("UP", "Up", tr("rigger.prop.bone_collection_move_direction_item_up", lang)),
                ("DOWN", "Down", tr("rigger.prop.bone_collection_move_direction_item_down", lang)),
            ),
            default="UP",
        ),
    }


@localized_props(_bone_collection_move_props)
class RIG_OT_hytale_bone_collection_move(Operator):
    """Reordena uma posição pra cima/baixo na lista inteira -- reflete
    imediatamente no painel nativo "Bone Collections", se já existir."""

    bl_idname = "armature.hytale_bone_collection_move"
    bl_label = "Move Bone Collection"
    description = tooltip("rigger.tooltip.bone_collection_move")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return is_active_armature(context) and len(obj.data.hytale_bone_collections) > 1

    def execute(self, context):
        armature = context.active_object.data
        collections = armature.hytale_bone_collections
        index = armature.hytale_bone_collections_index
        target = index - 1 if self.direction == "UP" else index + 1
        if not (0 <= target < len(collections)):
            return {"CANCELLED"}
        collections.move(index, target)
        armature.hytale_bone_collections_index = target
        sync_bone_collection_order(armature)
        _redraw_all_areas(context)
        return {"FINISHED"}


class RIG_UL_hytale_bone_collections(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if item.entry_type == "SECTION":
            row.prop(item, "name", text="", emboss=False, icon="OUTLINER_COLLECTION")
            parent_label = "Root" if item.parent in ("", SECTION_ROOT) else item.parent
            row.label(text=parent_label)
        else:
            row.prop(item, "name", text="", emboss=False, icon="GROUP_BONE")
            row.label(text=_resolve_collection_section_name(data, item))
