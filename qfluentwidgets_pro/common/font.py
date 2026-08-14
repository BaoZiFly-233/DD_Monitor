# coding: utf-8
from functools import lru_cache
from typing import List

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget

from .config import qconfig


def setFontFamilies(families: List[str], save=False):
    """ set the font families used by all widgets

    Parameters
    ----------
    families: List[str]
        font family names, the default value is `['Segoe UI', 'Microsoft YaHei', 'PingFang SC']`

    save: bool
        whether to save the change to config file
    """
    qconfig.set(qconfig.fontFamilies, families, save)


def fontFamilies() -> List[str]:
    """ Returns the font families used by all widgets """
    return qconfig.get(qconfig.fontFamilies).copy()


def setFont(widget: QWidget, fontSize=14, weight=QFont.Normal):
    """ set the font of widget

    Parameters
    ----------
    widget: QWidget
        the widget to set font

    fontSize: int
        font pixel size

    weight: `QFont.Weight`
        font weight
    """
    widget.setFont(getFont(fontSize, weight))


@lru_cache(maxsize=32)
def _fontTemplate(families, fontSize, weight):
    font = QFont()
    default_families = ("Segoe UI", "Microsoft YaHei", "PingFang SC")
    if families != default_families:
        font.setFamilies(list(families))
    font.setPixelSize(fontSize)
    font.setWeight(weight)
    return font


def getFont(fontSize=14, weight=QFont.Normal):
    """Create an implicitly shared font from a cached template."""
    families = tuple(qconfig.get(qconfig.fontFamilies))
    return QFont(_fontTemplate(families, fontSize, weight))


def fontStyleSheet(font: QFont):
    """ Returns the style sheet of font """
    families = []
    for family in font.families():
        families.append(f"'{family}'")

    qss = f"font: {font.pixelSize()}px {','.join(families)}"
    return qss
