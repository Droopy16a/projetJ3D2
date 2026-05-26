from game_client import Game
from menu import Menu


if __name__ == "__main__":
    # game = Game()
    menu = Menu()
    menu.run()
    start_requested = menu.start_requested
    selected_seed = menu.selected_seed
    menu.destroy()
    if start_requested:
        game = Game(module_seed=selected_seed)
        game.run()
    # game.run()
