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
#from unit_list import UnitList as unitList



class MacroBot(sc2.BotAI):
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
        self.gas_value = 1.5
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
        
        self.effective_dps_dealt = None
        self.effective_dps_taken = None
        self.available_units = None
        self.available_warpgate_units = None
        self.available_robo_units = None
        self.available_stargate_units = None
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
        
#    def unit_list(self): # Moved to another file
        
    # When an upgrade is complete/we notice an enemy upgrade completed, update unit stats by stats += amount.
#    async def on_upgrade_complete(self, upgrade):
    

    def calculate_effective_dps(self, own_army, enemy_army):    
        # Effective DPS = Target own unit's efficiency at killing target enemy's unit. Efficiency defined by damage done vs cost of own unit vs cost of enemy unit.
        # Modifiers to effective DPS: Splash damage increases effective DPS by factor of splash area vs enemy unit size. Bonuses to attribute and armor of enemy are included.
        # Splash modifier is currently modeled as square root of splash area/unit area.
        # If a unit is unable to hit the target, it does 0 effective DPS.
        # Effective HP is the reciprocal of enemy effective DPS against us
        # Units that cannot be damaged by the enemy would otherwise be counted as infinite hp, so cap it to avoid overvalueing flying units (and division by zero)
        # TODO: Find the best value for the effective hp cap. Current cap: 40s to die on equal costs.
        # TODO: Find best gas value multiplier. Current: 2x minerals
        # TODO: Include damage wasted in effective dps calculations
        # TODO: Update unit stats with their upgrades as the game progresses.
        # TODO: Perhaps we can calculate the stat table once at game start and as units are upgraded, and use those variables for threat level calculations instead of constantly calculating?
        if enemy_army.is_air: # Anti-air weapons
            if own_army.bonus_attr_air in enemy_army.attribute:
                bonus = 1
            else:
                bonus = 0
            damage_done = own_army.dmg_air + own_army.bonus_dmg_air*bonus - enemy_army.armor
            if damage_done > 0:
                # Time_to_kill = Total hp+shield/(damage done per attacks per attack speed). Does NOT consider overkill damage.
                time_to_kill = ((enemy_army.hp)/((own_army.attacks_air*(own_army.dmg_air + own_army.bonus_dmg_air*bonus - enemy_army.armor))/(own_army.attack_speed_air))\
                + (enemy_army.shields)/((own_army.attacks_air*(own_army.dmg_air + own_army.bonus_dmg_air*bonus - enemy_army.shield_armor))/(own_army.attack_speed_air)))
                # Effective_dps = %(hp+shield) dps
                effective_dps_air = 1/time_to_kill                        
            
                # Add in range-kiting speed disadvantage
                if own_army.is_air: # Air vs air combat
                    # If enemy range is more than our range, add kiting disadvantage. Otherwise, no dps modifier (range advantage is a hp modifier)
                    if (enemy_army.range_air > own_army.range_air):
                        # If we can catch up to them, our effective dps is now time to kill enemy + time to reach them
                        if (own_army.movement_speed > enemy_army.movement_speed*((enemy_army.attack_speed_air - enemy_army.attack_point_air)/enemy_army.attack_speed_air)):
                            # Time to reach = Range disadvantage / Speed advantage (our speed vs enemy kiting speed)
                            time_to_reach = (enemy_army.range_air - own_army.range_air)/(own_army.movement_speed - enemy_army.movement_speed*((enemy_army.attack_speed_air \
                                            - enemy_army.attack_point_air)/enemy_army.attack_speed_air))
                            
                            effective_dps_air = 1/(time_to_reach + time_to_kill)
                        # If we can't catch up to them, we effectively cannot reach them and thus cannot damage them.
                        else: 
                            effective_dps_air = 0
                else: # Enemy air vs our ground combat
                    # If enemy range is more than our range, add kiting disadvantage. Otherwise, no dps modifier (range advantage is a hp modifier)
                    if (enemy_army.range_ground > own_army.range_air):
                        # If we can catch up to them, our effective dps is now time to kill enemy + time to reach them
                        if (own_army.movement_speed > enemy_army.movement_speed*((enemy_army.attack_speed_ground - enemy_army.attack_point_ground)/enemy_army.attack_speed_ground)):
                            # Time to reach = Range disadvantage / Speed advantage (our speed vs enemy kiting speed)
                            time_to_reach = (enemy_army.range_ground - own_army.range_air)/(own_army.movement_speed - enemy_army.movement_speed*((enemy_army.attack_speed_ground \
                                            - enemy_army.attack_point_ground)/enemy_army.attack_speed_ground))
                            
                            effective_dps_air = 1/(time_to_reach + time_to_kill)
                        # If we can't catch up to them, we effectively cannot reach them and thus cannot damage them.
                        else: 
                            effective_dps_air = 0
            
                # Add in splash damage modifier = Square root of no. of units that can fit into the splash radius -> 0.8*
                effective_dps_air = max(0.8*(own_army.splash_area_air/(self.PI*(enemy_army.size/2)**2)), 1) * effective_dps_air
            # If damage_done = 0, either we can't hit air or they have equal armor to our damage, in which case attacking is futile despite still doing 0.5 damage.
            else: 
                effective_dps_air = 0
        # Enemy is not air, so air dps = 0                            
        else: 
            effective_dps_air = 0
        if enemy_army.is_ground: # Anti-ground weapons         
            if own_army.bonus_attr_ground in enemy_army.attribute:
                bonus = 1
            else:
                bonus = 0
            damage_done = own_army.dmg_ground + own_army.bonus_dmg_ground*bonus - enemy_army.armor
            if damage_done > 0:
                # Time_to_kill = Total hp+shield/(damage done per attacks per attack speed). Does NOT consider overkill damage.
                time_to_kill = ((enemy_army.hp)/((own_army.attacks_ground*(own_army.dmg_ground + own_army.bonus_dmg_ground*bonus - enemy_army.armor))/(own_army.attack_speed_ground))\
                + (enemy_army.shields)/((own_army.attacks_ground*(own_army.dmg_ground + own_army.bonus_dmg_ground*bonus - enemy_army.shield_armor))/(own_army.attack_speed_ground)))
                # Effective_dps = %(hp+shield) dps
                effective_dps_ground = 1/time_to_kill                        
                
                # Add in range-kiting speed disadvantage
                if own_army.is_air: # Enemy ground vs our air combat
                    # If enemy range is more than our range, add kiting disadvantage. Otherwise, no dps modifier (range advantage is a hp modifier)
                    if (enemy_army.range_air > own_army.range_ground):
                        # If we can catch up to them, our effective dps is now time to kill enemy + time to reach them
                        if (own_army.movement_speed > enemy_army.movement_speed*((enemy_army.attack_speed_air - enemy_army.attack_point_air)/enemy_army.attack_speed_air)):
                            # Time to reach = Range disadvantage / Speed advantage (our speed vs enemy kiting speed)
                            time_to_reach = (enemy_army.range_air - own_army.range_ground)/(own_army.movement_speed - enemy_army.movement_speed*((enemy_army.attack_speed_air \
                                            - enemy_army.attack_point_air)/enemy_army.attack_speed_air))
                            
                            effective_dps_ground = 1/(time_to_reach + time_to_kill)
                        # If we can't catch up to them, we effectively cannot reach them and thus cannot damage them.
                        else: 
                            effective_dps_ground = 0
                else: # Ground vs ground combat
                    # If enemy range is more than our range, add kiting disadvantage. Otherwise, no dps modifier (range advantage is a hp modifier)
                    if (enemy_army.range_ground > own_army.range_ground):
                        # If we can catch up to them, our effective dps is now time to kill enemy + time to reach them
                        if (own_army.movement_speed > enemy_army.movement_speed*((enemy_army.attack_speed_ground - enemy_army.attack_point_ground)/enemy_army.attack_speed_ground)):
                            # Time to reach = Range disadvantage / Speed advantage (our speed vs enemy kiting speed)
                            time_to_reach = (enemy_army.range_ground - own_army.range_ground)/(own_army.movement_speed - enemy_army.movement_speed*((enemy_army.attack_speed_ground \
                                            - enemy_army.attack_point_ground)/enemy_army.attack_speed_ground))
                            
                            effective_dps_ground = 1/(time_to_reach + time_to_kill)
                        # If we can't catch up to them, we effectively cannot reach them and thus cannot damage them.
                        else: 
                            effective_dps_ground = 0
                
                # Add in splash damage modifier = Square root of no. of units that can fit into the splash radius -> 0.8*
                effective_dps_ground = max(0.8*(own_army.splash_area_ground/(self.PI*(enemy_army.size/2)**2)), 1) * effective_dps_ground
            else:
                effective_dps_ground = 0
        # Enemy is not ground, so ground dps = 0
        else:
            effective_dps_ground = 0
            
        # Add in cost difference modifier. Vespene gas is counted as equally valuable as minerals. It may be worth more.
        effective_dps = ((enemy_army.minerals + self.gas_value*enemy_army.vespene)/(own_army.minerals + self.gas_value*own_army.vespene))*max(effective_dps_air,effective_dps_ground)
        return effective_dps
        
    def calculate_threat_level(self, own_army_race, own_units, enemy_army_race, enemy_units):
        # Finds the best units to deal with the known enemy army, and the current threat level represented by our present units vs known enemy units.
        # TODO: Improve this function. Most importantly, it needs to account for the existing units and that specialist units are good because they can focus on the units they are good against.
        #   Currently heavily favours tempests and stalkers, which actually isn't too bad an army comp for most scenarios.
        #   Synergy and foresight? Consider the strengths of 2 units at a time, rather than 1. Ideally, consider n extra units as a combined strength, but this would take too much compute.
        #   Tanking for other units and dps drop as each unit dies: Dps dealt lasts as long as the unit stays alive, and units survive in order of their range.
        #   Size matters: The shorter the range and the bigger the unit, the fewer numbers can attack at once. Conversely, the bigger the enemy unit, the more units can hit it.
        # TODO: We may want to know how much better the best unit is than the next best alternatives for handling tech requirements.
        # Own_army_race and enemy_army_race are list of units that can be made by us/enemy.
        # Own_units and enemy_units are the units we currently have and we think the enemy currently has.
        # enemy_units(enemy_army) therefore filters the existing units of the given type of enemy army unit.
        
        effective_dps_dealt = np.zeros((len(own_army_race),len(enemy_army_race)))
        effective_dps_taken = np.zeros((len(own_army_race),len(enemy_army_race)))
        effective_dps_dealt_test = np.zeros((len(own_army_race),len(enemy_army_race)))
        effective_dps_taken_test = np.zeros((len(own_army_race),len(enemy_army_race)))
        threat_level = np.zeros(len(own_army_race))
        i = 0
        for own_army in own_army_race:
            j = 0
            for enemy_army in enemy_army_race:
                
                
                effective_dps_dealt[i][j] = (self.calculate_effective_dps(own_army, enemy_army))\
                *(max(enemy_units(enemy_army).amount,0.2)*(enemy_army.minerals + self.gas_value*enemy_army.vespene))\
                *(max(own_units(own_army).amount,0.2)*(own_army.minerals + self.gas_value*own_army.vespene))
                effective_dps_taken[i][j] = (self.calculate_effective_dps(enemy_army, own_army))\
                *(max(enemy_units(enemy_army).amount,0.2)*(enemy_army.minerals + self.gas_value*enemy_army.vespene))\
                *(max(own_units(own_army).amount,0.2)*(own_army.minerals + self.gas_value*own_army.vespene))
                
                
                effective_dps_dealt_test[i][j] = (self.calculate_effective_dps(own_army, enemy_army))\
                *(max(enemy_units(enemy_army).amount,0.2)*(enemy_army.minerals + self.gas_value*enemy_army.vespene))\
                *((own_units(own_army).amount + 1)*(own_army.minerals + self.gas_value*own_army.vespene))
                effective_dps_taken_test[i][j] = (self.calculate_effective_dps(enemy_army, own_army))\
                *(max(enemy_units(enemy_army).amount,0.2)*(enemy_army.minerals + self.gas_value*enemy_army.vespene))\
                *((own_units(own_army).amount + 1)*(own_army.minerals + self.gas_value*own_army.vespene))
            
                j += 1
            # Surprisingly, despite seemingly favouring massing one unit, it still builds some warp gates to balance out.
            # Threat to our unit = total damage it takes from enemies/total damage it deals to enemies. Doesn't care if it can't hit all units as long as the sum of its damage is enough
#            threat_level[i] = ((np.sum(effective_dps_taken,axis=1))/(np.sum(effective_dps_dealt,axis=1)))[i] # Seems to favour carriers and zealots
            # Threat level against our unit = sum of (damage taken/damage dealt) vs known enemy units. Overvalues all-rounded units.
            threat_level[i] = np.sum(effective_dps_taken[i][:]/np.clip(effective_dps_dealt[i][:],a_min=0.01,a_max=None)) # Seems to favour tempests and stalkers. Doesn't seem to react to enemy.
            i += 1        
        
        
        # Unit size drop off: Model dps as max efficiency at units that can fit within (2*pi/4)*(range+2), after which you get sharp drop off. (for ground units only)
        # Units tanking for each other: Effective hp of unit is its time to reach + time to kill of all units shorter range than it.
        # Combat score = sum of each unit's effective dps* its effective hp.
        # Threat score = enemy's effective dps to us* its effective hp.
        # Take our combat score/enemy threat score
        
        
