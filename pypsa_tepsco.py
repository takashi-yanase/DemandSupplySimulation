##　TEST

import os, pandas as pd
from IPython.display import clear_output, display
from concurrent.futures import ThreadPoolExecutor
import warnings, requests, re, shutil

# 需要データの読み込み
def import_demand_data_from_network_file(network, network_file_name, demand_change_compared_to_2024):
    demand_data_raw = pd.read_excel(network_file_name, sheet_name='Demand', index_col=0, parse_dates=True)

    # demand_data_rawに格納されたデータをnetwork.loads_t.p_setに適用
    for load in network.loads.index:
        if load in demand_data_raw.columns:
            network.loads_t.p_set[load] = demand_data_raw[load] * (1 + demand_change_compared_to_2024 / 100)
        else:
            print(f"Warning: Load '{load}' not found in demand data.")

# 太陽光発電所の出力データをRenewable.Ninjaから取得してnetworkに適用
# networkのgeneratorsテーブルから太陽光発電所の座標を自動抽出
def import_solar_data_from_renewable_ninja(network, renewable_ninja_api_key, start_year, end_year):
    # 太陽光発電所のみを抽出
    solar_generators = network.generators[network.generators['carrier'] == '太陽光']
    
    print(f"Found {len(solar_generators)} solar generators in network")
    
    if solar_generators.empty:
        print("Warning: No solar generators found in network.")
        return
    
    # 座標データを確認
    if 'y' not in solar_generators.columns or 'x' not in solar_generators.columns:
        raise ValueError("Generators table must have 'y' (latitude) and 'x' (longitude) columns.")

    def fetch_solar_data(gen_name):
        gen = network.generators.loc[gen_name]
        lat, lon = gen['y'], gen['x']
        # Renewable.ninja APIは1MWの容量係数を返すので、容量は1に固定
        # 後で実際のp_nomを掛け算する必要はなく、容量係数のみを使用
        capacity = 1  # 1MW固定で容量係数を取得
        
        print(f"Fetching data for '{gen_name}' at ({lat}, {lon}), p_nom={gen['p_nom']} MW")
        
        # Renewable.ninja APIの正しいパラメータ
        # tracking=0: 固定式, azim=180: 南向き, tilt=35: 傾斜角35度（緯度と同じ程度）, system_loss=0.1: システム損失10%
        url = f"https://www.renewables.ninja/api/data/pv?lat={lat}&lon={lon}&capacity={capacity}&tracking=0&azim=180&tilt=35&system_loss=0.1&date_from={start_year}-01-01&date_to={end_year}-12-31&format=json"
        
        # APIキーはヘッダーで渡す
        headers = {'Authorization': f'Token {renewable_ninja_api_key}'}
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            # dataは辞書形式: キー=Unixタイムスタンプ(ミリ秒), 値={'electricity': value}
            # DataFrameに変換
            timestamps = []
            electricity_values = []
            for timestamp_ms, values in data['data'].items():
                # Unixタイムスタンプ(ミリ秒)をDatetimeに変換
                timestamps.append(pd.to_datetime(int(timestamp_ms), unit='ms', utc=True))
                # electricity値を取得（これが容量係数）
                electricity_values.append(values['electricity'])
            
            df = pd.DataFrame({'electricity': electricity_values}, index=timestamps)
            # タイムスタンプをUTC+9時間シフトして日本時間に調整
            # APIはUTC時刻を返すので、日本時間にするには9時間追加
            df.index = df.index + pd.Timedelta(hours=9)
            df.index = df.index.tz_localize(None)  # タイムゾーン情報を削除（naive datetimeに）
            
            print(f"  -> Received {len(df)} data points for '{gen_name}' (shifted to JST +9h)")
            return gen_name, df['electricity']
        else:
            error_msg = f"API request failed with status code {response.status_code}"
            if response.status_code == 403:
                error_msg += " (Check API key)"
            elif response.status_code == 400:
                error_msg += f" (Bad request - check parameters)"
            print(f"  -> Error: {error_msg}")
            warnings.warn(f"Failed to fetch data for generator '{gen_name}' at location ({lat}, {lon}): {error_msg}")
            return gen_name, None

    success_count = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_solar_data, gen_name): gen_name for gen_name in solar_generators.index}
        for future in futures:
            try:
                gen_name, electricity_data = future.result()
                if electricity_data is not None and len(electricity_data) > 0:
                    # networkのsnapshotsに合わせてデータを調整
                    if len(electricity_data) > len(network.snapshots):
                        electricity_data = electricity_data[:len(network.snapshots)]
                    elif len(electricity_data) < len(network.snapshots):
                        warnings.warn(f"Data length mismatch for '{gen_name}': got {len(electricity_data)}, expected {len(network.snapshots)}")
                    
                    network.generators_t.p_max_pu[gen_name] = electricity_data.values
                    print(f"✓ Successfully stored solar data for '{gen_name}' ({len(electricity_data)} points)")
                    success_count += 1
                else:
                    print(f"✗ No data received for '{gen_name}'")
            except Exception as e:
                gen_name = futures[future]
                print(f"✗ Error processing generator '{gen_name}': {e}")
                warnings.warn(f"Error processing generator '{gen_name}': {e}")
    
    print(f"\nSummary: Successfully loaded data for {success_count}/{len(solar_generators)} solar generators")
