"""
anim_tools.py -- Auxiliares de Animação (aba "Animation" do N-Panel).
======================================================================

Este submódulo NÃO desenha nada -- só registra os operadores (e duas
funções de leitura pura) que a aba "Animation" do interface.py usa.
Mesmo espírito de rigger.py: interface.py é quem desenha os botões, este
arquivo só fornece o que os botões chamam.

Cobre, até agora:
  1. Toggle de visibilidade das Bone Collections de alto nível que
     rigger.py já cria (Head/Spine/Body/Arm L/Arm R/Leg L/Leg R/Root/
     Tail/Face/Attachments) -- não cria nenhuma collection nova, só
     mostra/esconde as que o Auto-Rigger já gera.
  2. FK/IK -- dois jeitos de trocar, propositalmente separados:
     - ANIM_OT_hytale_set_fk_ik (botões FK/IK da lista, por índice de
       cadeia): troca CRUA, só a influência -- não mexe na pose. Pode
       dar um "pulo" visual se FK e IK estiverem posados diferente.
     - ANIM_OT_hytale_snap_selected (botão único "Snap FK/IK", olha o
       bone ATIVO selecionado): iguala a pose do lado oposto ao
       selecionado E troca pra esse lado oposto, tudo de uma vez --
       ver identify_chain_from_bone/snap_chain_pose logo abaixo.

CAVEAT -- Pole Local/Global: o pole target já tem dois Child Of no rig
(um mirando na ponta da cadeia -- "Local", ativo por padrão -- outro no
Origin_CTRL -- "Global", influência 0 por padrão -- ver
CONSTRAINT_CHILD_OF_LOCAL/GLOBAL em rigger/rig.py), mas hoje NENHUM dos
dois tem custom property + driver pra trocar entre eles (fica fixo no
que foi gerado). snap_chain_pose() calcula a matrix corrigida pra
QUALQUER Child Of ativa nesses bones (ver _snap_matrix_through_
constraints, que compensa até o inverse_matrix do "Set Inverse" já
aplicado -- ver rigger/rig.py) -- então funciona corretamente não
importa qual das duas esteja ativa no momento. Se um dia isso ganhar um
switch de verdade (teria que nascer em rigger/rig.py, não aqui),
nenhuma mudança deveria ser necessária neste arquivo.

DEPENDÊNCIA -- este arquivo importa de `.rigger`:
    BONE_PROPERTIES, CONSTRAINT_CHILD_OF_GLOBAL, CONSTRAINT_CHILD_OF_LOCAL,
    SUFFIX_CTRL, SUFFIX_IK, SUFFIX_IK_MCH, SUFFIX_MCH, SUFFIX_POLE,
    find_org_path, switch_property_name
Todos precisam estar na lista de reexport de rigger/__init__.py (alguns
-- BONE_PROPERTIES, find_org_path, switch_property_name -- não estavam
lá originalmente; foram adicionados especificamente pra este arquivo
poder existir sem duplicar lógica que já mora em rigger/rig.py e
rigger/constants.py).

Visibilidade das Bone Collections é lida/escrita via
`armature.collections_all` (API nativa do Blender 4.0+, plana --
inclusive as aninhadas dentro de "Main"), então este arquivo NÃO precisa
importar os nomes de collection de rigger/constants.py: recebe o nome
(string) já pronto de quem desenha (interface.py), que é quem decide
QUAIS collections mostrar na lista.
"""

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Operator
from mathutils import Vector

from .rigger import (
    BONE_PROPERTIES,
    CONSTRAINT_CHILD_OF_GLOBAL,
    CONSTRAINT_CHILD_OF_LOCAL,
    SUFFIX_CTRL,
    SUFFIX_IK,
    SUFFIX_IK_MCH,
    SUFFIX_MCH,
    SUFFIX_POLE,
    find_org_path,
    switch_property_name,
)


