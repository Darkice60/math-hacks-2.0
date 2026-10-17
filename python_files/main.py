# DarkIce60, zhaomax73, MrNemolio
# main.py file for math-hacks-2.0

import pygame
import sys

# Initialize all imported pygame modules
pygame.init()

# Set up the disply window (Width, Height)
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Airplane Simulation")

# Set up a clock to regulate frame rate
clock = pygame.time.Clock()


#INITIAL INSTANCES
airpotCoords = []                                                           # airport coords on map
worldMap = pygame.image.load("images/map.png")                        # world map image 
worldMap = pygame.transform.scale(worldMap, (1920, 1080))
# Main game loop
running = True
while running:

    # Gets mouse coords and sets them to x and y variables
    mouse_x, mouse_y = pygame.mouse.get_pos()

    # all inbuilt events in pygame (quit, key pressed)
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.MOUSEBUTTONDOWN:
            print("")


    # 3. Drawing/Rendering code
    screen.fill((0, 255, 0))  # Fill background with a dark gray color (R, G, B)
    screen.blit(worldMap, (0,0))
    
    # Draw a simple test circle in the center
    pygame.draw.circle(screen, (0, 191, 255), (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2), 50)

    # Refresh the full display Surface to the screen
    pygame.display.flip()

    # Limit the game to 60 frames per second
    clock.tick(60)

# Cleanly uninitialize everything and close the application
pygame.quit()
sys.exit()