#        i = 0
#        for own_army in own_army_race:
#            effective_dps_dealt_temp = effective_dps_dealt
#            effective_dps_taken_temp = effective_dps_taken
#            effective_dps_dealt_temp[i,:] = effective_dps_dealt_test[i,:]
#            effective_dps_taken_temp[i,:] = effective_dps_taken_test[i,:]      
#            
#            # Threat level i = Sum of total threats
#            threat_level[i] = (np.sum(effective_dps_taken_temp/np.clip(effective_dps_dealt_temp,a_min=0.1,a_max=None))/len(own_army_race)) # Heavily favours zealots and stalkers 
#        
#            i += 1


#        print('Statistics time!')
#        print(effective_dps_dealt.shape)
#        print(effective_dps_taken.shape)
#        print('Totals:')
#        print(np.sum(effective_dps_dealt))
#        print(np.sum(effective_dps_taken))
#        print('By row:')
#        print(np.sum(effective_dps_dealt,axis=1))
#        print(np.sum(effective_dps_taken,axis=1))
#        print((np.sum(effective_dps_taken,axis=1))/(np.sum(effective_dps_dealt,axis=1)))
            
            

        best_unit = own_army_race[np.argmin(threat_level)]
        return [threat_level, best_unit]
                    
    def scout_map(self, priority = 'Enemy'):
        # Assigns the next scouting location when called. This scouting location will change each time it is called, so only call it once for idle units! Spamming this will result in spazzing.
        # Input priority 'Enemy' or 'Map'
        # If priority is enemy, searches expansions in order of closest to enemy main (including the main)
        # If priority is map, searches expansions in order of closest to us (not including our taken bases)
        # Credit to RoachRush
        if priority == 'Enemy':
            if not self.scout_enemy:
                self.scout_enemy = itertools.cycle(self.ordered_expansions_enemy)
            self.scout_enemy_next = next(self.scout_enemy)
            scout_location = self.scout_enemy_next
        if priority == 'Map':
            if not self.clear_map:
                # start with enemy starting location, then cycle through all expansions
                self.clear_map = itertools.cycle(self.ordered_expansions)
            self.clear_map_next = next(self.clear_map)
            scout_location = self.clear_map_next
        return scout_location
    
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
            self.unit_list()

        
            # Check our race
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
            
            
            self.effective_dps_dealt = np.zeros((len(self.own_army_race),len(self.enemy_army_race)))
            self.effective_dps_taken = np.zeros((len(self.own_army_race),len(self.enemy_army_race)))
            i = 0
            for own_army in self.own_army_race:
                j = 0
                for enemy_army in self.enemy_army_race:
                    self.effective_dps_dealt[i][j] = (self.calculate_effective_dps(own_army,enemy_army))
                    self.effective_dps_taken[i][j] = (self.calculate_effective_dps(enemy_army,own_army))
                
#                    print(own_army)
#                    print(enemy_army)
#                    print(effective_dps_dealt[i][j])
#                    print(effective_dps_taken[i][j])
                    j += 1
                i += 1
            print('Statistics time!')
            print('Totals:')
            print(np.sum(self.effective_dps_dealt))
            print(np.sum(self.effective_dps_taken))
            print('By row:')
            print(np.sum(self.effective_dps_dealt,axis=1))
            print(np.sum(self.effective_dps_taken,axis=1))
            print((np.sum(self.effective_dps_taken,axis=1))/(np.sum(self.effective_dps_dealt,axis=1)))
                
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
        
        # Track known enemy units and structures. Updated whenever we see new units and removed whenever they die in vision.
        self.known_enemy_units += self.enemy_units.filter(lambda unit: unit not in self.known_enemy_units)
        self.known_enemy_structures += self.enemy_structures.filter(lambda unit: unit not in self.known_enemy_structures)
        # TODO: Implement self.future_enemy_units. Calculates how many and of what type of units we may face in the future. 
        # Based on the tech and production we see, calculate possible tech switches and amount of units in the future. More likely to see units we already see and new tech that was added.
        
        
        
        
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
        self.all_army = self.units.not_structure - self.units(PROBE) - self.units(INTERCEPTOR)
        [threat_level, best_unit] = self.calculate_threat_level(self.own_army_race, self.all_army, self.enemy_army_race, self.known_enemy_units) 
        
        # Choose target and attack, filter out invisible targets
        targets = (self.enemy_units | self.enemy_structures).filter(lambda unit: unit.can_be_attacked and not self.units({LARVA, EGG, INTERCEPTOR}))
        if self.all_army:
            army_center = self.all_army.center
        for army in self.all_army:            
            if targets:
                # If the enemy is not a threat, group up all army to attack together.
                if True: #min(threat_level) < 1:
                    target = targets.closest_to(army)
                    # Unit has no attack, stay near other army units                    
                    if army.weapon_cooldown == -1 and not army.is_moving: 
                        self.do(army.move(self.all_army.closest_to(army)))                
                    # Unit has just attacked, stutter step while waiting for attack cooldown
                    elif army.weapon_cooldown > self.kite_distance/army.movement_speed and army.target_in_range(target, bonus_distance = self.kite_distance):
                        kite_pos = army.position.towards(target.position, -1)
#                        self.do(army(STOP_DANCE))
                        self.do(army.move(kite_pos))
                        if army in self.units(VOIDRAY):
                            self.do(army(EFFECT_VOIDRAYPRISMATICALIGNMENT))
                    # Regroup
                    elif army.distance_to_squared(army_center) > 225 and not army.target_in_range(target) and targets.exclude_type({SCV, PROBE, DRONE}) and not army.is_moving:
                        self.do(army.move(army_center))
                    # Unit is ready to attack, go attack. Use smart command (right click) instead of attack because carriers/bcs don't work with attack
                    else:
                        if not army.is_attacking:
                            self.do(army.smart(target))
                # If the enemy is currently too strong, avoid the enemy army and poke.
#                if threat_level >= 1:
                    
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
        
        #find the buildings that are building, and have low health.
        for building in self.structures.filter(lambda x: x.build_progress < 1 and x.health + x.shield < 10):
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
                if AbilityId.EFFECT_CHRONOBOOSTENERGYCOST in abilities_nexus:
                    self.do(loop_nexus(EFFECT_CHRONOBOOSTENERGYCOST, nexus))
                    break
        # Distribute workers in gas and across bases
        # TODO: Dynamically calculate ideal resource ratio based on the unit composition we want and our current bank
        if iteration%(self.ITERATIONS_PER_MINUTE/30) == 0:
            await self.distribute_workers()


        # Calculate rate of supply consumption to supply remaining and preemptively build a dynamic amount of supply. Stop once we reach the 200 supply cap.
        # TODO: Include pending supply from town halls into supply calculations.
        # TODO: Intelligently choose pylon locations. Current behaviour: Put it within radius 5 of a nexus towards the center of the map
        if (self.supply_left + self.already_pending(PYLON)*8) < supply_rate*self.SUPPLY_BUILD_TIME and self.supply_cap + self.already_pending(PYLON)*8 <200:
            # Always check if you can afford something before you build it
            if self.can_afford(PYLON):
                await self.build(PYLON, near=nexus.position.towards(self.game_info.map_center, 5))

        # Train probe on nexuses that are undersaturated until worker cap
        if self.supply_workers + self.already_pending(PROBE) < min(self.townhalls.amount * 22, self.MAX_WORKERS) and nexus.is_idle:
            if self.can_afford(PROBE):
                self.do(nexus.train(PROBE), subtract_cost=True, subtract_supply=True)

        # If we are about to reach saturation on existing town halls, expand        
        # TODO: If it's too dangerous to expand, don't
        # TODO: Send worker to expansion location just in time for having money for town hall
        if self.supply_workers + self.NEXUS_SUPPLY_RATE*self.NEXUS_BUILD_TIME >= (self.townhalls.ready.amount + self.already_pending(NEXUS))*22:
            if self.can_afford(NEXUS):
                await self.expand_now()
            else:
                # If we need an expansion but don't have resources, save for it.
                save_resources = 1
        # If we have reached max workers and have a lot more minerals than gas, expand for more gas.
        elif self.supply_workers > self.MAX_WORKERS-10 and self.minerals > 2000 and self.minerals/max(self.vespene, 1) > 2 and self.already_pending(NEXUS) == 0:
            if self.can_afford(NEXUS):
                await self.expand_now()
            


        # Tech up
        # TODO: If we need a high-tech unit more quickly, have a weightage for tech-rushing that unit
        # TODO: Consider how much army we currently have to determine if it is safe to tech up.
        # TODO: Include every upgrade in the game, and consider how many of the unit we plan to use in the future (i.e. start charge before we have zealots if we want them soon)
        warpgate_tech = [ARCHON, DARKTEMPLAR]
        stargate_tech = [TEMPEST, CARRIER]
        robo_tech = [COLOSSUS, DISRUPTOR]
        [_, best_unit] = self.calculate_threat_level(self.own_army_race, self.all_army, self.enemy_army_race, self.known_enemy_units)
        
        if self.structures(PYLON).ready:
            pylon = self.structures(PYLON).ready.random
            # If we have a gateway completed, build cyber core
            if self.structures(GATEWAY).ready or self.structures(WARPGATE):
                if not self.structures(CYBERNETICSCORE):
                    if self.can_afford(CYBERNETICSCORE) and self.already_pending(CYBERNETICSCORE) == 0:
                        await self.build(CYBERNETICSCORE, near=pylon)
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
                await self.build(GATEWAY, near=pylon)
            
            # Tech: Upgrade warpgate units                        
            if best_unit in warpgate_tech:
                if self.structures(CYBERNETICSCORE).ready:
                    if not self.structures(TWILIGHTCOUNCIL):
                        if self.can_afford(TWILIGHTCOUNCIL) and self.already_pending(TWILIGHTCOUNCIL) == 0:
                            await self.build(TWILIGHTCOUNCIL, near=pylon)
                    
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
                                if self.can_afford(RESEARCH_ADEPTRESONATINGGLAIVES) and self.already_pending_upgrade(ADEPTRESONATINGGLAIVES) == 0:
                                    self.do(twilight.research(ADEPTRESONATINGGLAIVES))
                                elif not self.can_afford(RESEARCH_ADEPTRESONATINGGLAIVES):
                                    save_resources = 1
                                    
                            # If we want archons, build templar archives
                            if best_unit == ARCHON and self.structures(TWILIGHTCOUNCIL).ready:
                                if not self.structures(TEMPLARARCHIVE):
                                    if self.can_afford(TEMPLARARCHIVE) and self.already_pending(TEMPLARARCHIVE) == 0:
                                        await self.build(TEMPLARARCHIVE, near=pylon)
                                        
                            # If we want DTs, build dark shrine
                            # TODO: Or if we are maxed out or if they have no detection
                            if best_unit == DARKTEMPLAR and self.structures(TWILIGHTCOUNCIL).ready:
                                if not self.structures(DARKSHRINE):
                                    if self.can_afford(DARKSHRINE) and self.already_pending(DARKSHRINE) == 0:
                                        await self.build(DARKSHRINE, near=pylon)
            
            # Tech: T3 stargate                                        
            if best_unit in stargate_tech:
                if self.structures(STARGATE).ready:
                    if not self.structures(FLEETBEACON):
                        if self.can_afford(FLEETBEACON) and self.already_pending(FLEETBEACON) == 0:
                            await self.build(FLEETBEACON, near=pylon)
                        elif not self.can_afford(FLEETBEACON):
                            save_resources = 1
                # If we have no stargate, make one
                elif not self.structures(STARGATE):
                    if self.can_afford(STARGATE) and self.already_pending(STARGATE) == 0:
                        await self.build(STARGATE, near=pylon)
                        
            # Tech: T3 robo    
            if best_unit in robo_tech:                
                if self.structures(ROBOTICSFACILITY).ready:
                    if not self.structures(ROBOTICSBAY):
                        if self.can_afford(ROBOTICSBAY) and self.already_pending(ROBOTICSBAY) == 0:
                            await self.build(ROBOTICSBAY, near=pylon)
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
                        await self.build(ROBOTICSFACILITY, near=pylon)
                
            # Make detection if needed
            if self.need_detection and not self.have_detection and not self.already_pending(OBSERVER):
                if self.structures(ROBOTICSFACILITY).ready:
                    for rb in self.structures(ROBOTICSFACILITY).idle:
                        if self.can_afford(OBSERVER):
                            self.do(rb.train(OBSERVER), subtract_cost=True, subtract_supply=True)
                elif not self.structures(ROBOTICSFACILITY):
                    if self.can_afford(ROBOTICSFACILITY) and self.already_pending(ROBOTICSFACILITY) == 0:
                        await self.build(ROBOTICSFACILITY, near=pylon) 
