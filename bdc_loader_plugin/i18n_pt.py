"""Brazilian Portuguese texts of the interface, keyed by the English text in the code."""

import re

_TOUR = {
    # Callout
    "Step {} of {}": "Etapa {} de {}",
    "Start": "Começar",
    "Next": "Próximo",
    "Finish": "Concluir",
    "Back": "Voltar",
    "Skip tutorial": "Pular tutorial",
    "Waiting for your action": "Aguardando sua ação",
    "Done": "Concluído",
    # Sections
    "Getting started": "Introdução",
    "Data discovery": "Busca de dados",
    "Visualization": "Visualização",
    "Area of interest": "Área de interesse",
    "Tiles": "Tiles",
    "Time series": "Séries temporais",
    # Steps
    "Welcome to BDC Loader": "Bem-vindo ao BDC Loader",
    "A case study: native cerrado in western Bahia, deforested in 2022 (PRODES Cerrado). "
    "You run each step; the highlight shows where.": "Estudo de caso: cerrado nativo no oeste da Bahia, desmatado em 2022 "
    "(PRODES Cerrado). Você executa cada etapa; o destaque mostra onde.",
    "Select the data cube": "Selecione o cubo de dados",
    "Click <b>Cubes</b>, open the list and select <b>Sentinel-2 Cube 16D (S2-16D-2)</b>: "
    "10 m, one composite every 16 days.": "Clique em <b>Cubos</b>, abra a lista e selecione "
    "<b>Sentinel-2 Cube 16D (S2-16D-2)</b>: 10 m, um composto a cada 16 dias.",
    "Load the BDC tile grid": "Carregue a grade de tiles do BDC",
    "Open <b>Extent</b>. The plugin offers the BDC tile grids: select <b>BDC_SM_V2</b>, the small tiles.": "Abra "
    "<b>Extensão</b>. O plugin oferece as grades de tiles do BDC: selecione <b>BDC_SM_V2</b>, a de tiles pequenos.",
    "The BDC tile grid BDC_SM_V2 is already on the map. Click <b>Next</b>.": "A grade de tiles BDC_SM_V2 já está "
    "no mapa. Clique em <b>Próximo</b>.",
    "Draw the area of interest": "Desenhe a área de interesse",
    "Drag a box over the amber outline. The plugin returns when you release the mouse.": "Arraste um retângulo "
    "sobre o contorno âmbar. O plugin volta quando você solta o mouse.",
    "Search images clipped to the box": "Busque imagens recortadas",
    "Select <b>Crop</b>, then click <b>Search STAC</b>. Period: August to September 2022, the dry season.": "Selecione "
    "<b>Recortar</b> e clique em <b>Buscar STAC</b>. Período: agosto a setembro de 2022, a estação seca.",
    "Load all dates": "Carregue todas as datas",
    "Click <b>All</b> to select every date, then <b>Load layers</b>.": "Clique em <b>Todos</b> para selecionar "
    "todas as datas e depois em <b>Carregar camadas</b>.",
    "Navigate the timeline": "Navegue na linha do tempo",
    "The timeline bar holds one layer per date. Click <b>Next ▶</b> up to the last date.": "A barra da linha do "
    "tempo tem uma camada por data. Clique em <b>Próx. ▶</b> até a última data.",
    "Choose a band composition": "Escolha uma composição de bandas",
    "Under <b>Bands</b>, open <b>Preset</b> and select <b>False Color (8,4,3)</b>: NIR, red and green.": "Em "
    "<b>Bandas</b>, abra <b>Predefinição</b> e selecione <b>False Color (8,4,3)</b>: NIR, vermelho e verde.",
    "Load the new composition": "Carregue a nova composição",
    "Search with the new bands": "Busque com as novas bandas",
    "The results follow the bands of the search, so <b>Search STAC</b> turned amber. "
    "Click it again: same box and period.": "Os resultados seguem as bandas da busca, por isso <b>Buscar STAC</b> "
    "ficou âmbar. Clique de novo: mesmo retângulo e mesmo período.",
    "False color composite": "Composição falsa cor",
    "Vegetation appears red: dark red for native cerrado, bright red along the streams. "
    "Bare dry season fields appear green and pale blue.": "A vegetação aparece em vermelho: escuro no cerrado "
    "nativo, vivo ao longo dos córregos. Os campos sem cobertura da seca aparecem verdes e azul-claros.",
    "Clip to a polygon": "Recorte por um polígono",
    "The plugin ships an example circle. Under <b>Vector File</b>, click <b>Layer</b> "
    "and select <b>Tutorial circle</b>.": "O plugin traz um círculo de exemplo. Em <b>Arquivo vetorial</b>, clique "
    "em <b>Camada</b> e selecione <b>Tutorial circle</b>.",
    "Search within the polygon": "Busque dentro do polígono",
    "Click <b>Search STAC</b>: same period, images clipped to the circle.": "Clique em <b>Buscar STAC</b>: mesmo "
    "período, imagens recortadas pelo círculo.",
    "Load the clipped image": "Carregue a imagem recortada",
    "Select <b>14 Sep 2022</b>, then click <b>Load layers</b>.": "Selecione <b>14/09/2022</b> e clique em "
    "<b>Carregar camadas</b>.",
    "Polygon mask applied": "Máscara do polígono aplicada",
    "Only pixels inside the circle were loaded. Any polygon layer works the same way.": "Só os pixels dentro do "
    "círculo foram carregados. Qualquer camada de polígonos funciona igual.",
    "BDC tile grid": "Grade de tiles do BDC",
    "Each square is a BDC tile, about 110 km wide. The amber tile, 031020, covers the clearings.": "Cada quadrado é "
    "um tile do BDC, com cerca de 110 km. O tile âmbar, 031020, cobre os desmatamentos.",
    "Select a tile on the map": "Selecione um tile no mapa",
    "Click <b>Select on Map</b>, then the amber tile.": "Clique em <b>Selecionar no mapa</b> e depois no tile âmbar.",
    "Click inside the amber tile, 031020. The plugin returns by itself.": "Clique dentro do tile âmbar, 031020. "
    "O plugin volta sozinho.",
    "Search the whole tile": "Busque o tile inteiro",
    "Same period, back to True Color, for the whole tile. Click <b>Search STAC</b>.": "Mesmo período, de volta a "
    "True Color, para o tile inteiro. Clique em <b>Buscar STAC</b>.",
    "Load the tile": "Carregue o tile",
    "True color composite": "Composição cor verdadeira",
    "Pale fields were cleared from the cerrado. The dark ground cut by streams is native cerrado.": "Os campos "
    "claros foram desmatados. O terreno escuro cortado por córregos é cerrado nativo.",
    "Satellite image time series": "Séries temporais de imagens de satélite",
    "Turn on <b>Time Series</b>: the panel extracts the time series of a pixel from the BDC data cubes.": "Ligue "
    "<b>Séries temporais</b>: o painel extrai a série temporal de um pixel dos cubos de dados do BDC.",
    "Extract an NDVI time series": "Extraia uma série temporal de NDVI",
    "NDVI, 2019 to 2023, is set. Turn on the pick button, then click inside the amber circle.": "NDVI de 2019 a "
    "2023 já está definido. Ligue o botão de seleção e clique dentro do círculo âmbar.",
    "NDVI trajectory": "Trajetória do NDVI",
    "A seasonal cycle of native cerrado until late 2021, then an abrupt drop that persists: the clearing.": "Ciclo "
    "sazonal do cerrado nativo até o fim de 2021, depois uma queda abrupta que persiste: o desmatamento.",
    "RGB time series": "Série temporal em RGB",
    "Click <b>RGB</b>: each observation is drawn in the pixel's true color.": "Clique em <b>RGB</b>: cada "
    "observação é desenhada na cor verdadeira do pixel.",
    "Land cover change": "Mudança de cobertura da terra",
    "Olive-brown dots are cerrado vegetation. From late 2021 they turn pink and tan: bare soil. "
    "Pale dots are clouds.": "Pontos marrom-oliva são a vegetação do cerrado. Do fim de 2021 em diante ficam "
    "rosados e bege: solo exposto. Pontos claros são nuvens.",
    "Image of a date": "Imagem de uma data",
    "Double-click a dot: the map loads the image of that date. Try a pink dot of 2022.": "Clique duas vezes "
    "em um ponto: o mapa carrega a imagem daquela data. Tente um ponto rosado de 2022.",
    "Several points": "Vários pontos",
    "Click <b>Multi</b>, turn on the pick button, then click the three amber circles.": "Clique em <b>Multi</b>, "
    "ligue o botão de seleção e clique nos três círculos âmbar.",
    "Batch extraction": "Extração em lote",
    "Click <b>Extract</b> to read the three time series.": "Clique em <b>Extrair</b> para ler as três séries "
    "temporais.",
    "Compare trajectories": "Compare as trajetórias",
    "Use <b>&lt;</b> and <b>&gt;</b>: clearing of 2022, clearing of 2023 and native cerrado.": "Use <b>&lt;</b> e "
    "<b>&gt;</b>: desmatamento de 2022, desmatamento de 2023 e cerrado nativo.",
    "Tutorial complete": "Tutorial concluído",
    "Open it again from Settings, under <b>Show tutorial</b>.": "Abra de novo em Configurações, em "
    "<b>Mostrar tutorial</b>.",
}

_TOUR_PATTERNS = [
    (
        r"Click <b>(.+)</b>, then drag a box over the amber outline on the map\.",
        r"Clique em <b>\1</b> e arraste um retângulo sobre o contorno âmbar no mapa.",
    ),
    (
        r"That is (.+)\. Choose Sentinel-2 Cube 16D \(S2-16D-2\)\.",
        r"Essa é \1. Escolha Sentinel-2 Cube 16D (S2-16D-2).",
    ),
    (r"That is (.+)\. Choose False Color \(8,4,3\)\.", r"Essa é \1. Escolha False Color (8,4,3)."),
    (
        r"That is tile (\w+)\. Click ✕ to clear it, then select the amber one\.",
        r"Esse é o tile \1. Clique em ✕ para limpar e selecione o tile âmbar.",
    ),
    (
        r"Leave only tile (\w+): click ✕ to clear the list, then select it again\.",
        r"Deixe só o tile \1: clique em ✕ para limpar a lista e selecione-o de novo.",
    ),
    (
        r"(\d+) of (\d+) dates loaded\. Click All, then Load layers\.",
        r"\1 de \2 datas carregadas. Clique em Todos e depois em Carregar camadas.",
    ),
    (
        r"(P\d+) is outside the circles\. Click Clear, then click the three circles again\.",
        r"\1 está fora dos círculos. Clique em Limpar e clique de novo nos três círculos.",
    ),
]

_TOUR.update(
    {
        "That box misses the amber outline. Click Draw on Canvas again.": "O retângulo não cobre o contorno âmbar. "
        "Clique em desenhar de novo.",
        "That box is much larger than the outline. Click Draw on Canvas and draw a smaller one.": "O retângulo é "
        "muito maior que o contorno. Desenhe um menor.",
        "These are whole tiles. Pick Crop, then click Search STAC again.": "Estes são tiles inteiros. Escolha "
        "Recortar e clique em Buscar STAC de novo.",
        "No image of 14 Sep 2022 in the list: check the area and the dates.": "Não há imagem de 14/09/2022 na lista: "
        "confira a área e as datas.",
        "Tick only the 14 Sep 2022 card.": "Marque só o card de 14/09/2022.",
        "That point is outside the amber circle. Click inside it.": "Esse ponto está fora do círculo âmbar. "
        "Clique dentro dele.",
    }
)


