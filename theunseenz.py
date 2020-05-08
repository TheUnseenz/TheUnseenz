# -*- coding: utf-8 -*-
"""
Spyder Editor

Notes:
    Scouting - Periodically send something to scout the map. If we spot units headed somewhere that isn't our base or their home base, look for whats up
    Expanding - Expand when mineral line is about to be saturated within the build time of the town hall. 
    Supply - Calculate supply-increasing rate, if we are projected to be supply-blocked within the build time of supply, build supply. May need to have multiple supply being built concurrently. 
    Production - Calculate income and spending rate, add production buildings until spending rate is ~80% of income. Supply capped -> Add production until spending rate is 200% of income
        Spending rate is average of each type of unit the building can make.
    Unit composition - Estimate which units can we make to maximize damage done to enemy vs damage we can take from enemy, balance out 
        - Range vs speed advantage calculated by estimated time for enemy to catch up with us/us with them, calculated as hp multiplier. 
        - Faster and longer range = infinite hp, so weigh by army proportions
    Tech - What if we have tech buildings destroyed? How to handle continuing tech tree?         
    
    
    Issues to watch out for
    - Creep preventing buildings
    - Burrowed units preventing buildings
    - Split army according to enemy forces multiprong
    - Watch out for choke points and units on the high ground
    - Watch out for early cheese
    - Split units when enemy has splash nearby
    

To install:
pip install burnysc2
https://github.com/Blizzard/s2client-proto/blob/master/s2clientprotocol/data.proto#L83
"""

#import random

import numpy as np
import math
import itertools
import sc2
from sc2 import Race, Difficulty
from sc2.constants import *
from sc2.player import Bot, Computer, Human
from unit_list import unit_list



