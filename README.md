# TheUnseenz
A SC2 AI bot.
The bot will be a reactive macro-focused bot that adapts its behaviour to the game-state. It will be designed to be generic enough to handle most scenarios without explicit instructions on dealing with specific strategies, and will figure out the best response on its own. 

The bot should be portable enough that it will be easy to adapt to play random race, but for now it will play Protoss until I have developed its capabilities better.

Should I be able to make this perform well enough, I will enter it in the ProBots tournament (ESChamp). 

I do not plan to include machine learning in this yet, but I will eventually have many parameters to decide on which can be fine-tuned by machine learning.

# Why am I making this?
Currently, most SC2 bots have a select few strategies that they go for, depending on the state of the game. These strategies are predetermined by their authors based on what they believe are good. But what if there exists a good strategy that no one has thought of? Thus, my bot will decide for itself what is the optimal strategy, rather than me telling it a predetermined set of strategies.

# Future possible work:
If the SC2 API allows, I will try to port the macro portion of the bot to a custom mod/game. This will allow players to have a 1v1 match with other people with a level macro playing field, so they can enjoy the micro and strategy aspects of Starcraft II without being weighed down by poor macro skills. Alternatively, the reverse can be done, for players to refine their macro skills while the bots micro the units the players build.