_UI = {
    # Header
    "About": "Sobre",
    "Time Series": "Séries temporais",
    "Timeline Panel": "Linha do tempo",
    "About this plugin": "Sobre este plugin",
    "Explore INPE data, BDC data cubes, services, and technical references": "Dados do INPE, cubos de dados do BDC, "
    "serviços e referências técnicas",
    "Guided tour of the plugin, step by step": "Tour guiado do plugin, passo a passo",
    "Click to set the project CRS to SIRGAS 2000 / Brazil Albers\n"
    "(EPSG:10857 when available; compatible fallback on older QGIS versions)": "Define o SRC do projeto como "
    "SIRGAS 2000 / Brazil Albers\n(EPSG:10857 quando disponível; alternativa compatível em QGIS antigos)",
    "Open/Close BDC Time Series panel": "Abrir/fechar o painel de séries temporais",
    "Open/Close Timeline Toolbar": "Abrir/fechar a barra da linha do tempo",
    "Activity log — click to open/close": "Registro de atividades: clique para abrir/fechar",
    "Plugin settings (folders, performance, storage, tutorial)": "Configurações (pastas, desempenho, armazenamento, "
    "tutorial)",
    "Click to open BDC STAC catalog in browser": "Abrir o catálogo STAC do BDC no navegador",
    "Offline: local data": "Offline: dados locais",
    "<span style='color: #e74c3c; font-size: 9px;'>Offline: local data</span>": "<span style='color: #e74c3c; "
    "font-size: 9px;'>Offline: dados locais</span>",
    "\u26a1 Performance: click to configure": "\u26a1 Desempenho: clique para configurar",
    "Collection has no tile system": "A coleção não tem sistema de tiles",
    "<span style='color:#e67e22;'>Loading needs 1 or 3 bands (Download takes any number)</span>": "<span "
    "style='color:#e67e22;'>Carregar pede 1 ou 3 bandas (o download aceita qualquer número)</span>",
    # Collection and period
    "Collection": "Coleção",
    "Type:": "Tipo:",
    "All": "Todos",
    "Cubes": "Cubos",
    "Collections": "Coleções",
    "Mosaics": "Mosaicos",
    "Toggle individual collections": "Escolher coleções",
    "Period": "Período",
    "From:": "De:",
    "To:": "Até:",
    "Click the track to move the nearest handle, or drag a handle": "Clique na barra para mover a alça mais "
    "próxima, ou arraste uma alça",
    # Area filters
    "Extent": "Extensão",
    "North": "Norte",
    "South": "Sul",
    "East": "Leste",
    "West": "Oeste",
    "Calculate from": "Calcular de",
    "Layer": "Camada",
    "Layout Map": "Mapa do layout",
    "Bookmark": "Marcador",
    "Map Canvas Extent": "Extensão do mapa",
    "Draw on Canvas": "Desenhar no mapa",
    "Current Layer Extent": "Extensão da camada atual",
    "Set to current map canvas extent": "Usar a extensão atual do mapa",
    "Mode:": "Modo:",
    "Search Tiles": "Buscar tiles",
    "Crop": "Recortar",
    "Bounding box in EPSG:4326 (xmin,ymin,xmax,ymax).\nDrawn automatically or type manually and press Enter.": ""
    "Retângulo em EPSG:4326 (xmin,ymin,xmax,ymax).\nPreenchido ao desenhar, ou digite e tecle Enter.",
    "Copy bbox to clipboard": "Copiar o retângulo",
    "Zoom to bbox": "Zoom no retângulo",
    "Clear extent": "Limpar extensão",
    "Search intersecting tiles, merge by date, and\nclip the layers to the exact drawn extent.": "Busca os tiles "
    "que cruzam a área, junta por data\ne recorta as camadas na extensão desenhada.",
    "Search tiles that intersect the drawn extent.\nNo clipping — loads entire tiles.": "Busca os tiles que "
    "cruzam a extensão desenhada.\nSem recorte: carrega os tiles inteiros.",
    "Grid not loaded": "Grade não carregada",
    "-- Select --": "-- Selecione --",
    "No tile grid available": "Sem grade de tiles",
    "Load Grid": "Carregar grade",
    "Select on Map": "Selecionar no mapa",
    "Finish Selection": "Concluir seleção",
    "Load BDC tile grid on the map": "Carregar a grade de tiles do BDC no mapa",
    "Click tiles on the map to select": "Clique nos tiles no mapa para selecioná-los",
    "Finish tile selection on the map": "Concluir a seleção de tiles no mapa",
    "Copy tiles to clipboard": "Copiar os tiles",
    "Clear all tiles": "Limpar todos os tiles",
    "Vector File": "Arquivo vetorial",
    "Shapefile (.shp), GeoPackage (.gpkg) or a polygon layer of the project": "Shapefile (.shp), GeoPackage (.gpkg) "
    "ou camada de polígonos do projeto",
    "Browse to select a vector file...": "Procure um arquivo vetorial...",
    "Browse": "Procurar",
    "Use a polygon layer already in the project, such as a tile grid. "
    "Features selected on the map are the ones listed.": "Usa uma camada de polígonos do projeto, como uma grade de "
    "tiles. Só as feições selecionadas no mapa entram na lista.",
    "Clear shapefile": "Limpar arquivo vetorial",
    "Layer:": "Camada:",
    "Label field:": "Campo de rótulo:",
    "Merge all (use outer boundary)": "Unir todas (contorno externo)",
    "Merge all features into a single boundary (e.g. entire biome instead of individual ecoregions)": "Une todas as "
    "feições em um só contorno (por exemplo, o bioma inteiro em vez das ecorregiões)",
    "Select All": "Marcar todas",
    "Deselect All": "Desmarcar todas",
    # Bands and output
    "Bands": "Bandas",
    "Preset:": "Predefinição:",
    "New composition: choose its bands and name": "Nova composição: escolha as bandas e o nome",
    "Delete the selected composition (only compositions you saved)": "Excluir a composição selecionada (só as que "
    "você salvou)",
    "Add selected band": "Adicionar a banda selecionada",
    "Remove selected band": "Remover a banda selecionada",
    "Output": "Saída",
    "Limit:": "Limite:",
    "Show on map when loaded": "Mostrar no mapa ao carregar",
    "Checked: the first date of each series is drawn right away; the timeline steps through the others.\n"
    "Unchecked: the layers are added to the Layers panel turned off.": "Marcado: a primeira data de cada série é desenhada ao carregar; "
    "a linha do tempo percorre as outras.\nDesmarcado: as camadas entram no painel de camadas desligadas.",
    "Choose folder to save VRTs": "Escolher a pasta dos VRTs",
    # Actions
    "Import Query": "Importar consulta",
    "Export Code": "Exportar código",
    "Search STAC": "Buscar STAC",
    "Load layers": "Carregar camadas",
    "Download selected": "Baixar selecionados",
    "Clear": "Limpar",
    "Cancel": "Cancelar",
    "✕ Cancel": "✕ Cancelar",
    "Import query parameters from JSON or YAML file": "Importar os parâmetros de um arquivo JSON ou YAML",
    "Export query parameters to JSON, YAML, R, Python, or cURL": "Exportar os parâmetros para JSON, YAML, R, "
    "Python ou cURL",
    "Search items in the BDC STAC catalog": "Buscar itens no catálogo STAC do BDC",
    "Add the selected results to QGIS as layers. Images you have downloaded are read from your disk; "
    "the others are streamed from the BDC without downloading them.": "Adiciona os resultados selecionados ao QGIS "
    "como camadas. As imagens baixadas são lidas do disco; as outras são lidas do BDC pela rede, sem download.",
    "Download every selected result with the same format and projection": "Baixar todos os resultados selecionados "
    "no mesmo formato e projeção",
    "Clear all search results": "Limpar todos os resultados",
    # Results
    "<b>Results</b>": "<b>Resultados</b>",
    "View:": "Exibir:",
    "Detailed": "Detalhada",
    "Compact": "Compacta",
    "None": "Nenhum",
    "Downloaded:": "Baixados:",
    "Show cards with thumbnails": "Cards com miniaturas",
    "Show compact list without thumbnails": "Lista compacta sem miniaturas",
    "Select all results": "Marcar todos os resultados",
    "Deselect all results": "Desmarcar todos os resultados",
    "Show only items with locally downloaded images": "Mostrar só itens com imagens baixadas",
    "<b>Period Filter:</b>": "<b>Filtro de período:</b>",
    "<b>Max cloud:</b>": "<b>Nuvem máx.:</b>",
    "Reset": "Restaurar",
    "Reset filters to search values": "Voltar os filtros aos valores da busca",
    "Set parameters and click Search.": "Defina os parâmetros e clique em Buscar.",
    "<b>Extent Crop</b>": "<b>Recorte da extensão</b>",
    "Download image to local disk": "Baixar a imagem para o disco",
    # Timeline
    "◀ Prev": "◀ Ant.",
    "Next ▶": "Próx. ▶",
    "BDC Timeline": "Linha do tempo BDC",
    "Select a VRT": "Selecione um VRT",
    "Filter by tile / collection": "Filtrar por tile / coleção",
    "Zoom to tile extent": "Zoom na extensão do tile",
    "Previous date (Alt+Left)": "Data anterior (Alt+Esquerda)",
    "Next date (Alt+Right)": "Próxima data (Alt+Direita)",
    "Timeline ON — click to disable": "Linha do tempo ligada: clique para desligar",
    "Timeline OFF — click to enable": "Linha do tempo desligada: clique para ligar",
    "Keyboard shortcuts": "Atalhos de teclado",
    "Close timeline": "Fechar a linha do tempo",
    # Time series panel
    "BDC Satellite Image Time Series": "Séries temporais de imagens BDC",
    "Filter...": "Filtrar...",
    "Filter visible collections": "Filtrar as coleções visíveis",
    "Select BDC collection": "Selecionar a coleção do BDC",
    "Drag to resize bands area": "Arraste para redimensionar a área de bandas",
    "Points": "Pontos",
    "Single": "Único",
    "Pick multiple points, then Extract": "Marque vários pontos e clique em Extrair",
    "Click map → auto-extract for 1 point": "Clique no mapa → extração de 1 ponto",
    "Click map to select pixel (ESC to cancel)": "Clique no mapa para escolher o pixel (ESC cancela)",
    "Add point": "Adicionar ponto",
    "Copy coordinates": "Copiar coordenadas",
    "How to add points": "Como adicionar pontos",
    "Map point settings": "Pontos no mapa",
    "Load points from SHP or GPKG file": "Carregar pontos de um arquivo SHP ou GPKG",
    " Extract": " Extrair",
    "History": "Histórico",
    "Clear History": "Limpar histórico",
    "Chart": "Gráfico",
    "Click to open WTSS in browser": "Abrir o WTSS no navegador",
    # Chart
    "BDC Time Series — Chart": "Séries temporais BDC: gráfico",
    "BDC Chart": "Gráfico BDC",
    "Line": "Linha",
    "Bands:": "Bandas:",
    "Dynamic range": "Faixa dinâmica",
    "Extracting time series...": "Extraindo a série temporal...",
    "Extracting RGB bands...": "Extraindo as bandas RGB...",
    "Export complete time series as GeoPackage": "Exportar a série temporal completa como GeoPackage",
    "Automatic colors: each band stretched between the percentiles below,\ncomputed on the dates without clouds. "
    "Editing Min/Max fixes one range\nfor the three bands, in the chart's units.": "Cores automáticas: cada banda "
    "esticada entre os percentis abaixo,\ncalculados nas datas sem nuvem. Editar Min/Max fixa uma faixa\npara as "
    "três bandas, nas unidades do gráfico.",
    "Automatically center map rendering point when navigating charts": "Centralizar o mapa no ponto ao navegar "
    "entre os gráficos",
    "Brightness of the dots: below 1 brightens, above 1 darkens.\nAuto brightens series whose clear dates are dark "
    "(dense vegetation).": "Brilho dos pontos: abaixo de 1 clareia, acima de 1 escurece.\nAuto clareia séries cujas "
    "datas sem nuvem são escuras (vegetação densa).",
    "Click the track to move the nearest handle. Double-click to reset.": "Clique na barra para mover a alça mais "
    "próxima. Duplo clique restaura.",
    "Keep the current X and Y ranges when changing time series": "Manter as faixas X e Y ao trocar de série",
    "Reference band for Y axis rendering in RGB layout": "Banda de referência do eixo Y no modo RGB",
    "Select the band holding logical values for the Y axis rendering": "Banda com os valores do eixo Y",
    "Minimize": "Minimizar",
    "Float": "Destacar",
    "Close": "Fechar",
    # Grid offer
    "Load BDC Grid Reference": "Grade de referência do BDC",
    "Add a BDC tile grid": "Adicionar uma grade de tiles do BDC",
    "The grid shows where each BDC\ntile is and gives Draw on Canvas\na map to draw over.\n\n"
    "Choose a grid to load directly\nfrom GeoServer (WFS).": "A grade mostra onde fica cada\ntile do BDC e serve de "
    "base\npara desenhar no mapa.\n\nEscolha uma grade para carregar\ndireto do GeoServer (WFS).",
    "  110 × 110 km  — small tiles": "  110 × 110 km  — tiles pequenos",
    "  220 × 220 km  — medium tiles": "  220 × 220 km  — tiles médios",
    "  663 × 663 km  — large tiles": "  663 × 663 km  — tiles grandes",
    "110 × 110 km  — small tiles": "110 × 110 km  — tiles pequenos",
    "220 × 220 km  — medium tiles": "220 × 220 km  — tiles médios",
    "663 × 663 km  — large tiles": "663 × 663 km  — tiles grandes",
    '<a href="https://brazil-data-cube.github.io/specifications/bdc-grid.html">BDC Grid Specification ↗</a>': ""
    '<a href="https://brazil-data-cube.github.io/specifications/bdc-grid.html">Especificação da grade BDC ↗</a>',
    # Settings
    "Settings - BDC Loader": "Configurações - BDC Loader",
    "<b style='font-size: 14px;'>Settings</b>": "<b style='font-size: 14px;'>Configurações</b>",
    "Folders": "Pastas",
    "Performance": "Desempenho",
    "Storage": "Armazenamento",
    "Downloaded Images": "Imagens baixadas",
    "VRT Output Folder": "Pasta dos VRTs",
    "Image Download Folder": "Pasta de download",
    "Folder where VRTs will be saved": "Pasta onde os VRTs são salvos",
    "Folder where images will be downloaded": "Pasta onde as imagens são baixadas",
    "Layer Naming": "Nome das camadas",
    "Generate overviews (.ovr) automatically": "Gerar overviews (.ovr) automaticamente",
    "Show tutorial": "Mostrar tutorial",
    "Close Settings without saving and start the tutorial": "Fechar as Configurações sem salvar e abrir o tutorial",
    "Warn before loading collections that are not cloud-optimized": "Avisar antes de carregar coleções que não são COG",
    "<span style='color: #57606a; font-size: 10px;'>The VRT folder stores .vrt and .ovr files generated by the "
    "plugin.<br>The download folder stores COG images downloaded via the download button.</span>": "<span "
    "style='color: #57606a; font-size: 10px;'>A pasta de VRTs guarda os arquivos .vrt e .ovr gerados pelo plugin."
    "<br>A pasta de download guarda as imagens COG baixadas pelo botão de download.</span>",
    "<span style='color: #57606a; font-size: 10px;'>Overviews are reduced-resolution copies of remote VRTs that QGIS "
    "uses for fast rendering at zoom-out levels. Without them, QGIS must fetch full-resolution data from all remote "
    "tiles every time you pan or zoom, which can be very slow. Disabling this saves disk space but may degrade "
    "rendering performance for remote layers.</span>": "<span style='color: #57606a; font-size: 10px;'>Overviews são "
    "cópias de resolução reduzida dos VRTs remotos que o QGIS usa para desenhar rápido com zoom afastado. Sem elas, o "
    "QGIS lê os dados em resolução cheia de todos os tiles a cada movimento do mapa, o que pode ser lento. Desligar "
    "economiza disco, mas pode deixar as camadas remotas lentas.</span>",
    "<span style='color: #57606a; font-size: 10px;'>Collections served as plain GeoTIFF have no internal overviews, "
    "so QGIS streams whole scenes to draw them and no overview or contrast stretch is generated. The warning offers "
    "to cancel and download instead. Dismissing it with 'Don't show this warning again' clears this box.</span>": ""
    "<span style='color: #57606a; font-size: 10px;'>Coleções em GeoTIFF simples não têm overviews internas: o QGIS "
    "lê cenas inteiras para desenhá-las, sem overview nem realce de contraste. O aviso oferece cancelar e baixar. "
    "Dispensá-lo com 'Não mostrar de novo' desmarca esta opção.</span>",
    "Performance Profile": "Perfil de desempenho",
    "Profile:": "Perfil:",
    "Detailed Settings": "Ajustes detalhados",
    "Max Threads:": "Máx. de threads:",
    "GDAL Cache (MB):": "Cache do GDAL (MB):",
    "HTTP Timeout (s):": "Tempo limite HTTP (s):",
    "WTSS Workers:": "Processos WTSS:",
    "Download Connections:": "Conexões de download:",
    "Increase on slow connections": "Aumente em conexões lentas",
    "Lowered automatically if the server refuses": "Reduzido sozinho se o servidor recusar",
    "Time series from COGs: all bands and dates": "Séries temporais dos COGs: todas as bandas e datas",
    "Parallel WTSS extractions": "Extrações WTSS em paralelo",
    "Cache of the data read for a time series taken from the COGs": "Cache dos dados lidos para uma série temporal dos COGs",
    "Connection timeout when reading a time series from the COGs": "Tempo limite de conexão ao ler uma série temporal dos COGs",
    "Files read at once for a time series taken from the COGs": "Arquivos lidos ao mesmo tempo para uma série temporal dos COGs",
    "Parallel WTSS point queries": "Consultas WTSS em paralelo",
    "Simultaneous connections to the BDC server when downloading (default 24). More is faster on a fast network; if "
    "the server answers 'too many requests', the plugin lowers the number by itself for the rest of the session.": ""
    "Conexões simultâneas ao servidor do BDC no download (padrão 24). Mais é mais rápido em rede boa; se o servidor "
    "responder 'too many requests', o plugin reduz o número sozinho até o fim da sessão.",
    "VSI curl cache size": "Tamanho do cache VSI curl",
    "Restore Defaults": "Restaurar padrões",
    "Save": "Salvar",
    "<span style='color: #57606a; font-size: 10px;'>Disk usage by file type. Adjust warning thresholds (MB) and clean "
    "as needed.</span>": "<span style='color: #57606a; font-size: 10px;'>Uso de disco por tipo de arquivo. Ajuste os "
    "limites de aviso (MB) e limpe quando precisar.</span>",
    "<b style='font-size: 9px; color: #57606a;'>Type</b>": "<b style='font-size: 9px; color: #57606a;'>Tipo</b>",
    "<b style='font-size: 9px; color: #57606a;'>Used</b>": "<b style='font-size: 9px; color: #57606a;'>Usado</b>",
    "<b style='font-size: 9px; color: #57606a;'>Warn (MB)</b>": "<b style='font-size: 9px; color: #57606a;'>Aviso "
    "(MB)</b>",
    "VRT Files": "Arquivos VRT",
    "Temp Files": "Temporários",
    "Clean": "Limpar",
    "Selective Cleanup": "Limpeza seletiva",
    "Filter:": "Filtro:",
    "Regex pattern (e.g. CBERS.* or \\.ovr$)": "Expressão regular (ex.: CBERS.* ou \\.ovr$)",
    "Search": "Buscar",
    "Delete Selected": "Excluir selecionados",
    "Delete All Filtered": "Excluir os filtrados",
    "<b>Locally downloaded images:</b>": "<b>Imagens baixadas neste computador:</b>",
    "Refresh": "Atualizar",
    "Open": "Abrir",
    "No images downloaded yet.": "Nenhuma imagem baixada ainda.",
    "Format:": "Formato:",
    # Other windows
    "About BDC Loader": "Sobre o BDC Loader",
    "BDC Documentation": "Documentação do BDC",
    "Explore BDC & INPE Data": "Dados do BDC e do INPE",
    "Start with the official data portals, then use the optional technical references": "Comece pelos portais "
    "oficiais de dados; depois use as referências técnicas",
    "Activity Log — BDC Loader": "Registro de atividades — BDC Loader",
    "Last entries — newest at bottom": "Últimas entradas, as mais novas embaixo",
    "Copy": "Copiar",
    "Copy selected lines, or all lines if none are selected": "Copiar as linhas selecionadas, ou todas se nenhuma "
    "estiver selecionada",
    # Status and message boxes
    "Extent captured from map.": "Extensão capturada do mapa.",
    "Settings saved.": "Configurações salvas.",
    "Preparing layer %v/%m": "Preparando camada %v/%m",
    "Preparing for display %v/%m": "Preparando para exibição %v/%m",
    "Adding layer %v/%m": "Adicionando camada %v/%m",
    "Validation": "Validação",
    "Error": "Erro",
    "Info": "Informação",
    "Exported": "Exportado",
    "Confirm Deletion": "Confirmar exclusão",
    "Confirm Cleanup": "Confirmar limpeza",
    "Grid Loaded": "Grade carregada",
    "Grid Load Failed": "Falha ao carregar a grade",
    "Load the grid first!": "Carregue a grade primeiro!",
    "Invalid coordinates.": "Coordenadas inválidas.",
    "Coordinates out of range.": "Coordenadas fora do intervalo.",
    "Add at least one point.": "Adicione pelo menos um ponto.",
    "Enter a WKT POINT geometry.": "Informe uma geometria WKT POINT.",
    "Large extent for Crop": "Extensão grande para recorte",
    "Missing dependency": "Dependência ausente",
    "Install matplotlib": "Instalar matplotlib",
    "No data to export.": "Sem dados para exportar.",
    "Download Required": "Download necessário",
    "Delete composition": "Excluir composição",
    "New composition": "Nova composição",
    "BDC Projection": "Projeção BDC",
}

