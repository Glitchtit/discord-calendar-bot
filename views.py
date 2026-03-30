"""Interactive Discord UI components for the calendar bot."""

import re
from datetime import timedelta

import discord  # type: ignore

from log import logger
from utils import format_event, parse_date_string, get_local_timezone

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

_MAX_FIELD_LEN = 900  # Discord field limit is 1024; leave buffer
_MAX_FIELDS = 20      # Discord embed limit is 25; leave room for header


def build_event_pages(
    events_by_source: dict[str, list[dict]],
    *,
    title: str,
    description: str = "",
    color: int = 0x95A5A6,
) -> tuple[list[discord.Embed], list[list[dict]]]:
    """Build paginated embeds from events grouped by calendar source.

    Returns ``(pages, events_per_page)`` where *pages[i]* is a
    :class:`discord.Embed` and *events_per_page[i]* is the flat list
    of event dicts visible on that page.
    """
    pages: list[discord.Embed] = []
    epp: list[list[dict]] = []

    embed = discord.Embed(title=title, description=description, color=color)
    cur_events: list[dict] = []
    field_n = 0

    for source_name, events in sorted(events_by_source.items()):
        if not events:
            continue
        sorted_evts = sorted(
            events,
            key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")),
        )

        # Split into chunks that fit one embed field each
        chunks: list[list[dict]] = []
        chunk: list[dict] = []
        chunk_len = 0
        for ev in sorted_evts:
            line = f" {format_event(ev)}\n"
            if chunk and chunk_len + len(line) > _MAX_FIELD_LEN:
                chunks.append(chunk)
                chunk = [ev]
                chunk_len = len(line)
            else:
                chunk.append(ev)
                chunk_len += len(line)
        if chunk:
            chunks.append(chunk)

        for ci, ch in enumerate(chunks):
            if field_n >= _MAX_FIELDS:
                pages.append(embed)
                epp.append(cur_events)
                embed = discord.Embed(title=f"{title} (cont.)", color=color)
                cur_events = []
                field_n = 0

            name = f"📖 {source_name}" if ci == 0 else f"📖 {source_name} (cont.)"
            value = "\n".join(f" {format_event(e)}" for e in ch) + "\n\u200b"
            embed.add_field(name=name, value=value, inline=False)
            cur_events.extend(ch)
            field_n += 1

    # Always append at least one page
    pages.append(embed)
    epp.append(cur_events)
    return pages, epp


