import json
import mimetypes
import os
import sys
import threading
import copy
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk
import requests
from PIL import Image


APP_NAME = "PinkGift Tool"
DEFAULT_PANEL_URL = "https://site--pinky-software--65sy8vr2snqw.code.run"
BG = "#07090d"
SIDEBAR = "#0b0e14"
CARD = "#10141c"
CARD_ALT = "#171c27"
BORDER = "#222938"
TEXT = "#f7f8fb"
MUTED = "#8b93a7"
PINK = "#ff5aa9"
PINK_HOVER = "#ea468f"
PURPLE = "#8b66f6"
PURPLE_HOVER = "#7653df"
GREEN = "#49d6a0"
RED = "#f05d78"


def resource_path(*parts):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root.joinpath(*parts)


def settings_path():
    base = Path(os.getenv("APPDATA") or Path.home()) / "PinkGiftTool"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.json"


def load_settings():
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def save_settings(data):
    settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class ApiError(RuntimeError):
    pass


class PinkGiftApi:
    def __init__(self):
        self.base_url = DEFAULT_PANEL_URL
        self.session = requests.Session()
        self.session.headers.update({
            "X-PinkGift-Desktop": "1",
            "User-Agent": "PinkGiftTool/1.0",
            "Accept": "application/json",
        })

    def _request(self, method, path, **kwargs):
        try:
            response = self.session.request(method, self.base_url + path, timeout=25, **kwargs)
        except requests.RequestException as error:
            raise ApiError("Impossible de joindre le panel PinkGift.") from error
        try:
            payload = response.json()
        except ValueError as error:
            raise ApiError("Le panel a renvoyé une réponse invalide.") from error
        if not response.ok or not payload.get("ok", False):
            raise ApiError(payload.get("error") or f"Erreur HTTP {response.status_code}")
        return payload

    def login(self, base_url, password):
        clean_url = base_url.strip().rstrip("/")
        if not clean_url.startswith(("https://", "http://")):
            raise ApiError("L’adresse doit commencer par https://")
        self.base_url = clean_url
        return self._request("POST", "/api/desktop/login", json={"password": password})

    def status(self):
        return self._request("GET", "/api/desktop/status")

    def guilds(self):
        return self._request("GET", "/api/desktop/guilds")["guilds"]

    def channels(self, guild_id):
        return self._request("GET", f"/api/desktop/guilds/{guild_id}/channels")["channels"]

    def embeds(self):
        return self._request("GET", "/api/desktop/embeds")["embeds"]

    def publish(self, guild_id, channel_id, embed_key, mention_everyone=False):
        return self._request("POST", "/api/desktop/publish", json={
            "guild_id": guild_id,
            "channel_id": channel_id,
            "embed_key": embed_key,
            "mention_everyone": bool(mention_everyone),
        })["published"]

    def panel_snapshot(self, month=""):
        query = f"?month={month}" if month else ""
        return self._request("GET", "/api/desktop/panel/snapshot" + query)

    def order_action(self, order_id, action, code=""):
        return self._request("POST", f"/api/desktop/panel/orders/{order_id}", json={"action": action, "code": code})

    def update_stock(self, kind, key, available, region=""):
        return self._request("POST", "/api/desktop/panel/stock", json={
            "kind": kind, "key": key, "available": bool(available), "region": region,
        })

    def update_prices(self, pricing, purchase_costs):
        return self._request("POST", "/api/desktop/panel/prices", json={
            "pricing": pricing, "purchase_costs": purchase_costs,
        })

    def update_referral(self, **payload):
        return self._request("POST", "/api/desktop/panel/referrals", json=payload)

    def all_embeds(self):
        return self._request("GET", "/api/desktop/panel/embeds")["embeds"]

    def save_embed(self, embed_key, data):
        return self._request("POST", f"/api/desktop/panel/embeds/{embed_key}", json={"data": data})

    def upload_image(self, file_path):
        with open(file_path, "rb") as handle:
            content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            return self._request(
                "POST",
                "/api/desktop/panel/images",
                files={"image": (Path(file_path).name, handle, content_type)},
            )["image_url"]


