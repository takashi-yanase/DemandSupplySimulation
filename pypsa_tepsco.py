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
            carrier_output[carrier] = network.generators_t.p[gen]
        else:
            carrier_output[carrier] += network.generators_t.p[gen]

    # DataFrame化（index=時系列、columns=carrier）
    carrier_output_df = pd.DataFrame(carrier_output)

    # グラフ描画
    # キャリアの順序および色を指定（下から上に積み上がる順）
    desired_order = ["原子力", "火力（石炭）", "火力（ガス）", "火力（石油）", "水力", "太陽光", "バイオマス", "その他"]
    color_list = ["#4B0082", "#2F4F4F", "#FF8C00", "#FF0000", "#87CEEB", "#EEFF00", "#228B22", "#D2691E"]
    # 指定順で列を並び替える（存在する列だけ抽出）
    ordered_columns = [col for col in desired_order if col in carrier_output_df.columns]
    carrier_output_df = carrier_output_df[ordered_columns]

    # グラフ描画
    carrier_output_df.plot(
        kind="area", 
        stacked=True, 
        figsize=(12,6),
        alpha=0.8,
        color=color_list[:len(ordered_columns)],
        linewidth=0.5
    )
    plt.title("キャリア別合計発電出力（積み上げ）")
    plt.xlabel("時間")
    plt.ylabel("発電出力 [MW]")
    plt.legend(title="キャリア")
    plt.tight_layout()
    plt.show()



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
    # 並列処理を削除し、順次処理に変更してレート制限を回避
    # リクエスト間に1秒の遅延を入れる
    results = []
    for gen_name in solar_generators.index:
        try:
            gen_name, electricity_data = fetch_solar_data(gen_name)
            results.append((gen_name, electricity_data))
            # レート制限を回避するため、次のリクエストまで待機
            time.sleep(1)
        except Exception as e:
            print(f"  -> Exception occurred for '{gen_name}': {e}")
            results.append((gen_name, None))
    
    for gen_name, electricity_data in results:
        try:
            if electricity_data is not None and len(electricity_data) > 0:
                # electricity_dataのインデックスとnetwork.snapshotsを照合
                # 共通の時刻のみを抽出
                common_timestamps = electricity_data.index.intersection(network.snapshots)
                
                if len(common_timestamps) == 0:
                    warnings.warn(f"No matching timestamps for '{gen_name}'. Data index: {electricity_data.index[:5]}, Network snapshots: {network.snapshots[:5]}")
                else:
                    # 共通の時刻のデータのみを格納
                    network.generators_t.p_max_pu.loc[common_timestamps, gen_name] = electricity_data.loc[common_timestamps].values
                    print(f"✓ Successfully stored solar data for '{gen_name}' ({len(common_timestamps)} points)")
                    success_count += 1
            else:
                print(f"✗ No data received for '{gen_name}'")
        except Exception as e:
            print(f"✗ Error processing generator '{gen_name}': {e}")
            warnings.warn(f"Error processing generator '{gen_name}': {e}")
    
    print(f"\nSummary: Successfully loaded data for {success_count}/{len(solar_generators)} solar generators")
