import folium
from streamlit_folium import folium_static
import streamlit as st
from folium.plugins import MarkerCluster
from branca.element import Figure, MacroElement
from jinja2 import Template
import random
import hashlib
import polyline
import logging
import requests
import os
import json
import time

def get_vehicle_type(vehicle_model):
    """
    Determina o tipo de veículo com base no modelo.
    
    Args:
        vehicle_model: String com o modelo do veículo
        
    Returns:
        String representando o tipo de veículo para a API de rotas
    """
    vehicle_model = vehicle_model.lower() if vehicle_model else ""
    
    # Detectar tipo de veículo com base em palavras-chave no modelo
    if any(keyword in vehicle_model for keyword in ["ônibus", "onibus", "bus"]):
        return "bus"
    elif any(keyword in vehicle_model for keyword in ["van", "sprint", "ducato", "boxer", "kombi"]):
        return "van"
    elif any(keyword in vehicle_model for keyword in ["caminhão", "caminhao", "truck"]):
        return "truck"
    elif any(keyword in vehicle_model for keyword in ["moto", "bike", "motorcycle"]):
        return "motorcycle"
    else:
        return "car"  # Tipo padrão

# Paleta de cores distintas para melhor diferenciação das rotas
DISTINCT_COLORS = [
    '#3366CC', '#DC3912', '#FF9900', '#109618', '#990099', 
    '#0099C6', '#DD4477', '#66AA00', '#B82E2E', '#316395', 
    '#994499', '#22AA99', '#AAAA11', '#6633CC', '#E67300', 
    '#8B0707', '#329262', '#5574A6', '#FF6347', '#4B0082'
]

# Estilos de linha para melhor diferenciação visual
LINE_STYLES = [
    {'weight': 4, 'opacity': 0.8, 'dashArray': None},     # Linha sólida
    {'weight': 4, 'opacity': 0.8, 'dashArray': '10, 10'}, # Linha tracejada
    {'weight': 4, 'opacity': 0.8, 'dashArray': '1, 10'},  # Linha pontilhada
    {'weight': 4, 'opacity': 0.8, 'dashArray': '15, 10, 1, 10'} # Traço-ponto
]

def get_color_for_route(index, route_id=None):
    """
    Obtém uma cor distinta para uma rota baseada no índice ou ID
    
    Args:
        index: Índice da rota na lista
        route_id: ID da rota (opcional, para consistência entre carregamentos)
    
    Returns:
        String com código de cor hex
    """
    # Se temos um route_id, usá-lo para gerar uma cor consistente
    if route_id:
        # Converter route_id para um índice estável na paleta de cores
        hash_val = int(hashlib.md5(str(route_id).encode()).hexdigest(), 16)
        color_idx = hash_val % len(DISTINCT_COLORS)
        return DISTINCT_COLORS[color_idx]
    
    # Caso contrário, usar o índice na lista de cores
    return DISTINCT_COLORS[index % len(DISTINCT_COLORS)]

def get_line_style(index):
    """Obtém um estilo de linha baseado no índice"""
    return LINE_STYLES[index % len(LINE_STYLES)]