_AREAS = {"Extent": "Extensão", "Tiles": "Tiles", "Vector File": "Arquivo vetorial"}


def _area_names(text):
    for english, portuguese in _AREAS.items():
        text = text.replace(english, portuguese)
    return text.replace(" or ", " ou ").replace(" and ", " e ")


def _hint_tail(tail):
    """The sentences that follow the area hint: no tile grid, and filters closed but kept."""
    tail = tail.replace(" This collection has no tile grid.", " Esta coleção não tem grade de tiles.")
    tail = tail.replace(" is closed but kept: open to use again.", " está fechada e guardada: abra para usar de novo.")
    tail = tail.replace(" are closed but kept: open to use again.", " estão fechadas e guardadas: abra para usar.")
    return _area_names(tail)


def _choose_hint(match):
    return f"Escolha uma área: {_area_names(match.group(1))}." + _hint_tail(match.group(2))


def _using_hint(match):
    used, others = _area_names(match.group(1)), _area_names(match.group(2))
    return f"Usando {used}. Para usar {others}, feche ou limpe (\u2715) antes." + _hint_tail(match.group(3))


_LOAD_WORDS = (
    (" cropped layers", " camadas recortadas"),
    (" cropped layer", " camada recortada"),
    (" layers", " camadas"),
    (" layer", " camada"),
    ("Single band", "Banda única"),
    (" from your downloads", " dos seus downloads"),
    (" streamed from BDC", " lidas do BDC"),
)


def _load_note(match):
    text = match.group(0)
    for english, portuguese in _LOAD_WORDS:
        text = text.replace(english, portuguese)
    return text


_COLLECTION_WORDS = {
    "Cube": "Cubo",
    "Scenes": "Cenas",
    "Mosaic": "Mosaico",
    "Individual scenes": "cenas individuais",
    " days": " dias",
    " months": " meses",
    " month": " mês",
}


def _collection_info(match):
    text = match.group(0)
    for english, portuguese in (
        ("Type: ", "Tipo: "),
        ("Resolution: ", "Resolução: "),
        ("Compositing: ", "Composição: "),
        ("Platform: ", "Plataforma: "),
        ("No tiles (use Extent only)", "Sem tiles (use só Extensão)"),
        ("GeoTIFF (not cloud-optimized) \u2014 prefer Download", "GeoTIFF (não otimizado) \u2014 prefira baixar"),
        *_COLLECTION_WORDS.items(),
    ):
        text = text.replace(english, portuguese)
    return text


_BAND_NAMES = {
    "coastal": "costeiro",
    "blue": "azul",
    "green": "verde",
    "red": "vermelho",
    "yellow": "amarelo",
    "pan": "pancromática",
}


def _band_label(match):
    name = match.group(2)
    return f"{match.group(1)} ({_BAND_NAMES.get(name, name)})"


_STORAGE_TYPES = {
    "VRT Files": "arquivos VRT",
    "Temp Files": "temporários",
    "Downloads": "downloads",
    "Overviews": "overviews",
}


def _threshold(match):
    return f"Limite de aviso: {_STORAGE_TYPES.get(match.group(1), match.group(1))}"


_UI_PATTERNS = [
    (r"(\S+) \((coastal|blue|green|red|yellow|pan)\)", _band_label),
    (r"Period: (\d+) days \((.+)\)", r"Período: \1 dias (\2)"),
    (
        r"Folder (.+) is not available; files go to (.+) in this session\. Change it in Settings\.",
        r"A pasta \1 não está disponível; os arquivos vão para \2 nesta sessão. Altere em Configurações.",
    ),
    (r"Period: (\d\d/\d\d - .+)", r"Período: \1"),
    (r"Date: (.+)", r"Data: \1"),
    (r"Mean cloud: (.+)", r"Nuvem média: \1"),
    (r"Cloud: (.+)", r"Nuvem: \1"),
    (r"Intersection: (\d+) scenes? / (\d+) tiles?", r"Interseção: \1 cena(s) / \2 tile(s)"),
    (r"Open in STAC Browser\n(.+)", r"Abrir no STAC Browser\n\1"),
    (r"Collection: (.+)\nID: (.+)", r"Coleção: \1\nID: \2"),
    (r"Type: .+ \| Resolution: .+", _collection_info),
    (r"Choose one area: (.+?)\.((?: .*)?)", _choose_hint),
    (r"Using (.+?)\. To use (.+?), close it or clear it \(\u2715\) first\.((?: .*)?)", _using_hint),
    (r"<b>\d+</b> (?:cropped )?layers? &middot; .+", _load_note),
    (r"(\d+) features selected on the map", r"\1 feições selecionadas no mapa"),
    (
        r"(\d+) features: check the ones to use, or select them on the map",
        r"\1 feições: marque as que vai usar ou selecione no mapa",
    ),
    (r"(\d+) features: check the ones to use", r"\1 feições: marque as que vai usar"),
    (r"(\d+) features \(merged as single boundary\)", r"\1 feições (unidas em um contorno)"),
    (r"(\d+) of (\d+) features selected", r"\1 de \2 feições selecionadas"),
    (r"Grid (\S+) available locally", r"Grade \1 disponível no computador"),
    (r"Previous date \((.+)\)", r"Data anterior (\1)"),
    (r"Next date \((.+)\)", r"Próxima data (\1)"),
    (
        r"\u26a1 (.+) cores, (.+) GB RAM \u2192 <b>(\w+)</b> \((.+) threads\) \u00b7 "
        r"<span style='text-decoration: underline;'>Change in Settings \u2699</span>",
        r"\u26a1 \1 núcleos, \2 GB RAM \u2192 <b>\3</b> (\4 threads) \u00b7 "
        r"<span style='text-decoration: underline;'>Alterar em Configurações \u2699</span>",
    ),
    (
        r"(<span[^>]*>\u26a0 \d+ threads\. )High values may freeze QGIS on weaker machines\.(</span>)",
        r"\1Valores altos podem travar o QGIS em máquinas fracas.\2",
    ),
    (
        r"(<span[^>]*>\u26a1 \d+ threads\. )Moderate \u2014 should work on most machines\.(</span>)",
        r"\1Moderado: deve funcionar na maioria das máquinas.\2",
    ),
    (
        r"(<span[^>]*>\u2713 \d+ threads\. )Safe for most machines\.(</span>)",
        r"\1Seguro para a maioria das máquinas.\2",
    ),
    (
        r"(<span[^>]*>)Detected: (.+) CPU cores, (.+) RAM \u2192 profile <b>(\w+)</b>(</span>)",
        r"\1Detectado: \2 núcleos, \3 RAM \u2192 perfil <b>\4</b>\5",
    ),
    (r"Grid (\S+) loaded", r"Grade \1 carregada"),
    (r"Grid (\S+) — click Load Grid \(WFS\)", r"Grade \1: clique em Carregar grade (WFS)"),
    (r"\((\d+) features\)", r"(\1 feições)"),
    (r"(\d+) features loaded", r"\1 feições carregadas"),
    (r"STAC BDC online\. (\d+) collections loaded dynamically\.", r"STAC do BDC online. \1 coleções carregadas."),
    (r"(<span[^>]*>)STAC: Online \((\d+) collections\)(</span>)", r"\1STAC: online (\2 coleções)\3"),
    (r"STAC: Online \((\d+) collections\)", r"STAC: online (\1 coleções)"),
    (r"(<span[^>]*>)STAC: Online \((\d+)ms\)(</span>)", r"\1STAC: online (\2 ms)\3"),
    (r"STAC: Online \((\d+)ms\)", r"STAC: online (\1 ms)"),
    (r"(<span[^>]*>)STAC: Slow \((\d+)ms\)(</span>)", r"\1STAC: lento (\2 ms)\3"),
    (r"STAC: Slow \((\d+)ms\)", r"STAC: lento (\1 ms)"),
    (r"(\d+) dates: (.+) → (.+)  \[(.+)\]", r"\1 datas: \2 → \3  [\4]"),
    (r"1 date: (.+)", r"1 data: \1"),
    (r"Remove #(\d+)", r"Remover #\1"),
    (r"WTSS online — (\d+) ms", r"WTSS online: \1 ms"),
    (r"Warning threshold for (.+)", _threshold),
    (r"(.+)  \((\d+) files\)", r"\1  (\2 arquivos)"),
    (r"QGIS plugin for temporal series workflows • Version (.+)", r"Plugin QGIS para séries temporais • Versão \1"),
]

