import pygame

def load_image(path, scale=None):
    """Load and optionally scale an image."""
    image = pygame.image.load(path).convert_alpha()
    if scale:
        image = pygame.transform.smoothscale(image, scale)
    return image