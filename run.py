import sc2, sys
from __init__ import run_ladder_game
from sc2 import Race, Difficulty
from sc2.player import Bot, Computer
import random

# Load bot
from theunseenz import TheUnseenz
bot = Bot(Race.Protoss, TheUnseenz(), name="TheUnseenz")



allmaps = ['Ephemeron', 'EternalEmpireLE', 'NightshadeLE', 'SImulacrumLE', 'TritonLE', 'WorldofSleepersLE', 'ZenLE']


_realtime = False

_difficulty = Difficulty.CheatInsane #CheatInsane, CheatMoney, CheatVision
_opponent = random.choice([Race.Zerg, Race.Terran, Race.Protoss])
#_opponent = Race.Protoss

# Start game
if __name__ == '__main__':
    if "--LadderServer" in sys.argv:
        # Ladder game started by LadderManager
        print("Starting ladder game...")
        run_ladder_game(bot)
    else:
        # Local game
        print("Starting local game...")      
        sc2.run_game(sc2.maps.get(random.choice(allmaps)), [
            Bot(Race.Protoss, TheUnseenz()),
            Computer(_opponent, _difficulty)
        ], realtime=_realtime)