_DIALOGS = {
    # Download options
    "Download": "Download",
    "Files": "Arquivos",
    "One multiband GeoTIFF": "Um GeoTIFF multibanda",
    "One GeoTIFF per band": "Um GeoTIFF por banda",
    "One GeoTIFF per band + VRT": "Um GeoTIFF por banda + VRT",
    "A single file with every band, for viewing or sharing.": "Um só arquivo com todas as bandas, para ver ou "
    "compartilhar.",
    "Separate files, as analysis packages such as sits expect.": "Arquivos separados, como pacotes de análise "
    "como o sits esperam.",
    "Separate files plus a small VRT that opens them as one layer in QGIS.": "Arquivos separados e um VRT pequeno "
    "que os abre como uma camada no QGIS.",
    "Name the files for the sits package": "Nomear os arquivos para o pacote sits",
    "Files go to downloads/<collection>/sits/ named <collection>_<projection>_<tile>_<band>_<date>.tif, which "
    "sits_cube() reads as a local cube with its default parse_info.": "Os arquivos vão para "
    "downloads/<coleção>/sits/ com o nome <coleção>_<projeção>_<tile>_<banda>_<data>.tif, que o sits_cube() lê "
    "como cubo local com o parse_info padrão.",
    "Output projection": "Projeção de saída",
    "Native (BDC Albers)": "Nativa (BDC Albers)",
    "Keeps the grid the cube is stored in \u2014 nothing is resampled.": "Mantém a grade em que o cubo é "
    "guardado: nada é reamostrado.",
    "WGS 84 (EPSG:4326)": "WGS 84 (EPSG:4326)",
    "Geographic latitude/longitude \u2014 the most portable output.": "Latitude/longitude geográficas: a saída "
    "mais portável.",
    "Lines the download up with the project without on-the-fly reprojection.": "Alinha o download ao projeto, sem "
    "reprojeção na hora.",
    "Don't ask me again": "Não perguntar de novo",
    "Later downloads reuse these settings without asking.": "Os próximos downloads usam estas opções sem perguntar.",
    "Change folder...": "Trocar pasta...",
    # Export query
    "Export Query / Code": "Exportar consulta / código",
    "<b style='font-size:13px; color:#2c3e50;'>Export Query Parameters / Code Snippets</b>": "<b "
    "style='font-size:13px; color:#2c3e50;'>Exportar parâmetros da consulta / trechos de código</b>",
    "Copy to Clipboard": "Copiar",
    "Save File...": "Salvar arquivo...",
    # Collection filter
    "Filter Collections": "Filtrar coleções",
    "What is this dialog and what do the badges mean?": "O que é esta janela e o que as etiquetas significam?",
    "Apply": "Aplicar",
    "\u2713 Apply": "\u2713 Aplicar",
    # STAC offline
    "STAC - Connection Status": "STAC: estado da conexão",
    "<b style='font-size:14px;'>STAC Server Offline</b>": "<b style='font-size:14px;'>Servidor STAC offline</b>",
    "The <b>BDC STAC</b> server is currently unreachable.<br><br>The plugin is operating in <b>offline/fallback "
    "mode</b> with cached collection data. Some features like search and live temporal extents are unavailable "
    "until the server recovers.<br><br>The plugin will <b>automatically check</b> every 30 seconds and notify you "
    "when the service is back online.": "O servidor <b>STAC do BDC</b> está inacessível.<br><br>O plugin funciona em "
    "<b>modo offline</b>, com os dados de coleções guardados. Algumas funções, como a busca e os períodos "
    "atualizados, ficam indisponíveis até o servidor voltar.<br><br>O plugin <b>verifica sozinho</b> a cada 30 "
    "segundos e avisa quando o serviço voltar.",
    "<a href='https://data.inpe.br/bdc/stac/v1/' style='color:#2980b9; font-size:12px;'>Open STAC endpoint in "
    "browser to test</a>": "<a href='https://data.inpe.br/bdc/stac/v1/' style='color:#2980b9; font-size:12px;'>"
    "Abrir o endereço STAC no navegador para testar</a>",
    "Check Now": "Verificar agora",
    "Continue Offline": "Continuar offline",
    # Tile filter
    "Select Tiles": "Selecionar tiles",
    "<b style='font-size: 13px;'>Select tiles to filter</b>": "<b style='font-size: 13px;'>Selecione os tiles "
    "para filtrar</b>",
    "Search tile by ID...": "Buscar tile pelo ID...",
    # Composition
    "Composition name": "Nome da composição",
    "Name:": "Nome:",
    "Red:": "Vermelho:",
    "Green:": "Verde:",
    "Blue:": "Azul:",
    "No conflicts detected.": "Nenhum conflito.",
    # Timeline shortcuts
    "\u2328\ufe0f Keyboard Shortcuts \u2014 BDC Timeline": "\u2328\ufe0f Atalhos de teclado \u2014 Linha do tempo",
    "\u2328\ufe0f Configure Timeline Shortcuts": "\u2328\ufe0f Atalhos da linha do tempo",
    "Click in the field and <b>press</b> your desired key combination.<br>Do not type \u2014 just press the "
    "shortcut keys.": "Clique no campo e <b>pressione</b> a combinação de teclas.<br>Não digite: só pressione as "
    "teclas do atalho.",
    "Previous date": "Data anterior",
    "Next date": "Próxima data",
    "Press shortcut": "Pressione o atalho",
    "Clear this shortcut": "Limpar este atalho",
    "Click here, then press your desired shortcut keys": "Clique aqui e pressione as teclas do atalho",
    "Reset to defaults: Alt+Left / Alt+Right": "Restaurar o padrão: Alt+Esquerda / Alt+Direita",
    "\u21ba Reset Defaults": "\u21ba Restaurar padrão",
    # Time series history map settings
    "History Map Settings": "Pontos do histórico no mapa",
    "Show points on map": "Mostrar os pontos no mapa",
    "Show labels": "Mostrar rótulos",
    "Point Color:": "Cor do ponto:",
    "Point Size:": "Tamanho do ponto:",
    "VRT Composition (Chart Click)": "Composição do VRT (clique no gráfico)",
    "VRT Mode:": "Modo do VRT:",
    "Color Mode:": "Modo de cor:",
    "Single Band:": "Banda única:",
    "Single band": "Banda única",
    "Band R:": "Banda R:",
    "Band G:": "Banda G:",
    "Band B:": "Banda B:",
    "Leave empty to use chart bands (R/G/B combos)": "Deixe vazio para usar as bandas do gráfico (R/G/B)",
    # Settings and panels
    "Overviews": "Overviews",
    "Downloads": "Downloads",
    "Type": "Tipo",
    "Date": "Data",
    "Value": "Valor",
    "Luminance": "Luminância",
    "Reflectance / index (x10\u2074)": "Reflectância / índice (x10\u2074)",
    "Collection / Item / Band": "Coleção / item / banda",
    "Size": "Tamanho",
    "File": "Arquivo",
    "Folder": "Pasta",
}


def _lcf(match):
    text = match.group(0)
    for english, portuguese in ((" days", " dias"), (" months", " meses"), (" years", " anos")):
        text = text.replace(english, portuguese)
    return text


_DIALOG_PATTERNS = [
    (r".* \| .*LCF \d+ (?:days|months|years).*", _lcf),
    (r"Period: (\S+) to (\S+)", r"Período: \1 a \2"),
    (r"Download (\d+) band\(s\) for (\d+) selected results\?", r"Baixar \1 banda(s) de \2 resultados selecionados?"),
    (r"Folder: (.+)", r"Pasta: \1"),
    (r"First result\. Destination: (.+)\nFiles: (.+)", r"Primeiro resultado. Destino: \1\nArquivos: \2"),
    (r"Same bands as \"(.+)\"\.", r"Mesmas bandas de \"\1\"."),
    (r"Current QGIS project CRS \((.+)\)", r"SRC atual do projeto QGIS (\1)"),
    (r"Collection: <b>(.+)</b>", r"Coleção: <b>\1</b>"),
    (r"Ex: (.+)", r"Ex.: \1"),
]

_MORE = {
    "Filter Collections Help": "Ajuda: filtrar coleções",
    "<b>Filter Collections & Badges Explanation</b>": "<b>Filtro de coleções e etiquetas</b>",
    "<p><b>What does this dialog do?</b><br/>"
    "This dialog allows you to customize which STAC collections appear in the main dropdown list. "
    "Uncheck any collection you do not use to simplify navigation.</p>"
    "<p><b>Collection Badges:</b></p>"
    "<ul>"
    "<li><b>[CUBE] / [MOSAIC] / [SCENE]:</b> Category type of the STAC dataset.</li>"
    "<li><span style='color: #1e8449;'><b>[COG]:</b></span> Cloud-Optimized GeoTIFF — streams fast over network "
    "via internal overviews.</li>"
    "<li><span style='color: #b9770e;'><b>[GEOTIFF]:</b></span> Standard GeoTIFF — does not have pyramids; best "
    "suited for local download.</li>"
    "<li><span style='color: #707b7c;'><b>[NO GRID]:</b></span> Collections without a fixed tile grid (e.g. "
    "Amazonia-1) — search via Extent (BBOX) or Shapefile.</li>"
    "</ul>": "<p><b>Para que serve esta janela?</b><br/>"
    "Escolhe quais coleções STAC aparecem na lista principal. Desmarque as que não usa para simplificar a lista.</p>"
    "<p><b>Etiquetas das coleções:</b></p>"
    "<ul>"
    "<li><b>[CUBE] / [MOSAIC] / [SCENE]:</b> tipo do conjunto de dados STAC.</li>"
    "<li><span style='color: #1e8449;'><b>[COG]:</b></span> Cloud-Optimized GeoTIFF: lido rápido pela rede, com "
    "overviews internas.</li>"
    "<li><span style='color: #b9770e;'><b>[GEOTIFF]:</b></span> GeoTIFF comum, sem pirâmides: melhor baixar.</li>"
    "<li><span style='color: #707b7c;'><b>[NO GRID]:</b></span> coleções sem grade de tiles (ex.: Amazonia-1): "
    "busque por Extensão (BBOX) ou arquivo vetorial.</li>"
    "</ul>",
    "With one band every format writes the same single file.": "Com uma banda, todos os formatos gravam o mesmo "
    "arquivo.",
    "RGB (3 bands)": "RGB (3 bandas)",
    "Copied!": "Copiado!",
    "Import Query Specification": "Importar consulta",
    "Fill from Current UI (Tab)": "Preencher com a interface (Tab)",
    "Press Tab or click to insert current plugin UI query parameters": "Tecle Tab ou clique para inserir os "
    "parâmetros atuais do plugin",
    "Open File...": "Abrir arquivo...",
    "Paste JSON or YAML query specification here...\n\n"
    "Tip: Press Tab to instantly fill with current plugin UI parameters!\n\n"
    'Example:\n{\n  "collection": "S2-16D-2",\n  "temporal": {"start": "2024-01-01", "end": "2024-12-31"}\n}': ""
    "Cole aqui a consulta em JSON ou YAML...\n\nDica: tecle Tab para preencher com os parâmetros atuais do "
    'plugin.\n\nExemplo:\n{\n  "collection": "S2-16D-2",\n  "temporal": {"start": "2024-01-01", "end": '
    '"2024-12-31"}\n}',
    "Waiting for input (Press Tab to insert current UI query)...": "Aguardando a consulta (tecle Tab para inserir "
    "a da interface)...",
    "Apply to Plugin UI": "Aplicar ao plugin",
    "<b style='font-size:13px; color:#2c3e50;'>Paste JSON/YAML text or load from file:</b>": "<b "
    "style='font-size:13px; color:#2c3e50;'>Cole o texto JSON/YAML ou abra um arquivo:</b>",
    "Saved": "Salvo",
    "Query Loaded": "Consulta carregada",
    "The query parameters have been successfully applied to the plugin interface.": "Os parâmetros da consulta "
    "foram aplicados ao plugin.",
    "Save Error": "Erro ao salvar",
    "Materialization Error": "Erro ao montar a consulta",
    "Read Error": "Erro de leitura",
    "Application Error": "Erro ao aplicar",
    "Checking connection...": "Verificando a conexão...",
    "Server still unreachable. Next check in 30 s...": "Servidor ainda inacessível. Nova verificação em 30 s...",
    "Both shortcuts must be set.": "Defina os dois atalhos.",
    "Both shortcuts cannot be the same.": "Os dois atalhos não podem ser iguais.",
    "Shortcut conflict": "Conflito de atalho",
    "<b style='font-size:13px; color:#c0392b;'>Grid download failed</b><br>"
    "<span style='font-size:11px; color:#444;'>The server may be down or unavailable at the moment.</span>": "<b "
    "style='font-size:13px; color:#c0392b;'>Falha ao baixar a grade</b><br><span style='font-size:11px; "
    "color:#444;'>O servidor pode estar fora do ar no momento.</span>",
    "Please try again later. If the problem persists, contact the Brazil Data Cube team with the error below.": ""
    "Tente de novo mais tarde. Se o problema continuar, fale com a equipe do Brazil Data Cube e envie o erro abaixo.",
    "<span style='font-size:9px; color:#888;'>Select the text above and press Ctrl+C to copy.</span>": "<span "
    "style='font-size:9px; color:#888;'>Selecione o texto acima e tecle Ctrl+C para copiar.</span>",
    "  Email BDC Team": "  E-mail para a equipe do BDC",
    "Error downloading grid": "Erro ao baixar a grade",
    "Grid Update Available": "Atualização da grade disponível",
    "Restore": "Restaurar",
    "Range locked": "Faixa travada",
    "Install matplotlib for the plugin": "Instalar o matplotlib para o plugin",
    "Install the matplotlib version compatible with BDC Loader?\n\n"
    "It is downloaded once and kept in the plugin's own folder. "
    "Packages QGIS already has are used as they are.": "Instalar a versão do matplotlib compatível com o BDC "
    "Loader?\n\nEla é baixada uma vez e fica na pasta do plugin. Os pacotes que o QGIS já tem são usados como estão.",
    "Starting...": "Iniciando...",
    "Cancelling...": "Cancelando...",
    "Installation cancelled.": "Instalação cancelada.",
    "No filtered files to delete. Run a search first.": "Nenhum arquivo filtrado para excluir. Faça uma busca antes.",
    "Select files to delete.": "Selecione os arquivos a excluir.",
    "Invalid Regex": "Expressão regular inválida",
    "Downloads folder does not exist.": "A pasta de downloads não existe.",
    "Select an item to delete.": "Selecione um item para excluir.",
    "Path not found.": "Caminho não encontrado.",
}