class TheUnseenz(sc2.BotAI):
    def __init__(self):
        
        # Game defined variables
        self.ITERATIONS_PER_MINUTE = 165
        self.MAX_WORKERS = 76
        self.MAX_SUPPLY = 200
        self.SUPPLY_BUILD_TIME = 18
        self.NEXUS_BUILD_TIME = 71
        self.GAS_BUILD_TIME = 21
        self.NEXUS_MINERAL_RATE = 50/12
        self.NEXUS_SUPPLY_RATE = 1/12
        self.PI = 3.14
        self.gas_value = 2.5 # TODO: Find the best gas_value!
        self.own_army_race = None
        self.enemy_army_race = None
        # Production resource rate is currently average resource of unit/build time i.e. resource per second. Excluded units: Oracle, Observer, Warp prism
        # TODO: Make this dynamically adjusted on desired unit composition.
        self.WARPGATE_MINERAL_RATE = (100/20+50/23+125/23+125/20+50/32+125/32)/6 #4.05
        self.WARPGATE_VESPENE_RATE = (0/20+100/23+50/23+25/20+150/32+125/32)/6 #2.73
        self.WARPGATE_SUPPLY_RATE = (2/20+2/23+2/23+2/20+2/32+2/32)/6 #0.0831
        self.STARGATE_MINERAL_RATE = (150/25+250/43+250/43+(350+15*4)/64)/4 #6.01
        self.STARGATE_VESPENE_RATE = (100/25+150/43+175/43+250/64)/4 #3.87
        self.STARGATE_SUPPLY_RATE = (2/25+4/43+5/43+6/64)/4 #0.0957
        self.ROBO_MINERAL_RATE = (275/39+300/54+150/36)/3 #5.59
        self.ROBO_VESPENE_RATE = (100/39+200/54+150/36)/3 #3.48
        self.ROBO_SUPPLY_RATE = (4/39+6/54+3/36)/3 #0.099
        
        # Army management variables
        self.kite_distance = 0.5
        self.need_detection = False
        self.have_detection = False
        self.need_utility = False
        
        self.ordered_expansions = None
        self.scout_enemy = None
        self.scout_enemy_next = None
        self.clear_map = None
        self.clear_map_next = None
        
        self.own_time_to_kill = None
        self.own_time_to_reach = None
        self.enemy_time_to_kill = None
        self.enemy_time_to_reach = None
        
        self.last_army_supply = 0
        self.last_known_enemy_amount = 0
        self.threat_level = 1
        self.unit_score = None
        self.best_unit = 0
        # Terran: Note that many units have different forms and each form has a different unit name! -> Hellion/Hellbat, Widow mine, Siege tank, Viking, Liberator
        # Excluded units: Raven
        self.terran_army = [MARINE, MARAUDER, REAPER, GHOST, HELLION, HELLIONTANK, WIDOWMINE, SIEGETANK, SIEGETANKSIEGED, CYCLONE, THOR, THORAP, VIKINGFIGHTER, VIKINGASSAULT, \
                            LIBERATOR, LIBERATORAG, BANSHEE, BATTLECRUISER]
        # Protoss: Note that warp prism and observers have different forms with different names! 
        # Excluded units: High Templar, Observer, Warp Prism, Interceptors
        self.protoss_army = [ZEALOT, STALKER, SENTRY, ADEPT, DARKTEMPLAR, ARCHON, IMMORTAL, COLOSSUS, DISRUPTOR, PHOENIX, ORACLE, VOIDRAY, TEMPEST, CARRIER, MOTHERSHIP]
        
        # Zerg: Note that all zerg ground units can burrow! 
        # Excluded units: Vipers, Infestors, Swarm hosts, Overseers, Overlords, Broodlings, Locusts, Baneling
        # How do we count the combat strength of swarm hosts and brood lords? What about spellcasters?
        self.zerg_army = [ZERGLING, ROACH, RAVAGER, HYDRALISK, LURKERMP, QUEEN, MUTALISK, CORRUPTOR, BROODLORD, ULTRALISK]
       
    # Inspired by RoachRush again
    async def better_distribute_workers(self, resource_ratio = 3):
        if not self.workers:
            return
        mineral_income = self.state.score.collection_rate_minerals
        vespene_income = self.state.score.collection_rate_vespene
        
        excess_workers = self.workers.idle    
        
        # Find all oversaturated workers    
        for base in self.townhalls.ready:
            if base.surplus_harvesters > 0:
                workers_on_minerals = self.workers.filter(
                    lambda unit: not unit.is_carrying_resource and unit.order_target in self.mineral_field.tags and unit.distance_to_squared(base) < 100
                )
                if workers_on_minerals:
                    for n in range(base.surplus_harvesters):
                        # prevent crash by only taking the minimum
                        worker = workers_on_minerals[min(n, workers_on_minerals.amount) - 1]
                        excess_workers.append(worker)
                        
        # Oversaturated workers should be on minerals only
        for gas in self.gas_buildings.ready:
            if gas.surplus_harvesters > 0:
                workers_in_gas = self.workers.filter(
                    lambda unit: not unit.is_carrying_resource and unit.order_target == gas.tag
                )
                if workers_in_gas:
                    for n in range(gas.surplus_harvesters):
                        # prevent crash by only taking the minimum
                        worker = workers_in_gas[min(n, workers_in_gas.amount) - 1]
                        closest_mineral_patch = self.mineral_field.closest_to(worker)
                        self.do(worker.gather(closest_mineral_patch))
                        
        
        # Send oversaturated workers to fresh mineral fields
        for base in self.townhalls.ready:
            # Negative surplus harvesters indicates not enough workers
            if base.surplus_harvesters < 0:
                if excess_workers:
                    for n in range(-base.surplus_harvesters):
                        worker = excess_workers[min(n, excess_workers.amount) - 1]
                        fresh_mineral_patch = self.mineral_field.closest_to(base)
                        self.do(worker.gather(fresh_mineral_patch))
            
        # Check mineral-gas balance
        if mineral_income/max(vespene_income,1) > resource_ratio:
            # Not enough gas: Fill gas buildings
            for gas in self.gas_buildings.ready:
                # returns negative value if not enough workers
                if gas.surplus_harvesters < 0:                    
                    # Prioritize idle or oversaturated workers
                    if excess_workers:
                        # Gas should never have oversaturation
                        for n in range(-gas.surplus_harvesters):
                            worker = excess_workers[min(n, excess_workers.amount) - 1]
                            self.do(worker.gather(gas))
                    # If we don't have extra workers, grab some from minerals
                    else:
                        workers_on_minerals = self.workers.filter(
                            lambda unit: not unit.is_carrying_resource and unit.order_target in self.mineral_field.tags
                        )
                        if workers_on_minerals:
                            for n in range(-gas.surplus_harvesters):
                                # prevent crash by only taking the minimum
                                worker = workers_on_minerals[min(n, workers_on_minerals.amount) - 1]
                                self.do(worker.gather(gas))
        # Add hysterisis effect to avoid rubber banding
        elif mineral_income/max(vespene_income,1) < resource_ratio*0.95: 
            # Too much gas: Prioritize minerals
            # TODO: Decide: It won't fill gas if we already have enough gas, even if we have excess workers. Should I send the excess workers to gas?
            for base in self.townhalls.ready:
                # returns negative value if not enough workers
                if base.surplus_harvesters < 0:                    
                    # Prioritize idle or oversaturated workers
                    if excess_workers:
                        # Oversaturation is fine on minerals if we don't have fresh bases
                        for worker in excess_workers:
                            fresh_mineral_patch = self.mineral_field.closest_to(base)
                            self.do(worker.gather(fresh_mineral_patch))
                    # If we don't have extra workers, grab some from minerals
                    elif self.gas_buildings.ready:
                        workers_in_gas = self.workers.filter(
                            lambda unit: not unit.is_carrying_resource and unit.order_target in self.gas_buildings.tags
                        )
                        if workers_in_gas:
                            for n in range(-base.surplus_harvesters):
                                # prevent crash by only taking the minimum
                                worker = workers_in_gas[min(n, workers_in_gas.amount) - 1]
                                fresh_mineral_patch = self.mineral_field.closest_to(base)
                                self.do(worker.gather(fresh_mineral_patch))
        
        
        # Idle workers should mine minerals, even if its oversaturated.
        for worker in self.workers.idle:
            closest_mineral_patch = self.mineral_field.closest_to(self.townhalls.closest_to(worker))
            self.do(worker.gather(closest_mineral_patch))
            

    def calculate_effective_dps(self, own_army, enemy_army):    
        # Effective DPS = Target own unit's efficiency at killing target enemy's unit. Efficiency defined by damage done vs cost of own unit vs cost of enemy unit.
        # Modifiers to effective DPS: Splash damage increases effective DPS by factor of splash area vs enemy unit size. Bonuses to attribute and armor of enemy are included.
        # Splash modifier is currently modeled as square root of splash area/unit area.
        # If a unit is unable to hit the target, it does 0 effective DPS.
        # Effective HP is the reciprocal of enemy effective DPS against us
        # Units that cannot be damaged by the enemy would otherwise be counted as infinite hp, so cap it to avoid overvaluing flying units (and division by zero)
        # TODO: Find the best value for the effective hp cap.
        # TODO: Find best gas value multiplier. Current: 2x minerals
        # TODO: Include damage wasted in effective dps calculations
        time_to_kill_air = math.inf
        time_to_kill_ground = math.inf
        time_to_reach_air = math.inf
        time_to_reach_ground = math.inf
        
        if enemy_army.is_air: # Anti-air weapons
            if own_army.bonus_attr_air in enemy_army.attribute:
                bonus = 1
            else:
                bonus = 0
            damage_done = own_army.dmg_air + own_army.bonus_dmg_air*bonus - enemy_army.armor
            if damage_done > 0:
                # Time_to_kill = Total hp+shield/(damage done per attacks per attack speed). Does NOT consider overkill damage.
                time_to_kill_air = ((enemy_army.hp)/((own_army.attacks_air*(own_army.dmg_air + own_army.bonus_dmg_air*bonus - enemy_army.armor))/(own_army.attack_speed_air))\
                + (enemy_army.shields)/((own_army.attacks_air*(own_army.dmg_air + own_army.bonus_dmg_air*bonus - enemy_army.shield_armor))/(own_army.attack_speed_air)))
                # Effective_dps = %(hp+shield) dps                     
            
                # Add in range-kiting speed disadvantage
                if own_army.is_air: # Air vs air combat
                    # If enemy range is more than our range, add kiting disadvantage. Otherwise, no dps modifier (range advantage is a hp modifier)
                    if (enemy_army.range_air > own_army.range_air):
                        # If we can catch up to them, our effective dps is now time to kill enemy + time to reach them
                        if (own_army.movement_speed > enemy_army.movement_speed*((enemy_army.attack_speed_air - enemy_army.attack_point_air)/enemy_army.attack_speed_air)):
                            # Time to reach = Range disadvantage / Speed advantage (our speed vs enemy kiting speed)
                            time_to_reach_air = (enemy_army.range_air - own_army.range_air)/(own_army.movement_speed - enemy_army.movement_speed*((enemy_army.attack_speed_air \
                                            - enemy_army.attack_point_air)/enemy_army.attack_speed_air))
                            
                    else: # We have the same or more range than them, so they can't kite us.
                        time_to_reach_air = 0
                            
                else: # Enemy air vs our ground combat
                    # If enemy range is more than our range, add kiting disadvantage. Otherwise, no dps modifier (range advantage is a hp modifier)
                    if (enemy_army.range_ground > own_army.range_air):
                        # If we can catch up to them, our effective dps is now time to kill enemy + time to reach them
                        if (own_army.movement_speed > enemy_army.movement_speed*((enemy_army.attack_speed_ground - enemy_army.attack_point_ground)/enemy_army.attack_speed_ground)):
                            # Time to reach = Range disadvantage / Speed advantage (our speed vs enemy kiting speed)
                            time_to_reach_air = (enemy_army.range_ground - own_army.range_air)/(own_army.movement_speed - enemy_army.movement_speed*((enemy_army.attack_speed_ground \
                                            - enemy_army.attack_point_ground)/enemy_army.attack_speed_ground))
                            
                    else: # We have the same or more range than them, so they can't kite us.
                        time_to_reach_air = 0
                    
            
                # Add in splash damage modifier = Square root of no. of units that can fit into the splash radius -> 0.8*
                time_to_kill_air = time_to_kill_air/(max(0.8*(own_army.splash_area_air/(self.PI*(enemy_army.size/2)**2)), 1))
                
        if enemy_army.is_ground: # Anti-ground weapons         
            if own_army.bonus_attr_ground in enemy_army.attribute:
                bonus = 1
            else:
                bonus = 0
            damage_done = own_army.dmg_ground + own_army.bonus_dmg_ground*bonus - enemy_army.armor
            if damage_done > 0:
                # Time_to_kill = Total hp+shield/(damage done per attacks per attack speed). Does NOT consider overkill damage.
                time_to_kill_ground = ((enemy_army.hp)/((own_army.attacks_ground*(own_army.dmg_ground + own_army.bonus_dmg_ground*bonus - enemy_army.armor))/(own_army.attack_speed_ground))\
                + (enemy_army.shields)/((own_army.attacks_ground*(own_army.dmg_ground + own_army.bonus_dmg_ground*bonus - enemy_army.shield_armor))/(own_army.attack_speed_ground)))
                # Effective_dps = %(hp+shield) dps
                
                # Add in range-kiting speed disadvantage
                if own_army.is_air: # Enemy ground vs our air combat
                    # If enemy range is more than our range, add kiting disadvantage. Otherwise, no dps modifier (range advantage is a hp modifier)
                    if (enemy_army.range_air > own_army.range_ground):
                        # If we can catch up to them, our effective dps is now time to kill enemy + time to reach them
                        if (own_army.movement_speed > enemy_army.movement_speed*((enemy_army.attack_speed_air - enemy_army.attack_point_air)/enemy_army.attack_speed_air)):
                            # Time to reach = Range disadvantage / Speed advantage (our speed vs enemy kiting speed)
                            time_to_reach_ground = (enemy_army.range_air - own_army.range_ground)/(own_army.movement_speed - enemy_army.movement_speed*((enemy_army.attack_speed_air \
                                            - enemy_army.attack_point_air)/enemy_army.attack_speed_air))
                    else: # We have the same or more range than them, so they can't kite us.
                        time_to_reach_ground = 0
                    
                else: # Ground vs ground combat
                    # If enemy range is more than our range, add kiting disadvantage. Otherwise, no dps modifier (range advantage is a hp modifier)
                    if (enemy_army.range_ground > own_army.range_ground):
                        # If we can catch up to them, our effective dps is now time to kill enemy + time to reach them
                        if (own_army.movement_speed > enemy_army.movement_speed*((enemy_army.attack_speed_ground - enemy_army.attack_point_ground)/enemy_army.attack_speed_ground)):
                            # Time to reach = Range disadvantage / Speed advantage (our speed vs enemy kiting speed)
                            time_to_reach_ground = (enemy_army.range_ground - own_army.range_ground)/(own_army.movement_speed - enemy_army.movement_speed*((enemy_army.attack_speed_ground \
                                            - enemy_army.attack_point_ground)/enemy_army.attack_speed_ground))
                            
                    else: # We have the same or more range than them, so they can't kite us.
                        time_to_reach_ground = 0
                    
                
                # Add in splash damage modifier = Square root of no. of units that can fit into the splash radius -> 0.8*
                time_to_kill_ground = time_to_kill_ground/(max(0.8*(own_army.splash_area_ground/(self.PI*(enemy_army.size/2)**2)), 1))
                
        # Add in cost difference modifier. Vespene gas is counted as equally valuable as minerals. It may be worth more.
        time_to_kill_air = time_to_kill_air*((own_army.minerals + self.gas_value*own_army.vespene)/(enemy_army.minerals + self.gas_value*enemy_army.vespene))
        time_to_kill_ground = time_to_kill_ground*((own_army.minerals + self.gas_value*own_army.vespene)/(enemy_army.minerals + self.gas_value*enemy_army.vespene))
        
        # Choose the better weapon
        if (time_to_kill_air + time_to_reach_air) < (time_to_kill_ground + time_to_reach_ground):
            time_to_kill = time_to_kill_air
            time_to_reach = time_to_reach_air
        else:
            time_to_kill = time_to_kill_ground
            time_to_reach = time_to_reach_ground
            
        return [time_to_kill, time_to_reach]
        
    def calculate_threat_level(self, own_army_race, own_units, enemy_army_race, enemy_units, future_own_units = None, future_enemy_units = None):
        # Finds the best units to deal with the known enemy army, and the current threat level represented by our present units vs known enemy units.
        # For better performance, only run this function when either army size changes!
        # TODO: Improve this function. Most importantly, it needs to account for specialist units being good because they can focus on the units they are good against.
        #   Currently heavily favours tempests and stalkers, which actually isn't too bad an army comp for most scenarios.
        # TODO: We may want to know how much better the best unit is than the next best alternatives for handling tech requirements.
        
        # Own_army_race and enemy_army_race are list of units that can be made by us/enemy.
        # Own_units and enemy_units are the units we currently have and we know the enemy currently has.
        # enemy_units(enemy_army) therefore filters the existing units of the given type of enemy army unit.
        # Future_own_units and future_enemy_units are arrays of extra units we anticipate. Future_own_units[0] will give number of units of unit id 0.
        # To ensure fair comparisons, use number of future units = some_fixed_cost/unit_value_of_unit_id
        
        own_effective_dps = np.zeros((len(own_army_race),len(enemy_army_race)))
        own_effective_hp = np.zeros((len(own_army_race),len(enemy_army_race)))
        enemy_effective_dps = np.zeros((len(own_army_race),len(enemy_army_race)))
        enemy_effective_hp = np.zeros((len(own_army_race),len(enemy_army_race)))
        effective_dps_taken = np.zeros((len(own_army_race),len(enemy_army_race)))
        effective_dps_dealt = np.zeros((len(own_army_race),len(enemy_army_race)))
        
        own_time_to_kill = np.zeros((len(own_army_race),len(enemy_army_race)))
        enemy_time_to_kill = np.zeros((len(own_army_race),len(enemy_army_race)))
        
        if future_own_units is None:
            future_own_units = np.zeros(len(own_army_race))
        if future_enemy_units is None:
            future_enemy_units = np.zeros(len(enemy_army_race))
        i = 0
        for own_army in own_army_race:
            j = 0
            for enemy_army in enemy_army_race:
                # Add modifier: Number of units in combat
                # Unit size drop off: Model dps as max efficiency at units that can fit within (2*PI/4)*(range+2), after which you get sharp drop off. (for ground units only)
                # Too many units: Model excess unit dps as a square root drop off.
                # Check: Square roots in this function may cause lag. May need to find alternative.
                # Known issue: If 2 units have the same range, they will be allocated their own optimal units attacking. Similarly, they will not count as tanking for each other.
                # Conflicting units: Widow mines and marines, marauders and ghosts, thors, unsieged tanks and cyclones, stalkers and immortals, zealot/DT, ravagers and hydras, ling/ultra.
                
                # Note: Units we don't own will be registered as the initialized time to kill and dps dealt, which is currently both 0
                if (own_units(own_army) or future_own_units[i]) and (enemy_units(enemy_army) or future_enemy_units[j]):
                    optimal_units_attacking = math.floor((self.PI/2)*(max(own_army.range_ground, own_army.range_air) + 2)/own_army.size)
                    if (own_units(own_army).amount + future_own_units[i]) <= optimal_units_attacking or not own_army.is_ground:
                        own_time_to_kill[i][j] = self.own_time_to_kill[i][j].copy()\
                        *((enemy_units(enemy_army).amount + future_enemy_units[j])*(enemy_army.minerals + self.gas_value*enemy_army.vespene)\
                        /((own_units(own_army).amount + future_own_units[i])*(own_army.minerals + self.gas_value*own_army.vespene)))
                    else:                    
                        own_time_to_kill[i][j] = self.own_time_to_kill[i][j].copy()\
                        *((enemy_units(enemy_army).amount + future_enemy_units[j])*(enemy_army.minerals + self.gas_value*enemy_army.vespene)\
                        /(optimal_units_attacking + (math.sqrt(own_units(own_army).amount + future_own_units[i] - optimal_units_attacking))*(own_army.minerals + self.gas_value*own_army.vespene)))
                    
                    # Effective dps = Time it takes for each unit to reach and kill all units of another type. Weigh this for all units by their total value.
                    effective_dps_dealt[i][j] = (1/(self.own_time_to_reach[i][j].copy() + own_time_to_kill[i][j].copy()))\
                        *((enemy_units(enemy_army).amount + future_enemy_units[j])*(enemy_army.minerals + self.gas_value*enemy_army.vespene))
                
                # Calculations for enemy are symmetrical.