def get_route_geometry(start_point, end_point, waypoints, vehicle_type="car"):
    """
    Obtém geometria real de rota da API Geoapify, garantindo que o trajeto siga ruas reais
    
    Args:
        start_point: Ponto de partida {lat, lon}
        end_point: Ponto de chegada {lat, lon}
        waypoints: Lista de waypoints intermediários [{lat, lon}, ...]
        vehicle_type: Tipo de veículo (car, bus, etc.)
        
    Returns:
        Dados da rota com coordenadas ou None se ocorrer um erro
    """
    # Verificar se temos a API key
    API_KEY = os.environ.get("GEOAPIFY_API_KEY", "")
    if not API_KEY:
        logging.warning("API key Geoapify não encontrada no ambiente. Trajeto seguirá linha reta.")
        st.warning("API key não configurada. Configure a variável de ambiente GEOAPIFY_API_KEY para obter rotas reais.")
        return None

    # Mapeia tipos de veículos para modos de viagem da API
    vehicle_to_mode = {
        "car": "drive",
        "bus": "drive",
        "van": "drive", 
        "truck": "truck",
        "motorcycle": "motorcycle"
    }
    travel_mode = vehicle_to_mode.get(vehicle_type.lower(), "drive")
    
    # Verificar pontos de entrada
    if not isinstance(start_point, dict) or not isinstance(end_point, dict):
        logging.error("Pontos de início ou fim inválidos")
        return None
        
    if 'lat' not in start_point or 'lon' not in start_point or 'lat' not in end_point or 'lon' not in end_point:
        logging.error("Pontos de início ou fim sem coordenadas lat/lon")
        return None
    
    # Processar waypoints - verificar e filtrar
    valid_waypoints = []
    if waypoints:
        for wp in waypoints:
            if isinstance(wp, dict) and 'lat' in wp and 'lon' in wp and wp['lat'] and wp['lon']:
                valid_waypoints.append(wp)
    
    # Construir a string de waypoints: início, intermediários e fim
    all_points = [start_point] + valid_waypoints + [end_point]
    waypoint_str = "|".join([f"{point['lat']},{point['lon']}" for point in all_points])
    
    # Construir URL e parâmetros para a API
    url = "https://api.geoapify.com/v1/routing"
    params = {
        "waypoints": waypoint_str,
        "mode": travel_mode,
        "details": "instruction_details,route_details",
        "apiKey": API_KEY
    }
    
    try:
        st.info(f"Solicitando rota real da API Geoapify com {len(valid_waypoints)} paradas intermediárias...")
        
        # Fazer a chamada API com retry embutido
        max_retries = 3
        retry_delay = 2  # segundos
        
        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                
                # Verificar se a resposta contém dados úteis
                if 'features' in data and len(data['features']) > 0:
                    feature = data['features'][0]
                    
                    # Verificar se há geometria na resposta
                    if 'geometry' in feature:
                        logging.info(f"Rota com ruas reais obtida com sucesso: {len(feature['geometry'].get('coordinates', [])) if feature['geometry'].get('type') == 'LineString' else 'MultiLineString'} pontos")
                        return data  # Retornar o objeto completo para mais flexibilidade
                    else:
                        logging.error("Resposta da API não contém geometria")
                else:
                    logging.error(f"Resposta da API sem features: {data.get('message', 'Sem mensagem')}")
                
                break  # Se chegou aqui sem exceções, sai do loop
                
            except requests.exceptions.Timeout:
                logging.warning(f"Timeout na tentativa {attempt+1}/{max_retries}")
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    
            except requests.exceptions.HTTPError as e:
                # Não faz retry para erros HTTP que não são de conexão
                logging.error(f"Erro HTTP na API de routing: {e}")
                break
                
            except Exception as e:
                logging.error(f"Erro inesperado na chamada à API: {e}")
                break
                
        return None  # Se chegou aqui, não conseguiu obter dados válidos
        
    except Exception as e:
        logging.error(f"Erro ao obter geometria da rota: {str(e)}")
        return None