_DOCS = {
    "Start Here \u2014 Official INPE Data": "Comece aqui: dados oficiais do INPE",
    "Explore INPE Geospatial Data": "Dados geoespaciais do INPE",
    "Main catalog for satellite imagery and other INPE collections, including CBERS, AMAZONIA-1, Sentinel, Landsat, "
    "meteorological, topographic, and water-related datasets.": "Catálogo principal de imagens de satélite e outras "
    "coleções do INPE, como CBERS, AMAZONIA-1, Sentinel, Landsat e dados meteorológicos, topográficos e de água.",
    "Brazil Data Cube Products": "Produtos do Brazil Data Cube",
    "Primary reference for available data cubes, spatial and temporal resolution, coverage periods, BDC grids, "
    "EPSG:10857, composition bands, product descriptions, and access links.": "Referência principal dos cubos de "
    "dados: resolução espacial e temporal, períodos, grades BDC, EPSG:10857, bandas, descrição dos produtos e links "
    "de acesso.",
    "Explore &amp; Access BDC Collections": "Explorar e acessar as coleções do BDC",
    "STAC Browser": "STAC Browser",
    "Explore BDC collections, dates, items, metadata, and downloadable assets in a web interface.": "Coleções, "
    "datas, itens, metadados e arquivos para download do BDC em uma interface web.",
    "BDC Explorer": "BDC Explorer",
    "Interactive map for visualizing satellite imagery, mosaics, data cubes, time series, and land-use trajectories.": ""
    "Mapa interativo para ver imagens, mosaicos, cubos de dados, séries temporais e trajetórias de uso da terra.",
    "STAC API Endpoint": "Endereço da API STAC",
    "REST catalog used by this plugin for collection discovery, searches, metadata, and COG assets.": "Catálogo REST "
    "que o plugin usa para listar coleções, buscar, ler metadados e arquivos COG.",
    "Optional Technical References": "Referências técnicas",
    "Input Data": "Dados de entrada",
    "Source satellite imagery used by BDC: Sentinel-2, Landsat-8, CBERS-4/4A, AMAZONIA-1, and MODIS.": "Imagens de "
    "satélite usadas pelo BDC: Sentinel-2, Landsat-8, CBERS-4/4A, AMAZONIA-1 e MODIS.",
    "Concepts": "Conceitos",
    "Core definitions \u2014 Cube Collection, Tile, Band, GRS, Compositing Function, and the 4D data model.": ""
    "Definições básicas: coleção de cubos, tile, banda, GRS, função de composição e o modelo de dados 4D.",
    "Projection": "Projeção",
    "Albers Equal-Area Conic projection with SIRGAS-2000 datum, centered at 12\u00b0S / 54\u00b0W.": "Projeção "
    "cônica equivalente de Albers com datum SIRGAS-2000, centrada em 12\u00b0S / 54\u00b0W.",
    "Grids": "Grades",
    "Hierarchical tiling system \u2014 Small (105 km), Medium (211 km), and Large (4224 km) grid levels.": "Sistema "
    "hierárquico de tiles: níveis pequeno (105 km), médio (211 km) e grande (4224 km).",
    "Processing Flow": "Fluxo de processamento",
    "Pipeline from raw imagery to analysis-ready data cubes, including atmospheric correction and compositing.": ""
    "Da imagem bruta ao cubo de dados pronto para análise, com correção atmosférica e composição.",
    "Naming Convention": "Convenção de nomes",
    "How collections and files are named, e.g. <code>S2-16D_V2_008013_20220101_B01.tif</code>.": "Como coleções e "
    "arquivos são nomeados, por exemplo <code>S2-16D_V2_008013_20220101_B01.tif</code>.",
    "Legacy Product Access Guide": "Guia antigo de acesso aos produtos",
    "Additional BDC project instructions for STAC Browser, STAC API, and BDC Explorer.": "Instruções do projeto BDC "
    "para o STAC Browser, a API STAC e o BDC Explorer.",
    "Optional API Guides &amp; Notebooks": "Guias de API e notebooks",
    "STAC Service Guide": "Guia do serviço STAC",
    "Technical documentation for discovering and accessing BDC image collections and data cubes via STAC.": ""
    "Documentação técnica para encontrar e acessar coleções de imagens e cubos de dados do BDC pelo STAC.",
    "STAC Python Client": "Cliente STAC em Python",
    "Python client library (<code>pystac-client</code>) used internally by this plugin for STAC queries.": ""
    "Biblioteca Python (<code>pystac-client</code>) que o plugin usa nas consultas STAC.",
    "WTSS \u2014 Web Time Series Service": "WTSS: serviço web de séries temporais",
    "Lightweight service for extracting time series at a given point and time interval. Used by this plugin for fast "
    "single-point temporal extraction.": "Serviço leve que extrai a série temporal de um ponto em um intervalo de "
    "tempo. O plugin o usa para extrair séries de um ponto rapidamente.",
    "Retrieving Time Series (WTSS)": "Extração de séries temporais (WTSS)",
    "Step-by-step guide on how to query WTSS to retrieve spectral values over time.": "Passo a passo para consultar "
    "o WTSS e obter os valores espectrais ao longo do tempo.",
    "STAC Jupyter Notebooks": "Notebooks Jupyter do STAC",
    "Interactive examples demonstrating STAC catalog queries using Python.": "Exemplos interativos de consultas ao "
    "catálogo STAC em Python.",
    "WTSS Jupyter Notebooks": "Notebooks Jupyter do WTSS",
    "Interactive examples showing time series extraction via WTSS.": "Exemplos interativos de extração de séries "
    "temporais pelo WTSS.",
    "All links open in your default web browser. Start with the official INPE data portals; the remaining links "
    "provide direct access or optional technical detail.": "Os links abrem no navegador padrão. Comece pelos portais "
    "oficiais de dados do INPE; os demais dão acesso direto ou detalhes técnicos.",
    # About
    "Developed by": "Desenvolvido por",
    "Sao Jose dos Campos - SP, Brazil": "São José dos Campos - SP, Brasil",
    "Current Version:": "Versão atual:",
    "INPE - National Institute for Space Research": "INPE - Instituto Nacional de Pesquisas Espaciais",
    "This plugin was built from needs and features identified by the author to support day-to-day time series "
    "analysis workflows inside QGIS. Its design follows a practical, user-oriented view focused on loading, "
    "exploring, navigating and extracting temporal data.": "Este plugin nasceu de necessidades identificadas pelo "
    "autor para apoiar a análise de séries temporais no dia a dia, dentro do QGIS. O desenho é prático e voltado ao "
    "usuário: carregar, explorar, navegar e extrair dados temporais.",
    "BDC Loader is an independent plugin and <b>not an official Brazil Data Cube product</b>. It is aimed at frequent "
    "real-world use cases in temporal analysis.": "O BDC Loader é um plugin independente e <b>não é um produto oficial "
    "do Brazil Data Cube</b>. Ele atende a casos de uso frequentes em análise temporal.",
    "The expectation is that it will also be useful to other users working with similar routines.": "A expectativa é "
    "que também seja útil para outras pessoas com rotinas parecidas.",
    "Key Features": "Principais funções",
    "Integrated time series panel with temporal navigation inside QGIS.": "Painel de séries temporais com navegação "
    "no tempo, dentro do QGIS.",
    "Dynamic search across Brazil Data Cube STAC collections.": "Busca nas coleções STAC do Brazil Data Cube.",
    "Remote and local VRT generation designed for daily analytical workflows.": "Geração de VRT remotos e locais "
    "para o trabalho diário de análise.",
    "Loading of single bands or RGB compositions directly into the map.": "Carregamento de bandas únicas ou "
    "composições RGB direto no mapa.",
    "Point-based temporal value extraction focused on applied analysis.": "Extração de valores temporais por ponto, "
    "voltada à análise aplicada.",
    "Shortcuts, filters and interface choices designed for productivity.": "Atalhos, filtros e escolhas de "
    "interface pensados para a produtividade.",
    "Important notice": "Aviso importante",
    "The plugin relies on services, catalogs and concepts associated with Brazil Data Cube, but its interface, "
    "workflow decisions and part of its functionality reflect an independent, user-driven implementation developed "
    "for research and applied use.": "O plugin usa serviços, catálogos e conceitos do Brazil Data Cube, mas a "
    "interface, o fluxo de trabalho e parte das funções são uma implementação independente, feita para pesquisa e "
    "uso aplicado.",
    "Useful Links": "Links úteis",
    "Collections Documentation": "Documentação das coleções",
}

_ITEM_KINDS = {"file": ("arquivo", "Arquivo apagado"), "folder": ("pasta", "Pasta apagada")}


def _delete_one(match):
    kind = _ITEM_KINDS.get(match.group(1).lower(), (match.group(1), ""))[0]
    return f"Apagar {kind}: {match.group(2)}?\n\nNão dá para desfazer."


def _deleted_one(match):
    done = _ITEM_KINDS.get(match.group(1).lower(), ("", f"{match.group(1)} apagado"))[1]
    return f"{done}: {match.group(2)}"


def _n(count, one, many):
    """``count`` and the singular or the plural Portuguese words, as count_label in i18n."""
    return f"{count} {one if count == '1' else many}"


def _downloading(match):
    """[i/n] Downloading <what>: <size>[ of <total>][ (<speed>/s, <n> files at a time)]."""
    what = re.sub(r"(\d+) bands? of ", lambda m: f"{_n(m[1], 'banda', 'bandas')} de ", match[2])
    what = re.sub(r"^the tiles of ", "os tiles de ", re.sub(r"^grid ", "a grade ", what))
    progress = match[3].replace(" of ", " de ")
    progress = re.sub(
        r"(\d+) files? at a time\)", lambda m: f"{_n(m[1], 'arquivo', 'arquivos')} ao mesmo tempo)", progress
    )
    return f"{match[1]}Baixando {what}: {progress}"


def _download_summary(match):
    """[Download cancelled: i of n images processed, ]<n> images downloaded[, <n> without valid pixels (...)]..."""
    head = ""
    if match[1]:
        head = f"Download cancelado: {match[1]} de {_n(match[2], 'imagem processada', 'imagens processadas')}, "
    rest = (
        match[4].replace(" without valid pixels (", " sem pixel válido (").replace(" already on disk", " já no disco")
    )
    rest = rest.replace(" failed", " com falha")
    return f"{head}{_n(match[3], 'imagem baixada', 'imagens baixadas')}{rest}."


_FAILED = {
    "Search": "na busca",
    "Download": "no download",
    "Grid download": "no download da grade",
    "Time series extraction": "na extração da série temporal",
    "Loading collections": "no carregamento das coleções",
    "Loading layers": "no carregamento das camadas",
}
_REASONS = (
    (r"no layer was added to the map", "nenhuma camada foi adicionada ao mapa"),
    (r"(.+) could not be built", r"não foi possível montar \1"),
    (r"QGIS could not read (.+)", r"o QGIS não conseguiu ler \1"),
    (r"unknown error", "erro desconhecido"),
)


def _failed(match):
    """<Process> failed: <reason>. The reason is translated when the plugin wrote it."""
    process, reason = match[1], match[2]
    for english, portuguese in _REASONS:
        if re.fullmatch(english, reason):
            reason = re.sub(english, portuguese, reason)
            break
    date = re.fullmatch(r"Opening the image of (\S+)", process)
    where = f"ao abrir a imagem de {date[1]}" if date else _FAILED[process]
    return f"Falha {where}: {reason}."


def _reuse(match):
    """Extracting time series (<n> points already extracted, <n> points with new bands)..."""
    text = re.sub(
        r"(\d+) points? already extracted",
        lambda m: f"{_n(m[1], 'ponto já extraído', 'pontos já extraídos')}",
        match[1],
    )
    text = re.sub(r"(\d+) points? with new bands", lambda m: f"{_n(m[1], 'ponto', 'pontos')} com bandas novas", text)
    return f"Extraindo a série temporal ({text})..."


def _extracted(match):
    """<n> values extracted[: <n> new points, <n> updated, <n> unchanged].[ <n> pixel reads failed ...]"""
    text = _n(match[1], "valor extraído", "valores extraídos")
    if match[2]:
        parts = re.sub(r"(\d+) new points?", lambda m: _n(m[1], "ponto novo", "pontos novos"), match[2])
        parts = re.sub(r"(\d+) updated", lambda m: _n(m[1], "atualizado", "atualizados"), parts)
        parts = re.sub(r"(\d+) unchanged", r"\1 sem mudança", parts)
        text += f": {parts}"
    text += "."
    if match[3]:
        reads = _n(match[3], "leitura de pixel falhou", "leituras de pixel falharam")
        text += f" {reads} após nova tentativa; a série tem falhas."
    return text


_DISPLAY_STEPS = {"overview and contrast": "overview e contraste", "contrast": "contraste"}


def _display_progress(match):
    """Preparing layers for display (<step>): d/n (<s> s)[, waiting for the BDC server]."""
    text = f"Preparando as camadas para exibição ({_DISPLAY_STEPS[match[1]]}): {match[2]}/{match[3]} ({match[4]} s)"
    return text + (", aguardando o servidor do BDC" if match[5] else "")


def _load_report(match):
    """[Loading cancelled: ]<n> layers added to the map[, turned off] (<timing>).[ <notes>.]"""
    text = _n(match[2], "camada adicionada", "camadas adicionadas") + " ao mapa"
    if match[3]:
        text += ", " + ("desligada" if match[2] == "1" else "desligadas")
    timing = match[4].replace(" per layer", " por camada").replace("slow server", "servidor lento")
    text += f" ({timing.replace('moderate speed', 'velocidade moderada')})."
    if match[1]:
        text = "Carregamento cancelado: " + text
    notes = match[5]
    for english, one, many in (
        (r"(\d+) from your downloads", "dos seus downloads", "dos seus downloads"),
        (r"(\d+) streamed from the BDC", "lida do BDC", "lidas do BDC"),
        (r"(\d+) non-raster duplicates? skipped", "duplicada não raster ignorada", "duplicadas não raster ignoradas"),
        (
            r"(\d+) switched from the BDC to your downloads",
            "trocada do BDC pelos seus downloads",
            "trocadas do BDC pelos seus downloads",
        ),
        (r"(\d+) errors?", "erro", "erros"),
    ):
        notes = re.sub(english, lambda m, one=one, many=many: _n(m[1], one, many), notes)
    return text + notes


def _empty_layers(match):
    """<i> of <n> layers have no valid pixel in this area (...): <names>."""
    verb = "não tem" if match[1] == "1" else "não têm"
    names = re.sub(r" and (\d+) more$", r" e mais \1", match[3])
    return (
        f"{match[1]} de {_n(match[2], 'camada', 'camadas')} {verb} pixel válido nesta área (a imagem a cobre só com a "
        f"borda vazia, ou a área não tem dado): {names}."
    )


