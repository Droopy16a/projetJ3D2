import pygame
from utils import load_image


class Player:
    def __init__(self, x, y, width=80*4, height=100*4, platforms=[]):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.color = (0, 128, 255)  # For debugging, if needed
        self.speed = 16  # Horizontal speed
        self.jump_height = 25  # Jump velocity
        self.vel_y = 0
        self.gravity = 1.5
        self.on_ground = False
        self.platforms = platforms

        # Load animation frames
        self.frames = [
            load_image(f"./frame/frame{i}.png", scale=(width, height)) for i in range(0, 8)
        ]
        self.current_frame = 0
        self.animation_speed = 0.3  # Frames per second
        self.frame_timer = 0
        self.image = self.frames[0]
        self.mask = pygame.mask.from_surface(self.image)
        self.rect = self.image.get_rect(topleft=(self.x, self.y))

        self.orient = 1  # 1 for right, -1 for left
        self.dx = 0

    def move(self, dx, dy, dt):
        # Apply delta time for frame-rate independence
        dt_scale = dt / (1 / 60)  # Normalize to 60 FPS

        # --- Animation Logic ---
        if dx != 0 or not self.on_ground:  # Moving or in air
            self.frame_timer += self.animation_speed * dt_scale
            if self.frame_timer >= 1:
                self.frame_timer = 0
                self.current_frame = (self.current_frame + 1) % len(self.frames)
                if self.current_frame == 0:
                    self.current_frame = 1  # Skip idle frame
        else:
            self.current_frame = 0  # Idle frame

        self.image = self.frames[self.current_frame]
        self.mask = pygame.mask.from_surface(self.image)

        # Update orientation
        if dx != 0:
            self.orient = 1 if dx > 0 else -1
        self.dx = dx

        # Horizontal movement
        self.x += dx * self.speed * dt_scale

        # Jump initiation
        if dy < 0 and self.on_ground:
            self.vel_y = -self.jump_height
            self.on_ground = False

        # Apply gravity
        if not self.on_ground:
            self.vel_y += self.gravity * dt_scale
            self.y += self.vel_y * dt_scale

        # Update rect before collision
        self.rect.topleft = (self.x, self.y)

        # Platform collision
        self.on_ground = False  # Reset each frame
        for platform in self.platforms:
            if self.rect.colliderect(platform.rect):
                offset_x = platform.rect.x - self.rect.x
                offset_y = platform.rect.y - self.rect.y
                if self.mask.overlap(platform.mask, (offset_x, offset_y)):
                    # Check if player is falling and above platform
                    if self.vel_y >= 0 and self.y + self.height - self.vel_y * dt_scale <= platform.rect.y + 100:
                        # print("Checking collision with platform at", platform)
                        # self.y = platform.rect.y - self.rect.y
                        # print(self.y)
                        self.vel_y = 0
                        self.on_ground = True
                        self.rect.topleft = (self.x, self.y)
                        break

        # Ground collision (example ground at y=1000)
        # if self.y + self.height > 1000:
        #     self.y = 1000 - self.height
        #     self.vel_y = 0
        #     self.on_ground = True

        # Update rect after collisions
        self.rect.topleft = (self.x, self.y)

    def draw(self, screen):
        if self.orient > 0:
            screen.blit(self.image, self.rect)
        else:
            screen.blit(pygame.transform.flip(self.image, True, False), self.rect)