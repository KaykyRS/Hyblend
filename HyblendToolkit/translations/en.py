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
    "importer.flat_mesh_collections": "Flat Mesh Collections",
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
    # v0.14 -- tooltip do próprio dropdown de idioma (era hardcoded em
    # Inglês antes, dizendo "tooltips stay in English" -- não é mais
    # verdade, ver translations/__init__.py).
    "importer.prefs_language_tooltip": "Language used throughout the addon -- panel labels, dialogs, and "
    "tooltips (both button and field tooltips, as of v0.14)",

    # -----------------------------------------------------------------
    # importer.py -- IMPORT_OT_hytale_blockymodel, tooltips de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "importer.prop.blockymodel_import_mode": (
        "NEW: creates a brand new Armature + reference-mesh collection. "
        "ATTACH: merges this file's bones into an Armature that's already "
        "in the scene (e.g. an attachment/prop file like eyes, meant to "
        "plug into an existing character's attachment-point bones)"
    ),
    "importer.prop.blockymodel_import_mode_item_new": (
        "Creates a new Armature and reference-mesh collection"
    ),
    "importer.prop.blockymodel_import_mode_item_attach": (
        "Merges into an Armature already in the scene, reusing any bone/mesh "
        "that already has a matching name"
    ),
    "importer.prop.blockymodel_target_armature_name": (
        "Name of the existing Armature (in this .blend file) to attach "
        "this file's bones to. If a bone with a given name already exists "
        "there, it's reused as-is (NOT recreated/renamed with .001) -- "
        "e.g. an eye-attachment file plugs its bones under the "
        "character's existing 'R-Eye-Attachment' bone instead of "
        "duplicating it. Same for the reference-mesh collection: reused "
        "instead of creating a new one"
    ),
    "importer.prop.blockymodel_armature_name": (
        "Name for the new Armature and its reference-mesh collection. "
        "Leave empty to fall back to the .blockymodel filename -- note "
        "the file itself doesn't store a character/creature name (only "
        "bone/piece names), so for files like 'Model.blockymodel' that "
        "don't match the character's real name (e.g. a boss), type the "
        "name you actually want here"
    ),
    "importer.prop.blockymodel_generate_reference_boxes": (
        "Creates a simple mesh (box or quad) for each visual shape in the "
        "model, parented to the Armature and skinned (100% weight) to its "
        "bone via a Vertex Group + Armature modifier. Useful as a visual "
        "reference while animating, and already deformable/paintable"
    ),
    "importer.prop.blockymodel_flat_mesh_collections": (
        "Keep every bone's mesh collection at a single flat level, "
        "instead of the default nested layout (a bone's mesh collection "
        "sits inside its nearest ancestor bone's mesh collection, "
        "mirroring the model's own hierarchy -- same idea as folders in "
        "Blockbench). Enable this to flatten everything to one level "
        "instead"
    ),
    "importer.prop.blockymodel_generate_uvs": (
        "Generates UV coordinates for the reference meshes from the "
        "model's texture layout data (per-face pixel offsets). The "
        "original texture image size isn't stored in the file, so unless "
        "'Set Atlas Size Manually' is enabled below, the canvas size is "
        "INFERRED from the layout data itself -- this is only a lower "
        "bound (it can come out a few pixels short on width/height if "
        "the real texture has unused padding), so if you know the actual "
        "texture's pixel dimensions, set them manually for an exact match"
    ),
    "importer.prop.blockymodel_missing_face_mode": (
        "What to do with a box face that has no entry in the model's "
        "texture layout. CONFIRMED against the official Hytale "
        "Blockbench plugin's own source (blockymodel.ts): a missing "
        "entry ALWAYS means that face had no texture assigned in "
        "Blockbench -- there's no 'implicitly hidden by another piece' "
        "case. So 'Skip' below is the behavior that faithfully matches "
        "Blockbench itself (reloading the file there shows the same "
        "empty face). 'Reuse Opposite Face' is a cosmetic-only override "
        "for when you'd rather see some texture than a hole, even "
        "knowing it doesn't match the source file"
    ),
    "importer.prop.blockymodel_missing_face_mode_item_skip": (
        "Don't create geometry for that face. Faithful to what "
        "Blockbench itself would show -- a missing texture layout "
        "entry always means the face was genuinely untextured"
    ),
    "importer.prop.blockymodel_missing_face_mode_item_opposite": (
        "Create the face and reuse the texture from the opposite "
        "side of the same box. Does NOT match what Blockbench "
        "itself would show -- purely a visual patch to avoid holes, "
        "can paste the wrong-looking texture onto a visible face"
    ),
    "importer.prop.blockymodel_override_atlas_size": (
        "Use the exact pixel dimensions of your texture file instead of "
        "guessing them from the layout data. Recommended: open your "
        "texture (e.g. in Blockbench or an image viewer) and enter its "
        "width/height here"
    ),
    "importer.prop.blockymodel_atlas_width": "Exact width, in pixels, of the texture atlas image",
    "importer.prop.blockymodel_atlas_height": "Exact height, in pixels, of the texture atlas image",
    "importer.prop.blockymodel_create_material": (
        "Creates one shared material wired into Base Color through the "
        "generated UVs, applied to every reference mesh. Hytale/Blockbench "
        "models only use a single flat texture (no PBR maps), so this "
        "mirrors that. If 'Texture Image' below is set, loads that image "
        "and uses its real pixel dimensions for the UV layout (overriding "
        "'Set Atlas Size Manually' above, if also enabled); otherwise "
        "creates a blank placeholder sized from the atlas size in use"
    ),
    "importer.prop.blockymodel_texture_mode": (
        "'Automatic' finds the texture PNG on disk using the same "
        "convention as the official Hytale Blockbench plugin (same "
        "folder as the model, or a '<ModelName>_Textures' subfolder). "
        "'Manual' lets you point to a specific file instead, ignoring "
        "auto-detection entirely"
    ),
    "importer.prop.blockymodel_texture_mode_item_auto": (
        "Auto-detect the texture PNG next to the model (same "
        "convention as the official Hytale plugin)"
    ),
    "importer.prop.blockymodel_texture_mode_item_manual": (
        "Pick the texture PNG yourself -- auto-detection is skipped entirely"
    ),
    "importer.prop.blockymodel_texture_filepath": (
        "The model's texture PNG. The .blockymodel file only stores "
        "per-face pixel offsets, not the texture itself or its canvas "
        "size -- pointing this at the real file gives exact UVs using "
        "its actual dimensions (takes priority over 'Set Atlas Size "
        "Manually' above). Only used when 'Texture Mode' above is set "
        "to 'Manual'"
    ),
    "importer.prop.blockymodel_orient_z_up": (
        "Hytale uses Y as the 'up' axis; Blender uses Z. This rotates "
        "ONLY the Armature object as a whole (not individual bones) so "
        "the character stands upright in Blender's default view. Doesn't "
        "affect pose/animation values, which stay in each bone's local space"
    ),
    "importer.prop.blockymodel_unit_scale": (
        "The animation exporter (Export_blockyanim.py) multiplies "
        "position by 64 when saving. This only matches up if the rig "
        "here was built at 1/64 scale. Don't change this unless you're "
        "sure of a different value"
    ),

    # -----------------------------------------------------------------
    # importer.py -- IMPORT_OT_hytale_bbmodel, tooltips de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "importer.prop.bbmodel_armature_name": (
        "Name for the new Armature and its collection. Leave empty to "
        "fall back to the project's own name (stored inside the "
        ".bbmodel), or to the filename if that's also empty"
    ),
    "importer.prop.bbmodel_orient_z_up": (
        "Rotate the Armature object 90 degrees so it displays upright "
        "in Blender's Z-up viewport. Purely a display rotation on the "
        "Armature object itself -- bone data underneath is untouched"
    ),
    "importer.prop.bbmodel_unit_scale": (
        "Same meaning as in the .blockymodel importer -- see UNIT_SCALE_DEFAULT in common.py"
    ),
    "importer.prop.bbmodel_generate_reference_boxes": (
        "Creates a mesh for each cube element in the project, parented "
        "to the Armature and skinned (100% weight) to its owning bone "
        "via a Vertex Group + Armature modifier"
    ),
    "importer.prop.bbmodel_flat_mesh_collections": (
        "Keep every bone's mesh collection at a single flat level, "
        "instead of the default nested layout (a bone's mesh collection "
        "sits inside its nearest ancestor bone's mesh collection, "
        "mirroring the .bbmodel's own outliner/folder hierarchy). "
        "Enable this to flatten everything to one level instead"
    ),
    "importer.prop.bbmodel_generate_uvs": (
        "Generates UV coordinates for the reference meshes from each "
        "face's pixel rectangle, already stored directly in the "
        ".bbmodel (no inference needed, unlike the .blockymodel path)"
    ),
    "importer.prop.bbmodel_create_material": (
        "Decodes the texture(s) embedded in the .bbmodel itself "
        "(base64 PNG data) and creates one material per texture used, "
        "wired into Base Color/Alpha through the generated UVs -- no "
        "external texture file needed, everything is self-contained "
        "in the .bbmodel"
    ),

    # -----------------------------------------------------------------
    # anim_importer.py -- IMPORT_OT_hytale_blockyanim, tooltips de
    # campo (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "anim_importer.prop.target_mode": "Which bone layer to write the imported animation onto",
    "anim_importer.prop.target_mode_item_org": (
        "Keyframe the original game bones directly. Works on ANY armature -- rigged or "
        "not -- but on a rig with an FK/IK control layer on top, these keyframes won't "
        "move anything (the original bones are constrained to follow the control layer)"
    ),
    "anim_importer.prop.target_mode_item_ctrl": (
        "Writes onto the '_CTRL'/'_IK'/pole bones generated by the auto-rig tool "
        "(rigger.py), so the imported animation stays editable through the control rig -- "
        "configure Spine/Arms/Legs below"
    ),
    "anim_importer.prop.action_name": "Leave empty to use the file name",
    "anim_importer.prop.start_frame": "Blender frame where time=0 of the animation file lands",
    "anim_importer.prop.import_fps_preset": (
        "Target scene FPS for this import. If the scene isn't already at this FPS, "
        "it gets changed automatically before importing -- .blockyanim files are authored at "
        "60 FPS (FPS_HYTALE), so keeping this at 60 avoids the 'timing looks compressed' issue "
        "from importing into a lower-FPS scene. Same list as Blender's own Output Properties > "
        "Frame Rate -- pick 'Custom' to set FPS/Base separately, same as there"
    ),
    "anim_importer.prop.import_fps_preset_item_6": "6 fps",
    "anim_importer.prop.import_fps_preset_item_8": "8 fps",
    "anim_importer.prop.import_fps_preset_item_12": "12 fps",
    "anim_importer.prop.import_fps_preset_item_23_98": "23.976 fps (24000 / 1001, NTSC film)",
    "anim_importer.prop.import_fps_preset_item_24": "24 fps",
    "anim_importer.prop.import_fps_preset_item_25": "25 fps",
    "anim_importer.prop.import_fps_preset_item_29_97": "29.97 fps (30000 / 1001, NTSC)",
    "anim_importer.prop.import_fps_preset_item_30": "30 fps",
    "anim_importer.prop.import_fps_preset_item_50": "50 fps",
    "anim_importer.prop.import_fps_preset_item_59_94": "59.94 fps (60000 / 1001, NTSC)",
    "anim_importer.prop.import_fps_preset_item_60": "60 fps",
    "anim_importer.prop.import_fps_preset_item_120": "120 fps",
    "anim_importer.prop.import_fps_preset_item_240": "240 fps",
    "anim_importer.prop.import_fps_preset_item_custom": "Set FPS and Base separately below",
    "anim_importer.prop.import_fps_custom_fps": (
        "Custom Frame Rate 'Frame Rate' is set to 'Custom' -- same field as Output "
        "Properties > Frame Rate > FPS in Blender's own UI. Effective rate is FPS / Base"
    ),
    "anim_importer.prop.import_fps_custom_base": (
        "Custom Frame Rate 'Frame Rate' is set to 'Custom' -- same field as Output "
        "Properties > Frame Rate > Base in Blender's own UI. Effective rate is FPS / Base"
    ),
    "anim_importer.prop.loop_mode": "Whether this clip should close into a seamless loop",
    "anim_importer.prop.loop_mode_item_auto": (
        "Use the file's own 'holdLastKeyframe' flag: false = cycle (loop), true = "
        "start & end (hold last pose)"
    ),
    "anim_importer.prop.loop_mode_item_cycle": (
        "Force this clip to close into a loop: adds a closing pose at 'duration' that "
        "matches each channel's first keyframe, so it flows back into itself -- use for "
        "walk/run/idle cycles"
    ),
    "anim_importer.prop.loop_mode_item_one_shot": (
        "Force this clip to just hold its last pose at the end -- use for non-looping "
        "actions (attacks, deaths, one-off gestures)"
    ),
    "anim_importer.prop.bake_mode": (
        "Compute the exact pose at every frame directly from the file's raw keyframes "
        "(proper spherical interpolation for rotation), instead of relying on Blender's own "
        "per-component Bezier F-Curves. Produces far more keyframes, but avoids rotation "
        "interpolation artifacts -- especially noticeable with few, far-apart orientation "
        "keyframes (common in this format). Recommended for Cycle imports. Affects "
        "position/rotation on 'Original Bones' and shape stretch on both targets -- "
        "'Control Bones (FK)' position/rotation always bakes every frame regardless"
    ),
    "anim_importer.prop.keep_spine_follow": (
        "Control FK, Control IK and Default (FK + IK) only: by default, this stays ACTIVE -- "
        "any extra constraint on a control bone (ex: Belly_CTRL/Chest_CTRL partially following "
        "root.spine_CTRL) keeps blending in during import, and in modes that write IK, each "
        "pole target's Child Of constraints also stay active. Disable this to mute those "
        "constraints instead, making the imported pose match the source file exactly on the "
        "affected bones -- at the cost of root.spine_CTRL (and the poles' Child Of) no longer "
        "being usable as fine-tuning tools on top of the imported animation"
    ),
    "anim_importer.prop.spine_mode": (
        "Controllers only: how the rig's utility root bones (root.master_CTRL/"
        "root.pelvis_CTRL, rigger.py) behave. The source animation only ever moves Pelvis/Belly/"
        "Chest -- these root bones never move on their own, so they need this to travel with the "
        "animation (ex: walk/run cycles) instead of staying frozen near the origin"
    ),
    "anim_importer.prop.spine_mode_item_default": (
        "root.master_CTRL follows the Pelvis's animated position and rotation every frame "
        "-- root.pelvis_CTRL and Belly_CTRL (real children of root.master_CTRL) travel "
        "along automatically. Recommended -- matches the source animation's root motion"
    ),
    "anim_importer.prop.spine_mode_item_manual": (
        "root.master_CTRL/root.pelvis_CTRL stay frozen at rest -- Pelvis/Belly/Chest are "
        "still keyframed normally, but the character won't travel with root motion (ex: "
        "walking will look like walking in place). Leaves root.spine_CTRL free as a manual "
        "fine-tuning handle on top of the imported animation instead"
    ),
    "anim_importer.prop.arms_mode": (
        "Controllers only: how 'Arm'-type chains (armature.hytale_ik_chains, "
        "rigger.py) are keyframed"
    ),
    "anim_importer.prop.arms_mode_item_both": (
        "Writes both at once -- every arm segment gets its FK '_CTRL' AND the chain's IK "
        "tip (hand) + pole also get keyframed. fk_ik_switch defaults to FK (0); toggle it "
        "any time afterward, per chain, to preview or use the IK version instead -- no "
        "need to reimport"
    ),
    "anim_importer.prop.arms_mode_item_ctrl_fk": (
        "Only the per-segment '_CTRL' bones -- fk_ik_switch is left untouched (the chain "
        "doesn't receive any '_IK'/pole keyframes at all)"
    ),
    "anim_importer.prop.arms_mode_item_ik": (
        "Only the '_IK' tip (hand) + pole target -- per-segment '_CTRL' bones are skipped, "
        "and fk_ik_switch is set to IK (1)"
    ),
    "anim_importer.prop.legs_mode": (
        "Controllers only: how 'Leg'-type chains (armature.hytale_ik_chains, "
        "rigger.py) are keyframed -- same 3 options as Arms, applied independently"
    ),
    "anim_importer.prop.legs_mode_item_both": (
        "Writes both at once -- every leg segment gets its FK '_CTRL' AND the chain's IK "
        "tip (foot) + pole also get keyframed. fk_ik_switch defaults to FK (0); toggle it "
        "any time afterward, per chain, to preview or use the IK version instead -- no "
        "need to reimport"
    ),
    "anim_importer.prop.legs_mode_item_ctrl_fk": (
        "Only the per-segment '_CTRL' bones -- fk_ik_switch is left untouched (the chain "
        "doesn't receive any '_IK'/pole keyframes at all)"
    ),
    "anim_importer.prop.legs_mode_item_ik": (
        "Only the '_IK' tip (foot) + pole target -- per-segment '_CTRL' bones are skipped, "
        "and fk_ik_switch is set to IK (1)"
    ),

    # -----------------------------------------------------------------
    # exporter.py -- tooltips de botão (Operator.description, v0.14)
    # -----------------------------------------------------------------
    "exporter.tooltip.texture_picker_export_add": "Add a manual Texture Picker export entry to the list",
    "exporter.tooltip.texture_picker_export_remove": (
        "Remove the selected Texture Picker export entry from the list"
    ),

    # -----------------------------------------------------------------
    # exporter.py -- HYTALE_export_settings, tooltip de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "exporter.prop.export_settings_collection_name": (
        "Name of the Armature Bone Collection containing only the "
        "'original' game bones to export (Armature Data Properties > "
        "Bone Collections). If this collection doesn't exist on the "
        "armature, falls back to guessing by name suffix "
        "(_MCH/_CTRL/_IK), which is unreliable on complex rigs"
    ),

    # -----------------------------------------------------------------
    # exporter.py -- HYTALE_texture_picker_export_item, tooltips de
    # campo (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "exporter.prop.texture_picker_source_bone": (
        "Name of the helper bone whose Location drives the atlas "
        "picker (e.g. 'ui.texture_picker'). This bone itself is NOT "
        "exported -- only its Location is sampled"
    ),
    "exporter.prop.texture_picker_target_bone": (
        "Exact name of the real game bone to attach the "
        "'shapeUvOffset' channel to -- must be one of the exportable "
        "bones (e.g. 'Mouth', or any other atlas-driven part)"
    ),
    "exporter.prop.texture_picker_target_bones_extra": (
        "Comma-separated extra bone names that receive the exact same 'shapeUvOffset' data as "
        "Target Bone above -- for characters whose animated part is split across more than one "
        "mesh/bone (e.g. mirrored left/right halves) that must change expression together. Usually "
        "filled automatically by 'Create Texture Picker' from the Companion Bones configured on this "
        "entry, not typed here directly"
    ),
    "exporter.prop.texture_picker_step_x": (
        "In Blender units: how far the control bone has to move on X "
        "for the mouth/face texture to shift by one step. Must match "
        "whatever your shader/driver setup actually uses -- this "
        "doesn't invent the behavior, it just has to describe it "
        "correctly"
    ),
    "exporter.prop.texture_picker_px_x": (
        "How many raw texture pixels one X grid step represents in the file (the game expects raw "
        "pixel offsets, not a 0..1 fraction)"
    ),
    "exporter.prop.texture_picker_step_y": "Same as Grid Step X, for the control bone's Y movement",
    "exporter.prop.texture_picker_px_y": "Same as Pixels per Step X, for Y",

    # -----------------------------------------------------------------
    # exporter.py -- EXPORT_OT_hytale_blockyanim, tooltips de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "exporter.prop.blockyanim_bake_animation": (
        "ON (recommended): samples the final pose at every single "
        "frame, exactly as it looks in the viewport (IK, constraints, "
        "everything). Always safe, but makes bigger files. OFF: only "
        "samples frames that actually have a keyframe -- smaller "
        "files, but can look wrong if your rig uses IK, since IK "
        "poses aren't simple straight lines between keyframes"
    ),
    "exporter.prop.blockyanim_is_loop": (
        "ON: the animation eases back to its starting pose at the "
        "end, so it can repeat seamlessly (walk, run, idle). OFF: the "
        "animation just stops and holds its last pose (attacks, "
        "deaths, one-off actions). This setting applies to every file "
        "in this export, EXCEPT Actions re-exported with 'Keep "
        "Imported Timing' ON (Advanced Options > Re-Export), which use "
        "their own original value instead"
    ),
    "exporter.prop.blockyanim_force_start_end_keying": (
        "Only matters when 'Bake Every Frame' is OFF: makes sure the "
        "very first and last frame of each Action always get written, "
        "even if nothing was explicitly keyed exactly there. Without "
        "this, the exported clip could start or end a few frames "
        "early/late. Always on automatically when 'Bake Every Frame' "
        "is ON"
    ),
    "exporter.prop.blockyanim_export_texture_picker": (
        "Include 'shapeUvOffset' data for every configured Texture "
        "Picker instance (see the 'Hytale Export' panel in Object "
        "Properties to add/edit/remove instances). Turn off to skip "
        "this channel for this export only, without deleting any "
        "configured instance"
    ),
    "exporter.prop.blockyanim_frame_step": (
        "Only used when 'Bake Every Frame' is ON: 1 writes every "
        "single frame (safest). A higher number skips frames to save "
        "space, at the cost of smoothness -- only raise this if file "
        "size is a real problem"
    ),
    "exporter.prop.blockyanim_preserved_interpolation": (
        "Only used when 'Bake Every Frame' is OFF: how the game "
        "should smoothly move between two keyframes. Blockyanim only "
        "understands two styles (not full Bezier handles like "
        "Blender), so this one style is used for every keyframe"
    ),
    "exporter.prop.blockyanim_preserved_interpolation_item_smooth": (
        "Eases in and out between keyframes -- closest to Blender's default curves"
    ),
    "exporter.prop.blockyanim_preserved_interpolation_item_linear": (
        "Moves at a constant speed between keyframes, no easing"
    ),
    "exporter.prop.blockyanim_quantize_values": (
        "ON (recommended): rounds every written number to a fixed "
        "precision (see the three Step values below), which cleans up "
        "invisible floating-point jitter that Blender's math produces "
        "even for a bone that looks perfectly still. OFF: writes "
        "numbers exactly as Blender computed them, decimals and all"
    ),
    "exporter.prop.blockyanim_position_quantize_step": (
        "Smallest position change 'Snap to Grid' will keep, in game units. Smaller = more precise, "
        "larger file"
    ),
    "exporter.prop.blockyanim_rotation_quantize_step": (
        "Smallest rotation change 'Snap to Grid' will keep. Smaller = more precise, larger file"
    ),
    "exporter.prop.blockyanim_scale_quantize_step": (
        "Smallest stretch/scale change 'Snap to Grid' will keep. Smaller = more precise, larger file"
    ),
    "exporter.prop.blockyanim_position_zero_epsilon": (
        "A bone that should be perfectly still can still end up with "
        "a microscopic position value due to floating-point math -- "
        "in-game this can look like tiny, invisible-in-Blender "
        "shaking. Any position smaller than this (in game units) gets "
        "snapped to exactly zero instead"
    ),
    "exporter.prop.blockyanim_rotation_zero_epsilon": (
        "Same idea as Position Noise Floor, but for rotation: a bone "
        "that should be perfectly still can end up with a "
        "microscopic rotation instead of none at all (very common on "
        "IK legs/arms, where the solver rarely lands on an EXACT "
        "answer). Any rotation closer to 'no rotation at all' than "
        "this gets snapped to exactly zero"
    ),
    "exporter.prop.blockyanim_skip_redundant_frames": (
        "OFF (default): writes every sampled frame, guaranteeing an "
        "exact match to what you see in Blender. ON: additionally "
        "drops frames that don't add any real information -- for "
        "example, a long straight stretch of motion doesn't need a "
        "point every single frame if a few points already describe "
        "the same curve. This makes the file noticeably smaller but "
        "is LOSSY (can very slightly change the curve) -- only turn "
        "it on if file size is still a problem after 'Snap to Grid' "
        "and compact JSON formatting, which already help for free"
    ),
    "exporter.prop.blockyanim_position_epsilon": (
        "Only used when 'Remove Extra Frames' is ON: how far (in game "
        "units) a position/stretch frame is allowed to drift from a "
        "straight line before it's considered necessary to keep. "
        "Higher = more frames removed, less precise"
    ),
    "exporter.prop.blockyanim_rotation_epsilon": (
        "Only used when 'Remove Extra Frames' is ON: how far a "
        "rotation frame is allowed to drift from a smooth curve "
        "before it's considered necessary to keep. Higher = more "
        "frames removed, less precise"
    ),
    "exporter.prop.blockyanim_export_scale": (
        "ON (recommended): includes bone scale/stretch animation in "
        "the file (the 'shapeStretch' channel -- e.g. an eyebrow "
        "squashing/stretching). Turn OFF only if this rig never "
        "animates stretch and you want to skip sampling it entirely"
    ),
    "exporter.prop.blockyanim_scale_zero_epsilon": (
        "Same idea as Position Noise Floor, but for stretch: any scale closer to 1.0 (no stretch) "
        "than this on every axis gets snapped to exactly 1.0"
    ),
    "exporter.prop.blockyanim_bake_scale_hierarchy": (
        "Hytale/Blockbench bones don't inherit scale from their parent the way Blender's viewport "
        "does -- if you only keyframed scale on a parent bone (e.g. shrinking it to hide it, expecting "
        "children inside it to shrink and move closer together), the children would export with no "
        "scale/position change at all and stay full-size, spread out, in Blockbench/the game. Turn "
        "this ON to bake the parent's scale into every child's exported 'shapeStretch' AND pull each "
        "child's pivot toward the parent's, matching what you see in the Blender viewport. Only "
        "affects the exported file -- doesn't touch your actual keyframes"
    ),
    "exporter.prop.blockyanim_unit_scale": (
        "MUST match the exact value used when this character was "
        "imported (Hytale Blockymodel Importer) -- if they don't "
        "match, every position in the exported file will be wrong by "
        "a consistent scale factor. When in doubt, leave this at the "
        "default"
    ),
    "exporter.prop.blockyanim_output_decimal_places": (
        "How many digits after the decimal point to keep for every "
        "number in the file. Purely cosmetic and doesn't drop any "
        "keyframes -- just keeps the file from being full of numbers "
        "like 0.30000000000000004"
    ),
    "exporter.prop.blockyanim_pretty_print_json": (
        "OFF (default): writes the file as one compact line -- "
        "smaller, and nothing normally needs to read it by hand. ON: "
        "writes it nicely indented across many lines instead, purely "
        "so a human can open and read/compare it (roughly doubles "
        "file size; the game and Blockbench read either format "
        "identically)"
    ),
    "exporter.prop.blockyanim_use_source_metadata": (
        "Only matters for an Action that was imported by 'Import "
        "Hytale Animation' and hasn't been edited since. ON: reuse "
        "that file's exact original Duration/Loop values instead of "
        "the 'Loop?' option above and the current timeline length -- "
        "useful for a verification export, to check that reimporting "
        "an unedited file gives back exactly the same file. OFF "
        "(default, and what you want for normal editing work): always "
        "compute Duration/Loop fresh from the current timeline and "
        "the 'Loop?' option above. Leave this OFF whenever you've "
        "actually changed the animation, or a stale imported Duration "
        "shorter than your edit could silently cut off frames in the "
        "exported file"
    ),

    # -----------------------------------------------------------------
    # anim_tools.py -- tooltips de botão (Operator.description, v0.14)
    # -----------------------------------------------------------------
    "anim_tools.tooltip.set_fk_ik": "Switch this chain to FK or IK -- doesn't match the pose (use 'Snap "
    "FK/IK' for that)",
    "anim_tools.tooltip.set_head_follow": "Lock (follow the predecessor bone's rotation) or Free (keep "
    "Head_CTRL's own rotation)",
    "anim_tools.tooltip.snap_selected": "Match the pose of the opposite side (FK or IK) to the selected "
    "bone's chain, then switch to it -- does both the snap and the switch in one click, for whichever chain "
    "the active bone belongs to",
    "anim_tools.tooltip.keyframe_switch": "Insert a keyframe for this switch's current value at the "
    "current frame",

    # -----------------------------------------------------------------
    # anim_tools.py -- tooltips de campo (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "anim_tools.prop.set_fk_ik_chain_index": "Index into armature.hytale_ik_chains",
    "anim_tools.prop.keyframe_switch_chain_index": "Only used when switch == 'FK_IK'",

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
    "panel.export_texture_picker": "Texture Picker",
    "panel.export_collection": "Export Collection",
    "panel.texture_picker_target_bone": "Target Bone",

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
    "panel.btn_auto_detect_bones": "Auto-Detect Bones",
    # v0.7.5 -- headers dos 2 grupos visuais dentro do formulário Arm/Leg
    # (ver _draw_rig_bone_settings em interface.py) -- "Bones" sempre
    # visível, "Pole" collapsible (fechada por padrão, hytale_show_
    # pole_settings). "Organization" (Collection) não virou grupo --
    # continua um campo solto, mesmo padrão de Tail/Head/Spine/etc.
    "panel.bone_settings_group_bones": "Bones",
    "panel.bone_settings_group_pole": "Pole",
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
    # v0.7 -- campos exclusivos de Tail/Chain (sem IK, ver rigger.py).
    # v0.7.13 -- "Tail" virou "Chain" no chain_type/dropdown (ver
    # rigger.py) -- estes campos já eram genéricos (Parent/Start/End),
    # não precisaram mudar de texto.
    "panel.field_tail_parent": "Attach To (Parent)",
    "panel.field_tail_start": "Start Bone",
    "panel.field_tail_end": "End Bone",
    "panel.field_tail_tip_rotation_axis": "Tip Rotation Axis",
    "panel.field_tail_tip_rotation_deg": "Tip Rotation (deg)",
    "panel.field_tail_use_connect": "Connected",
    "panel.hint_tail_no_ik": "Ready for physics add-ons",
    # v0.9 (Etapa 2) -- campos de Head/Spine (organizacional, sem IK --
    # ver HytaleIKChainItem em rigger.py).
    "panel.field_neck_count": "Neck Bones Amount",
    "panel.field_neck_1": "Neck",
    "panel.field_neck_2": "Neck 2",
    "panel.field_neck_3": "Neck 3",
    "panel.field_neck_4": "Neck 4",
    "panel.field_neck_5": "Neck 5",
    "panel.field_head_bone": "Head",
    "panel.field_head_end_bone": "Head End",
    "panel.field_spine_count": "Spine Amount",
    "panel.field_pelvis_bone": "Pelvis",
    "panel.field_spine_1": "Spine1",
    "panel.field_spine_2": "Spine2",
    "panel.field_spine_3": "Spine3",
    "panel.field_spine_4": "Spine4",
    # v0.13.12 -- "Create root.spine_CTRL" (ver HytaleIKChainItem.
    # spine_ctrl_enabled em rigger/rig.py) -- liga/desliga root.spine_CTRL
    # e os constraints de Spine Follow (Belly_CTRL/Chest_CTRL) que
    # dependem dele.
    "panel.field_spine_ctrl_enabled": "Root Spine Controller",
    "panel.hint_spine_no_ik": "Organizational only",
    # v0.13 -- "Continuous Chain", compartilhado por HEAD e SPINE (ver
    # HytaleIKChainItem.continuous_chain/continuous_chain_link_bone em
    # rigger/rig.py). v0.13.4: sem UI (removida de interface.py -- ver
    # comentário lá) -- as duas keys ficam aqui sem uso por enquanto,
    # mesmo espírito de manter o sistema "dormente" no rig.py.
    "panel.field_continuous_chain": "Continuous Chain",
    "panel.field_continuous_chain_link": "Connect Last Bone To",
    # v0.13.4 -- "Head Free/Lock", exclusivo de HEAD (ver
    # HytaleIKChainItem.head_follow_enabled em rigger/rig.py).
    "panel.field_head_follow_enabled": "Head Free/Lock",
    # v0.15 -- "Create First Person Camera", exclusivo de HEAD (ver
    # HytaleIKChainItem.head_camera_* em rigger/rig.py).
    "panel.head_camera_section": "First Person Camera",
    "panel.field_head_camera_enabled": "Create First Person Camera",
    "panel.field_head_camera_parent_bone": "Camera Parent Bone",
    "panel.head_camera_offset_label": "Camera Offset",
    "panel.field_head_camera_offset_x": "X",
    "panel.field_head_camera_offset_y": "Y",
    "panel.field_head_camera_offset_z": "Z",
    "panel.head_camera_rotation_label": "Camera Rotation (deg)",
    "panel.field_head_camera_rotation_x": "X",
    "panel.field_head_camera_rotation_y": "Y",
    "panel.field_head_camera_rotation_z": "Z",
    "panel.field_head_camera_fov": "FOV (deg)",
    "panel.hint_head_camera": "Position/rotation are a starting point -- fine-tune to line up with this character's eyes",
    # v0.9.7 -- campos de Attachments (organizacional, sem IK -- ver
    # HytaleIKChainItem em rigger.py).
    "panel.field_attachments_count": "Attachments Bones Amount",
    "panel.field_attachment": "Attachment",
    "panel.hint_attachments_no_ik": "Organizational only",
    # v0.10 -- campos de Texture Picker (chain_type MOUTH até v0.10, virou
    # TEXTURE_PICKER na v0.11 -- organizacional + botão de geração, sem
    # IK -- ver HytaleIKChainItem/_build_texture_picker em rigger/rig.py).
    # v0.10.14/v0.10.15 -- Target Bone/Picker Parent ficam soltos (sem
    # box) -- só as seções realmente opcionais (Reference Image,
    # Companion Bones, Grid) viraram box collapsible.
    # Rótulos/hints encurtados -- explicação técnica completa continua
    # nos comentários de código e nas tooltips (hover).
    "panel.field_texture_picker_bone": "Target Bone",
    "panel.field_texture_picker_ui_parent_bone": "Picker Parent (opt.)",
    "panel.texture_picker_section_plane": "Reference Image",
    "panel.field_texture_picker_plane_scale": "Size",
    "panel.field_texture_picker_plane_offset_x": "Offset X",
    "panel.field_texture_picker_plane_offset_y": "Offset Y",
    "panel.hint_texture_picker_no_ik": "Builds a texture picker, not a bone chain",
    # v0.10.13 -- Companion Bones (ver HytaleIKChainItem.texture_picker_extra_bone_count/_1..N em rigger/rig.py).
    "panel.texture_picker_section_companions": "Companion Bones",
    "panel.field_texture_picker_extra_count": "Amount",
    "panel.field_texture_picker_extra_bone": "Bone",
    "panel.hint_texture_picker_companions_empty": "For extra bones that move with this one (e.g. mirrored halves)",
    # v0.10.13 -- Companion Target Bones no painel Export (ver HYTALE_export_bone_settings.uv_offset_target_bones_extra em exporter.py).
    "panel.texture_picker_extra_target_bones": "Companion Target Bones (auto-filled)",
    # v0.10.12/v0.10.14/v0.10.15 -- Grid (ver HytaleIKChainItem.texture_picker_grid_cols/_rows/_cell_width/_cell_height
    # em rigger/rig.py). v0.11 -- auto-detecção removida por completo, campos sempre digitados manualmente.
    "panel.texture_picker_section_grid": "Grid",
    "panel.field_texture_picker_grid_cols": "Columns",
    "panel.field_texture_picker_grid_rows": "Rows",
    "panel.field_texture_picker_grid_cell_width": "Cell Width",
    "panel.field_texture_picker_grid_cell_height": "Cell Height",
    "panel.field_side": "Side",
    # v0.7.5 -- ERA "Pole in Front (+Z)"/"Also Copy Location on IK (root)"
    # -- pedido explícito do usuário (nomes técnicos difíceis de
    # entender sem saber a implementação por trás). Mesma key, texto
    # mais direto sobre o EFEITO do toggle, não o mecanismo.
    "panel.field_pole_in_front": "Invert Direction",
    "panel.field_copy_location_ik": "Follow IK Target",
    # v0.7.5 -- ERA "Pole Distance"/"Pole Angle Mode"/etc -- o prefixo
    # "Pole" virou redundante depois que estes campos passaram a viver
    # dentro de uma caixa com o próprio header "Pole" (ver
    # _draw_rig_bone_settings em interface.py).
    "panel.field_pole_distance": "Distance",
    "panel.field_pole_angle_mode": "Angle Mode",
    "panel.field_pole_angle_preset_name": "Angle Preset",
    "panel.field_pole_angle_manual": "Angle (deg)",
    "panel.field_pole_angle_fine_tune": "Angle Fine-Tune (deg)",
    # v0.9 -- Collection Settings (Etapa 1). Dropdown "Collection" nas
    # entradas Arm/Leg do Bone Settings + a box nova entre Bone Settings
    # e Character Templates (ver interface.py/rigger.py).
    "panel.field_collection": "Collection",
    "panel.bone_collections_box": "Collection Settings",
    "panel.btn_load_default_collections": "Load Default Collections",
    "panel.btn_reset_bone_collection_grid": "Reset Row/Column to Defaults",
    "panel.hint_bone_collections": "Organize how bones are grouped for animation.",
    # v0.7.7 -- lista unificada: cada entrada é uma Collection (bone
    # collection real) ou uma Section (separador visual da aba
    # Animation, ver HytaleBoneCollectionItem.entry_type em rigger/
    # rig.py) -- "field_entry_type" é o seletor Collection/Section;
    # "field_parent" é o MESMO campo pros dois tipos, só o rótulo muda
    # (ver interface.py, _draw_rig_advanced) -- pra uma Collection
    # aparece como "Section" (field_section abaixo), pra uma Section
    # aparece como "Parent".
    "panel.field_entry_type": "Type",
    "panel.field_section": "Section",
    "panel.field_section_order": "Order",
    # v0.9.6 -- opções por-entrada de "Collection Settings": Parent/
    # Section (ver acima), Show in Animation Tab, e a grade (Row/Column
    # -- ver HytaleBoneCollectionItem em rigger.py).
    "panel.bone_collection_options_for": "Options for '{name}'",
    "panel.field_parent": "Parent",
    "panel.field_show_in_animation": "Show in Animation Tab",
    "panel.field_grid_row": "Row",
    "panel.field_grid_column": "Column",
    "panel.btn_create_rig": "Create Rig",
    "panel.btn_validate_rig": "Check Rig",
    "panel.btn_shape_edit_enter": "Shape Edit Mode",
    "panel.btn_shape_edit_finish": "Finish Shape Edit Mode",
    "panel.hint_shape_edit_no_active_bone": "Select a bone in Pose Mode to edit or mirror its custom shape.",
    "panel.btn_mirror_shape": "Mirror Shape",
    "panel.btn_use_selected_as_widget": "Use Selected Object as Widget",
    "panel.field_shape_translation": "Shape Location",
    "panel.field_shape_rotation": "Shape Rotation",
    "panel.field_shape_scale": "Shape Scale",
    "panel.btn_shape_vertex_edit_enter": "Edit Shape Vertices",
    "panel.btn_shape_vertex_edit_finish": "Finish Vertex Edit",
    "panel.label_vertex_edit_active": "Editing custom shape vertices",
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
    # v0.13.5 -- "Head Free/Lock" (ver ANIM_OT_hytale_set_head_follow/
    # get_head_follow_state em anim_tools.py). Sem hint separado -- a
    # box inteira só aparece quando o switch já existe (ver
    # get_head_follow_state), então não tem estado "vazio" pra explicar.
    "panel.anim_head_follow_box": "Head Free/Lock",

    # -----------------------------------------------------------------
    # rigger/rig.py -- Shape Edit Mode + Vertex Edit Mode + Mirror
    # Shape, tooltips de botão (Operator.description, v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.shape_edit_mode_enter": (
        "Mute the FK/IK shape-scale drivers so you can freely resize each control's custom shape -- use "
        "'Finish Shape Edit Mode' afterwards to lock in the new size as the driver's new max value"
    ),
    "rigger.tooltip.shape_edit_mode_finish": (
        "Lock in the custom shape sizes set while in Shape Edit Mode as the new max size, and restore the "
        "FK/IK shape-scale drivers"
    ),
    "rigger.tooltip.shape_vertex_edit_mode_enter": (
        "Enter Edit Mode directly on the active bone's custom shape mesh, hiding every other widget of this "
        "character -- use 'Finish Vertex Edit' afterwards to return to Pose Mode"
    ),
    "rigger.tooltip.shape_vertex_edit_mode_finish": (
        "Leave the widget's Edit Mode, re-hide this character's widgets, and return to Pose Mode"
    ),
    "rigger.tooltip.mirror_shape": (
        "Delete the L-/R- opposite bone's own shape (if any) and replace it with a mirrored copy of this "
        "bone's shape mesh, including its Location/Rotation/Scale"
    ),
    "rigger.tooltip.use_selected_as_widget": (
        "Copy the geometry of the other selected mesh object into the active bone's custom shape -- lets "
        "you use a fully custom, hand-modeled mesh as a widget instead of editing on top of the library shape"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- HytaleBoneCollectionItem, tooltips de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "rigger.prop.bone_collection_item_name": (
        "Name -- for a Collection, this is also the real Blender bone collection name after "
        "'Create Rig'. For a Section, it's just the header text shown in the Animation tab"
    ),
    "rigger.prop.bone_collection_item_entry_type_item_collection": (
        "A real bone collection -- bones can be assigned to it (via "
        "'Collection' on Bone Settings entries)"
    ),
    "rigger.prop.bone_collection_item_entry_type_item_section": (
        "A visual header in the Animation tab, grouping Collections together -- "
        "doesn't create any real bone collection"
    ),
    "rigger.prop.bone_collection_item_parent": (
        "Which Section this belongs under -- for a Collection, where its button appears in "
        "the Animation tab; for a Section, which Section it's nested under. 'Root / None' means top level "
        "(Section) or falls back to 'Main' (Collection). Purely visual, doesn't affect the real bone "
        "collection hierarchy"
    ),
    "rigger.prop.bone_collection_item_show_in_animation_tab": (
        "Whether a visibility toggle button for this collection appears in the Animation "
        "tab's 'Bone Collections' box. Off just hides the button here -- the collection itself is "
        "unaffected everywhere else"
    ),
    "rigger.prop.bone_collection_item_row": (
        "Vertical position among siblings (0 = top, higher = further down). For a Collection, "
        "siblings sharing the same Row are placed side by side, ordered by Column"
    ),
    "rigger.prop.bone_collection_item_column": (
        "Horizontal position within the Row (0 = leftmost, higher = further right). Entries "
        "with the same Row AND Column are ordered alphabetically. Collection-only -- a Section only uses Row"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- HytaleIKChainItem, tooltips de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "rigger.prop.ik_chain_chain_type": "What this entry configures -- see the type picker below for details on each",
    "rigger.prop.ik_chain_chain_type_item_arm": (
        "Two-segment limb (shoulder-arm-forearm-hand pattern) -- IK/FK-switchable chain"
    ),
    "rigger.prop.ik_chain_chain_type_item_leg": (
        "Two-segment limb (pelvis-thigh-calf-foot pattern) -- IK/FK-switchable chain"
    ),
    "rigger.prop.ik_chain_chain_type_item_chain": (
        "Chain of connected bones from root to tip, no IK -- for tails, long ears, "
        "or any sequence of bones that should move together"
    ),
    "rigger.prop.ik_chain_chain_type_item_head": (
        "Identifies the Neck (1-5 bones) + Head + Head End control bones -- no IK, organizational only"
    ),
    "rigger.prop.ik_chain_chain_type_item_spine": (
        "Identifies the Pelvis + Spine (1-4 bones) control bones -- no IK, organizational only"
    ),
    "rigger.prop.ik_chain_chain_type_item_attachments": (
        "Identifies specific Attachment control bones by name -- no IK, "
        "organizational only, in addition to the automatic name-based detection"
    ),
    "rigger.prop.ik_chain_chain_type_item_texture_picker": (
        "Identifies a control bone whose material is a texture atlas -- builds a UV-picker rig for it. No IK"
    ),
    "rigger.prop.ik_chain_label": "Free-form name just to identify this entry in the list (e.g. Arm L)",
    "rigger.prop.ik_chain_root_bone": "First bone of the chain (e.g. L-Arm, L-Thigh, or the first tail bone)",
    "rigger.prop.ik_chain_tip_bone": (
        "Last bone of the chain -- the target/effector for Arm/Leg (e.g. L-Hand, L-Foot), or "
        "the last tail bone for Tail"
    ),
    "rigger.prop.ik_chain_pole_bone": (
        "Arm/Leg only. Bone used as the position/orientation reference for the pole target "
        "(e.g. L-Forearm). Empty = automatically uses the middle bone of the root->tip path"
    ),
    "rigger.prop.ik_chain_parent_override": (
        "Bone this chain's root gets parented to (e.g. L-Shoulder_CTRL, Pelvis). Empty = unparented"
    ),
    "rigger.prop.ik_chain_tail_tip_rotation_axis": "Local axis the Tip Rotation angle bends around",
    "rigger.prop.ik_chain_tail_tip_rotation_axis_item_x": "Local X axis",
    "rigger.prop.ik_chain_tail_tip_rotation_axis_item_y": (
        "Local Y axis (the bone's own direction -- spins roll only, doesn't bend it)"
    ),
    "rigger.prop.ik_chain_tail_tip_rotation_axis_item_z": "Local Z axis",
    "rigger.prop.ik_chain_tail_tip_rotation_deg": (
        "Extra rotation applied to the tip bone's rest pose, around Tip Rotation Axis"
    ),
    "rigger.prop.ik_chain_tail_use_connect": (
        "Enable Blender's 'Connected' (bone.use_connect) on this chain's control bones -- off "
        "by default, since the chain's position already lines up without it"
    ),
    "rigger.prop.ik_chain_side": (
        "Body side of this chain -- used by pole_angle presets (e.g. Arm mode) that need a "
        "different value per side"
    ),
    "rigger.prop.ik_chain_pole_invert": (
        "Pole in front (positive Z axis of the reference bone) instead of behind (default, -Z)"
    ),
    "rigger.prop.ik_chain_pole_distance": "Distance from the pole target to the reference bone (pole_bone)",
    "rigger.prop.ik_chain_pole_angle_mode_item_auto": (
        "Calculates the pole angle automatically from the rest pose -- safe default for any character"
    ),
    "rigger.prop.ik_chain_pole_angle_mode_item_preset": (
        "Uses a calibrated value from the active rig template's presets"
    ),
    "rigger.prop.ik_chain_pole_angle_mode_item_manual": "Uses the value typed in Pole Angle directly",
    "rigger.prop.ik_chain_pole_angle_preset_name": (
        "Name of the entry (as defined in the active rig template's pole_angle_presets, e.g. "
        "'ARM') to use when Pole Angle Mode = Preset. Ignored in Auto/Manual mode"
    ),
    "rigger.prop.ik_chain_pole_angle_manual": (
        "Final pole_angle value, used only in Manual mode. Suggested starting point: 90 or "
        "-90 (typical elbow/knee) -- adjust the sign/value visually until the pole centers"
    ),
    "rigger.prop.ik_chain_pole_angle_fine_tune": "Added to the automatically calculated value -- used only in Auto mode",
    "rigger.prop.ik_chain_extra_ik_location": (
        "Also follow the target's position on IK, not just rotation/scale -- needed when "
        "the root bone doesn't follow the normal parent hierarchy"
    ),
    "rigger.prop.ik_chain_neck_count": "How many Neck bone fields to show below (0-5). Head/Head End are separate, always shown",
    "rigger.prop.ik_chain_org_bone_name_hint": (
        "Original bone name -- type/pick the ORIGINAL bone name (e.g. 'Head'), not '_CTRL': the matching "
        "control bone is resolved automatically"
    ),
    "rigger.prop.ik_chain_head_bone": (
        "Head original bone (defaults to the same bone HEAD_COLLECTION_ROOT already points to "
        "for the 'Player' rig, minus the '_CTRL' suffix -- see constants.py) -- type/pick the ORIGINAL bone "
        "name (e.g. 'Head'), not '_CTRL': the matching control bone is resolved automatically"
    ),
    "rigger.prop.ik_chain_head_end_bone": (
        "Optional bone at the very tip of the head (e.g. a jaw/chin end bone) -- leave empty "
        "if this rig doesn't have one -- type/pick the ORIGINAL bone name (e.g. 'Head'), not '_CTRL': the "
        "matching control bone is resolved automatically"
    ),
    "rigger.prop.ik_chain_spine_count": (
        "Total number of bones in this spine, including Pelvis (1-5). E.g. 3 = Pelvis + Spine1 + Spine2"
    ),
    "rigger.prop.ik_chain_spine_ctrl_enabled": (
        "Whether 'Create Rig' builds root.spine_CTRL, plus the Spine Follow constraints on Belly_CTRL/"
        "Chest_CTRL that depend on it. On by default. Turning this off after root.spine_CTRL already "
        "exists doesn't delete it -- run 'Remove Generated Bones' + 'Create Rig' again to fully drop it."
    ),
    "rigger.prop.ik_chain_continuous_chain": (
        "Redirects each listed bone's _CTRL Tail to touch the next one's Head (same trick the "
        "Chain type already uses) -- makes the chain look/behave like a connected sequence of bones "
        "instead of independent floating controls. Off by default, doesn't affect existing rigs unless "
        "turned on -- only the Tail moves, each bone's Head always stays at its original position."
    ),
    "rigger.prop.ik_chain_continuous_chain_link_bone": (
        "Optional. Original bone name whose Head this entry's LAST listed bone should point "
        "its Tail at (e.g. a Spine ending at 'Chest' connecting into a Head chain starting at 'Neck') -- "
        "leave empty to keep the last bone's own original Tail instead -- type/pick the ORIGINAL bone name "
        "(e.g. 'Head'), not '_CTRL': the matching control bone is resolved automatically"
    ),
    "rigger.prop.ik_chain_head_follow_enabled": (
        "Lock Head_CTRL's rotation to its predecessor bone (Neck, or Chest), switchable at pose time"
    ),
    "rigger.prop.ik_chain_head_camera_enabled": (
        "Adds a 'Create Camera' button below that parents a real Blender Camera object to the "
        "chosen bone -- useful for previewing/animating a first-person view"
    ),
    "rigger.prop.ik_chain_head_camera_parent_bone": (
        "Which bone the camera should be parented to (bone parenting -- follows the bone's pose "
        "automatically). Can be any bone on this armature, not just a Head/Neck bone -- type/pick the "
        "ORIGINAL bone name (e.g. 'Head'), not '_CTRL': the matching control bone is resolved automatically"
    ),
    "rigger.prop.ik_chain_head_camera_offset_x": "Nudge the camera left/right, local to the parent bone's rest orientation",
    "rigger.prop.ik_chain_head_camera_offset_y": "Nudge the camera forward/back, local to the parent bone's rest orientation",
    "rigger.prop.ik_chain_head_camera_offset_z": "Nudge the camera up/down, local to the parent bone's rest orientation",
    "rigger.prop.ik_chain_head_camera_rotation_x": "Extra rotation (degrees, local X to the parent bone)",
    "rigger.prop.ik_chain_head_camera_rotation_y": (
        "Extra rotation (degrees, local Y to the parent bone) -- default confirmed to face the "
        "camera forward on the parent bone's rest orientation"
    ),
    "rigger.prop.ik_chain_head_camera_rotation_z": "Extra rotation (degrees, local Z to the parent bone)",
    "rigger.prop.ik_chain_head_camera_fov": (
        "Horizontal field of view of the generated camera, in degrees -- not a confirmed Hytale "
        "value, just a reasonable FPS-game starting point"
    ),
    "rigger.prop.ik_chain_attachments_count": "How many Attachment bone fields to show below (0-{max})",
    "rigger.prop.ik_chain_texture_picker_bone": (
        "The bone whose mesh has the texture atlas (e.g. all the mouth expressions in one image) -- "
        "type/pick the ORIGINAL bone name (e.g. 'Head'), not '_CTRL': the matching control bone is "
        "resolved automatically"
    ),
    "rigger.prop.ik_chain_texture_picker_ui_parent_bone": (
        "Only needed if the picker should attach somewhere other than Target Bone. Leave "
        "empty in most cases -- type/pick the ORIGINAL bone name (e.g. 'Head'), not '_CTRL': the matching "
        "control bone is resolved automatically"
    ),
    "rigger.prop.ik_chain_texture_picker_plane_scale": (
        "Size of the reference image shown in the viewport for picking. Doesn't affect the exported animation"
    ),
    "rigger.prop.ik_chain_texture_picker_plane_offset_x": "Nudge the reference image left/right, if it isn't lined up right",
    "rigger.prop.ik_chain_texture_picker_plane_offset_y": "Nudge the reference image up/down, if it isn't lined up right",
    "rigger.prop.ik_chain_texture_picker_grid_cols": "How many texture-atlas cells across (left to right)",
    "rigger.prop.ik_chain_texture_picker_grid_rows": "How many rows of texture-atlas cells -- usually 1",
    "rigger.prop.ik_chain_texture_picker_grid_cell_width": "Pixel distance from one texture-atlas cell to the next, as seen in Blockbench",
    "rigger.prop.ik_chain_texture_picker_grid_cell_height": "Pixel distance between rows of texture-atlas cells. Doesn't matter if Rows is 1",
    "rigger.prop.ik_chain_texture_picker_extra_bone_count": (
        "How many other bones share this target's texture and should move together with it (0-{max})"
    ),
    "rigger.prop.ik_chain_texture_picker_extra_bone": (
        "Another bone whose mesh shares this same mouth texture (e.g. a mirrored left/"
        "right half) and should change expression together with Target Bone -- type/pick the ORIGINAL bone "
        "name (e.g. 'Head'), not '_CTRL': the matching control bone is resolved automatically"
    ),
    "rigger.prop.ik_chain_collection_override": (
        "Which bone collection this chain's bones go into (Main or Face, as organized in "
        "'Collection Settings'). 'Auto (default)' keeps the built-in behavior -- Arm L/Arm R/Leg L/Leg R"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- operadores de gerenciar a lista de cadeias IK,
    # tooltips de botão e de campo (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.ik_chain_add": "Add an empty entry (Arm/Leg/Tail/Head/Spine) to the list",
    "rigger.tooltip.ik_chain_remove": "Remove the selected IK chain from the list",
    "rigger.tooltip.ik_chain_move": "Move the selected entry up or down in the list",
    "rigger.prop.ik_chain_move_direction_item_up": "Move the entry one position up",
    "rigger.prop.ik_chain_move_direction_item_down": "Move the entry one position down",
    "rigger.tooltip.ik_chain_set_count": "Set the exact number of IK chains in the list, adding or removing at the end",
    "rigger.tooltip.ik_chain_pick_bone": "Copy the currently selected bone's name into this field",
    "rigger.tooltip.ik_chain_auto_detect": (
        "Scan this armature's bone names and try to add Head, Spine, Arm L/R and Leg L/R entries "
        "automatically, based on common naming keywords (Head/Neck, Pelvis/Spine, Shoulder/Arm/"
        "Forearm/Hand, Thigh/Calf/Foot) and L-/R- side prefixes. Never overwrites an entry that "
        "already exists for the same type/side -- always double-check the filled-in bones before "
        "using Create Rig"
    ),
    "rigger.tooltip.ik_chain_load_defaults": "Load a calibrated rig template, replacing the current IK chain list",
    "rigger.prop.ik_chain_load_defaults_preset": (
        "Rig template name to load -- leave empty to use whatever is currently selected in the "
        "Character Templates dropdown (wm.hytale_rig_template_selected, see interface.py)"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- operadores de Collection Settings, tooltips de
    # botão e de campo (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.bone_collection_load_defaults": (
        "Populate the list with the built-in collections (Head/Spine/Body/Arm L/Arm R/Leg L/Leg R/Root)"
    ),
    "rigger.tooltip.bone_collection_reset_grid": (
        "Fix Row/Column for the built-in collections (Head/Spine/Body/Arm L/Arm R/Leg L/Leg R/Root/Tail/"
        "Attachments) back to their default grid position, re-adding any of them that were deleted from "
        "the list. Custom collections are never touched"
    ),
    "rigger.tooltip.bone_collection_add": (
        "Add a new Collection (a real bone collection) or Section (a visual header) to the list"
    ),
    "rigger.prop.bone_collection_add_entry_type_item_collection": (
        "A real bone collection -- bones can be assigned to it"
    ),
    "rigger.prop.bone_collection_add_entry_type_item_section": (
        "A visual header in the Animation tab -- creates no real bone collection"
    ),
    "rigger.tooltip.bone_collection_remove": "Remove the selected entry from the list",
    "rigger.tooltip.bone_collection_move": "Move the selected entry up or down in the list",
    "rigger.prop.bone_collection_move_direction_item_up": "Move the entry one position up",
    "rigger.prop.bone_collection_move_direction_item_down": "Move the entry one position down",

    # -----------------------------------------------------------------
    # rigger/rig.py -- RIG_OT_hytale_validate_rig, tooltip de botão e
    # de campo (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.validate_rig": (
        "Check the IK chain list and export bone collection for common mistakes (report-only)"
    ),
    "rigger.prop.validate_rig_export_collection_name": (
        "Bone collection name that original (non-generated) bones are expected to be in -- same "
        "name exporter.py uses by default; change only if you've renamed that collection"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- RIG_OT_hytale_clear_generated, tooltips de botão
    # e de campo (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.clear_generated": "Delete all generated bones, keeping only the original ones",
    "rigger.prop.clear_generated_mode_item_only_rig": (
        "Delete generated bones and collections. Widgets, Collection Settings "
        "and Bone Settings are kept -- safe if you've hand-edited shapes in Shape Edit Mode"
    ),
    "rigger.prop.clear_generated_mode_item_delete_all": (
        "Delete everything: bones, collections, widgets, Collection "
        "Settings and Bone Settings -- back to a freshly imported armature"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- Texture Picker + First Person Camera, tooltips
    # de botão (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.texture_picker_create": (
        "Build a texture-atlas UV-picker rig for it (a dedicated root.ui/cursor bone pair + reference "
        "plane) from the Manual Grid values"
    ),
    "rigger.tooltip.texture_picker_remove": (
        "Remove the generated Texture Picker rig (root.ui/cursor bone pair, reference plane, material "
        "driver) for this entry"
    ),
    "rigger.tooltip.camera_create": "Create (or update) a First Person Camera object, bone-parented to the chosen bone",
    "rigger.tooltip.camera_remove": "Remove the generated First Person Camera object for this armature",

    # -----------------------------------------------------------------
    # rigger/rig.py -- RIG_OT_hytale_generate_rig ("Create Rig"),
    # tooltip de botão (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.generate_rig": "Create or update the rig layers, constraints and custom shapes",

    # -----------------------------------------------------------------
    # rigger/rig.py -- operadores de template (Rig/Shape/Collection),
    # tooltips de botão e de campo (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.shape_template_apply": "Set the active custom shape template (run 'Create Rig' again to apply)",
    "rigger.prop.shape_template_apply_template": (
        "Shape template name to activate -- leave empty to use whatever is currently selected in "
        "the Character Templates dropdown (wm.hytale_shape_template_selected, see interface.py)"
    ),
    "rigger.tooltip.rig_template_save": "Save the current IK chain list as a new template in your Documents/Hyblend folder",
    "rigger.tooltip.rig_template_delete": "Delete the selected rig template from your Documents/Hyblend folder (user templates only)",
    "rigger.tooltip.shape_template_save": "Save the current custom shapes as a new template in your Documents/Hyblend folder",
    "rigger.tooltip.shape_template_delete": "Delete the selected shape template from your Documents/Hyblend folder (user templates only)",
    "rigger.tooltip.collection_template_save": (
        "Save the armature's custom bone collections (created via Blender's native Bone Collections panel) "
        "as a new template in your Documents/Hyblend folder"
    ),
    "rigger.tooltip.collection_template_apply": "Apply the selected collection template to the active armature",
    "rigger.prop.collection_template_apply_template_name": (
        "Collection template name to apply -- leave empty to use whatever is currently selected "
        "in the Character Templates dropdown (wm.hytale_collection_template_selected, see interface.py)"
    ),
    "rigger.tooltip.collection_template_delete": (
        "Delete the selected collection template from your Documents/Hyblend folder (user templates only)"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- ensure_switch_property, tooltip de custom
    # property EM RUNTIME (id_properties_ui, não bpy.props -- v0.14).
    # Recriado toda vez que "Create Rig" roda, então NÃO precisa de
    # @localized_props/re-registro -- só tr() na hora certa.
    # -----------------------------------------------------------------
    "rigger.runtime.fk_ik_switch_description": "0 = FK, 1 = IK",
    "rigger.runtime.head_follow_switch_description": (
        "1 = Follow {source} (default), 0 = Free rotation (Head_CTRL keeps its own "
        "rotation/scale, still follows {source}'s position)"
    ),

    # -----------------------------------------------------------------
    # rigger/__init__.py -- properties soltas em Armature (sem
    # PropertyGroup por trás -- reatribuídas via refresh hook, ver
    # _assign_dynamic_properties, v0.14)
    # -----------------------------------------------------------------
    "rigger.prop.armature_apply_ik_joint_fix": (
        "Corrects the X position of specific IK chain joints, using the values defined by the active "
        "rig template (see 'ik_joint_x_overrides' in templates/rig/*.json) -- leave off for a template "
        "that hasn't defined/calibrated these values yet"
    ),
    "rigger.prop.armature_active_rig_template": (
        "Name of the rig template (templates/rig/*.json) currently loaded on this armature -- "
        "set automatically by 'Load Hytale IK Chain Preset', used to resolve pole_angle_presets/"
        "ik_joint_x_overrides/widget_translation_x_overrides at generation time"
    ),
    "rigger.prop.armature_active_shape_template": (
        "Name of the shape template (templates/shapes/*.json) currently active for this "
        "armature's custom shapes -- set automatically together with the rig template (or manually via "
        "'Set Hytale Shape Template')"
    ),
    "rigger.prop.armature_active_collection_template": (
        "Name of the collection template (templates/collections/*.json) most recently saved to "
        "or applied on this armature -- purely informational (unlike the rig/shape templates, this one is "
        "never auto-applied by 'Create Rig')"
    ),
    "rigger.prop.armature_shape_edit_mode": (
        "True while RIG_OT_hytale_shape_edit_mode_enter's mute is in effect on this armature's "
        "FK/IK shape-scale drivers -- set/cleared automatically by 'Enter'/'Finish Shape Edit Mode', read by "
        "interface.py to decide which of the two buttons to show and by 'Create Rig'/'Remove Generated Hytale "
        "Rig Bones' to refuse running mid-edit"
    ),
    "rigger.prop.armature_shape_vertex_edit_mode": (
        "True while a custom shape's mesh (the widget used by the active pose bone) is open in "
        "Edit Mode via 'Edit Shape Vertices' -- set/cleared automatically by that operator and 'Finish Vertex "
        "Edit', read by interface.py to draw the right panel (active_object is the widget MESH in this state, "
        "not the Armature) and by 'Create Rig'/'Remove Generated Hytale Rig Bones'/'Finish Shape Edit Mode' to "
        "refuse running with a vertex edit session left dangling"
    ),

    # -----------------------------------------------------------------
    # interface.py -- avisos reaproveitados em mais de uma aba
    # -----------------------------------------------------------------
    "panel.warn_anim_experimental": "Experimental",
    "panel.warn_texture_picker_wip_short": "WIP",
    "panel.warn_rig_experimental": "Rig generation is experimental",

    # -----------------------------------------------------------------
    # templates/__init__.py -- tooltips de botão (Operator.description,
    # v0.14 -- descoberto numa segunda varredura: estes 2 e os 5
    # abaixo tinham 0 bl_description, então caíam pro fallback de
    # docstring da classe -- em inglês curto nestes 2, mas em
    # português (nota de dev) em vários outros -- daí o "tooltip
    # aparece em português mesmo com o idioma em inglês")
    # -----------------------------------------------------------------
    "templates.tooltip.reload": "Rescan the templates folders for new or edited .json files",
    "templates.tooltip.open_user_folder": "Open your Documents/Hyblend/templates folder in the file explorer",

    # -----------------------------------------------------------------
    # importer.py -- tooltips de botão faltantes (v0.14, 2ª varredura)
    # -----------------------------------------------------------------
    "importer.tooltip.blockymodel": "Import a Hytale .blockymodel as an Armature (correct rest pose)",
    "importer.tooltip.bbmodel": "Import a Hytale character/creature from a Blockbench project (.bbmodel)",

    # -----------------------------------------------------------------
    # exporter.py -- tooltips de botão faltantes (v0.14, 2ª varredura)
    # -----------------------------------------------------------------
    "exporter.tooltip.select_all_actions": "Select or deselect every Action in the list below",
    "exporter.tooltip.blockyanim": (
        "Batch-export one or more Actions of the selected/active Armature to Hytale's "
        ".blockyanim format -- one file per Action, into a chosen folder"
    ),

    # -----------------------------------------------------------------
    # anim_importer.py -- tooltip de botão faltante (v0.14, 2ª
    # varredura)
    # -----------------------------------------------------------------
    "anim_importer.tooltip.blockyanim": "Import a .blockyanim file onto the active armature",

    # -----------------------------------------------------------------
    # interface.py -- TAB_ITEMS/RIG_SUBTAB_ITEMS, tooltips dos toggles
    # de aba/sub-aba (v0.14, 2ª varredura -- eram texto fixo na 3ª
    # posição da tupla items=, nunca passavam por tr())
    # -----------------------------------------------------------------
    "panel.tab_import_tooltip": "Import models and attachments",
    "panel.tab_export_tooltip": "Export animations",
    "panel.tab_rig_tooltip": "IK chains and rig generation",
    "panel.tab_animation_tooltip": "Bone collection visibility and FK/IK switches",
    "panel.tab_info_tooltip": "Credits and links",
    "panel.rig_subtab_setup_label": "Setup",
    "panel.rig_subtab_setup_tooltip": "Create/update the rig and everyday actions",
    "panel.rig_subtab_bone_settings_label": "Bone Settings",
    "panel.rig_subtab_bone_settings_tooltip": "IK chains and per-bone configuration",
    "panel.rig_subtab_advanced_label": "Advanced",
    "panel.rig_subtab_advanced_tooltip": "Bone collections and character templates",

    # -----------------------------------------------------------------
    # rigger/rig.py -- RIG_MT_hytale_ik_chain_add_menu / RIG_MT_hytale_
    # clear_generated_menu, tooltips de Menu (v0.14, 2ª varredura --
    # bpy.types.Menu suporta description() dinâmico igual Operator,
    # mas não testado 100% em Blender de verdade ainda -- ver comentário
    # em rigger/rig.py)
    # -----------------------------------------------------------------
    "rigger.tooltip.ik_chain_add_menu": "Choose what type of entry to add to the list",
    "rigger.tooltip.clear_generated_menu": "Delete generated bones -- choose how much to remove",

    # -----------------------------------------------------------------
    # common.py -- HYTALE_OT_pick_bone_into_field, tooltip de botão e
    # de campo (v0.14, 2ª varredura -- achado numa terceira passada,
    # tinha 0 bl_description E as 2 properties com texto hardcoded em
    # PORTUGUÊS, nunca passavam por tr() -- por isso aparecia em
    # português mesmo com o idioma do addon em inglês)
    # -----------------------------------------------------------------
    "common.tooltip.pick_bone_into_field": "Copy the currently selected bone's name into this field",
    "common.prop.pick_bone_data_path": (
        "Path, relative to the active object, to the datablock that owns the field (e.g. "
        "'data.hytale_export_settings')"
    ),
    "common.prop.pick_bone_field": "Name of the StringProperty to fill in",

    # -----------------------------------------------------------------
    # interface.py -- aba "Info" (créditos/links, ver _draw_info)
    # -----------------------------------------------------------------
    "panel.info_links_label": "Links",
    "panel.info_credits_label": "Credits",
    "panel.info_credits_created_by_label": "Created by:",
    "panel.info_credits_hytale_label": "Hypixel Studios",
    "panel.info_credits_hytale_disclaimer": (
        "Fan-made, unofficial tool. Not affiliated with or endorsed by Hypixel Studios."
    ),
}