def build_week_pages(
    events_by_day: dict,
    *,
    title: str,
    description: str = "",
    color: int = 0x95A5A6,
    monday=None,
) -> tuple[list[discord.Embed], list[list[dict]]]:
    """Build paginated embeds for a weekly view (one field per day)."""
    pages: list[discord.Embed] = []
    epp: list[list[dict]] = []

    embed = discord.Embed(title=title, description=description, color=color)
    cur_events: list[dict] = []
    field_n = 0

    days = [monday + timedelta(days=i) for i in range(7)] if monday else sorted(events_by_day.keys())

    for day in days:
        day_events = events_by_day.get(day, [])
        if not day_events:
            continue
        sorted_evts = sorted(
            day_events,
            key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")),
        )

        if field_n >= _MAX_FIELDS:
            pages.append(embed)
            epp.append(cur_events)
            embed = discord.Embed(title=f"{title} (cont.)", color=color)
            cur_events = []
            field_n = 0

        formatted = "\n".join(f" {format_event(e)}" for e in sorted_evts)
        # Safety truncation for extremely dense days
        if len(formatted) > _MAX_FIELD_LEN:
            lines = formatted.split("\n")
            kept: list[str] = []
            length = 0
            for ln in lines:
                if length + len(ln) + 1 > _MAX_FIELD_LEN - 40:
                    kept.append("*… more events on next page*")
                    break
                kept.append(ln)
                length += len(ln) + 1
            formatted = "\n".join(kept)

        embed.add_field(
            name=f"📅 {day.strftime('%A')}",
            value=formatted + "\n\u200b",
            inline=False,
        )
        cur_events.extend(sorted_evts)
        field_n += 1

    pages.append(embed)
    epp.append(cur_events)
    return pages, epp


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
        timeout: float = 180,
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
                "No event details available.", ephemeral=True
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
    embed = discord.Embed(title="📋 Event Details", color=color or 0x95A5A6)

    for event in events[:10]:
        title = event.get("original_summary") or event.get("summary", "Untitled")
        desc = event.get("description", "") or ""
        location = event.get("location", "") or ""

        parts: list[str] = []

        # Time
        start_data = event.get("start", {})
        end_data = event.get("end", {})
        tz = get_local_timezone()
        start_str = start_data.get("dateTime", start_data.get("date", ""))
        end_str = end_data.get("dateTime", end_data.get("date", ""))
        start_dt = parse_date_string(start_str, tz) if start_str else None
        end_dt = parse_date_string(end_str, tz) if end_str else None
        if start_dt:
            time_text = start_dt.strftime("%A %B %d, %H:%M")
            if end_dt:
                time_text += f" – {end_dt.strftime('%H:%M')}"
            parts.append(f"🕐 {time_text}")

        if location:
            parts.append(f"📍 {location}")

        links = extract_video_links(desc)
        for label, url in links:
            parts.append(f"🔗 [{label}]({url})")

        if desc:
            clean = desc.strip()[:300]
            if len(desc.strip()) > 300:
                clean += "…"
            parts.append(clean)

        if not parts:
            parts.append("*No additional details*")

        embed.add_field(
            name=title[:256],
            value="\n".join(parts)[:1024],
            inline=False,
        )

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
    lines: list[str] = []
    total = len(added) + len(removed) + len(changed)
    shown = 0

    if added:
        lines.append("**📥 Added:**")
        for ev in added:
            if shown >= cap:
                break
            lines.append(f"➕ {format_event(ev)}")
            shown += 1

    if removed:
        if lines:
            lines.append("")
        lines.append("**📤 Removed:**")
        for ev in removed:
            if shown >= cap:
                break
            title = ev.get("summary", "Untitled")
            if len(title) > 47:
                title = title[:44] + "..."
            # Time info
            start_data = ev.get("start", {})
            start_raw = start_data.get("dateTime", start_data.get("date", ""))
            tz = get_local_timezone()
            dt = parse_date_string(start_raw, tz) if start_raw else None
            time_str = dt.strftime("%a %H:%M") if dt else ""
            lines.append(f"➖ ~~{title}~~ `{time_str}`")
            shown += 1

    if changed:
        if lines:
            lines.append("")
        lines.append("**✏️ Changed:**")
        for old_ev, new_ev in changed:
            if shown >= cap:
                break
            lines.append(_format_change_diff(old_ev, new_ev))
            shown += 1

    if shown < total:
        lines.append(f"\n*… and {total - shown} more*")

    # Colour hint
    if added and not removed and not changed:
        color = 0x2ECC71  # green
    elif removed and not added and not changed:
        color = 0xE74C3C  # red
    else:
        color = 0xF1C40F  # yellow

    return "\n".join(lines), color


def _format_change_diff(old: dict, new: dict) -> str:
    """Produce a single line highlighting what changed between two events."""
    new_title = new.get("summary", "Untitled")
    if len(new_title) > 47:
        new_title = new_title[:44] + "..."

    diffs: list[str] = []

    # Title change
    old_title = old.get("summary", "")
    if old_title != new.get("summary", ""):
        ot = old_title[:30] + "…" if len(old_title) > 30 else old_title
        diffs.append(f"title was *{ot}*")

    # Time change
    tz = get_local_timezone()
    old_start = parse_date_string(
        old.get("start", {}).get("dateTime", old.get("start", {}).get("date", "")), tz
    )
    new_start = parse_date_string(
        new.get("start", {}).get("dateTime", new.get("start", {}).get("date", "")), tz
    )
    if old_start and new_start and old_start != new_start:
        diffs.append(f"was {old_start.strftime('%a %H:%M')}")

    # Location change
    old_loc = old.get("location", "") or ""
    new_loc = new.get("location", "") or ""
    if old_loc != new_loc:
        diffs.append(f"location was *{old_loc[:30]}*" if old_loc else "location added")

    diff_str = f" ({'  · '.join(diffs)})" if diffs else ""
    time_str = ""
    if new_start:
        time_str = f" `{new_start.strftime('%a %H:%M')}`"

    return f"✏️ **{new_title}**{time_str}{diff_str}"