#                if enemy_units(enemy_army) or future_enemy_units[j]:
                    optimal_units_attacking = math.floor((self.PI/2)*(max(enemy_army.range_ground, enemy_army.range_air) + 2)/enemy_army.size)
                    if (enemy_units(enemy_army).amount + future_enemy_units[j]) <= optimal_units_attacking or not enemy_army.is_ground:
                        enemy_time_to_kill[i][j] = self.enemy_time_to_kill[i][j].copy()\
                        *((own_units(own_army).amount + future_own_units[i])*(own_army.minerals + self.gas_value*own_army.vespene)\
                        /((enemy_units(enemy_army).amount + future_enemy_units[j])*(enemy_army.minerals + self.gas_value*enemy_army.vespene)))
                    else:                    
                        enemy_time_to_kill[i][j] = self.enemy_time_to_kill[i][j].copy()\
                        *((own_units(own_army).amount + future_own_units[i])*(own_army.minerals + self.gas_value*own_army.vespene)\
                        /(optimal_units_attacking + (math.sqrt(enemy_units(enemy_army).amount + future_enemy_units[j] - optimal_units_attacking))*(enemy_army.minerals + self.gas_value*enemy_army.vespene)))
                        
                    effective_dps_taken[i][j] = (1/(self.enemy_time_to_reach[i][j].copy() + enemy_time_to_kill[i][j].copy()))\
                        *((own_units(own_army).amount + future_own_units[i])*(own_army.minerals + self.gas_value*own_army.vespene))
                
                    
                j += 1
            i += 1        
        
        # TODO: Effective dps only lasts as long as the unit is alive. This is reflected in our combat score, but does not reflect how effective hp is calculated assuming full effective dps!
        
        no_threat = 0.01
        own_effective_dps = np.sum(effective_dps_dealt.copy(),axis=1)
        own_effective_hp = 1/np.sum(np.clip(effective_dps_taken.copy(),a_min=no_threat, a_max=None),axis=1)
        enemy_effective_dps = np.sum(effective_dps_taken.copy(),axis=0)
        enemy_effective_hp = 1/np.sum(np.clip(effective_dps_dealt.copy(), a_min=no_threat, a_max=None),axis=0)
        
        # Units tanking for each other: Effective hp of unit is its time to reach + time to kill of all units shorter range than it.
        # TODO: Also factor in time to kill of other units of the same type, not just shorter ranged units
        i = 0        
        for own_army in own_army_race:
            j = 0
            for other_own_army in own_army_race:
                if max(own_army.range_ground, own_army.range_air) > max(other_own_army.range_ground, other_own_army.range_air):
                    own_effective_hp[i] += np.sum(effective_dps_taken.copy(),axis=1)[j]
                j += 1
            i += 1
        
        i = 0        
        for enemy_army in enemy_army_race:
            j = 0
            for other_enemy_army in enemy_army_race:
                if max(enemy_army.range_ground, enemy_army.range_air) > max(other_enemy_army.range_ground, other_enemy_army.range_air):
                    enemy_effective_hp[i] += np.sum(effective_dps_dealt.copy(),axis=0)[j]
                j += 1
            i += 1
        

        # Combat score = sum of each unit's effective dps* its effective hp.
        own_combat_score = np.sum(own_effective_dps*own_effective_hp)
        enemy_combat_score = np.sum(enemy_effective_dps*enemy_effective_hp)
        # Threat level = our combat score/enemy combat score
        threat_level = enemy_combat_score/own_combat_score        
        
        return threat_level
                    
    def scout_map(self, priority = 'Enemy'):
        # Assigns the next scouting location when called. This scouting location will change each time it is called, so only call it once for idle units! Spamming this will result in spazzing.
        # Input priority 'Enemy' or 'Map'
        # If priority is enemy, searches enemy owned expansions in order of closest to enemy main (including the main)
        # If priority is map, searches non-owned expansions in order of closest to us (excludes all taken bases)
        # Inspired by RoachRush
        if priority == 'Enemy':
            # If we don't have the list of bases, make one
            if not self.scout_enemy:
                self.scout_enemy = iter(self.ordered_expansions_enemy)
            self.scout_enemy_next = next(self.scout_enemy, 0)
            # If we have exhausted our list, recreate the list, updated for any new/removed bases.
            if not self.scout_enemy_next:
                self.scout_enemy = iter(self.ordered_expansions_enemy)
                self.scout_enemy_next = next(self.scout_enemy, 0)
            scout_location = self.scout_enemy_next
        if priority == 'Map':
            if not self.clear_map:
                # start with enemy starting location, then cycle through all expansions
                self.clear_map = iter(self.ordered_expansions)
            self.clear_map_next = next(self.clear_map, 0)
            if not self.clear_map_next:
                self.clear_map = iter(self.ordered_expansions)
                self.clear_map_next = next(self.clear_map, 0)                                      
            scout_location = self.clear_map_next
        return scout_location
    
    def move_circle(self, cycle = 0, radius = 10):
        # Returns a point around a circle each time this function is called. Starts at (radius, 0) and goes counter clockwise.
        # Sight range of worker is 8
        num_points = 16
        degree = 2*math.pi*cycle
        circle = (radius*math.cos(degree), radius*math.sin(degree))
        cycle += 1/num_points
        return [circle, cycle]
    
    def send_scout(self, scouting_unit):
        # Assigns the given unit to scout the enemies base. It will run a circle around each of their bases in order until it dies.
        # Input scouting unit must be global (self.scout) or it won't work.
        # TODO: If it survives a full scout, bring it home.
        try: 
            # If these attributes are not yet defined, define them.
            scouting_unit.next_base
            scouting_unit.cycle
            scouting_unit.next_location
        except:
            scouting_unit.next_base = self.scout_map(priority = 'Enemy')
            [circle, scouting_unit.cycle] = self.move_circle()
            # Circle starts from 1/num_points, not 0.
            scouting_unit.next_location = scouting_unit.next_base + circle
        # Remember: scouting_unit is a snapshot of the unit's properties, and this is why we need to search for units with scouting_unit's tag!
        if self.units.find_by_tag(scouting_unit.tag):
            self.last_scout = self.time
            scout = self.units.find_by_tag(scouting_unit.tag)
            if scout.distance_to_squared(scouting_unit.next_location) < 25:
                [circle, scouting_unit.cycle] = self.move_circle(scouting_unit.cycle)
                scouting_unit.next_location = scouting_unit.next_base + circle
                # If we have completed a circle around this base, move to the next base.
                if scouting_unit.cycle % 1 == 0:
                    scouting_unit.next_base = self.scout_map(priority = 'Enemy')
                
            if not scout.order_target == scouting_unit.next_location:        
                self.do(scout.move(scouting_unit.next_location))
    
    # Removes destroyed units from known_enemy_units and known_enemy_structures. Seems to work. Will not register units dying in fog as dead, how do we deal with this?
    async def on_unit_destroyed(self, unit_tag):
        self.known_enemy_units = self.known_enemy_units.filter(lambda unit: unit.tag != unit_tag)
        self.known_enemy_structures = self.known_enemy_structures.filter(lambda unit: unit.tag != unit_tag)
