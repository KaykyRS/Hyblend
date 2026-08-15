"""
translations/pt_br.py -- Português (Brasil).
=============================================
Tradução completa (hoje) das keys de en.py. Se en.py ganhar uma key nova
que ainda não foi traduzida aqui, tr() cai pro texto em Inglês sozinho
até alguém preencher essa key aqui também -- ver docstring de en.py pra
instruções gerais de como editar/duplicar um arquivo de idioma.
"""

LANGUAGE_CODE = "PT_BR"
LANGUAGE_NAME = "Português (Brasil)"

TRANSLATIONS = {
    # -----------------------------------------------------------------
    # importer.py -- diálogo de Import (.blockymodel e .bbmodel)
    # -----------------------------------------------------------------
    "importer.section_target": "Destino",
    "importer.import_mode": "Modo de Import",
    "importer.target_armature": "Armature Alvo",
    "importer.armature_name": "Nome da Armature",
    "importer.section_rig": "Rig",
    "importer.orient_z_up": "Orientar para Z-up (só visual)",
    "importer.unit_scale": "Escala (unidade Blender por unidade do jogo)",
    "importer.section_visuals": "Visuais de Referência",
    "importer.generate_reference_boxes": "Gerar Malhas de Referência",
    "importer.generate_uvs": "Gerar UVs",
    "importer.create_material": "Criar Material",
    "importer.missing_face_mode": "Faces Sem Dado de Textura",
    "importer.override_atlas_size": "Definir Tamanho do Atlas Manualmente",
    "importer.atlas_width": "Largura do Atlas (px)",
    "importer.atlas_height": "Altura do Atlas (px)",
    "importer.texture_mode": "Modo de Textura",
    "importer.texture_filepath": "Imagem da Textura",

    # -----------------------------------------------------------------
    # importer.py -- Preferences do addon (dropdown de idioma)
    # -----------------------------------------------------------------
    "importer.prefs_language": "Idioma",
    "importer.prefs_reload_translations": "Recarregar Traduções",

    # -----------------------------------------------------------------
    # interface.py -- N-Panel, aba Import
    # -----------------------------------------------------------------
    "panel.new_model_header": "Novo Modelo",
    "panel.btn_new_blockymodel": ".blockymodel",
    "panel.btn_new_bbmodel": ".bbmodel",
    "panel.btn_import_attach": "Anexar ao Selecionado",
    "panel.hint_import_attach_none": "Selecione a Armature de destino primeiro",
    "panel.hint_import_attach_target": "Armature:",
    "panel.btn_import_anim": "Importar Animação",
    "panel.hint_import_anim_none": "Selecione a Armature de destino primeiro",
    "panel.hint_import_anim_target": "Armature:",

    # -----------------------------------------------------------------
    # interface.py -- N-Panel, aba Export
    # -----------------------------------------------------------------
    "panel.btn_export": "Exportar Animações",
    "panel.hint_export_none": "Selecione/ative uma Armature para exportar",
    "panel.hint_export_target": "Exportando de:",
    "panel.export_settings_box": "Configurações de Export",
    "panel.mouth_animation": "Animação da Boca",
    "panel.export_collection": "Coleção de Export",
    "panel.mouth_bone": "Bone da Boca",

    # -----------------------------------------------------------------
    # interface.py -- N-Panel, aba Rig
    # -----------------------------------------------------------------
    "panel.hint_rig_none": "Selecione uma Armature.",
    "panel.templates_box": "Templates de Personagem",
    "panel.active_rig_template": "Template de Rig:",
    "panel.active_shape_template": "Template de Shape:",
    "panel.active_collection_template": "Template de Collections:",
    "panel.template_none": "(nenhum)",
    "panel.load_shape_template": "Carregar Template de Shape...",
    "panel.load_collection_template": "Template de Collections",
    "panel.load_template_action": "Carregar",
    "panel.btn_reload_templates": "Recarregar Templates",
    "panel.btn_open_templates_folder": "Abrir Pasta de Templates",
    "panel.ik_chains_box": "Cadeias de IK",
    "panel.load_preset": "Carregar Preset...",
    "panel.apply_ik_joint_fix": "Aplicar Correção de Junta IK (do Template)",
    "panel.field_root_bone": "Bone Raiz",
    "panel.field_tip_bone": "Bone da Ponta",
    "panel.field_pole_bone": "Referência do Pole",
    "panel.field_root_parent": "Pai da Raiz",
    "panel.field_side": "Lado",
    "panel.field_pole_in_front": "Pole na Frente (+Z)",
    "panel.field_copy_location_ik": "Também Copiar Localização no IK (raiz)",
    "panel.field_pole_distance": "Distância do Pole",
    "panel.field_pole_angle_mode": "Modo do Ângulo do Pole",
    "panel.field_pole_angle_preset_name": "Preset do Ângulo do Pole",
    "panel.field_pole_angle_manual": "Ângulo do Pole (graus)",
    "panel.field_pole_angle_fine_tune": "Ajuste Fino do Ângulo do Pole (graus)",
    "panel.btn_create_rig": "Criar Rig",
    "panel.btn_remove_generated": "Remover Bones Gerados",

    # -----------------------------------------------------------------
    # interface.py -- avisos reaproveitados em mais de uma aba
    # -----------------------------------------------------------------
    "panel.warn_anim_experimental": "Experimental",
    "panel.warn_mouth_wip_short": "WIP",
    "panel.warn_rig_experimental": "Geração de rig é experimental",
}
