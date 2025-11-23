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

# 発電量プロット
def plot_total_generation_by_carrier(network):

    pd.options.plotting.backend = "matplotlib"  # プロットバックエンドをmatplotlibに
    plt.rcParams['font.family'] = 'Meiryo'  # または 'Meiryo', 'Yu Gothic' MS Gothic
    plt.rcParams['axes.unicode_minus'] = False  # マイナス符号も文字化け防止
    # 各generatorがどのcarrierかを取得
    carrier_map = network.generators['carrier']

    # generator名→carrier名の辞書
    gen_to_carrier = carrier_map.to_dict()

    # generators_t.pの列（generator名）ごとにcarrierでgroupbyして合計
    carrier_output = {}
    for gen, carrier in gen_to_carrier.items():
        if carrier not in carrier_output:
            carrier_output[carrier] = network.generators_t.p[gen].copy()  # .copy()を追加
        else:
            carrier_output[carrier] = carrier_output[carrier] + network.generators_t.p[gen]  # += ではなく = を使用
    
    # 揚水発電の出力を追加（linksから取得）
    phss_discharge = None
    phss_charge = None
    if hasattr(network, 'links') and hasattr(network, 'links_t'):
        # carrier='揚水'のリンクを抽出
        if 'carrier' in network.links.columns:
            phss_links = network.links[network.links['carrier'] == '揚水'].index
            
            if len(phss_links) > 0 and hasattr(network.links_t, 'p0'):
                # links_t.p0から揚水発電の出力を取得（p0は bus0 からの電力フロー）
                phss_total = network.links_t.p0[phss_links].sum(axis=1)
                # 正の値（放電=発電）と負の値（充電）を分離
                phss_discharge = phss_total.clip(lower=0)
                phss_charge = phss_total.clip(upper=0)
                carrier_output['揚水'] = phss_discharge.copy()
                carrier_output['揚水充電'] = phss_charge.copy()

    # DataFrame化（index=時系列、columns=carrier）
    carrier_output_df = pd.DataFrame(carrier_output)

    # グラフ描画
    # キャリアの順序および色を指定（下から上に積み上がる順）
    desired_order = ["原子力", "水力", "火力（石炭）", "火力（ガス）", "火力（石油）", "太陽光", "揚水", "バイオマス", "その他"]
    color_list = ["#4B0082", "#87CEEB", "#2F4F4F", "#FF8C00", "#FF0000", "#EEFF00", "#0649DB", "#228B22", "#D2691E"]
    
    # 指定順で列を並び替える（存在する列だけ抽出）
    ordered_columns = [col for col in desired_order if col in carrier_output_df.columns]
    carrier_output_df = carrier_output_df[ordered_columns]
    
    # 存在する列に対応する色のみ抽出
    colors_to_use = [color_list[desired_order.index(col)] for col in ordered_columns]
    
    fig, ax = plt.subplots(figsize=(14, 6))
    # グラフ描画
    total_load = network.loads_t['p_set'].sum(axis=1) 
    total_load.plot(ax=ax, linewidth=1, color="#D05555DF", label='Total Load (負荷)', linestyle='-', zorder=100)
    
    # 発電（正の値）を積み上げ
    carrier_output_df.plot.area(ax=ax, alpha=0.8, linewidth=0, stacked=True, zorder=1, color=colors_to_use)

    # 揚水充電（負の値）をマイナス方向に表示
    if phss_charge is not None:
        phss_charge.plot.area(ax=ax, alpha=0.8, linewidth=0, zorder=10, color="#0649DB", label='揚水充電')
        
        # Y軸の範囲を調整（充電の最小値を含める）
        y_max = max(total_load.max(), carrier_output_df.sum(axis=1).max())
        y_min = phss_charge.min()
        margin = (y_max - y_min) * 0.05  # 5%のマージン
        ax.set_ylim(y_min - margin, y_max + margin)
   
    plt.title("キャリア別合計発電出力（揚水含む・積み上げ）")
    plt.xlabel("時間")
    plt.ylabel("発電出力 [MW]")
    plt.legend(title="キャリア", bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.show()

def GetSolarTimeSeriesData(file_name, output_file, Year_of_analysis):
    # pypsa-japan-10BusModel.xlsx のbusesのバス名と座標を取得して、年間の時系列データを取得してCSVに保存

    import pandas as pd
    import requests
    renewable_ninja_api_key = '0ee68c7853037dcd2235f771d349d104e68996cf'

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
        print(f"警告: {solar_data_file} が見つかりません。APIからデータを取得します。")
        # 従来の方法（APIから取得）
        pypsa_tepsco.import_solar_data_from_renewable_ninja(network, renewable_ninja_api_key, Year_of_analysis, Year_of_analysis)
