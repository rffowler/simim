#!/usr/bin/env python3

import numpy as np
import pandas as pd
import geopandas 
import matplotlib.pyplot as plt
import contextily as ctx
import simim.data as data
import simim.models as models
import simim.visuals as visuals

# import statsmodels.api as sm
# #import statsmodels.formula.api as smf

from pysal.contrib.spint.gravity import Gravity
from pysal.contrib.spint.gravity import Attraction
from pysal.contrib.spint.gravity import Doubly

import ukcensusapi.Nomisweb as Nomisweb
import ukcensusapi.NRScotland as NRScotland
import ukcensusapi.NISRA as NISRA

from simim.utils import get_shapefile, calc_distances, od_matrix, get_config

import ukpopulation.utils as ukpoputils

ctrlads = ["E07000178", "E06000042", "E07000008"]
arclads = ["E07000181", "E07000180", "E07000177", "E07000179", "E07000004", "E06000032", "E06000055", "E06000056", "E07000011", "E07000012"]


def main(params):

  coverage = { "EW": ukpoputils.EW, "GB": ukpoputils.GB, "UK": ukpoputils.UK}.get(params["coverage"]) 
  if not coverage:
    raise RuntimeError("invalid coverage: %s" % params["coverage"])

  census_ew = Nomisweb.Nomisweb(params["cache_dir"])
  census_sc = NRScotland.NRScotland(params["cache_dir"])
  census_ni = NISRA.NISRA(params["cache_dir"])

  od_2011 = data.get_od(census_ew)

  # # CMLAD codes...
  # print("E06000048" in od_2011.USUAL_RESIDENCE_CODE.unique())
  # print("E06000057" in od_2011.USUAL_RESIDENCE_CODE.unique())
  # # TODO convert OD to non-CM LAD (more up to date migration data uses LAD)
  lookup = pd.read_csv("../microsimulation/persistent_data/gb_geog_lookup.csv.gz")

  # TODO need to remap old NI codes 95.. to N... ones

  # only need the CMLAD->LAD mapping
  lad_lookup = lookup[["LAD_CM", "LAD"]].drop_duplicates().reset_index(drop=True)
  od_2011 = od_2011.merge(lad_lookup, how='left', left_on="ADDRESS_ONE_YEAR_AGO_CODE", right_on="LAD_CM") \
    .rename({"LAD": "O_GEOGRAPHY_CODE"}, axis=1).drop(["LAD_CM"], axis=1)
  od_2011 = od_2011.merge(lad_lookup, how='left', left_on="USUAL_RESIDENCE_CODE", right_on="LAD_CM") \
   .rename({"LAD": "D_GEOGRAPHY_CODE", "OBS_VALUE": "MIGRATIONS"}, axis=1).drop(["LAD_CM"], axis=1)

  # ensure blanks arising from Sc/NI not being in lookup are reinstated from original data
  od_2011.loc[pd.isnull(od_2011.O_GEOGRAPHY_CODE), "O_GEOGRAPHY_CODE"] = od_2011.ADDRESS_ONE_YEAR_AGO_CODE[pd.isnull(od_2011.O_GEOGRAPHY_CODE)]
  od_2011.loc[pd.isnull(od_2011.D_GEOGRAPHY_CODE), "D_GEOGRAPHY_CODE"] = od_2011.USUAL_RESIDENCE_CODE[pd.isnull(od_2011.D_GEOGRAPHY_CODE)]

  od_2011 = od_2011[(~od_2011.O_GEOGRAPHY_CODE.isnull()) & (~od_2011.O_GEOGRAPHY_CODE.isnull())]
  od_2011.drop(["ADDRESS_ONE_YEAR_AGO_CODE", "USUAL_RESIDENCE_CODE"], axis=1, inplace=True)

  # TODO adjustments for Westminster/City or London and Cornwall/Scilly Isles
  # for now just remove City & Scilly
  od_2011 = od_2011[(od_2011.O_GEOGRAPHY_CODE != "E09000001") & (od_2011.D_GEOGRAPHY_CODE != "E09000001")]
  od_2011 = od_2011[(od_2011.O_GEOGRAPHY_CODE != "E06000053") & (od_2011.D_GEOGRAPHY_CODE != "E06000053")]

  geogs = od_2011.O_GEOGRAPHY_CODE.unique()

  # people
  #p_2011 = data.get_people(census_ew, census_sc, census_ni if do_NI else None)
  p_2011 = data.get_people(params["start_year"], geogs, params["cache_dir"])

  hh_2011 = data.get_households(census_ew, census_sc, census_ni if ukpoputils.NI in coverage else None)

  # get distances (url is GB ultra generalised clipped LAD boundaries/centroids)
  url = "https://opendata.arcgis.com/datasets/686603e943f948acaa13fb5d2b0f1275_4.zip?outSR=%7B%22wkid%22%3A27700%2C%22latestWkid%22%3A27700%7D"
  gdf = get_shapefile(url, params["cache_dir"])

  dists = calc_distances(gdf)
  print(dists.head())

  # merge with OD
  od_2011 = od_2011.merge(dists, how="left", left_on=["O_GEOGRAPHY_CODE", "D_GEOGRAPHY_CODE"], right_on=["orig", "dest"]).drop(["orig", "dest"], axis=1)

  # Merge population *at origin*
  od_2011 = od_2011.merge(p_2011, how="left", left_on="O_GEOGRAPHY_CODE", right_on="GEOGRAPHY_CODE").drop("GEOGRAPHY_CODE", axis=1)
  # Merge households *at destination*
  od_2011 = od_2011.merge(hh_2011, how="left", left_on="D_GEOGRAPHY_CODE", right_on="GEOGRAPHY_CODE").drop("GEOGRAPHY_CODE", axis=1)

  #print(odmatrix.shape)


  # set epsilon dist for O=D rows
  od_2011.loc[od_2011.O_GEOGRAPHY_CODE == od_2011.D_GEOGRAPHY_CODE, "DISTANCE"] = 1e-0
  print(od_2011.head())

  if ukpoputils.NI not in coverage:
    ni = ['95TT', '95XX', '95OO', '95GG', '95DD', '95QQ', '95ZZ', '95VV', '95YY', '95CC',
          '95II', '95NN', '95AA', '95RR', '95MM', '95LL', '95FF', '95BB', '95SS', '95HH',
          '95EE', '95PP', '95UU', '95WW', '95KK', '95JJ']
    od_2011 = od_2011[(~od_2011.O_GEOGRAPHY_CODE.isin(ni)) & (~od_2011.D_GEOGRAPHY_CODE.isin(ni))]
    odmatrix = od_2011[["MIGRATIONS", "O_GEOGRAPHY_CODE", "D_GEOGRAPHY_CODE"]].set_index(["O_GEOGRAPHY_CODE", "D_GEOGRAPHY_CODE"]).unstack().values
  
  # remove O=D rows and reset index
  #od_2011 = od_2011[od_2011.O_GEOGRAPHY_CODE != od_2011.D_GEOGRAPHY_CODE].reset_index(drop=True)

  # miniSIM
  #od_2011 = od_2011[(od_2011.O_GEOGRAPHY_CODE.isin(arclads)) & (od_2011.D_GEOGRAPHY_CODE.isin(arclads))]

  odmatrix = od_matrix(od_2011, "MIGRATIONS", "O_GEOGRAPHY_CODE", "D_GEOGRAPHY_CODE")

  print("model: %s[IGNORED] (%s)" % (params["model_type"], params["model_subtype"]))

  gravity = models.Model("gravity", params["model_subtype"], od_2011, "MIGRATIONS", "PEOPLE", "HOUSEHOLDS", "DISTANCE")
  prod = models.Model("production", params["model_subtype"], od_2011, "MIGRATIONS", "O_GEOGRAPHY_CODE", "HOUSEHOLDS", "DISTANCE")
  # TOO CONSTRAINED!
  # attr = models.Model("attraction", params["model_subtype"], od_2011, "MIGRATIONS", "PEOPLE", "D_GEOGRAPHY_CODE", "DISTANCE")
  # doubly = models.Model("doubly", params["model_subtype"], od_2011, "MIGRATIONS", "O_GEOGRAPHY_CODE", "D_GEOGRAPHY_CODE", "DISTANCE")

  # print(prod.impl.params)
  # print(attr.impl.params)
  # check = pd.DataFrame({"P_YHAT": prod.impl.yhat, "P_MANUAL": prod(xd=od_2011.HOUSEHOLDS.values), "P_MU": prod.dataset.mu,
  #                       "A_YHAT": attr.impl.yhat, "A_MANUAL": attr(xo=od_2011.PEOPLE.values), "A_ALPHA": attr.dataset.alpha})
  # check.to_csv("./check.csv", index=None)
  # stop


  print("Unconstrained Poisson Fitted R2 = %f" % gravity.impl.pseudoR2)
  print("Unconstrained Poisson Fitted RMSE = %f" % gravity.impl.SRMSE)

  model_odmatrix = od_matrix(gravity.dataset, "MODEL_MIGRATIONS", "O_GEOGRAPHY_CODE", "D_GEOGRAPHY_CODE")

  camkox = ctrlads.copy()
  camkox.extend(arclads)

  od_2011["CHANGED_HOUSEHOLDS"] = od_2011.HOUSEHOLDS
  #od_2011.loc[od_2011.D_GEOGRAPHY_CODE == "E07000178", "CHANGED_HOUSEHOLDS"] = od_2011.loc[od_2011.D_GEOGRAPHY_CODE == "E07000178", "CHANGED_HOUSEHOLDS"] + 300000 
  #od_2011.loc[od_2011.D_GEOGRAPHY_CODE.str.startswith("E09"), "CHANGED_HOUSEHOLDS"] = od_2011.loc[od_2011.D_GEOGRAPHY_CODE.str.startswith("E09"), "CHANGED_HOUSEHOLDS"] + 10000 
  od_2011.loc[od_2011.D_GEOGRAPHY_CODE.isin(camkox), "CHANGED_HOUSEHOLDS"] = od_2011.loc[od_2011.D_GEOGRAPHY_CODE.isin(camkox), "CHANGED_HOUSEHOLDS"] + 20000 
  #print(od_2011[od_2011.MIGRATIONS != od_2011.CHANGED_HOUSEHOLDS])

  od_2011["CHANGED_MIGRATIONS"] = gravity(od_2011.PEOPLE.values, od_2011.CHANGED_HOUSEHOLDS.values)
  # print(gravity.dataset[od_2011.MIGRATIONS != od_2011.CHANGED_MIGRATIONS])

  # update populations and recompute (numerically noisy?)
  #od_2011["PEOPLE"] = od_2011["PEOPLE"] + od_2011["CHANGED_MIGRATIONS"] - od_2011["MIGRATIONS"]
  #od_2011["CHANGED_MIGRATIONS"] = gravity(od_2011.PEOPLE.values, od_2011.CHANGED_HOUSEHOLDS.values)

  changed_odmatrix = od_matrix(od_2011, "CHANGED_MIGRATIONS", "O_GEOGRAPHY_CODE", "D_GEOGRAPHY_CODE")
  delta_odmatrix = changed_odmatrix - model_odmatrix

  delta = pd.DataFrame({"o_lad16cd": od_2011.O_GEOGRAPHY_CODE, 
                        "d_lad16cd": od_2011.D_GEOGRAPHY_CODE, 
                        "delta": -od_2011.CHANGED_MIGRATIONS + gravity.dataset.MODEL_MIGRATIONS})
  # remove in-LAD migrations and sun
  o_delta = delta.groupby("o_lad16cd").sum().reset_index().rename({"o_lad16cd": "lad16cd", "delta": "o_delta"}, axis=1)
  d_delta = delta.groupby("d_lad16cd").sum().reset_index().rename({"d_lad16cd": "lad16cd", "delta": "d_delta"}, axis=1)
  delta = o_delta.merge(d_delta)
  delta["net_delta"] = delta.o_delta - delta.d_delta
  print(delta)

  # visualise
  if params["graphics"]:
    # fig.suptitle("UK LAD SIMs using population as emitter, households as attractor")
    v = visuals.Visual(2,3)

    v.scatter((0,0), od_2011.MIGRATIONS, gravity.impl.yhat, "b.", "Gravity (unconstrained) fit: R^2=%.2f" % gravity.impl.pseudoR2)
    v.scatter((0,1), od_2011.MIGRATIONS, prod.impl.yhat, "k.", "Production constrained fit: R^2=%.2f" % prod.impl.pseudoR2)
    #v.scatter((0,2), od_2011.MIGRATIONS, doubly.impl.yhat, "r.", "Doubly constrained fit: R^2=%.2f" % doubly.impl.pseudoR2)

    # TODO change in population...
    # v.polygons((0,2), gdf, [120000, 670000], [0, 550000], "lightgrey")
    # v.polygons((0,2), gdf[gdf.lad16cd.isin(arclads)], [120000, 670000], [0, 550000], "orange")
    # v.polygons((0,2), gdf[gdf.lad16cd.isin(ctrlads)], [120000, 670000], [0, 550000], "red")
    gdf = gdf.merge(delta)
    limits = (-np.max(gdf.net_delta)/2, np.max(gdf.net_delta)/2)
    v.polygons2((0,2), gdf, [120000, 670000], [0, 550000], gdf.net_delta, cmap="seismic", clim=limits, edgecolor="darkgrey", linewidth=0.25)
    v.panel((0,2)).set_title("Gravity migration model implied impact on population")

    v.matrix((1,0), np.log(odmatrix+1), "Greens", title="Actual OD matrix (displaced log scale)")
    v.matrix((1,1), np.log(model_odmatrix+1), "Greys", title="Gravity model OD matrix (displaced log scale)")
    # we get away with log here as no values are -ve
    v.matrix((1,2), np.log(1+delta_odmatrix), "Oranges", title="Gravity model perturbed OD matrix delta")
    #absmax = max(np.max(delta_od),-np.min(delta_od))
    #v.matrix((1,2), delta_od, 'RdBu', title="Gravity model perturbed OD matrix delta", clim=(-absmax/50,absmax/50))

    v.show()
    v.to_png("doc/img/sim_basic.png")

if __name__ == "__main__":
  
  main(get_config())