class PinkGiftTool(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title(APP_NAME)
        self.geometry("1440x860")
        self.minsize(1180, 720)
        self.configure(fg_color=BG)

        self.api = PinkGiftApi()
        self.guilds = []
        self.channels = []
        self.embeds = []
        self.all_embed_items = []
        self.panel_data = {}
        self.price_entries = []
        self.preview_image_cache = {}
        self.guild_by_label = {}
        self.channel_by_label = {}
        self.embed_by_label = {}
        self.active_nav = None
        self.nav_buttons = {}
        self.logo_image = self._load_logo((46, 46))

        self._show_login()

    def _load_logo(self, size):
        logo = resource_path("static", "discord_icon.gif")
        try:
            image = Image.open(logo)
            image.seek(0)
            return ctk.CTkImage(light_image=image.copy(), dark_image=image.copy(), size=size)
        except (OSError, EOFError):
            return None

    def _clear(self):
        for child in self.winfo_children():
            child.destroy()

    def _run_async(self, job, success=None, failure=None):
        def runner():
            try:
                result = job()
            except Exception as error:
                self.after(0, lambda: (failure or self._show_error)(error))
            else:
                if success:
                    self.after(0, lambda: success(result))
        threading.Thread(target=runner, daemon=True).start()

    def _show_error(self, error):
        messagebox.showerror(APP_NAME, str(error), parent=self)

    def _show_login(self):
        self._clear()
        settings = load_settings()
        shell = ctk.CTkFrame(self, width=450, height=535, fg_color="#0e1219", border_color="#293044", border_width=1, corner_radius=16)
        shell.place(relx=0.5, rely=0.5, anchor="center")
        shell.grid_propagate(False)
        shell.grid_columnconfigure(0, weight=1)

        if self.logo_image:
            ctk.CTkLabel(shell, text="", image=self.logo_image).grid(row=0, column=0, pady=(35, 10))
        else:
            ctk.CTkLabel(shell, text="P", font=ctk.CTkFont(size=54, weight="bold"), text_color=PINK).grid(row=0, column=0, pady=(40, 10))
        ctk.CTkLabel(shell, text="PINKGIFT CONTROL CENTER", font=ctk.CTkFont(size=9, weight="bold"), text_color=PINK).grid(row=1, column=0)
        ctk.CTkLabel(shell, text="Connexion administrateur", font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT).grid(row=2, column=0, pady=(5, 4))
        ctk.CTkLabel(shell, text="Gère la boutique et Discord depuis une seule application.", font=ctk.CTkFont(size=11), text_color=MUTED).grid(row=3, column=0, pady=(0, 26))

        form = ctk.CTkFrame(shell, fg_color="transparent")
        form.grid(row=4, column=0, padx=38, sticky="ew")
        form.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(form, text="ADRESSE DU PANEL", anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED).grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.url_entry = ctk.CTkEntry(form, height=42, corner_radius=8, fg_color="#090c12", border_color=BORDER, text_color=TEXT)
        self.url_entry.grid(row=1, column=0, sticky="ew")
        self.url_entry.insert(0, settings.get("panel_url", DEFAULT_PANEL_URL))
        ctk.CTkLabel(form, text="MOT DE PASSE", anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED).grid(row=2, column=0, sticky="ew", pady=(20, 7))
        self.password_entry = ctk.CTkEntry(form, height=42, corner_radius=8, show="●", fg_color="#090c12", border_color=BORDER, text_color=TEXT)
        self.password_entry.grid(row=3, column=0, sticky="ew")
        self.password_entry.bind("<Return>", lambda _event: self._login())
        self.login_button = ctk.CTkButton(form, text="Accéder au panel", height=43, corner_radius=8, fg_color=PURPLE, hover_color=PURPLE_HOVER, font=ctk.CTkFont(size=12, weight="bold"), command=self._login)
        self.login_button.grid(row=4, column=0, sticky="ew", pady=(25, 0))
        self.login_status = ctk.CTkLabel(form, text="", text_color=MUTED)
        self.login_status.grid(row=5, column=0, pady=12)
        self.password_entry.focus_set()

    def _login(self):
        url = self.url_entry.get().strip()
        password = self.password_entry.get()
        if not password:
            self.login_status.configure(text="Entre le mot de passe du panel.", text_color=RED)
            return
        self.login_button.configure(state="disabled", text="Connexion…")
        self.login_status.configure(text="Connexion sécurisée au bot…", text_color=MUTED)

        def success(_payload):
            save_settings({"panel_url": self.api.base_url})
            self.password_entry.delete(0, "end")
            self._build_shell()
            self._load_initial_data()

        def failure(error):
            self.login_button.configure(state="normal", text="Se connecter")
            self.login_status.configure(text=str(error), text_color=RED)

        self._run_async(lambda: self.api.login(url, password), success, failure)

    def _build_shell(self):
        self._clear()
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=224, corner_radius=0, fg_color=SIDEBAR, border_color=BORDER, border_width=1)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(18, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=17, pady=(18, 17))
        if self.logo_image:
            ctk.CTkLabel(brand, text="", image=self.logo_image).pack(side="left")
        brand_copy = ctk.CTkFrame(brand, fg_color="transparent")
        brand_copy.pack(side="left", padx=10)
        ctk.CTkLabel(brand_copy, text="PinkGift", anchor="w", font=ctk.CTkFont(size=19, weight="bold"), text_color=TEXT).pack(fill="x")
        ctk.CTkLabel(brand_copy, text="CONTROL CENTER", anchor="w", font=ctk.CTkFont(size=8, weight="bold"), text_color=PINK).pack(fill="x")

        self._section_label(sidebar, 1, "ESPACE DE TRAVAIL")
        self._nav_button(sidebar, 2, "dashboard", "⌂", "Vue d’ensemble", self._show_dashboard)
        self._section_label(sidebar, 3, "GESTION")
        self._nav_button(sidebar, 4, "orders", "≡", "Commandes", self._show_orders)
        self._nav_button(sidebar, 5, "clients", "♙", "Clients", self._show_clients)
        self._nav_button(sidebar, 6, "finances", "↗", "Statistiques", self._show_finances)
        self._nav_button(sidebar, 7, "referrals", "◇", "Parrainages", self._show_referrals)
        self._section_label(sidebar, 8, "CATALOGUE")
        self._nav_button(sidebar, 9, "prices", "€", "Prix & coûts", self._show_prices)
        self._nav_button(sidebar, 10, "stock", "▦", "Disponibilités", self._show_stock)
        self._section_label(sidebar, 11, "DISCORD")
        self._nav_button(sidebar, 12, "embed_editor", "✎", "Éditeur d’embeds", self._show_embed_editor)
        self._nav_button(sidebar, 13, "embeds", "↥", "Publication", self._show_embeds)
        self._section_label(sidebar, 14, "APPLICATION")
        self._nav_button(sidebar, 15, "config", "⚙", "Configuration", self._show_config)

        connection_card = ctk.CTkFrame(sidebar, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=10)
        connection_card.grid(row=19, column=0, sticky="ew", padx=12, pady=(0, 9))
        ctk.CTkLabel(connection_card, text="SERVICE DISCORD", anchor="w", text_color="#606a7d", font=ctk.CTkFont(size=8, weight="bold")).pack(fill="x", padx=12, pady=(10, 2))
        self.connection_label = ctk.CTkLabel(connection_card, text="● Connexion…", anchor="w", text_color=MUTED, font=ctk.CTkFont(size=11, weight="bold"))
        self.connection_label.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(sidebar, text="Fermer l’application", height=35, corner_radius=8, fg_color="#24151d", hover_color="#351a26", text_color="#ff7893", font=ctk.CTkFont(size=11, weight="bold"), command=self.destroy).grid(row=20, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        topbar = ctk.CTkFrame(self.content, height=62, fg_color="#0c1017", corner_radius=0, border_color=BORDER, border_width=1)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        title_box = ctk.CTkFrame(topbar, fg_color="transparent")
        title_box.pack(side="left", padx=25, pady=10)
        ctk.CTkLabel(title_box, text="PINKGIFT  /", font=ctk.CTkFont(size=9, weight="bold"), text_color="#626b7e").pack(side="left", padx=(0, 7))
        self.page_title = ctk.CTkLabel(title_box, text="Vue d’ensemble", font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT)
        self.page_title.pack(side="left")
        status_pill = ctk.CTkFrame(topbar, fg_color="#111c19", border_color="#1f4b3e", border_width=1, corner_radius=12)
        status_pill.pack(side="right", padx=25, pady=14)
        self.top_status = ctk.CTkLabel(status_pill, text="● CONNEXION", text_color=MUTED, font=ctk.CTkFont(size=9, weight="bold"))
        self.top_status.pack(padx=12, pady=6)

        self.page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        self.page.grid(row=1, column=0, sticky="nsew")
        self._show_dashboard()

    def _section_label(self, parent, row, text):
        ctk.CTkLabel(parent, text=text, anchor="w", font=ctk.CTkFont(size=8, weight="bold"), text_color="#596276").grid(row=row, column=0, sticky="ew", padx=17, pady=(9, 4))

    def _nav_button(self, parent, row, key, icon, label, command):
        button = ctk.CTkButton(parent, text=f"{icon}     {label}", anchor="w", height=35, corner_radius=8, fg_color="transparent", hover_color="#161b26", text_color="#a0a8ba", font=ctk.CTkFont(size=11, weight="bold"), command=command)
        button.grid(row=row, column=0, sticky="ew", padx=9, pady=1)
        self.nav_buttons[key] = button

    def _select_nav(self, key, title):
        self.active_nav = key
        self.page_title.configure(text=title)
        for name, button in self.nav_buttons.items():
            button.configure(fg_color="#211b35" if name == key else "transparent", text_color="#d7c9ff" if name == key else "#a0a8ba", border_width=1 if name == key else 0, border_color="#3b2d61")
        for child in self.page.winfo_children():
            child.destroy()

    def _load_initial_data(self):
        def job():
            return self.api.status(), self.api.guilds(), self.api.embeds(), self.api.panel_snapshot(), self.api.all_embeds()

        def success(result):
            status, self.guilds, self.embeds, self.panel_data, self.all_embed_items = result
            ready = status.get("discord_ready", False)
            self.connection_label.configure(text="● Bot connecté" if ready else "● Bot hors ligne", text_color=GREEN if ready else RED)
            self.top_status.configure(text="BOT CONNECTÉ" if ready else "BOT HORS LIGNE", text_color=GREEN if ready else RED)
            self._show_dashboard()

        self._run_async(job, success)

    def _card(self, parent):
        return ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=12)

    def _show_dashboard(self):
        self._select_nav("dashboard", "Vue d’ensemble")
        body = ctk.CTkScrollableFrame(self.page, fg_color=BG)
        body.pack(fill="both", expand=True, padx=24, pady=22)

        hero = ctk.CTkFrame(body, fg_color="#131522", border_color="#343052", border_width=1, corner_radius=14)
        hero.pack(fill="x", pady=(0, 16))
        hero_copy = ctk.CTkFrame(hero, fg_color="transparent")
        hero_copy.pack(side="left", fill="both", expand=True, padx=24, pady=22)
        ctk.CTkLabel(hero_copy, text="PINKGIFT  ·  CENTRE DE CONTRÔLE", anchor="w", text_color="#b79cff", font=ctk.CTkFont(size=9, weight="bold")).pack(fill="x")
        ctk.CTkLabel(hero_copy, text="Toute ta boutique, au même endroit.", anchor="w", text_color=TEXT, font=ctk.CTkFont(size=24, weight="bold")).pack(fill="x", pady=(6, 4))
        ctk.CTkLabel(hero_copy, text="Commandes, prix, bénéfices et publications Discord synchronisés en direct.", anchor="w", text_color=MUTED, font=ctk.CTkFont(size=12)).pack(fill="x")
        hero_actions = ctk.CTkFrame(hero_copy, fg_color="transparent")
        hero_actions.pack(fill="x", pady=(17, 0))
        ctk.CTkButton(hero_actions, text="Gérer les commandes", width=155, height=36, corner_radius=8, fg_color=PURPLE, hover_color=PURPLE_HOVER, font=ctk.CTkFont(size=11, weight="bold"), command=self._show_orders).pack(side="left")
        ctk.CTkButton(hero_actions, text="Publier un embed", width=145, height=36, corner_radius=8, fg_color=CARD_ALT, hover_color="#202636", border_color="#30384a", border_width=1, font=ctk.CTkFont(size=11, weight="bold"), command=self._show_embeds).pack(side="left", padx=8)
        if self.logo_image:
            ctk.CTkLabel(hero, text="", image=self.logo_image).pack(side="right", padx=35)

        stats = ctk.CTkFrame(body, fg_color="transparent")
        stats.pack(fill="x")
        finances = self.panel_data.get("finances", {})
        for title, value, color in [
            ("COMMANDES DU MOIS", str(finances.get("orders", 0)), PURPLE),
            ("CHIFFRE D’AFFAIRES", f"{float(finances.get('revenue') or 0):.2f} €", PINK),
            ("BÉNÉFICE", f"{float(finances.get('profit') or 0):.2f} €", GREEN),
        ]:
            card = self._card(stats)
            card.pack(side="left", fill="x", expand=True, padx=(0, 12))
            ctk.CTkLabel(card, text=title, anchor="w", text_color="#6f788c", font=ctk.CTkFont(size=9, weight="bold")).pack(fill="x", padx=17, pady=(15, 5))
            ctk.CTkLabel(card, text=value, anchor="w", text_color=color, font=ctk.CTkFont(size=24, weight="bold")).pack(fill="x", padx=17, pady=(0, 15))

        shortcuts = ctk.CTkFrame(body, fg_color="transparent")
        shortcuts.pack(fill="x", pady=(16, 0))
        for title, subtitle, button, command in [
            ("Catalogue", "Ajuste les prix de vente et les coûts d’achat.", "Ouvrir les prix", self._show_prices),
            ("Communication Discord", "Modifie puis publie les panneaux avec aperçu réel.", "Ouvrir les embeds", self._show_embed_editor),
        ]:
            quick = self._card(shortcuts)
            quick.pack(side="left", fill="both", expand=True, padx=(0, 12))
            ctk.CTkLabel(quick, text=title, anchor="w", text_color=TEXT, font=ctk.CTkFont(size=15, weight="bold")).pack(fill="x", padx=18, pady=(16, 4))
            ctk.CTkLabel(quick, text=subtitle, anchor="w", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(fill="x", padx=18)
            ctk.CTkButton(quick, text=button, width=135, height=32, corner_radius=7, fg_color=CARD_ALT, hover_color="#222838", command=command).pack(anchor="w", padx=18, pady=15)

    def _refresh_panel(self, callback=None):
        self.top_status.configure(text="SYNCHRONISATION…", text_color=MUTED)

        def success(data):
            self.panel_data = data
            self.top_status.configure(text="BOT CONNECTÉ", text_color=GREEN)
            if callback:
                callback()

        self._run_async(self.api.panel_snapshot, success)

    def _page_header(self, parent, title, subtitle="", refresh=None):
        line = ctk.CTkFrame(parent, fg_color="transparent")
        line.pack(fill="x", pady=(0, 18))
        texts = ctk.CTkFrame(line, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(texts, text="ESPACE PINKGIFT", anchor="w", font=ctk.CTkFont(size=8, weight="bold"), text_color="#7965b5").pack(fill="x")
        ctk.CTkLabel(texts, text=title, anchor="w", font=ctk.CTkFont(size=21, weight="bold"), text_color=TEXT).pack(fill="x", pady=(3, 0))
        if subtitle:
            ctk.CTkLabel(texts, text=subtitle, anchor="w", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(fill="x", pady=(4, 0))
        if refresh:
            ctk.CTkButton(line, text="↻  Actualiser", width=105, height=34, corner_radius=8, fg_color=CARD_ALT, hover_color="#242b3a", border_color=BORDER, border_width=1, font=ctk.CTkFont(size=10, weight="bold"), command=refresh).pack(side="right")

    def _show_orders(self):
        self._select_nav("orders", "Commandes")
        body = ctk.CTkFrame(self.page, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=20)
        self._page_header(body, "Commandes", "Livraison, remboursement et suppression synchronisés avec Discord.", lambda: self._refresh_panel(self._show_orders))
        filters = ctk.CTkFrame(body, fg_color="transparent")
        filters.pack(fill="x", pady=(0, 10))
        self.order_filter = ctk.CTkComboBox(filters, values=["Toutes", "En attente", "Cartes & Nitro", "Valorant", "COD Points"], width=180, state="readonly", command=lambda _v: self._render_orders_list())
        self.order_filter.pack(side="left")
        self.order_filter.set("Toutes")
        self.orders_list = ctk.CTkScrollableFrame(body, fg_color=BG)
        self.orders_list.pack(fill="both", expand=True)
        self._render_orders_list()

    def _render_orders_list(self):
        if not hasattr(self, "orders_list"):
            return
        for child in self.orders_list.winfo_children():
            child.destroy()
        mode = self.order_filter.get()
        orders = list(self.panel_data.get("orders", []))
        if mode == "En attente":
            orders = [item for item in orders if str(item.get("status", "pending")).lower() == "pending"]
        elif mode == "Valorant":
            orders = [item for item in orders if str(item.get("service", "")).lower().startswith("valorant")]
        elif mode == "COD Points":
            orders = [item for item in orders if str(item.get("service", "")).upper().startswith("COD POINTS")]
        elif mode == "Cartes & Nitro":
            orders = [item for item in orders if not str(item.get("service", "")).lower().startswith("valorant") and not str(item.get("service", "")).upper().startswith("COD POINTS")]
        for order in orders[:200]:
            card = self._card(self.orders_list)
            card.pack(fill="x", pady=5)
            info = ctk.CTkFrame(card, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=15, pady=12)
            status = str(order.get("status") or "pending").lower()
            status_text = "EN ATTENTE" if status == "pending" else status.upper()
            ctk.CTkLabel(info, text=f"#{order['id']}  ·  {order.get('service') or 'Produit'}", anchor="w", text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold")).pack(fill="x")
            ctk.CTkLabel(info, text=f"@{order.get('user_name') or order.get('user_id')}  ·  payé {float(order.get('paid') or 0):.2f} €  ·  {order.get('created_at') or ''}", anchor="w", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(fill="x", pady=(4, 0))
            actions = ctk.CTkFrame(card, fg_color="transparent")
            actions.pack(side="right", padx=12)
            ctk.CTkLabel(actions, text=status_text, text_color="#ffd27b" if status == "pending" else GREEN, font=ctk.CTkFont(size=10, weight="bold")).pack(pady=(0, 5))
            if status == "pending":
                ctk.CTkButton(actions, text="Livrer", width=82, height=28, fg_color=PURPLE, command=lambda item=order: self._order_action(item, "deliver")).pack(side="left", padx=3)
                ctk.CTkButton(actions, text="Rembourser", width=92, height=28, fg_color="#9d294b", command=lambda item=order: self._order_action(item, "refund")).pack(side="left", padx=3)
            else:
                ctk.CTkButton(actions, text="Supprimer", width=88, height=28, fg_color="#6f263b", command=lambda item=order: self._order_action(item, "delete")).pack()
        if not orders:
            ctk.CTkLabel(self.orders_list, text="Aucune commande pour ce filtre.", text_color=MUTED).pack(pady=40)

    def _order_action(self, order, action):
        code = ""
        if action == "deliver":
            code = simpledialog.askstring(APP_NAME, f"Code de livraison pour la commande #{order['id']} :", parent=self) or ""
            if not code:
                return
        elif action == "refund" and not messagebox.askyesno(APP_NAME, "Rembourser cette commande sur le solde du client ?", parent=self):
            return
        elif action == "delete" and not messagebox.askyesno(APP_NAME, "Supprimer définitivement cette commande et sa commission associée ?", parent=self):
            return

        def success(result):
            messagebox.showinfo(APP_NAME, result.get("message", "Action terminée"), parent=self)
            self._refresh_panel(self._show_orders)

        self._run_async(lambda: self.api.order_action(order["id"], action, code), success)

    def _show_clients(self):
        self._select_nav("clients", "Clients")
        body = ctk.CTkFrame(self.page, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=20)
        self._page_header(body, "Clients", "Classement par montant dépensé.", lambda: self._refresh_panel(self._show_clients))
        table = ctk.CTkScrollableFrame(body, fg_color=BG)
        table.pack(fill="both", expand=True)
        for index, client in enumerate(self.panel_data.get("clients", []), 1):
            row = self._card(table)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=f"#{index}", width=45, text_color=PURPLE, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(12, 0), pady=12)
            ctk.CTkLabel(row, text=f"@{client.get('user_name')}", anchor="w", text_color=TEXT, font=ctk.CTkFont(weight="bold")).pack(side="left", fill="x", expand=True, padx=12)
            ctk.CTkLabel(row, text=f"{client.get('order_count', 0)} commandes", text_color=MUTED).pack(side="left", padx=16)
            ctk.CTkLabel(row, text=f"{float(client.get('total_spent') or 0):.2f} €", text_color=GREEN, font=ctk.CTkFont(size=15, weight="bold")).pack(side="right", padx=16)

    def _show_finances(self):
        self._select_nav("finances", "Statistiques")
        body = ctk.CTkScrollableFrame(self.page, fg_color=BG)
        body.pack(fill="both", expand=True, padx=22, pady=20)
        self._page_header(body, f"Statistiques · {self.panel_data.get('finance_month_label', '')}", "Chiffre d’affaires et bénéfices calculés sur les coûts d’achat.", lambda: self._refresh_panel(self._show_finances))
        stats = self.panel_data.get("finances", {})
        month_bar = ctk.CTkFrame(body, fg_color="transparent")
        month_bar.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(month_bar, text="Mois (AAAA-MM)", text_color=MUTED).pack(side="left")
        self.finance_month_entry = ctk.CTkEntry(month_bar, width=120, height=34, fg_color=CARD, border_color=BORDER)
        self.finance_month_entry.pack(side="left", padx=8)
        self.finance_month_entry.insert(0, str(stats.get("month") or ""))
        ctk.CTkButton(month_bar, text="Afficher", width=90, height=34, fg_color=PURPLE, command=self._load_finance_month).pack(side="left")
        cards = ctk.CTkFrame(body, fg_color="transparent")
        cards.pack(fill="x")
        for label, key, color in [("CHIFFRE D’AFFAIRES", "revenue", TEXT), ("COÛTS", "costs", RED), ("BÉNÉFICE", "profit", GREEN), ("COMMANDES", "orders", PURPLE)]:
            card = self._card(cards)
            card.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ctk.CTkLabel(card, text=label, text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", padx=15, pady=(14, 5))
            suffix = "" if key == "orders" else " €"
            ctk.CTkLabel(card, text=f"{stats.get(key, 0):.2f}{suffix}" if key != "orders" else str(stats.get(key, 0)), text_color=color, font=ctk.CTkFont(size=23, weight="bold")).pack(anchor="w", padx=15, pady=(0, 14))
        ctk.CTkLabel(body, text="Détail par produit", anchor="w", text_color=TEXT, font=ctk.CTkFont(size=17, weight="bold")).pack(fill="x", pady=(24, 8))
        for item in stats.get("breakdown", []):
            row = self._card(body)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=item.get("service", "Produit"), anchor="w", text_color=TEXT).pack(side="left", fill="x", expand=True, padx=14, pady=10)
            ctk.CTkLabel(row, text=f"CA {float(item.get('revenue') or 0):.2f} €", text_color=MUTED).pack(side="left", padx=14)
            ctk.CTkLabel(row, text=f"+{float(item.get('profit') or 0):.2f} €", text_color=GREEN, font=ctk.CTkFont(weight="bold")).pack(side="right", padx=14)

    def _load_finance_month(self):
        month = self.finance_month_entry.get().strip()

        def success(data):
            self.panel_data = data
            self._show_finances()

        self._run_async(lambda: self.api.panel_snapshot(month), success)

    def _show_referrals(self):
        self._select_nav("referrals", "Parrainages")
        body = ctk.CTkScrollableFrame(self.page, fg_color=BG)
        body.pack(fill="both", expand=True, padx=22, pady=20)
        self._page_header(body, "Parrainages", "Création des codes et suivi des commissions.", lambda: self._refresh_panel(self._show_referrals))
        form = self._card(body)
        form.pack(fill="x", pady=(0, 15))
        grid = ctk.CTkFrame(form, fg_color="transparent")
        grid.pack(fill="x", padx=15, pady=15)
        self.ref_entries = {}
        for col, (key, label) in enumerate([("code", "Code"), ("sponsor_name", "Parrain"), ("sponsor_id", "ID Discord"), ("percentage", "%"), ("paid", "Déjà versé")]):
            box = ctk.CTkFrame(grid, fg_color="transparent")
            box.grid(row=0, column=col, sticky="ew", padx=4)
            grid.grid_columnconfigure(col, weight=2 if key in ("sponsor_name", "sponsor_id") else 1)
            ctk.CTkLabel(box, text=label.upper(), anchor="w", text_color=MUTED, font=ctk.CTkFont(size=9, weight="bold")).pack(fill="x")
            entry = ctk.CTkEntry(box, height=36, fg_color=BG, border_color=BORDER)
            entry.pack(fill="x", pady=(5, 0))
            self.ref_entries[key] = entry
        self.ref_active = ctk.CTkSwitch(grid, text="Actif", progress_color=PINK)
        self.ref_active.grid(row=1, column=0, pady=(14, 0), sticky="w")
        self.ref_active.select()
        ctk.CTkButton(grid, text="Enregistrer", width=130, fg_color=PURPLE, command=self._save_referral).grid(row=1, column=4, pady=(12, 0), sticky="e")
        for item in self.panel_data.get("referrals", []):
            row = self._card(body)
            row.pack(fill="x", pady=4)
            info = f"{item.get('sponsor_name')} · {item.get('percentage', 0):g}% · {item.get('uses', 0)} ventes"
            ctk.CTkLabel(row, text=item.get("code", ""), width=120, text_color=PINK, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=14, pady=12)
            ctk.CTkLabel(row, text=info, anchor="w", text_color=TEXT).pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(row, text=f"À verser {float(item.get('due') or 0):.2f} €", text_color=GREEN, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=12)
            ctk.CTkButton(row, text="Modifier", width=75, height=28, fg_color=CARD_ALT, command=lambda data=item: self._edit_referral(data)).pack(side="left", padx=3)
            ctk.CTkButton(row, text="Supprimer", width=80, height=28, fg_color="#72263d", command=lambda data=item: self._delete_referral(data)).pack(side="right", padx=10)
        ctk.CTkLabel(body, text="Historique récent des commissions", anchor="w", text_color=TEXT, font=ctk.CTkFont(size=17, weight="bold")).pack(fill="x", pady=(22, 8))
        events = self.panel_data.get("referral_events", [])
        for event in events[:100]:
            row = self._card(body)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=event.get("code", ""), width=110, text_color=PINK, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=14, pady=10)
            ctk.CTkLabel(row, text=f"Client {event.get('user_id', '')} · {event.get('created_at', '')}", anchor="w", text_color=MUTED).pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(row, text=f"{float(event.get('commission') or 0):.2f} €", text_color=GREEN, font=ctk.CTkFont(weight="bold")).pack(side="right", padx=14)
        if not events:
            ctk.CTkLabel(body, text="Aucune commission enregistrée.", text_color=MUTED).pack(anchor="w", pady=12)

    def _edit_referral(self, item):
        for key, entry in self.ref_entries.items():
            entry.delete(0, "end")
            entry.insert(0, str(item.get(key, "")))
        self.ref_active.select() if item.get("active") else self.ref_active.deselect()

    def _save_referral(self):
        payload = {key: entry.get() for key, entry in self.ref_entries.items()}
        payload.update(action="save", active=bool(self.ref_active.get()))
        self._run_async(lambda: self.api.update_referral(**payload), lambda _r: self._refresh_panel(self._show_referrals))

    def _delete_referral(self, item):
        if not messagebox.askyesno(APP_NAME, f"Supprimer définitivement le code {item.get('code')} et tout son historique ?", parent=self):
            return
        self._run_async(lambda: self.api.update_referral(action="delete", code=item.get("code")), lambda _r: self._refresh_panel(self._show_referrals))

    @staticmethod
    def _nested_get(data, path, default=0):
        value = data
        for key in path:
            value = value.get(key, {}) if isinstance(value, dict) else {}
        return default if isinstance(value, dict) else value

    @staticmethod
    def _nested_set(data, path, value):
        target = data
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = value

    def _show_prices(self):
        self._select_nav("prices", "Prix & coûts")
        body = ctk.CTkFrame(self.page, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=20)
        self._page_header(body, "Prix & coûts d’achat", "Toute modification actualise les débits, les bénéfices et les embeds.", lambda: self._refresh_panel(self._show_prices))
        scroll = ctk.CTkScrollableFrame(body, fg_color=BG)
        scroll.pack(fill="both", expand=True)
        self.price_entries = []
        pricing = self.panel_data.get("pricing", {})
        costs = self.panel_data.get("purchase_costs", {})

        def section(title):
            ctk.CTkLabel(scroll, text=title, anchor="w", text_color=PINK, font=ctk.CTkFont(size=16, weight="bold")).pack(fill="x", pady=(16, 6))

        def row(label, sale_path=None, cost_path=None, official_path=None):
            line = self._card(scroll)
            line.pack(fill="x", pady=3)
            ctk.CTkLabel(line, text=label, anchor="w", width=330, text_color=TEXT).pack(side="left", fill="x", expand=True, padx=14, pady=9)
            for kind, path, source, caption in [
                ("pricing", sale_path, pricing, "Vente"),
                ("cost", cost_path, costs, "Coût"),
                ("pricing", official_path, pricing, "Officiel"),
            ]:
                if path:
                    box = ctk.CTkFrame(line, fg_color="transparent")
                    box.pack(side="left", padx=5)
                    ctk.CTkLabel(box, text=caption, text_color=MUTED, font=ctk.CTkFont(size=9)).pack(side="left", padx=4)
                    entry = ctk.CTkEntry(box, width=90, height=30, fg_color=BG, border_color=BORDER)
                    entry.pack(side="left")
                    entry.insert(0, str(self._nested_get(source, path, 0)))
                    self.price_entries.append((entry, kind, path))

        section("Tarifs généraux")
        for amount in self.panel_data.get("catalog", {}).get("gift_card_amounts", []):
            row(f"Carte cadeau {amount} €", ("gift_cards", str(amount)))
        row("Discord Nitro", ("discord_nitro",), ("discord_nitro",))
        for item in self.panel_data.get("catalog", {}).get("uber_eats", []):
            row(f"Uber Eats · {item['drop']} € estimés", ("uber_eats", item["key"]), ("uber_eats", item["key"]))
        section("Call of Duty Points")
        for item in self.panel_data.get("catalog", {}).get("cp", []):
            row(f"{item['points']} CP", ("cp", item["key"]), ("cp", item["key"]))
        section("Valorant Points")
        for item in self.panel_data.get("catalog", {}).get("valorant", []):
            row(
                f"{item['region']} · {item['pack']}",
                ("valorant", item["region_key"], item["pack_key"]),
                ("valorant", item["region_key"], item["pack_key"]),
                ("valorant_original", item["region_key"], item["pack_key"]),
            )
        section("Coûts des cartes cadeaux")
        for product in self.panel_data.get("catalog", {}).get("products", []):
            if product["key"] in ("UBEREATS", "DISCORD_NITRO"):
                continue
            for amount in self.panel_data.get("catalog", {}).get("gift_card_amounts", []):
                row(f"{product['label']} · {amount} €", None, ("gift_cards", product["key"], str(amount)))
        ctk.CTkButton(scroll, text="Enregistrer tous les prix et coûts", height=44, fg_color=PURPLE, hover_color="#7447dc", command=self._save_prices).pack(fill="x", pady=20)

    def _save_prices(self):
        pricing = copy.deepcopy(self.panel_data.get("pricing", {}))
        costs = copy.deepcopy(self.panel_data.get("purchase_costs", {}))
        try:
            for entry, kind, path in self.price_entries:
                value = float(entry.get().strip().replace(",", "."))
                self._nested_set(pricing if kind == "pricing" else costs, path, value)
        except ValueError:
            messagebox.showerror(APP_NAME, "Un prix ou un coût est invalide.", parent=self)
            return

        def success(result):
            self.panel_data["pricing"] = result["pricing"]
            self.panel_data["purchase_costs"] = result["purchase_costs"]
            messagebox.showinfo(APP_NAME, "Prix enregistrés et synchronisés avec Discord.", parent=self)

        self._run_async(lambda: self.api.update_prices(pricing, costs), success)

    def _show_stock(self):
        self._select_nav("stock", "Stock")
        body = ctk.CTkFrame(self.page, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=20)
        self._page_header(body, "Disponibilité des produits", "Les prochains menus Discord utilisent immédiatement ces états.", lambda: self._refresh_panel(self._show_stock))
        scroll = ctk.CTkScrollableFrame(body, fg_color=BG)
        scroll.pack(fill="both", expand=True)
        stock = self.panel_data.get("stock", {})
        for product in self.panel_data.get("catalog", {}).get("products", []):
            available = stock.get("products", {}).get(product["key"], True)
            self._stock_row(scroll, f"{product['emoji']} {product['label']}", "product", product["key"], available)
        ctk.CTkLabel(scroll, text="VALORANT POINTS", anchor="w", text_color=PINK, font=ctk.CTkFont(size=15, weight="bold")).pack(fill="x", pady=(18, 6))
        for item in self.panel_data.get("catalog", {}).get("valorant", []):
            available = stock.get("valorant", {}).get(item["region_key"], {}).get(item["pack_key"], True)
            self._stock_row(scroll, f"{item['region']} · {item['pack']}", "valorant", item["pack_key"], available, item["region_key"])

    def _stock_row(self, parent, label, kind, key, available, region=""):
        row = self._card(parent)
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=label, anchor="w", text_color=TEXT).pack(side="left", fill="x", expand=True, padx=14, pady=10)
        switch = ctk.CTkSwitch(row, text="Disponible", progress_color=GREEN)
        switch.pack(side="right", padx=14)
        switch.select() if available else switch.deselect()
        switch.configure(command=lambda: self._toggle_stock(switch, kind, key, region))

    def _toggle_stock(self, switch, kind, key, region):
        self._run_async(lambda: self.api.update_stock(kind, key, bool(switch.get()), region))

    def _show_embed_editor(self):
        self._select_nav("embed_editor", "Modifier les embeds")
        wrapper = ctk.CTkFrame(self.page, fg_color="transparent")
        wrapper.pack(fill="both", expand=True, padx=22, pady=20)
        self._page_header(wrapper, "Éditeur d’embeds", "Aperçu visuel en direct pendant la modification.", lambda: self._reload_all_embeds())
        content = ctk.CTkFrame(wrapper, fg_color="transparent")
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(1, weight=1)
        self.embed_editor_by_label = {f"{item.get('label')}  ·  {item['key']}": item for item in self.all_embed_items}
        values = list(self.embed_editor_by_label) or ["Chargement…"]
        self.embed_editor_combo = ctk.CTkComboBox(content, values=values, state="readonly", height=38, corner_radius=8, fg_color=CARD, border_color=BORDER, button_color=PURPLE, button_hover_color=PURPLE_HOVER, command=self._select_embed_editor)
        self.embed_editor_combo.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=(0, 10))
        self.embed_editor_combo.set(values[0])
        editor_actions = ctk.CTkFrame(content, fg_color="transparent")
        editor_actions.grid(row=0, column=1, sticky="e", pady=(0, 10))
        ctk.CTkButton(editor_actions, text="Importer une image", width=145, height=38, fg_color=CARD_ALT, command=self._upload_embed_image).pack(side="left", padx=(0, 7))
        ctk.CTkButton(editor_actions, text="Enregistrer l’embed", width=155, height=38, fg_color=PURPLE, command=self._save_embed_editor).pack(side="left")
        source_panel = self._card(content)
        source_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        source_panel.grid_columnconfigure(0, weight=1)
        source_panel.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(source_panel, text="CONTENU DE L’EMBED", anchor="w", text_color="#737d91", font=ctk.CTkFont(size=9, weight="bold")).grid(row=0, column=0, sticky="ew", padx=15, pady=(13, 8))
        self.embed_json_editor = ctk.CTkTextbox(source_panel, fg_color="#090c12", border_color=BORDER, border_width=1, corner_radius=8, text_color="#e5e7ef", font=("Consolas", 11), wrap="none")
        self.embed_json_editor.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.embed_json_editor.bind("<KeyRelease>", self._schedule_embed_live_preview)
        preview_panel = self._card(content)
        preview_panel.grid(row=1, column=1, sticky="nsew")
        preview_panel.grid_columnconfigure(0, weight=1)
        preview_panel.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(preview_panel, text="APERÇU DISCORD EN DIRECT", anchor="w", text_color="#737d91", font=ctk.CTkFont(size=9, weight="bold")).grid(row=0, column=0, sticky="ew", padx=15, pady=(13, 8))
        self.embed_visual = ctk.CTkScrollableFrame(preview_panel, fg_color="#0b0d11", border_color=BORDER, border_width=1, corner_radius=8)
        self.embed_visual.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        if self.all_embed_items:
            self._select_embed_editor(values[0])

    def _reload_all_embeds(self):
        self._run_async(self.api.all_embeds, lambda items: (setattr(self, "all_embed_items", items), self._show_embed_editor()))

    def _select_embed_editor(self, label):
        item = self.embed_editor_by_label.get(label)
        if not item:
            return
        self.embed_json_editor.delete("1.0", "end")
        self.embed_json_editor.insert("1.0", json.dumps(item.get("data", {}), ensure_ascii=False, indent=2))
        self._render_discord_preview(self.embed_visual, item.get("preview", {}))

    def _schedule_embed_live_preview(self, _event=None):
        if hasattr(self, "embed_preview_after"):
            self.after_cancel(self.embed_preview_after)
        self.embed_preview_after = self.after(250, self._update_embed_live_preview)

    def _update_embed_live_preview(self):
        try:
            data = json.loads(self.embed_json_editor.get("1.0", "end"))
            description = data.get("description", "")
            if isinstance(description, list):
                description = "\n".join(map(str, description))
            preview = {
                "title": data.get("title", ""), "description": description,
                "fields": data.get("fields", []), "footer": data.get("footer", ""),
                "image_url": data.get("image_url", ""),
                "thumbnail_url": data.get("thumbnail_url", ""),
                "color": self._rgb_to_int(data.get("color_rgb")),
            }
            self._render_discord_preview(self.embed_visual, preview)
        except (ValueError, TypeError):
            pass

    @staticmethod
    def _rgb_to_int(rgb):
        try:
            return (int(rgb[0]) << 16) + (int(rgb[1]) << 8) + int(rgb[2])
        except (TypeError, ValueError, IndexError):
            return 16761035

    def _render_discord_preview(self, parent, preview):
        for child in parent.winfo_children():
            child.destroy()
        color = int(preview.get("color") or 16761035)
        color_hex = f"#{color:06x}"[-7:]
        shell = ctk.CTkFrame(parent, fg_color="#1e1f22", corner_radius=7)
        shell.pack(fill="x", padx=8, pady=8)
        ctk.CTkFrame(shell, width=5, fg_color=color_hex, corner_radius=3).pack(side="left", fill="y")
        inside = ctk.CTkFrame(shell, fg_color="transparent")
        inside.pack(side="left", fill="both", expand=True, padx=14, pady=13)
        heading = ctk.CTkFrame(inside, fg_color="transparent")
        heading.pack(fill="x")
        text_column = ctk.CTkFrame(heading, fg_color="transparent")
        text_column.pack(side="left", fill="both", expand=True)
        thumbnail_url = str(preview.get("thumbnail_url") or "").strip()
        if thumbnail_url:
            thumbnail = ctk.CTkLabel(heading, text="Chargement…", width=82, height=82, text_color=MUTED)
            thumbnail.pack(side="right", anchor="ne", padx=(12, 0))
            self._load_preview_image(thumbnail, thumbnail_url, 82, 82)
        if preview.get("title"):
            ctk.CTkLabel(text_column, text=str(preview["title"]), anchor="w", justify="left", text_color="#f2f3f5", font=ctk.CTkFont(size=15, weight="bold"), wraplength=340 if thumbnail_url else 430).pack(fill="x", pady=(0, 7))
        if preview.get("description"):
            ctk.CTkLabel(text_column, text=str(preview["description"]), anchor="w", justify="left", text_color="#dbdee1", font=ctk.CTkFont(size=12), wraplength=340 if thumbnail_url else 430).pack(fill="x")
        fields = preview.get("fields", [])
        if fields:
            field_grid = ctk.CTkFrame(inside, fg_color="transparent")
            field_grid.pack(fill="x", pady=(2, 0))
            row_index = 0
            column_index = 0
            for field in fields:
                inline = bool(field.get("inline"))
                if not inline and column_index:
                    row_index += 1
                    column_index = 0
                field_box = ctk.CTkFrame(field_grid, fg_color="transparent")
                field_box.grid(
                    row=row_index,
                    column=column_index if inline else 0,
                    columnspan=1 if inline else 3,
                    sticky="new",
                    padx=(0, 10),
                    pady=(10, 0),
                )
                ctk.CTkLabel(field_box, text=str(field.get("name", "")), anchor="w", justify="left", text_color="#f2f3f5", font=ctk.CTkFont(size=12, weight="bold"), wraplength=135 if inline else 430).pack(fill="x")
                ctk.CTkLabel(field_box, text=str(field.get("value", "")), anchor="w", justify="left", text_color="#dbdee1", font=ctk.CTkFont(size=11), wraplength=135 if inline else 430).pack(fill="x", pady=(2, 0))
                if inline:
                    field_grid.grid_columnconfigure(column_index, weight=1)
                    column_index += 1
                    if column_index == 3:
                        row_index += 1
                        column_index = 0
                else:
                    row_index += 1
        if preview.get("image_url"):
            image_label = ctk.CTkLabel(inside, text="Chargement de l’image…", height=130, text_color=MUTED)
            image_label.pack(fill="x", pady=(12, 0))
            self._load_preview_image(image_label, str(preview["image_url"]), 430, 260)
        if preview.get("footer"):
            ctk.CTkLabel(inside, text=str(preview["footer"]), anchor="w", text_color="#b5bac1", font=ctk.CTkFont(size=10), wraplength=430).pack(fill="x", pady=(12, 0))

    def _load_preview_image(self, label, url, max_width, max_height):
        def apply_image(pil_image):
            if not label.winfo_exists():
                return
            width, height = pil_image.size
            ratio = min(max_width / max(width, 1), max_height / max(height, 1), 1)
            display_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
            rendered = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=display_size)
            label._pinkgift_image = rendered
            label.configure(text="", image=rendered, width=display_size[0], height=display_size[1])

        cached = self.preview_image_cache.get(url)
        if cached is not None:
            apply_image(cached)
            return

        def worker():
            try:
                response = requests.get(url, timeout=8, headers={"User-Agent": "PinkGiftTool/1.0"})
                response.raise_for_status()
                image = Image.open(BytesIO(response.content)).convert("RGBA")
                self.preview_image_cache[url] = image
                self.after(0, lambda: apply_image(image))
            except Exception:
                self.after(0, lambda: label.winfo_exists() and label.configure(text="Image indisponible", text_color=RED))

        threading.Thread(target=worker, daemon=True).start()

    def _save_embed_editor(self):
        item = self.embed_editor_by_label.get(self.embed_editor_combo.get())
        if not item:
            return
        try:
            data = json.loads(self.embed_json_editor.get("1.0", "end"))
        except ValueError as error:
            messagebox.showerror(APP_NAME, f"JSON invalide : {error}", parent=self)
            return

        def success(result):
            item["data"] = data
            item["preview"] = result.get("preview", {})
            self._render_discord_preview(self.embed_visual, item["preview"])
            messagebox.showinfo(APP_NAME, "Embed enregistré. Aucun redémarrage nécessaire.", parent=self)

        self._run_async(lambda: self.api.save_embed(item["key"], data), success)

    def _upload_embed_image(self):
        file_path = filedialog.askopenfilename(
            parent=self,
            title="Choisir l’image de l’embed",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp"), ("Tous les fichiers", "*.*")],
        )
        if not file_path:
            return

        def success(image_url):
            try:
                data = json.loads(self.embed_json_editor.get("1.0", "end"))
            except ValueError:
                data = {}
            data["image_url"] = image_url
            self.embed_json_editor.delete("1.0", "end")
            self.embed_json_editor.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))
            self._update_embed_live_preview()
            messagebox.showinfo(APP_NAME, "Image importée. Enregistre l’embed pour appliquer la modification.", parent=self)

        self._run_async(lambda: self.api.upload_image(file_path), success)

    def _show_embeds(self):
        self._select_nav("embeds", "Publier un embed")
        wrapper = ctk.CTkFrame(self.page, fg_color="transparent")
        wrapper.pack(fill="both", expand=True, padx=24, pady=22)
        wrapper.grid_columnconfigure(0, weight=5)
        wrapper.grid_columnconfigure(1, weight=4)
        wrapper.grid_rowconfigure(1, weight=1)

        heading = ctk.CTkFrame(wrapper, fg_color="transparent")
        heading.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(heading, text="DISCORD  ·  PUBLICATION", anchor="w", font=ctk.CTkFont(size=8, weight="bold"), text_color="#7965b5").pack(fill="x")
        ctk.CTkLabel(heading, text="Publier un panneau", anchor="w", font=ctk.CTkFont(size=21, weight="bold"), text_color=TEXT).pack(fill="x", pady=(3, 0))
        ctk.CTkLabel(heading, text="Choisis la destination et vérifie le rendu exact avant l’envoi.", anchor="w", font=ctk.CTkFont(size=11), text_color=MUTED).pack(fill="x", pady=(4, 0))
        form = self._card(wrapper)
        form.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        form.grid_columnconfigure(0, weight=1)

        self.guild_by_label = {f"{item['name']}  ·  {item['member_count']} membres": item for item in self.guilds}
        guild_values = list(self.guild_by_label) or ["Aucun serveur disponible"]
        self._field_label(form, "SERVEUR DISCORD", 0)
        self.guild_combo = ctk.CTkComboBox(form, values=guild_values, height=42, state="readonly", fg_color=BG, border_color=BORDER, command=self._guild_changed)
        self.guild_combo.grid(row=1, column=0, sticky="ew", padx=20)
        self.guild_combo.set(guild_values[0])

        self._field_label(form, "SALON DE PUBLICATION", 2)
        self.channel_combo = ctk.CTkComboBox(form, values=["Chargement…"], height=42, state="readonly", fg_color=BG, border_color=BORDER)
        self.channel_combo.grid(row=3, column=0, sticky="ew", padx=20)
        self.channel_combo.set("Chargement…")

        self._field_label(form, "EMBED À PUBLIER", 4)
        self.embed_by_label = {f"{item['category']}  ·  {item['label']}": item for item in self.embeds}
        embed_values = list(self.embed_by_label) or ["Chargement…"]
        self.embed_combo = ctk.CTkComboBox(form, values=embed_values, height=42, state="readonly", fg_color=BG, border_color=BORDER, command=self._embed_changed)
        self.embed_combo.grid(row=5, column=0, sticky="ew", padx=20)
        self.embed_combo.set(embed_values[0])

        mention_box = ctk.CTkFrame(form, fg_color=CARD_ALT, corner_radius=8)
        mention_box.grid(row=6, column=0, sticky="ew", padx=20, pady=20)
        mention_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(mention_box, text="Mentionner @everyone", anchor="w", text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 2))
        ctk.CTkLabel(mention_box, text="Désactivé par défaut pour éviter les pings accidentels.", anchor="w", text_color=MUTED, font=ctk.CTkFont(size=11)).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        self.mention_switch = ctk.CTkSwitch(mention_box, text="", progress_color=PINK)
        self.mention_switch.grid(row=0, column=1, rowspan=2, padx=14)

        self.publish_button = ctk.CTkButton(form, text="Publier dans le salon", height=44, corner_radius=8, fg_color=PURPLE, hover_color=PURPLE_HOVER, font=ctk.CTkFont(size=12, weight="bold"), command=self._publish)
        self.publish_button.grid(row=7, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.publish_status = ctk.CTkLabel(form, text="", text_color=MUTED, wraplength=460)
        self.publish_status.grid(row=8, column=0, sticky="ew", padx=20, pady=(0, 15))

        preview = self._card(wrapper)
        preview.grid(row=1, column=1, sticky="nsew")
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(preview, text="APERÇU DE L’EMBED", anchor="w", text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")).grid(row=0, column=0, sticky="ew", padx=18, pady=(17, 8))
        self.publish_preview_visual = ctk.CTkScrollableFrame(
            preview,
            fg_color="#0b0d11",
            border_color=BORDER,
            border_width=1,
        )
        self.publish_preview_visual.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

        if self.guilds:
            self._guild_changed(self.guild_combo.get())
        if self.embeds:
            self._embed_changed(self.embed_combo.get())

    def _field_label(self, parent, text, row):
        ctk.CTkLabel(parent, text=text, anchor="w", text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")).grid(row=row, column=0, sticky="ew", padx=20, pady=(18 if row == 0 else 15, 7))

    def _guild_changed(self, label):
        guild = self.guild_by_label.get(label)
        if not guild:
            return
        self.channel_combo.configure(values=["Chargement…"])
        self.channel_combo.set("Chargement…")

        def success(channels):
            self.channels = channels
            self.channel_by_label = {
                f"{item['category']}  /  #{item['name']}": item for item in channels
            }
            values = list(self.channel_by_label) or ["Aucun salon accessible"]
            self.channel_combo.configure(values=values)
            self.channel_combo.set(values[0])

        self._run_async(lambda: self.api.channels(guild["id"]), success)

    def _embed_changed(self, label):
        item = self.embed_by_label.get(label)
        if not item:
            return
        preview = item.get("preview") or {}
        if not preview.get("title"):
            preview = {**preview, "title": item["label"]}
        self._render_discord_preview(self.publish_preview_visual, preview)

    def _publish(self):
        guild = self.guild_by_label.get(self.guild_combo.get())
        channel = self.channel_by_label.get(self.channel_combo.get())
        embed = self.embed_by_label.get(self.embed_combo.get())
        if not guild or not channel or not embed:
            self.publish_status.configure(text="Sélectionne un serveur, un salon et un embed.", text_color=RED)
            return
        if self.mention_switch.get() and not messagebox.askyesno(APP_NAME, "Confirmer la mention @everyone ?", parent=self):
            return
        self.publish_button.configure(state="disabled", text="Publication…")
        self.publish_status.configure(text="Envoi du panneau à Discord…", text_color=MUTED)

        def success(result):
            self.publish_button.configure(state="normal", text="Publier dans le salon")
            self.publish_status.configure(text=f"✓ Publié dans #{result['channel_name']}", text_color=GREEN)

        def failure(error):
            self.publish_button.configure(state="normal", text="Publier dans le salon")
            self.publish_status.configure(text=str(error), text_color=RED)

        self._run_async(lambda: self.api.publish(guild["id"], channel["id"], embed["key"], self.mention_switch.get()), success, failure)

    def _show_config(self):
        self._select_nav("config", "Configuration")
        body = ctk.CTkFrame(self.page, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=22)
        card = self._card(body)
        card.pack(fill="x")
        ctk.CTkLabel(card, text="Connexion au panel", anchor="w", font=ctk.CTkFont(size=18, weight="bold"), text_color=TEXT).pack(fill="x", padx=20, pady=(18, 6))
        ctk.CTkLabel(card, text=self.api.base_url, anchor="w", text_color=MUTED).pack(fill="x", padx=20)
        ctk.CTkLabel(card, text="Le mot de passe n’est jamais enregistré sur l’ordinateur.", anchor="w", text_color=GREEN, font=ctk.CTkFont(size=12)).pack(fill="x", padx=20, pady=(7, 0))
        ctk.CTkButton(card, text="Changer de connexion", width=190, height=40, fg_color="#32223f", hover_color="#443052", command=self._show_login).pack(anchor="w", padx=20, pady=18)


if __name__ == "__main__":
    PinkGiftTool().mainloop()
