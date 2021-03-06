#!/usr/bin/env python3
"""
generate a scenario
"""

import numpy as np
import pandas as pd

def main(params):
  ctrlads = ["E07000178", "E06000042", "E07000008"]
  arclads = ["E07000181", "E07000180", "E07000177", "E07000179", "E07000004", "E06000032", "E06000055", "E06000056", "E07000011", "E07000012"]
  camkox = ctrlads.copy()
  camkox.extend(arclads)

  # increase household spaces in CaMKOx uniformly by 260000 over 5 years
  years = range(2020,2025)

  scenario = pd.DataFrame({"GEOGRAPHY_CODE": [], "YEAR": np.array(0, dtype=int), "HOUSEHOLDS": np.array(0, dtype=int)})

  hh_per_year_per_lad = int(260000 / 13 / 5)
  for year in years:
    scenario = scenario.append(pd.DataFrame({"GEOGRAPHY_CODE": camkox, "YEAR": year, "HOUSEHOLDS": hh_per_year_per_lad}), ignore_index=True)

  jobs_per_year_per_ctr = 25000 # 225000 total 
  # or perhaps just in the centres?
  scenario["JOBS"] = 0
  scenario.loc[scenario.GEOGRAPHY_CODE.isin(ctrlads), "JOBS"] = jobs_per_year_per_ctr

  gva_per_year_per_ctr = 200 # £M
  scenario["GVA"] = 0
  scenario.loc[scenario.GEOGRAPHY_CODE.isin(ctrlads), "GVA"] = gva_per_year_per_ctr
  scenario.loc[scenario.GEOGRAPHY_CODE.isin(arclads), "GVA"] = gva_per_year_per_ctr / 4

  # identify by LAD
  scenario.HOUSEHOLDS = scenario.HOUSEHOLDS + pd.to_numeric(scenario.GEOGRAPHY_CODE.str[-3:])

  scenario["CUM_HOUSEHOLDS"] = None 
  scenario["CUM_JOBS"] = None 
  for g in scenario.GEOGRAPHY_CODE.unique():
    for year in scenario.YEAR.unique():
      scenario.loc[(scenario.GEOGRAPHY_CODE==g) & (scenario.YEAR==year), "CUM_HOUSEHOLDS"] = \
        scenario[(scenario.GEOGRAPHY_CODE==g) & (scenario.YEAR <= year)].HOUSEHOLDS.sum()
      scenario.loc[(scenario.GEOGRAPHY_CODE==g) & (scenario.YEAR==year), "CUM_JOBS"] = \
        scenario[(scenario.GEOGRAPHY_CODE==g) & (scenario.YEAR <= year)].JOBS.sum()
      scenario.loc[(scenario.GEOGRAPHY_CODE==g) & (scenario.YEAR==year), "CUM_GVA"] = \
        scenario[(scenario.GEOGRAPHY_CODE==g) & (scenario.YEAR <= year)].GVA.sum()

  # or https://stackoverflow.com/questions/53707418/running-sums-from-one-column-conditional-on-values-in-another-column/53707484#53707484
  #scenario = scenario.sort_values(['GEOGRAPHY_CODE','YEAR']).reset_index(drop=True)
  #scenario['CUM_HOUSEHOLDS'] = scenario.groupby('GEOGRAPHY_CODE').agg({'HOUSEHOLDS':'cumsum'})

  print(scenario)
  scenario.to_csv("./scenario2.csv", index=False)

if __name__ == "__main__":

  main(None)