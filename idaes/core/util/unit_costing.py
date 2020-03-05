##############################################################################
# Institute for the Design of Advanced Energy Systems Process Systems
# Engineering Framework (IDAES PSE Framework) Copyright (c) 2018, by the
# software owners: The Regents of the University of California, through
# Lawrence Berkeley National Laboratory,  National Technology & Engineering
# Solutions of Sandia, LLC, Carnegie Mellon University, West Virginia
# University Research Corporation, et al. All rights reserved.
#
# Please see the files COPYRIGHT.txt and LICENSE.txt for full copyright and
# license information, respectively. Both files are also available online
# at the URL "https://github.com/IDAES/idaes-pse".
##############################################################################
# =============================================================================

from pyomo.environ import (Constraint,
                           Expression,
                           Var,
                           Param,
                           exp,
                           log10, log)


def global_costing_parameters(self, year=None):
    if year is None:
        year = '2018'
    # Cost index $/year (method argument or 2018 default)
    ce_index_dic = {'2019': 680, '2018': 671.1, '2017': 567.5, '2016': 541.7,
                    '2015': 556.8, '2014': 576.1, '2013': 567.3, '2012': 584.6,
                    '2011': 585.7, '2010': 550.8}

    self.CE_index = Param(mutable=True, initialize=ce_index_dic[year],
                          doc='CE cost index $ year')


def _make_vars(self):
    # build generic costing variables (all costing models need these vars)
    self.base_cost = Var(initialize=1e5,
                         bounds=(0, 1e12),
                         doc='Unit Base Cost cost in $')
    self.purchase_cost = Var(initialize=1e4,
                             bounds=(0, 1e12),
                             doc='Unit Purchase Cost in $')

    self.FM = Param(mutable=True, initialize=3,
                    doc='construction material correction factor')


def hx_costing(self, hx_type='U-tube', FM='stain_steel', L_factor='12ft'):
    '''
    Heat exchanger costing method
    Source: Process and Product Design Principles: Synthesis, Analysis,
    and Evaluation
    Seider, Seader, Lewin, Windagdo, 3rd Ed. John Wiley and Sons
    Chapter 22. Cost Accounting and Capital Cost Estimation
    22.2 Cost Indexes and Capital Investment

    This method computes the purchase cost (CP) for a shell and tube heat
    exchanger (Eq. 22.43), the model computes the base cost (CB for 4 type
    of heat exchangers, such as floating head, fixed head, U-tube, and
    Kettle vaporizer), construction material factor (FM), pressure design
    factor (FP), and tube length correction factor (FL), using CE base cost
    index of 500.

    Cp = FP*FM*FL*CB

    Args:
        hx_type : 'floating_head', 'fixed_head', 'U-tube'*, 'Kettle_vap'

        material factor (FM): 'stain_steel'*, 'carb_steel'

        tube length (FL): '8ft'*, '12ft', '16ft', '20ft'

        * --> default options

    Author: MZamarripa (created 9/17/2019; updated 2/21/2020)
    '''
    # ------------------------ Heat Exchanger cost ------------------------
    # heat exchanger cost
    # build generic costing variables
    # (base cost, purchase cost, material factor)
    _make_vars(self)
    self.FL = Param(mutable=True, initialize=1.12,
                    doc='hx tube length correction factor')

    self.FP = Var(initialize=100,
                  doc='Pressure factor')

    self.hx_os = Param(mutable=True, initialize=1.1,
                       doc='hx oversize factor 1.1 to 1.5')

    # select length correction factor
    c_fl = {'8ft': 1.25, '12ft': 1.12, '16ft': 1.05, '20ft': 1.00}
    self.FL = c_fl[L_factor]

    # select construction material (stainless steel default)
    c_material = {'stain_steel': 3, 'carbon_steel': 2}
    self.FM = c_material[FM]
    # ToDo (9/17/2019):FM can be calculated for advanced materials Eq.22.44
    # i.e. Carbon Steel/Cr-Mo steel, Cr-Mo steel/Cr-Mo steel, Monel/Monel,
    # Titanium/titanium, etc.

    # --------------------------------------------------
    # base cost calculation