#        print(len(self.known_enemy_units))    
#        print(len(self.known_enemy_structures))
            
    async def on_step(self, iteration):
        if iteration == 0:
            # Initialize
            await self.chat_send("(glhf)(protoss)")
            self.known_enemy_units = self.enemy_units
            self.known_enemy_structures = self.enemy_structures
            self.future_enemy_units = self.enemy_units
            # Import unit list
            unit_list(self)
            
        
            # Check our race
            # For some reason if we only do this on game start, the bot will forget the races.
            if (self.race == Race.Terran):
                self.own_army_race = self.terran_army
            if (self.race == Race.Protoss):
                self.own_army_race = self.protoss_army
            if (self.race == Race.Zerg):
                self.own_army_race == self.zerg_army
            # Check enemy race. TODO: Account for enemy random race and for zerg race-switching
            if (self.enemy_race == Race.Terran):
                self.enemy_army_race = self.terran_army  
            if (self.enemy_race == Race.Protoss):
                self.enemy_army_race = self.protoss_army
            if (self.enemy_race == Race.Zerg):
                self.enemy_army_race = self.zerg_army
            
            # Calculate effective dps dealt and taken once on game start as we only need to calculate this once
            # Also assign each unit type an ID for later reference.
            self.own_time_to_kill = np.zeros((len(self.own_army_race),len(self.enemy_army_race)))
            self.own_time_to_reach = np.zeros((len(self.own_army_race),len(self.enemy_army_race)))
            self.enemy_time_to_kill = np.zeros((len(self.own_army_race),len(self.enemy_army_race)))
            self.enemy_time_to_reach = np.zeros((len(self.own_army_race),len(self.enemy_army_race)))
            self.unit_score = np.zeros(len(self.own_army_race))
            i = 0
            for own_army in self.own_army_race:
                j = 0
                own_army.id = i
                for enemy_army in self.enemy_army_race:
                    enemy_army.id = j
                    [self.own_time_to_kill[i][j], self.own_time_to_reach[i][j]] = self.calculate_effective_dps(own_army,enemy_army)
                    [self.enemy_time_to_kill[i][j], self.enemy_time_to_reach[i][j]] = self.calculate_effective_dps(enemy_army,own_army)
                    
#                    self.effective_dps_dealt[i][j] = 1/(self.own_time_to_kill[i][j] + self.own_time_to_reach[i][j])
#                    self.effective_dps_taken[i][j] = 1/(self.enemy_time_to_kill[i][j] + self.enemy_time_to_reach[i][j])
#                    print(own_army)
#                    print(enemy_army)
#                    print('Dps dealt:')
#                    print(self.effective_dps_dealt[i][j])
#                    print(self.own_time_to_kill[i][j])
#                    print(self.own_time_to_reach[i][j])
#                    print('Dps taken:')
#                    print(self.effective_dps_taken[i][j])
#                    print(self.enemy_time_to_kill[i][j])
#                    print(self.enemy_time_to_reach[i][j])
                    
                    j += 1
                i += 1
