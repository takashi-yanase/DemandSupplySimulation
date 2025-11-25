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