import os, pandas as pd, time
from IPython.display import clear_output, display
from concurrent.futures import ThreadPoolExecutor
import warnings, requests, re, shutil
import matplotlib.pyplot as plt

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
    carrier_output_df.plot.area(ax=ax, alpha=0.6, linewidth=0, stacked=True, zorder=1, color=colors_to_use)

    # 揚水充電（負の値）をマイナス方向に表示
    if phss_charge is not None:
        phss_charge.plot.area(ax=ax, alpha=0.6, linewidth=0, zorder=10, color="#0649DB", label='揚水充電')
        
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


# バスごとの発電量内訳プロット
def plot_generation_by_bus(network):
    import pandas as pd
    import matplotlib.pyplot as plt
    # 日本語フォント設定
    plt.rcParams['font.family'] = 'Meiryo'
    plt.rcParams['axes.unicode_minus'] = False
    # 発電種別の順序と色を定義
    desired_order = ["原子力", "揚水", "水力", "火力（石炭）", "火力（ガス）", "火力（石油）", "太陽光", "バイオマス", "その他"]
    color_list = ["#745994", "#2C3796", "#87CEEB", "#339689", "#E77A61", "#FF0000", "#EEFF00", "#228B22", "#D2691E"]
    # バスのリスト
    bus_list = ['北海道', '東北', '東京', '北陸', '中部', '関西', '四国', '中国', '九州']
    # 各バスの発電量データを収集
    bus_generation_data = {}
    for bus_name in bus_list:
        # このバスに接続されている発電機を取得
        bus_generators = network.generators[network.generators.bus == bus_name]
        if len(bus_generators) == 0:
            continue
        # 発電機ごとの総発電量を計算
        gen_by_carrier = network.generators_t.p[bus_generators.index].sum().groupby(bus_generators.carrier).sum()
        # 揚水発電は除外
        if '揚水' in gen_by_carrier.index:
            gen_by_carrier = gen_by_carrier.drop('揚水')
        if gen_by_carrier.sum() > 0:
            bus_generation_data[bus_name] = gen_by_carrier
    # 1つのグラフに全地域の横棒グラフを作成
    fig, ax = plt.subplots(figsize=(12, len(bus_generation_data) * 0.8))

    # Y軸の位置を設定
    y_positions = range(len(bus_generation_data))
    bus_names_list = list(bus_generation_data.keys())

    # 各バスのデータをプロット
    for idx, (y_pos, bus_name) in enumerate(zip(y_positions, bus_names_list)):
        gen_data = bus_generation_data[bus_name]
        total_gen = gen_data.sum()
        
        # desired_orderに従って並び替え
        left = 0
        for carrier in desired_order:
            if carrier in gen_data.index and gen_data[carrier] > 0:
                percentage = (gen_data[carrier] / total_gen) * 100
                color = color_list[desired_order.index(carrier)]
                
                # 横棒を描画（最初のバスの時だけlabelを付ける）
                if idx == 0:
                    ax.barh(y_pos, percentage, left=left, color=color, label=carrier, height=0.6)
                else:
                    ax.barh(y_pos, percentage, left=left, color=color, height=0.6)
                
                # パーセント表示（5%以上の場合のみ）
                if percentage >= 5:
                    ax.text(left + percentage/2, y_pos, f'{percentage:.1f}%', 
                        ha='center', va='center', fontsize=9, fontweight='bold', color='white')
                left += percentage

    # グラフの設定
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.5, len(bus_generation_data) - 0.5)
    ax.set_xlabel('発電量の割合 (%)', fontsize=12)
    ax.set_yticks(y_positions)
    ax.set_yticklabels([f'{name}\n({bus_generation_data[name].sum():.0f} MWh)' for name in bus_names_list], fontsize=10)
    ax.set_title('地域別発電種別構成 (Generation Mix by Region)', fontsize=14, fontweight='bold', pad=15)
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=10)
    ax.grid(axis='x', alpha=0.3)
    ax.invert_yaxis()  # 上から下に並べる

    plt.tight_layout()
    plt.show()
# --- IGNORE ---


def plot_generation_mix_in_total_in_pie_graph(network):
    # 発電電力量を発電種別毎の円グラフで表示
    import matplotlib.pyplot as plt

    # 日本語フォント設定
    plt.rcParams['font.family'] = 'Meiryo'  # Windows用
    plt.rcParams['axes.unicode_minus'] = False  # マイナス記号の文字化け防止

    desired_order = ["原子力", "揚水", "水力", "火力（石炭）", "火力（ガス）", "火力（石油）", "太陽光", "バイオマス", "その他"]
    color_list = ["#745994", "#2C3796", "#87CEEB", "#339689", "#E77A61", "#FF0000", "#EEFF00", "#228B22", "#D2691E"]

    # 発電種別ごとの総発電量を計算
    generation_by_carrier = network.generators_t.p.sum().groupby(network.generators.carrier).sum()

    # まずネットワークにどんなcarrierがあるか確認
    print("ネットワーク内のcarrier一覧:")
    print(generation_by_carrier.index.tolist())

    # 揚水発電は除外
    if '揚水' in generation_by_carrier.index:
        generation_by_carrier = generation_by_carrier.drop('揚水')

    # desired_orderに従って並び替え（存在するもののみ）
    ordered_generation = {}
    for carrier in desired_order:
        if carrier in generation_by_carrier.index:
            ordered_generation[carrier] = generation_by_carrier[carrier]

    # 色の対応を作成
    colors_to_use = [color_list[desired_order.index(carrier)] for carrier in ordered_generation.keys()]

    # 円グラフを作成
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.pie(ordered_generation.values(), 
        labels=ordered_generation.keys(), 
        autopct='%1.1f%%',
        startangle=90, 
        colors=colors_to_use,
        textprops={'fontsize': 8})
    ax.set_title('発電種別ごとの総発電量 (Total Generation by Carrier Type)', fontsize=12)
    plt.tight_layout()
    plt.show()