#            print('Statistics time!')
#            print('Totals:')
#            print(np.sum(self.effective_dps_dealt))
#            print(np.sum(self.effective_dps_taken))
#            print('By row:')
#            print(np.sum(self.effective_dps_dealt,axis=1))
#            print(np.sum(self.effective_dps_taken,axis=1))
#            print((np.sum(self.effective_dps_taken,axis=1))/(np.sum(self.effective_dps_dealt,axis=1)))
                
        # Find closest expansions to enemy base. Includes enemy main base. self.owned_expansions includes our main base, but we take it out here.
        # Sorting the expansion keys conveniently converts it into a list for us (it otherwise is a dict_keys object)
        # Sort it on distance to enemy for finding the enemy and distance to us for finding proxies, it isn't always just in reverse order.
        # TODO: Keep track of which bases are taken by enemy so we don't keep running scouts into them.
        self.ordered_expansions = list(set(sorted(self.expansion_locations.keys())) - set(sorted(self.owned_expansions.keys())))
        self.ordered_expansions = sorted(
            self.ordered_expansions, key=lambda expansion: expansion.distance_to(self.start_location) 
        )
        self.ordered_expansions_enemy = sorted(
            self.ordered_expansions, key=lambda expansion: expansion.distance_to(self.enemy_start_locations[0]) 
        )
        
        # State management        
        # Mineral and vespene rates are per minute, supply rates are per second
        mineral_income = self.state.score.collection_rate_minerals
        vespene_income = self.state.score.collection_rate_vespene
        
        num_warpgates = (self.structures(WARPGATE).amount + self.structures(GATEWAY).ready.amount + self.already_pending(GATEWAY))
        num_stargates = (self.structures(STARGATE).ready.amount + self.already_pending(STARGATE))
        num_robos = (self.structures(ROBOTICSFACILITY).ready.amount + self.already_pending(ROBOTICSFACILITY))
        num_production = num_warpgates + num_stargates + num_robos
        
        # Once we are nearing worker cap, remove them from the resource consumption rate.
        if self.supply_workers >= self.MAX_WORKERS - 10: 
            supply_rate = num_warpgates*self.WARPGATE_SUPPLY_RATE + num_stargates*self.STARGATE_SUPPLY_RATE + num_robos*self.ROBO_SUPPLY_RATE            
            mineral_rate = (num_warpgates*self.WARPGATE_MINERAL_RATE + num_stargates*self.STARGATE_MINERAL_RATE + num_robos*self.ROBO_MINERAL_RATE + supply_rate*100/8)*60            
        else:    
            supply_rate = num_warpgates*self.WARPGATE_SUPPLY_RATE + num_stargates*self.STARGATE_SUPPLY_RATE + num_robos*self.ROBO_SUPPLY_RATE\
            + len(self.structures(NEXUS).ready)*self.NEXUS_SUPPLY_RATE
            mineral_rate = (num_warpgates*self.WARPGATE_MINERAL_RATE + num_stargates*self.STARGATE_MINERAL_RATE + num_robos*self.ROBO_MINERAL_RATE \
            + len(self.structures(NEXUS).ready)*self.NEXUS_MINERAL_RATE + supply_rate*100/8)*60
        vespene_rate = (num_warpgates*self.WARPGATE_VESPENE_RATE + num_stargates*self.STARGATE_VESPENE_RATE + num_robos*self.ROBO_VESPENE_RATE)*60
        
        save_resources = 0
        
        # Track our units
        self.all_army = self.units.not_structure - self.units(PROBE) - self.units(INTERCEPTOR)    
        pending_units = np.zeros(len(self.own_army_race))
        for own_army in self.own_army_race:
            pending_units[own_army.id] = self.already_pending(own_army)
        future_own_units = pending_units
        
        # Track known enemy units and structures. Updated whenever we see new units and removed whenever they die in vision.
        self.known_enemy_units += self.enemy_units.filter(lambda unit: unit not in self.known_enemy_units)
        self.known_enemy_structures += self.enemy_structures.filter(lambda unit: unit not in self.known_enemy_structures)
        
            
        # Determine if we need detection for enemy cloaked/burrowed units
        # DECIDE: What about burrow roaches? Baneling bombs? Should we preemptively build detection for tech lab starports? What about for clearing creep?
        if self.known_enemy_structures.of_type(STARPORT):
            for starport in self.known_enemy_structures.of_type(STARPORT):
                if starport.has_techlab:
                    self.need_detection = True
                    return
        if self.known_enemy_units.of_type({WIDOWMINE, GHOST, BANSHEE, DARKTEMPLAR, MOTHERSHIP, LURKERMP, INFESTOR}) \
        or self.known_enemy_structures.of_type({GHOSTACADEMY, DARKSHRINE, LURKERDEN}):
            self.need_detection = True
        if self.units(OBSERVER):
            self.have_detection = True
        else:
            self.have_detection = False           
        
        # Calculate which unit is most effective vs the enemy current and future units
        
        # Micro            
        # Self.all_army = F2 
        # If we are close to max supply, attack closes enemy unit/building, or if none is visible: attack move towards enemy spawn
        # TODO: Stay away from enemies if it's a fight we cannot win
        # TODO: Poke
        # TODO: If we have longer range than enemy, maintain max range. If we have shorter range than enemy, maintain (movement_speed*0.5*attackcooldown) distance if we are faster, and hug if we are closer
        # TODO: If we have notably smaller forces but both armies are small, use workers to turn the tides
        # TODO: Preferred targets by enemy dps, armor type, armor, hp remaining, range
        # TODO: Use army abilities
        # TODO: How to deal with high ground vision and choke points?
        # Don't repeat the same command on every frame, it's unnecessary apm and causes lag!
        
        # Only recalculate threat level if either army has changed to avoid unnecessary calculations.
        if not self.last_army_supply == self.supply_army or not self.last_known_enemy_amount == len(self.known_enemy_units):
            # TODO: Implement self.future_enemy_units. Calculates how many and of what type of units we may face in the future. 
            # How many: Each time we see their bases, count their workers and bases. We can assume that they will fill up inner bases before outer bases.
            # Assume that they constantly produce workers up to the number of bases we last saw, and mine 6 gas for every 16 minerals in that ratio, regardless of worker count.
            # Integrate their worker production via composite trapezoidal rule to calculate the total money they should have
            # Deduct each extra tech building we see from the total money they should have
            # What type: Based on the tech and production we see, calculate possible tech switches and amount of units in the future. More likely to see units we already see and new tech that was added.
            future_unit_value = (mineral_income + vespene_income)/2       
            future_enemy_units = np.zeros(len(self.enemy_army_race))
            for enemy_army in self.enemy_army_race:
                future_enemy_units[enemy_army.id] +=  future_unit_value/(enemy_army.minerals + self.gas_value*enemy_army.vespene)
                
            self.threat_level = self.calculate_threat_level(self.own_army_race, self.all_army, self.enemy_army_race, self.known_enemy_units, future_own_units, future_enemy_units) 
        
        # Choose target and attack, filter out invisible targets
        targets = (self.enemy_units | self.enemy_structures).filter(lambda unit: unit.can_be_attacked and not self.units({LARVA, EGG, INTERCEPTOR}))
        defenceless_targets = self.enemy_units.of_type({SCV, PROBE, DRONE, OVERLORD, OVERSEER})\
        | self.enemy_structures.exclude_type({MISSILETURRET, PLANETARYFORTRESS, PHOTONCANNON, SPINECRAWLER, SPORECRAWLER})
        if self.all_army:
            army_center = self.all_army.center
	
	# Worker scout on gateway start
        if self.structures(GATEWAY) and not self.worker_scout:
            self.worker_scout = self.units(PROBE).closest_to(self.enemy_start_locations[0])
            
        elif self.worker_scout:
            self.send_scout(self.worker_scout)
        for army in self.all_army:            
            if army not in self.units(HIGHTEMPLAR): # Don't touch HTs until they morph archons/I make logic for spellcasting!
                if targets:
                    # If the enemy is not a threat, group up all army to attack together.
                    if True: #min(self.threat_level) < 1:
                        target = targets.closest_to(army)
                        # Unit has no attack, stay near other army units                    
                        if army.weapon_cooldown == -1 and not army.is_moving: 
                            self.do(army.move(self.all_army.closest_to(army)))                
                        # Unit has just attacked, stutter step while waiting for attack cooldown
                        elif army.weapon_cooldown > self.kite_distance/army.movement_speed and army.target_in_range(target, bonus_distance = self.kite_distance):
                            kite_pos = army.position.towards(target.position, -8)
                            self.do(army.move(kite_pos))