#            
#        if self.structures(PYLON).ready:
#            pylon = self.structures(PYLON).ready.random
#            if self.structures(GATEWAY).ready or self.structures(WARPGATE).ready:
#                # If we have gateway completed, build cyber core
#                if not self.structures(CYBERNETICSCORE):
#                    if self.can_afford(CYBERNETICSCORE) and self.already_pending(CYBERNETICSCORE) == 0:
#                        await self.build(CYBERNETICSCORE, near=pylon)
#                else:
#                    # If cybercore is ready, research warpgate
#                    if (
#                            self.structures(CYBERNETICSCORE).ready
#                            and self.can_afford(RESEARCH_WARPGATE)
#                            and self.already_pending_upgrade(WARPGATERESEARCH) == 0
#                    ):
#                        ccore = self.structures(CYBERNETICSCORE).ready.first
#                        self.do(ccore(RESEARCH_WARPGATE), subtract_cost=True)
#                    
#                    # If we have lots of gateways, build twilight council
#                    if (self.structures(GATEWAY).ready.amount+self.structures(WARPGATE).ready.amount+self.already_pending(GATEWAY)) >= 4:
#                        if not self.structures(TWILIGHTCOUNCIL):
#                            if self.can_afford(TWILIGHTCOUNCIL) and self.already_pending(TWILIGHTCOUNCIL) == 0:
#                                await self.build(TWILIGHTCOUNCIL, near=pylon)
#                        
#                        else:
#                            if self.structures(TWILIGHTCOUNCIL).ready:                                    
#                                twilight = self.structures(TWILIGHTCOUNCIL).ready.first                                
#                                # If we have lots of zealot/stalker/adept, research charge/blink/glaives
#                                if self.units(ZEALOT).amount > 5:
#                                    if self.can_afford(RESEARCH_CHARGE) and self.already_pending_upgrade(CHARGE) == 0:
#                                        self.do(twilight.research(CHARGE))
#                                    elif not self.can_afford(RESEARCH_CHARGE):
#                                        save_resources = 1
#                                if self.units(STALKER).amount > 5:
#                                    if self.can_afford(RESEARCH_BLINK) and self.already_pending_upgrade(BLINKTECH) == 0:
#                                        self.do(twilight.research(BLINKTECH))
#                                    elif not self.can_afford(RESEARCH_BLINK):
#                                        save_resources = 1
#                                if self.units(ADEPT).amount > 5:
#                                    if self.can_afford(RESEARCH_ADEPTRESONATINGGLAIVES) and self.already_pending_upgrade(ADEPTRESONATINGGLAIVES) == 0:
#                                        self.do(twilight.research(ADEPTRESONATINGGLAIVES))
#                                    elif not self.can_afford(RESEARCH_ADEPTRESONATINGGLAIVES):
#                                        save_resources = 1
#                                    
#                            # If we have lots of vespene, build templar archives
#                            if self.structures(TWILIGHTCOUNCIL).ready and self.vespene > 500:
#                                if not self.structures(TEMPLARARCHIVE):
#                                    if self.can_afford(TEMPLARARCHIVE) and self.already_pending(TEMPLARARCHIVE) == 0:
#                                        await self.build(TEMPLARARCHIVE, near=pylon)
#                                        
#                            # If we have a big bank, build dark shrine
#                            if self.structures(TWILIGHTCOUNCIL).ready and self.vespene > 750 and self.minerals > 750:
#                                if not self.structures(DARKSHRINE):
#                                    if self.can_afford(DARKSHRINE) and self.already_pending(DARKSHRINE) == 0:
#                                        await self.build(DARKSHRINE, near=pylon)
#                        
#                    # If we have lots of stargates, build fleet beacon
#                    if len(self.structures(STARGATE)) >= 2:
#                        if not self.structures(FLEETBEACON):
#                            if self.can_afford(FLEETBEACON) and self.already_pending(FLEETBEACON) == 0:
#                                await self.build(FLEETBEACON, near=pylon)
#                            elif not self.can_afford(FLEETBEACON):
#                                save_resources = 1
#                                
#                    # If we have lots of robotics facilities, build robotics bay
#                    if len(self.structures(ROBOTICSFACILITY)) >= 1:
#                        if not self.structures(ROBOTICSBAY):
#                            if self.can_afford(ROBOTICSBAY) and self.already_pending(ROBOTICSBAY) == 0:
#                                await self.build(ROBOTICSBAY, near=pylon)
#                            elif not self.can_afford(ROBOTICSBAY):
#                                save_resources = 1
#                        # Research thermal lance        
#                        elif self.structures(ROBOTICSBAY).ready:
#                            robobay = self.structures(ROBOTICSBAY).ready.first
#                            if self.can_afford(RESEARCH_EXTENDEDTHERMALLANCE) and self.already_pending_upgrade(EXTENDEDTHERMALLANCE) == 0:
#                                self.do(robobay.research(EXTENDEDTHERMALLANCE))
                                
#            else:
#                # If we have no gateway, build gateway
#                if self.can_afford(GATEWAY) and self.structures(GATEWAY).amount == 0:
#                    await self.build(GATEWAY, near=pylon)
        
        # Build gas near completed nexuses once we have a cybercore (does not need to be completed)
        # Have weightage on earlier gas for tech rush
        if self.supply_workers + self.NEXUS_SUPPLY_RATE*self.GAS_BUILD_TIME >= self.townhalls.ready.amount*16 + self.structures(ASSIMILATOR).amount*3 and self.structures(CYBERNETICSCORE) \
        or self.MAX_WORKERS - self.supply_workers < 10:
            for nexus in self.townhalls.ready:
                vgs = self.vespene_geyser.closer_than(10, nexus)
                for vg in vgs:
                    if not self.can_afford(ASSIMILATOR):
                        break

                    worker = self.select_build_worker(vg.position)
                    if worker is None:
                        break

                    if not self.gas_buildings or not self.gas_buildings.closer_than(1, vg):
                        self.do(worker.build(ASSIMILATOR, vg), subtract_cost=True)
                        self.do(worker.stop(queue=True))


        # If we don't need to save resources, make stuff
        warp_try = 0
        if save_resources == 0: # Be careful to make sure that save_resources is only asserted when we cannot afford something!
            # Run through all our production buildings and make sure they are being used
            # TODO: BUG: Available units are sometimes not registered, and seem to vary based on the units available, not just the existing armies.
            # Stargate units
            if self.structures(FLEETBEACON).ready:
                self.available_stargate_units = [PHOENIX, ORACLE, VOIDRAY, TEMPEST, CARRIER]
            else:
                self.available_stargate_units = [PHOENIX, ORACLE, VOIDRAY]
            [_, best_unit] = self.calculate_threat_level(self.available_stargate_units, self.all_army, self.enemy_army_race, self.known_enemy_units) 
            for sg in self.structures(STARGATE).idle:
                if self.can_afford(best_unit):
                    self.do(sg.train(best_unit), subtract_cost=True, subtract_supply=True)
            
            # Robo units. TODO: Flag to produce observers and warp prism
            if self.structures(ROBOTICSBAY).ready:
                self.available_robo_units = [IMMORTAL, COLOSSUS, DISRUPTOR]
                [_, best_unit] = self.calculate_threat_level(self.available_robo_units, self.all_army, self.enemy_army_race, self.known_enemy_units) 
            else:
                self.available_robo_units = [IMMORTAL]
                best_unit = IMMORTAL
            for rb in self.structures(ROBOTICSFACILITY).idle:
                if self.can_afford(best_unit):
                    self.do(rb.train(best_unit), subtract_cost=True, subtract_supply=True)
            
            # Warpgate units. Prioritize robo and stargate units.
            self.available_warpgate_units = [ZEALOT]
            if self.structures(CYBERNETICSCORE).ready:
                self.available_warpgate_units.append(STALKER)
                self.available_warpgate_units.append(SENTRY)
                self.available_warpgate_units.append(ADEPT)
            if self.structures(TEMPLARARCHIVE).ready:
                self.available_warpgate_units.append(ARCHON)
            if self.structures(DARKSHRINE).ready:
                self.available_warpgate_units.append(DARKTEMPLAR)
            [_, best_unit] = self.calculate_threat_level(self.available_warpgate_units, self.all_army, self.enemy_army_race, self.known_enemy_units) 
            
            if not self.structures(STARGATE).ready.idle and not self.structures(ROBOTICSFACILITY).ready.idle:                
                if self.structures(PYLON).ready:
                    proxy = self.structures(PYLON).closest_to(self.enemy_start_locations[0])
                # TODO: Warp-in at power field closest to enemy, but at a minimum distance away. Include warp prism power fields.                    
                for wg in self.structures(WARPGATE).ready:
                    abilities = await self.get_available_abilities(wg)
                    if AbilityId.WARPGATETRAIN_ZEALOT in abilities:
                        pos = proxy.position.to2.random_on_distance(4)
                        placement = await self.find_placement(WARPGATETRAIN_ZEALOT, pos, placement_step=1)
                        while placement is None:
                            # pick random other pylon
                            proxy = self.structures(PYLON).random
                            pos = proxy.position.to2.random_on_distance(4)
                            placement = await self.find_placement(WARPGATETRAIN_ZEALOT, pos, placement_step=1)
                            warp_try +=1
                            if warp_try >= 5:
                                break
                            
                        if best_unit == ARCHON:
                            self.do(wg.warp_in(HIGHTEMPLAR, placement), subtract_cost=True, subtract_supply=True)
                        else:
                            self.do(wg.warp_in(best_unit, placement), subtract_cost=True, subtract_supply=True)
                            
                # If warp gate is not yet researched, use gateways. Warp gate research takes 100s, gateway units take ~30s to build, already_pending returns % completion, with 1 on completion
                if self.already_pending_upgrade(WARPGATERESEARCH) < 0.7 :
                    for gw in self.structures(GATEWAY).idle:
                        if self.can_afford(STALKER):
                            self.do(gw.train(STALKER), subtract_cost=True, subtract_supply = True)
                # If all our production is not idle and we have more income than expenditure, add more production buildings. If we are supply capped, add production up to ~2x income rate
                # TODO: Intelligent choices on which production buildings to make.
                # TODO: Sim city placement
                # Current behaviour: Balance out robo, stargate, warpgate in a 1:1:4 ratio when we want to spend minerals
                self.available_units = self.available_warpgate_units
                for unit in self.available_robo_units:
                    self.available_units.append(unit)
                for unit in self.available_stargate_units:
                    self.available_units.append(unit)
                
                if self.structures(PYLON).ready and self.structures(CYBERNETICSCORE).ready:
                    pylon = self.structures(PYLON).ready.random                    
                    # TODO: Dynamically modify income-expenditure ratio based on stage of the game (teching and expanding are not counted in expenditure but this is a significant cost early).
                    if mineral_income*0.8 > mineral_rate or (self.supply_used > 190 and mineral_income*1.5 > mineral_rate):
                        [_, best_unit] = self.calculate_threat_level(self.available_units, self.all_army, self.enemy_army_race, self.known_enemy_units) 
                        if best_unit in self.available_warpgate_units:
                            if self.can_afford(GATEWAY):
                                await self.build(GATEWAY, near=pylon)
                        if best_unit in self.available_robo_units:
                            if self.can_afford(ROBOTICSFACILITY):
                                await self.build(ROBOTICSFACILITY, near=pylon)
                        if best_unit in self.available_stargate_units:
                            if self.can_afford(STARGATE):
                                await self.build(STARGATE, near=pylon)
                            
