"""
data download functionality
"""
import os
import requests
import zipfile
import re
import warnings

import numpy as np
import pandas as pd
import geopandas as gpd

import ukcensusapi.Nomisweb as Nomisweb
import ukcensusapi.NRScotland as NRScotland
import ukcensusapi.NISRA as NISRA

import ukpopulation.myedata as MYEData
import ukpopulation.snppdata as SNPPData
import ukpopulation.nppdata as NPPData
import ukpopulation.snhpdata as SNHPData

import ukpopulation.utils as ukpoputils

import simim.utils as utils

class Instance():
  def __init__(self, params):

    self.coverage = { "EW": ukpoputils.EW, "GB": ukpoputils.GB, "UK": ukpoputils.UK }.get(params["coverage"]) 
    if not self.coverage:
      raise RuntimeError("invalid coverage: %s" % params["coverage"])

    self.cache_dir = params["cache_dir"]
    # initialise data sources
    self.census_ew = Nomisweb.Nomisweb(self.cache_dir)
    self.census_sc = NRScotland.NRScotland(self.cache_dir)
    self.census_ni = NISRA.NISRA(self.cache_dir)
    # population projections
    self.mye = MYEData.MYEData(self.cache_dir)
    self.snpp = SNPPData.SNPPData(self.cache_dir) 
    self.npp = NPPData.NPPData(self.cache_dir) 
    # households
    self.baseline = params["base_projection"]

    if not os.path.isdir(params["output_dir"]):
      raise ValueError("Output directory %s not found" % params["output_dir"])

    self.output_file = os.path.join(params["output_dir"], "simim_%s_%s_%s" % (params["model_type"], params["base_projection"], os.path.basename(params["scenario"])))
    self.custom_snpp_variant = pd.DataFrame()

    self.snhp = SNHPData.SNHPData(self.cache_dir)

    # holder for shapefile when requested
    self.shapefile = None

  def get_od(self):

    # get OD data
    # more up-to-date here (E&W by LAD, Scotland & NI by country)
    # https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/migrationwithintheuk/datasets/internalmigrationbyoriginanddestinationlocalauthoritiessexandsingleyearofagedetailedestimatesdataset

    uk_cmlad_codes="1132462081...1132462085,1132462127,1132462128,1132462356...1132462360,1132462086...1132462089,1132462129,1132462130,1132462145...1132462150,1132462229...1132462240,1132462337...1132462351,1132462090...1132462094,1132462269...1132462275,1132462352...1132462355,1132462368...1132462372,1132462095...1132462098,1132462151...1132462158,1132462241...1132462254,1132462262...1132462268,1132462276...1132462282,1132462099...1132462101,1132462131,1132462293...1132462300,1132462319...1132462323,1132462331...1132462336,1132462361...1132462367,1132462111...1132462114,1132462134,1132462135,1132462140...1132462144,1132462178...1132462189,1132462207...1132462216,1132462255...1132462261,1132462301...1132462307,1132462373...1132462404,1132462115...1132462126,1132462136...1132462139,1132462173...1132462177,1132462196...1132462206,1132462217...1132462228,1132462283...1132462287,1132462308...1132462318,1132462324...1132462330,1132462102,1132462103,1132462132,1132462133,1132462104...1132462110,1132462159...1132462172,1132462190...1132462195,1132462288...1132462292,1132462405...1132462484"
    table = "MM01CUK_ALL"
    query_params = {
      "date": "latest",
      "usual_residence": uk_cmlad_codes,
      "address_one_year_ago": uk_cmlad_codes,
      "age": 0,
      "c_sex": 0,
      "measures": 20100,
      "select": "ADDRESS_ONE_YEAR_AGO_CODE,USUAL_RESIDENCE_CODE,OBS_VALUE"
    }
    od = self.census_ew.get_data(table, query_params)
    #print(od_2011.USUAL_RESIDENCE_CODE.unique())
    return od

  def get_people(self, year, geogs):

    if isinstance(geogs, str):
      geogs = [geogs]

    geogs = ukpoputils.split_by_country(geogs)
    
    alldata = pd.DataFrame()
    for country in geogs:
      # TODO variants...
      if not geogs[country]: continue
      if year < self.snpp.min_year(country):
        data = self.mye.aggregate(["GENDER", "C_AGE"], geogs[country], year)
      elif year <= self.snpp.max_year(country):
        data = self.snpp.aggregate(["GENDER", "C_AGE"], geogs[country], year)
      else:
        print("%d population for %s is extrapolated" % (year, country))
        data = self.snpp.extrapolagg(["GENDER", "C_AGE"], self.npp, geogs[country], year)
      alldata = alldata.append(data, ignore_index=True, sort=False)

    alldata = alldata.rename({"OBS_VALUE": "PEOPLE"}, axis=1).drop("PROJECTED_YEAR_NAME", axis=1)

    # print(data.head())
    # print(len(data))
    return alldata

  # this is 2011 census data
  def get_households2011(self, geogs):

    # see https://docs.python.org/3/library/warnings.html
    warnings.warn("geogs argument to get_households is currently ignored")

    # households
    # get total household counts per LAD
    query_params = {
      "date": "latest",
      "RURAL_URBAN": "0",
      "CELL": "0",
      "MEASURES": "20100",
      "geography": "1946157057...1946157404",
      "select": "GEOGRAPHY_CODE,OBS_VALUE"
    }
    households = self.census_ew.get_data("KS105EW", query_params)
    # get Scotland
    households_sc = self.census_sc.get_data("KS105SC", "S92000003", "LAD", category_filters={"KS105SC_0_CODE": 0}).drop("KS105SC_0_CODE", axis=1)
    # print(households_sc)
    # print(len(households_sc))
    households = households.append(households_sc, ignore_index=True)
    #print(len(households))

    if "ni" in self.coverage:
      households_ni = self.census_ni.get_data("KS105NI", "N92000002", "LAD", category_filters={"KS105NI_0_CODE": 0}).drop("KS105NI_0_CODE", axis=1)
      # print(households_ni)
      # print(len(households_ni))
      households = households.append(households_ni)
      
    households.rename({"OBS_VALUE": "HOUSEHOLDS"}, axis=1, inplace=True)
    return households

  def get_households(self, year, geogs): 

    geogs = ukpoputils.split_by_country(geogs)

    allsnhp = pd.DataFrame()

    for country in geogs:
      if not geogs[country]: continue
      max_year= self.snhp.max_year(country)

      if year <= max_year:
        snhp = self.snhp.aggregate(geogs[country], year).rename({"OBS_VALUE": "HOUSEHOLDS"}, axis=1)
      else:
        print("%d households for %s is extrapolated" % (year, country))
        #print(self.snhp.aggregate(geogs[country], max_year))
        snhp = self.snhp.aggregate(geogs[country], max_year-1).merge(self.snhp.aggregate(geogs[country], max_year), 
          left_on="GEOGRAPHY_CODE", right_on="GEOGRAPHY_CODE")
        snhp["HOUSEHOLDS"] = snhp.OBS_VALUE_y + (snhp.OBS_VALUE_y - snhp.OBS_VALUE_x) * (year - max_year)
        snhp["PROJECTED_YEAR_NAME"] = year
        snhp.drop(["PROJECTED_YEAR_NAME_x", "OBS_VALUE_x", "PROJECTED_YEAR_NAME_y", "OBS_VALUE_y"], axis=1, inplace=True)

      # aggregate census-merged LADs 'E06000053' 'E09000001'
      snhp.loc[snhp.GEOGRAPHY_CODE=="E09000033", "HOUSEHOLDS"] = snhp[snhp.GEOGRAPHY_CODE.isin(["E09000001","E09000033"])].HOUSEHOLDS.sum()
      snhp.loc[snhp.GEOGRAPHY_CODE=="E06000052", "HOUSEHOLDS"] = snhp[snhp.GEOGRAPHY_CODE.isin(["E06000052","E06000053"])].HOUSEHOLDS.sum()
      allsnhp = allsnhp.append(snhp, ignore_index=True, sort=False)

    return allsnhp

  def get_jobs(self, year, geogs):
    """
    NM57 has both total jobs and density*, but raw data needs to be unstacked for ease of use
    *nomisweb: "Jobs density is the numbers of jobs per resident aged 16-64. For example, 
    a job density of 1.0 would mean that there is one job for every resident of working age."
    """

    # http://www.nomisweb.co.uk/api/v01/dataset/NM_57_1.data.tsv?
    # geography=1879048193...1879048573,1879048583,1879048574...1879048582&
    # date=latest&
    # item=1,3&measures=20100&
    # select=date_name,geography_name,geography_code,item_name,measures_name,obs_value,obs_status_name
    query_params = {
      "date": "latest",
      "item": "1,3",
      "MEASURES": "20100",
      "geography": "1879048193...1879048573,1879048583,1879048574...1879048582",
      "select": "GEOGRAPHY_CODE,ITEM_NAME,OBS_VALUE"
    }
    jobs = self.census_ew.get_data("NM_57_1", query_params)

    # aggregate census-merged LADs 'E06000053' 'E09000001'
    jobs.loc[jobs.GEOGRAPHY_CODE=="E09000033", "OBS_VALUE"] = jobs[jobs.GEOGRAPHY_CODE.isin(["E09000001","E09000033"])].OBS_VALUE.sum()
    jobs.loc[jobs.GEOGRAPHY_CODE=="E06000052", "OBS_VALUE"] = jobs[jobs.GEOGRAPHY_CODE.isin(["E06000052","E06000053"])].OBS_VALUE.sum()
    
    # TODO filter by geogs rather than hard-coding GB
    jobs = jobs[jobs.GEOGRAPHY_CODE.isin(geogs)]

    jobs = jobs.set_index(["GEOGRAPHY_CODE", "ITEM_NAME"]).unstack(level=-1).reset_index()
    jobs.columns = jobs.columns.map("".join)
    return jobs.rename({"OBS_VALUEJobs density": "JOBS_PER_WORKING_AGE_PERSON", "OBS_VALUETotal jobs": "JOBS"}, axis=1)

  # temporarily loading from csv pending response from nomisweb
  def get_gva(self, year, geogs):
    gva_all = pd.read_csv("./data/ons_gva1997-2015.csv")
    if year > 2015:
      print("using latest available (2015) GVA data")
      year = 2015

    # filter LADs and specific year
    return gva_all[gva_all.GEOGRAPHY_CODE.isin(geogs)][["GEOGRAPHY_CODE", str(year)]].rename({str(year): "GVA"}, axis=1)

  def get_shapefile(self, zip_url=None):
    """ 
    Gets and stores a shapefile from the given URL 
    same shapefile can be subsequently retrieved by calling this function without the zip_url arg
    Fails if no url is supplied and none has previously been specified
    """
    assert self.shapefile is not None or zip_url is not None
    if zip_url is not None:
      local_zipfile = os.path.join(self.cache_dir, utils.md5hash(zip_url) + ".zip")
      if not os.path.isfile(local_zipfile):
        response = requests.get(zip_url)
        response.raise_for_status()
        with open(local_zipfile, 'wb') as fd:
          for chunk in response.iter_content(chunk_size=1024):
            fd.write(chunk)
        print("downloaded OK")
      else: 
        print("using cached data: %s" % local_zipfile)
      
      zip = zipfile.ZipFile(local_zipfile)
      #print(zip.namelist())
      # find a shapefile in the zip...
      regex = re.compile(".*\.shp$")
      f = filter(regex.match, zip.namelist())
      shapefile = str(next(f))
      # can't find a way of reading this directly into geopandas
      zip.extractall(path=self.cache_dir)
      self.shapefile = gpd.read_file(os.path.join(self.cache_dir, shapefile))
    return self.shapefile

  def get_lad_lookup(self): 

    lookup = pd.read_csv("../microsimulation/persistent_data/gb_geog_lookup.csv.gz")
    # only need the CMLAD->LAD mapping
    return lookup[["LAD_CM", "LAD"]].drop_duplicates().reset_index(drop=True)

  def append_output(self, dataset, year):
    dataset["PROJECTED_YEAR_NAME"] = year
    self.custom_snpp_variant = self.custom_snpp_variant.append(dataset, ignore_index=True, sort=False)

  def summarise_output(self, scenario):
    horizon = self.custom_snpp_variant.PROJECTED_YEAR_NAME.unique().max()
    scen_horizon = min(horizon, scenario.data.YEAR.max())
    print("Cumulative scenario at %d" % scen_horizon)
    print(scenario.data[scenario.data.YEAR == scen_horizon])
    print("Summary at horizon year: %d" % horizon)
    print("In-region population changes:")
    inreg = self.custom_snpp_variant[(self.custom_snpp_variant.PROJECTED_YEAR_NAME == horizon)
                                   & (self.custom_snpp_variant.GEOGRAPHY_CODE.isin(scenario.geographies()))].drop("net_delta", axis=1) 
    print("TOTAL: %.0f baseline vs %.0f scenario (increase of %.0f)"
      % (inreg.PEOPLE_SNPP.sum(), inreg.PEOPLE.sum(), inreg.PEOPLE.sum() - inreg.PEOPLE_SNPP.sum()))
    print(inreg)

    print("10 largest migration origins:")
    print(self.custom_snpp_variant[self.custom_snpp_variant.PROJECTED_YEAR_NAME == horizon]
                            .nsmallest(10, "net_delta").drop("net_delta", axis=1))

  def write_output(self):
    self.custom_snpp_variant.drop(["net_delta","net_delta_prev","PEOPLE_prev"], axis=1).to_csv(self.output_file, index=False)

