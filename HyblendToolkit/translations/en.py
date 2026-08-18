"""
translations/en.py -- Inglês (idioma de referência / fallback).
=================================================================
Este é o arquivo CANÔNICO: toda key nova do addon nasce aqui primeiro,
e é nele que tr() (ver translations/__init__.py) cai automaticamente
quando o idioma escolhido pelo usuário não tem uma tradução pra alguma
key ainda. Por isso NÃO apague uma key daqui só porque parece não estar
em uso -- apagar uma key aqui faz ela aparecer crua (sem tradução
nenhuma, pro mundo inteiro) pra qualquer idioma que também não tenha
essa mesma key.

## Como criar um idioma novo

1. Duplique este arquivo (ou qualquer outro dentro de translations/)
   com um nome novo. O NOME DO ARQUIVO em si não importa pro Blender
   (só precisa terminar em ".py" e não começar com "_") -- ex.: copie
   "en.py" para "es.py", ou "de.py", ou "meu_idioma.py".
2. Troque LANGUAGE_CODE por um código curto, maiúsculo e único (é o
   valor salvo na preference do addon internamente -- ex.: "ES", "FR",
   "DE", ou "PT_PT" se um dia quiser separar de PT_BR).
3. Troque LANGUAGE_NAME pelo nome que deve aparecer no dropdown de
   idioma das Preferences (ex.: "Español", "Français", "Deutsch").
4. Traduza os VALUES do dicionário TRANSLATIONS logo abaixo -- não mexa
   nas KEYS (o texto entre aspas ANTES de cada ":"), só no texto DEPOIS
   dos dois-pontos.
5. Salve o arquivo dentro desta pasta (translations/) e reinicie o
   Blender, ou clique em "Reload Translations" nas Preferences do addon
   (Edit > Preferences > Add-ons > Hyblend Toolkit), ou rode Reload
   Scripts (F3 > Reload Scripts). O idioma novo aparece sozinho no
   dropdown -- não precisa editar nenhum outro arquivo .py do addon.

Não precisa traduzir TODAS as keys pro idioma ser aceito: qualquer key
que faltar no seu arquivo cai pro Inglês (este arquivo) automaticamente
-- comece só com as que você quiser e complete aos poucos, sem quebrar
nada no meio tempo.
"""

LANGUAGE_CODE = "EN"
LANGUAGE_NAME = "English"

