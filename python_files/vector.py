# Darkice60
# vector.py file for math-hacks-2.0

import math

class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def magnitude(self) -> float:
        return math.hypot(self.x, self.y)

    def __add__(self, other: "Vector") -> "Vector":
        return Vector(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vector") -> "Vector":
        return Vector(self.x + other.x, self.y + other.y)

    def __mul__(self, scala: float) -> "Vector":
         