_PARAM_NAMES = {"collection": "coleção", "bands": "bandas", "period": "período", "area": "área", "limit": "limite"}


def _params_changed(match):
    names = ", ".join(_PARAM_NAMES.get(name.strip(), name.strip()) for name in match.group(1).split(","))
    return f"Os parâmetros da busca mudaram ({names}). Clique em Buscar STAC de novo."


_STATUS = {
    # Main window
    "Select a collection with available bands first.": "Selecione antes uma coleção com bandas disponíveis.",
    "<b>Offline:</b> the BDC cannot be reached. Search lists the images downloaded on this computer; online "
    "search resumes when the connection returns.": "<b>Offline:</b> o BDC não responde. A busca lista as imagens "
    "baixadas neste computador; a busca online volta quando a conexão voltar.",
    "Cancelling download...": "Cancelando o download...",
    "Select one or more results to download.": "Selecione um ou mais resultados para baixar.",
    "Select at least 1 band before downloading.": "Selecione ao menos 1 banda antes de baixar.",
    "Grid download cancelled.": "Download da grade cancelado.",
    "The project has no polygon layer. Load one (for example a tile grid with Load Grid) or browse for a file.": (
        "O projeto não tem camada de polígonos. Carregue uma (por exemplo, a grade de tiles com Carregar grade) ou "
        "escolha um arquivo."
    ),
    "Band not available": "Banda indisponível",
    "Collection is not cloud-optimized": "Coleção sem otimização para nuvem (COG)",
    "Don't show this warning again": "Não mostrar este aviso de novo",
    "Select at least one item.": "Selecione ao menos um item.",
    "Select at least 1 band.": "Selecione ao menos 1 banda.",
    "Select 1 band (single image) or 3 bands (RGB composite).": "Selecione 1 banda (imagem única) ou 3 bandas "
    "(composição RGB).",
    "Loading cancelled.": "Carregamento cancelado.",
    "No layer loaded.\n\nCheck that:\n- Results are selected (checkboxes)\n- 1 or 3 bands are selected\n- The "
    "server is reachable": "Nenhuma camada carregada.\n\nConfira se:\n- há resultados marcados\n- há 1 ou 3 bandas "
    "selecionadas\n- o servidor responde",
    "Extent set from manual bbox.": "Extensão definida pelo bbox digitado.",
    "No bbox to center on.": "Não há bbox para centralizar.",
    "Image already downloaded": "Imagem já baixada",
    "Tiles (N/A)": "Tiles (n/d)",
    "Start date must not be after end date.": "A data inicial não pode ser depois da final.",
    # Time series panel
    "Loading collections...": "Carregando coleções...",
    "Select a collection.": "Selecione uma coleção.",
    "Select at least one band.": "Selecione ao menos uma banda.",
    "Line/polygon features were ignored.\n\nOnly Point geometries are supported.\nConvert centroids or generate "
    "points if needed.": "Feições de linha e polígono foram ignoradas.\n\nSó geometrias de ponto são aceitas.\n"
    "Converta em centroides ou gere pontos, se precisar.",
    # Dialogs
    "Apply the BDC Albers Equal-Area Conic projection\nas the current QGIS project CRS?\n\nProjection: Albers "
    "Equal-Area Conic\nDatum: SIRGAS-2000 (GRS80)\nOrigin: 12°S / 54°W\nStandard parallels: 2°S and 22°S": (
        "Aplicar a projeção cônica equivalente de Albers do BDC\ncomo SRC do projeto QGIS?\n\nProjeção: cônica "
        "equivalente de Albers\nDatum: SIRGAS-2000 (GRS80)\nOrigem: 12°S / 54°W\nParalelos padrão: 2°S e 22°S"
    ),
    "Failed to save the BDC CRS in the QGIS user database.": "Falha ao gravar o SRC do BDC no banco de dados do "
    "usuário do QGIS.",
    "Failed to create BDC CRS.": "Falha ao criar o SRC do BDC.",
    "The current project is already using SIRGAS 2000 / Brazil Albers.\n\nNo projection was added and no project "
    "setting was changed.": "O projeto já usa SIRGAS 2000 / Brazil Albers.\n\nNenhuma projeção foi acrescentada e "
    "nenhuma configuração do projeto mudou.",
    "R - sits Package (Data Cube)": "R - pacote sits (cubo de dados)",
    "R - rstac Package (STAC API)": "R - pacote rstac (API STAC)",
    "STAC item ID": "ID do item STAC",
    "All types": "Todos os tipos",
    ".vrt only": "Só .vrt",
    ".ovr only": "Só .ovr",
    ".tif only": "Só .tif",
    "Other": "Outros",
    "Single Color": "Cor única",
    "Random Colors": "Cores aleatórias",
    "Classified (random per point)": "Classificada (aleatória por ponto)",
    "Click or drag to adjust range. Double-click to reset.": "Clique ou arraste para ajustar a faixa. Clique duas "
    "vezes para restaurar.",
    "Toggle timeline": "Mostrar ou ocultar a linha do tempo",
    "WTSS: offline": "WTSS: offline",
    "Zoom to point": "Aproximar do ponto",
    "Issues found:": "Problemas encontrados:",
    "Field 'filters' must be an object.": "O campo 'filters' deve ser um objeto.",
    "Field 'cloud_cover_max' must be a number from 0 to 100.": "O campo 'cloud_cover_max' deve ser um número de 0 "
    "a 100.",
    "Field 'limit' must be a whole number greater than 0.": "O campo 'limit' deve ser um número inteiro maior que 0.",
    "Define a spatial extent, provide tiles, or load a shapefile to search.": "Defina uma extensão, informe tiles "
    "ou abra um arquivo vetorial para buscar.",
    "This collection has no tile system. Define a spatial extent or load a shapefile.": "Esta coleção não tem "
    "sistema de tiles. Defina uma extensão ou abra um arquivo vetorial.",
    "No band selected. Select at least 1 band.": "Nenhuma banda escolhida. Escolha ao menos 1 banda.",
    "No feature of the vector file is checked. Check at least one, or Merge all.": "Nenhuma feição do arquivo "
    "vetorial está marcada. Marque ao menos uma ou use Unir todas.",
    "The extent has no area. Drag a box on the map, or type four different coordinates.": "A extensão não tem "
    "área. Arraste um retângulo no mapa ou digite quatro coordenadas diferentes.",
    "The extent is outside longitude -180 to 180 and latitude -90 to 90.": "A extensão está fora da longitude "
    "-180 a 180 e da latitude -90 a 90.",
    "The parameters are back to those of the search.": "Os parâmetros voltaram aos da busca.",
    "Warning": "Aviso",
    "Download Errors": "Erros no download",
    "Mixed Geometry Warning": "Geometrias misturadas",
    "Single Band": "Banda única",
    "Custom": "Personalizado",
    "BDC Projection Ready": "Projeção do BDC aplicada",
    "BDC Projection Already Active": "Projeção do BDC já ativa",
    "JSON (Generic Spec)": "JSON (consulta genérica)",
    "YAML (Generic Spec)": "YAML (consulta genérica)",
    "cURL / HTTP Request": "cURL / requisição HTTP",
    "Add to Project": "Adicionar ao projeto",
    "Remove from history": "Remover do histórico",
    "Remove point": "Remover ponto",
    "WTSS unavailable \u2014 using STAC+VRT as fallback": "WTSS indisponível: usando STAC+VRT no lugar",
    # Query import
    "Query specification must be a valid JSON or YAML dictionary object.": "A consulta deve ser um objeto JSON ou "
    "YAML válido.",
    "Missing or invalid 'collection' field in query specification.": "Campo 'collection' ausente ou inválido na "
    "consulta.",
    "Field 'temporal' must be an object with 'start' and 'end' dates.": "O campo 'temporal' deve ser um objeto com "
    "as datas 'start' e 'end'.",
    "Invalid date format. Use YYYY-MM-DD (e.g. 2024-01-01).": "Data em formato inválido. Use AAAA-MM-DD (por "
    "exemplo, 2024-01-01).",
    "Field 'spatial' must be an object.": "O campo 'spatial' deve ser um objeto.",
    "Field 'tiles' must be a list of tile IDs.": "O campo 'tiles' deve ser uma lista de IDs de tile.",
    "Field 'bbox' must contain exactly 4 coordinates [west, south, east, north].": "O campo 'bbox' deve ter "
    "exatamente 4 coordenadas [oeste, sul, leste, norte].",
    "BBOX coordinates are out of valid geographical bounds (WGS84).": "As coordenadas do BBOX estão fora dos "
    "limites geográficos (WGS84).",
    "Invalid BBOX: minimum longitude/latitude is greater than maximum.": "BBOX inválido: a longitude ou latitude "
    "mínima é maior que a máxima.",
    "Invalid numeric values in BBOX coordinates.": "Valores numéricos inválidos nas coordenadas do BBOX.",
    "Paste JSON or YAML query text in the field above or load from a file.": "Cole a consulta em JSON ou YAML no "
    "campo acima ou carregue de um arquivo.",
    "Points \u2014 Help & Features": "Pontos: ajuda",
    "<b>\u25cf Map Picker:</b><br>"
    "Click the picker button, then click on the map to select a pixel.<br>"
    "Press <b>ESC</b> to deactivate and return to normal navigation.<br><br>"
    "<b>\u25cf Single mode:</b> Click map \u2192 auto-extracts time series for 1 point.<br>"
    "<b>\u25cf Multi mode:</b> Pick multiple points, then click <b>Extract</b>.<br><br>"
    "<b>\u25cf Coordinates (Lon/Lat):</b><br>"
    "Enter longitude and latitude in WGS84 (EPSG:4326) and click <b>+</b>.<br>"
    "Example: Lon = <code>-47.9292</code>, Lat = <code>-15.7801</code><br><br>"
    "<b>\u25cf WKT:</b><br>"
    "Enter a POINT geometry in WKT format:<br>"
    "<code>POINT(-47.9292 -15.7801)</code><br><br>"
    "<b>\u25cf Shapefile / GeoPackage:</b><br>"
    "Click <b>SHP / GPKG</b> to load point features.<br>"
    "Only <b>Point</b> or <b>MultiPoint</b> geometries are supported.<br>"
    "The label column is auto-detected from: "
    "<code>label</code>, <code>name</code>, <code>nome</code>, <code>id</code>.<br><br>"
    "<b>Required SHP/GPKG format:</b><br>"
    "\u2022 Geometry type: <b>Point</b> or <b>MultiPoint</b><br>"
    "\u2022 CRS: any (auto-reprojected to EPSG:4326)<br>"
    "\u2022 Optional columns: <code>label</code>, <code>name</code>, <code>nome</code>, or <code>id</code> for point "
    "labels<br><br>"
    "<b>\u25cf Bands filter:</b> Type in the filter box to search bands. "
    "Use <b>All</b>/<b>None</b> to toggle selection.<br><br>"
    "<b>\u25cf Interactions:</b><br>"
    "\u2022 <b>Double-click</b> a point to zoom to it on the map<br>"
    "\u2022 <b>Delete/Backspace</b> to remove selected points<br>"
    "\u2022 <b>Right-click</b> for context menu (remove, zoom, copy coords)": (
        "<b>\u25cf Seletor no mapa:</b><br>"
        "Clique no botão do seletor e depois no mapa para escolher um pixel.<br>"
        "Tecle <b>ESC</b> para desligar e voltar à navegação normal.<br><br>"
        "<b>\u25cf Modo único:</b> clique no mapa \u2192 extrai a série temporal de 1 ponto.<br>"
        "<b>\u25cf Modo múltiplo:</b> escolha vários pontos e clique em <b>Extrair</b>.<br><br>"
        "<b>\u25cf Coordenadas (Lon/Lat):</b><br>"
        "Digite longitude e latitude em WGS84 (EPSG:4326) e clique em <b>+</b>.<br>"
        "Exemplo: Lon = <code>-47.9292</code>, Lat = <code>-15.7801</code><br><br>"
        "<b>\u25cf WKT:</b><br>"
        "Digite uma geometria POINT em WKT:<br>"
        "<code>POINT(-47.9292 -15.7801)</code><br><br>"
        "<b>\u25cf Shapefile / GeoPackage:</b><br>"
        "Clique em <b>SHP / GPKG</b> para carregar feições de ponto.<br>"
        "Só geometrias <b>Point</b> ou <b>MultiPoint</b> são aceitas.<br>"
        "A coluna de rótulo é detectada entre: "
        "<code>label</code>, <code>name</code>, <code>nome</code>, <code>id</code>.<br><br>"
        "<b>Formato SHP/GPKG:</b><br>"
        "\u2022 Geometria: <b>Point</b> ou <b>MultiPoint</b><br>"
        "\u2022 SRC: qualquer um (reprojetado para EPSG:4326)<br>"
        "\u2022 Colunas opcionais para o rótulo: <code>label</code>, <code>name</code>, <code>nome</code> ou "
        "<code>id</code><br><br>"
        "<b>\u25cf Filtro de bandas:</b> digite na caixa de filtro para buscar bandas. "
        "Use <b>Todos</b>/<b>Nenhum</b> para marcar ou desmarcar.<br><br>"
        "<b>\u25cf Interações:</b><br>"
        "\u2022 <b>Clique duplo</b> num ponto aproxima o mapa dele<br>"
        "\u2022 <b>Delete/Backspace</b> remove os pontos selecionados<br>"
        "\u2022 <b>Botão direito</b> abre o menu (remover, aproximar, copiar coordenadas)"
    ),
}