def display_route_on_map(route_data, start_coord, end_coord, waypoints, color='blue'):
    """
    Exibe uma rota calculada em um mapa Folium, priorizando trajetos reais em ruas
    
    Args:
        route_data: Dados da rota retornados pela API
        start_coord: Coordenadas do ponto de partida
        end_coord: Coordenadas do ponto de chegada  
        waypoints: Lista de waypoints da rota
        color: Cor da linha da rota
    """
    # Create a folium map centered on the route area
    center_lat = (start_coord['lat'] + end_coord['lat']) / 2
    center_lon = (start_coord['lon'] + end_coord['lon']) / 2
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=13)
    
    # Add start marker com ícone e tooltip melhorados
    folium.Marker(
        location=[start_coord['lat'], start_coord['lon']],
        popup=folium.Popup("<b>Ponto de Partida</b><br>Garagem/Origem", max_width=300),
        icon=folium.Icon(color='green', icon='flag', prefix='fa'),
        tooltip="Ponto de Partida (Origem)"
    ).add_to(m)
    
    # Add end marker com ícone e tooltip melhorados
    folium.Marker(
        location=[end_coord['lat'], end_coord['lon']],
        popup=folium.Popup("<b>Ponto de Chegada</b><br>Empresa/Destino", max_width=300),
        icon=folium.Icon(color='red', icon='flag-checkered', prefix='fa'),
        tooltip="Ponto de Chegada (Destino)"
    ).add_to(m)
    
    # Use MarkerCluster for waypoints if there are many of them
    if len(waypoints) > 10:
        marker_cluster = MarkerCluster(name="Paradas").add_to(m)
        target_group = marker_cluster
    else:
        target_group = m
    
    # Add waypoint markers
    for i, wp in enumerate(waypoints):
        popup_content = f"""
        <div style="font-family: Arial; width: 200px;">
            <h4>Parada {i+1}</h4>
            <b>Passageiro:</b> {wp.get('name', 'Não informado')}<br>
            <b>ID:</b> {wp.get('person_id', 'N/A')}
        </div>
        """
        
        folium.Marker(
            location=[wp['lat'], wp['lon']],
            popup=folium.Popup(popup_content, max_width=300),
            icon=folium.Icon(color=color, icon='user', prefix='fa'),
            tooltip=f"Parada {i+1}: {wp.get('name', 'Passageiro')}"
        ).add_to(target_group)
    
    # MUDANÇA IMPORTANTE: Primeiro buscar rota real da API para garantir trajeto em ruas
    # mesmo que já tenhamos alguns dados no route_data
    line_added = False
    
    # NOVO: Agora chamamos a API primeiro para priorizar rotas reais em ruas
    try:
        # Obter geometria real de rota com a função melhorada
        vehicle_type = route_data.get('vehicle_type', 'car')
        api_route_data = get_route_geometry(start_coord, end_coord, waypoints, vehicle_type)
        
        if api_route_data and 'features' in api_route_data and len(api_route_data['features']) > 0:
            feature = api_route_data['features'][0]
            
            if 'geometry' in feature:
                geom = feature['geometry']
                if geom['type'] == 'LineString':
                    # Get coordinates from LineString (they're in lon, lat order in GeoJSON)
                    line_coords = [(coord[1], coord[0]) for coord in geom['coordinates']]
                    
                    # Obter métricas da rota
                    distance = api_route_data.get('distance', 0)
                    if 'properties' in feature:
                        distance = feature['properties'].get('distance', distance) / 1000
                        
                    duration = api_route_data.get('time', 0)
                    if 'properties' in feature:
                        duration = feature['properties'].get('time', duration) / 60
                    
                    # Add the line to the map with the specified color
                    route_line = folium.PolyLine(
                        line_coords,
                        color=color,
                        weight=5,  # Linha mais grossa
                        opacity=0.8,
                        tooltip=f"Trajeto em ruas reais | Distância: {distance:.1f}km | Tempo: {duration:.0f}min",
                        popup=f"Distância: {distance:.1f}km | Tempo estimado: {duration:.0f}min"
                    ).add_to(m)
                    line_added = True
                    st.success("✅ Trajeto em ruas reais obtido com sucesso!")
                
                elif geom['type'] == 'MultiLineString':
                    # Processar cada segmento do MultiLineString
                    for line_segment in geom['coordinates']:
                        line_coords = [(coord[1], coord[0]) for coord in line_segment]
                        folium.PolyLine(
                            line_coords,
                            color=color,
                            weight=5,
                            opacity=0.8
                        ).add_to(m)
                    line_added = True
                    st.success("✅ Trajeto em ruas reais obtido com sucesso!")
    except Exception as e:
        st.error(f"Erro ao buscar trajeto em ruas reais: {e}")
        logging.exception("Erro ao buscar trajeto em ruas reais")
    
    # Se não conseguiu obter rota real da API, tentar extrair do route_data existente
    if not line_added and 'features' in route_data:
        for feature in route_data['features']:
            if 'geometry' in feature and feature['geometry'].get('type') in ['LineString', 'MultiLineString']:
                try:
                    if feature['geometry']['type'] == 'LineString':
                        # Get coordinates from LineString (they're in lon, lat order in GeoJSON)
                        line_coords = [(coord[1], coord[0]) for coord in feature['geometry']['coordinates']]
                        
                        # Obter métricas da rota
                        distance = route_data.get('total_distance_km', 0)
                        if distance == 0 and 'properties' in feature:
                            distance = feature['properties'].get('distance', 0) / 1000
                            
                        duration = route_data.get('total_duration_minutes', 0)
                        if duration == 0 and 'properties' in feature:
                            duration = feature['properties'].get('time', 0) / 60
                        
                        # Add the line to the map with the specified color
                        route_line = folium.PolyLine(
                            line_coords,
                            color=color,
                            weight=4,
                            opacity=0.7,
                            tooltip=f"Distância: {distance:.1f}km | Tempo: {duration:.0f}min",
                            popup=f"Distância: {distance:.1f}km | Tempo estimado: {duration:.0f}min"
                        ).add_to(m)
                        line_added = True
                    
                    elif feature['geometry']['type'] == 'MultiLineString':
                        # Processar cada segmento do MultiLineString
                        for line_segment in feature['geometry']['coordinates']:
                            line_coords = [(coord[1], coord[0]) for coord in line_segment]
                            folium.PolyLine(
                                line_coords,
                                color=color,
                                weight=4,
                                opacity=0.7
                            ).add_to(m)
                        line_added = True
                except Exception as e:
                    st.error(f"Erro ao processar geometria: {e}")
    
    # Outros métodos de fallback permanecem os mesmos
    # ...existing code...
    
    # 5. Último recurso: desenhar linhas retas apenas como fallback, com aviso claro
    if not line_added:
        try:
            all_points = []
            all_points.append([start_coord['lat'], start_coord['lon']])
            for wp in waypoints:
                all_points.append([wp['lat'], wp['lon']])
            all_points.append([end_coord['lat'], end_coord['lon']])
            
            # Adicionar linha simples conectando os pontos
            folium.PolyLine(
                all_points,
                color=color,
                weight=3,
                opacity=0.5,
                dashArray='5, 5',  # Linha tracejada para indicar que é uma estimativa
                tooltip="ATENÇÃO: Trajeto simplificado (não representa ruas reais)"
            ).add_to(m)
            
            # Adiciona um aviso claro no mapa
            warning_html = """
            <div style="position: fixed; bottom: 10px; left: 10px; z-index: 1000;
                 background-color: #ffcccc; padding: 10px; border-radius: 5px; 
                 border: 2px solid red; font-weight: bold; max-width: 300px;">
                 ⚠️ AVISO: Esta rota é uma aproximação em linha reta 
                 e NÃO representa o trajeto real em ruas!
            </div>
            """
            m.get_root().html.add_child(folium.Element(warning_html))
            
            line_added = True
            st.warning("⚠️ ATENÇÃO: Exibindo trajeto simplificado em linha reta - não representa o caminho real em ruas!")
        except Exception as e:
            st.error(f"Não foi possível renderizar nenhum trajeto: {e}")

    # Add fullscreen button
    folium.plugins.Fullscreen().add_to(m)
    
    # Add locate control
    folium.plugins.LocateControl().add_to(m)
    
    # Add measure tool
    folium.plugins.MeasureControl(position='topright', primary_length_unit='kilometers').add_to(m)
    
    # Display the map
    folium_static(m)

