##　TEST

import os, pandas as pd
from IPython.display import clear_output, display
from concurrent.futures import ThreadPoolExecutor
import warnings
import requests
import re
import shutil

def import_demand_data(network, demand_file_name, demand_change_compared_to_2024):
    # Import and filter demand data to match network snapshots

    demand_data_raw = pd.read_csv(demand_file_name, index_col=0, parse_dates=True)
    print(demand_data_raw)
    # demand_data_rawに格納されたデータをnetwork.loads_t.p_setに適用
    for load in network.loads.index:
        if load in demand_data_raw.columns:
            network.loads_t.p_set[load] = demand_data_raw[load] * (1 + demand_change_compared_to_2024 / 100)
        else:
            print(f"Warning: Load '{load}' not found in demand data.")
