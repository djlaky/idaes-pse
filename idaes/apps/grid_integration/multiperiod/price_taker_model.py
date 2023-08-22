#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES).
#
# Copyright (c) 2018-2023 by the software owners: The Regents of the
# University of California, through Lawrence Berkeley National Laboratory,
# National Technology & Engineering Solutions of Sandia, LLC, Carnegie Mellon
# University, West Virginia University Research Corporation, et al.
# All rights reserved.  Please see the files COPYRIGHT.md and LICENSE.md
# for full copyright and license information.
#################################################################################
import pandas as pd
import numpy as np
from importlib import resources
from pathlib import Path
from pyomo.environ import (
    ConcreteModel,
    Block,
    Var,
    RangeSet,
    Objective,
    Constraint,
    NonNegativeReals,
    Expression,
    maximize,
)

from idaes.apps.grid_integration import MultiPeriodModel
from idaes.apps.grid_integration.multiperiod.design_and_operation_models import (
    DesignModelData,
    OperationModelData,
)

from sklearn.cluster import KMeans
from kneed import KneeLocator

import matplotlib.pyplot as plt

import logging

_logger = logging.getLogger(__name__)


class PriceTakerModel(ConcreteModel):
    def __init__(self, seed=20, horizon_length=24):
        super().__init__()
        self._seed = seed
        self._horizon_length = horizon_length

    @property
    def seed(self):
        return self._seed

    @seed.setter
    def seed(self, value):
        self._seed = value

    @property
    def horizon_length(self):
        return self._horizon_length

    @horizon_length.setter
    def horizon_length(self, value):
        if value <= 0:
            raise ValueError(f"horizon_length must be > 0, but {value} is provided.")
        self._horizon_length = value

    def generate_daily_data(self,raw_data,day_list):

        daily_data = pd.DataFrame(columns=day_list)

        # Extracting data to populate empty dataframe
        i = 0
        j = self._horizon_length
        day = 1
        while j <= len(raw_data):
            daily_data[day] = raw_data[i:j].reset_index(drop=True)
            i = j
            j = j + self._horizon_length
            day = day + 1
        
        return daily_data

    def reconfigure_raw_data(self, raw_data):
        """
        Reconfigures the raw price series data into a usable form

        Args:
            raw_data: imported price series data

        Returns:
            daily_data: reconfigured price series data
        """

        # Get column headings
        column_head = raw_data.columns.tolist()
        # Remove the date/time column
        scenarios = column_head[2:]

        # Creating an empty dataframe to store daily data for clustering
        day_list = list(range(1, (len(raw_data) // self._horizon_length) + 1))

        # Generate daily data
        for i in scenarios[0:1]:
            daily_data = self.generate_daily_data(
                raw_data=raw_data[i], day_list=day_list
            )

        return daily_data, scenarios

    def get_optimal_n_clusters(self, daily_data, kmin=None, kmax=None, plot=False):
        """
        Determines the appropriate number of clusters needed for a
        given price signal.

        Args:
            daily_data: reconfigured price series data
            kmin: minimum number of clusters
            kmax: maximum number of clusters
            plot: flag to determine if an elbow plot should be displayed

        Returns:
            n_clusters: the optimal number of clusters for the given data
            inertia_values: within-cluster sum-of-squares
        """
        if kmin is None:
            kmin = 4
        if kmax is None:
            kmax = 30
            _logger.warning(f"kmax was not set - using a default value of 30.")

        k_values = range(kmin, kmax)
        inertia_values = []

        np.random.seed(self._seed)

        # Compute the inertia (SSE) for k clusters

        for k in k_values:
            kmeans = KMeans(n_clusters=k).fit(daily_data.transpose())
            inertia_values.append(kmeans.inertia_)

        # Identify the "elbow point"
        elbow_point = KneeLocator(
            k_values, inertia_values, curve="convex", direction="decreasing"
        )
        n_clusters = elbow_point.knee

        print(f"Optimal # of clusters is: {n_clusters}")

        if n_clusters + 2 >= kmax:
            _logger.warning(
                f"Optimal number of clusters is close to kmax: {kmax}. Consider increasing kmax."
            )

        if plot == True:
            plt.show()
            plt.plot(k_values, inertia_values)
            plt.axvline(x=n_clusters, color="red", linestyle="--", label="Elbow")
            plt.xlabel("Number of clusters")
            plt.ylabel("Inertia")
            plt.title("Elbow Method")
            plt.xlim(kmin, kmax)
            plt.grid()
            plt.show()

        return n_clusters, inertia_values

    def cluster_lmp_data(self, raw_data, n_clusters, scenarios):
        """
        Clusters the given price signal in n_clusters. This method supports k-means, k-meteiod,...
        techniques for clustering.

        Args:

        Returns:
            lmp_data = {1: {1: 2, 2: 3, 3: 5}, 2: {1: 2, 2: 3, 3: 5}}
            weights = {1: 45, 2: 56}
        """
        # reconfiguring raw data 
        daily_data,scenarios  = self.reconfigure_raw_data(raw_data)
        
        # KMeans clustering with the optimal number of clusters
        kmeans = KMeans(n_clusters=n_clusters).fit(daily_data.transpose())
        centroids = kmeans.cluster_centers_
        labels = kmeans.labels_

        # Set any centroid values that are < 1e-4 to 0 to avoid noise
        for d in range(n_clusters):
            for t in range(24):
                if centroids[d][t] < 1e-4:
                    centroids[d][t] = 0

        n_clusters_list = range(0, n_clusters)
        weights_counter = np.zeros(n_clusters)

        # Compute weight for each cluster by counting its occurrences in the dataset
        for j in range(0, len(labels)):
            for k in n_clusters_list:
                if labels[j] == k:
                    weights_counter[k] += 1

        # Create dicts for lmp data and the weight of each cluster
        rep_days_data = {}
        weights_data = {}

        
        rep_days_data = pd.DataFrame(centroids.transpose(), columns = range(1,n_clusters+1))
        lmp_data = rep_days_data.to_dict()
        weights_data = pd.DataFrame(weights_counter)
        weights_data.index = np.arange(1, len(weights_data) + 1)
        weights = weights_data.to_dict()

        return lmp_data, weights

    def append_lmp_data(
        self,
        file_path,
        file_name,
        sheet = None,
        column_name="price",
        n_clusters=None,
        horizon_length=None,
    ):
        with resources.path(file_path, file_name) as p:
            path_to_file = Path(p).resolve()
        
        full_data = pd.read_excel( path_to_file, sheet_name=[sheet])[sheet]
        # editing the data
        if isinstance(column_name, list) and n_clusters is not None:
            # Multiple years and representative days
            self.set_years = [int(y) for y in column_name]
            self.set_days = RangeSet(1,n_clusters)
            self._n_time_points = horizon_length if horizon_length is not None else 24
            self.set_time = RangeSet(self._n_time_points)

            self.LMP = {}
            self.WEIGHTS = {}

            for year in column_name:
                price_data = full_data[year]
                lmp_data, weights = self.cluster_lmp_data(
                    price_data, n_clusters, horizon_length
                )
                y = int(year)

                for d in self.set_days:
                    for t in self.set_time:
                        self.LMP[t, d, y] = lmp_data[d][t]
                        self.WEIGHTS[d, y] = weights[0][d]

            return

        elif isinstance(column_name, list):
            # Multiple years, use fullyear price signal for each year
            self.set_years = [int(y) for y in column_name]
            self.set_days = None
            self._n_time_points = len(full_data)
            self.set_time = RangeSet(self._n_time_points)

            self.LMP = {}

            for year in column_name:
                price_data = full_data[year]
                y = int(year)

                for t in self.set_time:
                    self.LMP[t, y] = price_data[t - 1]

            return

        elif n_clusters is not None:
            # Single price signal, use reprentative days
            self.set_years = None
            self.set_days = RangeSet(1,n_clusters)
            self._n_time_points = horizon_length if horizon_length is not None else 24
            self.set_time = RangeSet(self._n_time_points-1)

            self.LMP = {}
            self.WEIGHTS = {}

            price_data = full_data
            lmp_data, weights = self.cluster_lmp_data(
                price_data, n_clusters, horizon_length
            )
            
            for d in self.set_days:
                for t in self.set_time:
                    self.LMP[t, d] = lmp_data[d][t]
                    self.WEIGHTS[d] = weights[0][d]
                    
            return

        else:
            # Single price signal, use full year's price signal
            self.set_years = None
            self.set_days = None
            self._n_time_points = len(full_data)
            self.set_time = RangeSet(self._n_time_points)

            price_data = full_data[column_name].to_list()
            self.LMP = {t: price_data[t - 1] for t in self.set_time}

            return

    def build_multiperiod_model(self, **kwargs):

        # if not self.model_sets_available:
        #     raise Exception(
        #         "Model sets have not been defined. Run get_lmp_data to construct model sets"
        #     )

        self.mp_model = MultiPeriodModel(
            n_time_points=self._n_time_points,
            set_days=self.set_days,
            set_years=self.set_years,
            use_stochastic_build=True,
            **kwargs,
        )
    #TODO: (1) Need to determine whether the minimum opterating power can be a parameter 
    #      or whether it largly depends on the capacity of the plant. 
    #      (2) Need to determine if the start up and shutdown limits can be modeled as bulk amounts vs
    #      a percentage of capacity 
    #      (3) How to model/code the cosntraints in without knowing what variable
    #      these constraints will be applied to. 
    def add_ramping_constraints(
        self, 
        startup_limit = 100, 
        shutdown_limit = 100,
        ramp_up_limit = 110, 
        ramp_down_limit = 110,
        minimum_opt_limit = 0,
          ):
        """
        Adds ramping constraints of the form
        -ramp_down_limit <= var(t) - var(t-1) <= ramp_up_limit on var
        

        Arguments: 
        startup_limit: The rate on the power when starting up (Mw/h)
        shutdown_limit: The rate on the pwoer when shuting down (Mw/h)
        ramp_up_limit: The ramp up rate for the system ( Mw/h)
        ramp_down_limit = The ramp down rate for the system (Mw/h)
        minimum_opt_limit: The minimum power the system is able to operate at at anytime t (Mw/h)

        Assumptions/relationship:
      Max_operating_power >= ramp_up_limit >= startup_limit >= minimum_opt_limit > 0
      Max_operating_power >= ramp_down_limit >= shutdown_limit >= minimum_opt_limit > 0
        """
        period = self.mp_model.period
        range_time_periods = [] 
        self.ramp_up_down_range= RangeSet(2,len(period)-1)

        if period[1,1].find_component('op_mode') == None:
            for p in period:
                range_time_periods.append(p)
                op_mode = 0
                startup = 0
    
                for blk in period[p].component_data_objects(Block):
                    if isinstance(blk, OperationModelData):
                        op_mode += blk.op_mode
                        startup += blk.startup

                period[p].op_mode = Expression(expr = op_mode)
                period[p].startup = Expression(expr = startup) 
               

        def ramp_up_con_rule(self,t):
            return (
                period[range_time_periods[t]].opt_power - period[range_time_periods[t-1]].opt_power <= 
                startup_limit * period[range_time_periods[t]].startup - minimum_opt_limit * period[range_time_periods[t-1]].startup
                + ramp_up_limit * period[range_time_periods[t]].op_mode
                + minimum_opt_limit*(period[range_time_periods[t]].op_mode - period[range_time_periods[t-1]].op_mode)
            )
        
        self.mp_model.ramp_up_con = Constraint(self.ramp_up_down_range, rule = ramp_up_con_rule )
        
        def ramp_down_con_rule(self,t) :
            return (
              period[range_time_periods[t-1]].opt_power- period[range_time_periods[t]].opt_power <= 
              shutdown_limit * (period[range_time_periods[t-1]].startup + 
              period[range_time_periods[t-1]].op_mode - period[range_time_periods[t]].op_mode)
              - minimum_opt_limit * period[range_time_periods[t]].startup 
              + ramp_down_limit * period[range_time_periods[t]].op_mode
            )

        self.mp_model.ramp_down_con = Constraint(self.ramp_up_down_range, rule = ramp_down_con_rule )

    def add_startup_shutdown(self,UT = 4,DT =4):
        """
        Adds startup/shutdown and minimum uptime/downtime constraints on
        a given unit/process

        
        Arguments:
        UT: Time required for the system to start up fully (hr)
        DT: Time required for the system to shutdown fully (hr)
        
        Assumption:
        UT >= 1 & DT >= 1
        """

        
        period = self.mp_model.period
        self.range_time_periods_SU = RangeSet(UT,len(period)-1) 
        self.range_time_periods_SD = RangeSet(DT,len(period)-1)
        range_time_periods = []
        
        for p in period:
            range_time_periods.append(p)
            op_mode = 0
            startup = 0

            for blk in period[p].component_data_objects(Block):
                if isinstance(blk, OperationModelData):
                    op_mode += blk.op_mode
                    startup += blk.startup
            period[p].op_mode = Expression(expr = op_mode)
            period[p].startup = Expression(expr = startup)
        
        
        def startup_con1_rule(self,t):
            return sum(period[range_time_periods[i]].startup for i in range(t-UT+1,t)) <= period[range_time_periods[t]].op_mode
    
        self.mp_model.startup_con1 = Constraint(self.range_time_periods_SU, rule = startup_con1_rule)
        
        def stutdown_con1_rule(self,t):
            return ( sum(period[range_time_periods[i]].startup for i in range(t - DT, t + 1)) <= 
                     1 - period[range_time_periods[t - DT]].op_mode )
        
        self.mp_model.stutdown_con1 = Constraint(self.range_time_periods_SD, rule = stutdown_con1_rule)

            

    def build_hourly_cashflows(self):
        period = self.mp_model.period

        for p in period:
            non_fuel_vom = 0
            fuel_cost = 0
            elec_revenue = 0
            carbon_price = 0

            for blk in period[p].component_data_objects(Block):
                if isinstance(blk, OperationModelData):
                    non_fuel_vom += blk.non_fuel_vom
                    fuel_cost += blk.fuel_cost
                    elec_revenue += blk.elec_revenue
                    carbon_price += blk.carbon_price

            period[p].non_fuel_vom = Expression(expr=non_fuel_vom)
            period[p].fuel_cost = Expression(expr=fuel_cost)
            period[p].elec_revenue = Expression(expr=elec_revenue)
            period[p].carbon_price = Expression(expr=carbon_price)

            period[p].net_cash_inflow = Expression(
                expr=period[p].elec_revenue
                - period[p].non_fuel_vom
                - period[p].fuel_cost
                - period[p].carbon_price
            )

    def build_cashflows(
        self,
        lifetime=30,
        discount_rate=0.08,
        corp_tax=0.2,
        other_costs=0,
        other_revenue=0,
        objective="NPV",
    ):
        """
        Builds overall cashflow expressions and appends objective function
        to the model
        """

        capex_expr = 0
        fom_expr = 0
        for blk in self.component_data_objects(Block):
            if isinstance(blk, DesignModelData):
                capex_expr += blk.capex
                fom_expr += blk.fom

        self.CAPEX = Var(within=NonNegativeReals, doc="Total CAPEX")
        self.capex_calculation = Constraint(expr=self.CAPEX == capex_expr)

        self.FOM = Var(within=NonNegativeReals, doc="Yearly Fixed O&M")
        self.fom_calculation = Constraint(expr=self.FOM == fom_expr)

        self.DEPRECIATION = Var(within=NonNegativeReals, doc="Yearly depreciation")
        self.dep_calculation = Constraint(
            expr=self.DEPRECIATION == self.CAPEX / lifetime
        )

        self.NET_CASH_INFLOW = Var(doc="Net cash inflow")
        self.net_cash_inflow_calculation = Constraint(
            expr=self.NET_CASH_INFLOW
            == sum(self.mp_model.period[p].net_cash_inflow for p in self.mp_model.period) # added period block name to the net_cash_inflow callout
        ) # added period block name to mp_model, to kthe len, and made a range list to loop over

        self.CORP_TAX = Var(within=NonNegativeReals, doc="Corporate tax")
        self.corp_tax_calculation = Constraint(
            expr=self.CORP_TAX
            >= corp_tax
            * (
                self.NET_CASH_INFLOW
                + other_revenue
                - other_costs
                - self.FOM
                - self.DEPRECIATION
            )
        )

        self.NET_PROFIT = Var(doc="Net profit after taxes")
        self.net_profit_calculation = Constraint(
            expr=self.NET_PROFIT
            == self.NET_CASH_INFLOW
            + other_revenue
            - other_costs
            - self.FOM
            - self.CORP_TAX
        )

        constant_cf_factor = (1 - (1 + discount_rate) ** (-lifetime)) / discount_rate
        self.NPV = Expression(expr=constant_cf_factor * self.NET_PROFIT - self.CAPEX)
        self.Annualized_NPV = Expression(
            expr=self.NET_PROFIT - (1 / constant_cf_factor) * self.CAPEX,
        )

        if objective == "NPV":
            self.obj = Objective(expr=self.NPV, sense=maximize)

        elif objective == "Annualized NPV":
            self.obj = Objective(expr=self.Annualized_NPV, sense=maximize)

        elif objective == "Net Profit":
            self.obj = Objective(expr=self.NET_PROFIT, sense=maximize)