_STATUS_PATTERNS = [
    (r"Exported (\d+) features\.\nAdd to QGIS project\?", r"\1 feições exportadas.\nAdicionar ao projeto QGIS?"),
    (r"Error exporting (CSV|GPKG): ((?s:.+))", r"Erro ao exportar \1: \2"),
    (r"matplotlib (.+) installed\.", r"matplotlib \1 instalado."),
    (
        r"Installation failed: matplotlib still cannot be imported\.",
        r"Falha na instalação: o matplotlib ainda não "
        r"pode ser importado.",
    ),
    (r"Installation failed: ((?s:.+))", r"Falha na instalação: \1"),
    (r'Composition "(.+)" saved\.', r'Composição "\1" salva.'),
    (r'Delete your composition "(.+)"\?', r'Apagar a sua composição "\1"?'),
    (r'Composition "(.+)" deleted\.', r'Composição "\1" apagada.'),
    (r"\((\d+) tiles\)", r"(\1 tiles)"),
    (r"\((\d+)/(\d+) tiles\)", r"(\1/\2 tiles)"),
    (r"\((\d+) dates\)", r"(\1 datas)"),
    (r"\((\d+)/(\d+) features\)", r"(\1/\2 feições)"),
    (r"Downloading grid (\S+)\.\.\.", r"Baixando a grade \1..."),
    (r"Download URL not available for grid (\S+)", r"Endereço de download indisponível para a grade \1"),
    (r"Grid (\S+) is already in the project", r"A grade \1 já está no projeto"),
    (r"Could not load grid (\S+)", r"Não foi possível carregar a grade \1"),
    (r"Extracting grid (\S+)\.\.\.", r"Extraindo a grade \1..."),
    (r"Converting grid (\S+) to GeoPackage\.\.\.", r"Convertendo a grade \1 para GeoPackage..."),
    (
        r"Grid (\S+) could not be loaded from WFS\.\nDownload shapefile now\?",
        r"A grade \1 não carregou pelo WFS.\nBaixar o shapefile agora?",
    ),
    (
        r"Grid (\S+) is stored as KML \(old format\)\.\nDownload optimized shapefile version\?\n\nThis will be "
        r"faster and use Brazil-only tiles\.",
        r"A grade \1 está em KML (formato antigo).\nBaixar a versão em shapefile?\n\nEla é mais rápida e só tem os "
        r"tiles do Brasil.",
    ),
    (r"Search error: ((?s:.+))", r"Erro na busca: \1"),
    (r"<b>No items found\.</b><br><br>((?s:.*))", r"<b>Nenhum item encontrado.</b><br><br>\1"),
    (r"Collection ID not found for: (.+)", r"ID da coleção não encontrado para: \1"),
    (r"Invalid vector file: (.+)", r"Arquivo vetorial inválido: \1"),
    (
        r"Could not load (\S+) from BDC GeoServer\.\nCheck your internet connection and try again\.",
        r"Não foi possível carregar \1 do GeoServer do BDC.\nConfira a conexão e tente de novo.",
    ),
    (r"Could not open: (.+)", r"Não foi possível abrir: \1"),
    (r"(.+) \(int\)", r"\1 (inteiro)"),
    (r"Coordinates copied: (.+)", r"Coordenadas copiadas: \1"),
    (r"Cannot open file: (.+)", r"Não foi possível abrir o arquivo: \1"),
    (r"Error loading vector: ((?s:.+))", r"Erro ao carregar o vetor: \1"),
    (
        r"The selected extent is large \(~(.+)° × (.+)°\)\.\n\nCrop mode builds cropped layers over this region, "
        r"which may take longer to process and load, especially with many selected items\.\n\nDo you want to "
        r"continue\?",
        r"A extensão escolhida é grande (~\1° × \2°).\n\nO recorte monta camadas recortadas nessa região, o que pode "
        r"demorar para processar e carregar, sobretudo com muitos itens marcados.\n\nContinuar?",
    ),
    (
        r"(\S+) is served as plain GeoTIFF, without the internal overviews that make remote reading fast\.\n\nThe "
        r"layer will load, but QGIS has to stream each full scene to draw it, so panning and zooming will be slow "
        r"and may fail against a busy server\. No overview or contrast stretch is generated for these layers\.\n\n"
        r"Download is the recommended way to work with this collection\.\n\nLoad the layers anyway\?",
        r"\1 é servida como GeoTIFF simples, sem as overviews internas que deixam a leitura remota rápida.\n\nA "
        r"camada carrega, mas o QGIS precisa ler cada cena inteira para desenhá-la, então mover e aproximar o mapa "
        r"fica lento e pode falhar com o servidor ocupado. Essas camadas não ganham overview nem ajuste de "
        r"contraste.\n\nPara esta coleção, o recomendado é baixar.\n\nCarregar as camadas mesmo assim?",
    ),
    (
        r"The Python module '(.+)' needed by BDC Loader was not found\. Reinstall the plugin from its ZIP; if the "
        r"module is not part of the plugin, install it in the Python used by QGIS and restart QGIS\.",
        r"O módulo Python '\1' de que o BDC Loader precisa não foi encontrado. Reinstale o plugin pelo ZIP; se o "
        r"módulo não faz parte do plugin, instale-o no Python do QGIS e reinicie o QGIS.",
    ),
    (
        r'Collection "(.+)" is not available in the sits BDC source\. The generated sits_cube\(\) will not run\. Use '
        r'the R - rstac or Python export instead, or check sits::sits_list_collections\(source = "BDC"\)\.',
        r'A coleção "\1" não está na fonte BDC do sits. O sits_cube() gerado não vai rodar. Use a exportação R - '
        r'rstac ou Python, ou confira sits::sits_list_collections(source = "BDC").',
    ),
    (r"File saved successfully:\n(.+)", r"Arquivo salvo:\n\1"),
    (r"Could not save file: ((?s:.+))", r"Não foi possível salvar o arquivo: \1"),
    (r"Could not read current UI spec: ((?s:.+))", r"Não foi possível ler a consulta da interface: \1"),
    (r"Could not read file: ((?s:.+))", r"Não foi possível ler o arquivo: \1"),
    (r"Could not apply query to UI: ((?s:.+))", r"Não foi possível aplicar a consulta à interface: \1"),
    (r"Folder does not exist: (.+)", r"A pasta não existe: \1"),
    (r"Delete (\w+): (.+)\?\n\nThis action cannot be undone\.", _delete_one),
    (r"Total: (\d+) file\(s\), (.+)", r"Total: \1 arquivo(s), \2"),
    (r"(\w+) deleted: (.+)", _deleted_one),
    (r"Error deleting: ((?s:.+))", r"Erro ao apagar: \1"),
    (
        r"Delete all (\d+) filtered file\(s\) \((.+)\)\?\n\nThis action cannot be undone\.",
        r"Apagar os \1 arquivo(s) filtrado(s) (\2)?\n\nNão dá para desfazer.",
    ),
    (r"Deleted (\d+)/(\d+) files\.", r"\1/\2 arquivos apagados."),
    (
        r"Delete (\d+) file\(s\) \((.+)\)\?\n\nThis action cannot be undone\.",
        r"Apagar \1 arquivo(s) (\2)?\n\nNão dá para desfazer.",
    ),
    (
        r"Delete all (.+) \((.+)\)\?\n\nThis action cannot be undone\.",
        r"Apagar tudo de \1 (\2)?\n\nNão dá para desfazer.",
    ),
    (r"Failed to clean (.+): ((?s:.+))", r"Falha ao limpar \1: \2"),
    (r"Could not compile: (.+)", r"Expressão inválida: \1"),
    (
        r"<a href='(.+)' style='color:#2980b9; font-size:12px;'>Open STAC endpoint in browser to test</a>",
        r"<a href='\1' style='color:#2980b9; font-size:12px;'>Abrir o endereço do STAC no navegador para testar</a>",
    ),
    (
        r"<span style='color:#27ae60; font-weight:bold;'>STAC is back online! \((\d+)ms\)</span>",
        r"<span style='color:#27ae60; font-weight:bold;'>O STAC voltou! (\1 ms)</span>",
    ),
    (r"(\d+)/(\d+) selected \((\d+) filtered\)", r"\1/\2 selecionados (\3 filtrados)"),
    (r"(\d+)/(\d+) selected", r"\1/\2 selecionados"),
    (r'Replaces your composition "(.+)" \((.+)\)\.', r'Substitui a sua composição "\1" (\2).'),
    (r"Reset to defaults: (.+) / (.+)", r"Restaurar o padrão: \1 / \2"),
    (
        r"Unknown spatial type '(.*)'\. Must be 'tiles', 'bbox', or 'vector'\.",
        r"Tipo espacial '\1' desconhecido. Use 'tiles', 'bbox' ou 'vector'.",
    ),
    (r"Valid query specification \(Collection: (.+)\)", r"Consulta válida (coleção: \1)"),
    (r"JSON/YAML syntax error on line (\d+): (.+)", r"Erro de sintaxe JSON/YAML na linha \1: \2"),
    (r"JSON syntax error on line (\d+): (.+)", r"Erro de sintaxe JSON na linha \1: \2"),
    (r"Decoding error: ((?s:.+))", r"Erro de decodificação: \1"),
    (
        r"The query period, (\S+) to (\S+), goes beyond the dates of this collection; it was set to (\S+) to (\S+)\.",
        r"O período da consulta, \1 a \2, passa das datas desta coleção; ele ficou de \3 a \4.",
    ),
    (
        r"Tiles with invalid format: (.+)\. Use BDC \(031023\), MGRS \(23LMF\), WRS2 \(233067\), STG \(h13v10\) or "
        r"Row/Path \(039/018\)\.",
        r"Tiles em formato inválido: \1. Use BDC (031023), MGRS (23LMF), WRS2 (233067), STG (h13v10) ou "
        r"linha/órbita (039/018).",
    ),
    (r"Search parameters changed \((.+)\)\. Click Search STAC again\.", _params_changed),
    (r"Error: ((?s:.+))", r"Erro: \1"),
    (r"Invalid WKT: (.+)", r"WKT inválido: \1"),
    (r"Custom \((.+)\)", r"Personalizada (\1)"),
    (r"Bands: (.+)", r"Bandas: \1"),
    (r"Auto \((.+)\)", r"Automático (\1)"),
    (r"Page (\d+) of (\d+)", r"Página \1 de \2"),
    (r"Saved in:\n(.+)", r"Salvo em:\n\1"),
]

# Process messages of the status line and the QGIS message bar (see "Messages" in docs/CONTRIBUTING.md).
_MESSAGES = {
    # Search
    "Searching images (STAC)...": "Buscando imagens (STAC)...",
    "Searching scenes that cross the vector features (STAC)...": "Buscando cenas que cruzam as feições (STAC)...",
    "Searching scenes for the crops (STAC)...": "Buscando cenas para os recortes (STAC)...",
    "Searching images downloaded on this computer...": "Buscando imagens baixadas neste computador...",
    "This collection has no tiles: the tile filter is ignored, the extent is used.": "Esta coleção não tem tiles: "
    "o filtro de tiles é ignorado e vale a extensão.",
    "The BDC cannot be reached. Searching the images downloaded on this computer.": "O BDC não responde. Buscando "
    "as imagens baixadas neste computador.",
    "The filters hide the only image found. Click Reset to show it.": "Os filtros escondem a única imagem "
    "encontrada. Clique em Restaurar para mostrá-la.",
    "Image list cleared.": "Lista de imagens limpa.",
    # Grid
    "Click a tile on the map, or press Esc to cancel.": "Clique num tile no mapa ou tecle Esc para cancelar.",
    # Load layers
    "Loading cancelled. For this collection, download the images instead.": "Carregamento cancelado. Para esta "
    "coleção, baixe as imagens.",
    "Cancelling layer loading...": "Cancelando o carregamento das camadas...",
    # Main window
    "Invalid bbox: type xmin,ymin,xmax,ymax.": "Bbox inválido: digite xmin,ymin,xmax,ymax.",
    "Invalid bbox: the minimum must be less than the maximum.": "Bbox inválido: o mínimo deve ser menor que o máximo.",
    "Invalid bbox: use numbers, for example -65.31,-11.94,-62.97,-9.73.": "Bbox inválido: use números, por exemplo "
    "-65.31,-11.94,-62.97,-9.73.",
    "Bbox copied to the clipboard.": "Bbox copiado.",
    # Time series
    "No collection available. Check the connection and restart the plugin.": "Nenhuma coleção disponível. Confira "
    "a conexão e reinicie o plugin.",
    "No collection available: the list bundled with the plugin could not be read.": "Nenhuma coleção disponível: "
    "não foi possível ler a lista que vem com o plugin.",
    "The point is already extracted.": "O ponto já foi extraído.",
    "Time series extraction cancelled.": "Extração da série temporal cancelada.",
    "Cancelling time series extraction...": "Cancelando a extração da série temporal...",
    "No images found for the point in this period.": "Nenhuma imagem encontrada para o ponto neste período.",
    "No images found for the points in this period.": "Nenhuma imagem encontrada para os pontos neste período.",
    "Time series extraction complete.": "Extração da série temporal concluída.",
    "History settings saved.": "Configurações do histórico salvas.",
    "History cleared.": "Histórico limpo.",
    "Click a point on the map, or press Esc to stop the picker.": "Clique num ponto no mapa ou tecle Esc para parar "
    "o seletor.",
    "Picker stopped.": "Seletor parado.",
    "Enter Lon and Lat before copying.": "Digite Lon e Lat antes de copiar.",
    "Points cleared.": "Pontos removidos.",
}