TRANSLATIONS = {
    # -----------------------------------------------------------------
    # importer.py -- diálogo de Import (.blockymodel e .bbmodel)
    # -----------------------------------------------------------------
    "importer.section_target": "Target",
    "importer.import_mode": "Import Mode",
    "importer.target_armature": "Target Armature",
    "importer.armature_name": "Armature Name",
    "importer.section_rig": "Rig",
    "importer.orient_z_up": "Orient to Z-up (visual only)",
    "importer.unit_scale": "Scale (Blender units per game unit)",
    "importer.section_visuals": "Reference Visuals",
    "importer.generate_reference_boxes": "Generate Reference Meshes",
    "importer.generate_uvs": "Generate UVs",
    "importer.create_material": "Create Material",
    "importer.missing_face_mode": "Faces Missing Texture Data",
    "importer.override_atlas_size": "Set Atlas Size Manually",
    "importer.atlas_width": "Atlas Width (px)",
    "importer.atlas_height": "Atlas Height (px)",
    "importer.texture_mode": "Texture Mode",
    "importer.texture_filepath": "Texture Image",

    # -----------------------------------------------------------------
    # importer.py -- Preferences do addon (dropdown de idioma)
    # -----------------------------------------------------------------
    "importer.prefs_language": "Language",
    "importer.prefs_reload_translations": "Reload Translations",

    # -----------------------------------------------------------------
    # interface.py -- N-Panel, aba Import
    # -----------------------------------------------------------------
    "panel.new_model_header": "New Model",
    "panel.btn_new_blockymodel": ".blockymodel",
    "panel.btn_new_bbmodel": ".bbmodel",
    "panel.btn_import_attach": "Attach to Selected",
    "panel.hint_import_attach_none": "Select the target Armature first",
    "panel.hint_import_attach_target": "Armature:",
    "panel.btn_import_anim": "Import Animation",
    "panel.hint_import_anim_none": "Select the target Armature first",
    "panel.hint_import_anim_target": "Armature:",

    # -----------------------------------------------------------------
    # interface.py -- N-Panel, aba Export
    # -----------------------------------------------------------------
    "panel.btn_export": "Export Animations",
    "panel.hint_export_none": "Select/activate an Armature to export",
    "panel.hint_export_target": "Exporting from:",
    "panel.export_settings_box": "Export Settings",
    "panel.mouth_animation": "Mouth Animation",
    "panel.export_collection": "Export Collection",
    "panel.mouth_bone": "Mouth Bone",

    # -----------------------------------------------------------------
    # interface.py -- N-Panel, aba Rig
    # -----------------------------------------------------------------
    "panel.hint_rig_none": "Select an Armature.",
    "panel.templates_box": "Character Templates",
    "panel.active_rig_template": "Rig Template:",
    "panel.active_shape_template": "Shape Template:",
    "panel.active_collection_template": "Collection Template:",
    "panel.template_none": "(none)",
    "panel.load_shape_template": "Load Shape Template...",
    "panel.load_collection_template": "Collection Template",
    "panel.load_template_action": "Load",
    "panel.btn_reload_templates": "Reload Templates",
    "panel.btn_open_templates_folder": "Open Templates Folder",
    "panel.ik_chains_box": "Bone Settings",
    "panel.load_preset": "Load Preset...",
    "panel.apply_ik_joint_fix": "Apply IK Joint Fix (from Template)",
    "panel.field_chain_type": "Type",
    # Campos genéricos (Root Bone/Tip Bone/Pole Reference/Root Parent) --
    # v0.7: não são mais usados diretamente pela UI (Arm/Leg têm rótulos
    # próprios abaixo, Tail tem os seus também) -- mantidas por
    # compatibilidade (nenhum código as referencia mais, mas remover
    # deixaria pt_br.py e qualquer outro idioma com uma key órfã sem
    # necessidade).
    "panel.field_root_bone": "Root Bone",
    "panel.field_tip_bone": "Tip Bone",
    "panel.field_pole_bone": "Pole Reference",
    "panel.field_root_parent": "Root Parent",
    # v0.7 -- rótulos por chain_type (ver _LIMB_FIELD_LABELS em interface.py).
    # Arm e Leg reaproveitam os MESMOS 4 campos/mesma lógica de sempre
    # (root_bone/tip_bone/pole_bone/parent_override) -- só o texto muda.
    "panel.field_arm_shoulder": "Shoulder / Root Parent",
    "panel.field_arm_upper": "Arm / Root Bone",
    "panel.field_arm_forearm": "Forearm / Pole Reference",
    "panel.field_arm_hand": "Hand / Tip Bone",
    "panel.field_leg_pelvis": "Pelvis / Root Parent",
    "panel.field_leg_thigh": "Thigh / Root Bone",
    "panel.field_leg_calf": "Calf / Pole Reference",
    "panel.field_leg_foot": "Foot / Tip Bone",
    # v0.7 -- campos exclusivos de Tail (sem IK, ver rigger.py).
    "panel.field_tail_parent": "Attach To (Parent)",
    "panel.field_tail_start": "Start Bone",
    "panel.field_tail_end": "End Bone",
    "panel.field_tail_tip_rotation_axis": "Tip Rotation Axis",
    "panel.field_tail_tip_rotation_deg": "Tip Rotation (deg)",
    "panel.hint_tail_no_ik": "Tail bones follow their controls directly (no IK) -- ready for physics add-ons",
    "panel.field_side": "Side",
    "panel.field_pole_in_front": "Pole in Front (+Z)",
    "panel.field_copy_location_ik": "Also Copy Location on IK (root)",
    "panel.field_pole_distance": "Pole Distance",
    "panel.field_pole_angle_mode": "Pole Angle Mode",
    "panel.field_pole_angle_preset_name": "Pole Angle Preset",
    "panel.field_pole_angle_manual": "Pole Angle (deg)",
    "panel.field_pole_angle_fine_tune": "Pole Angle Fine-Tune (deg)",
    "panel.btn_create_rig": "Create Rig",
    "panel.btn_validate_rig": "Check Rig",
    "panel.btn_shape_edit_enter": "Shape Edit Mode",
    "panel.btn_shape_edit_finish": "Finish Shape Edit Mode",
    "panel.hint_shape_edit_no_active_bone": "Select a bone in Pose Mode to edit or mirror its custom shape.",
    "panel.btn_mirror_shape": "Mirror Shape to Opposite Side",
    "panel.field_shape_translation": "Shape Location",
    "panel.field_shape_rotation": "Shape Rotation",
    "panel.field_shape_scale": "Shape Scale",
    "panel.btn_remove_generated": "Remove Generated Bones",

    # -----------------------------------------------------------------
    # interface.py -- aba Animation (anim_tools.py)
    # -----------------------------------------------------------------
    "panel.hint_anim_none": "Select an armature to see its animation controls.",
    "panel.anim_collections_box": "Bone Collections",
    "panel.hint_anim_no_rig": "No bone collections found yet -- generate the rig first.",
    "panel.anim_fkik_box": "FK / IK",
    "panel.btn_snap_selected": "Snap FK/IK",
    "panel.hint_anim_no_fkik": "No Arm/Leg chains with a generated FK/IK switch yet.",

    # -----------------------------------------------------------------
    # interface.py -- avisos reaproveitados em mais de uma aba
    # -----------------------------------------------------------------
    "panel.warn_anim_experimental": "Experimental",
    "panel.warn_mouth_wip_short": "WIP",
    "panel.warn_rig_experimental": "Rig generation is experimental",
}