def display_route_map(route_data):
    """Display the route on a Folium map."""
    try:
        # Extrair coordenadas de pontos de partida, chegada e paradas
        if 'waypoints' in route_data:
            # Obter primeiro e último waypoint como pontos de partida e chegada
            waypoints = route_data['waypoints']
            if len(waypoints) >= 2:
                start_coord = {'lat': waypoints[0].get('location', [0, 0])[0], 
                              'lon': waypoints[0].get('location', [0, 0])[1]}
                end_coord = {'lat': waypoints[-1].get('location', [0, 0])[0], 
                            'lon': waypoints[-1].get('location', [0, 0])[1]}
                
                # Waypoints intermediários
                intermediate_waypoints = []
                for wp in waypoints[1:-1]:
                    if 'location' in wp:
                        intermediate_waypoints.append({
                            'lat': wp['location'][0],
                            'lon': wp['location'][1],
                            'name': wp.get('name', 'Parada')
                        })
                
                # Criar mapa
                center_lat = (start_coord['lat'] + end_coord['lat']) / 2
                center_lon = (start_coord['lon'] + end_coord['lon']) / 2
                
                m = folium.Map(location=[center_lat, center_lon], zoom_start=12)
                
                # Adicionar marcadores
                folium.Marker(
                    location=[start_coord['lat'], start_coord['lon']],
                    popup="Ponto de Partida",
                    icon=folium.Icon(color='green', icon='play', prefix='fa')
                ).add_to(m)
                
                folium.Marker(
                    location=[end_coord['lat'], end_coord['lon']],
                    popup="Ponto de Chegada",
                    icon=folium.Icon(color='red', icon='stop', prefix='fa')
                ).add_to(m)
                
                # Adicionar paradas intermediárias
                for i, wp in enumerate(intermediate_waypoints):
                    folium.Marker(
                        location=[wp['lat'], wp['lon']],
                        popup=f"Parada {i+1}: {wp.get('name', 'Passageiro')}",
                        icon=folium.Icon(color='blue', icon='user', prefix='fa')
                    ).add_to(m)
                
                # Adicionar linha da rota
                line_added = False
                
                # 1. Tentar extrair geometria de LineString/MultiLineString
                if 'geometry' in route_data:
                    try:
                        geom = route_data['geometry']
                        if geom['type'] == 'LineString':
                            line_coords = [(coord[1], coord[0]) for coord in geom['coordinates']]
                            folium.PolyLine(
                                line_coords,
                                color='blue',
                                weight=4,
                                opacity=0.8
                            ).add_to(m)
                            line_added = True
                        elif geom['type'] == 'MultiLineString':
                            for line_segment in geom['coordinates']:
                                line_coords = [(coord[1], coord[0]) for coord in line_segment]
                                folium.PolyLine(
                                    line_coords,
                                    color='blue',
                                    weight=4,
                                    opacity=0.8
                                ).add_to(m)
                            line_added = True
                    except Exception as e:
                        st.warning(f"Erro ao processar geometria: {e}")
                
                # 2. Se não conseguiu extrair da geometria, tentar obter rota real da API
                if not line_added:
                    try:
                        # Obter geometria real de rota da API
                        route_geom = get_route_geometry(
                            start_coord,
                            end_coord,
                            intermediate_waypoints,
                            "car"  # Valor padrão
                        )
                        
                        if route_geom:
                            if route_geom['type'] == 'LineString':
                                line_coords = [(coord[1], coord[0]) for coord in route_geom['coordinates']]
                                folium.PolyLine(
                                    line_coords,
                                    color='blue',
                                    weight=4,
                                    opacity=0.8,
                                    tooltip="Rota em ruas reais (obtida da API)"
                                ).add_to(m)
                                line_added = True
                            elif route_geom['type'] == 'MultiLineString':
                                for line_segment in route_geom['coordinates']:
                                    line_coords = [(coord[1], coord[0]) for coord in line_segment]
                                    folium.PolyLine(
                                        line_coords,
                                        color='blue',
                                        weight=4,
                                        opacity=0.8
                                    ).add_to(m)
                                line_added = True
                    except Exception as e:
                        st.warning(f"Erro ao obter rota da API: {e}")
                
                # 3. Último recurso: criar linha reta conectando os pontos (com aviso)
                if not line_added:
                    route_line = []
                    route_line.append([start_coord['lat'], start_coord['lon']])
                    for wp in intermediate_waypoints:
                        route_line.append([wp['lat'], wp['lon']])
                    route_line.append([end_coord['lat'], end_coord['lon']])
                    
                    folium.PolyLine(
                        route_line,
                        color='blue',
                        weight=3,
                        opacity=0.5,
                        dashArray='5, 5',  # Linha tracejada para indicar que é uma rota estimada
                        tooltip="ATENÇÃO: Trajeto estimado (não representa ruas reais)"
                    ).add_to(m)
                    
                    # Adiciona um aviso claro no mapa
                    warning_html = """
                    <div style="position: fixed; bottom: 10px; left: 10px; z-index: 1000;
                         background-color: #ffcccc; padding: 10px; border-radius: 5px; 
                         border: 2px solid red; font-weight: bold; max-width: 300px;">
                         ⚠️ AVISO: Esta rota é uma aproximação em linha reta 
                         e NÃO representa o trajeto real em ruas!
                    </div>
                    """
                    m.get_root().html.add_child(folium.Element(warning_html))
                    
                    st.warning("⚠️ ATENÇÃO: Exibindo trajeto simplificado que não representa o caminho real em ruas!")
                
                # Exibir mapa
                folium_static(m)
            else:
                st.warning("Dados insuficientes para exibir a rota no mapa.")
        else:
            # Tenta extrair informações do formato GeoJSON
            display_route_on_map(route_data, 
                                {'lat': 0, 'lon': 0},  # Serão ignorados se houver features no route_data
                                {'lat': 0, 'lon': 0}, 
                                [])
    except Exception as e:
        st.error(f"Erro ao exibir o mapa da rota: {str(e)}")

