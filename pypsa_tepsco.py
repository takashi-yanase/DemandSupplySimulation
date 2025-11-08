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