#                            if army in self.units(VOIDRAY):
#                                self.do(army(EFFECT_VOIDRAYPRISMATICALIGNMENT))
                        # Regroup
                        elif army.distance_to_squared(army_center) > 225 and not army.target_in_range(target) and targets not in defenceless_targets and not army.is_moving:
                            self.do(army.move(army_center))
                        # Unit is ready to attack, go attack. Use smart command (right click) instead of attack because carriers/bcs don't work with attack
                        else:
    #                        if not army.is_attacking: # Units that can attack while moving don't work well with this!
                            self.do(army.smart(target))
                    # If the enemy is currently too strong, avoid the enemy army and poke.
    #                if self.threat_level >= 1:
                        
                    # If the enemy is attacking us and we are too weak by a little bit, fight with static defense and/or pull workers.
                    
                    # If the enemy is attacking us and we are too weak by far, rat.
                    
                    
                # If we don't see any enemies, scout the map
                elif army in self.all_army.idle:# and self.supply_used > 180:     
                    self.do(army.move(self.scout_map(priority = 'Map')))
        
                    
        # Morph archons            
        if self.units(HIGHTEMPLAR).idle.ready.amount >= 2:
            ht1 = self.units(HIGHTEMPLAR).idle.ready.random
            ht2 = next((ht for ht in self.units(HIGHTEMPLAR).idle.ready if ht.tag != ht1.tag), None)
            from s2clientprotocol import raw_pb2 as raw_pb
            from s2clientprotocol import sc2api_pb2 as sc_pb
            command = raw_pb.ActionRawUnitCommand(
                    ability_id=MORPH_ARCHON.value,
                    unit_tags=[ht1.tag, ht2.tag],
                    queue_command=False
                )
            action = raw_pb.ActionRaw(unit_command=command)
            await self._client._execute(action=sc_pb.RequestAction(
                    actions=[sc_pb.Action(action_raw=action)]
                ))
        
        #Find the buildings that are building, and have low health. Low health = less than 10% total hp
        for building in self.structures.filter(lambda x: x.build_progress < 1 and (x.health + x.shield)/(x.health_max + x.shield_max) < 0.1):
            self.do(building(CANCEL))
            
        # Macro
        if not self.townhalls.ready:
            # Attack with all workers if we don't have any nexuses left, attack-move on enemy spawn (doesn't work on 4 player map) so that probes auto attack on the way
            for worker in self.workers:
                self.do(worker.attack(self.enemy_start_locations[0]))
            return
        else:
            nexus = self.townhalls.ready.random


        # If this random nexus is not idle and has not chrono buff, chrono it with one of the nexuses we have. If we are near saturation, save the chrono.
        # TODO: Chrono important units (i.e. first 2 colossus, or tempest vs brood lords) or upgrades
        if not nexus.is_idle and not nexus.has_buff(CHRONOBOOSTENERGYCOST) and self.supply_workers < self.MAX_WORKERS - 25:
            nexuses = self.structures(NEXUS)
            abilities = await self.get_available_abilities(nexuses)
            for loop_nexus, abilities_nexus in zip(nexuses, abilities):
                if EFFECT_CHRONOBOOSTENERGYCOST in abilities_nexus:
                    self.do(loop_nexus(EFFECT_CHRONOBOOSTENERGYCOST, nexus))
                    break
			
        # Distribute workers in gas and across bases. Takes into account our mineral-gas expenditure ratio.
        # We don't need to check for oversaturation so often.
        if iteration%(self.ITERATIONS_PER_MINUTE/4) == 0:
            if vespene_rate:
                self.resource_ratio = mineral_rate/vespene_rate
            else:
                self.resource_ratio = 4            
            await self.better_distribute_workers(self.resource_ratio)
        # Idle workers should mine minerals, even if its oversaturated.
        # We do need to check for idle workers frequently. Workers that we need for other purposes should be kept moving or patroling to avoid pulling them to mine.
        for worker in self.workers.idle:
            closest_mineral_patch = self.mineral_field.closest_to(self.townhalls.closest_to(worker))
            self.do(worker.gather(closest_mineral_patch))
            
        

        # Choose building placement
        # Pylon positions = Walling placement, then next to unpowered buildings, then next to nexus without pylons, then next to other buildings. Avoid mineral line. TODO: Spotter pylons
        if await self.can_place(PYLON, self.main_base_ramp.protoss_wall_pylon):
            pylon_placement = self.main_base_ramp.protoss_wall_pylon
        else:
            random_building = self.structures({NEXUS, ASSIMILATOR, PYLON}).random
            pylon_placement = await self.find_placement(PYLON, near=random_building.position, placement_step=5)
#            pylon_placement = await self.find_placement(PYLON, near=nexus.position.towards(self.game_info.map_center, 5))
            
        # Building placement = Walling placement, then ... next to any pylon? 
        # Production -> Any pylon, Tech -> Furthest from enemy base, defence structures -> Nearest to enemy base. Prioritize plugging the wall, but not with defences        
        if self.structures(PYLON).ready:
            pylon = self.structures(PYLON).ready.random
            proxy = self.structures(PYLON).closest_to(self.enemy_start_locations[0])
            hidden = self.structures(PYLON).furthest_to(self.enemy_start_locations[0])                
            if await self.can_place(GATEWAY, self.main_base_ramp.protoss_wall_buildings[0]):
                building_placement = self.main_base_ramp.protoss_wall_buildings[0]
                tech_placement = self.main_base_ramp.protoss_wall_buildings[0]
            elif await self.can_place(GATEWAY, self.main_base_ramp.protoss_wall_buildings[1]):
                building_placement = self.main_base_ramp.protoss_wall_buildings[1]
                tech_placement = self.main_base_ramp.protoss_wall_buildings[1]                
            else:
                building_placement = await self.find_placement(GATEWAY, near=pylon.position)
                tech_placement = await self.find_placement(CYBERNETICSCORE, near=hidden.position)               
            
            defence_placement_small = await self.find_placement(SHIELDBATTERY, near=proxy.position)                
            tech_placement_small = await self.find_placement(DARKSHRINE, near=hidden.position)
            warpin_placement = await self.find_placement(WARPGATETRAIN_STALKER, near=proxy.position.to2.random_on_distance(4), placement_step = 1)
        

        # Calculate rate of supply consumption to supply remaining and preemptively build a dynamic amount of supply. Stop once we reach the 200 supply cap.
        # TODO: Include pending supply from town halls into supply calculations.
        if (self.supply_left + self.already_pending(PYLON)*8) < supply_rate*self.SUPPLY_BUILD_TIME and (self.supply_cap + self.already_pending(PYLON)*8) <200:
            # Always check if you can afford something before you build it
            if self.can_afford(PYLON):
                await self.build(PYLON, near=pylon_placement)

        # Train probe on nexuses that are undersaturated until worker cap 
        if self.supply_workers + self.already_pending(PROBE) < min(self.townhalls.amount*16 + ideal_gas_buildings*3, self.MAX_WORKERS) and nexus.is_idle:
            if self.can_afford(PROBE):
                self.do(nexus.train(PROBE), subtract_cost=True, subtract_supply=True)

        # If we are about to reach saturation on existing town halls, expand        
        # TODO: Send worker to expansion location just in time for having money for town hall
        if self.supply_workers + self.NEXUS_SUPPLY_RATE*self.NEXUS_BUILD_TIME >= \
        (self.townhalls.ready.amount + self.already_pending(NEXUS))*16 + max(ideal_gas_buildings, self.townhalls.amount*2)*3:
            if self.can_afford(NEXUS):
                await self.expand_now()
            # If we need an expansion but don't have resources, save for it unless we are in danger
            elif self.threat_level < 1.1:
                save_resources = 1
        # If we have reached max workers and have a lot more minerals than gas, expand for more gas.
        elif self.supply_workers > self.MAX_WORKERS-10 and self.minerals > 1000 and ideal_gas_buildings > self.townhalls.amount*2 and self.already_pending(NEXUS) == 0:
            await self.expand_now()
            
        # Build gas near completed nexuses once we have a cybercore (does not need to be completed)
        # TODO: Have weightage on earlier gas for tech rush
        
        if (self.structures(ASSIMILATOR).ready.amount + self.already_pending(ASSIMILATOR)) < ideal_gas_buildings and num_production:
            for nexus in self.townhalls.ready:
                vgs = self.vespene_geyser.closer_than(10, nexus)                
                for vg in vgs:
                    if not self.can_afford(ASSIMILATOR):
                        break                    
                    if not self.gas_buildings.closer_than(1,vg):
                        worker = self.select_build_worker(vg.position)
                        self.do(worker.build(ASSIMILATOR, vg), subtract_cost=True)
                        self.do(worker.stop(queue=True))
                        break
