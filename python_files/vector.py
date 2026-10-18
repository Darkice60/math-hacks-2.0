"""Small reusable 2D vector class for the MathHacks airplane simulation."""

from __future__ import annotations
import math


class Vector:
    def __init__(self, x: float, y: float):
        self.x = float(x)
        self.y = float(y)

    def magnitude(self) -> float:
        """Return the vector's length."""
        return math.hypot(self.x, self.y)

    def unit_vector(self) -> "Vector":
        """Return a unit vector with the same direction; zero stays zero."""
        length = self.magnitude()
        if length == 0:
            return Vector(0.0, 0.0)
        return self / length

    def dot(self, other: "Vector") -> float:
        """Return the dot product."""
        return self.x * other.x + self.y * other.y

    def __add__(self, other: "Vector") -> "Vector":
        if not isinstance(other, Vector):
            return NotImplemented
        return Vector(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vector") -> "Vector":
        if not isinstance(other, Vector):
            return NotImplemented
        return Vector(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Vector":
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return Vector(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> "Vector":
        return self * scalar

    def __truediv__(self, scalar: float) -> "Vector":
        if scalar == 0:
            raise ZeroDivisionError("Cannot divide a vector by zero")
        return Vector(self.x / scalar, self.y / scalar)

    def __neg__(self) -> "Vector":
        return Vector(-self.x, -self.y)

    def __repr__(self) -> str:
        return f"Vector({self.x:g}, {self.y:g})"
