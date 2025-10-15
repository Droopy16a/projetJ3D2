import pygame
import socket
from Player import Player
from Platform import Platform
from network_client import NetworkClient
import logging

logging.basicConfig(level=logging.INFO)

def main():
    pygame.init()
    screen = pygame.display.set_mode((1920, 1080))
    pygame.display.set_caption("Game")

    platforms = [
        Platform(0, 980, 1920, 250, color=(107, 73, 89)),
        Platform(300, 800, 300, 20),
        Platform(700, 600, 300, 20),
        Platform(1100, 400, 300, 20)
    ]
    player = Player(375, 285, platforms=platforms)

    hostname = socket.gethostname()
    ip_addr = socket.gethostbyname(hostname)
    net = NetworkClient(f'ws://{ip_addr}:8765')
    try:
        net.start()
    except Exception as e:
        logging.error(f"Failed to start network client: {e}")

    remote_players = {}
    bg = pygame.image.load("game_background_1.png")
    bg = pygame.transform.smoothscale(bg, (1920, 1080))
    bg_rect = bg.get_rect(center=(960, 540))

    clock = pygame.time.Clock()
    running = True

    def handle_input():
        keys = pygame.key.get_pressed()
        return (
            int(keys[pygame.K_q]),
            int(keys[pygame.K_d]),
            int(keys[pygame.K_SPACE]) 
        )

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        left, right, up = handle_input()
        dx = right - left
        dy = -up
        dt = clock.tick(60) / 1000

        screen.blit(bg, bg_rect)
        player.move(dx, dy, dt)
        player.draw(screen)

        try:
            net.send_position(player.x, player.y, dx, dy)
        except Exception as e:
            logging.warning(f"Failed to send input: {e}")

        remote = net.get_players()
        my_id = getattr(net, 'id', None)
        current_pids = set(remote.keys())
        for pid in list(remote_players.keys()):
            if pid not in current_pids and pid != my_id:
                del remote_players[pid]

        for pid, pdata in remote.items():
            if pid == my_id:
                continue
            try:
                if pid not in remote_players:
                    remote_players[pid] = Player(pdata.get('x', 375), pdata.get('y', 285), platforms=platforms)
                # print(pdata)
                rp = remote_players[pid]
                rp.x = float(pdata.get('x', rp.x))
                rp.y = float(pdata.get('y', rp.y))
                rp.vel_y = float(pdata.get('vy', 0))
                rp.move(0, 0, dt) 
                rp.draw(screen)
            except Exception as e:
                logging.warning(f"Error updating remote player {pid}: {e}")

        for platform in platforms:
            platform.draw(screen)
        pygame.display.flip()

    pygame.quit()
    try:
        net.stop()
    except Exception as e:
        logging.error(f"Failed to stop network client: {e}")

if __name__ == "__main__":
    main()