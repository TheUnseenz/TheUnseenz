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
    
   
To install sc2 package:
pip install burnysc2
"""

#import random

import sc2
from sc2 import Race, Difficulty
from sc2.constants import *
from sc2.player import Bot, Computer, Human



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
        self.need_detection = False
        self.have_detection = False
        # Terran: Note that many units have different forms and each form has a different unit name! -> Hellion/Hellbat, Widow mine, Siege tank, Viking, Liberator
        # Excluded units: Raven, Widow mine
        self.terran_army = {MARINE, MARAUDER, REAPER, GHOST, HELLION, SIEGETANK, CYCLONE, THOR, VIKING, MEDIVAC, LIBERATOR, BANSHEE, BATTLECRUISER}
        # Protoss: Note that warp prism and observers have different forms with different names! 
        # Excluded units: Disruptor, High Templar, Observer, Warp Prism, Interceptors
        self.protoss_army = {ZEALOT, STALKER, SENTRY, ADEPT, DARKTEMPLAR, ARCHON, IMMORTAL, COLOSSUS, PHOENIX, ORACLE, VOIDRAY, TEMPEST, CARRIER, MOTHERSHIP}
        # Zerg: Note that all zerg ground units can burrow! 
        # Excluded units: Vipers, Infestors, Swarm hosts, Overseers, Overlords, Broodlings, Locusts
        # How do we count the combat strength of swarm hosts and brood lords? What about spellcasters?
        self.zerg_army = {ZERGLING, BANELING, ROACH, RAVAGER, HYDRALISK, LURKER, QUEEN, MUTALISK, CORRUPTOR, BROODLORD, ULTRALISK}
    
        
        
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
            
            # Unit counters
            # TODO: Check which race we are, account for enemy random race and for zerg race-switching.
#            for own_army in self.protoss_army:
#                if self.enemy_race == Terran:
#                    for enemy_army in self.terran_army:
#                        self.units(own_army)
                
                    
            
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
        # Placeholder: Future units = 2x current enemy units.
        self.future_enemy_units = self.known_enemy_units
    
        # Determine if we need detection for enemy cloaked/burrowed units
        # DECIDE: What about burrow roaches? Baneling bombs? Should we preemptively build detection for tech lab starports? What about for clearing creep?
        if self.known_enemy_units.of_type({WIDOWMINE, GHOST, BANSHEE, DARKTEMPLAR, MOTHERSHIP, LURKER, INFESTOR}) or self.known_enemy_structures.of_type({GHOSTACADEMY, DARKSHRINE, LURKERDEN}) :
            self.need_detection = True
            
        # Calculate which unit is most effective vs the enemy current and future units
        
        # Micro            
        # Self.all_army = F2 
        # If we are close to max supply, attack closes enemy unit/building, or if none is visible: attack move towards enemy spawn
        # TODO: Stay away from enemies if it's a fight we cannot win
        # TODO: Poke
        # TODO: If we have longer range than enemy, maintain max range. If we have shorter range than enemy, maintain (movespeed*0.5*attackcooldown) distance if we are faster, and hug if we are closer
        # TODO: If we have notably smaller forces but both armies are small, use workers to turn the tides
        # TODO: Preferred targets by enemy dps, armor type, armor, hp remaining, range
        # TODO: Use army abilities
        self.all_army = self.units.not_structure - self.units(PROBE)
        for army in self.all_army:
            # Choose target and attack, filter out invisible targets
            targets = (self.enemy_units | self.enemy_structures).filter(lambda unit: unit.can_be_attacked and not self.units({LARVA, EGG, INTERCEPTOR}) )
            if targets:
                target = targets.closest_to(army)
                # Unit has no attack, stay near other army units                    
                if army.weapon_cooldown == -1: 
                    self.do(army.move(self.all_army.closest_to(army)))                
                # Unit has just attacked, stutter step while waiting for attack cooldown
                elif army.weapon_cooldown > 0.5:
                    kite_pos = army.position.towards(target.position, -1)
                    self.do(army.move(kite_pos))
                # Unit is ready to attack, go attack.
                else:
                    self.do(army.attack(target))
                
            elif self.MAX_SUPPLY - self.supply_used < 20:
                self.do(army.attack(self.enemy_start_locations[0]))
            
        for vr in self.units(VOIDRAY): # Does not work!
            # Activate charge ability if the void ray just attacked
            if vr.weapon_cooldown > 0:
                self.do(vr(EFFECT_VOIDRAYPRISMATICALIGNMENT))
                    
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
            self.combinedActions.append(building(CANCEL))
        
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

        # Train probe on nexuses that are undersaturated until worker cap (avoiding distribute workers functions)
        # if nexus.assigned_harvesters < nexus.ideal_harvesters and nexus.is_idle:
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
        if self.structures(PYLON).ready:
            pylon = self.structures(PYLON).ready.random
            if self.structures(GATEWAY).ready or self.structures(WARPGATE).ready:
                # If we have gateway completed, build cyber core
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
                    
                    # If we have lots of gateways, build twilight council
                    if (self.structures(GATEWAY).ready.amount+self.structures(WARPGATE).ready.amount+self.already_pending(GATEWAY)) >= 4:
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
                                    
                            # If we have lots of vespene, build templar archives
                            if self.structures(TWILIGHTCOUNCIL).ready and self.vespene > 500:
                                if not self.structures(TEMPLARARCHIVE):
                                    if self.can_afford(TEMPLARARCHIVE) and self.already_pending(TEMPLARARCHIVE) == 0:
                                        await self.build(TEMPLARARCHIVE, near=pylon)
                                        
                            # If we have a big bank, build dark shrine
                            if self.structures(TWILIGHTCOUNCIL).ready and self.vespene > 750 and self.minerals > 750:
                                if not self.structures(DARKSHRINE):
                                    if self.can_afford(DARKSHRINE) and self.already_pending(DARKSHRINE) == 0:
                                        await self.build(DARKSHRINE, near=pylon)
                        
                    # If we have lots of stargates, build fleet beacon
                    if len(self.structures(STARGATE)) >= 2:
                        if not self.structures(FLEETBEACON):
                            if self.can_afford(FLEETBEACON) and self.already_pending(FLEETBEACON) == 0:
                                await self.build(FLEETBEACON, near=pylon)
                            elif not self.can_afford(FLEETBEACON):
                                save_resources = 1
                                
                    # If we have lots of robotics facilities, build robotics bay
                    if len(self.structures(ROBOTICSFACILITY)) >= 1:
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
                                
            else:
                # If we have no gateway, build gateway
                if self.can_afford(GATEWAY) and self.structures(GATEWAY).amount == 0:
                    await self.build(GATEWAY, near=pylon)
        
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
            # TODO: Intelligent choices on which units to make.
            # Current behaviour: Stalker Colossus into Zealot Stalker Archon Colossus Immortal Voidray
            for sg in self.structures(STARGATE).idle:
                if self.can_afford(VOIDRAY):
                    self.do(sg.train(VOIDRAY), subtract_cost=True, subtract_supply=True)
            
            for rb in self.structures(ROBOTICSFACILITY).idle:
                if self.structures(ROBOTICSBAY).ready and self.units(COLOSSUS).amount < 6:
                    if self.can_afford(COLOSSUS):
                        self.do(rb.train(COLOSSUS), subtract_cost=True, subtract_supply=True)
                else:                        
                    if self.can_afford(IMMORTAL):
                        self.do(rb.train(IMMORTAL), subtract_cost=True, subtract_supply=True)
            
            # Prioritize robo and stargate over warpgate units                                    
            if not self.structures(STARGATE).ready.idle and not self.structures(ROBOTICSFACILITY).ready.idle:                
                if self.structures(PYLON).ready:
                    proxy = self.structures(PYLON).closest_to(self.enemy_start_locations[0])
                # TODO: Warp-in at power field closest to enemy, but at a minimum distance away. Include warp prism power fields.                    
                for wg in self.structures(WARPGATE).ready:
                    abilities = await self.get_available_abilities(wg)
                    if AbilityId.WARPGATETRAIN_STALKER in abilities:
                        pos = proxy.position.to2.random_on_distance(4)
                        placement = await self.find_placement(WARPGATETRAIN_STALKER, pos, placement_step=1)
                        while placement is None:
                            # pick random other pylon
                            proxy = self.structures(PYLON).random
                            pos = proxy.position.to2.random_on_distance(4)
                            placement = await self.find_placement(WARPGATETRAIN_STALKER, pos, placement_step=1)
                            warp_try +=1
                            if warp_try >= 5:
                                break
                            
                        if self.units(STALKER).amount < 20 and self.vespene > 200:
                            self.do(wg.warp_in(STALKER, placement), subtract_cost=True, subtract_supply=True)
                        elif self.vespene > 500 and self.structures(TEMPLARARCHIVE).ready:
                            self.do(wg.warp_in(HIGHTEMPLAR, placement), subtract_cost=True, subtract_supply=True)
                        elif self.minerals > 400:
                            self.do(wg.warp_in(ZEALOT, placement), subtract_cost=True, subtract_supply=True)                            
                # If warp gate is not yet researched, use gateways. Warp gate research takes 100s, gateway units take ~30s to build, already_pending returns % completion, with 1 on completion
                if self.already_pending_upgrade(WARPGATERESEARCH) > 0.7 :
                    for gw in self.structures(GATEWAY).idle:
                        if self.can_afford(STALKER):
                            self.do(gw.train(STALKER), subtract_cost=True, subtract_supply = True)
                # If all our production is not idle and we have more income than expenditure, add more production buildings. If we are supply capped, add production up to ~2x income rate
                # TODO: Intelligent choices on which production buildings to make.
                # TODO: Sim city placement
                # Current behaviour: Balance out robo, stargate, warpgate in a 1:1:4 ratio when we want to spend minerals
                if self.structures(PYLON).ready and self.structures(CYBERNETICSCORE).ready:
                    pylon = self.structures(PYLON).ready.random                    
                    # TODO: Dynamically modify income-expenditure ratio based on stage of the game (teching and expanding are not counted in expenditure but this is a significant cost early).
                    if mineral_income*0.8 > mineral_rate or (self.supply_used > 190 and mineral_income*1.5 > mineral_rate):
                        if num_warpgates > 2*(num_stargates + num_robos):
                            if num_robos <= num_stargates or num_robos < 2:
                                if self.can_afford(ROBOTICSFACILITY):
                                    await self.build(ROBOTICSFACILITY, near=pylon)
                            else:
                                if self.can_afford(STARGATE):
                                    await self.build(STARGATE, near=pylon)
                        else:
                            if self.can_afford(GATEWAY):
                                await self.build(GATEWAY, near=pylon)
                    
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
        
def main():
    sc2.run_game(
        sc2.maps.get("ZenLE"),
        #[Human(Race.Terran, name="VictimOfSkyNet"),Bot(Race.Protoss, MacroBot(), name="AncoraImparo")],
        [Bot(Race.Protoss, MacroBot(), name="AncoraImparo"), Computer(Race.Protoss, Difficulty.CheatInsane)],
        realtime=False,
    )


if __name__ == "__main__":
    main()
