"""Interactive Discord UI components for the calendar bot."""

import re
from datetime import timedelta

import discord  # type: ignore

from log import logger
from utils import format_event, event_when, escape_md, shorten, get_today

# ---------------------------------------------------------------------------
# Video-call link extraction
# ---------------------------------------------------------------------------

_ZOOM_RE = re.compile(r'https?://[\w.]*zoom\.us/[^\s<>"\']+', re.IGNORECASE)
_TEAMS_RE = re.compile(r'https?://teams\.microsoft\.com/[^\s<>"\']+', re.IGNORECASE)
_MEET_RE = re.compile(r'https?://meet\.google\.com/[^\s<>"\']+', re.IGNORECASE)


def extract_video_links(text: str) -> list[tuple[str, str]]:
    """Return [(label, url), ...] for Zoom / Teams / Meet links in *text*."""
    if not text:
        return []
    links: list[tuple[str, str]] = []
    for pattern, label in [(_ZOOM_RE, "Zoom"), (_TEAMS_RE, "Teams"), (_MEET_RE, "Google Meet")]:
        for m in pattern.finditer(text):
            links.append((label, m.group()))
    return links


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

_MAX_FIELD_LEN = 900   # Discord field limit is 1024; leave buffer
_MAX_FIELDS = 20       # Discord embed limit is 25; leave room for header
_MAX_PAGE_CHARS = 5500  # Discord rejects embeds over 6000 chars in total; leave room for the footer


def _start_key(e: dict) -> str:
    return e["start"].get("dateTime", e["start"].get("date", ""))


def _chunk_events(events: list[dict]) -> list[list[dict]]:
    """Split sorted events into groups whose formatted lines fit one embed field."""
    chunks: list[list[dict]] = []
    chunk: list[dict] = []
    chunk_len = 0
    for ev in sorted(events, key=_start_key):
        line_len = len(format_event(ev)) + 2
        if chunk and chunk_len + line_len > _MAX_FIELD_LEN:
            chunks.append(chunk)
            chunk, chunk_len = [], 0
        chunk.append(ev)
        chunk_len += line_len
    if chunk:
        chunks.append(chunk)
    return chunks


def _paginate(fields: list[tuple[str, list[dict]]], title: str, description: str, color: int):
    """Lay out (field name, events) pairs over as many embeds as Discord's limits need."""
    pages: list[discord.Embed] = []
    epp: list[list[dict]] = []
    embed = discord.Embed(title=title, description=description or None, color=color)
    cur_events: list[dict] = []
    page_chars = len(title) + len(description)

    for name, events in fields:
        value = "\n".join(format_event(e) for e in events)
        size = len(name) + len(value)
        if embed.fields and (len(embed.fields) >= _MAX_FIELDS or page_chars + size > _MAX_PAGE_CHARS):
            pages.append(embed)
            epp.append(cur_events)
            cont_title = f"{title} (cont.)"
            embed = discord.Embed(title=cont_title, color=color)
            cur_events = []
            page_chars = len(cont_title)
        embed.add_field(name=name, value=value, inline=False)
        cur_events.extend(events)
        page_chars += size

    # Always return at least one page
    pages.append(embed)
    epp.append(cur_events)
    return pages, epp


def build_event_pages(
    events: list[dict],
    *,
    title: str,
    description: str = "",
    color: int = 0x95A5A6,
) -> tuple[list[discord.Embed], list[list[dict]]]:
    """Build paginated embeds listing *events* in time order.

    Returns ``(pages, events_per_page)`` where *pages[i]* is a
    :class:`discord.Embed` and *events_per_page[i]* is the flat list
    of event dicts visible on that page.
    """
    n = len(events)
    heading = f"{n} event{'s' if n != 1 else ''}"
    fields = [(heading if ci == 0 else f"{heading} (cont.)", chunk)
              for ci, chunk in enumerate(_chunk_events(events))]
    return _paginate(fields, title, description, color)


def build_week_pages(
    events_by_day: dict,
    *,
    title: str,
    description: str = "",
    color: int = 0x95A5A6,
    monday=None,
) -> tuple[list[discord.Embed], list[list[dict]]]:
    """Build paginated embeds for a weekly view (one or more fields per day)."""
    days = [monday + timedelta(days=i) for i in range(7)] if monday else sorted(events_by_day.keys())
    today = get_today()
    fields = []
    for day in days:
        for ci, chunk in enumerate(_chunk_events(events_by_day.get(day, []))):
            # Multi-week ranges (e.g. /search) need the date to tell repeated weekdays apart
            label = day.strftime('%A %d.%m') if monday else day.strftime('%a %d.%m')
            if monday and day == today:
                label += " · today"
            fields.append((f"📅 {label}" + (" (cont.)" if ci else ""), chunk))
    return _paginate(fields, title, description, color)


# ---------------------------------------------------------------------------
# Paginated view
# ---------------------------------------------------------------------------

