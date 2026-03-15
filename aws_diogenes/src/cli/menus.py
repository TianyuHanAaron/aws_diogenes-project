"""Questionary menus for the local CLI."""

from __future__ import annotations

import questionary


CHANNEL_CHOICES = [
    ("Global", "global"),
    ("Local", "local"),
    ("Investment", "investment"),
    ("Interest", "interest"),
]

FREQUENCY_CHOICES = [
    questionary.Choice("Immediate", value="immediate"),
    questionary.Choice("Daily", value="daily"),
    questionary.Choice("Weekly", value="weekly"),
    questionary.Choice("Monthly", value="monthly"),
    questionary.Choice("Three Months", value="three_months"),
    questionary.Choice("Six Months", value="six_months"),
    questionary.Choice("Yearly", value="yearly"),
    questionary.Choice("None", value="none"),
]

def main_menu():
    return questionary.select(
        "Select an action to proceed!",
        choices=[
            "Create User",
            "Choose News Channels",
            "Choose Interests",
            "Set Email Delivery Frequency",
            "Stop Email Delivery",
            "Resume Email Delivery",
            "Generate Email Now",
            "Exit"
        ]
    ).ask()


def channel_menu(default: list[str] | None = None):
    selected = set(default or [])
    choices = [
        questionary.Choice(title, value=value, checked=value in selected)
        for title, value in CHANNEL_CHOICES
    ]
    return questionary.checkbox(
        "Select News Channels (use space to toggle, enter to confirm)",
        choices=choices,
    ).ask()


def frequency_menu():
    return questionary.select(
        "Choose Email Delivery Frequency",
        choices=FREQUENCY_CHOICES,
    ).ask()