def display_multiple_routes_on_map(created_routes, start_coord, end_coord):
    """
    Display multiple routes on a single map with actual driving paths instead of straight lines.
    Each route is shown with a different color.
    
    Args:
        created_routes: List of route data objects
        start_coord: Starting coordinates
        end_coord: Ending coordinates
    """
    # Create a folium map centered on the route area
    center_lat = (start_coord['lat'] + end_coord['lat']) / 2
    center_lon = (start_coord['lon'] + end_coord['lon']) / 2
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=12)
    
    # Add markers for the common start and end points
    folium.Marker(
        location=[start_coord['lat'], start_coord['lon']],
        popup=folium.Popup("<b>Ponto de Partida</b><br>Garagem/Origem", max_width=300),
        icon=folium.Icon(color='green', icon='flag', prefix='fa'),
        tooltip="Ponto de Partida (Origem)"
    ).add_to(m)
    
    folium.Marker(
        location=[end_coord['lat'], end_coord['lon']],
        popup=folium.Popup("<b>Ponto de Chegada</b><br>Empresa/Destino", max_width=300),
        icon=folium.Icon(color='red', icon='flag-checkered', prefix='fa'),
        tooltip="Ponto de Chegada (Destino)"
    ).add_to(m)
    
    # Create a list of colors for routes
    colors = ['blue', 'red', 'green', 'purple', 'orange', 'darkred', 
              'darkblue', 'darkgreen', 'cadetblue', 'pink', 'lightblue',
              'lightgreen', 'gray', 'black', 'lightred', 'beige']
    
    # Show loading message for routes
    with st.spinner("Carregando rotas reais do serviço de mapeamento... Isso pode levar alguns segundos."):
        # Add each route to the map
        for i, route_info in enumerate(created_routes):
            color = route_info.get('color', colors[i % len(colors)])
            vehicle_info = f"{route_info['vehicle']['model']} ({route_info['vehicle']['license_plate']})"
            passengers_count = len(route_info['passengers'])
            vehicle_type = get_vehicle_type(route_info['vehicle']['model'])
            
            # Add waypoint markers for this route with matching color
            for j, passenger in enumerate(route_info['passengers']):
                popup_text = f"<b>Rota {i+1} - Parada {j+1}</b><br/>{passenger.get('name', 'Passageiro')}"
                
                # Convert line color to marker color
                marker_color = color
                if color in ['darkred', 'darkblue', 'darkgreen', 'cadetblue', 'lightred', 'lightblue', 'lightgreen']:
                    marker_color = color.replace('dark', '').replace('light', '').replace('cadet', '')
                
                folium.Marker(
                    location=[passenger['lat'], passenger['lon']],
                    popup=folium.Popup(popup_text, max_width=300),
                    icon=folium.Icon(color=marker_color, icon='user', prefix='fa'),
                    tooltip=f"Rota {i+1}: {passenger.get('name', 'Passageiro')}"
                ).add_to(m)
            
            # IMPORTANT: First attempt to get real route from Geoapify API regardless 
            # of what might be in route_data to ensure we show actual driving routes
            route_added = False
            
            # Get passenger waypoints
            waypoints = []
            for passenger in route_info['passengers']:
                waypoints.append({
                    'lat': passenger['lat'],
                    'lon': passenger['lon'],
                    'name': passenger.get('name', 'Passageiro')
                })
            
            # Get route from Geoapify
            try:
                api_route_data = get_route_geometry(
                    start_coord, 
                    end_coord, 
                    waypoints,
                    vehicle_type
                )
                
                if api_route_data and 'features' in api_route_data and len(api_route_data['features']) > 0:
                    feature = api_route_data['features'][0]
                    
                    if 'geometry' in feature:
                        geom = feature['geometry']
                        if geom['type'] == 'LineString':
                            # Get coordinates (convert from [lon, lat] to [lat, lon] for Folium)
                            line_coords = [(coord[1], coord[0]) for coord in geom['coordinates']]
                            
                            # Get route metrics if available
                            distance = 0
                            duration = 0
                            if 'properties' in feature:
                                props = feature['properties']
                                if 'distance' in props:
                                    distance = props['distance'] / 1000  # Convert to km
                                if 'time' in props:
                                    duration = props['time'] / 60  # Convert to minutes
                            
                            # Add the actual driving path with specified color
                            folium.PolyLine(
                                line_coords,
                                color=color,
                                weight=5,
                                opacity=0.8,
                                tooltip=f"Rota {i+1}: {vehicle_info} - {passengers_count} passageiros | Distância: {distance:.1f}km | Tempo: {duration:.0f}min"
                            ).add_to(m)
                            route_added = True
                            
                        elif geom['type'] == 'MultiLineString':
                            # Process each segment of the MultiLineString
                            for line_segment in geom['coordinates']:
                                line_coords = [(coord[1], coord[0]) for coord in line_segment]
                                folium.PolyLine(
                                    line_coords,
                                    color=color,
                                    weight=5,
                                    opacity=0.8
                                ).add_to(m)
                            route_added = True
            
            except Exception as e:
                logging.error(f"Erro ao obter rota real da API para rota {i+1}: {e}")
            
            # FALLBACK 1: Try existing route_data if API call failed
            if not route_added and 'route_data' in route_info:
                route_data = route_info['route_data']
                
                # Try to extract route geometry from different API response formats
                try:
                    # Check for 'features' with 'LineString' geometry
                    if 'features' in route_data:
                        for feature in route_data['features']:
                            if 'geometry' in feature and feature['geometry'].get('type') == 'LineString':
                                line_coords = [(coord[1], coord[0]) for coord in feature['geometry']['coordinates']]
                                folium.PolyLine(
                                    line_coords,
                                    color=color,
                                    weight=4,
                                    opacity=0.8,
                                    tooltip=f"Rota {i+1}: {vehicle_info} - {passengers_count} passageiros"
                                ).add_to(m)
                                route_added = True
                                break
                    
                    # Check for direct geometry
                    elif 'geometry' in route_data:
                        if route_data['geometry'].get('type') == 'LineString':
                            line_coords = [(coord[1], coord[0]) for coord in route_data['geometry']['coordinates']]
                            folium.PolyLine(
                                line_coords,
                                color=color,
                                weight=4,
                                opacity=0.8,
                                tooltip=f"Rota {i+1}: {vehicle_info} - {passengers_count} passageiros"
                            ).add_to(m)
                            route_added = True
                except Exception as e:
                    logging.error(f"Erro ao processar geometria da rota {i+1} de route_data: {e}")
            
            # FALLBACK 2: Only as last resort, use simplified straight lines if both API and route_data failed
            if not route_added:
                st.warning(f"⚠️ Não foi possível obter o trajeto real para a rota {i+1}. Exibindo versão simplificada.")
                simplified_coords = []
                simplified_coords.append([start_coord['lat'], start_coord['lon']])
                
                # Add passenger coordinates in order
                for passenger in route_info['passengers']:
                    simplified_coords.append([passenger['lat'], passenger['lon']])
                
                simplified_coords.append([end_coord['lat'], end_coord['lon']])
                
                folium.PolyLine(
                    simplified_coords,
                    color=color,
                    weight=3,
                    opacity=0.6,
                    tooltip=f"Rota {i+1}: {vehicle_info} - {passengers_count} passageiros (SIMPLIFICADA)",
                    dash_array="5, 10"  # Dashed line to indicate simplified route
                ).add_to(m)
    
    # Create a legend for the map
    legend_html = """
    <div style="position: fixed; bottom: 50px; left: 50px; z-index: 1000; background-color: white; padding: 10px; border: 2px solid grey; border-radius: 5px;">
    <h4>Legenda - Rotas</h4>
    """
    
    for i, route_info in enumerate(created_routes):
        color = route_info.get('color', colors[i % len(colors)])
        vehicle_info = f"{route_info['vehicle']['model']} ({route_info['vehicle']['license_plate']})"
        passengers_count = len(route_info['passengers'])
        legend_html += f"""
        <div>
            <span style="background-color:{color}; width:20px; height:10px; display:inline-block; margin-right:5px;"></span>
            <span>Rota {i+1}: {vehicle_info} ({passengers_count} passageiros)</span>
        </div>
        """
    
    legend_html += "</div>"
    m.get_root().html.add_child(folium.Element(legend_html))
    
    # Add fullscreen button and measure tool
    folium.plugins.Fullscreen().add_to(m)
    folium.plugins.MeasureControl(position='topright', primary_length_unit='kilometers').add_to(m)
    
    # Display the map
    folium_static(m)