#       # select heat exchanger type:
    alf1 = {'floating_head': 11.9052,
            'fixed_head': 11.2927,
            'U-tube': 11.3852,
            'Kettle_vap': 12.2052}
    alf2 = {'floating_head': 0.8709,
            'fixed_head': 0.8228,
            'U-tube': 0.9186,
            'Kettle_vap': 0.8709}
    alf3 = {'floating_head': 0.09005,
            'fixed_head': 0.09861,
            'U-tube': 0.09790,
            'Kettle_vap': 0.09005}

    if (self.parent_block().config.tube.property_package.get_metadata().
            default_units['length']) == 'm':
        area = self.parent_block().area*10.7639
    elif (self.parent_block().config.tube.property_package.get_metadata().
            default_units['length']) == 'ft':
        area = self.area
    else:
        raise Exception('area units not suported')

    def hx_cost_rule(self):
        return self.base_cost == self.FL * exp(alf1[hx_type]
                                               - alf2[hx_type]
                                               * log(area*self.hx_os)
                                               + alf3[hx_type]
                                               * log(area*self.hx_os)**2)
    self.base_cost_eq = Constraint(rule=hx_cost_rule)

    # ------------------------------------------------------
    # Pressure factor calculation
    # doublecheck units (higher pressure fluid should be tube side)
    if (self.parent_block().config.tube.property_package.get_metadata().
            properties['pressure']['units']) == 'Pa':
        pressure = (self.parent_block().
                    tube.properties_in[0].pressure*14.69/1.01325e5)
    elif (self.parent_block().config.tube.property_package.get_metadata().
            properties['pressure']['units']) == 'psig':
        pressure = self.tube.properties_in[0].pressure

    # units must be in psig
    def hx_P_factor(self):
        # eq valid from 600 pisg to 3000 psig
        #    return self.hx_FP == 0.8510 + 0.1292*(pressure/600)
        #                                + 0.0198*(pressure/600)**2
        # eq valid from 100 pisg to 2000 psig
        return self.FP == 0.9803 + (0.018*(pressure*14.69/1.01325e5/100)
                                    + 0.0017*(pressure*14.69/1.01325e5/100)**2)
    self.p_factor_eq = Constraint(rule=hx_P_factor)

    # ---------------------------------------------------------
    # purchase cost equation
    def hx_CP_rule(self):
        return self.purchase_cost == (self.FP*self.FM*self.FL
                                      * (self.parent_block().flowsheet().
                                         costing.CE_index/500)*self.base_cost)
    self.cp_cost_eq = Constraint(rule=hx_CP_rule)


