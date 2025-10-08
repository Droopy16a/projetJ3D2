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
    net = NetworkClient('ws://127.0.0.1:8765')
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
        dx = keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
        dy = keys[pygame.K_DOWN] - keys[pygame.K_UP]
        dt = clock.tick(60) / 1000
        screen.blit(bg, bg_rect)
        # for nb, player in enumerate(players):
        player.move(dx, dy, dt)
        player.draw(screen)

        # Send input (left/right/up) for player[0]
        try:
            left = keys[pygame.K_LEFT] or keys[pygame.K_q]
            right = keys[pygame.K_RIGHT] or keys[pygame.K_d]
            up = keys[pygame.K_UP] or keys[pygame.K_z] or keys[pygame.K_SPACE]
            net.send_input(int(left), int(right), int(up))
        except Exception:
            pass

        # Draw remote players from network state using Player instances
        remote = net.get_players()
        my_id = getattr(net, 'id', None)
        for pid, pdata in remote.items():
            if pid == my_id:
                # skip drawing ourself (server may also echo our state)
                continue
            try:
                # create remote Player object if needed
                if pid not in remote_players:
                    # create with same platforms so collisions/rendering match
                    remote_players[pid] = Player(pdata.get('x', 0), pdata.get('y', 0), platforms=platforms)
                rp = remote_players[pid]
                # update authoritative position from server
                rp.x = float(pdata.get('x', rp.x))
                rp.y = float(pdata.get('y', rp.y))
                rp.vel_y = float(pdata.get('vy', rp.vel_y))
                # update rect to match new position before drawing
                rp.rect.topleft = (rp.x, rp.y)
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