import pygame
from utils import load_image


class Platform:
    def __init__(self, x, y, width, height, image_path=None, color=(0, 255, 0)):
        self.x = x
        self.y = y
        self.rect = pygame.Rect(x, y, width, height)
        self.color = color
        if image_path:
            self.image = load_image(image_path, scale=(width, height))
            self.mask = pygame.mask.from_surface(self.image)
        else:
            self.image = None
            self.mask = pygame.mask.Mask((width, height), fill=True)

    def draw(self, screen):
        if self.image:
            screen.blit(self.image, self.rect)
        else:
            pygame.draw.rect(screen, self.color, self.rect)