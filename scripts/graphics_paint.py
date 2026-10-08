"""Measured Office 16 gradient transfer; other renderers require revalidation."""
from functools import lru_cache
import json
from pathlib import Path
import numpy as np


@lru_cache(maxsize=1)
def profile():
    return json.loads((Path(__file__).resolve().parents[1]/
                       "assets/graphics/office16-gradient-profile.json").read_text(encoding="utf-8"))


def transfer(t):
    p = profile()
    return np.interp(t, p["positions"], p["weights"])


def mix(t, stops, colors):
    t = np.asarray(t)
    stops, colors = np.asarray(stops), np.asarray(colors)
    index = np.clip(np.searchsorted(stops, t, side="right")-1, 0, len(stops)-2)
    u = transfer(np.clip((t-stops[index])/(stops[index+1]-stops[index]), 0, 1))[:, None]
    gamma = profile()["gamma"]
    return np.clip(((1-u)*colors[index]**gamma+u*colors[index+1]**gamma)**(1/gamma), 0, 1)