#                        

                
        # Calculate best unit to make. Only recalculate if either army has changed to avoid unnecessary calculations.
        if not self.last_army_supply == self.supply_army or not self.last_known_enemy_amount == len(self.known_enemy_units):
            future_unit_value = (mineral_rate + vespene_rate)
            self.unit_score = np.zeros(len(self.own_army_race))
            i = 0
            for own_army in self.own_army_race:
                future_own_units = pending_units.copy()        
                future_own_units[i] += future_unit_value/(own_army.minerals + self.gas_value*own_army.vespene)
                self.unit_score[own_army.id] = self.calculate_threat_level(self.own_army_race, self.all_army, self.enemy_army_race, self.known_enemy_units, future_own_units, future_enemy_units)
                i += 1

        # Tech up
        # TODO: If we need a high-tech unit more quickly, have a weightage for tech-rushing that unit
        # TODO: Consider how much army we currently have to determine if it is safe to tech up.
        # TODO: Include every upgrade in the game, and consider how many of the unit we plan to use in the future (i.e. start charge before we have zealots if we want them soon)
        warpgate_tech = [ARCHON.id] # Disabled dark templars until I figure out a fix for threat level!
        stargate_tech = [TEMPEST.id, CARRIER.id]
        robo_tech = [COLOSSUS.id, DISRUPTOR.id]
        self.best_unit = np.argmin(self.unit_score)
        
        if self.structures(PYLON).ready:
            pylon = self.structures(PYLON).ready.random
            # If we have a gateway completed, build cyber core
            if self.structures(GATEWAY).ready or self.structures(WARPGATE):
                if not self.structures(CYBERNETICSCORE):
                    if self.can_afford(CYBERNETICSCORE) and self.already_pending(CYBERNETICSCORE) == 0:
                        await self.build(CYBERNETICSCORE, near=tech_placement)
                else:
                    # If cybercore is ready, research warpgate
                    if (
                            self.structures(CYBERNETICSCORE).ready
                            and self.can_afford(RESEARCH_WARPGATE)
                            and self.already_pending_upgrade(WARPGATERESEARCH) == 0
                    ):
                        ccore = self.structures(CYBERNETICSCORE).ready.first
                        self.do(ccore(RESEARCH_WARPGATE), subtract_cost=True)
            
            # If we have no gateway, build gateway
            elif self.can_afford(GATEWAY) and self.structures(GATEWAY).amount == 0:
                await self.build(GATEWAY, near=building_placement)
            
            # Tech: Upgrade warpgate units                        
            if self.best_unit in warpgate_tech:
                if self.structures(CYBERNETICSCORE).ready:
                    if not self.structures(TWILIGHTCOUNCIL):
                        if self.can_afford(TWILIGHTCOUNCIL) and self.already_pending(TWILIGHTCOUNCIL) == 0:
                            await self.build(TWILIGHTCOUNCIL, near=tech_placement)
                            
                    else:
                        if self.structures(TWILIGHTCOUNCIL).ready:
                            twilight = self.structures(TWILIGHTCOUNCIL).ready.first
                            # If we have lots of zealot/stalker/adept, research charge/blink/glaives
                            if self.units(ZEALOT).amount > 5:
                                if self.can_afford(RESEARCH_CHARGE) and self.already_pending_upgrade(CHARGE) == 0:
                                    self.do(twilight.research(CHARGE))
                                elif not self.can_afford(RESEARCH_CHARGE):
                                    save_resources = 1
                            if self.units(STALKER).amount > 5:
                                if self.can_afford(RESEARCH_BLINK) and self.already_pending_upgrade(BLINKTECH) == 0:
                                    self.do(twilight.research(BLINKTECH))
                                elif not self.can_afford(RESEARCH_BLINK):
                                    save_resources = 1
                            if self.units(ADEPT).amount > 5:
                                if self.can_afford(RESEARCH_ADEPTRESONATINGGLAIVES) and self.already_pending_upgrade(ADEPTPIERCINGATTACK) == 0:
                                    self.do(twilight.research(ADEPTPIERCINGATTACK))
                                elif not self.can_afford(RESEARCH_ADEPTRESONATINGGLAIVES):
                                    save_resources = 1
                                    
                            # If we want archons, build templar archives
                            if self.best_unit == ARCHON.id and self.structures(TWILIGHTCOUNCIL).ready:
                                if not self.structures(TEMPLARARCHIVE):
                                    if self.can_afford(TEMPLARARCHIVE) and self.already_pending(TEMPLARARCHIVE) == 0:
                                        await self.build(TEMPLARARCHIVE, near=tech_placement)
                                        
                            # If we want DTs, build dark shrine
                            # TODO: Or if we are maxed out or if they have no detection
                            if self.best_unit == DARKTEMPLAR.id and self.structures(TWILIGHTCOUNCIL).ready:
                                if not self.structures(DARKSHRINE):
                                    if self.can_afford(DARKSHRINE) and self.already_pending(DARKSHRINE) == 0:
                                        await self.build(DARKSHRINE, near=tech_placement_small)
            
            # Tech: T3 stargate                                        
            if self.best_unit in stargate_tech:
                if self.structures(STARGATE).ready:
                    if not self.structures(FLEETBEACON):
                        if self.can_afford(FLEETBEACON) and self.already_pending(FLEETBEACON) == 0:
                            await self.build(FLEETBEACON, near=tech_placement)
                        elif not self.can_afford(FLEETBEACON):
                            save_resources = 1
                # If we have no stargate, make one
                elif not self.structures(STARGATE):
                    if self.can_afford(STARGATE) and self.already_pending(STARGATE) == 0:
                        await self.build(STARGATE, near=building_placement)
                        
            # Tech: T3 robo    
            if self.best_unit in robo_tech:                
                if self.structures(ROBOTICSFACILITY).ready:
                    if not self.structures(ROBOTICSBAY):
                        if self.can_afford(ROBOTICSBAY) and self.already_pending(ROBOTICSBAY) == 0:
                            await self.build(ROBOTICSBAY, near=tech_placement)
                        elif not self.can_afford(ROBOTICSBAY):
                            save_resources = 1
                    # Research thermal lance        
                    elif self.structures(ROBOTICSBAY).ready:
                        robobay = self.structures(ROBOTICSBAY).ready.first
                        if self.can_afford(RESEARCH_EXTENDEDTHERMALLANCE) and self.already_pending_upgrade(EXTENDEDTHERMALLANCE) == 0:
                            self.do(robobay.research(EXTENDEDTHERMALLANCE))
                # If we have no robo facility, make one
                elif not self.structures(ROBOTICSFACILITY):
                    if self.can_afford(ROBOTICSFACILITY) and self.already_pending(ROBOTICSFACILITY) == 0:
                        await self.build(ROBOTICSFACILITY, near=building_placement)
                
            # Make detection if needed
            if self.need_detection and not self.have_detection and not self.already_pending(OBSERVER):
                if self.structures(ROBOTICSFACILITY).ready:
                    for rb in self.structures(ROBOTICSFACILITY).idle:
                        if self.can_afford(OBSERVER):
                            self.do(rb.train(OBSERVER), subtract_cost=True, subtract_supply=True)
                        elif not self.can_afford(OBSERVER):
                            save_resources = 1
                elif not self.structures(ROBOTICSFACILITY):
                    if self.can_afford(ROBOTICSFACILITY) and self.already_pending(ROBOTICSFACILITY) == 0:
                        await self.build(ROBOTICSFACILITY, near=building_placement)
                    elif not self.can_afford(ROBOTICSFACILITY):
                        save_resources = 1
        

            # If we don't need to save resources, make stuff
            warp_try = 0
            if (save_resources == 0 or self.minerals > 450): # Be careful to make sure that save_resources is only asserted when we cannot afford something!
                # Run through all our production buildings and make sure they are being used
                # Stargate units
                if self.structures(FLEETBEACON).ready: #Taking out oracles until I figure out logic for their energy management
                    available_stargate_units = [PHOENIX.id, VOIDRAY.id, TEMPEST.id, CARRIER.id]
                else:
                    available_stargate_units = [PHOENIX.id, VOIDRAY.id]
                self.best_unit = self.own_army_race[available_stargate_units[np.argmin(self.unit_score[available_stargate_units])]]
                # Update resource spending rate to be based on what units we are making
                self.STARGATE_MINERAL_RATE = self.best_unit.minerals/self.best_unit.build_time
                self.STARGATE_VESPENE_RATE = self.best_unit.vespene/self.best_unit.build_time
                self.STARGATE_SUPPLY_RATE = self.best_unit.supply/self.best_unit.build_time
                for sg in self.structures(STARGATE).idle:
                    if self.can_afford(self.best_unit):
                        self.do(sg.train(self.best_unit), subtract_cost=True, subtract_supply=True)
                
                # Robo units. TODO: Flag to produce observers and warp prism
                if self.structures(ROBOTICSBAY).ready:
                    available_robo_units = [IMMORTAL.id, COLOSSUS.id, DISRUPTOR.id]
                    self.best_unit = self.own_army_race[available_robo_units[np.argmin(self.unit_score[available_robo_units])]]
                else:
                    available_robo_units = [IMMORTAL.id]
                    self.best_unit = IMMORTAL
                # Update resource spending rate to be based on what units we are making
                self.ROBO_MINERAL_RATE = self.best_unit.minerals/self.best_unit.build_time
                self.ROBO_VESPENE_RATE = self.best_unit.vespene/self.best_unit.build_time
                self.ROBO_SUPPLY_RATE = self.best_unit.supply/self.best_unit.build_time                
                for rb in self.structures(ROBOTICSFACILITY).idle:
                    if self.can_afford(self.best_unit):
                        self.do(rb.train(self.best_unit), subtract_cost=True, subtract_supply=True)
                
                # Warpgate units. Prioritize robo and stargate units.
                available_warpgate_units = [ZEALOT.id]
                if self.structures(CYBERNETICSCORE).ready:
                    available_warpgate_units.append(STALKER.id)