def pressure_changer_costing(self, FM_mat="stain_steel",
                             # applies for all (pump, compressor, fan, blower)
                             mover_type="compressor",
                             # fan, blower, compressor
                             compressor_type="centrifugal",
                             # only for compressor
                             driver_mover_type="electrical_motor",
                             # only for compressors
                             pump_type="centrifugal",
                             # centrifugal, external_gear, reciprocating
                             pump_type_factor='1.4',
                             # 1.1 to 1.4, 2.1 and 2.2
                             # (needs to be wise-selected by user see table)
                             pump_motor_type_factor='open'):
    '''
    Pressure changer costing method
    Source: Process and Product Design Principles: Synthesis, Analysis,
    and Evaluation Seider, Seader, Lewin, Windagdo, 3rd Ed. John Wiley and Sons
    Chapter 22. Cost Accounting and Capital Cost Estimation
    22.2 Cost Indexes and Capital Investment

    This method computes the purchase cost (CP) for a pressure changer unit,
    and can be used for costing of pumps, fan, blower, compressor, or Turbine.

    Author: MZamarripa (created 2/21/2020)

    Arguments:

        if config.compressor
        if config.compressor is True:
        mover_type: Fan, Blower, Compressor*
            Fan_type:
            Blower_type:
            Compressor_type: centrifugal*, reciprocating, screw
                drive_type: electric_motor*, steam_turbine, gas_turbine

        FM - construction material:
            Pump: stain_steel*
            Compressor: stain_steel*, nickel_alloy
    *default option
    '''
    # build generic costing variables
    # (base cost, purchase cost, material factor)
    _make_vars(self)

    # if compressor is == False, that means pressure changer is a Turbine
    if self.parent_block().config.compressor is False:
        # turbine purchase cost calculation W / 746 = horsepower
        if self.parent_block().config.thermodynamic_assumption.name == 'pump':
            w = (self.parent_block().
                 work_fluid[self.parent_block().
                            flowsheet().config.time.first()])
        else:
            w = (self.parent_block().
                 work_mechanical[self.parent_block().
                                 flowsheet().config.time.first()])

        if(self.parent_block().config.property_package.get_metadata().
           properties['enth_mol']['units']) == 'J/mol':
            work_hp = w/746  # assuming work is in J/s

        elif(self.parent_block().config.property_package.get_metadata().
             properties['enth_mol']['units']) == 'kJ/kmol':
            work_hp = w*0.0003725  # assuming w is in kJ/hr

        elif(self.parent_block().config.property_package.get_metadata().
             properties['enth_mol']['units']) == 'cal/mol':
            work_hp = w * 0.00561  # assuming W is in cal/s

        elif(self.parent_block().config.property_package.get_metadata().
             properties['enth_mol']['units']) == 'cal/kmol':
            work_hp = w/641186.48  # assuming W is in cal/hr

        else:
            raise Exception("units not supported")

        def CP_rule(self):
            return self.purchase_cost == 530*(-1*work_hp)**0.81
        self.cp_cost_eq = Constraint(rule=CP_rule)

    # if compressor is True
    # Then the pressure changer could be a Pump, Fan, Blower, or Compressor
    else:
        # if ThermodynamicAssumption == Pump (the unit is a Pump)
        if self.parent_block().config.thermodynamic_assumption.name == 'pump':
            # assign work fluid  = to w
            w = self.parent_block().work_fluid[self.parent_block().flowsheet().config.time.first()]

            #new variables only used by pump costing
            self.pump_head = Var(initialize = 10,
                  doc = 'Pump Head in feet of fluid '
                  'flowing (Pressure rise/dens)')

            self.size_factor = Var(initialize = 10000,
                                   doc='pump size factor, f(Q,pump_head) in gpm*ft^0.5')
            
            self.motor_base_cost = Var(initialize = 10000, 
                                       doc = 'motor base purchase cost in $')
            
            self.pump_purchase_cost = Var(initialize = 100000, 
                                       doc = 'pump purchase cost in $')
            
            self.motor_purchase_cost = Var(initialize = 100000, 
                                       doc = 'motor purchase cost in $')
            
            self.FT = Param(mutable = True, initialize = 1, 
                          doc='pump-type factor')
            #work units
            if(self.parent_block().config.property_package.get_metadata().
               properties['enth_mol']['units']) == 'J/mol':
                work_hp = w/746  # assuming W is in J/s
        
            elif(self.parent_block().config.property_package.get_metadata().
               properties['enth_mol']['units']) == 'kJ/kmol':
                work_hp = w*0.0003725  # assuming W is in kJ/hr
            
            elif(self.parent_block().config.property_package.get_metadata().
               properties['enth_mol']['units']) == 'cal/mol':
                work_hp = w*0.00561 # assuming W is in cal/s
            
            elif(self.parent_block().config.property_package.get_metadata().
               properties['enth_mol']['units']) == 'cal/kmol':
                work_hp = w/641186.48  # assuming W is in cal/hr
            #end work units
            else:
                raise Exception('work units are not supported')
            
            # Pressure units    
            if(self.parent_block().config.property_package.get_metadata().
                 properties['pressure']['units']) == 'Pa' and (
                self.parent_block().config.property_package.get_metadata().
                 properties['dens_mass']['units']) =='kg/m^3':
                                                      # Pa to psi = lb/in^2  1ft^2 = 144 in^2
                deltaP_lb_ft2 = self.parent_block().deltaP[0] * 0.00014503773 * 144
                                                                                    # kg/m^3  1 kg= 2.2 lb  1m3 = 35.3147 ft^3
                dens_mass_lb_ft3 = self.parent_block().control_volume.properties_in[0].dens_mass * 2.2 / 35.3147
            # 1 bar = 2088.5472 lbf/ft2
            
            # end pressure units
            else:
                raise Exception('Pa and/or mass density - units not supported')
            
            # volumetric flow units
            if(self.parent_block().config.property_package.get_metadata().
                 properties['flow_vol']['units']) == 'm^3/s':
                # 1 m3/s = 15850.32314 gal(US)/min
                Q_gpm = self.parent_block().control_volume.\
                    properties_in[0].flow_vol * 15850.32314
                
