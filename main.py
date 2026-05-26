from game_client import Game
from menu import Menu

if __name__ == "__main__":
    # game = Game()
    menu = Menu()
    menu.run()
    start_requested = menu.start_requested
    menu.destroy()
    if start_requested:
        game = Game()
        game.run()
    # game.run()