def _redraw_all_areas(context):
    """Força o redraw de TODA área de TODA janela aberta. Mesmo problema
    (e mesmo fix) documentado em rigger/rig.py para outros botões que
    mudam um valor lido por um driver: escrever a custom property (ver
    ANIM_OT_hytale_set_fk_ik.execute) já recalcula o driver de
    influência/escala na hora (context.view_layer.update() cuida disso),
    mas o Blender não redesenha a viewport sozinho por causa disso --
    só quando QUALQUER outro evento (clicar num bone, por exemplo) força
    um redraw geral por outro motivo. Cópia local (não importada de
    rig.py) porque lá é uma função privada (prefixo "_"), fora do que
    rigger/__init__.py reexporta."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


# ---------------------------------------------------------------------------
# Bone Collections -- toggle de visibilidade
# ---------------------------------------------------------------------------


class ANIM_OT_hytale_toggle_collection_visibility(Operator):
    """Mostra/esconde uma bone collection do rig no viewport. Não muda
    nada de seleção/pose -- só o que fica desenhado. Funciona em
    qualquer nível de aninhamento (usa armature.collections_all, não
    armature.collections -- que só enxerga as de nível raiz)."""

    bl_idname = "armature.hytale_toggle_collection_visibility"
    bl_label = "Toggle Bone Collection Visibility"
    bl_description = "Show/hide this bone collection in the viewport"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty(
        description="Nome exato da bone collection (ex.: 'Arm L', 'Face') -- quem escolhe o valor é o "
        "interface.py, na hora de desenhar a lista"
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        armature = context.active_object.data
        coll = armature.collections_all.get(self.collection_name)
        if coll is None:
            # Rig ainda não gerado, ou essa collection específica não
            # existe nesse personagem (ex.: nenhuma cadeia Tail
            # configurada -- "Tail" nunca chegou a ser criada).
            self.report(
                {"WARNING"},
                f"Bone collection '{self.collection_name}' not found -- generate the rig first.",
            )
            return {"CANCELLED"}
        coll.is_visible = not coll.is_visible
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# FK/IK Switch + Snap -- por cadeia (armature.hytale_ik_chains)
# ---------------------------------------------------------------------------


def get_fk_ik_state(obj, item):
    """Leitura pura, sem efeito colateral: retorna 0 (FK), 1 (IK), ou
    None se esse switch ainda não existe (chain_type == TAIL -- não tem
    IK --, rig nunca gerado, ou entrada nova na lista que ainda não
    passou por "Create Rig"). Usada pelo interface.py só pra saber qual
    dos dois botões (FK/IK) desenhar destacado -- nunca escreve nada."""
    if item.chain_type == "TAIL":
        return None
    pose = obj.pose
    if pose is None:
        return None
    props_bone = pose.bones.get(BONE_PROPERTIES)
    if props_bone is None:
        return None
    prop_name = switch_property_name(item.tip_bone, item.side)
    value = props_bone.get(prop_name)
    if value is None:
        return None
    return 1 if value else 0


def _snap_matrix_through_constraints(context, pose_bone, target_matrix, constraint_names):
    """Escreve `target_matrix` em `pose_bone.matrix` de um jeito que
    dá o resultado final CORRETO mesmo com uma Child Of ativa
    (`constraint_names`, por nome -- a primeira com influência > 0 e
    subtarget válido é a usada; as outras são ignoradas).

    `pose_bone.matrix = valor` sozinho NÃO é "ciente" de constraints:
    ele calcula o canal local (matrix_basis) assumindo que mais nada
    vai mexer no bone depois -- mas a Child Of roda de novo assim que
    o depsgraph reavalia a pose. Uma primeira tentativa foi desativar a
    constraint, escrever, e reativar -- funciona SE con.inverse_matrix
    (gravado pelo "Set Inverse" que _apply_pole_childof_inverses já
    aplica na geração do rig) ainda corresponder à pose ATUAL do alvo
    -- mas ele foi calculado uma vez, no rest, e o alvo (ik_tip) acabou
    de ser movido por este mesmo Snap -- sobra um resíduo (era esse o
    "quase, mas não perfeito" -- só o "Set Inverse" manual, que
    recalcula esse valor, corrigia).

    A fórmula da Child Of (com Set Inverse já aplicado) é:
        final = target.matrix @ con.inverse_matrix @ rest_matrix @ matrix_basis
    Queremos final == target_matrix (o valor desejado). `.matrix = X`
    (sem constraint interferindo) grava matrix_basis = rest_matrix
    .inverted() @ X, ou seja rest_matrix @ matrix_basis == X -- então
    isolando X pra que, DEPOIS da Child Of rodar de novo em cima dele,
    o resultado bata com target_matrix:
        X = (target.matrix @ con.inverse_matrix).inverted() @ target_matrix
    Sem precisar desativar/reativar nada -- escreve direto, já
    compensado."""
    active_con = None
    for name in constraint_names:
        con = pose_bone.constraints.get(name)
        if con is not None and con.type == "CHILD_OF" and not con.mute and con.influence > 0.0 and con.subtarget:
            active_con = con
            break  # as duas (Local/Global) nunca deveriam estar ativas ao mesmo tempo -- para na primeira

    if active_con is None:
        pose_bone.matrix = target_matrix
        return

    target_pb = pose_bone.id_data.pose.bones.get(active_con.subtarget)
    if target_pb is None:
        pose_bone.matrix = target_matrix
        return

    pose_bone.matrix = (target_pb.matrix @ active_con.inverse_matrix).inverted() @ target_matrix
    context.view_layer.update()


def snap_chain_pose(context, obj, item, target_mode):
    """FK/IK Snap: iguala a pose dos controles do modo DE DESTINO
    (target_mode) à pose atualmente VISÍVEL da cadeia, pra trocar o
    switch sem "pulo". Não mexe no switch em si -- ver
    ANIM_OT_hytale_set_fk_ik, que chama isto ANTES de escrever a
    property.

    A leitura é sempre a mesma, não importa o modo atual: o bone `_MCH`
    de cada segmento ORG é a única fonte de verdade da pose visível (é
    ele quem os bones ORG realmente seguem -- ver CONSTRAINT_ORG_TO_MCH
    em rigger/rig.py) -- FK ou IK, o MCH já reflete o resultado, porque
    é ele quem recebe o blend das duas camadas via driver. Por isso este
    código não precisa saber em qual modo a cadeia está agora: só lê
    `_MCH` e escreve no lado (`_CTRL` ou `_IK`/pole) que ainda não é a
    fonte da verdade.

    -- target_mode == "FK": copia o matrix (armature space, já com
       constraints aplicados) de CADA `<org>_MCH` pro `<org>_CTRL`
       correspondente, segmento por segmento, raiz->ponta (nessa ordem
       -- um view_layer.update() entre cada um garante que o próximo
       bone da cadeia, cujo parent É o _CTRL anterior, calcula a
       própria pose local relativa ao valor NOVO do pai, não ao antigo).
       Funciona pra cadeia de qualquer tamanho (Thigh/Calf/Heel/Foot
       etc.), sem precisar saber quantos segmentos existem.

    -- target_mode == "IK": só 2 bones são realmente controláveis em IK
       (o resto é resolvido pelo solver) --
         1. `<tip>_IK` (o alvo solto, ex. Hand_IK) recebe o matrix de
            `<tip>_MCH`, compensado por um offset fixo de rest (a
            ponta foi reorientada na criação do rig -- ver comentário
            detalhado dentro do bloco IK, abaixo) -- sem essa
            compensação, a rotação da ponta (mão/pé) sai torta.
         2. O pole target (`<root>_Pole_CTRL`) é reposicionado usando a
            MESMA fórmula que `_pole_position` (rigger/rig.py) usa na
            hora de CRIAR o rig -- só que com o eixo Z do bone de
            referência (pole_bone, ou o bone do meio do caminho se
            vazio) tirado da pose ATUAL (via `<pole_ref>_MCH.matrix`)
            em vez do rest. Mesma regra de sinal (`item.pole_invert`)
            e mesma distância (`item.pole_distance`) que o usuário já
            configurou pra essa cadeia -- reaproveitadas, não
            reinventadas.

       O alvo IK e o pole já têm Child Of ATIVAS por padrão (ver
       _build_pose_constraints) -- `pose_bone.matrix = valor` sozinho
       NÃO dá o resultado certo nesse caso (o Blender não "desfaz" a
       constraint ao calcular o canal local -- ela roda de novo em
       cima depois e desloca o resultado). As duas escritas abaixo
       passam por `_snap_matrix_through_constraints`, que resolve a
       matemática da Child Of (incluindo o inverse_matrix do "Set
       Inverse" já aplicado -- ver rigger/rig.py) e escreve o valor já
       compensado.

    Retorna (True, None) em sucesso, (False, "motivo") se algum bone
    necessário não existir (rig não gerado, cadeia nova sem "Create Rig"
    ainda, etc.) -- quem chama decide se aborta o switch ou segue sem
    snap."""
    pose_bones = obj.pose.bones
    bones = obj.data.bones

    root_bone = bones.get(item.root_bone)
    if root_bone is None:
        return False, f"root bone '{item.root_bone}' not found"
    path = find_org_path(root_bone, item.tip_bone)
    if not path:
        return False, f"no bone path from '{item.root_bone}' to '{item.tip_bone}'"

    if target_mode == "FK":
        for org_bone in path:
            mch_pb = pose_bones.get(org_bone.name + SUFFIX_MCH)
            ctrl_pb = pose_bones.get(org_bone.name + SUFFIX_CTRL)
            if mch_pb is None or ctrl_pb is None:
                continue  # bone sem MCH/CTRL (ex. attachment) -- pula, não é erro
            ctrl_pb.matrix = mch_pb.matrix.copy()
            # Necessário ANTES do próximo segmento: o próximo _CTRL da
            # cadeia é filho DESTE _CTRL -- sem recalcular agora, ele
            # decompõe a própria pose relativa ao valor ANTIGO do pai.
            context.view_layer.update()
        return True, None

    if target_mode == "IK":
        tip_org = path[-1]
        tip_mch_pb = pose_bones.get(tip_org.name + SUFFIX_MCH)
        ik_tip_pb = pose_bones.get(tip_org.name + SUFFIX_IK)
        ik_tip_bone = bones.get(tip_org.name + SUFFIX_IK)
        bridge_bone = bones.get(tip_org.name + SUFFIX_IK_MCH)
        if tip_mch_pb is None or ik_tip_pb is None or ik_tip_bone is None or bridge_bone is None:
            return False, f"'{tip_org.name}{SUFFIX_MCH}'/'{tip_org.name}{SUFFIX_IK}' bones not found"

        # O bone `_IK` da PONTA (ex. Hand_IK) foi REORIENTADO na criação
        # do rig (aponta pro attachment ou "pra baixo" no mundo -- ver
        # _build_ik_layer) -- rest orientation DIFERENTE da do bridge
        # `_IK_MCH` (que mantém a rest do ORG original, intocada -- por
        # isso IK_CopyRotation/Scale, em _build_pose_constraints, miram
        # nele em vez de no `_IK` direto: precisam de uma rest "limpa").
        # Copiar tip_mch.matrix direto pro `_IK` (como fazíamos antes)
        # ignora essa diferença -- ao entrar em IK, o Blender aplica o
        # MESMO offset de novo (via bridge) EM CIMA de um valor que já
        # não tinha o offset compensado, e a mão sai torta.
        #
        # offset = a rest do `_IK` PRA a rest do bridge, em armature
        # space (calculável a qualquer momento via Bone.matrix_local --
        # não precisa de Edit Mode). Relação real em Pose Mode, com o
        # bridge sempre sem pose própria (matrix_basis identidade):
        #     bridge.matrix (mundo) = ik_tip.matrix (mundo) @ offset
        # Queremos bridge.matrix == tip_mch.matrix (é o que
        # IK_CopyRotation/Scale vão copiar pro MCH assim que o switch
        # virar 1) -- resolvendo pra ik_tip.matrix:
        #     ik_tip.matrix = tip_mch.matrix @ offset.inverted()
        # (offset.translation é sempre zero -- os três bones comparados
        # aqui compartilham a mesma cabeça, ver comentário em
        # rigger/__init__.py -- então isto não desloca a posição do
        # alvo, só corrige a rotação/escala.)
        offset = ik_tip_bone.matrix_local.inverted() @ bridge_bone.matrix_local
        # ik_tip tem uma Child Of ATIVA por padrão, mirando no
        # CHILD_OF_GLOBAL_TARGET (Origin_CTRL) -- ver
        # CONSTRAINT_CHILD_OF_GLOBAL em rigger/rig.py. `.matrix = X`
        # sozinho não compensa isso (ver _snap_matrix_through_
        # constraints, acima) -- por isso passa pelo helper em vez de
        # escrever direto.
        _snap_matrix_through_constraints(
            context, ik_tip_pb, tip_mch_pb.matrix @ offset.inverted(), [CONSTRAINT_CHILD_OF_GLOBAL]
        )

        # Necessário ANTES de mexer no pole: ele tem uma Child Of
        # ATIVA mirando neste MESMO ik_tip (ver CONSTRAINT_CHILD_OF_LOCAL
        # em rigger/rig.py) -- sem atualizar agora, o Blender resolveria
        # a matrix do pole daqui a pouco usando o valor ANTIGO (pré-snap)
        # do tip, e o pole (e a rotação dele, que a Child Of também
        # copia) saía errado.
        context.view_layer.update()

        pole_ref_name = item.pole_bone or path[len(path) // 2].name
        pole_ref_mch_pb = pose_bones.get(pole_ref_name + SUFFIX_MCH)
        pole_pb = pose_bones.get(path[0].name + SUFFIX_POLE)
        if pole_ref_mch_pb is not None and pole_pb is not None:
            ref_matrix = pole_ref_mch_pb.matrix
            z_axis = ref_matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))
            z_axis = z_axis.normalized() if z_axis.length > 1e-9 else Vector((0.0, 0.0, 1.0))
            sign = 1.0 if item.pole_invert else -1.0
            target_head = ref_matrix.translation + z_axis * (item.pole_distance * sign)

            new_matrix = pole_pb.matrix.copy()
            new_matrix.translation = target_head
            # Pole tem DUAS Child Of (Local -> ik_tip, ativa por
            # padrão; Global -> Origin_CTRL, influência 0 por padrão --
            # ver CONSTRAINT_CHILD_OF_LOCAL/GLOBAL em rigger/rig.py).
            # O helper acha sozinho qual das duas está ativa (a que
            # tiver influência > 0) e compensa a matrix pra ela --
            # incluindo o inverse_matrix do "Set Inverse" já aplicado,
            # que senão deixa um resíduo (mesmo se o Local, que mira
            # num ik_tip que a gente ACABOU de mover, "reproduzisse" a
            # si mesma -- o inverse foi calculado no rest, não agora).
            _snap_matrix_through_constraints(
                context, pole_pb, new_matrix, [CONSTRAINT_CHILD_OF_LOCAL, CONSTRAINT_CHILD_OF_GLOBAL]
            )
        # Sem pole_ref/pole bone -- não é fatal (o alvo IK já foi
        # posicionado acima); só o ângulo do cotovelo/joelho pode não
        # bater perfeitamente com a pose FK anterior.

        context.view_layer.update()
        return True, None

    return False, f"unknown target_mode '{target_mode}'"


def _resolve_switch_prop(obj, item):
    """Acha (props_bone, prop_name) da custom property de FK/IK switch
    desta cadeia, ou (None, "motivo") se não existir ainda (rig não
    gerado, cadeia nova sem regenerar). Compartilhado por
    ANIM_OT_hytale_set_fk_ik e ANIM_OT_hytale_snap_selected -- os dois
    escrevem exatamente a mesma property, só decidem de jeitos
    diferentes SE/QUANDO escrever."""
    props_bone = obj.pose.bones.get(BONE_PROPERTIES)
    if props_bone is None:
        return None, None, "rig not generated yet -- there's no FK/IK switch to set"
    prop_name = switch_property_name(item.tip_bone, item.side)
    if prop_name not in props_bone.keys():
        return None, None, (
            f"'{prop_name}' not found on the {BONE_PROPERTIES} bone -- generate/regenerate the rig first "
            "(this chain may have been added to the list after the last 'Create Rig')"
        )
    return props_bone, prop_name, None


def _write_fk_ik_switch(context, obj, props_bone, prop_name, mode):
    """Escreve 0/1 na custom property já resolvida (ver
    _resolve_switch_prop) e força o recálculo/redraw -- ver comentário
    detalhado dentro de ANIM_OT_hytale_set_fk_ik.execute (versão
    anterior) sobre por que update_tag()+view_layer.update()+redraw são
    TODOS necessários, não só um deles."""
    props_bone[prop_name] = 1 if mode == "IK" else 0
    obj.update_tag()
    context.view_layer.update()
    _redraw_all_areas(context)


class ANIM_OT_hytale_set_fk_ik(Operator):
    """Troca a cadeia (item de armature.hytale_ik_chains, por índice)
    pra FK (mode='FK') ou IK (mode='IK') -- SÓ a influência (custom
    property no bone PROPERTIES, criada por rigger.py -- ver
    ensure_fk_ik_switch_property/add_switch_driver em rigger/rig.py).
    NÃO iguala a pose (isso é ANIM_OT_hytale_snap_selected, separado de
    propósito -- pedido explícito: os botões de troca ficam "crus", o
    Snap é uma ação à parte que o usuário decide quando rodar)."""

    bl_idname = "pose.hytale_set_fk_ik"
    bl_label = "Set FK/IK"
    bl_description = "Switch this chain to FK or IK -- doesn't match the pose (use 'Snap FK/IK' for that)"
    bl_options = {"REGISTER", "UNDO"}

    chain_index: IntProperty(description="Índice em armature.hytale_ik_chains")
    mode: EnumProperty(items=[("FK", "FK", ""), ("IK", "IK", "")])

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE" and obj.pose is not None

    def execute(self, context):
        obj = context.active_object
        armature = obj.data
        chains = armature.hytale_ik_chains
        if not (0 <= self.chain_index < len(chains)):
            self.report({"WARNING"}, "Invalid chain index.")
            return {"CANCELLED"}

        item = chains[self.chain_index]
        if item.chain_type == "TAIL":
            self.report({"WARNING"}, "Tail chains don't have an FK/IK switch.")
            return {"CANCELLED"}

        props_bone, prop_name, reason = _resolve_switch_prop(obj, item)
        if props_bone is None:
            self.report({"WARNING"}, reason)
            return {"CANCELLED"}

        _write_fk_ik_switch(context, obj, props_bone, prop_name, self.mode)
        return {"FINISHED"}


def identify_chain_from_bone(obj, bone_name):
    """Dado o nome de um bone (tipicamente context.active_pose_bone.name),
    acha em qual cadeia ARM/LEG de armature.hytale_ik_chains ele
    participa, e de qual LADO (FK ou IK) -- olhando os bones reais da
    cadeia (via find_org_path, mesmo caminho que o Snap usa), não o
    nome cru: cobre CTRL de qualquer segmento (raiz/meio/ponta), o
    `_IK` da ponta e o Pole Target. Retorna (index, item, side) ou
    (None, None, None) se o bone não pertencer a nenhuma cadeia (ex.:
    bone de attachment, ou nenhum rig gerado ainda).

    `side` é o lado ONDE o bone selecionado está agora -- ANIM_OT_hytale_
    snap_selected usa o lado OPOSTO como target_mode (seleciona um
    _CTRL -> assume que o objetivo é preparar a troca PRA IK; seleciona
    o alvo IK ou o pole -> prepara a troca PRA FK)."""
    armature = obj.data
    bones = armature.bones
    for index, item in enumerate(armature.hytale_ik_chains):
        if item.chain_type == "TAIL" or not item.root_bone or not item.tip_bone:
            continue
        root_bone = bones.get(item.root_bone)
        if root_bone is None:
            continue
        path = find_org_path(root_bone, item.tip_bone)
        if not path:
            continue

        if bone_name == path[0].name + SUFFIX_POLE:
            return index, item, "IK"
        if bone_name == path[-1].name + SUFFIX_IK:
            return index, item, "IK"
        for org_bone in path:
            if bone_name == org_bone.name + SUFFIX_CTRL:
                return index, item, "FK"
    return None, None, None


class ANIM_OT_hytale_snap_selected(Operator):
    """Snap + Switch, baseado no bone selecionado -- olha o bone
    ATIVO/selecionado em Pose Mode, descobre a cadeia e de que LADO ele
    está (ver identify_chain_from_bone), iguala a pose do lado OPOSTO
    e JÁ TROCA o switch pra esse lado oposto. Ex.: seleciona um _CTRL
    (FK) -> iguala o IK à pose atual e troca a cadeia pra IK; seleciona
    o alvo IK ou o Pole Target -> iguala o FK e troca a cadeia pra FK.

    Diferente de ANIM_OT_hytale_set_fk_ik (botões FK/IK da lista, que
    só trocam a influência, sem mexer na pose) -- este é o botão único
    "Snap FK/IK": faz o trabalho dos dois (igualar + trocar) de uma vez
    só, só que pra UMA cadeia (a do bone selecionado), não por índice
    escolhido na UI."""

    bl_idname = "pose.hytale_snap_fk_ik_selected"
    bl_label = "Snap FK/IK"
    bl_description = (
        "Match the pose of the opposite side (FK or IK) to the selected bone's chain, then switch to it -- "
        "does both the snap and the switch in one click, for whichever chain the active bone belongs to"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "ARMATURE"
            and obj.pose is not None
            and context.active_pose_bone is not None
        )

    def execute(self, context):
        obj = context.active_object
        active_bone = context.active_pose_bone
        index, item, side = identify_chain_from_bone(obj, active_bone.name)
        if item is None:
            self.report(
                {"WARNING"},
                f"'{active_bone.name}' doesn't belong to any Arm/Leg chain -- select a chain's FK "
                "control, IK target, or Pole Target first.",
            )
            return {"CANCELLED"}

        props_bone, prop_name, reason = _resolve_switch_prop(obj, item)
        if props_bone is None:
            self.report({"WARNING"}, reason)
            return {"CANCELLED"}

        target_mode = "FK" if side == "IK" else "IK"
        ok, reason = snap_chain_pose(context, obj, item, target_mode)
        if not ok:
            self.report({"WARNING"}, f"Snap failed ({reason}) -- switching without matching the pose.")

        _write_fk_ik_switch(context, obj, props_bone, prop_name, target_mode)
        self.report({"INFO"}, f"Snapped and switched '{item.label or item.root_bone}' to {target_mode}.")
        return {"FINISHED"}


_CLASSES = (
    ANIM_OT_hytale_toggle_collection_visibility,
    ANIM_OT_hytale_set_fk_ik,
    ANIM_OT_hytale_snap_selected,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
