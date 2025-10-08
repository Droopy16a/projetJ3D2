from Player import Player
from Platform import Platform
import pygame
from network_client import NetworkClient

def main():
    pygame.init()
    screen = pygame.display.set_mode((1920, 1080))
    pygame.display.set_caption("Game")

    platforms = [Platform(0, 980, 1920, 250, color=(107, 73, 89)), Platform(300, 800, 300, 20), Platform(700, 600, 300, 20), Platform(1100, 400, 300, 20)]
    player = Player(375, 285, platforms=platforms)

    # Start network client (connect to local server by default)
    net = NetworkClient('ws://10.3.139.128:8765')
    try:
        net.start()
    except Exception:
        print("Failed to start network client")

    # Remote player objects keyed by server id
    remote_players = {}
    SIZE = 1

    bg = pygame.image.load("game_background_1.png")
    bg = pygame.transform.smoothscale(bg, (1920*SIZE, 1080*SIZE))
    bg_rect = bg.get_rect(center=(1920//2, 1080//2))

    clock = pygame.time.Clock()
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        keys = pygame.key.get_pressed()
        dx = keys[pygame.K_d] - keys[pygame.K_q]
        dy = keys[pygame.K_s] - keys[pygame.K_SPACE]
        dt = clock.tick(60) / 1000
        screen.blit(bg, bg_rect)
        # for nb, player in enumerate(players):
        player.move(dx, dy, dt)
        player.draw(screen)

        # Send input (left/right/up) for player[0]
        try:
            left = keys[pygame.K_q]
            right = keys[pygame.K_d]
            up = keys[pygame.K_SPACE]
            net.send_input(int(left), int(right), int(up))
        except Exception:
            pass

        # Draw remote players from network state using Player instances
        remote = net.get_players()
        my_id = getattr(net, 'id', None)
        for pid, pdata in remote.items():
            if pid == my_id:
                continue
            try:
                if pid not in remote_players:
                    remote_players[pid] = Player(375, pdata.get('y', 0), platforms=platforms)
                rp = remote_players[pid]
                vx = float(pdata.get('vx', 0))
                vy = float(pdata.get('vy', 0))
                dx_remote = 0
                if vx > 50:
                    dx_remote = 1
                elif vx < -50:
                    dx_remote = -1
                dy_remote = -1 if vy < -200 else 0
                rp.move(dx_remote, dy_remote, dt)
                rp.draw(screen)
            except Exception:
                pass

        # screen.fill((0, 0, 0))
        
        for platform in platforms:
            platform.draw(screen)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    try:
        net.stop()
    except Exception:
        pass

main()