_MESSAGE_PATTERNS = [
    # Failures of every process
    (
        r"(Search|Download|Grid download|Time series extraction|Loading collections|Loading layers|"
        r"Opening the image of \S+) failed: ((?s:.+))\.",
        _failed,
    ),
    # Search
    (
        r"Searching images \(STAC\): (\d+) found",
        lambda m: f"Buscando imagens (STAC): {_n(m[1], 'encontrada', 'encontradas')}",
    ),
    (r"Listing (\d+) images?\.\.\.", lambda m: f"Listando {_n(m[1], 'imagem', 'imagens')}..."),
    (
        r"Listing (\d+) dates? of (\d+) scenes?\.\.\.",
        lambda m: f"Listando {_n(m[1], 'data', 'datas')} de {_n(m[2], 'cena', 'cenas')}...",
    ),
    (r"(\d+) images? found\.", lambda m: _n(m[1], "imagem encontrada.", "imagens encontradas.")),
    (
        r"(\d+) scenes? grouped into (\d+) dates?\.",
        lambda m: f"{_n(m[1], 'cena agrupada', 'cenas agrupadas')} em {_n(m[2], 'data', 'datas')}.",
    ),
    (
        r"The filters hide all (\d+) images found\. Click Reset to show them\.",
        r"Os filtros escondem as \1 imagens encontradas. Clique em Restaurar para mostrá-las.",
    ),
    (r"(\d+) of (\d+) images shown by the filters\.", r"\1 de \2 imagens exibidas pelos filtros."),
    (
        r"Crop with tile filter: the search returns only scenes of tiles (.+) inside the extent\.",
        r"Recorte com filtro de tiles: a busca só traz cenas dos tiles \1 dentro da extensão.",
    ),
    (
        r"<b>Offline:</b> (\d+) downloaded images? found on this computer\. Layers load from disk; searching the BDC "
        r"resumes when it can be reached\.",
        lambda m: (
            f"<b>Offline:</b> {_n(m[1], 'imagem baixada encontrada', 'imagens baixadas encontradas')} neste "
            "computador. As camadas carregam do disco; a busca no BDC volta quando ele responder."
        ),
    ),
    (
        r"<b>Offline:</b> no downloaded image of (\S+) matches this period and area\. This computer holds (\d+) "
        r"downloaded images? of this collection and (\d+) in total\.",
        lambda m: (
            f"<b>Offline:</b> nenhuma imagem baixada de {m[1]} combina com este período e esta área. Este "
            f"computador tem {_n(m[2], 'imagem baixada', 'imagens baixadas')} desta coleção e {m[3]} no total."
        ),
    ),
    (
        r"No images found\. (\S+) has images from (\S+) to (\S+); choose a period inside it\.",
        r"Nenhuma imagem encontrada. \1 tem imagens de \2 a \3; escolha um período dentro dele.",
    ),
    (
        r"No images found\. (\d+) scenes? covers? the box around the vector features, but none crosses the checked "
        r"features\.",
        lambda m: (
            f"Nenhuma imagem encontrada. {_n(m[1], 'cena cobre', 'cenas cobrem')} o retângulo em volta das "
            "feições, mas nenhuma cruza as feições marcadas."
        ),
    ),
    (
        r"No images found in tiles (.+) from (\S+) to (\S+)\. Check that they belong to the (\S+) grid of (\S+)\.",
        r"Nenhuma imagem encontrada nos tiles \1 de \2 a \3. Confira se eles são da grade \4 de \5.",
    ),
    (
        r"No images found over this area from (\S+) to (\S+)\. It may be outside the coverage of (\S+); try a longer "
        r"period or another area\.",
        r"Nenhuma imagem encontrada nesta área de \1 a \2. Ela pode estar fora da cobertura de \3; tente um período "
        r"maior ou outra área.",
    ),
    (r"No images found from (\S+) to (\S+)\.", r"Nenhuma imagem encontrada de \1 a \2."),
    # Download
    (r"Image already downloaded: (.+)\.", r"Imagem já baixada: \1."),
    (r"Download folder saved in the settings: (.+)\.", r"Pasta de downloads salva nas configurações: \1."),
    (
        r"Estimating the size of (\d+) files?\.\.\.",
        lambda m: f"Estimando o tamanho de {_n(m[1], 'arquivo', 'arquivos')}...",
    ),
    (r"Download complete: (.+)\.", r"Download concluído: \1."),
    (
        r"Download complete, but (.+) has no valid pixel in this area \(the image covers it only with its empty "
        r"border, or has no data there\): ((?s:.+))\.",
        r"Download concluído, mas \1 não tem pixel válido nesta área (a imagem a cobre só com a borda vazia, ou não "
        r"tem dado nela): \2.",
    ),
    (
        r"(?:Download cancelled: (\d+) of (\d+) images? processed, )?(\d+) images? downloaded((?:, .+)?)\.",
        _download_summary,
    ),
    (r"Download cancelled: (.+)\.", r"Download cancelado: \1."),
    (
        r"(.*?)Preparing to download (\d+) bands? of (.+)\.\.\.",
        lambda m: f"{m[1]}Preparando o download de {_n(m[2], 'banda', 'bandas')} de {m[3]}...",
    ),
    (
        r"(.*?)Preparing to download (\d+) tile files? of (.+)\.\.\.",
        lambda m: f"{m[1]}Preparando o download de {_n(m[2], 'arquivo de tile', 'arquivos de tile')} de {m[3]}...",
    ),
    (
        r"(.*?)Reading (\S+) directly from the BDC \(the area covers ~(\d+)% of the largest tile\)\.\.\.",
        r"\1Lendo \2 direto do BDC (a área cobre ~\3% do maior tile)...",
    ),
    (r"((?:\[\d+/\d+\] )?)Downloading (\S+)\.\.\.", r"\1Baixando \2..."),
    (r"((?:\[\d+/\d+\] )?)Writing (.+): (\d+)%", r"\1Gravando \2: \3%"),
    (r"((?:\[\d+/\d+\] )?)Writing (.+): (\d+) s", r"\1Gravando \2: \3 s"),
    (r"((?:\[\d+/\d+\] )?)Downloading the area blocks of (.+?): (.+)", r"\1Baixando os blocos da área de \2: \3"),
    (r"((?:\[\d+/\d+\] )?)Downloading (.+?): (.+)", _downloading),
    # Grid
    (r"Grid (\S+) downloaded\.", r"Grade \1 baixada."),
    (r"Loading grid (\S+) from the BDC \(WFS\)\.\.\.", r"Carregando a grade \1 do BDC (WFS)..."),
    (r"Grid (\S+) added to the map\.", r"Grade \1 adicionada ao mapa."),
    (
        r"Grid (\S+) added to the map\. Draw on Canvas is ready\.",
        r"Grade \1 adicionada ao mapa. Desenhar no mapa está pronto.",
    ),
    (
        r"Grid loading failed: (\S+) could not be read from the BDC\.",
        r"Falha ao carregar a grade: não foi possível ler \1 do BDC.",
    ),
    (r"(\d+) tiles? copied to the clipboard\.", lambda m: _n(m[1], "tile copiado.", "tiles copiados.")),
    (
        r"The BDC is back online \((\d+) ms\)\. Collections updated\.",
        r"O BDC voltou a responder (\1 ms). Coleções atualizadas.",
    ),
    # Load layers
    (
        r"Preparing layers: (\d+)/(\d+) \((\d+) s, ~(.+) s per layer, ~(\d+) s left\)",
        r"Preparando as camadas: \1/\2 (\3 s, ~\4 s por camada, faltam ~\5 s)",
    ),
    (r"Reading image headers from the BDC: (\d+) s", r"Lendo os cabeçalhos das imagens no BDC: \1 s"),
    (
        r"Preparing (\d+) crops? \((\d+) in parallel\)\.\.\.",
        lambda m: f"Preparando {_n(m[1], 'recorte', 'recortes')} ({m[2]} em paralelo)...",
    ),
    (
        r"Preparing (\d+) layers? \((\d+) in parallel\)\.\.\.",
        lambda m: f"Preparando {_n(m[1], 'camada', 'camadas')} ({m[2]} em paralelo)...",
    ),
    (
        r"Loading cancelled: (\d+) of (\d+) layers? ready \((.+) s\)\. Adding them to the map\.\.\.",
        lambda m: (
            f"Carregamento cancelado: {m[1]} de {_n(m[2], 'camada pronta', 'camadas prontas')} ({m[3]} s). "
            "Adicionando-as ao mapa..."
        ),
    ),
    (
        r"(\d+) layers? already up to date; skipped\.",
        lambda m: _n(m[1], "camada já atualizada; ignorada.", "camadas já atualizadas; ignoradas."),
    ),
    (r"Adding (\d+) layers? to the map\.\.\.", lambda m: f"Adicionando {_n(m[1], 'camada', 'camadas')} ao mapa..."),
    (
        r"Preparing layers for display \((overview and contrast|contrast)\): (\d+)/(\d+) \((\d+) s\)"
        r"(, waiting for the BDC server)?",
        _display_progress,
    ),
    (
        r"(\d+) of (\d+) overviews? could not be created; those layers draw directly from the BDC\.",
        lambda m: (
            f"{m[1]} de {_n(m[2], 'overview', 'overviews')} "
            f"{'não pôde ser criada' if m[1] == '1' else 'não puderam ser criadas'}; essas camadas são desenhadas direto "
            "do BDC."
        ),
    ),
    (
        r"(\d+) of (\d+) layers? not cloud-optimized: no overview or contrast was prepared, and drawing reads each full "
        r"image from the BDC\. Download these images for fast local layers\.",
        lambda m: (
            f"{m[1]} de {_n(m[2], 'camada', 'camadas')} sem otimização para nuvem: nenhuma overview ou contraste "
            "foi preparado, e o desenho lê cada imagem inteira do BDC. Baixe essas imagens para ter camadas locais rápidas."
        ),
    ),
    (
        r"Preparing (\d+) of (\d+) layers? for display took over (\d+) s; they load without overview or contrast\.",
        lambda m: (
            f"Preparar {m[1]} de {_n(m[2], 'camada', 'camadas')} para exibição levou mais de {m[3]} s; elas "
            "carregam sem overview nem contraste."
        ),
    ),
    (r"(Loading cancelled: )?(\d+) layers? added to the map(, turned off)? \((.+?)\)\.((?: .+\.)?)", _load_report),
    (
        r"(\d+) layers? already loaded and up to date\.",
        lambda m: _n(m[1], "camada já carregada e atualizada.", "camadas já carregadas e atualizadas."),
    ),
    (
        r"(\d+) of (\d+) layers? (?:has|have) no valid pixel in this area \(the image covers it only with its empty "
        r"border, or the area has no data\): (.+)\.",
        _empty_layers,
    ),
    (
        r"Generated files take (\d+) MB of disk\. To free space, open the Storage tab in Settings\.",
        r"Os arquivos gerados ocupam \1 MB. Para liberar espaço, abra a aba Armazenamento em Configurações.",
    ),
    # Time series
    (r"(\d+) collections? loaded\.", lambda m: _n(m[1], "coleção carregada.", "coleções carregadas.")),
    (
        r"(\d+) collections? loaded \(offline\)\.",
        lambda m: _n(m[1], "coleção carregada (offline).", "coleções carregadas (offline)."),
    ),
    (
        r"Searching images for (\d+) points? \(STAC\)\.\.\.",
        lambda m: f"Buscando imagens de {_n(m[1], 'ponto', 'pontos')} (STAC)...",
    ),
    (
        r"Extracting time series \(STAC\): (\d+)/(\d+) files of (\d+) images?, (\d+) points?",
        lambda m: (
            f"Extraindo a série temporal (STAC): {m[1]}/{m[2]} arquivos de {_n(m[3], 'imagem', 'imagens')}, "
            f"{_n(m[4], 'ponto', 'pontos')}"
        ),
    ),
    (r"All (\d+) points are already extracted\.", r"Os \1 pontos já foram extraídos."),
    (r"Extracting time series \(((?:\d+ points? (?:already extracted|with new bands)(?:, )?)+)\)\.\.\.", _reuse),
    (
        r"Extracting time series of (\d+) points? \(WTSS\)\.\.\.",
        lambda m: f"Extraindo a série temporal de {_n(m[1], 'ponto', 'pontos')} (WTSS)...",
    ),
    (r"Extracting time series \(WTSS\): (\d+)/(\d+)", r"Extraindo a série temporal (WTSS): \1/\2"),
    (r"Extracting (.+) \(STAC\), not served by WTSS\.\.\.", r"Extraindo \1 (STAC), que o WTSS não fornece..."),
    (
        r"(\d+) values? extracted(?:: (.+?))?\.(?: (\d+) pixel reads? failed after a retry; the series has gaps\.)?",
        _extracted,
    ),
    (
        r"Extracting (\d+) bands? of the time series \((\S+)\): (.+)",
        lambda m: f"Extraindo {_n(m[1], 'banda', 'bandas')} da série temporal ({m[2]}): {m[3]}",
    ),
    (r"No images found for (.+) at this point\.", r"Nenhuma imagem encontrada para \1 neste ponto."),
    (
        r"(\d+) bands? extracted, (\d+) bands? without data: (.+)\.",
        lambda m: f"{_n(m[1], 'banda extraída', 'bandas extraídas')}, {_n(m[2], 'banda', 'bandas')} sem dados: {m[3]}.",
    ),
    (r"(\d+) bands? extracted\.", lambda m: _n(m[1], "banda extraída.", "bandas extraídas.")),
    (r"(\d+) bands? without data: (.+)\.", lambda m: f"{_n(m[1], 'banda', 'bandas')} sem dados: {m[2]}."),
    (
        r"Point #(\d+) removed; the history has (\d+) points?\.",
        lambda m: f"Ponto #{m[1]} removido; o histórico tem {_n(m[2], 'ponto', 'pontos')}.",
    ),
    (r"(\d+) points? to extract\.", lambda m: f"{_n(m[1], 'ponto', 'pontos')} a extrair."),
    (
        r"Picker stopped: (\d+) points? to extract\.",
        lambda m: f"Seletor parado: {_n(m[1], 'ponto', 'pontos')} a extrair.",
    ),
    (r"(\d+) points? loaded from (.+)\.", lambda m: f"{_n(m[1], 'ponto carregado', 'pontos carregados')} de {m[2]}."),
    (r"Duplicate point skipped: \((.+)\)\.", r"Ponto repetido ignorado: (\1)."),
    # Chart image
    (r"Opening the image of (\S+)\.\.\.", r"Abrindo a imagem de \1..."),
    (r"No image found for (\S+)\.", r"Nenhuma imagem encontrada para \1."),
    (r"Band (\S+) is not available\.", r"A banda \1 não está disponível."),
    (r"Layer (.+) added to the map\.", r"Camada \1 adicionada ao mapa."),
    (r"Layer (.+) shown on the map\.", r"Camada \1 exibida no mapa."),
    (r"CSV file exported: (.+)\.", r"Arquivo CSV exportado: \1."),
    (
        r"(\d+) features? exported to GeoPackage\.",
        lambda m: _n(m[1], "feição exportada", "feições exportadas") + " para GeoPackage.",
    ),
]

TEXTS = {**_UI, **_DIALOGS, **_MORE, **_DOCS, **_TOUR, **_STATUS, **_MESSAGES}

# (regular expression on the English text, replacement) for texts built at run time.
PATTERNS = [*_UI_PATTERNS, *_DIALOG_PATTERNS, *_TOUR_PATTERNS, *_MESSAGE_PATTERNS, *_STATUS_PATTERNS]