#                        if num_warpgates > 2*(num_stargates + num_robos):
#                            if num_robos <= num_stargates or num_robos < 2:
#                                if self.can_afford(ROBOTICSFACILITY):
#                                    await self.build(ROBOTICSFACILITY, near=pylon)
#                            else:
#                                if self.can_afford(STARGATE):
#                                    await self.build(STARGATE, near=pylon)
#                        else:
#                            if self.can_afford(GATEWAY):
#                                await self.build(GATEWAY, near=pylon)
                    
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
            print(self.calculate_threat_level(self.own_army_race, self.all_army, self.enemy_army_race, self.known_enemy_units))
            print(self.already_pending(PROBE))
            
        
    def unit_list(self): 
        # List of stats: No. of attacks, Damage, Bonus damage, Bonus attribute, Attack speed, Attack point for both ground and air 
        # Hp, Shields, Armor, Shield armor, Range, Movement speed, Splash area, Unit size, Attribute, Is air, Minerals, Vespene, Supply
        # Terran    
        # Terran: Note that many units have different forms and each form has a different unit name! -> Hellion/Hellbat, Widow mine, Siege tank, Viking, Liberator
        # Excluded units: Raven, Widow mine
        self.terran_army = [MARINE, MARAUDER, REAPER, GHOST, HELLION, HELLIONTANK, WIDOWMINE, SIEGETANK, SIEGETANKSIEGED, CYCLONE, THOR, THORAP, VIKINGFIGHTER, VIKINGASSAULT, \
                            LIBERATOR, LIBERATORAG, BANSHEE, BATTLECRUISER]
        
        MARINE.attacks_ground = 1*1.5
        MARINE.attacks_air = 1*1.5
        MARINE.dmg_ground = 6
        MARINE.dmg_air = 6
        MARINE.bonus_dmg_ground = 0
        MARINE.bonus_dmg_air = 0
        MARINE.bonus_attr_ground = None
        MARINE.bonus_attr_air = None
        MARINE.attack_speed_ground = 0.61
        MARINE.attack_speed_air = 0.61
        MARINE.attack_point_ground = 0.0357
        MARINE.attack_point_air = 0.0357
        MARINE.hp = 45 
        MARINE.shields = 0
        MARINE.armor = 0
        MARINE.shield_armor = 0
        MARINE.range_ground = 5
        MARINE.range_air = 5
        MARINE.leash_range = 0
        MARINE.movement_speed = 3.15*1.5
        MARINE.splash_area_air = 0
        MARINE.splash_area_ground = 0
        MARINE.size = 0.75 # Size is in diameter
        MARINE.attribute = ['Light', 'Biological']
        MARINE.is_air = False
        MARINE.is_ground = True
        MARINE.minerals = self.calculate_unit_value(MARINE).minerals
        MARINE.vespene = self.calculate_unit_value(MARINE).vespene
        MARINE.supply = self.calculate_supply_cost(MARINE) # Training/morph cost, so upgraded units must count their base units!
        
        MARAUDER.attacks_ground = 1*1.5
        MARAUDER.attacks_air = 0
        MARAUDER.dmg_ground = 10
        MARAUDER.dmg_air = 0
        MARAUDER.bonus_dmg_ground = 10
        MARAUDER.bonus_dmg_air = 0
        MARAUDER.bonus_attr_ground = 'Armored'
        MARAUDER.bonus_attr_air = None
        MARAUDER.attack_speed_ground = 1.07
        MARAUDER.attack_speed_air = 1.07
        MARAUDER.attack_point_ground = 0
        MARAUDER.attack_point_air = 0
        MARAUDER.hp = 125-20
        MARAUDER.shields = 0
        MARAUDER.armor = 1
        MARAUDER.shield_armor = 0
        MARAUDER.range_ground = 6
        MARAUDER.range_air = 0
        MARAUDER.leash_range = 0
        MARAUDER.movement_speed = 3.15*1.5
        MARAUDER.splash_area_air = 0
        MARAUDER.splash_area_ground = 0
        MARAUDER.size = 1.125 # Size is in diameter
        MARAUDER.attribute = ['Psionic', 'Biological']
        MARAUDER.is_air = False
        MARAUDER.is_ground = True
        MARAUDER.minerals = self.calculate_unit_value(MARAUDER).minerals
        MARAUDER.vespene = self.calculate_unit_value(MARAUDER).vespene
        MARAUDER.supply = self.calculate_supply_cost(MARAUDER) # Training/morph cost, so upgraded units must count their base units!
		
        REAPER.attacks_ground = 2
        REAPER.attacks_air = 0
        REAPER.dmg_ground = 4
        REAPER.dmg_air = 0
        REAPER.bonus_dmg_ground = 0
        REAPER.bonus_dmg_air = 0
        REAPER.bonus_attr_ground = None
        REAPER.bonus_attr_air = None
        REAPER.attack_speed_ground = 0.79
        REAPER.attack_speed_air = 0.79
        REAPER.attack_point_ground = 0
        REAPER.attack_point_air = 0
        REAPER.hp = 60
        REAPER.shields = 0
        REAPER.armor = 0
        REAPER.shield_armor = 0
        REAPER.range_ground = 5
        REAPER.range_air = 0
        REAPER.leash_range = 0
        REAPER.movement_speed = 5.25
        REAPER.splash_area_air = 0
        REAPER.splash_area_ground = 0
        REAPER.size = 0.75 # Size is in diameter
        REAPER.attribute = ['Light', 'Biological']
        REAPER.is_air = False
        REAPER.is_ground = True
        REAPER.minerals = self.calculate_unit_value(REAPER).minerals
        REAPER.vespene = self.calculate_unit_value(REAPER).vespene
        REAPER.supply = self.calculate_supply_cost(REAPER) # Training/morph cost, so upgraded units must count their base units!
        
        GHOST.attacks_ground = 1
        GHOST.attacks_air = 1
        GHOST.dmg_ground = 10
        GHOST.dmg_air = 10
        GHOST.bonus_dmg_ground = 10
        GHOST.bonus_dmg_air = 10
        GHOST.bonus_attr_ground = 'Light'
        GHOST.bonus_attr_air = 'Light'
        GHOST.attack_speed_ground = 1.07
        GHOST.attack_speed_air = 1.07
        GHOST.attack_point_ground = 0.0593
        GHOST.attack_point_air = 0.0593
        GHOST.hp = 100 
        GHOST.shields = 0
        GHOST.armor = 0
        GHOST.shield_armor = 0
        GHOST.range_ground = 6
        GHOST.range_air = 6
        GHOST.leash_range = 0
        GHOST.movement_speed = 3.94
        GHOST.splash_area_air = 0
        GHOST.splash_area_ground = 0
        GHOST.size = 0.75 # Size is in diameter
        GHOST.attribute = ['Psionic', 'Biological']
        GHOST.is_air = False
        GHOST.is_ground = True
        GHOST.minerals = self.calculate_unit_value(GHOST).minerals
        GHOST.vespene = self.calculate_unit_value(GHOST).vespene
        GHOST.supply = self.calculate_supply_cost(GHOST) # Training/morph cost, so upgraded units must count their base units!
		
        HELLION.attacks_ground = 1
        HELLION.attacks_air = 0
        HELLION.dmg_ground = 8
        HELLION.dmg_air = 0
        HELLION.bonus_dmg_ground = 6+5
        HELLION.bonus_dmg_air = 0
        HELLION.bonus_attr_ground = 'Light'
        HELLION.bonus_attr_air = None
        HELLION.attack_speed_ground = 1.79
        HELLION.attack_speed_air = 1.79
        HELLION.attack_point_ground = 0.1786
        HELLION.attack_point_air = 0.1786
        HELLION.hp = 90
        HELLION.shields = 0
        HELLION.armor = 0
        HELLION.shield_armor = 0
        HELLION.range_ground = 5
        HELLION.range_air = 0
        HELLION.leash_range = 0
        HELLION.movement_speed = 5.95
        HELLION.splash_area_air = 0
        HELLION.splash_area_ground = 2
        HELLION.size = 1.25 # Size is in diameter
        HELLION.attribute = ['Light', 'Mechanical']
        HELLION.is_air = False
        HELLION.is_ground = True
        HELLION.minerals = self.calculate_unit_value(HELLION).minerals
        HELLION.vespene = self.calculate_unit_value(HELLION).vespene
        HELLION.supply = self.calculate_supply_cost(HELLION) # Training/morph cost, so upgraded units must count their base units!
        
        HELLIONTANK.attacks_ground = 1
        HELLIONTANK.attacks_air = 0
        HELLIONTANK.dmg_ground = 18
        HELLIONTANK.dmg_air = 0
        HELLIONTANK.bonus_dmg_ground = 0+12
        HELLIONTANK.bonus_dmg_air = 0
        HELLIONTANK.bonus_attr_ground = 'Light'
        HELLIONTANK.bonus_attr_air = None
        HELLIONTANK.attack_speed_ground = 1.43
        HELLIONTANK.attack_speed_air = 1.43
        HELLIONTANK.attack_point_ground = 0.1193
        HELLIONTANK.attack_point_air = 0.1193
        HELLIONTANK.hp = 135
        HELLIONTANK.shields = 0
        HELLIONTANK.armor = 0
        HELLIONTANK.shield_armor = 0
        HELLIONTANK.range_ground = 2
        HELLIONTANK.range_air = 0
        HELLIONTANK.leash_range = 0
        HELLIONTANK.movement_speed = 3.15
        HELLIONTANK.splash_area_air = 0
        HELLIONTANK.splash_area_ground = 2.5
        HELLIONTANK.size = 1.25 # Size is in diameter
        HELLIONTANK.attribute = ['Light', 'Mechanical', 'Biological']
        HELLIONTANK.is_air = False
        HELLIONTANK.is_ground = True
        HELLIONTANK.minerals = self.calculate_unit_value(HELLIONTANK).minerals
        HELLIONTANK.vespene = self.calculate_unit_value(HELLIONTANK).vespene
        HELLIONTANK.supply = self.calculate_supply_cost(HELLIONTANK) # Training/morph cost, so upgraded units must count their base units!
        
        WIDOWMINE.attacks_ground = 1
        WIDOWMINE.attacks_air = 1
        WIDOWMINE.dmg_ground = 125
        WIDOWMINE.dmg_air = 125
        WIDOWMINE.bonus_dmg_ground = 0
        WIDOWMINE.bonus_dmg_air = 0
        WIDOWMINE.bonus_attr_ground = None 
        WIDOWMINE.bonus_attr_air = None
        WIDOWMINE.attack_speed_ground = 29
        WIDOWMINE.attack_speed_air = 29
        WIDOWMINE.attack_point_ground = 1.07 + 3
        WIDOWMINE.attack_point_air = 1.07 + 3
        WIDOWMINE.hp = 90
        WIDOWMINE.shields = 0
        WIDOWMINE.armor = 0
        WIDOWMINE.shield_armor = 0
        WIDOWMINE.range_ground = 5
        WIDOWMINE.range_air = 5
        WIDOWMINE.leash_range = 0
        WIDOWMINE.movement_speed = 3.94
        WIDOWMINE.splash_area_air = self.PI*(1.75**2)*40/125
        WIDOWMINE.splash_area_ground = self.PI*(1.75**2)*40/125
        WIDOWMINE.size = 1 # Size is in diameter
        WIDOWMINE.attribute = ['Light', 'Mechanical']
        WIDOWMINE.is_air = False
        WIDOWMINE.is_ground = True
        WIDOWMINE.minerals = self.calculate_unit_value(WIDOWMINE).minerals
        WIDOWMINE.vespene = self.calculate_unit_value(WIDOWMINE).vespene
        WIDOWMINE.supply = self.calculate_supply_cost(WIDOWMINE) # Training/morph cost, so upgraded units must count their base units!
        
        SIEGETANK.attacks_ground = 1
        SIEGETANK.attacks_air = 0
        SIEGETANK.dmg_ground = 15
        SIEGETANK.dmg_air = 0
        SIEGETANK.bonus_dmg_ground = 10
        SIEGETANK.bonus_dmg_air = 0
        SIEGETANK.bonus_attr_ground = 'Armored'
        SIEGETANK.bonus_attr_air = None
        SIEGETANK.attack_speed_ground = 0.74
        SIEGETANK.attack_speed_air = 0.74
        SIEGETANK.attack_point_ground = 0.1193
        SIEGETANK.attack_point_air = 0.1193
        SIEGETANK.hp = 175
        SIEGETANK.shields = 0
        SIEGETANK.armor = 1
        SIEGETANK.shield_armor = 0
        SIEGETANK.range_ground = 7
        SIEGETANK.range_air = 0
        SIEGETANK.leash_range = 0
        SIEGETANK.movement_speed = 3.15
        SIEGETANK.splash_area_air = 0
        SIEGETANK.splash_area_ground = 0
        SIEGETANK.size = 1.75 # Size is in diameter
        SIEGETANK.attribute = ['Armored', 'Mechanical']
        SIEGETANK.is_air = False
        SIEGETANK.is_ground = True
        SIEGETANK.minerals = self.calculate_unit_value(SIEGETANK).minerals
        SIEGETANK.vespene = self.calculate_unit_value(SIEGETANK).vespene
        SIEGETANK.supply = self.calculate_supply_cost(SIEGETANK) # Training/morph cost, so upgraded units must count their base units!
        
        SIEGETANKSIEGED.attacks_ground = 1
        SIEGETANKSIEGED.attacks_air = 0
        SIEGETANKSIEGED.dmg_ground = 40
        SIEGETANKSIEGED.dmg_air = 0
        SIEGETANKSIEGED.bonus_dmg_ground = 30
        SIEGETANKSIEGED.bonus_dmg_air = 0
        SIEGETANKSIEGED.bonus_attr_ground = 'Armored'
        SIEGETANKSIEGED.bonus_attr_air = None
        SIEGETANKSIEGED.attack_speed_ground = 2.14
        SIEGETANKSIEGED.attack_speed_air = 2.14
        SIEGETANKSIEGED.attack_point_ground = 2.14
        SIEGETANKSIEGED.attack_point_air = 2.14
        SIEGETANKSIEGED.hp = 175
        SIEGETANKSIEGED.shields = 0
        SIEGETANKSIEGED.armor = 1
        SIEGETANKSIEGED.shield_armor = 0
        SIEGETANKSIEGED.range_ground = 13
        SIEGETANKSIEGED.range_air = 0
        SIEGETANKSIEGED.leash_range = 0
        SIEGETANKSIEGED.movement_speed = 0
        SIEGETANKSIEGED.splash_area_air = 0
        SIEGETANKSIEGED.splash_area_ground = self.PI*(0.4687**2 + (0.7812**2-0.4687**2)*0.5 + (1.25**2-0.7812**2)*0.25)
        SIEGETANKSIEGED.size = 1.75 # Size is in diameter
        SIEGETANKSIEGED.attribute = ['Armored', 'Mechanical']
        SIEGETANKSIEGED.is_air = False
        SIEGETANKSIEGED.is_ground = True
        SIEGETANKSIEGED.minerals = self.calculate_unit_value(SIEGETANKSIEGED).minerals
        SIEGETANKSIEGED.vespene = self.calculate_unit_value(SIEGETANKSIEGED).vespene
        SIEGETANKSIEGED.supply = self.calculate_supply_cost(SIEGETANKSIEGED) # Training/morph cost, so upgraded units must count their base units!

        CYCLONE.attacks_ground = 1
        CYCLONE.attacks_air = 1
        CYCLONE.dmg_ground = 20
        CYCLONE.dmg_air = 20
        CYCLONE.bonus_dmg_ground = 0+20
        CYCLONE.bonus_dmg_air = 0+20
        CYCLONE.bonus_attr_ground = 'Armored'
        CYCLONE.bonus_attr_air = 'Armored'
        CYCLONE.attack_speed_ground = 0.71
        CYCLONE.attack_speed_air = 0.71
        CYCLONE.attack_point_ground = 0
        CYCLONE.attack_point_air = 0
        CYCLONE.hp = 120
        CYCLONE.shields = 0
        CYCLONE.armor = 1
        CYCLONE.shield_armor = 0
        CYCLONE.range_ground = 7
        CYCLONE.range_air = 7
        CYCLONE.leash_range = 15
        CYCLONE.movement_speed = 4.73
        CYCLONE.splash_area_air = 0
        CYCLONE.splash_area_ground = 0
        CYCLONE.size = 1.5 # Size is in diameter
        CYCLONE.attribute = ['Armored', 'Mechanical']
        CYCLONE.is_air = False
        CYCLONE.is_ground = True
        CYCLONE.minerals = self.calculate_unit_value(CYCLONE).minerals
        CYCLONE.vespene = self.calculate_unit_value(CYCLONE).vespene
        CYCLONE.supply = self.calculate_supply_cost(CYCLONE) # Training/morph cost, so upgraded units must count their base units!
        
        THOR.attacks_ground = 2
        THOR.attacks_air = 4
        THOR.dmg_ground = 30
        THOR.dmg_air = 6
        THOR.bonus_dmg_ground = 0
        THOR.bonus_dmg_air = 6
        THOR.bonus_attr_ground = None
        THOR.bonus_attr_air = 'Light'
        THOR.attack_speed_ground = 0.91
        THOR.attack_speed_air = 2.14
        THOR.attack_point_ground = 0.5936
        THOR.attack_point_air = 0.1193
        THOR.hp = 400
        THOR.shields = 0
        THOR.armor = 1
        THOR.shield_armor = 0
        THOR.range_ground = 7
        THOR.range_air = 10
        THOR.leash_range = 0
        THOR.movement_speed = 2.62
        THOR.splash_area_air = self.PI*0.5**2
        THOR.splash_area_ground = 0
        THOR.size = 2 # Size is in diameter
        THOR.attribute = ['Armored', 'Mechanical','Massive']
        THOR.is_air = False
        THOR.is_ground = True
        THOR.minerals = self.calculate_unit_value(THOR).minerals
        THOR.vespene = self.calculate_unit_value(THOR).vespene
        THOR.supply = self.calculate_supply_cost(THOR) # Training/morph cost, so upgraded units must count their base units!
                
        THORAP.attacks_ground = 2
        THORAP.attacks_air = 1
        THORAP.dmg_ground = 30
        THORAP.dmg_air = 25
        THORAP.bonus_dmg_ground = 0
        THORAP.bonus_dmg_air = 10
        THORAP.bonus_attr_ground = None
        THORAP.bonus_attr_air = 'Massive'
        THORAP.attack_speed_ground = 0.91
        THORAP.attack_speed_air = 0.91
        THORAP.attack_point_ground = 0.5936
        THORAP.attack_point_air = 0.1193
        THORAP.hp = 400
        THORAP.shields = 0
        THORAP.armor = 1
        THORAP.shield_armor = 0
        THORAP.range_ground = 7
        THORAP.range_air = 11
        THORAP.leash_range = 0
        THORAP.movement_speed = 2.62
        THORAP.splash_area_air = 0
        THORAP.splash_area_ground = 0
        THORAP.size = 2 # Size is in diameter
        THORAP.attribute = ['Armored', 'Mechanical','Massive']
        THORAP.is_air = False
        THORAP.is_ground = True
        THORAP.minerals = self.calculate_unit_value(THORAP).minerals
        THORAP.vespene = self.calculate_unit_value(THORAP).vespene
        THORAP.supply = self.calculate_supply_cost(THORAP) # Training/morph cost, so upgraded units must count their base units!
        
        VIKINGFIGHTER.attacks_ground = 0
        VIKINGFIGHTER.attacks_air = 2
        VIKINGFIGHTER.dmg_ground = 0
        VIKINGFIGHTER.dmg_air = 10
        VIKINGFIGHTER.bonus_dmg_ground = 0
        VIKINGFIGHTER.bonus_dmg_air = 4
        VIKINGFIGHTER.bonus_attr_ground = None
        VIKINGFIGHTER.bonus_attr_air = 'Armored'
        VIKINGFIGHTER.attack_speed_ground = 1.43
        VIKINGFIGHTER.attack_speed_air = 1.43
        VIKINGFIGHTER.attack_point_ground = 0.1193
        VIKINGFIGHTER.attack_point_air = 0.1193
        VIKINGFIGHTER.hp = 125
        VIKINGFIGHTER.shields = 0
        VIKINGFIGHTER.armor = 0
        VIKINGFIGHTER.shield_armor = 0
        VIKINGFIGHTER.range_ground = 0
        VIKINGFIGHTER.range_air = 9
        VIKINGFIGHTER.leash_range = 0
        VIKINGFIGHTER.movement_speed = 3.85
        VIKINGFIGHTER.splash_area_air = 0
        VIKINGFIGHTER.splash_area_ground = 0
        VIKINGFIGHTER.size = 1.5 # Size is in diameter
        VIKINGFIGHTER.attribute = ['Armored', 'Mechanical']
        VIKINGFIGHTER.is_air = True
        VIKINGFIGHTER.is_ground = False
        VIKINGFIGHTER.minerals = self.calculate_unit_value(VIKINGFIGHTER).minerals
        VIKINGFIGHTER.vespene = self.calculate_unit_value(VIKINGFIGHTER).vespene
        VIKINGFIGHTER.supply = self.calculate_supply_cost(VIKINGFIGHTER) # Training/morph cost, so upgraded units must count their base units!

        VIKINGASSAULT.attacks_ground = 1
        VIKINGASSAULT.attacks_air = 0
        VIKINGASSAULT.dmg_ground = 12
        VIKINGASSAULT.dmg_air = 0
        VIKINGASSAULT.bonus_dmg_ground = 8
        VIKINGASSAULT.bonus_dmg_air = 0
        VIKINGASSAULT.bonus_attr_ground = 'Mechanical'
        VIKINGASSAULT.bonus_attr_air = None
        VIKINGASSAULT.attack_speed_ground = 0.71
        VIKINGASSAULT.attack_speed_air = 0.71
        VIKINGASSAULT.attack_point_ground = 0.1193
        VIKINGASSAULT.attack_point_air = 0.1193
        VIKINGASSAULT.hp = 125
        VIKINGASSAULT.shields = 0
        VIKINGASSAULT.armor = 0
        VIKINGASSAULT.shield_armor = 0
        VIKINGASSAULT.range_ground = 6
        VIKINGASSAULT.range_air = 0
        VIKINGASSAULT.leash_range = 0
        VIKINGASSAULT.movement_speed = 3.85
        VIKINGASSAULT.splash_area_air = 0
        VIKINGASSAULT.splash_area_ground = 0
        VIKINGASSAULT.size = 1.5 # Size is in diameter
        VIKINGASSAULT.attribute = ['Armored', 'Mechanical']
        VIKINGASSAULT.is_air = False
        VIKINGASSAULT.is_ground = True
        VIKINGASSAULT.minerals = self.calculate_unit_value(VIKINGASSAULT).minerals
        VIKINGASSAULT.vespene = self.calculate_unit_value(VIKINGASSAULT).vespene
        VIKINGASSAULT.supply = self.calculate_supply_cost(VIKINGASSAULT) # Training/morph cost, so upgraded units must count their base units!
        
        LIBERATOR.attacks_ground = 0
        LIBERATOR.attacks_air = 2
        LIBERATOR.dmg_ground = 0
        LIBERATOR.dmg_air = 5
        LIBERATOR.bonus_dmg_ground = 0
        LIBERATOR.bonus_dmg_air = 0
        LIBERATOR.bonus_attr_ground = None
        LIBERATOR.bonus_attr_air = None
        LIBERATOR.attack_speed_ground = 1.29
        LIBERATOR.attack_speed_air = 1.29
        LIBERATOR.attack_point_ground = 0.1193
        LIBERATOR.attack_point_air = 0.1193
        LIBERATOR.hp = 180
        LIBERATOR.shields = 0
        LIBERATOR.armor = 0
        LIBERATOR.shield_armor = 0
        LIBERATOR.range_ground = 0
        LIBERATOR.range_air = 5
        LIBERATOR.leash_range = 0
        LIBERATOR.movement_speed = 4.72
        LIBERATOR.splash_area_air = self.PI*1.5**2
        LIBERATOR.splash_area_ground = 0
        LIBERATOR.size = 1.5 # Size is in diameter
        LIBERATOR.attribute = ['Armored', 'Mechanical']
        LIBERATOR.is_air = True
        LIBERATOR.is_ground = False
        LIBERATOR.minerals = self.calculate_unit_value(LIBERATOR).minerals
        LIBERATOR.vespene = self.calculate_unit_value(LIBERATOR).vespene
        LIBERATOR.supply = self.calculate_supply_cost(LIBERATOR) # Training/morph cost, so upgraded units must count their base units!
        
        LIBERATORAG.attacks_ground = 1
        LIBERATORAG.attacks_air = 0
        LIBERATORAG.dmg_ground = 75
        LIBERATORAG.dmg_air = 0
        LIBERATORAG.bonus_dmg_ground = 0
        LIBERATORAG.bonus_dmg_air = 0
        LIBERATORAG.bonus_attr_ground = None
        LIBERATORAG.bonus_attr_air = None
        LIBERATORAG.attack_speed_ground = 1.14
        LIBERATORAG.attack_speed_air = 1.14
        LIBERATORAG.attack_point_ground = 1.14
        LIBERATORAG.attack_point_air = 1.14
        LIBERATORAG.hp = 180
        LIBERATORAG.shields = 0
        LIBERATORAG.armor = 0
        LIBERATORAG.shield_armor = 0
        LIBERATORAG.range_ground = 10+3
        LIBERATORAG.range_air = 0
        LIBERATORAG.leash_range = 0
        LIBERATORAG.movement_speed = 0
        LIBERATORAG.splash_area_air = 0
        LIBERATORAG.splash_area_ground = 0
        LIBERATORAG.size = 1.5 # Size is in diameter
        LIBERATORAG.attribute = ['Armored', 'Mechanical']
        LIBERATORAG.is_air = True
        LIBERATORAG.is_ground = False
        LIBERATORAG.minerals = self.calculate_unit_value(LIBERATORAG).minerals
        LIBERATORAG.vespene = self.calculate_unit_value(LIBERATORAG).vespene
        LIBERATORAG.supply = self.calculate_supply_cost(LIBERATORAG) # Training/morph cost, so upgraded units must count their base units!
        
        BANSHEE.attacks_ground = 2
        BANSHEE.attacks_air = 0
        BANSHEE.dmg_ground = 12
        BANSHEE.dmg_air = 0
        BANSHEE.bonus_dmg_ground = 0
        BANSHEE.bonus_dmg_air = 0
        BANSHEE.bonus_attr_ground = None
        BANSHEE.bonus_attr_air = None
        BANSHEE.attack_speed_ground = 0.89
        BANSHEE.attack_speed_air = 0
        BANSHEE.attack_point_ground = 0.1193
        BANSHEE.attack_point_air = 0
        BANSHEE.hp = 140
        BANSHEE.shields = 0
        BANSHEE.armor = 0
        BANSHEE.shield_armor = 0
        BANSHEE.range_ground = 6
        BANSHEE.range_air = 0
        BANSHEE.leash_range = 0
        BANSHEE.movement_speed = 3.85+1.4
        BANSHEE.splash_area_air = 0
        BANSHEE.splash_area_ground = 0
        BANSHEE.size = 1.5 # Size is in diameter
        BANSHEE.attribute = ['Light', 'Mechanical']
        BANSHEE.is_air = True
        BANSHEE.is_ground = False
        BANSHEE.minerals = self.calculate_unit_value(BANSHEE).minerals
        BANSHEE.vespene = self.calculate_unit_value(BANSHEE).vespene
        BANSHEE.supply = self.calculate_supply_cost(BANSHEE) # Training/morph cost, so upgraded units must count their base units!
        
        BATTLECRUISER.attacks_ground = 1
        BATTLECRUISER.attacks_air = 1
        BATTLECRUISER.dmg_ground = 8
        BATTLECRUISER.dmg_air = 5
        BATTLECRUISER.bonus_dmg_ground = 0
        BATTLECRUISER.bonus_dmg_air = 0
        BATTLECRUISER.bonus_attr_ground = None
        BATTLECRUISER.bonus_attr_air = None
        BATTLECRUISER.attack_speed_ground = 0.16
        BATTLECRUISER.attack_speed_air = 0.16
        BATTLECRUISER.attack_point_ground = 0
        BATTLECRUISER.attack_point_air = 0
        BATTLECRUISER.hp = 550
        BATTLECRUISER.shields = 0
        BATTLECRUISER.armor = 3
        BATTLECRUISER.shield_armor = 0
        BATTLECRUISER.range_ground = 6
        BATTLECRUISER.range_air = 6
        BATTLECRUISER.leash_range = 0
        BATTLECRUISER.movement_speed = 2.62
        BATTLECRUISER.splash_area_air = 0
        BATTLECRUISER.splash_area_ground = 0
        BATTLECRUISER.size = 1.5 # Size is in diameter
        BATTLECRUISER.attribute = ['Armored', 'Mechanical', 'Massive']
        BATTLECRUISER.is_air = True
        BATTLECRUISER.is_ground = False
        BATTLECRUISER.minerals = self.calculate_unit_value(BATTLECRUISER).minerals
        BATTLECRUISER.vespene = self.calculate_unit_value(BATTLECRUISER).vespene
        BATTLECRUISER.supply = self.calculate_supply_cost(BATTLECRUISER) # Training/morph cost, so upgraded units must count their base units!
        
        
        # Protoss: Note that warp prism and observers have different forms with different names! 
        # Excluded units: High Templar, Observer, Warp Prism, Interceptor
        self.protoss_army = [ZEALOT, STALKER, SENTRY, ADEPT, DARKTEMPLAR, ARCHON, IMMORTAL, COLOSSUS, DISRUPTOR, PHOENIX, ORACLE, VOIDRAY, TEMPEST, CARRIER, MOTHERSHIP]
        
        ZEALOT.attacks_ground = 2
        ZEALOT.attacks_air = 0
        ZEALOT.dmg_ground = 8
        ZEALOT.dmg_air = 0
        ZEALOT.bonus_dmg_ground = 0
        ZEALOT.bonus_dmg_air = 0
        ZEALOT.bonus_attr_ground = None
        ZEALOT.bonus_attr_air = None
        ZEALOT.attack_speed_ground = 0.86
        ZEALOT.attack_speed_air = 0.86
        ZEALOT.attack_point_ground = 0
        ZEALOT.attack_point_air = 0
        ZEALOT.hp = 100
        ZEALOT.shields = 50
        ZEALOT.armor = 1
        ZEALOT.shield_armor = 0
        ZEALOT.range_ground = 0.1
        ZEALOT.range_air = 0
        ZEALOT.leash_range = 0
        ZEALOT.movement_speed = 3.15*1.5
        ZEALOT.splash_area_air = 0
        ZEALOT.splash_area_ground = 0
        ZEALOT.size = 1 # Size is in diameter
        ZEALOT.attribute = ['Light', 'Biological']
        ZEALOT.is_air = False
        ZEALOT.is_ground = True
        ZEALOT.minerals = self.calculate_unit_value(ZEALOT).minerals
        ZEALOT.vespene = self.calculate_unit_value(ZEALOT).vespene
        ZEALOT.supply = self.calculate_supply_cost(ZEALOT) # Training/morph cost, so upgraded units must count their base units!
        
        STALKER.attacks_ground = 1
        STALKER.attacks_air = 1
        STALKER.dmg_ground = 13
        STALKER.dmg_air = 13
        STALKER.bonus_dmg_ground = 5
        STALKER.bonus_dmg_air = 5
        STALKER.bonus_attr_ground = 'Armored'
        STALKER.bonus_attr_air = 'Armored'
        STALKER.attack_speed_ground = 1.34
        STALKER.attack_speed_air = 1.34
        STALKER.attack_point_ground = 0.1193
        STALKER.attack_point_air = 0.1193
        STALKER.hp = 80
        STALKER.shields = 80
        STALKER.armor = 1
        STALKER.shield_armor = 0
        STALKER.range_ground = 6
        STALKER.range_air = 6
        STALKER.leash_range = 0
        STALKER.movement_speed = 4.13
        STALKER.splash_area_air = 0
        STALKER.splash_area_ground = 0
        STALKER.size = 1.25 # Size is in diameter
        STALKER.attribute = ['Armored', 'Mechanical']
        STALKER.is_air = False
        STALKER.is_ground = True
        STALKER.minerals = self.calculate_unit_value(STALKER).minerals
        STALKER.vespene = self.calculate_unit_value(STALKER).vespene
        STALKER.supply = self.calculate_supply_cost(STALKER) # Training/morph cost, so upgraded units must count their base units!
        
        SENTRY.attacks_ground = 1
        SENTRY.attacks_air = 1
        SENTRY.dmg_ground = 6
        SENTRY.dmg_air = 6
        SENTRY.bonus_dmg_ground = 0
        SENTRY.bonus_dmg_air = 0
        SENTRY.bonus_attr_ground = None
        SENTRY.bonus_attr_air = None
        SENTRY.attack_speed_ground = 0.71
        SENTRY.attack_speed_air = 0.71
        SENTRY.attack_point_ground = 0.1193
        SENTRY.attack_point_air = 0.1193
        SENTRY.hp = 40
        SENTRY.shields = 40
        SENTRY.armor = 1
        SENTRY.shield_armor = 0
        SENTRY.range_ground = 5
        SENTRY.range_air = 5
        SENTRY.leash_range = 0
        SENTRY.movement_speed = 3.15
        SENTRY.splash_area_air = 0
        SENTRY.splash_area_ground = 0
        SENTRY.size = 1 # Size is in diameter
        SENTRY.attribute = ['Light', 'Mechanical', 'Psionic']
        SENTRY.is_air = False
        SENTRY.is_ground = True
        SENTRY.minerals = self.calculate_unit_value(SENTRY).minerals
        SENTRY.vespene = self.calculate_unit_value(SENTRY).vespene
        SENTRY.supply = self.calculate_supply_cost(SENTRY) # Training/morph cost, so upgraded units must count their base units!
        
        ADEPT.attacks_ground = 1*1.45
        ADEPT.attacks_air = 0
        ADEPT.dmg_ground = 10
        ADEPT.dmg_air = 0
        ADEPT.bonus_dmg_ground = 12
        ADEPT.bonus_dmg_air = 0
        ADEPT.bonus_attr_ground = 'Light'
        ADEPT.bonus_attr_air = None
        ADEPT.attack_speed_ground = 1.61
        ADEPT.attack_speed_air = 1.61
        ADEPT.attack_point_ground = 0.1193
        ADEPT.attack_point_air = 0.1193
        ADEPT.hp = 70
        ADEPT.shields = 70
        ADEPT.armor = 1
        ADEPT.shield_armor = 0
        ADEPT.range_ground = 4
        ADEPT.range_air = 0
        ADEPT.leash_range = 0
        ADEPT.movement_speed = 3.5
        ADEPT.splash_area_air = 0
        ADEPT.splash_area_ground = 0
        ADEPT.size = 1 # Size is in diameter
        ADEPT.attribute = ['Light', 'Biological']
        ADEPT.is_air = False
        ADEPT.is_ground = True
        ADEPT.minerals = self.calculate_unit_value(ADEPT).minerals
        ADEPT.vespene = self.calculate_unit_value(ADEPT).vespene
        ADEPT.supply = self.calculate_supply_cost(ADEPT) # Training/morph cost, so upgraded units must count their base units!
        
        DARKTEMPLAR.attacks_ground = 1
        DARKTEMPLAR.attacks_air = 0
        DARKTEMPLAR.dmg_ground = 45
        DARKTEMPLAR.dmg_air = 0
        DARKTEMPLAR.bonus_dmg_ground = 0
        DARKTEMPLAR.bonus_dmg_air = 0
        DARKTEMPLAR.bonus_attr_ground = None
        DARKTEMPLAR.bonus_attr_air = None
        DARKTEMPLAR.attack_speed_ground = 1.21
        DARKTEMPLAR.attack_speed_air = 0
        DARKTEMPLAR.attack_point_ground = 0.2579
        DARKTEMPLAR.attack_point_air = 0.2579
        DARKTEMPLAR.hp = 40
        DARKTEMPLAR.shields = 80
        DARKTEMPLAR.armor = 1
        DARKTEMPLAR.shield_armor = 0
        DARKTEMPLAR.range_ground = 0.1
        DARKTEMPLAR.range_air = 0
        DARKTEMPLAR.leash_range = 0
        DARKTEMPLAR.movement_speed = 3.94
        DARKTEMPLAR.splash_area_air = 0
        DARKTEMPLAR.splash_area_ground = 0
        DARKTEMPLAR.size = 0.75 # Size is in diameter
        DARKTEMPLAR.attribute = ['Light', 'Biological']
        DARKTEMPLAR.is_air = False
        DARKTEMPLAR.is_ground = True
        DARKTEMPLAR.minerals = self.calculate_unit_value(DARKTEMPLAR).minerals
        DARKTEMPLAR.vespene = self.calculate_unit_value(DARKTEMPLAR).vespene
        DARKTEMPLAR.supply = self.calculate_supply_cost(DARKTEMPLAR) # Training/morph cost, so upgraded units must count their base units!
        
        ARCHON.attacks_ground = 1
        ARCHON.attacks_air = 1
        ARCHON.dmg_ground = 25
        ARCHON.dmg_air = 25
        ARCHON.bonus_dmg_ground = 10
        ARCHON.bonus_dmg_air = 10
        ARCHON.bonus_attr_ground = 'Biological'
        ARCHON.bonus_attr_air = 'Biological'
        ARCHON.attack_speed_ground = 1.25
        ARCHON.attack_speed_air = 1.25
        ARCHON.attack_point_ground = 0.1193
        ARCHON.attack_point_air = 0.1193
        ARCHON.hp = 10
        ARCHON.shields = 350
        ARCHON.armor = 1
        ARCHON.shield_armor = 0
        ARCHON.range_ground = 3
        ARCHON.range_air = 3
        ARCHON.leash_range = 0
        ARCHON.movement_speed = 3.94
        ARCHON.splash_area_air = self.PI*(0.25**2 + (0.5**2-0.25**2)*0.5 + (1**2-0.5**2)*0.25)
        ARCHON.splash_area_ground = self.PI*(0.25**2 + (0.5**2-0.25**2)*0.5 + (1**2-0.5**2)*0.25)
        ARCHON.size = 2 # Size is in diameter
        ARCHON.attribute = ['Massive', 'Psionic']
        ARCHON.is_air = False
        ARCHON.is_ground = True
        ARCHON.minerals = self.calculate_unit_value(HIGHTEMPLAR).minerals*2 # If we want to make archons, we will use HTs not DTs.
        ARCHON.vespene = self.calculate_unit_value(HIGHTEMPLAR).vespene*2
        ARCHON.supply = self.calculate_supply_cost(ARCHON) # Training/morph cost, so upgraded units must count their base units!
        
        IMMORTAL.attacks_ground = 1
        IMMORTAL.attacks_air = 0
        IMMORTAL.dmg_ground = 20
        IMMORTAL.dmg_air = 0
        IMMORTAL.bonus_dmg_ground = 30
        IMMORTAL.bonus_dmg_air = 0
        IMMORTAL.bonus_attr_ground = 'Armored'
        IMMORTAL.bonus_attr_air = None
        IMMORTAL.attack_speed_ground = 1.04
        IMMORTAL.attack_speed_air = 1.04
        IMMORTAL.attack_point_ground = 0.1193
        IMMORTAL.attack_point_air = 0.1193
        IMMORTAL.hp = 200
        IMMORTAL.shields = 100 + 100 # We will count barrier as +100 shields
        IMMORTAL.armor = 1
        IMMORTAL.shield_armor = 0
        IMMORTAL.range_ground = 6
        IMMORTAL.range_air = 0
        IMMORTAL.leash_range = 0
        IMMORTAL.movement_speed = 3.15
        IMMORTAL.splash_area_air = 0
        IMMORTAL.splash_area_ground = 0
        IMMORTAL.size = 1.5 # Size is in diameter
        IMMORTAL.attribute = ['Armored', 'Mechanical']
        IMMORTAL.is_air = False
        IMMORTAL.is_ground = True
        IMMORTAL.minerals = self.calculate_unit_value(IMMORTAL).minerals
        IMMORTAL.vespene = self.calculate_unit_value(IMMORTAL).vespene
        IMMORTAL.supply = self.calculate_supply_cost(IMMORTAL) # Training/morph cost, so upgraded units must count their base units!
        
        COLOSSUS.attacks_ground = 2
        COLOSSUS.attacks_air = 0
        COLOSSUS.dmg_ground = 10
        COLOSSUS.dmg_air = 0
        COLOSSUS.bonus_dmg_ground = 5
        COLOSSUS.bonus_dmg_air = 0
        COLOSSUS.bonus_attr_ground = 'Light'
        COLOSSUS.bonus_attr_air = None
        COLOSSUS.attack_speed_ground = 1.07
        COLOSSUS.attack_speed_air = 1.07
        COLOSSUS.attack_point_ground = 0.0594
        COLOSSUS.attack_point_air = 0.0594
        COLOSSUS.hp = 200
        COLOSSUS.shields = 150
        COLOSSUS.armor = 1
        COLOSSUS.shield_armor = 0
        COLOSSUS.range_ground = 7+2
        COLOSSUS.range_air = 0
        COLOSSUS.leash_range = 0
        COLOSSUS.movement_speed = 3.15
        COLOSSUS.splash_area_air = 0
        COLOSSUS.splash_area_ground = 2.8
        COLOSSUS.size = 2 # Size is in diameter
        COLOSSUS.attribute = ['Armored', 'Mechanical', 'Massive']
        COLOSSUS.is_air = True
        COLOSSUS.is_ground = True
        COLOSSUS.minerals = self.calculate_unit_value(COLOSSUS).minerals
        COLOSSUS.vespene = self.calculate_unit_value(COLOSSUS).vespene
        COLOSSUS.supply = self.calculate_supply_cost(COLOSSUS) # Training/morph cost, so upgraded units must count their base units!
        
        DISRUPTOR.attacks_ground = 1
        DISRUPTOR.attacks_air = 0
        DISRUPTOR.dmg_ground = 145
        DISRUPTOR.dmg_air = 0
        DISRUPTOR.bonus_dmg_ground = 0
        DISRUPTOR.bonus_dmg_air = 0
        DISRUPTOR.bonus_attr_ground = None
        DISRUPTOR.bonus_attr_air = None
        DISRUPTOR.attack_speed_ground = 21.4
        DISRUPTOR.attack_speed_air = 21.4
        DISRUPTOR.attack_point_ground = 2.1
        DISRUPTOR.attack_point_air = 2.1
        DISRUPTOR.hp = 100
        DISRUPTOR.shields = 100
        DISRUPTOR.armor = 1
        DISRUPTOR.shield_armor = 0
        DISRUPTOR.range_ground = 11
        DISRUPTOR.range_air = 0
        DISRUPTOR.leash_range = 0
        DISRUPTOR.movement_speed = 3.15
        DISRUPTOR.splash_area_air = 0
        DISRUPTOR.splash_area_ground = self.PI*1.5**2
        DISRUPTOR.size = 1 # Size is in diameter
        DISRUPTOR.attribute = ['Armored', 'Mechanical']
        DISRUPTOR.is_air = False
        DISRUPTOR.is_ground = True
        DISRUPTOR.minerals = self.calculate_unit_value(DISRUPTOR).minerals
        DISRUPTOR.vespene = self.calculate_unit_value(DISRUPTOR).vespene
        DISRUPTOR.supply = self.calculate_supply_cost(DISRUPTOR) # Training/morph cost, so upgraded units must count their base units!
        
        PHOENIX.attacks_ground = 0
        PHOENIX.attacks_air = 2
        PHOENIX.dmg_ground = 0
        PHOENIX.dmg_air = 5
        PHOENIX.bonus_dmg_ground = 0
        PHOENIX.bonus_dmg_air = 5
        PHOENIX.bonus_attr_ground = None
        PHOENIX.bonus_attr_air = 'Light'
        PHOENIX.attack_speed_ground = 0.79
        PHOENIX.attack_speed_air = 0.79
        PHOENIX.attack_point_ground = 0
        PHOENIX.attack_point_air = 0
        PHOENIX.hp = 120
        PHOENIX.shields = 60
        PHOENIX.armor = 0
        PHOENIX.shield_armor = 0
        PHOENIX.range_ground = 0
        PHOENIX.range_air = 5+2
        PHOENIX.leash_range = 0
        PHOENIX.movement_speed = 5.95
        PHOENIX.splash_area_air = 0
        PHOENIX.splash_area_ground = 0
        PHOENIX.size = 1.5 # Size is in diameter
        PHOENIX.attribute = ['Light', 'Mechanical']
        PHOENIX.is_air = True
        PHOENIX.is_ground = False
        PHOENIX.minerals = self.calculate_unit_value(PHOENIX).minerals
        PHOENIX.vespene = self.calculate_unit_value(PHOENIX).vespene
        PHOENIX.supply = self.calculate_supply_cost(PHOENIX) # Training/morph cost, so upgraded units must count their base units!
        
        ORACLE.attacks_ground = 1
        ORACLE.attacks_air = 0
        ORACLE.dmg_ground = 15
        ORACLE.dmg_air = 0
        ORACLE.bonus_dmg_ground = 7
        ORACLE.bonus_dmg_air = 0
        ORACLE.bonus_attr_ground = 'Light'
        ORACLE.bonus_attr_air = None
        ORACLE.attack_speed_ground = 0.61
        ORACLE.attack_speed_air = 0.61
        ORACLE.attack_point_ground = 0.1193
        ORACLE.attack_point_air = 0.1193
        ORACLE.hp = 100 
        ORACLE.shields = 60
        ORACLE.armor = 0
        ORACLE.shield_armor = 0
        ORACLE.range_ground = 4
        ORACLE.range_air = 0
        ORACLE.leash_range = 0
        ORACLE.movement_speed = 5.6
        ORACLE.splash_area_air = 0
        ORACLE.splash_area_ground = 0
        ORACLE.size = 1.5 # Size is in diameter
        ORACLE.attribute = ['Armored', 'Mechanical']
        ORACLE.is_air = True
        ORACLE.is_ground = False
        ORACLE.minerals = self.calculate_unit_value(ORACLE).minerals
        ORACLE.vespene = self.calculate_unit_value(ORACLE).vespene
        ORACLE.supply = self.calculate_supply_cost(ORACLE) # Training/morph cost, so upgraded units must count their base units!
        
        VOIDRAY.attacks_ground = 1
        VOIDRAY.attacks_air = 1
        VOIDRAY.dmg_ground = 6
        VOIDRAY.dmg_air = 6
        VOIDRAY.bonus_dmg_ground = 4+6
        VOIDRAY.bonus_dmg_air = 4+6
        VOIDRAY.bonus_attr_ground = 'Armored'
        VOIDRAY.bonus_attr_air = 'Armored'
        VOIDRAY.attack_speed_ground = 0.36
        VOIDRAY.attack_speed_air = 0.36
        VOIDRAY.attack_point_ground = 0.1193
        VOIDRAY.attack_point_air = 0.1193
        VOIDRAY.hp = 150 
        VOIDRAY.shields = 100
        VOIDRAY.armor = 0
        VOIDRAY.shield_armor = 0
        VOIDRAY.range_ground = 6
        VOIDRAY.range_air = 6
        VOIDRAY.leash_range = 0
        VOIDRAY.movement_speed = 3.5
        VOIDRAY.splash_area_air = 0
        VOIDRAY.splash_area_ground = 0
        VOIDRAY.size = 2 # Size is in diameter
        VOIDRAY.attribute = ['Armored', 'Mechanical']
        VOIDRAY.is_air = True
        VOIDRAY.is_ground = False
        VOIDRAY.minerals = self.calculate_unit_value(VOIDRAY).minerals
        VOIDRAY.vespene = self.calculate_unit_value(VOIDRAY).vespene
        VOIDRAY.supply = self.calculate_supply_cost(VOIDRAY) # Training/morph cost, so upgraded units must count their base units!
        
        TEMPEST.attacks_ground = 1
        TEMPEST.attacks_air = 1
        TEMPEST.dmg_ground = 40
        TEMPEST.dmg_air = 30
        TEMPEST.bonus_dmg_ground = 0
        TEMPEST.bonus_dmg_air = 22
        TEMPEST.bonus_attr_ground = None
        TEMPEST.bonus_attr_air = 'Massive'
        TEMPEST.attack_speed_ground = 2.36
        TEMPEST.attack_speed_air = 2.36
        TEMPEST.attack_point_ground = 0.1193
        TEMPEST.attack_point_air = 0.1193
        TEMPEST.hp = 200 
        TEMPEST.shields = 100
        TEMPEST.armor = 2
        TEMPEST.shield_armor = 0
        TEMPEST.range_ground = 10
        TEMPEST.range_air = 14
        TEMPEST.leash_range = 0
        TEMPEST.movement_speed = 3.15
        TEMPEST.splash_area_air = 0
        TEMPEST.splash_area_ground = 0
        TEMPEST.size = 2.5 # Size is in diameter
        TEMPEST.attribute = ['Armored', 'Mechanical', 'Massive']
        TEMPEST.is_air = True
        TEMPEST.is_ground = False
        TEMPEST.minerals = self.calculate_unit_value(TEMPEST).minerals
        TEMPEST.vespene = self.calculate_unit_value(TEMPEST).vespene
        TEMPEST.supply = self.calculate_supply_cost(TEMPEST) # Training/morph cost, so upgraded units must count their base units!
        
        INTERCEPTOR.attacks_ground = 2
        INTERCEPTOR.attacks_air = 2
        INTERCEPTOR.dmg_ground = 5
        INTERCEPTOR.dmg_air = 5
        INTERCEPTOR.bonus_dmg_ground = 0
        INTERCEPTOR.bonus_dmg_air = 0
        INTERCEPTOR.bonus_attr_ground = None
        INTERCEPTOR.bonus_attr_air = None
        INTERCEPTOR.attack_speed_ground = 2.14
        INTERCEPTOR.attack_speed_air = 2.14
        INTERCEPTOR.attack_point_ground = 0.27
        INTERCEPTOR.attack_point_air = 0.27
        INTERCEPTOR.hp = 40
        INTERCEPTOR.shields = 40
        INTERCEPTOR.armor = 0
        INTERCEPTOR.shield_armor = 0
        INTERCEPTOR.range_ground = 8
        INTERCEPTOR.range_air = 8
        INTERCEPTOR.leash_range = 14
        INTERCEPTOR.movement_speed = 2.62
        INTERCEPTOR.splash_area_air = 0
        INTERCEPTOR.splash_area_ground = 0
        INTERCEPTOR.size = 0.5 # Size is in diameter
        INTERCEPTOR.attribute = ['Light', 'Mechanical']
        INTERCEPTOR.is_air = True
        INTERCEPTOR.is_ground = False
        INTERCEPTOR.minerals = self.calculate_unit_value(INTERCEPTOR).minerals
        INTERCEPTOR.vespene = self.calculate_unit_value(INTERCEPTOR).vespene
        INTERCEPTOR.supply = self.calculate_supply_cost(INTERCEPTOR) # Training/morph cost, so upgraded units must count their base units!
        
        CARRIER.attacks_ground = 2*8
        CARRIER.attacks_air = 2*8
        CARRIER.dmg_ground = 5
        CARRIER.dmg_air = 5
        CARRIER.bonus_dmg_ground = 0
        CARRIER.bonus_dmg_air = 0
        CARRIER.bonus_attr_ground = None
        CARRIER.bonus_attr_air = None
        CARRIER.attack_speed_ground = 2.14
        CARRIER.attack_speed_air = 2.14
        CARRIER.attack_point_ground = 0
        CARRIER.attack_point_air = 0
        CARRIER.hp = 300
        CARRIER.shields = 150
        CARRIER.armor = 2
        CARRIER.shield_armor = 0
        CARRIER.range_ground = 8
        CARRIER.range_air = 8
        CARRIER.leash_range = 14
        CARRIER.movement_speed = 2.62
        CARRIER.splash_area_air = 0
        CARRIER.splash_area_ground = 0
        CARRIER.size = 2.5 # Size is in diameter
        CARRIER.attribute = ['Armored', 'Mechanical', 'Massive']
        CARRIER.is_air = True
        CARRIER.is_ground = False
        CARRIER.minerals = self.calculate_unit_value(CARRIER).minerals
        CARRIER.vespene = self.calculate_unit_value(CARRIER).vespene
        CARRIER.supply = self.calculate_supply_cost(CARRIER) # Training/morph cost, so upgraded units must count their base units!
        
        MOTHERSHIP.attacks_ground = 6
        MOTHERSHIP.attacks_air = 6
        MOTHERSHIP.dmg_ground = 6
        MOTHERSHIP.dmg_air = 6
        MOTHERSHIP.bonus_dmg_ground = 0
        MOTHERSHIP.bonus_dmg_air = 0
        MOTHERSHIP.bonus_attr_ground = None
        MOTHERSHIP.bonus_attr_air = None
        MOTHERSHIP.attack_speed_ground = 1.58
        MOTHERSHIP.attack_speed_air = 1.58
        MOTHERSHIP.attack_point_ground = 0
        MOTHERSHIP.attack_point_air = 0
        MOTHERSHIP.hp = 350
        MOTHERSHIP.shields = 350
        MOTHERSHIP.armor = 2
        MOTHERSHIP.shield_armor = 0
        MOTHERSHIP.range_ground = 7
        MOTHERSHIP.range_air = 7
        MOTHERSHIP.leash_range = 0
        MOTHERSHIP.movement_speed = 2.62
        MOTHERSHIP.splash_area_air = 0
        MOTHERSHIP.splash_area_ground = 0
        MOTHERSHIP.size = 2.75 # Size is in diameter
        MOTHERSHIP.attribute = ['Armored', 'Mechanical', 'Psionic', 'Massive', 'Heroic']
        MOTHERSHIP.is_air = True
        MOTHERSHIP.is_ground = False
        MOTHERSHIP.minerals = self.calculate_unit_value(MOTHERSHIP).minerals
        MOTHERSHIP.vespene = self.calculate_unit_value(MOTHERSHIP).vespene
        MOTHERSHIP.supply = self.calculate_supply_cost(MOTHERSHIP) # Training/morph cost, so upgraded units must count their base units!
        
        
        # Zerg: Note that all zerg ground units can burrow! 
        # Excluded units: Vipers, Infestors, Swarm hosts, Overseers, Overlords, Broodlings, Locusts, Banelings
        # How do we count the combat strength of swarm hosts and brood lords? What about spellcasters? What about banelings?
        self.zerg_army = [ZERGLING, ROACH, RAVAGER, HYDRALISK, LURKERMP, QUEEN, MUTALISK, CORRUPTOR, BROODLORD, ULTRALISK]
        
        ZERGLING.attacks_ground = 1*1.4
        ZERGLING.attacks_air = 0
        ZERGLING.dmg_ground = 5
        ZERGLING.dmg_air = 0
        ZERGLING.bonus_dmg_ground = 0
        ZERGLING.bonus_dmg_air = 0
        ZERGLING.bonus_attr_ground = None
        ZERGLING.bonus_attr_air = None
        ZERGLING.attack_speed_ground = 0.497
        ZERGLING.attack_speed_air = 0.497
        ZERGLING.attack_point_ground = 0.1193
        ZERGLING.attack_point_air = 0.1193
        ZERGLING.hp = 35
        ZERGLING.shields = 0
        ZERGLING.armor = 0
        ZERGLING.shield_armor = 0
        ZERGLING.range_ground = 0.1
        ZERGLING.range_air = 0
        ZERGLING.leash_range = 0
        ZERGLING.movement_speed = 4.13*1.6
        ZERGLING.splash_area_air = 0
        ZERGLING.splash_area_ground = 0
        ZERGLING.size = 0.75 # Size is in diameter
        ZERGLING.attribute = ['Light', 'Biological']
        ZERGLING.is_air = False
        ZERGLING.is_ground = True
        ZERGLING.minerals = self.calculate_unit_value(ZERGLING).minerals
        ZERGLING.vespene = self.calculate_unit_value(ZERGLING).vespene
        ZERGLING.supply = self.calculate_supply_cost(ZERGLING) # Training/morph cost, so upgraded units must count their base units!
        
        ROACH.attacks_ground = 1
        ROACH.attacks_air = 0
        ROACH.dmg_ground = 16
        ROACH.dmg_air = 0
        ROACH.bonus_dmg_ground = 0
        ROACH.bonus_dmg_air = 0
        ROACH.bonus_attr_ground = None
        ROACH.bonus_attr_air = None
        ROACH.attack_speed_ground = 1.43
        ROACH.attack_speed_air = 1.43
        ROACH.attack_point_ground = 0.1193
        ROACH.attack_point_air = 0.1193
        ROACH.hp = 145
        ROACH.shields = 0
        ROACH.armor = 1
        ROACH.shield_armor = 0
        ROACH.range_ground = 4
        ROACH.range_air = 0
        ROACH.leash_range = 0
        ROACH.movement_speed = 3.15+1.05
        ROACH.splash_area_air = 0
        ROACH.splash_area_ground = 0
        ROACH.size = 1 # Size is in diameter
        ROACH.attribute = ['Armored', 'Biological']
        ROACH.is_air = False
        ROACH.is_ground = True
        ROACH.minerals = self.calculate_unit_value(ROACH).minerals
        ROACH.vespene = self.calculate_unit_value(ROACH).vespene
        ROACH.supply = self.calculate_supply_cost(ROACH) # Training/morph cost, so upgraded units must count their base units!
        
        # Does not include bile!
        RAVAGER.attacks_ground = 1
        RAVAGER.attacks_air = 0
        RAVAGER.dmg_ground = 16
        RAVAGER.dmg_air = 0
        RAVAGER.bonus_dmg_ground = 0
        RAVAGER.bonus_dmg_air = 0
        RAVAGER.bonus_attr_ground = None
        RAVAGER.bonus_attr_air = None
        RAVAGER.attack_speed_ground = 1.14
        RAVAGER.attack_speed_air = 1.14
        RAVAGER.attack_point_ground = 0.1429
        RAVAGER.attack_point_air = 0.1429
        RAVAGER.hp = 120
        RAVAGER.shields = 0
        RAVAGER.armor = 1
        RAVAGER.shield_armor = 0
        RAVAGER.range_ground = 6
        RAVAGER.range_air = 0
        RAVAGER.leash_range = 0
        RAVAGER.movement_speed = 3.85
        RAVAGER.splash_area_air = 0
        RAVAGER.splash_area_ground = 0
        RAVAGER.size = 1.5 # Size is in diameter
        RAVAGER.attribute = ['Biological']
        RAVAGER.is_air = False
        RAVAGER.is_ground = True
        RAVAGER.minerals = self.calculate_unit_value(RAVAGER).minerals
        RAVAGER.vespene = self.calculate_unit_value(RAVAGER).vespene
        RAVAGER.supply = self.calculate_supply_cost(RAVAGER) + self.calculate_supply_cost(ROACH) # Training/morph cost, so upgraded units must count their base units!
        
        HYDRALISK.attacks_ground = 1
        HYDRALISK.attacks_air = 1
        HYDRALISK.dmg_ground = 12
        HYDRALISK.dmg_air = 12
        HYDRALISK.bonus_dmg_ground = 0
        HYDRALISK.bonus_dmg_air = 0
        HYDRALISK.bonus_attr_ground = None
        HYDRALISK.bonus_attr_air = None
        HYDRALISK.attack_speed_ground = 0.54
        HYDRALISK.attack_speed_air = 0.54
        HYDRALISK.attack_point_ground = 0.1486
        HYDRALISK.attack_point_air = 0.1486
        HYDRALISK.hp = 90
        HYDRALISK.shields = 0
        HYDRALISK.armor = 0
        HYDRALISK.shield_armor = 0
        HYDRALISK.range_ground = 5+1
        HYDRALISK.range_air = 5+1
        HYDRALISK.leash_range = 0
        HYDRALISK.movement_speed = 3.15+0.7875
        HYDRALISK.splash_area_air = 0
        HYDRALISK.splash_area_ground = 0
        HYDRALISK.size = 1.25 # Size is in diameter
        HYDRALISK.attribute = ['Light', 'Biological']
        HYDRALISK.is_air = False
        HYDRALISK.is_ground = True
        HYDRALISK.minerals = self.calculate_unit_value(HYDRALISK).minerals
        HYDRALISK.vespene = self.calculate_unit_value(HYDRALISK).vespene
        HYDRALISK.supply = self.calculate_supply_cost(HYDRALISK) # Training/morph cost, so upgraded units must count their base units!
        
        # Models splash as radius of 3 of the spikes. 10 spikes are shot, but we assume only 3 are useful!
        LURKERMP.attacks_ground = 1
        LURKERMP.attacks_air = 0
        LURKERMP.dmg_ground = 20
        LURKERMP.dmg_air = 0
        LURKERMP.bonus_dmg_ground = 10
        LURKERMP.bonus_dmg_air = 0
        LURKERMP.bonus_attr_ground = 'Armored'
        LURKERMP.bonus_attr_air = None
        LURKERMP.attack_speed_ground = 1.43
        LURKERMP.attack_speed_air = 1.43
        LURKERMP.attack_point_ground = 1.43
        LURKERMP.attack_point_air = 1.43
        LURKERMP.hp = 200
        LURKERMP.shields = 0
        LURKERMP.armor = 1
        LURKERMP.shield_armor = 0
        LURKERMP.range_ground = 8+2
        LURKERMP.range_air = 0
        LURKERMP.leash_range = 0
        LURKERMP.movement_speed = 4.13
        LURKERMP.splash_area_air = 0
        LURKERMP.splash_area_ground = 3*self.PI*0.5**2
        LURKERMP.size = 1.5 # Size is in diameter
        LURKERMP.attribute = ['Armored', 'Biological']
        LURKERMP.is_air = False
        LURKERMP.is_ground = True
        LURKERMP.minerals = self.calculate_unit_value(LURKERMP).minerals
        LURKERMP.vespene = self.calculate_unit_value(LURKERMP).vespene
        LURKERMP.supply = self.calculate_supply_cost(LURKERMP) + self.calculate_supply_cost(HYDRALISK) # Training/morph cost, so upgraded units must count their base units!
        
        QUEEN.attacks_ground = 2
        QUEEN.attacks_air = 1
        QUEEN.dmg_ground = 4
        QUEEN.dmg_air = 9
        QUEEN.bonus_dmg_ground = 0
        QUEEN.bonus_dmg_air = 0
        QUEEN.bonus_attr_ground = None
        QUEEN.bonus_attr_air = None
        QUEEN.attack_speed_ground = 0.71
        QUEEN.attack_speed_air = 0.71
        QUEEN.attack_point_ground = 0.1193
        QUEEN.attack_point_air = 0.1193
        QUEEN.hp = 175
        QUEEN.shields = 0
        QUEEN.armor = 1
        QUEEN.shield_armor = 0
        QUEEN.range_ground = 5
        QUEEN.range_air = 8
        QUEEN.leash_range = 0
        QUEEN.movement_speed = 1.31
        QUEEN.splash_area_air = 0
        QUEEN.splash_area_ground = 0
        QUEEN.size = 1.75 # Size is in diameter
        QUEEN.attribute = ['Psionic', 'Biological']
        QUEEN.is_air = False
        QUEEN.is_ground = True
        QUEEN.minerals = self.calculate_unit_value(QUEEN).minerals
        QUEEN.vespene = self.calculate_unit_value(QUEEN).vespene
        QUEEN.supply = self.calculate_supply_cost(QUEEN) # Training/morph cost, so upgraded units must count their base units!
        
        # Models bounce damage as 3 hits of average damage (6). Does not reflect the poor scaling of the bounce with upgrades!
        MUTALISK.attacks_ground = 3
        MUTALISK.attacks_air = 3
        MUTALISK.dmg_ground = 6
        MUTALISK.dmg_air = 6
        MUTALISK.bonus_dmg_ground = 0
        MUTALISK.bonus_dmg_air = 0
        MUTALISK.bonus_attr_ground = None
        MUTALISK.bonus_attr_air = None
        MUTALISK.attack_speed_ground = 1.09
        MUTALISK.attack_speed_air = 1.09
        MUTALISK.attack_point_ground = 0
        MUTALISK.attack_point_air = 0
        MUTALISK.hp = 120
        MUTALISK.shields = 0
        MUTALISK.armor = 0
        MUTALISK.shield_armor = 0
        MUTALISK.range_ground = 3
        MUTALISK.range_air = 3
        MUTALISK.leash_range = 0
        MUTALISK.movement_speed = 5.6
        MUTALISK.splash_area_air = 0
        MUTALISK.splash_area_ground = 0
        MUTALISK.size = 1 # Size is in diameter
        MUTALISK.attribute = ['Light', 'Biological']
        MUTALISK.is_air = True
        MUTALISK.is_ground = False
        MUTALISK.minerals = self.calculate_unit_value(MUTALISK).minerals
        MUTALISK.vespene = self.calculate_unit_value(MUTALISK).vespene
        MUTALISK.supply = self.calculate_supply_cost(MUTALISK) # Training/morph cost, so upgraded units must count their base units!
        
        CORRUPTOR.attacks_ground = 0
        CORRUPTOR.attacks_air = 1
        CORRUPTOR.dmg_ground = 0
        CORRUPTOR.dmg_air = 14
        CORRUPTOR.bonus_dmg_ground = 0
        CORRUPTOR.bonus_dmg_air = 6
        CORRUPTOR.bonus_attr_ground = None
        CORRUPTOR.bonus_attr_air = 'Massive'
        CORRUPTOR.attack_speed_ground = 1.36
        CORRUPTOR.attack_speed_air = 1.36
        CORRUPTOR.attack_point_ground = 0.0446
        CORRUPTOR.attack_point_air = 0.0446
        CORRUPTOR.hp = 200
        CORRUPTOR.shields = 0
        CORRUPTOR.armor = 2
        CORRUPTOR.shield_armor = 0
        CORRUPTOR.range_ground = 0
        CORRUPTOR.range_air = 6
        CORRUPTOR.leash_range = 0
        CORRUPTOR.movement_speed = 4.725
        CORRUPTOR.splash_area_air = 0
        CORRUPTOR.splash_area_ground = 0
        CORRUPTOR.size = 1.25 # Size is in diameter
        CORRUPTOR.attribute = ['Armored', 'Biological']
        CORRUPTOR.is_air = True
        CORRUPTOR.is_ground = False
        CORRUPTOR.minerals = self.calculate_unit_value(CORRUPTOR).minerals
        CORRUPTOR.vespene = self.calculate_unit_value(CORRUPTOR).vespene
        CORRUPTOR.supply = self.calculate_supply_cost(CORRUPTOR) # Training/morph cost, so upgraded units must count their base units!
        
        # Assumes that broodlings hit twice each. Does not take into account hp of broodlings, broodlings getting multiple hits, or pathblocking!
        BROODLORD.attacks_ground = 6
        BROODLORD.attacks_air = 0
        BROODLORD.dmg_ground = (20+4*2)/3
        BROODLORD.dmg_air = 0
        BROODLORD.bonus_dmg_ground = 0
        BROODLORD.bonus_dmg_air = 0
        BROODLORD.bonus_attr_ground = None
        BROODLORD.bonus_attr_air = None
        BROODLORD.attack_speed_ground = 1.79*2
        BROODLORD.attack_speed_air = 1.79*2
        BROODLORD.attack_point_ground = 0.1193
        BROODLORD.attack_point_air = 0.1193
        BROODLORD.hp = 225
        BROODLORD.shields = 0
        BROODLORD.armor = 1
        BROODLORD.shield_armor = 0
        BROODLORD.range_ground = 10
        BROODLORD.range_air = 0
        BROODLORD.leash_range = 0
        BROODLORD.movement_speed = 1.97
        BROODLORD.splash_area_air = 0
        BROODLORD.splash_area_ground = 0
        BROODLORD.size = 1.25 # Size is in diameter
        BROODLORD.attribute = ['Armored', 'Biological', 'Massive']
        BROODLORD.is_air = True
        BROODLORD.is_ground = False
        BROODLORD.minerals = self.calculate_unit_value(BROODLORD).minerals
        BROODLORD.vespene = self.calculate_unit_value(BROODLORD).vespene
        BROODLORD.supply = self.calculate_supply_cost(BROODLORD) + self.calculate_supply_cost(CORRUPTOR) # Training/morph cost, so upgraded units must count their base units!
        
        ULTRALISK.attacks_ground = 1
        ULTRALISK.attacks_air = 0
        ULTRALISK.dmg_ground = 35
        ULTRALISK.dmg_air = 0
        ULTRALISK.bonus_dmg_ground = 0
        ULTRALISK.bonus_dmg_air = 0
        ULTRALISK.bonus_attr_ground = None
        ULTRALISK.bonus_attr_air = None
        ULTRALISK.attack_speed_ground = 0.61
        ULTRALISK.attack_speed_air = 0.61
        ULTRALISK.attack_point_ground = 0.238
        ULTRALISK.attack_point_air = 0.238
        ULTRALISK.hp = 500
        ULTRALISK.shields = 0
        ULTRALISK.armor = 2+2
        ULTRALISK.shield_armor = 0
        ULTRALISK.range_ground = 10
        ULTRALISK.range_air = 0
        ULTRALISK.leash_range = 0
        ULTRALISK.movement_speed = 4.13+0.82
        ULTRALISK.splash_area_air = 0
        ULTRALISK.splash_area_ground = 0.33*(self.PI*2**2)/2
        ULTRALISK.size = 2 # Size is in diameter
        ULTRALISK.attribute = ['Armored', 'Biological', 'Massive']
        ULTRALISK.is_air = False
        ULTRALISK.is_ground = True
        ULTRALISK.minerals = self.calculate_unit_value(ULTRALISK).minerals
        ULTRALISK.vespene = self.calculate_unit_value(ULTRALISK).vespene
        ULTRALISK.supply = self.calculate_supply_cost(ULTRALISK) # Training/morph cost, so upgraded units must count their base units!
        
        
            
def main():
    sc2.run_game(
        sc2.maps.get("ZenLE"),
        #[Human(Race.Terran, name="VictimOfSkyNet"),Bot(Race.Protoss, MacroBot(), name="AncoraImparo")],
        [Bot(Race.Protoss, MacroBot(), name="AncoraImparo"), Computer(Race.Protoss, Difficulty.CheatInsane)],
        realtime=False,
    )


if __name__ == "__main__":
    main()
