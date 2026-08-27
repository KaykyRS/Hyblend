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
    "importer.flat_mesh_collections": "Achatar Collections de Malha",
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
    "importer.prefs_language_tooltip": "Idioma usado no addon inteiro -- textos do painel, diálogos e "
    "tooltips (de botão e de campo, a partir da v0.14)",

    # -----------------------------------------------------------------
    # importer.py -- IMPORT_OT_hytale_blockymodel, tooltips de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "importer.prop.blockymodel_import_mode": (
        "NOVO: cria uma Armature nova + collection de malhas de referência. "
        "ANEXAR: mescla os bones deste arquivo numa Armature que já está "
        "na cena (ex.: um arquivo de attachment/peça avulsa, tipo olhos, "
        "feito pra encaixar nos bones de ponto de anexo de um personagem "
        "existente)"
    ),
    "importer.prop.blockymodel_import_mode_item_new": (
        "Cria uma Armature nova e uma collection de malhas de referência"
    ),
    "importer.prop.blockymodel_import_mode_item_attach": (
        "Mescla numa Armature já existente na cena, reaproveitando "
        "qualquer bone/malha que já tenha um nome correspondente"
    ),
    "importer.prop.blockymodel_target_armature_name": (
        "Nome da Armature já existente (neste .blend) pra anexar os bones "
        "deste arquivo. Se já existir um bone com o mesmo nome, ele é "
        "reaproveitado como está (NÃO recriado/renomeado com .001) -- ex.: "
        "um arquivo de anexo de olho encaixa seus bones sob o bone "
        "'R-Eye-Attachment' já existente do personagem, em vez de duplicá-lo. "
        "O mesmo vale pra collection de malhas de referência: reaproveitada "
        "em vez de criar uma nova"
    ),
    "importer.prop.blockymodel_armature_name": (
        "Nome pra Armature nova e sua collection de malhas de referência. "
        "Deixe vazio pra usar o nome do arquivo .blockymodel -- o arquivo "
        "em si não guarda um nome de personagem/criatura (só nomes de "
        "bone/peça), então pra arquivos tipo 'Model.blockymodel' que não "
        "batem com o nome real do personagem (ex.: um boss), digite aqui "
        "o nome que você realmente quer"
    ),
    "importer.prop.blockymodel_generate_reference_boxes": (
        "Cria uma malha simples (caixa ou quad) pra cada forma visual do "
        "modelo, parentada à Armature e skinada (100% de peso) ao seu bone "
        "via um Vertex Group + modifier Armature. Útil como referência "
        "visual enquanto anima, e já vem deformável/pintável"
    ),
    "importer.prop.blockymodel_flat_mesh_collections": (
        "Mantém a collection de malha de cada bone num único nível plano, "
        "em vez do layout aninhado padrão (a collection de um bone fica "
        "dentro da collection do bone ancestral mais próximo, espelhando "
        "a hierarquia do próprio modelo -- mesma ideia de pastas no "
        "Blockbench). Ative isto pra achatar tudo num nível só"
    ),
    "importer.prop.blockymodel_generate_uvs": (
        "Gera coordenadas UV pras malhas de referência a partir dos dados "
        "de layout de textura do modelo (offsets de pixel por face). O "
        "tamanho da imagem de textura original não é salvo no arquivo, "
        "então a menos que 'Definir Tamanho do Atlas Manualmente' esteja "
        "ativo abaixo, o tamanho do canvas é INFERIDO a partir do próprio "
        "layout -- isso é só um limite inferior (pode sair alguns pixels "
        "menor em largura/altura se a textura real tiver espaço em branco "
        "não usado), então se você souber as dimensões reais em pixels da "
        "textura, defina-as manualmente pra um resultado exato"
    ),
    "importer.prop.blockymodel_missing_face_mode": (
        "O que fazer com uma face de caixa que não tem entrada no layout "
        "de textura do modelo. CONFIRMADO contra o código-fonte do próprio "
        "plugin oficial do Hytale pro Blockbench (blockymodel.ts): uma "
        "entrada faltando SEMPRE significa que aquela face não tinha "
        "textura nenhuma atribuída no Blockbench -- não existe caso de "
        "'implicitamente escondida por outra peça'. Então 'Pular' abaixo é "
        "o comportamento que bate fielmente com o próprio Blockbench "
        "(recarregar o arquivo lá mostra a mesma face vazia). 'Reusar Face "
        "Oposta' é uma opção puramente cosmética pra quando você preferir "
        "ver alguma textura em vez de um buraco, mesmo sabendo que não bate "
        "com o arquivo original"
    ),
    "importer.prop.blockymodel_missing_face_mode_item_skip": (
        "Não cria geometria pra essa face. Fiel ao que o próprio "
        "Blockbench mostraria -- uma entrada de layout de textura faltando "
        "sempre significa que a face genuinamente não tinha textura"
    ),
    "importer.prop.blockymodel_missing_face_mode_item_opposite": (
        "Cria a face e reaproveita a textura do lado oposto da mesma "
        "caixa. NÃO bate com o que o próprio Blockbench mostraria -- é "
        "puramente um remendo visual pra evitar buracos, pode colar a "
        "textura errada numa face visível"
    ),
    "importer.prop.blockymodel_override_atlas_size": (
        "Usa as dimensões exatas em pixels do seu arquivo de textura em "
        "vez de tentar adivinhá-las a partir dos dados de layout. "
        "Recomendado: abra sua textura (ex.: no Blockbench ou num "
        "visualizador de imagem) e digite a largura/altura aqui"
    ),
    "importer.prop.blockymodel_atlas_width": "Largura exata, em pixels, da imagem de atlas de textura",
    "importer.prop.blockymodel_atlas_height": "Altura exata, em pixels, da imagem de atlas de textura",
    "importer.prop.blockymodel_create_material": (
        "Cria um material compartilhado ligado ao Base Color através das "
        "UVs geradas, aplicado a toda malha de referência. Modelos "
        "Hytale/Blockbench só usam uma textura plana única (sem mapas "
        "PBR), então isso espelha esse comportamento. Se 'Imagem da "
        "Textura' abaixo estiver definida, carrega essa imagem e usa suas "
        "dimensões reais em pixels pro layout de UV (sobrepondo 'Definir "
        "Tamanho do Atlas Manualmente' acima, se também ativo); senão cria "
        "um placeholder em branco do tamanho do atlas em uso"
    ),
    "importer.prop.blockymodel_texture_mode": (
        "'Automático' acha o PNG da textura no disco usando a mesma "
        "convenção do plugin oficial do Hytale pro Blockbench (mesma "
        "pasta do modelo, ou uma subpasta '<NomeDoModelo>_Textures'). "
        "'Manual' deixa você apontar pra um arquivo específico, ignorando "
        "a auto-detecção por completo"
    ),
    "importer.prop.blockymodel_texture_mode_item_auto": (
        "Auto-detecta o PNG da textura ao lado do modelo (mesma convenção "
        "do plugin oficial do Hytale)"
    ),
    "importer.prop.blockymodel_texture_mode_item_manual": (
        "Escolha o PNG da textura você mesmo -- a auto-detecção é "
        "totalmente ignorada"
    ),
    "importer.prop.blockymodel_texture_filepath": (
        "O PNG de textura do modelo. O arquivo .blockymodel só guarda "
        "offsets de pixel por face, não a textura em si nem o tamanho do "
        "canvas -- apontar isto pro arquivo real dá UVs exatas usando as "
        "dimensões reais dele (tem prioridade sobre 'Definir Tamanho do "
        "Atlas Manualmente' acima). Só usado quando 'Modo de Textura' "
        "acima está definido como 'Manual'"
    ),
    "importer.prop.blockymodel_orient_z_up": (
        "O Hytale usa Y como eixo 'pra cima'; o Blender usa Z. Isso "
        "rotaciona SÓ o objeto Armature como um todo (não os bones "
        "individuais) pra o personagem ficar em pé na visão padrão do "
        "Blender. Não afeta valores de pose/animação, que ficam no espaço "
        "local de cada bone"
    ),
    "importer.prop.blockymodel_unit_scale": (
        "O exportador de animação (Export_blockyanim.py) multiplica a "
        "posição por 64 ao salvar. Isso só bate se o rig aqui foi "
        "construído em escala 1/64. Não mude isto a menos que tenha "
        "certeza de um valor diferente"
    ),

    # -----------------------------------------------------------------
    # importer.py -- IMPORT_OT_hytale_bbmodel, tooltips de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "importer.prop.bbmodel_armature_name": (
        "Nome pra Armature nova e sua collection. Deixe vazio pra usar o "
        "nome do próprio projeto (guardado dentro do .bbmodel), ou o nome "
        "do arquivo se isso também estiver vazio"
    ),
    "importer.prop.bbmodel_orient_z_up": (
        "Rotaciona o objeto Armature em 90 graus pra ficar em pé na "
        "viewport Z-up do Blender. Puramente uma rotação de exibição no "
        "próprio objeto Armature -- o dado de bone por baixo não é "
        "tocado"
    ),
    "importer.prop.bbmodel_unit_scale": (
        "Mesmo significado que no importador de .blockymodel -- ver "
        "UNIT_SCALE_DEFAULT em common.py"
    ),
    "importer.prop.bbmodel_generate_reference_boxes": (
        "Cria uma malha pra cada elemento cubo do projeto, parentada à "
        "Armature e skinada (100% de peso) ao bone dono via um Vertex "
        "Group + modifier Armature"
    ),
    "importer.prop.bbmodel_flat_mesh_collections": (
        "Mantém a collection de malha de cada bone num único nível plano, "
        "em vez do layout aninhado padrão (a collection de um bone fica "
        "dentro da collection do bone ancestral mais próximo, espelhando "
        "a hierarquia própria do outliner/pastas do .bbmodel). Ative isto "
        "pra achatar tudo num nível só"
    ),
    "importer.prop.bbmodel_generate_uvs": (
        "Gera coordenadas UV pras malhas de referência a partir do "
        "retângulo de pixel de cada face, já guardado direto no .bbmodel "
        "(sem precisar inferir, diferente do caminho do .blockymodel)"
    ),
    "importer.prop.bbmodel_create_material": (
        "Decodifica a(s) textura(s) embutida(s) no próprio .bbmodel (dado "
        "PNG em base64) e cria um material por textura usada, ligado ao "
        "Base Color/Alpha através das UVs geradas -- não precisa de "
        "arquivo de textura externo, tudo já vem embutido no .bbmodel"
    ),

    # -----------------------------------------------------------------
    # anim_tools.py -- tooltips de botão (Operator.description, v0.14)
    # -----------------------------------------------------------------
    "anim_tools.tooltip.set_fk_ik": "Troca esta cadeia para FK ou IK -- não iguala a pose (use 'Snap "
    "FK/IK' pra isso)",
    "anim_tools.tooltip.set_head_follow": "Lock (segue a rotação do bone predecessor) ou Free (mantém a "
    "rotação própria do Head_CTRL)",
    "anim_tools.tooltip.snap_selected": "Iguala a pose do lado oposto (FK ou IK) à cadeia do bone "
    "selecionado, depois troca pra ele -- faz o snap e a troca num clique só, pra qualquer cadeia que o bone "
    "ativo pertença",
    "anim_tools.tooltip.keyframe_switch": "Insere um keyframe no valor atual deste switch, no frame atual",

    # -----------------------------------------------------------------
    # anim_tools.py -- tooltips de campo (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "anim_tools.prop.set_fk_ik_chain_index": "Índice em armature.hytale_ik_chains",
    "anim_tools.prop.keyframe_switch_chain_index": "Só usado quando switch == 'FK_IK'",

    # -----------------------------------------------------------------
    # exporter.py -- tooltips de botão (Operator.description, v0.14)
    # -----------------------------------------------------------------
    "exporter.tooltip.texture_picker_export_add": "Adiciona uma entrada manual de export de Texture Picker à lista",
    "exporter.tooltip.texture_picker_export_remove": "Remove a entrada de export de Texture Picker selecionada da lista",

    # -----------------------------------------------------------------
    # exporter.py -- HYTALE_export_settings, tooltip de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "exporter.prop.export_settings_collection_name": (
        "Nome da Bone Collection da Armature que contém só os bones "
        "'originais' do jogo pra exportar (Armature Data Properties > "
        "Bone Collections). Se essa collection não existir na armature, "
        "cai pra adivinhar pelo sufixo do nome (_MCH/_CTRL/_IK), o que "
        "não é confiável em rigs complexos"
    ),

    # -----------------------------------------------------------------
    # exporter.py -- HYTALE_texture_picker_export_item, tooltips de
    # campo (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "exporter.prop.texture_picker_source_bone": (
        "Nome do bone auxiliar cuja Location controla o picker do atlas "
        "(ex.: 'ui.texture_picker'). Esse bone em si NÃO é exportado -- "
        "só a Location dele é amostrada"
    ),
    "exporter.prop.texture_picker_target_bone": (
        "Nome exato do bone real do jogo pra anexar o canal "
        "'shapeUvOffset' -- precisa ser um dos bones exportáveis (ex.: "
        "'Mouth', ou qualquer outra peça controlada por atlas)"
    ),
    "exporter.prop.texture_picker_target_bones_extra": (
        "Nomes de bone extras, separados por vírgula, que recebem exatamente o mesmo dado "
        "'shapeUvOffset' do Target Bone acima -- pra personagens cuja parte animada é dividida "
        "entre mais de uma malha/bone (ex.: metades esquerda/direita espelhadas) que precisam "
        "mudar de expressão juntas. Normalmente preenchido automaticamente por 'Create Texture "
        "Picker' a partir dos Companion Bones configurados nesta entrada, não digitado aqui direto"
    ),
    "exporter.prop.texture_picker_step_x": (
        "Em unidades do Blender: o quanto o bone de controle precisa se "
        "mover no X pra a textura da boca/rosto avançar um passo. "
        "Precisa bater com o que sua configuração de shader/driver "
        "realmente usa -- isto não inventa o comportamento, só precisa "
        "descrevê-lo corretamente"
    ),
    "exporter.prop.texture_picker_px_x": (
        "Quantos pixels de textura crus um passo de grid em X representa no arquivo (o jogo "
        "espera offsets de pixel crus, não uma fração 0..1)"
    ),
    "exporter.prop.texture_picker_step_y": "Mesma coisa que Grid Step X, pro movimento em Y do bone de controle",
    "exporter.prop.texture_picker_px_y": "Mesma coisa que Pixels per Step X, pro Y",

    # -----------------------------------------------------------------
    # exporter.py -- EXPORT_OT_hytale_blockyanim, tooltips de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "exporter.prop.blockyanim_bake_animation": (
        "LIGADO (recomendado): amostra a pose final em CADA frame, "
        "exatamente como aparece na viewport (IK, constraints, tudo). "
        "Sempre seguro, mas gera arquivos maiores. DESLIGADO: só "
        "amostra frames que realmente têm um keyframe -- arquivos "
        "menores, mas pode sair errado se o rig usar IK, já que poses "
        "de IK não são linhas retas simples entre keyframes"
    ),
    "exporter.prop.blockyanim_is_loop": (
        "LIGADO: a animação suaviza de volta pra pose inicial no final, "
        "pra poder repetir sem emenda (andar, correr, idle). DESLIGADO: "
        "a animação simplesmente para e segura a última pose (ataques, "
        "mortes, ações únicas). Essa opção vale pra todo arquivo neste "
        "export, EXCETO Actions reexportadas com 'Keep Imported Timing' "
        "LIGADO (Opções Avançadas > Re-Export), que usam o próprio "
        "valor original"
    ),
    "exporter.prop.blockyanim_force_start_end_keying": (
        "Só importa quando 'Bake Every Frame' está DESLIGADO: garante "
        "que o primeiro e o último frame de cada Action sempre sejam "
        "escritos, mesmo que nada tenha sido explicitamente keyframado "
        "exatamente ali. Sem isso, o clip exportado pode começar ou "
        "terminar alguns frames antes/depois do esperado. Fica ligado "
        "automaticamente quando 'Bake Every Frame' está LIGADO"
    ),
    "exporter.prop.blockyanim_export_texture_picker": (
        "Inclui dado 'shapeUvOffset' pra cada instância de Texture "
        "Picker configurada (veja o painel 'Hytale Export' em Object "
        "Properties pra adicionar/editar/remover instâncias). Desligue "
        "pra pular esse canal só nesta exportação, sem apagar nenhuma "
        "instância configurada"
    ),
    "exporter.prop.blockyanim_frame_step": (
        "Só usado quando 'Bake Every Frame' está LIGADO: 1 escreve "
        "cada frame (mais seguro). Um número maior pula frames pra "
        "economizar espaço, ao custo de suavidade -- só aumente isto "
        "se o tamanho do arquivo for um problema de verdade"
    ),
    "exporter.prop.blockyanim_preserved_interpolation": (
        "Só usado quando 'Bake Every Frame' está DESLIGADO: como o "
        "jogo deve se mover suavemente entre dois keyframes. O "
        "Blockyanim só entende dois estilos (não handles Bezier "
        "completos como o Blender), então esse único estilo é usado "
        "pra todo keyframe"
    ),
    "exporter.prop.blockyanim_preserved_interpolation_item_smooth": (
        "Suaviza entrada e saída entre keyframes -- o mais próximo das curvas padrão do Blender"
    ),
    "exporter.prop.blockyanim_preserved_interpolation_item_linear": (
        "Se move em velocidade constante entre keyframes, sem suavização"
    ),
    "exporter.prop.blockyanim_quantize_values": (
        "LIGADO (recomendado): arredonda todo número escrito pra uma "
        "precisão fixa (veja os três valores de Step abaixo), o que "
        "limpa o ruído invisível de ponto flutuante que a matemática "
        "do Blender produz mesmo pra um bone que parece perfeitamente "
        "parado. DESLIGADO: escreve os números exatamente como o "
        "Blender calculou, decimais e tudo"
    ),
    "exporter.prop.blockyanim_position_quantize_step": (
        "Menor mudança de posição que 'Snap to Grid' vai manter, em unidades do jogo. Menor = mais "
        "preciso, arquivo maior"
    ),
    "exporter.prop.blockyanim_rotation_quantize_step": (
        "Menor mudança de rotação que 'Snap to Grid' vai manter. Menor = mais preciso, arquivo maior"
    ),
    "exporter.prop.blockyanim_scale_quantize_step": (
        "Menor mudança de stretch/escala que 'Snap to Grid' vai manter. Menor = mais preciso, arquivo maior"
    ),
    "exporter.prop.blockyanim_position_zero_epsilon": (
        "Um bone que deveria estar perfeitamente parado ainda pode "
        "acabar com um valor de posição microscópico por causa da "
        "matemática de ponto flutuante -- no jogo isso pode parecer um "
        "tremor minúsculo, invisível no Blender. Qualquer posição "
        "menor que isto (em unidades do jogo) é ajustada pra exatamente "
        "zero"
    ),
    "exporter.prop.blockyanim_rotation_zero_epsilon": (
        "Mesma ideia de Position Noise Floor, mas pra rotação: um bone "
        "que deveria estar perfeitamente parado pode acabar com uma "
        "rotação microscópica em vez de nenhuma (muito comum em pernas/"
        "braços IK, onde o solver raramente chega numa resposta EXATA). "
        "Qualquer rotação mais próxima de 'nenhuma rotação' que isto é "
        "ajustada pra exatamente zero"
    ),
    "exporter.prop.blockyanim_skip_redundant_frames": (
        "DESLIGADO (padrão): escreve todo frame amostrado, garantindo "
        "um resultado idêntico ao que você vê no Blender. LIGADO: "
        "também descarta frames que não acrescentam informação real -- "
        "por exemplo, um trecho longo de movimento em linha reta não "
        "precisa de um ponto a cada frame se alguns pontos já descrevem "
        "a mesma curva. Isso deixa o arquivo bem menor, mas é COM PERDA "
        "(pode mudar a curva ligeiramente) -- só ligue se o tamanho do "
        "arquivo ainda for um problema depois de 'Snap to Grid' e do "
        "JSON compacto, que já ajudam de graça"
    ),
    "exporter.prop.blockyanim_position_epsilon": (
        "Só usado quando 'Remove Extra Frames' está LIGADO: o quanto "
        "(em unidades do jogo) um frame de posição/stretch pode se "
        "afastar de uma linha reta antes de ser considerado necessário "
        "manter. Maior = mais frames removidos, menos preciso"
    ),
    "exporter.prop.blockyanim_rotation_epsilon": (
        "Só usado quando 'Remove Extra Frames' está LIGADO: o quanto "
        "um frame de rotação pode se afastar de uma curva suave antes "
        "de ser considerado necessário manter. Maior = mais frames "
        "removidos, menos preciso"
    ),
    "exporter.prop.blockyanim_export_scale": (
        "LIGADO (recomendado): inclui animação de escala/stretch de "
        "bone no arquivo (o canal 'shapeStretch' -- ex.: uma "
        "sobrancelha esticando/encolhendo). Desligue só se este rig "
        "nunca anima stretch e você quer pular essa amostragem "
        "inteira"
    ),
    "exporter.prop.blockyanim_scale_zero_epsilon": (
        "Mesma ideia de Position Noise Floor, mas pra stretch: qualquer escala mais próxima de 1.0 "
        "(sem stretch) que isto, em qualquer eixo, é ajustada pra exatamente 1.0"
    ),
    "exporter.prop.blockyanim_bake_scale_hierarchy": (
        "Bones do Hytale/Blockbench não herdam escala do pai do jeito "
        "que a viewport do Blender faz -- se você só keyframou escala "
        "num bone pai (ex.: encolhendo pra esconder, esperando que os "
        "filhos dentro dele encolham e se aproximem juntos), os filhos "
        "seriam exportados sem mudança nenhuma de escala/posição e "
        "ficariam em tamanho normal, espalhados, no Blockbench/jogo. "
        "Ligue isto pra assar a escala do pai dentro do 'shapeStretch' "
        "exportado de cada filho E puxar o pivot de cada filho em "
        "direção ao do pai, batendo com o que você vê na viewport do "
        "Blender. Só afeta o arquivo exportado -- não toca nos seus "
        "keyframes de verdade"
    ),
    "exporter.prop.blockyanim_unit_scale": (
        "PRECISA bater com o valor exato usado quando este personagem "
        "foi importado (Hytale Blockymodel Importer) -- se não baterem, "
        "toda posição no arquivo exportado vai estar errada por um "
        "fator de escala consistente. Na dúvida, deixe no padrão"
    ),
    "exporter.prop.blockyanim_output_decimal_places": (
        "Quantos dígitos depois do ponto decimal manter pra cada "
        "número no arquivo. Puramente cosmético e não descarta nenhum "
        "keyframe -- só evita que o arquivo fique cheio de números "
        "tipo 0.30000000000000004"
    ),
    "exporter.prop.blockyanim_pretty_print_json": (
        "DESLIGADO (padrão): escreve o arquivo como uma linha compacta "
        "-- menor, e normalmente ninguém precisa ler isso na mão. "
        "LIGADO: escreve bem indentado em várias linhas, puramente pra "
        "um humano poder abrir e ler/comparar (praticamente dobra o "
        "tamanho do arquivo; o jogo e o Blockbench leem os dois "
        "formatos igual)"
    ),
    "exporter.prop.blockyanim_use_source_metadata": (
        "Só importa pra uma Action que foi importada por 'Import "
        "Hytale Animation' e não foi editada desde então. LIGADO: "
        "reaproveita os valores exatos originais de Duration/Loop "
        "daquele arquivo em vez da opção 'Loop?' acima e do tamanho "
        "atual da timeline -- útil pra um export de verificação, pra "
        "conferir que reimportar um arquivo não editado devolve "
        "exatamente o mesmo arquivo. DESLIGADO (padrão, e o que você "
        "quer pra trabalho normal de edição): sempre calcula Duration/"
        "Loop do zero a partir da timeline atual e da opção 'Loop?' "
        "acima. Deixe DESLIGADO sempre que você tiver realmente mudado "
        "a animação, ou uma Duration importada desatualizada, mais "
        "curta que sua edição, pode silenciosamente cortar frames no "
        "arquivo exportado"
    ),

    # -----------------------------------------------------------------
    # anim_importer.py -- IMPORT_OT_hytale_blockyanim, tooltips de
    # campo (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "anim_importer.prop.target_mode": "Em qual camada de bone escrever a animação importada",
    "anim_importer.prop.target_mode_item_org": (
        "Keyframa os bones originais do jogo direto. Funciona em "
        "QUALQUER armature -- riggada ou não -- mas num rig com uma "
        "camada de controle FK/IK por cima, esses keyframes não vão "
        "mover nada (os bones originais estão restritos a seguir a "
        "camada de controle)"
    ),
    "anim_importer.prop.target_mode_item_ctrl": (
        "Escreve nos bones '_CTRL'/'_IK'/pole gerados pela ferramenta "
        "de auto-rig (rigger.py), então a animação importada continua "
        "editável através do rig de controle -- configure Spine/Arms/"
        "Legs abaixo"
    ),
    "anim_importer.prop.action_name": "Deixe vazio pra usar o nome do arquivo",
    "anim_importer.prop.start_frame": "Frame do Blender onde o tempo=0 do arquivo de animação cai",
    "anim_importer.prop.import_fps_preset": (
        "FPS alvo da cena pra este import. Se a cena ainda não estiver "
        "nesse FPS, ele é trocado automaticamente antes de importar -- "
        "arquivos .blockyanim são criados a 60 FPS (FPS_HYTALE), então "
        "manter isto em 60 evita o problema de 'timing parece "
        "comprimido' de importar numa cena com FPS mais baixo. Mesma "
        "lista de Output Properties > Frame Rate do próprio Blender -- "
        "escolha 'Custom' pra definir FPS/Base separadamente, igual lá"
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
    "anim_importer.prop.import_fps_preset_item_custom": "Define FPS e Base separadamente abaixo",
    "anim_importer.prop.import_fps_custom_fps": (
        "Frame Rate customizado -- 'Frame Rate' está definido como "
        "'Custom' -- mesmo campo que Output Properties > Frame Rate > "
        "FPS no próprio Blender. Taxa efetiva é FPS / Base"
    ),
    "anim_importer.prop.import_fps_custom_base": (
        "Frame Rate customizado -- 'Frame Rate' está definido como "
        "'Custom' -- mesmo campo que Output Properties > Frame Rate > "
        "Base no próprio Blender. Taxa efetiva é FPS / Base"
    ),
    "anim_importer.prop.loop_mode": "Se este clip deve fechar num loop sem emenda",
    "anim_importer.prop.loop_mode_item_auto": (
        "Usa a própria flag 'holdLastKeyframe' do arquivo: false = "
        "ciclo (loop), true = início & fim (segura a última pose)"
    ),
    "anim_importer.prop.loop_mode_item_cycle": (
        "Força este clip a fechar num loop: adiciona uma pose de "
        "fechamento em 'duration' que bate com o primeiro keyframe de "
        "cada canal, pra fluir de volta pra si mesmo -- use pra ciclos "
        "de andar/correr/idle"
    ),
    "anim_importer.prop.loop_mode_item_one_shot": (
        "Força este clip a só segurar a última pose no final -- use "
        "pra ações sem loop (ataques, mortes, gestos únicos)"
    ),
    "anim_importer.prop.bake_mode": (
        "Calcula a pose exata em cada frame direto dos keyframes crus "
        "do arquivo (interpolação esférica adequada pra rotação), em "
        "vez de depender das F-Curves Bezier por-componente do próprio "
        "Blender. Produz bem mais keyframes, mas evita artefatos de "
        "interpolação de rotação -- especialmente perceptível com "
        "poucos keyframes de orientação bem espaçados (comum neste "
        "formato). Recomendado pra imports em Cycle. Afeta posição/"
        "rotação em 'Original Bones' e stretch de shape nos dois "
        "alvos -- posição/rotação de 'Control Bones (FK)' sempre "
        "assa cada frame de qualquer jeito"
    ),
    "anim_importer.prop.keep_spine_follow": (
        "Só Control FK, Control IK e Default (FK + IK): por padrão, "
        "isto fica ATIVO -- qualquer constraint extra num bone de "
        "controle (ex.: Belly_CTRL/Chest_CTRL seguindo parcialmente "
        "root.spine_CTRL) continua se mesclando durante o import, e em "
        "modos que escrevem IK, os constraints Child Of de cada pole "
        "target também continuam ativos. Desative isto pra mutar esses "
        "constraints em vez disso, fazendo a pose importada bater "
        "exatamente com o arquivo de origem nos bones afetados -- ao "
        "custo de root.spine_CTRL (e o Child Of dos poles) não poder "
        "mais ser usado como ferramenta de ajuste fino em cima da "
        "animação importada"
    ),
    "anim_importer.prop.spine_mode": (
        "Só Controllers: como os bones raiz utilitários do rig "
        "(root.master_CTRL/root.pelvis_CTRL, rigger.py) se comportam. "
        "A animação de origem só move Pelvis/Belly/Chest -- esses "
        "bones raiz nunca se movem sozinhos, então precisam disto pra "
        "viajar junto com a animação (ex.: ciclos de andar/correr) em "
        "vez de ficar congelados perto da origem"
    ),
    "anim_importer.prop.spine_mode_item_default": (
        "root.master_CTRL segue a posição e rotação animadas da "
        "Pelvis a cada frame -- root.pelvis_CTRL e Belly_CTRL (filhos "
        "reais de root.master_CTRL) viajam junto automaticamente. "
        "Recomendado -- bate com o movimento de raiz da animação de "
        "origem"
    ),
    "anim_importer.prop.spine_mode_item_manual": (
        "root.master_CTRL/root.pelvis_CTRL ficam congelados em "
        "repouso -- Pelvis/Belly/Chest continuam keyframados "
        "normalmente, mas o personagem não vai viajar com o movimento "
        "de raiz (ex.: andar vai parecer andar no lugar). Deixa "
        "root.spine_CTRL livre como um controle manual de ajuste fino "
        "em cima da animação importada"
    ),
    "anim_importer.prop.arms_mode": (
        "Só Controllers: como as cadeias tipo 'Arm' "
        "(armature.hytale_ik_chains, rigger.py) são keyframadas"
    ),
    "anim_importer.prop.arms_mode_item_both": (
        "Escreve os dois de uma vez -- todo segmento de braço recebe "
        "seu '_CTRL' de FK E a ponta IK da cadeia (mão) + pole também "
        "são keyframados. fk_ik_switch começa em FK (0); alterne a "
        "qualquer momento depois, por cadeia, pra pré-visualizar ou "
        "usar a versão IK em vez disso -- sem precisar reimportar"
    ),
    "anim_importer.prop.arms_mode_item_ctrl_fk": (
        "Só os bones '_CTRL' por segmento -- fk_ik_switch fica "
        "intocado (a cadeia não recebe nenhum keyframe de '_IK'/pole)"
    ),
    "anim_importer.prop.arms_mode_item_ik": (
        "Só a ponta '_IK' (mão) + pole target -- os bones '_CTRL' por "
        "segmento são pulados, e fk_ik_switch é definido como IK (1)"
    ),
    "anim_importer.prop.legs_mode": (
        "Só Controllers: como as cadeias tipo 'Leg' "
        "(armature.hytale_ik_chains, rigger.py) são keyframadas -- "
        "mesmas 3 opções de Arms, aplicadas independentemente"
    ),
    "anim_importer.prop.legs_mode_item_both": (
        "Escreve os dois de uma vez -- todo segmento de perna recebe "
        "seu '_CTRL' de FK E a ponta IK da cadeia (pé) + pole também "
        "são keyframados. fk_ik_switch começa em FK (0); alterne a "
        "qualquer momento depois, por cadeia, pra pré-visualizar ou "
        "usar a versão IK em vez disso -- sem precisar reimportar"
    ),
    "anim_importer.prop.legs_mode_item_ctrl_fk": (
        "Só os bones '_CTRL' por segmento -- fk_ik_switch fica "
        "intocado (a cadeia não recebe nenhum keyframe de '_IK'/pole)"
    ),
    "anim_importer.prop.legs_mode_item_ik": (
        "Só a ponta '_IK' (pé) + pole target -- os bones '_CTRL' por "
        "segmento são pulados, e fk_ik_switch é definido como IK (1)"
    ),

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
    "panel.export_texture_picker": "Texture Picker",
    "panel.export_collection": "Coleção de Export",
    "panel.texture_picker_target_bone": "Bone Alvo",

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
    "panel.ik_chains_box": "Configurações de Bones",
    "panel.btn_auto_detect_bones": "Auto-Detectar Bones",
    # v0.7.5 -- headers dos 2 grupos visuais dentro do formulário Arm/Leg
    # (ver _draw_rig_bone_settings em interface.py) -- "Bones" sempre
    # visível, "Pole" collapsible.
    "panel.bone_settings_group_bones": "Bones",
    "panel.bone_settings_group_pole": "Pole",
    "panel.load_preset": "Carregar Preset...",
    "panel.apply_ik_joint_fix": "Aplicar Correção de Junta IK (do Template)",
    "panel.field_root_bone": "Bone Raiz",
    "panel.field_tip_bone": "Bone da Ponta",
    "panel.field_pole_bone": "Referência do Pole",
    "panel.field_root_parent": "Pai da Raiz",
    "panel.field_side": "Lado",
    # v0.7.5 -- ERA "Pole na Frente (+Z)"/"Também Copiar Localização no
    # IK (raiz)" -- mesmo motivo do en.py, texto mais direto sobre o
    # EFEITO do toggle.
    "panel.field_pole_in_front": "Inverter Direção",
    "panel.field_copy_location_ik": "Seguir Alvo do IK",
    # v0.7.5 -- prefixo "do Pole" removido (redundante dentro da caixa
    # "Pole" -- ver bone_settings_group_pole acima).
    "panel.field_pole_distance": "Distância",
    "panel.field_pole_angle_mode": "Modo do Ângulo",
    "panel.field_pole_angle_preset_name": "Preset do Ângulo",
    "panel.field_pole_angle_manual": "Ângulo (graus)",
    "panel.field_pole_angle_fine_tune": "Ajuste Fino do Ângulo (graus)",
    "panel.btn_create_rig": "Criar Rig",
    "panel.btn_remove_generated": "Remover Bones Gerados",

    # -----------------------------------------------------------------
    # interface.py -- campos por chain_type (Arm/Leg/Chain/Head/Spine/
    # Attachments/Texture Picker), aba Rig
    # -----------------------------------------------------------------
    "panel.field_chain_type": "Tipo",
    "panel.field_arm_shoulder": "Ombro / Parent Raiz",
    "panel.field_arm_upper": "Braço / Bone Raiz",
    "panel.field_arm_forearm": "Antebraço / Referência do Pole",
    "panel.field_arm_hand": "Mão / Bone Ponta",
    "panel.field_leg_pelvis": "Pelve / Parent Raiz",
    "panel.field_leg_thigh": "Coxa / Bone Raiz",
    "panel.field_leg_calf": "Panturrilha / Referência do Pole",
    "panel.field_leg_foot": "Pé / Bone Ponta",
    "panel.field_tail_parent": "Anexar A (Parent)",
    "panel.field_tail_start": "Bone Inicial",
    "panel.field_tail_end": "Bone Final",
    "panel.field_tail_tip_rotation_axis": "Eixo de Rotação da Ponta",
    "panel.field_tail_tip_rotation_deg": "Rotação da Ponta (graus)",
    "panel.field_tail_use_connect": "Conectado",
    "panel.hint_tail_no_ik": "Pronto para add-ons de física",
    "panel.field_neck_count": "Quantidade de Bones do Pescoço",
    "panel.field_neck_1": "Pescoço",
    "panel.field_neck_2": "Pescoço 2",
    "panel.field_neck_3": "Pescoço 3",
    "panel.field_neck_4": "Pescoço 4",
    "panel.field_neck_5": "Pescoço 5",
    "panel.field_head_bone": "Cabeça",
    "panel.field_head_end_bone": "Fim da Cabeça",
    "panel.field_spine_count": "Quantidade de Bones da Coluna",
    "panel.field_pelvis_bone": "Pelve",
    "panel.field_spine_1": "Coluna1",
    "panel.field_spine_2": "Coluna2",
    "panel.field_spine_3": "Coluna3",
    "panel.field_spine_4": "Coluna4",
    "panel.field_spine_ctrl_enabled": "Controlador Root da Coluna",
    "panel.hint_spine_no_ik": "Só organizacional",
    "panel.field_continuous_chain": "Cadeia Contínua",
    "panel.field_continuous_chain_link": "Conectar Último Bone A",
    "panel.field_head_follow_enabled": "Cabeça Livre/Travada",
    "panel.head_camera_section": "Câmera em Primeira Pessoa",
    "panel.field_head_camera_enabled": "Criar Câmera em Primeira Pessoa",
    "panel.field_head_camera_parent_bone": "Bone Pai da Câmera",
    "panel.head_camera_offset_label": "Offset da Câmera",
    "panel.field_head_camera_offset_x": "X",
    "panel.field_head_camera_offset_y": "Y",
    "panel.field_head_camera_offset_z": "Z",
    "panel.head_camera_rotation_label": "Rotação da Câmera (graus)",
    "panel.field_head_camera_rotation_x": "X",
    "panel.field_head_camera_rotation_y": "Y",
    "panel.field_head_camera_rotation_z": "Z",
    "panel.field_head_camera_fov": "FOV (graus)",
    "panel.hint_head_camera": (
        "Posição/rotação são um ponto de partida -- ajuste fino pra alinhar com os olhos deste "
        "personagem"
    ),
    "panel.field_attachments_count": "Quantidade de Bones de Attachment",
    "panel.field_attachment": "Attachment",
    "panel.hint_attachments_no_ik": "Só organizacional",
    "panel.field_texture_picker_bone": "Bone Alvo",
    "panel.field_texture_picker_ui_parent_bone": "Parent do Picker (opc.)",
    "panel.texture_picker_section_plane": "Imagem de Referência",
    "panel.field_texture_picker_plane_scale": "Tamanho",
    "panel.field_texture_picker_plane_offset_x": "Offset X",
    "panel.field_texture_picker_plane_offset_y": "Offset Y",
    "panel.hint_texture_picker_no_ik": "Cria um texture picker, não uma cadeia de bones",
    "panel.texture_picker_section_companions": "Companion Bones",
    "panel.field_texture_picker_extra_count": "Quantidade",
    "panel.field_texture_picker_extra_bone": "Bone",
    "panel.hint_texture_picker_companions_empty": (
        "Para bones extras que se movem junto com este (ex.: metades espelhadas)"
    ),
    "panel.texture_picker_extra_target_bones": "Companion Target Bones (preenchido automaticamente)",
    "panel.texture_picker_section_grid": "Grade",
    "panel.field_texture_picker_grid_cols": "Colunas",
    "panel.field_texture_picker_grid_rows": "Linhas",
    "panel.field_texture_picker_grid_cell_width": "Largura da Célula",
    "panel.field_texture_picker_grid_cell_height": "Altura da Célula",
    "panel.field_collection": "Collection",

    # -----------------------------------------------------------------
    # interface.py -- Collection Settings, aba Animation
    # -----------------------------------------------------------------
    "panel.bone_collections_box": "Configurações de Collection",
    "panel.btn_load_default_collections": "Carregar Collections Padrão",
    "panel.btn_reset_bone_collection_grid": "Restaurar Linha/Coluna aos Padrões",
    "panel.hint_bone_collections": "Organize como os bones são agrupados para animação.",
    "panel.field_entry_type": "Tipo",
    "panel.field_section": "Seção",
    "panel.field_section_order": "Ordem",
    "panel.bone_collection_options_for": "Opções de '{name}'",
    "panel.field_parent": "Parent",
    "panel.field_show_in_animation": "Mostrar na Aba Animation",
    "panel.field_grid_row": "Linha",
    "panel.field_grid_column": "Coluna",

    # -----------------------------------------------------------------
    # interface.py -- Validate Rig / Shape Edit Mode / Vertex Edit
    # Mode / Mirror Shape, aba Rig
    # -----------------------------------------------------------------
    "panel.btn_validate_rig": "Verificar Rig",
    "panel.btn_shape_edit_enter": "Modo de Edição de Shape",
    "panel.btn_shape_edit_finish": "Finalizar Modo de Edição de Shape",
    "panel.hint_shape_edit_no_active_bone": (
        "Selecione um bone em Pose Mode para editar ou espelhar seu custom shape."
    ),
    "panel.btn_mirror_shape": "Espelhar Shape",
    "panel.btn_use_selected_as_widget": "Usar Objeto Selecionado como Widget",
    "panel.field_shape_translation": "Posição do Shape",
    "panel.field_shape_rotation": "Rotação do Shape",
    "panel.field_shape_scale": "Escala do Shape",
    "panel.btn_shape_vertex_edit_enter": "Editar Vértices do Shape",
    "panel.btn_shape_vertex_edit_finish": "Finalizar Edição de Vértices",
    "panel.label_vertex_edit_active": "Editando vértices do custom shape",

    # -----------------------------------------------------------------
    # interface.py -- aba Animation (Bone Collections/FK-IK/Head Follow)
    # -----------------------------------------------------------------
    "panel.hint_anim_none": "Selecione uma armature para ver seus controles de animação.",
    "panel.anim_collections_box": "Collections de Bones",
    "panel.hint_anim_no_rig": "Nenhuma bone collection encontrada ainda -- gere o rig primeiro.",
    "panel.anim_fkik_box": "FK / IK",
    "panel.btn_snap_selected": "Snap FK/IK",
    "panel.hint_anim_no_fkik": "Nenhuma cadeia de Braço/Perna com switch de FK/IK gerado ainda.",
    "panel.anim_head_follow_box": "Cabeça Livre/Travada",

    # -----------------------------------------------------------------
    # interface.py -- avisos reaproveitados em mais de uma aba
    # -----------------------------------------------------------------
    "panel.warn_anim_experimental": "Experimental",
    "panel.warn_texture_picker_wip_short": "WIP",
    "panel.warn_rig_experimental": "Geração de rig é experimental",

    # -----------------------------------------------------------------
    # rigger/rig.py -- Shape Edit Mode + Vertex Edit Mode + Mirror
    # Shape, tooltips de botão (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.shape_edit_mode_enter": (
        "Muta os drivers de escala de shape FK/IK pra você poder redimensionar livremente o "
        "custom shape de cada controle -- use 'Finish Shape Edit Mode' depois pra travar o novo "
        "tamanho como o novo valor máximo do driver"
    ),
    "rigger.tooltip.shape_edit_mode_finish": (
        "Trava os tamanhos de custom shape definidos durante o Shape Edit Mode como o novo "
        "tamanho máximo, e restaura os drivers de escala de shape FK/IK"
    ),
    "rigger.tooltip.shape_vertex_edit_mode_enter": (
        "Entra em Edit Mode direto na malha do custom shape do bone ativo, escondendo todo "
        "outro widget deste personagem -- use 'Finish Vertex Edit' depois pra voltar ao Pose "
        "Mode"
    ),
    "rigger.tooltip.shape_vertex_edit_mode_finish": (
        "Sai do Edit Mode do widget, esconde de novo os widgets deste personagem, e volta ao "
        "Pose Mode"
    ),
    "rigger.tooltip.mirror_shape": (
        "Apaga o shape próprio do bone oposto L-/R- (se houver) e substitui por uma cópia "
        "espelhada da malha de shape deste bone, incluindo Location/Rotation/Scale"
    ),
    "rigger.tooltip.use_selected_as_widget": (
        "Copia a geometria do outro objeto de malha selecionado pro custom shape do bone ativo -- "
        "permite usar uma malha totalmente customizada, modelada à mão, como widget, em vez de "
        "editar em cima do shape da biblioteca"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- operadores de gerenciar a lista de cadeias IK,
    # tooltips de botão e de campo (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.ik_chain_add": "Adiciona uma entrada vazia (Arm/Leg/Tail/Head/Spine) à lista",
    "rigger.tooltip.ik_chain_remove": "Remove a cadeia de IK selecionada da lista",
    "rigger.tooltip.ik_chain_move": "Move a entrada selecionada pra cima ou pra baixo na lista",
    "rigger.prop.ik_chain_move_direction_item_up": "Move a entrada uma posição pra cima",
    "rigger.prop.ik_chain_move_direction_item_down": "Move a entrada uma posição pra baixo",
    "rigger.tooltip.ik_chain_set_count": "Define a quantidade exata de cadeias IK na lista, adicionando ou removendo no fim",
    "rigger.tooltip.ik_chain_pick_bone": "Copia o nome do bone atualmente selecionado pra este campo",
    "rigger.tooltip.ik_chain_auto_detect": (
        "Varre os nomes de bone deste armature e tenta adicionar entradas de Head, Spine, Arm L/R "
        "e Leg L/R automaticamente, com base em palavras-chave comuns (Head/Neck, Pelvis/Spine, "
        "Shoulder/Arm/Forearm/Hand, Thigh/Calf/Foot) e prefixos de lado L-/R-. Nunca sobrescreve "
        "uma entrada que já existe pro mesmo tipo/lado -- sempre confira os bones preenchidos "
        "antes de usar o Create Rig"
    ),
    "rigger.tooltip.ik_chain_load_defaults": "Carrega um rig template calibrado, substituindo a lista atual de cadeias IK",
    "rigger.prop.ik_chain_load_defaults_preset": (
        "Nome do rig template pra carregar -- deixe vazio pra usar o que está selecionado "
        "atualmente no dropdown Character Templates (wm.hytale_rig_template_selected, ver "
        "interface.py)"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- operadores de Collection Settings, tooltips de
    # botão e de campo (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.bone_collection_load_defaults": (
        "Preenche a lista com as collections nativas (Head/Spine/Body/Arm L/Arm R/Leg L/Leg R/"
        "Root)"
    ),
    "rigger.tooltip.bone_collection_reset_grid": (
        "Corrige Linha/Coluna das collections nativas (Head/Spine/Body/Arm L/Arm R/Leg L/Leg R/"
        "Root/Tail/Attachments) de volta pra posição de grade padrão, readicionando qualquer uma "
        "que tenha sido apagada da lista. Collections customizadas nunca são tocadas"
    ),
    "rigger.tooltip.bone_collection_add": (
        "Adiciona uma nova Collection (uma bone collection de verdade) ou Section (um cabeçalho "
        "visual) à lista"
    ),
    "rigger.prop.bone_collection_add_entry_type_item_collection": (
        "Uma bone collection de verdade -- bones podem ser atribuídos a ela"
    ),
    "rigger.prop.bone_collection_add_entry_type_item_section": (
        "Um cabeçalho visual na aba Animation -- não cria nenhuma bone collection real"
    ),
    "rigger.tooltip.bone_collection_remove": "Remove a entrada selecionada da lista",
    "rigger.tooltip.bone_collection_move": "Move a entrada selecionada pra cima ou pra baixo na lista",
    "rigger.prop.bone_collection_move_direction_item_up": "Move a entrada uma posição pra cima",
    "rigger.prop.bone_collection_move_direction_item_down": "Move a entrada uma posição pra baixo",

    # -----------------------------------------------------------------
    # rigger/rig.py -- RIG_OT_hytale_validate_rig, tooltip de botão e
    # de campo (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.validate_rig": (
        "Verifica a lista de cadeias IK e a bone collection de exportação em busca de erros "
        "comuns (só relatório)"
    ),
    "rigger.prop.validate_rig_export_collection_name": (
        "Nome da bone collection onde os bones originais (não gerados) devem estar -- mesmo nome "
        "que exporter.py usa por padrão; mude só se você renomeou essa collection"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- RIG_OT_hytale_clear_generated, tooltips de botão
    # e de campo (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.clear_generated": "Apaga todo bone gerado, mantendo só os originais",
    "rigger.prop.clear_generated_mode_item_only_rig": (
        "Apaga bones e collections gerados. Widgets, Collection Settings e Bone Settings são "
        "mantidos -- seguro se você editou shapes à mão em Shape Edit Mode"
    ),
    "rigger.prop.clear_generated_mode_item_delete_all": (
        "Apaga tudo: bones, collections, widgets, Collection Settings e Bone Settings -- volta a "
        "ser uma armature recém-importada"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- Texture Picker + First Person Camera, tooltips
    # de botão (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.texture_picker_create": (
        "Constrói um rig de UV-picker de atlas de textura pra ela (um par de bones root.ui/"
        "cursor dedicado + plane de referência) a partir dos valores de Manual Grid"
    ),
    "rigger.tooltip.texture_picker_remove": (
        "Remove o rig de Texture Picker gerado (par de bones root.ui/cursor, plane de "
        "referência, driver de material) desta entrada"
    ),
    "rigger.tooltip.camera_create": "Cria (ou atualiza) um objeto Camera em Primeira Pessoa, parentado ao bone escolhido",
    "rigger.tooltip.camera_remove": "Remove o objeto Camera em Primeira Pessoa gerado para esta armature",

    # -----------------------------------------------------------------
    # rigger/rig.py -- RIG_OT_hytale_generate_rig ("Create Rig"),
    # tooltip de botão (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.generate_rig": "Cria ou atualiza as camadas do rig, constraints e custom shapes",

    # -----------------------------------------------------------------
    # rigger/rig.py -- operadores de template (Rig/Shape/Collection),
    # tooltips de botão e de campo (v0.14)
    # -----------------------------------------------------------------
    "rigger.tooltip.shape_template_apply": "Define o shape template ativo (rode 'Create Rig' de novo pra aplicar)",
    "rigger.prop.shape_template_apply_template": (
        "Nome do shape template pra ativar -- deixe vazio pra usar o que está selecionado "
        "atualmente no dropdown Character Templates (wm.hytale_shape_template_selected, ver "
        "interface.py)"
    ),
    "rigger.tooltip.rig_template_save": "Salva a lista atual de cadeias IK como um template novo na sua pasta Documents/Hyblend",
    "rigger.tooltip.rig_template_delete": "Apaga o rig template selecionado da sua pasta Documents/Hyblend (só templates de usuário)",
    "rigger.tooltip.shape_template_save": "Salva os custom shapes atuais como um template novo na sua pasta Documents/Hyblend",
    "rigger.tooltip.shape_template_delete": "Apaga o shape template selecionado da sua pasta Documents/Hyblend (só templates de usuário)",
    "rigger.tooltip.collection_template_save": (
        "Salva as bone collections customizadas da armature (criadas via o painel nativo Bone "
        "Collections do Blender) como um template novo na sua pasta Documents/Hyblend"
    ),
    "rigger.tooltip.collection_template_apply": "Aplica o collection template selecionado na armature ativa",
    "rigger.prop.collection_template_apply_template_name": (
        "Nome do collection template pra aplicar -- deixe vazio pra usar o que está selecionado "
        "atualmente no dropdown Character Templates (wm.hytale_collection_template_selected, ver "
        "interface.py)"
    ),
    "rigger.tooltip.collection_template_delete": (
        "Apaga o collection template selecionado da sua pasta Documents/Hyblend (só templates de "
        "usuário)"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- ensure_switch_property, tooltip de custom
    # property EM RUNTIME (id_properties_ui, não bpy.props -- v0.14).
    # Recriado toda vez que "Create Rig" roda, então NÃO precisa de
    # @localized_props/re-registro -- só tr() na hora certa.
    # -----------------------------------------------------------------
    "rigger.runtime.fk_ik_switch_description": "0 = FK, 1 = IK",
    "rigger.runtime.head_follow_switch_description": (
        "1 = Segue {source} (padrão), 0 = Rotação livre (Head_CTRL mantém sua própria "
        "rotação/escala, mas continua seguindo a posição de {source})"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- HytaleBoneCollectionItem, tooltips de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "rigger.prop.bone_collection_item_name": (
        "Nome -- para uma Collection, é também o nome real da bone collection do Blender depois "
        "de 'Create Rig'. Para uma Section, é só o texto do cabeçalho mostrado na aba Animation"
    ),
    "rigger.prop.bone_collection_item_entry_type_item_collection": (
        "Uma bone collection de verdade -- bones podem ser atribuídos a ela (via "
        "'Collection' nas entradas de Bone Settings)"
    ),
    "rigger.prop.bone_collection_item_entry_type_item_section": (
        "Um cabeçalho visual na aba Animation, agrupando Collections -- não cria "
        "nenhuma bone collection real"
    ),
    "rigger.prop.bone_collection_item_parent": (
        "Sob qual Section esta entrada fica -- para uma Collection, onde o botão dela aparece na "
        "aba Animation; para uma Section, sob qual outra Section ela está aninhada. 'Root / None' "
        "significa nível raiz (Section) ou cai pra 'Main' (Collection). Puramente visual, não afeta "
        "a hierarquia real de bone collection"
    ),
    "rigger.prop.bone_collection_item_show_in_animation_tab": (
        "Se um botão de mostrar/esconder desta collection aparece na caixa 'Bone Collections' da "
        "aba Animation. Desligado só esconde o botão aqui -- a collection em si não é afetada em "
        "nenhum outro lugar"
    ),
    "rigger.prop.bone_collection_item_row": (
        "Posição vertical entre irmãos (0 = topo, quanto maior, mais pra baixo). Para uma "
        "Collection, irmãos que compartilham a mesma Row ficam lado a lado, ordenados por Column"
    ),
    "rigger.prop.bone_collection_item_column": (
        "Posição horizontal dentro da Row (0 = mais à esquerda, quanto maior, mais à direita). "
        "Entradas com a mesma Row E Column são ordenadas alfabeticamente. Só pra Collection -- uma "
        "Section só usa Row"
    ),

    # -----------------------------------------------------------------
    # rigger/rig.py -- HytaleIKChainItem, tooltips de campo
    # (@localized_props, v0.14)
    # -----------------------------------------------------------------
    "rigger.prop.ik_chain_chain_type": "O que esta entrada configura -- veja o seletor de tipo abaixo pros detalhes de cada um",
    "rigger.prop.ik_chain_chain_type_item_arm": (
        "Membro de dois segmentos (padrão ombro-braço-antebraço-mão) -- cadeia trocável entre IK/FK"
    ),
    "rigger.prop.ik_chain_chain_type_item_leg": (
        "Membro de dois segmentos (padrão pelve-coxa-panturrilha-pé) -- cadeia trocável entre IK/FK"
    ),
    "rigger.prop.ik_chain_chain_type_item_chain": (
        "Cadeia de bones conectados, da raiz até a ponta, sem IK -- pra caudas, orelhas compridas, "
        "ou qualquer sequência de bones que deva se mover junto"
    ),
    "rigger.prop.ik_chain_chain_type_item_head": (
        "Identifica os bones de controle Pescoço (1-5 bones) + Cabeça + Fim da Cabeça -- sem IK, "
        "só organizacional"
    ),
    "rigger.prop.ik_chain_chain_type_item_spine": (
        "Identifica os bones de controle Pelve + Coluna (1-4 bones) -- sem IK, só organizacional"
    ),
    "rigger.prop.ik_chain_chain_type_item_attachments": (
        "Identifica bones de controle de Attachment específicos por nome -- sem IK, só "
        "organizacional, além da detecção automática por nome"
    ),
    "rigger.prop.ik_chain_chain_type_item_texture_picker": (
        "Identifica um bone de controle cujo material é um atlas de textura -- constrói um rig de "
        "UV-picker pra ele. Sem IK"
    ),
    "rigger.prop.ik_chain_label": "Nome livre só pra identificar esta entrada na lista (ex.: Arm L)",
    "rigger.prop.ik_chain_root_bone": "Primeiro bone da cadeia (ex.: L-Arm, L-Thigh, ou o primeiro bone de cauda)",
    "rigger.prop.ik_chain_tip_bone": (
        "Último bone da cadeia -- o alvo/efetor pra Arm/Leg (ex.: L-Hand, L-Foot), ou o último "
        "bone de cauda pra Tail"
    ),
    "rigger.prop.ik_chain_pole_bone": (
        "Só Arm/Leg. Bone usado como referência de posição/orientação pro pole target (ex.: "
        "L-Forearm). Vazio = usa automaticamente o bone do meio do caminho raiz->ponta"
    ),
    "rigger.prop.ik_chain_parent_override": (
        "Bone ao qual a raiz desta cadeia é parentada (ex.: L-Shoulder_CTRL, Pelvis). Vazio = "
        "sem parent"
    ),
    "rigger.prop.ik_chain_tail_tip_rotation_axis": "Eixo local em torno do qual o ângulo de Tip Rotation dobra",
    "rigger.prop.ik_chain_tail_tip_rotation_axis_item_x": "Eixo X local",
    "rigger.prop.ik_chain_tail_tip_rotation_axis_item_y": (
        "Eixo Y local (a direção própria do bone -- só gira o roll, não dobra)"
    ),
    "rigger.prop.ik_chain_tail_tip_rotation_axis_item_z": "Eixo Z local",
    "rigger.prop.ik_chain_tail_tip_rotation_deg": (
        "Rotação extra aplicada à pose de repouso do bone da ponta, em torno de Tip Rotation Axis"
    ),
    "rigger.prop.ik_chain_tail_use_connect": (
        "Ativa o 'Connected' nativo do Blender (bone.use_connect) nos bones de controle desta "
        "cadeia -- desligado por padrão, já que a posição da cadeia já bate certo sem isso"
    ),
    "rigger.prop.ik_chain_side": (
        "Lado do corpo desta cadeia -- usado pelos presets de pole_angle (ex.: modo Arm) que "
        "precisam de um valor diferente por lado"
    ),
    "rigger.prop.ik_chain_pole_invert": (
        "Pole na frente (eixo Z positivo do bone de referência) em vez de atrás (padrão, -Z)"
    ),
    "rigger.prop.ik_chain_pole_distance": "Distância do pole target até o bone de referência (pole_bone)",
    "rigger.prop.ik_chain_pole_angle_mode_item_auto": (
        "Calcula o ângulo do pole automaticamente a partir da pose de repouso -- padrão seguro "
        "pra qualquer personagem"
    ),
    "rigger.prop.ik_chain_pole_angle_mode_item_preset": (
        "Usa um valor calibrado dos presets do rig template ativo"
    ),
    "rigger.prop.ik_chain_pole_angle_mode_item_manual": "Usa o valor digitado em Pole Angle diretamente",
    "rigger.prop.ik_chain_pole_angle_preset_name": (
        "Nome da entrada (definida em pole_angle_presets do rig template ativo, ex.: 'ARM') pra "
        "usar quando Pole Angle Mode = Preset. Ignorado em modo Auto/Manual"
    ),
    "rigger.prop.ik_chain_pole_angle_manual": (
        "Valor final de pole_angle, usado só em modo Manual. Ponto de partida sugerido: 90 ou -90 "
        "(cotovelo/joelho típico) -- ajuste o sinal/valor visualmente até o pole centralizar"
    ),
    "rigger.prop.ik_chain_pole_angle_fine_tune": "Somado ao valor calculado automaticamente -- usado só em modo Auto",
    "rigger.prop.ik_chain_extra_ik_location": (
        "Também segue a posição do alvo no IK, não só rotação/escala -- necessário quando o bone "
        "raiz não segue a hierarquia normal de parent"
    ),
    "rigger.prop.ik_chain_neck_count": "Quantos campos de bone de Pescoço mostrar abaixo (0-5). Head/Head End são separados, sempre mostrados",
    "rigger.prop.ik_chain_org_bone_name_hint": (
        "Nome do bone original -- digite/escolha o nome do bone ORIGINAL (ex.: 'Head'), não "
        "'_CTRL': o bone de controle correspondente é resolvido automaticamente"
    ),
    "rigger.prop.ik_chain_head_bone": (
        "Bone original da cabeça (usa por padrão o mesmo bone que HEAD_COLLECTION_ROOT já aponta "
        "pro rig 'Player', sem o sufixo '_CTRL' -- ver constants.py) -- digite/escolha o nome do "
        "bone ORIGINAL (ex.: 'Head'), não '_CTRL': o bone de controle correspondente é resolvido "
        "automaticamente"
    ),
    "rigger.prop.ik_chain_head_end_bone": (
        "Bone opcional na ponta extrema da cabeça (ex.: um bone de fim de queixo/maxilar) -- "
        "deixe vazio se este rig não tiver um -- digite/escolha o nome do bone ORIGINAL (ex.: "
        "'Head'), não '_CTRL': o bone de controle correspondente é resolvido automaticamente"
    ),
    "rigger.prop.ik_chain_spine_count": (
        "Número total de bones nesta coluna, incluindo Pelvis (1-5). Ex.: 3 = Pelvis + Spine1 + "
        "Spine2"
    ),
    "rigger.prop.ik_chain_spine_ctrl_enabled": (
        "Se 'Create Rig' cria o root.spine_CTRL, além dos constraints de Spine Follow em "
        "Belly_CTRL/Chest_CTRL que dependem dele. Ligado por padrão. Desligar depois que o "
        "root.spine_CTRL já existe não apaga ele -- rode 'Remove Generated Bones' + 'Create Rig' "
        "de novo pra remover de vez."
    ),
    "rigger.prop.ik_chain_continuous_chain": (
        "Redireciona a Tail (ponta) do '_CTRL' de cada bone listado pra tocar a Head (início) do "
        "próximo (mesmo truque que o tipo Chain já usa) -- faz a cadeia parecer/se comportar como "
        "uma sequência conectada de bones em vez de controles independentes flutuando. Desligado "
        "por padrão, não afeta rigs existentes a menos que seja ligado -- só a Tail se move, a "
        "Head de cada bone sempre fica na posição original."
    ),
    "rigger.prop.ik_chain_continuous_chain_link_bone": (
        "Opcional. Nome do bone original cuja Head o último bone listado desta entrada deve "
        "apontar sua Tail (ex.: uma Spine terminando em 'Chest' conectando numa cadeia Head "
        "começando em 'Neck') -- deixe vazio pra manter a própria Tail original do último bone -- "
        "digite/escolha o nome do bone ORIGINAL (ex.: 'Head'), não '_CTRL': o bone de controle "
        "correspondente é resolvido automaticamente"
    ),
    "rigger.prop.ik_chain_head_follow_enabled": (
        "Trava a rotação de Head_CTRL ao bone predecessor (Neck, ou Chest), alternável em tempo "
        "de pose"
    ),
    "rigger.prop.ik_chain_head_camera_enabled": (
        "Adiciona um botão 'Create Camera' abaixo que parenta um objeto Camera real do Blender ao "
        "bone escolhido -- útil pra pré-visualizar/animar uma visão em primeira pessoa"
    ),
    "rigger.prop.ik_chain_head_camera_parent_bone": (
        "A qual bone a câmera deve ser parentada (bone parenting -- segue a pose do bone "
        "automaticamente). Pode ser qualquer bone desta armature, não só um bone de Head/Neck -- "
        "digite/escolha o nome do bone ORIGINAL (ex.: 'Head'), não '_CTRL': o bone de controle "
        "correspondente é resolvido automaticamente"
    ),
    "rigger.prop.ik_chain_head_camera_offset_x": "Ajusta a câmera pra esquerda/direita, local à orientação de repouso do bone pai",
    "rigger.prop.ik_chain_head_camera_offset_y": "Ajusta a câmera pra frente/trás, local à orientação de repouso do bone pai",
    "rigger.prop.ik_chain_head_camera_offset_z": "Ajusta a câmera pra cima/baixo, local à orientação de repouso do bone pai",
    "rigger.prop.ik_chain_head_camera_rotation_x": "Rotação extra (graus, X local ao bone pai)",
    "rigger.prop.ik_chain_head_camera_rotation_y": (
        "Rotação extra (graus, Y local ao bone pai) -- padrão confirmado pra deixar a câmera de "
        "frente na orientação de repouso do bone pai"
    ),
    "rigger.prop.ik_chain_head_camera_rotation_z": "Rotação extra (graus, Z local ao bone pai)",
    "rigger.prop.ik_chain_head_camera_fov": (
        "Campo de visão horizontal da câmera gerada, em graus -- não é um valor confirmado do "
        "Hytale, só um ponto de partida razoável de jogo em primeira pessoa"
    ),
    "rigger.prop.ik_chain_attachments_count": "Quantos campos de bone de Attachment mostrar abaixo (0-{max})",
    "rigger.prop.ik_chain_texture_picker_bone": (
        "O bone cuja malha tem o atlas de textura (ex.: todas as expressões de boca numa imagem "
        "só) -- digite/escolha o nome do bone ORIGINAL (ex.: 'Head'), não '_CTRL': o bone de "
        "controle correspondente é resolvido automaticamente"
    ),
    "rigger.prop.ik_chain_texture_picker_ui_parent_bone": (
        "Só necessário se o picker deve se anexar em algum lugar diferente do Target Bone. Deixe "
        "vazio na maioria dos casos -- digite/escolha o nome do bone ORIGINAL (ex.: 'Head'), não "
        "'_CTRL': o bone de controle correspondente é resolvido automaticamente"
    ),
    "rigger.prop.ik_chain_texture_picker_plane_scale": (
        "Tamanho da imagem de referência mostrada na viewport pra seleção. Não afeta a animação "
        "exportada"
    ),
    "rigger.prop.ik_chain_texture_picker_plane_offset_x": "Ajusta a imagem de referência pra esquerda/direita, se não estiver alinhada certo",
    "rigger.prop.ik_chain_texture_picker_plane_offset_y": "Ajusta a imagem de referência pra cima/baixo, se não estiver alinhada certo",
    "rigger.prop.ik_chain_texture_picker_grid_cols": "Quantas células de atlas de textura na horizontal (esquerda pra direita)",
    "rigger.prop.ik_chain_texture_picker_grid_rows": "Quantas linhas de células de atlas de textura -- geralmente 1",
    "rigger.prop.ik_chain_texture_picker_grid_cell_width": "Distância em pixels de uma célula de atlas de textura até a próxima, como visto no Blockbench",
    "rigger.prop.ik_chain_texture_picker_grid_cell_height": "Distância em pixels entre linhas de células de atlas de textura. Não importa se Rows é 1",
    "rigger.prop.ik_chain_texture_picker_extra_bone_count": (
        "Quantos outros bones compartilham a textura deste alvo e devem se mover junto com ele "
        "(0-{max})"
    ),
    "rigger.prop.ik_chain_texture_picker_extra_bone": (
        "Outro bone cuja malha compartilha essa mesma textura de boca (ex.: uma metade esquerda/"
        "direita espelhada) e deve mudar de expressão junto com o Target Bone -- digite/escolha o "
        "nome do bone ORIGINAL (ex.: 'Head'), não '_CTRL': o bone de controle correspondente é "
        "resolvido automaticamente"
    ),
    "rigger.prop.ik_chain_collection_override": (
        "Em qual bone collection os bones desta cadeia vão (Main ou Face, conforme organizado em "
        "'Collection Settings'). 'Auto (default)' mantém o comportamento nativo -- Arm L/Arm R/Leg "
        "L/Leg R"
    ),

    # -----------------------------------------------------------------
    # rigger/__init__.py -- properties soltas em Armature (sem
    # PropertyGroup por trás -- reatribuídas via refresh hook, ver
    # _assign_dynamic_properties, v0.14)
    # -----------------------------------------------------------------
    "rigger.prop.armature_apply_ik_joint_fix": (
        "Corrige a posição X de juntas específicas da cadeia IK, usando os valores definidos pelo "
        "rig template ativo (ver 'ik_joint_x_overrides' em templates/rig/*.json) -- deixe "
        "desligado pra um template que ainda não definiu/calibrou esses valores"
    ),
    "rigger.prop.armature_active_rig_template": (
        "Nome do rig template (templates/rig/*.json) atualmente carregado nesta armature -- "
        "definido automaticamente por 'Load Hytale IK Chain Preset', usado pra resolver "
        "pole_angle_presets/ik_joint_x_overrides/widget_translation_x_overrides na hora da geração"
    ),
    "rigger.prop.armature_active_shape_template": (
        "Nome do shape template (templates/shapes/*.json) atualmente ativo pros custom shapes "
        "desta armature -- definido automaticamente junto com o rig template (ou manualmente via "
        "'Set Hytale Shape Template')"
    ),
    "rigger.prop.armature_active_collection_template": (
        "Nome do collection template (templates/collections/*.json) salvo ou aplicado mais "
        "recentemente nesta armature -- puramente informativo (diferente dos templates de rig/"
        "shape, este nunca é auto-aplicado por 'Create Rig')"
    ),
    "rigger.prop.armature_shape_edit_mode": (
        "Verdadeiro enquanto o mute de RIG_OT_hytale_shape_edit_mode_enter está em efeito nos "
        "drivers de escala de shape FK/IK desta armature -- definido/limpo automaticamente por "
        "'Enter'/'Finish Shape Edit Mode', lido por interface.py pra decidir qual dos dois botões "
        "mostrar e por 'Create Rig'/'Remove Generated Hytale Rig Bones' pra recusar rodar no meio "
        "de uma edição"
    ),
    "rigger.prop.armature_shape_vertex_edit_mode": (
        "Verdadeiro enquanto a malha de um custom shape (o widget usado pelo pose bone ativo) "
        "está aberta em Edit Mode via 'Edit Shape Vertices' -- definido/limpo automaticamente por "
        "esse operador e 'Finish Vertex Edit', lido por interface.py pra desenhar o painel certo "
        "(active_object é a MALHA do widget nesse estado, não a Armature) e por 'Create Rig'/"
        "'Remove Generated Hytale Rig Bones'/'Finish Shape Edit Mode' pra recusar rodar com uma "
        "sessão de edição de vértice pendurada"
    ),

    # -----------------------------------------------------------------
    # templates/__init__.py -- tooltips de botão (v0.14, 2ª varredura)
    # -----------------------------------------------------------------
    "templates.tooltip.reload": "Reescaneia as pastas de templates em busca de arquivos .json novos ou editados",
    "templates.tooltip.open_user_folder": "Abre sua pasta Documents/Hyblend/templates no explorador de arquivos",

    # -----------------------------------------------------------------
    # importer.py -- tooltips de botão faltantes (v0.14, 2ª varredura)
    # -----------------------------------------------------------------
    "importer.tooltip.blockymodel": "Importa um .blockymodel do Hytale como uma Armature (pose de repouso correta)",
    "importer.tooltip.bbmodel": "Importa um personagem/criatura do Hytale de um projeto Blockbench (.bbmodel)",

    # -----------------------------------------------------------------
    # exporter.py -- tooltips de botão faltantes (v0.14, 2ª varredura)
    # -----------------------------------------------------------------
    "exporter.tooltip.select_all_actions": "Marca ou desmarca todas as Actions da lista abaixo",
    "exporter.tooltip.blockyanim": (
        "Exporta em lote uma ou mais Actions da Armature selecionada/ativa pro formato "
        ".blockyanim do Hytale -- um arquivo por Action, numa pasta escolhida"
    ),

    # -----------------------------------------------------------------
    # anim_importer.py -- tooltip de botão faltante (v0.14, 2ª
    # varredura)
    # -----------------------------------------------------------------
    "anim_importer.tooltip.blockyanim": "Importa um arquivo .blockyanim pra armature ativa",

    # -----------------------------------------------------------------
    # interface.py -- TAB_ITEMS/RIG_SUBTAB_ITEMS, tooltips dos toggles
    # de aba/sub-aba (v0.14, 2ª varredura)
    # -----------------------------------------------------------------
    "panel.tab_import_tooltip": "Importar modelos e attachments",
    "panel.tab_export_tooltip": "Exportar animações",
    "panel.tab_rig_tooltip": "Cadeias IK e geração de rig",
    "panel.tab_animation_tooltip": "Visibilidade de bone collection e switches de FK/IK",
    "panel.tab_info_tooltip": "Créditos e links",
    # v0.14.1 -- rótulos ("label") das sub-abas: "Setup"/"Bone Settings"
    # ficam com o MESMO texto em inglês aqui de propósito (pedido
    # explícito do usuário -- só "Advanced" tem tradução de verdade
    # pro português). A OPÇÃO de traduzir os três existe (ver
    # interface.py, _rig_subtab_items) -- é só uma escolha de conteúdo
    # desta tradução específica, não uma limitação de código.
    "panel.rig_subtab_setup_label": "Setup",
    "panel.rig_subtab_setup_tooltip": "Criar/atualizar o rig e ações do dia a dia",
    "panel.rig_subtab_bone_settings_label": "Bone Settings",
    "panel.rig_subtab_bone_settings_tooltip": "Cadeias IK e configuração por bone",
    "panel.rig_subtab_advanced_label": "Avançado",
    "panel.rig_subtab_advanced_tooltip": "Bone collections e templates de personagem",

    # -----------------------------------------------------------------
    # rigger/rig.py -- RIG_MT_hytale_ik_chain_add_menu / RIG_MT_hytale_
    # clear_generated_menu, tooltips de Menu (v0.14, 2ª varredura)
    # -----------------------------------------------------------------
    "rigger.tooltip.ik_chain_add_menu": "Escolha qual tipo de entrada adicionar à lista",
    "rigger.tooltip.clear_generated_menu": "Apaga bones gerados -- escolha o quanto remover",

    # -----------------------------------------------------------------
    # common.py -- HYTALE_OT_pick_bone_into_field, tooltip de botão e
    # de campo (v0.14, 2ª varredura)
    # -----------------------------------------------------------------
    "common.tooltip.pick_bone_into_field": "Copia o nome do bone atualmente selecionado pra este campo",
    "common.prop.pick_bone_data_path": (
        "Caminho, relativo ao objeto ativo, até o datablock dono do campo (ex.: "
        "'data.hytale_export_settings')"
    ),
    "common.prop.pick_bone_field": "Nome da StringProperty a preencher",

    # -----------------------------------------------------------------
    # interface.py -- aba "Info" (créditos/links, ver _draw_info)
    # -----------------------------------------------------------------
    "panel.info_links_label": "Links",
    "panel.info_credits_label": "Créditos",
    "panel.info_credits_created_by_label": "Criado por:",
    "panel.info_credits_hytale_label": "Hypixel Studios",
    "panel.info_credits_hytale_disclaimer": (
        "Ferramenta feita por fã, não-oficial. Não afiliado nem endossado pela Hypixel Studios."
    ),
}