def extract_route_coordinates(route_data):
    """
    Extract the route coordinates from API response in different formats
    Returns a list of [lat, lon] pairs that describe the route geometry
    """
    # Try different formats based on the API response structure
    
    # Format 1: GeoJSON with LineString features
    if 'features' in route_data:
        for feature in route_data['features']:
            if feature.get('geometry', {}).get('type') == 'LineString':
                coordinates = feature['geometry'].get('coordinates', [])
                # GeoJSON format is [lon, lat], but folium needs [lat, lon]
                return [[coord[1], coord[0]] for coord in coordinates]
    
    # Format 2: Direct geometry object with coordinates
    if 'geometry' in route_data and 'coordinates' in route_data['geometry']:
        coordinates = route_data['geometry']['coordinates']
        if isinstance(coordinates[0], list):
            return [[coord[1], coord[0]] for coord in coordinates]
    
    # Format 3: Paths array with points
    if 'paths' in route_data and len(route_data['paths']) > 0:
        path = route_data['paths'][0]
        if 'points' in path and 'coordinates' in path['points']:
            coordinates = path['points']['coordinates']
            return [[coord[1], coord[0]] for coord in coordinates]
    
    # Format 4: Direct points array
    if 'points' in route_data and 'coordinates' in route_data['points']:
        coordinates = route_data['points']['coordinates']
        return [[coord[1], coord[0]] for coord in coordinates]
    
    # Format 5: Segments with geometry
    if 'segments' in route_data:
        coordinates = []
        for segment in route_data['segments']:
            if 'geometry' in segment:
                points = decode_polyline(segment['geometry'])
                if points:
                    coordinates.extend(points)
        if coordinates:
            return coordinates
    
    return None

