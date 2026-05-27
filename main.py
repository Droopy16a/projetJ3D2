import sys
from panda3d.core import loadPrcFileData

from game_client import Game
from menu import Menu

if __name__ == "__main__":
    while True:
        menu = Menu()
        menu.run()
        start_requested = menu.start_requested
        menu.destroy()

        if not start_requested:
            break

        game = Game()
        game.run()
        game.destroy()

        del game