class PaginatedEmbedView(discord.ui.View):
    """Embed pagination with ◀ / ▶ navigation and an optional 📋 Details button."""

    def __init__(
        self,
        pages: list[discord.Embed],
        events_per_page: list[list[dict]] | None = None,
        *,
        timeout: float | None = 24 * 3600,  # shortcut: buttons die on a bot restart, use persistent views if that matters
    ):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.events_per_page = events_per_page or [[] for _ in pages]
        self.current = 0
        self.message: discord.Message | None = None

        # Remove nav buttons when everything fits on one page
        if len(pages) <= 1:
            self.remove_item(self.prev_btn)
            self.remove_item(self.next_btn)

        # Remove details button when we have no event data
        if not any(self.events_per_page):
            self.remove_item(self.detail_btn)

        self._stamp_footer()
        self._sync_buttons()

    # -- helpers --

    def _stamp_footer(self):
        if len(self.pages) <= 1:
            return
        total = sum(len(ep) for ep in self.events_per_page)
        text = f"Page {self.current + 1}/{len(self.pages)}"
        if total:
            text += f" · {total} events"
        self.pages[self.current].set_footer(text=text)

    def _sync_buttons(self):
        if len(self.pages) <= 1:
            return
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1

    # -- buttons --

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current > 0:
            self.current -= 1
            self._stamp_footer()
            self._sync_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current], view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current < len(self.pages) - 1:
            self.current += 1
            self._stamp_footer()
            self._sync_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current], view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="📋 Details", style=discord.ButtonStyle.primary)
    async def detail_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        events = (
            self.events_per_page[self.current]
            if self.current < len(self.events_per_page)
            else []
        )
        if not events:
            await interaction.response.send_message(
                "No details for this page.", ephemeral=True
            )
            return
        embed = _build_detail_embed(events, self.pages[self.current].color)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Detail embed builder (ephemeral, shown on 📋 click)
# ---------------------------------------------------------------------------

def _build_detail_embed(events: list[dict], color) -> discord.Embed:
    """Ephemeral embed with full description, location, and video links."""
    embed = discord.Embed(title="📋 Details", color=color or 0x95A5A6)

    for event in events[:10]:
        title = event.get("original_summary") or event.get("summary") or "Untitled"
        desc = (event.get("description") or "").strip()
        location = event.get("location") or ""

        parts = [f"🕐 {event_when(event, with_date=True)}"]
        if location:
            parts.append(f"📍 {location}")
        parts += [f"🔗 [{label}]({url})" for label, url in extract_video_links(desc)]
        if desc:
            parts.append(shorten(desc, 300))

        embed.add_field(name=shorten(title, 256), value="\n".join(parts)[:1024], inline=False)

    if len(events) > 10:
        embed.set_footer(text=f"Showing 10 of {len(events)} events")

    return embed


# ---------------------------------------------------------------------------
# Change-notification formatting helpers
# ---------------------------------------------------------------------------

def format_change_lines(
    added: list[dict],
    removed: list[dict],
    changed: list[tuple[dict, dict]],
    *,
    cap: int = 15,
) -> tuple[str, int]:
    """Build a description string for a change-notification embed.

    Returns ``(text, color_hint)`` where *color_hint* is
    ``0x2ecc71`` (green / adds only), ``0xe74c3c`` (red / removals only),
    or ``0xf1c40f`` (yellow / mixed).
    """
    sections = [
        ("Added", [f"➕ {format_event(ev, with_date=True)}" for ev in added]),
        ("Changed", [_format_change_diff(old, new) for old, new in changed]),
        ("Removed", [f"➖ ~~{format_event(ev, with_date=True)}~~" for ev in removed]),
    ]
    lines: list[str] = []
    shown = 0
    for heading, items in sections:
        items = items[:max(0, cap - shown)]
        if not items:
            continue
        if lines:
            lines.append("")
        lines.append(f"**{heading}**")
        lines += items
        shown += len(items)

    total = len(added) + len(removed) + len(changed)
    if shown < total:
        lines.append(f"\n*… and {total - shown} more*")

    if added and not removed and not changed:
        color = 0x2ECC71  # green
    elif removed and not added and not changed:
        color = 0xE74C3C  # red
    else:
        color = 0xF1C40F  # yellow

    return "\n".join(lines), color


def _format_change_diff(old: dict, new: dict) -> str:
    """'✏️ **New title** `Sun 08.11 15:00` · was `Sun 08.11 13:30`, title was *Old*'."""
    diffs: list[str] = []
    old_when, new_when = event_when(old, with_date=True), event_when(new, with_date=True)
    if old_when != new_when:
        diffs.append(f"was `{old_when}`")
    # Compare original titles: the simplified ones can differ between runs
    if (old.get("original_summary") or old.get("summary")) != (new.get("original_summary") or new.get("summary")):
        diffs.append(f"title was *{escape_md(shorten(old.get('summary') or '', 40))}*")
    old_loc, new_loc = old.get("location") or "", new.get("location") or ""
    if old_loc != new_loc:
        diffs.append(f"location was *{escape_md(shorten(old_loc, 30))}*" if old_loc else "location added")
    return f"✏️ {format_event(new, with_date=True)} · {', '.join(diffs) or 'details updated'}"
