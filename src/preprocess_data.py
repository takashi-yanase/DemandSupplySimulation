##　TEST

import os, pandas as pd, time
from IPython.display import clear_output, display
from concurrent.futures import ThreadPoolExecutor
import warnings, requests, re, shutil
import matplotlib.pyplot as plt

# 需要データの読み込み
def import_demand_data_from_network_file(network, network_file_name, demand_change_compared_to_2024):
    demand_data_raw = pd.read_excel(network_file_name, sheet_name='Demand', index_col=0, parse_dates=True)

    # demand_data_rawに格納されたデータをnetwork.loads_t.p_setに適用
    for load in network.loads.index:
        if load in demand_data_raw.columns:
            network.loads_t.p_set[load] = demand_data_raw[load] * (1 + demand_change_compared_to_2024 / 100)
        else:
            print(f"Warning: Load '{load}' not found in demand data.")

# 太陽光発電の時系列データをRenewable.Ninja APIから取得してCSVに保存
def GetSolarTimeSeriesData(file_name, output_file, Year_of_analysis, renewable_ninja_api_key):
    # pypsa-japan-10BusModel.xlsx のbusesのバス名と座標を取得して、年間の時系列データを取得してCSVに保存
    import pandas as pd
    import requests

    # ネットワークファイルからバス情報を読み込み
    buses_df = pd.read_excel(file_name, sheet_name='buses')
    buses_df = buses_df.set_index('name')

    # 座標情報を含むバス位置データフレームを作成
    bus_coords = buses_df[['y', 'x']].copy()
    bus_coords.columns = ['lat', 'lon']
    bus_coords = bus_coords.dropna()

    print(f"取得したバス数: {len(bus_coords)}")
    print(bus_coords)

    # 年間の日付範囲を作成（JSTで最終的に必要な範囲）
    annual_snapshots = pd.date_range(f"{Year_of_analysis}-01-01 00:00",
                                    f"{Year_of_analysis}-12-31 23:00",
                                    freq="h")

    # 結果を格納するDataFrame
    solar_data_annual_full = pd.DataFrame(index=annual_snapshots)

    # 各バスの座標に対してRenewable.Ninja APIからデータを取得
    for bus_name, row in bus_coords.iterrows():
        lat = row['lat']
        lon = row['lon']
        
        print(f"Fetching data for {bus_name} (lat: {lat}, lon: {lon})...")
        
        # Renewable.Ninja API リクエスト
        # JSTへの変換で9時間進むため、前日の15:00 UTCから取得開始
        # （前日の15:00 UTC = 当日の0:00 JST）
        url = 'https://www.renewables.ninja/api/data/pv'
        params = {
            'lat': lat,
            'lon': lon,
            'date_from': f'{Year_of_analysis - 1}-12-31',  # 前年の12/31から取得
            'date_to': f'{Year_of_analysis}-12-31',
            'dataset': 'merra2',
            'capacity': 1.0,
            'system_loss': 0.1,
            'tracking': 0,
            'tilt': 35,
            'azim': 180,
            'format': 'json'
        }
        headers = {'Authorization': f'Token {renewable_ninja_api_key}'}
        
        response = requests.get(url, params=params, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            # レスポンス構造を確認してデバッグ
            if isinstance(data, dict) and 'data' in data:
                # 辞書形式のレスポンス (時刻がキーの場合)
                if isinstance(data['data'], dict):
                    # Unix時間(ミリ秒)をdatetimeに変換
                    time_keys = list(data['data'].keys())
                    # キーが数値(Unix時間)かどうか確認
                    if time_keys and str(time_keys[0]).isdigit():
                        # Unix時間(ミリ秒)の場合
                        time_index = pd.to_datetime([int(k) for k in time_keys], unit='ms')
                    else:
                        # 文字列形式の場合
                        time_index = pd.to_datetime(time_keys)
                    # JSTに変換（UTC+9時間）
                    time_index = time_index.tz_localize('UTC').tz_convert('Asia/Tokyo').tz_localize(None)
                    values = list(data['data'].values())
                    # 辞書から数値を抽出 (PyPSA形式)
                    if values and isinstance(values[0], dict):
                        values = [v.get('electricity', v) if isinstance(v, dict) else v for v in values]
                    # 時刻インデックスと値を組み合わせて、annual_snapshotsの範囲にリインデックス
                    temp_series = pd.Series(values, index=time_index)
                    solar_data_annual_full[bus_name] = temp_series.reindex(annual_snapshots, fill_value=0)
                # リスト形式のレスポンス (DataFrame変換可能な場合)
                elif isinstance(data['data'], list):
                    df_temp = pd.DataFrame(data['data'])
                    # 時刻カラム名を探す
                    time_col = next((col for col in df_temp.columns if 'time' in col.lower()), None)
                    if time_col:
                        df_temp.index = pd.to_datetime(df_temp[time_col])
                    # 発電量カラム名を探す
                    elec_col = next((col for col in df_temp.columns if 'electric' in col.lower() or 'power' in col.lower()), df_temp.columns[1] if len(df_temp.columns) > 1 else df_temp.columns[0])
                    solar_data_annual_full[bus_name] = df_temp[elec_col]
            else:
                print(f"  ⚠ Unexpected response format for {bus_name}")
                solar_data_annual_full[bus_name] = 0
            print(f"  ✓ Success for {bus_name}")
        else:
            print(f"  ✗ Failed for {bus_name}: {response.status_code}")
            solar_data_annual_full[bus_name] = 0

    # PyPSA形式のCSVとして保存（数値のみ、UTF-8エンコーディング）

    solar_data_annual_full.to_csv(output_file, encoding='utf-8-sig')
    print(f"\n年間太陽光データ(PyPSA形式)を保存しました: {output_file}")
    print(f"データサイズ: {solar_data_annual_full.shape}")
    print("\n最初の5行:")
    print(solar_data_annual_full.head())
    print("\n統計情報:")
    print(solar_data_annual_full.describe())

def SolarTimeSeriesDataSet(network,solar_data_file):
    # 太陽光発電データを読み込んで割り当て
    
    if os.path.exists(solar_data_file):
        print(f"太陽光データを読み込んでいます: {solar_data_file}")
        solar_data = pd.read_csv(solar_data_file, index_col=0, parse_dates=True)
        
        # 太陽光発電機を抽出（carrierが'solar'または'太陽光'のもの）
        solar_gens = network.generators[network.generators.carrier.str.contains('solar|太陽光', case=False, na=False)]
        
        # 各太陽光発電機にバスのデータを割り当て
        for gen_name in solar_gens.index:
            bus_name = network.generators.loc[gen_name, 'bus']
            if bus_name in solar_data.columns:
                # snapshotの範囲に合わせてリインデックス
                gen_data = solar_data[bus_name].reindex(network.snapshots, method='nearest')
                network.generators_t.p_max_pu[gen_name] = gen_data
            else:
                print(f"  ⚠ {gen_name} のバス {bus_name} がCSVに見つかりません")
                network.generators_t.p_max_pu[gen_name] = 0.0
    else:
        print(f"  ✗ 太陽光データファイルが存在しません: {solar_data_file}")