#                @self.Expression(self)
#                def Q_gpm(self):
#                    return self.parent_block().control_volume.properties_in[0].flow_vol * 15850.32314
            #end volumetric flow units
            else:
                raise Exception('flow vol units not supported')

            # build pump_head equation
            def p_head_rule(self):
                return self.pump_head == deltaP_lb_ft2 / dens_mass_lb_ft3
            self.p_head_eq = Constraint(rule = p_head_rule)
            
            # S  = Q(H)**0.5 (S = Size factor for pump)
            # Q = is the flow rate through the pump in gallons per minute
            # H = pump head in feet of flowing (pressure rise/liquid density)
            # build Size Factor equation
            def p_s_factor_rule(self):
                return self.size_factor == Q_gpm*(self.pump_head**0.5)
            self.s_factor_eq = Constraint(rule = p_s_factor_rule)
            

            #Base cost and Purchase cost for centrifugal pump
            # material factor dictionary for centrifugal pumps and external gear pumps
            material_factor_dic = {'cast_iron'   :1.00,
                                   'ductile_iron':1.15,
                                   'cast_steel'  :1.35,
                                   'bronze'      :1.90,
                                   'stain_steel' :2.00,
                                   'hastelloy_c' :2.95,
                                   'monel'       :3.30,
                                   'nickel'      :3.50,
                                   'titanium'    :9.70}
            # material factor dictionary for Reciprocating Plunger pumps
            material_factor_reciprocal_pumps = {'ductile_iron': 1.00,
                                                'Ni_Al_Bronze': 1.15,
                                                'carbon_steel': 1.50,
                                                'stain_steel': 2.20}
            
            # pump type factor dictionary (only used by centrifugal pumps)
            pump_type_factor_dic = {'1.1':1.00,
                                    '1.2':1.50,
                                    '1.3':1.70,
                                    '1.4':2.00,
                                    '2.1':2.70,
                                    '2.2':8.90}
            
            if pump_type == 'centrifugal':
                self.FM = material_factor_dic[FM_mat]
                self.FT = pump_type_factor_dic[pump_type_factor]
            
            elif pump_type == 'external_gear':
                self.FM = material_factor_dic[FM_mat]
                self.FT = 1
                
            elif pump_type == 'reciprocating':
                self.FM = material_factor_reciprocal_pumps[FM_mat]
                self.FT = 1
            else:
                raise Exception('pump type is not supported')
               
            # pump cost correlations ---------------------------------
            def base_pump_rule(self):
                if pump_type == 'centrifugal':
                    return self.base_cost == exp(9.7171 
                                             - 0.6019*log(self.size_factor)
                                             + 0.0519*log(self.size_factor)**2)
                elif pump_type == 'external_gear':
                    return self.base_cost == exp(7.6964
                                                 +0.1986*log(Q_gpm)
                                                 +0.0291*log(Q_gpm)**2
                                                 )
                elif pump_type == 'reciprocating':
                    #brake horsepower with efficiency np typically = 90%
                    PB = (Q_gpm*self.pump_head*dens_mass_lb_ft3/7.48052)/(33000*0.90)
                    
                    return self.base_cost == exp(7.8103
                                                 + 0.26986*log(PB)
                                                 + 0.06718*log(PB)**2
                                                 )
                else:
                    raise Exception('pump type not supported')
            self.base_pump_cost_eq = Constraint(rule=base_pump_rule)
        
            def CP_pump_rule(self):
                return self.pump_purchase_cost == (self.FT*self.FM*
                                  (self.parent_block().flowsheet().costing.CE_index/394)*self.base_cost)
            self.cp_pump_cost_eq = Constraint(rule=CP_pump_rule)
            
            # electric motor cost correlations ------------------------------
            pump_motor_type_dic = {'open':1,
                                   'enclosed':1.4,
                                   'explosion_proof':1.8}
            self.motor_FT = Param(mutable=True,
                                  initialize=pump_motor_type_dic[pump_motor_type_factor],
                                  doc='motor type factor')
            
            #pump fractional efficiency
            np = -0.316 + 0.24015*log(Q_gpm) - 0.01199*log(Q_gpm)**2
            
            # fractional efficiency of the electric motor
            nm = 0.80 + 0.0319*log(work_hp) - 0.00182*log(work_hp)**2
            
            #power consumption in horsepower
            @self.Expression()
            def power_consumption_hp(self):
                return (Q_gpm*self.pump_head*dens_mass_lb_ft3/7.48052)/(33000*np*nm)
            
            def base_motor_cost_rule(self):
                return self.motor_base_cost == exp(5.8259 
                                 + 0.13141*log(self.power_consumption_hp)
                                 + 0.053255*log(self.power_consumption_hp)**2
                                 + 0.028628*log(self.power_consumption_hp)**3
                                 + 0.0035549*log(self.power_consumption_hp)**4
                                 )
            self.base_motor_cost_eq = Constraint(rule=base_motor_cost_rule)
            
            def CP_motor_rule(self):
                return self.motor_purchase_cost == (self.motor_FT
                        *self.parent_block().flowsheet().costing.CE_index/394
                        *self.motor_base_cost)
            self.cp_motor_cost_eq = Constraint(rule = CP_motor_rule)
            
            # Total pump cost (pump + electrical motor)
            def cp_cost_rule(self):
                return self.purchase_cost ==  self.motor_purchase_cost + self.pump_purchase_cost 
            self.total_cost_eq = Constraint(rule=cp_cost_rule)
        # ends pump costing code
        
        # compressor = True, and using isothermal assumption (costing not needed)
        elif self.parent_block().config.thermodynamic_assumption.name == 'isothermal':
            raise Exception('compressors/blowers/fan with isthoermal assmption are two simple to be costed')
        
        # if config.compressor is = True
        # if thermodynamic_assumption is not = Pump (pressure changer could be a Fan, Blower, or Compressor)
        else:
            w = self.parent_block().work_mechanical[self.parent_block().flowsheet().config.time.first()]
            # check the units 
            if(self.parent_block().config.property_package.get_metadata().
               properties['enth_mol']['units']) == 'J/mol':
                work_hp = w/746  # assuming W is in J/s
                print(work_hp)
        
            elif(self.parent_block().config.property_package.get_metadata().
               properties['enth_mol']['units']) == 'kJ/kmol':
                work_hp = w*0.0003725  # assuming W is in kJ/hr
            
            elif(self.parent_block().config.property_package.get_metadata().
               properties['enth_mol']['units']) == 'cal/mol':
                work_hp = w*0.00561 # assuming W is in cal/s
            
            elif(self.parent_block().config.property_package.get_metadata().
               properties['enth_mol']['units']) == 'cal/kmol':
                work_hp = w/641186.48  # assuming W is in cal/hr
            # finish checking the units
            else:
                raise Exception("units not supported")
            # if compressor is = True, and not ThermodynamicAssumption.pump
            # the unit could be a Fan, a Blower, or a Compressor
            # The user has to select mover_type [compressor or Fan or Blower]
            if mover_type == "compressor":
                # Compressor Purchase Cost Correlation
                
                FD_param = {'electrical_motor':1, 'steam_turbine':1.15, 'gas_turbine':1.25}
                self.FD = Param(mutable = True, 
                                initialize = FD_param[driver_mover_type],
                                doc='drive factor')
                # compressor material factor dictionary
                material_factor_dic = {'carbon_steel':1,'stain_steel':2.5, 'nickel_alloy':5.0}
                
                self.FM = material_factor_dic[FM_mat]
                
                c_alf1 = {'centrifugal':7.58,
                          'reciprocating':7.9661, 
                          'screw':8.1238}
                
                c_alf2 = {'centrifugal':0.8,
                          'reciprocating':0.8, 
                          'screw':0.7243}
                
                #Purchase cost rule
                def CB_rule(self):
                    return self.base_cost == exp(c_alf1[compressor_type]
                                        + c_alf2[compressor_type]*log(work_hp))
                self.cb_cost_eq = Constraint(rule=CB_rule)
                
                def CP_rule(self):
                    return self.purchase_cost == (self.FD*self.FM*
                                      (self.parent_block().flowsheet().costing.CE_index/500)*self.base_cost)
                self.cp_cost_eq = Constraint(rule=CP_rule)

            elif mover_type == "fan":
                # fan cost correlation
                print('Fan costing coming soon')
            elif mover_type == "blower":
                #Blower Cost Correlation
                print('Blower costing coming soon')
            else:
                raise Exception('mover type not supported')    