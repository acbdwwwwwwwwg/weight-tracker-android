"""Persistent four-tab navigation used throughout the app."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from ui.theme import CARD, CARD_ALT, MUTED, PRIMARY, SURFACE_DOWN, TEXT, WHITE
from ui.widgets import RoundedButton, RoundedPanel


class BottomNavigation:
    ITEMS = (
        ("home", "⌂", "首页"),
        ("calendar", "▦", "日历"),
        ("progress", "▧", "体型"),
        ("profile", "●", "我的"),
    )

    def __init__(self, app):
        self.app = app
        self.buttons = {}
        self.root = RoundedPanel(orientation="horizontal", padding=(dp(6), dp(5)), spacing=dp(6),
                                 size_hint_y=None, height=dp(68), panel_color=CARD)
        for route, icon, title in self.ITEMS:
            button = RoundedButton(
                text=f"{icon}\n{title}",
                size_hint_x=1,
                size_hint_y=None,
                height=dp(56),
                font_size=dp(11),
                halign="center",
                valign="middle",
                corner_radius=14,
                fill_color=CARD_ALT,
                press_color=SURFACE_DOWN,
                color=MUTED,
            )
            if route == "progress":
                callback = app.open_progress_home
            else:
                callback = lambda *_args, destination=route: app.navigate_to(destination)
            button.bind(on_release=callback)
            self.buttons[route] = button
            self.root.add_widget(button)

    def set_active(self, route):
        for key, button in self.buttons.items():
            if key == route:
                button.fill_color = PRIMARY
                button.press_color = PRIMARY
                button.color = WHITE
            else:
                button.fill_color = CARD_ALT
                button.press_color = SURFACE_DOWN
                button.color = MUTED