def decode_polyline(polyline_str):
    """
    Decode a polyline string into a list of coordinates.
    This is used for formats where the route is encoded as a string.
    """
    try:
        # Try to use polyline module if available
        import polyline
        return polyline.decode(polyline_str)
    except (ImportError, Exception):
        # Fallback to empty list if module is unavailable or decoding fails
        return []

class InteractiveRouteMap:
    """
    Classe para criar mapas interativos com rotas
    que permitem mostrar/ocultar rotas e visualizar métricas
    """
    def add_route(self, route_info, index):
        """
        Adiciona uma rota ao mapa
        
        Args:
            route_info: Dados da rota
            index: Índice da rota para cores/estilos
        """
        # ...implementação para adicionar rotas...
    
    def display(self):
        """Exibe o mapa finalizado"""
        folium.LayerControl().add_to(self.map)
        folium_static(self.fig)

# Adicionar função auxiliar para extrair coordenadas de rota de diferentes formatos de API
def extract_route_coordinates(route_data):
    """
    Extrai coordenadas do trajeto de diferentes formatos de resposta da API.
    
    Args:
        route_data: Dados da rota retornados pela API
        
    Returns:
        Lista de coordenadas [lat, lon] ou None se não for possível extrair
    """
    try:
        # Método 1: GeoJSON LineString/MultiLineString em features
        if 'features' in route_data:
            for feature in route_data['features']:
                if 'geometry' in feature:
                    geom = feature['geometry']
                    if geom['type'] == 'LineString':
                        # Converter de [lon, lat] para [lat, lon]
                        return [(coord[1], coord[0]) for coord in geom['coordinates']]
                    elif geom['type'] == 'MultiLineString':
                        # Juntar todos os segmentos em uma única lista
                        coords = []
                        for segment in geom['coordinates']:
                            coords.extend([(coord[1], coord[0]) for coord in segment])
                        return coords
        
        # Método 2: 'path' com lista de objetos {lat, lon}
        if 'path' in route_data and len(route_data['path']) > 0:
            return [(p['lat'], p['lon']) for p in route_data['path']]
        
        # Método 3: Polyline codificado
        if 'polyline' in route_data and route_data['polyline']:
            try:
                import polyline
                return polyline.decode(route_data['polyline'])
            except ImportError:
                pass
            
        return None
    except Exception as e:
        logging.error(f"Erro ao extrair coordenadas da rota: {e}")
        return None