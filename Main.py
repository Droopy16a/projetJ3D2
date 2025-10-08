from Player import Player
from Platform import Platform
import pygame
from network_client import NetworkClient

def main():
    pygame.init()
    screen = pygame.display.set_mode((1920, 1080))
    pygame.display.set_caption("Game")

    platforms = [Platform(0, 980, 1920, 250, color=(107, 73, 89)), Platform(300, 800, 300, 20), Platform(700, 600, 300, 20), Platform(1100, 400, 300, 20)]
    players = [Player(375, 285, platforms=platforms), Player(0, 285, platforms=platforms)]

    # Start network client (connect to local server by default)
    net = NetworkClient('ws://127.0.0.1:8765')
    try:
        net.start()
    except Exception:
        print("Failed to start network client")

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
        dx = [keys[pygame.K_RIGHT] - keys[pygame.K_LEFT], keys[pygame.K_d] - keys[pygame.K_q]]
        dy = [keys[pygame.K_DOWN] - keys[pygame.K_UP], keys[pygame.K_s] - keys[pygame.K_z]]
        dt = clock.tick(60) / 1000
        screen.blit(bg, bg_rect)
        for nb, player in enumerate(players):
            player.move(dx[nb], dy[nb], dt)
            player.draw(screen)

        # Send input (left/right/up) for player[0]
        try:
            left = keys[pygame.K_LEFT] or keys[pygame.K_q]
            right = keys[pygame.K_RIGHT] or keys[pygame.K_d]
            up = keys[pygame.K_UP] or keys[pygame.K_z] or keys[pygame.K_SPACE]
            net.send_input(int(left), int(right), int(up))
        except Exception:
            pass

        # Draw remote players from network state
        remote = net.get_players()
        for pid, pdata in remote.items():
            try:
                rx = int(pdata.get('x', 0))
                ry = int(pdata.get('y', 0))
                pygame.draw.rect(screen, (255, 0, 0), (rx, ry, 40, 60))
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