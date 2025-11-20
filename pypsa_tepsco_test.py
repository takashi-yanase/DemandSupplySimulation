import time
import warnings 
import requests
from bs4 import BeautifulSoup
import pandas as pd

# 風力・太陽光発電設備のデータをスクレイピングして取得・保存
def scraping_data(network):
    
    url = "https://energy-sustainability.jp/maps/plant/"
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    # 風力・太陽光発電設備のデータを抽出
    # (実際の構造に応じてセレクタを調整)
    plants = []
    for item in soup.select('.plant-item'):
        plant_type = item.select_one('.type').text
        if plant_type in ['風力', '太陽光']:
            plants.append({
                'name': item.select_one('.name').text,
                'type': plant_type,
                'location': item.select_one('.location').text,
                'capacity': item.select_one('.capacity').text
            })

    # DataFrameに変換
    df = pd.DataFrame(plants)
    df.to_csv('renewable_plants.csv', index=False)