#                    available_warpgate_units.append(SENTRY.id) # Disabled sentries until I figure out a fix for threat level
                    available_warpgate_units.append(ADEPT.id)
                if self.structures(TEMPLARARCHIVE).ready:
                    available_warpgate_units.append(ARCHON.id)
                if self.structures(DARKSHRINE).ready:
                    available_warpgate_units.append(DARKTEMPLAR.id)
                self.best_unit = self.own_army_race[available_warpgate_units[np.argmin(self.unit_score[available_warpgate_units])]]
                # Update resource spending rate to be based on what units we are making
                self.WARPGATE_MINERAL_RATE = self.best_unit.minerals/self.best_unit.build_time
                self.WARPGATE_VESPENE_RATE = self.best_unit.vespene/self.best_unit.build_time
                self.WARPGATE_SUPPLY_RATE = self.best_unit.supply/self.best_unit.build_time
                
                if not self.structures(STARGATE).ready.idle and not self.structures(ROBOTICSFACILITY).ready.idle:                
                    if self.structures(PYLON).ready:
                        proxy = self.structures(PYLON).closest_to(self.enemy_start_locations[0])
                    # TODO: Warp-in at power field closest to enemy, but at a minimum distance away. Include warp prism power fields.
                    warp_ready = 0
                    for wg in self.structures(WARPGATE).ready:
                        abilities = await self.get_available_abilities(wg)
                        if WARPGATETRAIN_ZEALOT in abilities:
                            while warpin_placement is None:
                                # pick random other pylon
                                random_pylon = self.structures(PYLON).random
                                pos = random_pylon.position.to2.random_on_distance(4)
                                placement = await self.find_placement(WARPGATETRAIN_STALKER, pos, placement_step=1)
                                warp_try +=1
                                if warp_try >= 5:
                                    break
                            # If we have an odd number of high templars, add another to make a complete archon (since we don't have spellcasting logic yet)
                            if (self.best_unit == ARCHON or self.units(HIGHTEMPLAR).amount%2 == 1) and self.can_afford(HIGHTEMPLAR):
                                self.do(wg.warp_in(HIGHTEMPLAR, warpin_placement), subtract_cost=True, subtract_supply=True)
                            elif self.can_afford(self.best_unit):
                                self.do(wg.warp_in(self.best_unit, warpin_placement), subtract_cost=True, subtract_supply=True)
                            else:
                                warp_ready += 1
                                
                    # If warp gate is not yet researched, use gateways. Warp gate research takes 100s, gateway units take ~30s to build, already_pending returns % completion, with 1 on completion
                    if self.already_pending_upgrade(WARPGATERESEARCH) < 0.75 :
                        for gw in self.structures(GATEWAY).idle:
                            if self.can_afford(STALKER):
                                self.do(gw.train(STALKER), subtract_cost=True, subtract_supply = True)
                    # If all our production is not idle and we have more income than expenditure, add more production buildings. If we are supply capped, add production up to ~2x income rate                
                    # TODO: We need to scout our opponent to decide how early we need defences.
                    # Currently: Gateway->Nexus->Cyber->Stargate->Shield batteries
                    # If we let the bot build production before cyber is started, it goes gateway->gateway->cyber->nexus->stargate and doesn't get shield batteries
                    if not self.structures(GATEWAY).ready.idle and not warp_ready:# and self.structures(CYBERNETICSCORE):
                        if not self.structures(CYBERNETICSCORE).ready:                            
                            available_warpgate_units.append(STALKER.id)
                            available_warpgate_units.append(SENTRY.id)
                            available_warpgate_units.append(ADEPT.id)
                        if self.structures(FLEETBEACON):
                            available_stargate_units = [PHOENIX.id, VOIDRAY.id, TEMPEST.id, CARRIER.id]
                        if self.structures(ROBOTICSBAY):
                            available_robo_units = [IMMORTAL.id, COLOSSUS.id, DISRUPTOR.id]
                            
                        available_units = available_warpgate_units                            
                        if self.structures(CYBERNETICSCORE).ready:
                            for unit in available_robo_units:
                                available_units.append(unit)
                            for unit in available_stargate_units:
                                available_units.append(unit)
                             
                        # TODO: Dynamically modify income-expenditure ratio based on stage of the game (teching and expanding are not counted in expenditure but this is a significant cost early).
                        
                        if mineral_income*0.8 > mineral_rate or (self.threat_level > 1 and mineral_income*0.9 > mineral_rate) or (self.supply_used > 190 and mineral_income*1.5 > mineral_rate):
                            self.best_unit = self.own_army_race[available_units[np.argmin(self.unit_score[available_units])]]                            
                            if self.best_unit.id in available_warpgate_units:
                                if self.can_afford(GATEWAY):
                                    await self.build(GATEWAY, near=building_placement)
                            if self.best_unit.id in available_robo_units:
                                if self.can_afford(ROBOTICSFACILITY):
                                    await self.build(ROBOTICSFACILITY, near=building_placement)
                            if self.best_unit.id in available_stargate_units:
                                if self.can_afford(STARGATE):
                                    await self.build(STARGATE, near=building_placement)
                        # We've already added extra production and are using them, but they still have an advantage.                                
                        elif self.threat_level > 1.2: # 1 extra shield battery for every 0.2 threat level advantage they have (1.4,1.6...)
                            if (self.structures(SHIELDBATTERY).amount + self.already_pending(SHIELDBATTERY)) < min(((self.threat_level - 1.2)*5), 5):
                                if self.can_afford(SHIELDBATTERY):
                                    await self.build(SHIELDBATTERY, near=defence_placement_small)
                        
        self.last_army_supply = self.supply_army
        self.last_known_enemy_amount = len(self.known_enemy_units)
        # Debug info, print every minute
        if iteration%165 == 0:
            print("Income")
            print(mineral_income)
            print(vespene_income)
            print(mineral_rate)
            print(vespene_rate)
            print(num_warpgates)
            print(num_stargates)
            print(num_robos)
            print("Unit info")
            print(self.threat_level)
            
def main():
    sc2.run_game(
        sc2.maps.get("ZenLE"),
        #[Human(Race.Terran, name="PunyHuman"),Bot(Race.Protoss, TheUnseenz(), name="TheUnseenz")],
        [Bot(Race.Protoss, TheUnseenz(), name="TheUnseenz"), Computer(Race.Zerg, Difficulty.CheatInsane)],
        realtime=False,
    )



if __name__ == "__main__":
    main()
